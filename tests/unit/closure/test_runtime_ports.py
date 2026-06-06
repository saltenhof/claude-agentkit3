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
    ProductiveDocFidelityFeedbackPort,
    ProductiveSanityGatePort,
    ProductiveVectorDbSyncPort,
)
from agentkit.story_context_manager.types import StoryType

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
