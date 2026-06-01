"""Unit-Tests fuer IncidentCandidate/Incident Pydantic-Modelle (AG3-028 §2.1.3)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from agentkit.core_types import FailureCategory, IncidentStatus
from agentkit.failure_corpus import Incident, IncidentCandidate, IncidentSeverity
from agentkit.failure_corpus.types import IncidentId

_NOW = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)


def _candidate() -> IncidentCandidate:
    return IncidentCandidate(
        category=FailureCategory.SCOPE_DRIFT,
        severity=IncidentSeverity.HIGH,
        source_bc="governance-and-guards",
        story_id="AG3-001",
        run_id="run-1",
        summary="scope exceeded",
        evidence={"k": "v"},
        observed_at=_NOW,
    )


class TestIncidentCandidate:
    def test_constructable(self) -> None:
        cand = _candidate()
        assert cand.category is FailureCategory.SCOPE_DRIFT
        assert cand.severity is IncidentSeverity.HIGH
        assert cand.run_id == "run-1"

    def test_run_id_optional(self) -> None:
        cand = IncidentCandidate(
            category=FailureCategory.HALLUCINATION,
            severity=IncidentSeverity.MEDIUM,
            source_bc="verify-system",
            story_id="AG3-002",
            summary="hallucinated api",
            observed_at=_NOW,
        )
        assert cand.run_id is None

    def test_frozen(self) -> None:
        cand = _candidate()
        with pytest.raises(ValidationError):
            cand.summary = "mutated"  # type: ignore[misc]

    def test_extra_forbid(self) -> None:
        with pytest.raises(ValidationError):
            IncidentCandidate(
                category=FailureCategory.SCOPE_DRIFT,
                severity=IncidentSeverity.HIGH,
                source_bc="x",
                story_id="y",
                summary="z",
                observed_at=_NOW,
                unexpected_field="boom",  # type: ignore[call-arg]
            )


class TestIncident:
    def test_default_status_observed(self) -> None:
        incident = Incident(
            incident_id=IncidentId("FC-abc"),
            category=FailureCategory.SCOPE_DRIFT,
            severity=IncidentSeverity.HIGH,
            source_bc="governance-and-guards",
            story_id="AG3-001",
            run_id="run-1",
            summary="scope exceeded",
            evidence={},
            observed_at=_NOW,
            normalized_at=_NOW,
        )
        assert incident.incident_status is IncidentStatus.OBSERVED

    def test_frozen_and_extra_forbid(self) -> None:
        incident = Incident(
            incident_id=IncidentId("FC-abc"),
            category=FailureCategory.SCOPE_DRIFT,
            severity=IncidentSeverity.HIGH,
            source_bc="bc",
            story_id="AG3-001",
            summary="s",
            observed_at=_NOW,
            normalized_at=_NOW,
        )
        with pytest.raises(ValidationError):
            incident.summary = "mutated"  # type: ignore[misc]


class TestIncidentSeverity:
    def test_four_lowercase_values(self) -> None:
        assert [m.value for m in IncidentSeverity] == [
            "low",
            "medium",
            "high",
            "critical",
        ]
