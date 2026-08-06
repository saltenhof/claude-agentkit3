"""Tests for AdversarialChallenger -- real Layer-3 adversarial runtime (AG3-079)."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

import pytest
from tests.fixtures.installer_writer import writer_backed_install_kwargs
from tests.fixtures.vectordb_installer import ready_vectordb_install_kwargs
from tests.qa_artifact_support import write_qa_layer_envelopes

from agentkit.backend.bootstrap.composition_root import build_artifact_manager
from agentkit.backend.installer import InstallConfig, install_agentkit
from agentkit.backend.installer.paths import PROMPT_BUNDLE_STORE_ENV
from agentkit.backend.phase_state_store import FlowExecution, save_flow_execution
from agentkit.backend.state_backend.store.verify_story_context_repository import (
    StateBackendVerifyStoryContextAdapter,
)
from agentkit.backend.state_backend.story_lifecycle_store import save_story_context
from agentkit.backend.story_context_manager.models import StoryContext
from agentkit.backend.story_context_manager.types import StoryMode, StoryType
from agentkit.backend.verify_system.adversarial_orchestrator.challenger import AdversarialChallenger
from agentkit.backend.verify_system.adversarial_orchestrator.runtime.artifact import AdversarialResultReadError
from agentkit.backend.verify_system.adversarial_orchestrator.spawn import AdversarialSpawner, AdversarialTarget
from agentkit.backend.verify_system.contract import VerifyContextBundle
from agentkit.backend.verify_system.protocols import (
    ASSERTION_WEAKNESS_FINDING_TYPE,
    Finding,
    LayerResult,
    QALayer,
    Severity,
    TrustClass,
)
from agentkit.backend.verify_system.stage_registry import StageRegistry

if TYPE_CHECKING:
    from pathlib import Path


def _wired_audit_deps(store_dir: Path) -> dict[str, object]:
    """Prompt-audit deps as wired by the composition root (AG3-015)."""
    return {
        "artifact_manager": build_artifact_manager(store_dir),
        "story_context_port": StateBackendVerifyStoryContextAdapter(),
    }


class TestAdversarialChallenger:
    """AdversarialChallenger passthrough tests."""

    def test_evaluate_fails_closed_when_runtime_unwired(self, tmp_path: Path) -> None:
        """AC1: no passthrough PASS. Unwired runtime -> BLOCKING fail-closed."""
        challenger = AdversarialChallenger(**_wired_audit_deps(tmp_path))
        ctx = StoryContext(
            project_key="test-project",
            story_id="TEST-001",
            story_type=StoryType.BUGFIX,
            execution_route=StoryMode.EXECUTION,
        )
        result = challenger.evaluate(ctx, tmp_path)
        # FK-48 §48.1: the passthrough PASS is gone; an unwired runtime (no
        # sparring transport / telemetry emitter) fails closed.
        assert result.passed is False
        assert result.layer == "adversarial"
        assert len(result.findings) == 1
        assert result.findings[0].check == "adversarial_runtime"
        assert result.metadata["prompt_audit"] == {
            "status": "skipped",
            "reason": "project_root_unavailable",
        }

    def test_evaluate_materializes_prompt_audit_for_project_runs(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        project_root = tmp_path / "project"
        project_root.mkdir()
        monkeypatch.setenv(
            PROMPT_BUNDLE_STORE_ENV,
            str(tmp_path / ".prompt-bundle-store"),
        )
        install_agentkit(
            InstallConfig(
                project_key="test-project",
                project_name="test-project",
                project_root=project_root,
                github_owner="acme",  # AG3-039 R6: CP 7 coordinates are MANDATORY
                github_repo="demo",
                sonarqube_available=False,  # AG3-052: conscious opt-out, no live Sonar
                ci_available=False,  # AG3-056: conscious opt-out, no live Jenkins
                **ready_vectordb_install_kwargs(),
                # FK-91 single writer: register-project binds these ports to the
                # active control-plane writer; the installer permits no local
                # State-Backend fallback, so the test supplies the same ports.
                **writer_backed_install_kwargs(tmp_path / ".skill-bundle-store"),
            ),
        )
        story_dir = project_root / "stories" / "TEST-001"
        story_dir.mkdir(parents=True)
        save_story_context(
            story_dir,
            StoryContext(
                project_key="test-project",
                story_id="TEST-001",
                story_type=StoryType.BUGFIX,
                execution_route=StoryMode.EXECUTION,
                project_root=project_root,
            ),
        )
        save_flow_execution(
            story_dir,
            FlowExecution(
                project_key="test-project",
                story_id="TEST-001",
                run_id="run-review-001",
                flow_id="story-pipeline",
                level="story",
                owner="pipeline",
                attempt_no=1,
                started_at=datetime.now(tz=UTC),
            ),
        )
        challenger = AdversarialChallenger(**_wired_audit_deps(project_root))
        ctx = StoryContext(
            project_key="test-project",
            story_id="TEST-001",
            story_type=StoryType.BUGFIX,
            execution_route=StoryMode.EXECUTION,
            project_root=project_root,
        )

        result = challenger.evaluate(ctx, story_dir)

        audit = cast("dict[str, object]", result.metadata["prompt_audit"])
        assert audit["status"] == "materialized"
        assert audit["run_id"] == "run-review-001"
        assert audit["render_mode"] == "rendered"
        assert audit["artifact_path"] == (".agentkit/prompts/run-review-001/verify-adversarial-attempt-001/prompt.md")
        assert "manifest_path" not in audit
        assert isinstance(audit["audit_record_key"], str)
        assert (project_root / str(audit["artifact_path"])).is_file()
        assert not (
            project_root
            / ".agentkit"
            / "prompts"
            / "run-review-001"
            / "verify-adversarial-attempt-001"
            / "rendered-manifest.json"
        ).exists()

    def test_implements_qa_layer_protocol(self) -> None:
        challenger = AdversarialChallenger()
        assert isinstance(challenger, QALayer)

    def test_name_is_adversarial(self) -> None:
        challenger = AdversarialChallenger()
        assert challenger.name == "adversarial"

    def test_evaluate_runs_real_runtime_when_wired(self, tmp_path: Path) -> None:
        """AC1/2/5/6: a wired challenger runs the real runtime over sandbox evidence."""
        from agentkit.backend.telemetry.emitters import MemoryEmitter
        from agentkit.backend.telemetry.events import EventType

        project_root = tmp_path / "project"
        story_dir = project_root / "stories" / "TEST-001"
        # The sandbox epoch defaults to attempt=1 when no run scope resolves.
        sandbox = story_dir / "_temp" / "adversarial" / "TEST-001" / "1"
        sandbox.mkdir(parents=True)
        (sandbox / "test_edge.py").write_text("def test_edge():\n    assert True\n", encoding="utf-8")
        (sandbox / "result.json").write_text(
            json.dumps(
                {
                    "story_id": "TEST-001",
                    "status": "PASS",
                    "tests_executed": 1,
                    "tests": [
                        {
                            "sandbox_relpath": "test_edge.py",
                            "qualified_name": "test_edge::test_edge",
                            "outcome": "PASS",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        class _FakeSparringClient:
            def complete(self, *, role: str, prompt: str) -> str:
                del role, prompt
                return "missed: empty input\nmissed: huge input"

        emitter = MemoryEmitter()
        challenger = AdversarialChallenger(
            artifact_manager=build_artifact_manager(project_root),
            sparring_client=_FakeSparringClient(),
            telemetry_emitter=emitter,
        )
        ctx = StoryContext(
            project_key="test-project",
            story_id="TEST-001",
            story_type=StoryType.IMPLEMENTATION,
            execution_route=StoryMode.EXECUTION,
            project_root=project_root,
        )

        result = challenger.evaluate(ctx, story_dir)

        assert result.passed is True
        assert result.layer == "adversarial"
        # The five adversarial events were emitted (FK-48 §48.1.8).
        assert len(emitter.query("TEST-001", EventType.ADVERSARIAL_START)) == 1
        assert len(emitter.query("TEST-001", EventType.ADVERSARIAL_END)) == 1
        assert len(emitter.query("TEST-001", EventType.ADVERSARIAL_SPARRING)) == 1
        assert len(emitter.query("TEST-001", EventType.LLM_CALL)) == 1
        # The PASS test was promoted into the project tests/ suite.
        assert (project_root / "tests" / "test_edge.py").is_file()
        # The runtime owns the canonical adversarial.json write.
        assert result.metadata["artifact_materialized"] is True

    def test_evaluate_consumes_preceding_spawn_with_exact_layer2_source(self, tmp_path: Path) -> None:
        """I3: round N+1 consumes round N target and canonical source finding."""
        from agentkit.backend.telemetry.emitters import MemoryEmitter
        from agentkit.backend.verify_system.protocols import RunScope

        project_root = tmp_path / "project"
        story_dir = project_root / "stories" / "TEST-001"
        story_dir.mkdir(parents=True)
        flow = FlowExecution(
            project_key="test-project",
            story_id="TEST-001",
            run_id="run-x",
            flow_id="implementation",
            level="story",
            owner="pipeline",
            attempt_no=1,
        )
        save_flow_execution(story_dir, flow)
        source_finding = Finding(
            layer="qa_review",
            check="negative_case",
            severity=Severity.BLOCKING,
            message="negative case is not covered",
            trust_class=TrustClass.VERIFIED_LLM,
            finding_type=ASSERTION_WEAKNESS_FINDING_TYPE,
        )
        source_result = LayerResult(
            layer="qa_review",
            passed=False,
            findings=(source_finding,),
            metadata={"executed_check_ids": ("negative_case",)},
        )
        manager = build_artifact_manager(story_dir)
        source_reference = write_qa_layer_envelopes(
            story_dir,
            layer_results=(source_result,),
            stage_registry=StageRegistry(),
            attempt_nr=1,
        )["qa_review"]
        source_result = replace(
            source_result,
            artifact_reference=source_reference,
        )
        spawner = AdversarialSpawner(manager)
        targets = spawner.extract_mandatory_targets([source_result], 1)
        spawn_request = spawner.request_spawn(
            VerifyContextBundle(run_id="run-x", story_dir=story_dir, attempt=1),
            targets,
            story_id="TEST-001",
        )
        (spawn_request.sandbox_path / "result.json").write_text(
            json.dumps(
                {
                    "story_id": "TEST-001",
                    "status": "PASS",
                    "tests_executed": 1,
                    "tests": [],
                    "mandatory_target_results": [
                        {
                            "target_id": "qa_review.negative_case",
                            "status": "UNRESOLVABLE",
                            "reason": "external boundary cannot be reproduced",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        class _Port:
            def load(self, story_dir: Path) -> None:
                del story_dir
                return None

            def resolve_run_scope(self, story_dir: Path) -> RunScope:
                del story_dir
                return RunScope(run_id="run-x", story_id="TEST-001", attempt=2)

        class _FakeSparringClient:
            def complete(self, *, role: str, prompt: str) -> str:
                del role, prompt
                return "edge a"

        challenger = AdversarialChallenger(
            artifact_manager=manager,
            story_context_port=_Port(),
            sparring_client=_FakeSparringClient(),
            telemetry_emitter=MemoryEmitter(),
        )
        ctx = StoryContext(
            project_key="test-project",
            story_id="TEST-001",
            story_type=StoryType.IMPLEMENTATION,
            execution_route=StoryMode.EXECUTION,
            project_root=project_root,
        )
        result = challenger.evaluate(ctx, story_dir)
        assert result.passed is True
        assert result.metadata["adversarial_target_sources"] == (
            {
                "target_id": "qa_review.negative_case",
                "source_result_name": "qa_review",
                "source_check_id": "negative_case",
                "source_artifact_record_key": source_reference.record_key,
                "source_finding_index": 0,
            },
        )

    def test_evaluate_rejects_spawn_target_outside_source_findings(self, tmp_path: Path) -> None:
        """I3: a typed target still fails when its source membership is false."""
        from agentkit.backend.telemetry.emitters import MemoryEmitter
        from agentkit.backend.verify_system.protocols import RunScope

        project_root = tmp_path / "project"
        story_dir = project_root / "stories" / "TEST-001"
        story_dir.mkdir(parents=True)
        save_flow_execution(
            story_dir,
            FlowExecution(
                project_key="test-project",
                story_id="TEST-001",
                run_id="run-x",
                flow_id="implementation",
                level="story",
                owner="pipeline",
            ),
        )
        source_result = LayerResult(
            layer="qa_review",
            passed=False,
            findings=(
                Finding(
                    layer="qa_review",
                    check="negative_case",
                    severity=Severity.BLOCKING,
                    message="negative case is not covered",
                    trust_class=TrustClass.VERIFIED_LLM,
                    finding_type=ASSERTION_WEAKNESS_FINDING_TYPE,
                ),
            ),
            metadata={"executed_check_ids": ("negative_case",)},
        )
        manager = build_artifact_manager(story_dir)
        reference = write_qa_layer_envelopes(
            story_dir,
            layer_results=(source_result,),
            stage_registry=StageRegistry(),
            attempt_nr=1,
        )["qa_review"]
        source_result = replace(source_result, artifact_reference=reference)
        spawner = AdversarialSpawner(manager)
        target = replace(
            spawner.extract_mandatory_targets([source_result], 1)[0],
            source_finding_index=1,
        )
        spawner.request_spawn(
            VerifyContextBundle(run_id="run-x", story_dir=story_dir, attempt=1),
            [target],
            story_id="TEST-001",
        )

        class _Port:
            def load(self, story_dir: Path) -> None:
                del story_dir
                return None

            def resolve_run_scope(self, story_dir: Path) -> RunScope:
                del story_dir
                return RunScope(run_id="run-x", story_id="TEST-001", attempt=2)

        class _FakeSparringClient:
            def complete(self, *, role: str, prompt: str) -> str:
                del role, prompt
                return "edge a"

        challenger = AdversarialChallenger(
            artifact_manager=manager,
            story_context_port=_Port(),
            sparring_client=_FakeSparringClient(),
            telemetry_emitter=MemoryEmitter(),
        )
        result = challenger.evaluate(
            StoryContext(
                project_key="test-project",
                story_id="TEST-001",
                story_type=StoryType.IMPLEMENTATION,
                execution_route=StoryMode.EXECUTION,
                project_root=project_root,
            ),
            story_dir,
        )

        assert result.passed is False
        assert "exact Layer-2 result" in result.findings[0].message

    def test_source_finding_validation_rejects_forged_target_derivation(self) -> None:
        target = AdversarialTarget(
            finding_id="qa_review.negative_case",
            source_result_name="qa_review",
            source_check_id="negative_case",
            source_artifact_record_key="source-record",
            source_finding_index=0,
            source="qa_review round 1",
            normative_ref="negative case is not covered",
            addressed_part="happy path fixed",
            open_part="exercise the negative case",
            mandatory=True,
            test_anchor="test_negative_case_0.py",
        )
        source_finding: dict[str, object] = {
            "layer": "qa_review",
            "check": "negative_case",
            "severity": Severity.BLOCKING.value,
            "message": "negative case is not covered",
            "suggestion": "exercise the negative case",
            "finding_type": ASSERTION_WEAKNESS_FINDING_TYPE,
            "addressed_part": "happy path fixed",
        }
        metadata = {"executed_check_ids": ["negative_case"]}

        AdversarialChallenger._validate_source_finding(
            target,
            source_finding,
            metadata,
            expected_spawn_attempt=1,
        )

        forged_cases = (
            (target, {**source_finding, "finding_type": None}),
            (target, {**source_finding, "severity": "INFO"}),
            (target, {**source_finding, "addressed_part": "forged"}),
            (target, {**source_finding, "suggestion": "forged"}),
            (replace(target, finding_id="qa_review.forged"), source_finding),
            (replace(target, source="qa_review round 9"), source_finding),
            (replace(target, mandatory=False), source_finding),
            (replace(target, test_anchor="test_forged.py"), source_finding),
        )
        for forged_target, forged_finding in forged_cases:
            with pytest.raises(AdversarialResultReadError, match="exact executed Layer-2 member"):
                AdversarialChallenger._validate_source_finding(
                    forged_target,
                    forged_finding,
                    metadata,
                    expected_spawn_attempt=1,
                )

        with pytest.raises(AdversarialResultReadError, match="exact executed Layer-2 member"):
            AdversarialChallenger._validate_source_finding(
                target,
                source_finding,
                {"executed_check_ids": []},
                expected_spawn_attempt=1,
            )

    def test_source_artifact_scope_rejects_forged_record_key_dimensions(self) -> None:
        canonical_key = "TEST-001|run-x|qa-layer-qa-review|1|qa|verify-system.layer-2-qa-review"
        target = AdversarialTarget(
            finding_id="qa_review.negative_case",
            source_result_name="qa_review",
            source_check_id="negative_case",
            source_artifact_record_key=canonical_key,
            source_finding_index=0,
            source="qa_review round 1",
            normative_ref="negative case is not covered",
            addressed_part="",
            open_part="negative case is not covered",
            mandatory=True,
            test_anchor="test_negative_case_0.py",
        )

        assert AdversarialChallenger._expected_source_artifact_scope(
            target,
            story_id="TEST-001",
            run_id="run-x",
            expected_spawn_attempt=1,
        ) == ("qa-layer-qa-review", "verify-system.layer-2-qa-review")

        forged_keys = (
            canonical_key.replace("TEST-001", "TEST-999"),
            canonical_key.replace("run-x", "run-forged"),
            canonical_key.replace("|qa|", "|pipeline|"),
            canonical_key.replace("verify-system.layer-2-qa-review", "forged-producer"),
        )
        for forged_key in forged_keys:
            with pytest.raises(AdversarialResultReadError, match="exact canonical Layer-2 artifact"):
                AdversarialChallenger._expected_source_artifact_scope(
                    replace(target, source_artifact_record_key=forged_key),
                    story_id="TEST-001",
                    run_id="run-x",
                    expected_spawn_attempt=1,
                )

        structural_target = replace(
            target,
            source_result_name="structural",
            source_artifact_record_key=(
                "TEST-001|run-x|qa-layer-structural|1|qa|"
                "verify-system.layer-1-structural"
            ),
        )
        with pytest.raises(AdversarialResultReadError, match="exact canonical Layer-2 artifact"):
            AdversarialChallenger._expected_source_artifact_scope(
                structural_target,
                story_id="TEST-001",
                run_id="run-x",
                expected_spawn_attempt=1,
            )
