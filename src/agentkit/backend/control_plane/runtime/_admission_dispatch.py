"""Admission-time phase dispatcher resolution."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agentkit.backend.control_plane.dispatch import PhaseDispatcher
    from agentkit.backend.control_plane.models import (
        PhaseDispatchResult,
        PhaseMutationRequest,
    )
    from agentkit.backend.control_plane.repository import ControlPlaneRuntimeRepository

logger = logging.getLogger(__name__)


class _AdmissionDispatchMixin:
    """Resolve and invoke the deterministic phase dispatcher."""

    if TYPE_CHECKING:
        _repo: ControlPlaneRuntimeRepository
        _phase_dispatcher: PhaseDispatcher | None

    def _dispatch_phase(
        self,
        *,
        run_id: str,
        phase: str,
        request: PhaseMutationRequest,
        run_admitted: bool,
    ) -> PhaseDispatchResult | None:
        """Run the deterministic single-phase dispatch for a fresh start_phase.

        Resolves the run's :class:`StoryContext` through the sanctioned story read
        surface (same surface the mode resolution already uses) and drives the
        injected :class:`PhaseDispatcher`. Returns ``None`` when the story context
        is absent -- the idempotent persistence still commits, but no phase is
        dispatched (a missing context is surfaced by the dispatcher's own
        fail-closed path on the next resolvable call).

        AG3-054 ERROR-1 / AG3-142: the fresh-setup / first-call ADMISSION decision
        is computed RUN-scoped by the CALLER (``_evaluate_run_admission`` for THIS
        exact ``(project, story, run_id)`` -- since AG3-142, record-only) and
        threaded in here as ``run_admitted`` (a single admission read per call,
        never a second one). The dispatcher no longer derives "fresh" from
        story-scoped phase-state, so an OLD run's phase-state for the SAME story
        (after ``reset-escalation``, which mints a new run id but reuses the
        per-story story_dir) can never make a NEW, un-admitted run "not fresh" and
        SKIP the fail-closed pre-start guard.

        AG3-123: the Backend resolves the story-workspace filesystem anchor INSIDE
        the dispatcher via the injected ``StoryWorkspaceLocator`` (from canonical
        level-1 state, NOT ``ctx.project_root``). This method therefore no longer
        derives a ``story_dir`` from ``ctx.project_root`` -- the run-admission
        evaluation is decoupled from ``project_root`` resolvability. An unresolvable
        workspace is failed closed by the dispatcher as a structured rejection
        (``dispatched=False``); ``None`` is returned ONLY when the run
        ``StoryContext`` is absent, which the run-admission gate in
        :meth:`_start_phase_after_claim` handles fail-closed.
        """
        ctx = self._repo.load_story_context(request.project_key, request.story_id)
        if ctx is None:
            return None
        dispatcher = self._resolve_dispatcher()
        return dispatcher.dispatch(
            ctx=ctx,
            phase=phase,
            run_id=run_id,
            run_admitted=run_admitted,
            detail=request.detail,
        )

    def _resolve_dispatcher(self) -> PhaseDispatcher:
        """Return the injected dispatcher, lazily building the productive one."""
        if self._phase_dispatcher is None:
            from agentkit.backend.control_plane.dispatch import build_phase_dispatcher

            self._phase_dispatcher = build_phase_dispatcher()
        return self._phase_dispatcher


__all__ = ["_AdmissionDispatchMixin"]
