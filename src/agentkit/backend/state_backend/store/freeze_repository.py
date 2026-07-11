"""FreezeRepository — canonical ``governance_freeze_records`` persistence (FK-55 §55.8).

The canonical (truth) side of the dual freeze materialization (FK-55 §55.10.5 /
FK-31 §31.2.7): the state backend holds the freeze record, the local
``.agentkit/governance/freeze.json`` export is written by the overlay
(:class:`~agentkit.backend.governance.principal_capabilities.freeze.ConflictFreezeOverlay`).

Architecture (mirrors ``lock_record_repository.py`` / ``fc_incident_repository.py``):
- Postgres is canonical (DK-05 §5); SQLite is the test-only parallel path
  (``AGENTKIT_ALLOW_SQLITE=1``).
- Does NOT import from ``agentkit.backend.state_backend owner modules``.
- Schema (``governance_freeze_records``) lives in both ``postgres_schema.sql``
  (canonical) and the ``sqlite_store`` package (test-parallel) — this adapter only
  reads/writes via the bootstrapped schema.

Sources:
- FK-55 §55.8 / §55.10.5 — Conflict-Freeze, atomic dual materialization
- FK-31 §31.2.7        — storybezogener Freeze-Overlay
- AG3-032 §2.1.3       — governance_freeze_records table + freeze_repository
"""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agentkit.backend.core_types.freeze import (
    FreezeKind,
    is_canonical_freeze_epoch,
    next_freeze_epoch,
)
from agentkit.backend.core_types.plane_artifact_names import GOVERNANCE_FREEZE_EXPORT_PARTS
from agentkit.backend.utils.io import atomic_write_text, read_json_object

if TYPE_CHECKING:
    from collections.abc import Iterator

#: Local freeze export, relative to the project root (FK-31 §31.2.7 / AG3-023).
#: Sourced from ``core_types.plane_artifact_names`` (the single source of truth
#: for the governance-plane freeze path) — NOT duplicated here. ``core_types`` is
#: a lower layer than ``state_backend``, so this import respects unidirectional
#: layering while satisfying SINGLE SOURCE OF TRUTH; it is the same constant the
#: (higher) ``principal_capabilities.freeze`` module imports.
_FREEZE_EXPORT_RELPATH = Path(*GOVERNANCE_FREEZE_EXPORT_PARTS)


@dataclass(frozen=True)
class FreezeRecord:
    """A persisted member of the story-scoped freeze family."""

    story_id: str
    frozen_at: str
    freeze_reason: str
    freeze_version: int
    kind: FreezeKind
    freeze_epoch: str


# ---------------------------------------------------------------------------
# Backend detection (identical pattern to lock_record_repository)
# ---------------------------------------------------------------------------


def _is_postgres() -> bool:
    return os.environ.get("AGENTKIT_STATE_BACKEND", "sqlite").lower() == "postgres"


def _assert_sqlite_allowed() -> None:
    from agentkit.backend.state_backend.config import ALLOW_SQLITE_ENV, _sqlite_allowed

    if not _sqlite_allowed():
        raise RuntimeError(
            "SQLite backend is disabled for this path. "
            f"Set {ALLOW_SQLITE_ENV}=1 only for narrow unit-test execution.",
        )


def _sqlite_db_path(store_dir: Path) -> Path:
    from agentkit.backend.state_backend.config import versioned_sqlite_db_file
    from agentkit.backend.state_backend.paths import state_backend_dir

    return state_backend_dir(store_dir) / versioned_sqlite_db_file()


@contextmanager
def _sqlite_connect(store_dir: Path) -> Iterator[sqlite3.Connection]:
    from agentkit.backend.state_backend import sqlite_store

    _assert_sqlite_allowed()
    db_path = _sqlite_db_path(store_dir)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    try:
        # Setup runs inside try so a bootstrap failure closes the conn (no leak).
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys = ON")
        # SINGLE SOURCE OF TRUTH: bootstrap the full canonical schema so
        # governance_freeze_records exists (DDL owned by sqlite_store, AG3-032).
        sqlite_store._ensure_schema(conn)
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@contextmanager
def _postgres_connect() -> Iterator[Any]:
    from agentkit.backend.state_backend import postgres_store
    from agentkit.backend.state_backend.schema_bootstrap import ensure_versioned_schema

    with postgres_store.borrow_repository_connection() as conn:
        ensure_versioned_schema(conn)
        yield conn


