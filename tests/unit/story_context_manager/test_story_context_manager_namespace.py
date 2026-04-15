from agentkit.story import StoryContext as LegacyStoryContext
from agentkit.story_context_manager import StoryContext


def test_story_context_manager_namespace_reexports_legacy_api() -> None:
    assert StoryContext is LegacyStoryContext
