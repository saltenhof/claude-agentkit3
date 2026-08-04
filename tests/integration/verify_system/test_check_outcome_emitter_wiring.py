"""Integration: CheckOutcomeEmitter is wired into the real QA layer flow (AG3-108).

Proves AC2 of story AG3-108: after a real Layer-1 run (StructuralChecker) the
qa_check_outcomes rows are PERSISTED for triggered AND clean AND overridden
outcomes.  This is the proof that the emitter is NOT dead in production — it
actually runs and writes to the state backend.

Wiring under test:
  StructuralChecker.evaluate()
  -> LayerResult (with executed_check_ids populated in metadata)
  -> CheckOutcomeEmitter.build_batch()
  -> ProjectionAccessor.record_qa_layer_artifacts()
  -> SQLite qa_check_outcomes table

Also covers the end-to-end:
  ProjectionAccessor.read_projection(QA_CHECK_OUTCOMES)
  -> FacadeQACheckOutcomesRepository.read()
so the read path and write path are both exercised.

AC4 production wiring (overridden outcome via phase.py):
  save_override_record(story_dir, OverrideRecord(check_id=...))
  -> ImplementationPhaseHandler.on_enter (real phase.py code path)
     -> load_override_records(s_dir)
     -> CheckOutcomeEmitter.build_batch(..., override_records=<loaded>)
     -> ProjectionAccessor.record_qa_layer_artifacts()
     -> SQLite qa_check_outcomes row with outcome=overridden
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from tests.qa_artifact_support import write_qa_layer_envelopes

from agentkit.backend.core_types import PolicyVerdict, QaContext
from agentkit.backend.phase_state_store.models import FlowExecution
from agentkit.backend.pipeline_engine.phase_executor import PhaseSnapshot, PhaseStatus
from agentkit.backend.state_backend.pipeline_runtime_store import (
    save_flow_execution,
    save_phase_snapshot,
)
from agentkit.backend.state_backend.story_lifecycle_store import save_story_context
from agentkit.backend.story_context_manager.models import StoryContext
from agentkit.backend.story_context_manager.story_model import ChangeImpact
from agentkit.backend.story_context_manager.types import (
    ImplementationContract,
    StoryMode,
    StoryType,
    get_profile,
)
from agentkit.backend.telemetry.projection_accessor import ProjectionFilter, ProjectionKind
from agentkit.backend.verify_system.check_outcome_emitter import CheckOutcomeEmitter
from agentkit.backend.verify_system.contract import QaSubflowOutcome, VerifyContextBundle
from agentkit.backend.verify_system.stage_registry import StageRegistry
from agentkit.backend.verify_system.stage_registry.records import CheckOutcome
from agentkit.backend.verify_system.structural.checks import BuildTestEvidence
from agentkit.backend.verify_system.structural.system_evidence import ChangeEvidence
from integration.implementation_evidence_support import (
    ReadyEvidencePreparationCoordinator,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from agentkit.backend.artifacts import ArtifactReference
    from agentkit.backend.phase_state_store.models import OverrideRecord
    from agentkit.backend.telemetry.projection_accessor import ProjectionAccessor
    from agentkit.backend.verify_system.protocols import LayerResult
    from agentkit.backend.verify_system.stage_registry.records import (
        QACheckOutcomeRecord,
    )

pytestmark = pytest.mark.integration

_STORY_ID = "AG3-108"
_PROJECT_KEY = "proj-integration"
_RUN_ID = "run-wiring-001"


@pytest.fixture(autouse=True)
def _sqlite_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    from agentkit.backend.state_backend.persistence_test_support import (
        reset_backend_cache_for_tests,
    )

    monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
    monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")
    reset_backend_cache_for_tests()
    try:
        yield
    finally:
        reset_backend_cache_for_tests()


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


def _persist_qa_batch(
    story_dir: Path,
    flow: FlowExecution,
    layer_result: LayerResult,
    *,
    accessor: ProjectionAccessor,
    stage_registry: StageRegistry,
    override_records: list[OverrideRecord] | None = None,
) -> tuple[QACheckOutcomeRecord, ...]:
    """Build outcomes and persist all three QA projections in one batch."""
    outcomes = CheckOutcomeEmitter().build_batch(
        flow,
        (layer_result,),
        attempt_no=1,
        override_records=override_records,
        stage_registry=stage_registry,
    )
    artifact_references = write_qa_layer_envelopes(
        story_dir,
        layer_results=(layer_result,),
        stage_registry=stage_registry,
        attempt_nr=1,
    )
    layer_result = replace(
        layer_result,
        artifact_reference=artifact_references[layer_result.layer],
    )
    accessor.record_qa_layer_artifacts(
        story_dir,
        layer_results=(layer_result,),
        check_outcomes=outcomes,
        stage_registry=stage_registry,
        attempt_nr=1,
        owner_session_id="sqlite-test",
        expected_ownership_epoch=1,
        projection_dir=story_dir,
    )
    return outcomes


def _assert_structural_counts_match_persisted_rows(
    accessor: ProjectionAccessor,
) -> None:
    """Assert that stage counts describe the persisted outcome/finding rows."""
    projection_filter = ProjectionFilter(
        project_key=_PROJECT_KEY,
        run_id=_RUN_ID,
    )
    outcomes = accessor.read_projection(
        ProjectionKind.QA_CHECK_OUTCOMES,
        projection_filter,
    )
    stage_results = accessor.read_projection(
        ProjectionKind.QA_STAGE_RESULTS,
        projection_filter,
    )
    findings = accessor.read_projection(
        ProjectionKind.QA_FINDINGS,
        projection_filter,
    )
    structural = next(row for row in stage_results if row.stage_id == "structural")
    structural_findings = [row for row in findings if row.stage_id == "structural"]

    assert structural.total_checks == len(outcomes)
    assert structural.failed_checks == sum(
        1 for finding in structural_findings if finding.blocking
    )
    assert structural.warning_checks == sum(
        1 for finding in structural_findings if not finding.blocking
    )
    assert {
        row.check_id for row in outcomes if row.outcome is not CheckOutcome.CLEAN
    } == {finding.check_id for finding in structural_findings}


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
    save_flow_execution(story_dir, _flow())
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

    After a real StructuralChecker run, records are built and passed with the
    stage and finding projections to the productive atomic batch. They are then
    read back through the public accessor.
    """
    from agentkit.backend.bootstrap.composition_root import build_projection_accessor
    from agentkit.backend.verify_system.structural.checker import StructuralChecker

    story_dir = _prepare_story_dir(tmp_path)
    ctx = _ctx()
    flow = _flow()
    accessor = build_projection_accessor(story_dir)

    stage_registry = StageRegistry()
    checker = StructuralChecker(
        registry=stage_registry,
        telemetry=_GreenTel(),
        build_test_port=_GreenBt(),
        change_evidence_port=_GreenEv(),
    )
    layer_result = checker.evaluate(ctx, story_dir)

    # Validate that executed_check_ids is populated (prerequisite for clean rows).
    assert "executed_check_ids" in layer_result.metadata, (
        "StructuralChecker must populate executed_check_ids in metadata"
    )
    executed = tuple(layer_result.metadata["executed_check_ids"])  # type: ignore[arg-type]
    assert executed, "executed_check_ids must not be empty"
    assert len(executed) == len(set(executed))
    assert "phase_snapshots.setup" in executed
    assert "phase_snapshots.exploration" in executed

    emitted = _persist_qa_batch(
        story_dir,
        flow,
        layer_result,
        accessor=accessor,
        stage_registry=stage_registry,
    )

    assert len(emitted) == len(executed)

    # Read back via the PUBLIC accessor.
    rows = accessor.read_projection(
        ProjectionKind.QA_CHECK_OUTCOMES,
        ProjectionFilter(
            project_key=_PROJECT_KEY,
            run_id=_RUN_ID,
        ),
    )
    assert len(rows) == len(executed)
    stage_rows = accessor.read_projection(
        ProjectionKind.QA_STAGE_RESULTS,
        ProjectionFilter(project_key=_PROJECT_KEY, run_id=_RUN_ID),
    )
    structural_row = next(row for row in stage_rows if row.stage_id == "structural")
    assert structural_row.total_checks == len(rows)
    assert structural_row.failed_checks == 0
    assert structural_row.warning_checks == 0
    _assert_structural_counts_match_persisted_rows(accessor)

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

    stage_registry = StageRegistry()
    checker = StructuralChecker(
        registry=stage_registry,
        telemetry=_GreenTel(),
        build_test_port=_GreenBt(),
        change_evidence_port=_GreenEv(),
    )
    layer_result = checker.evaluate(ctx, story_dir)

    assert not layer_result.passed, "Test precondition: layer must fail"
    assert "executed_check_ids" in layer_result.metadata

    _persist_qa_batch(
        story_dir,
        flow,
        layer_result,
        accessor=accessor,
        stage_registry=stage_registry,
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
    _assert_structural_counts_match_persisted_rows(accessor)


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

    stage_registry = StageRegistry()
    checker = StructuralChecker(
        registry=stage_registry,
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

    _persist_qa_batch(
        story_dir,
        flow,
        layer_result,
        override_records=[override],
        accessor=accessor,
        stage_registry=stage_registry,
    )

    rows = accessor.read_projection(
        ProjectionKind.QA_CHECK_OUTCOMES,
        ProjectionFilter(project_key=_PROJECT_KEY, run_id=_RUN_ID),
    )
    overridden = [r for r in rows if r.outcome is CheckOutcome.OVERRIDDEN]
    assert len(overridden) == 1, f"Expected 1 overridden row; got {overridden!r}"
    assert overridden[0].check_id == "artifact.protocol"
    assert overridden[0].override_id == "ovr-wiring-001"
    _assert_structural_counts_match_persisted_rows(accessor)


# ---------------------------------------------------------------------------
# AC4: overridden outcome via the REAL implementation-phase production wiring
# ---------------------------------------------------------------------------
# The tests above use the atomic batch with hand-built override records. They
# prove the batch contract, not the phase.py load->pass wiring. The test below
# phase.py load->pass wiring.  The test below drives the REAL
# ImplementationPhaseHandler.on_enter path (the code in phase.py lines
# ~294-310 after the AC4 fix):
#
#   load_override_records(s_dir)          <- new, loads from store
#   -> _emitter.build_batch(..., override_records=<loaded>)
#   -> ProjectionAccessor.record_qa_layer_artifacts()
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
    injected by the test) and threaded through the real batch builder.
    """

    @property
    def stage_registry(self) -> StageRegistry:
        """Return registry evidence for the test's native check IDs."""
        return StageRegistry()

    def run_qa_subflow(
        self,
        ctx: VerifyContextBundle,
        story_id: str,
        qa_context: QaContext,
        target: ArtifactReference,
        *,
        previous_findings: tuple[object, ...] = (),
    ) -> QaSubflowOutcome:
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
        references = write_qa_layer_envelopes(
            ctx.story_dir,
            layer_results=(layer_result,),
            stage_registry=self.stage_registry,
            attempt_nr=ctx.attempt,
        )
        layer_result = replace(
            layer_result,
            artifact_reference=references[layer_result.layer],
        )
        decision = PolicyEngine().decide(
            [layer_result],
            story_type=StoryType.IMPLEMENTATION,
            traversed_layers=frozenset({4}),
        )
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
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC4: overridden outcome reaches qa_check_outcomes via the REAL phase.py path.

    AG3-108 AC4 (make-or-break): proves that ``ImplementationPhaseHandler.on_enter``
    loads the persisted OverrideRecords and passes them into the CheckOutcomeEmitter
    so the emitter can mark ``overridden`` for a matching check_id.

    Production wiring under test (phase.py ~294-310 after the AC4 fix):
      load_override_records(s_dir)
      -> _emitter.build_batch(flow, layer_results, ..., override_records=<loaded>)
      -> ProjectionAccessor.record_qa_layer_artifacts()
      -> SQLite qa_check_outcomes row outcome=overridden

    This is the real phase.py batch path, including the persisted override load,
    rather than a direct outcome-builder test. It covers the gap Codex flagged
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
        evidence_preparation=ReadyEvidencePreparationCoordinator(),  # type: ignore[arg-type]
    )
    monkeypatch.setattr(
        "agentkit.backend.implementation.phase._verify_evidence_inputs",
        lambda *args, **kwargs: object(),
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


class _RealFailingStabilityGateVerifySystem:
    """Return a real stability-gate result to the productive phase batch."""

    def __init__(self) -> None:
        self._stage_registry = StageRegistry()

    @property
    def stage_registry(self) -> StageRegistry:
        return self._stage_registry

    def run_qa_subflow(
        self,
        ctx: object,
        story_id: str,
        qa_context: object,
        target: object,
        *,
        previous_findings: tuple[object, ...] = (),
    ) -> object:
        from agentkit.backend.core_types.qa_artifact_names import ALL_QA_ARTIFACT_FILES
        from agentkit.backend.integration_stabilization.stability_gate_producer import (
            produce_stability_gate_layer_result,
        )
        from agentkit.backend.verify_system.policy_engine.engine import PolicyEngine

        del qa_context, target, previous_findings
        layer_result = produce_stability_gate_layer_result(
            story_dir=ctx.story_dir,
            run_id=ctx.run_id,
            touched_paths=("feature.py",),
            story_id=story_id,
            project_key=_PROJECT_KEY_AC4,
        )
        references = write_qa_layer_envelopes(
            ctx.story_dir,
            layer_results=(layer_result,),
            stage_registry=self._stage_registry,
            attempt_nr=ctx.attempt,
        )
        layer_result = replace(
            layer_result,
            artifact_reference=references[layer_result.layer],
        )
        decision = PolicyEngine(stage_registry=self._stage_registry).decide(
            [layer_result],
            story_type=StoryType.IMPLEMENTATION,
            traversed_layers=frozenset({4}),
            implementation_contract=ImplementationContract.INTEGRATION_STABILIZATION,
        )
        return QaSubflowOutcome(
            verdict=PolicyVerdict.FAIL,
            decision=decision,
            artifact_refs=ALL_QA_ARTIFACT_FILES,
            attempt_nr=ctx.attempt,
            qa_cycle_round=ctx.attempt,
            feedback=None,
            escalated=True,
            qa_cycle_id=f"{ctx.attempt:012x}",
            evidence_epoch=datetime(2026, 8, 4, tzinfo=UTC),
            evidence_fingerprint="b" * 64,
        )


def test_real_stability_gate_failure_reaches_implementation_phase_atomic_batch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """G1: real producer subchecks persist through phase.py as one QA batch."""
    from tests.phase_state_factory import make_phase_state

    from agentkit.backend.bootstrap.composition_root import build_projection_accessor
    from agentkit.backend.implementation.phase import ImplementationConfig, ImplementationPhaseHandler
    from agentkit.backend.integration_stabilization.models import (
        IntegrationScopeManifest,
        ManifestApprovalRecord,
        StabilizationBudgetCaps,
    )
    from agentkit.backend.integration_stabilization.state import (
        save_integration_manifest,
        save_manifest_approval,
    )
    from agentkit.backend.pipeline_engine.phase_envelope.store import PhaseEnvelopeStore
    from agentkit.backend.state_backend.persistence_test_support import reset_backend_cache_for_tests

    reset_backend_cache_for_tests()
    story_dir = _prepare_story_dir_ac4(tmp_path)
    story_context = _ctx_ac4().model_copy(
        update={
            "implementation_contract": ImplementationContract.INTEGRATION_STABILIZATION,
        }
    )
    save_story_context(story_dir, story_context)
    manifest = IntegrationScopeManifest(
        version=1,
        project_key=_PROJECT_KEY_AC4,
        story_id=_STORY_ID_AC4,
        implementation_contract="integration_stabilization",
        target_seams=("feature.py",),
        allowed_repos_paths=("feature.py",),
        integration_targets=("required-live-target",),
        allowed_contract_changes=(),
        stabilization_budget=StabilizationBudgetCaps(
            max_loops=3,
            max_new_surfaces=2,
            max_contract_changes=1,
            max_regressions_per_cycle=1,
        ),
    )
    save_integration_manifest(story_dir, manifest)
    save_manifest_approval(
        story_dir,
        ManifestApprovalRecord(
            project_key=_PROJECT_KEY_AC4,
            story_id=_STORY_ID_AC4,
            run_id=_RUN_ID_AC4,
            manifest_version=manifest.version,
            manifest_hash=manifest.content_hash,
        ),
    )
    monkeypatch.setattr(
        "agentkit.backend.implementation.phase._verify_evidence_inputs",
        lambda *args, **kwargs: object(),
    )
    handler = ImplementationPhaseHandler(
        ImplementationConfig(
            story_dir=story_dir,
            verify_system=_RealFailingStabilityGateVerifySystem(),  # type: ignore[arg-type]
            evidence_preparation=ReadyEvidencePreparationCoordinator(),  # type: ignore[arg-type]
        )
    )
    state = make_phase_state(
        story_id=_STORY_ID_AC4,
        phase="implementation",
        status=PhaseStatus.IN_PROGRESS,
    )

    result = handler.on_enter(
        story_context,
        PhaseEnvelopeStore.make_fresh_envelope(state),
    )

    assert result.status is PhaseStatus.ESCALATED
    rows = build_projection_accessor(story_dir).read_projection(
        ProjectionKind.QA_CHECK_OUTCOMES,
        ProjectionFilter(project_key=_PROJECT_KEY_AC4, run_id=_RUN_ID_AC4),
    )
    by_check = {row.check_id: row.outcome for row in rows}
    assert by_check["integration.integration_target_matrix_passed"] is CheckOutcome.TRIGGERED
    assert by_check["stability_gate"] is CheckOutcome.TRIGGERED
    assert by_check["integration.manifest_approval_required"] is CheckOutcome.CLEAN
    assert by_check["integration.binding_integrity"] is CheckOutcome.CLEAN

    reset_backend_cache_for_tests()
