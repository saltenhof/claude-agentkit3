"""Guard: DB connect helpers must close the connection on bootstrap error.

Regression guard for a latent CI-reliability defect of an entire class: several
``_connect`` / ``_sqlite_connect`` context-manager helpers opened the database
connection BEFORE entering the ``try/finally`` that closes it, so any exception
raised by the connection setup (``PRAGMA`` / ``row_factory`` / schema bootstrap)
leaked the open connection (no teardown). A leaked connection keeps an OS handle
on the database file open, which under randomized test ordering can bleed into
later tests.

Two complementary proofs:

* ``test_sqlite_store_connect_closes_when_ensure_schema_raises`` — realistic:
  forces the canonical ``sqlite_store._ensure_schema`` to raise and asserts the
  real connection is closed.
* ``test_connect_helper_closes_on_setup_failure`` — exhaustive: parametrized
  over every fixed SQLite connect helper. It replaces ``sqlite3.connect`` with a
  stub that raises on the first ``execute``/``executescript`` (the first setup
  step) and asserts each helper still closes the connection. This proves the
  ``try/finally`` now guards the handle from acquisition for the whole class.

The Postgres ``_postgres_connect`` helpers already open the connection and
immediately enter ``try`` (setup is inside), so they are not part of this class
and need no change; they are exercised by the integration suite against a real
database.
"""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING, Any

import pytest

