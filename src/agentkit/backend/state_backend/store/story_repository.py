"""State-backend repository for Story stammdaten (story_context_manager BC).

This is the SQLite/Postgres-backed implementation of ``StoryRepository``
(``story_context_manager.story_repository.StoryRepository`` Protocol).

Architecture Conformance AC003/AC004:
  - Does NOT import or use the generic ``state_backend.store.facade``.
  - Accesses the database directly via the sqlite_store / postgres_store
    drivers (raw connection pattern).
  - The ``stories`` and ``story_specifications`` tables were added in
    schema 3.3.0 (side-by-side, additive).

Design:
  - SQLite: uses ``_sqlite_connect`` (versioned .sqlite file).
  - Postgres: uses ``_postgres_connect`` (psycopg, DSN from env var).
  - Column naming differs between backends:
    - SQLite: ``participating_repos_json``, ``labels_json``, etc. (TEXT)
    - Postgres: ``participating_repos``, ``labels``, etc. (JSONB)
  - ``create_story_atomic`` wraps number allocation + story + spec save
    in a single database transaction (Befund 6).

Story stammdaten persistence is global (project-scoped), not per-story-dir.
"""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID

from agentkit.backend.core_types import StorySize
from agentkit.backend.story_context_manager.display_id import format_story_display_id
from agentkit.backend.story_context_manager.story_model import (
    ChangeImpact,
    ConceptQuality,
    RiskLevel,
    Story,
    StorySpecification,
    StoryStatus,
    WireStoryMode,
    WireStoryType,
)

if TYPE_CHECKING:
    from collections.abc import Iterator


# ---------------------------------------------------------------------------
# Backend detection
# ---------------------------------------------------------------------------


def _is_postgres() -> bool:
    """Return True when AGENTKIT_STATE_BACKEND=postgres."""
    return os.environ.get("AGENTKIT_STATE_BACKEND", "sqlite").lower() == "postgres"


def _assert_sqlite_allowed() -> None:
    """Raise RuntimeError if SQLite backend is not explicitly enabled.

    Enforces the AGENTKIT_ALLOW_SQLITE=1 gating pattern (Fix E8, AG3-031 Pass-6).
    """
    from agentkit.backend.state_backend.config import ALLOW_SQLITE_ENV, _sqlite_allowed

    if not _sqlite_allowed():
        raise RuntimeError(
            "SQLite backend is disabled for this path. "
            f"Set {ALLOW_SQLITE_ENV}=1 only for narrow unit-test execution.",
        )


# ---------------------------------------------------------------------------
# Helpers: JSON serialization (SQLite needs TEXT, Postgres handles natively)
# ---------------------------------------------------------------------------


def _dump(value: object) -> str:
    return json.dumps(value, sort_keys=True, default=str)


def _load(raw: str | None, default: Any) -> Any:
    if raw is None:
        return default
    return json.loads(raw)


# ---------------------------------------------------------------------------
# Row <-> Story conversion (SQLite variant — JSON-text columns)
# ---------------------------------------------------------------------------


def _story_to_sqlite_row(story: Story) -> dict[str, object]:
    return {
        "story_uuid": str(story.story_uuid),
        "project_key": story.project_key,
        "story_number": story.story_number,
        "story_display_id": story.story_display_id,
        "title": story.title,
        "story_type": story.story_type.value,
        "status": story.status.value,
        "size": story.size.value,
        "mode": story.mode.value if story.mode is not None else None,
        "epic": story.epic,
        "module": story.module,
        "participating_repos_json": _dump(story.participating_repos),
        "change_impact": story.change_impact.value,
        "concept_quality": story.concept_quality.value,
        "owner": story.owner,
        "risk": story.risk.value,
        "blocker": story.blocker,
        "labels_json": _dump(story.labels),
        "wave": story.wave,
        "critical_path": 1 if story.critical_path else 0,
        # AG3-057: Trigger 3 input (new_structures).
        "new_structures": 1 if story.new_structures else 0,
        # AG3-068: VectorDB-conflict producer flag (FK-21 §21.12).
        "vectordb_conflict_resolved": 1 if story.vectordb_conflict_resolved else 0,
        # AG3-072 (FK-54 §54.8.5): materialized split lineage (real ids).
        "split_from": story.split_from,
        "split_successors_json": _dump(story.split_successors),
        "created_at": story.created_at.isoformat() if story.created_at else None,
        "completed_at": story.completed_at.isoformat() if story.completed_at else None,
    }


