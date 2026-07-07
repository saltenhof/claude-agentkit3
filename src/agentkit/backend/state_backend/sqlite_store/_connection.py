"""SQLite connection lifecycle, pragmas, and schema bootstrap."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from importlib import import_module
from typing import TYPE_CHECKING

from agentkit.backend.state_backend.config import ALLOW_SQLITE_ENV, _sqlite_allowed

from ._common import state_db_path_for

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

def _assert_sqlite_allowed() -> None:
    """Raise RuntimeError if SQLite backend is not explicitly enabled.

    Enforces the AGENTKIT_ALLOW_SQLITE=1 gating pattern (Fix E8, AG3-031 Pass-6).
    """
    if not _sqlite_allowed():
        raise RuntimeError(
            f"SQLite backend is disabled for this path. Set {ALLOW_SQLITE_ENV}=1 only for narrow unit-test execution.",
        )


@contextmanager
def _connect(story_dir: Path) -> Iterator[sqlite3.Connection]:
    db_path = state_db_path_for(story_dir)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    _assert_sqlite_allowed()
    conn = sqlite3.connect(str(db_path))
    # The connection setup (row factory, PRAGMA, schema bootstrap) must live
    # INSIDE the try so a failure during bootstrap closes the connection instead
    # of leaking the open handle (fail-closed resource lifecycle). Leaking an
    # open SQLite connection keeps an OS handle on the database file and bled
    # into later tests under randomized ordering.
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        sqlite_store = import_module("agentkit.backend.state_backend.sqlite_store")
        sqlite_store._ensure_schema(conn)
        yield conn
        conn.commit()
    finally:
        conn.close()
