"""Unit tests for the thin Jenkins adapter (AG3-056 §2.1.1).

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

from agentkit.integration_clients.jenkins import JenkinsApiError, JenkinsClient


class _FakeResponse:
    def __init__(
        self,
        body: str,
        status: int = 200,
        headers: dict[str, str] | None = None,
    ) -> None:
        self._body = body.encode("utf-8")
        self.status = status
        self.headers = headers or {}

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


def test_trigger_build_returns_location_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[str] = []

    def _fake_urlopen(request: Any, timeout: int = 0) -> _FakeResponse:  # noqa: ARG001
        captured.append(request.full_url)
        return _FakeResponse(
            "", status=201, headers={"Location": "http://jenkins/queue/item/5/"}
        )

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)
    client = JenkinsClient("http://jenkins:8080", "tok", user="ak3")
    response = client.trigger_build(
        "ak3-pre-merge", parameters={"branch": "b", "commit_sha": "c"}
    )
    assert response.status_code == 201
    assert response.headers["location"] == "http://jenkins/queue/item/5/"
    assert "buildWithParameters" in captured[0]


def test_trigger_build_non_201_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _fake_urlopen(request: Any, timeout: int = 0) -> _FakeResponse:  # noqa: ARG001
        return _FakeResponse("", status=200)

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)
    client = JenkinsClient("http://jenkins:8080", "tok")
    with pytest.raises(JenkinsApiError, match="expected 201"):
        client.trigger_build("ak3-pre-merge", parameters={})


def test_build_status_parses_json(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_urlopen(request: Any, timeout: int = 0) -> _FakeResponse:  # noqa: ARG001
        return _FakeResponse(json.dumps({"building": False, "result": "SUCCESS"}))

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)
    client = JenkinsClient("http://jenkins:8080", "tok")
    response = client.build_status("ak3-pre-merge", 11)
    assert response.json_body["result"] == "SUCCESS"


def test_build_artifact_returns_text(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_urlopen(request: Any, timeout: int = 0) -> _FakeResponse:  # noqa: ARG001
        return _FakeResponse("ceTaskId=CE-1\n")

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)
    client = JenkinsClient("http://jenkins:8080", "tok")
    response = client.build_artifact("ak3-pre-merge", 11, ".scannerwork/report-task.txt")
    assert "ceTaskId=CE-1" in response.text_body


def test_http_error_is_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(request: Any, timeout: int = 0) -> _FakeResponse:  # noqa: ARG001
        raise urllib.error.HTTPError(
            request.full_url, 404, "missing", {}, io.BytesIO(b"")  # type: ignore[arg-type]
        )

    monkeypatch.setattr("urllib.request.urlopen", _raise)
    client = JenkinsClient("http://jenkins:8080", "tok")
    with pytest.raises(JenkinsApiError, match="HTTP 404"):
        client.job_exists("ak3-pre-merge")


def test_unreachable_is_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(request: Any, timeout: int = 0) -> _FakeResponse:  # noqa: ARG001
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr("urllib.request.urlopen", _raise)
    client = JenkinsClient("http://jenkins:8080", "tok")
    with pytest.raises(JenkinsApiError, match="unreachable"):
        client.whoami()


def test_malformed_json_is_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_urlopen(request: Any, timeout: int = 0) -> _FakeResponse:  # noqa: ARG001
        return _FakeResponse("{not json")

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)
    client = JenkinsClient("http://jenkins:8080", "tok")
    with pytest.raises(JenkinsApiError, match="malformed JSON"):
        client.whoami()
