"""Setup phase handler -- first phase in every pipeline run.

Builds the StoryContext from the authoritative AK3 Story-Service record
(AK3 owns the story; GitHub is only the code backend, FK-12 §12.1.1),
runs preflight checks, and optionally creates a git worktree.  On
successful completion, calls ``StoryService.begin_progress`` (FK-22 §22.4.3).

AG3-031 Pass-4 Fix E9 (2026-05-24): direct import of ``save_story_context``
from ``agentkit.backend.state_backend.store`` replaced by ``SetupContextRepository``
protocol injection via ``SetupPhaseHandler.__init__``.

AG3-031 Pass-5 Fix E9 (2026-05-24): ``_default_context_repository()`` factory
removed.  The composition root
(``agentkit.backend.bootstrap.composition_root.build_setup_preflight_gate``) is the
canonical wiring point.  All callers must inject a ``SetupContextRepository``
explicitly — no internal fallback factory remains.

AG3-031 Pass-6 Fix E9 (2026-05-24): lazy ``StateBackendStoryDependencyRepository``
fallback removed from ``_run_preflight_check``.  ``dependency_repository``
may be ``None``; ``run_preflight`` handles ``None`` natively (no-dep check).
All state-backend imports go through DI or composition root.
"""

from __future__ import annotations

import contextlib
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from agentkit.backend.config.loader import load_project_config
from agentkit.backend.core_types import PauseReason
from agentkit.backend.exceptions import ConfigError
from agentkit.backend.governance.setup_preflight_gate.context_builder import (
    build_story_context,
)
from agentkit.backend.governance.setup_preflight_gate.preflight import run_preflight
from agentkit.backend.installer.paths import story_dir
from agentkit.backend.pipeline_engine.lifecycle import HandlerResult
from agentkit.backend.pipeline_engine.phase_executor import (
    AreBundleSignal,
    AreBundleStatus,
    PhaseState,
    PhaseStatus,
    SetupPayload,
    evolve_phase_state,
)
from agentkit.backend.state_backend.paths import CONTEXT_EXPORT_FILE
from agentkit.backend.story_context_manager.types import StoryType, get_profile

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from agentkit.backend.control_plane.edge_commands import (
        PreflightOwnershipContext,
        PreflightProbeEvidence,
    )
    from agentkit.backend.execution_planning.repository import StoryDependencyRepository
    from agentkit.backend.governance.repository import SetupContextRepository
    from agentkit.backend.governance.setup_preflight_gate.edge_provisioning import (
        EdgeProvisioningCoordinator,
    )
    from agentkit.backend.governance.setup_preflight_gate.green_main import MainGreenPort
    from agentkit.backend.governance.setup_preflight_gate.preflight import PreflightCheckResult
    from agentkit.backend.pipeline_engine.phase_envelope.envelope import PhaseEnvelope
    from agentkit.backend.requirements_coverage.contract import ContextLoadResult
    from agentkit.backend.state_backend.store.mode_lock_repository import (
        ModeLockRecord,
        ModeLockRepository,
    )
    from agentkit.backend.story_context_manager.models import StoryContext
    from agentkit.backend.story_context_manager.service import StoryService

logger = logging.getLogger(__name__)

#: The typed edge-provisioning plan resolved once per ``on_enter`` (idempotent
#: on every re-entry): whether the story provisions worktrees, its participating
#: repos, and the story branch. ``uses_worktree`` is derived from the
#: AUTHORITATIVE StoryService record (the SAME source ``build_story_context``
#: reads), NEVER from the sparse/possibly-stale incoming ``StoryContext`` -- a
#: stale incoming ``story_type`` must not gate the edge probe/provision. It is
#: ``False`` for a config with ``create_worktree=False`` or an authoritatively
#: non-worktree profile -- then no edge command is commissioned and Checks 7/8
#: PASS (no edge consultation).
_WorktreePlan = tuple[bool, tuple[str, ...], str]


