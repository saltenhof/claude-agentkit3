"""Tests for canonical QA artifact serialization and persistence."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from agentkit.exceptions import CorruptStateError
from agentkit.qa.artifacts import (
    GUARDRAIL_FILE,
    LAYER_ARTIFACT_FILES,
    PROTECTED_QA_ARTIFACTS,
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
from agentkit.qa.policy_engine.engine import VerifyDecision
from agentkit.qa.protocols import Finding, LayerResult, Severity, TrustClass
from agentkit.state_backend import record_verify_decision, save_story_context
from agentkit.state_backend.config import ALLOW_SQLITE_ENV, STATE_BACKEND_ENV
from agentkit.state_backend.store import reset_backend_cache_for_tests
from agentkit.story_context_manager.models import StoryContext
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


def _finding(
    *,
    layer: str = "structural",
    check: str = "context_exists",
    severity: Severity = Severity.HIGH,
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


def _decision(*, passed: bool, status: str) -> VerifyDecision:
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
        status=status,
        layer_results=(structural, semantic),
        all_findings=structural.findings,
        blocking_findings=blocking,
        summary=f"Decision {status}",
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
        data = serialize_finding(_finding())
        assert data["layer"] == "structural"
        assert data["check"] == "context_exists"
        assert data["severity"] == "high"
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
        assert len(data["findings"]) == 1
        assert data["metadata"]["prompt_audit"]["status"] == "materialized"

    def test_build_verify_decision_artifact(self) -> None:
        artifact = build_verify_decision_artifact(
            _decision(passed=False, status="FAIL"),
            attempt_nr=2,
        )
        assert artifact["passed"] is False
        assert artifact["status"] == "FAIL"
        assert artifact["attempt_nr"] == 2
        assert len(artifact["layers"]) == 2
        assert artifact["all_findings_count"] == 1
        assert len(artifact["blocking_findings"]) == 1

class TestPersistence:
    def test_write_layer_artifacts(self, tmp_path: Path) -> None:
        produced = write_layer_artifacts(
            tmp_path,
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
        structural = json.loads((tmp_path / "structural.json").read_text("utf-8"))
        semantic = json.loads((tmp_path / "semantic-review.json").read_text("utf-8"))
        assert structural["layer"] == "structural"
        assert structural["attempt_nr"] == 4
        assert semantic["metadata"]["prompt_audit"]["status"] == "skipped"
        assert not (tmp_path / "unknown.json").exists()

    def test_write_verify_decision_artifacts(self, tmp_path: Path) -> None:
        produced = write_verify_decision_artifacts(
            tmp_path,
            decision=_decision(passed=True, status="PASS_WITH_WARNINGS"),
            attempt_nr=5,
        )
        assert produced == ("verify-decision.json",)
        canonical = json.loads((tmp_path / VERIFY_DECISION_FILE).read_text("utf-8"))
        assert canonical["status"] == "PASS_WITH_WARNINGS"
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
                story_id=tmp_path.name,
                story_type=StoryType.IMPLEMENTATION,
                execution_route=StoryMode.EXECUTION,
                title="Canonical decision",
            ),
        )
        record_verify_decision(
            tmp_path,
            decision=_decision(passed=True, status="PASS_WITH_WARNINGS"),
            attempt_nr=2,
        )
        (tmp_path / VERIFY_DECISION_FILE).write_text(
            json.dumps({"status": "FAIL", "passed": False}),
            encoding="utf-8",
        )

        name, data = load_verify_decision_artifact(tmp_path) or ("", {})

        assert name == VERIFY_DECISION_FILE
        assert data["status"] == "PASS_WITH_WARNINGS"

    def test_load_verify_decision_artifact_falls_back_to_projection_on_corrupt_scope(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.setattr(
            "agentkit.qa.artifacts.resolve_runtime_scope",
            lambda story_dir: (_ for _ in ()).throw(CorruptStateError("broken")),
        )
        monkeypatch.setattr(
            "agentkit.qa.artifacts.load_latest_verify_decision",
            lambda story_dir: None,
        )
        monkeypatch.setattr(
            "agentkit.qa.artifacts.load_verify_decision_projection",
            lambda story_dir: (VERIFY_DECISION_FILE, {"status": "PROJECTION"}),
        )

        assert load_verify_decision_artifact(tmp_path) == (
            VERIFY_DECISION_FILE,
            {"status": "PROJECTION"},
        )

    def test_write_layer_artifacts_falls_back_to_projection_when_scope_is_missing(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.setattr(
            "agentkit.qa.artifacts.record_layer_artifacts",
            lambda *args, **kwargs: (_ for _ in ()).throw(CorruptStateError("broken")),
        )

        def fake_write_layer_projection(
            story_dir: Path,
            *,
            layer_result: LayerResult,
            attempt_nr: int,
            projection_dir: Path | None = None,
        ) -> str | None:
            del story_dir, attempt_nr, projection_dir
            if layer_result.layer == "semantic":
                return "semantic-review.json"
            return None

        monkeypatch.setattr(
            "agentkit.qa.artifacts.write_layer_projection",
            fake_write_layer_projection,
        )

        produced = write_layer_artifacts(
            tmp_path,
            layer_results=(
                LayerResult(layer="semantic", passed=True),
                LayerResult(layer="unknown", passed=True),
            ),
            attempt_nr=3,
        )

        assert produced == ("semantic-review.json",)

    def test_write_verify_decision_artifacts_falls_back_to_projection(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.setattr(
            "agentkit.qa.artifacts.record_verify_decision",
            lambda *args, **kwargs: (_ for _ in ()).throw(CorruptStateError("broken")),
        )
        monkeypatch.setattr(
            "agentkit.qa.artifacts.write_verify_decision_projection",
            lambda story_dir, *, decision, attempt_nr, projection_dir=None: (
                "verify-decision.json",
            ),
        )

        produced = write_verify_decision_artifacts(
            tmp_path,
            decision=_decision(passed=True, status="PASS"),
            attempt_nr=2,
        )

        assert produced == ("verify-decision.json",)


class TestDecisionPassSemantics:
    def test_verify_decision_passed_for_canonical_pass(self) -> None:
        assert verify_decision_passed({"status": "PASS", "passed": True}) is True

    def test_verify_decision_passed_for_canonical_warnings(self) -> None:
        assert verify_decision_passed(
            {"status": "PASS_WITH_WARNINGS", "passed": True},
        ) is True

    def test_verify_decision_passed_requires_true_passed_flag(self) -> None:
        assert verify_decision_passed({"status": "PASS", "passed": False}) is False

    def test_verify_decision_failed_for_unexpected_status(self) -> None:
        assert verify_decision_passed({"status": "FAIL", "passed": False}) is False
