"""IntegrityGate Dimension 9 — SonarQube-Green (FK-35 §35.2.4a, consumes AG3-052).

Dimension 9 **verifies** the commit-bound ``sonarqube_gate`` attestation that
the (out-of-scope) Closure pre-merge scan produced — it **never runs a Sonar
scan of its own** (FK-35 §35.2.4a "verifies only — never re-scans").  All
Sonar semantics (commit-binding/stale-check, Broken-Window green criterion,
ledger reconcile, 3-state applicability) live in the
``verify_system.sonarqube_gate`` capability (AG3-052); this module is a thin
CONSUMER of that API and introduces **no second Sonar truth** (AK12, AG3-034
Remediation R2-C/A2).

The capability boundary is the injected :class:`SonarDimensionPort`: it resolves
the per-run applicability and the canonical AG3-052 :class:`SonarGateOutcome`
(produced by :func:`evaluate_sonarqube_gate` over the commit-bound attestation,
ledger, issues and post-apply re-read).  Dim 9 then merely **maps** that
capability outcome onto the integrity ``DimensionResult`` — it re-implements
none of the §35.2.4a verification conditions itself (no ``_verification_failure``
clone, no second gate mechanic).  ``governance`` never imports the SonarQube
adapter directly — the port is the seam, so unit tests stub only the
capability/HTTP boundary (MOCKS exception) while the applicability +
verification logic runs through the real :func:`evaluate_sonarqube_gate` /
:func:`resolve_for_context` (FK-33 §33.6.5).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from agentkit.governance.integrity_gate.dimensions import IntegrityDimension

if TYPE_CHECKING:
    from agentkit.config.models import SonarQubeConfig
    from agentkit.governance.integrity_gate import DimensionResult
    from agentkit.verify_system.sonarqube_gate import (
        SonarApplicability,
        SonarGateOutcome,
    )
    from agentkit.verify_system.sonarqube_gate.attestation import SonarAttestation

#: Canonical FK-35 §35.2.4a FAIL-code for a non-green Dim-9 verdict.
SONAR_NOT_GREEN = "SONAR_NOT_GREEN"


@dataclass(frozen=True)
class FreshAttestation:
    """The fresh, commit-bound attestation the Closure pre-merge scan produced.

    FK-29 §29.1a.3 / FK-35 §35.2.4a: in the Closure pre-merge barrier Dimension 9
    verifies the FRESH attestation the integrated-candidate Sonar scan (AG3-056)
    produced — it MUST NOT re-read the worktree's local ``.scannerwork`` (the
    stale-local-read path the predecessor failure removed). The barrier supplies
    THIS object to :meth:`IntegrityGate.evaluate`; Dim 9 evaluates exactly it.

    Attributes:
        attestation: The fresh, commit-bound ``SonarAttestation`` from the scan.
        expected_main_revision: The integrated-candidate commit the attestation
            MUST be bound to (``last_analyzed_revision`` == this). For the
            integrated candidate this is the candidate commit, not ``main`` HEAD
            (the scan analysed the integrated candidate, FK-29 §29.1a.3 d).
        config: The project ``sonarqube`` config (FK-03) — the authoritative
            source for the Dim-9 version-drift comparison (§35.2.4a item 5).
            ``None`` only when the truth-boundary read could not resolve it; the
            barrier never supplies a fresh attestation without a config, so a
            ``None`` here on a supplied attestation is a fail-closed drift.
        gate_outcome: The FULL AG3-052 :class:`SonarGateOutcome` the pre-merge
            scan produced over THIS run's analysis (FIX-1). Dim 9 consumes
            ``gate_outcome.passed`` as the green verdict — the SAME green truth
            as the impl-phase gate (Single-Match ledger reconciler + post-apply
            QG/open-issue re-read + Broken-Window overall-zero). Dim 9 NEVER
            re-derives green from the raw ``attestation.quality_gate_status``
            (that pre-apply status is only used for the commit-binding
            stale-check). A ``None`` here on a supplied attestation is a
            fail-closed gap (no gate evaluation = unverifiable green).
    """

    attestation: SonarAttestation
    expected_main_revision: str
    config: SonarQubeConfig | None
    gate_outcome: SonarGateOutcome | None


@dataclass(frozen=True)
class Dim9Resolution:
    """The capability-resolved Dim-9 inputs (AG3-052 output, not a second truth).

    The :class:`SonarDimensionPort` resolves this once per gate run from the
    ``sonarqube_gate`` capability: it carries the resolved 3-state applicability
    (FK-33 §33.6.5) and — for an APPLICABLE run — the canonical
    :class:`SonarGateOutcome` that :func:`evaluate_sonarqube_gate` produced over
    the commit-bound attestation.  Dim 9 only MAPS this onto a
    :class:`DimensionResult`; it never re-evaluates the §35.2.4a conditions.

    Attributes:
        applicability: Resolved 3-state applicability (FK-33 §33.6.5).  Dim 9 is
            only verified when ``APPLICABLE`` (the non-applicable resolutions are
            dropped upstream via ``dimensions_for(sonar_applicable=...)``).
        outcome: The AG3-052 capability outcome for an APPLICABLE run, or
            ``None`` for a not-applicable resolution (no Sonar verdict produced).
    """

    applicability: SonarApplicability
    outcome: SonarGateOutcome | None


class SonarDimensionPort(Protocol):
    """Capability seam for Dim 9 (``verify_system.sonarqube_gate``).

    Implementations resolve the commit-bound Sonar verification for the
    integrated pre-merge state of the given run by CONSUMING the AG3-052
    capability (``build_sonar_gate_port_for_run`` -> ``resolve_inputs`` ->
    ``evaluate_sonarqube_gate``).  The seam keeps ``governance`` free of any
    direct SonarQube adapter import (the capability is the boundary, AK12).
    """

    def resolve_dim9_outcome(self, gate_ctx: object) -> Dim9Resolution:
        """Return the per-run Dim-9 capability resolution (capability boundary)."""
        ...


def verify_sonarqube_green(resolution: Dim9Resolution) -> DimensionResult:
    """Dim 9 — map the AG3-052 capability outcome onto a ``DimensionResult``.

    Consumes the canonical :class:`SonarGateOutcome` that
    :func:`evaluate_sonarqube_gate` produced (commit-binding/stale-check via
    :meth:`SonarAttestation.is_bound_to`, Broken-Window overall-code green via
    :func:`is_green_status`, ledger reconcile, post-apply re-read — all inside
    the AG3-052 capability).  Dim 9 re-implements NONE of those conditions: a
    green capability outcome -> PASS; any other -> FAIL closed with
    ``SONAR_NOT_GREEN`` (the caller escalates, FK-35 §35.2.4a / §35.2.9).  Only
    invoked for an APPLICABLE Dim 9; a not-applicable resolution is dropped
    upstream (``dimensions_for(sonar_applicable=...)``).

    A missing capability outcome on an APPLICABLE resolution is a
    configured-but-unreachable Sonar -> fail-closed (never a silent pass).

    Args:
        resolution: The capability-resolved Dim-9 inputs (applicability +
            AG3-052 outcome).

    Returns:
        The :class:`DimensionResult` for Dim 9.
    """
    from agentkit.governance.integrity_gate import DimensionResult

    dim = IntegrityDimension.SONARQUBE_GREEN
    outcome = resolution.outcome
    if outcome is None:
        # APPLICABLE but the capability produced no outcome (no commit-bound
        # attestation resolvable) -> configured-but-unreachable -> fail-closed.
        return DimensionResult(
            dimension=dim,
            passed=False,
            failure_reason=SONAR_NOT_GREEN,
            detail=(
                "sonarqube_gate APPLICABLE but the AG3-052 capability produced no "
                "outcome (configured-but-unreachable -> fail-closed, FK-35 §35.2.4a)"
            ),
        )
    if outcome.passed:
        return DimensionResult(
            dimension=dim,
            passed=True,
            detail=(
                "Commit-bound Sonar attestation green via AG3-052 "
                f"(gate_status={outcome.gate_status}, FK-35 §35.2.4a)"
            ),
        )
    return DimensionResult(
        dimension=dim,
        passed=False,
        failure_reason=SONAR_NOT_GREEN,
        detail=(
            f"AG3-052 gate_status={outcome.gate_status}: {outcome.failure_reason}"
        ),
    )


def verify_fresh_attestation(fresh: FreshAttestation) -> DimensionResult:
    """Dim 9 — verify the FRESH pre-merge attestation (FK-35 §35.2.4a, no re-read).

    The canonical Closure pre-merge path (FK-29 §29.1a.3): the integrated-
    candidate Sonar scan (AG3-056) PRODUCED this fresh attestation AND ran the
    FULL AG3-052 gate over its analysis; Dim 9 here VERIFIES exactly those and
    NEVER re-reads the worktree's local ``.scannerwork`` and NEVER recomputes
    green itself. The verdict reuses the AG3-052 capability outcome over the
    SUPPLIED attestation (no second Sonar truth):

    1. commit-binding / stale-check via :meth:`SonarAttestation.is_bound_to`
       against the integrated-candidate revision (a green status for a different
       revision is invalid, FK-33 §33.6.3);
    2. config/version drift via :func:`detect_version_drift` (FK-35 §35.2.4a item
       5 — the tool versions must match the FK-03 expected pins; the hash
       baseline is a reported gap, see :mod:`.dim9_drift`);
    3. quality-gate green via the FULL AG3-052 :class:`SonarGateOutcome`
       (``gate_outcome.passed``) the pre-merge scan produced (FIX-1) — the
       Single-Match ledger reconciler, the accepted-exception transition, the
       post-apply QG/open-issue re-read and the Broken-Window overall-zero
       criterion (open non-accepted == 0) all ran inside the AG3-052 gate. Dim 9
       does NOT re-derive green from the raw ``attestation.quality_gate_status``
       (that pre-apply status is only the stale-check input above); it consumes
       exactly the gate outcome and issues NO second Sonar read (and never the
       worktree-local ``.scannerwork`` read AG3-056 removed).

    Any failure is a fail-closed ``SONAR_NOT_GREEN`` (the caller escalates,
    FK-35 §35.2.4a / §35.2.9). Only invoked for an APPLICABLE Closure run that
    carries a fresh attestation.

    Args:
        fresh: The fresh, commit-bound attestation + its expected binding, the
            FK-03 config for drift detection, and the AG3-052 gate outcome.

    Returns:
        The :class:`DimensionResult` for Dim 9.
    """
    from agentkit.governance.integrity_gate import DimensionResult
    from agentkit.governance.integrity_gate.dim9_drift import detect_version_drift

    dim = IntegrityDimension.SONARQUBE_GREEN
    attestation = fresh.attestation

    if not attestation.is_bound_to(fresh.expected_main_revision):
        return _fresh_fail(
            "fresh attestation not bound to the integrated candidate: "
            f"last_analyzed_revision={attestation.last_analyzed_revision!r} != "
            f"candidate={fresh.expected_main_revision!r} (drift scan<->merge)"
        )

    if fresh.config is None:
        # A supplied fresh attestation without a config cannot have its versions
        # verified against the FK-03 expectation -> fail-closed (never a green
        # verdict measured against an unverifiable toolchain, §35.2.4a item 5).
        return _fresh_fail(
            "fresh attestation supplied without an FK-03 sonarqube config: cannot "
            "verify config/version drift (FK-35 §35.2.4a item 5) -> fail-closed"
        )

    drift = detect_version_drift(attestation, fresh.config)
    if drift.drifted:
        return _fresh_fail(drift.reason or "config/version drift (FK-35 §35.2.4a)")

    # FIX-1: the green verdict is the FULL AG3-052 gate outcome the scan
    # produced, NOT the raw pre-apply quality_gate_status (that would bypass the
    # ledger reconciler, the post-apply re-read and the Broken-Window check). A
    # missing gate outcome on a supplied fresh attestation is an unverifiable
    # green -> fail-closed (the scan owns the gate run, FK-29 §29.1a.3 d).
    outcome = fresh.gate_outcome
    if outcome is None:
        return _fresh_fail(
            "fresh attestation supplied without an AG3-052 gate outcome: cannot "
            "verify green without the full gate evaluation (Single-Match ledger "
            "reconcile + post-apply re-read + Broken-Window) -> fail-closed (FIX-1)"
        )
    if not outcome.passed:
        return _fresh_fail(
            "fresh integrated-candidate Sonar gate not green: "
            f"gate_status={outcome.gate_status}: {outcome.failure_reason} "
            "(FULL AG3-052 gate over the fresh analysis, FK-35 §35.2.4a)"
        )

    return DimensionResult(
        dimension=dim,
        passed=True,
        detail=(
            "fresh integrated-candidate attestation verified green via the FULL "
            "AG3-052 gate + no config/version drift "
            f"(analysis_id={attestation.analysis_id}, "
            f"gate_status={outcome.gate_status}, FK-35 §35.2.4a)"
        ),
    )


def _fresh_fail(detail: str) -> DimensionResult:
    """Build a fail-closed Dim-9 result for a fresh-attestation verification."""
    from agentkit.governance.integrity_gate import DimensionResult

    return DimensionResult(
        dimension=IntegrityDimension.SONARQUBE_GREEN,
        passed=False,
        failure_reason=SONAR_NOT_GREEN,
        detail=detail,
    )


__all__ = [
    "SONAR_NOT_GREEN",
    "Dim9Resolution",
    "FreshAttestation",
    "SonarDimensionPort",
    "verify_fresh_attestation",
    "verify_sonarqube_green",
]
