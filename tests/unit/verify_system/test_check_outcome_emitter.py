"""Unit tests for CheckOutcomeEmitter and build_check_outcomes (AG3-108, FK-69 §69.15).

Covers:
- Emission for each outcome: triggered / clean / overridden
- Clean/PASS checks are persisted (not discarded)
- Override -> check_id correlation
- Blank/whitespace check_id in executed_check_ids raises ValueError (fail-closed)
- Missing project_key raises ValueError (fail-closed)
- Fallback when metadata["executed_check_ids"] absent (finding-derived set)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import pytest

from agentkit.verify_system.check_outcome_emitter import (
    CheckOutcomeEmitter,
    build_check_outcomes,
)
from agentkit.verify_system.protocols import Finding, LayerResult, Severity, TrustClass
from agentkit.verify_system.stage_registry.records import CheckOutcome

# ---------------------------------------------------------------------------
# Minimal stand-ins for FlowExecution and OverrideRecord
# ---------------------------------------------------------------------------


@dataclass
class _FakeFlow:
    project_key: str = "proj-test"
    story_id: str = "AG3-999"
    run_id: str = "run-abc"


@dataclass
class _FakeOverride:
    override_id: str
    check_id: str | None = None


_TS = datetime(2026, 6, 1, 10, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _finding(check_id: str, *, severity: Severity = Severity.BLOCKING) -> Finding:
    return Finding(
        layer="structural",
        check=check_id,
        severity=severity,
        message=f"test finding for {check_id}",
        trust_class=TrustClass.SYSTEM,
    )


def _layer_result(
    findings: list[Finding],
    executed_check_ids: list[str] | None = None,
    *,
    layer: str = "structural",
) -> LayerResult:
    metadata: dict[str, object] = {}
    if executed_check_ids is not None:
        metadata["executed_check_ids"] = executed_check_ids
    return LayerResult(
        layer=layer,
        passed=len(findings) == 0,
        findings=tuple(findings),
        metadata=metadata,
    )


# ---------------------------------------------------------------------------
# Tests: triggered outcome
# ---------------------------------------------------------------------------


def test_triggered_outcome() -> None:
    """A check that produced a finding gets outcome=triggered."""
    flow = _FakeFlow()
    result = _layer_result(
        [_finding("artifact.protocol")],
        executed_check_ids=["artifact.protocol", "branch.story"],
    )

    records = build_check_outcomes(flow, result, attempt_no=1, occurred_at=_TS)

    triggered = [r for r in records if r.check_id == "artifact.protocol"]
    assert len(triggered) == 1
    assert triggered[0].outcome is CheckOutcome.TRIGGERED
    assert triggered[0].project_key == "proj-test"
    assert triggered[0].run_id == "run-abc"
    assert triggered[0].stage_id == "structural"
    assert triggered[0].attempt_no == 1
    assert triggered[0].occurred_at == _TS


# ---------------------------------------------------------------------------
# Tests: clean outcome
# ---------------------------------------------------------------------------


def test_clean_outcome() -> None:
    """A check that passed (no finding) gets outcome=clean.

    This is the core regression test for the 'PASS checks discarded' bug
    (story §1, structured_evaluator.py:448): clean/PASS checks must be
    persisted.
    """
    flow = _FakeFlow()
    result = _layer_result(
        [],  # no findings
        executed_check_ids=["branch.story", "artifact.protocol"],
    )

    records = build_check_outcomes(flow, result, attempt_no=1, occurred_at=_TS)

    assert len(records) == 2
    for rec in records:
        assert rec.outcome is CheckOutcome.CLEAN


def test_clean_and_triggered_mixed() -> None:
    """Correctly separates triggered from clean checks in same layer."""
    flow = _FakeFlow()
    result = _layer_result(
        [_finding("artifact.protocol")],
        executed_check_ids=["artifact.protocol", "branch.story", "impl_fidelity"],
    )

    records = build_check_outcomes(flow, result, attempt_no=1, occurred_at=_TS)

    by_check = {r.check_id: r for r in records}
    assert by_check["artifact.protocol"].outcome is CheckOutcome.TRIGGERED
    assert by_check["branch.story"].outcome is CheckOutcome.CLEAN
    assert by_check["impl_fidelity"].outcome is CheckOutcome.CLEAN


# ---------------------------------------------------------------------------
# Tests: overridden outcome
# ---------------------------------------------------------------------------


def test_overridden_outcome() -> None:
    """A check suppressed by an OverrideRecord gets outcome=overridden."""
    flow = _FakeFlow()
    result = _layer_result(
        [],
        executed_check_ids=["artifact.protocol", "branch.story"],
    )
    override = _FakeOverride(override_id="ovr-001", check_id="artifact.protocol")

    records = build_check_outcomes(
        flow, result, attempt_no=1, occurred_at=_TS, override_records=[override]  # type: ignore[arg-type]
    )

    by_check = {r.check_id: r for r in records}
    assert by_check["artifact.protocol"].outcome is CheckOutcome.OVERRIDDEN
    assert by_check["artifact.protocol"].override_id == "ovr-001"
    # Non-overridden check remains clean
    assert by_check["branch.story"].outcome is CheckOutcome.CLEAN
    assert by_check["branch.story"].override_id is None


def test_override_correlation_via_override_id() -> None:
    """override_id is correctly propagated onto the overridden row."""
    flow = _FakeFlow()
    result = _layer_result(
        [_finding("qa_review")],
        executed_check_ids=["qa_review"],
    )
    override = _FakeOverride(override_id="ovr-xyz", check_id="qa_review")

    records = build_check_outcomes(
        flow, result, attempt_no=2, occurred_at=_TS, override_records=[override]  # type: ignore[arg-type]
    )

    assert len(records) == 1
    assert records[0].outcome is CheckOutcome.OVERRIDDEN
    assert records[0].override_id == "ovr-xyz"


def test_override_without_check_id_does_not_match() -> None:
    """An OverrideRecord with check_id=None does not cause overridden outcome."""
    flow = _FakeFlow()
    result = _layer_result(
        [],
        executed_check_ids=["impl_fidelity"],
    )
    override = _FakeOverride(override_id="ovr-002", check_id=None)

    records = build_check_outcomes(
        flow, result, attempt_no=1, occurred_at=_TS, override_records=[override]  # type: ignore[arg-type]
    )

    assert records[0].outcome is CheckOutcome.CLEAN
    assert records[0].override_id is None


# ---------------------------------------------------------------------------
# Tests: invariants and fail-closed
# ---------------------------------------------------------------------------


def test_blank_check_id_in_executed_raises() -> None:
    """Blank or whitespace check_id in executed_check_ids raises ValueError (fail-closed).

    AG3-108 ERROR 5 / FK-69 §69.11 rule 6: a blank check_id is corrupt input.
    Silent skipping is wrong — raise so callers can fix the upstream bug.
    """
    flow = _FakeFlow()

    for bad_id in ("", "  "):
        result = _layer_result(
            [],
            executed_check_ids=["valid.check", bad_id],
        )
        with pytest.raises(ValueError, match="blank or whitespace"):
            build_check_outcomes(flow, result, attempt_no=1, occurred_at=_TS)


def test_all_emitted_rows_have_nonempty_check_id() -> None:
    """Invariant: every emitted row has a non-empty check_id."""
    flow = _FakeFlow()
    result = _layer_result(
        [_finding("c1"), _finding("c2")],
        executed_check_ids=["c1", "c2", "c3"],
    )

    records = build_check_outcomes(flow, result, attempt_no=1, occurred_at=_TS)

    for rec in records:
        assert rec.check_id, f"Empty check_id in record: {rec!r}"


def test_fail_closed_empty_project_key() -> None:
    """Missing project_key raises ValueError (FK-69 §69.15.6 rule 7)."""
    flow = _FakeFlow(project_key="")
    result = _layer_result([], executed_check_ids=["c1"])

    with pytest.raises(ValueError, match="project_key"):
        build_check_outcomes(flow, result, attempt_no=1)


# ---------------------------------------------------------------------------
# Tests: fallback when executed_check_ids absent from metadata
# ---------------------------------------------------------------------------


def test_fallback_without_executed_check_ids_metadata() -> None:
    """When metadata has no executed_check_ids, derive check_ids from findings."""
    flow = _FakeFlow()
    result = _layer_result(
        [_finding("artifact.protocol"), _finding("branch.story")],
        executed_check_ids=None,  # no metadata key
    )

    records = build_check_outcomes(flow, result, attempt_no=1, occurred_at=_TS)

    # Should emit one triggered row per finding-derived check_id
    check_ids = {r.check_id for r in records}
    assert "artifact.protocol" in check_ids
    assert "branch.story" in check_ids
    for rec in records:
        assert rec.outcome is CheckOutcome.TRIGGERED


def test_fallback_no_findings_no_metadata_emits_empty() -> None:
    """No findings + no metadata -> no rows emitted (nothing to derive)."""
    flow = _FakeFlow()
    result = _layer_result([], executed_check_ids=None)

    records = build_check_outcomes(flow, result, attempt_no=1, occurred_at=_TS)

    assert records == []


# ---------------------------------------------------------------------------
# Tests: default timestamp
# ---------------------------------------------------------------------------


def test_default_occurred_at_is_utc() -> None:
    """When occurred_at=None the emitted rows have UTC-aware timestamp."""
    flow = _FakeFlow()
    result = _layer_result([], executed_check_ids=["c1"])

    before = datetime.now(UTC)
    records = build_check_outcomes(flow, result, attempt_no=1)
    after = datetime.now(UTC)

    assert len(records) == 1
    ts = records[0].occurred_at
    assert ts.tzinfo is not None
    assert before <= ts <= after


# ---------------------------------------------------------------------------
# Tests: CheckOutcomeEmitter (wrapper)
# ---------------------------------------------------------------------------


def test_check_outcome_emitter_returns_records() -> None:
    """CheckOutcomeEmitter.emit returns the same records as build_check_outcomes."""
    flow = _FakeFlow()
    result = _layer_result(
        [_finding("impl_fidelity")],
        executed_check_ids=["impl_fidelity", "ac_fulfilled"],
    )
    emitter = CheckOutcomeEmitter()

    records = emitter.emit(flow, result, attempt_no=1, occurred_at=_TS)  # type: ignore[arg-type]

    assert len(records) == 2
    by_check = {r.check_id: r for r in records}
    assert by_check["impl_fidelity"].outcome is CheckOutcome.TRIGGERED
    assert by_check["ac_fulfilled"].outcome is CheckOutcome.CLEAN


def test_check_outcome_emitter_calls_write_projection() -> None:
    """CheckOutcomeEmitter.emit calls write_projection on the accessor."""
    flow = _FakeFlow()
    result = _layer_result(
        [],
        executed_check_ids=["c1", "c2"],
    )

    calls: list[tuple[object, object]] = []

    class _FakeAccessor:
        def write_projection(self, kind: object, record: object) -> None:
            calls.append((kind, record))

    emitter = CheckOutcomeEmitter()
    emitter.emit(
        flow,  # type: ignore[arg-type]
        result,
        attempt_no=1,
        occurred_at=_TS,
        projection_accessor=_FakeAccessor(),
    )

    assert len(calls) == 2


def test_check_outcome_emitter_no_accessor_no_writes() -> None:
    """CheckOutcomeEmitter.emit with projection_accessor=None returns records only."""
    flow = _FakeFlow()
    result = _layer_result([], executed_check_ids=["c1"])
    emitter = CheckOutcomeEmitter()

    records = emitter.emit(flow, result, attempt_no=1, projection_accessor=None)  # type: ignore[arg-type]

    assert len(records) == 1


# ---------------------------------------------------------------------------
# Tests: origin_check_ref -> check_proposal_ref echo (FK-33 §33.2.1 /
#        FK-69 §69.15.6 rule 4, AG3-078)
# ---------------------------------------------------------------------------


def test_origin_check_ref_echoed_into_check_proposal_ref() -> None:
    """A StageDefinition with origin_check_ref=CHK-NNNN produces rows with
    check_proposal_ref=CHK-NNNN (FK-33 §33.2.1 / FK-69 §69.15.6 rule 4).

    verify-system echoes origin_check_ref verbatim; no FC interpretation.
    """
    from agentkit.verify_system.check_outcome_emitter import build_check_outcomes

    flow = _FakeFlow()
    result = _layer_result(
        [_finding("fc.mycheck")],
        executed_check_ids=["fc.mycheck", "fc.other"],
    )

    records = build_check_outcomes(
        flow,
        result,
        attempt_no=1,
        occurred_at=_TS,
        origin_check_ref="CHK-0042",
    )

    assert len(records) == 2
    for rec in records:
        assert rec.check_proposal_ref == "CHK-0042", (
            f"Expected check_proposal_ref='CHK-0042'; got {rec.check_proposal_ref!r}"
        )


def test_native_stage_produces_null_check_proposal_ref() -> None:
    """A native stage (origin_check_ref=None) produces check_proposal_ref=NULL.

    FK-33 §33.2.1: origin_check_ref is None for native checks (not FC-derived).
    """
    from agentkit.verify_system.check_outcome_emitter import build_check_outcomes

    flow = _FakeFlow()
    result = _layer_result(
        [],
        executed_check_ids=["artifact.protocol", "branch.story"],
    )

    records = build_check_outcomes(
        flow,
        result,
        attempt_no=1,
        occurred_at=_TS,
        origin_check_ref=None,
    )

    assert len(records) == 2
    for rec in records:
        assert rec.check_proposal_ref is None, (
            f"Expected check_proposal_ref=None for native stage; got {rec.check_proposal_ref!r}"
        )


def test_emitter_origin_check_ref_propagated_via_emit() -> None:
    """CheckOutcomeEmitter.emit propagates origin_check_ref to check_proposal_ref."""
    flow = _FakeFlow()
    result = _layer_result([], executed_check_ids=["fc.structural"])
    emitter = CheckOutcomeEmitter()

    records = emitter.emit(
        flow,  # type: ignore[arg-type]
        result,
        attempt_no=1,
        occurred_at=_TS,
        origin_check_ref="CHK-0007",
    )

    assert len(records) == 1
    assert records[0].check_proposal_ref == "CHK-0007"
