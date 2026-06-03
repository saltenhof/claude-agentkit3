"""Commit-bound SonarQube attestation (FK-33 §33.6.3).

The ``SonarAttestation`` field set is 1:1 with the normative formal
entity ``formal.deterministic-checks.entities.sonar-attestation``
(identity key ``analysis_id``) plus the ``commit_sha``/``tree_hash``
binding from FK-33 §33.6.3. A green status for a stale commit
(``last_analyzed_revision != main HEAD``) is invalid; the gate never
does a bare ``projectKey`` live-read.

``config_hash`` is NOT an attestation field; it is a *derived* drift
quantity over ``quality_gate_hash`` + ``quality_profile_hash`` + the
three versions (FK-03 Config-Hash). It is built/bound here; management
of the *registered expectation* is out of scope (AG3-052 §2.2).
``overall_zero_violations`` is NOT a field either — it is the
green-criterion (invariant), see :func:`is_green`.
"""

from __future__ import annotations

import hashlib

from pydantic import BaseModel, ConfigDict

#: SonarQube quality-gate "green" status value (``api/qualitygates``).
QUALITY_GATE_OK = "OK"


class SonarAttestation(BaseModel):
    """Commit-bound attestation of a concrete SonarQube analysis.

    Field set matches ``formal.deterministic-checks.entities.sonar-attestation``
    1:1 (exact attribute names) plus the FK-33 §33.6.3 commit binding.

    Attributes:
        commit_sha: Git commit the analysis was bound to.
        tree_hash: Git tree hash the analysis was bound to.
        analysis_id: SonarQube analysis identifier (identity key).
        ce_task_id: Compute-Engine task identifier.
        quality_gate_status: Raw quality-gate status (e.g. ``OK``/``ERROR``).
        quality_gate_hash: Hash of the active gate conditions.
        quality_profile_hash: Hash of the active rule profile.
        analysis_scope_hash: Hash of sources/inclusions/exclusions.
        new_code_definition: New-code reference (branch/date/days).
        exception_ledger_hash: Hash of the accepted-exception ledger
            (FK-33 §33.6.4 — bound into the attestation).
        last_analyzed_revision: Revision the analysis actually measured.
        sonarqube_version: SonarQube server version.
        branch_plugin_version: Community Branch Plugin version.
        scanner_version: Scanner version.
        status: Attestation lifecycle status.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    commit_sha: str
    tree_hash: str
    analysis_id: str
    ce_task_id: str
    quality_gate_status: str
    quality_gate_hash: str
    quality_profile_hash: str
    analysis_scope_hash: str
    new_code_definition: str
    exception_ledger_hash: str
    last_analyzed_revision: str
    sonarqube_version: str
    branch_plugin_version: str
    scanner_version: str
    status: str

    def config_hash(self) -> str:
        """Derive the FK-03 Config-Hash for drift detection.

        Composed from ``quality_gate_hash`` + ``quality_profile_hash`` +
        the three versions (SonarQube, branch-plugin, scanner). This is a
        *derived* quantity (NOT a stored attestation field): this story
        only builds/binds it; comparing it against a registered CP7
        expectation is out of scope (AG3-052 §2.2).

        Returns:
            64-char lowercase SHA-256 hex digest.
        """
        material = "\x1f".join(
            (
                self.quality_gate_hash,
                self.quality_profile_hash,
                self.sonarqube_version,
                self.branch_plugin_version,
                self.scanner_version,
            )
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    def is_bound_to(self, main_head_revision: str) -> bool:
        """Return whether the analysis is bound to the current main HEAD.

        A green status for an outdated commit
        (``last_analyzed_revision != main_head_revision``) is invalid
        (FK-33 §33.6.3 — no stale green).

        Args:
            main_head_revision: The authoritative current HEAD revision.

        Returns:
            ``True`` only when the analysed revision equals the HEAD.
        """
        return self.last_analyzed_revision == main_head_revision


def is_green_status(
    quality_gate_status: str, *, overall_open_issue_count: int
) -> bool:
    """Broken-Window / Overall-Code green criterion over a raw QG read.

    Green iff the Quality Gate reports OK AND there are zero open
    non-accepted issues across the whole analysed overall-code scope (not
    merely on new code). AK reads the gate status + the overall count; it
    interprets NO individual rules (tolerances live solely in the Sonar
    quality-gate profile). FK-33 §33.6.3.

    This status-based form is what the gate evaluates against the POST-apply
    RE-READ (AG3-052 E4): after the reconciler transitions single-matched
    issues to ``Accepted``, Sonar itself recomputes the gate (Accepted no
    longer counts) — AK re-reads the NEW verdict and the NEW open count, it
    does NOT subtract accepted keys from a stale count.

    Args:
        quality_gate_status: Raw quality-gate status (e.g. ``OK``/``ERROR``).
        overall_open_issue_count: Count of open, non-accepted issues across
            the whole analysed scope (from ``issues/search``).

    Returns:
        ``True`` iff quality gate is OK AND overall open issues == 0.
    """
    return quality_gate_status == QUALITY_GATE_OK and overall_open_issue_count == 0


def is_green(attestation: SonarAttestation, *, overall_open_issue_count: int) -> bool:
    """Broken-Window / Overall-Code green criterion (FK-33 §33.6.3).

    Convenience over :func:`is_green_status` using the attestation's
    quality-gate status. Green iff the Quality Gate reports OK AND there are
    zero open non-accepted issues across the whole analysed overall-code
    scope (not merely on new code).

    Args:
        attestation: The commit-bound attestation under evaluation.
        overall_open_issue_count: Count of open, non-accepted issues
            across the whole analysed scope (from ``issues/search``).

    Returns:
        ``True`` iff quality gate is OK AND overall open issues == 0.
    """
    return is_green_status(
        attestation.quality_gate_status,
        overall_open_issue_count=overall_open_issue_count,
    )


__all__ = ["QUALITY_GATE_OK", "SonarAttestation", "is_green", "is_green_status"]
