"""Productive ``ExplorationWorkerRunner`` adapter (AG3-055, FK-23 §23.3 / FK-43).

The bloodgroup-A :class:`~agentkit.backend.exploration.drafting.drafting.ExplorationDrafting`
core obtains the worker-produced change-frame through the
:class:`~agentkit.backend.exploration.drafting.ports.ExplorationWorkerRunner` boundary
port. This module is the PRODUCTIVE adapter: it materializes the
``worker-exploration.md`` prompt over the EXISTING AG3-044 worker-spawn path
(``WorkerSession`` -> ``PromptRuntime.materialize_prompt``, FK-44; the selector
picks ``worker-exploration`` for an EXPLORATION ``execution_route``) and then
reads back the worker's raw seven-part change-frame draft.

There is NO parallel spawn path: the exploration worker reuses the WORKER spawn
mechanics (``SpawnKind.WORKER``, ``SpawnReason.INITIAL``) with the exploration
prompt template (there is no EXPLORATION ``SpawnKind``). The worker -- the
non-deterministic harness actor (FK-23 §23.3) -- writes its raw draft to
``_temp/qa/{story_id}/change_frame.draft.json`` (FK-23 §23.3.2 step 6 output);
this adapter reads it across the boundary and hands the raw payload to the
drafting core, which validates it (``ChangeFrame.from_payload``) and writes the
canonical, protected ``change_frame.json``.

Fail-closed (FK-23 §23.3 / ZERO DEBT): a missing raw draft yields an EMPTY
result (``payload=None``) -> the drafting core rejects fail-closed (no artifact).
A present-but-unreadable raw draft RAISES (never a silent empty result). This is
the worker boundary -- the only sanctioned MOCKS-exception seam; the drafting
core's orchestration runs for real.

ERROR-2 scope discipline (FK-26 §26.2 / FAIL-CLOSED): the StoryContext used to
materialize the prompt is the persisted context at ``story_dir`` -- which is NOT
necessarily the requested ``(story_id, run_id)``. The runner cross-checks the
persisted context's ``story_id`` against the requested one AND the bound run id
against the requested ``run_id`` BEFORE materializing the prompt and BEFORE
reading the draft. On any mismatch (or an unresolvable context / run binding) it
fails closed: no prompt is materialized and no draft is read, so the prompt
context and the artifact identity can never diverge (prompt for story B while the
artifact is read for story A).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from agentkit.backend.core_types import SpawnReason
from agentkit.backend.core_types.qa_artifact_names import CHANGE_FRAME_DRAFT_FILE
from agentkit.backend.exceptions import CorruptStateError
from agentkit.backend.exploration.drafting.ports import ExplorationWorkerResult
from agentkit.backend.implementation.worker_session.session import (
    WorkerSession,
    build_state_backend_context_loader,
)
from agentkit.backend.installer.paths import resolve_qa_story_dir
from agentkit.backend.state_backend.pipeline_runtime_store import load_flow_execution
from agentkit.backend.state_backend.story_lifecycle_store import load_story_context

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.backend.prompt_runtime.runtime import PromptRuntime
    from agentkit.backend.story_context_manager.models import StoryContext


class StateBackendExplorationWorkerRunner:
    """Productive :class:`ExplorationWorkerRunner` over the AG3-044 spawn path.

    Args:
        story_dir: The story working directory (worker spawn context loader root
            + the ``_temp/qa/{story_id}/`` raw-draft location).
        prompt_runtime: The run-bound prompt runtime (FK-44) used to materialize
            the ``worker-exploration.md`` prompt instance.
    """

    def __init__(self, story_dir: Path, prompt_runtime: PromptRuntime) -> None:
        self._story_dir = story_dir
        self._prompt_runtime = prompt_runtime

    def run_exploration_worker(
        self, ctx: StoryContext, *, run_id: str, invocation_id: str
    ) -> ExplorationWorkerResult:
        """Materialize the prompt, spawn the worker, return its raw draft.

        Args:
            ctx: The authoritative story context for the run.
            run_id: The bound run correlation id (FK-02 §2.3.1 UUID).
            invocation_id: The spawn/invocation id (prompt-audit correlation).

        Returns:
            An :class:`ExplorationWorkerResult` carrying the worker's raw
            seven-part change-frame payload (``None`` when the worker produced no
            draft -> fail-closed in the drafting core) and the materialized
            prompt path.

        Raises:
            CorruptStateError: When the worker spawn context cannot be resolved
                (no ``StoryContext`` for the run), the persisted context / run
                binding does not match the requested ``(story_id, run_id)`` scope
                (ERROR-2; no prompt, no draft read), or the raw draft is present
                but unreadable / not a JSON object (fail-closed; never a silent
                skip).
            ProjectError: When the prompt bundle is missing / unbound (FK-44).
        """
        # ERROR-2 (FAIL-CLOSED): the prompt is materialized from the StoryContext
        # persisted at ``story_dir``, which the context loader resolves WITHOUT
        # the requested ids. Verify that persisted context (and the bound run id)
        # matches the requested scope BEFORE materializing the prompt or reading
        # the draft, so the prompt context and the artifact identity can never
        # diverge (prompt for story B while the artifact is read for story A).
        self._assert_scope_matches(ctx.story_id, run_id)
        # AG3-044 worker-spawn path: resolve + validate the worker context and
        # materialize the prompt. The selector picks ``worker-exploration`` for
        # an EXPLORATION execution_route (no parallel spawn path, FK-43 §43.3).
        session = WorkerSession(
            SpawnReason.INITIAL,
            ctx.story_id,
            run_id,
            context_loader=build_state_backend_context_loader(self._story_dir),
        )
        worker_context = session.resolve_worker_context()
        # Ensure the run prompt pin exists before materializing (FK-44 §44.3);
        # idempotent create-if-absent so a mid-run rebind cannot trip a spurious
        # mismatch.
        self._prompt_runtime.ensure_run_pin(run_id)
        prompt_path = session.compose_worker_prompt(
            worker_context,
            self._prompt_runtime,
            invocation_id=invocation_id,
        )

        # The worker (the harness actor) executes the seven FK-23 §23.3.2 steps
        # against the materialized prompt and emits its raw draft. Read it back
        # across the boundary; absence is an empty result (fail-closed in core).
        payload = self._read_raw_draft(ctx.story_id)
        return ExplorationWorkerResult(payload=payload, prompt_path=prompt_path)

    def _assert_scope_matches(self, story_id: str, run_id: str) -> None:
        """Fail closed unless the persisted context + run binding match the scope.

        ERROR-2: the prompt-materialization StoryContext is loaded out of
        ``story_dir`` ignoring the requested ids; the raw draft is read for the
        request's ``story_id``. If the persisted context belongs to a different
        story (or the bound run differs) the prompt and the artifact would
        diverge. Cross-checks BOTH the persisted context's ``story_id`` and the
        bound ``run_id`` against the request and refuses fail-closed on any
        mismatch / unresolvable input -- no prompt is materialized, no draft read.

        Args:
            story_id: The requested story display id (the draft-read scope).
            run_id: The requested run correlation id.

        Raises:
            CorruptStateError: When no StoryContext / FlowExecution is persisted
                for ``story_dir``, or its ``story_id`` / bound ``run_id`` does not
                match the requested scope.
        """
        persisted_ctx = load_story_context(self._story_dir)
        if persisted_ctx is None:
            raise CorruptStateError(
                "Exploration worker cannot resolve a persisted StoryContext for "
                "the prompt; refusing fail-closed (no prompt, no draft read).",
                detail={"story_id": story_id, "story_dir": str(self._story_dir)},
            )
        if persisted_ctx.story_id != story_id:
            raise CorruptStateError(
                "Exploration worker scope mismatch: the StoryContext persisted "
                "for the prompt belongs to a different story than the requested "
                "draft scope; refusing fail-closed (prompt/artifact divergence).",
                detail={
                    "requested_story_id": story_id,
                    "persisted_story_id": persisted_ctx.story_id,
                    "story_dir": str(self._story_dir),
                },
            )
        flow = load_flow_execution(self._story_dir)
        if flow is None or flow.run_id is None:
            raise CorruptStateError(
                "Exploration worker cannot resolve the bound run id for the "
                "prompt scope; refusing fail-closed (no prompt, no draft read).",
                detail={"story_id": story_id, "story_dir": str(self._story_dir)},
            )
        if flow.run_id != run_id:
            raise CorruptStateError(
                "Exploration worker scope mismatch: the run bound to the prompt "
                "context differs from the requested draft run; refusing "
                "fail-closed (prompt/artifact divergence).",
                detail={
                    "requested_run_id": run_id,
                    "bound_run_id": flow.run_id,
                    "story_dir": str(self._story_dir),
                },
            )

    def _read_raw_draft(self, story_id: str) -> dict[str, object] | None:
        """Read the worker's raw change-frame draft for ``story_id`` (fail-closed).

        Args:
            story_id: The story display id.

        Returns:
            The raw draft payload (a mapping), or ``None`` when no raw draft was
            produced (the worker emitted nothing -> empty result).

        Raises:
            CorruptStateError: When the raw draft is present but not valid JSON /
                not a JSON object (a produced-but-corrupt worker output is a hard
                error, never a silent empty result).
        """
        qa_dir = resolve_qa_story_dir(self._story_dir, story_id=story_id)
        draft_path = qa_dir / CHANGE_FRAME_DRAFT_FILE
        if not draft_path.is_file():
            return None
        try:
            raw = json.loads(draft_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
            raise CorruptStateError(
                "Exploration worker raw draft is present but not valid JSON "
                "(FK-23 §23.3.2); refusing fail-closed.",
                detail={"story_id": story_id, "draft_path": str(draft_path)},
            ) from exc
        if not isinstance(raw, dict):
            raise CorruptStateError(
                "Exploration worker raw draft must be a JSON object "
                "(FK-23 §23.4.1); refusing fail-closed.",
                detail={"story_id": story_id, "draft_path": str(draft_path)},
            )
        return raw


__all__ = ["StateBackendExplorationWorkerRunner"]
