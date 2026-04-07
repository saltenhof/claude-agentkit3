"""Setup phase handler -- first phase in every pipeline run.

Reads the GitHub issue, builds StoryContext, runs preflight checks,
and optionally creates a git worktree.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from agentkit.pipeline.lifecycle import HandlerResult
from agentkit.pipeline.phases.setup.context_builder import build_story_context
from agentkit.pipeline.phases.setup.preflight import run_preflight
from agentkit.pipeline.state import save_story_context
from agentkit.project_ops.shared.paths import story_dir
from agentkit.story.models import PhaseStatus
from agentkit.story.types import get_profile

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.story.models import PhaseState, StoryContext

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
            4. Compute the git worktree path if the story type
               requires one (actual ``git worktree add`` is deferred).
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
        cfg = self._config

        # 1. Preflight
        preflight = run_preflight(cfg.owner, cfg.repo, cfg.issue_nr)
        if not preflight.passed:
            error_msgs = tuple(
                c.message for c in preflight.checks if not c.passed
            )
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
            story_id=cfg.story_id or ctx.story_id,
        )

        # 3. Persist context.json
        s_dir = story_dir(cfg.project_root, enriched.story_id)
        s_dir.mkdir(parents=True, exist_ok=True)
        save_story_context(s_dir, enriched)

        artifacts: list[str] = [str(s_dir / "context.json")]

        # 4. Worktree path (compute only)
        profile = get_profile(enriched.story_type)
        if cfg.create_worktree and profile.uses_worktree:
            worktree_path = _compute_worktree_path(
                cfg.project_root, enriched.story_id,
            )
            # TODO: Actually run `git worktree add` here once we have
            # a real git repo in the execution environment. For now we
            # only compute and persist the intended path.
            enriched = enriched.model_copy(
                update={"worktree_path": worktree_path},
            )
            save_story_context(s_dir, enriched)
            logger.info(
                "Worktree path computed: %s (creation deferred)", worktree_path,
            )

        # 5. Return COMPLETED
        return HandlerResult(
            status=PhaseStatus.COMPLETED,
            artifacts_produced=tuple(artifacts),
        )

    def on_exit(self, ctx: StoryContext, state: PhaseState) -> None:
        """No-op for setup phase.

        Args:
            ctx: The story context (unused).
            state: The current phase state (unused).
        """

    def on_resume(
        self, ctx: StoryContext, state: PhaseState, trigger: str,
    ) -> HandlerResult:
        """Setup phase does not support resume -- return FAILED.

        Args:
            ctx: The story context (unused).
            state: The current phase state (unused).
            trigger: The resume trigger (unused).

        Returns:
            A ``HandlerResult`` with ``FAILED`` status.
        """
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
