"""Postgres row operations for canonical CCAG permission requests."""

from __future__ import annotations

from typing import Any

from ._connection import _connect_global

_COLUMNS = """request_id, project_key, story_id, run_id, principal_type,
tool_name, operation_class, path_classes, request_fingerprint, status,
requested_at, expires_at, resolution, decided_at, decision_note"""
_SELECT_BY_ID = "SELECT * FROM ccag_permission_requests WHERE request_id = ?"


def insert_ccag_permission_request_global_row(row: dict[str, Any]) -> dict[str, Any]:
    """Insert a request idempotently and return the stored row."""
    values = tuple(row[key] for key in _COLUMNS.replace("\n", " ").split(", "))
    with _connect_global() as conn:
        conn.execute(
            f"INSERT INTO ccag_permission_requests ({_COLUMNS}) VALUES "
            "(?, ?, ?, ?, ?, ?, ?, CAST(? AS JSONB), ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (request_id) DO NOTHING",
            values,
        )
        stored = conn.execute(_SELECT_BY_ID, (row["request_id"],)).fetchone()
    if stored is None:
        raise RuntimeError("permission request insert did not materialize a row")
    return dict(stored)


def load_ccag_permission_request_global_row(
    request_id: str, now: str
) -> dict[str, Any] | None:
    """Load one request after lazy expiry materialization."""
    with _connect_global() as conn:
        _expire(conn, now, "request_id = ?", (request_id,))
        row = conn.execute(_SELECT_BY_ID, (request_id,)).fetchone()
    return dict(row) if row is not None else None


def list_ccag_permission_request_rows_global(
    project_key: str, story_id: str, run_id: str, now: str
) -> list[dict[str, Any]]:
    """List one run's requests after lazy expiry materialization."""
    scope = (project_key, story_id, run_id)
    with _connect_global() as conn:
        _expire(conn, now, "project_key = ? AND story_id = ? AND run_id = ?", scope)
        rows = conn.execute(
            "SELECT * FROM ccag_permission_requests WHERE project_key = ? "
            "AND story_id = ? AND run_id = ? ORDER BY requested_at, request_id",
            scope,
        ).fetchall()
    return [dict(row) for row in rows]


def resolve_ccag_permission_request_global_row(
    request_id: str, status: str, resolution: str, note: str, now: str
) -> dict[str, Any] | None:
    """Resolve a pending request and return its terminal row."""
    with _connect_global() as conn:
        _expire(conn, now, "request_id = ?", (request_id,))
        conn.execute(
            "UPDATE ccag_permission_requests SET status = ?, resolution = ?, "
            "decided_at = ?, decision_note = ? WHERE request_id = ? AND status = 'pending'",
            (status, resolution, now, note, request_id),
        )
        row = conn.execute(_SELECT_BY_ID, (request_id,)).fetchone()
    return dict(row) if row is not None else None


def _expire(conn: Any, now: str, where: str, params: tuple[object, ...]) -> None:
    conn.execute(
        "UPDATE ccag_permission_requests SET status = 'expired', resolution = 'denied', "
        "decided_at = expires_at, decision_note = 'expired without human decision' "
        f"WHERE status = 'pending' AND expires_at <= ? AND {where}",
        (now, *params),
    )
