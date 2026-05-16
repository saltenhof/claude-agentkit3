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

    def evaluate(self, ctx: StoryContext, story_dir: Path) -> LayerResult:
        """Run all structural checks and collect findings.

        All checks run unconditionally -- no early returns. Findings
        are aggregated and the layer passes only if no ``BLOCKING``
        severity findings exist (FK-27 §27.4.2).

        Args:
            ctx: Story context for type-specific evaluation.
            story_dir: Directory containing story artifacts.

        Returns:
            LayerResult with all collected findings.
        """
        findings: list[Finding] = []

        # 1. Context existence
        f = check_context_exists(story_dir)
        if f:
            findings.append(f)

        # 2. Context validity
        f = check_context_valid(story_dir)
        if f:
            findings.append(f)

        # 3. Phase snapshots -- derived from story type profile
        profile = get_profile(ctx.story_type)
        # QA-subflow runs inside implementation; all prior phases need snapshots.
        implementation_index = _phase_index(profile.phases, "implementation")
        required_prior = list(profile.phases[:implementation_index])
        phase_findings = check_phase_snapshots(story_dir, required_prior)
        findings.extend(phase_findings)

        # 4. State file integrity
        f = check_no_corrupt_state(story_dir)
        if f:
            findings.append(f)

        passed = not any(
            f.severity == Severity.BLOCKING for f in findings
        )
        return LayerResult(
            layer=self.name,
            passed=passed,
            findings=tuple(findings),
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
