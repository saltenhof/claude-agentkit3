"""Unit tests for the IS manifest save/approval boundary (AG3-069 ERROR F/G).

AC3 (repo-set boundary) + AC11 (approval telemetry): these tests drive the real
``save_integration_manifest`` / ``approve_manifest`` boundary and prove the
repo-set check (``target_seams`` AND ``allowed_repos_paths`` vs bound worktree
roots) is enforced fail-closed BEFORE persisting, and that the
``integration_manifest_approved`` event is emitted at the approval boundary.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from agentkit.integration_stabilization.models import (
    IntegrationScopeManifest,
    ManifestApprovalRecord,
    StabilizationBudgetCaps,
)
from agentkit.integration_stabilization.state import (
    IS_MANIFEST_FILE,
    RepoSetViolationError,
    approve_manifest,
    save_integration_manifest,
)
from agentkit.telemetry.emitters import MemoryEmitter
from agentkit.telemetry.events import EventType

if TYPE_CHECKING:
    from pathlib import Path

_STORY = "IS-69"
_RUN = "run-is69"


def _caps() -> StabilizationBudgetCaps:
    return StabilizationBudgetCaps(
        max_loops=3,
        max_new_surfaces=2,
        max_contract_changes=1,
        max_regressions_per_cycle=1,
    )


def _manifest(
    target_seams: tuple[str, ...] = ("/wt/main/src/api/",),
    allowed_repos_paths: tuple[str, ...] = ("/wt/main/src/",),
) -> IntegrationScopeManifest:
    return IntegrationScopeManifest(
        version=1,
        project_key="PROJ",
        story_id=_STORY,
        implementation_contract="integration_stabilization",
        target_seams=target_seams,
        allowed_repos_paths=allowed_repos_paths,
        integration_targets=("e2e_login",),
        allowed_contract_changes=(),
        stabilization_budget=_caps(),
    )


def _approval(m: IntegrationScopeManifest) -> ManifestApprovalRecord:
    return ManifestApprovalRecord(
        project_key=m.project_key,
        story_id=m.story_id,
        run_id=_RUN,
        manifest_version=m.version,
        manifest_hash=m.content_hash,
    )


class TestSaveRepoSetEnforcement:
    def test_save_within_bounds_persists(self, tmp_path: Path) -> None:
        m = _manifest()
        save_integration_manifest(tmp_path, m, bound_roots=("/wt/main/",))
        assert (tmp_path / IS_MANIFEST_FILE).exists()

    def test_save_allowed_repo_path_outside_bounds_rejected(
        self, tmp_path: Path
    ) -> None:
        m = _manifest(allowed_repos_paths=("/other/repo/src/",))
        with pytest.raises(RepoSetViolationError):
            save_integration_manifest(tmp_path, m, bound_roots=("/wt/main/",))
        assert not (tmp_path / IS_MANIFEST_FILE).exists()

    def test_save_target_seam_outside_bounds_rejected(self, tmp_path: Path) -> None:
        """ERROR F: target_seams are ALSO covered by the repo-set check."""
        m = _manifest(target_seams=("/other/repo/seam/",))
        with pytest.raises(RepoSetViolationError):
            save_integration_manifest(tmp_path, m, bound_roots=("/wt/main/",))
        assert not (tmp_path / IS_MANIFEST_FILE).exists()

    def test_save_without_bound_roots_skips_check(self, tmp_path: Path) -> None:
        """No bound_roots => low-level write (fixtures path), no enforcement."""
        m = _manifest(allowed_repos_paths=("/anywhere/",))
        save_integration_manifest(tmp_path, m)
        assert (tmp_path / IS_MANIFEST_FILE).exists()


class TestApproveManifestBoundary:
    def test_approve_within_bounds_persists_and_emits(self, tmp_path: Path) -> None:
        m = _manifest()
        emitter = MemoryEmitter()
        approve_manifest(
            tmp_path,
            m,
            _approval(m),
            bound_roots=("/wt/main/",),
            current_run_id=_RUN,
            emitter=emitter,
        )
        assert (tmp_path / IS_MANIFEST_FILE).exists()
        events = emitter.query(_STORY, EventType.INTEGRATION_MANIFEST_APPROVED)
        assert len(events) == 1
        assert events[0].payload["manifest_hash"] == m.content_hash

    def test_approve_repo_set_violation_rejected_before_persist(
        self, tmp_path: Path
    ) -> None:
        m = _manifest(allowed_repos_paths=("/other/repo/",))
        emitter = MemoryEmitter()
        with pytest.raises(RepoSetViolationError):
            approve_manifest(
                tmp_path,
                m,
                _approval(m),
                bound_roots=("/wt/main/",),
                current_run_id=_RUN,
                emitter=emitter,
            )
        assert not (tmp_path / IS_MANIFEST_FILE).exists()
        assert emitter.query(_STORY, EventType.INTEGRATION_MANIFEST_APPROVED) == []

    def test_approve_binding_mismatch_rejected(self, tmp_path: Path) -> None:
        m = _manifest()
        bad_approval = ManifestApprovalRecord(
            project_key=m.project_key,
            story_id=m.story_id,
            run_id="run-OTHER",  # wrong run
            manifest_version=m.version,
            manifest_hash=m.content_hash,
        )
        with pytest.raises(ValueError, match="bind"):
            approve_manifest(
                tmp_path,
                m,
                bad_approval,
                bound_roots=("/wt/main/",),
                current_run_id=_RUN,
            )
        assert not (tmp_path / IS_MANIFEST_FILE).exists()
