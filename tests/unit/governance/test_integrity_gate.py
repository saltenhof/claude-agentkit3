"""Tests for IntegrityGate against canonical DB-backed runtime records.

Drives ``build_integrity_gate().evaluate`` over a populated SQLite story with a
substantive, FK-35-conformant QA artifact set (Remediation E-A: the dimensions
verify producer / status / depth / threshold, not mere existence).  Dim 9 is
exercised through a stubbed AG3-052 capability seam (no live Sonar).
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from agentkit.bootstrap.composition_root import build_artifact_manager
from agentkit.core_types import PolicyVerdict
from agentkit.exceptions import CorruptStateError
from agentkit.governance.integrity_gate import (
    IntegrityDimension,
    IntegrityGate,
    IntegrityGateStatus,
)
from agentkit.governance.integrity_gate.dim9_sonar import SONAR_NOT_GREEN
from agentkit.phase_state_store.models import FlowExecution
from agentkit.pipeline_engine.phase_executor import (
    PhaseSnapshot,
    PhaseStatus,
)
from agentkit.state_backend.config import ALLOW_SQLITE_ENV, STATE_BACKEND_ENV
from agentkit.state_backend.sqlite_store import state_db_path_for
from agentkit.state_backend.store import (
    record_layer_artifacts,
    record_verify_decision,
    reset_backend_cache_for_tests,
    save_flow_execution,
    save_phase_snapshot,
    save_story_context,
)
from agentkit.state_backend.store.integrity_gate_repository import (
    StateBackendIntegrityGateStateAdapter,
)
from agentkit.story_context_manager.models import StoryContext
from agentkit.story_context_manager.story_model import WireStoryMode
from agentkit.story_context_manager.types import StoryMode, StoryType
from agentkit.verify_system.artifacts import (
    write_layer_artifacts,
    write_verify_decision_artifacts,
)
from agentkit.verify_system.policy_engine.engine import VerifyDecision
from agentkit.verify_system.protocols import (
    Finding,
    LayerResult,
    Severity,
    TrustClass,
)
from agentkit.verify_system.sonarqube_gate import SonarApplicability

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

    from agentkit.state_backend.scope import RuntimeStateScope

_RUN = "run-integrity-001"
_CODE_PHASES = ("setup", "implementation", "closure")
_NONCODE_PHASES = ("setup", "closure")


@pytest.fixture(autouse=True)
def sqlite_backend_env(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    monkeypatch.setenv(STATE_BACKEND_ENV, "sqlite")
    monkeypatch.setenv(ALLOW_SQLITE_ENV, "1")
    monkeypatch.delenv("AGENTKIT_STATE_DATABASE_URL", raising=False)
    reset_backend_cache_for_tests()
    yield
    reset_backend_cache_for_tests()


# ---------------------------------------------------------------------------
# Stubbed AG3-052 Dim-9 capability seam (no live Sonar).
# ---------------------------------------------------------------------------


def _green_resolution() -> object:
    """A green AG3-052 capability resolution (the canonical SonarGateOutcome)."""
    from agentkit.governance.integrity_gate.dim9_sonar import Dim9Resolution
    from agentkit.verify_system.sonarqube_gate import SonarGateOutcome

    return Dim9Resolution(
        applicability=SonarApplicability.APPLICABLE,
        outcome=SonarGateOutcome(
            applicability=SonarApplicability.APPLICABLE,
            passed=True,
            gate_status="sonarqube_gate_passed",
        ),
    )


def _not_applicable_resolution() -> object:
    from agentkit.governance.integrity_gate.dim9_sonar import Dim9Resolution

    return Dim9Resolution(
        applicability=SonarApplicability.NOT_APPLICABLE_UNAVAILABLE, outcome=None
    )


class _StubSonarPort:
    def __init__(self, resolution: object) -> None:
        self._resolution = resolution

    def resolve_dim9_outcome(self, gate_ctx: object) -> object:
        _ = gate_ctx
        return self._resolution


def _green_gate() -> IntegrityGate:
    """IntegrityGate wired with the canonical envelope validator + green Dim 9."""
    from agentkit.artifacts import EnvelopeValidator
    from agentkit.bootstrap.composition_root import build_producer_registry

    return IntegrityGate(
        state_port=StateBackendIntegrityGateStateAdapter(),
        envelope_validator=EnvelopeValidator(build_producer_registry()),
        sonar_port=_StubSonarPort(_green_resolution()),  # type: ignore[arg-type]
    )


def _noncode_gate() -> IntegrityGate:
    from agentkit.artifacts import EnvelopeValidator
    from agentkit.bootstrap.composition_root import build_producer_registry

    return IntegrityGate(
        state_port=StateBackendIntegrityGateStateAdapter(),
        envelope_validator=EnvelopeValidator(build_producer_registry()),
        sonar_port=_StubSonarPort(_not_applicable_resolution()),  # type: ignore[arg-type]
    )


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
            mode=WireStoryMode.STANDARD,
            title="Integrity Gate Test",
            # FK-35 §35.2.4 Dim 8: context built at setup, strictly before the
            # QA-subflow decision flow_end (stamped at QA write time, ~now).
            created_at=datetime(2026, 4, 7, 12, 0, 0, tzinfo=UTC),
        ),
    )
    save_flow_execution(
        story_dir,
        FlowExecution(
            project_key="test-project",
            story_id="AG3-001",
            run_id=_RUN,
            flow_id="implementation",
            level="story",
            owner="pipeline_engine",
            status="IN_PROGRESS",
        ),
    )


def _create_snapshot(
    story_dir: Path, phase: str, status: PhaseStatus = PhaseStatus.COMPLETED
) -> None:
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


def _structural_result(*, passed: bool = True) -> LayerResult:
    findings = tuple(
        Finding(
            layer="structural",
            check=f"informational_check_{i}",
            severity=Severity.MINOR,
            message=(
                f"informational structural finding {i} with enough descriptive "
                "text to push the canonical envelope payload past 500 bytes"
            ),
            trust_class=TrustClass.SYSTEM,
            file_path=f"src/agentkit/module_{i}.py",
            line_number=i,
        )
        for i in range(3)
    )
    return LayerResult(
        layer="structural",
        passed=passed,
        findings=findings,
        metadata={"total_checks": 6},
    )


def _full_layers(*, passed: bool = True) -> tuple[LayerResult, ...]:
    return (
        _structural_result(passed=passed),
        LayerResult(layer="qa_review", passed=passed, findings=()),
        LayerResult(layer="semantic_review", passed=passed, findings=()),
        LayerResult(
            layer="adversarial",
            passed=passed,
            findings=(),
            metadata={"summary": "adversarial; " + ("edge probe " * 25)},
        ),
    )


def _create_decision(story_dir: Path, decision: str = "PASS") -> None:
    """Persist the full FK-35-conformant QA artifact set for testing."""
    verdict = PolicyVerdict.PASS if decision == "PASS" else PolicyVerdict.FAIL
    passed = verdict is PolicyVerdict.PASS
    layers = _full_layers(passed=passed)
    decision_obj = VerifyDecision(
        passed=passed,
        verdict=verdict,
        layer_results=layers,
        all_findings=(),
        blocking_findings=(),
        summary="decision summary",
        max_major_findings=0,
    )
    manager = build_artifact_manager(story_dir)
    write_layer_artifacts(
        manager=manager,
        story_id="AG3-001",
        run_id=_RUN,
        layer_results=layers,
        attempt_nr=1,
    )
    write_verify_decision_artifacts(
        manager=manager,
        story_id="AG3-001",
        run_id=_RUN,
        decision=decision_obj,
        attempt_nr=1,
    )
    record_layer_artifacts(story_dir, layer_results=layers, attempt_nr=1)
    record_verify_decision(story_dir, decision=decision_obj, attempt_nr=1)


def _populate_implementation_story(story_dir: Path) -> None:
    _create_context(story_dir)
    for phase in _CODE_PHASES:
        _create_snapshot(story_dir, phase)
    _create_decision(story_dir)


def _corrupt_table_payload(story_dir: Path, table: str) -> None:
    with sqlite3.connect(state_db_path_for(story_dir)) as conn:
        if table == "decision_records":
            conn.execute("UPDATE decision_records SET payload_json = 'not json'")
        elif table == "artifact_records":
            conn.execute("UPDATE artifact_envelopes SET payload_json = 'not json'")
        elif table == "story_contexts":
            conn.execute("UPDATE story_contexts SET payload_json = 'not json'")
        conn.commit()


def _delete_from_table(story_dir: Path, table: str) -> None:
    with sqlite3.connect(state_db_path_for(story_dir)) as conn:
        actual_table = "artifact_envelopes" if table == "artifact_records" else table
        conn.execute(f"DELETE FROM {actual_table}")
        conn.commit()


class TestIntegrityGateAllPassing:
    def test_implementation_all_pass(self, tmp_path: Path) -> None:
        story_dir = _story_dir(tmp_path)
        _populate_implementation_story(story_dir)
        result = _green_gate().evaluate(story_dir, StoryType.IMPLEMENTATION)
        assert result.passed is True
        assert result.failed_dimensions == ()

    def test_bugfix_all_pass(self, tmp_path: Path) -> None:
        story_dir = _story_dir(tmp_path)
        _create_context(story_dir, StoryType.BUGFIX)
        for phase in _CODE_PHASES:
            _create_snapshot(story_dir, phase)
        _create_decision(story_dir)
        result = _green_gate().evaluate(story_dir, StoryType.BUGFIX)
        assert result.passed is True

    def test_concept_all_pass(self, tmp_path: Path) -> None:
        story_dir = _story_dir(tmp_path)
        _create_context(story_dir, StoryType.CONCEPT)
        for phase in _NONCODE_PHASES:
            _create_snapshot(story_dir, phase)
        # Concept carries the mandatory structural artefact (Dim 1/3).
        manager = build_artifact_manager(story_dir)
        write_layer_artifacts(
            manager=manager, story_id="AG3-001", run_id=_RUN,
            layer_results=(_structural_result(),), attempt_nr=1,
        )
        record_layer_artifacts(
            story_dir, layer_results=(_structural_result(),), attempt_nr=1
        )
        result = _noncode_gate().evaluate(story_dir, StoryType.CONCEPT)
        assert result.passed is True

    def test_research_all_pass(self, tmp_path: Path) -> None:
        story_dir = _story_dir(tmp_path)
        _create_context(story_dir, StoryType.RESEARCH)
        for phase in _NONCODE_PHASES:
            _create_snapshot(story_dir, phase)
        manager = build_artifact_manager(story_dir)
        write_layer_artifacts(
            manager=manager, story_id="AG3-001", run_id=_RUN,
            layer_results=(_structural_result(),), attempt_nr=1,
        )
        record_layer_artifacts(
            story_dir, layer_results=(_structural_result(),), attempt_nr=1
        )
        result = _noncode_gate().evaluate(story_dir, StoryType.RESEARCH)
        assert result.passed is True


class _PoisonedSonarPort:
    """A Dim-9 capability port that MUST NOT be consulted (AG3-053 fresh path).

    When the Closure barrier supplies a fresh attestation, Dim 9 verifies exactly
    it and never re-resolves via the worktree port. This port raises if called, so
    a test fails loudly if the gate falls back to the stale worktree re-read.
    """

    def resolve_dim9_outcome(self, gate_ctx: object) -> object:
        _ = gate_ctx
        msg = "sonar_port consulted despite a supplied fresh attestation (no re-read!)"
        raise AssertionError(msg)


def _fresh_attestation_obj(commit_sha: str) -> object:
    from agentkit.config.models import SonarQubeConfig
    from agentkit.governance.integrity_gate.dim9_sonar import FreshAttestation
    from agentkit.verify_system.sonarqube_gate import (
        SonarApplicability,
        SonarGateOutcome,
    )
    from agentkit.verify_system.sonarqube_gate.attestation import (
        ATTESTATION_STATUS_READ,
        SonarAttestation,
    )

    attestation = SonarAttestation(
        commit_sha=commit_sha,
        tree_hash="2222tree2222",
        analysis_id="analysis-fresh-001",
        ce_task_id="ce-fresh-001",
        quality_gate_status="OK",
        quality_gate_hash="qg-hash",
        quality_profile_hash="qp-hash",
        analysis_scope_hash="scope-hash",
        new_code_definition="previous_version",
        exception_ledger_hash="ledger-hash",
        last_analyzed_revision=commit_sha,
        sonarqube_version="26.4",
        branch_plugin_version="1.23.0",
        scanner_version="5.0.1",
        status=ATTESTATION_STATUS_READ,
    )
    return FreshAttestation(
        attestation=attestation,
        expected_main_revision=commit_sha,
        config=SonarQubeConfig(
            available=True,
            enabled=True,
            base_url="https://sonar.example",
            token_env="SONAR_TOKEN",
            scanner_version="5.0.1",
        ),
        gate_outcome=SonarGateOutcome(
            applicability=SonarApplicability.APPLICABLE,
            passed=True,
            gate_status="sonarqube_gate_passed",
        ),
    )


class TestIntegrityGateFreshAttestationWiring:
    """AG3-053: the gate verifies the FRESH attestation, never re-reading (35.2.4a)."""

    def test_fresh_attestation_path_passes_dim9_without_consulting_port(
        self, tmp_path: Path
    ) -> None:
        from agentkit.artifacts import EnvelopeValidator
        from agentkit.bootstrap.composition_root import build_producer_registry

        story_dir = _story_dir(tmp_path)
        _populate_implementation_story(story_dir)
        gate = IntegrityGate(
            state_port=StateBackendIntegrityGateStateAdapter(),
            envelope_validator=EnvelopeValidator(build_producer_registry()),
            sonar_port=_PoisonedSonarPort(),  # type: ignore[arg-type]
        )
        result = gate.evaluate(
            story_dir,
            StoryType.IMPLEMENTATION,
            fresh_attestation=_fresh_attestation_obj("1111candidate1111"),  # type: ignore[arg-type]
        )
        # Dim 9 passed via the fresh path; the poisoned port was never consulted.
        assert result.passed is True
        dim9 = result.dimension_results[IntegrityDimension.SONARQUBE_GREEN]
        assert dim9.passed

    def test_fresh_attestation_red_qg_fails_dim9_via_fresh_path(
        self, tmp_path: Path
    ) -> None:
        from agentkit.artifacts import EnvelopeValidator
        from agentkit.bootstrap.composition_root import build_producer_registry
        from agentkit.config.models import SonarQubeConfig
        from agentkit.governance.integrity_gate.dim9_sonar import FreshAttestation
        from agentkit.verify_system.sonarqube_gate import (
            SonarApplicability,
            SonarGateOutcome,
        )
        from agentkit.verify_system.sonarqube_gate.attestation import (
            ATTESTATION_STATUS_READ,
            SonarAttestation,
        )

        story_dir = _story_dir(tmp_path)
        _populate_implementation_story(story_dir)
        # FIX-1: the green verdict is the FULL AG3-052 gate outcome. The
        # attestation's pre-apply QG is only the stale-check input; a red gate
        # outcome (post-apply re-read found it not green) fails Dim 9 closed.
        red = SonarAttestation(
            commit_sha="1111c1111",
            tree_hash="2222t2222",
            analysis_id="a-1",
            ce_task_id="ce-1",
            quality_gate_status="OK",
            quality_gate_hash="qg",
            quality_profile_hash="qp",
            analysis_scope_hash="scope",
            new_code_definition="previous_version",
            exception_ledger_hash="ledger",
            last_analyzed_revision="1111c1111",
            sonarqube_version="26.4",
            branch_plugin_version="1.23.0",
            scanner_version="5.0.1",
            status=ATTESTATION_STATUS_READ,
        )
        fresh = FreshAttestation(
            attestation=red,
            expected_main_revision="1111c1111",
            config=SonarQubeConfig(
                available=True, enabled=True, base_url="https://s",
                token_env="T", scanner_version="5.0.1",
            ),
            gate_outcome=SonarGateOutcome(
                applicability=SonarApplicability.APPLICABLE,
                passed=False,
                gate_status="failed",
                failure_reason="red_gate: overall_open_issues_post=2",
            ),
        )
        gate = IntegrityGate(
            state_port=StateBackendIntegrityGateStateAdapter(),
            envelope_validator=EnvelopeValidator(build_producer_registry()),
            sonar_port=_PoisonedSonarPort(),  # type: ignore[arg-type]
        )
        result = gate.evaluate(
            story_dir, StoryType.IMPLEMENTATION, fresh_attestation=fresh,  # type: ignore[arg-type]
        )
        assert result.passed is False
        assert result.overall is IntegrityGateStatus.ESCALATED
        assert result.failure_reason == SONAR_NOT_GREEN


class TestIntegrityGateCorruptData:
    def test_corrupt_verify_decision_fails(self, tmp_path: Path) -> None:
        story_dir = _story_dir(tmp_path)
        _populate_implementation_story(story_dir)
        _corrupt_table_payload(story_dir, "decision_records")
        result = _green_gate().evaluate(story_dir, StoryType.IMPLEMENTATION)
        assert result.passed is False

    def test_missing_structural_artifact_fails(self, tmp_path: Path) -> None:
        story_dir = _story_dir(tmp_path)
        _populate_implementation_story(story_dir)
        _delete_from_table(story_dir, "artifact_records")
        result = _green_gate().evaluate(story_dir, StoryType.IMPLEMENTATION)
        assert result.passed is False
        assert result.failure_reason == "MISSING_STRUCTURAL"

    def test_corrupt_context_record_fails(self, tmp_path: Path) -> None:
        story_dir = _story_dir(tmp_path)
        _populate_implementation_story(story_dir)
        _corrupt_table_payload(story_dir, "story_contexts")
        result = _green_gate().evaluate(story_dir, StoryType.IMPLEMENTATION)
        assert result.passed is False
        assert result.failure_reason == "MISSING_CONTEXT"

    def test_verify_decision_fail_blocks_gate(self, tmp_path: Path) -> None:
        story_dir = _story_dir(tmp_path)
        _create_context(story_dir)
        for phase in _CODE_PHASES:
            _create_snapshot(story_dir, phase)
        _create_decision(story_dir, decision="FAIL")
        result = _green_gate().evaluate(story_dir, StoryType.IMPLEMENTATION)
        assert result.passed is False
        dim7 = result.dimension_results[IntegrityDimension.NO_VERIFY]
        assert dim7.passed is False


class TestContextStatusValidationReal:
    """R3-F: the REAL context validation enforces FK-35 §35.2.4 Dim 2 Z. 268.

    The context's ``status == PASS`` is the Setup phase snapshot COMPLETED (the
    producer that finalises the context, FK-22 §22.4).  These tests drive the
    REAL ``StateBackendIntegrityGateStateAdapter.validate_context_record`` /
    ``evaluate_mandatory_artifact`` (no fake port) against the SQLite backend.
    """

    def test_setup_snapshot_not_completed_is_context_invalid(
        self, tmp_path: Path
    ) -> None:
        # Full story but the Setup phase snapshot is RUNNING (not COMPLETED) =>
        # context status != PASS => fail-closed CONTEXT_INVALID (ENVELOPE_VIOLATION).
        from agentkit.governance.integrity_gate.dimensions import ENVELOPE_VIOLATION

        story_dir = _story_dir(tmp_path)
        _create_context(story_dir)
        # Setup snapshot present but NOT COMPLETED; the rest completed.
        _create_snapshot(story_dir, "setup", status=PhaseStatus.IN_PROGRESS)
        _create_snapshot(story_dir, "implementation")
        _create_snapshot(story_dir, "closure")
        _create_decision(story_dir)

        result = _green_gate().evaluate(story_dir, StoryType.IMPLEMENTATION)

        assert result.passed is False
        ctx_dim = result.dimension_results[IntegrityDimension.CONTEXT_INVALID]
        assert ctx_dim.passed is False
        assert ctx_dim.failure_reason == ENVELOPE_VIOLATION
        assert "status != PASS" in (ctx_dim.detail or "")

    def test_setup_snapshot_completed_context_passes(self, tmp_path: Path) -> None:
        # The same story with a COMPLETED Setup snapshot => context status PASS.
        story_dir = _story_dir(tmp_path)
        _populate_implementation_story(story_dir)

        result = _green_gate().evaluate(story_dir, StoryType.IMPLEMENTATION)

        ctx_dim = result.dimension_results[IntegrityDimension.CONTEXT_INVALID]
        assert ctx_dim.passed is True


class TestIntegrityGateResearchFewerDimensions:
    def test_research_omits_code_only_dimensions(self, tmp_path: Path) -> None:
        story_dir = _story_dir(tmp_path)
        _create_context(story_dir, StoryType.RESEARCH)
        for phase in _NONCODE_PHASES:
            _create_snapshot(story_dir, phase)
        manager = build_artifact_manager(story_dir)
        write_layer_artifacts(
            manager=manager, story_id="AG3-001", run_id=_RUN,
            layer_results=(_structural_result(),), attempt_nr=1,
        )
        record_layer_artifacts(
            story_dir, layer_results=(_structural_result(),), attempt_nr=1
        )
        result = _noncode_gate().evaluate(story_dir, StoryType.RESEARCH)
        assert result.passed is True
        assert IntegrityDimension.NO_VERIFY not in result.dimension_results
        assert IntegrityDimension.SONARQUBE_GREEN not in result.dimension_results


class TestIntegrityGateDim9Wiring:
    def test_build_integrity_gate_wires_state_backend_adapter(self) -> None:
        from agentkit.bootstrap.composition_root import build_integrity_gate

        gate = build_integrity_gate()
        assert isinstance(
            gate._state_port, StateBackendIntegrityGateStateAdapter
        )

    def test_code_story_without_port_fails_closed(self, tmp_path: Path) -> None:
        # E-C: an impl story with NO sonar_port is APPLICABLE-but-unresolvable
        # -> Dim 9 fail-closed (never a silent skip).
        from agentkit.artifacts import EnvelopeValidator
        from agentkit.bootstrap.composition_root import build_producer_registry

        story_dir = _story_dir(tmp_path)
        _populate_implementation_story(story_dir)
        gate = IntegrityGate(
            state_port=StateBackendIntegrityGateStateAdapter(),
            envelope_validator=EnvelopeValidator(build_producer_registry()),
            sonar_port=None,
        )
        result = gate.evaluate(story_dir, StoryType.IMPLEMENTATION)
        assert result.overall is IntegrityGateStatus.ESCALATED
        assert result.failure_reason == SONAR_NOT_GREEN


# ---------------------------------------------------------------------------
# DI path with a recording state-port test-double (Fix E9).
# ---------------------------------------------------------------------------


class _RecordingStatePort:
    """Recording test-double for IntegrityGateStatePort (no real DB)."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self._structural_artifact: bool = False

    def has_completed_snapshot(self, story_dir: object, phase: str) -> bool:
        self.calls.append(("has_completed_snapshot", phase))
        return True

    def has_structural_artifact(self, story_dir: object) -> bool:
        self.calls.append(("has_structural_artifact", story_dir))
        return self._structural_artifact

    def has_structural_artifact_for_scope(self, scope: RuntimeStateScope) -> bool:
        self.calls.append(("has_structural_artifact_for_scope", scope))
        return self._structural_artifact

    def has_valid_context(self, story_dir: object) -> bool:
        self.calls.append(("has_valid_context", story_dir))
        return True

    def has_valid_phase_state(self, story_dir: object) -> bool:
        self.calls.append(("has_valid_phase_state", story_dir))
        return True

    def load_context_finished_at(
        self, story_dir: object, scope: object
    ) -> object | None:
        self.calls.append(("load_context_finished_at", story_dir))
        return None

    def validate_context_record(
        self, story_dir: object, scope: object
    ) -> str | None:
        self.calls.append(("validate_context_record", story_dir))
        return None

    def load_latest_verify_decision(
        self, story_dir: object
    ) -> dict[str, object] | None:
        self.calls.append(("load_latest_verify_decision", story_dir))
        return {"status": "PASS", "passed": True, "major_threshold": 0}

    def load_latest_verify_decision_for_scope(
        self, scope: RuntimeStateScope
    ) -> dict[str, object] | None:
        self.calls.append(("load_latest_verify_decision_for_scope", scope))
        return {"status": "PASS", "passed": True, "major_threshold": 0}

    def read_phase_state_record(self, story_dir: object) -> object | None:
        self.calls.append(("read_phase_state_record", story_dir))
        return None

    def resolve_runtime_scope(self, story_dir: object) -> RuntimeStateScope:
        self.calls.append(("resolve_runtime_scope", story_dir))
        raise CorruptStateError("no scope configured")

    def find_latest_qa_envelope(
        self, story_dir: object, scope: object, stage: str
    ) -> object | None:
        self.calls.append(("find_latest_qa_envelope", stage))
        return None


