"""Setup phase handler -- first phase in every pipeline run.

Reads the GitHub issue, builds StoryContext, runs preflight checks,
and optionally creates a git worktree.  On successful completion,
calls ``StoryService.begin_progress`` (FK-22 §22.4.3).

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
from agentkit.backend.exceptions import ConfigError, WorktreeError
from agentkit.backend.governance.setup_preflight_gate.context_builder import (
    build_internal_story_context,
    build_story_context,
)
from agentkit.backend.governance.setup_preflight_gate.preflight import run_preflight
from agentkit.backend.governance.setup_preflight_gate.worktree import setup_worktrees
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
from agentkit.backend.story_context_manager.types import get_profile
from agentkit.backend.utils.git import remove_worktree

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from agentkit.backend.execution_planning.repository import StoryDependencyRepository
    from agentkit.backend.governance.repository import SetupContextRepository
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
        owner: GitHub repository owner.
        repo: GitHub repository name.
        issue_nr: Issue number to process.
        project_root: Root directory of the target project.
        story_id: Optional explicit story ID.  If ``None``, derived
            from the issue number.
        create_worktree: Whether to create a git worktree.
            Automatically determined from story type when ``True``.
        story_service: Optional StoryService instance.  When provided,
            ``begin_progress`` is called on successful completion
            (FK-22 §22.4.3). When ``None``, the transition is skipped
            (legacy / standalone mode).
    """

    owner: str
    repo: str
    issue_nr: int
    project_root: Path
    story_id: str | None = None
    create_worktree: bool = True
    story_service: StoryService | None = None