from agentkit.backend.governance.ccag import leases as ccag_leases
from agentkit.backend.governance.ccag import requests as ccag_requests
from agentkit.backend.state_backend import sqlite_store
from agentkit.backend.state_backend.store import (
    artifact_repository,
    compaction_epoch_repository,
    conflict_freeze_proof_repository,
    custom_field_repository,
    fact_repository,
    freeze_repository,
    governance_hook_repository,
    guard_counter_repository,
    guard_decision_repository,
    lock_record_repository,
    mode_lock_repository,
    planning_projection_repository,
    project_registration_repository,
    skill_binding_repository,
    story_repository,
    telemetry_projection_repository_common,
    worker_health_repository,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from contextlib import AbstractContextManager
    from pathlib import Path


def test_sqlite_store_connect_closes_when_ensure_schema_raises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``sqlite_store._connect`` closes the connection if bootstrap raises."""
    monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
    monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")

    opened: list[sqlite3.Connection] = []
    real_connect = sqlite3.connect

    def _tracking_connect(*args: object, **kwargs: object) -> sqlite3.Connection:
        conn = real_connect(*args, **kwargs)  # type: ignore[arg-type]
        opened.append(conn)
        return conn

    monkeypatch.setattr(sqlite3, "connect", _tracking_connect)

    def _boom(_conn: sqlite3.Connection) -> None:
        msg = "simulated schema bootstrap failure"
        raise RuntimeError(msg)

    monkeypatch.setattr(sqlite_store, "_ensure_schema", _boom)

    story_dir = tmp_path / "STORY-1"
    story_dir.mkdir(parents=True, exist_ok=True)

    with (
        pytest.raises(RuntimeError, match="simulated schema bootstrap failure"),
        sqlite_store._connect(story_dir),
    ):
        pass  # pragma: no cover - body never reached

    assert opened, "expected the helper to open a sqlite connection"
    for conn in opened:
        # A closed connection raises ProgrammingError on use; a leaked (still
        # open) connection would execute successfully and fail this assertion.
        with pytest.raises(sqlite3.ProgrammingError):
            conn.execute("SELECT 1")


class _RaisingConnection:
    """Stand-in for a sqlite3 connection that fails during setup.

    ``execute`` / ``executescript`` raise on first use (mimicking a failing
    ``PRAGMA`` or schema bootstrap). ``close`` records that it ran so the test
    can assert the helper closed the connection on the failure path.
    """

    def __init__(self) -> None:
        self.closed = False
        self.row_factory: Any = None

    def execute(self, *_args: object, **_kwargs: object) -> Any:
        msg = "simulated setup/bootstrap failure"
        raise RuntimeError(msg)

    def executescript(self, *_args: object, **_kwargs: object) -> Any:
        msg = "simulated setup/bootstrap failure"
        raise RuntimeError(msg)

    def commit(self) -> None:  # pragma: no cover - never reached on failure path
        return None

    def rollback(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True


# Every fixed SQLite connect helper, with how to call it. ``dir`` helpers take a
# store/story directory; ``file`` helpers (CCAG) take the DB file path.
_SQLITE_CONNECT_HELPERS: list[tuple[str, Any, str]] = [
    ("sqlite_store._connect", sqlite_store._connect, "dir"),
    ("ccag.leases._connect", ccag_leases._connect, "file"),
    ("ccag.requests._connect", ccag_requests._connect, "file"),
    (
        "artifact_repository._sqlite_connect",
        artifact_repository._sqlite_connect,
        "dir",
    ),
    (
        "compaction_epoch_repository._sqlite_connect",
        compaction_epoch_repository._sqlite_connect,
        "dir",
    ),
    (
        "conflict_freeze_proof_repository._sqlite_connect",
        conflict_freeze_proof_repository._sqlite_connect,
        "dir",
    ),
    (
        "custom_field_repository._sqlite_connect",
        custom_field_repository._sqlite_connect,
        "dir",
    ),
    ("fact_repository._sqlite_connect", fact_repository._sqlite_connect, "dir"),
    ("freeze_repository._sqlite_connect", freeze_repository._sqlite_connect, "dir"),
    (
        "governance_hook_repository._sqlite_connect",
        governance_hook_repository._sqlite_connect,
        "dir",
    ),
    (
        "guard_counter_repository._sqlite_connect",
        guard_counter_repository._sqlite_connect,
        "dir",
    ),
    (
        "guard_decision_repository._sqlite_connect",
        guard_decision_repository._sqlite_connect,
        "dir",
    ),
    (
        "lock_record_repository._sqlite_connect",
        lock_record_repository._sqlite_connect,
        "dir",
    ),
    (
        "mode_lock_repository._sqlite_connect",
        mode_lock_repository._sqlite_connect,
        "dir",
    ),
    (
        "planning_projection_repository._sqlite_connect",
        planning_projection_repository._sqlite_connect,
        "dir",
    ),
    (
        "telemetry_projection_repository_common._sqlite_connect",
        telemetry_projection_repository_common._sqlite_connect,
        "dir",
    ),
    (
        "telemetry_projection_repository_common._sqlite_connect_qa",
        telemetry_projection_repository_common._sqlite_connect_qa,
        "dir",
    ),
    (
        "project_registration_repository._sqlite_connect",
        project_registration_repository._sqlite_connect,
        "dir",
    ),
    (
        "skill_binding_repository._sqlite_connect",
        skill_binding_repository._sqlite_connect,
        "dir",
    ),
    ("story_repository._sqlite_connect", story_repository._sqlite_connect, "dir"),
    (
        "worker_health_repository._sqlite_connect",
        worker_health_repository._sqlite_connect,
        "dir",
    ),
]


@pytest.mark.parametrize(
    ("connect_helper", "arg_kind"),
    [(helper, kind) for _name, helper, kind in _SQLITE_CONNECT_HELPERS],
    ids=[name for name, _helper, _kind in _SQLITE_CONNECT_HELPERS],
)
def test_connect_helper_closes_on_setup_failure(
    connect_helper: Callable[[Path], AbstractContextManager[Any]],
    arg_kind: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each SQLite connect helper closes the connection if setup raises."""
    monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
    monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")

    opened: list[_RaisingConnection] = []

    def _fake_connect(*_args: object, **_kwargs: object) -> _RaisingConnection:
        conn = _RaisingConnection()
        opened.append(conn)
        return conn

    # All helpers reference the shared ``sqlite3.connect``; patching it covers
    # every module uniformly.
    monkeypatch.setattr(sqlite3, "connect", _fake_connect)

    arg: Path
    if arg_kind == "file":
        arg = tmp_path / "ccag" / "store.sqlite"
    else:
        arg = tmp_path / "store_dir"
        arg.mkdir(parents=True, exist_ok=True)

    with (
        pytest.raises(RuntimeError, match="simulated setup/bootstrap failure"),
        connect_helper(arg),
    ):
        pass  # pragma: no cover - body never reached

    assert opened, "expected the helper to open a connection"
    assert all(conn.closed for conn in opened), (
        "connection was leaked (not closed) when setup/bootstrap raised"
    )
