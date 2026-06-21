"""Unit test for PromptRuntimeMaterializer (AG3-043 AK4 / FK-44 §44.4.2).

Proves the REAL materialization path end-to-end: a real ``PromptRuntime`` +
project-bound prompt bundle is used (no stub of PromptRuntime), so the
materialized prompt is resolved via ``materialize_prompt`` -- never a direct
resource read. Only the run-scope resolution (``StoryContextQueryPort``) is a
thin recording double (a state-backend grenze).
"""

from __future__ import annotations

import json
from hashlib import sha256
from typing import TYPE_CHECKING

import pytest

from agentkit.backend.artifacts import ArtifactManager, EnvelopeValidator, ProducerRegistry
from agentkit.backend.installer.paths import PROMPT_BUNDLE_STORE_ENV, prompt_bundle_store_dir
from agentkit.backend.prompt_runtime.register import register_prompt_runtime_producers
from agentkit.backend.prompt_runtime.resources import PROJECT_LOCK_RELPATH
from agentkit.backend.story_context_manager.models import StoryContext
from agentkit.backend.story_context_manager.types import StoryMode, StoryType
from agentkit.backend.verify_system.llm_evaluator.bundle import build_review_bundle
from agentkit.backend.verify_system.llm_evaluator.inputs import Layer2ReviewInput
from agentkit.backend.verify_system.llm_evaluator.prompt_materializer import (
    PromptRuntimeMaterializer,
)
from agentkit.backend.verify_system.llm_evaluator.structured_evaluator import (
    DOC_FIDELITY_CHECK_IDS,
    QA_REVIEW_CHECK_IDS,
    SEMANTIC_REVIEW_CHECK_IDS,
    ReviewerRole,
    template_name_for_role,
)
from agentkit.backend.verify_system.protocols import RunScope

if TYPE_CHECKING:
    from pathlib import Path

#: The real per-role prompt templates (W4: all roles, not just qa-review),
#: loaded from the canonical resources so the materialize path is proved for the
#: REAL prompt content of every role -- including the AG3-068
#: story_creation_review template (``vectordb-conflict``).
_REAL_TEMPLATE_NAMES = (
    "qa-review",
    "qa-semantic-review",
    "qa-doc-fidelity",
    "vectordb-conflict",
)


def _real_templates() -> dict[str, str]:
    from agentkit.backend.prompt_runtime.resources import load_prompt_template

    return {name: load_prompt_template(name) for name in _REAL_TEMPLATE_NAMES}


def _write_binding(project_root: Path) -> None:
    templates = _real_templates()
    bundle_dir = prompt_bundle_store_dir(
        "project-bound", "99", store_root=project_root / "prompt-bundles"
    )
    (bundle_dir / "internal" / "prompts").mkdir(parents=True)
    for name, content in templates.items():
        (bundle_dir / "internal" / "prompts" / f"{name}.md").write_text(
            content, encoding="utf-8"
        )
    entries = {
        name: {
            "relpath": f"internal/prompts/{name}.md",
            "sha256": sha256(content.encode("utf-8")).hexdigest(),
        }
        for name, content in templates.items()
    }
    manifest_text = json.dumps(
        {"bundle_id": "project-bound", "bundle_version": "99", "templates": entries}
    )
    (bundle_dir / "manifest.json").write_text(manifest_text, encoding="utf-8")
    lock_dir = project_root / PROJECT_LOCK_RELPATH.parent
    lock_dir.mkdir(parents=True, exist_ok=True)
    (project_root / PROJECT_LOCK_RELPATH).write_text(
        json.dumps(
            {
                "bundle_id": "project-bound",
                "bundle_version": "99",
                "binding_root": "prompts",
                "manifest_file": "manifest.json",
                "manifest_sha256": sha256(manifest_text.encode("utf-8")).hexdigest(),
                "templates": entries,
            }
        ),
        encoding="utf-8",
    )


