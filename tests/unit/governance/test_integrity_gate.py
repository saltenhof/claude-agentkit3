"""Tests for IntegrityGate against canonical DB-backed runtime records."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from agentkit.bootstrap.composition_root import build_artifact_manager, build_integrity_gate
from agentkit.core_types import PolicyVerdict
from agentkit.exceptions import CorruptStateError
from agentkit.governance.integrity_gate import IntegrityGate
from agentkit.phase_state_store.models import FlowExecution
from agentkit.state_backend.config import ALLOW_SQLITE_ENV, STATE_BACKEND_ENV
from agentkit.state_backend.scope import RuntimeStateScope
from agentkit.state_backend.sqlite_store import state_db_path_for
from agentkit.state_backend.store import (
    record_layer_artifacts,
    record_verify_decision,
    reset_backend_cache_for_tests,
    save_flow_execution,
    save_phase_snapshot,
    save_story_context,
)
from agentkit.story_context_manager.models import (
    PhaseSnapshot,
    PhaseStatus,
    StoryContext,
)
from agentkit.story_context_manager.types import StoryMode, StoryType
from agentkit.verify_system.artifacts import (
    write_layer_artifacts,
    write_verify_decision_artifacts,
)
from agentkit.verify_system.policy_engine.engine import VerifyDecision
from agentkit.verify_system.protocols import LayerResult

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path


@pytest.fixture(autouse=True)
def sqlite_backend_env(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
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
    mode: StoryMode | None = (
        StoryMode.EXECUTION
        if story_type in (StoryType.IMPLEMENTATION, StoryType.BUGFIX)
        else None
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
    # FlowExecution is required by write_layer_artifacts / write_verify_decision_artifacts
    # to resolve a runtime scope with run_id (fail-closed).
    save_flow_execution(
        story_dir,
        FlowExecution(
            project_key="test-project",
            story_id="AG3-001",
            run_id="run-integrity-001",
            flow_id="implementation",
            level="story",
            owner="pipeline_engine",
            status="IN_PROGRESS",
        ),
    )


def _create_snapshot(story_dir: Path, phase: str, status: PhaseStatus = PhaseStatus.COMPLETED) -> None:
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
    """Persist a verify decision artifact for testing.

    Args:
        story_dir: Target story directory.
        decision: ``"PASS"`` or ``"FAIL"``. Since AG3-021, ``PolicyVerdict``
            has only these two values; ``PASS_WITH_WARNINGS`` is gone.
    """
    verdict = PolicyVerdict.PASS if decision == "PASS" else PolicyVerdict.FAIL
    passed = verdict is PolicyVerdict.PASS
    structural = LayerResult(layer="structural", passed=passed, findings=())
    decision_obj = VerifyDecision(
        passed=passed,
        verdict=verdict,
        layer_results=(structural,),
        all_findings=(),
        blocking_findings=(),
        summary="decision summary",
    )
    # Schreibpfad 1: Envelope-Wahrheit via ArtifactManager (AG3-023 §AK12).
    manager = build_artifact_manager(story_dir)
    write_layer_artifacts(
        manager=manager,
        story_id="AG3-001",
        run_id="run-integrity-001",
        layer_results=(structural,),
        attempt_nr=1,
    )
    write_verify_decision_artifacts(
        manager=manager,
        story_id="AG3-001",
        run_id="run-integrity-001",
        decision=decision_obj,
        attempt_nr=1,
    )
    # Schreibpfad 2: FK-69-Materialisierung (qa_stage_results, qa_findings,
    # decision_records) -- IntegrityGate liest aktuell aus decision_records.
    record_layer_artifacts(
        story_dir,
        layer_results=(structural,),
        attempt_nr=1,
    )
    record_verify_decision(
        story_dir,
        decision=decision_obj,
        attempt_nr=1,
    )


def _populate_implementation_story(story_dir: Path) -> None:
    _create_context(story_dir)
    for phase in ("setup", "implementation"):
        _create_snapshot(story_dir, phase)
    _create_decision(story_dir)


def _corrupt_table_payload(story_dir: Path, table: str) -> None:
    with sqlite3.connect(state_db_path_for(story_dir)) as conn:
        if table == "decision_records":
            conn.execute("UPDATE decision_records SET payload_json = 'not json'")
        elif table == "artifact_records":
            # artifact_records removed in 3.4.0; corrupt artifact_envelopes instead
            conn.execute("UPDATE artifact_envelopes SET payload_json = 'not json'")
        elif table == "story_contexts":
            conn.execute("UPDATE story_contexts SET payload_json = 'not json'")
        conn.commit()


def _delete_from_table(story_dir: Path, table: str) -> None:
    with sqlite3.connect(state_db_path_for(story_dir)) as conn:
        # artifact_records removed in 3.4.0; map to artifact_envelopes
        actual_table = "artifact_envelopes" if table == "artifact_records" else table
        conn.execute(f"DELETE FROM {actual_table}")
        conn.commit()


class TestIntegrityGateAllPassing:
    def test_implementation_all_pass(self, tmp_path: Path) -> None:
        story_dir = _story_dir(tmp_path)
        _populate_implementation_story(story_dir)
        result = build_integrity_gate().evaluate(story_dir, StoryType.IMPLEMENTATION)
        assert result.passed is True
        assert len(result.failed_checks) == 0

    def test_bugfix_all_pass(self, tmp_path: Path) -> None:
        story_dir = _story_dir(tmp_path)
        _create_context(story_dir, StoryType.BUGFIX)
        for phase in ("setup", "implementation"):
            _create_snapshot(story_dir, phase)
        _create_decision(story_dir)
        result = build_integrity_gate().evaluate(story_dir, StoryType.BUGFIX)
        assert result.passed is True

    def test_concept_all_pass(self, tmp_path: Path) -> None:
        story_dir = _story_dir(tmp_path)
        _create_context(story_dir, StoryType.CONCEPT)
        for phase in ("setup", "implementation"):
            _create_snapshot(story_dir, phase)
        result = build_integrity_gate().evaluate(story_dir, StoryType.CONCEPT)
        assert result.passed is True

    def test_research_all_pass(self, tmp_path: Path) -> None:
        story_dir = _story_dir(tmp_path)
        _create_context(story_dir, StoryType.RESEARCH)
        for phase in ("setup", "implementation"):
            _create_snapshot(story_dir, phase)
        result = build_integrity_gate().evaluate(story_dir, StoryType.RESEARCH)
        assert result.passed is True


class TestIntegrityGateMissingSnapshot:
    def test_missing_setup_snapshot(self, tmp_path: Path) -> None:
        story_dir = _story_dir(tmp_path)
        _create_context(story_dir)
        _create_snapshot(story_dir, "implementation")
        _create_decision(story_dir)
        result = build_integrity_gate().evaluate(story_dir, StoryType.IMPLEMENTATION)
        assert result.passed is False
        assert any("setup" in check.dimension for check in result.failed_checks)

    def test_missing_implementation_snapshot(self, tmp_path: Path) -> None:
        story_dir = _story_dir(tmp_path)
        _create_context(story_dir)
        _create_snapshot(story_dir, "setup")
        _create_decision(story_dir)
        result = build_integrity_gate().evaluate(story_dir, StoryType.IMPLEMENTATION)
        assert result.passed is False
        assert any(
            "implementation" in check.dimension
            for check in result.failed_checks
        )


class TestIntegrityGateCorruptData:
    def test_corrupt_verify_decision(self, tmp_path: Path) -> None:
        story_dir = _story_dir(tmp_path)
        _populate_implementation_story(story_dir)
        _corrupt_table_payload(story_dir, "decision_records")
        result = build_integrity_gate().evaluate(story_dir, StoryType.IMPLEMENTATION)
        assert result.passed is False
        assert any(
            check.dimension == "verify_decision"
            for check in result.failed_checks
        )

    def test_missing_structural_artifact_fails(self, tmp_path: Path) -> None:
        story_dir = _story_dir(tmp_path)
        _populate_implementation_story(story_dir)
        _delete_from_table(story_dir, "artifact_records")
        result = build_integrity_gate().evaluate(story_dir, StoryType.IMPLEMENTATION)
        assert result.passed is False
        assert any(
            check.dimension == "structural_artifact"
            for check in result.failed_checks
        )

    def test_corrupt_phase_snapshot(self, tmp_path: Path) -> None:
        story_dir = _story_dir(tmp_path)
        _populate_implementation_story(story_dir)
        with sqlite3.connect(state_db_path_for(story_dir)) as conn:
            conn.execute(
                "UPDATE phase_snapshots "
                "SET payload_json = 'not json' "
                "WHERE phase = 'setup'"
            )
            conn.commit()
        result = build_integrity_gate().evaluate(story_dir, StoryType.IMPLEMENTATION)
        assert result.passed is False
        assert any("setup" in check.dimension for check in result.failed_checks)

    def test_corrupt_context_record(self, tmp_path: Path) -> None:
        story_dir = _story_dir(tmp_path)
        _populate_implementation_story(story_dir)
        _corrupt_table_payload(story_dir, "story_contexts")
        result = build_integrity_gate().evaluate(story_dir, StoryType.IMPLEMENTATION)
        assert result.passed is False
        assert any(
            check.dimension == "context_record"
            for check in result.failed_checks
        )

    def test_verify_decision_fail(self, tmp_path: Path) -> None:
        story_dir = _story_dir(tmp_path)
        _create_context(story_dir)
        for phase in ("setup", "implementation"):
            _create_snapshot(story_dir, phase)
        _create_decision(story_dir, decision="FAIL")
        result = build_integrity_gate().evaluate(story_dir, StoryType.IMPLEMENTATION)
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
        result = build_integrity_gate().evaluate(story_dir, StoryType.RESEARCH)
        assert result.passed is True
        assert "verify_decision" not in {check.dimension for check in result.checks}

    def test_concept_no_verify_decision_check(self, tmp_path: Path) -> None:
        story_dir = _story_dir(tmp_path)
        _create_context(story_dir, StoryType.CONCEPT)
        for phase in ("setup", "implementation"):
            _create_snapshot(story_dir, phase)
        result = build_integrity_gate().evaluate(story_dir, StoryType.CONCEPT)
        assert result.passed is True
        assert "verify_decision" not in {check.dimension for check in result.checks}


class TestIntegrityGateResultProperties:
    def test_failed_checks_property(self, tmp_path: Path) -> None:
        result = build_integrity_gate().evaluate(
            _story_dir(tmp_path),
            StoryType.IMPLEMENTATION,
        )
        assert result.passed is False
        assert len(result.failed_checks) > 0
        assert all(check.passed is False for check in result.failed_checks)


# ---------------------------------------------------------------------------
# Recording test-doubles for IntegrityGateStatePort (Fix E9)
# ---------------------------------------------------------------------------


class _RecordingStatePort:
    """Recording test-double for IntegrityGateStatePort.

    Configurable: each method has a corresponding ``_*_result`` attribute
    that controls the return value.  Calls are recorded in ``calls`` for
    assertion.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self._completed_snapshot: bool = True
        self._structural_artifact: bool = True
        self._structural_artifact_for_scope: bool = True
        self._valid_context: bool = True
        self._valid_phase_state: bool = True
        self._latest_verify_decision: dict[str, object] | None = {
            "status": "PASS", "passed": True
        }
        self._latest_verify_decision_for_scope: dict[str, object] | None = {
            "status": "PASS", "passed": True
        }
        self._phase_state_record: object | None = None
        self._runtime_scope_result: RuntimeStateScope | None = None
        self._resolve_scope_raise: type[Exception] | None = None

    def has_completed_snapshot(self, story_dir: object, phase: str) -> bool:
        self.calls.append(("has_completed_snapshot", phase))
        return self._completed_snapshot

    def has_structural_artifact(self, story_dir: object) -> bool:
        self.calls.append(("has_structural_artifact", story_dir))
        return self._structural_artifact

    def has_structural_artifact_for_scope(self, scope: RuntimeStateScope) -> bool:
        self.calls.append(("has_structural_artifact_for_scope", scope))
        return self._structural_artifact_for_scope

    def has_valid_context(self, story_dir: object) -> bool:
        self.calls.append(("has_valid_context", story_dir))
        return self._valid_context

    def has_valid_phase_state(self, story_dir: object) -> bool:
        self.calls.append(("has_valid_phase_state", story_dir))
        return self._valid_phase_state

    def load_latest_verify_decision(
        self, story_dir: object
    ) -> dict[str, object] | None:
        self.calls.append(("load_latest_verify_decision", story_dir))
        return self._latest_verify_decision

    def load_latest_verify_decision_for_scope(
        self, scope: RuntimeStateScope
    ) -> dict[str, object] | None:
        self.calls.append(("load_latest_verify_decision_for_scope", scope))
        return self._latest_verify_decision_for_scope

    def read_phase_state_record(self, story_dir: object) -> object | None:
        self.calls.append(("read_phase_state_record", story_dir))
        if self._phase_state_record is CorruptStateError:
            raise CorruptStateError("simulated corrupt")
        return self._phase_state_record

    def resolve_runtime_scope(self, story_dir: object) -> RuntimeStateScope:
        self.calls.append(("resolve_runtime_scope", story_dir))
        if self._resolve_scope_raise is not None:
            raise self._resolve_scope_raise("simulated")
        if self._runtime_scope_result is not None:
            return self._runtime_scope_result
        raise CorruptStateError("no scope configured")


