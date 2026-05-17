"""Tests for canonical QA artifact serialization and persistence."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, cast

import pytest

from agentkit.core_types import PolicyVerdict
from agentkit.exceptions import CorruptStateError
from agentkit.governance.guard_system.protected_paths import PROTECTED_QA_ARTIFACTS
from agentkit.phase_state_store.models import FlowExecution
from agentkit.state_backend.config import ALLOW_SQLITE_ENV, STATE_BACKEND_ENV
from agentkit.state_backend.store import (
    record_verify_decision,
    reset_backend_cache_for_tests,
    save_flow_execution,
    save_story_context,
)
from agentkit.story_context_manager.models import StoryContext
from agentkit.story_context_manager.types import StoryMode, StoryType
from agentkit.verify_system.artifacts import (
    GUARDRAIL_FILE,
    LAYER_ARTIFACT_FILES,
    VERIFY_DECISION_FILE,
    build_verify_decision_artifact,
    load_json_object,
    load_verify_decision_artifact,
    serialize_finding,
    serialize_layer_result,
    verify_decision_passed,
    write_layer_artifacts,
    write_verify_decision_artifacts,
)
from agentkit.verify_system.policy_engine.engine import VerifyDecision
from agentkit.verify_system.protocols import Finding, LayerResult, Severity, TrustClass

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


def _finding(
    *,
    layer: str = "structural",
    check: str = "context_exists",
    severity: Severity = Severity.BLOCKING,
) -> Finding:
    return Finding(
        layer=layer,
        check=check,
        severity=severity,
        message=f"{check} failed",
        trust_class=TrustClass.SYSTEM,
        file_path="/tmp/example.json",
        suggestion="Fix it",
    )


def _decision(*, passed: bool, verdict: PolicyVerdict) -> VerifyDecision:
    structural = LayerResult(
        layer="structural",
        passed=passed,
        findings=(() if passed else (_finding(),)),
        metadata={"kind": "deterministic"},
    )
    semantic = LayerResult(
        layer="semantic",
        passed=True,
        findings=(),
        metadata={"prompt_audit": {"status": "skipped"}},
    )
    blocking = structural.findings if not passed else ()
    return VerifyDecision(
        passed=passed,
        verdict=verdict,
        layer_results=(structural, semantic),
        all_findings=structural.findings,
        blocking_findings=blocking,
        summary=f"Decision {verdict.value}",
    )


class TestArtifactConstants:
    def test_protected_artifacts_include_all_runtime_files(self) -> None:
        assert LAYER_ARTIFACT_FILES == {
            "structural": "structural.json",
            "semantic": "semantic-review.json",
            "adversarial": "adversarial.json",
        }
        assert VERIFY_DECISION_FILE in PROTECTED_QA_ARTIFACTS
        assert GUARDRAIL_FILE in PROTECTED_QA_ARTIFACTS


class TestSerialization:
    def test_serialize_finding(self) -> None:
        data = serialize_finding(_finding(severity=Severity.BLOCKING))
        assert data["layer"] == "structural"
        assert data["check"] == "context_exists"
        assert data["severity"] == "BLOCKING"
        assert data["trust_class"] == "A"
        assert data["file_path"] == "/tmp/example.json"
        assert data["suggestion"] == "Fix it"

    def test_serialize_layer_result(self) -> None:
        result = LayerResult(
            layer="semantic",
            passed=True,
            findings=(_finding(layer="semantic", check="logic"),),
            metadata={"prompt_audit": {"status": "materialized"}},
        )
        data = serialize_layer_result(result, attempt_nr=3)
        assert data["layer"] == "semantic"
        assert data["passed"] is True
        assert data["attempt_nr"] == 3
        assert len(cast("list[object]", data["findings"])) == 1
        assert cast("dict[str, object]", data["metadata"])["prompt_audit"] == {
            "status": "materialized"
        }

    def test_build_verify_decision_artifact(self) -> None:
        artifact = build_verify_decision_artifact(
            _decision(passed=False, verdict=PolicyVerdict.FAIL),
            attempt_nr=2,
        )
        assert artifact["passed"] is False
        assert artifact["status"] == "FAIL"
        assert artifact["attempt_nr"] == 2
        assert len(cast("list[object]", artifact["layers"])) == 2
        assert artifact["all_findings_count"] == 1
        assert len(cast("list[object]", artifact["blocking_findings"])) == 1

class TestPersistence:
    def test_write_layer_artifacts(self, tmp_path: Path) -> None:
        # Needs a story context AND flow execution so ArtifactManager can
        # resolve a runtime scope with a run_id (fail-closed without).
        # _story_id_for(story_dir) returns story_dir.name, so the dir name
        # must match the persisted story_id.
        story_dir = tmp_path / "TEST-201"
        story_dir.mkdir(parents=True, exist_ok=True)
        save_story_context(
            story_dir,
            StoryContext(
                project_key="test-project",
                story_number=201,
                story_id="TEST-201",
                story_type=StoryType.IMPLEMENTATION,
                execution_route=StoryMode.EXECUTION,
                title="Layer artifacts test",
            ),
        )
        save_flow_execution(
            story_dir,
            FlowExecution(
                project_key="test-project",
                story_id="TEST-201",
                run_id="run-test-201",
                flow_id="implementation",
                level="story",
                owner="pipeline_engine",
                status="IN_PROGRESS",
            ),
        )
        produced = write_layer_artifacts(
            story_dir,
            layer_results=(
                LayerResult(layer="structural", passed=True),
                LayerResult(
                    layer="semantic",
                    passed=True,
                    metadata={"prompt_audit": {"status": "skipped"}},
                ),
                LayerResult(layer="unknown", passed=True),
            ),
            attempt_nr=4,
        )
        assert produced == ("structural.json", "semantic-review.json")
        # resolve_qa_story_dir falls back to story_dir when no project root found
        structural = json.loads((story_dir / "structural.json").read_text("utf-8"))
        semantic = json.loads((story_dir / "semantic-review.json").read_text("utf-8"))
        assert structural["layer"] == "structural"
        assert structural["attempt_nr"] == 4
        assert semantic["metadata"]["prompt_audit"]["status"] == "skipped"
        assert not (story_dir / "unknown.json").exists()

    def test_write_verify_decision_artifacts(self, tmp_path: Path) -> None:
        # Needs a story context AND flow execution so ArtifactManager can
        # resolve a runtime scope with a run_id.
        story_dir = tmp_path / "TEST-202"
        story_dir.mkdir(parents=True, exist_ok=True)
        save_story_context(
            story_dir,
            StoryContext(
                project_key="test-project",
                story_number=202,
                story_id="TEST-202",
                story_type=StoryType.IMPLEMENTATION,
                execution_route=StoryMode.EXECUTION,
                title="Verify decision test",
            ),
        )
        save_flow_execution(
            story_dir,
            FlowExecution(
                project_key="test-project",
                story_id="TEST-202",
                run_id="run-test-202",
                flow_id="implementation",
                level="story",
                owner="pipeline_engine",
                status="IN_PROGRESS",
            ),
        )
        produced = write_verify_decision_artifacts(
            story_dir,
            decision=_decision(passed=True, verdict=PolicyVerdict.PASS),
            attempt_nr=5,
        )
        assert produced == ("verify-decision.json",)
        canonical = json.loads((story_dir / VERIFY_DECISION_FILE).read_text("utf-8"))
        assert canonical["status"] == "PASS"
        assert canonical["passed"] is True

    def test_load_json_object_handles_invalid(self, tmp_path: Path) -> None:
        assert load_json_object(tmp_path / "missing.json") is None
        (tmp_path / "bad.json").write_text("{bad", encoding="utf-8")
        assert load_json_object(tmp_path / "bad.json") is None

    def test_load_verify_decision_artifact_prefers_canonical(
        self,
        tmp_path: Path,
    ) -> None:
        (tmp_path / VERIFY_DECISION_FILE).write_text(
            json.dumps({"status": "PASS", "passed": True}),
            encoding="utf-8",
        )
        name, data = load_verify_decision_artifact(tmp_path) or ("", {})
        assert name == VERIFY_DECISION_FILE
        assert data["status"] == "PASS"

    def test_load_verify_decision_artifact_prefers_canonical_state_record(
        self,
        tmp_path: Path,
    ) -> None:
        save_story_context(
            tmp_path,
            StoryContext(
                project_key="test-project",
                story_number=201,
                story_id="TEST-201",
                story_type=StoryType.IMPLEMENTATION,
                execution_route=StoryMode.EXECUTION,
                title="Canonical decision",
            ),
        )
        record_verify_decision(
            tmp_path,
            decision=_decision(passed=True, verdict=PolicyVerdict.PASS),
            attempt_nr=2,
        )
        (tmp_path / VERIFY_DECISION_FILE).write_text(
            json.dumps({"status": "FAIL", "passed": False}),
            encoding="utf-8",
        )

        name, data = load_verify_decision_artifact(tmp_path) or ("", {})

        assert name == VERIFY_DECISION_FILE
        assert data["status"] == "PASS"

    def test_load_verify_decision_artifact_falls_back_to_projection_on_corrupt_scope(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.setattr(
            "agentkit.verify_system.artifacts.resolve_runtime_scope",
            lambda story_dir: (_ for _ in ()).throw(CorruptStateError("broken")),
        )
        monkeypatch.setattr(
            "agentkit.verify_system.artifacts.load_latest_verify_decision",
            lambda story_dir: None,
        )
        monkeypatch.setattr(
            "agentkit.verify_system.artifacts._load_verify_decision_projection",
            lambda story_dir: (VERIFY_DECISION_FILE, {"status": "PROJECTION"}),
        )

        assert load_verify_decision_artifact(tmp_path) == (
            VERIFY_DECISION_FILE,
            {"status": "PROJECTION"},
        )



class TestDecisionPassSemantics:
    def test_verify_decision_passed_for_canonical_pass(self) -> None:
        assert verify_decision_passed({"status": "PASS", "passed": True}) is True

    def test_verify_decision_passed_rejects_pass_with_warnings(self) -> None:
        """PASS_WITH_WARNINGS faellt mit AG3-021 weg; ist kein valider Status."""
        assert verify_decision_passed(
            {"status": "PASS_WITH_WARNINGS", "passed": True},
        ) is False

    def test_verify_decision_passed_requires_true_passed_flag(self) -> None:
        assert verify_decision_passed({"status": "PASS", "passed": False}) is False

    def test_verify_decision_failed_for_unexpected_status(self) -> None:
        assert verify_decision_passed({"status": "FAIL", "passed": False}) is False
