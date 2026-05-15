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
  - SQLite: uses ``_connect`` from sqlite_store via the ``_db_path()``
    helper which resolves the versioned .sqlite file.
  - Postgres: uses a bare ``psycopg2`` connection from DSN env var.
  - Both share the same SQL surface (paramstyle differences are bridged
    with positional ``?`` for SQLite and ``%s`` for Postgres).

Story stammdaten persistence is global (project-scoped), not per-story-dir.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID

from agentkit.story_context_manager.story_model import (
    ChangeImpact,
    ConceptQuality,
    RiskLevel,
    Story,
    StorySpecification,
    StoryStatus,
    WireStoryMode,
    WireStorySize,
    WireStoryType,
)

if TYPE_CHECKING:
    from collections.abc import Iterator


# ---------------------------------------------------------------------------
# Helpers: JSON serialization
# ---------------------------------------------------------------------------


def _dump(value: object) -> str:
    return json.dumps(value, sort_keys=True, default=str)


def _load(raw: str | None, default: Any) -> Any:
    if raw is None:
        return default
    return json.loads(raw)


# ---------------------------------------------------------------------------
# Row <-> Story conversion
# ---------------------------------------------------------------------------


def _story_to_row(story: Story) -> dict[str, object]:
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


def _row_to_story(row: dict[str, Any]) -> Story:
    return Story(
        story_uuid=UUID(str(row["story_uuid"])),
        project_key=str(row["project_key"]),
        story_number=int(row["story_number"]),
        story_display_id=str(row["story_display_id"]),
        title=str(row["title"]),
        story_type=WireStoryType(str(row["story_type"])),
        status=StoryStatus(str(row["status"])),
        size=WireStorySize(str(row["size"])),
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


def _spec_to_row(story_uuid: UUID, spec: StorySpecification) -> dict[str, object]:
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


def _row_to_spec(row: dict[str, Any]) -> StorySpecification:
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
# SQLite implementation
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


class StateBackendStoryRepository:
    """SQLite/Postgres-backed implementation of StoryRepository Protocol.

    Architecture Conformance: does NOT use ``state_backend.store.facade``.
    This is an explicit, component-specific repository (AC003/AC004).

    Args:
        store_dir: Base directory for the state store (contains ``.agentkit/``).
            When ``None``, defaults to the current working directory.
    """

    def __init__(self, store_dir: Path | None = None) -> None:
        self._store_dir: Path = store_dir or Path.cwd()

    def get_by_display_id(self, story_display_id: str) -> Story | None:
        """Load a Story by its display ID."""
        with _sqlite_connect(self._store_dir) as conn:
            cursor = conn.execute(
                "SELECT * FROM stories WHERE story_display_id = ?",
                (story_display_id,),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return _row_to_story(dict(row))

    def get_by_uuid(self, story_uuid: UUID) -> Story | None:
        """Load a Story by its technical UUID."""
        with _sqlite_connect(self._store_dir) as conn:
            cursor = conn.execute(
                "SELECT * FROM stories WHERE story_uuid = ?",
                (str(story_uuid),),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return _row_to_story(dict(row))

    def list_for_project(self, project_key: str) -> list[Story]:
        """Return all Stories for a project, ordered by story_number."""
        with _sqlite_connect(self._store_dir) as conn:
            cursor = conn.execute(
                "SELECT * FROM stories WHERE project_key = ? ORDER BY story_number",
                (project_key,),
            )
            return [_row_to_story(dict(row)) for row in cursor.fetchall()]

    def search(self, project_key: str, query: str) -> list[Story]:
        """Search Stories by substring across key fields (case-insensitive)."""
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
            return [_row_to_story(dict(row)) for row in cursor.fetchall()]

    def allocate_next_story_number(self, project_key: str) -> int:
        """Atomically allocate the next story number for a project.

        SQLite: uses BEGIN IMMEDIATE to prevent concurrent writes.
        The counter is stored in ``story_number_counters`` (existing table).
        """
        with _sqlite_connect(self._store_dir) as conn:
            # Use BEGIN IMMEDIATE to get exclusive write access
            conn.execute("BEGIN IMMEDIATE")
            cursor = conn.execute(
                "SELECT next_story_number FROM story_number_counters "
                "WHERE project_key = ?",
                (project_key,),
            )
            row = cursor.fetchone()
            if row is None:
                # First story for this project: seed from MAX in stories table
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

    def save(self, story: Story) -> None:
        """Persist (insert or update) one Story using UPSERT."""
        row = _story_to_row(story)
        with _sqlite_connect(self._store_dir) as conn:
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

    def get_specification(self, story_uuid: UUID) -> StorySpecification | None:
        """Load the specification for a Story."""
        with _sqlite_connect(self._store_dir) as conn:
            cursor = conn.execute(
                "SELECT * FROM story_specifications WHERE story_uuid = ?",
                (str(story_uuid),),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return _row_to_spec(dict(row))

    def save_specification(
        self,
        story_uuid: UUID,
        spec: StorySpecification,
    ) -> None:
        """Persist (insert or update) one StorySpecification."""
        row = _spec_to_row(story_uuid, spec)
        with _sqlite_connect(self._store_dir) as conn:
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


# ---------------------------------------------------------------------------
# Idempotency key persistence (StateBackend)
# ---------------------------------------------------------------------------


class StateBackendIdempotencyKeyRepository:
    """SQLite-backed idempotency key repository (FK-91 §91.1a Rule 5).

    Stores op_id -> body_hash + result_payload in the ``idempotency_keys``
    table (schema 3.3.0). Uses the same versioned SQLite file as the
    story stammdaten.

    Args:
        store_dir: Base directory for the state store.
            When ``None``, defaults to the current working directory.
    """

    def __init__(self, store_dir: Path | None = None) -> None:
        self._store_dir: Path = store_dir or Path.cwd()

    def get(self, op_id: str) -> _IdempotencyRowRecord | None:
        """Load an existing idempotency record by op_id."""
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

    def save(self, record: _IdempotencyRowRecord) -> None:
        """Persist a new idempotency record."""
        with _sqlite_connect(self._store_dir) as conn:
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


class _IdempotencyRowRecord:
    """DB-row representation of an idempotency record.

    Structurally equivalent to ``idempotency.IdempotencyRecord`` but lives
    in state_backend to avoid circular imports. The ``IdempotencyKeyStore``
    wraps this class via its ``IdempotencyKeyRepository`` Protocol.
    """

    __slots__ = ("op_id", "body_hash", "result_payload", "created_at", "correlation_id")

    def __init__(
        self,
        op_id: str,
        body_hash: str,
        result_payload: dict[str, object],
        created_at: datetime,
        correlation_id: str,
    ) -> None:
        self.op_id = op_id
        self.body_hash = body_hash
        self.result_payload = result_payload
        self.created_at = created_at
        self.correlation_id = correlation_id
