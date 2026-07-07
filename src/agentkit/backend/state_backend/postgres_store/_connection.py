"""Postgres connection-pool lifecycle and connection borrowing."""

from __future__ import annotations

import atexit
import os
import threading
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from agentkit.backend.state_backend.config import (
    STATE_DATABASE_URL_ENV,
    load_state_backend_config,
    resolve_schema_name,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    import psycopg

from ._compat import _CompatConnection
from ._schema import _ensure_schema_once, _ensure_versioned_schema


def _database_url() -> str:
    config = load_state_backend_config()
    if not config.database_url:
        raise RuntimeError(
            f"{STATE_DATABASE_URL_ENV} must be set when AGENTKIT_STATE_BACKEND=postgres",
        )
    return config.database_url


def _database_label() -> str:
    return STATE_DATABASE_URL_ENV


def current_schema_name() -> str:
    """Return the resolved PostgreSQL schema used by this driver.

    Delegates to :func:`resolve_schema_name` so the test override (AG3-051) is
    honored consistently with every other connection path. Production returns
    the versioned ``ak3_v<slug>`` unchanged.
    """

    return resolve_schema_name()

_STATE_POOL_MAX_SIZE_ENV = "AGENTKIT_STATE_POOL_MAX_SIZE"
_DEFAULT_STATE_POOL_MAX_SIZE = 1
_POOL_LOCK = threading.Lock()
_POOL: ConnectionPool[psycopg.Connection[Any]] | None = None
_POOL_URL: str | None = None


def _resolve_state_pool_max_size() -> int:
    """Resolve the per-process pool ceiling (default 1 = one connection/worker)."""

    raw = os.environ.get(_STATE_POOL_MAX_SIZE_ENV)
    if raw is None or not raw.strip():
        return _DEFAULT_STATE_POOL_MAX_SIZE
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(
            f"Invalid {_STATE_POOL_MAX_SIZE_ENV}={raw!r}; expected a positive integer.",
        ) from exc
    if value < 1:
        raise RuntimeError(
            f"Invalid {_STATE_POOL_MAX_SIZE_ENV}={value}; the pool must allow at least one connection.",
        )
    return value


def _reset_pooled_connection(conn: psycopg.Connection[Any]) -> None:
    """Scrub per-borrow session state before a connection re-enters the pool.

    Discards any lingering transaction and resets every session GUC (notably
    ``search_path``, which each borrow re-establishes via
    :func:`ensure_versioned_schema`). Guarantees no session-state carry-over
    (``search_path`` / GUC leakage) between pooled borrows.
    """

    if conn.closed:
        return
    conn.rollback()
    conn.execute("RESET ALL")
    conn.commit()


def _build_state_pool(url: str) -> ConnectionPool[psycopg.Connection[Any]]:
    pool: ConnectionPool[psycopg.Connection[Any]] = ConnectionPool(
        conninfo=url,
        min_size=1,
        max_size=_resolve_state_pool_max_size(),
        kwargs={"row_factory": dict_row},
        reset=_reset_pooled_connection,
        check=ConnectionPool.check_connection,
        name="agentkit-state-backend",
        open=False,
    )
    pool.open()
    return pool


def _get_pool() -> ConnectionPool[psycopg.Connection[Any]]:
    """Return the process-bound connection pool for the active database URL.

    The pool is rebuilt only when the resolved URL changes (test env switching);
    within a process/worker bound to one URL it is reused, so exactly one physical
    connection (at the default ``max_size=1``) is held for the worker's lifetime.
    """

    global _POOL, _POOL_URL
    url = _database_url()
    with _POOL_LOCK:
        if _POOL is not None and url == _POOL_URL:
            return _POOL
        if _POOL is not None:
            _POOL.close()
        _POOL = _build_state_pool(url)
        _POOL_URL = url
        return _POOL


def _dispose_pool() -> None:
    """Close and forget the process-bound pool (atexit / test teardown)."""

    global _POOL, _POOL_URL
    with _POOL_LOCK:
        if _POOL is not None:
            _POOL.close()
        _POOL = None
        _POOL_URL = None


atexit.register(_dispose_pool)


@contextmanager
def _connect_global() -> Iterator[_CompatConnection]:
    # Borrow from the process-bound pool instead of opening a fresh connection per
    # operation (connection-churn elimination). ``pool.connection()`` commits on a
    # clean exit, rolls back on exception, and RETURNS the connection to the pool
    # (never closes it); ``_reset_pooled_connection`` scrubs session state on return.
    # The staged commits below are unchanged and load-bearing: they release the
    # global DDL advisory lock before the heavy table/index bootstrap so parallel
    # schemas do not serialize behind one worker.
    pool = _get_pool()
    with pool.connection() as conn:
        compat = _CompatConnection(conn)
        _ensure_versioned_schema(compat)
        conn.commit()
        _ensure_schema_once(compat)
        conn.commit()
        yield compat
        conn.commit()


@contextmanager
def _connect(story_dir: Path) -> Iterator[_CompatConnection]:
    del story_dir
    with _connect_global() as compat:
        yield compat


@contextmanager
def borrow_repository_connection() -> Iterator[psycopg.Connection[Any]]:
    """Borrow the process-bound pool connection for a StateBackend repository op.

    ONE connection way for the whole backend (FIX THE MODEL): the ``StateBackend*``
    repositories under ``state_backend.store`` share the SAME process-bound pool as
    the store instead of each opening a fresh ``psycopg.connect`` per operation. A
    worker therefore holds at most ONE physical connection (default ``max_size=1``)
    across store AND repository work, closing the "a repo op opens a SECOND transient
    connection" gap.

    This is the sanctioned StateBackendRepository -> StateBackendDrivers edge (the
    repos already import ``schema_bootstrap.ensure_versioned_schema`` from the same
    driver boundary). The borrow performs NO schema work itself: it yields the pooled
    raw connection and lets EACH repository run its own bootstrap
    (``ensure_versioned_schema`` and its per-repo ``CREATE TABLE IF NOT EXISTS`` /
    ``_ensure_schema_once``) exactly as before — so every repository's schema,
    ``search_path`` and DDL behaviour is unchanged; only the connection ACQUISITION
    moves to the pool.

    Transaction semantics are identical to the former connect-per-op model: the block
    commits on a clean exit and the pool's ``reset`` (``_reset_pooled_connection``,
    which runs ``conn.rollback()`` first) discards an uncommitted transaction on an
    exception. The connection is RETURNED to the pool (never closed), and ``RESET
    ALL`` scrubs session state so ``search_path`` starts each borrow at the same
    default a fresh connection would carry. Rows are ``dict_row`` (the pool default),
    matching every repository's dict-keyed row access — no per-repo row_factory
    override is required. No repository path acquires a second pooled connection while
    holding one (verified: no Store<->Repo and no Repo<->Repo nesting), so the size-1
    pool cannot self-deadlock.
    """
    pool = _get_pool()
    with pool.connection() as conn:
        yield conn
        conn.commit()


@contextmanager
def _borrow_pooled_connection_raw() -> Iterator[psycopg.Connection[Any]]:
    """Borrow the pooled raw connection WITHOUT running the schema bootstrap.

    Sanctioned maintenance seam (e.g. the Postgres test fixture's per-test
    TRUNCATE): it reuses the SAME pooled connection as store operations — so it adds
    NO connection churn — but deliberately SKIPS ``_ensure_versioned_schema`` /
    ``_ensure_schema_once``. Skipping the bootstrap is required, not merely an
    optimisation: running it here would populate the process schema-bootstrap cache
    (``_SCHEMA_ENSURED_NAMES``) BEFORE the caller mutates the schema (e.g. a TRUNCATE
    that empties ``schema_versions``), which would then suppress the legitimate
    re-bootstrap on the NEXT store operation. Callers must address objects by
    QUALIFIED ``schema.table`` — this connection carries no guaranteed
    ``search_path``. Commits on clean exit; ``pool.connection()`` rolls back on
    exception.
    """
    pool = _get_pool()
    with pool.connection() as conn:
        yield conn
        conn.commit()
