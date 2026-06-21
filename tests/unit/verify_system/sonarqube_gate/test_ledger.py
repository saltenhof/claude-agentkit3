"""Unit tests for the accepted-exception ledger (FK-33 §33.6.4).

Covers AC3: mandatory fields incl. normalized_code_fingerprint,
approved_by[3], scope; content_hash binds into the attestation.
"""

from __future__ import annotations

import pytest

from agentkit.backend.verify_system.sonarqube_gate import (
    AcceptedExceptionLedger,
    AcceptedExceptionLedgerEntry,
    LedgerInvalidError,
)


def _entry(**overrides: object) -> AcceptedExceptionLedgerEntry:
    base: dict[str, object] = {
        "rule_key": "python:S1192",
        "file_path": "src/a.py",
        "normalized_code_fingerprint": "fp-1",
        "expected_message_pattern": "Define a constant",
        "rationale": "intentional",
        "approved_by": ("alice", "bob", "carol"),
        "approved_commit": "c0ffee",
        "expiry": "2026-12-31",
        "scope": "main-eligible",
    }
    base.update(overrides)
    return AcceptedExceptionLedgerEntry(**base)  # type: ignore[arg-type]


class TestLedgerEntryFields:
    def test_valid_entry_round_trips(self) -> None:
        entry = _entry()
        assert entry.normalized_code_fingerprint == "fp-1"
        assert entry.approved_by == ("alice", "bob", "carol")
        assert entry.scope == "main-eligible"

    def test_requires_three_approvers(self) -> None:
        with pytest.raises(LedgerInvalidError, match="exactly 3"):
            _entry(approved_by=("alice", "bob"))

    def test_requires_distinct_approvers(self) -> None:
        """No agent may approve its own exception (six-eyes independence)."""
        with pytest.raises(LedgerInvalidError, match="DISTINCT"):
            _entry(approved_by=("alice", "alice", "bob"))

    def test_rejects_empty_approver(self) -> None:
        with pytest.raises(LedgerInvalidError, match="non-empty"):
            _entry(approved_by=("alice", "  ", "carol"))

    def test_rejects_unknown_scope(self) -> None:
        with pytest.raises(LedgerInvalidError, match="branch-only.*main-eligible"):
            _entry(scope="everywhere")


class TestLedgerContentHash:
    def test_content_hash_is_deterministic_and_order_independent(self) -> None:
        a = _entry(normalized_code_fingerprint="fp-a")
        b = _entry(normalized_code_fingerprint="fp-b")
        ledger_ab = AcceptedExceptionLedger(entries=(a, b))
        ledger_ba = AcceptedExceptionLedger(entries=(b, a))
        assert ledger_ab.content_hash() == ledger_ba.content_hash()
        assert len(ledger_ab.content_hash()) == 64  # noqa: PLR2004

    def test_content_hash_changes_with_entries(self) -> None:
        empty = AcceptedExceptionLedger().content_hash()
        one = AcceptedExceptionLedger(entries=(_entry(),)).content_hash()
        assert empty != one
