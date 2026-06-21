"""Conflict-freeze proof repository roundtrip tests."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from agentkit.backend.governance.guard_system.records import ConflictFreezeProofRecord
from agentkit.backend.state_backend.store.conflict_freeze_proof_repository import (
    ConflictFreezeProofRepository,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_conflict_freeze_proof_roundtrip(tmp_path: Path) -> None:
    activated_at = datetime(2026, 6, 9, 12, 0, tzinfo=UTC)
    proof = ConflictFreezeProofRecord(
        project_key="proj",
        story_id="AG3-087",
        run_id="run-1",
        proof_id="proof-1",
        activated_at=activated_at,
        blocked_principal="worker",
        resolution_service_path="agentkit reset-story",
    )
    repo = ConflictFreezeProofRepository(tmp_path)
    repo.save(proof)

    assert repo.latest_for_run("proj", "AG3-087", "run-1") == proof
