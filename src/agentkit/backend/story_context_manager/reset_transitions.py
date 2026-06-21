"""Story-Reset administrative transition axis (story_context_manager BC).

AG3-071 (FK-53): the administrative Story-Reset axis is a cohesive lifecycle
sub-surface of :class:`agentkit.backend.story_context_manager.service.StoryService`.
It is extracted here as a focused mixin plus the runnable-status admission
helper so the reset axis owns one clear unit instead of being interleaved with
the generic frontend/pipeline transitions.

The reset axis is deliberately NOT wired into the generic
``cancel``/``begin_progress``/``complete`` surface; it is driven exclusively by
``StoryResetService`` (the ``story_reset`` BC) which consumes these methods via
its ``StoryStatusPort`` protocol.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from agentkit.backend.story_context_manager.story_model import StoryStatus
from agentkit.backend.story_context_manager.wire_adapter import story_to_wire_summary

if TYPE_CHECKING:
    from collections.abc import Callable

    from agentkit.backend.story_context_manager.story_model import Story
    from agentkit.backend.story_context_manager.story_repository import StoryRepository


#: AG3-071 (FK-53 §53.7.2/§53.9.2): stati in which a story may NOT enter or resume
#: a normal pipeline run. ``RESETTING`` is fenced for an in-flight administrative
#: reset; ``RESET_FAILED`` is the fail-closed blocked state of an aborted reset.
#: A start/resume/retry/scheduler admission MUST consult this set and refuse,
#: independent of the (non-terminal) status — only ``StoryResetService.resume_reset``
#: of the same reset_id may advance a ``RESET_FAILED`` story.
_RESET_NON_RUNNABLE_STATUSES: frozenset[StoryStatus] = frozenset({
    StoryStatus.RESETTING,
    StoryStatus.RESET_FAILED,
})


def is_story_runnable_status(status: StoryStatus) -> bool:
    """Return whether a status permits a normal pipeline start/resume/retry.

    Fail-closed admission helper for the Story-Reset axis (FK-53 §53.9.2,
    AG3-071): a story under an in-flight reset (``RESETTING``) or in the blocked
    post-abort state (``RESET_FAILED``) is NOT runnable. Every start, resume,
    retry and scheduler-admission path must gate on this so a reset cannot be
    silently bypassed by re-entering the normal pipeline.

    Args:
        status: The story's current lifecycle status.

    Returns:
        ``False`` when the status is a reset-blocked status, ``True`` otherwise.
    """
    return status not in _RESET_NON_RUNNABLE_STATUSES


class _ResetTransitionHost(Protocol):
    """Structural requirements the reset transitions need from their host.

    The mixin is composed onto ``StoryService``; this protocol pins the exact
    collaborators it consumes so the extraction stays type-checked under
    ``mypy --strict`` without leaking the whole service surface.
    """

    _story_repo: StoryRepository
    _emit: Callable[[str, str, dict[str, object]], None]

    def get_story_or_raise(self, story_display_id: str) -> Story: ...


class ResetTransitionMixin:
    """Administrative Story-Reset transitions (FK-53, AG3-071).

    Mixed into :class:`StoryService`. These are the ONLY legal reset
    transitions; driven exclusively by ``StoryResetService`` and not callable
    from the frontend.
    """

    def begin_reset(self: _ResetTransitionHost, story_display_id: str) -> Story:
        """Fence a story for an administrative reset (In Progress -> Resetting).

        FK-53 §53.7.2 (Schritt 2): the reset fences the story BEFORE any deletion.
        Driven exclusively by ``StoryResetService``; not callable from the
        frontend and not part of the generic cancel surface. The escalation/
        exception finding that justifies the reset is established separately from
        run/audit artifacts — it is NOT a story stammdaten status (FK-53 §53.4).

        Args:
            story_display_id: The story to fence.

        Returns:
            The fenced Story (status ``Resetting``).

        Raises:
            StoryNotFoundError: When the story does not exist.
            InvalidStatusTransitionError: When the story is not In Progress.
        """
        from agentkit.backend.story_context_manager.service import _check_transition

        story = self.get_story_or_raise(story_display_id)
        _check_transition(story.status, StoryStatus.RESETTING, context="begin_reset")
        story.status = StoryStatus.RESETTING
        self._story_repo.save(story)
        wire_summary = story_to_wire_summary(story)
        self._emit(story.project_key, story_display_id, wire_summary)
        return story

    def complete_reset(self: _ResetTransitionHost, story_display_id: str) -> Story:
        """Return a reset story to the restartable base (Resetting -> In Progress).

        FK-53 §53.8: a successful reset leaves the story as a non-running but
        restartable work unit. The restartable base in the StoryStatus owner is
        ``In Progress`` (a later restart is a NEW execution epoch, not a resume of
        the purged run). This deliberately does NOT emit/set ``Cancelled`` — a
        reset keeps the story alive (counter-evidence to the FK-91 drift
        ``story_cancelled_administratively``).

        Args:
            story_display_id: The reset story to release.

        Returns:
            The released Story (status ``In Progress``).

        Raises:
            StoryNotFoundError: When the story does not exist.
            InvalidStatusTransitionError: When the story is not Resetting.
        """
        from agentkit.backend.story_context_manager.service import _check_transition

        story = self.get_story_or_raise(story_display_id)
        _check_transition(
            story.status, StoryStatus.IN_PROGRESS, context="complete_reset"
        )
        story.status = StoryStatus.IN_PROGRESS
        self._story_repo.save(story)
        wire_summary = story_to_wire_summary(story)
        self._emit(story.project_key, story_display_id, wire_summary)
        return story

    def mark_reset_failed(self: _ResetTransitionHost, story_display_id: str) -> Story:
        """Block a story after an aborted reset (Resetting -> Reset Failed).

        FK-53 §53.9.2: a reset that fails mid-flow leaves the story
        administratively blocked. ``Reset Failed`` is NOT runnable
        (:func:`is_story_runnable_status`) — only ``StoryResetService.resume_reset``
        of the same reset_id may move it on.

        Args:
            story_display_id: The story to mark blocked.

        Returns:
            The blocked Story (status ``Reset Failed``).

        Raises:
            StoryNotFoundError: When the story does not exist.
            InvalidStatusTransitionError: When the story is not Resetting.
        """
        from agentkit.backend.story_context_manager.service import _check_transition

        story = self.get_story_or_raise(story_display_id)
        _check_transition(
            story.status, StoryStatus.RESET_FAILED, context="mark_reset_failed"
        )
        story.status = StoryStatus.RESET_FAILED
        self._story_repo.save(story)
        wire_summary = story_to_wire_summary(story)
        self._emit(story.project_key, story_display_id, wire_summary)
        return story

    def resume_reset_transition(
        self: _ResetTransitionHost, story_display_id: str
    ) -> Story:
        """Re-fence a blocked reset story (Reset Failed -> Resetting).

        FK-53 §53.9.2: a re-run with the same reset_id is a resume, not a new
        reset. This moves a ``Reset Failed`` story back to ``Resetting`` so the
        SAME reset operation can converge its remaining purge domains. Idempotent
        at the call site: a story already ``Resetting`` is returned unchanged.

        Args:
            story_display_id: The blocked story to re-fence.

        Returns:
            The re-fenced Story (status ``Resetting``).

        Raises:
            StoryNotFoundError: When the story does not exist.
            InvalidStatusTransitionError: When the story is neither Reset Failed
                nor already Resetting.
        """
        from agentkit.backend.story_context_manager.service import _check_transition

        story = self.get_story_or_raise(story_display_id)
        if story.status is StoryStatus.RESETTING:
            return story
        _check_transition(
            story.status, StoryStatus.RESETTING, context="resume_reset_transition"
        )
        story.status = StoryStatus.RESETTING
        self._story_repo.save(story)
        wire_summary = story_to_wire_summary(story)
        self._emit(story.project_key, story_display_id, wire_summary)
        return story
