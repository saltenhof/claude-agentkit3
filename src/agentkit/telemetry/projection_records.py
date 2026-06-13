"""Aggregator file: re-exports the FK-69 projection-record classes as a union type.

The schema owner stays the respective BC (verify-system, story-closure, etc.).
This file ONLY defines the union for the ProjectionAccessor.

``StoryMetricsRecord`` (schema owner: story-closure), ``PhaseState`` (schema owner:
``pipeline_engine.phase_executor``, FK-39 §39.7 / AG3-059) and the
``ProjectionRecord`` union are used EXCLUSIVELY for type annotations (no runtime
``isinstance`` / Pydantic field). They are therefore resolved **lazily** through
the respective top-surface (``agentkit.closure`` resp.
``agentkit.pipeline_engine.phase_executor``, AC001-compliant) so telemetry-and-events
does NOT import the story-closure / pipeline-engine package at module init. The
legitimate runtime direction is ``closure -> telemetry`` (FK-29 §29.6, FK-69
§69.8): closure writes via ``Telemetry.write_projection``. Consistent with
``projection_accessor._build_kind_to_record_type`` (same anti-circular-import
pattern).

AG3-081 (AC4): the ``phase_state_projection`` variant of the union references the
**AG3-059-owned** typed ``PhaseState`` record (FK-69 §69.3) instead of
``dict[str, object]``. AG3-081 does NOT define the record type and does NOT build
the write path (write owner stays ``pipeline_engine.PhaseExecutor``, FK-69 §69.4;
the ProjectionAccessor keeps refusing ``PHASE_STATE_PROJECTION`` fail-closed). This
file only migrates the telemetry-side projection union onto the typed record.

Sources:
- FK-69 §69.3 -- table scope
- FK-69 §69.4 -- write ownership (schema owner per table)
- FK-29 §29.6 -- StoryMetric schema owner = story-closure
- FK-39 §39.7 -- PhaseState/PhaseStateCore schema owner = pipeline_engine.phase_executor (AG3-059)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from agentkit.failure_corpus.incident import Incident
from agentkit.verify_system.stage_registry.records import (
    QACheckOutcomeRecord,
    QAFindingRecord,
    QAStageResultRecord,
)

if TYPE_CHECKING:
    from agentkit.closure import StoryMetricsRecord
    from agentkit.pipeline_engine.phase_executor import PhaseState

    # ProjectionRecord: discriminated union over all FK-69 read-model classes.
    # ``PhaseState`` is the phase_state_projection record (FK-69 §69.3, schema
    # owner pipeline_engine.phase_executor / AG3-059); AG3-081 (AC4) migrates the
    # union from ``dict[str, object]`` onto this typed record (it does NOT define
    # it and does NOT build a write path). ``Incident`` is the fc_incidents record
    # (AG3-028 KONFLIKT-2). It lives in the leaf module ``failure_corpus.incident``
    # (which imports only core_types + types, NOT telemetry) -- analogous to
    # ``verify_system.stage_registry.records``.
    # AG3-108: ``QACheckOutcomeRecord`` added (FK-69 §69.15 per-check outcome
    # read model; schema owner verify-system).
    ProjectionRecord = (
        QAStageResultRecord
        | QAFindingRecord
        | QACheckOutcomeRecord
        | StoryMetricsRecord
        | PhaseState
        | Incident
    )

__all__ = [
    "Incident",
    "PhaseState",
    "ProjectionRecord",
    "QACheckOutcomeRecord",
    "QAFindingRecord",
    "QAStageResultRecord",
    "StoryMetricsRecord",
]


def __getattr__(name: str) -> Any:
    """Lazy runtime resolution of the closure-owned names (PEP 562).

    Avoids the telemetry <-> closure import cycle at module init: the
    story-closure package is imported only on the first actual runtime access to
    ``StoryMetricsRecord`` resp. ``ProjectionRecord`` -- by which point
    ``agentkit.closure`` has long been fully loaded.

    Args:
        name: Requested module attribute name.

    Returns:
        The resolved class resp. the union type.

    Raises:
        AttributeError: For all other names.
    """
    if name == "StoryMetricsRecord":
        from agentkit.closure import StoryMetricsRecord

        return StoryMetricsRecord
    if name == "PhaseState":
        # AG3-081 (AC4): the AG3-059-owned typed phase_state_projection record
        # (FK-69 §69.3, FK-39 §39.7). Resolved lazily via the phase_executor
        # top-surface so telemetry does not import pipeline_engine at module init
        # (anti-circular-import; the legitimate runtime direction is
        # pipeline_engine.PhaseExecutor -> phase_state_projection write path,
        # which is NOT this module).
        from agentkit.pipeline_engine.phase_executor import PhaseState

        return PhaseState
    if name == "ProjectionRecord":
        from agentkit.closure import StoryMetricsRecord
        from agentkit.pipeline_engine.phase_executor import PhaseState

        # AG3-028 Codex-r1 WARNING: Incident belongs in the runtime union (not only
        # under TYPE_CHECKING) so isinstance / union checks capture the
        # fc_incidents record at runtime. Incident lives in the leaf module
        # failure_corpus.incident (which imports no telemetry -> no cycle).
        # AG3-081 (AC4): PhaseState is the typed phase_state_projection record
        # (schema owner AG3-059) -- the union is no longer dict[str, object].
        # AG3-108: QACheckOutcomeRecord added (FK-69 §69.15).
        return (
            QAStageResultRecord
            | QAFindingRecord
            | QACheckOutcomeRecord
            | StoryMetricsRecord
            | PhaseState
            | Incident
        )
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
