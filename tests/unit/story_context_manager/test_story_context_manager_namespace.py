from agentkit.backend.pipeline_engine.phase_executor import PhaseState, PhaseStatus
from agentkit.backend.story_context_manager import StoryContext
from agentkit.backend.story_context_manager.types import StoryMode, StoryType


def test_story_context_manager_namespace_exposes_public_types() -> None:
    assert StoryContext.__name__ == "StoryContext"


def test_phase_state_models_are_owned_by_the_pipeline_engine() -> None:
    """FK-39 §39.7: phase-state model ownership is ``pipeline_engine.phase_executor``.

    The ``story_context_manager`` re-export bridge that used to serve these names
    is REMOVED (2026-08-02): a second import path for one model is a compat
    construct, and the owner is unambiguous.
    """
    import agentkit.backend.story_context_manager as scm

    assert PhaseState.__name__ == "PhaseState"
    assert PhaseStatus.__name__ == "PhaseStatus"
    for name in ("PhaseSnapshot", "PhaseState", "PhaseStatus"):
        assert not hasattr(scm, name), f"{name} must not be re-exported by story_context_manager"


def test_story_context_requires_the_canonical_concept_refs_key() -> None:
    """``concept_paths`` is REMOVED as an input alias — one key, one meaning.

    Reading old AND new spellings for the same fact is exactly the dual-read
    compat the no-compat-layers rule forbids; ``concept_refs`` is the only key.
    """
    ctx = StoryContext(
        project_key="test-project",
        story_id="AG3-100",
        story_type=StoryType.IMPLEMENTATION,
        execution_route=StoryMode.EXECUTION,
        concept_refs=("concept/technical-design/21_story_creation_pipeline.md",),
    )

    assert ctx.concept_refs == ("concept/technical-design/21_story_creation_pipeline.md",)
