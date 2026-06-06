"""Unit tests for the commit-bound Sonar scan runner (AG3-056 AC1/AC2/AC4).

Only the external HTTP boundary (CI backend + Sonar client) and the git tree
resolver are faked; the runner + binding-proof + attestation-construction
logic runs for real. Covers FIX-1 (attestation surfaced + complete), FIX-2
(revision via the analyses chain, no version/commit_sha fallback), FIX-3
(built-commit binding) and FIX-4 (complete attestation, fail-closed fields).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from agentkit.config.models import SonarQubeConfig
from agentkit.verify_system.pre_merge_runner.ci_run import CiRunUnavailableError
from agentkit.verify_system.pre_merge_runner.contract import CandidateRef
from agentkit.verify_system.pre_merge_runner.scan_runner import (
    CiSonarScanRunner,
    GitTreeHashResolver,
)

if TYPE_CHECKING:
    import pytest

from .fakes import (
    FAKE_TREE_HASH,
    FakeCiBackend,
    FakeSonarClient,
    empty_ledger,
    fake_tree_resolver,
    make_ci_result,
    run_cache,
)

_SHA = "cafe1234"
_BRANCH = "story/AG3-056-candidate"
_TREE = "tree9999"


def _sonar_config() -> SonarQubeConfig:
    return SonarQubeConfig(
        available=True,
        enabled=True,
        base_url="http://sonar:9901",
        token_env="SONAR_TOKEN",
        scanner_version="5.0.1",
    )


def _candidate() -> CandidateRef:
    return CandidateRef(branch=_BRANCH, commit_sha=_SHA, tree_hash=_TREE)


def _runner(backend: FakeCiBackend, client: FakeSonarClient) -> CiSonarScanRunner:
    return CiSonarScanRunner(
        run_cache=run_cache(backend),
        client=client,  # type: ignore[arg-type]
        config=_sonar_config(),
        ledger=empty_ledger(),
        tree_resolver=fake_tree_resolver,
    )


class TestPositivePath:
    def test_sonar_proves_candidate_revision_produces_bound_outcome(self) -> None:
        """AC1/AC2: a triggered run + Sonar reporting the candidate revision
        yields produced=True with the candidate's commit + proven tree."""
        backend = FakeCiBackend(result=make_ci_result())
        # ERROR-2: the analysis is found ONLY under the candidate branch
        # (the branch proof); the search is scoped to candidate.branch.
        client = FakeSonarClient(analyzed_revision=_SHA, analyses_branch=_BRANCH)
        outcome = _runner(backend, client).produce_attestation(_candidate())
        assert outcome.produced is True
        assert outcome.commit_sha == _SHA
        assert outcome.tree_hash == FAKE_TREE_HASH
        assert outcome.reason is None
        # FIX-1: the FULL AG3-052 gate ran over the run's analysis and is green
        # (empty open issues + OK post-apply QG) -> carried in the outcome.
        assert outcome.gate_outcome is not None
        assert outcome.gate_outcome.passed is True
        assert outcome.gate_outcome.gate_status == "sonarqube_gate_passed"
        # The run was actually triggered for the candidate (executed, not read).
        assert backend.calls == [(_BRANCH, _SHA)]

    def test_full_gate_runs_red_when_post_apply_gate_red(self) -> None:
        """FIX-1: the runner runs the FULL AG3-052 gate (not the raw QG). A red
        post-apply quality gate yields produced=True with a NOT-green gate
        outcome (Dim 9 consumes gate_outcome.passed, never the raw status)."""
        backend = FakeCiBackend(result=make_ci_result())
        client = FakeSonarClient(
            analyzed_revision=_SHA,
            analyses_branch=_BRANCH,
            quality_gate_status="ERROR",
        )
        outcome = _runner(backend, client).produce_attestation(_candidate())
        assert outcome.produced is True
        assert outcome.gate_outcome is not None
        assert outcome.gate_outcome.passed is False
        assert outcome.gate_outcome.gate_status == "failed"

    def test_full_gate_red_on_open_non_accepted_issue(self) -> None:
        """FIX-1: Broken-Window — an open non-accepted issue (not in the empty
        ledger) makes the gate red even with an OK QG status."""
        backend = FakeCiBackend(result=make_ci_result())
        client = FakeSonarClient(
            analyzed_revision=_SHA,
            analyses_branch=_BRANCH,
            quality_gate_status="OK",
            open_issues=(
                {"key": "I-1", "rule": "py:S100", "hash": "fp1", "message": "smell"},
            ),
        )
        outcome = _runner(backend, client).produce_attestation(_candidate())
        assert outcome.produced is True
        assert outcome.gate_outcome is not None
        assert outcome.gate_outcome.passed is False

    def test_fresh_complete_attestation_is_surfaced(self) -> None:
        """FIX-1/FIX-4/ERROR-A/ERROR-B: the proven outcome carries the FRESH,
        COMPLETE attestation. The analysisId is resolved from ce/task; the
        integrity hashes are COMPUTED (non-empty sha256, not invented fields);
        the scanner version comes from the run."""
        backend = FakeCiBackend(
            result=make_ci_result(scanner_version="5.0.1")
        )
        client = FakeSonarClient(
            analyzed_revision=_SHA, analysis_id="AX-1", analyses_branch=_BRANCH
        )
        outcome = _runner(backend, client).produce_attestation(_candidate())
        att = outcome.attestation
        assert att is not None
        # Bound to the proven candidate commit + git-derived tree (not empty).
        assert att.last_analyzed_revision == _SHA
        assert att.commit_sha == _SHA
        assert att.tree_hash == FAKE_TREE_HASH
        # ERROR-A: the analysisId is the REAL one resolved via ce/task.
        assert att.analysis_id == "AX-1"
        assert att.ce_task_id == "CE-1"
        # ERROR-B: the integrity hashes are COMPUTED 64-char sha256 digests
        # (sourced from authoritative endpoints), never invented literals.
        assert len(att.quality_gate_hash) == 64
        assert len(att.quality_profile_hash) == 64
        assert len(att.analysis_scope_hash) == 64
        assert att.quality_gate_status == "OK"
        assert att.exception_ledger_hash == empty_ledger().content_hash()
        assert att.sonarqube_version == "26.4"
        # ERROR-B: scanner version is sourced from the producing run.
        assert att.scanner_version == "5.0.1"
        # ERROR-1: EVERY mandatory FK-33 §33.6.3 binding is non-empty (the
        # validator would have rejected construction otherwise).
        for field_name in (
            "commit_sha",
            "tree_hash",
            "analysis_id",
            "ce_task_id",
            "quality_gate_status",
            "quality_gate_hash",
            "quality_profile_hash",
            "analysis_scope_hash",
            "exception_ledger_hash",
            "last_analyzed_revision",
            "sonarqube_version",
            "branch_plugin_version",
            "scanner_version",
        ):
            assert str(getattr(att, field_name)).strip()


