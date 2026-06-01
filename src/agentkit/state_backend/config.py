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
# AG3-028 Codex-r1 Remediation 2026-06-01: 3.9.0 -> 3.10.0 (fc_incidents
# realigned to FK-41 §41.3.1 — project_key NOT NULL, incident_id FC-YYYY-NNNN,
# run_id NOT NULL, role CHECK (worker|qa|governance), phase/model/symptom,
# evidence_json = list[str], recorded_at, tags/impact/pattern_ref; new
# fc_incident_counters table for gap-free FC-YYYY-NNNN allocation).
# AG3-028 Codex-r2 Remediation 2026-06-01: 3.10.0 -> 3.11.0 (incident_id GLOBAL
# unique — PK = incident_id allein statt (project_key, incident_id);
# fc_incident_counters auf year allein gekeyt statt (project_key, year);
# DB-CHECKs fuer FC-YYYY-NNNN-Format und evidence_json = JSON-Array). PK-/
# Counter-Struktur aendert sich -> erneuter Side-by-Side-Bump (FK-18 §18.9a):
# ein frisches ak3_v3_11_0 schema / agentkit_3_11_0.sqlite wird erzeugt; die
# alte DB bleibt unangetastet.
# AG3-028 Codex-r3/r4 Remediation 2026-06-01: 3.11.0 -> 3.12.0. r3 hat die
# fc_incidents-CHECKs verschaerft (incident_id == FC-YYYY-NNNN mit >=4-stelliger
# Ziffern-Sequenz; evidence_json = JSON-Array AUS STRINGS via Postgres-jsonpath),
# OHNE Version-Bump. Da CREATE TABLE IF NOT EXISTS eine bestehende Tabelle nicht
# ersetzt, behielten bereits gebootete 3.11.0-DBs die alten (schwaecheren)
# Constraints (zwei DBs gleicher Version, divergentes Schema). Der Bump auf
# 3.12.0 stellt den Side-by-Side-Vertrag (FK-18 §18.9a) wieder her: die
# verschaerften Constraints landen frisch in ak3_v3_12_0 / agentkit_3_12_0.sqlite.
# AG3-028 Codex-r6 Remediation 2026-06-01: 3.12.0 -> 3.13.0. Auch fuer die
# OPTIONALE Spalte tags wird jetzt die JSON-Array-AUS-STRINGS-Form DB-seitig
# erzwungen (Postgres-CHECK via jsonpath; SQLite Array-CHECK + Element-Trigger).
# Zuvor liessen sich tags='"x"'/'{"k":"v"}' als Nicht-Array durchschmuggeln.
# Constraint-Aenderung -> Side-by-Side-Bump (FK-18 §18.9a): frisch in
# ak3_v3_13_0 / agentkit_3_13_0.sqlite.
SCHEMA_VERSION = "3.13.0"
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
