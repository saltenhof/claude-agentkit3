"""State-backend repository for Story stammdaten (story_context_manager BC).

This is the SQLite/Postgres-backed implementation of ``StoryRepository``
(``story_context_manager.story_repository.StoryRepository`` Protocol).

Architecture Conformance AC003/AC004:
  - Does NOT import or use the generic ``state_backend.store.facade``.
  - Accesses the database directly via the sqlite_store / postgres_store
    drivers (raw connection pattern).
  - The ``stories``, ``story_specifications``, and ``idempotency_keys``
    tables were added in schema 3.3.0 (side-by-side, additive).

Design:
  - SQLite: uses ``_sqlite_connect`` (versioned .sqlite file).
  - Postgres: uses ``_postgres_connect`` (psycopg, DSN from env var).
  - Column naming differs between backends:
    - SQLite: ``participating_repos_json``, ``labels_json``, etc. (TEXT)
    - Postgres: ``participating_repos``, ``labels``, etc. (JSONB)
  - ``create_story_atomic`` wraps number allocation + story + spec +
    idempotency save in a single database transaction (Befund 6).

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

from agentkit.core_types import StorySize
from agentkit.story_context_manager.idempotency import IdempotencyRecord
from agentkit.story_context_manager.story_model import (
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


def _postgres_database_url() -> str:
    url = os.environ.get("AGENTKIT_STATE_DATABASE_URL", "")
    if not url:
        raise RuntimeError(
            "AGENTKIT_STATE_DATABASE_URL must be set when "
            "AGENTKIT_STATE_BACKEND=postgres"
        )
    return url


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
    from agentkit.state_backend.config import versioned_sqlite_db_file
    from agentkit.state_backend.paths import state_backend_dir

    return state_backend_dir(store_dir) / versioned_sqlite_db_file()


@contextmanager
def _sqlite_connect(store_dir: Path) -> Iterator[sqlite3.Connection]:
    db_path = _sqlite_db_path(store_dir)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    # Ensure the stories tables exist (additive, idempotent)
    _ensure_story_tables_sqlite(conn)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _ensure_story_tables_sqlite(conn: sqlite3.Connection) -> None:
    """Create the story stammdaten tables if they don't exist yet.

    These tables were added in schema 3.3.0 (side-by-side, additive).
    """
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
            created_at TEXT,
            completed_at TEXT,
            PRIMARY KEY (story_uuid),
            UNIQUE (story_display_id),
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

        CREATE TABLE IF NOT EXISTS idempotency_keys (
            op_id TEXT NOT NULL,
            body_hash TEXT NOT NULL,
            result_payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            correlation_id TEXT NOT NULL,
            PRIMARY KEY (op_id)
        );
        """
    )


# ---------------------------------------------------------------------------
# Postgres connection helper
# ---------------------------------------------------------------------------


