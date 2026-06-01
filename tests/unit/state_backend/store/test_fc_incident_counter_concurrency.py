"""Race-Sicherheit des globalen FC-YYYY-NNNN-Allokators (AG3-028 Codex-r2).

Beweist, dass zwei (bzw. viele) konkurrierende ERST-Allokationen desselben
Jahres VERSCHIEDENE incident_ids erhalten — der alte Bug (SELECT ... FOR UPDATE
sperrt bei fehlender Counter-Zeile nichts -> zwei Txns liefern FC-YYYY-0001) ist
geschlossen. Die Allokation laeuft in EINEM atomaren UPSERT mit RETURNING unter
BEGIN IMMEDIATE (SQLite-16-Thread-Stil, analog dem story_number-Test AG3-050).

Postgres-Concurrency ist lokal nicht beweisbar (N1-WARNING, wie AG3-050); der
atomare ON CONFLICT(year) DO UPDATE ... RETURNING-Pfad ist dort strukturell
race-sicher (kein TOCTOU mehr).
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from agentkit.core_types import FailureCategory
from agentkit.failure_corpus import IncidentDraft, IncidentRole, IncidentSeverity
from agentkit.state_backend.config import ALLOW_SQLITE_ENV, STATE_BACKEND_ENV
from agentkit.state_backend.store import reset_backend_cache_for_tests
from agentkit.state_backend.store.fc_incident_repository import (
    StateBackendFCIncidentsRepository,
)

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

_NOW = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def sqlite_env(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    monkeypatch.setenv(STATE_BACKEND_ENV, "sqlite")
    monkeypatch.setenv(ALLOW_SQLITE_ENV, "1")
    reset_backend_cache_for_tests()
    yield
    reset_backend_cache_for_tests()


def _draft(i: int) -> IncidentDraft:
    return IncidentDraft(
        project_key=f"proj-{i % 3}",
        story_id=f"AG3-{i:03d}",
        run_id=f"run-{i}",
        category=FailureCategory.SCOPE_DRIFT,
        severity=IncidentSeverity.HIGH,
        phase="implementation",
        role=IncidentRole.WORKER,
        model="claude-opus",
        symptom=f"symptom {i}",
        evidence=[f"e{i}"],
        recorded_at=_NOW,
    )


def test_initial_counter_two_concurrent_allocations_differ(tmp_path: Path) -> None:
    """Zwei konkurrierende ERST-Allokationen (gleiches Jahr) -> zwei
    VERSCHIEDENE ids, keine FC-2026-0001-Kollision."""
    # Schema einmal vorab bereitstellen (wie in Produktion beim Start), damit die
    # konkurrierende Phase nur auf der BEGIN-IMMEDIATE-Allokation kontendiert und
    # nicht auf autocommit-CREATE-TABLE-DDL.
    StateBackendFCIncidentsRepository(tmp_path).read(project_key="warmup")

    barrier = threading.Barrier(2)

    def _alloc(i: int) -> str:
        barrier.wait()
        return str(StateBackendFCIncidentsRepository(tmp_path).record_incident(_draft(i)))

    with ThreadPoolExecutor(max_workers=2) as pool:
        ids = list(pool.map(_alloc, range(2)))

    assert len(set(ids)) == 2, f"initial-counter race produced a collision: {ids}"
    assert sorted(ids) == ["FC-2026-0001", "FC-2026-0002"]


def test_many_concurrent_allocations_are_globally_unique_gap_free(
    tmp_path: Path,
) -> None:
    """16 Threads allozieren gleichzeitig -> global eindeutige, luecklose
    FC-2026-NNNN-Sequenz (kein Duplikat, keine Luecke)."""
    StateBackendFCIncidentsRepository(tmp_path).read(project_key="warmup")

    worker_count = 16
    barrier = threading.Barrier(worker_count)

    def _alloc(i: int) -> str:
        barrier.wait()
        return str(StateBackendFCIncidentsRepository(tmp_path).record_incident(_draft(i)))

    with ThreadPoolExecutor(max_workers=worker_count) as pool:
        ids = list(pool.map(_alloc, range(worker_count)))

    seqs = sorted(int(i.rsplit("-", 1)[1]) for i in ids)
    assert seqs == list(range(1, worker_count + 1)), (
        f"allocated ids must be unique and gap-free under concurrency: {ids}"
    )
    assert len(set(ids)) == worker_count
