"""Unit tests for TelemetryContract rules (FK-68 §68.4/68.9/68.10, AG3-037).

Uses a first-class in-memory ``ExecutionEventReader`` fake (not a mock): a real
implementation of the port backed by a plain list. The contract logic is pure
over the event stream, so this exercises the real rule behaviour. A real
``MemoryEmitter`` captures any ``preflight_compliance_violation`` event the
production path persists (FK-68 §68.9.3 — no silent suppression).
"""

from __future__ import annotations

from datetime import UTC, datetime

from agentkit.telemetry.contract.records import ExecutionEventRecord
from agentkit.telemetry.contract.results import TelemetryScope
from agentkit.telemetry.contract.telemetry_contract import (
    ContractStatus,
    TelemetryContract,
)
from agentkit.telemetry.emitters import MemoryEmitter
from agentkit.telemetry.events import EventType

_RUN = "run-001"
_PROJECT = "proj"
_STORY = "AG3-001"
_SCOPE = TelemetryScope(project_key=_PROJECT, story_id=_STORY, run_id=_RUN)


class _FakeReader:
    """In-memory ExecutionEventReader fake (real port implementation)."""

    def __init__(self, events: list[ExecutionEventRecord]) -> None:
        self._events = events

    def read_run_events(self, run_id: str) -> list[ExecutionEventRecord]:
        return [e for e in self._events if e.run_id == run_id]


def _event(
    event_type: EventType,
    *,
    role: str | None = None,
    pool: str | None = None,
    run_id: str = _RUN,
) -> ExecutionEventRecord:
    payload: dict[str, object] = {}
    if role is not None:
        payload["role"] = role
    if pool is not None:
        payload["pool"] = pool
    return ExecutionEventRecord(
        project_key="proj",
        story_id="AG3-001",
        run_id=run_id,
        event_id=f"evt-{event_type.value}-{role or ''}-{pool or ''}-{id(payload)}",
        event_type=event_type.value,
        occurred_at=datetime.now(UTC),
        source_component="test",
        severity="info",
        payload=payload,
    )


def _contract(
    events: list[ExecutionEventRecord],
) -> tuple[TelemetryContract, MemoryEmitter]:
    emitter = MemoryEmitter()
    return TelemetryContract(_FakeReader(events), emitter, _SCOPE), emitter


# ---------------------------------------------------------------------------
# check_agent_start_end_pairing (FK-68 §68.4.1)
# ---------------------------------------------------------------------------


def test_agent_pairing_pass_with_one_start_one_end() -> None:
    contract, _ = _contract([_event(EventType.AGENT_START), _event(EventType.AGENT_END)])
    result = contract.check_agent_start_end_pairing(_RUN)
    assert result.status is ContractStatus.PASS
    assert result.rule_id == "FK-68 §68.4.1"


def test_agent_pairing_fail_when_end_missing() -> None:
    contract, _ = _contract([_event(EventType.AGENT_START)])
    result = contract.check_agent_start_end_pairing(_RUN)
    assert result.status is ContractStatus.FAIL
    assert "agent_end=0" in result.detail


def test_agent_pairing_fail_when_start_missing() -> None:
    contract, _ = _contract([_event(EventType.AGENT_END)])
    result = contract.check_agent_start_end_pairing(_RUN)
    assert result.status is ContractStatus.FAIL


def test_agent_pairing_fail_when_duplicate_start() -> None:
    contract, _ = _contract(
        [
            _event(EventType.AGENT_START),
            _event(EventType.AGENT_START),
            _event(EventType.AGENT_END),
        ]
    )
    result = contract.check_agent_start_end_pairing(_RUN)
    assert result.status is ContractStatus.FAIL


# ---------------------------------------------------------------------------
# check_review_compliant_coverage (FK-68 §68.4.2)
# ---------------------------------------------------------------------------


