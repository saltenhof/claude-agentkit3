from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from agentkit.backend.state_backend import config as state_config
from agentkit.backend.state_backend import (
    postgres_store,
    sqlite_store,
)
from agentkit.backend.state_backend.sqlite_store import load_project_rows


def test_schema_version_helpers_derive_versioned_names() -> None:
    # AG3-025: 3.4.0 -> 3.5.0 (attempts-Tabelle, FK-18 §18.9a)
    # AG3-025 Re-Review: 3.5.0 -> 3.5.1 (story_id-Spalte + story-scoped Index)
    # AG3-031: 3.5.1 -> 3.6.0 (governance_hook_registrations-Tabelle)
    # AG3-015: 3.6.0 -> 3.7.0 (artifact_class CHECK + 'prompt_audit', FK-44 §44.6)
    # AG3-050: 3.7.0 -> 3.8.0 (story_dependencies FK retargeted to the static
    # stories(story_display_id) identity; FK-02 §2.11.3, FK-18 §18.6a)
    # AG3-028: 3.8.0 -> 3.9.0 (fc_incidents table; FK-41 §41.3.1, FK-69, FK-18 §18.9a)
    # AG3-028 Codex-r1: 3.9.0 -> 3.10.0 (fc_incidents realigned to FK-41 §41.3.1:
    # project_key/run_id/role/phase/model/symptom NOT NULL, evidence list[str],
    # FC-YYYY-NNNN ids + fc_incident_counters table)
    # AG3-028 Codex-r2: 3.10.0 -> 3.11.0 (incident_id GLOBAL unique — PK =
    # incident_id allein; fc_incident_counters auf year allein gekeyt; DB-CHECKs
    # fuer FC-YYYY-NNNN-Format + evidence_json = JSON-Array)
    # AG3-028 Codex-r3/r4: 3.11.0 -> 3.12.0 (verschaerfte fc_incidents-CHECKs:
    # incident_id-Sequenz >=4 Ziffern + nur Ziffern; evidence_json = JSON-Array
    # AUS STRINGS via Postgres-jsonpath. Bump, weil CREATE TABLE IF NOT EXISTS
    # bestehende 3.11.0-Constraints nicht ersetzt — FK-18 §18.9a Side-by-Side)
    # AG3-028 Codex-r6: 3.12.0 -> 3.13.0 (auch tags wird als JSON-Array-aus-
    # Strings DB-seitig erzwungen — Postgres-CHECK + SQLite-Array-CHECK)
    # AG3-048: 3.13.0 -> 3.14.0 (skill_bindings table; agent-skills BC
    # persistence, FK-43 §43.4.1, bc-cut-decisions.md §BC 11, FK-18 §18.9a)
    # AG3-040 Sub-Block (b): 3.14.0 -> 3.15.0 (fc_patterns + fc_check_proposals
    # tables; failure-corpus BC, FK-41 §41.3.2/§41.3.3, FK-69 §69.3, FK-18 §18.9a)
    # AG3-032: 3.15.0 -> 3.16.0 (governance_freeze_records table; Principal-
    # Capability-Modell, FK-55 §55.8/§55.10.5, FK-31 §31.2.7, FK-18 §18.9a)
    # AG3-034: 3.16.0 -> 3.17.0 (project_mode_lock table; Fast/Standard-Mode-Lock
    # Read-Pfad fuer Preflight-Check 10, FK-24 §24.3.3, FK-22 §22.3.1, FK-18 §18.9a)
    # AG3-039: 3.17.0 -> 3.18.0 (project_registry table; Installer-Checkpoint 7
    # State-Backend-Registrierung, FK-50 §50.3 CP 7, formal.installer.entities,
    # FK-18 §18.9a)
    # AG3-038: 3.18.0 -> 3.19.0 (analytics fact tables fact_story/
    # fact_guard_period/fact_pool_period/fact_pipeline_period/fact_corpus_period
    # + sync_state + guard_invocation_counters scratchpad; kpi-and-dashboard BC,
    # FK-62 §62.2.1-62.2.7, FK-60 §60.3.4, FK-18 §18.9a)
    # AG3-054: 3.19.0 -> 3.20.0 (control_plane_operations gains claimed_by /
    # claimed_at for the leased, owner-scoped claim; FK-91, FK-22 §22.9,
    # FK-18 §18.9a)
    # AG3-075: 3.20.0 -> 3.21.0 (compaction_epochs table; FK-36 story-scoped
    # compaction recovery epoch store, FK-18 §18.9a)
    # AG3-096: 3.22.0 -> 3.23.0 (tm_tasks + tm_task_links tables;
    # task-management BC, FK-77 state and typed links, FK-18 §18.9a)
    # AG3-106: 3.23.0 -> 3.24.0 (governance_hook_registrations CHECK admits
    # Claude Code PostToolUseFailure for failed tool-call outcomes, FK-30/FK-76)
    # AG3-068: 3.24.0 -> 3.25.0 (stories.vectordb_conflict_resolved column;
    # FK-21 §21.12 producer flag, additive ALTER TABLE migration)
    # AG3-072: 3.25.0 -> 3.26.0 (stories.split_from + stories.split_successors
    # columns; FK-54 §54.8.5 materialized split lineage, additive ALTER TABLE
    # migrations, FK-18 §18.9a)
    # AG3-108: 3.26.0 -> 3.27.0 (qa_check_outcomes table + check_id column on
    # override_records; FK-69 §69.15 Per-Check-Outcome-Read-Model + §69.11 rule 3
    # override->check correlation, Schema-Owner verify-system, Codex-approved,
    # FK-18 §18.9a)
    # AG3-078: 3.27.0 -> 3.28.0 (fc_check_proposals.check_proposal_ref on
    # qa_check_outcomes; FC_PATTERNS/FC_CHECK_PROPOSALS accessor-owned;
    # PatternPromotion/CheckFactory/CheckEffectivenessTracker; FK-41 §41.5/§41.6)
    # AG3-120: 3.28.0 -> 3.29.0 (story_contexts.issue_nr column DROPPED; AK3 owns
    # the story via story_id, GitHub is only the code backend, FK-12 §12.1.1 /
    # FK-91 §91.2 rule 9; side-by-side versioned-schema migration, FK-18 §18.9a)
    # AG3-150: 3.29.0 -> 3.30.0 (freeze-family kind + freeze_epoch).
    # AG3-150 R1: 3.30.0 -> 3.31.0 (per-kind active set + epoch audit highwater).
    assert state_config.SCHEMA_VERSION == "3.31.0"
    assert state_config.versioned_postgres_schema_name("3.0.0") == "ak3_v3_0_0"
    assert state_config.versioned_sqlite_db_file("3.0.0") == "agentkit_3_0_0.sqlite"
    assert state_config.versioned_postgres_schema_name() == "ak3_v3_31_0"
    assert state_config.versioned_sqlite_db_file() == "agentkit_3_31_0.sqlite"


