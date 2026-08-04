"""Per-check outcome emitter for verify-system (FK-69 §69.15, AG3-108).

This module is the canonical record builder for ``qa_check_outcomes`` rows.
verify-system calls :func:`build_check_outcomes` after every QA layer execution
to prepare a row for EVERY executed check — not just findings. Persistence is
owned exclusively by the joint QA-layer batch.

Three outcome paths:
- **triggered**: a non-PASS finding exists for this check_id (finding produced).
- **clean**: the check ran and passed with no finding (PASS).
- **overridden**: the check outcome was suppressed by an explicit override.

Schema-Owner: verify-system.
DB-Owner: telemetry-and-events via
ProjectionAccessor.record_qa_layer_artifacts.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from agentkit.backend.verify_system.stage_registry.records import (
    CheckOutcome,
    QACheckOutcomeRecord,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from agentkit.backend.phase_state_store.models import FlowExecution, OverrideRecord
    from agentkit.backend.verify_system.protocols import LayerResult
    from agentkit.backend.verify_system.stage_registry.registry import StageRegistry


__all__ = [
    "CheckOutcomeEmitter",
    "build_check_outcomes",
    "validate_qa_layer_artifact_batch",
    "validate_layer_result_execution_protocol",
]


def _build_override_index(
    override_records: list[OverrideRecord] | None,
) -> dict[str, OverrideRecord]:
    """Map ``check_id`` -> the FIRST matching ``OverrideRecord`` (FK-69 §69.15.6)."""
    index: dict[str, OverrideRecord] = {}
    for ovr in override_records or ():
        if ovr.check_id and ovr.check_id not in index:
            index[ovr.check_id] = ovr
    return index


def validate_layer_result_execution_protocol(
    layer_result: LayerResult,
) -> tuple[str, ...]:
    """Validate and return the complete executed-check protocol.

    The producer must supply a sequence of string IDs. Findings cannot recover
    clean checks, so they are never used as an execution-protocol substitute.
    Blank IDs and findings outside the protocol are corrupt input. Repeated IDs
    remain repeated executions in the aggregate count; persistence upserts the
    per-check outcome identity once.
    """
    if "executed_check_ids" not in layer_result.metadata:
        raise ValueError(
            "layer_result.metadata['executed_check_ids'] is required for the "
            "complete QA execution protocol (FK-69 §69.15 fail-closed)"
        )
    raw_executed = layer_result.metadata["executed_check_ids"]
    if not isinstance(raw_executed, (list, tuple)) or any(not isinstance(check_id, str) for check_id in raw_executed):
        raise ValueError(
            "layer_result.metadata['executed_check_ids'] must be a list or tuple of strings (FK-69 §69.15 fail-closed)"
        )
    executed_check_ids = tuple(raw_executed)
    blank_check_ids = [check_id for check_id in executed_check_ids if not check_id.strip()]
    if blank_check_ids:
        raise ValueError(
            f"blank or whitespace-only check_id in executed_check_ids — corrupt input, fail-closed: {blank_check_ids[0]!r}"
        )
    executed_check_id_set = set(executed_check_ids)
    missing_finding_check_ids = sorted(
        {finding.check for finding in layer_result.findings if finding.check and finding.check not in executed_check_id_set}
    )
    if missing_finding_check_ids:
        raise ValueError(
            "layer_result findings reference check_id(s) absent from "
            "metadata['executed_check_ids']: "
            f"{missing_finding_check_ids!r} (FK-69 §69.15 fail-closed)"
        )
    return executed_check_ids


def _classify_check_outcome(
    check_id: str,
    override_index: dict[str, OverrideRecord],
    triggered_check_ids: set[str],
) -> tuple[CheckOutcome, str | None]:
    """Classify one executed check as overridden / triggered / clean.

    Override wins over triggered (an explicitly suppressed check is ``overridden``
    even if it produced a finding); the correlated ``override_id`` is returned.
    """
    if check_id in override_index:
        return CheckOutcome.OVERRIDDEN, override_index[check_id].override_id
    if check_id in triggered_check_ids:
        return CheckOutcome.TRIGGERED, None
    return CheckOutcome.CLEAN, None


def build_check_outcomes(
    flow: FlowExecution,
    layer_result: LayerResult,
    *,
    attempt_no: int,
    occurred_at: datetime | None = None,
    override_records: list[OverrideRecord] | None = None,
    check_origin_refs: Mapping[str, str | None] | None,
    stage_registry: StageRegistry,
) -> list[QACheckOutcomeRecord]:
    """Build per-check outcome rows from a completed QA layer result.

    Emits exactly one row per executed check_id.  The full set of executed
    check IDs is taken exclusively from
    ``layer_result.metadata["executed_check_ids"]``. Missing or malformed
    metadata fails closed because findings only identify triggered checks and
    cannot reconstruct the complete execution protocol.

    The ``overridden`` outcome is applied when an ``OverrideRecord`` with
    a matching ``check_id`` exists in ``override_records``.  The first
    matching override's ``override_id`` is used for correlation.

    FK-69 §69.15.6 invariant: every emitted row has a non-blank ``check_id``.
    FK-69 §69.15.6 rule 7: ``project_key`` must not be empty (fail-closed).

    FK-33 §33.2.1 / FK-69 §69.15.6 rule 4 / AG3-078 ERROR 1:
    ``check_origin_refs`` is the per-check mapping ``check_id -> origin_check_ref``
    (``CHK-NNNN | None``) built from the stage registry. Each row's
    ``check_proposal_ref`` is resolved individually — FC-derived check_ids carry
    their CHK-NNNN, native check_ids get NULL. This is the correct granularity:
    a single layer may contain both FC-derived and native checks.
    ``check_origin_refs`` is mandatory and contains one explicit member for
    every executed check. Registry entries resolve their exact origin; native
    checks are represented by an explicit ``None`` value. A missing mapping or
    member fails closed instead of silently classifying incomplete provenance
    as native.

    Args:
        flow: The currently executing ``FlowExecution`` (provides identity
            fields ``project_key``, ``story_id``, ``run_id``).
        layer_result: The completed ``LayerResult`` from one QA layer run.
        attempt_no: 1-based remediation attempt number.
        occurred_at: UTC timestamp of the check execution.  Defaults to
            ``datetime.now(UTC)`` when ``None``.
        override_records: Optional list of ``OverrideRecord`` objects that
            may suppress individual checks.  A record is correlated when
            ``override_record.check_id`` matches the executed check's
            ``check_id``.  ``None`` / empty list means no overrides.
        check_origin_refs: Required per-check mapping
            ``check_id -> CHK-NNNN | None`` built from the stage registry
            (AG3-078 ERROR 1). Each row's ``check_proposal_ref`` is resolved
            individually (FC-derived -> CHK-NNNN; native -> NULL). The caller
            materializes one explicit member for every executed check from the
            registry origin table and the layer's native-check contract.
        stage_registry: Bound registry that owns Result-name to Stage-ID
            resolution.

    Returns:
        A list of :class:`~agentkit.backend.verify_system.stage_registry.records.QACheckOutcomeRecord`,
        one per executed check.

    Raises:
        ValueError: If ``flow.project_key`` is empty, the execution protocol is
            incomplete, or the per-check origin mapping is incomplete
            (FAIL-CLOSED).
    """
    if not flow.project_key:
        raise ValueError(
            "FlowExecution.project_key must not be empty — "
            "fa-check-outcomes emission requires a valid project_key "
            "(FK-69 §69.15.6 rule 7 fail-closed)"
        )
    if check_origin_refs is None:
        raise ValueError("check_origin_refs is required for precise per-check QA provenance (FK-33 §33.2.1 fail-closed)")

    ts: datetime = occurred_at if occurred_at is not None else datetime.now(UTC)
    override_index = _build_override_index(override_records)
    executed_check_ids = validate_layer_result_execution_protocol(layer_result)
    canonical_stage_id = stage_registry.canonical_stage_id_for_result_name(layer_result.layer)
    # Triggered set: check_ids that produced a finding.
    triggered_check_ids: set[str] = {f.check for f in layer_result.findings if f.check}

    records: list[QACheckOutcomeRecord] = []
    for check_id in executed_check_ids:
        if check_id not in check_origin_refs:
            raise ValueError(
                f"check_origin_refs has no entry for executed check_id {check_id!r} (FK-69 §69.11 rule 10 fail-closed)"
            )
        resolved_origin = check_origin_refs[check_id]

        outcome, override_id = _classify_check_outcome(check_id, override_index, triggered_check_ids)
        records.append(
            QACheckOutcomeRecord(
                project_key=flow.project_key,
                story_id=flow.story_id,
                run_id=flow.run_id,
                stage_id=canonical_stage_id,
                attempt_no=attempt_no,
                check_id=check_id,
                outcome=outcome,
                occurred_at=ts,
                check_proposal_ref=resolved_origin,
                override_id=override_id,
            )
        )

    return records


def validate_qa_layer_artifact_batch(
    layer_results: tuple[LayerResult, ...],
    check_outcomes: tuple[QACheckOutcomeRecord, ...],
    *,
    stage_registry: StageRegistry,
    attempt_no: int,
) -> None:
    """Validate the complete Stage/Finding/Outcome batch before persistence.

    Every executed check must have an outcome under the same canonical stage,
    and no outcome may exist without a corresponding executed check. This is
    the verify-system precondition for the single atomic FK-69 batch writer.
    """
    expected_outcomes: set[tuple[str, str]] = set()
    finding_checks: set[tuple[str, str]] = set()
    for layer_result in layer_results:
        stage_id = stage_registry.canonical_stage_id_for_result_name(
            layer_result.layer
        )
        executed_check_ids = validate_layer_result_execution_protocol(layer_result)
        expected_outcomes.update(
            (stage_id, check_id) for check_id in executed_check_ids
        )
        finding_checks.update(
            (stage_id, finding.check)
            for finding in layer_result.findings
            if finding.check
        )

    actual_outcomes = {
        (record.stage_id, record.check_id) for record in check_outcomes
    }
    if actual_outcomes != expected_outcomes:
        missing = sorted(expected_outcomes - actual_outcomes)
        unexpected = sorted(actual_outcomes - expected_outcomes)
        raise ValueError(
            "QA layer batch outcome protocol mismatch: "
            f"missing={missing!r}, unexpected={unexpected!r}"
        )
    wrong_attempts = sorted(
        {record.attempt_no for record in check_outcomes if record.attempt_no != attempt_no}
    )
    if wrong_attempts:
        raise ValueError(
            f"QA layer batch contains outcome attempts outside attempt {attempt_no}: {wrong_attempts!r}"
        )
    triggered_without_finding = sorted(
        (record.stage_id, record.check_id)
        for record in check_outcomes
        if record.outcome is CheckOutcome.TRIGGERED
        and (record.stage_id, record.check_id) not in finding_checks
    )
    if triggered_without_finding:
        raise ValueError(
            "triggered QA outcomes require a finding in the same atomic batch: "
            f"{triggered_without_finding!r}"
        )
    findings_without_failed_outcome = sorted(
        (record.stage_id, record.check_id)
        for record in check_outcomes
        if (record.stage_id, record.check_id) in finding_checks
        and record.outcome not in {CheckOutcome.TRIGGERED, CheckOutcome.OVERRIDDEN}
    )
    if findings_without_failed_outcome:
        raise ValueError(
            "QA findings require a triggered or overridden outcome in the "
            "same atomic batch: "
            f"{findings_without_failed_outcome!r}"
        )


class CheckOutcomeEmitter:
    """Stateless verify-system builder for per-check outcome records."""

    def build_batch(
        self,
        flow: FlowExecution,
        layer_results: tuple[LayerResult, ...],
        *,
        attempt_no: int,
        override_records: list[OverrideRecord] | None = None,
        stage_registry: StageRegistry,
    ) -> tuple[QACheckOutcomeRecord, ...]:
        """Build the complete outcome record set for one QA-layer batch."""
        records: list[QACheckOutcomeRecord] = []
        for layer_result in layer_results:
            executed_check_ids = validate_layer_result_execution_protocol(
                layer_result
            )
            check_origin_refs = stage_registry.resolve_check_origin_refs(
                list(executed_check_ids)
            )
            records.extend(
                self.build(
                    flow,
                    layer_result,
                    attempt_no=attempt_no,
                    override_records=override_records,
                    check_origin_refs=check_origin_refs,
                    stage_registry=stage_registry,
                )
            )
        return tuple(records)

    def build(
        self,
        flow: FlowExecution,
        layer_result: LayerResult,
        *,
        attempt_no: int,
        occurred_at: datetime | None = None,
        override_records: list[OverrideRecord] | None = None,
        check_origin_refs: Mapping[str, str | None] | None,
        stage_registry: StageRegistry,
    ) -> list[QACheckOutcomeRecord]:
        """Build per-check outcome records for one layer result.

        Args:
            flow: The currently executing ``FlowExecution``.
            layer_result: The completed ``LayerResult``.
            attempt_no: 1-based remediation attempt number.
            occurred_at: Optional explicit UTC timestamp.
            override_records: Optional override records for override correlation.
            check_origin_refs: Required per-check mapping
                ``check_id -> CHK-NNNN | None`` built from the stage registry
                (AG3-078 ERROR 1).
            stage_registry: Bound registry that owns Result-name to Stage-ID
                resolution.

        Returns:
            List of :class:`~agentkit.backend.verify_system.stage_registry.records.QACheckOutcomeRecord`
            prepared for the caller's atomic QA-layer batch.
        """
        return build_check_outcomes(
            flow,
            layer_result,
            attempt_no=attempt_no,
            occurred_at=occurred_at,
            override_records=override_records,
            check_origin_refs=check_origin_refs,
            stage_registry=stage_registry,
        )
