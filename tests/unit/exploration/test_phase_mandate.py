"""Unit tests for the AG3-047 mandate flow in ExplorationPhaseHandler.on_enter.

Constructs the handler directly with first-class in-test collaborators (real
mandate components; doubled only at the boundary ports: change-frame reader, run
scope, declared-impact reader, telemetry emitter, review). Covers the routing
branches not reached by the productive integration test: the fine-design
round-limit escalation, the gate non-APPROVED mapping, and the fail-closed
"classifier wired without its collaborators" guards.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from tests.exploration_change_frame_fixture import EXAMPLE_RUN_ID, example_change_frame
from tests.phase_state_factory import make_phase_state

from agentkit.core_types import ExplorationGateStatus
from agentkit.exploration.change_frame import AffectedBuildingBlocks, OpenPoints
from agentkit.exploration.freeze import DesignFreezeMarker
from agentkit.exploration.mandate.classification import MandateClassification
from agentkit.exploration.mandate.fine_design import (
    FineDesignRoundOutcome,
    FineDesignSubprocess,
)
from agentkit.exploration.mandate.impact_checker import ImpactExceedanceChecker
from agentkit.exploration.mandate.scope_detector import ScopeExplosionDetector
from agentkit.exploration.mandate.telemetry import MandateTelemetry
from agentkit.exploration.phase import ExplorationConfig, ExplorationPhaseHandler
from agentkit.pipeline_engine.phase_envelope.store import PhaseEnvelopeStore
from agentkit.pipeline_engine.phase_executor import (
    ExplorationPayload,
    PhaseStatus,
)
from agentkit.story_context_manager.models import StoryContext
from agentkit.story_context_manager.story_model import ChangeImpact
from agentkit.story_context_manager.types import StoryMode, StoryType
from agentkit.telemetry.emitters import MemoryEmitter
from agentkit.telemetry.events import EventType

if TYPE_CHECKING:
    import pytest

    from agentkit.exploration.change_frame import ChangeFrame
    from agentkit.exploration.review import ExplorationGateResult

_STORY_ID = "AG3-047"


@dataclass
class _FixedReader:
    frame: ChangeFrame | None

    def load_change_frame(self, *, story_id: str, run_id: str) -> ChangeFrame | None:
        del story_id, run_id
        return self.frame


@dataclass
class _FixedRunScope:
    def resolve_run_id(self, story_dir: Path, *, story_id: str) -> str:
        del story_dir, story_id
        return EXAMPLE_RUN_ID


@dataclass
class _FixedImpactReader:
    declared: ChangeImpact

    def declared_change_impact(self, *, story_id: str) -> ChangeImpact:
        del story_id
        return self.declared


@dataclass
class _NeverConverge:
    def run_round(
        self, change_frame: ChangeFrame, *, round_number: int
    ) -> FineDesignRoundOutcome:
        del change_frame, round_number
        return FineDesignRoundOutcome(converged=False, decisions=())


@dataclass
class _ConvergeNow:
    """A fine-design evaluator that converges immediately (no decisions)."""

    def run_round(
        self, change_frame: ChangeFrame, *, round_number: int
    ) -> FineDesignRoundOutcome:
        del change_frame, round_number
        return FineDesignRoundOutcome(converged=True, decisions=())


@dataclass
class _NoopWriter:
    written: list[ChangeFrame] = field(default_factory=list)

    def write_change_frame_file(
        self, story_dir: Path, *, story_id: str, run_id: str, frame: ChangeFrame
    ) -> Path:
        del story_dir, story_id, run_id
        self.written.append(frame)
        return Path("change_frame.json")


@dataclass
class _ScriptedReview:
    """A double for ExplorationReview that returns a scripted gate result."""

    result: ExplorationGateResult
    run_design_challenge_seen: list[bool] = field(default_factory=list)

    def run(
        self, change_frame: ChangeFrame, *, run_design_challenge: bool = True
    ) -> ExplorationGateResult:
        del change_frame
        self.run_design_challenge_seen.append(run_design_challenge)
        return self.result


def _ctx() -> StoryContext:
    return StoryContext(
        project_key="p",
        story_id=_STORY_ID,
        story_type=StoryType.IMPLEMENTATION,
        execution_route=StoryMode.EXPLORATION,
        title="t",
        project_root=Path("root"),
    )


def _envelope() -> object:
    return PhaseEnvelopeStore.make_fresh_envelope(
        make_phase_state(
            story_id=_STORY_ID,
            phase="exploration",
            status=PhaseStatus.IN_PROGRESS,
            payload=ExplorationPayload(),
        )
    )


def _mandate() -> MandateClassification:
    return MandateClassification(
        scope_detector=ScopeExplosionDetector(),
        impact_checker=ImpactExceedanceChecker(),
    )


def _fine_design_frame() -> ChangeFrame:
    return example_change_frame(story_id=_STORY_ID, run_id=EXAMPLE_RUN_ID).model_copy(
        update={
            "affected_building_blocks": AffectedBuildingBlocks(affected=["one"]),
            "open_points": OpenPoints(
                decided=[], assumptions=[], approval_needed=["unresolved detail"]
            ),
        }
    )


def _trivial_frame() -> ChangeFrame:
    return example_change_frame(story_id=_STORY_ID, run_id=EXAMPLE_RUN_ID).model_copy(
        update={
            "affected_building_blocks": AffectedBuildingBlocks(affected=["one"]),
            "open_points": OpenPoints(
                decided=["adapter pattern"], assumptions=[], approval_needed=[]
            ),
        }
    )


def _handler(
    frame: ChangeFrame,
    *,
    review: object | None,
    fine_design: FineDesignSubprocess | None,
    emitter: MemoryEmitter,
    impact_reader: object | None,
) -> ExplorationPhaseHandler:
    return ExplorationPhaseHandler(
        change_frame_reader=_FixedReader(frame),
        run_scope_resolver=_FixedRunScope(),
        review=review,  # type: ignore[arg-type]
        config=ExplorationConfig(story_dir=Path("story")),
        mandate_classification=_mandate(),
        declared_impact_reader=impact_reader,  # type: ignore[arg-type]
        fine_design=fine_design,
        freeze_marker=DesignFreezeMarker(
            writer=_NoopWriter(), clock=lambda: datetime.now(UTC)
        ),
        telemetry=MandateTelemetry(emitter),
    )


def test_fine_design_max_rounds_escalates_and_emits_decisions() -> None:
    """Fine-design that never converges -> ESCALATED (round limit, FK-25 §25.5.1)."""
    emitter = MemoryEmitter()
    fine_design = FineDesignSubprocess(_NeverConverge())
    # A review is wired (the review-None guard runs first) but it never executes:
    # the fine-design round-limit escalates before the gate.
    review = _ScriptedReview(_dummy_approved())
    handler = _handler(
        _fine_design_frame(),
        review=review,
        fine_design=fine_design,
        emitter=emitter,
        impact_reader=_FixedImpactReader(ChangeImpact.ARCHITECTURE_IMPACT),
    )

    result = handler.on_enter(_ctx(), _envelope())

    assert result.status is PhaseStatus.ESCALATED
    assert result.suggested_reaction is not None
    assert "fine_design_max_rounds_exceeded" in result.suggested_reaction
    # The escalation short-circuits BEFORE the exit-gate runs.
    assert review.run_design_challenge_seen == []


def test_gate_rejected_maps_to_escalated() -> None:
    """A REJECTED gate (no freeze) -> ESCALATED with gate REJECTED."""
    from agentkit.exploration.review.doc_fidelity import DocFidelityResult
    from agentkit.exploration.review.review import ExplorationGateResult
    from agentkit.verify_system.protocols import Finding, Severity, TrustClass

    rejected = ExplorationGateResult(
        stage1_result=DocFidelityResult(
            status="fail",
            findings=(
                Finding(
                    layer="doc_fidelity",
                    check="impl_fidelity",
                    severity=Severity.BLOCKING,
                    message="conflict",
                    trust_class=TrustClass.VERIFIED_LLM,
                ),
            ),
            evaluator_result_ref=_dummy_ref(),
        ),
        stage2a_result=None,
        stage2b_result=None,
        overall_status=ExplorationGateStatus.REJECTED,
        review_rounds=0,
    )
    emitter = MemoryEmitter()
    handler = _handler(
        example_change_frame(story_id=_STORY_ID, run_id=EXAMPLE_RUN_ID).model_copy(
            update={"affected_building_blocks": AffectedBuildingBlocks(affected=["x"])}
        ),
        review=_ScriptedReview(rejected),
        fine_design=FineDesignSubprocess(_NeverConverge()),
        emitter=emitter,
        impact_reader=_FixedImpactReader(ChangeImpact.ARCHITECTURE_IMPACT),
    )

    result = handler.on_enter(_ctx(), _envelope())

    assert result.status is PhaseStatus.ESCALATED
    # MANDATE telemetry still emitted before the gate ran.
    assert any(
        e.event_type is EventType.MANDATE_CLASSIFICATION
        for e in emitter.all_events
    )


def test_classifier_without_impact_reader_fails_closed() -> None:
    """Mandate wired but no declared-impact reader -> fail-closed FAILED."""
    emitter = MemoryEmitter()
    handler = _handler(
        example_change_frame(story_id=_STORY_ID, run_id=EXAMPLE_RUN_ID).model_copy(
            update={"affected_building_blocks": AffectedBuildingBlocks(affected=["x"])}
        ),
        review=_ScriptedReview(_dummy_approved()),
        fine_design=FineDesignSubprocess(_NeverConverge()),
        emitter=emitter,
        impact_reader=None,
    )

    result = handler.on_enter(_ctx(), _envelope())

    assert result.status is PhaseStatus.FAILED


def test_trivial_class_suppresses_stage2b_design_challenge() -> None:
    """WARNING-4 (a): a TRIVIAL frame runs the review with challenge SUPPRESSED.

    The mandate gating computes ``run_design_challenge=False`` for a trivial
    decision; the phase must pass that flag to ``ExplorationReview.run`` so the
    optional Stage 2b is suppressed. The gate (Stage 1 + Stage 2a) still ran:
    the result came from the review, NOT from a mandate bypass (the APPROVED
    result requires a real Stage-1 PASS, NO ERROR BYPASSING).
    """
    emitter = MemoryEmitter()
    review = _ScriptedReview(_dummy_approved())
    handler = _handler(
        _trivial_frame(),
        review=review,
        fine_design=FineDesignSubprocess(_ConvergeNow()),
        emitter=emitter,
        impact_reader=_FixedImpactReader(ChangeImpact.ARCHITECTURE_IMPACT),
    )

    result = handler.on_enter(_ctx(), _envelope())

    assert result.status is PhaseStatus.COMPLETED
    # Stage 2b is suppressed for the trivial class.
    assert review.run_design_challenge_seen == [False]
    # The mandate classified the frame and the gate still ran (no bypass).
    assert any(
        e.event_type is EventType.MANDATE_CLASSIFICATION for e in emitter.all_events
    )


def test_fine_design_class_forces_stage2b_design_challenge() -> None:
    """WARNING-4 (b): a converged FINE_DESIGN frame cannot skip the challenge.

    The fine-design class warrants the adversarial Stage 2b: once the fine-design
    subprocess converges the flow reaches the gate with
    ``run_design_challenge=True`` forced (the mandate gating, not a per-call
    default).
    """
    emitter = MemoryEmitter()
    review = _ScriptedReview(_dummy_approved())
    handler = _handler(
        _fine_design_frame(),
        review=review,
        fine_design=FineDesignSubprocess(_ConvergeNow()),
        emitter=emitter,
        impact_reader=_FixedImpactReader(ChangeImpact.ARCHITECTURE_IMPACT),
    )

    result = handler.on_enter(_ctx(), _envelope())

    assert result.status is PhaseStatus.COMPLETED
    # Stage 2b is forced ON for the fine-design class.
    assert review.run_design_challenge_seen == [True]


def test_exploration_for_implementation_sets_execution_pending(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FK-24 §24.12: approved implementation exploration sets follow-up flags."""
    _enable_sqlite(monkeypatch)
    story_dir = tmp_path / "stories" / _STORY_ID
    story_dir.mkdir(parents=True)
    handler = ExplorationPhaseHandler(
        change_frame_reader=_FixedReader(_trivial_frame()),
        run_scope_resolver=_FixedRunScope(),
        review=_ScriptedReview(_dummy_approved()),  # type: ignore[arg-type]
        config=ExplorationConfig(story_dir=story_dir),
    )

    result = handler.on_enter(
        _ctx().model_copy(update={"project_root": tmp_path}), _envelope()
    )

    from agentkit.state_backend.store import load_story_context

    persisted = load_story_context(story_dir)
    assert result.status is PhaseStatus.COMPLETED
    assert persisted is not None
    assert persisted.implementation_required is True
    assert persisted.closure_allowed is False
    assert persisted.story_done is False
    assert persisted.exploration_completed is True
    assert persisted.execution_pending is True


