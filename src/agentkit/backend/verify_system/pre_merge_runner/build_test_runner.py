"""Commit-bound Build/Test runner for the pre-merge barrier (AG3-056).

Fulfils :class:`BuildTestPort`: obtains the integrated candidate's ONE CI run
(shared with the scan facet via the :class:`CandidateRunCache`, FIX-3), and
reports green ONLY when that run's build + test passed for exactly that commit
(AG3-056 AC3). Red/aborted/unreachable/timeout all fail closed.

The result is commit-bound by construction AND by verification: the run was
parameterised with the candidate's branch + commit, AND the runner requires
the commit Jenkins ACTUALLY built (``built_commit``) to equal the candidate
commit (FIX-3) — a job that silently builds branch-tip cannot report green for
a foreign commit. The runner does not invent or re-derive the binding; it
reports the terminal CI verdict for the one run it triggered.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from agentkit.backend.verify_system.pre_merge_runner.ci_run import CiRunUnavailableError
from agentkit.backend.verify_system.pre_merge_runner.contract import BuildTestOutcome

if TYPE_CHECKING:
    from agentkit.backend.verify_system.pre_merge_runner.ci_run import CandidateRunCache
    from agentkit.backend.verify_system.pre_merge_runner.contract import CandidateRef


@dataclass(frozen=True)
class CiBuildTestRunner:
    """Productive :class:`BuildTestPort` over a shared :class:`CandidateRunCache`.

    Attributes:
        run_cache: The shared cache that triggers ONE CI run per candidate and
            serves the SAME run to both this build/test facet and the scan
            facet (FIX-3).
    """

    run_cache: CandidateRunCache

    def run(self, candidate: CandidateRef) -> BuildTestOutcome:
        """Trigger + await build/test for the candidate (fail-closed).

        Args:
            candidate: The integrated-candidate commit to build and test.

        Returns:
            ``green=True`` ONLY when the triggered run's build+test passed AND
            Jenkins actually built exactly that commit; otherwise a fail-closed
            ``green=False`` outcome with a machine reason (red/aborted/
            unreachable/timeout/built-commit mismatch).
        """
        if not candidate.commit_sha:
            return BuildTestOutcome(green=False, reason="candidate_commit_sha_missing")
        try:
            result = self.run_cache.run_for(candidate)
        except CiRunUnavailableError as exc:
            return BuildTestOutcome(green=False, reason=f"ci_run_unavailable: {exc}")
        if result.built_commit is None:
            return BuildTestOutcome(
                green=False,
                reason="built_commit_unknown: Jenkins exposed no built revision",
            )
        if result.built_commit != candidate.commit_sha:
            return BuildTestOutcome(
                green=False,
                reason=(
                    f"built_commit_mismatch: built={result.built_commit!r} "
                    f"candidate={candidate.commit_sha!r}"
                ),
            )
        if not result.build_succeeded:
            return BuildTestOutcome(
                green=False,
                reason=f"build_test_not_green: ci_result={result.result!r}",
            )
        return BuildTestOutcome(green=True)


__all__ = ["CiBuildTestRunner"]
