"""Implementation and structural evidence composition outside Closure."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

    from agentkit.backend.bootstrap import composition_closure_types as closure_types
    from agentkit.backend.bootstrap import composition_verify_types as verify_types
    from agentkit.backend.closure.multi_repo_saga import ClosureRepo, GitReadBackend
    from agentkit.backend.verify_system.pre_merge_runner.contract import BuildTestPort


_TEST_FILE_MARKERS: tuple[str, ...] = ("test_", "_test.", "/tests/", "tests/")


@dataclass(frozen=True)
class CiBuildTestFastRunner:
    """Run implementation fast-mode CI against a system-measured candidate."""

    build_test_port: BuildTestPort
    git_backend: GitReadBackend

    def __call__(self, story_dir: Path) -> tuple[bool, str | None]:
        """Run Build/Test for the implementation worktree HEAD fail-closed."""
        from agentkit.backend.closure.multi_repo_saga import ClosureRepo
        from agentkit.backend.verify_system.pre_merge_runner.contract import CandidateRef

        repo = ClosureRepo(name=story_dir.name, repo_root=story_dir)
        branch = self._read(repo, "rev-parse", "--abbrev-ref", "HEAD")
        commit = self._read(repo, "rev-parse", "HEAD")
        tree = self._read(repo, "rev-parse", "HEAD^{tree}")
        if commit is None or tree is None or branch is None:
            return False, "cannot bind fast CI to the implementation worktree HEAD"
        outcome = self.build_test_port.run(
            CandidateRef(branch=branch, commit_sha=commit, tree_hash=tree)
        )
        return (True, None) if outcome.green else (False, outcome.reason)

    def _read(self, repo: ClosureRepo, *args: str) -> str | None:
        result = self.git_backend.run(repo, *args)
        return result.stdout.strip() if result.ok and result.stdout.strip() else None


def build_fast_test_runner(
    ci_config: object | None,
) -> Callable[[Path], tuple[bool, str | None]] | None:
    """Build the implementation fast-mode tests-green CI runner."""
    from agentkit.backend.bootstrap.composition_git import (
        CompositionSubprocessGitBackend,
    )
    from agentkit.backend.config.models import JenkinsConfig
    from agentkit.backend.verify_system.pre_merge_runner.runtime_wiring import (
        build_build_test_runner,
    )

    typed_ci = ci_config if isinstance(ci_config, JenkinsConfig) else None
    if typed_ci is None or not typed_ci.available:
        return None
    build_test_port = build_build_test_runner(typed_ci, Path.cwd())
    if build_test_port is None:  # pragma: no cover - guarded above
        return None
    return CiBuildTestFastRunner(
        build_test_port=build_test_port,
        git_backend=CompositionSubprocessGitBackend(),
    )


def build_structural_build_test_port(
    ci_config: object | None,
    story_dir: Path,
) -> verify_types.BuildTestEvidencePort:
    """Build the implementation Layer-1 build/test system-evidence port."""
    from agentkit.backend.config.models import JenkinsConfig
    from agentkit.backend.verify_system.pre_merge_runner.runtime_wiring import (
        build_build_test_runner,
    )
    from agentkit.backend.verify_system.structural.checks import ABSENT_BUILD_TEST_PORT

    typed_ci = ci_config if isinstance(ci_config, JenkinsConfig) else None
    if typed_ci is None or not typed_ci.available:
        return ABSENT_BUILD_TEST_PORT
    build_test_port = build_build_test_runner(typed_ci, story_dir)
    if build_test_port is None:  # pragma: no cover - guarded above
        return ABSENT_BUILD_TEST_PORT
    return _CiBuildTestEvidenceAdapter(
        build_test_port=build_test_port,
        git_backend=_system_git_backend(),
    )


def _system_git_backend() -> closure_types.RepoGitBackend:
    """Resolve Git evidence for implementation, never Closure merge."""
    from agentkit.backend.bootstrap.composition_git import (
        CompositionSubprocessGitBackend,
    )

    return CompositionSubprocessGitBackend()


@dataclass(frozen=True)
class _CiBuildTestEvidenceAdapter:
    """Adapt commit-bound CI to implementation structural evidence."""

    build_test_port: verify_types.BuildTestPort
    git_backend: closure_types.RepoGitBackend

    def evaluate(self, story_dir: Path) -> verify_types.BuildTestEvidence | None:
        """Run CI for the system-measured implementation worktree revision."""
        from agentkit.backend.closure.multi_repo_saga import ClosureRepo
        from agentkit.backend.verify_system.pre_merge_runner.contract import CandidateRef
        from agentkit.backend.verify_system.structural.checks import BuildTestEvidence

        repo = ClosureRepo(name=story_dir.name, repo_root=story_dir)
        branch = self._read(repo, "rev-parse", "--abbrev-ref", "HEAD")
        commit = self._read(repo, "rev-parse", "HEAD")
        tree = self._read(repo, "rev-parse", "HEAD^{tree}")
        if branch is None or commit is None or tree is None:
            return None
        outcome = self.build_test_port.run(
            CandidateRef(branch=branch, commit_sha=commit, tree_hash=tree)
        )
        return BuildTestEvidence(
            build_ok=outcome.green,
            tests_green=outcome.green,
            test_file_count=self._diff_test_file_count(repo),
            coverage_report_present=outcome.green,
            coverage_meets_threshold=outcome.green,
            detail=outcome.reason,
        )

    def _diff_test_file_count(self, repo: object) -> int:
        from agentkit.backend.closure.multi_repo_saga import ClosureRepo

        assert isinstance(repo, ClosureRepo)  # noqa: S101 - internal typed call
        out = self._read(repo, "diff", "--name-only", "origin/main...HEAD")
        if out is None:
            out = self._read(repo, "diff", "--name-only", "HEAD")
        return sum(
            1
            for line in (out or "").splitlines()
            if any(marker in line for marker in _TEST_FILE_MARKERS)
        )

    def _read(self, repo: object, *args: str) -> str | None:
        from agentkit.backend.closure.multi_repo_saga import ClosureRepo

        assert isinstance(repo, ClosureRepo)  # noqa: S101 - internal typed call
        result = self.git_backend.run(repo, *args)
        return result.stdout.strip() if result.ok and result.stdout.strip() else None
