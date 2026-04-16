from agentkit.story_context_manager import PhaseState, PhaseStatus, StoryContext


def test_story_context_manager_namespace_exposes_public_types() -> None:
    assert StoryContext.__name__ == "StoryContext"
    assert PhaseState.__name__ == "PhaseState"
    assert PhaseStatus.__name__ == "PhaseStatus"
