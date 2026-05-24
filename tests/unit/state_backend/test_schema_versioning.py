from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from agentkit.state_backend import config as state_config
from agentkit.state_backend import postgres_store, sqlite_store
from agentkit.state_backend.sqlite_store import load_project_rows


def test_schema_version_helpers_derive_versioned_names() -> None:
    # AG3-025: 3.4.0 -> 3.5.0 (attempts-Tabelle, FK-18 §18.9a)
    # AG3-025 Re-Review: 3.5.0 -> 3.5.1 (story_id-Spalte + story-scoped Index)
    # AG3-031: 3.5.1 -> 3.6.0 (governance_hook_registrations-Tabelle)
    assert state_config.SCHEMA_VERSION == "3.6.0"
    assert state_config.versioned_postgres_schema_name("3.0.0") == "ak3_v3_0_0"
    assert state_config.versioned_sqlite_db_file("3.0.0") == "agentkit_3_0_0.sqlite"
    assert state_config.versioned_postgres_schema_name() == "ak3_v3_6_0"
    assert state_config.versioned_sqlite_db_file() == "agentkit_3_6_0.sqlite"


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
