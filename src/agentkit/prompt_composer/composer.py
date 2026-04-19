"""Prompt composition -- builds complete prompts from templates and context."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

from agentkit.installer.paths import prompt_instance_dir
from agentkit.prompt_composer.resources import (
    load_prompt_template,
    prompt_bundle_id,
    prompt_bundle_version,
    prompt_template_relpath,
    prompt_template_sha256,
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
    template_name: str
    template_relpath: str
    template_sha256: str
    rendered_sha256: str
    story_id: str
    sentinel: str


@dataclass(frozen=True)
class MaterializedPromptInstance:
    prompt_path: Path
    manifest_path: Path


@dataclass(frozen=True)
class ComposeConfig:
    story_type: StoryType
    mode: StoryMode | None = None
    spawn_reason: str = "initial"
    round_nr: int = 1
    feedback: str = ""

    @property
    def execution_route(self) -> StoryMode | None:
        """Semantic alias for the historic ``mode`` configuration field."""

        return self.mode


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


def compose_prompt(
    ctx: StoryContext,
    config: ComposeConfig,
) -> ComposedPrompt:
    template_name = select_template_name(
        story_type=config.story_type,
        execution_route=config.execution_route,
        spawn_reason=config.spawn_reason,
    )
    project_root = ctx.project_root
    template = load_prompt_template(template_name, project_root=project_root)
    placeholders = _build_placeholder_map(ctx, config)
    content = template.format_map(placeholders)

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
    rendered_sha256 = hashlib.sha256(
        content.encode("utf-8"),
    ).hexdigest()

    return ComposedPrompt(
        content=content,
        prompt_bundle_id=prompt_bundle_id(project_root),
        prompt_bundle_version=prompt_bundle_version(project_root),
        template_name=template_name,
        template_relpath=prompt_template_relpath(
            template_name,
            project_root=project_root,
        ),
        template_sha256=prompt_template_sha256(
            template_name,
            project_root=project_root,
        ),
        rendered_sha256=rendered_sha256,
        story_id=ctx.story_id,
        sentinel=sentinel,
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
                "template_name": prompt.template_name,
                "template_relpath": prompt.template_relpath,
                "template_sha256": prompt.template_sha256,
                "rendered_sha256": prompt.rendered_sha256,
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

__all__ = [
    "ComposeConfig",
    "ComposedPrompt",
    "MaterializedPromptInstance",
    "compose_prompt",
    "write_prompt",
    "write_prompt_instance",
]
