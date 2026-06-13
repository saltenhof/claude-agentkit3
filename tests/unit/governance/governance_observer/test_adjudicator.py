"""Tests for GovernanceAdjudicator — prompt builder and response parser.

Validates FK-35 §35.3.7 schema enforcement (fail-closed on invalid schema).
"""

from __future__ import annotations

import json

import pytest

from agentkit.governance.governance_observer.adjudicator import (
    GovernanceAdjudicationError,
    build_adjudication_prompt,
    parse_adjudication_response,
)
from agentkit.governance.governance_observer.models import (
    AdjudicationIncidentType,
    AdjudicationRecommendedAction,
    AdjudicationSeverity,
    GovernanceAdjudicationVerdict,
)


def _valid_verdict_dict() -> dict[str, object]:
    return {
        "incident_type": "role_violation",
        "severity": "high",
        "confidence": 0.9,
        "evidence_summary": "Orchestrator wrote code.",
        "recommended_action": "pause_story",
    }


def test_parse_adjudication_response_valid_json() -> None:
    """Valid JSON verdict parses to GovernanceAdjudicationVerdict."""
    raw = json.dumps(_valid_verdict_dict())
    verdict = parse_adjudication_response(raw)
    assert isinstance(verdict, GovernanceAdjudicationVerdict)
    assert verdict.incident_type == AdjudicationIncidentType.ROLE_VIOLATION
    assert verdict.severity == AdjudicationSeverity.HIGH
    assert verdict.confidence == pytest.approx(0.9)
    assert verdict.recommended_action == AdjudicationRecommendedAction.PAUSE_STORY


def test_parse_adjudication_response_strips_markdown_fence() -> None:
    """Markdown-fenced JSON is unwrapped and parsed correctly."""
    raw = "```json\n" + json.dumps(_valid_verdict_dict()) + "\n```"
    verdict = parse_adjudication_response(raw)
    assert verdict.severity == AdjudicationSeverity.HIGH


def test_parse_adjudication_response_invalid_json_raises() -> None:
    """Non-JSON response raises GovernanceAdjudicationError (fail-closed)."""
    with pytest.raises(GovernanceAdjudicationError, match="not valid JSON"):
        parse_adjudication_response("this is not json")


def test_parse_adjudication_response_schema_violation_raises() -> None:
    """Valid JSON with wrong schema raises GovernanceAdjudicationError (fail-closed)."""
    bad = {"unknown_field": "oops"}
    with pytest.raises(GovernanceAdjudicationError, match="schema validation"):
        parse_adjudication_response(json.dumps(bad))


def test_parse_adjudication_response_invalid_severity_raises() -> None:
    """Invalid enum value in severity field raises GovernanceAdjudicationError."""
    data = {**_valid_verdict_dict(), "severity": "ultra_high"}
    with pytest.raises(GovernanceAdjudicationError):
        parse_adjudication_response(json.dumps(data))


def test_parse_adjudication_response_confidence_out_of_range_raises() -> None:
    """Confidence > 1.0 raises GovernanceAdjudicationError."""
    data = {**_valid_verdict_dict(), "confidence": 1.5}
    with pytest.raises(GovernanceAdjudicationError):
        parse_adjudication_response(json.dumps(data))


def test_build_adjudication_prompt_includes_key_fields() -> None:
    """Prompt contains the incident candidate key fields."""
    from datetime import UTC, datetime

    from agentkit.governance.governance_observer.models import GovernanceIncidentCandidate

    candidate = GovernanceIncidentCandidate(
        project_key="PRJ",
        story_id="AG3-085",
        run_id="run-001",
        created_at=datetime.now(UTC),
        risk_score=40,
        event_count=5,
        dominant_signals=["orchestrator_code_read_write"],
        evidence_summary="Code write signals.",
        time_span_s=90.0,
    )
    prompt = build_adjudication_prompt(candidate, story_context_summary="Story X")
    assert "PRJ" in prompt
    assert "AG3-085" in prompt
    assert "run-001" in prompt
    assert "40" in prompt
    assert "Story X" in prompt
