"""Runtime-Execution-Purge-Port tests (AG3-109, FK-53 §53.7.5).

Exercises the REAL driver path on both stores:

* SQLite: always (``AGENTKIT_ALLOW_SQLITE=1``).
* Postgres: opt-in via the project harness; skipped when
  ``AGENTKIT_STATE_DATABASE_URL`` is not set (real ``postgres_schema.sql`` /
  ``postgres_store`` driver, same pattern as the other state_backend roundtrip
  tests, e.g. ``test_governance_hook_repository``).

Each roundtrip seeds rows via the canonical ``save_*`` facade APIs / owner
repositories, purges via the NEW owner-purge APIs / coordinating port, then
asserts removal via the real ``load_*`` / query path. No hand-rolled fake that
skips the actual DELETE.

§3 coverage map:
* AK1  -> ``TestPerEntityRoundtrip`` (one test per entity, both stores)
* AK2  -> ``TestPortFanOut`` (fan-out + counters + type assertion)
* AK3  -> ``TestIdempotency`` (second purge == 0, no error)
* AK4  -> ``TestRuntimeResidue`` (positive clean + negative artificial residue;
  §53.7.5 rule regression: stale snapshot/verify decision cannot influence a
  later run — second-QA closure of ``phase_snapshots`` + ``decision_records``)
* AK5  -> wiring via ``build_runtime_execution_purge_port`` (production assembly)
* AK6  -> run-bound artifact precision (other-run rows survive)
* negative path -> ``TestFailClosed`` (missing project_key/story_id/run_id)
* boundary -> ``TestReadModelBoundary`` (phase_state_projection NOT duplicated;
  canonical phase_states IS purged)
* fail-closed scoping -> ``TestResidueProbeScoping`` (mis-scoped purge surfaces
  as residue; the probe does not share the purge's project_key predicate)
"""

from __future__ import annotations

import os
import shutil
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from tests.phase_state_factory import make_phase_state

from agentkit.backend.artifacts import ArtifactEnvelope
from agentkit.backend.artifacts.producer import Producer, ProducerId, ProducerType
from agentkit.backend.bootstrap.composition_root import (
    build_runtime_execution_purge_port,
    build_runtime_execution_residue_probe,
)
from agentkit.backend.core_types import ArtifactClass, EnvelopeStatus, PolicyVerdict
from agentkit.backend.core_types.attempt import AttemptOutcome
from agentkit.backend.core_types.override import OverrideType
from agentkit.backend.governance.guard_system.records import (
    GuardDecision,
    GuardDecisionOutcome,
)
from agentkit.backend.phase_state_store.models import (
    FlowExecution,
    NodeExecutionLedger,
    OverrideRecord,
)
from agentkit.backend.pipeline_engine.phase_executor.models import (
    PhaseName,
    PhaseSnapshot,
    PhaseStatus,
)
from agentkit.backend.pipeline_engine.phase_executor.records import AttemptRecord
from agentkit.backend.state_backend.config import (
    ALLOW_SQLITE_ENV,
    STATE_BACKEND_ENV,
    STATE_DATABASE_URL_ENV,
)
from agentkit.backend.state_backend.store import (
    facade,
    reset_backend_cache_for_tests,
)
from agentkit.backend.state_backend.store.artifact_repository import (
    StateBackendArtifactRepository,
)
from agentkit.backend.state_backend.store.guard_decision_repository import (
    GuardDecisionRepository,
)
from agentkit.backend.state_backend.store.runtime_execution_purge import (
    RUNTIME_EXECUTION_PURGE_DOMAINS,
    RuntimeExecutionPurgePort,
    RuntimeExecutionPurgeResult,
    RuntimeExecutionResidueProbe,
)
from agentkit.backend.telemetry.contract.records import ExecutionEventRecord
from agentkit.backend.verify_system.policy_engine.engine import VerifyDecision

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

_PROJECT = "test-purge-proj"
_STORY = "AG3-9001"
_RUN = "11111111-1111-4111-8111-111111111111"
_OTHER_RUN = "22222222-2222-4222-8222-222222222222"
_NOW = datetime(2026, 6, 12, 10, 0, tzinfo=UTC)


def _has_postgres_url() -> bool:
    return bool(os.environ.get(STATE_DATABASE_URL_ENV, ""))


