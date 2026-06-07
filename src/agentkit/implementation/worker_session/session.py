"""WorkerSession — worker spawn binding + context resolution (FK-26 §26.2).

A :class:`WorkerSession` binds one worker spawn to its ``(spawn_reason,
story_id, run_id)`` and owns the FK-26 §26.2 call chain:

``resolve_worker_context()`` -> ``validate_worker_context()`` ->
``compose_worker_prompt()`` (Decision 2026-04-08 Element 9).

``resolve_worker_context`` reads the authoritative :class:`StoryContext` via an
injected loader port (so the bloodgroup-A session does no direct
``state_backend`` import and stays unit-testable) and builds the typed
:class:`WorkerContext` item-set keyed by :class:`WorkerContextItemKey`
(FK-26 §26.2.1). ``compose_worker_prompt`` materialises the worker prompt via
``PromptRuntime.materialize_prompt`` with the template that matches the
session's :class:`SpawnReason` (FK-44; the selection lives in the composer).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from agentkit.exceptions import CorruptStateError

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.core_types import SpawnReason
    from agentkit.prompt_runtime.runtime import PromptRuntime
    from agentkit.story_context_manager.models import StoryContext


class WorkerContextItemKey(StrEnum):
    """Keys of the worker spawn-context item-set (FK-26 §26.2.1).

    The FK-26 §26.2.2 worker-context table mapped to typed keys (Decision
    2026-04-08 Element 9: ``WorkerContextItemKey`` StrEnum).

    Attributes:
        STORY_BRIEF: Story description / brief.
        ACCEPTANCE_CRITERIA: Acceptance-criteria reference.
        STORY_TYPE: Story type (drives review cadence).
        STORY_SIZE: Story size.
        WORKTREE_MAP: Repo-name -> worktree-path map (multi-repo, FK-22 §22.6.4).
        CONCEPT_REFS: Concept / design-artifact references.
        FEEDBACK: Remediation feedback list (remediation spawns only).
    """

    STORY_BRIEF = "story_brief"
    ACCEPTANCE_CRITERIA = "acceptance_criteria"
    STORY_TYPE = "story_type"
    STORY_SIZE = "story_size"
    WORKTREE_MAP = "worktree_map"
    CONCEPT_REFS = "concept_refs"
    FEEDBACK = "feedback"


@dataclass(frozen=True)
class WorkerContext:
    """Resolved, validated worker spawn context (FK-26 §26.2).

    Attributes:
        story_id: Story display id.
        run_id: Run correlation id.
        spawn_reason: Why this worker is spawned (drives the prompt variant).
        items: The typed context item-set keyed by :class:`WorkerContextItemKey`.
    """

    story_id: str
    run_id: str
    spawn_reason: SpawnReason
    items: dict[WorkerContextItemKey, str]


@runtime_checkable
class StoryContextLoaderPort(Protocol):
    """Read-only port resolving the authoritative ``StoryContext`` for a run.

    Keeps the bloodgroup-A :class:`WorkerSession` free of a direct
    ``state_backend`` import (AG3-035 BC-topology); the productive adapter is
    wired in the composition root.
    """

    def load(self, story_id: str, run_id: str) -> StoryContext | None:
        """Load the persisted ``StoryContext`` for ``(story_id, run_id)``.

        Args:
            story_id: Story display id.
            run_id: Run correlation id.

        Returns:
            The ``StoryContext`` or ``None`` when none is persisted.
        """
        ...


class WorkerSession:
    """One worker spawn binding + its FK-26 §26.2 context-resolution chain."""

    def __init__(
        self,
        spawn_reason: SpawnReason,
        story_id: str,
        run_id: str,
        *,
        context_loader: StoryContextLoaderPort,
    ) -> None:
        """Bind a worker spawn to its identity and its context loader.

        Args:
            spawn_reason: Why this worker is spawned (FK-26 §26.2.3 variant).
            story_id: Story display id.
            run_id: Run correlation id.
            context_loader: Port resolving the authoritative ``StoryContext``.
        """
        self._spawn_reason = spawn_reason
        self._story_id = story_id
        self._run_id = run_id
        self._context_loader = context_loader
        self._story_context: StoryContext | None = None

    @property
    def story_id(self) -> str:
        """Return the bound story display id."""
        return self._story_id

    @property
    def run_id(self) -> str:
        """Return the bound run correlation id."""
        return self._run_id

    @property
    def spawn_reason(self) -> SpawnReason:
        """Return the bound spawn reason."""
        return self._spawn_reason

    @property
    def project_key(self) -> str:
        """Return the resolved project key (loads the StoryContext if needed)."""
        return self._resolve_story_context().project_key

    def resolve_worker_context(self) -> WorkerContext:
        """Resolve + validate the worker spawn context (FK-26 §26.2.1).

        Reads the authoritative ``StoryContext``, builds the typed item-set and
        validates it (the remediation variant requires the feedback item). Fails
        closed when the context cannot be resolved — a worker is never spawned
        against an unknown story (CLAUDE.md FAIL-CLOSED).

        Returns:
            A validated :class:`WorkerContext`.

        Raises:
            CorruptStateError: When no ``StoryContext`` is persisted for the run.
            ValueError: When the resolved item-set is invalid for the spawn
                reason (e.g. a remediation spawn without feedback).
        """
        ctx = self._resolve_story_context()
        items = self._build_items(ctx)
        self._validate_worker_context(items)
        return WorkerContext(
            story_id=self._story_id,
            run_id=self._run_id,
            spawn_reason=self._spawn_reason,
            items=items,
        )

    def compose_worker_prompt(
        self,
        context: WorkerContext,
        prompt_runtime: PromptRuntime,
        *,
        invocation_id: str,
        attempt: int = 1,
    ) -> str:
        """Materialise the worker prompt for ``context`` (FK-26 §26.2 / FK-44).

        Delegates template selection to the composer via ``ComposeConfig``: the
        template matches ``context.spawn_reason`` (e.g. ``worker-remediation``
        for a remediation spawn). The run-scoped prompt is materialised + audited
        through :meth:`PromptRuntime.materialize_prompt`.

        Args:
            context: The resolved worker context.
            prompt_runtime: The run-bound prompt runtime (FK-44).
            invocation_id: Spawn/invocation id for the audit record.
            attempt: Audit attempt counter (>= 1).

        Returns:
            The POSIX path of the materialised prompt instance (project-relative).
        """
        from agentkit.prompt_runtime.composer import ComposeConfig
        from agentkit.prompt_runtime.selectors import select_template_name

        story_ctx = self._resolve_story_context()
        config = ComposeConfig(
            story_type=story_ctx.story_type,
            execution_route=story_ctx.execution_route,
            spawn_reason=context.spawn_reason,
        )
        template_name = select_template_name(
            story_ctx.story_type,
            story_ctx.execution_route,
            spawn_reason=context.spawn_reason,
        )
        instance = prompt_runtime.materialize_prompt(
            story_ctx,
            template_name,
            config,
            run_id=self._run_id,
            invocation_id=invocation_id,
            attempt=attempt,
        )
        return instance.prompt_path.as_posix()

    def _resolve_story_context(self) -> StoryContext:
        """Load + cache the authoritative ``StoryContext`` (fail-closed)."""
        if self._story_context is not None:
            return self._story_context
        ctx = self._context_loader.load(self._story_id, self._run_id)
        if ctx is None:
            raise CorruptStateError(
                "WorkerSession cannot resolve a StoryContext for the spawn; "
                "a worker is never spawned against an unknown story "
                "(FK-26 §26.2).",
                detail={"story_id": self._story_id, "run_id": self._run_id},
            )
        self._story_context = ctx
        return ctx

    def _build_items(self, ctx: StoryContext) -> dict[WorkerContextItemKey, str]:
        """Build the typed worker-context item-set from the story context."""
        items: dict[WorkerContextItemKey, str] = {
            WorkerContextItemKey.STORY_BRIEF: ctx.title or ctx.story_id,
            WorkerContextItemKey.STORY_TYPE: ctx.story_type.value,
            WorkerContextItemKey.STORY_SIZE: ctx.story_size.value,
            WorkerContextItemKey.ACCEPTANCE_CRITERIA: (
                f"_temp/qa/{ctx.story_id}/context.json"
            ),
        }
        if ctx.worktree_map:
            items[WorkerContextItemKey.WORKTREE_MAP] = ", ".join(
                f"{name}={path}" for name, path in sorted(ctx.worktree_map.items())
            )
        from agentkit.core_types import SpawnReason

        if self._spawn_reason is SpawnReason.REMEDIATION:
            items[WorkerContextItemKey.FEEDBACK] = (
                f"_temp/qa/{ctx.story_id}/feedback.json"
            )
        return items

    def _validate_worker_context(
        self,
        items: dict[WorkerContextItemKey, str],
    ) -> None:
        """Validate the item-set for the spawn reason (FK-26 §26.2, fail-closed).

        Args:
            items: The resolved item-set.

        Raises:
            ValueError: When a required item is missing for the spawn reason —
                a remediation spawn without its feedback list, or a spawn
                without the story brief.
        """
        from agentkit.core_types import SpawnReason

        if WorkerContextItemKey.STORY_BRIEF not in items:
            raise ValueError(
                "worker context missing story_brief (FK-26 §26.2.1)",
            )
        if (
            self._spawn_reason is SpawnReason.REMEDIATION
            and WorkerContextItemKey.FEEDBACK not in items
        ):
            raise ValueError(
                "remediation worker context missing feedback (FK-26 §26.2.3); "
                "a remediation spawn must carry the defect list",
            )


def build_state_backend_context_loader(story_dir: Path) -> StoryContextLoaderPort:
    """Build the productive ``StoryContextLoaderPort`` backed by the state backend.

    Composition-root helper: wires the bloodgroup-A :class:`WorkerSession` to the
    persisted ``StoryContext`` for ``story_dir`` without leaking the
    ``state_backend`` import into the session itself.

    Args:
        story_dir: Story working directory.

    Returns:
        A loader port resolving the persisted ``StoryContext``.
    """
    from agentkit.state_backend.store import load_story_context

    class _StateBackendLoader:
        def load(self, story_id: str, run_id: str) -> StoryContext | None:
            del story_id, run_id  # scope is the story_dir for the active run
            return load_story_context(story_dir)

    return _StateBackendLoader()


__all__ = [
    "StoryContextLoaderPort",
    "WorkerContext",
    "WorkerContextItemKey",
    "WorkerSession",
    "build_state_backend_context_loader",
]
