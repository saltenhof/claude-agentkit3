"""Structural QA layer -- deterministic checks without LLM.

Orchestrates individual check functions. No business logic beyond
aggregation (ARCH-12). Implements the ``QALayer`` protocol.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.story_context_manager.types import get_profile
from agentkit.verify_system.protocols import Finding, LayerResult, Severity
from agentkit.verify_system.structural.checks import (
    check_context_exists,
    check_context_valid,
    check_no_corrupt_state,
    check_phase_snapshots,
)

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.story_context_manager.models import StoryContext
    from agentkit.verify_system.llm_evaluator.inputs import Layer2ReviewInput


class StructuralChecker:
    """Layer 1: Deterministic structural checks.

    Checks: context exists, context valid, snapshots present, state
    not corrupt. All checks run regardless of earlier failures
    (fail-closed, collect all findings).

    Satisfies the :class:`~agentkit.verify_system.protocols.QALayer` protocol.
    """

    @property
    def name(self) -> str:
        """Return the layer name.

        Returns:
            ``"structural"``.
        """
        return "structural"

    def evaluate(
        self,
        ctx: StoryContext,
        story_dir: Path,
        *,
        review_input: Layer2ReviewInput | None = None,
    ) -> LayerResult:
        """Run all structural checks and collect findings.

        All checks run unconditionally -- no early returns. Findings
        are aggregated and the layer passes only if no ``BLOCKING``
        severity findings exist (FK-27 §27.4.2).

        ``review_input`` is accepted but ignored by Layer 1 (Structural);
        it is only used by Layer-2 reviewers.

        Args:
            ctx: Story context for type-specific evaluation.
            story_dir: Directory containing story artifacts.
            review_input: Ignored by Layer 1. Accepted for protocol
                compatibility with ``QALayer``.

        Returns:
            LayerResult with all collected findings.
        """
        del review_input  # Layer 1 does not use review_input.
        findings: list[Finding] = []
        checks_run = 0

        # 1. Context existence
        checks_run += 1
        f = check_context_exists(story_dir)
        if f:
            findings.append(f)

        # 2. Context validity
        checks_run += 1
        f = check_context_valid(story_dir)
        if f:
            findings.append(f)

        # 3. Phase snapshots -- derived from story type profile (one check per
        # required prior phase).
        profile = get_profile(ctx.story_type)
        # QA-subflow runs inside implementation; all prior phases need snapshots.
        implementation_index = _phase_index(profile.phases, "implementation")
        required_prior = list(profile.phases[:implementation_index])
        checks_run += len(required_prior)
        phase_findings = check_phase_snapshots(story_dir, required_prior)
        findings.extend(phase_findings)

        # 4. State file integrity
        checks_run += 1
        f = check_no_corrupt_state(story_dir)
        if f:
            findings.append(f)

        passed = not any(
            f.severity == Severity.BLOCKING for f in findings
        )
        # FK-35 §35.2.4 Dim 3 (STRUCTURAL_SHALLOW): record how many checks the
        # layer actually ran so the IntegrityGate can verify check depth
        # against the canonical structural envelope (not mere existence).
        return LayerResult(
            layer=self.name,
            passed=passed,
            findings=tuple(findings),
            metadata={"total_checks": checks_run},
        )


def _phase_index(phases: tuple[str, ...], target: str) -> int:
    """Find the index of a phase in the phase tuple.

    If the target phase is not found, returns the length of the tuple
    (i.e., all phases are considered prior).

    Args:
        phases: Ordered tuple of phase names.
        target: Phase name to locate.

    Returns:
        Index of the target phase, or ``len(phases)`` if not found.
    """
    for i, phase in enumerate(phases):
        if phase == target:
            return i
    return len(phases)
