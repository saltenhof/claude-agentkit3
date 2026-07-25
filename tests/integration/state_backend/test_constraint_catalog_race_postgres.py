"""Regression coverage for schema-local catalog access in the Postgres bootstrap.

AG3-172. Two independent defects, both rooted in the same model error — treating
the PER-DATABASE system catalog as if it were schema-local:

* :func:`test_constraint_verification_ignores_parallel_foreign_catalog_churn`
  covers the OID race (AC3): a constraint OID resolved across a global
  ``pg_class.relname`` scan can vanish while a foreign schema is dropped.
* :func:`test_story_identity_fk_is_applied_per_schema` covers the cross-schema
  guard leak (AC5): an unscoped ``pg_constraint.conname`` existence probe reads
  foreign schemas, so only the first-bootstrapped schema gets the constraint.
"""

from __future__ import annotations

import os
import threading
import uuid
from contextlib import contextmanager
from typing import TYPE_CHECKING

import psycopg
import pytest
from psycopg import sql

from agentkit.backend.state_backend.config import (
    SCHEMA_OVERRIDE_ALLOWED_ENV,
    SCHEMA_OVERRIDE_ENV,
    STATE_BACKEND_ENV,
    STATE_DATABASE_URL_ENV,
)
from agentkit.backend.state_backend.persistence_test_support import (
    reset_backend_cache_for_tests,
)
from agentkit.backend.state_backend.postgres_store._compat import _CompatConnection
from agentkit.backend.state_backend.postgres_store._schema import (
    _verify_evidence_command_kind_present,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

_CHURNER_COUNT = 4
_VERIFY_ITERATIONS = 250
#: Schemas bootstrapped by :func:`test_story_identity_fk_is_applied_per_schema`.
#: Two is the minimum that can expose a first-wins guard leak.
_PEER_SCHEMA_COUNT = 2
#: The story-identity FK whose existence guard must be schema-scoped. It is NOT
#: part of the ``CREATE TABLE`` in ``postgres_schema.sql``; only
#: ``_ensure_story_identity_constraints`` adds it, so a leaking guard is the
#: difference between an enforced and an unenforced reference.
_STORY_IDENTITY_FK = "story_contexts_project_key_fkey"
#: The sibling FK that was already correctly schema-scoped. Asserting it in the
#: same test keeps the comparison honest: a bootstrap that adds NOTHING would
#: fail here too, so a green result really means "both schemas got both FKs".
_FAILURE_CORPUS_FK = "fc_patterns_check_ref_fkey"


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


def _drop_schemas(database_url: str, schema_names: list[str]) -> None:
    """Drop every schema in *schema_names* CASCADE (test-owned schemas only)."""
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
        _drop_schemas(postgres_isolated_schema, churn_schemas)

    assert all(not thread.is_alive() for thread in threads)
    assert not errors
    assert cycles[0] > 0


def _constraint_schemas(database_url: str, conname: str) -> set[str]:
    """Return every schema of the database whose tables carry *conname*.

    Rows are read POSITIONALLY: this opens its own ``psycopg.connect`` (default
    tuple ``row_factory``), unlike the pooled store connection which is
    ``dict_row``.
    """
    with psycopg.connect(database_url, autocommit=True) as conn:
        rows = conn.execute(
            """
            SELECT n.nspname
            FROM pg_constraint c
            JOIN pg_class t ON t.oid = c.conrelid
            JOIN pg_namespace n ON n.oid = t.relnamespace
            WHERE c.conname = %s
            """,
            (conname,),
        ).fetchall()
        return {str(row[0]) for row in rows}


def _bootstrap_schema_via_production_path(database_url: str, schema: str) -> None:
    """Create *schema* and run the real production DDL bootstrap into it.

    Uses the same seam as the worker-schema fixture (env override gate ->
    ``_connect_global``) so the constraint set under test is produced by the
    production schema owner, never assembled by the test.
    """
    with psycopg.connect(database_url, autocommit=True) as conn:
        conn.execute(
            sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema)),
        )
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))

    from agentkit.backend.state_backend import postgres_store

    with _schema_override(database_url, schema), postgres_store._connect_global():
        pass


@contextmanager
def _schema_override(database_url: str, schema: str) -> Iterator[None]:
    """Pin the backend env to *schema* for the duration of the block.

    Mirrors ``tests.fixtures.postgres_backend.postgres_worker_schema``: the four
    env vars are saved, replaced and restored explicitly, with the backend /
    schema-bootstrap caches cleared on both edges so no cached schema decision
    leaks into or out of the block.
    """
    previous = {
        STATE_BACKEND_ENV: os.environ.get(STATE_BACKEND_ENV),
        STATE_DATABASE_URL_ENV: os.environ.get(STATE_DATABASE_URL_ENV),
        SCHEMA_OVERRIDE_ENV: os.environ.get(SCHEMA_OVERRIDE_ENV),
        SCHEMA_OVERRIDE_ALLOWED_ENV: os.environ.get(SCHEMA_OVERRIDE_ALLOWED_ENV),
    }
    os.environ[STATE_BACKEND_ENV] = "postgres"
    os.environ[STATE_DATABASE_URL_ENV] = database_url
    os.environ[SCHEMA_OVERRIDE_ENV] = schema
    os.environ[SCHEMA_OVERRIDE_ALLOWED_ENV] = "1"
    reset_backend_cache_for_tests()
    try:
        yield
    finally:
        reset_backend_cache_for_tests()
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


@pytest.mark.integration
def test_story_identity_fk_is_applied_per_schema(
    postgres_isolated_schema: str,
) -> None:
    """Every bootstrapped schema gets the story-identity FK, not just the first.

    ``pg_constraint`` is a PER-DATABASE catalog and constraint names are unique
    only per table, so an existence guard filtering on ``conname`` ALONE sees
    foreign schemas. Before the fix, ``_ensure_story_identity_constraints`` used
    exactly such a guard: the first schema bootstrapped into a database got
    ``story_contexts_project_key_fkey``, and every later schema silently kept
    ``story_contexts.project_key`` unreferenced.

    That is a fail-open integrity hole in production (a database legitimately
    carries several ``ak3_v*`` schemas) and a determinism defect under xdist:
    which worker schema ends up enforcing the reference depends purely on
    bootstrap order. Two peer schemas bootstrapped through the production path
    must be structurally identical.
    """
    unique = uuid.uuid4().hex[:12]
    peers = [f"ak3test_fkscope{unique}_{index}" for index in range(_PEER_SCHEMA_COUNT)]

    try:
        for schema in peers:
            _bootstrap_schema_via_production_path(postgres_isolated_schema, schema)

        story_identity = _constraint_schemas(postgres_isolated_schema, _STORY_IDENTITY_FK)
        failure_corpus = _constraint_schemas(postgres_isolated_schema, _FAILURE_CORPUS_FK)
    finally:
        _drop_schemas(postgres_isolated_schema, peers)

    missing = [schema for schema in peers if schema not in story_identity]
    assert not missing, (
        f"{_STORY_IDENTITY_FK} missing in {missing}: the existence guard leaked "
        f"across schemas (present in {sorted(story_identity)})"
    )
    assert all(schema in failure_corpus for schema in peers), (
        f"{_FAILURE_CORPUS_FK} missing in a peer schema — the bootstrap itself did "
        f"not run, so the story-identity assertion above proves nothing "
        f"(present in {sorted(failure_corpus)})"
    )