def test_review_coverage_pass_when_roles_and_compliant_present() -> None:
    contract, _ = _contract(
        [
            _event(EventType.REVIEW_REQUEST, role="qa"),
            _event(EventType.REVIEW_REQUEST, role="architecture"),
            _event(EventType.REVIEW_COMPLIANT),
            _event(EventType.REVIEW_COMPLIANT),
        ]
    )
    result = contract.check_review_compliant_coverage(_RUN, {"qa", "architecture"})
    assert result.status is ContractStatus.PASS


def test_review_coverage_fail_when_required_role_missing() -> None:
    contract, _ = _contract(
        [
            _event(EventType.REVIEW_REQUEST, role="qa"),
            _event(EventType.REVIEW_COMPLIANT),
        ]
    )
    result = contract.check_review_compliant_coverage(_RUN, {"qa", "architecture"})
    assert result.status is ContractStatus.FAIL
    assert "architecture" in result.detail


def test_review_coverage_fail_when_compliant_undercounts() -> None:
    contract, _ = _contract(
        [
            _event(EventType.REVIEW_REQUEST, role="qa"),
            _event(EventType.REVIEW_REQUEST, role="qa"),
            _event(EventType.REVIEW_COMPLIANT),
        ]
    )
    result = contract.check_review_compliant_coverage(_RUN, {"qa"})
    assert result.status is ContractStatus.FAIL
    assert "must equal" in result.detail


def test_review_coverage_fail_when_compliant_overcounts() -> None:
    # FK-68 §68.4: strict equality. An extra/malformed review_compliant must NOT
    # pass (fail-closed against overcount).
    contract, _ = _contract(
        [
            _event(EventType.REVIEW_REQUEST, role="qa"),
            _event(EventType.REVIEW_COMPLIANT),
            _event(EventType.REVIEW_COMPLIANT),
        ]
    )
    result = contract.check_review_compliant_coverage(_RUN, {"qa"})
    assert result.status is ContractStatus.FAIL
    assert "must equal" in result.detail


# ---------------------------------------------------------------------------
# check_preflight_compliant_balance (FK-68 §68.9.3 / §68.10.2)
# ---------------------------------------------------------------------------


def test_preflight_balance_pass() -> None:
    contract, emitter = _contract(
        [
            _event(EventType.PREFLIGHT_REQUEST),
            _event(EventType.PREFLIGHT_RESPONSE),
            _event(EventType.PREFLIGHT_COMPLIANT),
        ]
    )
    result = contract.check_preflight_compliant_balance(_RUN)
    assert result.status is ContractStatus.PASS
    assert result.rule_id == "FK-68 §68.9.2"
    assert emitter.all_events == []


def test_preflight_fail_when_empty_stream_is_missing() -> None:
    # FK-68 §68.9.3: preflight is mandatory; an empty stream is PREFLIGHT_MISSING,
    # NOT a pass (fail-closed).
    contract, emitter = _contract([_event(EventType.AGENT_START)])
    result = contract.check_preflight_compliant_balance(_RUN)
    assert result.status is ContractStatus.FAIL
    assert result.rule_id == "FK-68 §68.9.2"
    assert "PREFLIGHT_MISSING" in result.detail
    assert len(emitter.all_events) == 1
    assert (
        emitter.all_events[0].event_type
        is EventType.PREFLIGHT_COMPLIANCE_VIOLATION
    )


def test_preflight_fail_on_request_compliant_imbalance() -> None:
    contract, emitter = _contract(
        [
            _event(EventType.PREFLIGHT_REQUEST),
            _event(EventType.PREFLIGHT_REQUEST),
            _event(EventType.PREFLIGHT_RESPONSE),
            _event(EventType.PREFLIGHT_RESPONSE),
            _event(EventType.PREFLIGHT_COMPLIANT),
        ]
    )
    result = contract.check_preflight_compliant_balance(_RUN)
    assert result.status is ContractStatus.FAIL
    assert result.rule_id == "FK-68 §68.9.2"
    assert "PREFLIGHT_NOT_COMPLIANT" in result.detail
    assert len(emitter.all_events) == 1


