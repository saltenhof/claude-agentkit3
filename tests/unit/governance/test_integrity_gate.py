"""Tests for IntegrityGate against canonical DB-backed runtime records."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from agentkit.exceptions import CorruptStateError
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
from agentkit.state_backend.config import ALLOW_SQLITE_ENV, STATE_BACKEND_ENV
from agentkit.state_backend.scope import RuntimeStateScope
from agentkit.state_backend.store import reset_backend_cache_for_tests
from agentkit.story_context_manager.models import PhaseSnapshot, StoryContext
from agentkit.story_context_manager.types import StoryMode, StoryType

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture(autouse=True)
def sqlite_backend_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(STATE_BACKEND_ENV, "sqlite")
    monkeypatch.setenv(ALLOW_SQLITE_ENV, "1")
    monkeypatch.delenv("AGENTKIT_STATE_DATABASE_URL", raising=False)
    reset_backend_cache_for_tests()
    yield
    reset_backend_cache_for_tests()


def _story_dir(root: Path, story_id: str = "AG3-001") -> Path:
    story_dir = root / "stories" / story_id
    story_dir.mkdir(parents=True, exist_ok=True)
    return story_dir


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
            project_key="test-project",
            story_id="AG3-001",
            story_type=story_type,
            execution_route=mode,
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
        story_dir = _story_dir(tmp_path)
        _populate_implementation_story(story_dir)
        result = IntegrityGate().evaluate(story_dir, StoryType.IMPLEMENTATION)
        assert result.passed is True
        assert len(result.failed_checks) == 0

    def test_bugfix_all_pass(self, tmp_path: Path) -> None:
        story_dir = _story_dir(tmp_path)
        _create_context(story_dir, StoryType.BUGFIX)
        for phase in ("setup", "implementation", "verify"):
            _create_snapshot(story_dir, phase)
        _create_decision(story_dir)
        result = IntegrityGate().evaluate(story_dir, StoryType.BUGFIX)
        assert result.passed is True

    def test_concept_all_pass(self, tmp_path: Path) -> None:
        story_dir = _story_dir(tmp_path)
        _create_context(story_dir, StoryType.CONCEPT)
        for phase in ("setup", "implementation"):
            _create_snapshot(story_dir, phase)
        result = IntegrityGate().evaluate(story_dir, StoryType.CONCEPT)
        assert result.passed is True

    def test_research_all_pass(self, tmp_path: Path) -> None:
        story_dir = _story_dir(tmp_path)
        _create_context(story_dir, StoryType.RESEARCH)
        for phase in ("setup", "implementation"):
            _create_snapshot(story_dir, phase)
        result = IntegrityGate().evaluate(story_dir, StoryType.RESEARCH)
        assert result.passed is True


class TestIntegrityGateMissingSnapshot:
    def test_missing_setup_snapshot(self, tmp_path: Path) -> None:
        story_dir = _story_dir(tmp_path)
        _create_context(story_dir)
        _create_snapshot(story_dir, "implementation")
        _create_snapshot(story_dir, "verify")
        _create_decision(story_dir)
        result = IntegrityGate().evaluate(story_dir, StoryType.IMPLEMENTATION)
        assert result.passed is False
        assert any("setup" in check.dimension for check in result.failed_checks)

    def test_missing_verify_snapshot(self, tmp_path: Path) -> None:
        story_dir = _story_dir(tmp_path)
        _create_context(story_dir)
        _create_snapshot(story_dir, "setup")
        _create_snapshot(story_dir, "implementation")
        _create_decision(story_dir)
        result = IntegrityGate().evaluate(story_dir, StoryType.IMPLEMENTATION)
        assert result.passed is False
        assert any("verify" in check.dimension for check in result.failed_checks)


class TestIntegrityGateCorruptData:
    def test_corrupt_verify_decision(self, tmp_path: Path) -> None:
        story_dir = _story_dir(tmp_path)
        _populate_implementation_story(story_dir)
        _corrupt_table_payload(story_dir, "decision_records")
        result = IntegrityGate().evaluate(story_dir, StoryType.IMPLEMENTATION)
        assert result.passed is False
        assert any(
            check.dimension == "verify_decision"
            for check in result.failed_checks
        )

    def test_missing_structural_artifact_fails(self, tmp_path: Path) -> None:
        story_dir = _story_dir(tmp_path)
        _populate_implementation_story(story_dir)
        _delete_from_table(story_dir, "artifact_records")
        result = IntegrityGate().evaluate(story_dir, StoryType.IMPLEMENTATION)
        assert result.passed is False
        assert any(
            check.dimension == "structural_artifact"
            for check in result.failed_checks
        )

    def test_corrupt_phase_snapshot(self, tmp_path: Path) -> None:
        story_dir = _story_dir(tmp_path)
        _populate_implementation_story(story_dir)
        with sqlite3.connect(state_db_path(story_dir)) as conn:
            conn.execute(
                "UPDATE phase_snapshots "
                "SET payload_json = 'not json' "
                "WHERE phase = 'setup'"
            )
            conn.commit()
        result = IntegrityGate().evaluate(story_dir, StoryType.IMPLEMENTATION)
        assert result.passed is False
        assert any("setup" in check.dimension for check in result.failed_checks)

    def test_corrupt_context_record(self, tmp_path: Path) -> None:
        story_dir = _story_dir(tmp_path)
        _populate_implementation_story(story_dir)
        _corrupt_table_payload(story_dir, "story_contexts")
        result = IntegrityGate().evaluate(story_dir, StoryType.IMPLEMENTATION)
        assert result.passed is False
        assert any(
            check.dimension == "context_record"
            for check in result.failed_checks
        )

    def test_verify_decision_fail(self, tmp_path: Path) -> None:
        story_dir = _story_dir(tmp_path)
        _create_context(story_dir)
        for phase in ("setup", "implementation", "verify"):
            _create_snapshot(story_dir, phase)
        _create_decision(story_dir, decision="FAIL")
        result = IntegrityGate().evaluate(story_dir, StoryType.IMPLEMENTATION)
        assert result.passed is False
        assert any(
            check.dimension == "verify_decision"
            for check in result.failed_checks
        )


class TestIntegrityGateResearchFewerDimensions:
    def test_research_fewer_dimensions(self, tmp_path: Path) -> None:
        story_dir = _story_dir(tmp_path)
        _create_context(story_dir, StoryType.RESEARCH)
        for phase in ("setup", "implementation"):
            _create_snapshot(story_dir, phase)
        result = IntegrityGate().evaluate(story_dir, StoryType.RESEARCH)
        assert result.passed is True
        assert "verify_decision" not in {check.dimension for check in result.checks}

    def test_concept_no_verify_decision_check(self, tmp_path: Path) -> None:
        story_dir = _story_dir(tmp_path)
        _create_context(story_dir, StoryType.CONCEPT)
        for phase in ("setup", "implementation"):
            _create_snapshot(story_dir, phase)
        result = IntegrityGate().evaluate(story_dir, StoryType.CONCEPT)
        assert result.passed is True
        assert "verify_decision" not in {check.dimension for check in result.checks}


class TestIntegrityGateResultProperties:
    def test_failed_checks_property(self, tmp_path: Path) -> None:
        result = IntegrityGate().evaluate(
            _story_dir(tmp_path),
            StoryType.IMPLEMENTATION,
        )
        assert result.passed is False
        assert len(result.failed_checks) > 0
        assert all(check.passed is False for check in result.failed_checks)


class TestIntegrityGateStaticBranches:
    def test_structural_artifact_uses_runtime_scope_reader(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        scope = RuntimeStateScope(
            project_key="test-project",
            story_id="AG3-001",
            story_dir=tmp_path,
            run_id="run-1",
        )
        seen: list[RuntimeStateScope] = []

        monkeypatch.setattr(
            "agentkit.governance.integrity_gate.backend_has_structural_artifact_for_scope",
            lambda runtime_scope: seen.append(runtime_scope) or True,
        )
        monkeypatch.setattr(
            "agentkit.governance.integrity_gate.backend_has_structural_artifact",
            lambda story_dir: pytest.fail("story_dir fallback should not be used"),
        )

        result = IntegrityGate._check_structural_artifact(tmp_path, scope)

        assert result.passed is True
        assert seen == [scope]

    def test_verify_decision_uses_runtime_scope_reader(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        scope = RuntimeStateScope(
            project_key="test-project",
            story_id="AG3-001",
            story_dir=tmp_path,
            run_id="run-1",
        )
        seen: list[RuntimeStateScope] = []

        def fake_scope_loader(runtime_scope: RuntimeStateScope) -> dict[str, object]:
            seen.append(runtime_scope)
            return {"status": "PASS", "passed": True}

        monkeypatch.setattr(
            "agentkit.governance.integrity_gate.load_latest_verify_decision_for_scope",
            fake_scope_loader,
        )
        monkeypatch.setattr(
            "agentkit.governance.integrity_gate.verify_decision_passed",
            lambda payload: True,
        )
        monkeypatch.setattr(
            "agentkit.governance.integrity_gate.load_latest_verify_decision",
            lambda story_dir: pytest.fail("story_dir fallback should not be used"),
        )

        result = IntegrityGate._check_verify_decision(tmp_path, scope)

        assert result.passed is True
        assert seen == [scope]

    def test_phase_state_record_reports_corrupt_state(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.setattr(
            "agentkit.governance.integrity_gate.read_phase_state_record",
            lambda story_dir: (_ for _ in ()).throw(CorruptStateError("broken")),
        )

        result = IntegrityGate._check_phase_state_record(tmp_path)

        assert result.passed is False
        assert result.dimension == "phase_state_record"

    def test_phase_state_record_fails_when_existing_record_is_invalid(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.setattr(
            "agentkit.governance.integrity_gate.read_phase_state_record",
            lambda story_dir: object(),
        )
        monkeypatch.setattr(
            "agentkit.governance.integrity_gate.backend_has_valid_phase_state",
            lambda story_dir: False,
        )

        result = IntegrityGate._check_phase_state_record(tmp_path)

        assert result.passed is False
        assert result.message == "Missing or invalid canonical phase state record"