def _sqlite_row_to_story(row: dict[str, Any]) -> Story:
    return Story(
        story_uuid=UUID(str(row["story_uuid"])),
        project_key=str(row["project_key"]),
        story_number=int(row["story_number"]),
        story_display_id=str(row["story_display_id"]),
        title=str(row["title"]),
        story_type=WireStoryType(str(row["story_type"])),
        status=StoryStatus(str(row["status"])),
        size=StorySize(str(row["size"])),
        mode=WireStoryMode(str(row["mode"])) if row["mode"] else None,
        epic=str(row["epic"]),
        module=str(row["module"]),
        participating_repos=_load(str(row["participating_repos_json"]), []),
        change_impact=ChangeImpact(str(row["change_impact"])),
        concept_quality=ConceptQuality(str(row["concept_quality"])),
        owner=str(row["owner"]),
        risk=RiskLevel(str(row["risk"])),
        blocker=str(row["blocker"]) if row["blocker"] else None,
        labels=_load(str(row["labels_json"]), []),
        wave=int(row["wave"]),
        critical_path=bool(row["critical_path"]),
        # AG3-057: Trigger 3 input (new_structures). Fail-closed default 0/False
        # when the column is absent (older schema rows without the column).
        new_structures=bool(row.get("new_structures", 0)),
        # AG3-068: VectorDB-conflict producer flag. Fail-closed default 0/False
        # when the column is absent (older schema rows without the column).
        vectordb_conflict_resolved=bool(row.get("vectordb_conflict_resolved", 0)),
        # AG3-072 (FK-54 §54.8.5): materialized split lineage. Fail-closed
        # defaults (None / []) when the columns are absent on older schema rows.
        split_from=(
            str(row["split_from"])
            if row.get("split_from")
            else None
        ),
        split_successors=_load(row.get("split_successors_json"), []),
        created_at=(
            datetime.fromisoformat(str(row["created_at"]))
            if row["created_at"]
            else None
        ),
        completed_at=(
            datetime.fromisoformat(str(row["completed_at"]))
            if row["completed_at"]
            else None
        ),
    )


def _sqlite_spec_to_row(story_uuid: UUID, spec: StorySpecification) -> dict[str, object]:
    return {
        "story_uuid": str(story_uuid),
        "need": spec.need,
        "solution": spec.solution,
        "acceptance_json": _dump(list(spec.acceptance)),
        "definition_of_done_json": _dump(list(spec.definition_of_done))
        if spec.definition_of_done is not None
        else None,
        "concept_refs_json": _dump(list(spec.concept_refs))
        if spec.concept_refs is not None
        else None,
        "guardrail_refs_json": _dump(list(spec.guardrail_refs))
        if spec.guardrail_refs is not None
        else None,
        "external_sources_json": _dump(list(spec.external_sources))
        if spec.external_sources is not None
        else None,
    }


def _sqlite_row_to_spec(row: dict[str, Any]) -> StorySpecification:
    return StorySpecification(
        need=str(row["need"]) if row["need"] else None,
        solution=str(row["solution"]) if row["solution"] else None,
        acceptance=_load(str(row["acceptance_json"]), []),
        definition_of_done=_load(row.get("definition_of_done_json"), None),
        concept_refs=_load(row.get("concept_refs_json"), None),
        guardrail_refs=_load(row.get("guardrail_refs_json"), None),
        external_sources=_load(row.get("external_sources_json"), None),
    )


# ---------------------------------------------------------------------------
# Row <-> Story conversion (Postgres variant — JSONB columns, UUID native)
# ---------------------------------------------------------------------------


def _story_to_pg_row(story: Story) -> dict[str, object]:
    """Build a row dict for Postgres (JSONB columns hold Python objects)."""
    return {
        "story_uuid": str(story.story_uuid),
        "project_key": story.project_key,
        "story_number": story.story_number,
        "story_display_id": story.story_display_id,
        "title": story.title,
        "story_type": story.story_type.value,
        "status": story.status.value,
        "size": story.size.value,
        "mode": story.mode.value if story.mode is not None else None,
        "epic": story.epic,
        "module": story.module,
        "participating_repos": story.participating_repos,
        "change_impact": story.change_impact.value,
        "concept_quality": story.concept_quality.value,
        "owner": story.owner,
        "risk": story.risk.value,
        "blocker": story.blocker,
        "labels": story.labels,
        "wave": story.wave,
        "critical_path": story.critical_path,
        # AG3-057: Trigger 3 input (new_structures).
        "new_structures": story.new_structures,
        # AG3-068: VectorDB-conflict producer flag (FK-21 §21.12).
        "vectordb_conflict_resolved": story.vectordb_conflict_resolved,
        # AG3-072 (FK-54 §54.8.5): materialized split lineage (real ids).
        "split_from": story.split_from,
        "split_successors": story.split_successors,
        "created_at": story.created_at.isoformat() if story.created_at else None,
        "completed_at": story.completed_at.isoformat() if story.completed_at else None,
    }