_SQLITE_UPSERT = """
    INSERT INTO governance_freeze_records (
        story_id, frozen_at, freeze_reason, freeze_version, kind, freeze_epoch
    ) VALUES (
        :story_id, :frozen_at, :freeze_reason, :freeze_version, :kind, :freeze_epoch
    )
    ON CONFLICT (story_id, kind) DO UPDATE SET
        frozen_at = excluded.frozen_at,
        freeze_reason = excluded.freeze_reason,
        freeze_version = excluded.freeze_version,
        freeze_epoch = excluded.freeze_epoch
"""

_PG_UPSERT = """
    INSERT INTO governance_freeze_records (
        story_id, frozen_at, freeze_reason, freeze_version, kind, freeze_epoch
    ) VALUES (
        %(story_id)s, %(frozen_at)s, %(freeze_reason)s, %(freeze_version)s,
        %(kind)s, %(freeze_epoch)s
    )
    ON CONFLICT (story_id, kind) DO UPDATE SET
        frozen_at = excluded.frozen_at,
        freeze_reason = excluded.freeze_reason,
        freeze_version = excluded.freeze_version,
        freeze_epoch = excluded.freeze_epoch
"""

_SQLITE_INSERT_AUDIT = """
    INSERT INTO governance_freeze_audit_records (
        story_id, freeze_epoch, kind, frozen_at, freeze_reason, freeze_version
    ) VALUES (
        :story_id, :freeze_epoch, :kind, :frozen_at, :freeze_reason, :freeze_version
    )
"""

_PG_INSERT_AUDIT = """
    INSERT INTO governance_freeze_audit_records (
        story_id, freeze_epoch, kind, frozen_at, freeze_reason, freeze_version
    ) VALUES (
        %(story_id)s, %(freeze_epoch)s, %(kind)s, %(frozen_at)s,
        %(freeze_reason)s, %(freeze_version)s
    )
"""