def test_preflight_fail_when_response_missing() -> None:
    # response != request even though request == compliant -> NOT compliant.
    contract, emitter = _contract(
        [
            _event(EventType.PREFLIGHT_REQUEST),
            _event(EventType.PREFLIGHT_COMPLIANT),
        ]
    )
    result = contract.check_preflight_compliant_balance(_RUN)
    assert result.status is ContractStatus.FAIL
    assert "PREFLIGHT_NOT_COMPLIANT" in result.detail
    assert len(emitter.all_events) == 1


def test_preflight_fails_closed_on_scope_mismatch() -> None:
    # FIX-1 guard: a run_id that does not match the bound authoritative scope
    # must fail closed (the violation would otherwise be persisted under the
    # wrong run). No emission happens because attribution is ambiguous.
    contract, emitter = _contract(
        [
            _event(EventType.PREFLIGHT_REQUEST),
            _event(EventType.PREFLIGHT_RESPONSE),
            _event(EventType.PREFLIGHT_COMPLIANT),
        ]
    )
    result = contract.check_preflight_compliant_balance("some-other-run")
    assert result.status is ContractStatus.FAIL
    assert result.rule_id == "FK-68 §68.9.4"
    assert "does not match" in result.detail
    assert emitter.all_events == []


# ---------------------------------------------------------------------------
# check_llm_call_role_coverage (FK-68 §68.4.3)
# ---------------------------------------------------------------------------


def test_llm_role_coverage_pass_against_configured_pool() -> None:
    contract, _ = _contract(
        [
            _event(EventType.LLM_CALL, pool="chatgpt"),
            _event(EventType.LLM_CALL, pool="gemini"),
        ]
    )
    result = contract.check_llm_call_role_coverage(
        _RUN, {"qa_review": "chatgpt", "semantic_review": "gemini"}
    )
    assert result.status is ContractStatus.PASS


def test_llm_role_coverage_fail_when_pool_missing() -> None:
    contract, _ = _contract([_event(EventType.LLM_CALL, pool="chatgpt")])
    result = contract.check_llm_call_role_coverage(
        _RUN, {"qa_review": "chatgpt", "semantic_review": "gemini"}
    )
    assert result.status is ContractStatus.FAIL
    assert "semantic_review->gemini" in result.detail


def test_llm_role_coverage_ignores_self_reported_role_without_pool() -> None:
    # An llm_call carrying only a self-reported role (no/wrong pool) must NOT
    # satisfy the configured role->pool contract (FK-68 §68.4, no bypass).
    contract, _ = _contract([_event(EventType.LLM_CALL, role="qa_review")])
    result = contract.check_llm_call_role_coverage(_RUN, {"qa_review": "chatgpt"})
    assert result.status is ContractStatus.FAIL
    assert "qa_review->chatgpt" in result.detail


# ---------------------------------------------------------------------------
# check_no_integrity_violation (FK-68 §68.4.4) — AG3-081 AC3
# ---------------------------------------------------------------------------


def test_no_integrity_violation_pass_when_absent() -> None:
    contract, _ = _contract([_event(EventType.AGENT_START)])
    result = contract.check_no_integrity_violation(_RUN)
    assert result.status is ContractStatus.PASS
    assert result.rule_id == "FK-68 §68.4.4"


def test_no_integrity_violation_fail_when_present() -> None:
    contract, _ = _contract([_event(EventType.INTEGRITY_VIOLATION)])
    result = contract.check_no_integrity_violation(_RUN)
    assert result.status is ContractStatus.FAIL
    assert "integrity_violation" in result.detail


# ---------------------------------------------------------------------------
# check_web_call_within_budget (FK-68 §68.4.5) — AG3-081 AC3
# ---------------------------------------------------------------------------


