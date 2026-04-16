from pathlib import Path

from agentkit.prompt_composer import ComposeConfig, compose_prompt
from agentkit.story_context_manager import StoryContext
from agentkit.story_context_manager.types import StoryMode, StoryType


def test_prompt_composer_namespace_exposes_composition_api() -> None:
    ctx = StoryContext(
        story_id="AG3-001",
        story_type=StoryType.IMPLEMENTATION,
        mode=StoryMode.EXECUTION,
        issue_nr=42,
        title="Add widget feature",
        project_root=Path("/tmp/project"),
    )

    prompt = compose_prompt(ctx, ComposeConfig(story_type=StoryType.IMPLEMENTATION))
    assert prompt.template_name == "worker-implementation"
