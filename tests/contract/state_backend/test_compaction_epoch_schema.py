from __future__ import annotations

import os
from typing import TYPE_CHECKING

import psycopg
import pytest
from psycopg import sql

from agentkit.state_backend.config import resolve_schema_name

if TYPE_CHECKING:
    from collections.abc import Iterator

pytest_plugins = ("tests.fixtures.postgres_backend",)


@pytest.fixture()
def _pg_conn(postgres_backend_env: str) -> Iterator[psycopg.Connection[object]]:
    schema = resolve_schema_name()
    conn = psycopg.connect(os.environ["AGENTKIT_STATE_DATABASE_URL"], autocommit=True)
    conn.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
    try:
        yield conn
    finally:
        conn.close()


def test_compaction_epochs_schema_and_primary_key(
    _pg_conn: psycopg.Connection[object],
) -> None:
    schema = resolve_schema_name()
    rows = _pg_conn.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = %s AND table_name = 'compaction_epochs'
        """,
        (schema,),
    ).fetchall()
    assert {str(row[0]) for row in rows} == {
        "project_key",
        "story_id",
        "epoch",
        "updated_at",
    }
    pk_rows = _pg_conn.execute(
        """
        SELECT kcu.column_name
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
          ON tc.constraint_name = kcu.constraint_name
         AND tc.table_schema = kcu.table_schema
        WHERE tc.constraint_type = 'PRIMARY KEY'
          AND tc.table_schema = %s
          AND tc.table_name = 'compaction_epochs'
        ORDER BY kcu.ordinal_position
        """,
        (schema,),
    ).fetchall()
    assert [str(row[0]) for row in pk_rows] == ["project_key", "story_id"]