class TestIntegrityGateWithRecordingPort:
    def test_missing_structural_aborts_and_blocks_later_dimensions(
        self, tmp_path: Path
    ) -> None:
        port = _RecordingStatePort()
        port._structural_artifact = False

        gate = IntegrityGate(state_port=port)  # type: ignore[arg-type]
        result = gate.evaluate(tmp_path, StoryType.IMPLEMENTATION)

        assert result.overall is IntegrityGateStatus.FAIL
        assert result.failure_reason == "MISSING_STRUCTURAL"
        assert "MISSING_STRUCTURAL" in result.missing_artifacts
        # No sonar_port wired -> code story -> Dim 9 APPLICABLE (fail-closed) is
        # in the blocked set after the mandatory abort.
        assert set(result.blocked_dimensions) == {
            IntegrityDimension.STRUCTURAL_SHALLOW,
            IntegrityDimension.NO_LLM_REVIEW,
            IntegrityDimension.NO_ADVERSARIAL,
            IntegrityDimension.NO_VERIFY,
            IntegrityDimension.TIMESTAMP_INVERSION,
            IntegrityDimension.CONFLICT_FREEZE_PROOF,
            IntegrityDimension.SONARQUBE_GREEN,
        }
        assert IntegrityDimension.STRUCTURAL_SHALLOW not in result.dimension_results
