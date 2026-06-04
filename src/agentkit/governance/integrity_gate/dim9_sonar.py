"""IntegrityGate Dimension 9 — SonarQube-Green (FK-35 §35.2.4a, consumes AG3-052).

Dimension 9 **verifies** the commit-bound ``sonarqube_gate`` attestation that
the (out-of-scope) Closure pre-merge scan produced — it **never runs a Sonar
scan of its own** (FK-35 §35.2.4a "verifiziert nur — vermisst nicht neu").  All
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
    from agentkit.governance.integrity_gate import DimensionResult
    from agentkit.verify_system.sonarqube_gate import (
        SonarApplicability,
        SonarGateOutcome,
    )

#: Canonical FK-35 §35.2.4a FAIL-code for a non-green Dim-9 verdict.
SONAR_NOT_GREEN = "SONAR_NOT_GREEN"


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


__all__ = [
    "SONAR_NOT_GREEN",
    "Dim9Resolution",
    "SonarDimensionPort",
    "verify_sonarqube_green",
]
