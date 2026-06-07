"""Gate contracts for quality gates in the workflow DSL.

Gates are data structures that define quality-gate contracts -- what
stages a gate has, who the actors are, what evidence is required, and
what outcomes are possible. Gates do NOT execute anything; that is the
responsibility of the gate runner in the engine layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from agentkit.process.language.guards import GuardFn


class ExplorationGateStage(StrEnum):
    """The three typed stages of the exploration exit-gate (FK-23 §23.5).

    The exploration exit-gate is a three-stage model (FK-23 §23.5): Stage 1
    document-fidelity (§23.5.1), Stage 2a design-review (§23.5.2) and the
    optional Stage 2b design-challenge (§23.5.3). The wire values match the
    workflow-DSL yield-points ``design_review`` / ``design_challenge`` so the
    typed stage model and the imperative topology never drift apart
    (exploration-and-design.B3).

    Attributes:
        DOC_FIDELITY: Stage 1 -- binary document-fidelity check (§23.5.1).
        DESIGN_REVIEW: Stage 2a -- design-review with remediation loop (§23.5.2).
        DESIGN_CHALLENGE: Stage 2b -- optional design-challenge (§23.5.3).
    """

    DOC_FIDELITY = "doc_fidelity"
    DESIGN_REVIEW = "design_review"
    DESIGN_CHALLENGE = "design_challenge"


class ExplorationGateStageSpec(BaseModel):
    """Typed contract for one stage of the exploration exit-gate (FK-23 §23.5).

    Models the workflow-DSL gate stage as data, not a free string: it binds the
    typed :class:`ExplorationGateStage` id to its workflow-DSL yield-point and
    the stage policy (``required`` / ``rollback_on_fail``). The exploration
    phase handler reads these specs to drive the gate in the concept-normative
    order; the gate runner never executes anything from here (gates are data,
    FK-23 §23.5). Immutable + ``extra="forbid"`` (fail-closed: no untyped stage
    fields).

    Note:
        Named ``ExplorationGateStageSpec`` to avoid clobbering the long-lived,
        differently-shaped workflow-DSL :class:`GateStage` dataclass (AG3-001);
        this is the exploration-gate-specific typed stage model (AG3-046).

    Attributes:
        stage_id: The typed stage identity (FK-23 §23.5 three-stage model).
        yield_point: The workflow-DSL yield-point name this stage maps to
            (``design_review`` / ``design_challenge``; Stage 1 runs inline
            before the first yield, so it carries an empty yield-point).
        required: Whether the stage MUST run to pass the gate. Stage 1 and
            Stage 2a are required; Stage 2b is optional (mandate-gated, AG3-047).
        rollback_on_fail: Whether a FAIL of this stage rolls the change-frame
            back to an editable draft (FK-25 §25.4.2: editable until gate-PASS).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    stage_id: ExplorationGateStage
    yield_point: str
    required: bool
    rollback_on_fail: bool


@dataclass(frozen=True)
class GateStage:
    """A single stage within a quality gate.

    Each stage represents one evaluation step performed by a specific
    actor (e.g. "structural_checker", "qa_agent", "guardrail_agent").

    Args:
        name: Short identifier for this stage (e.g. "structural", "semantic").
        actor: Who performs this stage (e.g. "system", "qa_agent").
        evidence: Artifact paths or names that serve as evidence.
        outcomes: Possible outcomes of this stage.
        condition: Optional guard that must pass for this stage to run.
        risk_triggers: Patterns or conditions that trigger elevated risk handling.
    """

    name: str
    actor: str
    evidence: tuple[str, ...] = ()
    outcomes: tuple[str, ...] = ("PASS", "FAIL")
    condition: GuardFn | None = None
    risk_triggers: tuple[str, ...] = ()


@dataclass(frozen=True)
class Gate:
    """A quality gate contract with one or more stages.

    A gate defines the structure of a quality checkpoint: which stages
    it consists of, how many remediation rounds are allowed, and what
    happens when the maximum is exceeded.

    Args:
        id: Unique gate identifier (e.g. "verify_gate", "exploration_gate").
        stages: Ordered tuple of gate stages.
        max_remediation_rounds: Maximum number of remediation attempts
            before escalation.
        on_max_exceeded: Action to take when max rounds are exceeded
            (e.g. "escalate", "fail_hard").
        final_aggregation: Strategy for aggregating stage results
            (e.g. "deterministic", "majority").
    """

    id: str
    stages: tuple[GateStage, ...] = ()
    max_remediation_rounds: int = 2
    on_max_exceeded: str = "escalate"
    final_aggregation: str = "deterministic"
