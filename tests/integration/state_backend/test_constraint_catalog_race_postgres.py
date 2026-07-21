"""Regression coverage for schema-local constraint verification under DDL churn."""

from __future__ import annotations

import os
import threading
import uuid

import psycopg
import pytest
from psycopg import sql

from agentkit.backend.state_backend.config import SCHEMA_OVERRIDE_ENV
from agentkit.backend.state_backend.postgres_store._compat import _CompatConnection
from agentkit.backend.state_backend.postgres_store._schema import (
    _verify_evidence_command_kind_present,
)

_CHURNER_COUNT = 4
_VERIFY_ITERATIONS = 250


def _catalog_churner(
    database_url: str,
    schema_name: str,
    ready: threading.Barrier,
    stop: threading.Event,
    cycles: list[int],
    errors: list[BaseException],
) -> None:
    """Repeatedly replace a foreign schema carrying the same target relation."""
    try:
        with psycopg.connect(database_url, autocommit=True) as conn:
            conn.execute(
                sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name)),
            )
            conn.execute(
                sql.SQL(
                    "CREATE TABLE {}.edge_command_records ("
                    "command_kind TEXT CHECK (command_kind IN ('foreign_kind'))"
                    ")"
                ).format(sql.Identifier(schema_name)),
            )
            ready.wait(timeout=15)
            while not stop.is_set():
                conn.execute(
                    sql.SQL("DROP SCHEMA {} CASCADE").format(
                        sql.Identifier(schema_name),
                    ),
                )
                conn.execute(
                    sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name)),
                )
                conn.execute(
                    sql.SQL(
                        "CREATE TABLE {}.edge_command_records ("
                        "command_kind TEXT CHECK (command_kind IN ('foreign_kind'))"
                        ")"
                    ).format(sql.Identifier(schema_name)),
                )
                cycles[0] += 1
    except BaseException as exc:  # pragma: no cover - surfaced in the main thread
        errors.append(exc)
        stop.set()


def _cleanup_churn_schemas(database_url: str, schema_names: list[str]) -> None:
    with psycopg.connect(database_url, autocommit=True) as conn:
        for schema_name in schema_names:
            conn.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                    sql.Identifier(schema_name),
                ),
            )


@pytest.mark.integration
def test_constraint_verification_ignores_parallel_foreign_catalog_churn(
    postgres_isolated_schema: str,
) -> None:
    """A foreign worker drop cannot invalidate the current schema's probe.

    The old query joined every relation named ``edge_command_records`` before
    filtering on ``current_schema()``. PostgreSQL consequently evaluated
    ``pg_get_constraintdef()`` for foreign worker constraints, allowing a
    concurrent ``DROP SCHEMA ... CASCADE`` to remove the relation between the
    catalog scan and definition lookup. The production query must bind the
    stable current-schema relation before resolving any constraint OID.
    """
    target_schema = os.environ[SCHEMA_OVERRIDE_ENV]
    unique = uuid.uuid4().hex[:12]
    churn_schemas = [f"ak3race_{unique}_{index}" for index in range(_CHURNER_COUNT)]
    ready = threading.Barrier(_CHURNER_COUNT + 1)
    stop = threading.Event()
    cycles = [0]
    errors: list[BaseException] = []
    threads = [
        threading.Thread(
            target=_catalog_churner,
            args=(
                postgres_isolated_schema,
                schema_name,
                ready,
                stop,
                cycles,
                errors,
            ),
            name=f"constraint-catalog-churn-{index}",
        )
        for index, schema_name in enumerate(churn_schemas)
    ]

    for thread in threads:
        thread.start()

    try:
        ready.wait(timeout=15)
        with psycopg.connect(postgres_isolated_schema, autocommit=True) as conn:
            conn.execute(
                sql.SQL("SET search_path TO {}, public").format(
                    sql.Identifier(target_schema),
                ),
            )
            compat = _CompatConnection(conn)
            for _ in range(_VERIFY_ITERATIONS):
                assert _verify_evidence_command_kind_present(compat)
    finally:
        stop.set()
        for thread in threads:
            thread.join(timeout=10)
        _cleanup_churn_schemas(postgres_isolated_schema, churn_schemas)

    assert all(not thread.is_alive() for thread in threads)
    assert not errors
    assert cycles[0] > 0
