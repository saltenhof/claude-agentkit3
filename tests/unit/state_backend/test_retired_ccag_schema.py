"""Fresh SQLite schemas exclude the retired CCAG permission tables."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from agentkit.backend.state_backend import sqlite_store

if TYPE_CHECKING:
    from pathlib import Path


_RETIRED_CCAG_TABLES = {
    "ccag_permission_requests",
    "ccag_permission_leases",
}


class _RollbackLegacyProbeError(Exception):
    """Force transaction rollback after the preservation assertion."""


def test_fresh_sqlite_schema_does_not_create_retired_ccag_tables(
    tmp_path: Path,
) -> None:
    """A new SQLite backend contains current tables but no retired CCAG state."""

    with sqlite_store._connect(tmp_path) as connection:
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }

    assert "project_registry" in tables
    assert tables.isdisjoint(_RETIRED_CCAG_TABLES)


def test_existing_sqlite_schema_retains_retired_ccag_tables(tmp_path: Path) -> None:
    """Current bootstrap leaves the deliberately retained legacy tables intact."""

    with (
        pytest.raises(_RollbackLegacyProbeError),
        sqlite_store._connect(tmp_path) as connection,
    ):
        connection.execute(
            "CREATE TABLE ccag_permission_requests "
            "(legacy_id TEXT PRIMARY KEY, legacy_payload TEXT)"
        )
        connection.execute(
            "CREATE TABLE ccag_permission_leases "
            "(legacy_id TEXT PRIMARY KEY, legacy_payload TEXT)"
        )
        connection.execute(
            "INSERT INTO ccag_permission_requests "
            "(legacy_id, legacy_payload) VALUES (?, ?)",
            ("legacy-row", "preserve-me"),
        )
        connection.execute(
            "INSERT INTO ccag_permission_leases "
            "(legacy_id, legacy_payload) VALUES (?, ?)",
            ("legacy-row", "preserve-me"),
        )
        sqlite_store._ensure_schema(connection)
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        assert tables >= _RETIRED_CCAG_TABLES
        for query in (
            "SELECT legacy_payload FROM ccag_permission_requests WHERE legacy_id = ?",
            "SELECT legacy_payload FROM ccag_permission_leases WHERE legacy_id = ?",
        ):
            row = connection.execute(query, ("legacy-row",)).fetchone()
            assert row is not None and row[0] == "preserve-me"
        raise _RollbackLegacyProbeError
