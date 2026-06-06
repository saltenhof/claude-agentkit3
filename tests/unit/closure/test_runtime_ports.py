"""Unit tests for the productive closure runtime ports (AG3-053).

These exercise the real adapter logic of ``ProductiveSanityGatePort`` (the
fast-mode Sanity-Gate, FK-29 §29.1a.6) against a stub ``GitBackend`` at the git
boundary -- the adapter genuinely runs ``git status`` / ``git rebase`` rather
than being a blanket no-op. The doc-fidelity / VectorDB seams are honest
non-blocking warnings (their productive capabilities do not exist yet); their
contract is that they always run and surface a Warning, never a silent skip.

The integrated-candidate Build/Test + Sonar scan ports are NOT tested here: they
are the AG3-056 ``CiBuildTestRunner`` / ``CiSonarScanRunner`` (covered by the
pre_merge_runner test suite); AG3-053 consumes them via the composition root.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from agentkit.closure.multi_repo_saga import GitCommandResult
from agentkit.closure.runtime_ports import (
    CiBuildTestFastRunner,
    ProductiveDocFidelityFeedbackPort,
    ProductiveSanityGatePort,
    ProductiveVectorDbSyncPort,
)
from agentkit.story_context_manager.types import StoryType
from agentkit.verify_system.pre_merge_runner.contract import (
    BuildTestOutcome,
    CandidateRef,
)

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.closure.multi_repo_saga import ClosureRepo


@dataclass
class _ScriptedGitBackend:
    """Stub GitBackend returning a scripted result per git verb.

    ``results`` maps a git verb (the first arg) to a ``GitCommandResult``;
    an absent verb defaults to success with empty stdout.
    """

    results: dict[str, GitCommandResult] = field(default_factory=dict)
    commands: list[tuple[str, ...]] = field(default_factory=list)

    def run(self, repo: ClosureRepo, *args: str) -> GitCommandResult:
        del repo
        self.commands.append(args)
        verb = args[0] if args else ""
        return self.results.get(verb, GitCommandResult(returncode=0, stdout=""))

    def remove_worktree(self, repo: ClosureRepo) -> None:
        del repo


@dataclass
class _HeadGitBackend:
    """Stub GitBackend returning a fixed HEAD branch/commit/tree for rev-parse."""

    branch: str = "story/FAST-1"
    commit: str = "c0ffee"
    tree: str = "7ee5"
    fail: bool = False

    def run(self, repo: ClosureRepo, *args: str) -> GitCommandResult:
        del repo
        if self.fail:
            return GitCommandResult(returncode=128, stdout="", stderr="not a repo")
        if args == ("rev-parse", "--abbrev-ref", "HEAD"):
            return GitCommandResult(returncode=0, stdout=self.branch + "\n")
        if args == ("rev-parse", "HEAD"):
            return GitCommandResult(returncode=0, stdout=self.commit + "\n")
        if args == ("rev-parse", "HEAD^{tree}"):
            return GitCommandResult(returncode=0, stdout=self.tree + "\n")
        return GitCommandResult(returncode=0, stdout="")

    def remove_worktree(self, repo: ClosureRepo) -> None:
        del repo


@dataclass
class _StubBuildTestPort:
    """Stub AG3-056 BuildTestPort recording the candidate it was run on."""

    green: bool = True
    reason: str | None = None
    seen: list[CandidateRef] = field(default_factory=list)

    def run(self, candidate: CandidateRef) -> BuildTestOutcome:
        self.seen.append(candidate)
        return BuildTestOutcome(green=self.green, reason=self.reason)


def test_fast_test_runner_green_binds_to_worktree_head(tmp_path: Path) -> None:
    """FIX-6: the fast floor runs the REAL Build/Test port on the worktree HEAD."""
    git = _HeadGitBackend()
    port = _StubBuildTestPort(green=True)
    runner = CiBuildTestFastRunner(build_test_port=port, git_backend=git)  # type: ignore[arg-type]
    green, reason = runner(tmp_path)
    assert green is True
    assert reason is None
    # The Build/Test ran against exactly the resolved HEAD commit + tree.
    assert port.seen[0].commit_sha == "c0ffee"
    assert port.seen[0].tree_hash == "7ee5"
    assert port.seen[0].branch == "story/FAST-1"


def test_fast_test_runner_red_fails_closed(tmp_path: Path) -> None:
    """FIX-6: a red Build/Test is a fail-closed floor failure (NO ERROR BYPASSING)."""
    git = _HeadGitBackend()
    port = _StubBuildTestPort(green=False, reason="build_test_not_green")
    runner = CiBuildTestFastRunner(build_test_port=port, git_backend=git)  # type: ignore[arg-type]
    green, reason = runner(tmp_path)
    assert green is False
    assert reason == "build_test_not_green"


def test_fast_test_runner_unresolvable_head_fails_closed(tmp_path: Path) -> None:
    """FIX-6: an unreadable worktree HEAD fails closed (cannot confirm tests)."""
    git = _HeadGitBackend(fail=True)
    port = _StubBuildTestPort(green=True)
    runner = CiBuildTestFastRunner(build_test_port=port, git_backend=git)  # type: ignore[arg-type]
    green, reason = runner(tmp_path)
    assert green is False
    assert reason is not None
    assert "HEAD" in reason
    assert port.seen == []  # Build/Test never ran on an unknown revision


def test_sanity_gate_clean_worktree_and_rebase_ok_but_no_runner_escalates(
    tmp_path: Path,
) -> None:
    """Worktree clean + rebase OK, no test runner -> fail-closed (AG3-018 gap)."""
    git = _ScriptedGitBackend()
    port = ProductiveSanityGatePort(git_backend=git)

    outcome = port.evaluate(tmp_path, StoryType.IMPLEMENTATION)

    assert not outcome.passed
    assert "tests-green" in (outcome.reason or "")
    # The git-mechanic checks really ran (not a blanket no-op).
    verbs = [cmd[0] for cmd in git.commands if cmd]
    assert "status" in verbs
    assert "rebase" in verbs


def test_sanity_gate_dirty_worktree_escalates_before_rebase(tmp_path: Path) -> None:
    """A dirty worktree fails closed before any rebase attempt."""
    git = _ScriptedGitBackend(
        results={"status": GitCommandResult(returncode=0, stdout=" M file.py\n")}
    )
    port = ProductiveSanityGatePort(git_backend=git)

    outcome = port.evaluate(tmp_path, StoryType.BUGFIX)

    assert not outcome.passed
    assert "worktree is not clean" in (outcome.reason or "")
    assert all(cmd[0] != "rebase" for cmd in git.commands if cmd)


def test_sanity_gate_rebase_conflict_aborts_and_escalates(tmp_path: Path) -> None:
    """A rebase conflict aborts the rebase and escalates (FK-29 §29.1a.6)."""
    git = _ScriptedGitBackend(
        results={
            "rebase": GitCommandResult(returncode=1, stderr="CONFLICT in file.py"),
        }
    )
    port = ProductiveSanityGatePort(git_backend=git)

    outcome = port.evaluate(tmp_path, StoryType.IMPLEMENTATION)

    assert not outcome.passed
    assert "rebase" in (outcome.reason or "").lower()
    # The conflicting rebase is aborted so the worktree is not left mid-rebase.
    assert ("rebase", "--abort") in git.commands


def test_sanity_gate_all_green_with_runner_passes(tmp_path: Path) -> None:
    """Clean worktree + rebase OK + injected runner green -> PASS."""
    git = _ScriptedGitBackend()
    port = ProductiveSanityGatePort(
        git_backend=git, test_runner=lambda _d: (True, None)
    )

    outcome = port.evaluate(tmp_path, StoryType.IMPLEMENTATION)

    assert outcome.passed
    assert outcome.reason is None


def test_sanity_gate_runner_red_escalates(tmp_path: Path) -> None:
    """An injected runner reporting red tests escalates with its reason."""
    git = _ScriptedGitBackend()
    port = ProductiveSanityGatePort(
        git_backend=git, test_runner=lambda _d: (False, "3 tests failed")
    )

    outcome = port.evaluate(tmp_path, StoryType.IMPLEMENTATION)

    assert not outcome.passed
    assert outcome.reason == "3 tests failed"


def test_doc_fidelity_feedback_is_nonblocking_warning(tmp_path: Path) -> None:
    """Level-4 doc-fidelity always runs and surfaces a Warning (no silent skip)."""
    port = ProductiveDocFidelityFeedbackPort()

    passed, warning = port.evaluate_feedback_fidelity(None, tmp_path)  # type: ignore[arg-type]

    assert not passed
    assert warning is not None
    assert "doc-fidelity" in warning


def test_vectordb_sync_is_nonblocking_warning(tmp_path: Path) -> None:
    """VectorDB sync always runs and surfaces a Warning when unavailable."""
    port = ProductiveVectorDbSyncPort()

    triggered, warning = port.trigger_sync(None, tmp_path)  # type: ignore[arg-type]

    assert not triggered
    assert warning is not None
    assert "VectorDB" in warning


# ---------------------------------------------------------------------------
# ProductiveModeLockReleasePort (AG3-018 DELTA-E, FK-24 §24.3.3)
# ---------------------------------------------------------------------------


@dataclass
class _RecordingModeLockRepo:
    """Recording mode-lock repository double (release path)."""

    released: list[tuple[str, str]] = field(default_factory=list)

    def release(self, project_key: str, mode: str) -> object:
        self.released.append((project_key, mode))
        return object()


def test_mode_lock_release_no_marker_is_noop(tmp_path: Path) -> None:
    """A story that never acquired (no marker) owes no release (idempotent)."""
    from agentkit.closure.runtime_ports import ProductiveModeLockReleasePort

    repo = _RecordingModeLockRepo()
    port = ProductiveModeLockReleasePort(mode_lock_repo=repo)  # type: ignore[arg-type]

    released, warning = port.release(tmp_path, "proj")

    assert released is True
    assert warning is None
    assert repo.released == []


def test_mode_lock_release_uses_acquired_mode_from_marker(tmp_path: Path) -> None:
    """The release uses the mode recorded in the durable acquire marker."""
    from agentkit.closure.runtime_ports import ProductiveModeLockReleasePort
    from agentkit.governance.setup_preflight_gate.mode_lock_marker import (
        record_mode_lock_acquired,
    )

    record_mode_lock_acquired(tmp_path, mode="fast")
    repo = _RecordingModeLockRepo()
    port = ProductiveModeLockReleasePort(mode_lock_repo=repo)  # type: ignore[arg-type]

    released, warning = port.release(tmp_path, "proj")

    assert released is True
    assert warning is None
    assert repo.released == [("proj", "fast")]
