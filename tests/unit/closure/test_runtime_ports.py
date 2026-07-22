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

import pytest  # noqa: TC002 -- used at runtime in test signatures

from agentkit.backend.bootstrap.composition_implementation_evidence import (
    CiBuildTestFastRunner,
)
from agentkit.backend.closure.multi_repo_saga import GitCommandResult
from agentkit.backend.closure.runtime_ports import (
    ProductiveDocFidelityFeedbackPort,
    ProductiveSanityGatePort,
    ProductiveVectorDbSyncPort,
)
from agentkit.backend.story_context_manager.types import StoryType
from agentkit.backend.verify_system.pre_merge_runner.contract import (
    BuildTestOutcome,
    CandidateRef,
)

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.backend.closure.multi_repo_saga import ClosureRepo


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


def test_doc_fidelity_feedback_accepts_injected_layer2_client() -> None:
    """The level-4 feedback port carries the SAME injectable Layer-2 LlmClient.

    AG3-067 def-1: the productive feedback path is NOT hard-wired to
    ``FailClosedLlmClient`` anymore -- the composition root injects the SAME
    Layer-2 transport ``build_verify_system`` resolves, so when the productive
    pool lands (AG3-070) this seam runs a real verdict through the SAME
    ``ConformanceService.check_fidelity(level=feedback)`` path. The end-to-end
    REAL evaluation (PASS vs FAIL verdict) is proved in
    ``tests/integration/closure/test_feedback_fidelity_real_eval.py``; here we
    only assert the wiring seam is injectable (no hard-coded transport).
    """

    @dataclass
    class _FakeRealClient:
        def complete(self, *, role: str, prompt: str) -> str:
            del role, prompt
            return "[]"

    injected = _FakeRealClient()
    port = ProductiveDocFidelityFeedbackPort(llm_client=injected)

    assert port.llm_client is injected
    # The default (no injection) stays fail-closed but the field exists -- the
    # transport is a seam, not a hard-coded FailClosedLlmClient inside the method.
    assert ProductiveDocFidelityFeedbackPort().llm_client is None


def test_doc_fidelity_feedback_setup_failure_is_nonblocking_warning(
    tmp_path: Path,
) -> None:
    """A setup-time failure (no state backend) is a NON-BLOCKING warning, not a raise.

    With a bare ``tmp_path`` (no manifest-index / no run scope) the conformance
    stack cannot be built; the post-merge step must surface that as a human
    Warning + failure-corpus incident candidate, never a closure blockade
    (FK-38 §38.3). This guards the non-blocking contract for the degraded path.
    """
    port = ProductiveDocFidelityFeedbackPort()

    passed, warning = port.evaluate_feedback_fidelity(None, tmp_path)  # type: ignore[arg-type]

    assert not passed
    assert warning is not None
    assert "feedback_fidelity" in warning


