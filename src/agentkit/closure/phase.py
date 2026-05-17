"""Closure phase handler -- final phase that closes a story.

Validates prior phases, closes the GitHub issue, and writes
an execution report.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from agentkit.closure.execution_report.records import ExecutionReport
from agentkit.closure.execution_report.writer import write_execution_report
from agentkit.closure.post_merge_finalization.metrics import (
    build_story_metrics_record,
)
from agentkit.exceptions import IntegrationError
from agentkit.installer.paths import resolve_qa_story_dir
from agentkit.pipeline_engine.lifecycle import HandlerResult
from agentkit.state_backend.store import (
    load_phase_snapshot,
    save_story_context,
    upsert_story_metrics,
)
from agentkit.story_context_manager.models import PhaseStatus, QaCycleStatus
from agentkit.story_context_manager.types import get_profile

if TYPE_CHECKING:
    from datetime import datetime
    from pathlib import Path

    from agentkit.closure.post_merge_finalization.records import StoryMetricsRecord
    from agentkit.pipeline_engine.phase_envelope.envelope import PhaseEnvelope
    from agentkit.story_context_manager.models import StoryContext
    from agentkit.story_context_manager.service import StoryService

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
        story_service: Optional StoryService instance.  When provided,
            ``complete_story`` is called on successful closure
            (formal.story-workflow.invariant.completion_only_after_closure).
            When ``None``, the transition is skipped (legacy / standalone mode).
    """

    owner: str | None = None
    repo: str | None = None
    issue_nr: int | None = None
    close_issue: bool = True
    story_dir: Path | None = None
    story_service: StoryService | None = None


