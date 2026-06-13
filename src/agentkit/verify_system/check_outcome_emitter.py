"""Per-check outcome emitter for verify-system (FK-69 §69.15, AG3-108).

This module is the canonical producer of ``qa_check_outcomes`` rows.
verify-system calls :func:`build_check_outcomes` after every QA layer execution
to persist a row for EVERY executed check — not just findings.

Three outcome paths:
- **triggered**: a non-PASS finding exists for this check_id (finding produced).
- **clean**: the check ran and passed with no finding (PASS).
- **overridden**: the check outcome was suppressed by an explicit override.

Schema-Owner: verify-system.
DB-Owner: telemetry-and-events via ProjectionAccessor / FacadeQACheckOutcomesRepository.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from agentkit.verify_system.stage_registry.records import (
    CheckOutcome,
    QACheckOutcomeRecord,
)

if TYPE_CHECKING:
    from agentkit.phase_state_store.models import FlowExecution, OverrideRecord
    from agentkit.verify_system.protocols import LayerResult


__all__ = [
    "CheckOutcomeEmitter",
    "build_check_outcomes",
]


def build_check_outcomes(
    flow: FlowExecution,
    layer_result: LayerResult,
    *,
    attempt_no: int,
    occurred_at: datetime | None = None,
    override_records: list[OverrideRecord] | None = None,
) -> list[QACheckOutcomeRecord]:
    """Build per-check outcome rows from a completed QA layer result.

    Emits exactly one row per executed check_id.  The full set of executed
    check IDs is taken from ``layer_result.metadata["executed_check_ids"]``
    when present; otherwise it is derived as the union of all finding check_ids
    (gives at least the ``triggered`` set, no ``clean`` rows for checks not in
    findings).

    The ``overridden`` outcome is applied when an ``OverrideRecord`` with
    a matching ``check_id`` exists in ``override_records``.  The first
    matching override's ``override_id`` is used for correlation.

    FK-69 §69.15.6 invariant: every emitted row has a non-blank ``check_id``.
    FK-69 §69.15.6 rule 7: ``project_key`` must not be empty (fail-closed).

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

    Returns:
        A list of :class:`~agentkit.verify_system.stage_registry.records.QACheckOutcomeRecord`,
        one per executed check.

    Raises:
        ValueError: If ``flow.project_key`` is empty (FK-69 §69.15.6 rule 7,
            FAIL-CLOSED).
    """
    if not flow.project_key:
        raise ValueError(
            "FlowExecution.project_key must not be empty — "
            "fa-check-outcomes emission requires a valid project_key "
            "(FK-69 §69.15.6 rule 7 fail-closed)"
        )

    ts: datetime = occurred_at if occurred_at is not None else datetime.now(UTC)

    # Build override index: check_id -> first matching OverrideRecord.
    override_index: dict[str, OverrideRecord] = {}
    if override_records:
        for ovr in override_records:
            if ovr.check_id and ovr.check_id not in override_index:
                override_index[ovr.check_id] = ovr

    # Collect executed check IDs from metadata or fall back to finding checks.
    # Do NOT filter blank strings here — the fail-closed check below raises on them.
    raw_executed: object = layer_result.metadata.get("executed_check_ids")
    executed_check_ids: list[str]
    if isinstance(raw_executed, (list, tuple, set, frozenset)):
        executed_check_ids = [str(cid) for cid in raw_executed]
    else:
        # Fall back: derive from findings (covers at least triggered set).
        executed_check_ids = list(
            {f.check for f in layer_result.findings if f.check}
        )

    # Build triggered set: check_ids that produced a finding.
    triggered_check_ids: set[str] = {f.check for f in layer_result.findings if f.check}

    records: list[QACheckOutcomeRecord] = []
    for check_id in executed_check_ids:
        if not check_id or not check_id.strip():
            # FK-69 §69.11 rule 6 / AG3-108 ERROR 5: blank/whitespace-only
            # check_id is corrupt input — fail-closed (raise, do not silently
            # drop the row). The caller must ensure executed_check_ids
            # contains only valid, non-blank identifiers.
            raise ValueError(
                f"blank or whitespace-only check_id in executed_check_ids — "
                f"corrupt input, fail-closed (FK-69 §69.11 rule 6): {check_id!r}"
            )

        if check_id in override_index:
            ovr = override_index[check_id]
            outcome = CheckOutcome.OVERRIDDEN
            override_id: str | None = ovr.override_id
        elif check_id in triggered_check_ids:
            outcome = CheckOutcome.TRIGGERED
            override_id = None
        else:
            outcome = CheckOutcome.CLEAN
            override_id = None

        records.append(
            QACheckOutcomeRecord(
                project_key=flow.project_key,
                story_id=flow.story_id,
                run_id=flow.run_id,
                stage_id=layer_result.layer,
                attempt_no=attempt_no,
                check_id=check_id,
                outcome=outcome,
                occurred_at=ts,
                override_id=override_id,
            )
        )

    return records


class CheckOutcomeEmitter:
    """Stateless helper that builds and persists per-check outcome rows.

    Wraps :func:`build_check_outcomes` and calls
    ``projection_accessor.write_projection`` for each emitted record.

    This class is the verify-system-internal production entry point.
    Tests can call :func:`build_check_outcomes` directly without a
    ``ProjectionAccessor`` dependency.
    """

    def emit(
        self,
        flow: FlowExecution,
        layer_result: LayerResult,
        *,
        attempt_no: int,
        occurred_at: datetime | None = None,
        override_records: list[OverrideRecord] | None = None,
        projection_accessor: Any | None = None,
    ) -> list[QACheckOutcomeRecord]:
        """Build and persist per-check outcome rows for one layer result.

        Args:
            flow: The currently executing ``FlowExecution``.
            layer_result: The completed ``LayerResult``.
            attempt_no: 1-based remediation attempt number.
            occurred_at: Optional explicit UTC timestamp.
            override_records: Optional override records for override correlation.
            projection_accessor: Optional ``ProjectionAccessor`` to persist
                records.  When ``None``, records are returned but not written.
                Typed as ``Any`` to avoid a circular import from verify-system
                -> telemetry; the caller is responsible for passing a valid
                ``ProjectionAccessor`` instance.

        Returns:
            List of :class:`~agentkit.verify_system.stage_registry.records.QACheckOutcomeRecord`
            that were (or would be) persisted.
        """
        from agentkit.telemetry.projection_accessor import ProjectionKind

        records = build_check_outcomes(
            flow,
            layer_result,
            attempt_no=attempt_no,
            occurred_at=occurred_at,
            override_records=override_records,
        )
        if projection_accessor is not None:
            for record in records:
                projection_accessor.write_projection(
                    ProjectionKind.QA_CHECK_OUTCOMES, record
                )
        return records
