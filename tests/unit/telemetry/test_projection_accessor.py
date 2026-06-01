"""Unit-Tests fuer ProjectionAccessor.

Testet:
- write_projection: jedes ProjectionKind leitet in das richtige Repository
- read_projection: Filter werden korrekt durchgereicht
- Discriminated-Union-Validierung: falscher Record-Typ -> ProjectionRecordTypeMismatchError
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from agentkit.closure.post_merge_finalization.records import StoryMetricsRecord
from agentkit.telemetry.errors import (
    ProjectionKindNotAccessorOwnedError,
    ProjectionRecordTypeMismatchError,
)
from agentkit.telemetry.projection_accessor import (
    ProjectionAccessor,
    ProjectionFilter,
    ProjectionKind,
)
from agentkit.verify_system.stage_registry.records import (
    QAFindingRecord,
    QAStageResultRecord,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_qa_stage_result() -> QAStageResultRecord:
    return QAStageResultRecord(
        project_key="test-proj",
        story_id="TEST-001",
        run_id="run-abc",
        attempt_no=1,
        stage_id="structural",
        layer="structural",
        producer_component="qa-structural-check",
        status="PASS",
        blocking=False,
        total_checks=5,
        failed_checks=0,
        warning_checks=0,
        artifact_id="art-123",
        recorded_at=datetime.now(UTC),
    )


def _make_qa_finding() -> QAFindingRecord:
    return QAFindingRecord(
        project_key="test-proj",
        story_id="TEST-001",
        run_id="run-abc",
        attempt_no=1,
        stage_id="structural",
        finding_id="structural-abc123",
        check_id="mypy_error",
        status="REPORTED",
        severity="BLOCKING",
        blocking=True,
        source_component="qa-structural-check",
        artifact_id="art-123",
        occurred_at=datetime.now(UTC),
    )


def _make_story_metrics() -> StoryMetricsRecord:
    return StoryMetricsRecord(
        project_key="test-proj",
        story_id="TEST-001",
        run_id="run-abc",
        story_type="IMPLEMENTATION",
        story_size="M",
        mode="EXECUTION",
        processing_time_min=12.5,
        qa_rounds=2,
        increments=3,
        final_status="COMPLETED",
        completed_at="2026-05-25T10:00:00+00:00",
    )


def _make_incident() -> object:
    from datetime import UTC as _UTC
    from datetime import datetime as _dt

    from agentkit.core_types import FailureCategory
    from agentkit.failure_corpus.incident import Incident
    from agentkit.failure_corpus.types import (
        IncidentId,
        IncidentRole,
        IncidentSeverity,
    )

    return Incident(
        project_key="pk",
        incident_id=IncidentId("FC-2026-0001"),
        run_id="run-abc",
        story_id="TEST-001",
        category=FailureCategory.SCOPE_DRIFT,
        severity=IncidentSeverity.HIGH,
        phase="implementation",
        role=IncidentRole.WORKER,
        model="claude-opus",
        symptom="scope exceeded",
        evidence=["e1"],
        recorded_at=_dt(2026, 6, 1, 12, 0, 0, tzinfo=_UTC),
    )


def _make_draft() -> object:
    from datetime import UTC as _UTC
    from datetime import datetime as _dt

    from agentkit.core_types import FailureCategory
    from agentkit.failure_corpus.incident import IncidentDraft
    from agentkit.failure_corpus.types import IncidentRole, IncidentSeverity

    return IncidentDraft(
        project_key="pk",
        run_id="run-abc",
        story_id="TEST-001",
        category=FailureCategory.SCOPE_DRIFT,
        severity=IncidentSeverity.HIGH,
        phase="implementation",
        role=IncidentRole.WORKER,
        model="claude-opus",
        symptom="scope exceeded",
        evidence=["e1"],
        recorded_at=_dt(2026, 6, 1, 12, 0, 0, tzinfo=_UTC),
    )


def _make_repos() -> MagicMock:
    """Erzeugt einen Mock-ProjectionRepositories-Container."""
    repos = MagicMock()
    repos.qa_stage_results = MagicMock()
    repos.qa_findings = MagicMock()
    repos.story_metrics = MagicMock()
    repos.phase_state_projection = MagicMock()
    repos.fc_incidents = MagicMock()
    return repos


# ---------------------------------------------------------------------------
# write_projection: korrekter Record-Typ -> richtiges Repository
# ---------------------------------------------------------------------------


def test_write_qa_stage_results_calls_repo() -> None:
    """write_projection(QA_STAGE_RESULTS, QAStageResultRecord) -> qa_stage_results.write."""
    repos = _make_repos()
    accessor = ProjectionAccessor(repos)
    record = _make_qa_stage_result()

    accessor.write_projection(ProjectionKind.QA_STAGE_RESULTS, record)

    repos.qa_stage_results.write.assert_called_once_with(record)
    repos.qa_findings.write.assert_not_called()
    repos.story_metrics.write.assert_not_called()


def test_write_qa_findings_calls_repo() -> None:
    """write_projection(QA_FINDINGS, QAFindingRecord) -> qa_findings.write."""
    repos = _make_repos()
    accessor = ProjectionAccessor(repos)
    record = _make_qa_finding()

    accessor.write_projection(ProjectionKind.QA_FINDINGS, record)

    repos.qa_findings.write.assert_called_once_with(record)
    repos.qa_stage_results.write.assert_not_called()
    repos.story_metrics.write.assert_not_called()


def test_write_story_metrics_calls_repo() -> None:
    """write_projection(STORY_METRICS, StoryMetricsRecord) -> story_metrics.write."""
    repos = _make_repos()
    accessor = ProjectionAccessor(repos)
    record = _make_story_metrics()

    accessor.write_projection(ProjectionKind.STORY_METRICS, record)

    repos.story_metrics.write.assert_called_once_with(record)
    repos.qa_stage_results.write.assert_not_called()
    repos.qa_findings.write.assert_not_called()


# ---------------------------------------------------------------------------
# write_projection: falscher Record-Typ -> ProjectionRecordTypeMismatchError
# ---------------------------------------------------------------------------


def test_wrong_record_type_for_qa_stage_results_raises() -> None:
    """QA_STAGE_RESULTS mit QAFindingRecord -> ProjectionRecordTypeMismatchError."""
    repos = _make_repos()
    accessor = ProjectionAccessor(repos)
    wrong_record = _make_qa_finding()  # falscher Typ

    with pytest.raises(ProjectionRecordTypeMismatchError) as exc_info:
        accessor.write_projection(ProjectionKind.QA_STAGE_RESULTS, wrong_record)

    err = exc_info.value
    assert err.kind == ProjectionKind.QA_STAGE_RESULTS
    assert err.expected == QAStageResultRecord
    assert err.received == QAFindingRecord
    repos.qa_stage_results.write.assert_not_called()


def test_wrong_record_type_for_qa_findings_raises() -> None:
    """QA_FINDINGS mit StoryMetricsRecord -> ProjectionRecordTypeMismatchError."""
    repos = _make_repos()
    accessor = ProjectionAccessor(repos)
    wrong_record = _make_story_metrics()

    with pytest.raises(ProjectionRecordTypeMismatchError):
        accessor.write_projection(ProjectionKind.QA_FINDINGS, wrong_record)

    repos.qa_findings.write.assert_not_called()


def test_wrong_record_type_for_story_metrics_raises() -> None:
    """STORY_METRICS mit QAStageResultRecord -> ProjectionRecordTypeMismatchError."""
    repos = _make_repos()
    accessor = ProjectionAccessor(repos)
    wrong_record = _make_qa_stage_result()

    with pytest.raises(ProjectionRecordTypeMismatchError):
        accessor.write_projection(ProjectionKind.STORY_METRICS, wrong_record)

    repos.story_metrics.write.assert_not_called()


# ---------------------------------------------------------------------------
# write_projection: extern besessene Kinds -> ProjectionKindNotAccessorOwnedError
# (FK-69 §69.3/§69.4 expliziter Owner-Vertrag; Codex-Recheck #3: kein toter
#  NotImplementedError-Pfad, sondern fail-closed mit Owner-Benennung)
# ---------------------------------------------------------------------------


def test_phase_state_projection_write_raises_not_accessor_owned() -> None:
    """PHASE_STATE_PROJECTION ist extern besessen (Write-Owner: PhaseExecutor)."""
    repos = _make_repos()
    accessor = ProjectionAccessor(repos)
    record = _make_story_metrics()  # Typ spielt keine Rolle; Kind extern besessen

    with pytest.raises(ProjectionKindNotAccessorOwnedError) as exc_info:
        accessor.write_projection(ProjectionKind.PHASE_STATE_PROJECTION, record)

    assert exc_info.value.kind is ProjectionKind.PHASE_STATE_PROJECTION
    assert "PhaseExecutor" in exc_info.value.owner
    # Subklasse von NotImplementedError (Backwards-Kompatibilitaet der Guards):
    assert isinstance(exc_info.value, NotImplementedError)


def test_fc_incidents_record_calls_repo() -> None:
    """AG3-028 Codex-r1: FC_INCIDENTS wird ueber record_fc_incident geschrieben.

    Die generische write_projection-API ist fail-closed (id muss zurueck);
    der dedizierte Pfad delegiert an fc_incidents.record_incident und gibt die id.
    """
    from agentkit.failure_corpus.types import IncidentId
    from agentkit.telemetry.errors import FCIncidentWriteViaDedicatedMethodError

    repos = _make_repos()
    repos.fc_incidents.record_incident.return_value = IncidentId("FC-2026-0007")
    accessor = ProjectionAccessor(repos)
    draft = _make_draft()

    # Generische write_projection ist fail-closed.
    with pytest.raises(FCIncidentWriteViaDedicatedMethodError):
        accessor.write_projection(ProjectionKind.FC_INCIDENTS, _make_incident())  # type: ignore[arg-type]

    # Dedizierter Pfad gibt die id zurueck.
    incident_id = accessor.record_fc_incident(draft)  # type: ignore[arg-type]
    repos.fc_incidents.record_incident.assert_called_once_with(draft)
    assert incident_id == "FC-2026-0007"
    repos.story_metrics.write.assert_not_called()


def test_is_accessor_owned_contract() -> None:
    """is_accessor_owned trennt accessor-besessene von extern besessenen Kinds.

    FK-69 §69.3 listet alle 7 Tabellen; §69.4 vergibt Write-Ownership. Der
    Accessor besitzt QA + story_metrics + (seit AG3-028) fc_incidents; die
    uebrigen drei Kinds sind bewusst publiziert, aber extern besessen.
    """
    owned = {
        ProjectionKind.QA_STAGE_RESULTS,
        ProjectionKind.QA_FINDINGS,
        ProjectionKind.STORY_METRICS,
        ProjectionKind.FC_INCIDENTS,
    }
    external = {
        ProjectionKind.PHASE_STATE_PROJECTION,
        ProjectionKind.FC_PATTERNS,
        ProjectionKind.FC_CHECK_PROPOSALS,
    }
    for kind in owned:
        assert ProjectionAccessor.is_accessor_owned(kind) is True
    for kind in external:
        assert ProjectionAccessor.is_accessor_owned(kind) is False
    # Vollstaendigkeit: jede der 7 FK-69-Tabellen ist klassifiziert.
    assert owned | external == set(ProjectionKind)


# ---------------------------------------------------------------------------
# read_projection: Filter werden korrekt durchgereicht
# ---------------------------------------------------------------------------


def test_read_qa_stage_results_passes_filter() -> None:
    """read_projection(QA_STAGE_RESULTS, filter) leitet Filter an Repository."""
    repos = _make_repos()
    repos.qa_stage_results.read.return_value = []
    accessor = ProjectionAccessor(repos)
    f = ProjectionFilter(
        project_key="pk",
        story_id="S-001",
        run_id="run-xyz",
        attempt_no=2,
        stage_id="structural",
    )

    result = accessor.read_projection(ProjectionKind.QA_STAGE_RESULTS, f)

    repos.qa_stage_results.read.assert_called_once_with(
        project_key="pk",
        story_id="S-001",
        run_id="run-xyz",
        attempt_no=2,
        stage_id="structural",
    )
    assert result == []


def test_read_qa_findings_passes_filter() -> None:
    """read_projection(QA_FINDINGS, filter) leitet Filter an Repository."""
    repos = _make_repos()
    expected = [_make_qa_finding()]
    repos.qa_findings.read.return_value = expected
    accessor = ProjectionAccessor(repos)
    f = ProjectionFilter(story_id="S-001", run_id="run-xyz")

    result = accessor.read_projection(ProjectionKind.QA_FINDINGS, f)

    repos.qa_findings.read.assert_called_once_with(
        project_key=None,
        story_id="S-001",
        run_id="run-xyz",
        attempt_no=None,
        stage_id=None,
    )
    assert result == expected


def test_read_story_metrics_passes_filter() -> None:
    """read_projection(STORY_METRICS, filter) leitet Filter an Repository."""
    repos = _make_repos()
    expected = [_make_story_metrics()]
    repos.story_metrics.read.return_value = expected
    accessor = ProjectionAccessor(repos)
    f = ProjectionFilter(project_key="pk", story_id="S-001")

    result = accessor.read_projection(ProjectionKind.STORY_METRICS, f)

    repos.story_metrics.read.assert_called_once_with(
        project_key="pk",
        story_id="S-001",
        run_id=None,
    )
    assert result == expected


def test_read_fc_incidents_passes_filter() -> None:
    """AG3-028 KONFLIKT-2: FC_INCIDENTS-Read leitet Filter an fc_incidents.read."""
    repos = _make_repos()
    expected = [_make_incident()]
    repos.fc_incidents.read.return_value = expected
    accessor = ProjectionAccessor(repos)
    f = ProjectionFilter(project_key="pk", story_id="S-001", run_id="run-xyz")

    result = accessor.read_projection(ProjectionKind.FC_INCIDENTS, f)

    repos.fc_incidents.read.assert_called_once_with(
        project_key="pk",
        story_id="S-001",
        run_id="run-xyz",
    )
    assert result == expected


def test_read_fc_patterns_raises_not_accessor_owned() -> None:
    """FC_PATTERNS bleibt fail-closed bis zur Producer-Folge-Story."""
    repos = _make_repos()
    accessor = ProjectionAccessor(repos)
    f = ProjectionFilter()

    with pytest.raises(ProjectionKindNotAccessorOwnedError) as exc_info:
        accessor.read_projection(ProjectionKind.FC_PATTERNS, f)

    assert exc_info.value.kind is ProjectionKind.FC_PATTERNS


def test_read_phase_state_projection_raises_not_accessor_owned() -> None:
    """PHASE_STATE_PROJECTION-Read ist extern besessen (Write-Owner: PhaseExecutor)."""
    repos = _make_repos()
    accessor = ProjectionAccessor(repos)
    f = ProjectionFilter()

    with pytest.raises(ProjectionKindNotAccessorOwnedError) as exc_info:
        accessor.read_projection(ProjectionKind.PHASE_STATE_PROJECTION, f)

    assert exc_info.value.kind is ProjectionKind.PHASE_STATE_PROJECTION
    assert "PhaseExecutor" in exc_info.value.owner


# ---------------------------------------------------------------------------
# ProjectionRecordTypeMismatchError -- Fehlerattribute pruefen
# ---------------------------------------------------------------------------


def test_mismatch_error_attributes() -> None:
    """ProjectionRecordTypeMismatchError hat kind/expected/received."""
    err = ProjectionRecordTypeMismatchError(
        kind=ProjectionKind.QA_STAGE_RESULTS,
        expected=QAStageResultRecord,
        received=StoryMetricsRecord,
    )
    assert err.kind == ProjectionKind.QA_STAGE_RESULTS
    assert err.expected == QAStageResultRecord
    assert err.received == StoryMetricsRecord
    assert "QAStageResultRecord" in str(err)
    assert "StoryMetricsRecord" in str(err)