class TestNegativePaths:
    def test_revision_mismatch_fails_closed(self) -> None:
        """Stale/foreign analysis (Sonar reports a different revision)."""
        backend = FakeCiBackend(result=make_ci_result())
        client = FakeSonarClient(analyzed_revision="deadbeef")
        outcome = _runner(backend, client).produce_attestation(_candidate())
        assert outcome.produced is False
        assert outcome.commit_sha is None
        assert outcome.tree_hash is None
        assert outcome.attestation is None
        assert outcome.reason is not None
        assert "revision_mismatch" in outcome.reason

    def test_no_revision_reported_fails_closed(self) -> None:
        """Sonar reports no revision => fail closed (never stapled, FIX-2)."""
        backend = FakeCiBackend(result=make_ci_result())
        client = FakeSonarClient(analyzed_revision="")
        outcome = _runner(backend, client).produce_attestation(_candidate())
        assert outcome.produced is False
        assert outcome.attestation is None
        assert outcome.reason is not None
        # The analyses chain reports no revision => SonarApiError surfaced.
        assert "sonar_unreachable" in outcome.reason

    def test_analysis_only_under_different_branch_fails_closed(self) -> None:
        """ERROR-2: the analysisId exists, but only under a DIFFERENT branch's
        analyses. The candidate-branch-scoped project_analyses/search finds
        nothing => the revision read misses => fail closed (the branch proof IS
        finding the analysisId on the candidate branch)."""
        backend = FakeCiBackend(result=make_ci_result())
        # The analysis exists ONLY under "main", but the search is scoped to the
        # candidate branch (story/...), so it is not found there.
        client = FakeSonarClient(analyzed_revision=_SHA, analyses_branch="main")
        outcome = _runner(backend, client).produce_attestation(_candidate())
        assert outcome.produced is False
        assert outcome.attestation is None
        assert outcome.reason is not None
        # No analysis on the candidate branch => SonarApiError surfaced.
        assert "sonar_unreachable" in outcome.reason

    def test_built_commit_mismatch_fails_closed(self) -> None:
        """FIX-3: Jenkins built a different commit than the candidate."""
        backend = FakeCiBackend(
            result=make_ci_result(built_commit="0ther999")
        )
        client = FakeSonarClient(analyzed_revision=_SHA)
        outcome = _runner(backend, client).produce_attestation(_candidate())
        assert outcome.produced is False
        assert outcome.attestation is None
        assert outcome.reason is not None
        assert "built_commit_mismatch" in outcome.reason

    def test_built_commit_unknown_fails_closed(self) -> None:
        """FIX-3: Jenkins exposed no built revision => fail closed."""
        backend = FakeCiBackend(
            result=make_ci_result(built_commit=None)
        )
        client = FakeSonarClient(analyzed_revision=_SHA)
        outcome = _runner(backend, client).produce_attestation(_candidate())
        assert outcome.produced is False
        assert outcome.reason is not None
        assert "built_commit_unknown" in outcome.reason

    def test_run_without_analysis_reference_fails_closed(self) -> None:
        """No ceTaskId from the run => no scan was produced (AC1)."""
        backend = FakeCiBackend(result=make_ci_result(ce_task_id=None))
        client = FakeSonarClient(analyzed_revision=_SHA)
        outcome = _runner(backend, client).produce_attestation(_candidate())
        assert outcome.produced is False
        assert outcome.attestation is None
        assert outcome.reason == "no_analysis_from_run"

    def test_run_without_scanner_version_fails_closed(self) -> None:
        """ERROR-B: the run exposed no scanner version => fail closed (never a
        placeholder scanner version in a produced attestation)."""
        backend = FakeCiBackend(
            result=make_ci_result(scanner_version=None)
        )
        client = FakeSonarClient(analyzed_revision=_SHA)
        outcome = _runner(backend, client).produce_attestation(_candidate())
        assert outcome.produced is False
        assert outcome.attestation is None
        assert outcome.reason is not None
        assert "sonar_unreachable" in outcome.reason

    def test_ce_task_pending_fails_closed(self) -> None:
        """ERROR-A: a non-terminal (PENDING) ce/task => fail closed."""
        backend = FakeCiBackend(result=make_ci_result())
        client = FakeSonarClient(analyzed_revision=_SHA, ce_status="PENDING")
        outcome = _runner(backend, client).produce_attestation(_candidate())
        assert outcome.produced is False
        assert outcome.attestation is None
        assert outcome.reason is not None
        assert "sonar_unreachable" in outcome.reason

    def test_ce_task_failed_fails_closed(self) -> None:
        """ERROR-A: a FAILED ce/task => fail closed."""
        backend = FakeCiBackend(result=make_ci_result())
        client = FakeSonarClient(analyzed_revision=_SHA, ce_status="FAILED")
        outcome = _runner(backend, client).produce_attestation(_candidate())
        assert outcome.produced is False
        assert outcome.attestation is None
        assert outcome.reason is not None
        assert "sonar_unreachable" in outcome.reason

    def test_ce_task_success_without_analysis_id_fails_closed(self) -> None:
        """ERROR-A: a SUCCESS ce/task carrying no analysisId => fail closed."""
        backend = FakeCiBackend(result=make_ci_result())
        client = FakeSonarClient(
            analyzed_revision=_SHA, ce_carries_analysis_id=False
        )
        outcome = _runner(backend, client).produce_attestation(_candidate())
        assert outcome.produced is False
        assert outcome.attestation is None
        assert outcome.reason is not None
        assert "sonar_unreachable" in outcome.reason

    def test_analysis_id_absent_from_analyses_fails_closed(self) -> None:
        """ERROR-A: the resolved analysisId is not in project_analyses (strict
        key match, no single-entry fallback) => fail closed."""
        backend = FakeCiBackend(result=make_ci_result())
        # ce/task resolves AX-OTHER but project_analyses only carries AX-1.
        client = FakeSonarClient(
            analyzed_revision=_SHA, analysis_id="AX-OTHER", analyses_key="AX-1"
        )
        outcome = _runner(backend, client).produce_attestation(_candidate())
        assert outcome.produced is False
        assert outcome.attestation is None
        assert outcome.reason is not None
        assert "sonar_unreachable" in outcome.reason

    def test_ci_unreachable_fails_closed(self) -> None:
        backend = FakeCiBackend(error=CiRunUnavailableError("jenkins down"))
        client = FakeSonarClient(analyzed_revision=_SHA)
        outcome = _runner(backend, client).produce_attestation(_candidate())
        assert outcome.produced is False
        assert outcome.attestation is None
        assert outcome.reason is not None
        assert "ci_run_unavailable" in outcome.reason

    def test_sonar_unreachable_fails_closed(self) -> None:
        backend = FakeCiBackend(result=make_ci_result())
        client = FakeSonarClient(analyzed_revision=_SHA, raise_on="project_status")
        outcome = _runner(backend, client).produce_attestation(_candidate())
        assert outcome.produced is False
        assert outcome.attestation is None
        assert outcome.reason is not None
        assert "sonar_unreachable" in outcome.reason

    def test_missing_candidate_commit_fails_closed(self) -> None:
        backend = FakeCiBackend(result=make_ci_result())
        client = FakeSonarClient(analyzed_revision=_SHA)
        candidate = CandidateRef(branch=_BRANCH, commit_sha="", tree_hash=_TREE)
        outcome = _runner(backend, client).produce_attestation(candidate)
        assert outcome.produced is False
        assert outcome.reason == "candidate_commit_sha_missing"
        # No CI run is triggered for an empty candidate commit.
        assert backend.calls == []

