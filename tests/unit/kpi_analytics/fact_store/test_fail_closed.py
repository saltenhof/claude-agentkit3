"""FAIL-CLOSED unit test: a read against a missing fact table raises (AG3-038 §7).

The repository self-bootstraps the canonical schema on every connect, so a
dropped table is normally recreated. To prove the *contract* — the read path has
NO empty-result fallback — the bootstrap is neutralised after the table is
dropped, leaving it genuinely absent. The read must then raise the backend error
(``sqlite3.OperationalError``), never return ``[]``.
"""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

import pytest

from agentkit.backend.state_backend import sqlite_store
from agentkit.backend.state_backend.config import versioned_sqlite_db_file
from agentkit.backend.state_backend.paths import state_backend_dir
from agentkit.backend.state_backend.store.fact_repository import StateBackendFactRepository

if TYPE_CHECKING:
    from pathlib import Path


def test_read_missing_table_raises_not_silent_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = StateBackendFactRepository(tmp_path)
    # Bootstrap the schema, then drop fact_story directly on the DB file.
    repo.list_fact_stories("p1")
    db_path = state_backend_dir(tmp_path) / versioned_sqlite_db_file()
    drop_conn = sqlite3.connect(str(db_path))
    try:
        drop_conn.execute("DROP TABLE fact_story")
        drop_conn.commit()
    finally:
        drop_conn.close()

    # Neutralise the auto-bootstrap so the table stays genuinely missing.
    monkeypatch.setattr(sqlite_store, "_ensure_schema", lambda conn: None)

    with pytest.raises(sqlite3.OperationalError, match="no such table"):
        repo.list_fact_stories("p1")
