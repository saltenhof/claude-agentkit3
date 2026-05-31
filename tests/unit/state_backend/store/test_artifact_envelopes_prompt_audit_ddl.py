"""E3a (AG3-015 Review R1): sqlite_store global DDL accepts ``prompt_audit``.

The ``artifact_envelopes`` table is created by the global ``sqlite_store``
schema (``_ensure_schema``). The later ``CREATE TABLE IF NOT EXISTS`` in
``artifact_repository`` does NOT rewrite an already-created table, so the
global DDL's ``artifact_class`` CHECK constraint must itself include
``prompt_audit`` -- otherwise a DB first touched via ``sqlite_store`` would
reject prompt-audit envelopes. This pins that there is no second, competing
DDL truth.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from agentkit.artifacts import (
    ArtifactEnvelope,
    Producer,
    ProducerId,
    ProducerType,
)
from agentkit.core_types import ArtifactClass, EnvelopeStatus
from agentkit.state_backend.config import ALLOW_SQLITE_ENV, STATE_BACKEND_ENV
from agentkit.state_backend.sqlite_store import _connect
from agentkit.state_backend.store import reset_backend_cache_for_tests
from agentkit.state_backend.store.artifact_repository import (
    StateBackendArtifactRepository,
)

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path


@pytest.fixture(autouse=True)
def _sqlite_env(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    monkeypatch.setenv(STATE_BACKEND_ENV, "sqlite")
    monkeypatch.setenv(ALLOW_SQLITE_ENV, "1")
    reset_backend_cache_for_tests()
    yield
    reset_backend_cache_for_tests()


def _prompt_audit_envelope(run_id: str) -> ArtifactEnvelope:
    ts = datetime(2026, 6, 1, tzinfo=UTC)
    return ArtifactEnvelope(
        schema_version="3.0",
        story_id="AG3-015",
        run_id=run_id,
        stage="prompt-materialization",
        attempt=1,
        producer=Producer(
            type=ProducerType.DETERMINISTIC,
            name="prompt-runtime.materialization",
            id=ProducerId(f"{run_id}:inv-1"),
            version="2",
        ),
        started_at=ts,
        finished_at=ts,
        status=EnvelopeStatus.PASS,
        artifact_class=ArtifactClass.PROMPT_AUDIT,
        payload={"render_mode": "rendered"},
    )


def test_prompt_audit_accepted_on_sqlite_store_preinitialized_db(
    tmp_path: Path,
) -> None:
    story_dir = tmp_path / "stories" / "TEST-PA-001"
    story_dir.mkdir(parents=True)

    # Pre-create the DB via the GLOBAL sqlite_store schema so the
    # artifact_envelopes table (and its CHECK) come from sqlite_store, not
    # from artifact_repository.
    with _connect(story_dir) as conn:
        names = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    assert "artifact_envelopes" in names

    repo = StateBackendArtifactRepository(store_dir=story_dir)
    ref = repo.write_envelope(_prompt_audit_envelope("run-pa-1"))
    loaded = repo.read_envelope(ref)
    assert loaded is not None
    assert loaded.artifact_class is ArtifactClass.PROMPT_AUDIT
