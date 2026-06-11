"""Configuration helpers for canonical state backend selection."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from enum import StrEnum

from agentkit.config.sqlite_gate import ALLOW_SQLITE_ENV, sqlite_allowed

STATE_BACKEND_ENV = "AGENTKIT_STATE_BACKEND"
STATE_DATABASE_URL_ENV = "AGENTKIT_STATE_DATABASE_URL"
# AG3-051: test-only Postgres schema override. Production/runtime/build NEVER
# set these; the override is honored fail-closed (gate active AND name matches
# the reserved test namespace) so a leaked override cannot point at production
# data. See FK-18 §18.9a (versioned schema) and AG3-051 §2.1.2.
SCHEMA_OVERRIDE_ENV = "AGENTKIT_PG_SCHEMA_OVERRIDE"
SCHEMA_OVERRIDE_ALLOWED_ENV = "AGENTKIT_PG_SCHEMA_OVERRIDE_ALLOWED"
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
# unique — PK = incident_id alone instead of (project_key, incident_id);
# fc_incident_counters keyed on year alone instead of (project_key, year);
# DB CHECKs for the FC-YYYY-NNNN format and evidence_json = JSON array). The PK/
# counter structure changes -> another side-by-side bump (FK-18 §18.9a):
# a fresh ak3_v3_11_0 schema / agentkit_3_11_0.sqlite is created; the
# old DB stays untouched.
# AG3-028 Codex-r3/r4 Remediation 2026-06-01: 3.11.0 -> 3.12.0. r3 tightened the
# fc_incidents CHECKs (incident_id == FC-YYYY-NNNN with a >=4-digit
# digit sequence; evidence_json = JSON array OF STRINGS via Postgres jsonpath),
# WITHOUT a version bump. Since CREATE TABLE IF NOT EXISTS does not replace an
# existing table, already-booted 3.11.0 DBs kept the old (weaker)
# constraints (two DBs of the same version, divergent schema). The bump to
# 3.12.0 restores the side-by-side contract (FK-18 §18.9a): the
# tightened constraints land fresh in ak3_v3_12_0 / agentkit_3_12_0.sqlite.
# AG3-028 Codex-r6 Remediation 2026-06-01: 3.12.0 -> 3.13.0. The OPTIONAL column
# tags is now also forced into the JSON-ARRAY-OF-STRINGS form on the DB side
# (Postgres CHECK via jsonpath; SQLite array CHECK + element trigger).
# Previously tags='"x"'/'{"k":"v"}' could be smuggled through as a non-array.
# Constraint change -> side-by-side bump (FK-18 §18.9a): fresh in
# ak3_v3_13_0 / agentkit_3_13_0.sqlite.
# AG3-048: 3.13.0 -> 3.14.0 (skill_bindings table added; agent-skills BC
# persistence, FK-43 §43.4.1 Link-Bindungsvertrag, bc-cut-decisions.md §BC 11.
# Canonical Postgres + SQLite test-parallel schema with identical DDL. The table
# owns the SkillBinding shape from AG3-027 (binding_id PK, UNIQUE(project_key,
# skill_name), binding_mode CHECK IN ('SYMLINK', 'JUNCTION') — platform-aware
# per FK-43 §43.4.1.1: symlink on POSIX, directory junction on Windows; status
# CHECK over all SIX SkillLifecycleStatus values, index
# idx_skill_bindings_project_skill).
# Idempotent side-by-side migration via the versioned-schema pattern (FK-18
# §18.9a) — a fresh ak3_v3_14_0 schema / agentkit_3_14_0.sqlite file is created;
# the old 3.13.0 DB is never touched.
# AG3-040 Sub-Block (b): 3.14.0 -> 3.15.0 (fc_patterns + fc_check_proposals
# tables added; FK-41 §41.3.2/§41.3.3, FK-69 §69.3. Schema owner failure-corpus,
# DB owner telemetry-and-events. Canonical Postgres (JSONB/jsonpath CHECK) +
# SQLite test-parallel schema with identical semantics. fc_patterns: PK
# pattern_id (FP-NNNN), CHECK on status (4 pattern-status values), category (12
# FailureCategory values), promotion_rule (3), risk_level (3), confirmed_by =
# 'human'; incident_refs = JSON array of strings. fc_check_proposals: PK check_id
# (CHK-NNNN), pattern_ref FK -> fc_patterns(pattern_id), CHECK on status (5
# check-status values), check_type (6 CheckType values), false_positive_risk (3),
# approved_by = 'human'; positive_/negative_fixtures = JSON arrays. New enums
# PatternStatus (4), CheckStatus (5), CheckType (6) in core_types. Only tables +
# repository skeletons; the writers PatternPromotion/CheckFactory stay Out of
# Scope (FK-41 §41.5/§41.6). Idempotent side-by-side migration via the
# versioned-schema pattern (FK-18 §18.9a) — a fresh ak3_v3_15_0 schema /
# agentkit_3_15_0.sqlite file is created; the old 3.14.0 DB is never touched.
# AG3-032 (FK-55 §55.8/§55.10.5, FK-31 §31.2.7): 3.15.0 -> 3.16.0
# (governance_freeze_records table added; principal-capability model. Schema/
# DB owner governance-and-guards. Canonical Postgres + SQLite test-parallel
# schema with IDENTICAL DDL. The table is the canonical (truth) side of the dual
# conflict-freeze materialization; the local .agentkit/governance/freeze.json
# export carries a matching freeze_version. Columns: story_id PK, frozen_at,
# freeze_reason, freeze_version. Idempotent side-by-side migration via the
# versioned-schema pattern (FK-18 §18.9a): a fresh ak3_v3_16_0 schema /
# agentkit_3_16_0.sqlite file is created; the old 3.15.0 DB is never touched.
# AG3-034 (FK-24 §24.3.3, FK-22 §22.3.1 Check 10): 3.16.0 -> 3.17.0
# (project_mode_lock table added; project-wide control-plane mode lock for the
# fast/standard mutual exclusion. AG3-034 provides ONLY the read path for
# preflight check 10 (no_competing_story_mode_active) — the atomic setting
# at story start is an AG3-018 follow-up (story.md §2.1.2 / §2.2). Schema/DB owner
# governance-and-guards. Canonical Postgres + SQLite test-parallel schema with
# IDENTICAL DDL: project_key PK, active_mode NULL|execution|exploration|fast
# (CHECK), holder_count >= 0 (CHECK), updated_at. Idempotent side-by-side
# migration via the versioned-schema pattern (FK-18 §18.9a): a fresh ak3_v3_17_0
# schema / agentkit_3_17_0.sqlite file is created; the old 3.16.0 DB is never
# touched.
# AG3-039 (FK-50 §50.3 CP 7, formal.installer.entities §project-registration):
# 3.17.0 -> 3.18.0 (project_registry table added; canonical State-Backend
# project registration for Installer-Checkpoint 7. Schema-/DB-Owner
# installation-and-bootstrap. Canonical Postgres + SQLite test-parallel schema
# with IDENTICAL DDL: project_key PK, project_root UNIQUE, github_owner/
# github_repo NOT NULL, runtime_profile CHECK IN ('core','are'), config_version
# / config_digest NOT NULL, registered_at NOT NULL, last_verified_at NULL,
# last_upgraded_at NULL. Idempotent side-by-side migration via the
# versioned-schema pattern (FK-18 §18.9a): a fresh ak3_v3_18_0 schema /
# agentkit_3_18_0.sqlite file is created; the old 3.17.0 DB is never touched.
# AG3-038 (FK-62 §62.2.1-62.2.7, FK-60 §60.3.4): 3.18.0 -> 3.19.0 (analytics
# fact tables fact_story/fact_guard_period/fact_pool_period/fact_pipeline_period/
# fact_corpus_period + sync_state + guard_invocation_counters scratchpad added;
# kpi-and-dashboard BC analytics schema layer. Canonical Postgres + SQLite
# test-parallel schema with IDENTICAL column/PK semantics; tables join the SINGLE
# versioned schema (no separate top-level ``analytics`` schema — that would be
# cross-version-shared and break the side-by-side invariant; see the placement
# note in postgres_schema.sql). project_key is the leading scope key on every
# fact/scratchpad table (FK-62 §62.2 tenancy rule). The MigrationRunner
# (state_backend.migration, FK-62 §62.4) records this as logical analytics
# version 3.4 in the idempotent ``schema_versions`` cursor. Idempotent
# side-by-side migration via the versioned-schema pattern (FK-18 §18.9a) — a
# fresh ak3_v3_20_0 schema / agentkit_3_20_0.sqlite file is created; the old
# 3.19.0 DB is never touched.
#
# 3.20.0 (AG3-054): control_plane_operations gains claimed_by / claimed_at for
# the leased, owner-scoped claim (FK-91, FK-22 §22.9). A fresh schema gets the
# columns from CREATE TABLE; an existing same-version schema gets them via the
# idempotent ALTER TABLE ... ADD COLUMN IF NOT EXISTS statements in
# postgres_store._schema_alter_statements (FK-62 §62.4 strategy).
# 3.21.0 (AG3-075): compaction_epochs table added for FK-36 story-scoped
# compaction recovery epochs. Fresh schemas get the table from the canonical
# Postgres/SQLite DDL; existing schemas get the idempotent v3.5 MigrationRunner
# migration and schema_versions cursor entry.
# 3.23.0 (AG3-096): tm_tasks + tm_task_links tables added for FK-77
# task-management state and typed links.
# 3.25.0 (AG3-068): stories.vectordb_conflict_resolved column added (FK-21 §21.12
# producer flag). Fresh schemas get it from the canonical Postgres/SQLite DDL;
# existing schemas get the idempotent additive ALTER TABLE migration.
SCHEMA_VERSION = "3.25.0"
_SCHEMA_VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")
# AG3-051: reserved test-schema namespace. Disjoint from the production schema
# name (``ak3_v<slug>``), so a test override can never resolve onto production
# data even if the gate is mis-set.
_TEST_SCHEMA_NAME_PATTERN = re.compile(r"^ak3test_[a-z0-9_]+$")
_TRUTHY = frozenset({"1", "true", "yes", "on"})


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


def resolve_schema_name(version: str | None = None) -> str:
    """Resolve the active PostgreSQL schema name (single source of truth).

    Production path returns the versioned schema ``ak3_v<slug>`` unchanged. A
    test override (``AGENTKIT_PG_SCHEMA_OVERRIDE``) is honored **only** when it
    is fail-closed safe:

    - the gate ``AGENTKIT_PG_SCHEMA_OVERRIDE_ALLOWED`` is truthy, AND
    - the override matches the reserved test namespace ``^ak3test_[a-z0-9_]+$``.

    Any other combination raises :class:`RuntimeError`. Production/runtime/build
    never set the override, so their behaviour is identical to
    :func:`versioned_postgres_schema_name`. The reserved prefix guarantees a
    test schema can never collide with production data.

    Args:
        version: Optional explicit schema version; defaults to ``SCHEMA_VERSION``.

    Returns:
        The resolved schema name to ``CREATE SCHEMA`` / ``SET search_path`` on.

    Raises:
        RuntimeError: If the override is set without an active gate or with a
            name outside the reserved ``ak3test_`` namespace.
    """

    override = os.environ.get(SCHEMA_OVERRIDE_ENV)
    if override is None:
        return versioned_postgres_schema_name(version)
    if os.environ.get(SCHEMA_OVERRIDE_ALLOWED_ENV, "").lower() not in _TRUTHY:
        raise RuntimeError(
            f"{SCHEMA_OVERRIDE_ENV} is set but {SCHEMA_OVERRIDE_ALLOWED_ENV} is "
            "not active. The schema override is a test-only control and stays "
            "fail-closed in production paths.",
        )
    if _TEST_SCHEMA_NAME_PATTERN.fullmatch(override) is None:
        raise RuntimeError(
            f"Invalid {SCHEMA_OVERRIDE_ENV}={override!r}; a test schema override "
            "must match ^ak3test_[a-z0-9_]+$ (reserved test namespace).",
        )
    return override


def versioned_sqlite_db_file(version: str | None = None) -> str:
    """Return the SQLite file name for a schema version."""

    return f"agentkit_{schema_version_slug(version)}.sqlite"


__all__ = [
    "STATE_BACKEND_ENV",
    "STATE_DATABASE_URL_ENV",
    "ALLOW_SQLITE_ENV",
    "SCHEMA_OVERRIDE_ENV",
    "SCHEMA_OVERRIDE_ALLOWED_ENV",
    "SCHEMA_VERSION",
    "StateBackendConfig",
    "StateBackendKind",
    "load_state_backend_config",
    "resolve_schema_name",
    "schema_version_slug",
    "versioned_postgres_schema_name",
    "versioned_sqlite_db_file",
]
