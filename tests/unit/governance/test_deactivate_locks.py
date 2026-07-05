"""Unit tests for Governance.deactivate_locks (AG3-031 §2.1.4).

Uses Recording-Repository test doubles (not MagicMock) per project rules.

AG3-031 Pass-3 FK-30-Korrektur 2026-05-24 (Fix E6):
  LockRecordNotFoundError is raised by repo on unknown story_id; Governance
  surfaces it as errors[0] rather than silently returning empty result.
  Story AK5 corrected to fail-closed semantics.

AG3-145 sub-step D (FK-10 §10.2.4a):
  The WorktreeRepository dependency was removed. deactivate_locks no longer
  writes physically into worktrees; the dev-local .agent-guard projection runs
  over the edge bundle-publication + tombstone_worktree_roots mechanism. The
  former Fix-E4 worktree-loop tests were deleted with the removed behavior.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agentkit.backend.governance.errors import LockRecordNotFoundError
from agentkit.backend.governance.hook_registration import RegistrationResult
from agentkit.backend.governance.locks import LockRecordId

# ---------------------------------------------------------------------------
# Recording test doubles
# ---------------------------------------------------------------------------


class _RecordingLockRepo:
    """In-memory recording double for LockRecordRepository.

    Enforces fail-closed semantics (Fix E6): raises LockRecordNotFoundError
    when no locks are stored for the requested story_id.
    """

    def __init__(self, stored_locks: list[LockRecordId] | None = None) -> None:
        self._locks: list[LockRecordId] = list(stored_locks or [])
        self.deactivate_calls: list[str] = []
        self._raise_on_story: str | None = None
        # story IDs that exist but all locks already INACTIVE (idempotent path)
        self._known_story_ids: set[str] = set()
        if stored_locks:
            for lid in stored_locks:
                self._known_story_ids.add(lid.split("|")[1] if "|" in lid else lid)

    def mark_known(self, story_id: str) -> None:
        """Mark story_id as known (exists in DB, possibly already INACTIVE)."""
        self._known_story_ids.add(story_id)

    def fail_for_story(self, story_id: str) -> None:
        """Configure the double to raise RuntimeError (DB error) on the given story_id."""
        self._raise_on_story = story_id

    def deactivate_locks_for_story(self, story_id: str) -> list[LockRecordId]:
        self.deactivate_calls.append(story_id)
        if self._raise_on_story == story_id:
            raise RuntimeError(f"DB error for story {story_id!r}")
        # Check if story is known at all (fail-closed — Fix E6)
        has_locks = any(story_id in lid for lid in self._locks)
        if not has_locks and story_id not in self._known_story_ids:
            raise LockRecordNotFoundError(
                f"No lock records found for story_id={story_id!r}."
            )
        removed = [lid for lid in self._locks if story_id in lid]
        self._locks = [lid for lid in self._locks if story_id not in lid]
        return removed


class _RecordingHookRepo:
    """Stub hook repo (unused in deactivate_locks tests)."""

    def register(self, project_key: str, hook_definitions: list) -> RegistrationResult:
        return RegistrationResult()

    def list_for_project(self, project_key: str) -> list:
        return []

    def clear_for_project(self, project_key: str) -> None:
        pass


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _make_governance(
    lock_repo: _RecordingLockRepo | None = None,
    project_key: str = "test-project",
) -> object:
    from agentkit.backend.governance.runner import Governance

    return Governance(
        hook_repo=_RecordingHookRepo(),  # type: ignore[arg-type]
        lock_repo=lock_repo or _RecordingLockRepo(),  # type: ignore[arg-type]
        project_key=project_key,
    )


# ---------------------------------------------------------------------------
# Tests: happy path
# ---------------------------------------------------------------------------


class TestDeactivateLocksHappyPath:
    """deactivate_locks removes locks and edge bundles."""

    def test_locks_deactivated(self) -> None:
        lock_id = LockRecordId("test-project|story-001|run-1|story_execution")
        repo = _RecordingLockRepo(stored_locks=[lock_id])
        gov = _make_governance(repo)

        result = gov.deactivate_locks("story-001")  # type: ignore[union-attr]

        assert lock_id in result.deactivated_locks
        assert result.errors == []

    def test_edge_bundle_removed(self, tmp_path: Path) -> None:
        """Edge bundle file is removed when present."""
        story_id = "story-edge-001"
        bundle_path = tmp_path / "_temp" / "governance" / story_id / "edge-bundle.json"
        bundle_path.parent.mkdir(parents=True, exist_ok=True)
        bundle_path.write_text('{"status": "active"}')

        repo = _RecordingLockRepo()
        gov = _make_governance(repo)

        import os

        old_cwd = Path.cwd()
        os.chdir(tmp_path)
        try:
            result = gov.deactivate_locks(story_id)  # type: ignore[union-attr]
        finally:
            os.chdir(old_cwd)

        assert not bundle_path.exists()
        # Path is relative (under tmp_path) — check it's in result
        assert len(result.removed_edge_bundles) == 1

    def test_repo_called_with_story_id(self) -> None:
        repo = _RecordingLockRepo()
        gov = _make_governance(repo)

        gov.deactivate_locks("my-story")  # type: ignore[union-attr]

        assert "my-story" in repo.deactivate_calls


# ---------------------------------------------------------------------------
# Tests: idempotency (re-call when all locks already INACTIVE)
# ---------------------------------------------------------------------------


class TestDeactivateLocksIdempotent:
    """Calling deactivate_locks when all locks are already INACTIVE returns empty list."""

    def test_already_inactive_returns_empty_no_error(self) -> None:
        """Story is known (locks previously deactivated) — empty result, no error.

        AG3-031 Pass-3 Fix E6: story_id must be known (mark_known).
        Unknown story raises LockRecordNotFoundError (surfaced in errors).
        """
        repo = _RecordingLockRepo(stored_locks=[])
        repo.mark_known("story-already-inactive")
        gov = _make_governance(repo)

        result = gov.deactivate_locks("story-already-inactive")  # type: ignore[union-attr]

        assert result.deactivated_locks == []
        assert result.removed_edge_bundles == []
        assert result.errors == []

    def test_unknown_story_id_surfaced_in_errors(self) -> None:
        """Completely unknown story_id → fail-closed → error in errors[0].

        AG3-031 Pass-3 Fix E6: LockRecordNotFoundError is caught by Governance
        and placed in errors[], not re-raised (unlike DB errors).
        Story AK5 corrected: fail-closed semantics.
        """
        repo = _RecordingLockRepo(stored_locks=[])
        gov = _make_governance(repo)

        result = gov.deactivate_locks("unknown-story-id")  # type: ignore[union-attr]

        assert len(result.errors) >= 1
        assert any("unknown-story-id" in e or "lock records" in e for e in result.errors)

    def test_missing_edge_bundle_is_ok(self) -> None:
        """Missing edge-bundle file is not an error when locks were deactivated."""
        lock_id = LockRecordId("test-project|story-no-bundle|run-1|story_execution")
        repo = _RecordingLockRepo(stored_locks=[lock_id])
        gov = _make_governance(repo)

        result = gov.deactivate_locks("story-no-bundle")  # type: ignore[union-attr]

        assert result.errors == []
        assert result.removed_edge_bundles == []


# ---------------------------------------------------------------------------
# Tests: IO error handling
# ---------------------------------------------------------------------------


class TestDeactivateLocksIOErrors:
    """IO errors on edge-bundle deletion go into errors[], not raised."""

    def test_io_error_on_bundle_deletion_collected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        story_id = "story-io-fail"
        bundle_path = tmp_path / "_temp" / "governance" / story_id / "edge-bundle.json"
        bundle_path.parent.mkdir(parents=True, exist_ok=True)
        bundle_path.write_text("{}")

        # Monkeypatch Path.unlink to raise OSError
        original_unlink = Path.unlink

        def _failing_unlink(self: Path, missing_ok: bool = False) -> None:
            if "edge-bundle.json" in str(self):
                raise OSError("Permission denied (simulated)")
            original_unlink(self, missing_ok=missing_ok)  # type: ignore[call-arg]

        monkeypatch.setattr(Path, "unlink", _failing_unlink)

        repo = _RecordingLockRepo()
        gov = _make_governance(repo)

        import os

        old_cwd = Path.cwd()
        os.chdir(tmp_path)
        try:
            result = gov.deactivate_locks(story_id)  # type: ignore[union-attr]
        finally:
            os.chdir(old_cwd)

        assert len(result.errors) >= 1
        assert any("Permission denied" in e or "edge-bundle" in e for e in result.errors)
        assert result.removed_edge_bundles == []

    def test_db_error_is_raised(self) -> None:
        """Critical DB errors bubble up, not swallowed."""
        repo = _RecordingLockRepo()
        repo.fail_for_story("story-db-fail")
        gov = _make_governance(repo)

        with pytest.raises(RuntimeError, match="DB error"):
            gov.deactivate_locks("story-db-fail")  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# Tests: DeactivationResult model
# ---------------------------------------------------------------------------


class TestDeactivationResultModel:
    """DeactivationResult Pydantic model works correctly."""

    def test_empty_defaults(self) -> None:
        from agentkit.backend.governance.locks import DeactivationResult

        result = DeactivationResult()
        assert result.deactivated_locks == []
        assert result.removed_edge_bundles == []
        assert result.errors == []

    def test_populated_result(self) -> None:
        from agentkit.backend.governance.locks import DeactivationResult

        lid = LockRecordId("proj|story|run|type")
        p = Path("_temp/governance/story/edge-bundle.json")
        result = DeactivationResult(
            deactivated_locks=[lid],
            removed_edge_bundles=[p],
            errors=["some error"],
        )
        assert result.deactivated_locks == [lid]
        assert result.removed_edge_bundles == [p]
        assert result.errors == ["some error"]


# ---------------------------------------------------------------------------
# Tests: AC8 — governance deactivation no longer writes into worktrees (AG3-145 D)
# ---------------------------------------------------------------------------


class TestDeactivateLocksDoesNotTouchWorktrees:
    """AG3-145 D (AC8, FK-10 §10.2.4a): deactivate_locks never writes worktrees.

    The physical ``.agent-guard`` projection (lock-export removal + mode marker)
    moved off the backend entirely onto the edge bundle-publication + tombstone
    mechanism (proven edge-side in
    ``tests/unit/projectedge/test_client.py::test_local_edge_publisher_removes_tombstoned_lock_export``).
    Governance therefore must leave a worktree's ``.agent-guard`` files untouched.
    """

    def test_worktree_agent_guard_files_are_untouched(self, tmp_path: Path) -> None:
        import os

        # A worktree with a live dev-local lock export + no mode marker.
        worktree = tmp_path / "worktrees" / "story-wt"
        guard = worktree / ".agent-guard"
        guard.mkdir(parents=True)
        lock_file = guard / "lock.json"
        lock_file.write_text('{"status": "active"}', encoding="utf-8")

        repo = _RecordingLockRepo()
        repo.mark_known("story-untouched")
        gov = _make_governance(repo)

        old_cwd = Path.cwd()
        os.chdir(tmp_path)
        try:
            result = gov.deactivate_locks("story-untouched")  # type: ignore[union-attr]
        finally:
            os.chdir(old_cwd)

        # Governance did NOT reach into the worktree: the lock export survives and
        # no mode.json was written there (that is the edge's job now).
        assert lock_file.exists()
        assert not (guard / "mode.json").exists()
        # No worktree lock-export path is reported as removed by the backend.
        assert result.removed_lock_exports == []  # type: ignore[union-attr]
        assert result.errors == []  # type: ignore[union-attr]
