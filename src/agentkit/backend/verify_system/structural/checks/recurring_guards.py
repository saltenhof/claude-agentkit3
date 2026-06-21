"""Recurring guards (FK-27 §27.4.3, telemetry-based).

These guards check the PROCESS, not the solution (FK-33 §33.4.1). They count
canonical ``execution_events`` via the injected
:class:`agentkit.backend.verify_system.protocols.TelemetryEventQueryPort`.

REF-036 / FK-27 §27.4.3 two-stage LLM-review check: ``guard.llm_reviews``
(Gate 1 -- were reviews requested at all?) and ``guard.multi_llm`` (Gate 2 --
did ALL mandatory reviewers complete?) are SEPARATE BLOCKING gates and are
implemented as two distinct check functions. Empirical reason (BB2-057): both
were once only WARNING and could not block closure.

FAIL-CLOSED: the No-op telemetry port returns 0 for every event type, so the
BLOCKING guards FAIL when no telemetry is wired (NO ERROR BYPASSING).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.backend.verify_system.protocols import Finding, TrustClass

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.backend.core_types import Severity
    from agentkit.backend.story_context_manager.models import StoryContext
    from agentkit.backend.verify_system.protocols import TelemetryEventQueryPort

__all__ = [
    "MANDATORY_REVIEWER_ROLES",
    "check_guard_llm_reviews",
    "check_guard_multi_llm",
    "check_guard_no_violations",
    "check_guard_review_compliance",
]

#: Canonical telemetry event types (FK-27 §27.4.3 / FK-33 §33.3.2 / the
#: ``EventType`` enum in ``telemetry.events``).
_REVIEW_REQUEST = "review_request"
_REVIEW_COMPLIANT = "review_compliant"
_INTEGRITY_VIOLATION = "integrity_violation"
#: FK-27 §27.4.3 Gate 2: per mandatory reviewer role at least one CANONICAL
#: ``llm_call_complete`` event (the role is carried in the event payload).
#: FK-27 §27.4.3 is explicit: count ``llm_call_complete`` (emitted only AFTER
#: the review artefact §27.5.5 is written), NOT the bare ``llm_call`` (pool
#: send). This is what catches "review started, never completed" (FK-37
#: §37.1.6); counting ``llm_call`` would pass a started-but-incomplete review.
_LLM_CALL_COMPLETE = "llm_call_complete"

#: FK-27 §27.4.3 Gate 2 mandatory reviewer roles (qa_review, semantic_review,
#: doc_fidelity). Each must have at least one completion event.
MANDATORY_REVIEWER_ROLES: tuple[str, ...] = (
    "qa_review",
    "semantic_review",
    "doc_fidelity",
)


def _finding(check: str, severity: Severity, message: str) -> Finding:
    return Finding(
        layer="structural",
        check=check,
        severity=severity,
        message=message,
        trust_class=TrustClass.SYSTEM,
    )


def check_guard_llm_reviews(
    ctx: StoryContext,
    story_dir: Path,
    *,
    severity: Severity,
    telemetry: TelemetryEventQueryPort,
) -> Finding | None:
    """FK-27 §27.4.3 ``guard.llm_reviews`` (Gate 1, REF-036, BLOCKING).

    At least one ``review_request`` event must exist for the story.

    Args:
        ctx: Story context (authoritative ``story_id``).
        story_dir: Story working directory (event store root).
        severity: Registry-resolved severity (FK-27 §27.4.3: BLOCKING).
        telemetry: Telemetry event count port.

    Returns:
        ``None`` on PASS; a BLOCKING finding when no review was requested.
    """
    count = telemetry.count_events(
        story_dir,
        story_id=ctx.story_id,
        event_type=_REVIEW_REQUEST,
        project_key=ctx.project_key,
    )
    if count < 1:
        return _finding(
            "guard.llm_reviews", severity,
            "no review_request telemetry event (Gate 1, REF-036, FK-27 §27.4.3)",
        )
    return None


def check_guard_review_compliance(
    ctx: StoryContext,
    story_dir: Path,
    *,
    severity: Severity,
    telemetry: TelemetryEventQueryPort,
) -> Finding | None:
    """FK-27 §27.4.3 ``guard.review_compliance`` (MAJOR).

    Reviews ran over approved templates: ``review_compliant`` count must be at
    least the ``review_request`` count (FK-33 §33.3.2).

    FIX-B (FK-33 §33.3.2 run scope, fail-CLOSED): a ``0 == 0`` count on an
    UNRESOLVABLE run scope would otherwise free-pass (``0 < 0`` is False). So,
    like the other run-scoped guards, probe ``run_scope_resolvable`` first: when
    the active run scope cannot be resolved the compliance counts cannot be
    verified for this run and the guard fails closed.

    Args:
        ctx: Story context (authoritative ``story_id``).
        story_dir: Story working directory.
        severity: Registry-resolved severity (FK-27 §27.4.3: MAJOR).
        telemetry: Telemetry event count port.

    Returns:
        ``None`` on PASS; a MAJOR finding when compliance lags requests OR when
        the run scope is unresolvable (fail-closed).
    """
    if not telemetry.run_scope_resolvable(story_dir):
        return _finding(
            "guard.review_compliance", severity,
            "run scope unresolvable -- review_compliant/review_request counts "
            "cannot be verified for this run; fail-closed "
            "(FK-27 §27.4.3 / FK-33 §33.3.2)",
        )
    requested = telemetry.count_events(
        story_dir,
        story_id=ctx.story_id,
        event_type=_REVIEW_REQUEST,
        project_key=ctx.project_key,
    )
    compliant = telemetry.count_events(
        story_dir,
        story_id=ctx.story_id,
        event_type=_REVIEW_COMPLIANT,
        project_key=ctx.project_key,
    )
    if compliant < requested:
        return _finding(
            "guard.review_compliance", severity,
            f"review_compliant ({compliant}) < review_request ({requested}) "
            "(FK-27 §27.4.3)",
        )
    return None


def check_guard_no_violations(
    ctx: StoryContext,
    story_dir: Path,
    *,
    severity: Severity,
    telemetry: TelemetryEventQueryPort,
) -> Finding | None:
    """FK-27 §27.4.3 ``guard.no_violations`` (BLOCKING).

    No ``integrity_violation`` event may have occurred during the work.

    FIX-B (FK-33 §33.3.2 run scope, fail-CLOSED): unlike the must-have-events
    guards, this guard PASSES on a count of ``0``. A ``0`` on an UNRESOLVABLE
    run scope would therefore be a free pass on stale/unknown telemetry. So the
    guard first probes ``run_scope_resolvable``: when the active run scope cannot
    be resolved, the guard fails closed (a violation on this run cannot be ruled
    out) -- it never free-passes on an unresolvable scope.

    Args:
        ctx: Story context (authoritative ``story_id``).
        story_dir: Story working directory.
        severity: Registry-resolved severity (FK-27 §27.4.3: BLOCKING).
        telemetry: Telemetry event count port.

    Returns:
        ``None`` on PASS; a BLOCKING finding when any violation occurred OR when
        the run scope is unresolvable (fail-closed).
    """
    if not telemetry.run_scope_resolvable(story_dir):
        return _finding(
            "guard.no_violations", severity,
            "run scope unresolvable -- cannot rule out an integrity_violation "
            "for this run; fail-closed (FK-27 §27.4.3 / FK-33 §33.3.2)",
        )
    count = telemetry.count_events(
        story_dir,
        story_id=ctx.story_id,
        event_type=_INTEGRITY_VIOLATION,
        project_key=ctx.project_key,
    )
    if count > 0:
        return _finding(
            "guard.no_violations", severity,
            f"{count} integrity_violation telemetry event(s) (FK-27 §27.4.3)",
        )
    return None


def check_guard_multi_llm(
    ctx: StoryContext,
    story_dir: Path,
    *,
    severity: Severity,
    telemetry: TelemetryEventQueryPort,
) -> Finding | None:
    """FK-27 §27.4.3 ``guard.multi_llm`` (Gate 2, REF-036, BLOCKING).

    Every mandatory reviewer role (``qa_review``, ``semantic_review``,
    ``doc_fidelity``) must have COMPLETED -- at least one canonical
    ``llm_call_complete`` event per role (FK-27 §27.4.3: emitted only after the
    review artefact §27.5.5 is written, never on a bare API response). Gate 2 is
    INDEPENDENT of Gate 1.

    Args:
        ctx: Story context (authoritative ``story_id``).
        story_dir: Story working directory.
        severity: Registry-resolved severity (FK-27 §27.4.3: BLOCKING).
        telemetry: Telemetry event count port.

    Returns:
        ``None`` on PASS; a BLOCKING finding listing roles without completion.
    """
    missing = [
        role
        for role in MANDATORY_REVIEWER_ROLES
        if telemetry.count_events(
            story_dir,
            story_id=ctx.story_id,
            event_type=_LLM_CALL_COMPLETE,
            role=role,
            project_key=ctx.project_key,
        )
        < 1
    ]
    if missing:
        return _finding(
            "guard.multi_llm", severity,
            f"mandatory reviewer role(s) without an llm_call_complete event: "
            f"{missing} (Gate 2, REF-036, FK-27 §27.4.3 -- counts the "
            "completed-artefact event, not the bare llm_call)",
        )
    return None