class FreezeRepository:
    """Canonical persistence adapter for ``governance_freeze_records``.

    Args:
        store_dir: Base directory for SQLite state store. Ignored for Postgres.
    """

    def __init__(self, store_dir: Path | None = None) -> None:
        from pathlib import Path as _Path

        self._store_dir: Path = store_dir or _Path.cwd()

    def set_freeze(
        self,
        story_id: str,
        *,
        frozen_at: str,
        freeze_reason: str,
        freeze_version: int,
        kind: FreezeKind = FreezeKind.CONFLICT_FREEZE,
    ) -> FreezeRecord:
        """Persist (upsert) the canonical freeze record for ``story_id``.

        Returns:
            The persisted :class:`FreezeRecord`.
        """
        if not freeze_reason.strip():
            raise ValueError("freeze_reason must not be empty")
        if _is_postgres():
            with _postgres_connect() as conn:
                # The same transaction-scoped story lock is taken by regime
                # commit fences, closing the absent-row INSERT race as well as
                # ordinary update races.
                conn.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                    (story_id,),
                )
                previous = conn.execute(
                    "SELECT freeze_epoch FROM governance_freeze_audit_records "
                    "WHERE story_id=%s "
                    "ORDER BY length(freeze_epoch) DESC, freeze_epoch DESC LIMIT 1",
                    (story_id,),
                ).fetchone()
                previous_epoch = str(previous["freeze_epoch"]) if previous is not None else None
                freeze_epoch = next_freeze_epoch(previous_epoch)
                row = _freeze_row(
                    story_id=story_id,
                    frozen_at=frozen_at,
                    freeze_reason=freeze_reason,
                    freeze_version=freeze_version,
                    kind=kind,
                    freeze_epoch=freeze_epoch,
                )
                audit_cursor = conn.execute(_PG_INSERT_AUDIT, row)
                if int(audit_cursor.rowcount) != 1:
                    raise RuntimeError("freeze audit insert affected an unexpected row count")
                cursor = conn.execute(_PG_UPSERT, row)
                if int(cursor.rowcount) != 1:
                    raise RuntimeError("freeze upsert affected an unexpected row count")
                _invalidate_open_takeover_challenges(conn, row)
        else:
            with _sqlite_connect(self._store_dir) as conn:
                previous = conn.execute(
                    "SELECT freeze_epoch FROM governance_freeze_audit_records "
                    "WHERE story_id=? "
                    "ORDER BY length(freeze_epoch) DESC, freeze_epoch DESC LIMIT 1",
                    (story_id,),
                ).fetchone()
                previous_epoch = str(previous["freeze_epoch"]) if previous is not None else None
                freeze_epoch = next_freeze_epoch(previous_epoch)
                row = _freeze_row(
                    story_id=story_id,
                    frozen_at=frozen_at,
                    freeze_reason=freeze_reason,
                    freeze_version=freeze_version,
                    kind=kind,
                    freeze_epoch=freeze_epoch,
                )
                audit_cursor = conn.execute(_SQLITE_INSERT_AUDIT, row)
                if int(audit_cursor.rowcount) != 1:
                    raise RuntimeError("freeze audit insert affected an unexpected row count")
                cursor = conn.execute(_SQLITE_UPSERT, row)
                if int(cursor.rowcount) != 1:
                    raise RuntimeError("freeze upsert affected an unexpected row count")
        return FreezeRecord(
            story_id=story_id,
            frozen_at=frozen_at,
            freeze_reason=freeze_reason,
            freeze_version=freeze_version,
            kind=kind,
            freeze_epoch=freeze_epoch,
        )

    def read_freeze(
        self,
        story_id: str,
        kind: FreezeKind = FreezeKind.CONFLICT_FREEZE,
    ) -> FreezeRecord | None:
        """Return one active family member, defaulting to conflict-freeze."""
        if _is_postgres():
            return self._pg_read(story_id, kind)
        return self._sqlite_read(story_id, kind)

    def read_freezes(self, story_id: str) -> tuple[FreezeRecord, ...]:
        """Return the complete active freeze-family set for ``story_id``."""
        if _is_postgres():
            return self._pg_read_all(story_id)
        return self._sqlite_read_all(story_id)

    def clear_freeze(
        self,
        story_id: str,
        kind: FreezeKind = FreezeKind.CONFLICT_FREEZE,
    ) -> int:
        """Resolve only ``(story_id, kind)``; return rows removed."""
        if _is_postgres():
            with _postgres_connect() as conn:
                conn.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                    (story_id,),
                )
                cursor = conn.execute(
                    "DELETE FROM governance_freeze_records WHERE story_id=%s AND kind=%s",
                    (story_id, kind.value),
                )
                return int(cursor.rowcount)
        with _sqlite_connect(self._store_dir) as conn:
            cursor = conn.execute(
                "DELETE FROM governance_freeze_records WHERE story_id=? AND kind=?",
                (story_id, kind.value),
            )
            return int(cursor.rowcount)

    def _sqlite_read(self, story_id: str, kind: FreezeKind) -> FreezeRecord | None:
        with _sqlite_connect(self._store_dir) as conn:
            row = conn.execute(
                "SELECT * FROM governance_freeze_records WHERE story_id=? AND kind=?",
                (story_id, kind.value),
            ).fetchone()
        return _row_to_record(dict(row)) if row is not None else None

    def _pg_read(self, story_id: str, kind: FreezeKind) -> FreezeRecord | None:
        with _postgres_connect() as conn:
            row = conn.execute(
                "SELECT * FROM governance_freeze_records WHERE story_id=%s AND kind=%s",
                (story_id, kind.value),
            ).fetchone()
        return _row_to_record(dict(row)) if row is not None else None

    def _sqlite_read_all(self, story_id: str) -> tuple[FreezeRecord, ...]:
        with _sqlite_connect(self._store_dir) as conn:
            rows = conn.execute(
                "SELECT * FROM governance_freeze_records WHERE story_id=? ORDER BY kind",
                (story_id,),
            ).fetchall()
        return tuple(_row_to_record(dict(row)) for row in rows)

    def _pg_read_all(self, story_id: str) -> tuple[FreezeRecord, ...]:
        with _postgres_connect() as conn:
            rows = conn.execute(
                "SELECT * FROM governance_freeze_records WHERE story_id=%s ORDER BY kind",
                (story_id,),
            ).fetchall()
        return tuple(_row_to_record(dict(row)) for row in rows)


def _row_to_record(row: dict[str, Any]) -> FreezeRecord:
    reason = row.get("freeze_reason")
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("persisted freeze_reason is missing or empty")
    epoch = row.get("freeze_epoch")
    if not isinstance(epoch, str) or not is_canonical_freeze_epoch(epoch):
        raise ValueError("persisted freeze_epoch is not canonical")
    return FreezeRecord(
        story_id=str(row["story_id"]),
        frozen_at=str(row["frozen_at"]),
        freeze_reason=reason,
        freeze_version=int(row["freeze_version"]),
        kind=FreezeKind(row["kind"]),
        freeze_epoch=epoch,
    )


