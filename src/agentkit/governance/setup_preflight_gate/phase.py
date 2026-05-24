"""Setup phase handler -- first phase in every pipeline run.

Reads the GitHub issue, builds StoryContext, runs preflight checks,
and optionally creates a git worktree.  On successful completion,
calls ``StoryService.begin_progress`` (FK-22 §22.4.3).

AG3-031 Pass-4 Fix E9 (2026-05-24): direct import of ``save_story_context``
from ``agentkit.state_backend.store`` replaced by ``SetupContextRepository``
protocol injection via ``SetupPhaseHandler.__init__``.  The composition
root wires the ``StateBackendSetupContextAdapter`` as the default.
"""

from __future__ import annotations

import contextlib
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from agentkit.config.loader import load_project_config
from agentkit.exceptions import ConfigError, WorktreeError
from agentkit.governance.setup_preflight_gate.context_builder import build_story_context
from agentkit.governance.setup_preflight_gate.preflight import run_preflight
from agentkit.governance.setup_preflight_gate.worktree import setup_worktrees
from agentkit.installer.paths import story_dir
from agentkit.pipeline_engine.lifecycle import HandlerResult
from agentkit.state_backend.paths import CONTEXT_EXPORT_FILE
from agentkit.story_context_manager.models import PhaseStatus
from agentkit.story_context_manager.types import get_profile
from agentkit.utils.git import remove_worktree

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.governance.repository import SetupContextRepository
    from agentkit.pipeline_engine.phase_envelope.envelope import PhaseEnvelope
    from agentkit.story_context_manager.models import StoryContext
    from agentkit.story_context_manager.service import StoryService

logger = logging.getLogger(__name__)


def _default_context_repository() -> SetupContextRepository:
    """Build the default ``SetupContextRepository`` via the state backend.

    Lazy import keeps the module-level import graph clean:
    ``governance.setup_preflight_gate.phase`` imports only from
    ``governance.repository`` (Protocols) at TYPE_CHECKING time.  The
    concrete adapter is imported here, at runtime, only when
    ``SetupPhaseHandler`` is constructed without an explicit repository.

    Returns:
        A ``StateBackendSetupContextAdapter`` instance.
    """
    from agentkit.state_backend.store.setup_context_repository import (
        StateBackendSetupContextAdapter,
    )

    return StateBackendSetupContextAdapter()


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

    Implements the :class:`~agentkit.pipeline_engine.lifecycle.PhaseHandler`
    protocol.  Reads a GitHub issue, builds the story context, runs
    preflight checks, persists the context, and optionally prepares a
    git worktree path.  On successful completion, transitions the story
    to ``In Progress`` via ``StoryService.begin_progress`` when a
    ``story_service`` is provided in ``SetupConfig`` (FK-22 §22.4.3).

    Args:
        config: Setup phase configuration.
        context_repository: Repository for persisting ``StoryContext``.
            When ``None``, the default ``StateBackendSetupContextAdapter``
            is used (Fix E9, AG3-031 Pass-4).
    """

    def __init__(
        self,
        config: SetupConfig,
        context_repository: SetupContextRepository | None = None,
    ) -> None:
        self._config = config
        self._context_repo: SetupContextRepository = (
            context_repository
            if context_repository is not None
            else _default_context_repository()
        )

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

        preflight_error = _run_preflight_check(cfg, ctx, story_service)
        if preflight_error is not None:
            return preflight_error

        enriched = build_story_context(
            owner=cfg.owner,
            repo=cfg.repo,
            issue_nr=cfg.issue_nr,
            project_root=cfg.project_root,
            project_key=ctx.project_key,
            story_id=cfg.story_id or ctx.story_id,
        )

        s_dir = story_dir(cfg.project_root, enriched.story_id)
        s_dir.mkdir(parents=True, exist_ok=True)
        self._context_repo.save(s_dir, enriched)

        artifacts: list[str] = [str(s_dir / CONTEXT_EXPORT_FILE)]

        worktree_outcome = _setup_worktrees_if_needed(
            cfg, enriched, s_dir, self._context_repo
        )
        if isinstance(worktree_outcome, HandlerResult):
            return worktree_outcome
        enriched = worktree_outcome

        begin_error = _begin_progress(story_service, enriched.story_id)
        if begin_error is not None:
            return begin_error

        return HandlerResult(
            status=PhaseStatus.COMPLETED,
            artifacts_produced=tuple(artifacts),
            updated_context=enriched,
        )

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


def _resolve_story_service(cfg: SetupConfig) -> StoryService:
    """Return the injected StoryService or build a real one (Befund 9)."""
    if cfg.story_service is not None:
        return cfg.story_service
    from agentkit.story_context_manager.service import StoryService as _StoryService
    return _StoryService()


def _run_preflight_check(
    cfg: SetupConfig,
    ctx: StoryContext,
    story_service: StoryService,
) -> HandlerResult | None:
    """Run preflight; return None on pass or a FAILED HandlerResult on failure."""
    from agentkit.state_backend.store.story_dependency_repository import (
        StateBackendStoryDependencyRepository,
    )

    story_display_id = cfg.story_id or ctx.story_id
    preflight = run_preflight(
        story_display_id,
        story_service,
        dependency_repository=StateBackendStoryDependencyRepository(),
    )
    if preflight.passed:
        return None
    error_msgs = tuple(c.message for c in preflight.checks if not c.passed)
    return HandlerResult(status=PhaseStatus.FAILED, errors=error_msgs)


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
