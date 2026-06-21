"""GuardDecision repository roundtrip tests."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from agentkit.backend.governance.guard_system.records import (
    GuardDecision,
    GuardDecisionOutcome,
)
from agentkit.backend.state_backend.store.guard_decision_repository import (
    GuardDecisionRepository,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_guard_decision_append_read_roundtrip(tmp_path: Path) -> None:
    decided_at = datetime(2026, 6, 9, 12, 0, tzinfo=UTC)
    decision = GuardDecision(
        project_key="proj",
        story_id="AG3-087",
        run_id="run-1",
        flow_id="flow-1",
        guard_decision_id="gd-1",
        guard_key="security.secrets",
        outcome=GuardDecisionOutcome.ERROR,
        decided_at=decided_at,
        node_id="node-1",
        reason="secret hit",
        evidence_ref="qa/structural",
    )
    repo = GuardDecisionRepository(tmp_path)
    repo.append(decision)

    assert repo.list_for_run("proj", "AG3-087", "run-1") == (decision,)