def test_web_call_within_budget_pass_when_under() -> None:
    contract, _ = _contract([_event(EventType.WEB_CALL), _event(EventType.WEB_CALL)])
    result = contract.check_web_call_within_budget(_RUN, 5)
    assert result.status is ContractStatus.PASS
    assert result.rule_id == "FK-68 §68.4.5"


def test_web_call_within_budget_pass_when_equal() -> None:
    contract, _ = _contract([_event(EventType.WEB_CALL), _event(EventType.WEB_CALL)])
    result = contract.check_web_call_within_budget(_RUN, 2)
    assert result.status is ContractStatus.PASS


def test_web_call_within_budget_fail_when_over() -> None:
    contract, _ = _contract(
        [_event(EventType.WEB_CALL), _event(EventType.WEB_CALL), _event(EventType.WEB_CALL)]
    )
    result = contract.check_web_call_within_budget(_RUN, 2)
    assert result.status is ContractStatus.FAIL
    assert "exceeds the configured web budget" in result.detail


# ---------------------------------------------------------------------------
# check_all aggregation (SIX rules — AG3-081 AC3)
# ---------------------------------------------------------------------------


def _complete_run_events() -> list[ExecutionEventRecord]:
    return [
        _event(EventType.AGENT_START),
        _event(EventType.AGENT_END),
        _event(EventType.REVIEW_REQUEST, role="qa"),
        _event(EventType.REVIEW_COMPLIANT),
        _event(EventType.PREFLIGHT_REQUEST),
        _event(EventType.PREFLIGHT_RESPONSE),
        _event(EventType.PREFLIGHT_COMPLIANT),
        _event(EventType.LLM_CALL, role="qa", pool="chatgpt"),
    ]


def test_check_all_passes_for_complete_run() -> None:
    contract, _ = _contract(_complete_run_events())
    result = contract.check_all(_RUN, {"qa"}, {"qa": "chatgpt"}, web_call_budget=200)
    assert result.passed
    assert result.failures == ()
    # AC3: check_all aggregates SIX rules (four pre-existing + the two new ones).
    assert len(result.rule_results) == 6
    assert {r.rule_id for r in result.rule_results} == {
        "FK-68 §68.4.1",
        "FK-68 §68.4.2",
        "FK-68 §68.4.3",
        "FK-68 §68.4.4",
        "FK-68 §68.4.5",
        "FK-68 §68.9.2",
    }


def test_check_all_collects_failures() -> None:
    contract, _ = _contract([_event(EventType.AGENT_START)])
    result = contract.check_all(_RUN, {"qa"}, {"qa": "chatgpt"}, web_call_budget=200)
    assert not result.passed
    # The pairing, review-coverage, preflight (missing) and llm-coverage rules
    # fail; no_integrity_violation and web_call_within_budget pass on this stream.
    failing_rules = {r.rule_id for r in result.failures}
    assert "FK-68 §68.4.1" in failing_rules
    assert "FK-68 §68.4.2" in failing_rules
    assert "FK-68 §68.9.2" in failing_rules
    assert "FK-68 §68.4.3" in failing_rules


def test_check_all_fails_on_integrity_violation() -> None:
    # AC3 negative class (d): an integrity_violation in an otherwise complete run
    # fails check_all fail-closed.
    contract, _ = _contract([*_complete_run_events(), _event(EventType.INTEGRITY_VIOLATION)])
    result = contract.check_all(_RUN, {"qa"}, {"qa": "chatgpt"}, web_call_budget=200)
    assert not result.passed
    assert "FK-68 §68.4.4" in {r.rule_id for r in result.failures}


def test_check_all_fails_on_web_budget_exceeded() -> None:
    # AC3 negative class (e): web_call over budget fails check_all fail-closed.
    contract, _ = _contract(
        [*_complete_run_events(), _event(EventType.WEB_CALL), _event(EventType.WEB_CALL)]
    )
    result = contract.check_all(_RUN, {"qa"}, {"qa": "chatgpt"}, web_call_budget=1)
    assert not result.passed
    assert "FK-68 §68.4.5" in {r.rule_id for r in result.failures}