# ---------------------------------------------------------------------------
# Backend parametrization: real SQLite always, real Postgres opt-in
# ---------------------------------------------------------------------------


@pytest.fixture(params=["sqlite", "postgres"])
def backend(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Iterator[Path]:
    """Yield a store_dir for the parametrized backend (purge run pre-cleaned).

    The Postgres branch drives the REAL ``postgres_store`` driver against the
    project's worker-scoped test schema (``postgres_isolated_schema`` — docker
    Postgres or an explicit ``AGENTKIT_STATE_DATABASE_URL``). It skips only when
    neither a docker daemon nor an explicit URL is available.
    """
    if request.param == "postgres":
        if shutil.which("docker") is None and not _has_postgres_url():
            pytest.skip("No docker / AGENTKIT_STATE_DATABASE_URL — Postgres skipped")
        # Provisions a live PG schema and sets backend=postgres + URL + override.
        request.getfixturevalue("postgres_isolated_schema")
    else:
        monkeypatch.setenv(STATE_BACKEND_ENV, "sqlite")
        monkeypatch.setenv(ALLOW_SQLITE_ENV, "1")
    reset_backend_cache_for_tests()
    story_dir = tmp_path / _STORY
    story_dir.mkdir(parents=True, exist_ok=True)
    # Pre-clean (Postgres shares a worker schema across tests in a run).
    _purge_all(story_dir)
    yield story_dir
    _purge_all(story_dir)
    reset_backend_cache_for_tests()


def _purge_all(story_dir: Path) -> None:
    for run in (_RUN, _OTHER_RUN):
        RuntimeExecutionPurgePort(story_dir).purge_run(_PROJECT, _STORY, run)


# ---------------------------------------------------------------------------
# Seed helpers (real save_* facade / owner repositories)
# ---------------------------------------------------------------------------


def _seed_flow_execution(story_dir: Path, run_id: str = _RUN) -> None:
    facade.save_flow_execution(
        story_dir,
        FlowExecution(
            project_key=_PROJECT,
            story_id=_STORY,
            run_id=run_id,
            flow_id="flow-1",
            level="story",
            owner="orchestrator",
            started_at=_NOW,
        ),
    )


def _seed_node_ledger(story_dir: Path, run_id: str = _RUN) -> None:
    facade.save_node_execution_ledger(
        story_dir,
        NodeExecutionLedger(
            project_key=_PROJECT,
            story_id=_STORY,
            run_id=run_id,
            flow_id="flow-1",
            node_id="node-1",
            execution_count=1,
            success_count=1,
        ),
    )


def _seed_attempt(story_dir: Path, run_id: str = _RUN) -> None:
    facade.save_attempt(
        story_dir,
        AttemptRecord(
            run_id=run_id,
            phase="implementation",
            attempt=1,
            outcome=AttemptOutcome.COMPLETED,
            started_at=_NOW,
            ended_at=_NOW,
        ),
    )


def _seed_override(story_dir: Path, run_id: str = _RUN) -> None:
    facade.save_override_record(
        story_dir,
        OverrideRecord(
            override_id=f"ovr-{run_id}",
            project_key=_PROJECT,
            story_id=_STORY,
            run_id=run_id,
            flow_id="flow-1",
            target_node_id="node-1",
            override_type=OverrideType.SKIP_NODE,
            actor_type="human",
            actor_id="alice",
            reason="manual skip",
            created_at=_NOW,
        ),
    )


def _seed_guard_decision(story_dir: Path, run_id: str = _RUN) -> None:
    GuardDecisionRepository(story_dir).append(
        GuardDecision(
            project_key=_PROJECT,
            story_id=_STORY,
            run_id=run_id,
            flow_id="flow-1",
            guard_decision_id=f"gd-{run_id}",
            guard_key="security.secrets",
            outcome=GuardDecisionOutcome.PASS,
            decided_at=_NOW,
        )
    )


def _seed_phase_state(story_dir: Path, run_id: str = _RUN) -> None:
    facade.save_phase_state(
        story_dir,
        make_phase_state(story_id=_STORY, run_id=run_id, phase="implementation"),
    )


def _seed_phase_snapshot(story_dir: Path) -> None:
    facade.save_phase_snapshot(
        story_dir,
        PhaseSnapshot(
            story_id=_STORY,
            phase=PhaseName.SETUP,
            status=PhaseStatus.COMPLETED,
            completed_at=_NOW,
        ),
    )


def _seed_verify_decision(story_dir: Path, attempt_nr: int = 3) -> None:
    # NOTE: the Postgres driver requires an existing flow_executions row to
    # resolve the decision scope — seed the flow execution first (as the real
    # verify path does). attempt_nr defaults to 3 to model a LATE attempt of a
    # corrupted run (attempt numbering restarts at 1 in the next run, so a
    # leftover row would shadow the new run's decision via MAX(attempt_nr)).
    facade.record_verify_decision(
        story_dir,
        decision=VerifyDecision(
            passed=True,
            verdict=PolicyVerdict.PASS,
            layer_results=(),
            all_findings=(),
            blocking_findings=(),
            summary="seeded stale verify decision (second-QA §53.7.5 probe)",
        ),
        attempt_nr=attempt_nr,
    )


def _seed_execution_event(story_dir: Path, run_id: str = _RUN) -> None:
    facade.append_execution_event(
        story_dir,
        ExecutionEventRecord(
            project_key=_PROJECT,
            story_id=_STORY,
            run_id=run_id,
            event_id=f"ev-{run_id}",
            event_type="phase_started",
            occurred_at=_NOW,
            source_component="pipeline",
            severity="info",
            phase="implementation",
        ),
    )


def _seed_artifact_envelope(story_dir: Path, run_id: str = _RUN) -> None:
    StateBackendArtifactRepository(story_dir).write_envelope(
        ArtifactEnvelope(
            schema_version="3.0",
            story_id=_STORY,
            run_id=run_id,
            stage="implementation",
            attempt=1,
            producer=Producer(
                type=ProducerType.WORKER,
                name="worker-agent",
                id=ProducerId("w-1"),
            ),
            started_at=_NOW,
            finished_at=_NOW,
            status=EnvelopeStatus.PASS,
            artifact_class=ArtifactClass.HANDOVER,
        )
    )


def _seed_all(story_dir: Path, run_id: str = _RUN) -> None:
    _seed_flow_execution(story_dir, run_id)
    _seed_node_ledger(story_dir, run_id)
    _seed_attempt(story_dir, run_id)
    _seed_override(story_dir, run_id)
    _seed_guard_decision(story_dir, run_id)
    _seed_verify_decision(story_dir)  # needs the flow execution seeded above
    _seed_phase_state(story_dir, run_id)
    _seed_phase_snapshot(story_dir)
    _seed_execution_event(story_dir, run_id)
    _seed_artifact_envelope(story_dir, run_id)


def _residue(story_dir: Path, run_id: str = _RUN) -> dict[str, int]:
    return facade.count_runtime_execution_residue(
        story_dir, _PROJECT, _STORY, run_id
    )


# ---------------------------------------------------------------------------
# AK1: per-entity roundtrip (create -> purge -> gone) on BOTH stores
# ---------------------------------------------------------------------------


class TestPerEntityRoundtrip:
    """Each Runtime-Execution entity: seed via save_*, purge, assert gone."""

    def test_flow_executions_roundtrip(self, backend: Path) -> None:
        _seed_flow_execution(backend)
        assert facade.load_flow_execution(backend) is not None
        deleted = facade.purge_flow_executions(backend, _PROJECT, _STORY, _RUN)
        assert deleted == 1
        assert facade.load_flow_execution(backend) is None

    def test_node_execution_ledgers_roundtrip(self, backend: Path) -> None:
        _seed_node_ledger(backend)
        assert facade.load_node_execution_ledger(backend, "flow-1", "node-1") is not None
        deleted = facade.purge_node_execution_ledgers(backend, _PROJECT, _STORY, _RUN)
        assert deleted == 1
        assert facade.load_node_execution_ledger(backend, "flow-1", "node-1") is None

    def test_attempts_roundtrip(self, backend: Path) -> None:
        _seed_attempt(backend)
        assert facade.load_attempts(backend, "implementation", run_id=_RUN)
        deleted = facade.purge_attempts(backend, _STORY, _RUN)
        assert deleted == 1
        assert facade.load_attempts(backend, "implementation", run_id=_RUN) == []

    def test_override_records_roundtrip(self, backend: Path) -> None:
        _seed_override(backend)
        assert facade.load_override_records(backend)
        deleted = facade.purge_override_records(backend, _PROJECT, _STORY, _RUN)
        assert deleted == 1
        assert facade.load_override_records(backend) == []

    def test_guard_decisions_roundtrip(self, backend: Path) -> None:
        _seed_guard_decision(backend)
        repo = GuardDecisionRepository(backend)
        assert repo.list_for_run(_PROJECT, _STORY, _RUN)
        deleted = facade.purge_guard_decisions(backend, _PROJECT, _STORY, _RUN)
        assert deleted == 1
        assert repo.list_for_run(_PROJECT, _STORY, _RUN) == ()

    def test_phase_states_roundtrip(self, backend: Path) -> None:
        _seed_phase_state(backend)
        assert facade.load_phase_state(backend) is not None
        deleted = facade.purge_phase_states(backend, _STORY)
        assert deleted == 1
        assert facade.load_phase_state(backend) is None

    def test_phase_snapshots_roundtrip(self, backend: Path) -> None:
        _seed_phase_snapshot(backend)
        assert facade.backend_has_completed_snapshot(backend, "setup")
        deleted = facade.purge_phase_snapshots(backend, _STORY)
        assert deleted == 1
        assert not facade.backend_has_completed_snapshot(backend, "setup")

    def test_decision_records_roundtrip(self, backend: Path) -> None:
        _seed_flow_execution(backend)  # Postgres decision scope needs the flow
        _seed_verify_decision(backend)
        assert facade.load_latest_verify_decision(backend) is not None
        deleted = facade.purge_decision_records(backend, _STORY)
        assert deleted == 1
        assert facade.load_latest_verify_decision(backend) is None

    def test_execution_events_roundtrip(self, backend: Path) -> None:
        _seed_execution_event(backend)
        assert facade.load_execution_events(backend, run_id=_RUN)
        deleted = facade.purge_execution_events(backend, _PROJECT, _STORY, _RUN)
        assert deleted == 1
        assert facade.load_execution_events(backend, run_id=_RUN) == []

    def test_artifact_envelopes_roundtrip(self, backend: Path) -> None:
        _seed_artifact_envelope(backend)
        repo = StateBackendArtifactRepository(backend)
        assert (
            repo.find_latest_envelope(
                story_id=_STORY,
                run_id=_RUN,
                artifact_class=ArtifactClass.HANDOVER,
                stage="implementation",
            )
            is not None
        )
        deleted = facade.purge_run_bound_artifact_envelopes(backend, _STORY, _RUN)
        assert deleted == 1
        assert (
            repo.find_latest_envelope(
                story_id=_STORY,
                run_id=_RUN,
                artifact_class=ArtifactClass.HANDOVER,
                stage="implementation",
            )
            is None
        )


# ---------------------------------------------------------------------------
# AK2: port fan-out + counters + runtime-specific result type
# ---------------------------------------------------------------------------


class TestPortFanOut:
    """One coordinated call removes all Runtime-Execution domains."""

    def test_fan_out_removes_all_domains_with_counters(self, backend: Path) -> None:
        _seed_all(backend)
        port = build_runtime_execution_purge_port(backend)

        result = port.purge_run(_PROJECT, _STORY, _RUN)

        assert sorted(result.purged_rows) == sorted(RUNTIME_EXECUTION_PURGE_DOMAINS)
        assert all(count == 1 for count in result.purged_rows.values())
        assert result.total_purged == len(RUNTIME_EXECUTION_PURGE_DOMAINS)
        # All gone after fan-out.
        assert all(count == 0 for count in _residue(backend).values())

    def test_result_type_is_runtime_specific_not_projection_purge_result(
        self, backend: Path
    ) -> None:
        from agentkit.backend.telemetry.projection_accessor import PurgeResult

        port = build_runtime_execution_purge_port(backend)
        result = port.purge_run(_PROJECT, _STORY, _RUN)

        assert isinstance(result, RuntimeExecutionPurgeResult)
        assert not isinstance(result, PurgeResult)

    def test_port_constructible_via_production_assembly(self, backend: Path) -> None:
        # AK5: the port + residue probe must be built through the real
        # composition root, not only hand-instantiated in a test.
        port = build_runtime_execution_purge_port(backend)
        probe = build_runtime_execution_residue_probe(backend)
        assert isinstance(port, RuntimeExecutionPurgePort)
        assert isinstance(probe, RuntimeExecutionResidueProbe)


# ---------------------------------------------------------------------------
# AK3: idempotency (second purge == 0 additional deletions, no error)
# ---------------------------------------------------------------------------


class TestIdempotency:
    """FK-53 §53.9.1: convergent purge — repeated call deletes nothing."""

    def test_second_port_purge_deletes_zero(self, backend: Path) -> None:
        _seed_all(backend)
        port = build_runtime_execution_purge_port(backend)

        first = port.purge_run(_PROJECT, _STORY, _RUN)
        assert first.total_purged == len(RUNTIME_EXECUTION_PURGE_DOMAINS)

        second = port.purge_run(_PROJECT, _STORY, _RUN)
        assert second.total_purged == 0
        assert all(count == 0 for count in second.purged_rows.values())

    def test_purge_of_absent_run_is_no_op(self, backend: Path) -> None:
        port = build_runtime_execution_purge_port(backend)
        result = port.purge_run(_PROJECT, _STORY, "never-written-run")
        assert result.total_purged == 0


# ---------------------------------------------------------------------------
# AK4: Runtime-Residue verify positive (clean) + negative (artificial residue)
# ---------------------------------------------------------------------------


class TestRuntimeResidue:
    """Runtime-Residue building block (FK-53 §53.7.5 rule)."""

    def test_residue_clean_after_purge(self, backend: Path) -> None:
        _seed_all(backend)
        port = build_runtime_execution_purge_port(backend)
        port.purge_run(_PROJECT, _STORY, _RUN)

        probe = build_runtime_execution_residue_probe(backend)
        residue = probe.check_run(_PROJECT, _STORY, _RUN)
        assert residue.is_clean
        assert all(count == 0 for count in residue.residue_rows.values())

    def test_residue_detected_for_artificial_residue(self, backend: Path) -> None:
        # Negative: a single surviving runtime object must trip the probe.
        _seed_guard_decision(backend)
        probe = build_runtime_execution_residue_probe(backend)
        residue = probe.check_run(_PROJECT, _STORY, _RUN)
        assert not residue.is_clean
        assert residue.residue_rows["guard_decisions"] == 1

    def test_stale_snapshot_and_verify_decision_cannot_influence_next_run(
        self, backend: Path
    ) -> None:
        # §53.7.5 rule regression (second-QA closure): completed-phase snapshots
        # and verify decisions are read STORY-keyed by guard/gate paths
        # (Integrity-Gate Dim 2 via backend_has_completed_snapshot; decision via
        # MAX(attempt_nr), which restarts at 1 in the next run). After the purge
        # neither may answer for the purged run.
        _seed_flow_execution(backend)
        _seed_phase_snapshot(backend)
        _seed_verify_decision(backend, attempt_nr=3)  # late attempt of old run
        assert facade.backend_has_completed_snapshot(backend, "setup")
        assert facade.backend_verify_decision_passed(backend)

        port = build_runtime_execution_purge_port(backend)
        result = port.purge_run(_PROJECT, _STORY, _RUN)
        assert result.purged_rows["phase_snapshots"] == 1
        assert result.purged_rows["decision_records"] == 1

        assert not facade.backend_has_completed_snapshot(backend, "setup")
        assert facade.load_latest_verify_decision(backend) is None
        assert not facade.backend_verify_decision_passed(backend)
        probe = build_runtime_execution_residue_probe(backend)
        assert probe.check_run(_PROJECT, _STORY, _RUN).is_clean


# ---------------------------------------------------------------------------
# Negative path: fail-closed on incomplete scope
# ---------------------------------------------------------------------------


class TestFailClosed:
    """Missing project_key (or story_id/run_id) fails closed, not silent purge."""

    def test_missing_project_key_raises(self, backend: Path) -> None:
        port = build_runtime_execution_purge_port(backend)
        with pytest.raises(ValueError, match="project_key"):
            port.purge_run("", _STORY, _RUN)

    def test_missing_run_id_raises(self, backend: Path) -> None:
        port = build_runtime_execution_purge_port(backend)
        with pytest.raises(ValueError, match="run_id"):
            port.purge_run(_PROJECT, _STORY, "")

    def test_missing_story_id_raises(self, backend: Path) -> None:
        port = build_runtime_execution_purge_port(backend)
        with pytest.raises(ValueError, match="story_id"):
            port.purge_run(_PROJECT, "", _RUN)

    def test_residue_probe_missing_project_key_raises(self, backend: Path) -> None:
        probe = build_runtime_execution_residue_probe(backend)
        with pytest.raises(ValueError, match="project_key"):
            probe.check_run("", _STORY, _RUN)


# ---------------------------------------------------------------------------
# AK6: run-bound artifact precision (other-run rows survive)
# ---------------------------------------------------------------------------


class TestRunBoundArtifactPrecision:
    """Only run-bound artifact_envelopes rows for (story_id, run_id) are purged."""

    def test_other_run_artifacts_survive(self, backend: Path) -> None:
        _seed_artifact_envelope(backend, _RUN)
        _seed_artifact_envelope(backend, _OTHER_RUN)

        deleted = facade.purge_run_bound_artifact_envelopes(backend, _STORY, _RUN)
        assert deleted == 1

        repo = StateBackendArtifactRepository(backend)
        assert (
            repo.find_latest_envelope(
                story_id=_STORY,
                run_id=_RUN,
                artifact_class=ArtifactClass.HANDOVER,
                stage="implementation",
            )
            is None
        )
        # The other run's durable-across-reset row is untouched.
        assert (
            repo.find_latest_envelope(
                story_id=_STORY,
                run_id=_OTHER_RUN,
                artifact_class=ArtifactClass.HANDOVER,
                stage="implementation",
            )
            is not None
        )


# ---------------------------------------------------------------------------
# Fail-closed scoping: the probe must not share the purge's project_key blind spot
# ---------------------------------------------------------------------------


class TestResidueProbeScoping:
    """A mis-scoped purge (wrong-but-non-empty project_key) surfaces as residue.

    The destructive purge keeps its narrow ``project_key`` predicate; the probe
    counts ``(story_id, run_id)``-scoped. If both shared the predicate, a purge
    called with a wrong ``project_key`` would delete nothing in the
    project-keyed tables AND the probe would report clean — a silent §53.7.5
    violation. Second-QA fix: the probe is deliberately broader.
    """

    def test_mis_scoped_purge_is_flagged_as_residue(self, backend: Path) -> None:
        _seed_guard_decision(backend)  # written under _PROJECT
        port = build_runtime_execution_purge_port(backend)

        # Wrong-but-non-empty project scope: project-keyed deletes match nothing.
        result = port.purge_run("some-other-project", _STORY, _RUN)
        assert result.purged_rows["guard_decisions"] == 0

        # The probe must fail closed on the surviving run-bound row.
        probe = build_runtime_execution_residue_probe(backend)
        residue = probe.check_run("some-other-project", _STORY, _RUN)
        assert not residue.is_clean
        assert residue.residue_rows["guard_decisions"] == 1

        # Correctly scoped purge converges to clean.
        assert port.purge_run(_PROJECT, _STORY, _RUN).purged_rows[
            "guard_decisions"
        ] == 1
        assert probe.check_run(_PROJECT, _STORY, _RUN).is_clean


# ---------------------------------------------------------------------------
# Boundary: read-model purge NOT duplicated; canonical phase_states IS purged
# ---------------------------------------------------------------------------


class TestReadModelBoundary:
    """Story does not duplicate read-model purge; canonical phase_states purged."""

    def test_port_does_not_touch_read_model_domains(self, backend: Path) -> None:
        # The runtime purge result keys are exactly the Runtime-Execution tables;
        # read-model tables (phase_state_projection, story_metrics, qa_*) are NOT
        # part of this story's purge surface.
        port = build_runtime_execution_purge_port(backend)
        result = port.purge_run(_PROJECT, _STORY, _RUN)
        assert "phase_state_projection" not in result.purged_rows
        assert "story_metrics" not in result.purged_rows
        assert "qa_stage_results" not in result.purged_rows
        assert "qa_findings" not in result.purged_rows

    def test_canonical_phase_states_is_purged(self, backend: Path) -> None:
        _seed_phase_state(backend)
        assert facade.load_phase_state(backend) is not None
        port = build_runtime_execution_purge_port(backend)
        result = port.purge_run(_PROJECT, _STORY, _RUN)
        assert result.purged_rows["phase_states"] == 1
        assert facade.load_phase_state(backend) is None
