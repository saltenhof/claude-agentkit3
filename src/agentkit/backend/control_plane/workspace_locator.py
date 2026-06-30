"""Backend-resolved story-workspace locator (AG3-123).

Decouples the canonical phase dispatch (``PhaseDispatcher`` /
``ControlPlaneRuntimeService``) from the dev-local ``StoryContext.project_root``.

FK-10 §10.2.3 / I3: AK3 has NO canonical project-local runtime -- the
deterministic core runs in the backend, which may be co-located with OR remote
from the dev process. The worktree / filesystem anchor therefore must NOT be a
dev-supplied path; it is resolved Backend-side from canonical level-1 state
(the ``project_registry``), never from ``ctx.project_root``, ``cwd`` or a
dev-process request field.

The locator is the SINGLE source for the workspace location (FIX THE MODEL):
``story_dir`` / store-root / setup-coordinate anchor all derive from the one
:class:`StoryWorkspace` it returns. Fail-closed: an unresolvable workspace
raises the typed :class:`StoryWorkspaceUnresolvedError` (FK-10 §10.6) -- never a
silent no-op and never a ``cwd`` fallback.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, ValidationError

from agentkit.backend.exceptions import PipelineError
from agentkit.backend.installer.paths import story_dir as resolve_story_dir

if TYPE_CHECKING:
    from agentkit.backend.installer.registration import ProjectRegistration


class StoryWorkspace(BaseModel):
    """The Backend-resolved filesystem anchor for a story run (AG3-123).

    The single typed carrier of the workspace location. ``project_root`` is the
    canonical run store / worktree anchor (resolved from level-1 state) and
    ``story_dir`` is the engine persistence root derived from it; both replace any
    interpretation of a dev-supplied ``StoryContext.project_root``.

    Attributes:
        project_key: Owning project key the workspace was resolved for.
        story_id: The story whose working directory ``story_dir`` addresses.
        run_id: The run the workspace was resolved for (carried for diagnostics
            and future per-run worktree binding; the FS anchor itself is
            project-scoped today).
        project_root: The canonical run store / worktree filesystem anchor.
        story_dir: The story working directory (engine persistence root),
            ``<project_root>/stories/<story_id>``.
    """

    project_key: str
    story_id: str
    run_id: str
    project_root: Path
    story_dir: Path

    model_config = ConfigDict(frozen=True, extra="forbid")


class StoryWorkspaceUnresolvedError(PipelineError):
    """Fail-closed: the Backend cannot resolve a story run's workspace (AG3-123).

    Raised when canonical level-1 state carries no resolvable filesystem anchor
    for ``(project_key, story_id, run_id)`` (e.g. the project is not registered in
    ``project_registry``). FK-10 §10.6 / I3: a missing canonical precondition is a
    fail-closed error, never a silent dispatch or a ``cwd`` fallback. Subclasses
    :class:`~agentkit.backend.exceptions.PipelineError` so the dispatcher's existing
    fail-closed surface normalizes it to a structured rejection.
    """


@runtime_checkable
class StoryWorkspaceLocator(Protocol):
    """Backend port resolving the FS anchor of a story run from level-1 state."""

    def resolve(
        self, project_key: str, story_id: str, run_id: str
    ) -> StoryWorkspace:
        """Resolve the run's :class:`StoryWorkspace` from canonical level-1 state.

        Fail-closed: raise :class:`StoryWorkspaceUnresolvedError` when the anchor
        cannot be resolved -- never return a ``cwd`` / dev-supplied placeholder.
        """
        ...


class ProjectRegistrationLookup(Protocol):
    """Read port for the canonical ``project_registry`` (level-1) lookup."""

    def get(self, project_key: str) -> ProjectRegistration | None:
        """Return the registration for ``project_key``, or ``None`` if absent."""
        ...


@dataclass(frozen=True)
class StateBackendStoryWorkspaceLocator:
    """Resolve the workspace from the canonical ``project_registry`` (AG3-123).

    Reads the authoritative ``project_root`` from the level-1 project registry
    (FK-10 §10.2.0 "kanonischer Zustand lebt nur auf Ebene 1"), keyed by
    ``project_key`` -- never from ``ctx.project_root``, ``cwd`` or request data.
    The story working directory is then the canonical
    ``<project_root>/stories/<story_id>`` layout (FK-01 §1.1a: git/worktree
    mechanic stays filesystem-bound on the Backend side -- the locator moves the
    anchor, it does not abolish it).

    Attributes:
        registration_lookup: The level-1 ``project_registry`` read port.
    """

    registration_lookup: ProjectRegistrationLookup

    def resolve(
        self, project_key: str, story_id: str, run_id: str
    ) -> StoryWorkspace:
        """Resolve the run workspace from the level-1 project registry."""
        # FAIL-CLOSED (AG3-123): the registry read DECODES the row through the
        # ``ProjectRegistration`` model, whose model-floor now REJECTS a relative
        # ``project_root`` (the registration boundary). A legacy/corrupt row with a
        # relative root therefore raises a pydantic ``ValidationError`` from inside
        # the repository -- which would ESCAPE the dispatcher (it only normalizes
        # ``PipelineError``) as a fail-OPEN crash. Convert a row decode/validation
        # failure into the typed :class:`StoryWorkspaceUnresolvedError` (a
        # ``PipelineError``) so the dispatcher normalizes it to a fail-closed
        # rejection. Only the decode/validation class is caught -- unrelated bugs
        # are NOT swallowed.
        try:
            registration = self.registration_lookup.get(project_key)
        except ValidationError as exc:
            raise StoryWorkspaceUnresolvedError(
                "Cannot resolve the story workspace: the project_registry row for "
                f"project_key={project_key!r} failed to decode into a valid "
                "ProjectRegistration (fail-closed; FK-10 §10.6 / I3). A malformed "
                "or legacy row -- e.g. a RELATIVE project_root the model-floor now "
                "forbids -- must surface as a typed rejection here, never escape as "
                "an unhandled ValidationError past the dispatcher.",
                detail={
                    "project_key": project_key,
                    "story_id": story_id,
                    "run_id": run_id,
                    "decode_error": str(exc),
                },
            ) from exc
        if registration is None:
            raise StoryWorkspaceUnresolvedError(
                "Cannot resolve the story workspace: no project_registry entry "
                f"for project_key={project_key!r} (fail-closed; FK-10 §10.6 / "
                "I3). The Backend resolves the filesystem anchor from canonical "
                "level-1 state, not from a dev-supplied project_root.",
                detail={
                    "project_key": project_key,
                    "story_id": story_id,
                    "run_id": run_id,
                },
            )
        project_root = registration.project_root
        # FAIL-CLOSED (AG3-123): the canonical anchor MUST be an ABSOLUTE path that
        # EXISTS on the backend host. A relative registry root would otherwise make
        # ``story_dir`` resolve against the backend process ``cwd`` -- exactly the
        # cwd fallback I3 forbids -- and a stale/absent root would proceed past the
        # locator only to fail later as opaque config/git errors. Both are a
        # missing canonical precondition -> typed :class:`StoryWorkspaceUnresolvedError`
        # (FK-10 §10.6), never a silent dispatch against an unusable anchor.
        if not project_root.is_absolute():
            raise StoryWorkspaceUnresolvedError(
                "Cannot resolve the story workspace: the project_registry root "
                f"{str(project_root)!r} for project_key={project_key!r} is RELATIVE "
                "(fail-closed; FK-10 §10.6 / I3). The canonical filesystem anchor "
                "must be absolute -- a relative root would resolve against the "
                "backend process cwd, the dev-local fallback AG3-123 forbids.",
                detail={
                    "project_key": project_key,
                    "story_id": story_id,
                    "run_id": run_id,
                    "project_root": str(project_root),
                },
            )
        if not project_root.is_dir():
            raise StoryWorkspaceUnresolvedError(
                "Cannot resolve the story workspace: the project_registry root "
                f"{str(project_root)!r} for project_key={project_key!r} does not "
                "exist on the backend host (fail-closed; FK-10 §10.6 / I3). A "
                "stale/absent canonical anchor must fail closed at the locator, "
                "not surface later as an opaque config/git error.",
                detail={
                    "project_key": project_key,
                    "story_id": story_id,
                    "run_id": run_id,
                    "project_root": str(project_root),
                },
            )
        return StoryWorkspace(
            project_key=project_key,
            story_id=story_id,
            run_id=run_id,
            project_root=project_root,
            story_dir=resolve_story_dir(project_root, story_id),
        )


def build_story_workspace_locator() -> StoryWorkspaceLocator:
    """Build the productive Backend workspace locator over level-1 state.

    Wires the canonical ``project_registry`` read surface
    (``StateBackendProjectRegistrationRepository``); on the productive Postgres
    backend (FK-10 §10.2.0) the registry is global, so the resolution needs no
    dev-local path -- the remote-capable core never assumes a co-located
    project_root.
    """
    from agentkit.backend.state_backend.store.project_registration_repository import (
        StateBackendProjectRegistrationRepository,
    )

    return StateBackendStoryWorkspaceLocator(
        registration_lookup=StateBackendProjectRegistrationRepository(),
    )


__all__ = [
    "ProjectRegistrationLookup",
    "StateBackendStoryWorkspaceLocator",
    "StoryWorkspace",
    "StoryWorkspaceLocator",
    "StoryWorkspaceUnresolvedError",
    "build_story_workspace_locator",
]
