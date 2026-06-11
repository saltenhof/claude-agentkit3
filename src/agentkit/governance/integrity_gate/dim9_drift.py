"""IntegrityGate Dimension 9 — config/version drift check (FK-35 §35.2.4a item 5).

FK-35 §35.2.4a item 5 requires Dimension 9 to confirm that the fresh
attestation's ``quality_gate_hash`` / ``quality_profile_hash`` /
``analysis_scope_hash`` / ``new_code_definition`` AND the SonarQube /
Community-Branch-Plugin / Scanner versions "match the values expected for the
project (FK-03 ``sonarqube`` config + config hash). Drift here means the analysis
was measured against a different rule set — FAIL."

This module verifies the part of that rule that has an AUTHORITATIVE expected
source in code today: the TOOL VERSIONS, which are directly derivable from the
FK-03 ``sonarqube`` config (``min_version``, ``plugins.community_branch
.min_version`` and the pinned ``scanner_version``). The attestation's measured
versions are compared against those pins; a measured version BELOW the configured
minimum (SonarQube / branch plugin) or a measured scanner version DIFFERENT from
the pinned scanner version is drift = FAIL (the analysis ran against a different
toolchain than the one declared for the project).

THE HASH BASELINE IS A KNOWN, REPORTED GAP (AG3-053 stop-and-report, briefing
§4b/§10). FK-35 §35.2.4a item 5 also wants the four CONFIG HASHES
(``quality_gate_hash`` / ``quality_profile_hash`` / ``analysis_scope_hash`` /
``new_code_definition``) compared against an EXPECTED baseline. That baseline is
NOT a value derivable from FK-03 config: the hashes are COMPUTED at scan time
from the live SonarQube Web-API (see
``verify_system.sonarqube_gate.integrity_hashes``), and there is currently NO
captured/registered baseline for them anywhere in the concept or the code (the
Setup green-main precondition reads green/stale but persists no baseline
attestation, and the state backend stores no expected config-hash). Inventing a
baseline contract here would be a concept decision for the human, so this module
deliberately does NOT fabricate one. :func:`detect_version_drift` performs the
version-drift check now and returns a typed result; the hash comparison is left
to a future, human-defined baseline source (see the story stop-and-report).

The check is fail-closed: a measured version that cannot be parsed as SemVer is
drift (an attestation must never carry an unparseable toolchain version into a
green verdict).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agentkit.config.models import SonarQubeConfig
    from agentkit.verify_system.sonarqube_gate.attestation import SonarAttestation


@dataclass(frozen=True)
class DriftResult:
    """Result of the Dim-9 config/version drift comparison (FK-35 §35.2.4a item 5).

    Attributes:
        drifted: ``True`` when the measured toolchain versions do not match the
            FK-03 expected pins (a fail-closed Dim-9 FAIL).
        reason: A machine reason naming the drifting field(s); ``None`` when no
            drift was detected.
    """

    drifted: bool
    reason: str | None = None


def detect_version_drift(
    attestation: SonarAttestation,
    config: SonarQubeConfig,
) -> DriftResult:
    """Compare the attestation's tool versions against the FK-03 config pins.

    FK-35 §35.2.4a item 5: the SonarQube / Community-Branch-Plugin / Scanner
    versions of the fresh attestation must match the values expected for the
    project (FK-03 ``sonarqube`` config). Concretely:

    * ``sonarqube_version`` must be >= ``config.min_version``;
    * ``branch_plugin_version`` must be >= ``config.plugins.community_branch
      .min_version``;
    * ``scanner_version`` must EQUAL the pinned ``config.scanner_version`` (when
      a version is pinned) — the scanner version is an exact AK3-controlled pin,
      not a minimum.

    Drift in any of these means the analysis was measured against a different
    toolchain than the one declared for the project => FAIL (fail-closed).

    Args:
        attestation: The fresh, commit-bound attestation under verification.
        config: The project ``sonarqube`` config (FK-03), the authoritative
            source of the expected versions.

    Returns:
        A :class:`DriftResult` (``drifted=True`` with a reason on any mismatch).
    """
    reasons: list[str] = []

    sq = _version_below_minimum(
        attestation.sonarqube_version, config.min_version, field="sonarqube_version"
    )
    if sq is not None:
        reasons.append(sq)

    plugin = _version_below_minimum(
        attestation.branch_plugin_version,
        config.plugins.community_branch.min_version,
        field="branch_plugin_version",
    )
    if plugin is not None:
        reasons.append(plugin)

    if config.scanner_version is not None and (
        attestation.scanner_version != config.scanner_version
    ):
        reasons.append(
            "scanner_version drift: measured "
            f"{attestation.scanner_version!r} != pinned "
            f"{config.scanner_version!r}"
        )

    if reasons:
        return DriftResult(
            drifted=True,
            reason="config/version drift (FK-35 §35.2.4a): " + "; ".join(reasons),
        )
    return DriftResult(drifted=False)


def _version_below_minimum(
    measured: str, minimum: str, *, field: str
) -> str | None:
    """Return a drift reason when ``measured`` is below ``minimum`` (else ``None``).

    An unparseable measured/minimum version is itself drift (fail-closed: an
    attestation must never carry an unverifiable toolchain version into a green
    verdict).
    """
    measured_tuple = _parse_semver(measured)
    minimum_tuple = _parse_semver(minimum)
    if measured_tuple is None:
        return f"{field} unparseable: {measured!r} (cannot verify >= {minimum!r})"
    if minimum_tuple is None:  # pragma: no cover - config SemVer is validated upstream
        return f"{field} expected-minimum unparseable: {minimum!r}"
    if measured_tuple < minimum_tuple:
        return f"{field} below minimum: measured {measured!r} < expected {minimum!r}"
    return None


def _parse_semver(value: str) -> tuple[int, ...] | None:
    """Parse a dotted version into a comparable int tuple (``None`` on failure)."""
    if not value:
        return None
    parts = value.split(".")
    try:
        return tuple(int(part) for part in parts)
    except ValueError:
        return None


__all__ = ["DriftResult", "detect_version_drift"]
