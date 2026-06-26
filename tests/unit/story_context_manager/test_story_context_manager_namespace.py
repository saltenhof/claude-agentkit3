from agentkit.backend.story_context_manager import PhaseState, PhaseStatus, StoryContext
from agentkit.backend.story_context_manager.types import StoryMode, StoryType


def test_story_context_manager_namespace_exposes_public_types() -> None:
    assert StoryContext.__name__ == "StoryContext"
    assert PhaseState.__name__ == "PhaseState"
    assert PhaseStatus.__name__ == "PhaseStatus"


def test_story_context_accepts_legacy_concept_paths_input() -> None:
    ctx = StoryContext(
        project_key="test-project",
        story_id="AG3-100",
        story_type=StoryType.IMPLEMENTATION,
        execution_route=StoryMode.EXECUTION,
        concept_paths=("concept/technical-design/21_story_creation_pipeline.md",),
    )

    assert ctx.concept_refs == ("concept/technical-design/21_story_creation_pipeline.md",)