def _default_fence_scope_binder(
    *,
    project_key: str,
    story_id: str,
    run_id: str,
) -> contextlib.AbstractContextManager[None]:
    """No-op fence-scope binder (unwired default -- fail-closed by omission).

    AG3-144 (Codex round-3, architecture-conformance fix): ``setup_preflight_gate.phase``
    must have ZERO ``state_backend.store`` imports -- module-level OR lazy
    (``tests/unit/governance/test_architecture_conformance_imports.py``). The
    REAL binder -- which resolves the active ownership-lease snapshot
    (``resolve_ownership_fence_snapshot``) and binds it
    (``bind_ownership_fence_scope``) -- lives in the composition root (the
    sanctioned ``state_backend.store`` import boundary,
    ``agentkit.backend.bootstrap.composition_root``) and is injected into
    :class:`SetupPhaseHandler` via ``fence_scope_binder`` (DI, not a lazy
    fallback import).

    This default is used only by callers that construct
    :class:`SetupPhaseHandler` WITHOUT wiring a real binder (legacy/unit-test
    constructions on the narrow SQLite path, where the Postgres fenced write
    boundary is never reached). On Postgres, an unwired binder yields an
    EMPTY scope here -- the ARE-bundle ``ArtifactEnvelope`` write then fails
    CLOSED with ``CorruptStateError`` (no bound ``OwnershipFenceScope``),
    never fail-open.
    """
    del project_key, story_id, run_id
    return contextlib.nullcontext()


class AreBundleLoaderPort(Protocol):
    """Setup collaborator for loading the ARE bundle."""

    def load_context(
        self,
        story_id: str,
        run_id: str,
    ) -> ContextLoadResult:
        """Load and persist the ARE bundle for the setup run."""


@dataclass
class SetupConfig:
    """Configuration for the setup phase handler.

    Attributes:
        project_root: Root directory of the target project.
        story_id: Optional explicit story ID.  When ``None``, the story ID is
            taken from the initial ``StoryContext`` passed to ``on_enter``.
        create_worktree: Whether to create a git worktree.
            Automatically determined from story type when ``True``.
        story_service: Optional StoryService instance.  When provided,
            ``begin_progress`` is called on successful completion
            (FK-22 §22.4.3). When ``None``, the transition is skipped
            (legacy / standalone mode).
    """

    project_root: Path
    story_id: str | None = None
    create_worktree: bool = True
    story_service: StoryService | None = None


