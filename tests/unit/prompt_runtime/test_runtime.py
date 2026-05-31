"""Top-surface tests for PromptRuntime (AG3-015 AK1-AK10).

Covers the four contract methods (materialize_prompt, create_run_pin,
update_binding, compute_audit_hash), audit persistence via ArtifactManager,
static/rendered render modes, stale-cache rejection and fail-closed paths.
"""

from __future__ import annotations

import json
from hashlib import sha256
from typing import TYPE_CHECKING

import pytest

from agentkit.artifacts import (
    ArtifactManager,
    EnvelopeValidator,
    ProducerRegistry,
)
from agentkit.core_types import ArtifactClass
from agentkit.exceptions import ProjectError
from agentkit.installer.paths import (
    PROMPT_BUNDLE_STORE_ENV,
    prompt_bundle_store_dir,
)
from agentkit.prompt_runtime.composer import ComposeConfig
from agentkit.prompt_runtime.pins import PromptRunPin
from agentkit.prompt_runtime.register import register_prompt_runtime_producers
from agentkit.prompt_runtime.resources import PROJECT_LOCK_RELPATH
from agentkit.prompt_runtime.runtime import PromptInstance, PromptRuntime
from agentkit.story_context_manager.models import StoryContext
from agentkit.story_context_manager.types import StoryMode, StoryType

if TYPE_CHECKING:
    from pathlib import Path


def _make_context(project_root: Path) -> StoryContext:
    return StoryContext(
        project_key="test-project",
        story_id="AG3-001",
        story_type=StoryType.IMPLEMENTATION,
        execution_route=StoryMode.EXECUTION,
        issue_nr=42,
        title="Add widget feature",
        project_root=project_root,
        worktree_path=None,
        worktree_map={},
        participating_repos=[],
    )


def _bundle_templates() -> dict[str, str]:
    return {
        "worker-implementation": (
            "# Project Bound Prompt {story_id}\n"
            "[SENTINEL:worker-implementation-v1:{story_id}]\n"
        ),
    }


def _write_binding(project_root: Path, *, version: str = "99") -> None:
    templates = _bundle_templates()
    bundle_dir = prompt_bundle_store_dir(
        "project-bound",
        version,
        store_root=project_root / "prompt-bundles",
    )
    (bundle_dir / "internal" / "prompts").mkdir(parents=True)
    for name, content in templates.items():
        (bundle_dir / "internal" / "prompts" / f"{name}.md").write_text(
            content, encoding="utf-8"
        )
    manifest_text = json.dumps(
        {
            "bundle_id": "project-bound",
            "bundle_version": version,
            "templates": {
                name: {
                    "relpath": f"internal/prompts/{name}.md",
                    "sha256": sha256(content.encode("utf-8")).hexdigest(),
                }
                for name, content in templates.items()
            },
        },
    )
    (bundle_dir / "manifest.json").write_text(manifest_text, encoding="utf-8")
    lock_dir = project_root / PROJECT_LOCK_RELPATH.parent
    lock_dir.mkdir(parents=True, exist_ok=True)
    (project_root / PROJECT_LOCK_RELPATH).write_text(
        json.dumps(
            {
                "bundle_id": "project-bound",
                "bundle_version": version,
                "binding_root": "prompts",
                "manifest_file": "manifest.json",
                "manifest_sha256": sha256(manifest_text.encode("utf-8")).hexdigest(),
                "templates": {
                    name: {
                        "relpath": f"internal/prompts/{name}.md",
                        "sha256": sha256(content.encode("utf-8")).hexdigest(),
                    }
                    for name, content in templates.items()
                },
            },
        ),
        encoding="utf-8",
    )


