"""Contract tests pinning the phase dispatch to ``formal.story-workflow.*`` (AG3-054).

These pin the dispatch's phase-transition-enforcement + the FK-45 §45.3 reaction
normalization against the SSOT formal spec under
``concept/formal-spec/story-workflow/`` -- NOT a test-local duplicate. A drift
between the dispatch behaviour and the spec (valid/invalid transitions, the
first-call-setup invariant, forward-only progression, no exploration backjump,
the run-admission guard) fails the contract.

The tests are pure / in-memory (no DB): ``_enforce_transition`` and ``_normalize``
are exercised against forged in-memory phase-states + the real typed workflows.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml
from tests.phase_state_factory import make_phase_state

from agentkit.control_plane.dispatch import _enforce_transition, _normalize
from agentkit.core_types import ExplorationGateStatus
from agentkit.pipeline_engine.engine import EngineResult
from agentkit.pipeline_engine.phase_executor import (
    ExplorationPayload,
    PhaseName,
    PhaseState,
    PhaseStatus,
)
from agentkit.process.language.definitions import resolve_workflow
from agentkit.story_context_manager.models import StoryContext
from agentkit.story_context_manager.types import StoryMode, StoryType

_SPEC_ROOT = (
    Path(__file__).resolve().parents[3]
    / "concept"
    / "formal-spec"
    / "story-workflow"
)
_FORMAL_BLOCK = re.compile(
    r"<!-- FORMAL-SPEC:BEGIN -->\s*```yaml\n(?P<body>.*?)\n```", re.DOTALL
)


def _load_spec(name: str) -> dict[str, object]:
    text = (_SPEC_ROOT / name).read_text(encoding="utf-8")
    match = _FORMAL_BLOCK.search(text)
    assert match is not None, f"no FORMAL-SPEC block in {name}"
    return yaml.safe_load(match.group("body"))


def _phase_short(spec_id: str) -> str:
    """``story-workflow.phase.setup`` -> ``setup``."""
    return spec_id.rsplit(".", 1)[-1]


def _formal_phase_edges() -> set[tuple[str, str]]:
    """The canonical (from, to) phase-axis edges from the SSOT state-machine."""
    sm = _load_spec("state-machine.md")
    phase_axis = sm["phase_axis"]
    return {
        (_phase_short(t["from"]), _phase_short(t["to"]))
        for t in phase_axis["transitions"]
    }


def _completed(phase: str) -> PhaseState:
    return make_phase_state(story_id="AG3-001", phase=phase, status=PhaseStatus.COMPLETED)


def _ctx(*, route: StoryMode = StoryMode.EXECUTION) -> StoryContext:
    """A minimal story context for transition-guard evaluation.

    ``route`` drives the guarded ``setup -> {exploration,implementation}`` weiche
    (``mode_is_exploration`` / ``mode_is_not_exploration``).
    """
    return StoryContext(
        project_key="tenant-a",
        story_id="AG3-001",
        story_type=StoryType.IMPLEMENTATION,
        execution_route=route,
    )


def _ctx_for_edge(src: str, dst: str) -> StoryContext:
    """Pick a story context whose route SATISFIES the guard on ``src -> dst``."""
    if (src, dst) == ("setup", "exploration"):
        return _ctx(route=StoryMode.EXPLORATION)
    return _ctx(route=StoryMode.EXECUTION)


def _state_for_edge(src: str) -> PhaseState:
    """A COMPLETED ``src`` state that SATISFIES the guard for outgoing edges.

    The ``exploration -> implementation`` edge is guarded by
    ``exploration_gate_approved``, which requires a COMPLETED exploration phase
    whose :class:`ExplorationPayload` carries ``gate_status == APPROVED``.
    """
    if src == PhaseName.EXPLORATION.value:
        return make_phase_state(
            story_id="AG3-001",
            phase=src,
            status=PhaseStatus.COMPLETED,
            payload=ExplorationPayload(gate_status=ExplorationGateStatus.APPROVED),
        )
    return _completed(src)


class TestRunAdmissionInvariantPinned:
    def test_phase_start_requires_release_and_readiness_invariant_exists(self) -> None:
        """The new run-admission guard invariant exists in the SSOT spec."""
        invariants = _load_spec("invariants.md")["invariants"]
        ids = {inv["id"] for inv in invariants}
        assert (
            "story-workflow.invariant.phase_start_requires_release_and_readiness"
            in ids
        )

    def test_forward_only_and_setup_routing_invariants_exist(self) -> None:
        """Forward-only + fail-closed setup routing invariants exist."""
        invariants = _load_spec("invariants.md")["invariants"]
        ids = {inv["id"] for inv in invariants}
        assert "story-workflow.invariant.forward_only" in ids
        assert "story-workflow.invariant.setup_routes_fail_closed" in ids


class TestValidTransitionsMatchSpec:
    def test_every_formal_edge_is_admitted_by_dispatch(self) -> None:
        """Each SSOT phase edge is admitted by the dispatch transition-enforcement.

        The completed-predecessor edge (from a COMPLETED ``from`` phase to the
        spec ``to`` phase) must be admitted whenever it is present in the resolved
        workflow for some story type.
        """
        formal_edges = _formal_phase_edges()
        # Map each edge to a story type whose workflow contains it.
        all_workflow_edges: dict[tuple[str, str], StoryType] = {}
        for story_type in StoryType:
            workflow = resolve_workflow(story_type)
            for edge in workflow.edges:
                all_workflow_edges[(edge.source, edge.target)] = story_type

        for src, dst in formal_edges:
            story_type = all_workflow_edges.get((src, dst))
            if story_type is None:
                continue  # edge only legal for a mode not present in any workflow
            workflow = resolve_workflow(story_type)
            rejection = _enforce_transition(
                workflow, _ctx_for_edge(src, dst), _state_for_edge(src), dst
            )
            assert rejection is None, (
                f"formal edge {src}->{dst} wrongly rejected: {rejection}"
            )


class TestInvalidTransitionsRejected:
    def test_skip_phase_jump_is_rejected(self) -> None:
        """setup -> closure (skipping implementation) is not a workflow edge."""
        workflow = resolve_workflow(StoryType.IMPLEMENTATION)
        rejection = _enforce_transition(
            workflow, _ctx(), _completed("setup"), "closure"
        )
        assert rejection is not None
        assert "Invalid phase transition" in rejection

    def test_no_exploration_backjump(self) -> None:
        """implementation -> exploration is never a legal edge (no backjump)."""
        workflow = resolve_workflow(StoryType.IMPLEMENTATION)
        rejection = _enforce_transition(
            workflow, _ctx(), _completed("implementation"), "exploration"
        )
        assert rejection is not None
        assert "Invalid phase transition" in rejection

    def test_closure_backjump_is_rejected(self) -> None:
        """closure -> implementation is never legal (forward-only)."""
        workflow = resolve_workflow(StoryType.IMPLEMENTATION)
        rejection = _enforce_transition(
            workflow, _ctx(), _completed("closure"), "implementation"
        )
        assert rejection is not None

    def test_transition_from_not_completed_predecessor_rejected(self) -> None:
        """A valid edge is still rejected when the predecessor is not COMPLETED."""
        workflow = resolve_workflow(StoryType.BUGFIX)
        not_done = make_phase_state(
            story_id="AG3-001", phase="setup", status=PhaseStatus.PAUSED
        )
        rejection = _enforce_transition(workflow, _ctx(), not_done, "implementation")
        assert rejection is not None
        assert "not 'completed'" in rejection

    def test_guarded_edge_rejected_when_guard_unsatisfied(self) -> None:
        """FK-45 §45.2: a graph edge whose GUARD fails for this story is rejected.

        ``setup -> exploration`` IS a workflow edge, but it is guarded by
        ``mode_is_exploration``. For an execution-route story the guard fails, so
        the transition-enforcement must reject the edge (exploration-skip) even
        though the graph edge and the COMPLETED predecessor both hold.
        """
        workflow = resolve_workflow(StoryType.IMPLEMENTATION)
        rejection = _enforce_transition(
            workflow, _ctx(route=StoryMode.EXECUTION), _completed("setup"), "exploration"
        )
        assert rejection is not None
        # W9/#7: the dispatch mirrors the engine -- for an execution-route story
        # the engine's FIRST-passing outgoing edge from setup targets
        # implementation (guard _mode_is_not_exploration), NOT exploration, so the
        # exploration request is rejected (exploration-skip via engine ordering).
        assert "first-passing edge to 'implementation'" in rejection
        assert "not the requested phase 'exploration'" in rejection

    def test_exploration_to_implementation_rejected_without_approved_gate(
        self,
    ) -> None:
        """FK-45 §45.2: exploration -> implementation needs ``gate_status APPROVED``.

        The edge is guarded by ``exploration_gate_approved``; a COMPLETED
        exploration whose payload gate is not APPROVED is rejected fail-closed.
        """
        workflow = resolve_workflow(StoryType.IMPLEMENTATION)
        rejection = _enforce_transition(
            workflow,
            _ctx(route=StoryMode.EXPLORATION),
            _completed("exploration"),  # no APPROVED ExplorationPayload
            "implementation",
        )
        assert rejection is not None
        # W9/#7: the only outgoing edge from exploration is the guarded
        # exploration -> implementation; when ``exploration_gate_approved`` fails
        # the engine selects NO edge, so the dispatch rejects the transition.
        assert "no outgoing transition guard is satisfied" in rejection


class TestReactionNormalization:
    @pytest.mark.parametrize(
        ("engine_status", "next_phase", "expected_status", "expected_reaction"),
        [
            ("phase_completed", "implementation", "phase_completed", "run_worker"),
            ("phase_completed", None, "phase_completed", "advance"),
            ("yielded", None, "yielded", "await_external"),
            ("escalated", None, "escalated", "escalate"),
            ("failed", None, "failed", "escalate"),
            ("blocked", None, "blocked", "escalate"),
        ],
    )
    def test_engine_status_maps_to_fk45_reaction(
        self,
        engine_status: str,
        next_phase: str | None,
        expected_status: str,
        expected_reaction: str,
    ) -> None:
        """FK-45 §45.3: engine outcome maps to the normalized dispatch reaction."""
        result = EngineResult(
            status=engine_status,
            phase="implementation",
            next_phase=next_phase,
        )
        normalized = _normalize(result)
        assert normalized.status == expected_status
        assert normalized.reaction == expected_reaction
        assert normalized.dispatched is True