class SetupPhaseHandler:
    """Phase handler for the Setup phase.

    Implements the :class:`~agentkit.backend.pipeline_engine.lifecycle.PhaseHandler`
    protocol.  Reads a GitHub issue, builds the story context, runs
    preflight checks, persists the context, and optionally prepares a
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
    ) -> None:
        self._config = config
        self._context_repo: SetupContextRepository = context_repository
        self._dependency_repo: StoryDependencyRepository | None = dependency_repository
        self._mode_lock_repo = mode_lock_repository
        self._green_main_port = green_main_port
        self._are_bundle_loader = are_bundle_loader
        self._residue_probe = residue_probe

    def on_enter(self, ctx: StoryContext, envelope: PhaseEnvelope) -> HandlerResult:
        """Execute the setup phase.

        Steps:
            1. Run preflight checks against StoryService -- if any fail,
               return ``FAILED``.
            2. Build ``StoryContext`` from the GitHub issue.
            3. Save ``context.json`` to the story directory.
            4. Create a git worktree via ``git worktree add`` if the story
               type requires one; on failure return ``FAILED``.
            5. If a ``story_service`` is configured, call
               ``begin_progress`` on the story to transition it to
               ``In Progress`` (FK-22 §22.4.3).
            6. Return ``COMPLETED`` with a list of produced artifacts.

        Note:
            The *ctx* parameter is the **initial** context (may be
            sparse).  This handler enriches it from the GitHub issue
            and persists the enriched version.

        Args:
            ctx: The initial (possibly sparse) story context.
            envelope: The current phase envelope (state unused by setup).

        Returns:
            A ``HandlerResult`` describing the outcome.
        """
        _ = envelope
        cfg = self._config
        story_service = _resolve_story_service(cfg)

        preflight_error = _run_preflight_check(
            cfg,
            ctx,
            story_service,
            self._dependency_repo,
            self._mode_lock_repo,
            self._residue_probe,
        )
        if preflight_error is not None:
            return preflight_error

        enriched = self._build_enriched_context(cfg, ctx, story_service)

        s_dir = story_dir(cfg.project_root, enriched.story_id)
        s_dir.mkdir(parents=True, exist_ok=True)
        self._context_repo.save(s_dir, enriched)

        artifacts: list[str] = [str(s_dir / CONTEXT_EXPORT_FILE)]

        updated_state: PhaseState | None = None
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

        worktree_outcome = _setup_worktrees_if_needed(
            cfg, enriched, s_dir, self._context_repo
        )
        if isinstance(worktree_outcome, HandlerResult):
            return worktree_outcome
        enriched = worktree_outcome

        # FK-24 §24.3.3 (AG3-018, FIX-3): atomically ACQUIRE the project mode-lock
        # BEFORE the status transition — the enforcement half of the Fast/Standard
        # between-modes mutex (Preflight Check 10 was the early read; this is the
        # last-writer CAS). Acquiring FIRST is required so that on a mode conflict
        # the story stays in Approved (FK-24 §24.3.3 "Story bleibt in Approved"):
        # if it had transitioned first, an acquire-fail would leave it In Progress.
        # Runs for ALL modes (standard + fast); idempotent per story via a durable
        # marker so a re-run does not double-increment the holder count.
        from agentkit.backend.governance.setup_preflight_gate.mode_lock_marker import (
            mode_lock_acquired,
        )

        freshly_acquired = (
            self._mode_lock_repo is not None and not mode_lock_acquired(s_dir)
        )
        acquire_error = self._acquire_mode_lock(enriched, s_dir)
        if acquire_error is not None:
            return acquire_error

        # Status transition AFTER a successful acquire. If begin_progress fails AND
        # this run freshly acquired the holder, COMPENSATE (release the holder we
        # just took + clear the marker) so the mutex does not leak a holder for a
        # story that never went In Progress. A re-run that did NOT freshly acquire
        # leaves the prior holder intact (no double-release).
        begin_error = _begin_progress(story_service, enriched.story_id)
        if begin_error is not None:
            if freshly_acquired:
                self._compensate_mode_lock(enriched, s_dir)
            return begin_error

        return HandlerResult(
            status=PhaseStatus.COMPLETED,
            artifacts_produced=tuple(artifacts),
            updated_context=enriched,
            updated_state=updated_state,
        )

    def _build_enriched_context(
        self,
        cfg: SetupConfig,
        ctx: StoryContext,
        story_service: StoryService,
    ) -> StoryContext:
        """Build the enriched StoryContext WITHOUT GitHub for internal stories (#2).

        ERROR-2 fix (FK-12 §12.7.1): a code-producing story (implementation/bugfix)
        is GitHub-backed -- its context is read from the GitHub issue
        (``build_story_context`` -> ``get_issue``). An INTERNAL story
        (CONCEPT/RESEARCH) has no worktree/merge and NO GitHub coordinates, so it
        must NOT contact GitHub: it is built from the authoritative ``StoryService``
        record (``build_internal_story_context``), never via a dummy
        owner/repo/issue passed into a GitHub-reading path. The same authoritative
        criterion as the dispatch / setup-config path is used
        (``is_code_producing_story``).

        FIX-1 (FK-24 §24.3.3): for the code-producing path the operative ``mode``
        still comes from the authoritative ``StoryService`` record, not labels.
        """
        from agentkit.backend.verify_system.sonarqube_gate.applicability import (
            is_code_producing_story,
        )

        if not is_code_producing_story(ctx.story_type):
            return build_internal_story_context(
                project_root=cfg.project_root,
                project_key=ctx.project_key,
                story_id=cfg.story_id or ctx.story_id,
                story_service=story_service,
            )
        return build_story_context(
            owner=cfg.owner,
            repo=cfg.repo,
            issue_nr=cfg.issue_nr,
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
        _ctx: StoryContext,
        _envelope: PhaseEnvelope,
        _trigger: str,
    ) -> HandlerResult:
        """Setup phase does not support resume -- return FAILED.

        Args:
            ctx: The story context (unused).
            envelope: The current phase envelope (unused).
            trigger: The resume trigger (unused).

        Returns:
            A ``HandlerResult`` with ``FAILED`` status.
        """
        _ = _ctx, _envelope, _trigger
        return HandlerResult(
            status=PhaseStatus.FAILED,
            errors=("Setup phase does not support resume",),
        )

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


def _setup_worktrees_if_needed(
    cfg: SetupConfig,
    enriched: StoryContext,
    s_dir: Path,
    context_repo: SetupContextRepository,
) -> StoryContext | HandlerResult:
    """Create worktrees and persist enriched context — returns updated ctx or FAILED."""
    profile = get_profile(enriched.story_type)
    if not (cfg.create_worktree and profile.uses_worktree):
        return enriched

    try:
        project_config = load_project_config(cfg.project_root)
        worktree_results = setup_worktrees(
            enriched.story_id,
            enriched,
            project_config,
            project_root=cfg.project_root,
        )
    except (ConfigError, WorktreeError) as e:
        return HandlerResult(status=PhaseStatus.FAILED, errors=(str(e),))

    worktree_path = (
        worktree_results[0].worktree_path if worktree_results else None
    )
    worktree_map = {
        result.repo_name: result.worktree_path
        for result in worktree_results
    }
    enriched = enriched.model_copy(
        update={
            "worktree_path": worktree_path,
            "worktree_map": worktree_map,
        },
    )

    try:
        context_repo.save(s_dir, enriched)
    except Exception as persist_err:
        # Worktree was created but context persistence failed.
        # Clean up the worktree so it does not leak.
        for result in worktree_results:
            repo_root = result.worktree_path.parent.parent
            with contextlib.suppress(WorktreeError):
                remove_worktree(repo_root, result.worktree_path)
        return HandlerResult(
            status=PhaseStatus.FAILED,
            errors=(f"Failed to persist worktree context: {persist_err}",),
        )

    logger.info(
        "Worktrees created: %s",
        ", ".join(
            f"{result.repo_name}={result.worktree_path}"
            for result in worktree_results
        ),
    )
    return enriched


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
