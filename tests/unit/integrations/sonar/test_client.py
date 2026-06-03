"""Unit tests for the thin SonarQube adapter (AG3-052 §2.1.1).

Only the external HTTP boundary (``urllib.request.urlopen``) is stubbed
(MOCKS-Ausnahme); the adapter's request building + fail-closed handling
runs for real.
"""

from __future__ import annotations

import io
import json
import urllib.error
from typing import Any

import pytest

from agentkit.integrations.sonar import SonarApiError, SonarClient


class _FakeResponse:
    def __init__(self, body: str, status: int = 200) -> None:
        self._body = body.encode("utf-8")
        self.status = status

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


@pytest.fixture
def captured_urls(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    urls: list[str] = []

    def _fake_urlopen(request: Any, timeout: int = 0) -> _FakeResponse:  # noqa: ARG001
        urls.append(request.full_url)
        return _FakeResponse(json.dumps({"projectStatus": {"status": "OK"}}))

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)
    return urls


def test_project_status_uses_analysis_id(captured_urls: list[str]) -> None:
    client = SonarClient("http://sonar:9901", "tok")
    response = client.project_status(analysis_id="AX-1")
    assert response.status_code == 200
    assert "analysisId=AX-1" in captured_urls[0]
    assert "qualitygates/project_status" in captured_urls[0]


def test_project_status_requires_a_key() -> None:
    client = SonarClient("http://sonar:9901", "tok")
    with pytest.raises(SonarApiError, match="analysis_id or ce_task_id"):
        client.project_status()


def test_http_error_is_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(request: Any, timeout: int = 0) -> _FakeResponse:  # noqa: ARG001
        raise urllib.error.HTTPError(request.full_url, 503, "down", {}, io.BytesIO(b""))  # type: ignore[arg-type]

    monkeypatch.setattr("urllib.request.urlopen", _raise)
    client = SonarClient("http://sonar:9901", "tok")
    with pytest.raises(SonarApiError, match="HTTP 503"):
        client.system_status()


def test_unreachable_is_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(request: Any, timeout: int = 0) -> _FakeResponse:  # noqa: ARG001
        raise urllib.error.URLError("no route")

    monkeypatch.setattr("urllib.request.urlopen", _raise)
    client = SonarClient("http://sonar:9901", "tok")
    with pytest.raises(SonarApiError, match="unreachable"):
        client.installed_plugins()


def test_malformed_json_is_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    def _bad(request: Any, timeout: int = 0) -> _FakeResponse:  # noqa: ARG001
        return _FakeResponse("not json{{")

    monkeypatch.setattr("urllib.request.urlopen", _bad)
    client = SonarClient("http://sonar:9901", "tok")
    with pytest.raises(SonarApiError, match="malformed JSON"):
        client.system_status()


def test_transition_issue_posts(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def _fake(request: Any, timeout: int = 0) -> _FakeResponse:  # noqa: ARG001
        seen["method"] = request.method
        seen["url"] = request.full_url
        return _FakeResponse("{}")

    monkeypatch.setattr("urllib.request.urlopen", _fake)
    client = SonarClient("http://sonar:9901", "tok")
    client.transition_issue("ISSUE-1", "accept")
    assert seen["method"] == "POST"
    assert "issues/do_transition" in seen["url"]
