"""Tests for pipeline state persistence (atomic I/O, roundtrips, robustness)."""

from __future__ import annotations

import json
import sqlite3
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
from agentkit.state_backend.config import ALLOW_SQLITE_ENV, STATE_BACKEND_ENV
from agentkit.state_backend.store import reset_backend_cache_for_tests
from agentkit.story_context_manager.models import (
    PhaseSnapshot,
    PhaseState,
    PhaseStatus,
    StoryContext,
)
from agentkit.story_context_manager.types import StoryMode, StoryType


@pytest.fixture(autouse=True)
def sqlite_backend_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(STATE_BACKEND_ENV, "sqlite")
    monkeypatch.setenv(ALLOW_SQLITE_ENV, "1")
    reset_backend_cache_for_tests()
    yield
    reset_backend_cache_for_tests()


def _story_dir(root: Path, story_id: str = "TEST-001") -> Path:
    story_dir = root / "stories" / story_id
    story_dir.mkdir(parents=True, exist_ok=True)
    return story_dir


def _make_ctx() -> StoryContext:
    """Create a minimal StoryContext for testing."""
    return StoryContext(
        project_key="test-project",
        story_id="TEST-001",
        story_type=StoryType.IMPLEMENTATION,
        execution_route=StoryMode.EXPLORATION,
        title="Test story",
    )


def _bootstrap_context(story_dir: Path) -> StoryContext:
    ctx = _make_ctx()
    save_story_context(story_dir, ctx)
    return ctx


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
        story_dir = _story_dir(tmp_path)
        state = _make_state()
        _bootstrap_context(story_dir)
        save_phase_state(story_dir, state)
        loaded = load_phase_state(story_dir)

        assert loaded is not None
        assert loaded.story_id == state.story_id
        assert loaded.phase == state.phase
        assert loaded.status == state.status

    def test_writes_to_phase_state_json(self, tmp_path: Path) -> None:
        story_dir = _story_dir(tmp_path)
        _bootstrap_context(story_dir)
        save_phase_state(story_dir, _make_state())
        assert (story_dir / "phase-state.json").exists()

    def test_load_missing_returns_none(self, tmp_path: Path) -> None:
        result = load_phase_state(_story_dir(tmp_path))
        assert result is None

    def test_load_corrupt_raises_error(self, tmp_path: Path) -> None:
        story_dir = _story_dir(tmp_path)
        _bootstrap_context(story_dir)
        save_phase_state(story_dir, _make_state())
        with sqlite3.connect(story_dir / ".agentkit" / "state.sqlite3") as conn:
            conn.execute("UPDATE phase_states SET payload_json = 'not json'")
            conn.commit()
        with pytest.raises(CorruptStateError, match="corrupt"):
            load_phase_state(story_dir)

    def test_load_invalid_schema_raises_error(self, tmp_path: Path) -> None:
        story_dir = _story_dir(tmp_path)
        _bootstrap_context(story_dir)
        save_phase_state(story_dir, _make_state())
        with sqlite3.connect(story_dir / ".agentkit" / "state.sqlite3") as conn:
            conn.execute(
                "UPDATE phase_states SET payload_json = ?",
                ('{"wrong_field": "value"}',),
            )
            conn.commit()
        with pytest.raises(CorruptStateError, match="payload is invalid"):
            load_phase_state(story_dir)


# --- save_story_context / load_story_context ---


class TestStoryContextPersistence:
    """Tests for StoryContext roundtrip persistence."""

    def test_roundtrip(self, tmp_path: Path) -> None:
        story_dir = _story_dir(tmp_path)
        ctx = _make_ctx()
        save_story_context(story_dir, ctx)
        loaded = load_story_context(story_dir)

        assert loaded is not None
        assert loaded.story_id == ctx.story_id
        assert loaded.story_type == ctx.story_type
        assert loaded.execution_route == ctx.execution_route
        assert loaded.title == ctx.title

    def test_load_missing_returns_none(self, tmp_path: Path) -> None:
        result = load_story_context(_story_dir(tmp_path))
        assert result is None

    def test_load_corrupt_returns_none(self, tmp_path: Path) -> None:
        story_dir = _story_dir(tmp_path)
        save_story_context(story_dir, _make_ctx())
        with sqlite3.connect(story_dir / ".agentkit" / "state.sqlite3") as conn:
            conn.execute("UPDATE story_contexts SET payload_json = 'not json'")
            conn.commit()
        with pytest.raises(CorruptStateError, match="invalid"):
            load_story_context(story_dir)


