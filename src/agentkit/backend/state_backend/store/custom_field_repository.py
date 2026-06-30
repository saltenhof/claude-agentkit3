"""Story custom field persistence repository."""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agentkit.backend.story_context_manager.custom_fields import (
    ProviderSyncStatus,
    StoryCustomFieldDefinition,
    StoryCustomFieldSource,
    StoryCustomFieldType,
    StoryCustomFieldValue,
    StoryCustomFieldValueStatus,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

_AGENTKIT_OWNER = "agentkit"


class StoryCustomFieldWriteRejectedError(RuntimeError):
    """Raised when the AgentKit single-writer bar rejects a custom-field write."""


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
        conn.execute("PRAGMA foreign_keys = ON")
        sqlite_store._ensure_schema(conn)
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _postgres_database_url() -> str:
    url = os.environ.get("AGENTKIT_STATE_DATABASE_URL", "")
    if not url:
        raise RuntimeError(
            "AGENTKIT_STATE_DATABASE_URL must be set when "
            "AGENTKIT_STATE_BACKEND=postgres"
        )
    return url


@contextmanager
def _postgres_connect() -> Iterator[Any]:
    import psycopg
    from psycopg.rows import dict_row

    from agentkit.backend.state_backend.schema_bootstrap import ensure_versioned_schema

    conn = psycopg.connect(_postgres_database_url(), row_factory=dict_row)
    try:
        ensure_versioned_schema(conn)
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


class StoryCustomFieldRepository:
    """SQLite/Postgres-backed custom-field definition/value repository."""

    # SQL statements are class-level to keep module top-level LOC within budget.
    _SQLITE_DEFINITION_UPSERT: str = """
    INSERT INTO story_custom_field_definitions (
        project_key, field_key, display_name, field_type, provider,
        provider_field_ref, is_required, is_writable_by_agentkit, allowed_values
    ) VALUES (
        :project_key, :field_key, :display_name, :field_type, :provider,
        :provider_field_ref, :is_required, :is_writable_by_agentkit,
        :allowed_values
    )
    ON CONFLICT (project_key, field_key) DO UPDATE SET
        display_name=excluded.display_name,
        field_type=excluded.field_type,
        provider=excluded.provider,
        provider_field_ref=excluded.provider_field_ref,
        is_required=excluded.is_required,
        is_writable_by_agentkit=excluded.is_writable_by_agentkit,
        allowed_values=excluded.allowed_values
"""
    _PG_DEFINITION_UPSERT: str = """
    INSERT INTO story_custom_field_definitions (
        project_key, field_key, display_name, field_type, provider,
        provider_field_ref, is_required, is_writable_by_agentkit, allowed_values
    ) VALUES (
        %(project_key)s, %(field_key)s, %(display_name)s, %(field_type)s,
        %(provider)s, %(provider_field_ref)s, %(is_required)s,
        %(is_writable_by_agentkit)s, CAST(%(allowed_values)s AS jsonb)
    )
    ON CONFLICT (project_key, field_key) DO UPDATE SET
        display_name=excluded.display_name,
        field_type=excluded.field_type,
        provider=excluded.provider,
        provider_field_ref=excluded.provider_field_ref,
        is_required=excluded.is_required,
        is_writable_by_agentkit=excluded.is_writable_by_agentkit,
        allowed_values=excluded.allowed_values
"""
    _SQLITE_DEFINITION_SELECT: str = """
    SELECT * FROM story_custom_field_definitions
    WHERE project_key=:project_key AND field_key=:field_key
"""
    _PG_DEFINITION_SELECT: str = """
    SELECT * FROM story_custom_field_definitions
    WHERE project_key=%(project_key)s AND field_key=%(field_key)s
"""
    _SQLITE_VALUE_UPSERT: str = """
    INSERT INTO story_custom_field_values (
        project_key, story_id, field_key, value, value_status, source,
        last_synced_at, last_written_by, provider_sync_status, conflict_detected,
        last_sync_attempt_at
    ) VALUES (
        :project_key, :story_id, :field_key, :value, :value_status, :source,
        :last_synced_at, :last_written_by, :provider_sync_status,
        :conflict_detected, :last_sync_attempt_at
    )
    ON CONFLICT (project_key, story_id, field_key) DO UPDATE SET
        value=excluded.value,
        value_status=excluded.value_status,
        source=excluded.source,
        last_synced_at=excluded.last_synced_at,
        last_written_by=excluded.last_written_by,
        provider_sync_status=excluded.provider_sync_status,
        conflict_detected=excluded.conflict_detected,
        last_sync_attempt_at=excluded.last_sync_attempt_at
"""
    _PG_VALUE_UPSERT: str = """
    INSERT INTO story_custom_field_values (
        project_key, story_id, field_key, value, value_status, source,
        last_synced_at, last_written_by, provider_sync_status, conflict_detected,
        last_sync_attempt_at
    ) VALUES (
        %(project_key)s, %(story_id)s, %(field_key)s, %(value)s,
        %(value_status)s, %(source)s, %(last_synced_at)s, %(last_written_by)s,
        %(provider_sync_status)s, %(conflict_detected)s, %(last_sync_attempt_at)s
    )
    ON CONFLICT (project_key, story_id, field_key) DO UPDATE SET
        value=excluded.value,
        value_status=excluded.value_status,
        source=excluded.source,
        last_synced_at=excluded.last_synced_at,
        last_written_by=excluded.last_written_by,
        provider_sync_status=excluded.provider_sync_status,
        conflict_detected=excluded.conflict_detected,
        last_sync_attempt_at=excluded.last_sync_attempt_at
"""
    _SQLITE_VALUE_SELECT: str = """
    SELECT * FROM story_custom_field_values
    WHERE project_key=:project_key AND story_id=:story_id AND field_key=:field_key
"""
    _PG_VALUE_SELECT: str = """
    SELECT * FROM story_custom_field_values
    WHERE project_key=%(project_key)s AND story_id=%(story_id)s
      AND field_key=%(field_key)s
"""

    def __init__(self, store_dir: Path | None = None) -> None:
        self._store_dir = store_dir or Path.cwd()

    def save_definition(self, definition: StoryCustomFieldDefinition) -> None:
        """Upsert one custom field definition."""
        if _is_postgres():
            with _postgres_connect() as conn:
                conn.execute(self._PG_DEFINITION_UPSERT, _definition_row(definition))
            return
        with _sqlite_connect(self._store_dir) as conn:
            conn.execute(self._SQLITE_DEFINITION_UPSERT, _definition_row(definition))

    def get_definition(
        self,
        project_key: str,
        field_key: str,
    ) -> StoryCustomFieldDefinition | None:
        """Return a custom field definition, if present."""
        params = {"project_key": project_key, "field_key": field_key}
        if _is_postgres():
            with _postgres_connect() as conn:
                row = conn.execute(self._PG_DEFINITION_SELECT, params).fetchone()
        else:
            with _sqlite_connect(self._store_dir) as conn:
                row = conn.execute(self._SQLITE_DEFINITION_SELECT, params).fetchone()
        return None if row is None else _definition_from_row(dict(row))

    def save_value(self, value: StoryCustomFieldValue) -> None:
        """Upsert one custom field value without changing ownership rules."""
        if _is_postgres():
            with _postgres_connect() as conn:
                conn.execute(self._PG_VALUE_UPSERT, _value_row(value))
            return
        with _sqlite_connect(self._store_dir) as conn:
            conn.execute(self._SQLITE_VALUE_UPSERT, _value_row(value))

    def write_agentkit_value(self, value: StoryCustomFieldValue) -> None:
        """Write a value through the AgentKit single-writer bar."""
        definition = self.get_definition(value.project_key, value.field_key)
        if definition is None or not definition.is_writable_by_agentkit:
            raise StoryCustomFieldWriteRejectedError(
                "field is not writable by AgentKit"
            )
        existing = self.get_value(value.project_key, value.story_id, value.field_key)
        if existing is not None and existing.conflict_detected:
            raise StoryCustomFieldWriteRejectedError("field has a provider conflict")
        if (
            existing is not None
            and existing.last_written_by is not None
            and existing.last_written_by != _AGENTKIT_OWNER
        ):
            raise StoryCustomFieldWriteRejectedError(
                "field is owned by a foreign writer"
            )
        self.save_value(
            StoryCustomFieldValue(
                project_key=value.project_key,
                story_id=value.story_id,
                field_key=value.field_key,
                value=value.value,
                value_status=value.value_status,
                source=StoryCustomFieldSource.AGENTKIT,
                last_synced_at=value.last_synced_at,
                last_written_by=_AGENTKIT_OWNER,
                provider_sync_status=value.provider_sync_status,
                conflict_detected=value.conflict_detected,
                last_sync_attempt_at=value.last_sync_attempt_at,
            )
        )

    def get_value(
        self,
        project_key: str,
        story_id: str,
        field_key: str,
    ) -> StoryCustomFieldValue | None:
        """Return a custom field value, if present."""
        params = {
            "project_key": project_key,
            "story_id": story_id,
            "field_key": field_key,
        }
        if _is_postgres():
            with _postgres_connect() as conn:
                row = conn.execute(self._PG_VALUE_SELECT, params).fetchone()
        else:
            with _sqlite_connect(self._store_dir) as conn:
                row = conn.execute(self._SQLITE_VALUE_SELECT, params).fetchone()
        return None if row is None else _value_from_row(dict(row))



def _definition_row(definition: StoryCustomFieldDefinition) -> dict[str, object]:
    return {
        "project_key": definition.project_key,
        "field_key": definition.field_key,
        "display_name": definition.display_name,
        "field_type": definition.field_type.value,
        "provider": definition.provider,
        "provider_field_ref": definition.provider_field_ref,
        "is_required": int(definition.is_required),
        "is_writable_by_agentkit": int(definition.is_writable_by_agentkit),
        "allowed_values": json.dumps(list(definition.allowed_values)),
    }


def _definition_from_row(row: dict[str, Any]) -> StoryCustomFieldDefinition:
    return StoryCustomFieldDefinition(
        project_key=str(row["project_key"]),
        field_key=str(row["field_key"]),
        display_name=str(row["display_name"]),
        field_type=StoryCustomFieldType(str(row["field_type"])),
        provider=str(row["provider"]),
        provider_field_ref=str(row["provider_field_ref"]),
        is_required=bool(row["is_required"]),
        is_writable_by_agentkit=bool(row["is_writable_by_agentkit"]),
        allowed_values=_json_string_tuple(row["allowed_values"]),
    )


def _value_row(value: StoryCustomFieldValue) -> dict[str, object]:
    return {
        "project_key": value.project_key,
        "story_id": value.story_id,
        "field_key": value.field_key,
        "value": value.value,
        "value_status": value.value_status.value,
        "source": value.source.value,
        "last_synced_at": _dt_to_str(value.last_synced_at),
        "last_written_by": value.last_written_by,
        "provider_sync_status": value.provider_sync_status.value,
        "conflict_detected": int(value.conflict_detected),
        "last_sync_attempt_at": _dt_to_str(value.last_sync_attempt_at),
    }


def _value_from_row(row: dict[str, Any]) -> StoryCustomFieldValue:
    return StoryCustomFieldValue(
        project_key=str(row["project_key"]),
        story_id=str(row["story_id"]),
        field_key=str(row["field_key"]),
        value=str(row["value"]),
        value_status=StoryCustomFieldValueStatus(str(row["value_status"])),
        source=StoryCustomFieldSource(str(row["source"])),
        last_synced_at=_dt_from_value(row.get("last_synced_at")),
        last_written_by=_optional_str(row.get("last_written_by")),
        provider_sync_status=ProviderSyncStatus(str(row["provider_sync_status"])),
        conflict_detected=bool(row["conflict_detected"]),
        last_sync_attempt_at=_dt_from_value(row.get("last_sync_attempt_at")),
    )


def _dt_to_str(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def _dt_from_value(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value)
    return None


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _json_string_tuple(value: object) -> tuple[str, ...]:
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return tuple(value)
    loaded = json.loads(str(value))
    if isinstance(loaded, list) and all(isinstance(item, str) for item in loaded):
        return tuple(loaded)
    raise ValueError("allowed_values must be a JSON array of strings")


__all__ = [
    "StoryCustomFieldRepository",
    "StoryCustomFieldWriteRejectedError",
]