def test_vectordb_sync_queues_lifecycle_owned_task(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R7: Closure returns after registry handoff; status is observable."""
    from agentkit.backend.vectordb import sync_task_registry as reg_mod

    registry = reg_mod.reset_sync_task_registry_for_tests()
    calls: list[object] = []

    def fake_work(root: object) -> None:
        calls.append(root)

    monkeypatch.setattr(reg_mod, "run_story_sync_work", fake_work)

    port = ProductiveVectorDbSyncPort()

    class _Ctx:
        project_root = tmp_path

    story_dir = tmp_path / "stories" / "S1"
    story_dir.mkdir(parents=True)
    triggered, warning = port.trigger_sync(_Ctx(), story_dir)  # type: ignore[arg-type]
    assert triggered is True
    assert warning is None
    registry.drain(timeout=5.0)
    assert calls == [tmp_path]
    # At least one task recorded as succeeded
    statuses = [
        rec.status
        for rec in [
            registry.status(tid)
            for tid in list(registry._tasks)  # noqa: SLF001 -- test observability
        ]
        if rec is not None
    ]
    assert reg_mod.SyncTaskStatus.SUCCEEDED in statuses


def test_vectordb_sync_post_start_error_is_observable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R7: worker failure after queue handoff is recorded on the task."""
    from agentkit.backend.vectordb import sync_task_registry as reg_mod

    registry = reg_mod.reset_sync_task_registry_for_tests()

    def boom(root: object) -> None:
        del root
        raise RuntimeError("engine exploded")

    monkeypatch.setattr(reg_mod, "run_story_sync_work", boom)
    port = ProductiveVectorDbSyncPort()

    class _Ctx:
        project_root = tmp_path

    triggered, warning = port.trigger_sync(_Ctx(), tmp_path / "s")  # type: ignore[arg-type]
    assert triggered is True
    assert warning is None
    registry.drain(timeout=5.0)
    failed = [
        registry.status(tid)
        for tid in list(registry._tasks)  # noqa: SLF001
    ]
    assert any(
        rec is not None
        and rec.status is reg_mod.SyncTaskStatus.FAILED
        and rec.error
        and "engine exploded" in rec.error
        for rec in failed
    )


def test_vectordb_sync_shutdown_rejects_new_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from agentkit.backend.vectordb import sync_task_registry as reg_mod

    registry = reg_mod.reset_sync_task_registry_for_tests()
    registry.shutdown(wait=True)
    port = ProductiveVectorDbSyncPort()

    class _Ctx:
        project_root = tmp_path

    triggered, warning = port.trigger_sync(_Ctx(), tmp_path)  # type: ignore[arg-type]
    assert triggered is False
    assert warning is not None
    assert "VectorDB" in warning or "queue" in warning.lower() or "shut" in warning.lower()


def test_vectordb_sync_is_nonblocking_warning(tmp_path: Path) -> None:
    """Missing project_root still returns boolean + optional warning (no silent skip)."""
    port = ProductiveVectorDbSyncPort()

    class _Ctx:
        project_root = None

    triggered, warning = port.trigger_sync(_Ctx(), tmp_path)  # type: ignore[arg-type]
    assert isinstance(triggered, bool)
    if not triggered:
        assert warning is not None
        assert "VectorDB" in warning or "story_sync" in (warning or "")


# ---------------------------------------------------------------------------
# ProductiveModeLockReleasePort (AG3-018 DELTA-E, FK-24 §24.3.3)
# ---------------------------------------------------------------------------


@dataclass
class _RecordingModeLockRepo:
    """Recording mode-lock repository double (release path)."""

    released: list[tuple[str, str, str]] = field(default_factory=list)
    holder: object | None = None

    def read_holder(self, project_key: str, story_id: str, run_id: str) -> object | None:
        del project_key, story_id, run_id
        return self.holder

    def release(self, project_key: str, story_id: str, run_id: str) -> object:
        self.released.append((project_key, story_id, run_id))
        return object()


def test_mode_lock_release_no_marker_is_noop(tmp_path: Path, monkeypatch: object) -> None:
    """A story that never acquired (no marker) owes no release (idempotent)."""
    from agentkit.backend.closure.runtime_ports import ProductiveModeLockReleasePort

    repo = _RecordingModeLockRepo()
    port = ProductiveModeLockReleasePort(mode_lock_repo=repo)  # type: ignore[arg-type]

    from agentkit.backend.state_backend.scope import RuntimeStateScope

    monkeypatch.setattr(  # type: ignore[attr-defined]
        "agentkit.backend.state_backend.runtime_scope_resolver.resolve_runtime_scope",
        lambda story_dir: RuntimeStateScope(
            project_key="proj", story_id="AG3-131", story_dir=story_dir, run_id="run-1"
        ),
    )
    released, warning = port.release(tmp_path, "proj", "AG3-131")

    assert released is True
    assert warning is None
    assert repo.released == []


def test_mode_lock_release_uses_acquired_mode_from_marker(
    tmp_path: Path, monkeypatch: object
) -> None:
    """The release uses the mode recorded in the durable acquire marker."""
    from agentkit.backend.closure.runtime_ports import ProductiveModeLockReleasePort
    from agentkit.backend.governance.setup_preflight_gate.mode_lock_marker import (
        record_mode_lock_acquired,
    )

    record_mode_lock_acquired(tmp_path, mode="fast")
    from agentkit.backend.state_backend.scope import RuntimeStateScope
    from agentkit.backend.state_backend.store.mode_lock_repository import (
        ModeLockHolderRecord,
    )

    monkeypatch.setattr(  # type: ignore[attr-defined]
        "agentkit.backend.state_backend.runtime_scope_resolver.resolve_runtime_scope",
        lambda story_dir: RuntimeStateScope(
            project_key="proj", story_id="AG3-131", story_dir=story_dir, run_id="run-1"
        ),
    )
    repo = _RecordingModeLockRepo(
        holder=ModeLockHolderRecord("proj", "AG3-131", "run-1", "fast", "now")
    )
    port = ProductiveModeLockReleasePort(mode_lock_repo=repo)  # type: ignore[arg-type]

    released, warning = port.release(tmp_path, "proj", "AG3-131")

    assert released is True
    assert warning is None
    assert repo.released == [("proj", "AG3-131", "run-1")]
