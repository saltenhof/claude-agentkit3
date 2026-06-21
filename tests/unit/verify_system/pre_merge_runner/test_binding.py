"""Unit tests for the candidate-binding proof (AG3-056 AC1/AC2).

The binding proof is the heart of the story: a Sonar attestation is accepted
ONLY when Sonar itself reports the analysed revision == candidate commit. The
branch is proven UPSTREAM (ERROR-2): a non-empty attestation already implies
the analysisId was found on the candidate-branch-scoped
``project_analyses/search`` (see ``read_last_analyzed_revision``), so
:func:`prove_binding` only confirms the revision. Every other case fails
closed with a reason.
"""

from __future__ import annotations

from agentkit.backend.verify_system.pre_merge_runner.binding import prove_binding
from agentkit.backend.verify_system.sonarqube_gate.attestation import SonarAttestation

_CANDIDATE_SHA = "cafe1234"


def _attestation(*, revision: str) -> SonarAttestation:
    # Every MANDATORY FK-33 §33.6.3 field is non-empty (ERROR-1): a READ
    # attestation with an empty mandatory field can no longer be constructed.
    return SonarAttestation(
        commit_sha=revision,
        tree_hash="treehash",
        analysis_id="AX-1",
        ce_task_id="CE-1",
        quality_gate_status="OK",
        quality_gate_hash="qgh",
        quality_profile_hash="qph",
        analysis_scope_hash="ash",
        new_code_definition="PREVIOUS_VERSION",
        exception_ledger_hash="ledgerhash",
        last_analyzed_revision=revision,
        sonarqube_version="26.4",
        branch_plugin_version="1.23.0",
        scanner_version="5.0",
        status="READ",
    )


class TestBindingProven:
    def test_matching_revision_is_bound(self) -> None:
        proof = prove_binding(
            _attestation(revision=_CANDIDATE_SHA),
            candidate_commit_sha=_CANDIDATE_SHA,
        )
        assert proof.bound is True
        assert proof.reason is None


class TestBindingFailsClosed:
    def test_no_attestation_is_unbound(self) -> None:
        proof = prove_binding(
            None,
            candidate_commit_sha=_CANDIDATE_SHA,
        )
        assert proof.bound is False
        assert proof.reason == "no_analysis_from_run"

    def test_revision_mismatch_is_unbound(self) -> None:
        """A stale/foreign analysis (different revision) fails closed (ERROR-2)."""
        proof = prove_binding(
            _attestation(revision="deadbeef"),
            candidate_commit_sha=_CANDIDATE_SHA,
        )
        assert proof.bound is False
        assert proof.reason is not None
        assert "revision_mismatch" in proof.reason

    def test_missing_candidate_commit_is_unbound(self) -> None:
        proof = prove_binding(
            _attestation(revision=_CANDIDATE_SHA),
            candidate_commit_sha="",
        )
        assert proof.bound is False
        assert proof.reason == "candidate_commit_sha_missing"