def _pg_row_to_story(row: dict[str, Any]) -> Story:
    """Reconstruct a Story from a Postgres row (JSONB already deserialized)."""
    repos = row.get("participating_repos") or []
    labels = row.get("labels") or []
    return Story(
        story_uuid=UUID(str(row["story_uuid"])),
        project_key=str(row["project_key"]),
        story_number=int(row["story_number"]),
        story_display_id=str(row["story_display_id"]),
        title=str(row["title"]),
        story_type=WireStoryType(str(row["story_type"])),
        status=StoryStatus(str(row["status"])),
        size=StorySize(str(row["size"])),
        mode=WireStoryMode(str(row["mode"])) if row["mode"] else None,
        epic=str(row["epic"]),
        module=str(row["module"]),
        participating_repos=[str(r) for r in repos],
        change_impact=ChangeImpact(str(row["change_impact"])),
        concept_quality=ConceptQuality(str(row["concept_quality"])),
        owner=str(row["owner"]),
        risk=RiskLevel(str(row["risk"])),
        blocker=str(row["blocker"]) if row["blocker"] else None,
        labels=[str(lb) for lb in labels],
        wave=int(row["wave"]),
        critical_path=bool(row["critical_path"]),
        # AG3-057: Trigger 3 input (new_structures). Fail-closed default False
        # when column absent (older schema rows without the column).
        new_structures=bool(row.get("new_structures", False)),
        # AG3-068: VectorDB-conflict producer flag. Fail-closed default False
        # when column absent (older schema rows without the column).
        vectordb_conflict_resolved=bool(row.get("vectordb_conflict_resolved", False)),
        # AG3-072 (FK-54 §54.8.5): materialized split lineage. Fail-closed
        # defaults (None / []) when the columns are absent on older schema rows.
        split_from=(
            str(row["split_from"])
            if row.get("split_from")
            else None
        ),
        split_successors=[str(sid) for sid in (row.get("split_successors") or [])],
        created_at=(
            datetime.fromisoformat(str(row["created_at"]))
            if row["created_at"]
            else None
        ),
        completed_at=(
            datetime.fromisoformat(str(row["completed_at"]))
            if row["completed_at"]
            else None
        ),
    )


def _pg_spec_to_row(story_uuid: UUID, spec: StorySpecification) -> dict[str, object]:
    return {
        "story_uuid": str(story_uuid),
        "need": spec.need,
        "solution": spec.solution,
        "acceptance": list(spec.acceptance),
        "definition_of_done": list(spec.definition_of_done)
        if spec.definition_of_done is not None
        else None,
        "concept_refs": list(spec.concept_refs)
        if spec.concept_refs is not None
        else None,
        "guardrail_refs": list(spec.guardrail_refs)
        if spec.guardrail_refs is not None
        else None,
        "external_sources": list(spec.external_sources)
        if spec.external_sources is not None
        else None,
    }


def _pg_row_to_spec(row: dict[str, Any]) -> StorySpecification:
    return StorySpecification(
        need=str(row["need"]) if row["need"] else None,
        solution=str(row["solution"]) if row["solution"] else None,
        acceptance=list(row.get("acceptance") or []),
        definition_of_done=list(row["definition_of_done"])
        if row.get("definition_of_done") is not None
        else None,
        concept_refs=list(row["concept_refs"])
        if row.get("concept_refs") is not None
        else None,
        guardrail_refs=list(row["guardrail_refs"])
        if row.get("guardrail_refs") is not None
        else None,
        external_sources=list(row["external_sources"])
        if row.get("external_sources") is not None
        else None,
    )


# ---------------------------------------------------------------------------
# SQLite connection helper
# ---------------------------------------------------------------------------


def _sqlite_db_path(store_dir: Path) -> Path:
    """Return the versioned SQLite database path for the given store_dir."""
    from agentkit.backend.state_backend.config import versioned_sqlite_db_file
    from agentkit.backend.state_backend.paths import state_backend_dir

    return state_backend_dir(store_dir) / versioned_sqlite_db_file()