@contextmanager
def _postgres_connect() -> Iterator[Any]:
    """Open a psycopg connection with dict_row factory and versioned schema."""
    import psycopg
    from psycopg.rows import dict_row

    from agentkit.state_backend.config import versioned_postgres_schema_name

    schema = versioned_postgres_schema_name()
    conn = psycopg.connect(_postgres_database_url(), row_factory=dict_row)
    try:
        conn.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
        conn.execute(f"SET search_path TO {schema}, public")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


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
    # Number allocation (within open transaction for atomic create)
    # ------------------------------------------------------------------

    def allocate_next_story_number(self, project_key: str) -> int:
        """Atomically allocate the next story number for a project.

        SQLite: uses BEGIN IMMEDIATE to prevent concurrent writes.
        Postgres: relies on the caller holding an exclusive transaction
          (used inside ``create_story_atomic``).
        """
        if _is_postgres():
            return self._pg_allocate_next_story_number(project_key)
        with _sqlite_connect(self._store_dir) as conn:
            # Use BEGIN IMMEDIATE to get exclusive write access
            conn.execute("BEGIN IMMEDIATE")
            return _sqlite_allocate_story_number(conn, project_key)

    def _pg_allocate_next_story_number(self, project_key: str) -> int:
        with _postgres_connect() as conn:
            return _pg_allocate_story_number(conn, project_key)

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
        does (Befund 6 — atomicity). Idempotency is persisted by the
        caller after this call returns (INSERT-OR-IGNORE is inherently
        race-safe and does not need to be in the same transaction).

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
            # Patch story_number and story_display_id in-place (mutable model)
            story.story_number = story_number
            story.story_display_id = f"{story_id_prefix}-{story_number}"
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
            story.story_display_id = f"{story_id_prefix}-{story_number}"
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
            created_at, completed_at
        ) VALUES (
            :story_uuid, :project_key, :story_number, :story_display_id,
            :title, :story_type, :status, :size, :mode, :epic, :module,
            :participating_repos_json, :change_impact, :concept_quality,
            :owner, :risk, :blocker, :labels_json, :wave, :critical_path,
            :created_at, :completed_at
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
            created_at, completed_at
        ) VALUES (
            %(story_uuid)s, %(project_key)s, %(story_number)s,
            %(story_display_id)s, %(title)s, %(story_type)s, %(status)s,
            %(size)s, %(mode)s, %(epic)s, %(module)s,
            %(participating_repos)s::jsonb, %(change_impact)s,
            %(concept_quality)s, %(owner)s, %(risk)s, %(blocker)s,
            %(labels)s::jsonb, %(wave)s, %(critical_path)s,
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
            created_at = EXCLUDED.created_at,
            completed_at = EXCLUDED.completed_at
        """,
        {
            **row,
            "participating_repos": json.dumps(row["participating_repos"]),
            "labels": json.dumps(row["labels"]),
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


def _sqlite_insert_idempotency(
    conn: sqlite3.Connection, record: IdempotencyRecord
) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO idempotency_keys
            (op_id, body_hash, result_payload_json, created_at, correlation_id)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            record.op_id,
            record.body_hash,
            _dump(record.result_payload),
            record.created_at.isoformat(),
            record.correlation_id,
        ),
    )


def _pg_insert_idempotency(conn: Any, record: IdempotencyRecord) -> None:
    conn.execute(
        """
        INSERT INTO idempotency_keys
            (op_id, body_hash, result_payload, created_at, correlation_id)
        VALUES (%s, %s, %s::jsonb, %s, %s)
        ON CONFLICT(op_id) DO NOTHING
        """,
        (
            record.op_id,
            record.body_hash,
            json.dumps(record.result_payload),
            record.created_at.isoformat(),
            record.correlation_id,
        ),
    )


# ---------------------------------------------------------------------------
# Idempotency key persistence (StateBackend)
# ---------------------------------------------------------------------------


class StateBackendIdempotencyKeyRepository:
    """SQLite/Postgres-backed idempotency key repository (FK-91 §91.1a Rule 5).

    Stores op_id -> body_hash + result_payload in the ``idempotency_keys``
    table (schema 3.3.0).

    Args:
        store_dir: Base directory for the state store.
            Used only for the SQLite backend. Defaults to cwd.
    """

    def __init__(self, store_dir: Path | None = None) -> None:
        self._store_dir: Path = store_dir or Path.cwd()

    def get(self, op_id: str) -> _IdempotencyRowRecord | None:
        """Load an existing idempotency record by op_id."""
        if _is_postgres():
            return self._pg_get(op_id)
        with _sqlite_connect(self._store_dir) as conn:
            cursor = conn.execute(
                "SELECT * FROM idempotency_keys WHERE op_id = ?",
                (op_id,),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return _IdempotencyRowRecord(
                op_id=str(row["op_id"]),
                body_hash=str(row["body_hash"]),
                result_payload=json.loads(str(row["result_payload_json"])),
                created_at=datetime.fromisoformat(str(row["created_at"])),
                correlation_id=str(row["correlation_id"]),
            )

    def _pg_get(self, op_id: str) -> _IdempotencyRowRecord | None:
        with _postgres_connect() as conn:
            cursor = conn.execute(
                "SELECT op_id, body_hash, result_payload, "
                "created_at, correlation_id "
                "FROM idempotency_keys WHERE op_id = %s",
                (op_id,),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            payload = row["result_payload"]
            if isinstance(payload, str):
                payload = json.loads(payload)
            created = row["created_at"]
            if isinstance(created, str):
                created = datetime.fromisoformat(created)
            return _IdempotencyRowRecord(
                op_id=str(row["op_id"]),
                body_hash=str(row["body_hash"]),
                result_payload=payload,
                created_at=created,
                correlation_id=str(row["correlation_id"]),
            )

    def save(self, record: IdempotencyRecord) -> None:
        """Persist a new idempotency record (first write wins)."""
        if _is_postgres():
            self._pg_save(record)
            return
        with _sqlite_connect(self._store_dir) as conn:
            _sqlite_insert_idempotency(conn, record)

    def _pg_save(self, record: IdempotencyRecord) -> None:
        with _postgres_connect() as conn:
            _pg_insert_idempotency(conn, record)


class _IdempotencyRowRecord(IdempotencyRecord):
    """DB-row representation of an idempotency record.

    Subclasses ``IdempotencyRecord`` from ``story_context_manager.idempotency``
    so that ``StateBackendIdempotencyKeyRepository`` satisfies the
    ``IdempotencyKeyRepository`` Protocol (nominal subtyping).
    """
