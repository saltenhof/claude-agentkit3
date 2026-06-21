"""Unit-Tests fuer IncidentCandidate/IncidentDraft/Incident (AG3-028 §2.1.3, FK-41 §41.4.1)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from agentkit.backend.core_types import FailureCategory, IncidentStatus
from agentkit.backend.failure_corpus import (
    Incident,
    IncidentCandidate,
    IncidentDraft,
    IncidentRole,
    IncidentSeverity,
)
from agentkit.backend.failure_corpus.types import IncidentId

_NOW = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)


def _candidate() -> IncidentCandidate:
    return IncidentCandidate(
        project_key="proj-a",
        story_id="AG3-001",
        run_id="run-1",
        category=FailureCategory.SCOPE_DRIFT,
        severity=IncidentSeverity.HIGH,
        phase="implementation",
        role=IncidentRole.WORKER,
        model="claude-opus",
        symptom="scope exceeded",
        evidence=["commit a1b2c3d: out of scope"],
        merge_blocked=True,
    )


class TestIncidentCandidate:
    def test_constructable(self) -> None:
        cand = _candidate()
        assert cand.project_key == "proj-a"
        assert cand.category is FailureCategory.SCOPE_DRIFT
        assert cand.role is IncidentRole.WORKER
        assert cand.evidence == ["commit a1b2c3d: out of scope"]

    def test_gate_inputs_default(self) -> None:
        cand = IncidentCandidate(
            project_key="p",
            story_id="s",
            run_id="r",
            category=FailureCategory.HALLUCINATION,
            severity=IncidentSeverity.MEDIUM,
            phase="implementation",
            role=IncidentRole.QA,
            model="m",
            symptom="x",
        )
        assert cand.merge_blocked is False
        assert cand.rework_minutes == 0
        assert cand.evidence == []

    def test_frozen(self) -> None:
        cand = _candidate()
        with pytest.raises(ValidationError):
            cand.symptom = "mutated"  # type: ignore[misc]

    def test_rejects_dict_evidence(self) -> None:
        # Codex-r2: evidence MUSS list[str] sein, kein dict (FAIL-CLOSED).
        with pytest.raises(ValidationError):
            IncidentCandidate(
                project_key="p",
                story_id="s",
                run_id="r",
                category=FailureCategory.SCOPE_DRIFT,
                severity=IncidentSeverity.HIGH,
                phase="implementation",
                role=IncidentRole.WORKER,
                model="m",
                symptom="z",
                evidence={"k": "v"},  # type: ignore[arg-type]
            )

    def test_extra_forbid(self) -> None:
        with pytest.raises(ValidationError):
            IncidentCandidate(
                project_key="p",
                story_id="s",
                run_id="r",
                category=FailureCategory.SCOPE_DRIFT,
                severity=IncidentSeverity.HIGH,
                phase="implementation",
                role=IncidentRole.WORKER,
                model="m",
                symptom="z",
                unexpected_field="boom",  # type: ignore[call-arg]
            )


class TestIncident:
    def test_default_status_observed(self) -> None:
        incident = Incident(
            project_key="proj-a",
            incident_id=IncidentId("FC-2026-0001"),
            run_id="run-1",
            story_id="AG3-001",
            category=FailureCategory.SCOPE_DRIFT,
            severity=IncidentSeverity.HIGH,
            phase="implementation",
            role=IncidentRole.WORKER,
            model="claude-opus",
            symptom="scope exceeded",
            evidence=["e1"],
            recorded_at=_NOW,
        )
        assert incident.incident_status is IncidentStatus.OBSERVED
        assert incident.pattern_ref is None

    def test_frozen_and_extra_forbid(self) -> None:
        incident = Incident(
            project_key="proj-a",
            incident_id=IncidentId("FC-2026-0001"),
            run_id="run-1",
            story_id="AG3-001",
            category=FailureCategory.SCOPE_DRIFT,
            severity=IncidentSeverity.HIGH,
            phase="implementation",
            role=IncidentRole.WORKER,
            model="m",
            symptom="s",
            recorded_at=_NOW,
        )
        with pytest.raises(ValidationError):
            incident.symptom = "mutated"  # type: ignore[misc]

    def test_rejects_invalid_incident_id_format(self) -> None:
        # Codex-r2: FC-YYYY-NNNN FAIL-CLOSED — "not-fc" muss rot werden.
        with pytest.raises(ValidationError):
            Incident(
                project_key="proj-a",
                incident_id=IncidentId("not-fc"),
                run_id="run-1",
                story_id="AG3-001",
                category=FailureCategory.SCOPE_DRIFT,
                severity=IncidentSeverity.HIGH,
                phase="implementation",
                role=IncidentRole.WORKER,
                model="m",
                symptom="s",
                recorded_at=_NOW,
            )

    def test_rejects_dict_evidence(self) -> None:
        # Codex-r2: evidence MUSS list[str] sein — dict-evidence muss rot werden.
        with pytest.raises(ValidationError):
            Incident(
                project_key="proj-a",
                incident_id=IncidentId("FC-2026-0001"),
                run_id="run-1",
                story_id="AG3-001",
                category=FailureCategory.SCOPE_DRIFT,
                severity=IncidentSeverity.HIGH,
                phase="implementation",
                role=IncidentRole.WORKER,
                model="m",
                symptom="s",
                evidence={"k": "v"},  # type: ignore[arg-type]
                recorded_at=_NOW,
            )


class TestIncidentDraft:
    def test_no_incident_id_field(self) -> None:
        # FK-41 §41.3.1: incident_id wird DB-seitig vergeben; der Draft hat keins.
        assert "incident_id" not in IncidentDraft.model_fields


class TestIncidentSeverity:
    def test_four_lowercase_values(self) -> None:
        assert [m.value for m in IncidentSeverity] == [
            "low",
            "medium",
            "high",
            "critical",
        ]


class TestIncidentRole:
    def test_three_values(self) -> None:
        assert [m.value for m in IncidentRole] == ["worker", "qa", "governance"]