class SetupPhaseHandler:
    """Phase handler for the Setup phase.

    Implements the :class:`~agentkit.backend.pipeline_engine.lifecycle.PhaseHandler`
    protocol.  Builds the story context from the AK3 Story-Service record,
    runs preflight checks, persists the context, and optionally prepares a
    git worktree path.  On successful completion, transitions the story
    to ``In Progress`` via ``StoryService.begin_progress`` when a
    ``story_service`` is provided in ``SetupConfig`` (FK-22 §22.4.3).

    Args:
        config: Setup phase configuration.
        context_repository: Repository for persisting ``StoryContext``.
            Must be provided explicitly.  Use
            ``agentkit.backend.bootstrap.composition_root.build_setup_preflight_gate()``
            to obtain the canonical adapter (AG3-031 Pass-5 Fix E9).
        dependency_repository: Repository for story dependencies used in
            preflight.  When ``None``, the dependency check is skipped
            inside ``run_preflight`` (no lazy import).  Provide a test
            double or real repository to enable the dependency check
            (AG3-031 Pass-6 Fix E9).
        fence_scope_binder: AG3-144 (Codex round-3) DI seam for the
            ownership-lease fence (FK-91 §91.1a Rule 15). Called as
            ``fence_scope_binder(project_key=..., story_id=..., run_id=...)``
            around the ARE-bundle load; must return a context manager. This
            module has ZERO ``state_backend.store`` imports (architecture
            conformance) -- the REAL binder (resolves
            ``resolve_ownership_fence_snapshot`` and binds it via
            ``bind_ownership_fence_scope``) is built and injected by
            ``agentkit.backend.bootstrap.composition_root``. Defaults to a
            no-op binder (``contextlib.nullcontext``) so existing/sqlite unit
            tests that construct this handler without wiring a binder keep
            working; on Postgres an unwired binder yields no bound scope, so
            the fenced write fails CLOSED (``CorruptStateError``), never
            fail-open.
    """

    def __init__(
        self,
        config: SetupConfig,
        context_repository: SetupContextRepository,
        dependency_repository: StoryDependencyRepository | None = None,
        *,
        mode_lock_repository: ModeLockRepository | None = None,
        green_main_port: MainGreenPort | None = None,
        are_bundle_loader: AreBundleLoaderPort | None = None,
        residue_probe: Callable[[Path, str], bool] | None = None,
        fence_scope_binder: Callable[
            ..., contextlib.AbstractContextManager[None]
        ] = _default_fence_scope_binder,
        edge_provisioning_coordinator: EdgeProvisioningCoordinator | None = None,
    ) -> None:
        self._config = config
        self._context_repo: SetupContextRepository = context_repository
        self._dependency_repo: StoryDependencyRepository | None = dependency_repository
        self._mode_lock_repo = mode_lock_repository
        self._green_main_port = green_main_port
        self._are_bundle_loader = are_bundle_loader
        self._residue_probe = residue_probe
        self._fence_scope_binder = fence_scope_binder
        # AG3-145 Teilschritt C: the edge-provisioning coordinator commissions
        # ``preflight_probe`` / ``provision_worktree`` commands and reads the
        # reported results (FK-10 §10.2.4a). ``None`` on the non-worktree path
        # (create_worktree=False) where no edge command is ever commissioned; a
        # worktree story WITHOUT a wired coordinator fails closed in the staged
        # flow (no silent backend provisioning fallback -- that path is removed).
        self._edge_provisioning = edge_provisioning_coordinator

    def on_enter(self, ctx: StoryContext, envelope: PhaseEnvelope) -> HandlerResult:
        """Execute the setup phase.

        Steps:
            1. Run preflight checks against StoryService -- if any fail,
               return ``FAILED``.
            2. Build ``StoryContext`` from the AK3 Story-Service record.
            3. Save ``context.json`` to the story directory.
            4. Create a git worktree via ``git worktree add`` if the story
               type requires one; on failure return ``FAILED``.
            5. If a ``story_service`` is configured, call
               ``begin_progress`` on the story to transition it to
               ``In Progress`` (FK-22 §22.4.3).
            6. Return ``COMPLETED`` with a list of produced artifacts.

        Note:
            The *ctx* parameter is the **initial** context (may be
            sparse).  This handler enriches it from the AK3 Story-Service
            record and persists the enriched version.

        Args:
            ctx: The initial (possibly sparse) story context.
            envelope: The current phase envelope (state unused by setup).

        Returns:
            A ``HandlerResult`` describing the outcome.
        """
        cfg = self._config
        story_service = _resolve_story_service(cfg)
        run_id = envelope.state.run_id
        story_display_id = cfg.story_id or ctx.story_id
        plan = self._resolve_worktree_plan(cfg, story_display_id, story_service)

        # AG3-145 Teilschritt C (FK-22 §22.3.1, FK-91 §91.1b): Checks 7/8 decide
        # on the edge ``preflight_probe`` evidence + the backend ownership
        # context. Commission the probe per participating repo and PAUSE
        # fail-closed (``AWAITING_EDGE_PROVISIONING``) until the edge reports --
        # no optimistic PASS, no wall-clock timeout. A non-worktree story skips
        # this and Checks 7/8 PASS (no edge consultation).
        probe_stage = self._edge_probe_stage(
            ctx, plan, run_id=run_id, story_display_id=story_display_id
        )
        if isinstance(probe_stage, HandlerResult):
            return probe_stage
        edge_probe_reports, edge_ownership = probe_stage

        preflight_error = _run_preflight_check(
            cfg,
            ctx,
            story_service,
            self._dependency_repo,
            self._mode_lock_repo,
            self._residue_probe,
            edge_probe_reports=edge_probe_reports,
            edge_ownership=edge_ownership,
            participating_repos=plan[1],
        )
        if preflight_error is not None:
            return preflight_error

        enriched = self._build_enriched_context(cfg, ctx, story_service)

        s_dir = story_dir(cfg.project_root, enriched.story_id)
        s_dir.mkdir(parents=True, exist_ok=True)
        self._context_repo.save(s_dir, enriched)

        artifacts: list[str] = [str(s_dir / CONTEXT_EXPORT_FILE)]

        updated_state: PhaseState | None = None
        # AG3-144 (Codex round-3, FK-91 §91.1a Rule 15): the ARE dock-point-2
        # ``load_context`` call below writes an ``are_bundle.json``
        # ArtifactEnvelope (FK-40) through the SAME ``ArtifactManager`` write
        # boundary the QA-subflow uses; bind this run's early-captured lease
        # snapshot for its duration (the control-plane's setup-start commit has
        # already materialized the active ``run_ownership_records`` row by the
        # time this phase handler runs, AG3-142 SOLL-015). The binder is
        # injected (DI via the composition root, architecture-conformance fix):
        # this module has ZERO ``state_backend.store`` imports -- resolving the
        # snapshot and calling ``bind_ownership_fence_scope`` happens INSIDE the
        # injected ``self._fence_scope_binder`` callable.
        with self._fence_scope_binder(
            project_key=enriched.project_key,
            story_id=enriched.story_id,
            run_id=run_id,
        ):
            bundle_step = self._load_are_bundle(enriched, envelope.state)
        if bundle_step is not None:
            bundle_result, updated_state = bundle_step
            if bundle_result.are_bundle_ref is not None:
                artifacts.append(bundle_result.are_bundle_ref)
            if bundle_result.status.name in {"FAIL", "ERROR"}:
                return HandlerResult(
                    status=PhaseStatus.FAILED,
                    errors=(bundle_result.reason or "are_bundle: FAILED",),
                    artifacts_produced=tuple(artifacts),
                    updated_context=enriched,
                    updated_state=updated_state,
                )

        # FK-22 §22.4c: green-main precondition AFTER the story-type weiche and
        # BEFORE worktree creation — a red main must not even produce a worktree.
        green_main_error = self._check_green_main(cfg, enriched)
        if green_main_error is not None:
            return green_main_error

        # AG3-145 Teilschritt C (FK-91 §91.1b, FK-56 §56.8): commission the edge
        # ``provision_worktree`` per participating repo and PAUSE fail-closed
        # until the ``worktree_report`` arrives; ``worktree_map`` is populated
        # from the REPORTED physical paths (the backend derives none). Without a
        # reported result the setup phase does not complete.
        worktree_outcome = self._edge_provision_stage(
            enriched, plan, s_dir, run_id=run_id
        )
        if isinstance(worktree_outcome, HandlerResult):
            return worktree_outcome
        enriched = worktree_outcome

        # FK-24 §24.3.3 (AG3-018, FIX-3): acquire the project mode-lock BEFORE the
        # status transition, then transition to In Progress. Extracted into
        # _acquire_lock_and_begin_progress to keep on_enter's cognitive complexity
        # within bounds; the acquire-first ordering and fresh-acquire compensation
        # semantics are documented on that helper.
        lock_error = self._acquire_lock_and_begin_progress(
            enriched, s_dir, story_service
        )
        if lock_error is not None:
            return lock_error

        return HandlerResult(
            status=PhaseStatus.COMPLETED,
            artifacts_produced=tuple(artifacts),
            updated_context=enriched,
            updated_state=updated_state,
        )

    def _acquire_lock_and_begin_progress(
        self,
        enriched: StoryContext,
        s_dir: Path,
        story_service: StoryService,
    ) -> HandlerResult | None:
        """Acquire the project mode-lock, then transition the story to In Progress.

        FK-24 §24.3.3 (AG3-018, FIX-3): atomically ACQUIRE the Fast/Standard
        between-modes mutex BEFORE the status transition (the enforcement half;
        Preflight Check 10 was the early read, this is the last-writer CAS).
        Acquiring FIRST keeps the story in Approved on a mode conflict ("Story
        bleibt in Approved") -- a transition-first order would leave a rejected
        story In Progress. Runs for ALL modes; idempotent per story via a durable
        marker (a re-run does not double-increment the holder count). If
        ``_begin_progress`` fails AND this run FRESHLY acquired the holder,
        compensate (release + clear the marker) so the mutex does not leak a
        holder for a story that never went In Progress; a re-run that did not
        freshly acquire leaves the prior holder intact (no double-release).

        Returns:
            A terminal :class:`HandlerResult` on acquire/begin failure, or
            ``None`` on success (the caller proceeds to COMPLETED).
        """
        from agentkit.backend.governance.setup_preflight_gate.mode_lock_marker import (
            mode_lock_acquired,
        )

        freshly_acquired = (
            self._mode_lock_repo is not None and not mode_lock_acquired(s_dir)
        )
        acquire_error = self._acquire_mode_lock(enriched, s_dir)
        if acquire_error is not None:
            return acquire_error
        begin_error = _begin_progress(story_service, enriched.story_id)
        if begin_error is not None:
            if freshly_acquired:
                self._compensate_mode_lock(enriched, s_dir)
            return begin_error
        return None

    def _build_enriched_context(
        self,
        cfg: SetupConfig,
        ctx: StoryContext,
        story_service: StoryService,
    ) -> StoryContext:
        """Build the enriched StoryContext from the AK3 Story-Service record.

        AK3 owns the user story (``story_id``); GitHub is only the code backend
        (FK-12 §12.1.1, FK-91 §91.2 rule 9). For EVERY story type the context is
        built from the authoritative ``StoryService`` record via
        :func:`build_story_context` — never from a GitHub issue. The story type,
        operative ``mode`` (FK-24 §24.3.3), title, size, labels and trigger
        inputs all come from that record (Single Source of Truth).
        """
        return build_story_context(
            project_root=cfg.project_root,
            project_key=ctx.project_key,
            story_id=cfg.story_id or ctx.story_id,
            story_service=story_service,
        )

    def _acquire_mode_lock(
        self, enriched: StoryContext, s_dir: Path
    ) -> HandlerResult | None:
        """Atomically acquire the project mode-lock (FK-24 §24.3.3, AG3-018).

        Idempotent per story via a durable acquire marker: a re-run of Setup for
        the SAME story does not double-increment the holder count. An opposite
        mode already held fails closed (``ModeLockConflictError`` -> FAILED;
        Check 10 normally catches this earlier — this is the last-writer guard).
        When no ``ModeLockRepository`` is wired (standalone/legacy), the acquire
        is skipped (the mutex is then unenforced, the documented absent-repo case).

        Args:
            enriched: The enriched story context (carries ``mode``).
            s_dir: The story working directory (durable marker location).

        Returns:
            ``None`` on success/skip; a FAILED ``HandlerResult`` on conflict.
        """
        from agentkit.backend.governance.errors import ModeLockConflictError
        from agentkit.backend.governance.setup_preflight_gate.mode_lock_marker import (
            mode_lock_acquired,
            record_mode_lock_acquired,
        )

        if self._mode_lock_repo is None:
            return None
        if mode_lock_acquired(s_dir):
            return None
        try:
            self._mode_lock_repo.acquire(enriched.project_key, enriched.mode.value)
        except ModeLockConflictError as exc:
            return HandlerResult(
                status=PhaseStatus.FAILED,
                errors=(f"no_competing_story_mode_active: {exc}",),
            )
        record_mode_lock_acquired(s_dir, mode=enriched.mode.value)
        return None

    def _compensate_mode_lock(self, enriched: StoryContext, s_dir: Path) -> None:
        """Release a freshly-acquired holder + clear the marker (FIX-3 compensation).

        Run only when this Setup run freshly acquired the mode-lock but a
        subsequent step (the status transition) failed. Releases the holder this
        run took so the between-modes mutex does not leak a holder for a story that
        never went In Progress, then clears the durable marker so Closure owes no
        further release. Best-effort: a release issue is logged, never re-raised
        (the begin_progress failure is the real, returned error).

        Args:
            enriched: The enriched story context (carries ``mode``/``project_key``).
            s_dir: The story working directory (durable marker location).
        """
        from agentkit.backend.governance.setup_preflight_gate.mode_lock_marker import (
            clear_mode_lock_marker,
        )

        if self._mode_lock_repo is None:
            return
        try:
            self._mode_lock_repo.release(enriched.project_key, enriched.mode.value)
        except Exception as exc:  # noqa: BLE001 -- best-effort compensation
            logger.warning(
                "mode-lock compensation release failed for story=%s: %s",
                enriched.story_id,
                exc,
            )
        clear_mode_lock_marker(s_dir)

    def on_exit(self, _ctx: StoryContext, _envelope: PhaseEnvelope) -> None:
        """No-op for setup phase.

        Args:
            ctx: The story context (unused).
            envelope: The current phase envelope (unused).
        """
        _ = _ctx, _envelope

    def on_resume(
        self,
        ctx: StoryContext,
        envelope: PhaseEnvelope,
        trigger: str,
    ) -> HandlerResult:
        """Resume the setup phase after an edge-provisioning PAUSE (AG3-145).

        Setup PAUSES fail-closed with ``AWAITING_EDGE_PROVISIONING`` while it
        awaits the edge ``preflight_probe`` / ``worktree_report`` results
        (FK-10 §10.2.4a, FK-91 §91.1b). Resume re-runs ``on_enter``, which is
        idempotent by construction: the coordinator commissions a command only
        when it does not already exist and reads back the reported result. When
        the edge has not reported yet the same staged flow PAUSES again (no
        wall-clock timeout, no optimistic continue). Mirrors the exploration
        design-review PAUSE/resume flow.

        Args:
            ctx: The story context for this run.
            envelope: The current (PAUSED) phase envelope.
            trigger: The resume trigger (unused: the staged flow re-derives its
                position from the commissioned commands' reported state).

        Returns:
            The :class:`HandlerResult` from ``on_enter``.
        """
        del trigger
        return self.on_enter(ctx, envelope)

    def _check_green_main(
        self, cfg: SetupConfig, enriched: StoryContext
    ) -> HandlerResult | None:
        """Evaluate the FK-22 §22.4c green-main precondition (consumes AG3-052).

        Resolves applicability from the project ``sonarqube.available`` flag and
        the story's decoupled ``mode`` axis; a not-applicable resolution
        (available==false / fast / non-code) is a SKIP.  A RED/STALE main fails
        Setup closed and writes the active, blame-free cleanup proposal into the
        phase-state result (§22.4c.3).  Returns ``None`` to proceed.
        """
        from agentkit.backend.governance.setup_preflight_gate.green_main import (
            check_main_green_precondition,
        )

        available = _sonar_available(cfg.project_root)
        result = check_main_green_precondition(
            available=available,
            mode=enriched.mode,
            story_type=enriched.story_type,
            port=self._green_main_port,
        )
        if not result.blocks_setup:
            return None
        logger.error(
            "Setup fail-closed: main is %s (head=%s); %s",
            result.status.value,
            result.main_head,
            result.cleanup_proposal,
        )
        return HandlerResult(
            status=PhaseStatus.FAILED,
            errors=(
                f"sonarqube_main_green: {result.status.value} "
                f"(main_head={result.main_head}); cleanup_proposal="
                f"{result.cleanup_proposal}",
            ),
        )

    def _load_are_bundle(
        self,
        enriched: StoryContext,
        state: PhaseState,
    ) -> tuple[ContextLoadResult, PhaseState] | None:
        """Run the deterministic ARE bundle setup step when wired."""

        if self._are_bundle_loader is None:
            return None
        result = self._are_bundle_loader.load_context(
            enriched.story_id,
            state.run_id,
        )
        if result.status.name == "SKIPPED":
            status = AreBundleStatus.SKIPPED
        elif result.status.name == "PASS":
            status = AreBundleStatus.LOADED
        else:
            status = AreBundleStatus.FAILED
        payload = state.payload if isinstance(state.payload, SetupPayload) else SetupPayload()
        updated_payload = payload.model_copy(
            update={
                "are_bundle": AreBundleSignal(
                    status=status,
                    requirement_count=result.requirement_count,
                )
            }
        )
        updated_state = evolve_phase_state(state, payload=updated_payload)
        return result, updated_state

    def _resolve_worktree_plan(
        self,
        cfg: SetupConfig,
        story_display_id: str,
        story_service: StoryService,
    ) -> _WorktreePlan:
        """Resolve the edge-provisioning plan (uses_worktree, repos, branch).

        The worktree classification (``uses_worktree``) AND the participating
        repos are derived from the AUTHORITATIVE StoryService record -- the SAME
        source :func:`build_story_context` reads (``story.story_type`` +
        ``story.participating_repos``) -- NEVER from the sparse/possibly-stale
        incoming ``StoryContext`` (Codex r1 CRITICAL, fail-open fix): a stale
        incoming ``story_type=CONCEPT`` must not cause an authoritatively
        IMPLEMENTATION story with participating repos to skip the edge probe /
        provision and complete setup with no edge report. Because the classifier
        reads the authoritative record on EVERY entry, an idempotent resume
        re-derives the SAME plan.

        A ``create_worktree=False`` config (an authoritative SetupConfig flag,
        not a sparse context field) or an authoritatively non-worktree story
        profile provisions nothing (``uses_worktree=False``); Checks 7/8 then run
        without edge consultation. An unresolvable story yields no repos so the
        staged edge flow is skipped and preflight (Check 1) reports the missing
        story.
        """
        branch = f"story/{story_display_id}"
        if not cfg.create_worktree:
            return (False, (), branch)
        story = story_service.get_story(story_display_id)
        if story is None:
            return (False, (), branch)
        profile = get_profile(StoryType(story.story_type.value))
        if not profile.uses_worktree:
            return (False, (), branch)
        return (bool(story.participating_repos), tuple(story.participating_repos), branch)

    def _require_coordinator(self) -> EdgeProvisioningCoordinator | HandlerResult:
        """Return the wired coordinator or a fail-closed FAILED result.

        A worktree story with NO wired coordinator fails closed: the backend
        provisioning path was removed in this sub-step (FK-10 §10.2.4a), so
        there is no silent fallback -- provisioning MUST run through the edge.
        """
        if self._edge_provisioning is None:
            return HandlerResult(
                status=PhaseStatus.FAILED,
                errors=(
                    "edge_provisioning_unavailable: no EdgeProvisioningCoordinator "
                    "is wired; a worktree story cannot provision (FK-10 §10.2.4a: "
                    "backend worktree provisioning was removed, AG3-145).",
                ),
            )
        return self._edge_provisioning

    def _edge_probe_stage(
        self,
        ctx: StoryContext,
        plan: _WorktreePlan,
        *,
        run_id: str,
        story_display_id: str,
    ) -> tuple[
        dict[str, PreflightProbeEvidence | None] | None,
        PreflightOwnershipContext | None,
    ] | HandlerResult:
        """Commission + read the ``preflight_probe`` commands (Checks 7/8 evidence).

        Returns the per-repo probe evidence + ownership context for preflight, a
        PAUSED result while the edge has not reported, or a FAILED result when no
        coordinator is wired. A non-worktree story returns ``(None, None)`` (no
        edge consultation -> Checks 7/8 PASS).
        """
        uses_worktree, repos, branch = plan
        if not uses_worktree:
            return (None, None)
        coordinator = self._require_coordinator()
        if isinstance(coordinator, HandlerResult):
            return coordinator
        outcome = coordinator.ensure_preflight_probes(
            project_key=ctx.project_key,
            story_id=story_display_id,
            run_id=run_id,
            repos=repos,
            branch=branch,
        )
        if outcome.pending:
            return self._edge_pause()
        return (outcome.evidence, outcome.ownership)

    def _edge_provision_stage(
        self,
        enriched: StoryContext,
        plan: _WorktreePlan,
        s_dir: Path,
        *,
        run_id: str,
    ) -> StoryContext | HandlerResult:
        """Commission + read the ``provision_worktree`` commands (FK-91 §91.1b).

        On a reported result populates ``worktree_map``/``worktree_path`` from the
        REPORTED physical paths (the SINGLE truth, FK-56 §56.8) and persists the
        enriched context. Returns a PAUSED result while the edge has not
        reported, or a FAILED result on a coordinator absence / a provisioning
        error report. A non-worktree story returns the context unchanged.
        """
        uses_worktree, repos, branch = plan
        if not uses_worktree:
            return enriched
        coordinator = self._require_coordinator()
        if isinstance(coordinator, HandlerResult):
            return coordinator
        outcome = coordinator.ensure_provisioning(
            project_key=enriched.project_key,
            story_id=enriched.story_id,
            run_id=run_id,
            repos=repos,
            branch=branch,
            base_ref="main",
        )
        if outcome.pending:
            return self._edge_pause(updated_context=enriched)
        if outcome.failed_repos:
            return HandlerResult(
                status=PhaseStatus.FAILED,
                errors=(
                    "edge_provisioning_failed: the edge reported a failure for "
                    f"repos {sorted(outcome.failed_repos)}",
                ),
                updated_context=enriched,
            )
        worktree_map = dict(outcome.worktree_map)
        worktree_path = next(iter(worktree_map.values())) if worktree_map else None
        enriched = enriched.model_copy(
            update={"worktree_path": worktree_path, "worktree_map": worktree_map},
        )
        self._context_repo.save(s_dir, enriched)
        logger.info(
            "Worktrees provisioned by edge: %s",
            ", ".join(f"{repo}={path}" for repo, path in worktree_map.items()),
        )
        return enriched

    @staticmethod
    def _edge_pause(
        *, updated_context: StoryContext | None = None
    ) -> HandlerResult:
        """Build the fail-closed ``AWAITING_EDGE_PROVISIONING`` PAUSE result.

        FK-91 §91.1a Rule 16 / FK-10 §10.2.4a: the open edge command stays
        visibly open (no wall-clock TTL); the phase resumes only after the edge
        reports. Mirrors the exploration design-review PAUSE.
        """
        return HandlerResult(
            status=PhaseStatus.PAUSED,
            yield_status=PauseReason.AWAITING_EDGE_PROVISIONING.value,
            updated_context=updated_context,
        )


