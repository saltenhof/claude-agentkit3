"""Integration: BLOCKED-exit escalates with NO QA-subflow (FK-26 §26.11.2).

Proves the ``worker_blocked_escalates`` invariant on the REAL
``ImplementationPhaseHandler.on_enter`` path: a ``worker-manifest.json`` with
``status: BLOCKED`` returns ``PhaseStatus.ESCALATED`` with the blocker details in
``suggested_reaction`` AND never starts the QA-subflow (NO ERROR BYPASSING).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from tests.phase_state_factory import make_phase_state

from agentkit.backend.implementation.phase import (
    ImplementationConfig,
    ImplementationPhaseHandler,
)
from agentkit.backend.phase_state_store.models import FlowExecution
from agentkit.backend.pipeline_engine.engine import PipelineEngine
from agentkit.backend.pipeline_engine.lifecycle import PhaseHandlerRegistry
from agentkit.backend.pipeline_engine.phase_envelope.store import PhaseEnvelopeStore
from agentkit.backend.pipeline_engine.phase_executor import (
    PhaseStatus,
)
from agentkit.backend.process.language.definitions import IMPLEMENTATION_WORKFLOW
from agentkit.backend.state_backend.config import ALLOW_SQLITE_ENV, STATE_BACKEND_ENV
from agentkit.backend.state_backend.persistence_test_support import reset_backend_cache_for_tests
from agentkit.backend.state_backend.pipeline_runtime_store import save_flow_execution
from agentkit.backend.state_backend.story_lifecycle_store import save_story_context
from agentkit.backend.story_context_manager.models import StoryContext
from agentkit.backend.story_context_manager.types import StoryMode, StoryType

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

    from agentkit.backend.verify_system.contract import QaSubflowOutcome, VerifyContextBundle


@pytest.fixture(autouse=True)
def _sqlite_backend(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    monkeypatch.setenv(STATE_BACKEND_ENV, "sqlite")
    monkeypatch.setenv(ALLOW_SQLITE_ENV, "1")
    reset_backend_cache_for_tests()
    yield
    reset_backend_cache_for_tests()


class _EmptyStageRegistry:
    """Minimal stage-registry double exposing no stages (AG3-078, FK-33 §33.2.1)."""

    stages: tuple[object, ...] = ()


class _ExplodingVerifySystem:
    """VerifySystem double that fails the test if the QA-subflow is ever called.

    This is how the integration test PROVES the BLOCKED-exit runs BEFORE (and
    instead of) the QA-subflow: any call here is a wiring bug (the handler
    bypassed the manifest check).
    """

    @property
    def stage_registry(self) -> _EmptyStageRegistry:
        """Empty stage registry (AG3-078: no FC-derived origin stages)."""
        return _EmptyStageRegistry()

    def run_qa_subflow(
        self,
        ctx: VerifyContextBundle,
        story_id: str,
        qa_context: object,
        target: object,
        *,
        previous_findings: tuple[object, ...] = (),
    ) -> QaSubflowOutcome:
        del ctx, story_id, qa_context, target, previous_findings
        msg = "QA-subflow MUST NOT run when the worker manifest is BLOCKED"
        raise AssertionError(msg)


def _ctx() -> StoryContext:
    return StoryContext(
        project_key="test-project",
        story_id="AG3-044",
        story_type=StoryType.IMPLEMENTATION,
        execution_route=StoryMode.EXECUTION,
    )


def _write_blocked_manifest(story_dir: Path) -> None:
    manifest = {
        "story_id": "AG3-044",
        "run_id": "run-1",
        "status": "blocked",
        "completed_at": "2026-06-07T00:00:00+00:00",
        "blocking_category": "POLICY_CONFLICT",
        "blocking_issue": "pre_commit_hook_secret_detection",
        "recommended_next_action": "Extend the pre-commit hook with exceptions",
    }
    (story_dir / "worker-manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )


def test_blocked_manifest_escalates_without_qa_subflow(tmp_path: Path) -> None:
    """status=BLOCKED -> ESCALATED, QA-subflow never invoked."""
    story_dir = tmp_path / "stories" / "AG3-044"
    story_dir.mkdir(parents=True)
    save_story_context(story_dir, _ctx())
    _write_blocked_manifest(story_dir)

    config = ImplementationConfig(
        story_dir=story_dir,
        # test double: a minimal VerifySystem stub whose run_qa_subflow raises if
        # ever reached (proves BLOCKED short-circuits before QA); not the full surface.
        verify_system=_ExplodingVerifySystem(),  # type: ignore[arg-type]
    )
    handler = ImplementationPhaseHandler(config)
    state = make_phase_state(
        story_id="AG3-044", phase="implementation", status=PhaseStatus.IN_PROGRESS
    )
    envelope = PhaseEnvelopeStore.make_fresh_envelope(state)

    result = handler.on_enter(_ctx(), envelope)

    assert result.status == PhaseStatus.ESCALATED
    # AG3-044 AC6 (FK-26 §26.11.2): the structured blocker details live in the
    # TYPED ``suggested_reaction`` field, NOT smuggled through errors[0].
    assert result.suggested_reaction is not None
    suggested = json.loads(result.suggested_reaction)
    assert suggested["blocking_category"] == "POLICY_CONFLICT"
    assert suggested["blocking_issue"] == "pre_commit_hook_secret_detection"
    assert suggested["recommended_next_action"]
    # ``errors`` carries only a plain human summary line (no structured JSON).
    assert result.errors
    assert "POLICY_CONFLICT" in result.errors[0]
    assert "pre_commit_hook_secret_detection" in result.errors[0]
    # NO QA artifacts were produced (the subflow never ran).
    assert result.artifacts_produced == ()


def test_engine_propagates_suggested_reaction_to_caller(tmp_path: Path) -> None:
    """REAL engine: a BLOCKED escalation's suggested_reaction reaches the caller.

    FIX-2 (AG3-044 AC6, FK-26 §26.11.2): the terminal ``HandlerResult`` carries
    the structured blocker payload in ``suggested_reaction``; this drives the
    REAL :class:`PipelineEngine.run_phase` (not the handler in isolation) and
    asserts the field survives the engine boundary onto ``EngineResult`` — the
    blocked-exit assertion that the structured payload reaches production
    callers (no fail-open drop to only the human-summary ``errors`` string).
    """
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
    _write_blocked_manifest(story_dir)

    config = ImplementationConfig(
        story_dir=story_dir,
        # test double: a minimal VerifySystem stub whose run_qa_subflow raises if
        # ever reached (proves BLOCKED short-circuits before QA); not the full surface.
        verify_system=_ExplodingVerifySystem(),  # type: ignore[arg-type]
    )
    registry = PhaseHandlerRegistry()
    registry.register("implementation", ImplementationPhaseHandler(config))
    engine = PipelineEngine(IMPLEMENTATION_WORKFLOW, registry, story_dir)

    state = make_phase_state(
        story_id="AG3-044", phase="implementation", status=PhaseStatus.IN_PROGRESS
    )
    envelope = PhaseEnvelopeStore.make_fresh_envelope(state)

    result = engine.run_phase(_ctx(), envelope)

    # The engine reports the escalation AND forwards the typed reaction.
    assert result.status == "escalated"
    assert result.phase == "implementation"
    assert result.suggested_reaction is not None
    suggested = json.loads(result.suggested_reaction)
    assert suggested["blocking_category"] == "POLICY_CONFLICT"
    assert suggested["blocking_issue"] == "pre_commit_hook_secret_detection"
    assert suggested["recommended_next_action"]
    # The human-summary errors string is ALSO present, but the structured payload
    # is NOT smuggled through it.
    assert result.errors
    assert "POLICY_CONFLICT" in result.errors[0]


def test_non_blocked_manifest_does_not_short_circuit(tmp_path: Path) -> None:
    """A COMPLETED manifest does NOT trigger the BLOCKED-exit (QA-subflow runs).

    Here the exploding double WOULD be reached, proving the gate only fires for
    BLOCKED (the AssertionError surfaces as the QA-subflow being entered).
    """
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
    (story_dir / "worker-manifest.json").write_text(
        json.dumps(
            {
                "story_id": "AG3-044",
                "run_id": "run-1",
                "status": "completed",
                "completed_at": "2026-06-07T00:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    config = ImplementationConfig(
        story_dir=story_dir,
        # test double: a minimal VerifySystem stub whose run_qa_subflow raises if
        # ever reached (proves BLOCKED short-circuits before QA); not the full surface.
        verify_system=_ExplodingVerifySystem(),  # type: ignore[arg-type]
    )
    handler = ImplementationPhaseHandler(config)
    state = make_phase_state(
        story_id="AG3-044", phase="implementation", status=PhaseStatus.IN_PROGRESS
    )
    envelope = PhaseEnvelopeStore.make_fresh_envelope(state)

    # COMPLETED does not short-circuit; the handler proceeds toward the QA-subflow
    # (which the exploding double turns into an AssertionError -> proves the gate
    # did NOT fire for a non-BLOCKED manifest).
    with pytest.raises(AssertionError, match="QA-subflow MUST NOT run"):
        handler.on_enter(_ctx(), envelope)