# --- save_attempt / load_attempts ---


class TestAttemptPersistence:
    """Tests for AttemptRecord roundtrip persistence."""

    def test_roundtrip_single(self, tmp_path: Path) -> None:
        story_dir = _story_dir(tmp_path)
        _bootstrap_context(story_dir)
        attempt = _make_attempt()
        save_attempt(story_dir, attempt)
        loaded = load_attempts(story_dir, "exploration")

        assert len(loaded) == 1
        rec = loaded[0]
        assert rec.attempt_id == attempt.attempt_id
        assert rec.phase == attempt.phase
        assert rec.exit_status == PhaseStatus.COMPLETED
        assert rec.outcome == "completed"
        assert rec.artifacts_produced == ("design.md",)

    def test_roundtrip_multiple(self, tmp_path: Path) -> None:
        story_dir = _story_dir(tmp_path)
        _bootstrap_context(story_dir)
        save_attempt(story_dir, _make_attempt(attempt_id="exploration-001"))
        save_attempt(
            story_dir,
            _make_attempt(
                attempt_id="exploration-002",
                exit_status=PhaseStatus.FAILED,
                outcome="failed",
            ),
        )

        loaded = load_attempts(story_dir, "exploration")
        assert len(loaded) == 2
        assert loaded[0].attempt_id == "exploration-001"
        assert loaded[1].attempt_id == "exploration-002"
        assert loaded[1].exit_status == PhaseStatus.FAILED

    def test_load_empty_directory_returns_empty_list(
        self,
        tmp_path: Path,
    ) -> None:
        result = load_attempts(_story_dir(tmp_path), "exploration")
        assert result == []

    def test_load_nonexistent_phase_returns_empty_list(
        self,
        tmp_path: Path,
    ) -> None:
        result = load_attempts(_story_dir(tmp_path), "nonexistent")
        assert result == []

    def test_attempt_numbering_increments(self, tmp_path: Path) -> None:
        story_dir = _story_dir(tmp_path)
        _bootstrap_context(story_dir)
        save_attempt(story_dir, _make_attempt(attempt_id="a1"))
        save_attempt(story_dir, _make_attempt(attempt_id="a2"))

        attempts = load_attempts(story_dir, "exploration")
        assert len(attempts) == 2
        assert attempts[0].attempt_id == "a1"
        assert attempts[1].attempt_id == "a2"


# --- save_phase_snapshot / load_phase_snapshot ---


class TestPhaseSnapshotPersistence:
    """Tests for PhaseSnapshot roundtrip persistence."""

    def test_roundtrip(self, tmp_path: Path) -> None:
        story_dir = _story_dir(tmp_path)
        _bootstrap_context(story_dir)
        snapshot = _make_snapshot()
        save_phase_snapshot(story_dir, snapshot)
        loaded = load_phase_snapshot(story_dir, "setup")

        assert loaded is not None
        assert loaded.story_id == snapshot.story_id
        assert loaded.phase == snapshot.phase
        assert loaded.status == PhaseStatus.COMPLETED
        assert loaded.artifacts == ["protocol.md"]
        assert loaded.evidence == {"tests_passed": True}

    def test_load_missing_returns_none(self, tmp_path: Path) -> None:
        result = load_phase_snapshot(_story_dir(tmp_path), "setup")
        assert result is None

    def test_writes_to_correct_filename(self, tmp_path: Path) -> None:
        story_dir = _story_dir(tmp_path)
        _bootstrap_context(story_dir)
        save_phase_snapshot(story_dir, _make_snapshot())
        assert (story_dir / "phase-state-setup.json").exists()

    def test_snapshot_lookup_does_not_infer_story_id_from_orphaned_rows(
        self,
        tmp_path: Path,
    ) -> None:
        story_dir = _story_dir(tmp_path)
        db_dir = story_dir / ".agentkit"
        db_dir.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(db_dir / "state.sqlite3") as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS phase_snapshots (
                    story_id TEXT NOT NULL,
                    phase TEXT NOT NULL,
                    status TEXT NOT NULL,
                    completed_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    PRIMARY KEY (story_id, phase)
                )
                """
            )
            conn.execute(
                """
                INSERT INTO phase_snapshots (
                    story_id, phase, status, completed_at, payload_json
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    "ORPHAN-001",
                    "setup",
                    "completed",
                    datetime(2026, 1, 15, 10, 30, 0, tzinfo=UTC).isoformat(),
                    json.dumps(
                        _make_snapshot().model_dump(mode="json"),
                        sort_keys=True,
                        default=str,
                    ),
                ),
            )
            conn.commit()

        assert load_phase_snapshot(story_dir, "setup") is None


