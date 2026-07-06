"""Branch & completion checks (FK-27 §27.4.2 / FK-33 §33.3.2).

These are BLOCKING checks, so per the FK-33 §33.5.2 core rule ("class C may
never be blocking", FK-07-008) they MUST decide on INDEPENDENT system evidence,
NOT on the worker's ``worker-manifest.json`` (a Trust-C self-report). They
therefore consult the :class:`ChangeEvidence` collected by the system evidence
provider: the actual checked-out branch, the real commit history since the base
ref, and the AG3-147 two-stage push verification result. Branch/commit data is
Trust B (FK-33 §33.5.1 "system-emitted data ... commit history"); the push
state is the Edge report plus server ref-read, never a backend-local upstream
guess. The findings are ``SYSTEM`` (blocking-eligible).

The expected branch ``story/{story_id}`` comes from the authoritative
``StoryContext.story_id`` (single source of truth). The worker manifest is NOT
read here -- it is at most ADDITIVE evidence and may never gate a BLOCKING.

FAIL-CLOSED: when the system evidence is unconfirmable
(``ChangeEvidence.available is False`` -- no git repo / git unreadable), each
check FAILs (NO ERROR BYPASSING). A missing git provider can never silently
pass a worker's branch/commit/push claim.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.backend.verify_system.protocols import Finding, TrustClass

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.backend.core_types import Severity
    from agentkit.backend.story_context_manager.models import StoryContext
    from agentkit.backend.verify_system.structural.system_evidence import ChangeEvidence

__all__ = [
    "check_branch_commit_trailers",
    "check_branch_story",
    "check_completion_commit",
    "check_completion_push",
]

#: FK-22 §22 / FK-27 §27.4.2: the canonical per-story branch name prefix.
_STORY_BRANCH_PREFIX = "story/"
_BRANCH_COMMIT_TRAILERS_CHECK = "branch.commit_trailers"


def _finding(check: str, severity: Severity, message: str) -> Finding:
    return Finding(
        layer="structural",
        check=check,
        severity=severity,
        message=message,
        trust_class=TrustClass.SYSTEM,
    )


def _unconfirmable(check: str, severity: Severity, fk: str) -> Finding:
    """Fail-closed finding when the system git evidence is unavailable."""
    return _finding(
        check, severity,
        f"system git evidence unavailable; cannot confirm {check} from an "
        f"independent source -> fail-closed ({fk}, FK-33 §33.5.2 -- a BLOCKING "
        "check may not fall back to worker self-report)",
    )


def check_branch_story(
    ctx: StoryContext,
    story_dir: Path,
    *,
    severity: Severity,
    evidence: ChangeEvidence,
) -> Finding | None:
    """FK-27 §27.4.2 ``branch.story``: work is on ``story/{story_id}``.

    Decides on the SYSTEM ``git`` branch (``evidence.current_branch``), not the
    worker manifest (FK-33 §33.5.2).

    Args:
        ctx: Story context (authoritative ``story_id``).
        story_dir: Story working directory (unused; evidence is pre-collected).
        severity: Registry-resolved severity (FK-27 §27.4.2: BLOCKING).
        evidence: Independent system change evidence.

    Returns:
        ``None`` on PASS; a finding when git is on no/another branch.
    """
    del story_dir
    if not evidence.available:
        return _unconfirmable("branch.story", severity, "FK-27 §27.4.2")
    expected = f"{_STORY_BRANCH_PREFIX}{ctx.story_id}"
    if evidence.current_branch != expected:
        return _finding(
            "branch.story", severity,
            f"git branch is {evidence.current_branch!r}, expected {expected!r} "
            "(FK-27 §27.4.2)",
        )
    return None


def check_branch_commit_trailers(
    ctx: StoryContext,
    story_dir: Path,
    *,
    severity: Severity,
    evidence: ChangeEvidence,
) -> Finding | None:
    """FK-27 §27.4.2 ``branch.commit_trailers``: story-id in every commit.

    Decides on the SYSTEM ``git log`` commit history, not the worker manifest.

    Args:
        ctx: Story context (authoritative ``story_id``).
        story_dir: Story working directory (unused; evidence is pre-collected).
        severity: Registry-resolved severity (FK-27 §27.4.2: BLOCKING).
        evidence: Independent system change evidence.

    Returns:
        ``None`` on PASS; a finding when a real commit message lacks the story
        id, or there are no commits.
    """
    del story_dir
    if not evidence.available:
        return _unconfirmable(
            _BRANCH_COMMIT_TRAILERS_CHECK, severity, "FK-27 §27.4.2"
        )
    if not evidence.commit_messages:
        return _finding(
            _BRANCH_COMMIT_TRAILERS_CHECK, severity,
            "no commits on the story branch since base-ref (FK-27 §27.4.2)",
        )
    untagged = [msg for msg in evidence.commit_messages if ctx.story_id not in msg]
    if untagged:
        return _finding(
            _BRANCH_COMMIT_TRAILERS_CHECK, severity,
            f"{len(untagged)} commit(s) do not carry story id {ctx.story_id!r} "
            "(FK-27 §27.4.2)",
        )
    return None


def check_completion_commit(
    ctx: StoryContext,
    story_dir: Path,
    *,
    severity: Severity,
    evidence: ChangeEvidence,
) -> Finding | None:
    """FK-33 §33.3.2 ``completion.commit``: at least one commit since base-ref.

    Decides on the SYSTEM ``git log`` history, not the worker manifest.

    Args:
        ctx: Story context (unused; uniform signature).
        story_dir: Story working directory (unused; evidence is pre-collected).
        severity: Registry-resolved severity (FK-33 §33.3.2: BLOCKING).
        evidence: Independent system change evidence.

    Returns:
        ``None`` on PASS; a finding when there is no commit since the base ref.
    """
    del ctx, story_dir
    if not evidence.available:
        return _unconfirmable("completion.commit", severity, "FK-33 §33.3.2")
    if not evidence.commit_messages:
        return _finding(
            "completion.commit", severity,
            "no commit since base-ref on the story branch (FK-33 §33.3.2)",
        )
    return None


def check_completion_push(
    ctx: StoryContext,
    story_dir: Path,
    *,
    severity: Severity,
    evidence: ChangeEvidence,
) -> Finding | None:
    """FK-33 §33.3.2 ``completion.push``: branch server-verified as pushed.

    Decides on ``evidence.pushed`` sourced from the two-stage AG3-147 barrier
    (Edge push report plus server ref-read), not a worker ``pushed`` claim and
    not a backend-local upstream check.

    Args:
        ctx: Story context (unused; uniform signature).
        story_dir: Story working directory (unused; evidence is pre-collected).
        severity: Registry-resolved severity (FK-33 §33.3.2: BLOCKING).
        evidence: Independent system change evidence.

    Returns:
        ``None`` on PASS; a finding when the two-stage push verification does
        not confirm the branch is pushed.
    """
    del ctx, story_dir
    if not evidence.available:
        return _unconfirmable("completion.push", severity, "FK-33 §33.3.2")
    if not evidence.pushed:
        return _finding(
            "completion.push", severity,
            "story branch is not server-verified-pushed (FK-33 §33.3.2)",
        )
    return None