def _freeze_row(
    *,
    story_id: str,
    frozen_at: str,
    freeze_reason: str,
    freeze_version: int,
    kind: FreezeKind,
    freeze_epoch: str,
) -> dict[str, object]:
    """Map the typed record fields to the persistence row shape."""

    return {
        "story_id": story_id,
        "frozen_at": frozen_at,
        "freeze_reason": freeze_reason,
        "freeze_version": freeze_version,
        "kind": kind.value,
        "freeze_epoch": freeze_epoch,
        "freeze_terminal_ref": f"freeze:{kind.value}:{freeze_epoch}",
    }


def _invalidate_open_takeover_challenges(conn: Any, row: dict[str, object]) -> None:
    """Invalidate open takeover decisions in the same freeze-entry transaction."""

    conn.execute(
        """
        UPDATE control_plane_operations AS operation
        SET status = 'invalidated', updated_at = %(frozen_at)s,
            response_json = jsonb_build_object(
                'status', 'invalidated',
                'op_id', operation.op_id,
                'operation_kind', 'ownership_takeover_request',
                'run_id', challenge.run_id,
                'phase', 'ownership'
            )::text
        FROM takeover_challenges AS challenge
        WHERE operation.op_id = challenge.request_op_id
          AND challenge.story_id = %(story_id)s
          AND challenge.status = 'pending'
        """,
        row,
    )
    conn.execute(
        """
        UPDATE takeover_approvals
        SET status = 'invalidated', decided_at = %(frozen_at)s,
            decision_reason = 'freeze'
        WHERE story_id = %(story_id)s AND status IN ('pending', 'approved')
        """,
        row,
    )
    conn.execute(
        """
        UPDATE takeover_challenges
        SET status = 'invalidated', decided_at = %(frozen_at)s,
            terminal_op_id = %(freeze_terminal_ref)s
        WHERE story_id = %(story_id)s AND status = 'pending'
        """,
        row,
    )


class LocalFreezeJsonExport:
    """Local hook-readable ``.agentkit/governance/freeze.json`` export adapter.

    Implements the
    :class:`~agentkit.backend.governance.principal_capabilities.freeze.LocalFreezeExport`
    boundary. The byte-level read/write of the export lives here (state_backend
    side) so the ``principal_capabilities`` package never imports a filesystem-IO
    helper directly (AG3-032 AK10). FK-55 §55.10.5 / FK-31 §31.2.7: the export is
    the hook-fast projection of the canonical backend freeze record.

    Args:
        project_root: Project root the export is written under.
    """

    def __init__(self, project_root: Path | None = None) -> None:
        self._project_root: Path = project_root or Path.cwd()

    def _export_path(self) -> Path:
        return self._project_root / _FREEZE_EXPORT_RELPATH

    def write(
        self,
        story_id: str,
        *,
        frozen_at: str,
        freeze_reason: str,
        freeze_version: int,
    ) -> None:
        """Atomically write the local freeze export (FK-55 §55.10.5)."""
        payload = {
            "story_id": story_id,
            "frozen_at": frozen_at,
            "freeze_reason": freeze_reason,
            "freeze_version": freeze_version,
        }
        atomic_write_text(self._export_path(), json.dumps(payload, indent=2))

    def write_record(self, record: FreezeRecord) -> None:
        """Atomically publish one canonical freeze-family record locally."""

        payload = {
            "story_id": record.story_id,
            "frozen_at": record.frozen_at,
            "freeze_reason": record.freeze_reason,
            "freeze_version": record.freeze_version,
            "kind": record.kind.value,
            "freeze_epoch": record.freeze_epoch,
        }
        atomic_write_text(self._export_path(), json.dumps(payload, indent=2))

    def read(self) -> dict[str, object] | None:
        """Return the local export payload, or ``None`` when absent.

        Raises:
            OSError / ValueError: When the export exists but cannot be parsed
                (a corrupt export is a fault, not a soft fallback — FAIL-CLOSED;
                the overlay re-raises as ``FreezePersistenceError``).
        """
        path = self._export_path()
        if not path.exists():
            return None
        return read_json_object(path)

    def remove(self) -> None:
        """Remove the local freeze export if present."""
        path = self._export_path()
        if path.exists():
            path.unlink()


__all__ = [
    "FreezeRecord",
    "FreezeRepository",
    "LocalFreezeJsonExport",
]
