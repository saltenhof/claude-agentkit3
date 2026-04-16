"""Prompt composition -- builds complete prompts from templates and context."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from agentkit.prompt_composer.selectors import select_template_name
from agentkit.prompt_composer.sentinels import extract_sentinel
from agentkit.prompt_composer.templates import TEMPLATES
from agentkit.utils.io import atomic_write_text

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.story_context_manager.models import StoryContext
    from agentkit.story_context_manager.types import StoryMode, StoryType


@dataclass(frozen=True)
class ComposedPrompt:
    content: str
    template_name: str
    story_id: str
    sentinel: str


@dataclass(frozen=True)
class ComposeConfig:
    story_type: StoryType
    mode: StoryMode | None = None
    spawn_reason: str = "initial"
    round_nr: int = 1
    feedback: str = ""


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
        "mode": str(ctx.mode.value) if ctx.mode else "N/A",
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
        mode=config.mode,
        spawn_reason=config.spawn_reason,
    )
    template = TEMPLATES[template_name]
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

    return ComposedPrompt(
        content=content,
        template_name=template_name,
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

__all__ = [
    "ComposeConfig",
    "ComposedPrompt",
    "compose_prompt",
    "write_prompt",
]
