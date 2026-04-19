"""Tests for IntegrityGate against canonical DB-backed runtime records."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from agentkit.governance.integrity_gate import IntegrityGate
from agentkit.qa.policy_engine.engine import VerifyDecision
from agentkit.qa.protocols import LayerResult
from agentkit.state_backend import (
    record_layer_artifacts,
    record_verify_decision,
    save_phase_snapshot,
    save_story_context,
    state_db_path,
)
from agentkit.story_context_manager.models import PhaseSnapshot, StoryContext
from agentkit.story_context_manager.types import StoryMode, StoryType

if TYPE_CHECKING:
    from pathlib import Path


def _create_context(
    story_dir: Path,
    story_type: StoryType = StoryType.IMPLEMENTATION,
) -> None:
    mode = (
        StoryMode.EXECUTION
        if story_type in (StoryType.IMPLEMENTATION, StoryType.BUGFIX)
        else StoryMode.NOT_APPLICABLE
    )
    save_story_context(
        story_dir,
        StoryContext(
            story_id="AG3-001",
            story_type=story_type,
            mode=mode,
            title="Integrity Gate Test",
        ),
    )


def _create_snapshot(story_dir: Path, phase: str, status: str = "completed") -> None:
    save_phase_snapshot(
        story_dir,
        PhaseSnapshot(
            story_id="AG3-001",
            phase=phase,
            status=status,
            completed_at=datetime(2026, 4, 7, 12, 0, 0, tzinfo=UTC),
            artifacts=[],
            evidence={},
        ),
    )


def _create_decision(story_dir: Path, decision: str = "PASS") -> None:
    passed = decision in ("PASS", "PASS_WITH_WARNINGS")
    structural = LayerResult(layer="structural", passed=passed, findings=())
    record_layer_artifacts(
        story_dir,
        layer_results=(structural,),
        attempt_nr=1,
    )
    record_verify_decision(
        story_dir,
        decision=VerifyDecision(
            passed=passed,
            status=decision,
            layer_results=(structural,),
            all_findings=(),
            blocking_findings=(),
            summary="decision summary",
        ),
        attempt_nr=1,
    )


def _populate_implementation_story(story_dir: Path) -> None:
    _create_context(story_dir)
    for phase in ("setup", "implementation", "verify"):
        _create_snapshot(story_dir, phase)
    _create_decision(story_dir)


def _corrupt_table_payload(story_dir: Path, table: str) -> None:
    with sqlite3.connect(state_db_path(story_dir)) as conn:
        if table == "decision_records":
            conn.execute("UPDATE decision_records SET payload_json = 'not json'")
        elif table == "artifact_records":
            conn.execute("UPDATE artifact_records SET payload_json = 'not json'")
        elif table == "story_contexts":
            conn.execute("UPDATE story_contexts SET payload_json = 'not json'")
        conn.commit()


def _delete_from_table(story_dir: Path, table: str) -> None:
    with sqlite3.connect(state_db_path(story_dir)) as conn:
        conn.execute(f"DELETE FROM {table}")
        conn.commit()


class TestIntegrityGateAllPassing:
    def test_implementation_all_pass(self, tmp_path: Path) -> None:
        _populate_implementation_story(tmp_path)
        result = IntegrityGate().evaluate(tmp_path, StoryType.IMPLEMENTATION)
        assert result.passed is True
        assert len(result.failed_checks) == 0

    def test_bugfix_all_pass(self, tmp_path: Path) -> None:
        _create_context(tmp_path, StoryType.BUGFIX)
        for phase in ("setup", "implementation", "verify"):
            _create_snapshot(tmp_path, phase)
        _create_decision(tmp_path)
        result = IntegrityGate().evaluate(tmp_path, StoryType.BUGFIX)
        assert result.passed is True

    def test_concept_all_pass(self, tmp_path: Path) -> None:
        _create_context(tmp_path, StoryType.CONCEPT)
        for phase in ("setup", "implementation"):
            _create_snapshot(tmp_path, phase)
        result = IntegrityGate().evaluate(tmp_path, StoryType.CONCEPT)
        assert result.passed is True

    def test_research_all_pass(self, tmp_path: Path) -> None:
        _create_context(tmp_path, StoryType.RESEARCH)
        for phase in ("setup", "implementation"):
            _create_snapshot(tmp_path, phase)
        result = IntegrityGate().evaluate(tmp_path, StoryType.RESEARCH)
        assert result.passed is True


class TestIntegrityGateMissingSnapshot:
    def test_missing_setup_snapshot(self, tmp_path: Path) -> None:
        _create_context(tmp_path)
        _create_snapshot(tmp_path, "implementation")
        _create_snapshot(tmp_path, "verify")
        _create_decision(tmp_path)
        result = IntegrityGate().evaluate(tmp_path, StoryType.IMPLEMENTATION)
        assert result.passed is False
        assert any("setup" in check.dimension for check in result.failed_checks)

    def test_missing_verify_snapshot(self, tmp_path: Path) -> None:
        _create_context(tmp_path)
        _create_snapshot(tmp_path, "setup")
        _create_snapshot(tmp_path, "implementation")
        _create_decision(tmp_path)
        result = IntegrityGate().evaluate(tmp_path, StoryType.IMPLEMENTATION)
        assert result.passed is False
        assert any("verify" in check.dimension for check in result.failed_checks)


class TestIntegrityGateCorruptData:
    def test_corrupt_verify_decision(self, tmp_path: Path) -> None:
        _populate_implementation_story(tmp_path)
        _corrupt_table_payload(tmp_path, "decision_records")
        result = IntegrityGate().evaluate(tmp_path, StoryType.IMPLEMENTATION)
        assert result.passed is False
        assert any(
            check.dimension == "verify_decision"
            for check in result.failed_checks
        )

    def test_missing_structural_artifact_fails(self, tmp_path: Path) -> None:
        _populate_implementation_story(tmp_path)
        _delete_from_table(tmp_path, "artifact_records")
        result = IntegrityGate().evaluate(tmp_path, StoryType.IMPLEMENTATION)
        assert result.passed is False
        assert any(
            check.dimension == "structural_artifact"
            for check in result.failed_checks
        )

    def test_corrupt_phase_snapshot(self, tmp_path: Path) -> None:
        _populate_implementation_story(tmp_path)
        with sqlite3.connect(state_db_path(tmp_path)) as conn:
            conn.execute(
                "UPDATE phase_snapshots "
                "SET payload_json = 'not json' "
                "WHERE phase = 'setup'"
            )
            conn.commit()
        result = IntegrityGate().evaluate(tmp_path, StoryType.IMPLEMENTATION)
        assert result.passed is False
        assert any("setup" in check.dimension for check in result.failed_checks)

    def test_corrupt_context_record(self, tmp_path: Path) -> None:
        _populate_implementation_story(tmp_path)
        _corrupt_table_payload(tmp_path, "story_contexts")
        result = IntegrityGate().evaluate(tmp_path, StoryType.IMPLEMENTATION)
        assert result.passed is False
        assert any(
            check.dimension == "context_record"
            for check in result.failed_checks
        )

    def test_verify_decision_fail(self, tmp_path: Path) -> None:
        _create_context(tmp_path)
        for phase in ("setup", "implementation", "verify"):
            _create_snapshot(tmp_path, phase)
        _create_decision(tmp_path, decision="FAIL")
        result = IntegrityGate().evaluate(tmp_path, StoryType.IMPLEMENTATION)
        assert result.passed is False
        assert any(
            check.dimension == "verify_decision"
            for check in result.failed_checks
        )


class TestIntegrityGateResearchFewerDimensions:
    def test_research_fewer_dimensions(self, tmp_path: Path) -> None:
        _create_context(tmp_path, StoryType.RESEARCH)
        for phase in ("setup", "implementation"):
            _create_snapshot(tmp_path, phase)
        result = IntegrityGate().evaluate(tmp_path, StoryType.RESEARCH)
        assert result.passed is True
        assert "verify_decision" not in {check.dimension for check in result.checks}

    def test_concept_no_verify_decision_check(self, tmp_path: Path) -> None:
        _create_context(tmp_path, StoryType.CONCEPT)
        for phase in ("setup", "implementation"):
            _create_snapshot(tmp_path, phase)
        result = IntegrityGate().evaluate(tmp_path, StoryType.CONCEPT)
        assert result.passed is True
        assert "verify_decision" not in {check.dimension for check in result.checks}


class TestIntegrityGateResultProperties:
    def test_failed_checks_property(self, tmp_path: Path) -> None:
        result = IntegrityGate().evaluate(tmp_path, StoryType.IMPLEMENTATION)
        assert result.passed is False
        assert len(result.failed_checks) > 0
        assert all(check.passed is False for check in result.failed_checks)
