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
from agentkit.verify_system.protocols import (
    Finding,
    LayerResult,
    Severity,
    TrustClass,
)

#: Trust classes whose findings are permitted to block (DK-04 §4.2 /
#: FK-33 §33.5). Trust A (``SYSTEM``) and Trust B (``VERIFIED_LLM``) are
#: authoritative enough to block; Trust C (``WORKER_ASSERTION``) is the
#: worker's own self-report and — per the DK-04 §4.2 / FK-33 §33.5.2
#: Kernregel "Klasse C darf nie blocking sein" (FK-07-008) — must NEVER
#: block: the agent must not be able to pass its own check. This frozenset
#: is the single source of truth for "may a finding of this trust class
#: contribute a blocking decision"; both blocking rules in
#: :func:`_compute_blocking` funnel through :func:`_trust_can_block`.
_BLOCKING_TRUST_CLASSES: frozenset[TrustClass] = frozenset(
    (TrustClass.SYSTEM, TrustClass.VERIFIED_LLM)
)


def _trust_can_block(finding: Finding) -> bool:
    """Return whether a finding's trust class may contribute to a FAIL.

    Single trust-class blocking predicate over :data:`_BLOCKING_TRUST_CLASSES`
    (DK-04 §4.2 / FK-33 §33.5.2): Trust A (``SYSTEM``) and Trust B
    (``VERIFIED_LLM``) may block, Trust C (``WORKER_ASSERTION``) may NEVER
    block. All blocking decisions in :func:`_compute_blocking` funnel through
    here so the trust-class block rule stays a single source of truth (no
    second blocking truth, FIX THE MODEL).

    Args:
        finding: The finding to classify.

    Returns:
        ``True`` iff ``finding.trust_class`` is in
        :data:`_BLOCKING_TRUST_CLASSES`.
    """
    return finding.trust_class in _BLOCKING_TRUST_CLASSES


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
        max_major_findings: The MAJOR-findings threshold this decision was
            taken under (FK-27 §27.7.2).  Persisted into the decision artefact
            as ``major_threshold`` so the IntegrityGate Dim 4 (DECISION_INVALID,
            FK-35 §35.2.4) can verify the canonical policy record carries it.
    """

    passed: bool
    verdict: PolicyVerdict
    layer_results: tuple[LayerResult, ...]
    all_findings: tuple[Finding, ...]
    blocking_findings: tuple[Finding, ...]
    summary: str
    max_major_findings: int = 0

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

    1. A ``Severity.BLOCKING`` finding whose trust class *may block*
       (Trust A ``SYSTEM`` or Trust B ``VERIFIED_LLM``, see
       :func:`_trust_can_block`) -> FAIL. ``BLOCKING`` is the *unconditional*,
       *schwellenunabhaengige* severity (FK-27 §27.4.2): such a finding blocks
       the QA-subflow hard, independent of ``max_major_findings``. This covers
       both the Trust-A structural/Sonar blockers AND a Trust-B Layer-2 FAIL --
       FK-33 §33.8.2 / FK-34 §34.2.5: "jeder [Layer-2] FAIL blockiert
       (FK-05-164)", which is threshold-independent. A Trust-C
       (``WORKER_ASSERTION``) finding NEVER blocks here (DK-04 §4.2 / FK-33
       §33.5.2 Kernregel "Klasse C darf nie blocking sein", FK-07-008) -- the
       worker must not be able to pass its own check. This is the SINGLE
       blocking truth; there is no second gate.
    2. More than ``max_major_findings`` MAJOR findings (any blocking-eligible
       trust) -> FAIL.
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
            max_major_findings=self._max_major,
        )


def _compute_blocking(
    findings: list[Finding],
    max_major: int,
) -> list[Finding]:
    """Determine which findings are blocking.

    Only findings whose trust class *may block* (:func:`_trust_can_block` --
    Trust A ``SYSTEM`` / Trust B ``VERIFIED_LLM``) are ever considered. Trust C
    (``WORKER_ASSERTION``) findings are filtered out up front and can NEVER
    contribute a blocking decision, neither via the BLOCKING-severity rule nor
    via the MAJOR-threshold rule (DK-04 §4.2 / FK-33 §33.5.2 Kernregel "Klasse
    C darf nie blocking sein", FK-07-008). This single trust filter is the one
    place the trust-class rule lives (no second blocking truth, FIX THE MODEL).

    Rules (applied to blocking-eligible findings only):
    - Any ``Severity.BLOCKING`` finding blocks immediately and
      *schwellenunabhaengig* (FK-27 §27.4.2): ``BLOCKING`` is the unconditional
      severity. This realises both the Trust-A structural/Sonar block AND the
      FK-33 §33.8.2 / FK-34 §34.2.5 "jeder Layer-2 FAIL blockiert" rule (a
      Layer-2 FAIL maps to a Trust-B ``BLOCKING`` finding, not a
      threshold-gated MAJOR).
    - If total MAJOR findings exceed ``max_major``, all MAJOR findings block.

    Args:
        findings: All findings to evaluate.
        max_major: Maximum number of MAJOR findings allowed before
            they become blocking.

    Returns:
        List of blocking findings.
    """
    eligible = [f for f in findings if _trust_can_block(f)]

    blocking: list[Finding] = []

    # Rule 1: any BLOCKING-severity finding blocks immediately, INDEPENDENT of
    # max_major (FK-27 §27.4.2 BLOCKING = hard) -- but only for trust classes
    # that may block (Trust C already filtered out above).
    severity_blockers = [
        f for f in eligible if f.severity == Severity.BLOCKING
    ]
    blocking.extend(severity_blockers)

    # Rule 2: Too many MAJOR findings (blocking-eligible trust) become blocking.
    all_major = [f for f in eligible if f.severity == Severity.MAJOR]
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
