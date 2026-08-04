"""Unit tests for CheckOutcomeEmitter and build_check_outcomes (AG3-108, FK-69 §69.15).

Covers:
- Emission for each outcome: triggered / clean / overridden
- Clean/PASS checks are persisted (not discarded)
- Override -> check_id correlation
- Blank/whitespace check_id in executed_check_ids raises ValueError (fail-closed)
- Missing project_key raises ValueError (fail-closed)
- Missing or malformed executed_check_ids fails closed
- Missing per-check origin mapping fails closed
- Registry-owned Result-name to Stage-ID persistence
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

import pytest

from agentkit.backend.verify_system.check_outcome_emitter import (
    CheckOutcomeEmitter,
    build_check_outcomes,
)
from agentkit.backend.verify_system.protocols import Finding, LayerResult, Severity, TrustClass
from agentkit.backend.verify_system.stage_registry.records import CheckOutcome
from agentkit.backend.verify_system.stage_registry.registry import StageRegistry

if TYPE_CHECKING:
    from agentkit.backend.phase_state_store.models import FlowExecution, OverrideRecord

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
_STAGE_REGISTRY = StageRegistry.result_catalog_only()


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


def _origin_refs(result: LayerResult) -> dict[str, str | None]:
    """Build explicit native-check provenance for a unit-test result."""
    raw_ids = result.metadata["executed_check_ids"]
    assert isinstance(raw_ids, (list, tuple))
    check_ids = [str(check_id) for check_id in raw_ids]
    return {check_id: None for check_id in check_ids}


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

    records = build_check_outcomes(
        flow,
        result,
        attempt_no=1,
        occurred_at=_TS,
        check_origin_refs=_origin_refs(result),
        stage_registry=_STAGE_REGISTRY,
    )

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

    records = build_check_outcomes(
        flow,
        result,
        attempt_no=1,
        occurred_at=_TS,
        check_origin_refs=_origin_refs(result),
        stage_registry=_STAGE_REGISTRY,
    )

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

    records = build_check_outcomes(
        flow,
        result,
        attempt_no=1,
        occurred_at=_TS,
        check_origin_refs=_origin_refs(result),
        stage_registry=_STAGE_REGISTRY,
    )

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
        flow,
        result,
        attempt_no=1,
        occurred_at=_TS,
        override_records=[cast("OverrideRecord", override)],
        check_origin_refs=_origin_refs(result),
        stage_registry=_STAGE_REGISTRY,
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
        flow,
        result,
        attempt_no=2,
        occurred_at=_TS,
        override_records=[cast("OverrideRecord", override)],
        check_origin_refs=_origin_refs(result),
        stage_registry=_STAGE_REGISTRY,
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
        flow,
        result,
        attempt_no=1,
        occurred_at=_TS,
        override_records=[cast("OverrideRecord", override)],
        check_origin_refs=_origin_refs(result),
        stage_registry=_STAGE_REGISTRY,
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
            build_check_outcomes(
                flow,
                result,
                attempt_no=1,
                occurred_at=_TS,
                check_origin_refs=_origin_refs(result),
                stage_registry=_STAGE_REGISTRY,
            )


def test_all_emitted_rows_have_nonempty_check_id() -> None:
    """Invariant: every emitted row has a non-empty check_id."""
    flow = _FakeFlow()
    result = _layer_result(
        [_finding("c1"), _finding("c2")],
        executed_check_ids=["c1", "c2", "c3"],
    )

    records = build_check_outcomes(
        flow,
        result,
        attempt_no=1,
        occurred_at=_TS,
        check_origin_refs=_origin_refs(result),
        stage_registry=_STAGE_REGISTRY,
    )

    for rec in records:
        assert rec.check_id, f"Empty check_id in record: {rec!r}"


def test_fail_closed_empty_project_key() -> None:
    """Missing project_key raises ValueError (FK-69 §69.15.6 rule 7)."""
    flow = _FakeFlow(project_key="")
    result = _layer_result([], executed_check_ids=["c1"])

    with pytest.raises(ValueError, match="project_key"):
        build_check_outcomes(
            flow,
            result,
            attempt_no=1,
            check_origin_refs=_origin_refs(result),
            stage_registry=_STAGE_REGISTRY,
        )


# ---------------------------------------------------------------------------
# Tests: required executed_check_ids protocol
# ---------------------------------------------------------------------------


def test_missing_executed_check_ids_fails_closed_with_named_reason() -> None:
    """Findings cannot substitute for the complete execution protocol."""
    flow = _FakeFlow()
    result = _layer_result(
        [_finding("artifact.protocol"), _finding("branch.story")],
        executed_check_ids=None,
    )

    with pytest.raises(ValueError, match="executed_check_ids.*required"):
        build_check_outcomes(
            flow,
            result,
            attempt_no=1,
            occurred_at=_TS,
            check_origin_refs={
                "artifact.protocol": None,
                "branch.story": None,
            },
            stage_registry=_STAGE_REGISTRY,
        )


@pytest.mark.parametrize(
    "malformed_ids",
    ["artifact.protocol", {"artifact.protocol": None}, ["artifact.protocol", 7]],
)
def test_malformed_executed_check_ids_fails_closed_with_named_reason(
    malformed_ids: object,
) -> None:
    """The execution protocol accepts only a list or tuple of strings."""
    flow = _FakeFlow()
    result = LayerResult(
        layer="structural",
        passed=True,
        findings=(),
        metadata={"executed_check_ids": malformed_ids},
    )

    with pytest.raises(ValueError, match="list or tuple of strings"):
        build_check_outcomes(
            flow,
            result,
            attempt_no=1,
            occurred_at=_TS,
            check_origin_refs={"artifact.protocol": None},
            stage_registry=_STAGE_REGISTRY,
        )


def test_finding_check_missing_from_execution_protocol_fails_closed() -> None:
    """A finding cannot exist outside the complete executed-check protocol."""
    flow = _FakeFlow()
    result = _layer_result(
        [_finding("artifact.protocol")],
        executed_check_ids=[],
    )

    with pytest.raises(ValueError, match="findings reference.*artifact.protocol"):
        build_check_outcomes(
            flow,
            result,
            attempt_no=1,
            occurred_at=_TS,
            check_origin_refs={},
            stage_registry=_STAGE_REGISTRY,
        )


# ---------------------------------------------------------------------------
# Tests: default timestamp
# ---------------------------------------------------------------------------


def test_default_occurred_at_is_utc() -> None:
    """When occurred_at=None the emitted rows have UTC-aware timestamp."""
    flow = _FakeFlow()
    result = _layer_result([], executed_check_ids=["c1"])

    before = datetime.now(UTC)
    records = build_check_outcomes(
        flow,
        result,
        attempt_no=1,
        check_origin_refs=_origin_refs(result),
        stage_registry=_STAGE_REGISTRY,
    )
    after = datetime.now(UTC)

    assert len(records) == 1
    ts = records[0].occurred_at
    assert ts.tzinfo is not None
    assert before <= ts <= after


# ---------------------------------------------------------------------------
# Tests: CheckOutcomeEmitter (wrapper)
# ---------------------------------------------------------------------------


def test_check_outcome_emitter_returns_records() -> None:
    """CheckOutcomeEmitter.build returns the same records as the pure builder."""
    flow = _FakeFlow()
    result = _layer_result(
        [_finding("impl_fidelity")],
        executed_check_ids=["impl_fidelity", "ac_fulfilled"],
    )
    emitter = CheckOutcomeEmitter()

    records = emitter.build(
        cast("FlowExecution", flow),
        result,
        attempt_no=1,
        occurred_at=_TS,
        check_origin_refs=_origin_refs(result),
        stage_registry=_STAGE_REGISTRY,
    )

    assert len(records) == 2
    by_check = {r.check_id: r for r in records}
    assert by_check["impl_fidelity"].outcome is CheckOutcome.TRIGGERED
    assert by_check["ac_fulfilled"].outcome is CheckOutcome.CLEAN


# ---------------------------------------------------------------------------
# Tests: origin_check_ref -> check_proposal_ref echo (FK-33 §33.2.1 /
#        FK-69 §69.15.6 rule 4, AG3-078)
# ---------------------------------------------------------------------------


def test_per_check_origin_refs_are_echoed_without_layer_wide_fallback() -> None:
    """Each check receives only its exact registry-derived provenance."""
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
        check_origin_refs={"fc.mycheck": "CHK-0042", "fc.other": "CHK-0043"},
        stage_registry=_STAGE_REGISTRY,
    )

    assert len(records) == 2
    by_check = {record.check_id: record for record in records}
    assert by_check["fc.mycheck"].check_proposal_ref == "CHK-0042"
    assert by_check["fc.other"].check_proposal_ref == "CHK-0043"


def test_native_stage_produces_null_check_proposal_ref() -> None:
    """A native stage (origin_check_ref=None) produces check_proposal_ref=NULL.

    FK-33 §33.2.1: origin_check_ref is None for native checks (not FC-derived).
    """
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
        check_origin_refs={"artifact.protocol": None, "branch.story": None},
        stage_registry=_STAGE_REGISTRY,
    )

    assert len(records) == 2
    for rec in records:
        assert rec.check_proposal_ref is None, (
            f"Expected check_proposal_ref=None for native stage; got {rec.check_proposal_ref!r}"
        )


def test_emitter_propagates_precise_check_origin_ref() -> None:
    """CheckOutcomeEmitter propagates the per-check registry origin."""
    flow = _FakeFlow()
    result = _layer_result([], executed_check_ids=["fc.structural"])
    emitter = CheckOutcomeEmitter()

    records = emitter.build(
        cast("FlowExecution", flow),
        result,
        attempt_no=1,
        occurred_at=_TS,
        check_origin_refs={"fc.structural": "CHK-0007"},
        stage_registry=_STAGE_REGISTRY,
    )

    assert len(records) == 1
    assert records[0].check_proposal_ref == "CHK-0007"


def test_adversarial_target_provenance_requires_canonical_source_evidence() -> None:
    """A dotted target name alone cannot invent its check provenance."""
    flow = _FakeFlow()
    source = LayerResult(
        layer="qa_review",
        passed=False,
        findings=(
            Finding(
                layer="qa_review",
                check="ac_fulfilled",
                severity=Severity.BLOCKING,
                message="acceptance criterion not fulfilled",
                trust_class=TrustClass.VERIFIED_LLM,
            ),
        ),
        metadata={"executed_check_ids": ("ac_fulfilled",)},
    )
    target_id = "P3-INV-6"
    adversarial = LayerResult(
        layer="adversarial",
        passed=False,
        metadata={
            "executed_check_ids": ("adversarial_runtime", target_id),
            "adversarial_target_sources": (
                {
                    "target_id": target_id,
                    "source_result_name": "qa_review",
                    "source_check_id": "ac_fulfilled",
                    "source_artifact_record_key": "qa-review-envelope",
                    "source_finding_index": 0,
                },
            ),
        },
    )

    records = CheckOutcomeEmitter().build_batch(
        cast("FlowExecution", flow),
        (source, adversarial),
        attempt_no=1,
        stage_registry=StageRegistry(),
    )

    target_record = next(record for record in records if record.check_id == target_id)
    assert target_record.check_proposal_ref is None


def test_adversarial_target_provenance_rejects_missing_source_artifact() -> None:
    """Typed metadata cannot omit the canonical source-result identity."""
    flow = _FakeFlow()
    source = LayerResult(
        layer="qa_review",
        passed=True,
        metadata={"executed_check_ids": ("scope_compliance",)},
    )
    target_id = "qa_review.ac_fulfilled"
    adversarial = LayerResult(
        layer="adversarial",
        passed=False,
        metadata={
            "executed_check_ids": ("adversarial_runtime", target_id),
            "adversarial_target_sources": (
                {
                    "target_id": target_id,
                    "source_result_name": "qa_review",
                    "source_check_id": "ac_fulfilled",
                    "source_artifact_record_key": "",
                    "source_finding_index": 0,
                },
            ),
        },
    )

    with pytest.raises(ValueError, match="must not be empty"):
        CheckOutcomeEmitter().build_batch(
            cast("FlowExecution", flow),
            (source, adversarial),
            attempt_no=1,
            stage_registry=StageRegistry(),
        )


def test_missing_check_origin_refs_fails_closed_with_named_reason() -> None:
    """AC3: absent precise provenance never falls back to a layer-wide value."""
    flow = _FakeFlow()
    result = _layer_result([], executed_check_ids=["artifact.protocol"])

    with pytest.raises(ValueError, match="check_origin_refs is required"):
        build_check_outcomes(
            flow,
            result,
            attempt_no=1,
            check_origin_refs=None,
            stage_registry=_STAGE_REGISTRY,
        )


def test_missing_check_origin_ref_member_fails_closed_with_named_reason() -> None:
    """Absent membership is not equivalent to explicit native provenance."""
    flow = _FakeFlow()
    result = _layer_result([], executed_check_ids=["artifact.protocol"])

    with pytest.raises(ValueError, match="no entry.*artifact.protocol"):
        build_check_outcomes(
            flow,
            result,
            attempt_no=1,
            check_origin_refs={},
            stage_registry=_STAGE_REGISTRY,
        )


def test_doc_fidelity_outcome_uses_canonical_stage_id() -> None:
    """The registry maps the evaluator role to its canonical persisted stage."""
    flow = _FakeFlow()
    result = _layer_result(
        [],
        executed_check_ids=["impl_fidelity"],
        layer="doc_fidelity",
    )

    records = build_check_outcomes(
        flow,
        result,
        attempt_no=1,
        check_origin_refs={"impl_fidelity": None},
        stage_registry=_STAGE_REGISTRY,
    )

    assert records[0].stage_id == "doc_fidelity_impl"
