"""Policy engine -- deterministic aggregation of QA layer results.

Takes LayerResults from all layers, applies trust weighting, and
produces a final PASS/FAIL decision per FK-27 §27.7.2. No LLM, no
side effects (ARCH-12).

PolicyVerdict ist seit AG3-021 ein StrEnum aus ``agentkit.core_types``
mit nur zwei Werten: PASS und FAIL. Der LLM-Check-Status am
Envelope-Rand (AG3-022, FK-71) ist eine getrennte Werteliste und
gehoert ausdruecklich nicht in diesen Modul-Kontext.
"""

from __future__ import annotations

from dataclasses import dataclass

from agentkit.core_types import PolicyVerdict
from agentkit.verify_system.protocols import Finding, LayerResult, Severity, TrustClass


@dataclass(frozen=True)
class VerifyDecision:
    """Final decision from the policy engine.

    Immutable result (ARCH-29). Business result via return type (ARCH-20).

    Args:
        passed: Whether the overall verification passed.
        verdict: Endentscheidung als ``PolicyVerdict``-Enum
            (``PASS`` oder ``FAIL``).
        layer_results: Tuple of all layer results that contributed.
        all_findings: Flattened tuple of all findings from all layers.
        blocking_findings: Tuple of findings that caused failure.
        summary: Human-readable summary of the decision.
    """

    passed: bool
    verdict: PolicyVerdict
    layer_results: tuple[LayerResult, ...]
    all_findings: tuple[Finding, ...]
    blocking_findings: tuple[Finding, ...]
    summary: str

    @property
    def status(self) -> str:
        """Wire-Repraesentation des Verdicts.

        Liefert ausschliesslich ``"PASS"`` oder ``"FAIL"`` gemaess
        FK-27 §27.7.2 und ``PolicyVerdict`` (AG3-021); weitere
        Zwischenwerte sind nicht zulaessig.
        """
        return self.verdict.value


class PolicyEngine:
    """Layer 4: Deterministic aggregation.

    Applies the following rules in order:

    1. ANY BLOCKING finding from SYSTEM trust -> FAIL.
    2. More than ``max_major_findings`` MAJOR findings from any trust -> FAIL.
    3. Otherwise -> PASS (warnings/minor findings tolerated).

    Configurable thresholds via constructor.
    """

    def __init__(self, max_major_findings: int = 0) -> None:
        """Initialise the policy engine.

        Args:
            max_major_findings: Maximum number of MAJOR findings tolerated
                before they become blocking. Default ``0`` (any MAJOR
                blocks, identical to the v2 ``max_high_findings=0``
                threshold pre-rename).
        """
        self._max_major = max_major_findings

    def decide(self, layer_results: list[LayerResult]) -> VerifyDecision:
        """Produce a final decision from all layer results.

        Args:
            layer_results: List of results from all QA layers.

        Returns:
            A ``VerifyDecision`` with the aggregated outcome
            (``PolicyVerdict.PASS`` or ``PolicyVerdict.FAIL``).
        """
        results_tuple = tuple(layer_results)

        # Flatten all findings
        all_findings: list[Finding] = []
        for lr in layer_results:
            all_findings.extend(lr.findings)

        all_findings_tuple = tuple(all_findings)

        # Identify blocking findings
        blocking = _compute_blocking(all_findings, self._max_major)
        blocking_tuple = tuple(blocking)

        # Determine verdict — only PASS/FAIL per FK-27 §27.7.2.
        if blocking_tuple:
            verdict = PolicyVerdict.FAIL
            passed = False
            summary = _build_fail_summary(blocking_tuple)
        elif all_findings_tuple:
            verdict = PolicyVerdict.PASS
            passed = True
            summary = _build_warnings_summary(all_findings_tuple)
        else:
            verdict = PolicyVerdict.PASS
            passed = True
            summary = "All QA layers passed with no findings."

        return VerifyDecision(
            passed=passed,
            verdict=verdict,
            layer_results=results_tuple,
            all_findings=all_findings_tuple,
            blocking_findings=blocking_tuple,
            summary=summary,
        )


def _compute_blocking(
    findings: list[Finding],
    max_major: int,
) -> list[Finding]:
    """Determine which findings are blocking.

    Rules:
    - Any BLOCKING finding from SYSTEM trust blocks immediately.
    - If total MAJOR findings (any trust) exceed ``max_major``, all
      MAJOR findings block.

    Args:
        findings: All findings to evaluate.
        max_major: Maximum number of MAJOR findings allowed before
            they become blocking.

    Returns:
        List of blocking findings.
    """
    blocking: list[Finding] = []

    # Rule 1: BLOCKING from SYSTEM trust blocks immediately.
    system_blockers = [
        f for f in findings
        if f.trust_class == TrustClass.SYSTEM
        and f.severity == Severity.BLOCKING
    ]
    blocking.extend(system_blockers)

    # Rule 2: Too many MAJOR findings (any trust) become blocking.
    all_major = [f for f in findings if f.severity == Severity.MAJOR]
    if len(all_major) > max_major:
        for f in all_major:
            if f not in blocking:
                blocking.append(f)

    return blocking


def _build_fail_summary(blocking: tuple[Finding, ...]) -> str:
    """Build a human-readable summary for FAIL decisions.

    Args:
        blocking: Tuple of blocking findings.

    Returns:
        Summary string listing blocking finding count and details.
    """
    blocking_count = sum(
        1 for f in blocking if f.severity == Severity.BLOCKING
    )
    major_count = sum(1 for f in blocking if f.severity == Severity.MAJOR)
    parts: list[str] = []
    if blocking_count:
        parts.append(f"{blocking_count} blocking")
    if major_count:
        parts.append(f"{major_count} major")
    detail = ", ".join(parts)
    return f"FAIL: {len(blocking)} blocking finding(s) ({detail})."


def _build_warnings_summary(findings: tuple[Finding, ...]) -> str:
    """Build a human-readable summary for PASS decisions that carry
    non-blocking findings.

    Args:
        findings: Tuple of all (non-blocking) findings.

    Returns:
        Summary string with finding counts by severity.
    """
    counts: dict[str, int] = {}
    for f in findings:
        counts[f.severity.value] = counts.get(f.severity.value, 0) + 1
    parts = [f"{count} {sev}" for sev, count in counts.items()]
    detail = ", ".join(parts)
    return f"PASS with warnings: {len(findings)} finding(s) ({detail})."
