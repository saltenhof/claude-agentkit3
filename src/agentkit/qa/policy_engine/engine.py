"""Policy engine -- deterministic aggregation of QA layer results.

Takes LayerResults from all layers, applies trust weighting, and
produces a final PASS/FAIL decision. No LLM, no side effects (ARCH-12).
"""

from __future__ import annotations

from dataclasses import dataclass

from agentkit.qa.protocols import Finding, LayerResult, Severity, TrustClass


@dataclass(frozen=True)
class VerifyDecision:
    """Final decision from the policy engine.

    Immutable result (ARCH-29). Business result via return type (ARCH-20).

    Args:
        passed: Whether the overall verification passed.
        status: Decision status string (``"PASS"``, ``"FAIL"``,
            ``"PASS_WITH_WARNINGS"``).
        layer_results: Tuple of all layer results that contributed.
        all_findings: Flattened tuple of all findings from all layers.
        blocking_findings: Tuple of findings that caused failure.
        summary: Human-readable summary of the decision.
    """

    passed: bool
    status: str
    layer_results: tuple[LayerResult, ...]
    all_findings: tuple[Finding, ...]
    blocking_findings: tuple[Finding, ...]
    summary: str


class PolicyEngine:
    """Layer 4: Deterministic aggregation.

    Applies the following rules in order:

    1. ANY critical finding from SYSTEM trust -> FAIL.
    2. ANY high finding from SYSTEM trust -> FAIL.
    3. More than ``max_high_findings`` high findings from any trust -> FAIL.
    4. Only medium/low/info findings -> PASS_WITH_WARNINGS.
    5. No findings -> PASS.

    Configurable thresholds via constructor.
    """

    def __init__(self, max_high_findings: int = 0) -> None:
        self._max_high = max_high_findings

    def decide(self, layer_results: list[LayerResult]) -> VerifyDecision:
        """Produce a final decision from all layer results.

        Args:
            layer_results: List of results from all QA layers.

        Returns:
            A ``VerifyDecision`` with the aggregated outcome.
        """
        results_tuple = tuple(layer_results)

        # Flatten all findings
        all_findings: list[Finding] = []
        for lr in layer_results:
            all_findings.extend(lr.findings)

        all_findings_tuple = tuple(all_findings)

        # Identify blocking findings
        blocking = _compute_blocking(all_findings, self._max_high)
        blocking_tuple = tuple(blocking)

        # Determine status
        if blocking_tuple:
            status = "FAIL"
            passed = False
            summary = _build_fail_summary(blocking_tuple)
        elif all_findings_tuple:
            status = "PASS_WITH_WARNINGS"
            passed = True
            summary = _build_warnings_summary(all_findings_tuple)
        else:
            status = "PASS"
            passed = True
            summary = "All QA layers passed with no findings."

        return VerifyDecision(
            passed=passed,
            status=status,
            layer_results=results_tuple,
            all_findings=all_findings_tuple,
            blocking_findings=blocking_tuple,
            summary=summary,
        )


def _compute_blocking(
    findings: list[Finding],
    max_high: int,
) -> list[Finding]:
    """Determine which findings are blocking.

    Rules:
    - Any CRITICAL finding from SYSTEM trust blocks.
    - Any HIGH finding from SYSTEM trust blocks.
    - If total HIGH findings (any trust) exceed ``max_high``, all HIGH
      findings block.

    Args:
        findings: All findings to evaluate.
        max_high: Maximum number of HIGH findings allowed before
            they become blocking.

    Returns:
        List of blocking findings.
    """
    blocking: list[Finding] = []

    # Rule 1 & 2: CRITICAL or HIGH from SYSTEM trust
    system_blockers = [
        f for f in findings
        if f.trust_class == TrustClass.SYSTEM
        and f.severity in (Severity.CRITICAL, Severity.HIGH)
    ]
    blocking.extend(system_blockers)

    # Rule 3: Too many HIGH findings from any trust
    all_high = [f for f in findings if f.severity == Severity.HIGH]
    if len(all_high) > max_high:
        for f in all_high:
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
    critical_count = sum(1 for f in blocking if f.severity == Severity.CRITICAL)
    high_count = sum(1 for f in blocking if f.severity == Severity.HIGH)
    parts: list[str] = []
    if critical_count:
        parts.append(f"{critical_count} critical")
    if high_count:
        parts.append(f"{high_count} high")
    detail = ", ".join(parts)
    return f"FAIL: {len(blocking)} blocking finding(s) ({detail})."


def _build_warnings_summary(findings: tuple[Finding, ...]) -> str:
    """Build a human-readable summary for PASS_WITH_WARNINGS decisions.

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
