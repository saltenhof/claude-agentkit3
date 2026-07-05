"""Preflight checks for the setup phase (FK-22 §22.3 / §22.3.1).

The Setup-Preflight gate validates the legal startability of a story.  All
ten checks (FK-22 §22.3.1) run **always** — even after an earlier failure —
so a human sees every blocker at once (FK-22 §22.3.2, fail-closed).  Each
failing check carries a human-readable ``cleanup_hint`` (FK-22 §22.3.4).

Checks are performed against the AK3 StoryService (story_context_manager BC)
and canonical runtime/state-backend records, not GitHub — GitHub was the v2
approach, replaced in FK-22 §22.4.1.

Each check lives in its own submodule under ``preflight_checks/`` and exposes
``def check(ctx: PreflightContext) -> PreflightCheckResult`` (AG3-034 AK2).
This module owns the typed result model, the ``PreflightContext`` input and
the deterministic aggregation (``run_preflight``).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from agentkit.backend.control_plane.edge_commands import (
        PreflightOwnershipContext,
        PreflightProbeEvidence,
    )
    from agentkit.backend.execution_planning.repository import StoryDependencyRepository
    from agentkit.backend.state_backend.store.mode_lock_repository import ModeLockRecord
    from agentkit.backend.story_context_manager.service import StoryService
    from agentkit.backend.story_context_manager.story_model import Story

logger = logging.getLogger(__name__)


class PreflightCheckId(StrEnum):
    """Canonical IDs of the ten preflight checks (FK-22 §22.3.1)."""

    STORY_EXISTS = "story_exists"
    STORY_ATTRIBUTES_CONSISTENT = "story_attributes_consistent"
    STATUS_APPROVED = "status_approved"
    DEPENDENCIES_DONE = "dependencies_done"
    NO_EXECUTION_ARTIFACTS = "no_execution_artifacts"
    NO_ACTIVE_RUNTIME_RESIDUE = "no_active_runtime_residue"
    NO_STORY_BRANCH = "no_story_branch"
    NO_STALE_WORKTREE = "no_stale_worktree"
    NO_SCOPE_OVERLAP = "no_scope_overlap"
    NO_COMPETING_STORY_MODE_ACTIVE = "no_competing_story_mode_active"


class PreflightStatus(StrEnum):
    """Outcome of a single preflight check (FK-22 §22.3)."""

    PASS = "PASS"
    FAIL = "FAIL"


class PreflightCheckResult(BaseModel):
    """Result of one preflight check (FK-22 §22.3.1 / story.md §2.1.1).

    Attributes:
        check_id: The canonical check identifier.
        status: ``PASS`` or ``FAIL``.
        detail: Human-readable description of the outcome.  On a fail-closed
            exception this is ``"exception: <type>: <msg>"`` (AK4).
        cleanup_hint: Human-readable remediation hint; present (non-``None``)
            for every ``FAIL`` (FK-22 §22.3.4, AK3).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    check_id: PreflightCheckId
    status: PreflightStatus
    detail: str | None = None
    cleanup_hint: str | None = None