class TestGitTreeHashResolver:
    def test_delegates_to_git_tree_hash_of_commit(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The productive resolver delegates to ``utils.git.tree_hash_of_commit``."""
        import agentkit.utils.git as git_utils

        seen: dict[str, object] = {}

        def _fake(repo_root: Path, commit_sha: str) -> str:
            seen["repo_root"] = repo_root
            seen["commit"] = commit_sha
            return "treeXYZ"

        monkeypatch.setattr(git_utils, "tree_hash_of_commit", _fake)
        resolver = GitTreeHashResolver(repo_root=Path("/repo"))
        assert resolver(_SHA) == "treeXYZ"
        assert seen == {"repo_root": Path("/repo"), "commit": _SHA}


class TestNegativePathsTreeResolver:
    def test_tree_resolver_failure_fails_closed(self) -> None:
        """FIX-4: an unresolvable tree hash never stamps an empty tree."""
        backend = FakeCiBackend(result=make_ci_result())
        client = FakeSonarClient(analyzed_revision=_SHA)

        def _boom(commit_sha: str) -> str:
            raise RuntimeError(f"no such commit {commit_sha}")

        runner = CiSonarScanRunner(
            run_cache=run_cache(backend),
            client=client,  # type: ignore[arg-type]
            config=_sonar_config(),
            ledger=empty_ledger(),
            tree_resolver=_boom,
        )
        outcome = runner.produce_attestation(_candidate())
        assert outcome.produced is False
        assert outcome.attestation is None
        assert outcome.reason is not None
        assert "sonar_unreachable" in outcome.reason
