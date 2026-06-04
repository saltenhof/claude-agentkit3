"""Build remediation feedback from QA findings.

Transforms technical findings into actionable feedback for the
remediation worker. Pure transformation, no side effects.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from agentkit.verify_system.protocols import Finding, Severity
from agentkit.verify_system.remediation.finding_resolution import (
    FindingKey,
    FindingResolutionStatus,
    is_open_resolution_status,
    resolution_map_has_open_findings,
)

if TYPE_CHECKING:
    from agentkit.verify_system.policy_engine.engine import VerifyDecision


@dataclass(frozen=True)
class RemediationFeedback:
    """Structured feedback for remediation.

    Immutable value object (ARCH-29). Contains all information a
    remediation worker needs to fix the identified issues.

    Args:
        story_id: Identifier of the story under review.
        round_nr: Current remediation round number.
        blocking_findings: Findings that must be fixed.
        advisory_findings: Findings that should be considered.
        summary: Human-readable summary of what needs fixing.
        finding_resolution: Per previous-round finding resolution status
            (FK-34 / DK-04 §4.6), keyed by the ``(layer, check)`` finding id.
            Empty in the initial round (no previous findings) and populated in
            remediation rounds (AG3-041 §2.1.5). NOT_RESOLVED entries mark
            still-open previous findings the closure gate must observe.
    """

    story_id: str
    round_nr: int
    blocking_findings: tuple[Finding, ...]
    advisory_findings: tuple[Finding, ...]
    summary: str
    finding_resolution: dict[FindingKey, FindingResolutionStatus] = field(
        default_factory=dict
    )

    def has_open_findings(self) -> bool:
        """Return whether any previous-round finding is still open (blocking).

        FK-34 (Finding-Resolution): an open finding is one that is NOT fully
        resolved. Both ``NOT_RESOLVED`` and ``PARTIALLY_RESOLVED`` block closure
        — a partially-resolved finding still carries an unaddressed remainder
        (FK-34 ~§Z.685-699; DK-04 §4.6.3 grades an unmet mandatory target at
        least ``partially_resolved``). Only ``FULLY_RESOLVED`` clears.

        Returns:
            ``True`` if ``finding_resolution`` carries at least one entry that
            is ``NOT_RESOLVED`` or ``PARTIALLY_RESOLVED`` (an open previous
            finding); ``False`` otherwise (empty, or all ``FULLY_RESOLVED``).
        """
        return resolution_map_has_open_findings(self.finding_resolution)

    def to_prompt_text(self) -> str:
        """Format feedback as text suitable for a remediation prompt.

        Returns:
            A multi-line string with structured feedback sections.
        """
        lines: list[str] = [
            f"## Remediation Feedback (Round {self.round_nr})",
            "",
            f"Story: {self.story_id}",
            "Status: FAILED",
            "",
        ]

        if self.blocking_findings:
            lines.append(f"### Blocking Issues ({len(self.blocking_findings)})")
            lines.append("")
            for i, f in enumerate(self.blocking_findings, 1):
                sev = f.severity.value.upper()
                lines.append(f"{i}. [{sev}] {f.check}: {f.message}")
                if f.file_path:
                    lines.append(f"   File: {f.file_path}")
                if f.suggestion:
                    lines.append(f"   Suggestion: {f.suggestion}")
            lines.append("")

        if self.advisory_findings:
            lines.append(f"### Advisory ({len(self.advisory_findings)})")
            lines.append("")
            for i, f in enumerate(self.advisory_findings, 1):
                sev = f.severity.value.upper()
                lines.append(f"{i}. [{sev}] {f.check}: {f.message}")
            lines.append("")

        if self.finding_resolution:
            open_findings = [
                (key, status)
                for key, status in self.finding_resolution.items()
                if is_open_resolution_status(status)
            ]
            if open_findings:
                lines.append(
                    f"### Unresolved Previous Findings ({len(open_findings)})"
                )
                lines.append("")
                for i, ((layer, check), status) in enumerate(open_findings, 1):
                    lines.append(
                        f"{i}. [{layer}] {check}: still {status.value.upper()}"
                    )
                lines.append("")

        lines.append(f"Summary: {self.summary}")
        return "\n".join(lines)


def build_feedback(
    decision: VerifyDecision,
    story_id: str,
    round_nr: int,
    *,
    finding_resolution: dict[FindingKey, FindingResolutionStatus] | None = None,
) -> RemediationFeedback | None:
    """Build remediation feedback from a verify decision.

    If the decision passed, returns ``None`` (no feedback needed).
    If the decision failed, builds structured feedback from the
    blocking and advisory findings.

    Args:
        decision: The verify decision to build feedback from.
        story_id: Story identifier for the feedback.
        round_nr: Current remediation round number.
        finding_resolution: Optional per previous-round finding resolution
            map (FK-34 / DK-04 §4.6). Passed in remediation rounds so the
            feedback carries which previous findings remain ``NOT_RESOLVED``;
            ``None``/empty in the initial round.

    Returns:
        ``RemediationFeedback`` if the decision failed, otherwise ``None``.
    """
    if decision.passed:
        return None

    advisory = tuple(
        f for f in decision.all_findings
        if f.severity != Severity.BLOCKING
    )

    return RemediationFeedback(
        story_id=story_id,
        round_nr=round_nr,
        blocking_findings=decision.blocking_findings,
        advisory_findings=advisory,
        summary=decision.summary,
        finding_resolution=dict(finding_resolution) if finding_resolution else {},
    )
