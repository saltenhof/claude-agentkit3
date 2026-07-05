"""ProjectEdgeClient wiring for the Edge-Command-Queue endpoints (AG3-145 B).

Covers the GET fetch (query params + ack read, no publish), the POST result
(own op_id, no publish), and the transport's structured-rejection parsing of
the 403/404/409 EdgeCommandMutationResult bodies.
"""

from __future__ import annotations

import json
from email.message import Message
from io import BytesIO
from typing import TYPE_CHECKING, Any
from urllib.error import HTTPError

import pytest

from agentkit.backend.control_plane.models import (
    EdgeCommandMutationResult,
    EdgeCommandResultRequest,
    OpenEdgeCommandsResponse,
    WorktreeReport,
)
from agentkit.harness_client.projectedge import (
    HttpsJsonTransport,
    LocalEdgePublisher,
    ProjectEdgeClient,
)

if TYPE_CHECKING:
    from pathlib import Path


class _RecordingTransport:
    def __init__(self, response: dict[str, object]) -> None:
        self.calls: list[tuple[str, str, object]] = []
        self._response = response

    def send(
        self, *, method: str, path: str, payload: object = None, headers: object = None,
    ) -> dict[str, object]:
        del headers
        self.calls.append((method, path, payload))
        return dict(self._response)


class _FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body
        self.headers: dict[str, str] = {}

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body


def _client(transport: object, tmp_path: Path) -> ProjectEdgeClient:
    return ProjectEdgeClient(
        transport=transport,  # type: ignore[arg-type]
        publisher=LocalEdgePublisher(project_root=tmp_path),
    )


def _result_request() -> EdgeCommandResultRequest:
    return EdgeCommandResultRequest(
        project_key="tenant-a",
        story_id="AG3-100",
        session_id="sess-A",
        op_id="op-1",
        result=WorktreeReport(repo_id="api", outcome="provisioned", worktree_root="/wt"),
    )


def test_fetch_open_commands_uses_query_params_and_returns_typed_response(
    tmp_path: Path,
) -> None:
    response = OpenEdgeCommandsResponse(commands=[]).model_dump(mode="json")
    transport = _RecordingTransport(response)
    client = _client(transport, tmp_path)

    result = client.fetch_open_commands(
        run_id="run-1", project_key="tenant-a", session_id="sess-A"
    )

    assert isinstance(result, OpenEdgeCommandsResponse)
    method, path, payload = transport.calls[0]
    assert method == "GET"
    assert path.startswith("/v1/project-edge/story-runs/run-1/commands?")
    assert "project_key=tenant-a" in path
    assert "session_id=sess-A" in path
    assert payload is None  # a GET carries no body


def test_report_command_result_posts_the_typed_request(tmp_path: Path) -> None:
    response = EdgeCommandMutationResult(
        status="completed", command_id="cmd-1", op_id="op-1"
    ).model_dump(mode="json")
    transport = _RecordingTransport(response)
    client = _client(transport, tmp_path)

    result = client.report_command_result(
        command_id="cmd-1", request=_result_request()
    )

    assert isinstance(result, EdgeCommandMutationResult)
    assert result.status == "completed"
    method, path, payload = transport.calls[0]
    assert method == "POST"
    assert path == "/v1/project-edge/commands/cmd-1/result"
    assert isinstance(payload, dict)
    assert payload["op_id"] == "op-1"


def test_report_command_result_url_encodes_the_command_id(tmp_path: Path) -> None:
    response = EdgeCommandMutationResult(
        status="completed", command_id="cmd/evil", op_id="op-1"
    ).model_dump(mode="json")
    transport = _RecordingTransport(response)
    client = _client(transport, tmp_path)

    client.report_command_result(command_id="cmd/evil", request=_result_request())

    _, path, _ = transport.calls[0]
    assert path == "/v1/project-edge/commands/cmd%2Fevil/result"


@pytest.mark.parametrize("http_code", [403, 404, 409])
def test_transport_returns_structured_command_rejection_on_4xx(
    monkeypatch: pytest.MonkeyPatch, http_code: int
) -> None:
    """The 403/404/409 EdgeCommandMutationResult rejection body is RETURNED, not raised."""
    rejected = EdgeCommandMutationResult(
        status="rejected",
        command_id="cmd-1",
        op_id="op-1",
        error_code="ownership_transferred",
    ).model_dump(mode="json")

    def fake_urlopen(request: Any, context: Any = None) -> _FakeResponse:
        del request, context
        raise HTTPError(
            url="https://127.0.0.1:9080/v1/project-edge/commands/cmd-1/result",
            code=http_code,
            msg="rejected",
            hdrs=Message(),
            fp=BytesIO(json.dumps(rejected).encode("utf-8")),
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    transport = HttpsJsonTransport(base_url="https://127.0.0.1:9080")

    body = transport.send(
        method="POST",
        path="/v1/project-edge/commands/cmd-1/result",
        payload={"op_id": "op-1"},
    )

    assert body["status"] == "rejected"
    assert body["error_code"] == "ownership_transferred"


def test_client_report_surfaces_ownership_transferred_rejection_over_real_transport(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    rejected = EdgeCommandMutationResult(
        status="rejected",
        command_id="cmd-1",
        op_id="op-1",
        error_code="ownership_transferred",
    ).model_dump(mode="json")

    def fake_urlopen(request: Any, context: Any = None) -> _FakeResponse:
        del request, context
        raise HTTPError(
            url="https://127.0.0.1:9080/v1/project-edge/commands/cmd-1/result",
            code=403,
            msg="Forbidden",
            hdrs=Message(),
            fp=BytesIO(json.dumps(rejected).encode("utf-8")),
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    client = _client(HttpsJsonTransport(base_url="https://127.0.0.1:9080"), tmp_path)

    result = client.report_command_result(command_id="cmd-1", request=_result_request())

    assert result.status == "rejected"
    assert result.error_code == "ownership_transferred"
