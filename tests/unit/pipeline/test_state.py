"""Tests for pipeline state persistence (atomic I/O, roundtrips, robustness)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path  # noqa: TCH003 — used at runtime by tmp_path fixture type

import pytest

from agentkit.exceptions import CorruptStateError
from agentkit.pipeline.state import (
    AttemptRecord,
    atomic_write_json,
    load_attempts,
    load_json_safe,
    load_phase_snapshot,
    load_phase_state,
    load_story_context,
    save_attempt,
    save_phase_snapshot,
    save_phase_state,
    save_story_context,
)
from agentkit.story_context_manager.models import PhaseSnapshot, PhaseState, PhaseStatus, StoryContext
from agentkit.story_context_manager.types import StoryMode, StoryType


def _make_ctx() -> StoryContext:
    """Create a minimal StoryContext for testing."""
    return StoryContext(
        story_id="TEST-001",
        story_type=StoryType.IMPLEMENTATION,
        mode=StoryMode.EXPLORATION,
        title="Test story",
    )


def _make_state() -> PhaseState:
    """Create a minimal PhaseState for testing."""
    return PhaseState(
        story_id="TEST-001",
        phase="setup",
        status=PhaseStatus.IN_PROGRESS,
    )


def _make_snapshot() -> PhaseSnapshot:
    """Create a minimal PhaseSnapshot for testing."""
    return PhaseSnapshot(
        story_id="TEST-001",
        phase="setup",
        status=PhaseStatus.COMPLETED,
        completed_at=datetime(2026, 1, 15, 10, 30, 0, tzinfo=UTC),
        artifacts=["protocol.md"],
        evidence={"tests_passed": True},
    )


def _make_attempt(
    *,
    phase: str = "exploration",
    attempt_id: str = "exploration-001",
    exit_status: PhaseStatus | None = PhaseStatus.COMPLETED,
    outcome: str | None = "completed",
) -> AttemptRecord:
    """Create an AttemptRecord for testing."""
    return AttemptRecord(
        attempt_id=attempt_id,
        phase=phase,
        entered_at=datetime(2026, 1, 15, 10, 0, 0, tzinfo=UTC),
        exit_status=exit_status,
        guard_evaluations=({"guard": "preflight", "passed": True},),
        artifacts_produced=("design.md",),
        outcome=outcome,
    )


# --- atomic_write_json ---


class TestAtomicWriteJson:
    """Tests for atomic JSON file writing."""

    def test_writes_file_with_correct_content(self, tmp_path: Path) -> None:
        target = tmp_path / "data.json"
        data: dict[str, object] = {"key": "value", "count": 42}
        atomic_write_json(target, data)

        assert target.exists()
        loaded = json.loads(target.read_text(encoding="utf-8"))
        assert loaded["key"] == "value"
        assert loaded["count"] == 42

    def test_overwrites_existing_file(self, tmp_path: Path) -> None:
        target = tmp_path / "data.json"
        atomic_write_json(target, {"version": 1})
        atomic_write_json(target, {"version": 2})

        loaded = json.loads(target.read_text(encoding="utf-8"))
        assert loaded["version"] == 2

    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        target = tmp_path / "nested" / "deep" / "data.json"
        atomic_write_json(target, {"nested": True})

        assert target.exists()
        loaded = json.loads(target.read_text(encoding="utf-8"))
        assert loaded["nested"] is True

    def test_no_tmp_file_remains(self, tmp_path: Path) -> None:
        target = tmp_path / "data.json"
        atomic_write_json(target, {"clean": True})

        tmp_files = list(tmp_path.glob("*.tmp"))
        assert tmp_files == []


# --- load_json_safe ---


class TestLoadJsonSafe:
    """Tests for safe JSON loading."""

    def test_loads_existing_file(self, tmp_path: Path) -> None:
        target = tmp_path / "data.json"
        target.write_text('{"key": "value"}', encoding="utf-8")

        result = load_json_safe(target)
        assert result is not None
        assert result["key"] == "value"

    def test_missing_file_returns_none(self, tmp_path: Path) -> None:
        result = load_json_safe(tmp_path / "nonexistent.json")
        assert result is None

    def test_corrupt_file_returns_none(self, tmp_path: Path) -> None:
        target = tmp_path / "bad.json"
        target.write_text("not json", encoding="utf-8")

        result = load_json_safe(target)
        assert result is None

    def test_array_returns_none(self, tmp_path: Path) -> None:
        target = tmp_path / "array.json"
        target.write_text("[1, 2, 3]", encoding="utf-8")

        result = load_json_safe(target)
        assert result is None


# --- save_phase_state / load_phase_state ---


class TestPhaseStatePersistence:
    """Tests for PhaseState roundtrip persistence."""

    def test_roundtrip(self, tmp_path: Path) -> None:
        state = _make_state()
        save_phase_state(tmp_path, state)
        loaded = load_phase_state(tmp_path)

        assert loaded is not None
        assert loaded.story_id == state.story_id
        assert loaded.phase == state.phase
        assert loaded.status == state.status

    def test_writes_to_phase_state_json(self, tmp_path: Path) -> None:
        save_phase_state(tmp_path, _make_state())
        assert (tmp_path / "phase-state.json").exists()

    def test_load_missing_returns_none(self, tmp_path: Path) -> None:
        result = load_phase_state(tmp_path)
        assert result is None

    def test_load_corrupt_raises_error(self, tmp_path: Path) -> None:
        (tmp_path / "phase-state.json").write_text(
            "not json", encoding="utf-8",
        )
        with pytest.raises(CorruptStateError, match="corrupt"):
            load_phase_state(tmp_path)

    def test_load_invalid_schema_raises_error(self, tmp_path: Path) -> None:
        (tmp_path / "phase-state.json").write_text(
            '{"wrong_field": "value"}', encoding="utf-8",
        )
        with pytest.raises(CorruptStateError, match="validation failed"):
            load_phase_state(tmp_path)


# --- save_story_context / load_story_context ---


class TestStoryContextPersistence:
    """Tests for StoryContext roundtrip persistence."""

    def test_roundtrip(self, tmp_path: Path) -> None:
        ctx = _make_ctx()
        save_story_context(tmp_path, ctx)
        loaded = load_story_context(tmp_path)

        assert loaded is not None
        assert loaded.story_id == ctx.story_id
        assert loaded.story_type == ctx.story_type
        assert loaded.mode == ctx.mode
        assert loaded.title == ctx.title

    def test_load_missing_returns_none(self, tmp_path: Path) -> None:
        result = load_story_context(tmp_path)
        assert result is None

    def test_load_corrupt_returns_none(self, tmp_path: Path) -> None:
        (tmp_path / "context.json").write_text(
            "not json", encoding="utf-8",
        )
        result = load_story_context(tmp_path)
        assert result is None


# --- save_attempt / load_attempts ---


class TestAttemptPersistence:
    """Tests for AttemptRecord roundtrip persistence."""

    def test_roundtrip_single(self, tmp_path: Path) -> None:
        attempt = _make_attempt()
        save_attempt(tmp_path, attempt)
        loaded = load_attempts(tmp_path, "exploration")

        assert len(loaded) == 1
        rec = loaded[0]
        assert rec.attempt_id == attempt.attempt_id
        assert rec.phase == attempt.phase
        assert rec.exit_status == PhaseStatus.COMPLETED
        assert rec.outcome == "completed"
        assert rec.artifacts_produced == ("design.md",)

    def test_roundtrip_multiple(self, tmp_path: Path) -> None:
        save_attempt(tmp_path, _make_attempt(attempt_id="exploration-001"))
        save_attempt(tmp_path, _make_attempt(
            attempt_id="exploration-002",
            exit_status=PhaseStatus.FAILED,
            outcome="failed",
        ))

        loaded = load_attempts(tmp_path, "exploration")
        assert len(loaded) == 2
        assert loaded[0].attempt_id == "exploration-001"
        assert loaded[1].attempt_id == "exploration-002"
        assert loaded[1].exit_status == PhaseStatus.FAILED

    def test_load_empty_directory_returns_empty_list(
        self, tmp_path: Path,
    ) -> None:
        result = load_attempts(tmp_path, "exploration")
        assert result == []

    def test_load_nonexistent_phase_returns_empty_list(
        self, tmp_path: Path,
    ) -> None:
        result = load_attempts(tmp_path, "nonexistent")
        assert result == []

    def test_attempt_numbering_increments(self, tmp_path: Path) -> None:
        save_attempt(tmp_path, _make_attempt(attempt_id="a1"))
        save_attempt(tmp_path, _make_attempt(attempt_id="a2"))

        attempts_dir = tmp_path / "phase-runs" / "exploration"
        files = sorted(attempts_dir.glob("attempt-*.json"))
        assert len(files) == 2
        assert files[0].name == "attempt-001.json"
        assert files[1].name == "attempt-002.json"


# --- save_phase_snapshot / load_phase_snapshot ---


class TestPhaseSnapshotPersistence:
    """Tests for PhaseSnapshot roundtrip persistence."""

    def test_roundtrip(self, tmp_path: Path) -> None:
        snapshot = _make_snapshot()
        save_phase_snapshot(tmp_path, snapshot)
        loaded = load_phase_snapshot(tmp_path, "setup")

        assert loaded is not None
        assert loaded.story_id == snapshot.story_id
        assert loaded.phase == snapshot.phase
        assert loaded.status == PhaseStatus.COMPLETED
        assert loaded.artifacts == ["protocol.md"]
        assert loaded.evidence == {"tests_passed": True}

    def test_load_missing_returns_none(self, tmp_path: Path) -> None:
        result = load_phase_snapshot(tmp_path, "setup")
        assert result is None

    def test_writes_to_correct_filename(self, tmp_path: Path) -> None:
        save_phase_snapshot(tmp_path, _make_snapshot())
        assert (tmp_path / "phase-state-setup.json").exists()


# --- Pipeline robustness tests ---


class TestPipelineRobustness:
    """Robustness tests for corrupt/missing state scenarios.

    These verify that the persistence layer handles degraded conditions
    gracefully instead of crashing.
    """

    def test_corrupt_phase_state_raises_error(self, tmp_path: Path) -> None:
        """phase-state.json exists but contains garbage -> CorruptStateError."""
        (tmp_path / "phase-state.json").write_text(
            "{invalid json!!!", encoding="utf-8",
        )
        with pytest.raises(CorruptStateError):
            load_phase_state(tmp_path)

    def test_missing_context_json_returns_none(self, tmp_path: Path) -> None:
        """context.json does not exist at all."""
        assert load_story_context(tmp_path) is None

    def test_corrupt_attempt_is_skipped(self, tmp_path: Path) -> None:
        """One corrupt attempt file does not prevent loading others."""
        # Save a valid attempt
        save_attempt(tmp_path, _make_attempt(attempt_id="good"))

        # Write a corrupt attempt file manually
        corrupt_dir = tmp_path / "phase-runs" / "exploration"
        corrupt_path = corrupt_dir / "attempt-002.json"
        corrupt_path.write_text("not valid json", encoding="utf-8")

        # Save another valid attempt (will be attempt-003 since 002 exists)
        save_attempt(tmp_path, _make_attempt(attempt_id="also-good"))

        loaded = load_attempts(tmp_path, "exploration")
        # The corrupt file is skipped, so we get the two valid ones
        assert len(loaded) == 2
        ids = [r.attempt_id for r in loaded]
        assert "good" in ids
        assert "also-good" in ids

    def test_phase_state_with_wrong_schema_raises_error(
        self, tmp_path: Path,
    ) -> None:
        """phase-state.json has valid JSON but wrong Pydantic schema."""
        atomic_write_json(
            tmp_path / "phase-state.json",
            {"totally": "wrong", "fields": 123},
        )
        with pytest.raises(CorruptStateError, match="validation failed"):
            load_phase_state(tmp_path)

    def test_snapshot_with_corrupt_json_returns_none(
        self, tmp_path: Path,
    ) -> None:
        """phase-state-<phase>.json contains garbage."""
        (tmp_path / "phase-state-verify.json").write_text(
            "{{broken", encoding="utf-8",
        )
        assert load_phase_snapshot(tmp_path, "verify") is None

    def test_load_phase_state_missing_returns_none(self, tmp_path: Path) -> None:
        """Missing phase-state.json returns None (fresh run)."""
        assert load_phase_state(tmp_path) is None

    def test_load_phase_state_non_dict_raises_error(self, tmp_path: Path) -> None:
        """Array instead of object in phase-state.json -> CorruptStateError."""
        (tmp_path / "phase-state.json").write_text(
            "[1, 2, 3]", encoding="utf-8",
        )
        with pytest.raises(CorruptStateError, match="not a JSON object"):
            load_phase_state(tmp_path)
