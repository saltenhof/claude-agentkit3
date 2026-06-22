"""Single source of truth for PostgreSQL schema resolution and bootstrap.

Both :mod:`agentkit.backend.state_backend.postgres_store` and every
``StateBackend*`` repository under :mod:`agentkit.backend.state_backend.store` use this
helper so the versioned (or test-overridden) schema is resolved and created in
exactly one place. Before AG3-051 each repository carried its own
``CREATE SCHEMA``/``SET search_path`` copy with raw f-string interpolation; that
duplication is the model defect this module removes.

The schema name comes from :func:`agentkit.backend.state_backend.config.resolve_schema_name`
(fail-closed test override, reserved ``ak3test_`` namespace) and is emitted via
``psycopg.sql.Identifier`` — never raw string interpolation — closing the
SQL-identifier-injection surface.

This module is a T-bloodtype infrastructure driver. It MUST NOT import
BC-Records (A-bloodtype components).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from psycopg import sql

from agentkit.backend.state_backend.config import resolve_schema_name

if TYPE_CHECKING:
    import psycopg

_GLOBAL_DDL_LOCK_KEY = "agentkit_postgres_global_ddl"


def ensure_versioned_schema(conn: psycopg.Connection[Any]) -> None:
    """Create and select the resolved versioned schema on a raw connection.

    Idempotent: ``CREATE SCHEMA IF NOT EXISTS`` followed by ``SET search_path``.
    The schema name is resolved once via :func:`resolve_schema_name` and quoted
    with :class:`psycopg.sql.Identifier`.

    Args:
        conn: An open ``psycopg`` connection. ``search_path`` is set on this
            connection for the remainder of its lifetime.
    """

    conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (_GLOBAL_DDL_LOCK_KEY,))
    conn.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    schema = resolve_schema_name()
    conn.execute(
        sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(schema))
    )
    conn.execute(
        sql.SQL("SET search_path TO {}, public").format(sql.Identifier(schema)),
    )
    # The advisory lock is transaction-scoped. All call sites invoke this helper
    # immediately after opening a fresh connection; commit here so later
    # repository-specific schema bootstrap cannot hold the global DDL lock.
    conn.commit()


__all__ = ["ensure_versioned_schema"]
