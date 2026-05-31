"""Integration-level tests fuer die drei Layer-2 Reviewer (W1 / AG3-026).

Testet die Reviewer-Klassen in realistischen Szenarien (Prompt-Audit,
Protokoll-Konformitaet). Detaillierte PASS/FAIL-Dimension-Tests sind in
``tests/unit/verify_system/llm_evaluator/test_reviewers.py``.

AG3-026 Pass-3 ERROR-5: all evaluate() calls now pass review_input.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from hashlib import sha256
from typing import TYPE_CHECKING, cast

from agentkit.bootstrap.composition_root import build_artifact_manager
from agentkit.installer import InstallConfig, install_agentkit
from agentkit.installer.paths import (
    PROMPT_BUNDLE_STORE_ENV,
    prompt_bundle_lock_path,
    prompt_bundle_store_dir,
)
from agentkit.phase_state_store import FlowExecution, save_flow_execution
from agentkit.prompt_runtime.runtime import PromptRuntime
from agentkit.state_backend.store import save_story_context
from agentkit.state_backend.store.verify_story_context_repository import (
    StateBackendVerifyStoryContextAdapter,
)
from agentkit.story_context_manager.models import StoryContext
from agentkit.story_context_manager.types import StoryMode, StoryType
from agentkit.verify_system.llm_evaluator.inputs import Layer2ReviewInput
from agentkit.verify_system.llm_evaluator.reviewer import (
    DocFidelityReviewer,
    QaReviewReviewer,
    SemanticReviewer,
)
from agentkit.verify_system.prompt_audit import materialize_qa_prompt_audit
from agentkit.verify_system.protocols import QALayer

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _minimal_ctx() -> StoryContext:
    return StoryContext(
        project_key="test-project",
        story_id="TEST-001",
        story_type=StoryType.IMPLEMENTATION,
        execution_route=StoryMode.EXECUTION,
    )


def _wired_audit_deps(store_dir: Path) -> dict[str, object]:
    """Build the injected prompt-audit deps the composition root wires.

    AG3-015 / FK-44 §44.4.2: the QA layers materialize prompts via
    ``PromptRuntime.materialize_prompt`` (audited through the
    ``ArtifactManager``) and resolve the run correlation through the
    state-backed ``StoryContextQueryPort`` -- no loose ``rendered-manifest``
    JSON and no direct ``state_backend.store`` import inside ``verify_system``.
    """
    return {
        "artifact_manager": build_artifact_manager(store_dir),
        "story_context_port": StateBackendVerifyStoryContextAdapter(),
    }


def _empty_ri() -> Layer2ReviewInput:
    """Empty Layer2ReviewInput (all fields empty strings)."""
    return Layer2ReviewInput()


def _clone_bundle_version(
    project_root: Path,
    *,
    new_version: str,
) -> tuple[str, str]:
    """Clone the installed prompt bundle to a new, materially different version.

    Reads the bundle id/version from the installed project lock, copies the
    central-store bundle dir to ``new_version`` and appends a per-template
    marker so the new version yields different template bytes/digests than the
    pinned one. Returns ``(bundle_id, old_version)``.
    """

    lock = json.loads(
        prompt_bundle_lock_path(project_root).read_text(encoding="utf-8"),
    )
    bundle_id = str(lock["bundle_id"])
    old_version = str(lock["bundle_version"])

    old_root = prompt_bundle_store_dir(bundle_id, old_version)
    new_root = prompt_bundle_store_dir(bundle_id, new_version)
    manifest = json.loads(
        (old_root / "manifest.json").read_text(encoding="utf-8"),
    )
    templates = cast("dict[str, dict[str, str]]", manifest["templates"])
    for name, spec in templates.items():
        relpath = spec["relpath"]
        src = old_root / relpath
        content = src.read_text(encoding="utf-8")
        rebound = f"{content}\n<!-- rebound v{new_version} {name} -->\n"
        dst = new_root / relpath
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(rebound, encoding="utf-8")
        spec["sha256"] = sha256(rebound.encode("utf-8")).hexdigest()
    manifest["bundle_version"] = new_version
    (new_root / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return bundle_id, old_version


class TestPromptAuditPinStabilityAfterRebind:
    """N1 (AG3-015 review R2): the verify prompt-audit path is a pin CONSUMER.

    Reproduces and guards the regression where the audit path called
    ``create_run_pin`` (-> ``initialize_prompt_run_pin`` ->
    ``ensure_prompt_run_pin``) unconditionally before every materialization,
    re-validating the existing run pin against the *current* project lock. After
    a legitimate mid-run ``update_binding`` that tripped a spurious
    ``PROMPT_RUN_PIN_MISMATCH`` and prevented the pinned run from materializing
    its prompt -- breaking C2 ``binding_changes_affect_only_future_runs``
    (FK-44 §44.4.2). The path now ``ensure_run_pin`` (create-if-absent only) and
    never re-validates an existing pin against the lock.
    """

    def _wire_run(
        self,
        project_root: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> tuple[Path, StoryContext]:
        project_root.mkdir()
        monkeypatch.setenv(
            PROMPT_BUNDLE_STORE_ENV,
            str(project_root.parent / ".prompt-bundle-store"),
        )
        install_agentkit(
            InstallConfig(
                project_key="test-project",
                project_name="test-project",
                project_root=project_root,
            ),
        )
        story_dir = project_root / "stories" / "TEST-001"
        story_dir.mkdir(parents=True)
        save_story_context(
            story_dir,
            StoryContext(
                project_key="test-project",
                story_id="TEST-001",
                story_type=StoryType.IMPLEMENTATION,
                execution_route=StoryMode.EXECUTION,
                project_root=project_root,
            ),
        )
        save_flow_execution(
            story_dir,
            FlowExecution(
                project_key="test-project",
                story_id="TEST-001",
                run_id="run-rebind-001",
                flow_id="story-pipeline",
                level="story",
                owner="pipeline",
                attempt_no=1,
                started_at=datetime.now(tz=UTC),
            ),
        )
        ctx = StoryContext(
            project_key="test-project",
            story_id="TEST-001",
            story_type=StoryType.IMPLEMENTATION,
            execution_route=StoryMode.EXECUTION,
            project_root=project_root,
        )
        return story_dir, ctx

    def test_materializes_pinned_bytes_after_rebind(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        project_root = tmp_path / "project"
        story_dir, ctx = self._wire_run(project_root, monkeypatch)
        artifact_manager = build_artifact_manager(project_root)
        story_context_port = StateBackendVerifyStoryContextAdapter()

        # Pin the active run to the installed version via the (idempotent)
        # consumer entry, then capture the pinned bytes the run must keep.
        runtime = PromptRuntime(project_root, artifact_manager)
        runtime.ensure_run_pin("run-rebind-001")

        # Legitimate mid-run rebind: a materially different future version.
        bundle_id, _ = _clone_bundle_version(project_root, new_version="999")
        PromptRuntime(project_root).update_binding(bundle_id, "999")

        # The pinned run must still materialize -- no PROMPT_RUN_PIN_MISMATCH.
        audit = materialize_qa_prompt_audit(
            layer_name="semantic_review",
            template_name="qa-semantic-review",
            ctx=ctx,
            story_dir=story_dir,
            artifact_manager=artifact_manager,
            story_context_port=story_context_port,
        )

        assert audit["status"] == "materialized", audit
        assert audit["run_id"] == "run-rebind-001"
        # The materialized prompt carries the PINNED bytes, not the rebound v999
        # marker (C2: binding_changes_affect_only_future_runs).
        prompt_text = (
            project_root / str(audit["artifact_path"])
        ).read_text(encoding="utf-8")
        assert "rebound v999" not in prompt_text

    def test_missing_pin_is_skipped_fail_closed(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """No pin and no resolvable binding -> clean skip, never a crash.

        A resolvable run scope exists, but neither a run pin nor a project lock
        is present (the lock is removed). ``ensure_run_pin`` cannot create a pin
        and ``materialize_prompt`` is fail-closed; the audit must surface that
        as a clean ``skipped`` status instead of crashing the QA subflow.
        """
        project_root = tmp_path / "project"
        story_dir, ctx = self._wire_run(project_root, monkeypatch)
        # Remove the project lock so no pin can be created and no binding
        # resolves -- the genuine fail-closed path.
        prompt_bundle_lock_path(project_root).unlink()
        artifact_manager = build_artifact_manager(project_root)
        story_context_port = StateBackendVerifyStoryContextAdapter()

        audit = materialize_qa_prompt_audit(
            layer_name="semantic_review",
            template_name="qa-semantic-review",
            ctx=ctx,
            story_dir=story_dir,
            artifact_manager=artifact_manager,
            story_context_port=story_context_port,
        )

        # Missing pin + missing lock -> ensure_run_pin/materialize fail-closed,
        # surfaced as a clean skip (not an uncaught ProjectError crash).
        assert audit["status"] == "skipped", audit
        assert audit["reason"] == "materialization_failed", audit


# ---------------------------------------------------------------------------
# QaReviewReviewer
# ---------------------------------------------------------------------------


class TestQaReviewReviewer:
    """QaReviewReviewer integration tests (AG3-026 Pass-2)."""

    def test_evaluate_returns_layer_result_with_qa_review_layer(
        self, tmp_path: Path
    ) -> None:
        """evaluate() always returns LayerResult with layer='qa_review'."""
        reviewer = QaReviewReviewer()
        result = reviewer.evaluate(_minimal_ctx(), tmp_path, review_input=_empty_ri())
        assert result.layer == "qa_review"

    def test_evaluate_includes_prompt_audit_in_metadata(self, tmp_path: Path) -> None:
        """evaluate() includes 'prompt_audit' in metadata."""
        reviewer = QaReviewReviewer(**_wired_audit_deps(tmp_path))
        result = reviewer.evaluate(_minimal_ctx(), tmp_path, review_input=_empty_ri())
        assert result.metadata["prompt_audit"] == {
            "status": "skipped",
            "reason": "project_root_unavailable",
        }

    def test_name_is_qa_review(self) -> None:
        reviewer = QaReviewReviewer()
        assert reviewer.name == "qa_review"

    def test_implements_qa_layer_protocol(self) -> None:
        reviewer = QaReviewReviewer()
        assert isinstance(reviewer, QALayer)


# ---------------------------------------------------------------------------
# SemanticReviewer
# ---------------------------------------------------------------------------


class TestSemanticReviewer:
    """SemanticReviewer integration tests (AG3-026 Pass-2)."""

    def test_evaluate_returns_passed_on_empty_dir(self, tmp_path: Path) -> None:
        """PASS: empty story_dir has no .py files to check.

        With empty review_input, layer2_input.missing (MAJOR) is emitted,
        but no BLOCKING -> passed=True. findings is non-empty.
        """
        reviewer = SemanticReviewer(**_wired_audit_deps(tmp_path))
        result = reviewer.evaluate(_minimal_ctx(), tmp_path, review_input=_empty_ri())
        assert result.passed is True
        assert result.layer == "semantic_review"
        # layer2_input.missing is MAJOR; passed is still True (no BLOCKING)
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
            ),
        )
        story_dir = project_root / "stories" / "TEST-001"
        story_dir.mkdir(parents=True)
        save_story_context(
            story_dir,
            StoryContext(
                project_key="test-project",
                story_id="TEST-001",
                story_type=StoryType.IMPLEMENTATION,
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
        reviewer = SemanticReviewer(**_wired_audit_deps(project_root))
        ctx = StoryContext(
            project_key="test-project",
            story_id="TEST-001",
            story_type=StoryType.IMPLEMENTATION,
            execution_route=StoryMode.EXECUTION,
            project_root=project_root,
        )

        result = reviewer.evaluate(ctx, story_dir, review_input=_empty_ri())

        audit = cast("dict[str, object]", result.metadata["prompt_audit"])
        assert audit["status"] == "materialized"
        assert audit["run_id"] == "run-review-001"
        assert audit["render_mode"] == "rendered"
        # FK-44 §44.4.1 canonical run-scoped instance path (prompt.md), not a
        # loose layer-named file; audit persisted via ArtifactManager.
        assert audit["artifact_path"] == (
            ".agentkit/prompts/run-review-001/"
            "verify-semantic_review-attempt-001/prompt.md"
        )
        assert "manifest_path" not in audit
        assert isinstance(audit["audit_record_key"], str)
        assert len(str(audit["output_sha256"])) == 64
        assert (
            project_root / str(audit["artifact_path"])
        ).is_file()
        # No loose rendered-manifest.json is written as audit truth anymore.
        assert not (
            project_root
            / ".agentkit"
            / "prompts"
            / "run-review-001"
            / "verify-semantic_review-attempt-001"
            / "rendered-manifest.json"
        ).exists()

    def test_evaluate_skips_when_flow_story_does_not_match_context(
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
            ),
        )
        story_dir = project_root / "stories" / "OTHER-999"
        story_dir.mkdir(parents=True)
        save_story_context(
            story_dir,
            StoryContext(
                project_key="test-project",
                story_id="OTHER-999",
                story_type=StoryType.IMPLEMENTATION,
                execution_route=StoryMode.EXECUTION,
                project_root=project_root,
            ),
        )
        save_flow_execution(
            story_dir,
            FlowExecution(
                project_key="test-project",
                story_id="OTHER-999",
                run_id="run-review-001",
                flow_id="story-pipeline",
                level="story",
                owner="pipeline",
                attempt_no=1,
                started_at=datetime.now(tz=UTC),
            ),
        )
        reviewer = SemanticReviewer(**_wired_audit_deps(project_root))
        ctx = StoryContext(
            project_key="test-project",
            story_id="TEST-001",
            story_type=StoryType.IMPLEMENTATION,
            execution_route=StoryMode.EXECUTION,
            project_root=project_root,
        )

        result = reviewer.evaluate(ctx, story_dir, review_input=_empty_ri())

        assert result.metadata["prompt_audit"] == {
            "status": "skipped",
            "reason": "story_identity_mismatch",
        }

    def test_implements_qa_layer_protocol(self) -> None:
        reviewer = SemanticReviewer()
        assert isinstance(reviewer, QALayer)

    def test_name_is_semantic_review(self) -> None:
        reviewer = SemanticReviewer()
        assert reviewer.name == "semantic_review"


# ---------------------------------------------------------------------------
# DocFidelityReviewer
# ---------------------------------------------------------------------------


class TestDocFidelityReviewer:
    """DocFidelityReviewer integration tests (AG3-026 Pass-2)."""

    def test_evaluate_returns_passed_on_empty_dir(self, tmp_path: Path) -> None:
        """PASS: empty story_dir has no .py files to check.

        With empty review_input, layer2_input.missing (MAJOR) is emitted,
        but no BLOCKING -> passed=True.
        """
        reviewer = DocFidelityReviewer(**_wired_audit_deps(tmp_path))
        result = reviewer.evaluate(_minimal_ctx(), tmp_path, review_input=_empty_ri())
        assert result.passed is True
        assert result.layer == "doc_fidelity"
        assert result.metadata["prompt_audit"] == {
            "status": "skipped",
            "reason": "project_root_unavailable",
        }

    def test_name_is_doc_fidelity(self) -> None:
        reviewer = DocFidelityReviewer()
        assert reviewer.name == "doc_fidelity"

    def test_implements_qa_layer_protocol(self) -> None:
        reviewer = DocFidelityReviewer()
        assert isinstance(reviewer, QALayer)
