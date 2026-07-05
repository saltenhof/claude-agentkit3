"""Unit tests for the pure preflight 7/8 decision logic (AG3-145 Teilschritt C).

Blood-type A: the Project Edge collects the ``preflight_probe`` evidence; the
BACKEND decides here with ownership context + the remote ref-read. Every outcome
is a NAMED, differentiated finding (FK-22 §22.3.1) -- never a collective FAIL.
"""

from __future__ import annotations

from agentkit.backend.control_plane.edge_commands import (
    PREFLIGHT_FINDING_CODES,
    PreflightOwnershipContext,
    PreflightProbeEvidence,
    decide_branch_preflight,
    decide_worktree_preflight,
    edge_command_id,
)

_NO_OWNERSHIP = PreflightOwnershipContext(own_session_active_ownership=False)
_OWN_ACTIVE = PreflightOwnershipContext(own_session_active_ownership=True)


# ---------------------------------------------------------------------------
# Check 7 -- branch decision
# ---------------------------------------------------------------------------


class TestBranchDecision:
    def test_missing_probe_fails_closed(self) -> None:
        finding = decide_branch_preflight(None, _NO_OWNERSHIP)
        assert not finding.passed
        assert finding.finding_code == "edge_probe_missing"

    def test_no_branch_passes(self) -> None:
        evidence = PreflightProbeEvidence(repo_id="r", branch_present=False)
        finding = decide_branch_preflight(evidence, _NO_OWNERSHIP)
        assert finding.passed
        assert finding.finding_code == "no_leftover_state"

    def test_stale_foreign_branch_fails(self) -> None:
        evidence = PreflightProbeEvidence(
            repo_id="r", branch_present=True, head_sha="local"
        )
        finding = decide_branch_preflight(evidence, _NO_OWNERSHIP)
        assert not finding.passed
        assert finding.finding_code == "stale_foreign_branch"

    def test_locally_ahead_fails(self) -> None:
        evidence = PreflightProbeEvidence(
            repo_id="r", branch_present=True, head_sha="local", remote_head_sha="remote"
        )
        finding = decide_branch_preflight(evidence, _NO_OWNERSHIP)
        assert not finding.passed
        assert finding.finding_code == "locally_ahead"

    def test_legitimate_takeover_passes(self) -> None:
        # Active OWN ownership + local head aligned to the takeover base -> PASS.
        evidence = PreflightProbeEvidence(
            repo_id="r",
            branch_present=True,
            head_sha="base-sha",
            takeover_base_sha="base-sha",
        )
        finding = decide_branch_preflight(evidence, _OWN_ACTIVE)
        assert finding.passed
        assert finding.finding_code == "legitimate_takeover"

    def test_takeover_off_base_is_stale_or_dirty(self) -> None:
        evidence = PreflightProbeEvidence(
            repo_id="r",
            branch_present=True,
            head_sha="drifted",
            takeover_base_sha="base-sha",
        )
        finding = decide_branch_preflight(evidence, _OWN_ACTIVE)
        assert not finding.passed
        assert finding.finding_code == "local_stale_or_dirty_takeover_target"

    def test_remote_diverged_after_takeover_fails(self) -> None:
        evidence = PreflightProbeEvidence(
            repo_id="r",
            branch_present=True,
            head_sha="base-sha",
            remote_head_sha="advanced",
            takeover_base_sha="base-sha",
        )
        finding = decide_branch_preflight(evidence, _OWN_ACTIVE)
        assert not finding.passed
        assert finding.finding_code == "remote_branch_diverged_after_takeover"


# ---------------------------------------------------------------------------
# Check 8 -- worktree decision
# ---------------------------------------------------------------------------


class TestWorktreeDecision:
    def test_missing_probe_fails_closed(self) -> None:
        finding = decide_worktree_preflight(None, _NO_OWNERSHIP, story_id="S")
        assert not finding.passed
        assert finding.finding_code == "edge_probe_missing"

    def test_no_worktree_passes(self) -> None:
        evidence = PreflightProbeEvidence(
            repo_id="r", branch_present=False, worktree_present=False
        )
        finding = decide_worktree_preflight(evidence, _NO_OWNERSHIP, story_id="S")
        assert finding.passed
        assert finding.finding_code == "no_leftover_state"

    def test_foreign_worktree_fails(self) -> None:
        evidence = PreflightProbeEvidence(
            repo_id="r", branch_present=False, worktree_present=True
        )
        finding = decide_worktree_preflight(evidence, _NO_OWNERSHIP, story_id="S")
        assert not finding.passed
        assert finding.finding_code == "foreign_worktree"

    def test_wrong_marker_wrong_story_fails(self) -> None:
        evidence = PreflightProbeEvidence(
            repo_id="r",
            branch_present=False,
            worktree_present=True,
            marker_present=True,
            marker_story_id="OTHER",
        )
        finding = decide_worktree_preflight(evidence, _NO_OWNERSHIP, story_id="S")
        assert not finding.passed
        assert finding.finding_code == "wrong_marker_wrong_story"

    def test_legit_takeover_worktree_passes(self) -> None:
        evidence = PreflightProbeEvidence(
            repo_id="r",
            branch_present=True,
            worktree_present=True,
            marker_present=True,
            marker_story_id="S",
            takeover_base_sha="base-sha",
        )
        finding = decide_worktree_preflight(evidence, _OWN_ACTIVE, story_id="S")
        assert finding.passed
        assert finding.finding_code == "legitimate_takeover"

    def test_takeover_missing_marker_is_stale_or_dirty(self) -> None:
        evidence = PreflightProbeEvidence(
            repo_id="r",
            branch_present=True,
            worktree_present=True,
            marker_present=False,
            takeover_base_sha="base-sha",
        )
        finding = decide_worktree_preflight(evidence, _OWN_ACTIVE, story_id="S")
        assert not finding.passed
        assert finding.finding_code == "local_stale_or_dirty_takeover_target"


# ---------------------------------------------------------------------------
# Contract pins
# ---------------------------------------------------------------------------


def test_finding_codes_are_pinned() -> None:
    expected = frozenset(
        {
            "no_leftover_state",
            "legitimate_takeover",
            "edge_probe_missing",
            "stale_foreign_branch",
            "locally_ahead",
            "remote_branch_diverged_after_takeover",
            "foreign_worktree",
            "wrong_marker_wrong_story",
            "local_stale_or_dirty_takeover_target",
        }
    )
    assert expected == PREFLIGHT_FINDING_CODES


def test_edge_command_id_is_deterministic_and_unique() -> None:
    assert edge_command_id("run-1", "preflight_probe", "repo-a") == (
        "run-1::preflight_probe::repo-a"
    )
    # Distinct across kind + repo + run.
    ids = {
        edge_command_id("run-1", "preflight_probe", "repo-a"),
        edge_command_id("run-1", "provision_worktree", "repo-a"),
        edge_command_id("run-1", "preflight_probe", "repo-b"),
        edge_command_id("run-2", "preflight_probe", "repo-a"),
    }
    assert len(ids) == 4