def _sonar_available(project_root: Path) -> bool:
    """Return the project's ``sonarqube.available`` flag (fail-closed default).

    A missing/unreadable project config or absent ``sonarqube`` stanza defaults
    ``available=True`` (FK-03 §3: the green-gate is the default for
    code-producing projects; ``available=false`` is a conscious opt-out).  The
    applicability resolver then decides skip-vs-fail-closed (FK-33 §33.6.5).
    """
    try:
        project_config = load_project_config(project_root)
    except (ConfigError, OSError):
        return True
    pipeline = getattr(project_config, "pipeline", None)
    sonar = getattr(pipeline, "sonarqube", None) if pipeline is not None else None
    if sonar is None:
        return True
    return bool(getattr(sonar, "available", True))


def _resolve_story_service(cfg: SetupConfig) -> StoryService:
    """Return the injected StoryService or build a real one (Befund 9)."""
    if cfg.story_service is not None:
        return cfg.story_service
    from agentkit.backend.story_context_manager.service import StoryService as _StoryService
    return _StoryService()


def _run_preflight_check(
    cfg: SetupConfig,
    ctx: StoryContext,
    story_service: StoryService,
    dependency_repository: StoryDependencyRepository | None = None,
    mode_lock_repository: ModeLockRepository | None = None,
    residue_probe: Callable[[Path, str], bool] | None = None,
    *,
    edge_probe_reports: dict[str, PreflightProbeEvidence | None] | None = None,
    edge_ownership: PreflightOwnershipContext | None = None,
    participating_repos: tuple[str, ...] = (),
) -> HandlerResult | None:
    """Run preflight; return None on pass or a FAILED HandlerResult on failure.

    Args:
        cfg: Setup configuration.
        ctx: Current story context.
        story_service: StoryService instance for preflight checks.
        dependency_repository: Optional repository for story dependencies.
            When ``None``, dependency checks are skipped inside
            ``run_preflight`` — no lazy import (AG3-031 Pass-6 Fix E9).
        mode_lock_repository: Optional ``ModeLockRepository`` whose read path
            feeds Preflight Check 10 (``no_competing_story_mode_active``,
            Check-10 wiring).  When ``None`` the mode-lock is treated as idle.
        edge_probe_reports: Per-repo edge ``preflight_probe`` evidence for
            Checks 7/8 (AG3-145 Teilschritt C). ``None`` for a non-worktree
            story (Checks 7/8 PASS trivially).
        edge_ownership: The backend ownership decision context for Checks 7/8.
        participating_repos: The repos Checks 7/8 iterate.
    """
    from agentkit.backend.governance.setup_preflight_gate.preflight import PreflightStatus

    story_display_id = cfg.story_id or ctx.story_id
    mode_lock_reader = _build_mode_lock_reader(mode_lock_repository)
    preflight = run_preflight(
        story_display_id,
        story_service,
        project_key=ctx.project_key,
        project_root=cfg.project_root,
        dependency_repository=dependency_repository,
        mode_lock_reader=mode_lock_reader,
        active_runtime_residue=residue_probe,
        edge_probe_reports=edge_probe_reports,
        edge_ownership=edge_ownership,
        participating_repos=participating_repos,
    )
    if preflight.passed:
        return None
    error_msgs = tuple(
        _preflight_error_message(c)
        for c in preflight.checks
        if c.status is PreflightStatus.FAIL
    )
    return HandlerResult(status=PhaseStatus.FAILED, errors=error_msgs)


