"""Tests for verify_system.artifacts (ArtifactManager-injected API).

Re-Refactor nach Stefan-Review: verify_system/artifacts.py akzeptiert nur
noch eine injizierte ``ArtifactManager``-Instanz; kein
``state_backend.store``-Import mehr im Modul-Header (AG3-023 §AK12).
Die Tests injizieren den Manager via ``build_artifact_manager`` aus dem
Composition-Root.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, cast

import pytest

from agentkit.backend.artifacts import ArtifactNotFoundError
from agentkit.backend.bootstrap.composition_root import build_artifact_manager
from agentkit.backend.core_types import PolicyVerdict
from agentkit.backend.governance.guard_system.protected_paths import PROTECTED_QA_ARTIFACTS
from agentkit.backend.verify_system.artifacts import (
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
from agentkit.backend.verify_system.policy_engine.engine import VerifyDecision
from agentkit.backend.verify_system.protocols import Finding, LayerResult, Severity, TrustClass

if TYPE_CHECKING:
    from pathlib import Path


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
        # FK-27 §27.7: kanonische Dateinamen (neue Wire-Strings mit Underscore).
        assert LAYER_ARTIFACT_FILES == {
            "structural": "structural.json",
            "adversarial": "adversarial.json",
            "qa_review": "qa_review.json",
            "semantic_review": "semantic_review.json",
            "doc_fidelity": "doc_fidelity.json",
        }
        # decision.json ist der kanonische Name (nicht verify-decision.json).
        assert VERIFY_DECISION_FILE == "decision.json"
        # Alle 6 FK-27-Artefakte muessen in der Schutzliste sein.
        assert GUARDRAIL_FILE in PROTECTED_QA_ARTIFACTS
        for qa_file in (
            "structural.json",
            "qa_review.json",
            "semantic_review.json",
            "doc_fidelity.json",
            "adversarial.json",
            "decision.json",
        ):
            assert qa_file in PROTECTED_QA_ARTIFACTS, (
                f"{qa_file!r} fehlt in PROTECTED_QA_ARTIFACTS"
            )


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


class TestPersistenceViaManager:
    """Persist via ArtifactManager — verify_system kennt state_backend nicht direkt."""

    def test_write_layer_artifacts_round_trip(self, tmp_path: Path) -> None:
        manager = build_artifact_manager(tmp_path)
        produced = write_layer_artifacts(
            manager=manager,
            story_id="TEST-201",
            run_id="run-test-201",
            layer_results=(
                LayerResult(layer="structural", passed=True),
                LayerResult(
                    layer="semantic_review",
                    passed=True,
                    metadata={"prompt_audit": {"status": "skipped"}},
                ),
                LayerResult(layer="unknown", passed=True),  # ignored: unknown layer
            ),
            attempt_nr=4,
        )
        # Unknown layers werden nicht geschrieben.
        # FK-27 §27.7: semantic_review.json (Underscore, kein Dash).
        assert produced == ("structural.json", "semantic_review.json")
        # Read-back via Manager.read_latest beweist, dass ArtifactManager
        # die einzige Lese-/Schreib-API ist.
        from agentkit.backend.core_types import ArtifactClass

        envelope = manager.read_latest(
            story_id="TEST-201",
            run_id="run-test-201",
            artifact_class=ArtifactClass.QA,
            stage="qa-layer-structural",
        )
        assert envelope.payload is not None
        assert envelope.payload["layer"] == "structural"
        assert envelope.payload["attempt_nr"] == 4

    def test_write_verify_decision_round_trip(self, tmp_path: Path) -> None:
        manager = build_artifact_manager(tmp_path)
        produced = write_verify_decision_artifacts(
            manager=manager,
            story_id="TEST-202",
            run_id="run-test-202",
            decision=_decision(passed=True, verdict=PolicyVerdict.PASS),
            attempt_nr=5,
        )
        assert produced == (VERIFY_DECISION_FILE,)
        name_payload = load_verify_decision_artifact(
            manager=manager,
            story_id="TEST-202",
            run_id="run-test-202",
        )
        assert name_payload is not None
        name, payload = name_payload
        assert name == VERIFY_DECISION_FILE
        assert payload["status"] == "PASS"
        assert payload["passed"] is True

    def test_rewrite_with_different_status_upserts_envelope(
        self, tmp_path: Path,
    ) -> None:
        """Anti-Divergence: identischer Key + neuer Status -> UPSERT, kein Silent-Ignore.

        Stefan-Befund 2: Re-Write mit gleicher Reference muss den
        Envelope auf den aktuellen Stand bringen; die alte ``INSERT OR
        IGNORE``-Semantik fuehrte zu divergenter Wahrheit zwischen
        Envelope und Projektion.
        """
        manager = build_artifact_manager(tmp_path)
        from agentkit.backend.core_types import ArtifactClass

        # 1. Schreibe passed=true.
        write_layer_artifacts(
            manager=manager,
            story_id="TEST-203",
            run_id="run-test-203",
            layer_results=(LayerResult(layer="structural", passed=True),),
            attempt_nr=1,
        )
        envelope_first = manager.read_latest(
            story_id="TEST-203",
            run_id="run-test-203",
            artifact_class=ArtifactClass.QA,
            stage="qa-layer-structural",
        )
        assert envelope_first.status.value == "PASS"

        # 2. Schreibe gleichen Key mit passed=false.
        write_layer_artifacts(
            manager=manager,
            story_id="TEST-203",
            run_id="run-test-203",
            layer_results=(LayerResult(layer="structural", passed=False),),
            attempt_nr=1,
        )
        envelope_second = manager.read_latest(
            story_id="TEST-203",
            run_id="run-test-203",
            artifact_class=ArtifactClass.QA,
            stage="qa-layer-structural",
        )
        # UPSERT muss den Status auf FAIL gezogen haben (NICHT silent PASS lassen).
        assert envelope_second.status.value == "FAIL"
        assert envelope_second.payload is not None
        assert envelope_second.payload["passed"] is False

    def test_load_verify_decision_returns_none_when_missing(
        self, tmp_path: Path,
    ) -> None:
        manager = build_artifact_manager(tmp_path)
        result = load_verify_decision_artifact(
            manager=manager,
            story_id="TEST-MISSING",
            run_id="run-missing",
        )
        assert result is None

    def test_manager_read_latest_raises_when_missing(self, tmp_path: Path) -> None:
        manager = build_artifact_manager(tmp_path)
        from agentkit.backend.core_types import ArtifactClass

        with pytest.raises(ArtifactNotFoundError):
            manager.read_latest(
                story_id="TEST-MISSING",
                run_id="run-missing",
                artifact_class=ArtifactClass.QA,
                stage="qa-policy-decision",
            )


class TestProjectionFileLoad:
    def test_load_json_object_handles_invalid(self, tmp_path: Path) -> None:
        assert load_json_object(tmp_path / "missing.json") is None
        (tmp_path / "bad.json").write_text("{bad", encoding="utf-8")
        assert load_json_object(tmp_path / "bad.json") is None


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


def _unused_json_import_marker() -> None:
    # json is used for projection-file tests elsewhere; keep import stable.
    json.dumps({})
