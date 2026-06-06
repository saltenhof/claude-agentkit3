"""Productive closure runtime port adapters (AG3-053, wired by the comp-root).

These adapters fulfil the closure collaborator Protocols
(``merge_sequence``/``post_merge_finalization``) by CONSUMING the existing
capabilities at the real external boundaries (git, the verify-system level-4
evaluator, the VectorDB sync, the governance top surface). They build NO second
merge/gate/Sonar/lock truth -- each is a thin seam.

The integrated-candidate Build/Test + Sonar scan ports are NOT defined here:
they are the AG3-056 Pre-Merge-Verification-Runner's productive
``CiBuildTestRunner`` / ``CiSonarScanRunner``, wired by the composition root via
``verify_system.pre_merge_runner.runtime_wiring.build_pre_merge_runners`` (the
old fail-open ``build_sonar_gate_port_for_run`` scan path is REMOVED -- AG3-053
consumes AG3-056 instead). The fast-mode Sanity-Gate (``ProductiveSanityGatePort``)
stays here (closure-owned fast path; AG3-018 will parametrize it later).

The composition root (``build_closure_phase_handler``) is the one productive
wiring point. The handler never builds these itself (DI / truth boundary).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from agentkit.closure.merge_sequence import SanityOutcome

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from agentkit.closure.multi_repo_saga import ClosureRepo, GitBackend
    from agentkit.governance import Governance
    from agentkit.story_context_manager.models import StoryContext
    from agentkit.story_context_manager.types import StoryType

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProductiveSanityGatePort:
    """Fast-mode Sanity-Gate seam (FK-29 §29.1a.6).

    The fast-mode sanity precondition is "tests green AND worktree clean AND
    pre-merge rebase onto ``main`` OK". This adapter genuinely exercises the two
    git-mechanic predicates it can confirm at the real git boundary -- it is NOT
    a blanket no-op:

    1. worktree clean -- ``git status --porcelain`` is empty;
    2. pre-merge rebase OK -- a dry ``git rebase`` of the story branch onto
       ``origin/main`` succeeds (a conflict aborts the rebase and escalates,
       FK-29 §29.1a.6 "Rebase-Konflikt -> Eskalation").

    The third predicate ("tests green") needs a live test run. The fast-mode
    live test runner is the AG3-018 boundary (FK-24 §24.3.4); when no
    ``test_runner`` is injected this adapter fails closed AFTER the real git
    checks -- a fast story without a confirmed test result escalates rather than
    silently merging (FAIL-CLOSED). When AG3-018 injects a real ``test_runner``
    the adapter confirms all three predicates.

    Attributes:
        git_backend: The git side-effect port (the real subprocess backend in
            production; stubbed at the git boundary in tests).
        test_runner: Optional fast-mode test runner returning ``(green, reason)``.
            ``None`` => the tests-green predicate is unconfirmable (AG3-018 not
            yet wired) and the gate fails closed after the git checks.
    """

    git_backend: GitBackend
    test_runner: Callable[[Path], tuple[bool, str | None]] | None = None

    def evaluate(self, story_dir: Path, story_type: StoryType) -> SanityOutcome:
        """Evaluate the fast-mode sanity precondition (real git checks first)."""
        del story_type
        from agentkit.closure.multi_repo_saga import ClosureRepo

        repo = ClosureRepo(name=story_dir.name, repo_root=story_dir)
        clean = self._worktree_clean(repo)
        if not clean.passed:
            return clean
        rebase = self._pre_merge_rebase_ok(repo)
        if not rebase.passed:
            return rebase
        return self._tests_green(story_dir)

    def _worktree_clean(self, repo: ClosureRepo) -> SanityOutcome:
        """Confirm the worktree is clean via ``git status --porcelain``."""
        result = self.git_backend.run(repo, "status", "--porcelain")
        if not result.ok:
            return SanityOutcome(
                passed=False,
                reason=f"git status failed: {result.stderr.strip() or result.returncode}",
            )
        if result.stdout.strip():
            return SanityOutcome(
                passed=False,
                reason="worktree is not clean (uncommitted changes present)",
            )
        return SanityOutcome(passed=True)

    def _pre_merge_rebase_ok(self, repo: ClosureRepo) -> SanityOutcome:
        """Confirm a clean rebase onto ``origin/main`` (abort on conflict)."""
        self.git_backend.run(repo, "fetch", "origin", "main")
        rebase = self.git_backend.run(repo, "rebase", "origin/main")
        if rebase.ok:
            return SanityOutcome(passed=True)
        # A rebase conflict leaves the rebase in progress -- abort it so the
        # worktree is not left mid-rebase, then escalate (FK-29 §29.1a.6).
        self.git_backend.run(repo, "rebase", "--abort")
        return SanityOutcome(
            passed=False,
            reason=(
                "pre-merge rebase onto origin/main failed (conflict): "
                f"{rebase.stderr.strip() or rebase.returncode}"
            ),
        )

    def _tests_green(self, story_dir: Path) -> SanityOutcome:
        """Confirm tests are green via the injected runner (fail-closed if absent)."""
        if self.test_runner is None:
            return SanityOutcome(
                passed=False,
                reason=(
                    "fast-mode sanity gate: worktree clean and rebase OK, but the "
                    "tests-green predicate has no live test runner (AG3-018 boundary) "
                    "-> cannot confirm tests green, escalate"
                ),
            )
        green, reason = self.test_runner(story_dir)
        if green:
            return SanityOutcome(passed=True)
        return SanityOutcome(
            passed=False,
            reason=reason or "fast-mode tests are not green",
        )


@dataclass(frozen=True)
class ProductiveDocFidelityFeedbackPort:
    """Level-4 doc-fidelity feedback seam (FK-38 §38.3.1, non-blocking).

    Consumes ``verify_system.llm_evaluator`` (``role=doc_fidelity``). The level-4
    feedback evaluation (``final_diff`` vs existing docs) has no productive
    callable yet (FK-38 §38.3.1 / AG3-026 builds only the QA-subflow roles). The
    step is MANDATORY but NON-BLOCKING: rather than silently no-op, this seam
    records a human Warning every run until the level-4 capability lands.
    """

    def evaluate_feedback_fidelity(
        self, ctx: StoryContext, story_dir: Path
    ) -> tuple[bool, str | None]:
        """Run the level-4 feedback check; non-blocking Warning when unavailable."""
        del ctx, story_dir
        return (
            False,
            "level-4 doc-fidelity feedback has no productive "
            "verify_system.llm_evaluator feedback callable yet (FK-38 §38.3.1) "
            "-- human review whether existing docs need updating",
        )


@dataclass(frozen=True)
class ProductiveVectorDbSyncPort:
    """VectorDB sync seam (FK-13 §13.7.1, fire-and-forget, non-blocking).

    Triggers an async ``story_sync`` so the freshly closed story is searchable.
    The VectorDB integration is not yet available in the target project (FK-13);
    the step is MANDATORY but NON-BLOCKING: this seam records a human Warning when
    the sync cannot be triggered (never a silent skip; the STEP still runs).
    """

    def trigger_sync(
        self, ctx: StoryContext, story_dir: Path
    ) -> tuple[bool, str | None]:
        """Trigger the (async) VectorDB sync; non-blocking Warning when absent."""
        del ctx, story_dir
        return (
            False,
            "VectorDB sync (story_sync, FK-13 §13.7.1) has no productive "
            "integration yet -- closed story not yet indexed for retrieval",
        )


@dataclass(frozen=True)
class ProductiveGuardDeactivationPort:
    """Guard-deactivation seam (FK-29 §29.5, governance top surface).

    Delegates to ``Governance.deactivate_locks`` (the governance top surface).
    Closure holds NO lock logic itself (single delegation step). Non-blocking: a
    deactivation error is collected as a human Warning, never an ESCALATED verdict
    (the story is already merged).

    Attributes:
        governance: The wired ``Governance`` top surface.
    """

    governance: Governance

    def deactivate(self, story_id: str) -> tuple[bool, str | None]:
        """Deactivate the story locks; non-blocking Warning on any error."""
        try:
            result = self.governance.deactivate_locks(story_id)
        except Exception as exc:  # noqa: BLE001 -- non-blocking step (post-merge)
            logger.warning("guard deactivation failed for story=%s: %s", story_id, exc)
            return (False, f"deactivate_locks raised: {exc}")
        if result.errors:
            return (False, "; ".join(result.errors))
        return (True, None)


__all__ = [
    "ProductiveDocFidelityFeedbackPort",
    "ProductiveGuardDeactivationPort",
    "ProductiveSanityGatePort",
    "ProductiveVectorDbSyncPort",
]
