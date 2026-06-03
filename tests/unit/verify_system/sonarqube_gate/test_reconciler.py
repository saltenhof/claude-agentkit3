"""Unit tests for the deterministic single-match reconciler (FK-33 §33.6.4).

Covers AC4: exactly-1 match applies; 0 or >1 fails closed; matching uses
the stable triple (rule_key + normalized_code_fingerprint +
expected_message_pattern), NOT issueKey/line.
"""

from __future__ import annotations

import pytest

from agentkit.verify_system.sonarqube_gate import (
    AcceptedExceptionLedgerEntry,
    ReconcilerFailClosedError,
    SonarIssue,
    reconcile_single_match,
)


def _entry(**overrides: object) -> AcceptedExceptionLedgerEntry:
    base: dict[str, object] = {
        "rule_key": "python:S1192",
        "file_path": "src/a.py",
        "normalized_code_fingerprint": "fp-1",
        "expected_message_pattern": r"Define a constant",
        "rationale": "intentional",
        "approved_by": ("alice", "bob", "carol"),
        "approved_commit": "c0ffee",
        "expiry": "",
        "scope": "branch-only",
    }
    base.update(overrides)
    return AcceptedExceptionLedgerEntry(**base)  # type: ignore[arg-type]


def _issue(**overrides: object) -> SonarIssue:
    base: dict[str, object] = {
        "issue_key": "ISSUE-1",
        "rule_key": "python:S1192",
        "normalized_code_fingerprint": "fp-1",
        "message": "Define a constant instead of duplicating this literal.",
    }
    base.update(overrides)
    return SonarIssue(**base)  # type: ignore[arg-type]


class TestSingleMatch:
    def test_exactly_one_match_applies(self) -> None:
        result = reconcile_single_match((_entry(),), (_issue(issue_key="ISSUE-9"),))
        assert result.accepted_issue_keys == ("ISSUE-9",)

    def test_match_uses_stable_triple_not_issue_key(self) -> None:
        """A different issue_key still matches via the stable triple."""
        result = reconcile_single_match(
            (_entry(),), (_issue(issue_key="DIFFERENT-KEY"),)
        )
        assert result.accepted_issue_keys == ("DIFFERENT-KEY",)


class TestFailClosed:
    def test_zero_match_fails_closed(self) -> None:
        with pytest.raises(ReconcilerFailClosedError, match="matched 0"):
            reconcile_single_match((_entry(),), ())

    def test_zero_match_when_fingerprint_differs(self) -> None:
        with pytest.raises(ReconcilerFailClosedError, match="matched 0"):
            reconcile_single_match(
                (_entry(),), (_issue(normalized_code_fingerprint="other-fp"),)
            )

    def test_multi_match_fails_closed(self) -> None:
        issues = (_issue(issue_key="A"), _issue(issue_key="B"))
        with pytest.raises(ReconcilerFailClosedError, match="matched 2"):
            reconcile_single_match((_entry(),), issues)

    def test_message_pattern_mismatch_fails_closed(self) -> None:
        with pytest.raises(ReconcilerFailClosedError, match="matched 0"):
            reconcile_single_match(
                (_entry(),), (_issue(message="completely unrelated message"),)
            )

    def test_invalid_pattern_fails_closed(self) -> None:
        with pytest.raises(ReconcilerFailClosedError, match="invalid"):
            reconcile_single_match(
                (_entry(expected_message_pattern="["),), (_issue(),)
            )
