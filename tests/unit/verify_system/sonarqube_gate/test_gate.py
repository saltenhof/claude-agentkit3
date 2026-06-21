"""Unit tests for the gate orchestration (FK-33 §33.6, state-machine).

Covers AC6 (state-machine conformance of the verdict) + AC4 (reconciler
runs BEFORE the green/red verdict) at the capability level.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from agentkit.backend.story_context_manager.types import StoryType
from agentkit.backend.verify_system.sonarqube_gate import (
    AcceptedExceptionLedgerEntry,
    SonarApplicability,
    SonarAttestation,
    SonarIssue,
    evaluate_sonarqube_gate,
    resolve_for_context,
)
from agentkit.backend.verify_system.sonarqube_gate.port import PostApplyGateState

if TYPE_CHECKING:
    from collections.abc import Callable

_HEAD = "rev-2"


def _reader(
    status: str = "OK", count: int = 0
) -> Callable[[], PostApplyGateState]:
    """Build a POST-apply re-reader returning a fixed recomputed gate state."""

    def _read() -> PostApplyGateState:
        return PostApplyGateState(
            quality_gate_status=status, overall_open_issue_count=count
        )

    return _read


def _att(**overrides: object) -> SonarAttestation:
    base: dict[str, object] = {
        "commit_sha": "c0ffee",
        "tree_hash": "deadbeef",
        "analysis_id": "AX-1",
        "ce_task_id": "CE-1",
        "quality_gate_status": "OK",
        "quality_gate_hash": "qgh",
        "quality_profile_hash": "qph",
        "analysis_scope_hash": "ash",
        "new_code_definition": "PREVIOUS_VERSION",
        "exception_ledger_hash": "elh",
        "last_analyzed_revision": _HEAD,
        "sonarqube_version": "26.4",
        "branch_plugin_version": "1.23.0",
        "scanner_version": "5.0",
        "status": "READ",
    }
    base.update(overrides)
    return SonarAttestation(**base)  # type: ignore[arg-type]


def _evaluate(**kw: object):  # type: ignore[no-untyped-def]
    # E4: the green verdict comes from the POST-apply RE-READ, not the
    # attestation's pre-apply status. The default reader reports a recomputed
    # green gate (OK + 0 open); tests override it to model red/recomputed
    # states. The default attestation stays "OK" only for the commit-binding
    # stale-check (its status is no longer the verdict).
    defaults: dict[str, object] = {
        "applicability": SonarApplicability.APPLICABLE,
        "attestation": _att(),
        "main_head_revision": _HEAD,
        "ledger_entries": (),
        "current_issues": (),
        "post_apply_reader": _reader("OK", 0),
    }
    defaults.update(kw)
    return evaluate_sonarqube_gate(**defaults)  # type: ignore[arg-type]


class TestApplicableVerdicts:
    def test_green_passes(self) -> None:
        outcome = _evaluate()
        assert outcome.passed is True
        assert outcome.gate_status == "sonarqube_gate_passed"

    def test_red_quality_gate_fails_closed(self) -> None:
        # E4: the POST-apply re-read reports ERROR => red (no AK subtraction).
        outcome = _evaluate(post_apply_reader=_reader("ERROR", 0))
        assert outcome.passed is False
        assert outcome.gate_status == "failed"
        assert "red_gate" in (outcome.failure_reason or "")

    def test_overall_issues_fail_closed(self) -> None:
        # E4: post-apply re-read still shows open issues => red even with QG OK.
        outcome = _evaluate(post_apply_reader=_reader("OK", 2))
        assert outcome.passed is False
        assert outcome.gate_status == "failed"

    def test_missing_post_apply_reader_fails_closed(self) -> None:
        # E4: an APPLICABLE run cannot confirm green without re-reading.
        outcome = _evaluate(post_apply_reader=None)
        assert outcome.passed is False
        assert "post_apply_reread_unavailable" in (outcome.failure_reason or "")

    def test_post_apply_reader_error_fails_closed(self) -> None:
        # E4: a configured-but-unreachable Sonar on the re-read fails closed.
        def _boom() -> PostApplyGateState:
            raise ValueError("sonar down")

        outcome = _evaluate(post_apply_reader=_boom)
        assert outcome.passed is False
        assert "post_apply_reread_failed" in (outcome.failure_reason or "")

    def test_stale_attestation_fails_closed(self) -> None:
        outcome = _evaluate(attestation=_att(last_analyzed_revision="old"))
        assert outcome.passed is False
        assert "stale_attestation" in (outcome.failure_reason or "")

    def test_missing_attestation_fails_closed(self) -> None:
        outcome = _evaluate(attestation=None)
        assert outcome.passed is False
        assert outcome.failure_reason == "attestation_unreadable"


class TestReconcilerBeforeVerdict:
    """AC4 (capability level): reconciler runs BEFORE the green/red verdict.

    With a green attestation but a 0-match ledger, the verdict is FAILED
    via the reconciler — not passed — proving the reconciler gates the
    verdict.
    """

    def test_zero_match_ledger_fails_before_green(self) -> None:
        entry = AcceptedExceptionLedgerEntry(
            rule_key="python:S1192",
            file_path="src/a.py",
            normalized_code_fingerprint="fp-x",
            expected_message_pattern="x",
            rationale="r",
            approved_by=("a", "b", "c"),
            approved_commit="c0ffee",
            expiry="",
            scope="branch-only",
        )
        outcome = _evaluate(ledger_entries=(entry,), current_issues=())
        assert outcome.passed is False
        assert "ledger_reconcile_fail_closed" in (outcome.failure_reason or "")

    def test_single_match_applies_and_passes(self) -> None:
        entry = AcceptedExceptionLedgerEntry(
            rule_key="python:S1192",
            file_path="src/a.py",
            normalized_code_fingerprint="fp-x",
            expected_message_pattern="dup",
            rationale="r",
            approved_by=("a", "b", "c"),
            approved_commit="c0ffee",
            expiry="",
            scope="branch-only",
        )
        issue = SonarIssue(
            issue_key="K1",
            rule_key="python:S1192",
            normalized_code_fingerprint="fp-x",
            message="dup literal",
        )
        applied: list[str] = []
        # E4 (POST-apply RE-READ): one open non-accepted issue pre-apply
        # (current_issues=(issue,)); the single-match accept is APPLIED, then
        # Sonar recomputes the gate so the re-read reports OK + 0. The verdict
        # flips red->green THROUGH the re-read — no AK subtraction. The reader
        # below models that recomputation.
        outcome = _evaluate(
            ledger_entries=(entry,),
            current_issues=(issue,),
            issue_applier=applied.append,
            post_apply_reader=_reader("OK", 0),
        )
        assert outcome.passed is True
        assert outcome.accepted_issue_keys == ("K1",)
        # AC4: the single-matched issue is ACTUALLY applied (transitioned)
        # BEFORE the green verdict, via the injected applier.
        assert applied == ["K1"]

    def test_unmatched_open_issue_stays_red_post_apply(self) -> None:
        """E4: an open issue with NO ledger match keeps the gate red.

        With one open non-accepted issue and an EMPTY ledger, nothing is
        accepted, so the POST-apply re-read still reports ERROR + 1 open and
        the gate fails closed. Proves the accept (not a count fudge) is what
        flips the verdict.
        """
        outcome = _evaluate(
            ledger_entries=(),
            current_issues=(
                SonarIssue(
                    issue_key="K9",
                    rule_key="python:S1192",
                    normalized_code_fingerprint="fp-z",
                    message="dup literal",
                ),
            ),
            post_apply_reader=_reader("ERROR", 1),
        )
        assert outcome.passed is False
        assert outcome.gate_status == "failed"
        assert "overall_open_issues_post=1" in (outcome.failure_reason or "")

    def test_single_match_apply_failure_fails_closed(self) -> None:
        """A failed Sonar transition (apply) fails the gate closed (E4)."""
        from agentkit.backend.verify_system.sonarqube_gate import ReconcilerApplyError

        entry = AcceptedExceptionLedgerEntry(
            rule_key="python:S1192",
            file_path="src/a.py",
            normalized_code_fingerprint="fp-x",
            expected_message_pattern="dup",
            rationale="r",
            approved_by=("a", "b", "c"),
            approved_commit="c0ffee",
            expiry="",
            scope="branch-only",
        )
        issue = SonarIssue(
            issue_key="K1",
            rule_key="python:S1192",
            normalized_code_fingerprint="fp-x",
            message="dup literal",
        )

        def _failing_applier(issue_key: str) -> None:
            raise ReconcilerApplyError(f"denied for {issue_key}")

        outcome = _evaluate(
            ledger_entries=(entry,),
            current_issues=(issue,),
            issue_applier=_failing_applier,
        )
        assert outcome.passed is False
        assert "ledger_apply_fail_closed" in (outcome.failure_reason or "")


class TestNotApplicable:
    def test_unavailable_skips_no_verdict(self) -> None:
        outcome = _evaluate(
            applicability=SonarApplicability.NOT_APPLICABLE_UNAVAILABLE,
            attestation=None,
        )
        assert outcome.passed is None
        assert outcome.gate_status == "sonarqube_gate_not_applicable"

    def test_fast_must_not_reach_the_gate(self) -> None:
        """Fast resolution drops the stage in the caller; the gate is never run.

        The state machine (formal.deterministic-checks) knows NO
        ``not_applicable_fast`` Sonar status (AG3-052 E2). A fast resolution
        means the ``sonarqube_gate`` stage is dropped entirely by the caller
        (``run_sonarqube_gate_stage`` returns ``None``); invoking the gate
        capability with FAST is a wiring bug and fails closed.
        """
        with pytest.raises(ValueError, match="must not be invoked"):
            _evaluate(
                applicability=SonarApplicability.NOT_APPLICABLE_FAST, attestation=None
            )


class TestResolveForContext:
    def test_resolve_for_context_delegates(self) -> None:
        result = resolve_for_context(
            available=True, fast=False, story_type=StoryType.IMPLEMENTATION
        )
        assert result is SonarApplicability.APPLICABLE

    def test_resolve_for_context_fast_drops_gate(self) -> None:
        result = resolve_for_context(
            available=True, fast=True, story_type=StoryType.IMPLEMENTATION
        )
        assert result is SonarApplicability.NOT_APPLICABLE_FAST

    def test_resolve_for_context_rejects_non_story_type(self) -> None:
        with pytest.raises(TypeError, match="story_type must be a StoryType"):
            resolve_for_context(available=True, fast=False, story_type="impl")
