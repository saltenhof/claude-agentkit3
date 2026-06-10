"""Build remediation feedback from QA findings.

Transforms technical findings into actionable feedback for the
remediation worker. Pure transformation, no side effects.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from agentkit.verify_system.protocols import Finding, Severity, TrustClass
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
        lines.extend(self._blocking_section())
        lines.extend(self._advisory_section())
        lines.extend(self._unresolved_section())
        lines.append(f"Summary: {self.summary}")
        return "\n".join(lines)

    def _blocking_section(self) -> list[str]:
        """Render the blocking-findings section (empty when none)."""
        if not self.blocking_findings:
            return []
        lines = [f"### Blocking Issues ({len(self.blocking_findings)})", ""]
        for i, f in enumerate(self.blocking_findings, 1):
            sev = f.severity.value.upper()
            lines.append(f"{i}. [{sev}] {f.check}: {f.message}")
            if f.file_path:
                lines.append(f"   File: {f.file_path}")
            if f.suggestion:
                lines.append(f"   Suggestion: {f.suggestion}")
        lines.append("")
        return lines

    def _advisory_section(self) -> list[str]:
        """Render the advisory-findings section (empty when none)."""
        if not self.advisory_findings:
            return []
        lines = [f"### Advisory ({len(self.advisory_findings)})", ""]
        for i, f in enumerate(self.advisory_findings, 1):
            sev = f.severity.value.upper()
            lines.append(f"{i}. [{sev}] {f.check}: {f.message}")
        lines.append("")
        return lines

    def _unresolved_section(self) -> list[str]:
        """Render the open previous-findings section (empty when none)."""
        open_findings = [
            (key, status)
            for key, status in self.finding_resolution.items()
            if is_open_resolution_status(status)
        ]
        if not open_findings:
            return []
        lines = [f"### Unresolved Previous Findings ({len(open_findings)})", ""]
        for i, ((layer, check), status) in enumerate(open_findings, 1):
            lines.append(f"{i}. [{layer}] {check}: still {status.value.upper()}")
        lines.append("")
        return lines


def build_feedback(
    decision: VerifyDecision,
    story_id: str,
    round_nr: int,
    *,
    finding_resolution: dict[FindingKey, FindingResolutionStatus] | None = None,
    extra_blocking_findings: tuple[Finding, ...] = (),
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
    if decision.passed and not extra_blocking_findings:
        return None

    advisory = tuple(
        f for f in decision.all_findings
        if f.severity != Severity.BLOCKING
    )
    blocking = (*decision.blocking_findings, *extra_blocking_findings)

    return RemediationFeedback(
        story_id=story_id,
        round_nr=round_nr,
        blocking_findings=blocking,
        advisory_findings=advisory,
        summary=_summary_with_extra_findings(decision.summary, extra_blocking_findings),
        finding_resolution=dict(finding_resolution) if finding_resolution else {},
    )


def mandatory_target_findings_from_adversarial(
    adversarial_payload: dict[str, object],
) -> tuple[Finding, ...]:
    """Map unmet mandatory adversarial targets to real ``Finding`` objects.

    AC8 remediation r2 (FAIL-CLOSED): the ``mandatory_target_results`` key being
    GENUINELY ABSENT means the adversarial stage tracked no mandatory targets ->
    no findings (``()``). But a PRESENT key with a wrong shape (not a list) — or a
    list ENTRY that is not a mapping — is a broken artifact, NOT "no targets":
    silently dropping it would lose a BLOCKING mandatory target the remediation
    loop needs. Such a present-but-broken shape raises
    :class:`MandatoryTargetReadError` instead of being swallowed, consistent with
    the present-but-None-payload guard in
    :func:`agentkit.verify_system.system._mandatory_target_feedback_findings`.

    Raises:
        MandatoryTargetReadError: When ``mandatory_target_results`` is present but
            not a list, or a list entry is present but not a mapping.
    """
    from agentkit.verify_system.errors import MandatoryTargetReadError

    if "mandatory_target_results" not in adversarial_payload:
        # Key genuinely absent -> the adversarial stage tracked no mandatory
        # targets. This is a valid "no targets" state, not a broken artifact.
        return ()
    raw_results = adversarial_payload.get("mandatory_target_results")
    if not isinstance(raw_results, list):
        raise MandatoryTargetReadError(
            "The adversarial artifact carries a 'mandatory_target_results' key but "
            f"its shape is broken: expected a list, got {type(raw_results).__name__}. "
            "A present-but-malformed mandatory_target_results must not silently drop "
            "a mandatory target (FAIL-CLOSED)."
        )
    findings: list[Finding] = []
    for raw in raw_results:
        if not isinstance(raw, dict):
            raise MandatoryTargetReadError(
                "The adversarial artifact's 'mandatory_target_results' contains an "
                f"entry of the wrong shape: expected a mapping, got {type(raw).__name__}. "
                "A present-but-malformed mandatory-target entry must not silently "
                "drop a mandatory target (FAIL-CLOSED)."
            )
        status = str(raw.get("status", "")).upper()
        if status in {"TESTED", "UNRESOLVABLE"}:
            continue
        target_id = str(raw.get("target_id") or raw.get("id") or "mandatory_target")
        detail = str(raw.get("detail") or raw.get("reason") or "target was not tested")
        findings.append(
            Finding(
                layer="adversarial",
                check=target_id,
                severity=Severity.BLOCKING,
                message=(
                    "Mandatory adversarial target not fulfilled: "
                    f"{target_id} (status={status or 'MISSING'}; {detail})"
                ),
                trust_class=TrustClass.VERIFIED_LLM,
                suggestion="Cover this mandatory adversarial target or mark it UNRESOLVABLE with evidence.",
            )
        )
    return tuple(findings)


def _summary_with_extra_findings(
    summary: str,
    extra_blocking_findings: tuple[Finding, ...],
) -> str:
    if not extra_blocking_findings:
        return summary
    return (
        f"{summary} Mandatory adversarial target feedback added: "
        f"{len(extra_blocking_findings)} blocking finding(s)."
    )
