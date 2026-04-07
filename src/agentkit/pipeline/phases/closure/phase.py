"""Closure phase handler -- final phase that closes a story.

Validates prior phases, closes the GitHub issue, and writes
an execution report.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from agentkit.exceptions import IntegrationError
from agentkit.pipeline.lifecycle import HandlerResult
from agentkit.pipeline.phases.closure.execution_report import (
    ExecutionReport,
    _now_iso,
    write_execution_report,
)
from agentkit.pipeline.state import load_phase_snapshot
from agentkit.story.models import PhaseStatus
from agentkit.story.types import get_profile

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.story.models import PhaseState, StoryContext

logger = logging.getLogger(__name__)


@dataclass
class ClosureConfig:
    """Configuration for the closure phase handler.

    Attributes:
        owner: GitHub repository owner (for issue close).
        repo: GitHub repository name.
        issue_nr: GitHub issue number.
        close_issue: Whether to close the GitHub issue.
        story_dir: Story artifacts directory.
    """

    owner: str | None = None
    repo: str | None = None
    issue_nr: int | None = None
    close_issue: bool = True
    story_dir: Path | None = None


class ClosurePhaseHandler:
    """Phase handler for the Closure phase.

    Implements the :class:`~agentkit.pipeline.lifecycle.PhaseHandler`
    protocol.

    Steps:
        1. Validate prior phase snapshots exist (all phases before
           closure must be COMPLETED).
        2. Close GitHub issue (if configured).
        3. Write execution report (``closure.json``).
        4. Return COMPLETED.

    If prior phases are not completed, returns FAILED (not BLOCKED --
    closure should only be entered via the engine's transition system
    which already validates this).
    """

    def __init__(self, config: ClosureConfig) -> None:
        self._config = config

    def on_enter(self, ctx: StoryContext, state: PhaseState) -> HandlerResult:
        """Execute closure.

        1. Determine required prior phases from story type profile.
        2. Check that phase snapshots exist for all prior phases.
        3. Close GitHub issue (if configured, best-effort -- failure
           is warning, not error).
        4. Write ``closure.json`` execution report.
        5. Return COMPLETED with list of artifacts.

        Args:
            ctx: The story context for this pipeline run.
            state: The current phase state.

        Returns:
            A ``HandlerResult`` describing the outcome.
        """
        cfg = self._config
        warnings: list[str] = []

        # Resolve story_dir
        s_dir = cfg.story_dir
        if s_dir is None:
            return HandlerResult(
                status=PhaseStatus.FAILED,
                errors=("story_dir is not configured in ClosureConfig",),
            )

        # 1. Determine required prior phases
        profile = get_profile(ctx.story_type)
        prior_phases = profile.phases[:-1]  # all except closure itself

        # 2. Check phase snapshots for all prior phases
        missing: list[str] = []
        for phase in prior_phases:
            snapshot = load_phase_snapshot(s_dir, phase)
            if snapshot is None:
                missing.append(phase)

        if missing:
            return HandlerResult(
                status=PhaseStatus.FAILED,
                errors=tuple(
                    f"Prior phase '{p}' has no completed snapshot"
                    for p in missing
                ),
            )

        # 3. Close GitHub issue (best-effort)
        issue_closed = False
        if (
            cfg.close_issue
            and cfg.owner is not None
            and cfg.repo is not None
            and cfg.issue_nr is not None
        ):
            try:
                from agentkit.integrations.github.issues import (
                    close_issue as gh_close_issue,
                )

                gh_close_issue(cfg.owner, cfg.repo, cfg.issue_nr)
                issue_closed = True
                logger.info(
                    "Closed GitHub issue %s/%s#%d",
                    cfg.owner, cfg.repo, cfg.issue_nr,
                )
            except IntegrationError as exc:
                warning_msg = (
                    f"Failed to close GitHub issue "
                    f"{cfg.owner}/{cfg.repo}#{cfg.issue_nr}: {exc}"
                )
                warnings.append(warning_msg)
                logger.warning(warning_msg)

        # 4. Write execution report
        status = (
            "completed_with_warnings" if warnings else "completed"
        )
        report = ExecutionReport(
            story_id=ctx.story_id,
            story_type=str(ctx.story_type.value),
            status=status,
            phases_executed=tuple(prior_phases) + ("closure",),
            started_at=(
                ctx.created_at.isoformat() if ctx.created_at else None
            ),
            completed_at=_now_iso(),
            issue_closed=issue_closed,
            warnings=tuple(warnings),
        )
        report_path = write_execution_report(s_dir, report)

        # 5. Return COMPLETED
        return HandlerResult(
            status=PhaseStatus.COMPLETED,
            artifacts_produced=(str(report_path),),
        )

    def on_exit(self, ctx: StoryContext, state: PhaseState) -> None:
        """No-op for closure phase.

        Args:
            ctx: The story context (unused).
            state: The current phase state (unused).
        """

    def on_resume(
        self, ctx: StoryContext, state: PhaseState, trigger: str,
    ) -> HandlerResult:
        """Closure phase does not support resume -- return FAILED.

        Args:
            ctx: The story context (unused).
            state: The current phase state (unused).
            trigger: The resume trigger (unused).

        Returns:
            A ``HandlerResult`` with ``FAILED`` status.
        """
        return HandlerResult(
            status=PhaseStatus.FAILED,
            errors=("Closure phase does not support resume",),
        )
