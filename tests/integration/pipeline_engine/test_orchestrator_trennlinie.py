"""Integration: orchestrator-trennlinie -- QA-FAIL spawns a remediation worker.

FK-20 §20.5.1 / AG3-044 §2.1.7: the ImplementationPhaseHandler runs NO inline
``while True`` remediation loop. On a QA-subflow FAIL below the round ceiling it
returns ``IN_PROGRESS`` with ``agents_to_spawn=[remediation_worker]`` (subflow-
internal, no phase change); the engine persists that and re-yields so the
orchestrator spawns the worker.
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from agentkit.core_types import (
    PolicyVerdict,
    SpawnKind,
    SpawnReason,
    SpawnRequest,
)
from agentkit.core_types.qa_artifact_names import ALL_QA_ARTIFACT_FILES
from agentkit.implementation.phase import (
    ImplementationConfig,
    ImplementationPhaseHandler,
)
from agentkit.phase_state_store.models import FlowExecution
from agentkit.pipeline_engine.engine import PipelineEngine
from agentkit.pipeline_engine.lifecycle import HandlerResult, PhaseHandlerRegistry
from agentkit.pipeline_engine.phase_envelope.store import PhaseEnvelopeStore
from agentkit.process.language.definitions import IMPLEMENTATION_WORKFLOW
from agentkit.state_backend.config import ALLOW_SQLITE_ENV, STATE_BACKEND_ENV
from agentkit.state_backend.store import (
    read_phase_state_record,
    reset_backend_cache_for_tests,
    save_flow_execution,
    save_story_context,
)
from agentkit.story_context_manager.models import (
    PhaseState,
    PhaseStatus,
    QaCycleStatus,
    StoryContext,
)
from agentkit.story_context_manager.types import StoryMode, StoryType
from agentkit.verify_system.contract import QaSubflowOutcome
from agentkit.verify_system.policy_engine.engine import PolicyEngine
from agentkit.verify_system.protocols import (
    Finding,
    LayerResult,
    Severity,
    TrustClass,
)
from agentkit.verify_system.remediation.feedback import build_feedback

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

    from agentkit.pipeline_engine.phase_envelope.envelope import PhaseEnvelope
    from agentkit.verify_system.contract import VerifyContextBundle


@pytest.fixture(autouse=True)
def _sqlite_backend(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    monkeypatch.setenv(STATE_BACKEND_ENV, "sqlite")
    monkeypatch.setenv(ALLOW_SQLITE_ENV, "1")
    reset_backend_cache_for_tests()
    yield
    reset_backend_cache_for_tests()


def _fail_outcome(attempt_nr: int) -> QaSubflowOutcome:
    """A FAIL outcome that is NOT escalated (round below the ceiling)."""
    blocking = LayerResult(
        layer="structural",
        passed=False,
        findings=(
            Finding(
                layer="structural",
                check="context_exists",
                severity=Severity.BLOCKING,
                message="missing",
                trust_class=TrustClass.SYSTEM,
            ),
        ),
    )
    decision = PolicyEngine().decide([blocking])
    feedback = build_feedback(decision, "AG3-044", attempt_nr)
    return QaSubflowOutcome(
        verdict=PolicyVerdict.FAIL,
        decision=decision,
        artifact_refs=ALL_QA_ARTIFACT_FILES,
        attempt_nr=attempt_nr,
        qa_cycle_round=attempt_nr,
        feedback=feedback,
        escalated=False,
        qa_cycle_id=f"{attempt_nr:012x}",
        evidence_epoch=datetime(2026, 6, 7, tzinfo=UTC),
        evidence_fingerprint="f" * 64,
    )


class _FailVerifySystem:
    """VerifySystem double returning a non-escalated FAIL (CONTINUE_REMEDIATION)."""

    def run_qa_subflow(
        self,
        ctx: VerifyContextBundle,
        story_id: str,
        qa_context: object,
        target: object,
        *,
        previous_findings: tuple[object, ...] = (),
    ) -> QaSubflowOutcome:
        del story_id, qa_context, target, previous_findings
        return _fail_outcome(ctx.attempt)


def _ctx() -> StoryContext:
    return StoryContext(
        project_key="test-project",
        story_id="AG3-044",
        story_type=StoryType.IMPLEMENTATION,
        execution_route=StoryMode.EXECUTION,
    )


def _story_dir(tmp_path: Path) -> Path:
    story_dir = tmp_path / "stories" / "AG3-044"
    story_dir.mkdir(parents=True)
    save_story_context(story_dir, _ctx())
    save_flow_execution(
        story_dir,
        FlowExecution(
            project_key="test-project",
            story_id="AG3-044",
            run_id="run-1",
            flow_id="implementation",
            level="story",
            owner="pipeline_engine",
            status="IN_PROGRESS",
        ),
    )
    return story_dir


def test_no_inline_while_loop_in_handler() -> None:
    """Source pin: on_enter has NO ``while`` loop (orchestrator-trennlinie)."""
    source = inspect.getsource(ImplementationPhaseHandler.on_enter)
    assert "while " not in source, (
        "ImplementationPhaseHandler.on_enter must not run an inline "
        "remediation loop (AG3-044 §2.1.7)"
    )


def test_qa_fail_below_ceiling_sets_remediation_spawn(tmp_path: Path) -> None:
    """FAIL below ceiling -> IN_PROGRESS + agents_to_spawn=[remediation_worker]."""
    story_dir = _story_dir(tmp_path)
    config = ImplementationConfig(
        story_dir=story_dir,
        max_feedback_rounds=3,
        verify_system=_FailVerifySystem(),  # type: ignore[arg-type]
    )
    handler = ImplementationPhaseHandler(config)
    state = PhaseState(
        story_id="AG3-044", phase="implementation", status=PhaseStatus.IN_PROGRESS
    )
    envelope = PhaseEnvelopeStore.make_fresh_envelope(state)

    result = handler.on_enter(_ctx(), envelope)

    assert result.status == PhaseStatus.IN_PROGRESS
    assert result.yield_status == "awaiting_remediation"
    assert result.updated_state is not None
    spawn = result.updated_state.agents_to_spawn
    assert len(spawn) == 1
    assert spawn[0].kind is SpawnKind.WORKER
    assert spawn[0].spawn_reason is SpawnReason.REMEDIATION
    # The QA cycle status reflects the remediation wait (FK-27 §27.2.2).
    payload = result.updated_state.payload
    assert payload is not None
    assert payload.qa_cycle_status is QaCycleStatus.AWAITING_REMEDIATION


class _ReentryHandler:
    """Handler returning IN_PROGRESS + agents_to_spawn (orchestrator-trennlinie).

    Mirrors what the REAL ImplementationPhaseHandler returns on a QA-FAIL below
    the ceiling: ``PhaseStatus.IN_PROGRESS`` with a remediation spawn order set
    on the updated state. Used to drive the REAL PipelineEngine end-to-end.
    """

    def on_enter(self, ctx: StoryContext, envelope: PhaseEnvelope) -> HandlerResult:
        del ctx
        updated = envelope.state.model_copy(
            update={
                "agents_to_spawn": [
                    SpawnRequest(
                        kind=SpawnKind.WORKER,
                        spawn_reason=SpawnReason.REMEDIATION,
                        target_id="AG3-044",
                    ),
                ],
            },
        )
        return HandlerResult(
            status=PhaseStatus.IN_PROGRESS,
            yield_status="awaiting_remediation",
            updated_state=updated,
        )

    def on_exit(self, ctx: StoryContext, envelope: PhaseEnvelope) -> None:
        del ctx, envelope

    def on_resume(
        self, ctx: StoryContext, envelope: PhaseEnvelope, trigger: str
    ) -> HandlerResult:
        del trigger
        return self.on_enter(ctx, envelope)


def test_engine_persists_agents_to_spawn_and_yields_without_transition(
    tmp_path: Path,
) -> None:
    """REAL engine: IN_PROGRESS+agents_to_spawn -> persisted, yielded, no transition.

    Drives the productive :class:`PipelineEngine` (not source inspection) with a
    handler returning IN_PROGRESS + ``agents_to_spawn``. Asserts the persisted
    ``PhaseState.status == IN_PROGRESS``, that ``agents_to_spawn`` survives
    persistence, and that the engine yields without a phase transition
    (FK-20 §20.5.1 / FK-45 §45.3).
    """
    story_dir = _story_dir(tmp_path)
    workflow = IMPLEMENTATION_WORKFLOW
    registry = PhaseHandlerRegistry()
    registry.register("implementation", _ReentryHandler())
    engine = PipelineEngine(workflow, registry, story_dir)

    state = PhaseState(
        story_id="AG3-044", phase="implementation", status=PhaseStatus.IN_PROGRESS
    )
    envelope = PhaseEnvelopeStore.make_fresh_envelope(state)

    result = engine.run_phase(_ctx(), envelope)

    # The engine yields for orchestrator re-entry (no phase transition).
    assert result.status == "yielded"
    assert result.phase == "implementation"
    assert result.yield_status == "awaiting_remediation"
    assert result.next_phase is None

    # The persisted PhaseState is IN_PROGRESS and carries the spawn order.
    persisted = read_phase_state_record(story_dir)
    assert persisted is not None
    assert persisted.status == PhaseStatus.IN_PROGRESS
    assert persisted.phase == "implementation"
    assert len(persisted.agents_to_spawn) == 1
    assert persisted.agents_to_spawn[0].kind is SpawnKind.WORKER
    assert persisted.agents_to_spawn[0].spawn_reason is SpawnReason.REMEDIATION
