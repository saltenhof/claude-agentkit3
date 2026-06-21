"""Unit tests for the commit-bound build/test runner (AG3-056 AC3/AC4)."""

from __future__ import annotations

from agentkit.backend.verify_system.pre_merge_runner.build_test_runner import CiBuildTestRunner
from agentkit.backend.verify_system.pre_merge_runner.ci_run import CiRunUnavailableError
from agentkit.backend.verify_system.pre_merge_runner.contract import CandidateRef

from .fakes import FakeCiBackend, make_ci_result, run_cache

_SHA = "cafe1234"
_BRANCH = "story/AG3-056-candidate"


def _candidate(commit_sha: str = _SHA) -> CandidateRef:
    return CandidateRef(branch=_BRANCH, commit_sha=commit_sha, tree_hash="t")


def _runner(backend: FakeCiBackend) -> CiBuildTestRunner:
    return CiBuildTestRunner(run_cache=run_cache(backend))


class TestGreen:
    def test_successful_run_is_green_commit_bound(self) -> None:
        backend = FakeCiBackend(
            result=make_ci_result(build_succeeded=True, built_commit=_SHA)
        )
        outcome = _runner(backend).run(_candidate())
        assert outcome.green is True
        assert outcome.reason is None
        # Build/test ran for exactly the candidate commit (commit-bound).
        assert backend.calls == [(_BRANCH, _SHA)]


class TestNotGreen:
    def test_failed_run_fails_closed(self) -> None:
        backend = FakeCiBackend(
            result=make_ci_result(
                build_succeeded=False, result="FAILURE", built_commit=_SHA
            )
        )
        outcome = _runner(backend).run(_candidate())
        assert outcome.green is False
        assert outcome.reason is not None
        assert "FAILURE" in outcome.reason

    def test_aborted_run_fails_closed(self) -> None:
        backend = FakeCiBackend(
            result=make_ci_result(
                build_succeeded=False, result="ABORTED", built_commit=_SHA
            )
        )
        outcome = _runner(backend).run(_candidate())
        assert outcome.green is False
        assert outcome.reason is not None
        assert "ABORTED" in outcome.reason

    def test_built_commit_mismatch_fails_closed(self) -> None:
        """FIX-3: a green build of a foreign commit must not pass."""
        backend = FakeCiBackend(
            result=make_ci_result(build_succeeded=True, built_commit="0ther999")
        )
        outcome = _runner(backend).run(_candidate())
        assert outcome.green is False
        assert outcome.reason is not None
        assert "built_commit_mismatch" in outcome.reason

    def test_built_commit_unknown_fails_closed(self) -> None:
        backend = FakeCiBackend(
            result=make_ci_result(build_succeeded=True, built_commit=None)
        )
        outcome = _runner(backend).run(_candidate())
        assert outcome.green is False
        assert outcome.reason is not None
        assert "built_commit_unknown" in outcome.reason

    def test_ci_unreachable_fails_closed(self) -> None:
        backend = FakeCiBackend(error=CiRunUnavailableError("jenkins timeout"))
        outcome = _runner(backend).run(_candidate())
        assert outcome.green is False
        assert outcome.reason is not None
        assert "ci_run_unavailable" in outcome.reason

    def test_missing_candidate_commit_fails_closed(self) -> None:
        backend = FakeCiBackend(result=make_ci_result())
        outcome = _runner(backend).run(_candidate(commit_sha=""))
        assert outcome.green is False
        assert outcome.reason == "candidate_commit_sha_missing"
        assert backend.calls == []
