"""Tests for FK-47 request DSL and deterministic request resolution."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError

from agentkit.backend.core_types.verify_evidence import (
    VerifyEvidenceFile,
    VerifyEvidenceObservation,
    VerifyEvidenceObservationStatus,
)
from agentkit.backend.verify_system.evidence import (
    MAX_REQUESTS,
    RequestResolver,
    RequestResult,
    RequestType,
    ReviewerRequest,
    parse_preflight_response,
)

if TYPE_CHECKING:
    from pathlib import Path


def _resolver(tmp_path: Path) -> RequestResolver:
    concept = tmp_path / "concept"
    concept.mkdir()
    (concept / "source.md").write_text("# Runtime Binding\nDetails\n", encoding="utf-8")
    return RequestResolver(story_dir=tmp_path / "story")


def _observation(index: int, path: str = "src/context.py") -> VerifyEvidenceObservation:
    return VerifyEvidenceObservation(
        request_index=index,
        status=VerifyEvidenceObservationStatus.COLLECTED,
        candidates=(
            VerifyEvidenceFile.from_content(
                repo_id="app", path=path, content=f"content for {path}"
            ),
        ),
        content="test evidence collected",
    )


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


def test_request_resolver_keeps_only_backend_local_concept_handler() -> None:
    handlers = [
        name
        for name in dir(RequestResolver)
        if name.startswith("_resolve_") and name not in {"_resolve_single"}
    ]
    assert handlers == ["_resolve_concept_source"]


def test_all_seven_handlers_resolve_real_requests(tmp_path: Path) -> None:
    resolver = _resolver(tmp_path)
    requests = [
        ReviewerRequest(type=RequestType.NEED_FILE, target="src/schema.py", reason="needed"),
        ReviewerRequest(type=RequestType.NEED_SCHEMA, target="UserSchema", reason="needed"),
        ReviewerRequest(type=RequestType.NEED_CALLSITE, target="target_func", reason="needed"),
        ReviewerRequest(type=RequestType.NEED_RUNTIME_BINDING, target="service_url", reason="needed"),
        ReviewerRequest(
            type=RequestType.NEED_TEST_EVIDENCE,
            target="pytest -q",
            reason="needed",
        ),
        ReviewerRequest(type=RequestType.NEED_CONCEPT_SOURCE, target="Runtime Binding", reason="needed"),
        ReviewerRequest(type=RequestType.NEED_DIFF_EXPANSION, target="src/changed.py", region="changed", reason="needed"),
    ]

    observations = [_observation(index) for index in range(5)] + [_observation(6)]
    results = resolver.resolve_all(requests, observations)

    assert [result.request.type for result in results] == [request.type for request in requests]
    assert all(result.status == "RESOLVED" for result in results)


def test_need_concept_source_uses_repo_root_for_real_stories_layout(tmp_path: Path) -> None:
    story_dir = tmp_path / "stories" / "AG3-062"
    story_dir.mkdir(parents=True)
    concept_dir = tmp_path / "concept" / "technical-design"
    concept_dir.mkdir(parents=True)
    (concept_dir / "fk-47.md").write_text("# Review Request Dialog\n", encoding="utf-8")
    other_story_dir = tmp_path / "stories" / "AG3-061"
    other_story_dir.mkdir()
    (other_story_dir / "story.md").write_text("# Evidence Assembler Foundation\n", encoding="utf-8")
    resolver = RequestResolver(story_dir=story_dir)

    results = resolver.resolve_all([
        ReviewerRequest(
            type=RequestType.NEED_CONCEPT_SOURCE,
            target="Review Request Dialog",
            reason="needed",
        ),
        ReviewerRequest(
            type=RequestType.NEED_CONCEPT_SOURCE,
            target="Evidence Assembler Foundation",
            reason="needed",
        ),
    ])

    assert [result.status for result in results] == ["RESOLVED", "RESOLVED"]
    assert results[0].file_path is not None
    assert results[0].file_path.endswith("concept/technical-design/fk-47.md")
    assert results[1].file_path is not None
    assert results[1].file_path.endswith("stories/AG3-061/story.md")


def test_d3_rule_returns_unresolved_for_zero_and_multiple_matches(tmp_path: Path) -> None:
    resolver = RequestResolver(story_dir=tmp_path / "story")

    ambiguous = resolver.resolve_all([
        ReviewerRequest(type=RequestType.NEED_SCHEMA, target="UserSchema", reason="needed")
    ], [
        VerifyEvidenceObservation(
            request_index=0,
            status=VerifyEvidenceObservationStatus.COLLECTED,
            candidates=(
                VerifyEvidenceFile.from_content(repo_id="app", path="a.py", content="a"),
                VerifyEvidenceFile.from_content(repo_id="app", path="b.py", content="b"),
            ),
        )
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


def test_need_test_evidence_timeout_does_not_block_other_requests(tmp_path: Path) -> None:
    resolver = _resolver(tmp_path)
    results = resolver.resolve_all([
        ReviewerRequest(type=RequestType.NEED_TEST_EVIDENCE, target="timeout-command", reason="needed"),
        ReviewerRequest(type=RequestType.NEED_FILE, target="src/schema.py", reason="needed"),
    ], [
        VerifyEvidenceObservation(
            request_index=0,
            status=VerifyEvidenceObservationStatus.TIMEOUT,
            finding_code="TEST_EVIDENCE_TIMEOUT",
        ),
        _observation(1, "src/schema.py"),
    ])

    assert [result.status for result in results] == ["TIMEOUT", "RESOLVED"]
