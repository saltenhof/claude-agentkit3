"""SQLite test-parallel row operations for CCAG permission leases."""

from __future__ import annotations

from typing import Any

from ._common import _project_store_dir
from ._connection import _connect

_COLUMNS = """lease_id, request_ref, project_key, story_id, run_id,
principal_type, tool_name, operation_class, path_classes, request_fingerprint,
max_uses, consumed, issued_at, expires_at"""
_SELECT_BY_ID = "SELECT * FROM ccag_permission_leases WHERE lease_id = ?"


def insert_ccag_permission_lease_global_row(row: dict[str, Any]) -> dict[str, Any]:
    """Insert a lease idempotently and return the stored row."""
    values = tuple(row[key] for key in _COLUMNS.replace("\n", " ").split(", "))
    with _connect(_project_store_dir(None)) as conn:
        conn.execute(
            f"INSERT INTO ccag_permission_leases ({_COLUMNS}) VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (lease_id) DO NOTHING", values
        )
        stored = conn.execute(_SELECT_BY_ID, (row["lease_id"],)).fetchone()
    if stored is None:
        raise RuntimeError("permission lease insert did not materialize a row")
    return dict(stored)


def load_ccag_permission_lease_global_row(lease_id: str) -> dict[str, Any] | None:
    """Load one canonical permission lease."""
    with _connect(_project_store_dir(None)) as conn:
        row = conn.execute(_SELECT_BY_ID, (lease_id,)).fetchone()
    return dict(row) if row is not None else None


def consume_ccag_permission_lease_global_row(
    lease_id: str, now: str
) -> tuple[dict[str, Any] | None, bool]:
    """Atomically consume one available use and return the updated row."""
    with _connect(_project_store_dir(None)) as conn:
        row = conn.execute(
            "UPDATE ccag_permission_leases SET consumed = consumed + 1 "
            "WHERE lease_id = ? AND consumed < max_uses AND expires_at > ? RETURNING *",
            (lease_id, now),
        ).fetchone()
        applied = row is not None
        if not applied:
            row = conn.execute(_SELECT_BY_ID, (lease_id,)).fetchone()
    return (dict(row) if row is not None else None, applied)
