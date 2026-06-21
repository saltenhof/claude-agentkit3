"""Unit tests for the ARE REST client."""

from __future__ import annotations

import inspect
import json
from typing import Any

import pytest

from agentkit.backend.requirements_coverage.are_client import AreClient, AreHttpResponse
from agentkit.backend.requirements_coverage.contract import (
    AreDockpointStatus,
    AreRequirementType,
    EvidenceType,
)
from agentkit.backend.requirements_coverage.errors import (
    AreClientDecodeError,
    AreClientHttpError,
)


def _requirement(requirement_id: str = "REQ-1") -> dict[str, object]:
    return {
        "requirement_id": requirement_id,
        "requirement_type": AreRequirementType.SYSTEM.value,
        "summary": "Requirement",
        "description": None,
        "must_cover": True,
        "acceptance_criteria": [],
        "recurring": False,
    }


class RecordingTransport:
    def __init__(self, payload: object, *, status_code: int = 200) -> None:
        self.payload = payload
        self.status_code = status_code
        self.requests: list[dict[str, Any]] = []

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        body: bytes | None = None,
    ) -> AreHttpResponse:
        self.requests.append(
            {"method": method, "url": url, "headers": headers, "body": body}
        )
        raw = self.payload if isinstance(self.payload, bytes) else json.dumps(self.payload).encode()
        return AreHttpResponse(status_code=self.status_code, body=raw)


def test_list_requirements_http_body() -> None:
    transport = RecordingTransport({"requirements": [_requirement()]})
    client = AreClient("https://are.example.com", "token", transport=transport)

    result = client.list_requirements("AG3-077", "backend")

    assert result[0].requirement_id == "REQ-1"
    request = transport.requests[0]
    assert request["method"] == "GET"
    assert request["url"] == "https://are.example.com/requirements?story_id=AG3-077&scope=backend"
    assert request["headers"]["Authorization"] == "Bearer token"


def test_get_recurring_http_body() -> None:
    transport = RecordingTransport({"requirements": [_requirement("REQ-R")]})
    client = AreClient("https://are.example.com", transport=transport)

    result = client.get_recurring("backend", "implementation")

    assert result[0].requirement_id == "REQ-R"
    assert transport.requests[0]["url"].endswith(
        "/requirements/recurring?scope=backend&story_type=implementation"
    )


def test_load_context_http_body() -> None:
    transport = RecordingTransport({"requirements": [_requirement()], "loaded_at": "2026-06-09T00:00:00+00:00"})
    client = AreClient("https://are.example.com", transport=transport)

    context = client.load_context("AG3-077")

    assert len(context.requirements) == 1
    assert transport.requests[0]["url"] == "https://are.example.com/stories/AG3-077/context"


def test_submit_evidence_http_body() -> None:
    transport = RecordingTransport({"status": AreDockpointStatus.PASS.value})
    client = AreClient("https://are.example.com", transport=transport)

    result = client.submit_evidence(
        "AG3-077",
        "REQ-1",
        EvidenceType.TEST_REPORT,
        "tests/test_x.py::test_y",
    )

    assert result.status is AreDockpointStatus.PASS
    request = transport.requests[0]
    assert request["method"] == "POST"
    assert json.loads(request["body"].decode()) == {
        "evidence_ref": "tests/test_x.py::test_y",
        "evidence_type": "test_report",
        "requirement_id": "REQ-1",
    }


def test_check_gate_http_body() -> None:
    transport = RecordingTransport({"status": "PASS", "verdict": "PASS"})
    client = AreClient("https://are.example.com", transport=transport)

    verdict = client.check_gate("AG3-077")

    assert verdict.status is AreDockpointStatus.PASS
    assert transport.requests[0]["url"] == "https://are.example.com/stories/AG3-077/gate"


def test_http_error_is_typed() -> None:
    transport = RecordingTransport({"error": "down"}, status_code=503)
    client = AreClient("https://are.example.com", transport=transport)

    with pytest.raises(AreClientHttpError):
        client.check_gate("AG3-077")


def test_decode_error_is_typed() -> None:
    transport = RecordingTransport(b"{not-json")
    client = AreClient("https://are.example.com", transport=transport)

    with pytest.raises(AreClientDecodeError):
        client.check_gate("AG3-077")


class TestAreClientSignatures:
    """Signatures remain aligned with FK-40 §40.4.1."""

    def test_public_method_signatures(self) -> None:
        assert list(inspect.signature(AreClient.list_requirements).parameters) == [
            "self",
            "story_id",
            "scope",
        ]
        assert list(inspect.signature(AreClient.get_recurring).parameters) == [
            "self",
            "scope",
            "story_type",
        ]
        assert list(inspect.signature(AreClient.load_context).parameters) == ["self", "story_id"]
        assert list(inspect.signature(AreClient.check_gate).parameters) == ["self", "story_id"]

    def test_init_signature(self) -> None:
        sig = inspect.signature(AreClient.__init__)
        assert list(sig.parameters) == ["self", "base_url", "auth_token", "transport"]
        assert sig.parameters["auth_token"].default is None
        assert sig.parameters["transport"].kind is inspect.Parameter.KEYWORD_ONLY