@contextmanager
def _sqlite_connect(store_dir: Path) -> Iterator[sqlite3.Connection]:
    db_path = _sqlite_db_path(store_dir)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    _assert_sqlite_allowed()
    conn = sqlite3.connect(str(db_path), timeout=30.0)
    try:
        # Setup runs inside try so a bootstrap failure closes the conn (no leak).
        conn.row_factory = sqlite3.Row
        # AG3-050 C2: set busy_timeout FIRST so every subsequent lock acquisition
        # (including the WAL switch and BEGIN IMMEDIATE inside
        # create_story_atomic) waits for a held write lock instead of failing
        # immediately. This keeps the single canonical allocator gap-free +
        # race-safe under real cross-connection concurrency.
        conn.execute("PRAGMA busy_timeout = 30000")
        # Only switch journal mode when it is not already WAL. The WAL switch
        # needs an exclusive moment that does NOT honour busy_timeout, so
        # re-issuing it on every connection would spuriously raise "database is
        # locked" under concurrent create_story_atomic calls. Reading the
        # current mode takes no write lock; once any connection has set WAL it
        # is persistent for the file.
        current_mode = conn.execute("PRAGMA journal_mode").fetchone()
        if current_mode is None or str(current_mode[0]).lower() != "wal":
            conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys = ON")
        # Ensure the stories tables exist (additive, idempotent). The CREATE
        # TABLE IF NOT EXISTS DDL waits on the write lock via busy_timeout above.
        _ensure_story_tables_sqlite(conn)
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _migrate_stories_table_sqlite(conn: sqlite3.Connection) -> None:
    """Apply additive column migrations to an already-existing ``stories`` table.

    Each migration is gated behind a column-existence check so it is idempotent
    and safe to call on every connection.

    AG3-057: adds ``new_structures INTEGER NOT NULL DEFAULT 0`` (Trigger 3 input).
    AG3-068: adds ``vectordb_conflict_resolved INTEGER NOT NULL DEFAULT 0``
    (FK-21 §21.12 producer flag).
    """
    existing_columns = {
        row[1]
        for row in conn.execute("PRAGMA table_info(stories)").fetchall()
    }
    if "new_structures" not in existing_columns:
        conn.execute(
            "ALTER TABLE stories ADD COLUMN new_structures INTEGER NOT NULL DEFAULT 0"
        )
    if "vectordb_conflict_resolved" not in existing_columns:
        conn.execute(
            "ALTER TABLE stories ADD COLUMN "
            "vectordb_conflict_resolved INTEGER NOT NULL DEFAULT 0"
        )
    # AG3-072 (FK-54 §54.8.5): materialized split lineage columns.
    if "split_from" not in existing_columns:
        conn.execute("ALTER TABLE stories ADD COLUMN split_from TEXT")
    if "split_successors_json" not in existing_columns:
        conn.execute(
            "ALTER TABLE stories ADD COLUMN "
            "split_successors_json TEXT NOT NULL DEFAULT '[]'"
        )


