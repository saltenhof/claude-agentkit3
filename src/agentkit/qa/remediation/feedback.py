"""Build remediation feedback from QA findings.

Transforms technical findings into actionable feedback for the
remediation worker. Pure transformation, no side effects.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from agentkit.qa.protocols import Finding, Severity

if TYPE_CHECKING:
    from agentkit.qa.policy_engine.engine import VerifyDecision


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
    """

    story_id: str
    round_nr: int
    blocking_findings: tuple[Finding, ...]
    advisory_findings: tuple[Finding, ...]
    summary: str

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

        lines.append(f"Summary: {self.summary}")
        return "\n".join(lines)


def build_feedback(
    decision: VerifyDecision,
    story_id: str,
    round_nr: int,
) -> RemediationFeedback | None:
    """Build remediation feedback from a verify decision.

    If the decision passed, returns ``None`` (no feedback needed).
    If the decision failed, builds structured feedback from the
    blocking and advisory findings.

    Args:
        decision: The verify decision to build feedback from.
        story_id: Story identifier for the feedback.
        round_nr: Current remediation round number.

    Returns:
        ``RemediationFeedback`` if the decision failed, otherwise ``None``.
    """
    if decision.passed:
        return None

    advisory = tuple(
        f for f in decision.all_findings
        if f.severity not in (Severity.CRITICAL, Severity.HIGH)
    )

    return RemediationFeedback(
        story_id=story_id,
        round_nr=round_nr,
        blocking_findings=decision.blocking_findings,
        advisory_findings=advisory,
        summary=decision.summary,
    )
