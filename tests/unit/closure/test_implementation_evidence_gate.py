"""Tests for the FK-24 implementation-evidence terminality gate."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from agentkit.closure.gates import evaluate_implementation_evidence_gate
from agentkit.core_types.qa_artifact_names import (
    HANDOVER_FILE,
    PROTOCOL_FILE,
    WORKER_MANIFEST_FILE,
)
from agentkit.story_context_manager.types import StoryType
from agentkit.verify_system.structural.system_evidence import ChangeEvidence

if TYPE_CHECKING:
    from pathlib import Path


def test_implementation_evidence_gate_exploration_only_fails(tmp_path: Path) -> None:
    """AC2(i): exploration-only artifacts are not implementation evidence."""
    (tmp_path / "exploration-summary.md").write_text("summary\n", encoding="utf-8")
    (tmp_path / "change_frame.json").write_text("{}", encoding="utf-8")

    verdict = evaluate_implementation_evidence_gate(
        story_type=StoryType.IMPLEMENTATION,
        story_dir=tmp_path,
        change_evidence=ChangeEvidence(
            available=True,
            changed_files=("exploration-summary.md", "change_frame.json"),
        ),
    )

    assert verdict.passed is False


def test_implementation_evidence_gate_manifest_protocol_without_system_diff_fails(
    tmp_path: Path,
) -> None:
    """AC2(ii): worker manifest claims never replace System git-diff evidence."""
    _write_required_worker_artifacts(tmp_path)

    verdict = evaluate_implementation_evidence_gate(
        story_type=StoryType.IMPLEMENTATION,
        story_dir=tmp_path,
        change_evidence=ChangeEvidence(available=True, changed_files=()),
    )

    assert verdict.passed is False
    assert "System git diff" in (verdict.blocking_reason or "")


def test_implementation_evidence_gate_required_artifacts_and_system_diff_pass(
    tmp_path: Path,
) -> None:
    """AC2(iii): required artifacts plus confirming Trust-B diff pass."""
    _write_required_worker_artifacts(tmp_path)

    verdict = evaluate_implementation_evidence_gate(
        story_type=StoryType.BUGFIX,
        story_dir=tmp_path,
        change_evidence=ChangeEvidence(
            available=True,
            changed_files=("src/agentkit/example.py",),
        ),
    )

    assert verdict.passed is True


def _write_required_worker_artifacts(story_dir: Path) -> None:
    (story_dir / HANDOVER_FILE).write_text("handover\n", encoding="utf-8")
    (story_dir / PROTOCOL_FILE).write_text("protocol\n", encoding="utf-8")
    (story_dir / WORKER_MANIFEST_FILE).write_text(
        json.dumps(
            {
                "story_id": "TEST-001",
                "run_id": "run-test-001",
                "status": "completed",
                "completed_at": datetime(2026, 1, 1, tzinfo=UTC).isoformat(),
                "files_changed": ["src/agentkit/example.py"],
                "tests_added": [],
                "acceptance_criteria_status": {"AC1": "done"},
            }
        ),
        encoding="utf-8",
    )
