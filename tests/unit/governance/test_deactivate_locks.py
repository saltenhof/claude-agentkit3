"""Unit tests for Governance.deactivate_locks (AG3-031 §2.1.4).

Uses Recording-Repository test doubles (not MagicMock) per project rules.

AG3-031 Pass-3 FK-30-Korrektur 2026-05-24 (Fix E6):
  LockRecordNotFoundError is raised by repo on unknown story_id; Governance
  surfaces it as errors[0] rather than silently returning empty result.
  Story AK5 corrected to fail-closed semantics.

AG3-031 Pass-4 (Fix E4):
  WorktreeRepository injected into Governance; _restore_ai_augmented_mode
  iterates over all worktree paths, removing .agent-guard/lock.json and
  writing .agent-guard/mode.json in each.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agentkit.governance.errors import LockRecordNotFoundError
from agentkit.governance.hook_registration import RegistrationResult
from agentkit.governance.locks import LockRecordId

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


class _RecordingWorktreeRepo:
    """Recording test-double for WorktreeRepository (Fix E4).

    Returns a configurable list of worktree paths.  Records calls.
    """

    def __init__(self, worktree_paths: list[Path] | None = None) -> None:
        self._paths: list[Path] = list(worktree_paths or [])
        self.calls: list[str] = []

    def list_worktree_paths(self, story_id: str) -> list[Path]:
        self.calls.append(story_id)
        return self._paths


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _make_governance(
    lock_repo: _RecordingLockRepo | None = None,
    project_key: str = "test-project",
    worktree_repo: _RecordingWorktreeRepo | None = None,
) -> object:
    from agentkit.governance.runner import Governance

    return Governance(
        hook_repo=_RecordingHookRepo(),  # type: ignore[arg-type]
        lock_repo=lock_repo or _RecordingLockRepo(),  # type: ignore[arg-type]
        project_key=project_key,
        worktree_repo=worktree_repo or _RecordingWorktreeRepo(),  # type: ignore[arg-type]
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
        from agentkit.governance.locks import DeactivationResult

        result = DeactivationResult()
        assert result.deactivated_locks == []
        assert result.removed_edge_bundles == []
        assert result.errors == []

    def test_populated_result(self) -> None:
        from agentkit.governance.locks import DeactivationResult

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
# Tests: Worktree loop (Fix E4 — FK-30 §30.6.0 + FK-22 §22.7)
# ---------------------------------------------------------------------------


class TestDeactivateLocksWorktreeLoop:
    """_restore_ai_augmented_mode iterates over all worktree paths.

    Each worktree's .agent-guard/lock.json is deleted and
    .agent-guard/mode.json receives the ai_augmented marker.
    """

    def _setup_worktree(self, base: Path, name: str) -> Path:
        """Create a worktree dir with .agent-guard/lock.json present."""
        wt = base / name
        guard = wt / ".agent-guard"
        guard.mkdir(parents=True, exist_ok=True)
        (guard / "lock.json").write_text('{"status": "active"}', encoding="utf-8")
        return wt

    def test_lock_json_removed_in_each_worktree(self, tmp_path: Path) -> None:
        """After deactivate_locks, all .agent-guard/lock.json files are gone."""
        wt1 = self._setup_worktree(tmp_path, "wt-alpha")
        wt2 = self._setup_worktree(tmp_path, "wt-beta")

        wt_repo = _RecordingWorktreeRepo(worktree_paths=[wt1, wt2])
        lock_repo = _RecordingLockRepo()
        lock_repo.mark_known("story-wt-001")
        gov = _make_governance(lock_repo, worktree_repo=wt_repo)

        gov.deactivate_locks("story-wt-001")  # type: ignore[union-attr]

        assert not (wt1 / ".agent-guard" / "lock.json").exists(), (
            "lock.json must be deleted from wt-alpha"
        )
        assert not (wt2 / ".agent-guard" / "lock.json").exists(), (
            "lock.json must be deleted from wt-beta"
        )

    def test_mode_json_written_in_each_worktree(self, tmp_path: Path) -> None:
        """After deactivate_locks, .agent-guard/mode.json has ai_augmented marker."""
        import json

        wt1 = self._setup_worktree(tmp_path, "wt-one")
        wt2 = self._setup_worktree(tmp_path, "wt-two")

        wt_repo = _RecordingWorktreeRepo(worktree_paths=[wt1, wt2])
        lock_repo = _RecordingLockRepo()
        lock_repo.mark_known("story-mode-001")
        gov = _make_governance(lock_repo, worktree_repo=wt_repo)

        gov.deactivate_locks("story-mode-001")  # type: ignore[union-attr]

        for wt, name in [(wt1, "wt-one"), (wt2, "wt-two")]:
            mode_file = wt / ".agent-guard" / "mode.json"
            assert mode_file.exists(), f"mode.json must exist in {name}"
            data = json.loads(mode_file.read_text(encoding="utf-8"))
            assert data["operating_mode"] == "ai_augmented", (
                f"mode.json in {name} must have operating_mode=ai_augmented"
            )
            assert data["story_id"] == "story-mode-001"

    def test_removed_lock_exports_collects_worktree_lock_paths(
        self, tmp_path: Path
    ) -> None:
        """removed_lock_exports includes .agent-guard/lock.json paths from worktrees."""
        wt1 = self._setup_worktree(tmp_path, "wt-x")
        wt2 = self._setup_worktree(tmp_path, "wt-y")

        wt_repo = _RecordingWorktreeRepo(worktree_paths=[wt1, wt2])
        lock_repo = _RecordingLockRepo()
        lock_repo.mark_known("story-collect-001")
        gov = _make_governance(lock_repo, worktree_repo=wt_repo)

        result = gov.deactivate_locks("story-collect-001")  # type: ignore[union-attr]

        lock_paths = result.removed_lock_exports  # type: ignore[union-attr]
        assert len(lock_paths) == 2
        names = {p.name for p in lock_paths}
        assert "lock.json" in names

    def test_worktree_without_agent_guard_skipped(self, tmp_path: Path) -> None:
        """Worktrees without .agent-guard directory are skipped without error."""
        # Worktree exists but has no .agent-guard dir
        wt_no_guard = tmp_path / "wt-no-guard"
        wt_no_guard.mkdir()

        wt_repo = _RecordingWorktreeRepo(worktree_paths=[wt_no_guard])
        lock_repo = _RecordingLockRepo()
        lock_repo.mark_known("story-no-guard")
        gov = _make_governance(lock_repo, worktree_repo=wt_repo)

        result = gov.deactivate_locks("story-no-guard")  # type: ignore[union-attr]

        # No errors; no removed exports; restored may be False (nothing written)
        assert result.errors == []  # type: ignore[union-attr]
        assert result.removed_lock_exports == []  # type: ignore[union-attr]

    def test_restored_true_when_at_least_one_worktree_written(
        self, tmp_path: Path
    ) -> None:
        """restored_to_ai_augmented is True when at least one mode.json is written."""
        wt = self._setup_worktree(tmp_path, "wt-restore")

        wt_repo = _RecordingWorktreeRepo(worktree_paths=[wt])
        lock_repo = _RecordingLockRepo()
        lock_repo.mark_known("story-restore-001")
        gov = _make_governance(lock_repo, worktree_repo=wt_repo)

        result = gov.deactivate_locks("story-restore-001")  # type: ignore[union-attr]

        assert result.restored_to_ai_augmented is True  # type: ignore[union-attr]

    def test_worktree_repo_called_with_story_id(self, tmp_path: Path) -> None:
        """list_worktree_paths is called with the correct story_id."""
        wt_repo = _RecordingWorktreeRepo(worktree_paths=[])
        lock_repo = _RecordingLockRepo()
        lock_repo.mark_known("story-track-001")
        gov = _make_governance(lock_repo, worktree_repo=wt_repo)

        gov.deactivate_locks("story-track-001")  # type: ignore[union-attr]

        assert "story-track-001" in wt_repo.calls