def _ensure_story_tables_sqlite(conn: sqlite3.Connection) -> None:
    """Create the story stammdaten tables if they don't exist yet.

    These tables were added in schema 3.3.0 (side-by-side, additive).
    AG3-057: the ``new_structures`` column is added via ``ALTER TABLE ADD COLUMN``
    when the table already exists but the column is absent (additive migration).

    Concurrency (AG3-050 C2): the ``CREATE TABLE`` DDL takes a write lock and,
    when issued in autocommit mode, SQLite refuses to honour ``busy_timeout``
    for the read->write upgrade and raises ``SQLITE_BUSY`` immediately. We
    therefore gate the DDL behind a cheap, read-lock-only ``sqlite_master``
    existence check: only the very first connection (when the table is absent)
    runs the DDL; all later connections skip it and never contend on the write
    lock during concurrent ``create_story_atomic`` calls.
    """
    existing = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'stories'",
    ).fetchone()
    if existing is not None:
        # Table already exists — apply any additive column migrations.
        _migrate_stories_table_sqlite(conn)
        return
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS stories (
            story_uuid TEXT NOT NULL,
            project_key TEXT NOT NULL,
            story_number INTEGER NOT NULL,
            story_display_id TEXT NOT NULL,
            title TEXT NOT NULL,
            story_type TEXT NOT NULL,
            status TEXT NOT NULL,
            size TEXT NOT NULL,
            mode TEXT,
            epic TEXT NOT NULL,
            module TEXT NOT NULL,
            participating_repos_json TEXT NOT NULL,
            change_impact TEXT NOT NULL,
            concept_quality TEXT NOT NULL,
            owner TEXT NOT NULL,
            risk TEXT NOT NULL,
            blocker TEXT,
            labels_json TEXT NOT NULL,
            wave INTEGER NOT NULL,
            critical_path INTEGER NOT NULL,
            -- AG3-057: Trigger 3 input — new code/module structures introduced.
            -- Default 0 (False) = fail-closed: absence does not trigger Exploration.
            new_structures INTEGER NOT NULL DEFAULT 0,
            -- AG3-068: VectorDB-conflict producer flag (FK-21 §21.12).
            -- Default 0 (False) = fail-closed: only a resolved stage-2 conflict sets it.
            vectordb_conflict_resolved INTEGER NOT NULL DEFAULT 0,
            -- AG3-072 (FK-54 §54.8.5): materialized split lineage. ``split_from``
            -- is the cancelled source on a successor; ``split_successors_json`` is
            -- the real successor id list on the source. Defaults NULL / '[]'.
            split_from TEXT,
            split_successors_json TEXT NOT NULL DEFAULT '[]',
            created_at TEXT,
            completed_at TEXT,
            PRIMARY KEY (story_uuid),
            UNIQUE (story_display_id),
            -- AG3-050 A3: project-scoped UNIQUE backing the composite FK from
            -- story_dependencies (project_key, story_id) so cross-project edges
            -- fail closed at the database layer.
            UNIQUE (project_key, story_display_id),
            UNIQUE (project_key, story_number)
        );

        CREATE INDEX IF NOT EXISTS stories_project_key_idx
            ON stories (project_key);

        CREATE TABLE IF NOT EXISTS story_specifications (
            story_uuid TEXT NOT NULL,
            need TEXT,
            solution TEXT,
            acceptance_json TEXT NOT NULL,
            definition_of_done_json TEXT,
            concept_refs_json TEXT,
            guardrail_refs_json TEXT,
            external_sources_json TEXT,
            PRIMARY KEY (story_uuid)
        );
        """
    )


# ---------------------------------------------------------------------------
# Postgres connection helper
# ---------------------------------------------------------------------------


@contextmanager
def _postgres_connect() -> Iterator[Any]:
    """Open a psycopg connection with dict_row factory and versioned schema."""
    from agentkit.backend.state_backend import postgres_store
    from agentkit.backend.state_backend.schema_bootstrap import ensure_versioned_schema

    with postgres_store.borrow_repository_connection() as conn:
        ensure_versioned_schema(conn)
        yield conn


# ---------------------------------------------------------------------------
# StateBackendStoryRepository
# ---------------------------------------------------------------------------


class StateBackendStoryRepository:
    """SQLite/Postgres-backed implementation of StoryRepository Protocol.

    Architecture Conformance: does NOT use ``state_backend.store.facade``.
    This is an explicit, component-specific repository (AC003/AC004).

    Backend is determined at method-call time from
    ``AGENTKIT_STATE_BACKEND`` env var (``sqlite`` or ``postgres``).

    Args:
        store_dir: Base directory for the state store (contains ``.agentkit/``).
            Used only for the SQLite backend. Defaults to cwd.
    """

    def __init__(self, store_dir: Path | None = None) -> None:
        self._store_dir: Path = store_dir or Path.cwd()

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    def get_by_display_id(self, story_display_id: str) -> Story | None:
        """Load a Story by its display ID."""
        if _is_postgres():
            return self._pg_get_by_display_id(story_display_id)
        with _sqlite_connect(self._store_dir) as conn:
            cursor = conn.execute(
                "SELECT * FROM stories WHERE story_display_id = ?",
                (story_display_id,),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return _sqlite_row_to_story(dict(row))

    def _pg_get_by_display_id(self, story_display_id: str) -> Story | None:
        with _postgres_connect() as conn:
            cursor = conn.execute(
                "SELECT * FROM stories WHERE story_display_id = %s",
                (story_display_id,),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return _pg_row_to_story(dict(row))

    def get_by_uuid(self, story_uuid: UUID) -> Story | None:
        """Load a Story by its technical UUID."""
        if _is_postgres():
            return self._pg_get_by_uuid(story_uuid)
        with _sqlite_connect(self._store_dir) as conn:
            cursor = conn.execute(
                "SELECT * FROM stories WHERE story_uuid = ?",
                (str(story_uuid),),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return _sqlite_row_to_story(dict(row))

    def _pg_get_by_uuid(self, story_uuid: UUID) -> Story | None:
        with _postgres_connect() as conn:
            cursor = conn.execute(
                "SELECT * FROM stories WHERE story_uuid = %s",
                (str(story_uuid),),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return _pg_row_to_story(dict(row))

    def list_for_project(self, project_key: str) -> list[Story]:
        """Return all Stories for a project, ordered by story_number."""
        if _is_postgres():
            return self._pg_list_for_project(project_key)
        with _sqlite_connect(self._store_dir) as conn:
            cursor = conn.execute(
                "SELECT * FROM stories WHERE project_key = ? ORDER BY story_number",
                (project_key,),
            )
            return [_sqlite_row_to_story(dict(row)) for row in cursor.fetchall()]

    def _pg_list_for_project(self, project_key: str) -> list[Story]:
        with _postgres_connect() as conn:
            cursor = conn.execute(
                "SELECT * FROM stories WHERE project_key = %s ORDER BY story_number",
                (project_key,),
            )
            return [_pg_row_to_story(dict(row)) for row in cursor.fetchall()]

    def search(self, project_key: str, query: str) -> list[Story]:
        """Search Stories by substring across key fields (case-insensitive)."""
        if _is_postgres():
            return self._pg_search(project_key, query)
        q = query.lower()
        with _sqlite_connect(self._store_dir) as conn:
            cursor = conn.execute(
                """
                SELECT * FROM stories
                WHERE project_key = ?
                  AND (
                      LOWER(story_display_id) LIKE ? ESCAPE '!'
                      OR LOWER(title) LIKE ? ESCAPE '!'
                      OR LOWER(module) LIKE ? ESCAPE '!'
                      OR LOWER(epic) LIKE ? ESCAPE '!'
                      OR LOWER(participating_repos_json) LIKE ? ESCAPE '!'
                  )
                ORDER BY story_number
                """,
                (
                    project_key,
                    f"%{q}%",
                    f"%{q}%",
                    f"%{q}%",
                    f"%{q}%",
                    f"%{q}%",
                ),
            )
            return [_sqlite_row_to_story(dict(row)) for row in cursor.fetchall()]

    def _pg_search(self, project_key: str, query: str) -> list[Story]:
        q = f"%{query.lower()}%"
        with _postgres_connect() as conn:
            cursor = conn.execute(
                """
                SELECT * FROM stories
                WHERE project_key = %s
                  AND (
                      LOWER(story_display_id) LIKE %s
                      OR LOWER(title) LIKE %s
                      OR LOWER(module) LIKE %s
                      OR LOWER(epic) LIKE %s
                      OR LOWER(participating_repos::text) LIKE %s
                  )
                ORDER BY story_number
                """,
                (project_key, q, q, q, q, q),
            )
            return [_pg_row_to_story(dict(row)) for row in cursor.fetchall()]

    # ------------------------------------------------------------------
    # Save (story and spec)
    # ------------------------------------------------------------------

    def save(self, story: Story) -> None:
        """Persist (insert or update) one Story using UPSERT."""
        if _is_postgres():
            self._pg_save_story(story)
            return
        row = _story_to_sqlite_row(story)
        with _sqlite_connect(self._store_dir) as conn:
            _sqlite_upsert_story(conn, row)

    def _pg_save_story(self, story: Story) -> None:
        row = _story_to_pg_row(story)
        with _postgres_connect() as conn:
            _pg_upsert_story(conn, row)

    def get_specification(self, story_uuid: UUID) -> StorySpecification | None:
        """Load the specification for a Story."""
        if _is_postgres():
            return self._pg_get_specification(story_uuid)
        with _sqlite_connect(self._store_dir) as conn:
            cursor = conn.execute(
                "SELECT * FROM story_specifications WHERE story_uuid = ?",
                (str(story_uuid),),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return _sqlite_row_to_spec(dict(row))

    def _pg_get_specification(self, story_uuid: UUID) -> StorySpecification | None:
        with _postgres_connect() as conn:
            cursor = conn.execute(
                "SELECT * FROM story_specifications WHERE story_uuid = %s",
                (str(story_uuid),),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return _pg_row_to_spec(dict(row))

    def save_specification(
        self,
        story_uuid: UUID,
        spec: StorySpecification,
    ) -> None:
        """Persist (insert or update) one StorySpecification."""
        if _is_postgres():
            self._pg_save_specification(story_uuid, spec)
            return
        row = _sqlite_spec_to_row(story_uuid, spec)
        with _sqlite_connect(self._store_dir) as conn:
            _sqlite_upsert_spec(conn, row)

    def _pg_save_specification(
        self,
        story_uuid: UUID,
        spec: StorySpecification,
    ) -> None:
        row = _pg_spec_to_row(story_uuid, spec)
        with _postgres_connect() as conn:
            _pg_upsert_spec(conn, row)

    # ------------------------------------------------------------------
    # Atomic story creation (Befund 6)
    # ------------------------------------------------------------------

    def create_story_atomic(
        self,
        story: Story,
        spec: StorySpecification,
        *,
        story_id_prefix: str,
    ) -> None:
        """Atomically allocate a story number and persist story + spec.

        Allocates the next story number, sets ``story.story_number``
        and ``story.story_display_id`` on the caller's Story object,
        then persists the Story and StorySpecification within a single
        database transaction.

        For SQLite: wraps all writes inside BEGIN IMMEDIATE so that
        concurrent creations cannot race on the same story number.

        For Postgres: wraps all writes inside a single connection commit;
        the ``story_number`` UNIQUE constraint serialises concurrent inserts.

        This guarantees that either both story + spec succeed or neither
        does (Befund 6 — atomicity). Request-level idempotency is handled
        by the caller's unified in-flight idempotency guard (AG3-140), not
        by this persistence method.

        Args:
            story: The Story entity to persist. ``story_number`` and
                ``story_display_id`` are mutated in-place by this method.
            spec: The StorySpecification to persist.
            story_id_prefix: Project story-ID prefix (e.g. ``"AK3"``).
                Used to build ``story_display_id`` from the allocated number.
        """
        if _is_postgres():
            self._pg_create_story_atomic(story, spec, story_id_prefix=story_id_prefix)
            return
        self._sqlite_create_story_atomic(story, spec, story_id_prefix=story_id_prefix)

    def _sqlite_create_story_atomic(
        self,
        story: Story,
        spec: StorySpecification,
        *,
        story_id_prefix: str,
    ) -> None:
        """SQLite-specific atomic story creation within BEGIN IMMEDIATE."""
        with _sqlite_connect(self._store_dir) as conn:
            conn.execute("BEGIN IMMEDIATE")
            story_number = _sqlite_allocate_story_number(conn, story.project_key)
            # Patch story_number and story_display_id in-place (mutable model).
            # FK-02 §2.11.2: display-ID materialized via the single formatter.
            story.story_number = story_number
            story.story_display_id = format_story_display_id(
                story_id_prefix, story_number
            )
            _sqlite_upsert_story(conn, _story_to_sqlite_row(story))
            _sqlite_upsert_spec(conn, _sqlite_spec_to_row(story.story_uuid, spec))

    def _pg_create_story_atomic(
        self,
        story: Story,
        spec: StorySpecification,
        *,
        story_id_prefix: str,
    ) -> None:
        """Postgres-specific atomic story creation."""
        with _postgres_connect() as conn:
            story_number = _pg_allocate_story_number(conn, story.project_key)
            story.story_number = story_number
            story.story_display_id = format_story_display_id(
                story_id_prefix, story_number
            )
            _pg_upsert_story(conn, _story_to_pg_row(story))
            _pg_upsert_spec(conn, _pg_spec_to_row(story.story_uuid, spec))


# ---------------------------------------------------------------------------
# Shared SQL helpers (avoid code duplication between classes)
# ---------------------------------------------------------------------------


def _sqlite_allocate_story_number(
    conn: sqlite3.Connection, project_key: str
) -> int:
    """Allocate the next story number within an already-open SQLite connection."""
    cursor = conn.execute(
        "SELECT next_story_number FROM story_number_counters WHERE project_key = ?",
        (project_key,),
    )
    row = cursor.fetchone()
    if row is None:
        max_cursor = conn.execute(
            "SELECT MAX(story_number) FROM stories WHERE project_key = ?",
            (project_key,),
        )
        max_row = max_cursor.fetchone()
        existing_max = int(max_row[0]) if max_row and max_row[0] else 0
        next_n = existing_max + 1
        conn.execute(
            "INSERT INTO story_number_counters (project_key, next_story_number) "
            "VALUES (?, ?)",
            (project_key, next_n + 1),
        )
    else:
        next_n = int(row[0])
        conn.execute(
            "UPDATE story_number_counters SET next_story_number = ? "
            "WHERE project_key = ?",
            (next_n + 1, project_key),
        )
    return next_n


def _pg_allocate_story_number(conn: Any, project_key: str) -> int:
    """Allocate the next story number within an already-open Postgres connection."""
    cursor = conn.execute(
        "SELECT next_story_number FROM story_number_counters "
        "WHERE project_key = %s FOR UPDATE",
        (project_key,),
    )
    row = cursor.fetchone()
    if row is None:
        max_cursor = conn.execute(
            "SELECT COALESCE(MAX(story_number), 0) AS m FROM stories "
            "WHERE project_key = %s",
            (project_key,),
        )
        max_row = max_cursor.fetchone()
        existing_max = int(max_row["m"]) if max_row else 0
        next_n = existing_max + 1
        conn.execute(
            "INSERT INTO story_number_counters (project_key, next_story_number) "
            "VALUES (%s, %s)",
            (project_key, next_n + 1),
        )
    else:
        next_n = int(row["next_story_number"])
        conn.execute(
            "UPDATE story_number_counters SET next_story_number = %s "
            "WHERE project_key = %s",
            (next_n + 1, project_key),
        )
    return next_n


def _sqlite_upsert_story(
    conn: sqlite3.Connection, row: dict[str, object]
) -> None:
    conn.execute(
        """
        INSERT INTO stories (
            story_uuid, project_key, story_number, story_display_id,
            title, story_type, status, size, mode, epic, module,
            participating_repos_json, change_impact, concept_quality,
            owner, risk, blocker, labels_json, wave, critical_path,
            new_structures, vectordb_conflict_resolved,
            split_from, split_successors_json, created_at, completed_at
        ) VALUES (
            :story_uuid, :project_key, :story_number, :story_display_id,
            :title, :story_type, :status, :size, :mode, :epic, :module,
            :participating_repos_json, :change_impact, :concept_quality,
            :owner, :risk, :blocker, :labels_json, :wave, :critical_path,
            :new_structures, :vectordb_conflict_resolved,
            :split_from, :split_successors_json, :created_at, :completed_at
        )
        ON CONFLICT(story_uuid) DO UPDATE SET
            title = excluded.title,
            story_type = excluded.story_type,
            status = excluded.status,
            size = excluded.size,
            mode = excluded.mode,
            epic = excluded.epic,
            module = excluded.module,
            participating_repos_json = excluded.participating_repos_json,
            change_impact = excluded.change_impact,
            concept_quality = excluded.concept_quality,
            owner = excluded.owner,
            risk = excluded.risk,
            blocker = excluded.blocker,
            labels_json = excluded.labels_json,
            wave = excluded.wave,
            critical_path = excluded.critical_path,
            new_structures = excluded.new_structures,
            vectordb_conflict_resolved = excluded.vectordb_conflict_resolved,
            split_from = excluded.split_from,
            split_successors_json = excluded.split_successors_json,
            created_at = excluded.created_at,
            completed_at = excluded.completed_at
        """,
        row,
    )


def _pg_upsert_story(conn: Any, row: dict[str, object]) -> None:
    conn.execute(
        """
        INSERT INTO stories (
            story_uuid, project_key, story_number, story_display_id,
            title, story_type, status, size, mode, epic, module,
            participating_repos, change_impact, concept_quality,
            owner, risk, blocker, labels, wave, critical_path,
            new_structures, vectordb_conflict_resolved,
            split_from, split_successors, created_at, completed_at
        ) VALUES (
            %(story_uuid)s, %(project_key)s, %(story_number)s,
            %(story_display_id)s, %(title)s, %(story_type)s, %(status)s,
            %(size)s, %(mode)s, %(epic)s, %(module)s,
            %(participating_repos)s::jsonb, %(change_impact)s,
            %(concept_quality)s, %(owner)s, %(risk)s, %(blocker)s,
            %(labels)s::jsonb, %(wave)s, %(critical_path)s,
            %(new_structures)s, %(vectordb_conflict_resolved)s,
            %(split_from)s, %(split_successors)s::jsonb,
            %(created_at)s, %(completed_at)s
        )
        ON CONFLICT(story_uuid) DO UPDATE SET
            title = EXCLUDED.title,
            story_type = EXCLUDED.story_type,
            status = EXCLUDED.status,
            size = EXCLUDED.size,
            mode = EXCLUDED.mode,
            epic = EXCLUDED.epic,
            module = EXCLUDED.module,
            participating_repos = EXCLUDED.participating_repos,
            change_impact = EXCLUDED.change_impact,
            concept_quality = EXCLUDED.concept_quality,
            owner = EXCLUDED.owner,
            risk = EXCLUDED.risk,
            blocker = EXCLUDED.blocker,
            labels = EXCLUDED.labels,
            wave = EXCLUDED.wave,
            critical_path = EXCLUDED.critical_path,
            new_structures = EXCLUDED.new_structures,
            vectordb_conflict_resolved = EXCLUDED.vectordb_conflict_resolved,
            split_from = EXCLUDED.split_from,
            split_successors = EXCLUDED.split_successors,
            created_at = EXCLUDED.created_at,
            completed_at = EXCLUDED.completed_at
        """,
        {
            **row,
            "participating_repos": json.dumps(row["participating_repos"]),
            "labels": json.dumps(row["labels"]),
            "split_successors": json.dumps(row["split_successors"]),
        },
    )


def _sqlite_upsert_spec(
    conn: sqlite3.Connection, row: dict[str, object]
) -> None:
    conn.execute(
        """
        INSERT INTO story_specifications (
            story_uuid, need, solution, acceptance_json,
            definition_of_done_json, concept_refs_json,
            guardrail_refs_json, external_sources_json
        ) VALUES (
            :story_uuid, :need, :solution, :acceptance_json,
            :definition_of_done_json, :concept_refs_json,
            :guardrail_refs_json, :external_sources_json
        )
        ON CONFLICT(story_uuid) DO UPDATE SET
            need = excluded.need,
            solution = excluded.solution,
            acceptance_json = excluded.acceptance_json,
            definition_of_done_json = excluded.definition_of_done_json,
            concept_refs_json = excluded.concept_refs_json,
            guardrail_refs_json = excluded.guardrail_refs_json,
            external_sources_json = excluded.external_sources_json
        """,
        row,
    )


def _pg_upsert_spec(conn: Any, row: dict[str, object]) -> None:
    conn.execute(
        """
        INSERT INTO story_specifications (
            story_uuid, need, solution, acceptance,
            definition_of_done, concept_refs,
            guardrail_refs, external_sources
        ) VALUES (
            %(story_uuid)s, %(need)s, %(solution)s, %(acceptance)s::jsonb,
            %(definition_of_done)s::jsonb, %(concept_refs)s::jsonb,
            %(guardrail_refs)s::jsonb, %(external_sources)s::jsonb
        )
        ON CONFLICT(story_uuid) DO UPDATE SET
            need = EXCLUDED.need,
            solution = EXCLUDED.solution,
            acceptance = EXCLUDED.acceptance,
            definition_of_done = EXCLUDED.definition_of_done,
            concept_refs = EXCLUDED.concept_refs,
            guardrail_refs = EXCLUDED.guardrail_refs,
            external_sources = EXCLUDED.external_sources
        """,
        {
            **row,
            "acceptance": json.dumps(row["acceptance"]),
            "definition_of_done": json.dumps(row["definition_of_done"])
            if row.get("definition_of_done") is not None
            else None,
            "concept_refs": json.dumps(row["concept_refs"])
            if row.get("concept_refs") is not None
            else None,
            "guardrail_refs": json.dumps(row["guardrail_refs"])
            if row.get("guardrail_refs") is not None
            else None,
            "external_sources": json.dumps(row["external_sources"])
            if row.get("external_sources") is not None
            else None,
        },
    )