class _FixedRunScopePort:
    """StoryContextQueryPort double: returns a fixed run scope (state grenze)."""

    def __init__(self, story_id: str) -> None:
        self._story_id = story_id

    def load(self, story_dir: Path) -> StoryContext | None:
        del story_dir
        return None

    def resolve_run_scope(self, story_dir: Path) -> RunScope | None:
        del story_dir
        return RunScope(run_id="run-1", story_id=self._story_id, attempt=1)


@pytest.fixture
def _manager(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ArtifactManager:
    monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
    monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")
    registry = ProducerRegistry()
    register_prompt_runtime_producers(registry)
    from agentkit.backend.state_backend.store.artifact_repository import (
        StateBackendArtifactRepository,
    )

    return ArtifactManager(
        repository=StateBackendArtifactRepository(store_dir=tmp_path),
        validator=EnvelopeValidator(registry),
    )


#: Role -> (a check-id that MUST appear in its materialized prompt). Pins the
#: per-role template content against the role's SSOT whitelist (W4).
_ROLE_EXPECTED_CHECK = {
    ReviewerRole.QA_REVIEW: sorted(QA_REVIEW_CHECK_IDS)[0],
    ReviewerRole.SEMANTIC_REVIEW: next(iter(SEMANTIC_REVIEW_CHECK_IDS)),
    ReviewerRole.DOC_FIDELITY: next(iter(DOC_FIDELITY_CHECK_IDS)),
    ReviewerRole.STORY_CREATION_REVIEW: "conflict_assessment",
}


@pytest.mark.parametrize("role", list(ReviewerRole))
def test_render_uses_materialized_prompt_and_template_sha(
    role: ReviewerRole,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    _manager: ArtifactManager,
) -> None:
    """W4: every one of the three real Layer-2 templates materializes correctly.

    Proves for ALL three roles (not just qa-review) that the prompt is resolved
    via ``materialize_prompt`` (placeholders rendered, story_id substituted) and
    that the returned ``template_sha256`` matches the bound template bytes.
    """
    _write_binding(tmp_path)
    monkeypatch.setenv(PROMPT_BUNDLE_STORE_ENV, str(tmp_path / "prompt-bundles"))
    ctx = StoryContext(
        project_key="test-project",
        story_id="AG3-001",
        story_type=StoryType.IMPLEMENTATION,
        execution_route=StoryMode.EXECUTION,
        project_root=tmp_path,
    )
    materializer = PromptRuntimeMaterializer(
        ctx=ctx,
        story_dir=tmp_path,
        artifact_manager=_manager,
        story_context_port=_FixedRunScopePort("AG3-001"),
    )
    bundle = build_review_bundle(
        Layer2ReviewInput(story_spec="b"), story_id="AG3-001", qa_cycle_round=1
    )
    resolved_ctx, story_id = materializer.context_for(bundle)
    assert story_id == "AG3-001"
    text, template_sha = materializer.render(role, resolved_ctx, story_id)
    # The materialized prompt is the rendered template (placeholders resolved).
    assert "AG3-001" in text
    assert "{story_id}" not in text  # placeholder was substituted
    assert _ROLE_EXPECTED_CHECK[role] in text
    expected_sha = sha256(
        _real_templates()[template_name_for_role(role)].encode("utf-8")
    ).hexdigest()
    assert template_sha == expected_sha


def test_context_for_rejects_story_id_mismatch(tmp_path: Path) -> None:
    ctx = StoryContext(
        project_key="test-project",
        story_id="AG3-001",
        story_type=StoryType.IMPLEMENTATION,
        execution_route=StoryMode.EXECUTION,
        project_root=tmp_path,
    )
    materializer = PromptRuntimeMaterializer(
        ctx=ctx,
        story_dir=tmp_path,
        artifact_manager=None,  # type: ignore[arg-type]  # not reached
        story_context_port=_FixedRunScopePort("AG3-001"),
    )
    bundle = build_review_bundle(
        Layer2ReviewInput(), story_id="OTHER-9", qa_cycle_round=1
    )
    from agentkit.backend.verify_system.llm_evaluator.llm_client import LlmClientError

    with pytest.raises(LlmClientError, match="identity check"):
        materializer.context_for(bundle)
