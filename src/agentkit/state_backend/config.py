"""Configuration helpers for canonical state backend selection."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from enum import StrEnum

from agentkit.config.sqlite_gate import ALLOW_SQLITE_ENV, sqlite_allowed

STATE_BACKEND_ENV = "AGENTKIT_STATE_BACKEND"
STATE_DATABASE_URL_ENV = "AGENTKIT_STATE_DATABASE_URL"
# AG3-015: 3.6.0 -> 3.7.0 (artifact_class CHECK extended with
# 'prompt_audit'; FK-44 §44.6, AG3-023 §2.1.4 idempotent side-by-side
# migration per FK-18 §18.9a).
# AG3-050: 3.7.0 -> 3.8.0 (story_dependencies FK retargeted from the runtime
# story_contexts projection to the STATIC stories stammdaten identity; FK-02
# §2.11.3, FK-18 §18.6a/§18.13). The endpoints use a COMPOSITE FK
# (project_key, story_id) -> stories(project_key, story_display_id) backed by a
# new UNIQUE (project_key, story_display_id) on stories, so cross-project edges
# fail closed (A3). Idempotent side-by-side migration via the versioned-schema
# pattern (FK-18 §18.9a) — a fresh ak3_v3_8_0 schema / agentkit_3_8_0.sqlite file
# is created; the old FK never coexists. FK violations (dependency on an unknown
# or cross-project story) stay fail-closed.
# AG3-028: 3.8.0 -> 3.9.0 (fc_incidents table added; FK-41 §41.3.1, FK-69. New
# accessor-owned FK-69 projection with CHECK constraints on category (12),
# severity (4 IncidentSeverity values) and incident_status (4 IncidentStatus
# values). Idempotent side-by-side migration via the versioned-schema pattern
# (FK-18 §18.9a) — a fresh ak3_v3_9_0 schema / agentkit_3_9_0.sqlite file is
# created; the old DB is never touched.
SCHEMA_VERSION = "3.9.0"
_SCHEMA_VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")


class StateBackendKind(StrEnum):
    SQLITE = "sqlite"
    POSTGRES = "postgres"


@dataclass(frozen=True)
class StateBackendConfig:
    """Resolved state-backend configuration for the current process."""

    backend: StateBackendKind
    database_url: str | None = None


def _sqlite_allowed() -> bool:
    """Backward-compatible accessor for the config-foundation SQLite gate.

    Defined locally (not a bare import alias) so existing
    ``boundary.state_backend_repository`` modules may keep importing it from
    this driver-config module under mypy's ``no_implicit_reexport``. The single
    source of truth is :func:`agentkit.config.sqlite_gate.sqlite_allowed`.
    """
    return sqlite_allowed()


def load_state_backend_config() -> StateBackendConfig:
    """Resolve backend kind and DSN from the environment."""

    raw_kind = os.environ.get(STATE_BACKEND_ENV, StateBackendKind.POSTGRES.value)
    try:
        backend = StateBackendKind(raw_kind)
    except ValueError as exc:
        raise RuntimeError(
            f"Unsupported {STATE_BACKEND_ENV}={raw_kind!r}; "
            "expected 'postgres' or 'sqlite'"
        ) from exc

    if backend is StateBackendKind.SQLITE and not _sqlite_allowed():
        raise RuntimeError(
            "SQLite backend is disabled for runtime/build/contract/integration/e2e "
            f"paths. Set {ALLOW_SQLITE_ENV}=1 only for narrow unit-test execution.",
        )

    database_url = os.environ.get(STATE_DATABASE_URL_ENV)
    return StateBackendConfig(
        backend=backend,
        database_url=database_url,
    )


def schema_version_slug(version: str | None = None) -> str:
    """Return the storage-safe slug for a SemVer schema version."""

    resolved = version or SCHEMA_VERSION
    if _SCHEMA_VERSION_PATTERN.fullmatch(resolved) is None:
        raise RuntimeError(
            f"Invalid SCHEMA_VERSION={resolved!r}; expected SemVer like '3.0.0'",
        )
    return resolved.replace(".", "_")


def versioned_postgres_schema_name(version: str | None = None) -> str:
    """Return the PostgreSQL schema name for a schema version."""

    return f"ak3_v{schema_version_slug(version)}"


def versioned_sqlite_db_file(version: str | None = None) -> str:
    """Return the SQLite file name for a schema version."""

    return f"agentkit_{schema_version_slug(version)}.sqlite"


__all__ = [
    "STATE_BACKEND_ENV",
    "STATE_DATABASE_URL_ENV",
    "ALLOW_SQLITE_ENV",
    "SCHEMA_VERSION",
    "StateBackendConfig",
    "StateBackendKind",
    "load_state_backend_config",
    "schema_version_slug",
    "versioned_postgres_schema_name",
    "versioned_sqlite_db_file",
]