def test_exploration_writes_human_readable_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FK-24 §24.12: implementation exploration writes exploration-summary.md."""
    _enable_sqlite(monkeypatch)
    story_dir = tmp_path / "stories" / _STORY_ID
    story_dir.mkdir(parents=True)
    handler = ExplorationPhaseHandler(
        change_frame_reader=_FixedReader(_trivial_frame()),
        run_scope_resolver=_FixedRunScope(),
        review=_ScriptedReview(_dummy_approved()),  # type: ignore[arg-type]
        config=ExplorationConfig(story_dir=story_dir),
    )

    result = handler.on_enter(
        _ctx().model_copy(update={"project_root": tmp_path}), _envelope()
    )

    summary = story_dir / "exploration-summary.md"
    assert result.status is PhaseStatus.COMPLETED
    assert summary.is_file()
    text = summary.read_text(encoding="utf-8")
    for section in (
        "## Investigated",
        "## Decided",
        "## Open",
        "## Mandatory Next Phase",
        "## Why Not Yet Complete",
    ):
        assert section in text


def _dummy_ref() -> object:
    from agentkit.artifacts.reference import ArtifactReference
    from agentkit.core_types import ArtifactClass

    return ArtifactReference(
        artifact_class=ArtifactClass.QA,
        story_id=_STORY_ID,
        run_id=EXAMPLE_RUN_ID,
        record_key="x.json",
    )


def _dummy_approved() -> object:
    from agentkit.exploration.review.doc_fidelity import DocFidelityResult
    from agentkit.exploration.review.review import ExplorationGateResult

    return ExplorationGateResult(
        stage1_result=DocFidelityResult(
            status="pass", findings=(), evaluator_result_ref=_dummy_ref()
        ),
        stage2a_result=None,
        stage2b_result=None,
        overall_status=ExplorationGateStatus.APPROVED,
        review_rounds=1,
    )


def _enable_sqlite(monkeypatch: pytest.MonkeyPatch) -> None:
    from agentkit.state_backend.config import ALLOW_SQLITE_ENV, STATE_BACKEND_ENV
    from agentkit.state_backend.store import reset_backend_cache_for_tests

    monkeypatch.setenv(STATE_BACKEND_ENV, "sqlite")
    monkeypatch.setenv(ALLOW_SQLITE_ENV, "1")
    reset_backend_cache_for_tests()
