"""Unit tests for Governance.deactivate_locks (AG3-031 §2.1.4).

Uses Recording-Repository test doubles (not MagicMock) per project rules.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agentkit.governance.hook_registration import RegistrationResult
from agentkit.governance.locks import LockRecordId

# ---------------------------------------------------------------------------
# Recording test doubles
# ---------------------------------------------------------------------------


class _RecordingLockRepo:
    """In-memory recording double for LockRecordRepository."""

    def __init__(self, stored_locks: list[LockRecordId] | None = None) -> None:
        self._locks: list[LockRecordId] = list(stored_locks or [])
        self.deactivate_calls: list[str] = []
        self._raise_on_story: str | None = None

    def fail_for_story(self, story_id: str) -> None:
        """Configure the double to raise on the given story_id."""
        self._raise_on_story = story_id

    def deactivate_locks_for_story(self, story_id: str) -> list[LockRecordId]:
        self.deactivate_calls.append(story_id)
        if self._raise_on_story == story_id:
            raise RuntimeError(f"DB error for story {story_id!r}")
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
    from agentkit.governance.runner import Governance

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
# Tests: idempotency (empty locks)
# ---------------------------------------------------------------------------


class TestDeactivateLocksIdempotent:
    """Calling deactivate_locks when no locks exist is fine."""

    def test_empty_result_when_no_locks(self) -> None:
        repo = _RecordingLockRepo(stored_locks=[])
        gov = _make_governance(repo)

        result = gov.deactivate_locks("story-no-locks")  # type: ignore[union-attr]

        assert result.deactivated_locks == []
        assert result.removed_edge_bundles == []
        assert result.errors == []

    def test_missing_edge_bundle_is_ok(self) -> None:
        """Missing edge-bundle file is not an error."""
        repo = _RecordingLockRepo()
        gov = _make_governance(repo)

        result = gov.deactivate_locks("nonexistent-story")  # type: ignore[union-attr]

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