class TestIntegrityGateWithRecordingPort:
    """Validate IntegrityGate DI path using a recording state-port test-double.

    These tests replace the former monkeypatch-based ``TestIntegrityGateStaticBranches``
    tests, which patched module-level symbols that no longer exist after Fix E9.
    """

    def test_structural_artifact_uses_scope_reader_when_scope_has_run_id(
        self, tmp_path: Path
    ) -> None:
        """When runtime_scope has run_id, has_structural_artifact_for_scope is called."""
        port = _RecordingStatePort()
        scope = RuntimeStateScope(
            project_key="test-project",
            story_id="AG3-001",
            story_dir=tmp_path,
            run_id="run-1",
        )
        port._runtime_scope_result = scope
        port._resolve_scope_raise = None

        gate = IntegrityGate(state_port=port)  # type: ignore[arg-type]
        result = gate._check_structural_artifact(tmp_path, scope)

        assert result.passed is True
        scope_calls = [
            c for c in port.calls if c[0] == "has_structural_artifact_for_scope"
        ]
        assert scope_calls, "has_structural_artifact_for_scope should have been called"
        fallback_calls = [c for c in port.calls if c[0] == "has_structural_artifact"]
        assert not fallback_calls, "story_dir fallback must not be used when scope has run_id"

    def test_structural_artifact_falls_back_to_story_dir_when_scope_none(
        self, tmp_path: Path
    ) -> None:
        """When runtime_scope is None, has_structural_artifact(story_dir) is used."""
        port = _RecordingStatePort()

        gate = IntegrityGate(state_port=port)  # type: ignore[arg-type]
        result = gate._check_structural_artifact(tmp_path, None)

        assert result.passed is True
        fallback_calls = [c for c in port.calls if c[0] == "has_structural_artifact"]
        assert fallback_calls, "story_dir fallback should be called when scope is None"

    def test_verify_decision_uses_scope_reader_when_scope_has_run_id(
        self, tmp_path: Path
    ) -> None:
        """When runtime_scope has run_id, load_latest_verify_decision_for_scope is called."""
        port = _RecordingStatePort()
        scope = RuntimeStateScope(
            project_key="test-project",
            story_id="AG3-001",
            story_dir=tmp_path,
            run_id="run-1",
        )

        gate = IntegrityGate(state_port=port)  # type: ignore[arg-type]
        result = gate._check_verify_decision(tmp_path, scope)

        assert result.passed is True
        scope_calls = [
            c for c in port.calls
            if c[0] == "load_latest_verify_decision_for_scope"
        ]
        assert scope_calls
        fallback_calls = [
            c for c in port.calls if c[0] == "load_latest_verify_decision"
        ]
        assert not fallback_calls, "story_dir fallback must not be used when scope has run_id"

    def test_phase_state_record_reports_corrupt_state(self, tmp_path: Path) -> None:
        """CorruptStateError from read_phase_state_record yields failed check."""
        port = _RecordingStatePort()
        port._phase_state_record = CorruptStateError  # sentinel: raise on access

        gate = IntegrityGate(state_port=port)  # type: ignore[arg-type]
        result = gate._check_phase_state_record(tmp_path)

        assert result.passed is False
        assert result.dimension == "phase_state_record"

    def test_phase_state_record_fails_when_existing_record_is_invalid(
        self, tmp_path: Path
    ) -> None:
        """Non-None phase state record + has_valid_phase_state=False → failed check."""
        port = _RecordingStatePort()
        port._phase_state_record = object()  # non-None → not absent
        port._valid_phase_state = False

        gate = IntegrityGate(state_port=port)  # type: ignore[arg-type]
        result = gate._check_phase_state_record(tmp_path)

        assert result.passed is False
        assert result.message == "Missing or invalid canonical phase state record"

    def test_evaluate_passes_all_checks_with_recording_port(
        self, tmp_path: Path
    ) -> None:
        """Full evaluate() path passes when all port methods return positive results."""
        port = _RecordingStatePort()
        scope = RuntimeStateScope(
            project_key="p",
            story_id="AG3-001",
            story_dir=tmp_path,
            run_id="run-1",
        )
        port._runtime_scope_result = scope
        port._resolve_scope_raise = None
        port._phase_state_record = object()  # non-None, valid_phase_state=True

        gate = IntegrityGate(state_port=port)  # type: ignore[arg-type]
        result = gate.evaluate(tmp_path, StoryType.IMPLEMENTATION)

        assert result.passed is True
        assert result.failed_checks == ()

    def test_build_integrity_gate_wires_state_backend_adapter(self) -> None:
        """build_integrity_gate() wires StateBackendIntegrityGateStateAdapter as state_port."""
        from agentkit.state_backend.store.integrity_gate_repository import (
            StateBackendIntegrityGateStateAdapter,
        )

        gate = build_integrity_gate()
        assert isinstance(gate._state_port, StateBackendIntegrityGateStateAdapter)
