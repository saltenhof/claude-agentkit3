"""Unit-Tests fuer IncidentTriage / IncidentNormalizer / IngressCriteria (AG3-028 §2.1.4).

Der ``ProjectionWriterPort`` wird hier durch einen minimalen In-Memory-Spy
ersetzt: das ist ein technisch begruendeter, isolierter Unit-Test der reinen
Triage-Logik (CLAUDE.md MOCKS/STUBS-Ausnahme 2). Der echte Schreibpfad ueber
den ProjectionAccessor wird im Roundtrip-/Integration-Test verprobt.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from agentkit.core_types import FailureCategory
from agentkit.failure_corpus import (
    Incident,
    IncidentCandidate,
    IncidentNormalizer,
    IncidentSeverity,
    IncidentTriage,
    IngressCriteria,
)
from agentkit.failure_corpus.errors import IncidentRejectedError, IncidentRejectReason
from agentkit.failure_corpus.types import IncidentId

if TYPE_CHECKING:
    from agentkit.telemetry.projection_accessor import ProjectionKind
    from agentkit.telemetry.projection_records import ProjectionRecord

_NOW = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)


class _SpyWriter:
    """Minimaler ProjectionWriterPort-Spy fuer den isolierten Triage-Test."""

    def __init__(self) -> None:
        self.writes: list[tuple[ProjectionKind, ProjectionRecord]] = []

    def write_projection(
        self,
        projection_kind: ProjectionKind,
        record: ProjectionRecord,
    ) -> None:
        self.writes.append((projection_kind, record))


def _candidate(
    *,
    severity: IncidentSeverity = IncidentSeverity.HIGH,
    summary: str = "scope exceeded",
    story_id: str = "AG3-001",
    source_bc: str = "governance-and-guards",
) -> IncidentCandidate:
    return IncidentCandidate(
        category=FailureCategory.SCOPE_DRIFT,
        severity=severity,
        source_bc=source_bc,
        story_id=story_id,
        run_id="run-1",
        summary=summary,
        evidence={"x": 1},
        observed_at=_NOW,
    )


class TestIncidentNormalizer:
    def test_collapses_whitespace_and_sets_normalized_at(self) -> None:
        normalizer = IncidentNormalizer()
        incident = normalizer.normalize(
            _candidate(summary="  scope   exceeded \n badly  "),
            incident_id=IncidentId("FC-1"),
            normalized_at=_NOW,
        )
        assert incident.summary == "scope exceeded badly"
        assert incident.normalized_at == _NOW

    def test_caps_summary_length(self) -> None:
        normalizer = IncidentNormalizer(max_summary_length=5)
        incident = normalizer.normalize(
            _candidate(summary="abcdefghij"),
            incident_id=IncidentId("FC-1"),
            normalized_at=_NOW,
        )
        assert incident.summary == "abcde"

    def test_returns_incident_instance(self) -> None:
        incident = IncidentNormalizer().normalize(
            _candidate(),
            incident_id=IncidentId("FC-1"),
            normalized_at=_NOW,
        )
        assert isinstance(incident, Incident)


class TestIngressCriteria:
    def test_rejects_below_min_severity(self) -> None:
        criteria = IngressCriteria(min_severity=IncidentSeverity.MEDIUM)
        with pytest.raises(IncidentRejectedError) as exc:
            criteria.check(_candidate(severity=IncidentSeverity.LOW), now=_NOW)
        assert IncidentRejectReason.BELOW_MIN_SEVERITY in exc.value.reason_codes

    def test_accepts_at_min_severity(self) -> None:
        criteria = IngressCriteria(min_severity=IncidentSeverity.MEDIUM)
        criteria.check(_candidate(severity=IncidentSeverity.MEDIUM), now=_NOW)

    def test_dedup_within_window(self) -> None:
        criteria = IngressCriteria(dedup_window_s=60.0)
        cand = _candidate()
        criteria.check(cand, now=_NOW)
        criteria.remember(cand, now=_NOW)
        later = _NOW.replace(second=30)
        with pytest.raises(IncidentRejectedError) as exc:
            criteria.check(cand, now=later)
        assert IncidentRejectReason.DUPLICATE_WINDOW in exc.value.reason_codes

    def test_dedup_outside_window_allowed(self) -> None:
        criteria = IngressCriteria(dedup_window_s=60.0)
        cand = _candidate()
        criteria.check(cand, now=_NOW)
        criteria.remember(cand, now=_NOW)
        later = _NOW.replace(minute=2)
        # outside 60s window -> accepted again
        criteria.check(cand, now=later)


class TestIncidentTriageIngest:
    def _triage(self, writer: _SpyWriter) -> IncidentTriage:
        return IncidentTriage(
            normalizer=IncidentNormalizer(),
            criteria=IngressCriteria(),
            projection_writer=writer,
        )

    def test_happy_path_writes_fc_incidents(self) -> None:
        from agentkit.telemetry.projection_accessor import ProjectionKind

        writer = _SpyWriter()
        triage = self._triage(writer)

        incident_id = triage.ingest(_candidate())

        assert len(writer.writes) == 1
        kind, record = writer.writes[0]
        assert kind is ProjectionKind.FC_INCIDENTS
        assert isinstance(record, Incident)
        assert record.incident_id == incident_id
        assert record.summary == "scope exceeded"

    def test_reject_does_not_write(self) -> None:
        writer = _SpyWriter()
        triage = self._triage(writer)
        with pytest.raises(IncidentRejectedError):
            triage.ingest(_candidate(severity=IncidentSeverity.LOW))
        assert writer.writes == []

    def test_three_steps_dedup_blocks_second_identical(self) -> None:
        writer = _SpyWriter()
        triage = self._triage(writer)
        triage.ingest(_candidate())
        # identical candidate within the 60s default window -> rejected
        with pytest.raises(IncidentRejectedError):
            triage.ingest(_candidate())
        assert len(writer.writes) == 1