class ClosurePhaseHandler:
    """Phase handler for the Closure phase.

    Implements the :class:`~agentkit.pipeline_engine.lifecycle.PhaseHandler`
    protocol.

    Steps:
        1. Validate prior phase snapshots exist (all phases before
           closure must be COMPLETED).
        2. Close GitHub issue (if configured).
        3. Write execution report (``closure.json``).
        4. Transition story to Done via ``StoryService.complete_story``
           (when ``story_service`` is configured).
        5. Return COMPLETED.

    If prior phases are not completed, returns FAILED (not BLOCKED --
    closure should only be entered via the engine's transition system
    which already validates this).
    """

    def __init__(self, config: ClosureConfig) -> None:
        self._config = config

    def on_enter(self, ctx: StoryContext, envelope: PhaseEnvelope) -> HandlerResult:
        """Execute closure.

        1. Determine required prior phases from story type profile.
        2. Check that phase snapshots exist for all prior phases.
        3. Close GitHub issue (if configured, best-effort -- failure
           is warning, not error).
        4. Write ``closure.json`` execution report.
        5. Return COMPLETED with list of artifacts.

        Args:
            ctx: The story context for this pipeline run.
            envelope: The current phase envelope (state unused by closure).

        Returns:
            A ``HandlerResult`` describing the outcome.
        """
        _ = envelope
        cfg = self._config

        if cfg.story_dir is None:
            return HandlerResult(
                status=PhaseStatus.FAILED,
                errors=("story_dir is not configured in ClosureConfig",),
            )
        s_dir = cfg.story_dir
        save_story_context(s_dir, ctx)

        profile = get_profile(ctx.story_type)
        prior_phases = profile.phases[:-1]  # all except closure itself

        missing = _validate_prior_phases(s_dir, prior_phases)
        if missing:
            return HandlerResult(status=PhaseStatus.FAILED, errors=tuple(missing))

        story_closed, warnings = _close_github_issue(cfg)

        status = "completed_with_warnings" if warnings else "completed"
        metrics_or_error = _build_and_persist_metrics(s_dir, ctx, status)
        if isinstance(metrics_or_error, HandlerResult):
            return metrics_or_error
        metrics = metrics_or_error

        report = ExecutionReport(
            story_id=ctx.story_id,
            story_type=str(ctx.story_type.value),
            status=status,
            phases_executed=tuple(prior_phases) + ("closure",),
            started_at=ctx.created_at.isoformat() if ctx.created_at else None,
            completed_at=metrics.completed_at,
            story_closed=story_closed,
            warnings=tuple(warnings),
            metrics=metrics.to_metrics_payload(),
        )
        report_path = write_execution_report(
            s_dir,
            report,
            projection_dir=resolve_qa_story_dir(
                s_dir,
                story_id=ctx.story_id,
                project_root=ctx.project_root,
            ),
        )

        transition_error = _transition_story_done(cfg, ctx.story_id)
        if transition_error is not None:
            return transition_error

        return HandlerResult(
            status=PhaseStatus.COMPLETED,
            artifacts_produced=(str(report_path),),
        )

    def on_exit(self, _ctx: StoryContext, _envelope: PhaseEnvelope) -> None:
        """No-op for closure phase.

        Args:
            ctx: The story context (unused).
            envelope: The current phase envelope (unused).
        """
        _ = _ctx, _envelope

    def on_resume(
        self, _ctx: StoryContext, _envelope: PhaseEnvelope, _trigger: str,
    ) -> HandlerResult:
        """Closure phase does not support resume -- return FAILED.

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
            errors=("Closure phase does not support resume",),
        )


def _completed_at() -> datetime:
    from datetime import UTC, datetime

    return datetime.now(tz=UTC)


def _validate_prior_phases(s_dir: Path, prior_phases: tuple[str, ...]) -> list[str]:
    """Return one error message per phase whose snapshot is missing or not COMPLETED."""
    missing: list[str] = []
    for phase in prior_phases:
        snapshot = load_phase_snapshot(s_dir, phase)
        if snapshot is None:
            missing.append(f"Phase '{phase}': no snapshot found")
            continue
        if snapshot.status != PhaseStatus.COMPLETED:
            missing.append(
                f"Phase '{phase}': status is "
                f"'{snapshot.status}', expected 'completed'",
            )
            continue
        if phase == "implementation":
            qa_status = snapshot.evidence.get("qa_cycle_status")
            if qa_status not in (None, QaCycleStatus.PASS.value):
                missing.append(
                    f"Phase 'implementation': qa_cycle_status is "
                    f"'{qa_status}', expected 'pass'",
                )
    return missing


def _close_github_issue(cfg: ClosureConfig) -> tuple[bool, list[str]]:
    """Best-effort GitHub issue close — returns ``(closed, warnings)``."""
    if not (
        cfg.close_issue
        and cfg.owner is not None
        and cfg.repo is not None
        and cfg.issue_nr is not None
    ):
        return False, []
    try:
        from agentkit.integrations.github.issues import (
            close_issue as gh_close_issue,
        )

        gh_close_issue(cfg.owner, cfg.repo, cfg.issue_nr)
    except IntegrationError as exc:
        issue_ref = f"{cfg.owner}/{cfg.repo}#{cfg.issue_nr}"
        warning_msg = f"Failed to close GitHub issue {issue_ref}: {exc}"
        logger.warning(warning_msg)
        return False, [warning_msg]
    logger.info(
        "Closed GitHub issue %s/%s#%d",
        cfg.owner, cfg.repo, cfg.issue_nr,
    )
    return True, []


def _build_and_persist_metrics(
    s_dir: Path,
    ctx: StoryContext,
    status: str,
) -> StoryMetricsRecord | HandlerResult:
    """Materialise the metrics record or return a ``HandlerResult`` on failure."""
    try:
        metrics = build_story_metrics_record(
            s_dir,
            ctx,
            completed_at=_completed_at(),
            final_status=status,
        )
        upsert_story_metrics(s_dir, metrics)
    except Exception as exc:  # noqa: BLE001
        return HandlerResult(
            status=PhaseStatus.FAILED,
            errors=(f"Failed to materialize story metrics: {exc}",),
        )
    return metrics


def _transition_story_done(
    cfg: ClosureConfig, story_id: str,
) -> HandlerResult | None:
    """Call ``complete_story`` (Befund 9 default service) — return None on success."""
    story_service = cfg.story_service
    if story_service is None:
        from agentkit.story_context_manager.service import StoryService as _StoryService
        story_service = _StoryService()
    try:
        story_service.complete_story(story_id)
    except Exception as cs_err:  # noqa: BLE001
        return HandlerResult(
            status=PhaseStatus.FAILED,
            errors=(f"complete_story failed: {cs_err}",),
        )
    return None
