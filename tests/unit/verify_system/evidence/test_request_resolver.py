"""Tests for FK-47 request DSL and deterministic request resolution."""

from __future__ import annotations

import json
import subprocess
import sys
from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError

from agentkit.verify_system.evidence import (
    MAX_REQUESTS,
    RequestResolver,
    RequestResult,
    RequestType,
    ReviewerRequest,
    parse_preflight_response,
)
from agentkit.verify_system.evidence import request_resolver as resolver_module
from agentkit.verify_system.evidence.repo_context import RepoContext

if TYPE_CHECKING:
    from pathlib import Path


def _repo(tmp_path: Path) -> RepoContext:
    repo_path = tmp_path / "app"
    (repo_path / "src").mkdir(parents=True)
    (repo_path / "tests").mkdir()
    (repo_path / "config").mkdir()
    (repo_path / "src" / "schema.py").write_text("class UserSchema:\n    pass\n", encoding="utf-8")
    (repo_path / "src" / "caller.py").write_text("def run():\n    target_func()\n", encoding="utf-8")
    (repo_path / "config" / "settings.yaml").write_text("service_url: http://example.invalid\n", encoding="utf-8")
    (repo_path / "src" / "changed.py").write_text("def changed():\n    return 1\n", encoding="utf-8")
    return RepoContext(repo_id="app", repo_path=repo_path, affected=True)


def _resolver(tmp_path: Path) -> RequestResolver:
    repo = _repo(tmp_path)
    concept = tmp_path / "concept"
    concept.mkdir()
    (concept / "source.md").write_text("# Runtime Binding\nDetails\n", encoding="utf-8")
    return RequestResolver({"app": repo}, "app", story_dir=tmp_path / "story")


def test_request_type_values_are_exact() -> None:
    assert [request_type.value for request_type in RequestType] == [
        "NEED_FILE",
        "NEED_SCHEMA",
        "NEED_CALLSITE",
        "NEED_RUNTIME_BINDING",
        "NEED_TEST_EVIDENCE",
        "NEED_CONCEPT_SOURCE",
        "NEED_DIFF_EXPANSION",
    ]


def test_reviewer_request_and_result_are_frozen_and_forbid_extra() -> None:
    request = ReviewerRequest(type=RequestType.NEED_FILE, target="src/schema.py", reason="needed")
    result = RequestResult(request=request, status="RESOLVED")

    with pytest.raises(ValidationError):
        ReviewerRequest(type=RequestType.NEED_FILE, target="src/schema.py", reason="needed", extra=True)  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        request.target = "other.py"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        result.status = "UNRESOLVED"  # type: ignore[misc]


def test_parse_preflight_response_caps_to_max_requests_and_warns(caplog: pytest.LogCaptureFixture) -> None:
    raw = {
        "requests": [
            {"type": "NEED_FILE", "target": f"file-{index}.py", "reason": "needed"}
            for index in range(MAX_REQUESTS + 2)
        ]
    }

    requests = parse_preflight_response(json.dumps(raw))

    assert len(requests) == MAX_REQUESTS
    assert requests[-1].target == "file-7.py"
    assert "processing first 8" in caplog.text


def test_parse_preflight_response_invalid_schema_returns_empty_list_and_warns(
    caplog: pytest.LogCaptureFixture,
) -> None:
    assert parse_preflight_response('{"not_requests": []}') == []
    assert "could not be parsed" in caplog.text


def test_request_resolver_has_exactly_seven_handler_methods() -> None:
    handlers = [
        name
        for name in dir(RequestResolver)
        if name.startswith("_resolve_") and name not in {"_resolve_single"}
    ]
    assert sorted(handlers) == [
        "_resolve_callsite",
        "_resolve_concept_source",
        "_resolve_diff_expansion",
        "_resolve_file",
        "_resolve_runtime_binding",
        "_resolve_schema",
        "_resolve_test_evidence",
    ]


def test_all_seven_handlers_resolve_real_requests(tmp_path: Path) -> None:
    resolver = _resolver(tmp_path)
    requests = [
        ReviewerRequest(type=RequestType.NEED_FILE, target="src/schema.py", reason="needed"),
        ReviewerRequest(type=RequestType.NEED_SCHEMA, target="UserSchema", reason="needed"),
        ReviewerRequest(type=RequestType.NEED_CALLSITE, target="target_func", reason="needed"),
        ReviewerRequest(type=RequestType.NEED_RUNTIME_BINDING, target="service_url", reason="needed"),
        ReviewerRequest(
            type=RequestType.NEED_TEST_EVIDENCE,
            target=f'"{sys.executable}" -c "print(123)"',
            reason="needed",
        ),
        ReviewerRequest(type=RequestType.NEED_CONCEPT_SOURCE, target="Runtime Binding", reason="needed"),
        ReviewerRequest(type=RequestType.NEED_DIFF_EXPANSION, target="src/changed.py", region="changed", reason="needed"),
    ]

    results = resolver.resolve_all(requests)

    assert [result.request.type for result in results] == [request.type for request in requests]
    assert all(result.status == "RESOLVED" for result in results)


def test_d3_rule_returns_unresolved_for_zero_and_multiple_matches(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo.repo_path / "src" / "other_schema.py").write_text("class UserSchema:\n    pass\n", encoding="utf-8")
    resolver = RequestResolver({"app": repo}, "app", story_dir=tmp_path / "story")

    ambiguous = resolver.resolve_all([
        ReviewerRequest(type=RequestType.NEED_SCHEMA, target="UserSchema", reason="needed")
    ])[0]
    missing = resolver.resolve_all([
        ReviewerRequest(type=RequestType.NEED_FILE, target="missing.py", reason="needed")
    ])[0]

    assert ambiguous.status == "UNRESOLVED"
    assert "Ambiguous candidates" in (ambiguous.content or "")
    assert missing.status == "UNRESOLVED"


def test_resolve_all_caps_to_first_eight_and_warns(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    resolver = _resolver(tmp_path)
    requests = [
        ReviewerRequest(type=RequestType.NEED_FILE, target=f"missing-{index}.py", reason="needed")
        for index in range(MAX_REQUESTS + 1)
    ]

    results = resolver.resolve_all(requests)

    assert len(results) == MAX_REQUESTS
    assert all(f"missing-{index}.py" in results[index].request.target for index in range(MAX_REQUESTS))
    assert "processing first 8" in caplog.text


def test_need_test_evidence_timeout_does_not_block_other_requests(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolver = _resolver(tmp_path)
    real_run = subprocess.run

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        command = args[0] if args else kwargs.get("args")
        if command == "timeout-command":
            raise subprocess.TimeoutExpired(cmd="timeout-command", timeout=30)
        return real_run(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(resolver_module.subprocess, "run", fake_run)

    results = resolver.resolve_all([
        ReviewerRequest(type=RequestType.NEED_TEST_EVIDENCE, target="timeout-command", reason="needed"),
        ReviewerRequest(type=RequestType.NEED_FILE, target="src/schema.py", reason="needed"),
    ])

    assert [result.status for result in results] == ["TIMEOUT", "RESOLVED"]
