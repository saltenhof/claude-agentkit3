"""Post-merge finalization steps 6-9 (FK-29 §29.1.4, BC 7 ``PostMergeFinalization``).

Thin orchestration of the four MANDATORY but NON-BLOCKING closure steps that run
AFTER the merge and the story-done/metrics steps (FK-29 §29.1.4 steps 6-9; BC 7
``PostMergeFinalization``):

6. Doc-fidelity feedback (level 4 feedback fidelity, FK-38 §38.3.1) -- runs
   AFTER the merge and BEFORE postflight.
7. Postflight gates (the five deterministic checks, FK-29 §29.3).
8. VectorDB sync (FK-13 §13.7.1, fire-and-forget).
9. Guard deactivation (``Governance.deactivate_locks``, FK-29 §29.5).

Each step is a MANDATORY step (it always runs -- there is no empty
``postflight_done`` anchor) but NON-BLOCKING: a failure produces a Warning for
the human (FK-29 §29.3.2 / FK-38 §38.3.1), never an ESCALATED verdict and never a
rollback (the code is already on main). ``postflight_done = true`` marks
"postflight ran", NOT "all checks green".

The fachliche depth of single checks (the WorkflowMetric schema FK-29 §29.6, the
nine-section ExecutionReport FK-29 §29.4) stays with separate owners; this module
wires the STEPS, not their depth.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

from agentkit.backend.core_types import PROTOCOL_FILE, VERIFY_DECISION_FILE
from agentkit.backend.core_types.qa_artifact_names import LAYER_ARTIFACT_FILES
from agentkit.backend.installer.paths import qa_story_dir
from agentkit.backend.state_backend.store import (
    resolve_runtime_scope,
)
from agentkit.backend.state_backend.telemetry_event_store import (
    load_execution_events,
    load_story_metrics,
)
from agentkit.backend.story_context_manager.types import StoryType
from agentkit.backend.telemetry.events import EventType

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.backend.story_context_manager.models import StoryContext

#: Required QA artefacts for the ``artifacts_complete`` postflight check.
#: impl/bugfix need the full structural+decision+context set; concept/research
#: only ``context.json`` (no QA-subflow). FK-29 §29.3.1.
_CODE_REQUIRED_ARTIFACTS: tuple[str, ...] = (
    LAYER_ARTIFACT_FILES["structural"],
    VERIFY_DECISION_FILE,
    "context.json",
)
_NON_CODE_REQUIRED_ARTIFACTS: tuple[str, ...] = ("context.json",)


class DocFidelityFeedbackPort(Protocol):
    """Level-4 doc-fidelity feedback seam (FK-38 §38.3.1, AG3-026).

    The productive implementation consumes the ``verify_system.llm_evaluator``
    capability (``role=doc_fidelity``) to ask whether existing documentation must
    be updated after the merge. Non-blocking: a FAIL is a human Warning, not a
    block (the story is already merged).
    """

    def evaluate_feedback_fidelity(
        self, ctx: StoryContext, story_dir: Path
    ) -> tuple[bool, str | None]:
        """Return ``(passed, warning)`` for the level-4 feedback check."""
        ...


class VectorDbSyncPort(Protocol):
    """VectorDB sync seam (FK-13 §13.7.1, fire-and-forget).

    The productive implementation triggers an async ``story_sync`` so the freshly
    closed story is searchable for following stories. Non-blocking: an
    unreachable VectorDB is a human Warning, not a block.
    """

    def trigger_sync(self, ctx: StoryContext, story_dir: Path) -> tuple[bool, str | None]:
        """Trigger the (async) sync; return ``(triggered, warning)``."""
        ...


class GuardDeactivationPort(Protocol):
    """Guard-deactivation seam (FK-29 §29.5, governance top surface).

    The productive implementation delegates to ``Governance.deactivate_locks``.
    Closure holds NO lock logic itself (single delegation step). Non-blocking: a
    deactivation error is a human Warning, not a block.
    """

    def deactivate(self, story_id: str) -> tuple[bool, str | None]:
        """Deactivate the story locks; return ``(deactivated, warning)``."""
        ...


@dataclass(frozen=True)
class PostflightCheck:
    """One postflight check result (FK-29 §29.3.1)."""

    check: str
    passed: bool
    detail: str = ""


@dataclass(frozen=True)
class FinalizationResult:
    """Aggregated result of the four post-merge finalization steps.

    Attributes:
        postflight_checks: The five postflight check results (FK-29 §29.3.1).
        warnings: Non-blocking warnings gathered across steps 6-9 (FK-29
            §29.3.2). A non-empty list does NOT prevent COMPLETED.
    """

    postflight_checks: tuple[PostflightCheck, ...]
    warnings: tuple[str, ...] = field(default_factory=tuple)


def run_post_merge_finalization(
    ctx: StoryContext,
    *,
    story_dir: Path,
    story_closed: bool,
    doc_fidelity_port: DocFidelityFeedbackPort,
    vectordb_sync_port: VectorDbSyncPort,
    guard_deactivation_port: GuardDeactivationPort,
) -> FinalizationResult:
    """Run the four mandatory, non-blocking finalization steps (FK-29 §29.1.4 6-9).

    Order is fixed (FK-29 §29.1.4): doc-fidelity feedback (6) -> postflight (7)
    -> VectorDB sync (8) -> guard deactivation (9). Every step ALWAYS runs (no
    empty anchor); each gathers a Warning on failure instead of escalating.

    Args:
        ctx: The run :class:`StoryContext`.
        story_dir: The story working directory.
        story_closed: Whether the story status reached Done (postflight input).
        doc_fidelity_port: Level-4 doc-fidelity seam (step 6).
        vectordb_sync_port: VectorDB sync seam (step 8).
        guard_deactivation_port: Guard-deactivation seam (step 9).

    Returns:
        A :class:`FinalizationResult` (postflight checks + non-blocking warnings).
    """
    warnings: list[str] = []

    # Step 6: doc-fidelity feedback (after merge, before postflight; FK-38 §38.3.1).
    _passed, doc_warning = doc_fidelity_port.evaluate_feedback_fidelity(ctx, story_dir)
    if doc_warning is not None:
        warnings.append(f"doc-fidelity feedback (level 4): {doc_warning}")

    # Step 7: postflight gates (the five checks; FK-29 §29.3).
    checks = run_postflight_checks(ctx, story_dir=story_dir, story_closed=story_closed)
    warnings.extend(
        f"postflight {c.check} FAILED: {c.detail}" for c in checks if not c.passed
    )

    # Step 8: VectorDB sync (fire-and-forget; FK-13 §13.7.1).
    _triggered, sync_warning = vectordb_sync_port.trigger_sync(ctx, story_dir)
    if sync_warning is not None:
        warnings.append(f"VectorDB sync: {sync_warning}")

    # Step 9: guard deactivation (governance top surface; FK-29 §29.5).
    _deactivated, guard_warning = guard_deactivation_port.deactivate(ctx.story_id)
    if guard_warning is not None:
        warnings.append(f"guard deactivation: {guard_warning}")

    return FinalizationResult(
        postflight_checks=tuple(checks),
        warnings=tuple(warnings),
    )


def run_postflight_checks(
    ctx: StoryContext,
    *,
    story_dir: Path,
    story_closed: bool,
) -> tuple[PostflightCheck, ...]:
    """Run the five deterministic postflight checks (FK-29 §29.3.1).

    The checks are reported, never raised: a FAIL is a non-blocking Warning
    upstream (FK-29 §29.3.2). The result drives the ``postflight_done`` checkpoint
    (which marks "postflight ran", not "all green").

    Args:
        ctx: The run :class:`StoryContext`.
        story_dir: The story working directory.
        story_closed: Whether the story reached Done.

    Returns:
        The five :class:`PostflightCheck` results in canonical order.
    """
    return (
        _check_story_dir_exists(story_dir),
        _check_story_closed(story_closed),
        _check_metrics_set(story_dir),
        _check_telemetry_complete(ctx, story_dir),
        _check_artifacts_complete(ctx, story_dir),
    )


def _check_story_dir_exists(story_dir: Path) -> PostflightCheck:
    """``story_dir_exists``: the story directory and ``protocol.md`` exist."""
    has_dir = story_dir.is_dir()
    has_protocol = (story_dir / PROTOCOL_FILE).is_file()
    passed = has_dir and has_protocol
    detail = "" if passed else f"story_dir={story_dir} dir={has_dir} protocol={has_protocol}"
    return PostflightCheck(check="story_dir_exists", passed=passed, detail=detail)


def _check_story_closed(story_closed: bool) -> PostflightCheck:
    """``story_closed``: the AK3 story status reached Done."""
    return PostflightCheck(
        check="story_closed",
        passed=story_closed,
        detail="" if story_closed else "story status is not Done",
    )


def _check_metrics_set(story_dir: Path) -> PostflightCheck:
    """``metrics_set``: closure metrics (QA rounds + completed-at) were written."""
    try:
        metrics = load_story_metrics(story_dir)
    except Exception as exc:  # noqa: BLE001 -- postflight never raises (non-blocking)
        return PostflightCheck(
            check="metrics_set", passed=False, detail=f"metrics unreadable: {exc}"
        )
    passed = len(metrics) >= 1
    return PostflightCheck(
        check="metrics_set",
        passed=passed,
        detail="" if passed else "no story metrics persisted",
    )


def _check_telemetry_complete(ctx: StoryContext, story_dir: Path) -> PostflightCheck:
    """``telemetry_complete``: ``agent_start`` and ``agent_end`` events exist."""
    try:
        scope = resolve_runtime_scope(story_dir)
        has_start = _has_event(ctx, story_dir, scope, EventType.AGENT_START.value)
        has_end = _has_event(ctx, story_dir, scope, EventType.AGENT_END.value)
    except Exception as exc:  # noqa: BLE001 -- postflight never raises (non-blocking)
        return PostflightCheck(
            check="telemetry_complete", passed=False, detail=f"telemetry unreadable: {exc}"
        )
    passed = has_start and has_end
    detail = "" if passed else f"agent_start={has_start} agent_end={has_end}"
    return PostflightCheck(check="telemetry_complete", passed=passed, detail=detail)


def _has_event(
    ctx: StoryContext, story_dir: Path, scope: object, event_type: str
) -> bool:
    """Whether at least one event of ``event_type`` exists for the run scope."""
    run_id = getattr(scope, "run_id", None)
    project_key = getattr(scope, "project_key", ctx.project_key)
    if run_id is None:
        return False
    events = load_execution_events(
        story_dir,
        project_key=project_key,
        story_id=ctx.story_id,
        run_id=run_id,
        event_type=event_type,
    )
    return len(events) >= 1


def _check_artifacts_complete(ctx: StoryContext, story_dir: Path) -> PostflightCheck:
    """``artifacts_complete``: the required QA artefacts exist (FK-29 §29.3.1)."""
    required = _required_artifacts(ctx.story_type)
    projection_dir = qa_story_dir(_project_root_for(ctx, story_dir), ctx.story_id)
    missing = [name for name in required if not (projection_dir / name).is_file()]
    passed = not missing
    detail = "" if passed else f"missing={missing} in {projection_dir}"
    return PostflightCheck(check="artifacts_complete", passed=passed, detail=detail)


def _required_artifacts(story_type: StoryType) -> tuple[str, ...]:
    """Required QA artefacts per story type (FK-29 §29.3.1, typed switch)."""
    if story_type in (StoryType.IMPLEMENTATION, StoryType.BUGFIX):
        return _CODE_REQUIRED_ARTIFACTS
    return _NON_CODE_REQUIRED_ARTIFACTS


def _project_root_for(ctx: StoryContext, story_dir: Path) -> Path:
    """Resolve the project root for the QA projection directory."""
    if ctx.project_root is not None:
        return ctx.project_root
    # ``story_dir`` is ``{project_root}/stories/{story_id}``; two parents up.
    return story_dir.parent.parent


__all__ = [
    "DocFidelityFeedbackPort",
    "FinalizationResult",
    "GuardDeactivationPort",
    "PostflightCheck",
    "VectorDbSyncPort",
    "run_post_merge_finalization",
    "run_postflight_checks",
]