@pytest.fixture()
def manager(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ArtifactManager:
    monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
    monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")
    registry = ProducerRegistry()
    register_prompt_runtime_producers(registry)
    from agentkit.state_backend.store.artifact_repository import (
        StateBackendArtifactRepository,
    )

    return ArtifactManager(
        repository=StateBackendArtifactRepository(store_dir=tmp_path),
        validator=EnvelopeValidator(registry),
    )


class TestCreateRunPin:
    def test_returns_pydantic_pin_with_pinned_at(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write_binding(tmp_path)
        monkeypatch.setenv(PROMPT_BUNDLE_STORE_ENV, str(tmp_path / "prompt-bundles"))
        runtime = PromptRuntime(tmp_path)

        pin = runtime.create_run_pin("run-1")

        assert isinstance(pin, PromptRunPin)
        assert pin.prompt_bundle_id == "project-bound"
        assert pin.prompt_bundle_version == "99"
        assert pin.resolved_prompt_bundle_version == "99"
        assert pin.resolved_prompt_bundle_manifest_digest == pin.prompt_manifest_sha256
        assert pin.pinned_at.tzinfo is not None

    def test_pin_roundtrip(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write_binding(tmp_path)
        monkeypatch.setenv(PROMPT_BUNDLE_STORE_ENV, str(tmp_path / "prompt-bundles"))
        runtime = PromptRuntime(tmp_path)
        written = runtime.create_run_pin("run-1")
        loaded = runtime.load_run_pin("run-1")
        assert loaded is not None
        assert loaded.prompt_bundle_id == written.prompt_bundle_id
        assert loaded.prompt_bundle_version == written.prompt_bundle_version
        assert loaded.prompt_manifest_sha256 == written.prompt_manifest_sha256


class TestUpdateBinding:
    def test_writes_lock_for_future_runs(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write_binding(tmp_path, version="99")
        _write_binding(tmp_path, version="100")  # new version in store
        monkeypatch.setenv(PROMPT_BUNDLE_STORE_ENV, str(tmp_path / "prompt-bundles"))
        runtime = PromptRuntime(tmp_path)

        runtime.update_binding("project-bound", "100")

        lock = json.loads(
            (tmp_path / PROJECT_LOCK_RELPATH).read_text(encoding="utf-8")
        )
        assert lock["bundle_id"] == "project-bound"
        assert lock["bundle_version"] == "100"
        assert lock["manifest_file"] == "manifest.json"
        assert "manifest_sha256" in lock

    def test_active_run_stable_after_rebind(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """C2: a pinned run keeps its bundle after update_binding (AK6)."""
        _write_binding(tmp_path, version="99")
        monkeypatch.setenv(PROMPT_BUNDLE_STORE_ENV, str(tmp_path / "prompt-bundles"))
        runtime = PromptRuntime(tmp_path)
        runtime.create_run_pin("run-1")  # pins v99

        # Make v100 available in the store, then rebind the project lock.
        _write_binding(tmp_path, version="100")
        runtime.update_binding("project-bound", "100")

        from agentkit.prompt_runtime.pins import resolve_run_prompt_binding

        binding = resolve_run_prompt_binding(tmp_path, "run-1")
        assert binding.bundle_version == "99"  # still pinned

    def test_missing_bundle_is_fail_closed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(PROMPT_BUNDLE_STORE_ENV, str(tmp_path / "prompt-bundles"))
        runtime = PromptRuntime(tmp_path)
        with pytest.raises(ProjectError, match="missing prompt bundle manifest"):
            runtime.update_binding("project-bound", "nope")


class TestComputeAuditHash:
    def test_deterministic(
        self, tmp_path: Path
    ) -> None:
        runtime = PromptRuntime(tmp_path)
        a = runtime.compute_audit_hash(
            template_text="t", render_inputs={"a": "1"}, output_text="o"
        )
        b = runtime.compute_audit_hash(
            template_text="t", render_inputs={"a": "1"}, output_text="o"
        )
        assert a == b


class TestMaterializePrompt:
    def test_rendered_persists_audit_via_manager(
        self,
        tmp_path: Path,
        manager: ArtifactManager,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _write_binding(tmp_path)
        monkeypatch.setenv(PROMPT_BUNDLE_STORE_ENV, str(tmp_path / "prompt-bundles"))
        runtime = PromptRuntime(tmp_path, manager)
        runtime.create_run_pin("run-1")
        ctx = _make_context(tmp_path)

        instance = runtime.materialize_prompt(
            ctx,
            "worker-implementation",
            ComposeConfig(story_type=StoryType.IMPLEMENTATION),
            run_id="run-1",
            invocation_id="inv-1",
            render_mode="rendered",
        )

        assert isinstance(instance, PromptInstance)
        assert instance.render_mode == "rendered"
        assert instance.prompt_path == (
            tmp_path / ".agentkit" / "prompts" / "run-1" / "inv-1" / "prompt.md"
        )
        assert instance.prompt_path.is_file()
        # Audit record is retrievable via the ArtifactManager.
        assert instance.audit_reference.artifact_class is ArtifactClass.PROMPT_AUDIT
        loaded = manager.read(instance.audit_reference)
        assert loaded.payload is not None
        assert loaded.payload["render_mode"] == "rendered"
        assert loaded.payload["output_sha256"] == instance.audit_hash.output_sha256

    def test_static_persists_audit_and_projects_file(
        self,
        tmp_path: Path,
        manager: ArtifactManager,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _write_binding(tmp_path)
        monkeypatch.setenv(PROMPT_BUNDLE_STORE_ENV, str(tmp_path / "prompt-bundles"))
        runtime = PromptRuntime(tmp_path, manager)
        runtime.create_run_pin("run-1")
        ctx = _make_context(tmp_path)

        instance = runtime.materialize_prompt(
            ctx,
            "worker-implementation",
            ComposeConfig(story_type=StoryType.IMPLEMENTATION),
            run_id="run-1",
            invocation_id="inv-static",
            render_mode="static",
        )

        assert instance.render_mode == "static"
        assert instance.prompt_path.is_file()
        loaded = manager.read(instance.audit_reference)
        assert loaded.payload is not None
        assert loaded.payload["render_mode"] == "static"

    def test_unknown_render_mode_fail_closed(
        self,
        tmp_path: Path,
        manager: ArtifactManager,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _write_binding(tmp_path)
        monkeypatch.setenv(PROMPT_BUNDLE_STORE_ENV, str(tmp_path / "prompt-bundles"))
        runtime = PromptRuntime(tmp_path, manager)
        runtime.create_run_pin("run-1")
        ctx = _make_context(tmp_path)
        with pytest.raises(ProjectError, match="Unknown render_mode"):
            runtime.materialize_prompt(
                ctx,
                "worker-implementation",
                ComposeConfig(story_type=StoryType.IMPLEMENTATION),
                run_id="run-1",
                invocation_id="inv-x",
                render_mode="bogus",
            )

    def test_materialize_without_manager_fail_closed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write_binding(tmp_path)
        monkeypatch.setenv(PROMPT_BUNDLE_STORE_ENV, str(tmp_path / "prompt-bundles"))
        runtime = PromptRuntime(tmp_path)  # no ArtifactManager
        runtime.create_run_pin("run-1")
        ctx = _make_context(tmp_path)
        with pytest.raises(ProjectError, match="requires an ArtifactManager"):
            runtime.materialize_prompt(
                ctx,
                "worker-implementation",
                ComposeConfig(story_type=StoryType.IMPLEMENTATION),
                run_id="run-1",
                invocation_id="inv-1",
                render_mode="static",
            )


class TestRejectStaleLocalPromptCache:
    def test_identical_local_copy_is_allowed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write_binding(tmp_path)
        monkeypatch.setenv(PROMPT_BUNDLE_STORE_ENV, str(tmp_path / "prompt-bundles"))
        runtime = PromptRuntime(tmp_path)
        runtime.create_run_pin("run-1")
        canonical = (
            prompt_bundle_store_dir(
                "project-bound", "99", store_root=tmp_path / "prompt-bundles"
            )
            / "internal"
            / "prompts"
            / "worker-implementation.md"
        )
        local = tmp_path / "prompts" / "worker-implementation.md"
        local.parent.mkdir(parents=True, exist_ok=True)
        local.write_text(canonical.read_text(encoding="utf-8"), encoding="utf-8")

        # Identical projection: no error.
        runtime.reject_stale_local_prompt_cache(
            run_id="run-1",
            local_prompt_path=local,
            template_name="worker-implementation",
        )

    def test_stale_local_copy_is_rejected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write_binding(tmp_path)
        monkeypatch.setenv(PROMPT_BUNDLE_STORE_ENV, str(tmp_path / "prompt-bundles"))
        runtime = PromptRuntime(tmp_path)
        runtime.create_run_pin("run-1")
        local = tmp_path / "prompts" / "worker-implementation.md"
        local.parent.mkdir(parents=True, exist_ok=True)
        local.write_text("# STALE diverged copy\n", encoding="utf-8")

        with pytest.raises(ProjectError, match="Stale project-local prompt cache"):
            runtime.reject_stale_local_prompt_cache(
                run_id="run-1",
                local_prompt_path=local,
                template_name="worker-implementation",
            )