def _build_mode_lock_reader(
    mode_lock_repository: ModeLockRepository | None,
) -> Callable[[str], ModeLockRecord | None] | None:
    """Build the FAIL-CLOSED Check-10 mode-lock read path (E-E fix).

    Returns a reader ``reader(project_key) -> ModeLockRecord | None`` that
    delegates straight to ``ModeLockRepository.read_lock`` WITHOUT catching
    errors: a read failure must surface as a fail-closed Check-10 ``FAIL`` (via
    ``run_preflight._run_one``), NOT be masked as an idle lock that hides a real
    mode conflict.  ``None`` repository (standalone/legacy) -> no reader (Check
    10 then treats the lock as idle, the documented absent-repo case).
    """
    if mode_lock_repository is None:
        return None
    return mode_lock_repository.read_lock


def _preflight_error_message(check: PreflightCheckResult) -> str:
    """Render a single failed preflight check into a human-readable error line.

    Includes the cleanup hint (FK-22 §22.3.4) so the human reading the
    phase-state result sees the concrete remediation step.

    Args:
        check: A failed :class:`PreflightCheckResult`.

    Returns:
        ``"<check_id>: <detail>[ -> <cleanup_hint>]"``.
    """
    detail = check.detail or "failed"
    line = f"{check.check_id.value}: {detail}"
    if check.cleanup_hint:
        line = f"{line} -> {check.cleanup_hint}"
    return line


def _begin_progress(
    story_service: StoryService, story_id: str,
) -> HandlerResult | None:
    """Call ``begin_progress``; return None on success or FAILED HandlerResult."""
    try:
        story_service.begin_progress(story_id)
    except Exception as bp_err:  # noqa: BLE001
        return HandlerResult(
            status=PhaseStatus.FAILED,
            errors=(f"begin_progress failed: {bp_err}",),
        )
    return None