# --- Pipeline robustness tests ---


class TestPipelineRobustness:
    """Robustness tests for corrupt/missing state scenarios.

    These verify that the persistence layer handles degraded conditions
    gracefully instead of crashing.
    """

    def test_corrupt_phase_state_raises_error(self, tmp_path: Path) -> None:
        """phase-state.json exists but contains garbage -> CorruptStateError."""
        story_dir = _story_dir(tmp_path)
        _bootstrap_context(story_dir)
        save_phase_state(story_dir, _make_state())
        with sqlite3.connect(story_dir / ".agentkit" / "state.sqlite3") as conn:
            conn.execute("UPDATE phase_states SET payload_json = '{invalid json!!!'")
            conn.commit()
        with pytest.raises(CorruptStateError):
            load_phase_state(story_dir)

    def test_missing_context_json_returns_none(self, tmp_path: Path) -> None:
        """context.json does not exist at all."""
        assert load_story_context(_story_dir(tmp_path)) is None

    def test_corrupt_attempt_is_skipped(self, tmp_path: Path) -> None:
        """One corrupt attempt file does not prevent loading others."""
        story_dir = _story_dir(tmp_path)
        _bootstrap_context(story_dir)
        # Save a valid attempt
        save_attempt(story_dir, _make_attempt(attempt_id="good"))

        with sqlite3.connect(story_dir / ".agentkit" / "state.sqlite3") as conn:
            conn.execute(
                "INSERT INTO attempt_records ("
                "story_id, phase, seq, attempt_id, entered_at, exit_status, "
                "outcome, yield_status, resume_trigger, "
                "guard_evaluations_json, artifacts_json"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "TEST-001",
                    "exploration",
                    2,
                    "corrupt",
                    datetime.now(tz=UTC).isoformat(),
                    "completed",
                    "completed",
                    None,
                    None,
                    "not json",
                    '["design.md"]',
                ),
            )
            conn.commit()

        # Save another valid attempt (will be seq 3 since 2 exists)
        save_attempt(story_dir, _make_attempt(attempt_id="also-good"))

        loaded = load_attempts(story_dir, "exploration")
        # The corrupt file is skipped, so we get the two valid ones
        assert len(loaded) == 2
        ids = [r.attempt_id for r in loaded]
        assert "good" in ids
        assert "also-good" in ids

    def test_phase_state_with_wrong_schema_raises_error(
        self,
        tmp_path: Path,
    ) -> None:
        """phase-state.json has valid JSON but wrong Pydantic schema."""
        story_dir = _story_dir(tmp_path)
        _bootstrap_context(story_dir)
        save_phase_state(story_dir, _make_state())
        with sqlite3.connect(story_dir / ".agentkit" / "state.sqlite3") as conn:
            conn.execute(
                "UPDATE phase_states SET payload_json = ?",
                ('{"totally": "wrong", "fields": 123}',),
            )
            conn.commit()
        with pytest.raises(CorruptStateError, match="payload is invalid"):
            load_phase_state(story_dir)

    def test_snapshot_with_corrupt_json_returns_none(
        self,
        tmp_path: Path,
    ) -> None:
        """phase-state-<phase>.json contains garbage."""
        story_dir = _story_dir(tmp_path)
        (story_dir / "phase-state-verify.json").write_text(
            "{{broken",
            encoding="utf-8",
        )
        assert load_phase_snapshot(story_dir, "verify") is None

    def test_load_phase_state_missing_returns_none(self, tmp_path: Path) -> None:
        """Missing phase-state.json returns None (fresh run)."""
        assert load_phase_state(_story_dir(tmp_path)) is None

    def test_load_phase_state_non_dict_raises_error(self, tmp_path: Path) -> None:
        """Array instead of object in phase-state.json -> CorruptStateError."""
        story_dir = _story_dir(tmp_path)
        _bootstrap_context(story_dir)
        save_phase_state(story_dir, _make_state())
        with sqlite3.connect(story_dir / ".agentkit" / "state.sqlite3") as conn:
            conn.execute("UPDATE phase_states SET payload_json = '[1, 2, 3]'")
            conn.commit()
        with pytest.raises(CorruptStateError, match="payload is invalid"):
            load_phase_state(story_dir)
