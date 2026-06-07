"""Integration test: ExplorationPhaseHandler.on_enter full mandate flow (AG3-047).

Drives the PRODUCTIVE ``build_exploration_phase_handler`` (real mandate
classification + scope detector + impact checker + fine-design skeleton + design
freeze + telemetry + the state-backed DeclaredImpactReader) against a real sqlite
backend and the productive ``ArtifactManager`` for all four mandate-class paths:

* SCOPE_EXPLOSION -> ESCALATED (recommend story split), no freeze;
* IMPACT_ESCALATION -> ESCALATED (architecture review), no freeze;
* FINE_DESIGN (converged) + TRIVIAL -> review -> APPROVED -> freeze -> COMPLETED.

The ONLY doubled seam is the LLM transport inside the injected review
(``ScriptedLlmClient`` -- the LLM grenze); the declared change_impact is read
from a REAL persisted ``Story`` so the composition-root DeclaredImpactReader
wiring is exercised end-to-end.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from tests.exploration_change_frame_fixture import (
    EXAMPLE_CREATED_AT,
    example_change_frame,
)
from tests.unit.exploration.review.scripted import (
    ScriptedLlmClient,
    build_real_sink,
    build_scripted_evaluator,
)

from agentkit.artifacts import (
    ArtifactEnvelope,
    EnvelopeStatus,
    Producer,
    ProducerId,
    ProducerType,
)
from agentkit.bootstrap.composition_root import (
    build_artifact_manager,
    build_exploration_phase_handler,
)
from agentkit.core_types import ArtifactClass
from agentkit.core_types.qa_artifact_names import CHANGE_FRAME_FILE
from agentkit.exploration.change_frame import (
    AffectedBuildingBlocks,
    ChangeFrame,
    ContractChanges,
    OpenPoints,
)
from agentkit.exploration.register import (
    EXPLORATION_ENTWURF_PRODUCER,
    EXPLORATION_ENTWURF_STAGE,
)
from agentkit.exploration.review.design_review import DesignReviewRunner
from agentkit.exploration.review.doc_fidelity import DocFidelityChecker
from agentkit.exploration.review.review import ExplorationReview
from agentkit.installer.paths import resolve_qa_story_dir
from agentkit.phase_state_store.models import FlowExecution
from agentkit.pipeline_engine.phase_envelope.store import PhaseEnvelopeStore
from agentkit.state_backend.config import ALLOW_SQLITE_ENV, STATE_BACKEND_ENV
from agentkit.state_backend.store import (
    load_execution_events,
    reset_backend_cache_for_tests,
    save_flow_execution,
)
from agentkit.state_backend.store.exploration_change_frame_repository import (
    StateBackendExplorationChangeFrameAdapter,
)
from agentkit.state_backend.store.story_repository import StateBackendStoryRepository
from agentkit.story_context_manager.models import (
    ExplorationPayload,
    PhaseState,
    PhaseStatus,
    StoryContext,
)
from agentkit.story_context_manager.story_model import (
    ChangeImpact,
    Story,
    WireStoryType,
)
from agentkit.story_context_manager.types import StoryMode, StoryType
from agentkit.telemetry.events import EventType

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

_STORY_ID = "AG3-047"
_RUN_ID = "55555555-5555-4555-8555-555555555555"


@pytest.fixture(autouse=True)
def sqlite_backend_env(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[None, None, None]:
    monkeypatch.setenv(STATE_BACKEND_ENV, "sqlite")
    monkeypatch.setenv(ALLOW_SQLITE_ENV, "1")
    reset_backend_cache_for_tests()
    yield
    reset_backend_cache_for_tests()


def _story_dir(tmp_path: Path) -> Path:
    story_dir = tmp_path / "stories" / _STORY_ID
    story_dir.mkdir(parents=True, exist_ok=True)
    return story_dir


def _ctx(story_dir: Path) -> StoryContext:
    return StoryContext(
        project_key="test-project",
        story_id=_STORY_ID,
        story_type=StoryType.IMPLEMENTATION,
        execution_route=StoryMode.EXPLORATION,
        title="Mandate classification flow",
        project_root=story_dir.parent.parent,
    )


def _bind_flow(story_dir: Path) -> None:
    save_flow_execution(
        story_dir,
        FlowExecution(
            project_key="test-project",
            story_id=_STORY_ID,
            run_id=_RUN_ID,
            flow_id="exploration",
            level="story",
            owner="pipeline_engine",
            status="IN_PROGRESS",
        ),
    )


def _save_story(story_dir: Path, *, declared: ChangeImpact) -> None:
    StateBackendStoryRepository(story_dir).save(
        Story(
            project_key="test-project",
            story_number=47,
            story_display_id=_STORY_ID,
            title="Mandate classification flow",
            story_type=WireStoryType.IMPLEMENTATION,
            participating_repos=["repo-a"],
            change_impact=declared,
        )
    )


def _persist_frame(manager: object, story_dir: Path, frame: ChangeFrame) -> None:
    """Persist an arbitrary change-frame the way the AG3-055 worker would."""
    envelope = ArtifactEnvelope(
        schema_version="3.0",
        story_id=_STORY_ID,
        run_id=_RUN_ID,
        stage=EXPLORATION_ENTWURF_STAGE,
        attempt=1,
        producer=Producer(
            type=ProducerType.WORKER,
            name=EXPLORATION_ENTWURF_PRODUCER,
            id=ProducerId(f"{EXPLORATION_ENTWURF_PRODUCER}-{_RUN_ID}"),
        ),
        started_at=EXAMPLE_CREATED_AT,
        finished_at=EXAMPLE_CREATED_AT,
        status=EnvelopeStatus.PASS,
        artifact_class=ArtifactClass.ENTWURF,
        payload=frame.model_dump(mode="json"),
    )
    manager.write(envelope)  # type: ignore[attr-defined]
    StateBackendExplorationChangeFrameAdapter(manager).write_change_frame_file(  # type: ignore[arg-type]
        story_dir, story_id=_STORY_ID, run_id=_RUN_ID, frame=frame
    )


def _state() -> PhaseState:
    return PhaseState(
        story_id=_STORY_ID,
        phase="exploration",
        status=PhaseStatus.IN_PROGRESS,
        payload=ExplorationPayload(),
    )


def _passing_review(ctx: StoryContext, story_dir: Path) -> ExplorationReview:
    """Build a REAL ExplorationReview with a scripted (PASS) LLM transport."""
    client = ScriptedLlmClient(doc_fidelity=["PASS"], semantic_review=["PASS"])
    evaluator = build_scripted_evaluator(ctx, client)
    sink = build_real_sink(story_dir)
    return ExplorationReview(
        stage1_doc_fidelity=DocFidelityChecker(evaluator, sink),
        stage2a_design_review=DesignReviewRunner(evaluator, sink),
        stage2b_design_challenge=None,
        artifact_manager=build_artifact_manager(story_dir),
    )


def _trivial_frame() -> ChangeFrame:
    return example_change_frame(story_id=_STORY_ID, run_id=_RUN_ID).model_copy(
        update={
            "affected_building_blocks": AffectedBuildingBlocks(affected=["one"]),
            "open_points": OpenPoints(
                decided=["adapter pattern"], assumptions=[], approval_needed=[]
            ),
        }
    )


def _fine_design_frame() -> ChangeFrame:
    return example_change_frame(story_id=_STORY_ID, run_id=_RUN_ID).model_copy(
        update={
            "affected_building_blocks": AffectedBuildingBlocks(affected=["one"]),
            "open_points": OpenPoints(
                decided=[],
                assumptions=[],
                approval_needed=["broker streaming contract unresolved"],
            ),
        }
    )


def _exploding_frame() -> ChangeFrame:
    return example_change_frame(story_id=_STORY_ID, run_id=_RUN_ID).model_copy(
        update={
            "affected_building_blocks": AffectedBuildingBlocks(
                affected=[f"m{i}" for i in range(8)],
            ),
            "contract_changes": ContractChanges(
                interfaces=["a", "b"],
                data_model=["c", "d"],
                events=["e"],
                external_integrations=["f"],
            ),
        }
    )


def _impact_frame() -> ChangeFrame:
    return example_change_frame(story_id=_STORY_ID, run_id=_RUN_ID).model_copy(
        update={
            "affected_building_blocks": AffectedBuildingBlocks(
                affected=["m1", "m2", "m3", "m4"],
            ),
            "contract_changes": ContractChanges(
                interfaces=["a", "b"], data_model=["c"], events=["d"]
            ),
        }
    )


def _frozen_file_exists(story_dir: Path) -> bool:
    path = resolve_qa_story_dir(story_dir, story_id=_STORY_ID) / CHANGE_FRAME_FILE
    if not path.is_file():
        return False
    return bool(json.loads(path.read_text(encoding="utf-8")).get("frozen"))


def test_scope_explosion_escalates(tmp_path: Path) -> None:
    """Klasse 3 -> ESCALATED with the story-split reaction; no freeze."""
    story_dir = _story_dir(tmp_path)
    _bind_flow(story_dir)
    _save_story(story_dir, declared=ChangeImpact.ARCHITECTURE_IMPACT)
    manager = build_artifact_manager(story_dir)
    _persist_frame(manager, story_dir, _exploding_frame())
    ctx = _ctx(story_dir)
    handler = build_exploration_phase_handler(
        story_dir, review=_passing_review(ctx, story_dir)
    )

    result = handler.on_enter(ctx, PhaseEnvelopeStore.make_fresh_envelope(_state()))

    assert result.status is PhaseStatus.ESCALATED
    assert result.suggested_reaction == "scope_explosion_detected: recommend story split"
    assert _frozen_file_exists(story_dir) is False
    events = {
        e.event_type for e in load_execution_events(story_dir, story_id=_STORY_ID)
    }
    assert EventType.MANDATE_CLASSIFICATION in events
    assert EventType.SCOPE_EXPLOSION_CHECK in events
    assert EventType.IMPACT_EXCEEDANCE_CHECK in events


def test_impact_escalation_escalates(tmp_path: Path) -> None:
    """Klasse 4 -> ESCALATED with the architecture-review reaction; no freeze."""
    story_dir = _story_dir(tmp_path)
    _bind_flow(story_dir)
    _save_story(story_dir, declared=ChangeImpact.LOCAL)
    manager = build_artifact_manager(story_dir)
    _persist_frame(manager, story_dir, _impact_frame())
    ctx = _ctx(story_dir)
    handler = build_exploration_phase_handler(
        story_dir, review=_passing_review(ctx, story_dir)
    )

    result = handler.on_enter(ctx, PhaseEnvelopeStore.make_fresh_envelope(_state()))

    assert result.status is PhaseStatus.ESCALATED
    assert result.suggested_reaction == "impact_exceedance: architecture review needed"
    assert _frozen_file_exists(story_dir) is False


def test_trivial_approves_and_freezes(tmp_path: Path) -> None:
    """Klasse 1 (trivial) -> review APPROVED -> freeze -> COMPLETED."""
    story_dir = _story_dir(tmp_path)
    _bind_flow(story_dir)
    _save_story(story_dir, declared=ChangeImpact.ARCHITECTURE_IMPACT)
    manager = build_artifact_manager(story_dir)
    _persist_frame(manager, story_dir, _trivial_frame())
    ctx = _ctx(story_dir)
    handler = build_exploration_phase_handler(
        story_dir, review=_passing_review(ctx, story_dir)
    )

    result = handler.on_enter(ctx, PhaseEnvelopeStore.make_fresh_envelope(_state()))

    assert result.status is PhaseStatus.COMPLETED
    assert _frozen_file_exists(story_dir) is True


def test_fine_design_escalates_fail_closed_no_freeze(tmp_path: Path) -> None:
    """Klasse 2 (fine-design) on the PRODUCTIVE wiring -> ESCALATED, no freeze.

    ERROR-1 fix (FK-25 §25.5 / §25.5.4): the productive composition root wires the
    fail-closed :class:`_UnavailableFineDesignEvaluator` (the real multi-LLM
    fine-design evaluator is a follow-up). A class-2 frame therefore ESCALATES to
    a human with the ``fine_design_required`` reaction instead of silently
    reaching APPROVED / freeze with no real fine-design. The change-frame is NOT
    frozen (NO ERROR BYPASSING).
    """
    story_dir = _story_dir(tmp_path)
    _bind_flow(story_dir)
    _save_story(story_dir, declared=ChangeImpact.ARCHITECTURE_IMPACT)
    manager = build_artifact_manager(story_dir)
    _persist_frame(manager, story_dir, _fine_design_frame())
    ctx = _ctx(story_dir)
    handler = build_exploration_phase_handler(
        story_dir, review=_passing_review(ctx, story_dir)
    )

    result = handler.on_enter(ctx, PhaseEnvelopeStore.make_fresh_envelope(_state()))

    assert result.status is PhaseStatus.ESCALATED
    assert result.suggested_reaction is not None
    assert "fine_design_required" in result.suggested_reaction
    assert _frozen_file_exists(story_dir) is False
    # The mandate classification telemetry still fired before the escalation.
    events = {
        e.event_type for e in load_execution_events(story_dir, story_id=_STORY_ID)
    }
    assert EventType.MANDATE_CLASSIFICATION in events
