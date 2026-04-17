"""Gate contracts for quality gates in the workflow DSL.

Gates are data structures that define quality-gate contracts -- what
stages a gate has, who the actors are, what evidence is required, and
what outcomes are possible. Gates do NOT execute anything; that is the
responsibility of the gate runner in the engine layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agentkit.process.language.guards import GuardFn


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