def test_schema_version_rejects_non_semver() -> None:
    with pytest.raises(RuntimeError):
        state_config.schema_version_slug("3")


def test_sqlite_state_db_path_contains_current_schema_version(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(state_config, "SCHEMA_VERSION", "3.2.0")

    assert sqlite_store.state_db_path_for(tmp_path).name == "agentkit_3_2_0.sqlite"


def test_sqlite_bootstrap_is_idempotent_and_side_by_side(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(state_config, "SCHEMA_VERSION", "3.0.0")
    assert load_project_rows(tmp_path) == []
    first_path = sqlite_store.state_db_path_for(tmp_path)
    with sqlite3.connect(first_path) as conn:
        conn.execute("INSERT INTO projects VALUES (?, ?, ?, ?, ?)", ("old", "Old", "OLD", "{}", None))
        conn.commit()

    assert load_project_rows(tmp_path, include_archived=True)[0]["key"] == "old"

    monkeypatch.setattr(state_config, "SCHEMA_VERSION", "3.2.0")
    assert load_project_rows(tmp_path) == []
    second_path = sqlite_store.state_db_path_for(tmp_path)

    assert first_path.exists()
    assert second_path.exists()
    assert first_path.name == "agentkit_3_0_0.sqlite"
    assert second_path.name == "agentkit_3_2_0.sqlite"


def test_postgres_current_schema_name_uses_schema_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(state_config, "SCHEMA_VERSION", "3.2.1")

    assert postgres_store.current_schema_name() == "ak3_v3_2_1"
