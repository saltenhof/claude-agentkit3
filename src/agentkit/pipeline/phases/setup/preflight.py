"""Preflight checks for the setup phase.

All checks run even if earlier ones fail (fail-closed, collect all errors).
"""

from __future__ import annotations

from dataclasses import dataclass

from agentkit.exceptions import IntegrationError
from agentkit.integrations.github.issues import IssueData, get_issue


@dataclass(frozen=True)
class PreflightCheck:
    """A single preflight check result.

    Attributes:
        name: Short identifier for the check (e.g. ``"issue_exists"``).
        passed: Whether the check passed.
        message: Human-readable description of the outcome.
    """

    name: str
    passed: bool
    message: str


@dataclass(frozen=True)
class PreflightResult:
    """Result of all preflight checks.

    Attributes:
        passed: ``True`` only if every individual check passed.
        checks: Tuple of all check results, in execution order.
        issue_data: The fetched issue data, or ``None`` if the issue
            could not be retrieved.
    """

    passed: bool
    checks: tuple[PreflightCheck, ...]
    issue_data: IssueData | None = None


_STORY_TYPE_LABELS: frozenset[str] = frozenset({
    "bug",
    "bugfix",
    "concept",
    "research",
    "implementation",
})
"""Labels that map to a recognised story type."""


def _has_story_type_label(labels: tuple[str, ...]) -> bool:
    """Check whether at least one label maps to a known story type.

    Args:
        labels: Tuple of label names from the issue.

    Returns:
        ``True`` if a recognisable story-type label is present.
    """
    return any(label.strip().lower() in _STORY_TYPE_LABELS for label in labels)


def run_preflight(
    owner: str,
    repo: str,
    issue_nr: int,
) -> PreflightResult:
    """Run all preflight checks against a GitHub issue.

    Checks (all run regardless of earlier failures):
        1. **issue_exists** -- ``gh issue view`` succeeds.
        2. **issue_open** -- issue state is ``OPEN``.
        3. **has_story_type** -- at least one label maps to a
           recognised story type, or the default (IMPLEMENTATION)
           is acceptable.

    Args:
        owner: GitHub repository owner.
        repo: GitHub repository name.
        issue_nr: Issue number to validate.

    Returns:
        A ``PreflightResult`` containing all check outcomes.
    """
    checks: list[PreflightCheck] = []
    issue: IssueData | None = None

    # --- Check 1: issue exists ---
    try:
        issue = get_issue(owner, repo, issue_nr)
        checks.append(PreflightCheck(
            name="issue_exists",
            passed=True,
            message=f"Issue #{issue_nr} found: {issue.title}",
        ))
    except IntegrationError as exc:
        checks.append(PreflightCheck(
            name="issue_exists",
            passed=False,
            message=f"Issue #{issue_nr} not found: {exc}",
        ))

    # --- Check 2: issue is open ---
    if issue is not None:
        is_open = issue.state == "OPEN"
        checks.append(PreflightCheck(
            name="issue_open",
            passed=is_open,
            message=(
                f"Issue #{issue_nr} is {issue.state}"
                if not is_open
                else f"Issue #{issue_nr} is OPEN"
            ),
        ))
    else:
        checks.append(PreflightCheck(
            name="issue_open",
            passed=False,
            message="Cannot check state: issue could not be fetched",
        ))

    # --- Check 3: has recognisable story type ---
    # Default IMPLEMENTATION is always acceptable, so this check
    # passes even without an explicit story-type label.
    if issue is not None:
        has_label = _has_story_type_label(issue.labels)
        checks.append(PreflightCheck(
            name="has_story_type",
            passed=True,
            message=(
                f"Story type label found in: {list(issue.labels)}"
                if has_label
                else "No explicit story-type label; defaulting to IMPLEMENTATION"
            ),
        ))
    else:
        checks.append(PreflightCheck(
            name="has_story_type",
            passed=False,
            message="Cannot determine story type: issue could not be fetched",
        ))

    all_passed = all(c.passed for c in checks)
    return PreflightResult(
        passed=all_passed,
        checks=tuple(checks),
        issue_data=issue if all_passed else issue,
    )
