"""Integration: governance cooldown query against the REAL Postgres backend.

CODEX review AG3-085 (round 5): the SQLite-backed governance regression tests
(``tests/integration/governance/test_governance_observer_backend.py``) never
exercise the Postgres ``max_adjudication_occurred_at`` SQL.  Because
``execution_events.payload_json`` is a ``TEXT`` column (postgres_schema.sql),
the cooldown filter must cast to ``jsonb`` before the ``->>`` operator
(``(payload_json::jsonb)->>'signal_type' = ?``) — a bare ``payload_json->>...``
raises ``operator does not exist: text ->> unknown`` at runtime on Postgres.
SQLite's ``json_extract`` works on TEXT directly, so the defect was green
locally and would only fail on the Jenkins Linux/Postgres CI.

These tests run against a real, worker-scoped, per-test-isolated Postgres
schema.  The ``postgres_isolated_schema`` fixture is auto-attached to every
``/integration/state_backend/`` item by ``tests/integration/conftest.py`` and
pins ``AGENTKIT_STATE_BACKEND=postgres`` + an ephemeral test DSN.  Locally the
fixture spins a disposable Docker container (``postgres:17-alpine``); on the
CI it binds the provisioned Postgres.  When neither an explicit Postgres env
nor Docker is available the session fixture fails closed (it does NOT silently
no-op), so these tests genuinely execute the SQL on Postgres.

They prove the cooldown query EXECUTES on Postgres without error and returns
the correct ``MAX(occurred_at)`` for the EXACT ``signal_type`` — the parity
counterpart to the SQLite-backed cooldown tests.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from agentkit.governance.governance_observer.reader import (
    StateBackendGovernanceEventReader,
)
from agentkit.state_backend.store.facade import (
    append_execution_event,
    load_last_adjudication_ts,
)
from agentkit.telemetry.contract.records import ExecutionEventRecord

if TYPE_CHECKING:
    from pathlib import Path

_PROJECT = "pg-gov-cooldown"
_STORY = "AG3-085-pg"
_RUN = "run-pg-001"
_TARGET_SIGNAL = "orchestrator_code_read_write"
_OTHER_SIGNAL = "qa_fail_repeated"


def _write_governance_adjudication(
    story_dir: Path,
    *,
    signal_type: str,
    occurred_at: datetime,
) -> None:
    """Write one governance_adjudication event via the real append path.

    On Postgres the ``story_dir`` argument is ignored by the store (the
    connection is derived from the environment set by the isolation fixture);
    it is forwarded only for API parity with the SQLite driver.

    Args:
        story_dir: Story directory (ignored by the Postgres backend).
        signal_type: ``signal_type`` wire value embedded in the payload.
        occurred_at: Explicit ISO-8601 timestamp for the event.
    """
    record = ExecutionEventRecord(
        project_key=_PROJECT,
        story_id=_STORY,
        run_id=_RUN,
        event_id=f"evt-{uuid.uuid4().hex}",
        event_type="governance_adjudication",
        occurred_at=occurred_at,
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


@pytest.mark.integration
def test_cooldown_query_executes_and_returns_max_on_postgres(tmp_path: Path) -> None:
    """The ``(payload_json::jsonb)->>'signal_type'`` cooldown query runs on Postgres.

    Inserts adjudications for two distinct signal types (with > 0 of the target
    type) and asserts that both ``max_adjudication_occurred_at`` and the public
    ``load_last_adjudication_ts`` return the correct ``MAX(occurred_at)`` for the
    EXACT target signal type — i.e. the JSON-on-TEXT cast is correct and the
    query does not raise on a ``TEXT`` ``payload_json`` column.
    """
    base_ts = datetime(2026, 5, 1, 9, 0, 0, tzinfo=UTC)
    target_latest = base_ts + timedelta(seconds=120)

    # Two adjudications for the TARGET signal — the second is the MAX.
    _write_governance_adjudication(
        tmp_path, signal_type=_TARGET_SIGNAL, occurred_at=base_ts
    )
    _write_governance_adjudication(
        tmp_path, signal_type=_TARGET_SIGNAL, occurred_at=target_latest
    )
    # A NEWER adjudication for a DIFFERENT signal — must not leak into the result.
    _write_governance_adjudication(
        tmp_path,
        signal_type=_OTHER_SIGNAL,
        occurred_at=base_ts + timedelta(seconds=300),
    )

    # Direct store call — exercises the exact cooldown SQL on Postgres.
    from agentkit.state_backend import postgres_store

    raw = postgres_store.max_adjudication_occurred_at(
        tmp_path,
        project_key=_PROJECT,
        story_id=_STORY,
        run_id=_RUN,
        payload_signal_type=_TARGET_SIGNAL,
    )
    assert raw is not None, "cooldown query returned no row for the target signal"
    assert datetime.fromisoformat(raw) == target_latest

    # Public facade — same query, parsed to a UNIX float.
    result = load_last_adjudication_ts(
        tmp_path,
        project_key=_PROJECT,
        story_id=_STORY,
        run_id=_RUN,
        payload_signal_type=_TARGET_SIGNAL,
    )
    assert result is not None
    assert abs(result - target_latest.timestamp()) < 1.0, (
        f"Expected MAX(occurred_at) ~{target_latest.timestamp()}, got {result}"
    )


@pytest.mark.integration
def test_cooldown_query_scoped_to_exact_signal_type_on_postgres(
    tmp_path: Path,
) -> None:
    """An adjudication for signal A does not match the cooldown query for signal B.

    Proves the exact-match (``= ?``, not ``LIKE``) semantics hold on Postgres:
    only the OTHER signal exists, so the target-signal cooldown must return
    ``None`` — and the query must still execute without a TEXT/jsonb operator
    error.
    """
    adj_ts = datetime(2026, 5, 1, 9, 0, 0, tzinfo=UTC)
    _write_governance_adjudication(
        tmp_path, signal_type=_OTHER_SIGNAL, occurred_at=adj_ts
    )

    reader = StateBackendGovernanceEventReader(story_dir=None)
    result = reader.read_last_adjudication_ts(
        _PROJECT, _STORY, _RUN, signal_type=_TARGET_SIGNAL
    )
    assert result is None, (
        f"Cooldown from {_OTHER_SIGNAL!r} must not match {_TARGET_SIGNAL!r}"
    )


@pytest.mark.integration
def test_cooldown_query_returns_none_when_absent_on_postgres(tmp_path: Path) -> None:
    """No adjudication for the scope -> the query executes and returns ``None``."""
    result = load_last_adjudication_ts(
        tmp_path,
        project_key=_PROJECT,
        story_id=_STORY,
        run_id=_RUN,
        payload_signal_type=_TARGET_SIGNAL,
    )
    assert result is None