class PreflightResult(BaseModel):
    """Aggregated result of all ten preflight checks (story.md §2.1.1).

    Attributes:
        overall: ``PASS`` only when every individual check passed.
        checks: All check results, in canonical execution order. Ten for a
            standard story; the four FK-24 §24.3.4 minimum checks for a ``fast``
            story (FIX-5 mode-aware applicability).
        failed_check_ids: IDs of the checks that failed (possibly empty).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    overall: PreflightStatus
    checks: tuple[PreflightCheckResult, ...]
    failed_check_ids: tuple[PreflightCheckId, ...]

    @property
    def passed(self) -> bool:
        """Backwards-compatible boolean alias for ``overall == PASS``."""
        return self.overall is PreflightStatus.PASS


@dataclass(frozen=True)
class PreflightContext:
    """Input bundle for the ten preflight checks (story.md §2.1.1, AK2).

    Side-effecting reads (state backend, git, mode-lock) are injected as
    callables/ports with real defaults so that each ``check(ctx)`` stays a
    pure function of its context and tests can use ``tmp_path`` fixtures
    instead of mocks (story.md §8).

    Attributes:
        story_display_id: Story display ID to validate (e.g. ``"AK3-042"``).
        project_key: Owning project key (mode-lock / scope scoping).
        project_root: Project root for filesystem residue checks.
        service: Authoritative StoryService.
        story: The resolved Story, or ``None`` if it could not be fetched.
            Populated once by :func:`run_preflight` (Check 1).
        dependency_repository: Optional dependency edge repository (Check 4).
        execution_artifacts_present: Probe for Check 5 — ``True`` when an
            unfinished prior run left execution artifacts.
        active_runtime_residue: Probe for Check 6 — ``True`` when an active or
            inconsistent prior-run runtime state exists.  FAIL-CLOSED: the
            orchestrator injects a run-id-aware state-backend probe (Finding B);
            when ``None`` the standalone default reads the canonical phase-state
            for the story (any incomplete prior phase-state == residue).
        edge_probe_reports: Per-repo edge ``preflight_probe`` evidence keyed by
            ``repo_id`` (Checks 7/8, AG3-145 Teilschritt C, FK-22 §22.3.1).
            ``None`` means the edge was NOT consulted for this dispatch (a
            non-worktree story) -> Checks 7/8 PASS trivially. A dict means the
            worktree edge was consulted: for every participating repo a
            missing/``None`` entry FAILs the check fail-closed
            (``edge_probe_missing``), never an optimistic PASS.
        edge_ownership: The backend ownership decision context for Checks 7/8
            (active ``run_ownership_records`` row + ``takeover_base_sha``); used
            to distinguish ``stale foreign`` (FAIL) from ``legitimate takeover``
            (PASS). Defaults to the no-active-ownership, no-takeover context.
        participating_repos: The repos Checks 7/8 iterate when
            ``edge_probe_reports`` is set.
        mode_lock: A pre-resolved project mode-lock record (Check 10, decoupled
            fast/standard axis), or ``None`` when idle / unset.  Used only when
            ``mode_lock_reader`` is ``None`` (e.g. tests that seed a record
            directly).
        mode_lock_reader: FAIL-CLOSED read path for Check 10 (E-E fix) —
            ``reader(project_key) -> ModeLockRecord | None``.  When provided it
            is the authoritative source: Check 10 calls it and a read error
            propagates so :func:`_run_one` turns it into a fail-closed ``FAIL``
            (a read failure must NEVER be masked as idle).  When ``None`` the
            check falls back to the pre-resolved ``mode_lock`` field.
    """

    story_display_id: str
    project_key: str
    project_root: Path
    service: StoryService
    story: Story | None = None
    dependency_repository: StoryDependencyRepository | None = None
    execution_artifacts_present: Callable[[Path, str], bool] | None = None
    active_runtime_residue: Callable[[Path, str], bool] | None = None
    edge_probe_reports: dict[str, PreflightProbeEvidence | None] | None = None
    edge_ownership: PreflightOwnershipContext | None = None
    participating_repos: tuple[str, ...] = ()
    mode_lock: ModeLockRecord | None = None
    mode_lock_reader: Callable[[str], ModeLockRecord | None] | None = None


# ---------------------------------------------------------------------------
# Aggregation (FK-22 §22.3.2: all ten checks run, fail-closed)
# ---------------------------------------------------------------------------


def run_preflight(
    story_display_id: str,
    service: StoryService,
    *,
    project_key: str = "",
    project_root: Path | None = None,
    dependency_repository: StoryDependencyRepository | None = None,
    mode_lock: ModeLockRecord | None = None,
    mode_lock_reader: Callable[[str], ModeLockRecord | None] | None = None,
    active_runtime_residue: Callable[[Path, str], bool] | None = None,
    edge_probe_reports: dict[str, PreflightProbeEvidence | None] | None = None,
    edge_ownership: PreflightOwnershipContext | None = None,
    participating_repos: tuple[str, ...] = (),
    context: PreflightContext | None = None,
) -> PreflightResult:
    """Run the applicable preflight checks (FK-22 §22.3.1), fail-closed.

    A standard story runs all ten checks; a ``fast`` story runs ONLY the four
    FK-24 §24.3.4 minimum checks (FIX-5, mode read from the AUTHORITATIVE story
    record). Every applicable check runs regardless of earlier failures (FK-22
    §22.3.2). An exception raised inside any check is converted to a ``FAIL`` with
    ``detail="exception: <type>: <msg>"`` (AK4) — no applicable check is silently
    skipped.

    Args:
        story_display_id: Story display ID to validate.
        service: Authoritative StoryService.
        project_key: Owning project key (mode-lock / scope scoping).
        project_root: Project root for filesystem residue checks.  Defaults
            to the current working directory when ``None``.
        dependency_repository: Optional dependency edge repository (Check 4).
        mode_lock: Pre-resolved project mode-lock record (Check 10), or
            ``None`` (used only when ``mode_lock_reader`` is ``None``).
        mode_lock_reader: FAIL-CLOSED Check-10 read path (E-E fix); a read
            error propagates to a fail-closed ``FAIL`` instead of being masked
            as idle.
        active_runtime_residue: Injected run-aware residue probe for Check 6
            (Finding B); the orchestrator wires a state-backend probe (a
            protected ``governance`` check may not read the loader itself).
            When ``None`` Check 6's default fails closed.
        context: Pre-built :class:`PreflightContext`.  When provided, the
            other keyword arguments are ignored — used by callers (and tests)
            that need to inject probe callables.

    Returns:
        A :class:`PreflightResult` with all ten outcomes.
    """
    from pathlib import Path as _Path

    if context is None:
        story = service.get_story(story_display_id)
        context = PreflightContext(
            story_display_id=story_display_id,
            project_key=project_key,
            project_root=project_root or _Path.cwd(),
            service=service,
            story=story,
            dependency_repository=dependency_repository,
            mode_lock=mode_lock,
            mode_lock_reader=mode_lock_reader,
            active_runtime_residue=active_runtime_residue,
            edge_probe_reports=edge_probe_reports,
            edge_ownership=edge_ownership,
            participating_repos=participating_repos,
        )
    elif context.story is None:
        context = _with_resolved_story(context)

    check_order = _check_order_for(context)
    results = tuple(_run_one(check_fn, context) for check_fn in check_order)
    failed = tuple(r.check_id for r in results if r.status is PreflightStatus.FAIL)
    overall = PreflightStatus.FAIL if failed else PreflightStatus.PASS
    return PreflightResult(
        overall=overall,
        checks=results,
        failed_check_ids=failed,
    )


def _check_order_for(
    context: PreflightContext,
) -> tuple[Callable[[PreflightContext], PreflightCheckResult], ...]:
    """Select the applicable preflight checks for the story's mode (FIX-5).

    FK-24 §24.3.4 Mode-Profil (Setup -> Preflight-Gates): a ``fast`` story runs
    ONLY the four minimum checks (``story_exists``, no active run, no stale
    worktree, mode-conflict §24.3.3); status/deps/scope-overlap are OUT for fast.
    Every other mode runs the full ten (FK-22 §22.3.1). The mode is read from the
    AUTHORITATIVE resolved ``Story`` record (FIX-1) -- NOT labels; when the story
    could not be resolved (Check 1 will fail) the full set runs so ``story_exists``
    reports the missing story.

    Args:
        context: The preflight context (carries the resolved ``story``).

    Returns:
        The ordered tuple of check callables to run.
    """
    from agentkit.backend.story_context_manager.story_model import WireStoryMode

    story = context.story
    if story is not None and story.mode is WireStoryMode.FAST:
        return _FAST_CHECK_ORDER
    return _CHECK_ORDER


def _with_resolved_story(context: PreflightContext) -> PreflightContext:
    """Return a context with ``story`` resolved from the service (Check 1)."""
    from dataclasses import replace
    from typing import cast

    story = context.service.get_story(context.story_display_id)
    # ``dataclasses.replace`` is modelled by SonarQube as returning the generic
    # ``DataclassInstance`` protocol (S5886/S5890); the cast documents the
    # concrete return type for Sonar. mypy already infers ``PreflightContext``
    # via the ``replace`` TypeVar, so to mypy the cast is redundant -> the
    # explained ignore reconciles the two analyzers (no behaviour change).
    return cast("PreflightContext", replace(context, story=story))  # type: ignore[redundant-cast]


def _run_one(
    check_fn: Callable[[PreflightContext], PreflightCheckResult],
    context: PreflightContext,
) -> PreflightCheckResult:
    """Run a single check fail-closed; map exceptions to ``FAIL`` (AK4)."""
    try:
        return check_fn(context)
    except Exception as exc:  # noqa: BLE001 -- fail-closed: never skip a check
        check_id = _CHECK_IDS[check_fn]
        logger.warning(
            "Preflight check %s raised %s: %s",
            check_id.value,
            type(exc).__name__,
            exc,
        )
        return PreflightCheckResult(
            check_id=check_id,
            status=PreflightStatus.FAIL,
            detail=f"exception: {type(exc).__name__}: {exc}",
            cleanup_hint=f"Preflight check {check_id.value!r} raised an unexpected "
            "error; inspect the preflight artifact and resolve the underlying "
            "cause before restarting the story.",
        )


def _build_check_order() -> tuple[
    tuple[Callable[[PreflightContext], PreflightCheckResult], PreflightCheckId],
    ...,
]:
    """Return the (check_fn, check_id) pairs in canonical order (FK-22 §22.3.1)."""
    from agentkit.backend.governance.setup_preflight_gate.preflight_checks import (
        dependencies_done,
        no_active_runtime_residue,
        no_competing_story_mode_active,
        no_execution_artifacts,
        no_scope_overlap,
        no_stale_worktree,
        no_story_branch,
        status_approved,
        story_attributes_consistent,
        story_exists,
    )

    return (
        (story_exists.check, PreflightCheckId.STORY_EXISTS),
        (story_attributes_consistent.check, PreflightCheckId.STORY_ATTRIBUTES_CONSISTENT),
        (status_approved.check, PreflightCheckId.STATUS_APPROVED),
        (dependencies_done.check, PreflightCheckId.DEPENDENCIES_DONE),
        (no_execution_artifacts.check, PreflightCheckId.NO_EXECUTION_ARTIFACTS),
        (no_active_runtime_residue.check, PreflightCheckId.NO_ACTIVE_RUNTIME_RESIDUE),
        (no_story_branch.check, PreflightCheckId.NO_STORY_BRANCH),
        (no_stale_worktree.check, PreflightCheckId.NO_STALE_WORKTREE),
        (no_scope_overlap.check, PreflightCheckId.NO_SCOPE_OVERLAP),
        (
            no_competing_story_mode_active.check,
            PreflightCheckId.NO_COMPETING_STORY_MODE_ACTIVE,
        ),
    )


_CHECK_ORDER: tuple[
    Callable[[PreflightContext], PreflightCheckResult], ...
] = tuple(fn for fn, _ in _build_check_order())
_CHECK_IDS: dict[
    Callable[[PreflightContext], PreflightCheckResult], PreflightCheckId
] = dict(_build_check_order())

#: FK-24 §24.3.4 Mode-Profil: the four MINIMUM checks a ``fast`` story runs
#: (story_exists, no active run, no stale worktree, mode-conflict §24.3.3).
#: Status/dependencies/scope-overlap are OUT for fast (FIX-5).
_FAST_CHECK_IDS: frozenset[PreflightCheckId] = frozenset(
    {
        PreflightCheckId.STORY_EXISTS,
        PreflightCheckId.NO_ACTIVE_RUNTIME_RESIDUE,
        PreflightCheckId.NO_STALE_WORKTREE,
        PreflightCheckId.NO_COMPETING_STORY_MODE_ACTIVE,
    }
)
_FAST_CHECK_ORDER: tuple[
    Callable[[PreflightContext], PreflightCheckResult], ...
] = tuple(fn for fn, cid in _build_check_order() if cid in _FAST_CHECK_IDS)


__all__ = [
    "PreflightCheckId",
    "PreflightCheckResult",
    "PreflightContext",
    "PreflightResult",
    "PreflightStatus",
    "run_preflight",
]
