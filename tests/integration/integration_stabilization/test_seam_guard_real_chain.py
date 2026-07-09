"""Integration: IS seam + budget guards via the REAL installed GuardRunner chain.

AG3-069 ERROR D / MAJOR I: these tests drive the PRODUCTIVE
``evaluate_pre_tool_use`` path (which builds the guard chain via
``_guards_for_state`` and runs it through the REAL ``GuardRunner``) -- NOT a
hand-built ``GuardRunner([SeamAllowlistGuard])``. They prove:

* a write OUTSIDE the declared seams is BLOCKED through the real chain;
* a write INSIDE the declared seams is ALLOWED;
* an IS story with a MISSING/UNBOUND manifest fails CLOSED (FailClosedSeamGuard),
  never silently skips (the AC7 fail-open bug);
* the seam allowlist is materialized to the concept-conform
  ``.agent-guard/seam_allowlist.json`` file and READ by the guard;
* a STANDARD story is unaffected (no IS guard in the chain).

Removing the IS guard wiring from ``_guards_for_state`` (or reverting the
fail-closed ``_maybe_seam_guard``) makes these tests fail.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from agentkit.backend.control_plane.models import (
    EdgeBundle,
    EdgePointer,
    SessionRunBindingView,
    StoryExecutionLockView,
)
from agentkit.backend.governance.guard_evaluation import HookEvent, evaluate_pre_tool_use
from agentkit.backend.governance.protocols import ViolationType
from agentkit.backend.installer.paths import story_dir as _story_dir
from agentkit.backend.integration_stabilization.models import (
    IntegrationScopeManifest,
    ManifestApprovalRecord,
    StabilizationBudgetCaps,
)
from agentkit.backend.integration_stabilization.seam_allowlist_guard import SEAM_ALLOWLIST_FILE
from agentkit.backend.integration_stabilization.state import (
    save_integration_manifest,
    save_manifest_approval,
)
from agentkit.backend.state_backend.story_lifecycle_store import save_story_context
from agentkit.backend.story_context_manager.models import StoryContext
from agentkit.backend.story_context_manager.types import (
    ImplementationContract,
    StoryMode,
    StoryType,
)
from agentkit.harness_client.projectedge.client import LocalEdgePublisher

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.integration

_STORY = "IS-69"
_PROJECT = "tenant-a"
_RUN = "run-is69"


def _bundle(worktree_root: str) -> EdgeBundle:
    now = datetime(2026, 6, 7, 12, 0, tzinfo=UTC)
    return EdgeBundle(
        current=EdgePointer(
            project_key=_PROJECT,
            export_version="edge-001",
            operating_mode="story_execution",
            bundle_dir="_temp/governance/bundles/edge-001",
            sync_after=now + timedelta(minutes=5),
            freshness_class="guarded_read",
            generated_at=now,
        ),
        session=SessionRunBindingView(
            session_id="sess-001",
            project_key=_PROJECT,
            story_id=_STORY,
            run_id=_RUN,
            principal_type="orchestrator",
            worktree_roots=[worktree_root],
            binding_version="bind-001",
            operating_mode="story_execution",
        ),
        lock=StoryExecutionLockView(
            project_key=_PROJECT,
            story_id=_STORY,
            run_id=_RUN,
            lock_type="story_execution",
            status="ACTIVE",
            worktree_roots=[worktree_root],
            binding_version="bind-001",
            activated_at=now,
            updated_at=now,
        ),
        qa_lock=None,
    )


def _manifest(worktree: Path) -> IntegrationScopeManifest:
    seam = str(worktree / "src" / "api")
    return IntegrationScopeManifest(
        version=1,
        project_key=_PROJECT,
        story_id=_STORY,
        implementation_contract="integration_stabilization",
        target_seams=(seam,),
        # Narrow declared repo path (NOT the whole worktree): a write to
        # src/unrelated/ is then outside both the seam and the allowed repo path.
        allowed_repos_paths=(str(worktree / "src" / "api"),),
        integration_targets=("e2e_login",),
        allowed_contract_changes=(),
        stabilization_budget=StabilizationBudgetCaps(
            max_loops=3,
            max_new_surfaces=2,
            max_contract_changes=1,
            max_regressions_per_cycle=1,
        ),
    )


def _approval(m: IntegrationScopeManifest) -> ManifestApprovalRecord:
    return ManifestApprovalRecord(
        project_key=_PROJECT,
        story_id=_STORY,
        run_id=_RUN,
        manifest_version=m.version,
        manifest_hash=m.content_hash,
    )


def _is_ctx() -> StoryContext:
    return StoryContext(
        project_key=_PROJECT,
        story_id=_STORY,
        story_type=StoryType.IMPLEMENTATION,
        implementation_contract=ImplementationContract.INTEGRATION_STABILIZATION,
        execution_route=StoryMode.EXPLORATION,
    )


def _write_event(project_root: Path, worktree: Path, target: Path) -> HookEvent:
    del project_root
    return HookEvent(
        operation="file_write",
        operation_args={"file_path": str(target)},
        freshness_class="mutation",
        cwd=str(worktree),
        session_id="sess-001",
        principal_kind="main",
    )


def _setup_is_story(tmp_path: Path, *, approved: bool) -> Path:
    """Publish an IS edge bundle + persist context (and manifest/approval)."""
    worktree = tmp_path / "worktree"
    worktree.mkdir(parents=True, exist_ok=True)
    LocalEdgePublisher(project_root=tmp_path).publish(_bundle(str(worktree)))
    s_dir = _story_dir(tmp_path, _STORY)
    s_dir.mkdir(parents=True, exist_ok=True)
    save_story_context(s_dir, _is_ctx())
    if approved:
        m = _manifest(worktree)
        save_integration_manifest(s_dir, m)
        save_manifest_approval(s_dir, _approval(m))
    return worktree


class TestSeamGuardViaRealChain:
    def test_write_outside_seam_blocked_via_real_chain(self, tmp_path: Path) -> None:
        worktree = _setup_is_story(tmp_path, approved=True)
        target = worktree / "src" / "unrelated" / "hack.py"

        verdict = evaluate_pre_tool_use(
            _write_event(tmp_path, worktree, target), project_root=tmp_path
        )

        assert verdict.allowed is False

    def test_write_inside_seam_allowed_via_real_chain(self, tmp_path: Path) -> None:
        worktree = _setup_is_story(tmp_path, approved=True)
        target = worktree / "src" / "api" / "handler.py"

        verdict = evaluate_pre_tool_use(
            _write_event(tmp_path, worktree, target), project_root=tmp_path
        )

        assert verdict.allowed is True

    def test_allowlist_materialized_to_agent_guard_file(self, tmp_path: Path) -> None:
        """The seam allowlist is materialized to .agent-guard/seam_allowlist.json."""
        worktree = _setup_is_story(tmp_path, approved=True)
        target = worktree / "src" / "api" / "handler.py"
        evaluate_pre_tool_use(
            _write_event(tmp_path, worktree, target), project_root=tmp_path
        )
        assert (worktree / SEAM_ALLOWLIST_FILE).exists()

    def test_manifest_without_approval_fails_closed_via_real_chain(
        self, tmp_path: Path
    ) -> None:
        """ERROR D: a manifest present but WITHOUT an approval BLOCKS (not skips).

        Truth-boundary: governance detects an IS campaign from the persisted
        manifest artifact (it may not read the protected story context). A
        manifest present but unapproved is a broken IS guard => FailClosed BLOCK.
        """
        worktree = tmp_path / "worktree"
        worktree.mkdir(parents=True, exist_ok=True)
        LocalEdgePublisher(project_root=tmp_path).publish(_bundle(str(worktree)))
        s_dir = _story_dir(tmp_path, _STORY)
        s_dir.mkdir(parents=True, exist_ok=True)
        save_story_context(s_dir, _is_ctx())
        # Manifest present, but NO approval record -> fail-closed.
        save_integration_manifest(s_dir, _manifest(worktree))
        target = worktree / "src" / "api" / "handler.py"

        verdict = evaluate_pre_tool_use(
            _write_event(tmp_path, worktree, target), project_root=tmp_path
        )

        assert verdict.allowed is False
        assert verdict.violation_type is ViolationType.SCOPE_VIOLATION

    def test_binding_mismatch_fails_closed_via_real_chain(self, tmp_path: Path) -> None:
        """ERROR D: a manifest with a wrong-run approval BLOCKS fail-closed."""
        worktree = tmp_path / "worktree"
        worktree.mkdir(parents=True, exist_ok=True)
        LocalEdgePublisher(project_root=tmp_path).publish(_bundle(str(worktree)))
        s_dir = _story_dir(tmp_path, _STORY)
        s_dir.mkdir(parents=True, exist_ok=True)
        save_story_context(s_dir, _is_ctx())
        m = _manifest(worktree)
        save_integration_manifest(s_dir, m)
        # Approval bound to a DIFFERENT run id -> binding integrity fails.
        save_manifest_approval(
            s_dir,
            ManifestApprovalRecord(
                project_key=_PROJECT,
                story_id=_STORY,
                run_id="run-wrong",
                manifest_version=m.version,
                manifest_hash=m.content_hash,
            ),
        )
        target = worktree / "src" / "api" / "handler.py"

        verdict = evaluate_pre_tool_use(
            _write_event(tmp_path, worktree, target), project_root=tmp_path
        )

        assert verdict.allowed is False


class TestSeamGuardFailClosedOnMissingAllowlistFile:
    """ERROR D (round-3): no worktree root => FailClosedSeamGuard => writes blocked.

    With no worktree_roots in the EdgeBundle the materialise+read loop is
    skipped and ``allowlist`` stays ``None``.  The prior behaviour was to fall
    back to the in-memory manifest allowlist (fail-OPEN).  The fix returns
    ``FailClosedSeamGuard`` instead so every mutation is blocked until the
    guard can be properly materialized from a real worktree root.
    """

    def _bundle_no_worktree(self) -> EdgeBundle:
        """EdgeBundle with an empty worktree_roots list."""
        from datetime import UTC, datetime, timedelta

        now = datetime(2026, 6, 7, 12, 0, tzinfo=UTC)
        return EdgeBundle(
            current=EdgePointer(
                project_key=_PROJECT,
                export_version="edge-002",
                operating_mode="story_execution",
                bundle_dir="_temp/governance/bundles/edge-002",
                sync_after=now + timedelta(minutes=5),
                freshness_class="guarded_read",
                generated_at=now,
            ),
            session=SessionRunBindingView(
                session_id="sess-002",
                project_key=_PROJECT,
                story_id=_STORY,
                run_id=_RUN,
                principal_type="orchestrator",
                worktree_roots=[],  # no worktree root -> materialise loop skipped
                binding_version="bind-002",
                operating_mode="story_execution",
            ),
            lock=StoryExecutionLockView(
                project_key=_PROJECT,
                story_id=_STORY,
                run_id=_RUN,
                lock_type="story_execution",
                status="ACTIVE",
                worktree_roots=[],
                binding_version="bind-002",
                activated_at=now,
                updated_at=now,
            ),
            qa_lock=None,
        )

    def test_no_worktree_root_blocks_write_fail_closed(self, tmp_path: Path) -> None:
        """ERROR D: no worktree root => FailClosedSeamGuard => write blocked.

        An IS story with an approved+bound manifest but no worktree roots in
        the EdgeBundle must NOT use the in-memory fallback.  The guard must
        fail closed and block every mutation.  This test would pass (allowing
        the write) if the old in-memory fallback were reinstated -- proving
        the test regresses when the ERROR D fix is reverted.
        """
        from agentkit.harness_client.projectedge.client import LocalEdgePublisher

        LocalEdgePublisher(project_root=tmp_path).publish(self._bundle_no_worktree())
        s_dir = _story_dir(tmp_path, _STORY)
        s_dir.mkdir(parents=True, exist_ok=True)
        save_story_context(s_dir, _is_ctx())
        # Build a manifest whose seam is inside a dummy (non-existent) worktree.
        dummy_worktree = tmp_path / "worktree-nonexistent"
        m = _manifest(dummy_worktree)
        save_integration_manifest(s_dir, m)
        save_manifest_approval(s_dir, _approval(m))

        # The write target is INSIDE the declared seam -- the in-memory fallback
        # would allow it; the fail-closed guard must block it.
        target = dummy_worktree / "src" / "api" / "handler.py"

        verdict = evaluate_pre_tool_use(
            HookEvent(
                operation="file_write",
                operation_args={"file_path": str(target)},
                freshness_class="mutation",
                cwd=str(dummy_worktree),
                session_id="sess-002",
                principal_kind="main",
            ),
            project_root=tmp_path,
        )

        # Must be BLOCKED (fail-closed), NOT allowed via in-memory fallback.
        assert verdict.allowed is False, (
            "ERROR D: write must be blocked when no worktree root is available; "
            "the in-memory fallback is a fail-OPEN and must not be used"
        )


class TestBudgetRegressionCapViaRealChain:
    """AC4/MAJOR I: the regression-per-cycle cap blocks via the REAL guard chain."""

    def test_regression_cap_exhausted_blocks_via_real_chain(
        self, tmp_path: Path
    ) -> None:
        """A regression count at the cap blocks the next mutation fail-closed.

        This drives the REAL installed GuardRunner chain (via
        ``evaluate_pre_tool_use``) — NOT the StabilizationBudget model property —
        and exercises the regression-per-cycle cap specifically (max=1, used=1).
        """
        import json

        worktree = _setup_is_story(tmp_path, approved=True)
        s_dir = _story_dir(tmp_path, _STORY)
        # Regression cap is 1 (see _manifest); a count of 1 exhausts it.
        (s_dir / "integration_budget.json").write_text(
            json.dumps(
                {
                    "loops_used": 0,
                    "new_surfaces_used": 0,
                    "contract_changes_used": 0,
                    "regressions_this_cycle": 1,
                }
            ),
            encoding="utf-8",
        )
        # Write a path INSIDE the seam so the seam guard would allow it — the
        # block must come from the budget guard (regression cap), not the seam.
        target = worktree / "src" / "api" / "fix.py"

        verdict = evaluate_pre_tool_use(
            _write_event(tmp_path, worktree, target), project_root=tmp_path
        )

        assert verdict.allowed is False
        assert verdict.violation_type is ViolationType.POLICY_VIOLATION


class TestStandardStoryUnaffectedViaRealChain:
    def test_standard_story_write_not_blocked_by_is_guard(
        self, tmp_path: Path
    ) -> None:
        """Contract gate: a STANDARD story is unaffected (no IS guard in chain)."""
        worktree = tmp_path / "worktree"
        worktree.mkdir(parents=True, exist_ok=True)
        LocalEdgePublisher(project_root=tmp_path).publish(_bundle(str(worktree)))
        s_dir = _story_dir(tmp_path, _STORY)
        s_dir.mkdir(parents=True, exist_ok=True)
        save_story_context(
            s_dir,
            StoryContext(
                project_key=_PROJECT,
                story_id=_STORY,
                story_type=StoryType.IMPLEMENTATION,
                implementation_contract=ImplementationContract.STANDARD,
                execution_route=StoryMode.EXPLORATION,
            ),
        )
        # A write inside the worktree (ScopeGuard-allowed) is not IS-blocked.
        target = worktree / "src" / "anything" / "file.py"

        verdict = evaluate_pre_tool_use(
            _write_event(tmp_path, worktree, target), project_root=tmp_path
        )

        assert verdict.allowed is True
