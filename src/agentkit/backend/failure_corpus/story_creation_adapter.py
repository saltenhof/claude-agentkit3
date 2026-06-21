"""AK3StoryCreationAdapter — concrete StoryCreationPort implementation (FK-41 §41.6.6, AG3-078).

Transport-agnostic story-creation adapter that calls the AK3 story-creation
surface (``StoryService.create_story``) — no direct GitHub/CLI coupling.

Sources:
- FK-41 §41.6.6 -- create_check_implementation_story (transport-agnostic)
- FK-91 §91.1a -- StoryService.create_story
"""

from __future__ import annotations

import uuid

from agentkit.backend.failure_corpus.check_factory import StoryCreationPort


class AK3StoryCreationAdapter:
    """Concrete StoryCreationPort: delegates to ``StoryService.create_story``.

    Creates an Implementation-type story whose title carries the sharpened
    invariant (``"[FC-CHECK] Implement check {check_id}: {invariant}"``) in the
    given project. The ``check_id``, ``pattern_ref`` and ``check_type`` travel as
    typed labels so the implementing worker can route by check type.

    Args:
        project_key: Project key for the created story.

    Raises:
        RuntimeError: If story creation fails (FAIL-CLOSED: story must be
            created before the check is set ACTIVE, FK-41 §41.6.6).
    """

    def __init__(self, project_key: str) -> None:
        self._project_key = project_key

    def create_check_implementation_story(
        self,
        check_id: str,
        pattern_ref: str,
        invariant: str,
        check_type: str,
    ) -> str:
        """Create an implementation story for a check proposal (FK-41 §41.6.6).

        Args:
            check_id: The check proposal identity (CHK-NNNN).
            pattern_ref: The parent pattern identity (FP-NNNN).
            invariant: The sharpened invariant statement.
            check_type: The check-type wire value.

        Returns:
            The display_id of the created story.

        Raises:
            RuntimeError: If story creation fails (FAIL-CLOSED).
        """
        from agentkit.backend.story_context_manager.service import StoryService
        from agentkit.backend.story_context_manager.story_model import (
            CreateStoryInput,
            WireStoryType,
        )

        try:
            service = StoryService()
            title = f"[FC-CHECK] Implement check {check_id}: {invariant}"
            request = CreateStoryInput(
                project_key=self._project_key,
                title=title,
                story_type=WireStoryType.IMPLEMENTATION,
                repos=[self._project_key],
                epic="failure-corpus",
                module="failure-corpus",
                owner="failure-corpus",
                labels=[
                    f"fc-check:{check_id}",
                    f"pattern:{pattern_ref}",
                    f"check-type:{check_type}",
                ],
            )
            op_id = f"fc-check-story-{check_id}-{uuid.uuid4().hex[:8]}"
            story = service.create_story(request, op_id=op_id)
            return story.story_display_id
        except Exception as exc:
            raise RuntimeError(
                f"AK3StoryCreationAdapter: failed to create implementation story "
                f"for check {check_id!r} — FAIL-CLOSED (FK-41 §41.6.6): {exc}"
            ) from exc


# Verify protocol compliance at import time.
assert isinstance(AK3StoryCreationAdapter("_"), StoryCreationPort), (
    "AK3StoryCreationAdapter must satisfy StoryCreationPort protocol"
)


__all__ = [
    "AK3StoryCreationAdapter",
]
