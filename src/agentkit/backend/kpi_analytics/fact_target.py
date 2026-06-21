"""Typed fact-column mapping for the KPI catalog (FK-61 §61.2–§61.11, FK-62 §62.2).

Each active KPI maps to one or more ``FactTarget`` entries, where each
``FactTarget`` pairs a fact table with a non-empty frozenset of column names.
Most KPIs have a single target; KPIs whose raw data spans more than one fact
table (e.g. ``execution_vs_exploration_ratio``) carry multiple ``FactTarget``
entries in their tuple.

``KPI_FACT_TARGETS`` maps each active KPI id to a tuple of ``FactTarget``
values (always at least one entry) so the fail-closed contract test (AC3)
can verify every (table, column) pair against the FK-62 Pydantic records.

``FactTable`` names the five analytics fact tables; ``FactTarget`` pairs one
table with its column set.

Design rationale for choosing ``fact_store/models.py`` as the fail-closed
resolution source (AC3): the Pydantic record models carry the full FK-62
§62.2 column set (AG3-117 reconciliation) as Python field names.  Introspecting
``model_fields`` at test time gives a deterministic, type-checked column list
without parsing SQL or migration files — the only source that is both
machine-readable and authoritative for the physical column identifiers.

ARCH-55: all identifiers are English.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class FactTable(StrEnum):
    """Analytics fact table identifiers (FK-62 §62.2.1–§62.2.5)."""

    FACT_STORY = "fact_story"
    FACT_GUARD_PERIOD = "fact_guard_period"
    FACT_POOL_PERIOD = "fact_pool_period"
    FACT_PIPELINE_PERIOD = "fact_pipeline_period"
    FACT_CORPUS_PERIOD = "fact_corpus_period"


@dataclass(frozen=True)
class FactTarget:
    """Typed binding of a KPI to one fact table and its column(s).

    A KPI that spans a single fact table uses exactly one ``FactTarget``.
    A KPI whose source data spans multiple fact tables (e.g.
    ``execution_vs_exploration_ratio``: raw ``fact_story.pipeline_mode``
    aggregated into ``fact_pipeline_period.execution_count /
    exploration_count``) is represented as a *tuple* of ``FactTarget``
    values in ``KPI_FACT_TARGETS`` — one entry per table.

    Attributes:
        table: The fact table that stores this KPI's data.
        columns: The non-empty set of column names within ``table`` that
            carry this KPI's data.  A KPI that spans multiple columns
            within one table (e.g. ``phase_time_distribution`` → five
            phase columns) lists all of them here so the fail-closed
            contract test can verify each one against the FK-62 Pydantic
            record.
    """

    table: FactTable
    columns: frozenset[str]


def _t(table: FactTable, *columns: str) -> FactTarget:
    """Shorthand constructor: ``_t(FACT_STORY, "qa_round_count")``."""
    if not columns:
        raise ValueError("FactTarget requires at least one column name")
    return FactTarget(table=table, columns=frozenset(columns))


_S = FactTable.FACT_STORY
_G = FactTable.FACT_GUARD_PERIOD
_P = FactTable.FACT_POOL_PERIOD
_PP = FactTable.FACT_PIPELINE_PERIOD
_C = FactTable.FACT_CORPUS_PERIOD


def _build_kpi_fact_targets() -> dict[str, tuple[FactTarget, ...]]:
    """Build and return the canonical KPI → fact-column mapping.

    Called exactly once at module load to populate ``KPI_FACT_TARGETS``.
    Wrapping the large literal in a function keeps module-level LOC within
    the Sonar PY_MODULE_TOP_LEVEL_MAX_LOC_100 limit.

    Mapping rationale (FK-61 §61.2–§61.11, FK-62 §62.2):
    - Each value is a tuple of one or more FactTarget entries.
    - Most KPIs have exactly one entry (single fact table).
    - Multi-table KPIs have one entry per table.
    - ``prompt_integrity_violation_by_stage`` targets FK-62 column names
      WITHOUT the ``_count`` suffix (FK-62 §62.2.2 is authoritative).
      FK-61 §61.4.2 names with ``_count`` suffix are a documentation drift;
      this is the sole known FK-61↔FK-62 divergence (story.md §2.1.2).
    """
    return {
        # -----------------------------------------------------------------------
        # Domain 1 — Story Sizing (7 AKTIV)
        # -----------------------------------------------------------------------
        "compaction_count_per_story": (_t(_S, "compaction_count"),),
        "qa_round_count": (_t(_S, "qa_round_count"),),
        "processing_time_by_type_and_size": (_t(_S, "processing_time_ms", "story_type", "story_size"),),
        "feedback_loop_convergence": (_t(_S, "feedback_converged"),),
        # FK-61 §61.2.2: raw source fact_story.pipeline_mode; aggregated into
        # fact_pipeline_period.execution_count and fact_pipeline_period.exploration_count.
        # Both fact tables are represented as separate FactTarget entries.
        "execution_vs_exploration_ratio": (
            _t(_S, "pipeline_mode"),
            _t(_PP, "execution_count", "exploration_count"),
        ),
        "blocked_ac_distribution": (_t(_S, "blocked_ac_count", "blocked_ac_detail_json"),),
        "policy_required_stage_miss_rate": (
            _t(_PP, "stage_miss_count", "stage_miss_detail_json"),
        ),
        # -----------------------------------------------------------------------
        # Domain 2 — LLM Selection (5 AKTIV)
        # -----------------------------------------------------------------------
        "llm_response_time_p50": (_t(_P, "response_time_p50_ms"),),
        "llm_verdict_adoption_rate": (_t(_P, "verdict_adopted_count", "verdict_total_count"),),
        "llm_finding_precision": (
            _t(_P, "finding_true_positive_count", "finding_false_positive_count"),
        ),
        "llm_call_count_per_story": (_t(_S, "llm_call_count"),),
        "quorum_trigger_rate": (_t(_P, "quorum_triggered_count"),),
        # -----------------------------------------------------------------------
        # Domain 3 — Governance (7 AKTIV)
        # -----------------------------------------------------------------------
        "guard_violation_count_by_type": (_t(_G, "violation_count"),),
        "guard_violation_rate_by_guard": (_t(_G, "invocation_count", "violation_rate"),),
        # FK-62 §62.2.2 authoritative (no _count suffix); FK-61 §61.4.2 drift documented in story.md §2.1.2
        "prompt_integrity_violation_by_stage": (
            _t(
                _G,
                "violation_stage_escape",
                "violation_stage_schema",
                "violation_stage_template",
            ),
        ),
        "governance_escape_detection_count": (_t(_G, "escape_detection_count"),),
        "orchestrator_governance_violation_count": (_t(_G, "violation_count"),),
        "impact_violation_rate": (_t(_PP, "impact_violation_count", "impact_check_count"),),
        "integrity_gate_block_rate": (
            _t(_PP, "integrity_gate_block_count", "integrity_gate_total_count"),
        ),
        # -----------------------------------------------------------------------
        # Domain 4 — Doc Fidelity (1 AKTIV)
        # -----------------------------------------------------------------------
        "doc_fidelity_conflict_rate_by_level": (
            _t(_PP, "doc_fidelity_conflict_by_level_json"),
        ),
        # -----------------------------------------------------------------------
        # Domain 5 — QA Effectiveness (7 AKTIV)
        # -----------------------------------------------------------------------
        "first_pass_success_rate": (_t(_PP, "first_pass_count", "story_count"),),
        "finding_survival_rate": (
            _t(_PP, "finding_survival_count", "finding_total_count"),
        ),
        "check_effectiveness_by_id": (_t(_PP, "effective_check_ids_json"),),
        "adversarial_hit_rate": (_t(_S, "adversarial_hit_rate"),),
        "adversarial_findings_count": (_t(_S, "adversarial_findings_count"),),
        "adversarial_tests_created_count": (_t(_S, "adversarial_tests_created"),),
        "finding_resolution_quality": (
            _t(
                _S,
                "findings_fully_resolved",
                "findings_partially_resolved",
                "findings_not_resolved",
            ),
        ),
        # -----------------------------------------------------------------------
        # Domain 6 — Review Quality (1 AKTIV)
        # -----------------------------------------------------------------------
        "review_template_effectiveness": (_t(_P, "template_finding_rate_json"),),
        # -----------------------------------------------------------------------
        # Domain 7 — VectorDB (2 AKTIV)
        # -----------------------------------------------------------------------
        "vectordb_similarity_threshold_calibration": (
            _t(_PP, "vectordb_total_hits", "vectordb_above_threshold", "vectordb_classified_conflict"),
        ),
        "vectordb_duplicate_detection_rate": (_t(_PP, "vectordb_duplicate_detected"),),
        # -----------------------------------------------------------------------
        # Domain 8 — ARE Integration (2 AKTIV)
        # -----------------------------------------------------------------------
        "are_gate_result": (_t(_S, "are_gate_passed"),),
        "are_evidence_coverage_rate": (
            _t(_S, "are_total_requirements", "are_covered_requirements"),
        ),
        # -----------------------------------------------------------------------
        # Domain 9 — Failure Corpus (2 AKTIV)
        # -----------------------------------------------------------------------
        "incident_volume_per_month": (_t(_C, "new_incident_count"),),
        "pattern_to_check_conversion_rate": (
            _t(_C, "patterns_with_active_check", "patterns_total_count"),
        ),
        # -----------------------------------------------------------------------
        # Domain 10 — Process Efficiency (6 AKTIV)
        # -----------------------------------------------------------------------
        "phase_time_distribution": (
            _t(
                _S,
                "phase_setup_ms",
                "phase_exploration_ms",
                "phase_implementation_ms",
                "phase_verify_ms",
                "phase_closure_ms",
            ),
        ),
        "story_predictability": (_t(_PP, "processing_time_variance_ms2"),),
        "processing_time_trend": (_t(_PP, "processing_time_avg_ms"),),
        "qa_round_trend": (_t(_PP, "qa_round_avg"),),
        "files_changed_per_story": (_t(_S, "files_changed"),),
        "increment_count_per_story": (_t(_S, "increment_count"),),
    }


KPI_FACT_TARGETS: dict[str, tuple[FactTarget, ...]] = _build_kpi_fact_targets()

def resolve_kpi_fact_columns(
    kpi_id: str,
    table_to_fields: dict[FactTable, frozenset[str]],
) -> list[str]:
    """Return columns from ``KPI_FACT_TARGETS[kpi_id]`` that are absent from the schema.

    Used by the AC3 fail-closed test to assert that every (table, column) pair
    in the mapping resolves to a real FK-62 Pydantic model field.

    Args:
        kpi_id: The KPI identifier to look up in ``KPI_FACT_TARGETS``.
        table_to_fields: Mapping of ``FactTable`` → frozenset of known field names
            (typically built from ``model_fields`` of the five fact Pydantic records).

    Returns:
        A list of ``"<table>.<column>"`` strings for every column that is
        present in the mapping but absent from the provided schema.
        An empty list means all columns resolve successfully.

    Raises:
        KeyError: When ``kpi_id`` is not in ``KPI_FACT_TARGETS``.
    """
    targets = KPI_FACT_TARGETS[kpi_id]
    missing: list[str] = []
    for ft in targets:
        known = table_to_fields.get(ft.table, frozenset())
        for col in ft.columns:
            if col not in known:
                missing.append(f"{ft.table}.{col}")
    return missing


def validate_kpi_definition(
    decision_question: str,
    hook_or_event: str,
) -> list[str]:
    """Validate basic structural invariants of a KPI definition.

    This is the typed callable used by the AC4 negative tests to prove that
    crafted-invalid inputs are detected rather than silently accepted.

    Rules checked (FK-60 §60.2 P1, FK-61 source-owner):
    - ``decision_question`` must be non-empty (FK-60 §60.2 P1).
    - ``hook_or_event`` must be non-empty (FK-61: no KPI without a source).

    Args:
        decision_question: The decision_question field of a KpiDefinition.
        hook_or_event: The collection_point.hook_or_event field.

    Returns:
        A list of human-readable error strings.  An empty list means the
        inputs pass all checks.
    """
    errors: list[str] = []
    if not decision_question.strip():
        errors.append("decision_question must not be empty (FK-60 §60.2 P1)")
    if not hook_or_event.strip():
        errors.append(
            "collection_point.hook_or_event must not be empty (FK-61 source-owner rule)"
        )
    return errors


def validate_class2_or_3_source(
    kpi_id: str,
    hook_or_event: str,
    required_event_fragment: str,
) -> list[str]:
    """Assert a Class-2/3 KPI references its required AG3-081 event/payload.

    Class 2 (new AG3-081 event) and Class 3 (enriched AG3-081 payload) KPIs
    MUST name the owning event or payload field in ``hook_or_event``.  This
    check enforces that constraint so a misconfigured Class-2/3 KPI fails
    loudly.

    Args:
        kpi_id: Identifier of the KPI being validated (used in error messages).
        hook_or_event: The collection_point.hook_or_event value.
        required_event_fragment: The AG3-081 event name or payload path that
            must appear as a substring of ``hook_or_event``.

    Returns:
        A list of error strings; empty means the check passes.
    """
    errors: list[str] = []
    if not hook_or_event.strip():
        errors.append(
            f"KPI {kpi_id!r}: hook_or_event is empty; Class-2/3 KPIs must"
            " reference the owning AG3-081 event/payload"
        )
    elif required_event_fragment not in hook_or_event:
        errors.append(
            f"KPI {kpi_id!r}: hook_or_event {hook_or_event!r} does not contain"
            f" required AG3-081 fragment {required_event_fragment!r}"
        )
    return errors


__all__ = [
    "FactTable",
    "FactTarget",
    "KPI_FACT_TARGETS",
    "resolve_kpi_fact_columns",
    "validate_class2_or_3_source",
    "validate_kpi_definition",
]
