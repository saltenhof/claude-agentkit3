"""Fresh Postgres schemas exclude the retired CCAG permission tables."""

from __future__ import annotations

import pytest

from agentkit.backend.state_backend import postgres_store
from agentkit.backend.state_backend.config import resolve_schema_name

pytestmark = pytest.mark.contract

_RETIRED_CCAG_TABLES = {
    "ccag_permission_requests",
    "ccag_permission_leases",
}


class _RollbackLegacyProbeError(Exception):
    """Force transaction rollback after the preservation assertion."""


def test_fresh_postgres_schema_does_not_create_retired_ccag_tables(
    postgres_worker_schema: tuple[str, str],
) -> None:
    """A new Postgres backend contains current tables but no retired CCAG state."""

    _database_url, fresh_schema = postgres_worker_schema
    assert resolve_schema_name() == fresh_schema
    with postgres_store._connect_global() as connection:
        tables = {
            str(row["table_name"])
            for row in connection.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = current_schema()
                  AND table_type = 'BASE TABLE'
                """
            ).fetchall()
        }

    assert "project_registry" in tables
    assert tables.isdisjoint(_RETIRED_CCAG_TABLES)


def test_existing_postgres_schema_retains_retired_ccag_tables(
    postgres_worker_schema: tuple[str, str],
) -> None:
    """Current bootstrap leaves the deliberately retained legacy tables intact."""

    _database_url, isolated_schema = postgres_worker_schema
    assert resolve_schema_name() == isolated_schema
    with (
        pytest.raises(_RollbackLegacyProbeError),
        postgres_store._connect_global() as connection,
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
            "(legacy_id, legacy_payload) VALUES (%s, %s)",
            ("legacy-row", "preserve-me"),
        )
        connection.execute(
            "INSERT INTO ccag_permission_leases "
            "(legacy_id, legacy_payload) VALUES (%s, %s)",
            ("legacy-row", "preserve-me"),
        )
        postgres_store._ensure_schema(connection)
        tables = {
            str(row["table_name"])
            for row in connection.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = current_schema()
                  AND table_type = 'BASE TABLE'
                """
            ).fetchall()
        }
        assert tables >= _RETIRED_CCAG_TABLES
        for query in (
            "SELECT legacy_payload FROM ccag_permission_requests "
            "WHERE legacy_id = %s",
            "SELECT legacy_payload FROM ccag_permission_leases WHERE legacy_id = %s",
        ):
            row = connection.execute(query, ("legacy-row",)).fetchone()
            assert row is not None and row["legacy_payload"] == "preserve-me"
        raise _RollbackLegacyProbeError
