"""Regression tests for Postgres fixture collection binding."""

from __future__ import annotations

from tests.integration.conftest import _is_postgres_integration_item


def test_sqlite_only_pipeline_engine_files_do_not_receive_postgres_fixture() -> None:
    assert not _is_postgres_integration_item(
        "tests/integration/pipeline_engine/test_orchestrator_trennlinie.py",
        "tests/integration/pipeline_engine/test_orchestrator_trennlinie.py::"
        "test_engine_persists_agents_to_spawn_and_yields_without_transition",
    )
    assert not _is_postgres_integration_item(
        "tests/integration/pipeline_engine/test_blocked_exit.py",
        "tests/integration/pipeline_engine/test_blocked_exit.py::"
        "test_engine_propagates_suggested_reaction_to_caller",
    )


def test_postgres_pipeline_engine_files_still_receive_postgres_fixture() -> None:
    assert _is_postgres_integration_item(
        "tests/integration/pipeline_engine/test_pipeline_runner.py",
        "tests/integration/pipeline_engine/test_pipeline_runner.py::"
        "test_pipeline_runner_persists_phase_state",
    )
