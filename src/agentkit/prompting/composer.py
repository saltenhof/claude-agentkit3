"""Prompt composition -- builds complete prompts from templates and context."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from agentkit.prompting.selectors import select_template_name
from agentkit.prompting.sentinels import extract_sentinel
from agentkit.prompting.templates import TEMPLATES
from agentkit.utils.io import atomic_write_text

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.story.models import StoryContext
    from agentkit.story.types import StoryMode, StoryType


@dataclass(frozen=True)
class ComposedPrompt:
    """Result of prompt composition.

    Args:
        content: The fully rendered prompt text.
        template_name: Which template was used (key into ``TEMPLATES``).
        story_id: Story identifier embedded in the prompt.
        sentinel: The sentinel marker string present in the prompt.
    """

    content: str
    template_name: str
    story_id: str
    sentinel: str


@dataclass(frozen=True)
class ComposeConfig:
    """Configuration for prompt composition.

    Args:
        story_type: The type of story being processed.
        mode: Execution mode (may be ``None``).
        spawn_reason: Why the worker is being spawned.
        round_nr: Review/remediation round number.
        feedback: QA feedback text for remediation prompts.
    """

    story_type: StoryType
    mode: StoryMode | None = None
    spawn_reason: str = "initial"
    round_nr: int = 1
    feedback: str = ""


def _build_placeholder_map(
    ctx: StoryContext,
    config: ComposeConfig,
) -> dict[str, str]:
    """Build the placeholder map from story context and compose config.

    Args:
        ctx: The durable story context.
        config: Composition configuration.

    Returns:
        Dictionary mapping placeholder names to their string values.
    """
    project_root = (
        str(ctx.project_root)
        if ctx.project_root is not None
        else "N/A"
    )
    body = (
        config.feedback
        if config.spawn_reason == "remediation"
        else ctx.title
    )
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
    """Compose a worker prompt from a template and story context.

    Steps:

    1. Select template via :func:`select_template_name`.
    2. Build placeholder map from :class:`StoryContext` and
       :class:`ComposeConfig`.
    3. Render template with :meth:`str.format_map`.
    4. Extract sentinel from rendered text.
    5. Return :class:`ComposedPrompt`.

    Args:
        ctx: The durable story context providing story metadata.
        config: Composition configuration (type, mode, round, etc.).

    Returns:
        A fully composed prompt with metadata.

    Raises:
        KeyError: If a required placeholder is missing from the
            placeholder map.
        ValueError: If the rendered prompt does not contain a valid
            sentinel marker.
    """
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

    # Reconstruct the sentinel string from extracted components
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
    """Write a composed prompt to disk.

    The filename follows the pattern::

        {template_name}--{spawn_reason}--r{round_nr}.md

    Uses :func:`~agentkit.project_ops.shared.file_ops.atomic_write_text`
    for crash-safe writing.

    Args:
        prompt: The composed prompt to write.
        output_dir: Directory where the prompt file will be created.
        spawn_reason: Why the worker is being spawned (used in filename).
        round_nr: Review/remediation round number (used in filename).

    Returns:
        The path to the written file.
    """
    filename = (
        f"{prompt.template_name}--{spawn_reason}--r{round_nr}.md"
    )
    path = output_dir / filename
    atomic_write_text(path, prompt.content)
    return path
