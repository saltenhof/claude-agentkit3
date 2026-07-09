"""Integration tests: GovernanceObserver against the real SQLite state backend.

MAJOR finding fix (CODEX review AG3-085): the unit tests use an in-memory
ScriptedEventReader so they never exercise sqlite's ORDER BY occurred_at DESC
LIMIT.  These tests wire the :class:`StateBackendGovernanceEventReader`
against a real (tmp_path-scoped) SQLite database to prove:

(a) Only the newest ``window_size`` events contribute to the score (eviction).
(b) The score is purely DB-derived — no in-memory carry between calls.
(c) ``read_last_adjudication_ts`` cooldown semantics over the real backend.

All writes use the real ``append_execution_event`` path (story-dir-scoped
SQLite).  The reader uses ``StateBackendGovernanceEventReader(story_dir=…)``
which calls the public ``load_execution_events`` facade with ``limit=window_size``
so the window query exercises the real SQL (ORDER BY occurred_at DESC LIMIT).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from agentkit.backend.governance.governance_observer.reader import StateBackendGovernanceEventReader
from agentkit.backend.governance.governance_observer.score import compute_risk_score
from agentkit.backend.state_backend.persistence_test_support import (
    reset_backend_cache_for_tests,
)
from agentkit.backend.state_backend.telemetry_event_store import append_execution_event
from agentkit.backend.telemetry.contract.records import ExecutionEventRecord

if TYPE_CHECKING:
    from pathlib import Path

_PROJECT = "int-gov-obs"
_STORY = "AG3-085-int"
_RUN = "run-int-001"


# ---------------------------------------------------------------------------
# Backend fixture — real SQLite, tmp_path-scoped
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _sqlite_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    """Activate the SQLite backend for every test in this module."""
    monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
    monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")
    monkeypatch.delenv("AGENTKIT_STATE_DATABASE_URL", raising=False)
    reset_backend_cache_for_tests()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_governance_signal(
    story_dir: Path,
    *,
    project_key: str = _PROJECT,
    story_id: str = _STORY,
    run_id: str = _RUN,
    risk_points: int,
    signal_type: str = "orchestrator_code_read_write",
    occurred_at: datetime | None = None,
) -> None:
    """Write one governance_signal event to the real SQLite store.

    Args:
        story_dir: Story directory for the SQLite database.
        project_key: Project scope.
        story_id: Story scope.
        run_id: Run scope.
        risk_points: Risk-point weight to embed in the payload.
        signal_type: Signal type wire value.
        occurred_at: Optional explicit timestamp (defaults to UTC now).
    """
    ts = occurred_at if occurred_at is not None else datetime.now(UTC)
    record = ExecutionEventRecord(
        project_key=project_key,
        story_id=story_id,
        run_id=run_id,
        event_id=f"evt-{uuid.uuid4().hex}",
        event_type="governance_signal",
        occurred_at=ts,
        source_component="test",
        severity="info",
        phase="implementation",
        payload={
            "risk_points": risk_points,
            "signal_type": signal_type,
            "actor": "test-agent",
        },
    )
    append_execution_event(story_dir, record)


def _write_governance_adjudication(
    story_dir: Path,
    *,
    project_key: str = _PROJECT,
    story_id: str = _STORY,
    run_id: str = _RUN,
    signal_type: str = "orchestrator_code_read_write",
    occurred_at: datetime | None = None,
) -> None:
    """Write one governance_adjudication event to the real SQLite store.

    Args:
        story_dir: Story directory for the SQLite database.
        project_key: Project scope.
        story_id: Story scope.
        run_id: Run scope.
        signal_type: Signal type wire value.
        occurred_at: Optional explicit timestamp (defaults to UTC now).
    """
    ts = occurred_at if occurred_at is not None else datetime.now(UTC)
    record = ExecutionEventRecord(
        project_key=project_key,
        story_id=story_id,
        run_id=run_id,
        event_id=f"evt-{uuid.uuid4().hex}",
        event_type="governance_adjudication",
        occurred_at=ts,
        source_component="test",
        severity="info",
        phase="implementation",
        payload={
            "incident_type": "role_violation",
            "severity": "medium",
            "confidence": 0.75,
            "recommended_action": "document_incident",
            "signal_type": signal_type,
        },
    )
    append_execution_event(story_dir, record)


# ---------------------------------------------------------------------------
# MAJOR (a): rolling-window eviction via real SQL ORDER BY DESC LIMIT
# ---------------------------------------------------------------------------


def test_rolling_window_eviction_only_newest_contribute(tmp_path: Path) -> None:
    """Only the ``window_size`` newest events contribute to the score.

    Inserts ``window_size + extra`` governance_signal events.  The oldest
    ``extra`` events have higher risk_points but must be excluded by the
    DESC LIMIT query.  The score must equal the sum of the newest
    ``window_size`` events only.

    Proves FK-35 §35.3.5 eviction at the real DB boundary.
    """
    window_size = 5
    base_ts = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)

    # Write 3 OLD events with large risk_points (100 each) — must be evicted
    for i in range(3):
        _write_governance_signal(
            tmp_path,
            risk_points=100,
            occurred_at=base_ts + timedelta(seconds=i),
        )

    # Write ``window_size`` (5) NEWER events with 10 risk_points each
    for i in range(window_size):
        _write_governance_signal(
            tmp_path,
            risk_points=10,
            occurred_at=base_ts + timedelta(seconds=100 + i),
        )

    reader = StateBackendGovernanceEventReader(story_dir=tmp_path)
    score = compute_risk_score(
        reader, _PROJECT, _STORY, _RUN, window_size=window_size
    )

    # Only the 5 newest events (10 pts each) should be in the window
    assert score == window_size * 10, (
        f"Expected score={window_size * 10} (only newest {window_size} events), "
        f"got {score}.  Eviction via ORDER BY occurred_at DESC LIMIT failed."
    )


def test_score_is_db_derived_no_in_memory_carry(tmp_path: Path) -> None:
    """Score is purely DB-derived — no in-memory carry between calls.

    Calls compute_risk_score twice using the SAME reader instance but with
    different DB states (after inserting additional events between calls).
    The second call must reflect the updated DB contents, not a cached score.

    Proves FK-35 §35.3.1a — no in-memory rolling buffer.
    """
    window_size = 10
    reader = StateBackendGovernanceEventReader(story_dir=tmp_path)

    # First call: no events written yet
    score_before = compute_risk_score(
        reader, _PROJECT, _STORY, _RUN, window_size=window_size
    )
    assert score_before == 0, f"Expected 0 before writes, got {score_before}"

    # Write 3 events (10 pts each = 30 total)
    for _ in range(3):
        _write_governance_signal(tmp_path, risk_points=10)

    # Second call on the SAME reader instance — must reflect the DB update
    score_after = compute_risk_score(
        reader, _PROJECT, _STORY, _RUN, window_size=window_size
    )
    assert score_after == 30, (
        f"Expected 30 after 3 x 10-pt events, got {score_after}.  "
        "Score appears to be carried in-memory rather than re-queried from DB."
    )


# ---------------------------------------------------------------------------
# MAJOR (b): read_last_adjudication_ts cooldown semantics over real backend
# ---------------------------------------------------------------------------


def test_read_last_adjudication_ts_returns_none_when_no_adjudication(
    tmp_path: Path,
) -> None:
    """Returns None when no adjudication exists (cooldown not active)."""
    reader = StateBackendGovernanceEventReader(story_dir=tmp_path)
    ts = reader.read_last_adjudication_ts(
        _PROJECT, _STORY, _RUN, signal_type="orchestrator_code_read_write"
    )
    assert ts is None


def test_read_last_adjudication_ts_returns_timestamp_for_signal_type(
    tmp_path: Path,
) -> None:
    """Returns the UNIX timestamp of the most-recent adjudication for the signal type."""
    adj_ts = datetime(2026, 3, 15, 12, 0, 0, tzinfo=UTC)
    _write_governance_adjudication(
        tmp_path,
        signal_type="orchestrator_code_read_write",
        occurred_at=adj_ts,
    )
    reader = StateBackendGovernanceEventReader(story_dir=tmp_path)
    result = reader.read_last_adjudication_ts(
        _PROJECT, _STORY, _RUN, signal_type="orchestrator_code_read_write"
    )
    assert result is not None
    assert abs(result - adj_ts.timestamp()) < 1.0, (
        f"Expected ~{adj_ts.timestamp()}, got {result}"
    )


def test_read_last_adjudication_ts_scoped_to_signal_type(tmp_path: Path) -> None:
    """Adjudication for signal_type A does not affect cooldown for signal_type B."""
    adj_ts = datetime(2026, 3, 15, 12, 0, 0, tzinfo=UTC)
    _write_governance_adjudication(
        tmp_path,
        signal_type="qa_fail_repeated",
        occurred_at=adj_ts,
    )
    reader = StateBackendGovernanceEventReader(story_dir=tmp_path)
    # Different signal type — must return None
    result = reader.read_last_adjudication_ts(
        _PROJECT, _STORY, _RUN, signal_type="orchestrator_code_read_write"
    )
    assert result is None, (
        "Cooldown from 'qa_fail_repeated' must not block 'orchestrator_code_read_write'"
    )


def test_read_last_adjudication_ts_returns_max_of_multiple(tmp_path: Path) -> None:
    """Returns the LATEST timestamp when multiple adjudications exist."""
    base_ts = datetime(2026, 3, 15, 12, 0, 0, tzinfo=UTC)
    signal = "orchestrator_code_read_write"
    # Write two adjudications — the second is 60s later
    _write_governance_adjudication(tmp_path, signal_type=signal, occurred_at=base_ts)
    _write_governance_adjudication(
        tmp_path, signal_type=signal, occurred_at=base_ts + timedelta(seconds=60)
    )
    reader = StateBackendGovernanceEventReader(story_dir=tmp_path)
    result = reader.read_last_adjudication_ts(
        _PROJECT, _STORY, _RUN, signal_type=signal
    )
    expected = (base_ts + timedelta(seconds=60)).timestamp()
    assert result is not None
    assert abs(result - expected) < 1.0, (
        f"Expected latest adjudication ts ~{expected}, got {result}"
    )


# ---------------------------------------------------------------------------
# FIX B regression: > 200 other-signal adjudications must not hide same-signal
# ---------------------------------------------------------------------------


def test_read_last_adjudication_ts_not_obscured_by_200_plus_other_signals(
    tmp_path: Path,
) -> None:
    """Same-signal adjudication is found even when 200+ other-signal adjudications
    are newer (FK-35 §35.3.11 regression — FIX B).

    The old bounded-scan approach read the newest 200 governance_adjudication events
    globally, then filtered by signal_type in Python.  If 200+ adjudications for
    OTHER signal types exist with timestamps NEWER than the target signal's
    adjudication, the target was pushed out of the 200-row window and the cooldown
    was missed (wrong re-adjudication).

    The new approach uses a DB-side MAX(occurred_at) with exact JSON field
    matching, making it immune to other-signal volume.

    This test inserts:
    - 1 adjudication for the TARGET signal at an OLDER timestamp
    - 210 adjudications for a DIFFERENT signal at NEWER timestamps

    After the insert the target-signal adjudication is NOT in the newest 200 rows
    globally.  The new implementation must still return the correct timestamp.
    """
    base_ts = datetime(2026, 4, 1, 0, 0, 0, tzinfo=UTC)
    target_signal = "qa_fail_repeated"
    other_signal = "orchestrator_code_read_write"

    # Write the target signal's adjudication (timestamp = base_ts, the oldest)
    target_adj_ts = base_ts
    _write_governance_adjudication(
        tmp_path, signal_type=target_signal, occurred_at=target_adj_ts
    )

    # Write 210 adjudications for the OTHER signal at NEWER timestamps
    # (these will dominate the newest-200 window)
    for i in range(210):
        _write_governance_adjudication(
            tmp_path,
            signal_type=other_signal,
            occurred_at=base_ts + timedelta(seconds=i + 1),
        )

    reader = StateBackendGovernanceEventReader(story_dir=tmp_path)
    result = reader.read_last_adjudication_ts(
        _PROJECT, _STORY, _RUN, signal_type=target_signal
    )

    assert result is not None, (
        "read_last_adjudication_ts returned None for target signal even though an "
        "adjudication exists — the DB-side MAX query must not be blocked by 200+ "
        "other-signal adjudications (FK-35 §35.3.11 regression / FIX B)"
    )
    assert abs(result - target_adj_ts.timestamp()) < 1.0, (
        f"Expected cooldown timestamp ~{target_adj_ts.timestamp()}, got {result}"
    )


# ---------------------------------------------------------------------------
# FIX C: fail-closed on SQLite backend + story_dir=None
# ---------------------------------------------------------------------------


def test_sqlite_backend_story_dir_none_raises_at_construction(
    tmp_path: Path,
) -> None:
    """Construction with story_dir=None raises when SQLite backend is active (FIX C).

    Defaulting to Path.cwd() for SQLite is a latent wrong-database read.
    FAIL-CLOSED: construction must raise ValueError rather than silently
    reading the wrong DB.
    """
    # SQLite backend is already active via the autouse fixture
    with pytest.raises(ValueError, match="story_dir must not be None"):
        StateBackendGovernanceEventReader(story_dir=None)
