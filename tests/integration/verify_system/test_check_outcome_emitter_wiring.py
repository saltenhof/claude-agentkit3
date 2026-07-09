"""Integration: CheckOutcomeEmitter is wired into the real QA layer flow (AG3-108).

Proves AC2 of story AG3-108: after a real Layer-1 run (StructuralChecker) the
qa_check_outcomes rows are PERSISTED for triggered AND clean AND overridden
outcomes.  This is the proof that the emitter is NOT dead in production — it
actually runs and writes to the state backend.

Wiring under test:
  StructuralChecker.evaluate()
  -> LayerResult (with executed_check_ids populated in metadata)
  -> CheckOutcomeEmitter.emit(accessor=ProjectionAccessor)
  -> FacadeQACheckOutcomesRepository.write()
  -> SQLite qa_check_outcomes table

Also covers the end-to-end:
  ProjectionAccessor.read_projection(QA_CHECK_OUTCOMES)
  -> FacadeQACheckOutcomesRepository.read()
so the read path and write path are both exercised.

AC4 production wiring (overridden outcome via phase.py):
  save_override_record(story_dir, OverrideRecord(check_id=...))
  -> ImplementationPhaseHandler.on_enter (real phase.py code path)
     -> load_override_records(s_dir)
     -> CheckOutcomeEmitter.emit(..., override_records=<loaded>)
     -> FacadeQACheckOutcomesRepository.write()
     -> SQLite qa_check_outcomes row with outcome=overridden
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from agentkit.backend.phase_state_store.models import FlowExecution
from agentkit.backend.pipeline_engine.phase_executor import PhaseSnapshot, PhaseStatus
from agentkit.backend.state_backend.pipeline_runtime_store import save_phase_snapshot
from agentkit.backend.state_backend.story_lifecycle_store import save_story_context
from agentkit.backend.story_context_manager.models import StoryContext
from agentkit.backend.story_context_manager.story_model import ChangeImpact
from agentkit.backend.story_context_manager.types import StoryMode, StoryType, get_profile
from agentkit.backend.telemetry.projection_accessor import ProjectionFilter, ProjectionKind
from agentkit.backend.verify_system.check_outcome_emitter import CheckOutcomeEmitter
from agentkit.backend.verify_system.stage_registry import StageRegistry
from agentkit.backend.verify_system.stage_registry.records import CheckOutcome
from agentkit.backend.verify_system.structural.checks import BuildTestEvidence
from agentkit.backend.verify_system.structural.system_evidence import ChangeEvidence

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.integration

_STORY_ID = "AG3-108"
_PROJECT_KEY = "proj-integration"
_RUN_ID = "run-wiring-001"


@pytest.fixture(autouse=True)
def _sqlite_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
    monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")
    os.environ["AGENTKIT_STATE_BACKEND"] = "sqlite"
    os.environ["AGENTKIT_ALLOW_SQLITE"] = "1"


def _ctx() -> StoryContext:
    return StoryContext(
        project_key=_PROJECT_KEY,
        story_id=_STORY_ID,
        story_type=StoryType.IMPLEMENTATION,
        execution_route=StoryMode.EXPLORATION,
    )


def _flow() -> FlowExecution:
    return FlowExecution(
        project_key=_PROJECT_KEY,
        story_id=_STORY_ID,
        run_id=_RUN_ID,
        flow_id="flow-wiring-001",
        level="story",
        owner="test",
    )


class _GreenTel:
    """Stub telemetry that reports a passing story."""

    def count_events(
        self,
        story_dir: Path,
        *,
        story_id: str,
        event_type: str,
        role: str | None = None,
        project_key: str | None = None,
        run_id: str | None = None,
    ) -> int:
        del story_dir, story_id, project_key, run_id
        return {
            ("review_request", None): 2,
            ("review_compliant", None): 2,
            ("llm_call_complete", "qa_review"): 1,
            ("llm_call_complete", "semantic_review"): 1,
            ("llm_call_complete", "doc_fidelity"): 1,
        }.get((event_type, role), 0)

    def run_scope_resolvable(self, story_dir: Path) -> bool:
        del story_dir
        return True


class _GreenBt:
    """Stub build/test port that reports green CI."""

    def evaluate(self, story_dir: Path) -> BuildTestEvidence | None:
        del story_dir
        return BuildTestEvidence(
            build_ok=True,
            tests_green=True,
            test_file_count=3,
            coverage_report_present=True,
            coverage_meets_threshold=True,
        )


class _GreenEv:
    """Stub change-evidence that reports a compliant story branch."""

    def collect(self, story_dir: Path) -> ChangeEvidence:
        del story_dir
        return ChangeEvidence(
            available=True,
            current_branch=f"story/{_STORY_ID}",
            commit_messages=(f"feat({_STORY_ID}): implement feature",),
            pushed=True,
            secret_files=(),
            changed_files=("feature.py",),
            actual_impact=ChangeImpact("Component"),
        )


def _prepare_story_dir(tmp_path: Path) -> Path:
    """Set up a minimal passing story directory for Layer-1."""
    story_dir = tmp_path / "stories" / _STORY_ID
    story_dir.mkdir(parents=True, exist_ok=True)
    ctx = _ctx()
    save_story_context(story_dir, ctx)
    for phase in get_profile(ctx.story_type).phases:
        if phase == "implementation":
            break
        save_phase_snapshot(
            story_dir,
            PhaseSnapshot(
                story_id=_STORY_ID,
                phase=phase,
                status=PhaseStatus.COMPLETED,
                completed_at=datetime.now(tz=UTC),
                artifacts=[],
                evidence={},
            ),
        )
    (story_dir / "protocol.md").write_text("protocol body " * 10, encoding="utf-8")
    (story_dir / "feature.py").write_text("value = 42\n", encoding="utf-8")
    (story_dir / "worker-manifest.json").write_text(
        json.dumps({
            "story_id": _STORY_ID,
            "status": "DONE",
            "files": ["feature.py"],
            "declared_change_impact": "Component",
        }),
        encoding="utf-8",
    )
    (story_dir / "handover.json").write_text(
        json.dumps({
            "changes_summary": "added feature",
            "increments": [{"description": "f", "commit_sha": "a", "tests_added": []}],
            "assumptions": [],
            "existing_tests": ["tests/test_feature.py::test_x"],
            "risks_for_qa": [],
            "drift_log": [],
            "acceptance_criteria_status": {"AC-1": "ADDRESSED"},
        }),
        encoding="utf-8",
    )
    return story_dir


def test_emitter_wiring_persists_clean_rows_for_passing_layer1(tmp_path: Path) -> None:
    """A passing Layer-1 run produces clean qa_check_outcomes rows via the real wiring.

    AG3-108 AC2 (make-or-break): the CheckOutcomeEmitter is NOT dead in
    production.  After a real StructuralChecker run the executor calls
    CheckOutcomeEmitter.emit(..., projection_accessor=accessor) which persists
    rows to the SQLite qa_check_outcomes table.  We then read them back through
    the PUBLIC ProjectionAccessor.read_projection to confirm end-to-end wiring.
    """
    from agentkit.backend.bootstrap.composition_root import build_projection_accessor
    from agentkit.backend.verify_system.structural.checker import StructuralChecker

    story_dir = _prepare_story_dir(tmp_path)
    ctx = _ctx()
    flow = _flow()
    accessor = build_projection_accessor(story_dir)

    checker = StructuralChecker(
        registry=StageRegistry(),
        telemetry=_GreenTel(),
        build_test_port=_GreenBt(),
        change_evidence_port=_GreenEv(),
    )
    layer_result = checker.evaluate(ctx, story_dir)

    # Validate that executed_check_ids is populated (prerequisite for clean rows).
    assert "executed_check_ids" in layer_result.metadata, (
        "StructuralChecker must populate executed_check_ids in metadata"
    )
    executed = set(layer_result.metadata["executed_check_ids"])  # type: ignore[arg-type]
    assert len(executed) > 0, "executed_check_ids must not be empty"

    # Wire: emit check outcomes via the real emitter + accessor.
    emitter = CheckOutcomeEmitter()
    emitted = emitter.emit(
        flow,  # type: ignore[arg-type]
        layer_result,
        attempt_no=1,
        projection_accessor=accessor,
    )

    # At least some rows emitted.
    assert len(emitted) > 0, "At least one outcome row must be emitted"

    # Read back via the PUBLIC accessor.
    rows = accessor.read_projection(
        ProjectionKind.QA_CHECK_OUTCOMES,
        ProjectionFilter(
            project_key=_PROJECT_KEY,
            run_id=_RUN_ID,
        ),
    )
    # The DB upserts on PK (project_key, run_id, stage_id, attempt_no, check_id),
    # so duplicate check_ids in executed_check_ids (e.g. "phase_snapshots" per phase)
    # produce one row in the DB per unique PK. Rows persisted >= 1.
    assert len(rows) > 0, "At least one outcome row must be persisted"
    assert len(emitted) > 0, "At least one outcome row must be emitted"

    # All rows for a passing Layer-1 must be clean.
    assert layer_result.passed, "Test precondition: layer must pass for this test"
    for row in rows:
        assert row.outcome is CheckOutcome.CLEAN, (
            f"Expected CLEAN for {row.check_id!r}; got {row.outcome}"
        )
        assert row.project_key == _PROJECT_KEY
        assert row.run_id == _RUN_ID
        assert row.attempt_no == 1
        assert row.check_id, "check_id must be non-empty"


def test_emitter_wiring_persists_triggered_row_for_failed_check(tmp_path: Path) -> None:
    """A failing Layer-1 check produces a triggered row alongside clean rows.

    Proves both triggered and clean rows are emitted in one shot when some
    checks pass and one fails.  The emitter must NOT drop PASS checks.
    """
    from agentkit.backend.bootstrap.composition_root import build_projection_accessor
    from agentkit.backend.verify_system.structural.checker import StructuralChecker

    story_dir = _prepare_story_dir(tmp_path)
    ctx = _ctx()
    flow = _flow()
    accessor = build_projection_accessor(story_dir)

    # Break protocol.md so artifact.protocol fires (TRIGGERED).
    (story_dir / "protocol.md").unlink()

    checker = StructuralChecker(
        registry=StageRegistry(),
        telemetry=_GreenTel(),
        build_test_port=_GreenBt(),
        change_evidence_port=_GreenEv(),
    )
    layer_result = checker.evaluate(ctx, story_dir)

    assert not layer_result.passed, "Test precondition: layer must fail"
    assert "executed_check_ids" in layer_result.metadata

    emitter = CheckOutcomeEmitter()
    emitter.emit(
        flow,  # type: ignore[arg-type]
        layer_result,
        attempt_no=1,
        projection_accessor=accessor,
    )

    rows = accessor.read_projection(
        ProjectionKind.QA_CHECK_OUTCOMES,
        ProjectionFilter(project_key=_PROJECT_KEY, run_id=_RUN_ID),
    )
    assert len(rows) > 0

    by_outcome: dict[str, list[str]] = {}
    for row in rows:
        by_outcome.setdefault(row.outcome.value, []).append(row.check_id)

    # Must have at least one triggered row (artifact.protocol failed).
    assert "triggered" in by_outcome, (
        f"Expected triggered rows; got outcomes: {set(by_outcome)}"
    )
    # Must also have clean rows (PASS checks not discarded).
    assert "clean" in by_outcome, (
        "PASS checks must produce clean rows (core AC2 invariant)"
    )


def test_emitter_wiring_persists_overridden_row(tmp_path: Path) -> None:
    """An override matching a check_id produces an overridden outcome row."""
    from agentkit.backend.bootstrap.composition_root import build_projection_accessor
    from agentkit.backend.core_types.override import OverrideType
    from agentkit.backend.phase_state_store.models import OverrideRecord
    from agentkit.backend.verify_system.structural.checker import StructuralChecker

    story_dir = _prepare_story_dir(tmp_path)
    ctx = _ctx()
    flow = _flow()
    accessor = build_projection_accessor(story_dir)

    # Break protocol.md so artifact.protocol fires.
    (story_dir / "protocol.md").unlink()

    checker = StructuralChecker(
        registry=StageRegistry(),
        telemetry=_GreenTel(),
        build_test_port=_GreenBt(),
        change_evidence_port=_GreenEv(),
    )
    layer_result = checker.evaluate(ctx, story_dir)

    # Build an OverrideRecord suppressing the artifact.protocol check.
    override = OverrideRecord(
        override_id="ovr-wiring-001",
        project_key=_PROJECT_KEY,
        story_id=_STORY_ID,
        run_id=_RUN_ID,
        flow_id="flow-wiring-001",
        target_node_id=None,
        override_type=OverrideType.FORCE_GATE_PASS,
        actor_type="orchestrator",
        actor_id="test",
        reason="integration test override",
        created_at=datetime.now(tz=UTC),
        check_id="artifact.protocol",
    )

    emitter = CheckOutcomeEmitter()
    emitter.emit(
        flow,  # type: ignore[arg-type]
        layer_result,
        attempt_no=1,
        override_records=[override],
        projection_accessor=accessor,
    )

    rows = accessor.read_projection(
        ProjectionKind.QA_CHECK_OUTCOMES,
        ProjectionFilter(project_key=_PROJECT_KEY, run_id=_RUN_ID),
    )
    overridden = [r for r in rows if r.outcome is CheckOutcome.OVERRIDDEN]
    assert len(overridden) == 1, f"Expected 1 overridden row; got {overridden!r}"
    assert overridden[0].check_id == "artifact.protocol"
    assert overridden[0].override_id == "ovr-wiring-001"


# ---------------------------------------------------------------------------
# AC4: overridden outcome via the REAL implementation-phase production wiring
# ---------------------------------------------------------------------------
# The tests above call CheckOutcomeEmitter.emit() DIRECTLY with hand-built
# override_records=[...] — that only proves the emitter logic, not the
# phase.py load->pass wiring.  The test below drives the REAL
# ImplementationPhaseHandler.on_enter path (the code in phase.py lines
# ~294-310 after the AC4 fix):
#
#   load_override_records(s_dir)          <- new, loads from store
#   -> _emitter.emit(..., override_records=<loaded>)  <- new param
#   -> FacadeQACheckOutcomesRepository.write()
#   -> SQLite qa_check_outcomes row with outcome=overridden
#
# This is the exact gap Codex flagged in round-1 review.
# ---------------------------------------------------------------------------

_STORY_ID_AC4 = "AG3-10804"
_PROJECT_KEY_AC4 = "proj-ac4"
_RUN_ID_AC4 = "run-ac4-001"
_OVERRIDE_CHECK_ID = "artifact.protocol"
_OVERRIDE_ID = "ovr-ac4-001"


def _ctx_ac4() -> StoryContext:
    return StoryContext(
        project_key=_PROJECT_KEY_AC4,
        story_id=_STORY_ID_AC4,
        story_type=StoryType.IMPLEMENTATION,
        execution_route=StoryMode.EXPLORATION,
    )


def _flow_ac4() -> FlowExecution:
    return FlowExecution(
        project_key=_PROJECT_KEY_AC4,
        story_id=_STORY_ID_AC4,
        run_id=_RUN_ID_AC4,
        flow_id="flow-ac4-001",
        level="story",
        owner="test",
    )


def _prepare_story_dir_ac4(tmp_path: Path) -> Path:
    """Minimal story dir for AC4: FlowExecution + OverrideRecord persisted."""
    from agentkit.backend.state_backend.pipeline_runtime_store import (
        save_flow_execution,
        save_override_record,
    )

    story_dir = tmp_path / "stories" / _STORY_ID_AC4
    story_dir.mkdir(parents=True, exist_ok=True)
    ctx = _ctx_ac4()
    save_story_context(story_dir, ctx)
    # Persist phase snapshots for all phases before implementation.
    for phase in get_profile(ctx.story_type).phases:
        if phase == "implementation":
            break
        save_phase_snapshot(
            story_dir,
            PhaseSnapshot(
                story_id=_STORY_ID_AC4,
                phase=phase,
                status=PhaseStatus.COMPLETED,
                completed_at=datetime.now(tz=UTC),
                artifacts=[],
                evidence={},
            ),
        )
    # Persist FlowExecution (required by phase.py load_flow_execution check).
    save_flow_execution(story_dir, _flow_ac4())
    # Persist an OverrideRecord suppressing the artifact.protocol check.
    from agentkit.backend.core_types.override import OverrideType
    from agentkit.backend.phase_state_store.models import OverrideRecord

    override = OverrideRecord(
        override_id=_OVERRIDE_ID,
        project_key=_PROJECT_KEY_AC4,
        story_id=_STORY_ID_AC4,
        run_id=_RUN_ID_AC4,
        flow_id="flow-ac4-001",
        target_node_id=None,
        override_type=OverrideType.FORCE_GATE_PASS,
        actor_type="orchestrator",
        actor_id="test",
        reason="AC4 production-wiring integration test",
        created_at=datetime.now(tz=UTC),
        check_id=_OVERRIDE_CHECK_ID,
    )
    save_override_record(story_dir, override)
    # Write minimal worker artefacts so the handler does not short-circuit.
    (story_dir / "protocol.md").write_text("protocol body " * 10, encoding="utf-8")
    (story_dir / "feature.py").write_text("value = 42\n", encoding="utf-8")
    # Worker-manifest must satisfy the WorkerManifestStatus schema (extra="forbid",
    # required fields: story_id, run_id, status, completed_at). COMPLETED status
    # does not require blocker fields.
    (story_dir / "worker-manifest.json").write_text(
        json.dumps({
            "story_id": _STORY_ID_AC4,
            "run_id": _RUN_ID_AC4,
            "status": "completed",
            "completed_at": "2026-06-13T00:00:00+00:00",
            "files_changed": ["feature.py"],
        }),
        encoding="utf-8",
    )
    (story_dir / "handover.json").write_text(
        json.dumps({
            "changes_summary": "added feature",
            "increments": [{"description": "f", "commit_sha": "a", "tests_added": []}],
            "assumptions": [],
            "existing_tests": ["tests/test_feature.py::test_x"],
            "risks_for_qa": [],
            "drift_log": [],
            "acceptance_criteria_status": {"AC-1": "ADDRESSED"},
        }),
        encoding="utf-8",
    )
    return story_dir


class _PassVerifySystemWithOverridableCheck:
    """VerifySystem stub that returns PASS with a controlled LayerResult.

    The LayerResult exposes ``executed_check_ids`` including the check that
    should be overridden (_OVERRIDE_CHECK_ID).  The check has no finding
    (not triggered), so without an override it would be ``clean``; with the
    persisted OverrideRecord loaded by phase.py the outcome is ``overridden``.

    This double proves that the override is loaded from the store (not
    injected by the test) and threaded through the real emit() call.
    """

    @property
    def stage_registry(self) -> StageRegistry:
        """Return an empty registry (no FC-derived stages in this test double).

        AG3-078 ERROR 1: phase.py calls verify_system.stage_registry.stages to
        build the per-check origin_check_ref mapping. Test double must satisfy
        this interface with an empty tuple so all check_ids get NULL
        check_proposal_ref (no FC-derived checks in this stub's layer result).
        """
        return StageRegistry(stages=())

    def run_qa_subflow(
        self,
        ctx: object,
        story_id: str,
        qa_context: object,
        target: object,
        *,
        previous_findings: tuple[object, ...] = (),
    ) -> object:
        from agentkit.backend.core_types import PolicyVerdict
        from agentkit.backend.core_types.qa_artifact_names import ALL_QA_ARTIFACT_FILES
        from agentkit.backend.verify_system.contract import QaSubflowOutcome
        from agentkit.backend.verify_system.policy_engine.engine import PolicyEngine
        from agentkit.backend.verify_system.protocols import LayerResult

        del story_id, qa_context, target, previous_findings

        # A clean layer result that lists the overridable check in executed_check_ids
        # but produces NO finding for it (so without override -> clean; with -> overridden).
        layer_result = LayerResult(
            layer="structural",
            passed=True,
            findings=(),
            metadata={
                "executed_check_ids": [_OVERRIDE_CHECK_ID, "artifact.worker_manifest"],
            },
        )
        decision = PolicyEngine().decide([layer_result])
        attempt = getattr(ctx, "attempt", 1)
        return QaSubflowOutcome(
            verdict=PolicyVerdict.PASS,
            decision=decision,
            artifact_refs=ALL_QA_ARTIFACT_FILES,
            attempt_nr=attempt,
            qa_cycle_round=attempt,
            feedback=None,
            escalated=False,
            qa_cycle_id=f"{attempt:012x}",
            evidence_epoch=datetime(2026, 6, 13, tzinfo=UTC),
            evidence_fingerprint="a" * 64,
        )


def test_phase_wiring_emits_overridden_outcome_via_production_path(
    tmp_path: Path,
) -> None:
    """AC4: overridden outcome reaches qa_check_outcomes via the REAL phase.py path.

    AG3-108 AC4 (make-or-break): proves that ``ImplementationPhaseHandler.on_enter``
    loads the persisted OverrideRecords and passes them into the CheckOutcomeEmitter
    so the emitter can mark ``overridden`` for a matching check_id.

    Production wiring under test (phase.py ~294-310 after the AC4 fix):
      load_override_records(s_dir)
      -> _emitter.emit(flow, layer_result, ..., override_records=<loaded>, accessor=accessor)
      -> FacadeQACheckOutcomesRepository.write()
      -> SQLite qa_check_outcomes row outcome=overridden

    This is NOT a direct CheckOutcomeEmitter.emit() call with hand-built
    override_records — it is the real phase.py code path that Codex flagged
    as the gap in round-1 review.
    """
    from agentkit.backend.bootstrap.composition_root import build_projection_accessor
    from agentkit.backend.implementation.phase import ImplementationConfig, ImplementationPhaseHandler
    from agentkit.backend.pipeline_engine.phase_envelope.store import PhaseEnvelopeStore
    from agentkit.backend.state_backend.persistence_test_support import reset_backend_cache_for_tests

    reset_backend_cache_for_tests()
    story_dir = _prepare_story_dir_ac4(tmp_path)

    config = ImplementationConfig(
        story_dir=story_dir,
        verify_system=_PassVerifySystemWithOverridableCheck(),  # type: ignore[arg-type]
    )
    handler = ImplementationPhaseHandler(config)

    from tests.phase_state_factory import make_phase_state

    state = make_phase_state(
        story_id=_STORY_ID_AC4,
        phase="implementation",
        status=PhaseStatus.IN_PROGRESS,
    )
    envelope = PhaseEnvelopeStore.make_fresh_envelope(state)

    result = handler.on_enter(_ctx_ac4(), envelope)

    # The stub returns PASS, so the handler must have COMPLETED.
    assert result.status == PhaseStatus.COMPLETED, (
        f"Expected COMPLETED from PASS outcome; got {result.status!r}. "
        f"errors={result.errors!r}"
    )

    # Read back qa_check_outcomes via the PUBLIC accessor.
    accessor = build_projection_accessor(story_dir)
    rows = accessor.read_projection(
        ProjectionKind.QA_CHECK_OUTCOMES,
        ProjectionFilter(
            project_key=_PROJECT_KEY_AC4,
            run_id=_RUN_ID_AC4,
        ),
    )
    assert len(rows) > 0, "At least one qa_check_outcomes row must be persisted"

    overridden_rows = [r for r in rows if r.outcome is CheckOutcome.OVERRIDDEN]
    assert len(overridden_rows) == 1, (
        f"Expected exactly 1 overridden row for check_id={_OVERRIDE_CHECK_ID!r}; "
        f"got {overridden_rows!r}. All rows: {[(r.check_id, r.outcome) for r in rows]!r}"
    )
    assert overridden_rows[0].check_id == _OVERRIDE_CHECK_ID, (
        f"overridden row check_id mismatch: {overridden_rows[0].check_id!r}"
    )
    assert overridden_rows[0].override_id == _OVERRIDE_ID, (
        f"overridden row override_id mismatch: {overridden_rows[0].override_id!r}"
    )

    # The other check should be clean (not triggered, not overridden).
    clean_rows = [r for r in rows if r.outcome is CheckOutcome.CLEAN]
    assert any(r.check_id == "artifact.worker_manifest" for r in clean_rows), (
        "artifact.worker_manifest must be clean (not overridden, not triggered); "
        f"clean rows: {[(r.check_id, r.outcome) for r in clean_rows]!r}"
    )

    reset_backend_cache_for_tests()
