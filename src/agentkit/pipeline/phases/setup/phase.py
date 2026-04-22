"""Setup phase handler -- first phase in every pipeline run.

Reads the GitHub issue, builds StoryContext, runs preflight checks,
and optionally creates a git worktree.
"""

from __future__ import annotations

import contextlib
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from agentkit.exceptions import WorktreeError
from agentkit.installer.paths import story_dir
from agentkit.pipeline.lifecycle import HandlerResult
from agentkit.pipeline.phases.setup.context_builder import build_story_context
from agentkit.pipeline.phases.setup.preflight import run_preflight
from agentkit.state_backend import CONTEXT_EXPORT_FILE, save_story_context
from agentkit.story_context_manager.models import PhaseStatus
from agentkit.story_context_manager.types import get_profile
from agentkit.utils.git import create_worktree, remove_worktree

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.story_context_manager.models import PhaseState, StoryContext

logger = logging.getLogger(__name__)


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
    """

    owner: str
    repo: str
    issue_nr: int
    project_root: Path
    story_id: str | None = None
    create_worktree: bool = True


class SetupPhaseHandler:
    """Phase handler for the Setup phase.

    Implements the :class:`~agentkit.pipeline.lifecycle.PhaseHandler`
    protocol.  Reads a GitHub issue, builds the story context, runs
    preflight checks, persists the context, and optionally prepares a
    git worktree path.
    """

    def __init__(self, config: SetupConfig) -> None:
        self._config = config

    def on_enter(self, ctx: StoryContext, state: PhaseState) -> HandlerResult:
        """Execute the setup phase.

        Steps:
            1. Run preflight checks -- if any fail, return ``FAILED``.
            2. Build ``StoryContext`` from the GitHub issue.
            3. Save ``context.json`` to the story directory.
            4. Create a git worktree via ``git worktree add`` if the story
               type requires one; on failure return ``FAILED``.
            5. Return ``COMPLETED`` with a list of produced artifacts.

        Note:
            The *ctx* parameter is the **initial** context (may be
            sparse).  This handler enriches it from the GitHub issue
            and persists the enriched version.

        Args:
            ctx: The initial (possibly sparse) story context.
            state: The current phase state.

        Returns:
            A ``HandlerResult`` describing the outcome.
        """
        _ = state
        cfg = self._config

        # 1. Preflight
        preflight = run_preflight(cfg.owner, cfg.repo, cfg.issue_nr)
        if not preflight.passed:
            error_msgs = tuple(c.message for c in preflight.checks if not c.passed)
            return HandlerResult(
                status=PhaseStatus.FAILED,
                errors=error_msgs,
            )

        # 2. Build enriched context
        enriched = build_story_context(
            owner=cfg.owner,
            repo=cfg.repo,
            issue_nr=cfg.issue_nr,
            project_root=cfg.project_root,
            project_key=ctx.project_key,
            story_id=cfg.story_id or ctx.story_id,
        )

        # 3. Persist context.json
        s_dir = story_dir(cfg.project_root, enriched.story_id)
        s_dir.mkdir(parents=True, exist_ok=True)
        save_story_context(s_dir, enriched)

        artifacts: list[str] = [str(s_dir / CONTEXT_EXPORT_FILE)]

        # 4. Create git worktree
        profile = get_profile(enriched.story_type)
        if cfg.create_worktree and profile.uses_worktree:
            worktree_path = _compute_worktree_path(
                cfg.project_root,
                enriched.story_id,
            )
            branch_name = f"story/{enriched.story_id}"
            try:
                create_worktree(
                    repo_root=cfg.project_root,
                    worktree_path=worktree_path,
                    branch=branch_name,
                )
            except WorktreeError as e:
                return HandlerResult(
                    status=PhaseStatus.FAILED,
                    errors=(str(e),),
                )
            enriched = enriched.model_copy(
                update={"worktree_path": worktree_path},
            )
            try:
                save_story_context(s_dir, enriched)
            except Exception as persist_err:
                # Worktree was created but context persistence failed.
                # Clean up the worktree so it does not leak.
                with contextlib.suppress(WorktreeError):
                    remove_worktree(cfg.project_root, worktree_path)
                return HandlerResult(
                    status=PhaseStatus.FAILED,
                    errors=(f"Failed to persist worktree context: {persist_err}",),
                )
            logger.info(
                "Worktree created: %s (branch: %s)",
                worktree_path,
                branch_name,
            )

        # 5. Return COMPLETED
        return HandlerResult(
            status=PhaseStatus.COMPLETED,
            artifacts_produced=tuple(artifacts),
            updated_context=enriched,
        )

    def on_exit(self, _ctx: StoryContext, _state: PhaseState) -> None:
        """No-op for setup phase.

        Args:
            ctx: The story context (unused).
            state: The current phase state (unused).
        """
        _ = _ctx, _state

    def on_resume(
        self,
        _ctx: StoryContext,
        _state: PhaseState,
        _trigger: str,
    ) -> HandlerResult:
        """Setup phase does not support resume -- return FAILED.

        Args:
            ctx: The story context (unused).
            state: The current phase state (unused).
            trigger: The resume trigger (unused).

        Returns:
            A ``HandlerResult`` with ``FAILED`` status.
        """
        _ = _ctx, _state, _trigger
        return HandlerResult(
            status=PhaseStatus.FAILED,
            errors=("Setup phase does not support resume",),
        )


def _compute_worktree_path(project_root: Path, story_id: str) -> Path:
    """Compute the worktree path for a story.

    The worktree is placed at ``<project_root>/.worktrees/<story_id>``.

    Args:
        project_root: Root directory of the target project.
        story_id: The story identifier.

    Returns:
        The intended worktree directory path.
    """
    return project_root / ".worktrees" / story_id
