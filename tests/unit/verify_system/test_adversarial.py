"""Tests for AdversarialChallenger -- real Layer-3 adversarial runtime (AG3-079)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

from agentkit.backend.bootstrap.composition_root import build_artifact_manager
from agentkit.backend.installer import InstallConfig, install_agentkit
from agentkit.backend.installer.paths import PROMPT_BUNDLE_STORE_ENV
from agentkit.backend.phase_state_store import FlowExecution, save_flow_execution
from agentkit.backend.state_backend.store import save_story_context
from agentkit.backend.state_backend.store.verify_story_context_repository import (
    StateBackendVerifyStoryContextAdapter,
)
from agentkit.backend.verify_system.adversarial_orchestrator.challenger import AdversarialChallenger

if TYPE_CHECKING:
    from pathlib import Path

    import pytest
from agentkit.backend.story_context_manager.models import StoryContext
from agentkit.backend.story_context_manager.types import StoryMode, StoryType
from agentkit.backend.verify_system.protocols import QALayer


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
        assert audit["artifact_path"] == (
            ".agentkit/prompts/run-review-001/"
            "verify-adversarial-attempt-001/prompt.md"
        )
        assert "manifest_path" not in audit
        assert isinstance(audit["audit_record_key"], str)
        assert (
            project_root / str(audit["artifact_path"])
        ).is_file()
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
        (sandbox / "test_edge.py").write_text(
            "def test_edge():\n    assert True\n", encoding="utf-8"
        )
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

    def test_evaluate_resolves_sandbox_epoch_from_run_scope(
        self, tmp_path: Path
    ) -> None:
        """AC2: the challenger resolves the sandbox epoch via the run-scope port."""
        from agentkit.backend.telemetry.emitters import MemoryEmitter
        from agentkit.backend.verify_system.protocols import RunScope

        project_root = tmp_path / "project"
        story_dir = project_root / "stories" / "TEST-001"
        # The run scope reports attempt=3 -> the sandbox epoch is "3".
        sandbox = story_dir / "_temp" / "adversarial" / "TEST-001" / "3"
        sandbox.mkdir(parents=True)
        (sandbox / "result.json").write_text(
            json.dumps(
                {"story_id": "TEST-001", "status": "PASS", "tests_executed": 1, "tests": []}
            ),
            encoding="utf-8",
        )

        class _Port:
            def load(self, story_dir: Path) -> None:
                del story_dir
                return None

            def resolve_run_scope(self, story_dir: Path) -> RunScope:
                del story_dir
                return RunScope(run_id="run-x", story_id="TEST-001", attempt=3)

        class _FakeSparringClient:
            def complete(self, *, role: str, prompt: str) -> str:
                del role, prompt
                return "edge a"

        challenger = AdversarialChallenger(
            artifact_manager=build_artifact_manager(project_root),
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
