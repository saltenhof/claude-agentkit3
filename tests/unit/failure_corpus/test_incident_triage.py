"""Unit-Tests fuer IncidentTriage / IncidentNormalizer / IngressCriteria (AG3-028 §2.1.4, FK-41 §41.4.3).

Writer-/Reader-Ports werden hier durch minimale In-Memory-Spies ersetzt: ein
technisch begruendeter, isolierter Unit-Test der reinen Triage-Logik
(CLAUDE.md MOCKS/STUBS-Ausnahme 2). Der echte Schreib-/Lesepfad ueber den
ProjectionAccessor wird im Roundtrip-/Integration-Test verprobt.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from agentkit.core_types import FailureCategory, IncidentStatus
from agentkit.failure_corpus import (
    IncidentCandidate,
    IncidentDraft,
    IncidentNormalizer,
    IncidentRole,
    IncidentSeverity,
    IncidentTriage,
    IngressCriteria,
)
from agentkit.failure_corpus.errors import IncidentRejectedError, IncidentRejectReason
from agentkit.failure_corpus.types import IncidentId

if TYPE_CHECKING:
    from agentkit.telemetry.projection_accessor import ProjectionFilter, ProjectionKind
    from agentkit.telemetry.projection_records import ProjectionRecord

_NOW = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)


class _SpyWriter:
    """Minimaler IncidentWriterPort-Spy; vergibt sequenzielle FC-Ids."""

    def __init__(self) -> None:
        self.drafts: list[IncidentDraft] = []

    def record_fc_incident(self, draft: IncidentDraft) -> IncidentId:
        self.drafts.append(draft)
        return IncidentId(f"FC-2026-{len(self.drafts):04d}")


class _SpyReader:
    """Minimaler ProjectionReaderPort-Spy; gibt fest konfigurierte Records zurueck."""

    def __init__(self, existing: list[ProjectionRecord] | None = None) -> None:
        self._existing = existing or []
        self.reads: list[tuple[ProjectionKind, ProjectionFilter]] = []

    def read_projection(
        self,
        projection_kind: ProjectionKind,
        filter: ProjectionFilter,  # noqa: A002
    ) -> list[ProjectionRecord]:
        self.reads.append((projection_kind, filter))
        return list(self._existing)


def _candidate(
    *,
    severity: IncidentSeverity = IncidentSeverity.HIGH,
    symptom: str = "scope exceeded",
    story_id: str = "AG3-001",
    category: FailureCategory = FailureCategory.SCOPE_DRIFT,
    merge_blocked: bool = True,
    rework_minutes: int = 0,
) -> IncidentCandidate:
    return IncidentCandidate(
        project_key="proj-a",
        story_id=story_id,
        run_id="run-1",
        category=category,
        severity=severity,
        phase="implementation",
        role=IncidentRole.WORKER,
        model="claude-opus",
        symptom=symptom,
        evidence=["e1"],
        merge_blocked=merge_blocked,
        rework_minutes=rework_minutes,
    )


class TestIncidentNormalizer:
    def test_collapses_whitespace_and_sets_recorded_at(self) -> None:
        draft = IncidentNormalizer().normalize(
            _candidate(symptom="  scope   exceeded \n badly  "),
            recorded_at=_NOW,
        )
        assert draft.symptom == "scope exceeded badly"
        assert draft.recorded_at == _NOW
        assert draft.incident_status is IncidentStatus.OBSERVED

    def test_caps_symptom_length(self) -> None:
        draft = IncidentNormalizer(max_symptom_length=5).normalize(
            _candidate(symptom="abcdefghij"),
            recorded_at=_NOW,
        )
        assert draft.symptom == "abcde"

    def test_returns_draft_without_id(self) -> None:
        draft = IncidentNormalizer().normalize(_candidate(), recorded_at=_NOW)
        assert isinstance(draft, IncidentDraft)


class TestIngressCriteria:
    """DK-07 §7.3.6: reines ODER der vier Aufnahmekriterien."""

    def test_admits_severity_at_or_above_min(self) -> None:
        # MEDIUM allein genuegt (Severity-Kriterium des ODER), kein weiterer
        # Trigger noetig.
        IngressCriteria().check(
            _candidate(
                severity=IncidentSeverity.MEDIUM,
                merge_blocked=False,
                rework_minutes=0,
            ),
            is_novel=False,
        )

    def test_admits_low_plus_merge_blocked(self) -> None:
        # DK-07 §7.3.6: LOW + merge_blocked wird aufgenommen (kein AND-Floor mehr).
        IngressCriteria().check(
            _candidate(
                severity=IncidentSeverity.LOW, merge_blocked=True, rework_minutes=0
            ),
            is_novel=False,
        )

    def test_admits_low_plus_rework_over_threshold(self) -> None:
        IngressCriteria().check(
            _candidate(
                severity=IncidentSeverity.LOW, merge_blocked=False, rework_minutes=31
            ),
            is_novel=False,
        )

    def test_admits_low_plus_novel(self) -> None:
        IngressCriteria().check(
            _candidate(
                severity=IncidentSeverity.LOW, merge_blocked=False, rework_minutes=0
            ),
            is_novel=True,
        )

    def test_rejects_low_with_no_criterion(self) -> None:
        # LOW + nichts: kein ODER-Kriterium greift -> NOT_SIGNIFICANT.
        with pytest.raises(IncidentRejectedError) as exc:
            IngressCriteria().check(
                _candidate(
                    severity=IncidentSeverity.LOW,
                    merge_blocked=False,
                    rework_minutes=0,
                ),
                is_novel=False,
            )
        assert exc.value.reason_codes == (IncidentRejectReason.NOT_SIGNIFICANT,)

    def test_rework_exactly_at_threshold_with_low_is_not_significant(self) -> None:
        # "Ueber 30 Minuten" -> 30 genau ist KEIN Trigger (strict >); LOW + sonst
        # nichts -> NOT_SIGNIFICANT.
        with pytest.raises(IncidentRejectedError):
            IngressCriteria().check(
                _candidate(
                    severity=IncidentSeverity.LOW,
                    merge_blocked=False,
                    rework_minutes=30,
                ),
                is_novel=False,
            )

    def test_rejects_exact_duplicate_window(self) -> None:
        # Exakter Duplikat im Zeitfenster -> DUPLICATE_WINDOW (separat).
        with pytest.raises(IncidentRejectedError) as exc:
            IngressCriteria().check(
                _candidate(severity=IncidentSeverity.HIGH),
                is_novel=False,
                is_duplicate=True,
            )
        assert exc.value.reason_codes == (IncidentRejectReason.DUPLICATE_WINDOW,)


class TestIncidentTriageIngest:
    def _triage(self, writer: _SpyWriter, reader: _SpyReader) -> IncidentTriage:
        return IncidentTriage(
            normalizer=IncidentNormalizer(),
            criteria=IngressCriteria(),
            writer=writer,
            reader=reader,
        )

    def test_happy_path_persists_and_returns_id(self) -> None:
        writer, reader = _SpyWriter(), _SpyReader()
        incident_id = self._triage(writer, reader).ingest(_candidate())

        assert len(writer.drafts) == 1
        assert writer.drafts[0].symptom == "scope exceeded"
        assert incident_id == "FC-2026-0001"

    def test_novelty_checks_corpus_projectbound(self) -> None:
        writer, reader = _SpyWriter(), _SpyReader()
        self._triage(writer, reader).ingest(_candidate())

        from agentkit.telemetry.projection_accessor import ProjectionKind

        assert len(reader.reads) == 1
        kind, flt = reader.reads[0]
        assert kind is ProjectionKind.FC_INCIDENTS
        assert flt.project_key == "proj-a"

    def test_reject_does_not_persist(self) -> None:
        # Existierender Incident gleicher (project, category) -> nicht novel;
        # LOW + nicht merge-blocked + kein Rework -> NOT_SIGNIFICANT.
        from agentkit.failure_corpus import Incident

        existing = Incident(
            project_key="proj-a",
            incident_id=IncidentId("FC-2026-0001"),
            run_id="run-0",
            story_id="AG3-000",
            category=FailureCategory.SCOPE_DRIFT,
            severity=IncidentSeverity.HIGH,
            phase="implementation",
            role=IncidentRole.WORKER,
            model="m",
            symptom="prior",
            recorded_at=_NOW,
        )
        writer, reader = _SpyWriter(), _SpyReader([existing])
        with pytest.raises(IncidentRejectedError):
            self._triage(writer, reader).ingest(
                _candidate(
                    severity=IncidentSeverity.LOW,
                    merge_blocked=False,
                    rework_minutes=0,
                )
            )
        assert writer.drafts == []

    def test_not_significant_when_in_corpus_and_no_trigger(self) -> None:
        # Existierender Incident gleicher (project, category) -> nicht novel;
        # LOW, kein Merge-Block, Rework klein -> NOT_SIGNIFICANT (reines ODER).
        from agentkit.failure_corpus import Incident

        existing = Incident(
            project_key="proj-a",
            incident_id=IncidentId("FC-2026-0001"),
            run_id="run-0",
            story_id="AG3-000",
            category=FailureCategory.SCOPE_DRIFT,
            severity=IncidentSeverity.HIGH,
            phase="implementation",
            role=IncidentRole.WORKER,
            model="m",
            symptom="prior",
            recorded_at=_NOW,
        )
        writer, reader = _SpyWriter(), _SpyReader([existing])
        with pytest.raises(IncidentRejectedError) as exc:
            self._triage(writer, reader).ingest(
                _candidate(
                    category=FailureCategory.SCOPE_DRIFT,
                    severity=IncidentSeverity.LOW,
                    merge_blocked=False,
                    rework_minutes=5,
                )
            )
        assert exc.value.reason_codes == (IncidentRejectReason.NOT_SIGNIFICANT,)
        assert writer.drafts == []

    def test_exact_duplicate_in_corpus_rejected(self) -> None:
        # Exakter Duplikat (gleiche fachliche Signatur) bereits im Corpus ->
        # DUPLICATE_WINDOW, auch wenn Severity/Trigger eine Aufnahme erlauben.
        from agentkit.failure_corpus import Incident

        existing = Incident(
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
            recorded_at=_NOW,
        )
        writer, reader = _SpyWriter(), _SpyReader([existing])
        with pytest.raises(IncidentRejectedError) as exc:
            self._triage(writer, reader).ingest(
                _candidate(
                    severity=IncidentSeverity.HIGH,
                    symptom="scope exceeded",
                    merge_blocked=True,
                )
            )
        assert exc.value.reason_codes == (IncidentRejectReason.DUPLICATE_WINDOW,)
        assert writer.drafts == []
