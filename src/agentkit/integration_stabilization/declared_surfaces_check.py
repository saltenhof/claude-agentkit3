"""``declared_surfaces_only`` — deterministic Layer-1 structural check.

FK-05 §5.10 / FK-37 §37.1.3 / Invariant: declared_surfaces_only_is_deterministic.

Compares actually-touched surfaces (from the diff) against the declared
surfaces in the integration scope manifest, the seam allowlist, and the
active repo set. Any undeclared touch is a BLOCKING finding.

This check is 100% deterministic: no LLM path, no external calls.
It is registered as a Layer-1 structural check (ARCH-06 GovernanceGuard
compatible signature) and also runs inside the seam_allowlist guard.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

from agentkit.core_types import Severity
from agentkit.verify_system.protocols import Finding, TrustClass

if TYPE_CHECKING:
    from agentkit.integration_stabilization.models import IntegrationScopeManifest

__all__ = [
    "DeclaredSurfacesCheckResult",
    "check_declared_surfaces_only",
    "is_path_within_seam_allowlist",
]


@dataclass(frozen=True)
class DeclaredSurfacesCheckResult:
    """Result of the ``declared_surfaces_only`` deterministic check.

    Attributes:
        passed: True iff all touched paths are within declared surfaces.
        undeclared_paths: Paths that are not covered by any declared seam.
        findings: Structural findings (one per undeclared path, BLOCKING).
    """

    passed: bool
    undeclared_paths: tuple[str, ...]
    findings: tuple[Finding, ...]


def is_path_within_seam_allowlist(
    path: str,
    *,
    seam_allowlist: tuple[str, ...],
) -> bool:
    """Return True iff ``path`` is within any declared seam.

    A path is ``within`` a seam entry if it exactly equals the entry or
    is a sub-path of it (uses ``os.path`` prefix semantics, the same
    approach as ``ScopeGuard``).

    Args:
        path: The file path to check (will be normpath'd).
        seam_allowlist: Tuple of declared seam path prefixes.

    Returns:
        True iff the path is covered by at least one seam entry.
    """
    norm = os.path.normpath(path)
    for seam in seam_allowlist:
        norm_seam = os.path.normpath(seam)
        if norm == norm_seam or norm.startswith(norm_seam + os.sep):
            return True
    return False


def check_declared_surfaces_only(
    *,
    touched_paths: tuple[str, ...],
    manifest: IntegrationScopeManifest,
    seam_allowlist: tuple[str, ...] | None = None,
    quarantined_deltas: tuple[str, ...] = (),
) -> DeclaredSurfacesCheckResult:
    """Check that every touched path is within the declared surfaces.

    Deterministic Layer-1 check (invariant: declared_surfaces_only_is_deterministic).
    No LLM path. Compares ``touched_paths`` against:
    - ``manifest.target_seams`` (the primary declared integration seams)
    - ``manifest.allowed_repos_paths`` (the allowed repo-set boundary)
    - ``seam_allowlist`` (the materialized guard-overlay allowlist, if provided)

    An undeclared touch is a BLOCKING finding (FK-05 §5.10).

    AG3-069 (AC10, FK-05 §5.7/§5.13): a touched path that matches a QUARANTINED
    pre-snapshot cross-scope delta is BLOCKING even when it falls within a
    declared seam — reclassification must NOT retroactively legalize a
    pre-manifest delta (invariant
    ``reclassification_may_not_legalize_pre_manifest_cross_scope_delta``).

    Args:
        touched_paths: Paths actually touched in the diff (from the worker).
        manifest: The active integration scope manifest.
        seam_allowlist: Optional materialized seam allowlist. When provided,
            paths within it are also considered declared.
        quarantined_deltas: Pre-snapshot cross-scope deltas read from the
            reclassification quarantine state. A touched path matching one of
            these is BLOCKING regardless of seam membership (not legalized).

    Returns:
        A ``DeclaredSurfacesCheckResult`` with PASS or BLOCKING findings.
    """
    # Build the combined declared-surface set from manifest seams + allowed paths
    # + optional materialized seam_allowlist.
    combined_allowlist: tuple[str, ...] = (
        *manifest.target_seams,
        *manifest.allowed_repos_paths,
        *(seam_allowlist or ()),
    )

    quarantine_set = {os.path.normpath(d) for d in quarantined_deltas}

    undeclared: list[str] = []
    quarantined_touched: list[str] = []
    for path in touched_paths:
        norm = os.path.normpath(path)
        if norm in quarantine_set:
            # A pre-snapshot quarantined delta is NEVER legalized by the IS
            # contract, even inside a declared seam (FK-05 §5.7/§5.13).
            quarantined_touched.append(path)
            continue
        if not is_path_within_seam_allowlist(path, seam_allowlist=combined_allowlist):
            undeclared.append(path)

    if not undeclared and not quarantined_touched:
        return DeclaredSurfacesCheckResult(
            passed=True,
            undeclared_paths=(),
            findings=(),
        )

    findings = tuple(
        Finding(
            layer="structural",
            check="integration.declared_surfaces_only",
            severity=Severity.BLOCKING,
            message=(
                f"Undeclared surface touched: {path!r}. "
                "Path is not within any declared seam, allowed repo path, "
                "or seam allowlist (FK-05 §5.10, invariant: "
                "declared_surfaces_only_is_deterministic)."
            ),
            trust_class=TrustClass.SYSTEM,
        )
        for path in undeclared
    ) + tuple(
        Finding(
            layer="structural",
            check="integration.declared_surfaces_only",
            severity=Severity.BLOCKING,
            message=(
                f"Quarantined pre-snapshot cross-scope delta touched: {path!r}. "
                "A pre-manifest delta is NOT retroactively legalized by "
                "reclassification (FK-05 §5.7/§5.13, invariant: "
                "reclassification_may_not_legalize_pre_manifest_cross_scope_delta)."
            ),
            trust_class=TrustClass.SYSTEM,
        )
        for path in quarantined_touched
    )

    return DeclaredSurfacesCheckResult(
        passed=False,
        undeclared_paths=(*undeclared, *quarantined_touched),
        findings=findings,
    )
