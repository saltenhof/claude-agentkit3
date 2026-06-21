"""Deterministic single-match accepted-exception reconciler (FK-33 §33.6.4).

A deterministic pipeline step (scoped ``Administer Issues`` token; the
worker/agent has NO issue-admin rights) applies a ledger exception ONLY
when exactly ONE current Sonar issue matches the entry. Matching uses the
stable triple ``rule_key`` + ``normalized_code_fingerprint`` +
``expected_message_pattern`` — NEVER the unstable ``issueKey``/line.

Zero or more-than-one matches fail the reconciler **closed**
(``ReconcilerFailClosedError``): renewed six-eyes approval is required.
The reconciler is applied to the final branch scan BEFORE the green/red
verdict is decided (gate.py wires it).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from agentkit.backend.verify_system.sonarqube_gate.errors import ReconcilerFailClosedError

if TYPE_CHECKING:
    from agentkit.backend.verify_system.sonarqube_gate.ledger import (
        AcceptedExceptionLedgerEntry,
    )

# AG3-052 §2.2: the post-merge reconcile against main and the six-eyes
# quorum PROCESS are out of scope; this module owns the single-match
# matching contract and the fail-closed verdict only.


@dataclass(frozen=True)
class SonarIssue:
    """Transport-neutral view of one current Sonar issue.

    Built from ``api/issues/search`` results by the caller. ``issue_key``
    is carried for the admin transition only — it is NEVER used to match
    against the ledger (it is unstable).

    Attributes:
        issue_key: SonarQube-internal issue key (for the transition call).
        rule_key: Rule key (matched).
        normalized_code_fingerprint: Refactor-stable code fingerprint
            (matched).
        message: Issue message (matched against the entry's pattern).
    """

    issue_key: str
    rule_key: str
    normalized_code_fingerprint: str
    message: str


@dataclass(frozen=True)
class ReconciliationResult:
    """Outcome of reconciling the ledger against current issues.

    Attributes:
        accepted_issue_keys: Issue keys to transition to ``Accepted``
            (exactly one per applied ledger entry).
    """

    accepted_issue_keys: tuple[str, ...]


def _entry_matches(
    entry_rule_key: str,
    entry_fingerprint: str,
    pattern: re.Pattern[str],
    issue: SonarIssue,
) -> bool:
    return (
        issue.rule_key == entry_rule_key
        and issue.normalized_code_fingerprint == entry_fingerprint
        and pattern.search(issue.message) is not None
    )


def reconcile_single_match(
    ledger_entries: tuple[AcceptedExceptionLedgerEntry, ...],
    current_issues: tuple[SonarIssue, ...],
) -> ReconciliationResult:
    """Reconcile each ledger entry to exactly one current issue.

    For each entry, count current issues matching the stable triple. A
    count of exactly one applies the exception; zero or more than one
    fails closed (FK-33 §33.6.4).

    Args:
        ledger_entries: Accepted-exception ledger entries to reconcile.
        current_issues: Current Sonar issues for the scan target.

    Returns:
        A :class:`ReconciliationResult` with the issue keys to accept.

    Raises:
        ReconcilerFailClosedError: When any entry matches zero or more
            than one current issue.
    """
    accepted: list[str] = []
    for entry in ledger_entries:
        rule_key = entry.rule_key
        fingerprint = entry.normalized_code_fingerprint
        raw_pattern = entry.expected_message_pattern
        try:
            pattern = re.compile(raw_pattern)
        except re.error as exc:
            raise ReconcilerFailClosedError(
                f"ledger entry for rule {rule_key!r} has an invalid "
                f"expected_message_pattern {raw_pattern!r}: {exc}"
            ) from exc

        matches = [
            issue
            for issue in current_issues
            if _entry_matches(rule_key, fingerprint, pattern, issue)
        ]
        if len(matches) != 1:
            raise ReconcilerFailClosedError(
                f"accepted-exception ledger entry (rule={rule_key!r}, "
                f"fingerprint={fingerprint!r}) matched {len(matches)} current "
                "Sonar issues; exactly 1 required (FK-33 §33.6.4 single-match). "
                "Fail-closed: renewed six-eyes approval needed."
            )
        accepted.append(matches[0].issue_key)
    return ReconciliationResult(accepted_issue_keys=tuple(accepted))


__all__ = ["ReconciliationResult", "SonarIssue", "reconcile_single_match"]
