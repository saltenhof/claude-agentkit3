"""Prompt composition -- builds complete prompts from templates and context."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

from agentkit.exceptions import ProjectError
from agentkit.installer.paths import prompt_instance_dir
from agentkit.prompt_composer.pins import (
    initialize_prompt_run_pin,
    resolve_run_prompt_binding,
)
from agentkit.prompt_composer.resources import (
    load_prompt_template,
    prompt_template_relpath,
    prompt_template_sha256,
    resolve_bootstrap_prompt_binding,
)
from agentkit.prompt_composer.selectors import select_template_name
from agentkit.prompt_composer.sentinels import extract_sentinel
from agentkit.utils.io import atomic_write_text

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.story_context_manager.models import StoryContext
    from agentkit.story_context_manager.types import StoryMode, StoryType


@dataclass(frozen=True)
class ComposedPrompt:
    content: str
    prompt_bundle_id: str
    prompt_bundle_version: str
    prompt_manifest_sha256: str
    logical_prompt_id: str
    template_name: str
    template_relpath: str
    render_mode: str
    template_sha256: str
    render_input_digest: str
    output_sha256: str
    story_id: str
    sentinel: str


@dataclass(frozen=True)
class MaterializedPromptInstance:
    prompt_path: Path
    manifest_path: Path


@dataclass(frozen=True)
class RenderedPromptArtifact:
    prompt_path: Path
    manifest_path: Path


@dataclass(frozen=True)
class ComposeConfig:
    story_type: StoryType
    execution_route: StoryMode | None = None
    spawn_reason: str = "initial"
    round_nr: int = 1
    feedback: str = ""


@dataclass(frozen=True)
class _ResolvedPromptSource:
    binding_bundle_id: str
    binding_bundle_version: str
    binding_manifest_sha256: str
    template_text: str
    template_relpath: str
    template_sha256: str


def _build_placeholder_map(
    ctx: StoryContext,
    config: ComposeConfig,
) -> dict[str, str]:
    project_root = str(ctx.project_root) if ctx.project_root is not None else "N/A"
    body = config.feedback if config.spawn_reason == "remediation" else ctx.title
    return {
        "story_id": ctx.story_id,
        "title": ctx.title,
        "issue_nr": str(ctx.issue_nr) if ctx.issue_nr is not None else "N/A",
        "mode": str(ctx.execution_route.value) if ctx.execution_route else "N/A",
        "size": "N/A",
        "body": body,
        "project_root": project_root,
        "round_nr": str(config.round_nr),
        "feedback": config.feedback,
    }


def _logical_prompt_id(template_name: str) -> str:
    return f"prompt.{template_name}"


def _render_input_digest(placeholders: dict[str, str]) -> str:
    return hashlib.sha256(
        json.dumps(placeholders, sort_keys=True).encode("utf-8"),
    ).hexdigest()


def _resolve_prompt_source(
    *,
    template_name: str,
    project_root: Path | None,
    story_id: str,
    run_id: str | None,
) -> _ResolvedPromptSource:
    if project_root is None:
        binding = resolve_bootstrap_prompt_binding()
        template = load_prompt_template(template_name)
    else:
        if run_id is None:
            raise ProjectError(
                "Prompt composition for a project-bound run requires run_id",
                detail={"story_id": story_id},
            )
        binding = resolve_run_prompt_binding(project_root, run_id)
        template = load_prompt_template(template_name, project_root=project_root)

    return _ResolvedPromptSource(
        binding_bundle_id=binding.bundle_id,
        binding_bundle_version=binding.bundle_version,
        binding_manifest_sha256=binding.manifest_sha256,
        template_text=template,
        template_relpath=prompt_template_relpath(
            template_name,
            project_root=project_root,
        ),
        template_sha256=prompt_template_sha256(
            template_name,
            project_root=project_root,
        ),
    )


def compose_named_prompt(
    ctx: StoryContext,
    template_name: str,
    config: ComposeConfig,
    *,
    run_id: str | None = None,
) -> ComposedPrompt:
    project_root = ctx.project_root
    source = _resolve_prompt_source(
        template_name=template_name,
        project_root=project_root,
        story_id=ctx.story_id,
        run_id=run_id,
    )
    placeholders = _build_placeholder_map(ctx, config)
    render_input_digest = _render_input_digest(placeholders)
    content = source.template_text.format_map(placeholders)

    sentinel_data = extract_sentinel(content)
    if sentinel_data is None:
        msg = (
            f"Rendered template '{template_name}' does not contain a "
            f"valid sentinel marker"
        )
        raise ValueError(msg)

    sentinel = (
        f"[SENTINEL:{sentinel_data['template']}"
        f"-v{sentinel_data['version']}"
        f":{sentinel_data['story_id']}]"
    )
    output_sha256 = hashlib.sha256(
        content.encode("utf-8"),
    ).hexdigest()

    return ComposedPrompt(
        content=content,
        prompt_bundle_id=source.binding_bundle_id,
        prompt_bundle_version=source.binding_bundle_version,
        prompt_manifest_sha256=source.binding_manifest_sha256,
        logical_prompt_id=_logical_prompt_id(template_name),
        template_name=template_name,
        template_relpath=source.template_relpath,
        render_mode="rendered",
        template_sha256=source.template_sha256,
        render_input_digest=render_input_digest,
        output_sha256=output_sha256,
        story_id=ctx.story_id,
        sentinel=sentinel,
    )


def compose_prompt(
    ctx: StoryContext,
    config: ComposeConfig,
    *,
    run_id: str | None = None,
) -> ComposedPrompt:
    template_name = select_template_name(
        story_type=config.story_type,
        execution_route=config.execution_route,
        spawn_reason=config.spawn_reason,
    )
    return compose_named_prompt(
        ctx,
        template_name,
        config,
        run_id=run_id,
    )


def write_prompt(
    prompt: ComposedPrompt,
    output_dir: Path,
    *,
    spawn_reason: str = "initial",
    round_nr: int = 1,
) -> Path:
    filename = f"{prompt.template_name}--{spawn_reason}--r{round_nr}.md"
    path = output_dir / filename
    atomic_write_text(path, prompt.content)
    return path


def write_prompt_instance(
    prompt: ComposedPrompt,
    project_root: Path,
    *,
    run_id: str,
    invocation_id: str,
) -> MaterializedPromptInstance:
    """Write the canonical run-scoped prompt artifact set."""

    output_dir = prompt_instance_dir(project_root, run_id, invocation_id)
    initialize_prompt_run_pin(project_root, run_id=run_id)
    binding = resolve_run_prompt_binding(project_root, run_id)
    if (
        prompt.prompt_bundle_id != binding.bundle_id
        or prompt.prompt_bundle_version != binding.bundle_version
        or prompt.prompt_manifest_sha256 != binding.manifest_sha256
    ):
        raise ProjectError(
            "Prompt instance metadata does not match the active run pin",
            detail={
                "run_id": run_id,
                "expected": {
                    "prompt_bundle_id": binding.bundle_id,
                    "prompt_bundle_version": binding.bundle_version,
                    "prompt_manifest_sha256": binding.manifest_sha256,
                },
                "actual": {
                    "prompt_bundle_id": prompt.prompt_bundle_id,
                    "prompt_bundle_version": prompt.prompt_bundle_version,
                    "prompt_manifest_sha256": prompt.prompt_manifest_sha256,
                },
            },
        )
    prompt_path = output_dir / "prompt.md"
    manifest_path = output_dir / "manifest.json"
    atomic_write_text(prompt_path, prompt.content)
    atomic_write_text(
        manifest_path,
        json.dumps(
            {
                "run_id": run_id,
                "invocation_id": invocation_id,
                "story_id": prompt.story_id,
                "prompt_bundle_id": prompt.prompt_bundle_id,
                "prompt_bundle_version": prompt.prompt_bundle_version,
                "prompt_manifest_sha256": prompt.prompt_manifest_sha256,
                "prompt_instance_id": invocation_id,
                "logical_prompt_id": prompt.logical_prompt_id,
                "template_name": prompt.template_name,
                "template_relpath": prompt.template_relpath,
                "render_mode": prompt.render_mode,
                "template_sha256": prompt.template_sha256,
                "render_input_digest": prompt.render_input_digest,
                "output_sha256": prompt.output_sha256,
                "artifact_path": prompt_path.relative_to(project_root).as_posix(),
                "prompt_file": "prompt.md",
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
    )
    return MaterializedPromptInstance(
        prompt_path=prompt_path,
        manifest_path=manifest_path,
    )


def write_rendered_prompt_artifact(
    prompt: ComposedPrompt,
    project_root: Path,
    *,
    run_id: str,
    invocation_id: str,
    artifact_name: str = "rendered-prompt.md",
) -> RenderedPromptArtifact:
    """Write a run-scoped rendered prompt artifact for non-agent consumers."""

    output_dir = prompt_instance_dir(project_root, run_id, invocation_id)
    initialize_prompt_run_pin(project_root, run_id=run_id)
    binding = resolve_run_prompt_binding(project_root, run_id)
    if (
        prompt.prompt_bundle_id != binding.bundle_id
        or prompt.prompt_bundle_version != binding.bundle_version
        or prompt.prompt_manifest_sha256 != binding.manifest_sha256
    ):
        raise ProjectError(
            "Rendered prompt metadata does not match the active run pin",
            detail={
                "run_id": run_id,
                "expected": {
                    "prompt_bundle_id": binding.bundle_id,
                    "prompt_bundle_version": binding.bundle_version,
                    "prompt_manifest_sha256": binding.manifest_sha256,
                },
                "actual": {
                    "prompt_bundle_id": prompt.prompt_bundle_id,
                    "prompt_bundle_version": prompt.prompt_bundle_version,
                    "prompt_manifest_sha256": prompt.prompt_manifest_sha256,
                },
            },
        )
    prompt_path = output_dir / artifact_name
    manifest_path = output_dir / "rendered-manifest.json"
    atomic_write_text(prompt_path, prompt.content)
    atomic_write_text(
        manifest_path,
        json.dumps(
            {
                "run_id": run_id,
                "invocation_id": invocation_id,
                "prompt_instance_id": invocation_id,
                "story_id": prompt.story_id,
                "artifact_kind": "rendered_prompt",
                "prompt_bundle_id": prompt.prompt_bundle_id,
                "prompt_bundle_version": prompt.prompt_bundle_version,
                "prompt_manifest_sha256": prompt.prompt_manifest_sha256,
                "logical_prompt_id": prompt.logical_prompt_id,
                "template_name": prompt.template_name,
                "template_relpath": prompt.template_relpath,
                "render_mode": prompt.render_mode,
                "template_sha256": prompt.template_sha256,
                "render_input_digest": prompt.render_input_digest,
                "output_sha256": prompt.output_sha256,
                "artifact_path": prompt_path.relative_to(project_root).as_posix(),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
    )
    return RenderedPromptArtifact(
        prompt_path=prompt_path,
        manifest_path=manifest_path,
    )

__all__ = [
    "ComposeConfig",
    "ComposedPrompt",
    "MaterializedPromptInstance",
    "RenderedPromptArtifact",
    "compose_named_prompt",
    "compose_prompt",
    "write_rendered_prompt_artifact",
    "write_prompt",
    "write_prompt_instance",
]
