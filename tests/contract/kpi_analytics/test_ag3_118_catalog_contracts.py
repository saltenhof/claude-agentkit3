"""Contract tests for AG3-118: KPI-Katalog-Population (40 AKTIV-KPIs).

Extends the AG3-038 contract family. Pins:

(a) Exact 40-AKTIV-ID frozenset — compared ID-for-ID, not just count.
(b) Per-KPI field validation against FK-60 §60.4 (non-empty decision_question,
    name, formula_repr; valid granularity/domain; data_available matching [R]/[N]).
(c) Fail-closed: every (table, column) pair in KPI_FACT_TARGETS must resolve to a
    field on the corresponding FK-62 Pydantic record model (FactStory,
    FactGuardPeriod, FactPoolPeriod, FactPipelinePeriod, FactCorpusPeriod).

    Canonical resolution source choice: ``kpi_analytics/fact_store/models.py``
    Pydantic record models are chosen over the SQL schema, migration SQL, or
    ``_fact_sql.py`` column lists because:
    1. ``model_fields`` is machine-readable and deterministic at import time.
    2. The AG3-117 reconciliation (renames, adds, drops, type-changes) is applied
       directly in the models — they are the single typed truth for the physical
       column identifiers (FK-62 §62.2 / AG3-117 design decision).
    3. No file I/O, no SQL parsing, no subprocess: just Python field introspection.

    KPI_FACT_TARGETS maps each KPI id to a *tuple* of FactTarget entries (one per
    fact table).  The AC3 test iterates ALL entries and checks EVERY (table, column)
    pair — a multi-table KPI (e.g. execution_vs_exploration_ratio) is fully covered.

(d) Source-owner class checks per FK-61 §61.2–§61.11 (§2.1.3):
    - Class 2/3 (AG3-081 new event / enriched payload): hook_or_event must not
      be empty and must reference an AG3-081-registered event name.
    - Class 4 (runtime metric/projection): hook_or_event is a read-model reference;
      no AG3-081 event required.  finding_resolution_quality is Class 4 (FK-34
      StructuredEvaluator output, NOT an AG3-081 event — FK-61 §61.6.2).
      llm_finding_precision is Class 4 (FK-61 §61.3.2: RefreshWorker correlation,
      no new event).
    - Class 5 (scratchpad): guard_violation_rate_by_guard's hook_or_event must
      reference the scratchpad, not an event type.
    - Completeness assertion: the union of per-class KPI id sets == the full 40
      frozenset (no KPI omitted from class assignment).
    - Faithful class-pin: ``test_catalog_source_owner_class_matches_test_class_sets``
      derives each KPI's expected class from the per-class frozensets and asserts it
      equals the machine-readable ``source_owner_class`` field on the catalog's
      ``KpiCollectionPoint``.  Catalog-vs-test class drift causes a hard failure.
    - True negative tests: crafted-invalid inputs are fed to the typed validator
      callables; rejection is asserted.

(e) P95 is INVENTAR (absent from catalog) — test belegt the absence.

(f) Canonical wire-key pins (FK-61 §61.12.2):
    integrity_gate_result.blocked_dimensions, are_gate_result.total_requirements,
    are_gate_result.covered_requirements — and their target columns are present in
    the FK-62 Pydantic schema.

(g) llm_response_time_p50 is AKTIV and maps to fact_pool_period.response_time_p50_ms;
    llm_response_time_p95 is INVENTAR and absent.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from agentkit.kpi_analytics.catalog import KpiCatalog, KpiGranularity
from agentkit.kpi_analytics.fact_store.models import (
    FactCorpusPeriod,
    FactGuardPeriod,
    FactPipelinePeriod,
    FactPoolPeriod,
    FactStory,
)
from agentkit.kpi_analytics.fact_target import (
    KPI_FACT_TARGETS,
    FactTable,
    resolve_kpi_fact_columns,
    validate_class2_or_3_source,
    validate_kpi_definition,
)

if TYPE_CHECKING:
    from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def catalog() -> KpiCatalog:
    """Module-scoped KpiCatalog (avoids re-registration overhead per test)."""
    return KpiCatalog()


# ---------------------------------------------------------------------------
# (a) Exact 40-AKTIV-ID frozenset — ID-for-ID comparison
# ---------------------------------------------------------------------------

_EXPECTED_AKTIV_IDS: frozenset[str] = frozenset({
    # Domain 1 — Story Sizing (7)
    "compaction_count_per_story",
    "qa_round_count",
    "processing_time_by_type_and_size",
    "feedback_loop_convergence",
    "execution_vs_exploration_ratio",
    "blocked_ac_distribution",
    "policy_required_stage_miss_rate",
    # Domain 2 — LLM Selection (5)
    "llm_response_time_p50",
    "llm_verdict_adoption_rate",
    "llm_finding_precision",
    "llm_call_count_per_story",
    "quorum_trigger_rate",
    # Domain 3 — Governance (7)
    "guard_violation_count_by_type",
    "guard_violation_rate_by_guard",
    "prompt_integrity_violation_by_stage",
    "governance_escape_detection_count",
    "orchestrator_governance_violation_count",
    "impact_violation_rate",
    "integrity_gate_block_rate",
    # Domain 4 — Doc Fidelity (1)
    "doc_fidelity_conflict_rate_by_level",
    # Domain 5 — QA Effectiveness (7)
    "first_pass_success_rate",
    "finding_survival_rate",
    "check_effectiveness_by_id",
    "adversarial_hit_rate",
    "adversarial_findings_count",
    "adversarial_tests_created_count",
    "finding_resolution_quality",
    # Domain 6 — Review Quality (1)
    "review_template_effectiveness",
    # Domain 7 — VectorDB (2)
    "vectordb_similarity_threshold_calibration",
    "vectordb_duplicate_detection_rate",
    # Domain 8 — ARE Integration (2)
    "are_gate_result",
    "are_evidence_coverage_rate",
    # Domain 9 — Failure Corpus (2)
    "incident_volume_per_month",
    "pattern_to_check_conversion_rate",
    # Domain 10 — Process Efficiency (6)
    "phase_time_distribution",
    "story_predictability",
    "processing_time_trend",
    "qa_round_trend",
    "files_changed_per_story",
    "increment_count_per_story",
})


def test_catalog_registered_ids_exactly_match_fk60_aktiv_frozenset(
    catalog: KpiCatalog,
) -> None:
    """Contract AC1: registered IDs == FK-60 §60.4 AKTIV frozenset (ID-for-ID).

    Counts are not sufficient — this test compares the full set so any
    added, removed, or misspelled ID causes a red test.
    """
    registered = frozenset(d.kpi_id for d in catalog.list_definitions())
    missing = _EXPECTED_AKTIV_IDS - registered
    extra = registered - _EXPECTED_AKTIV_IDS
    assert not missing, f"KPIs expected but not registered: {sorted(missing)}"
    assert not extra, f"KPIs registered but not in FK-60 AKTIV set: {sorted(extra)}"


def test_catalog_count_is_exactly_40(catalog: KpiCatalog) -> None:
    """Contract AC1 (redundant sanity): exactly 40 KPIs registered."""
    assert len(catalog.list_definitions()) == 40


def test_kpi_fact_targets_covers_all_40_aktiv_ids() -> None:
    """Contract: KPI_FACT_TARGETS mapping covers exactly the 40 AKTIV IDs."""
    target_ids = frozenset(KPI_FACT_TARGETS.keys())
    missing = _EXPECTED_AKTIV_IDS - target_ids
    extra = target_ids - _EXPECTED_AKTIV_IDS
    assert not missing, f"KPIs in FK-60 AKTIV but missing from KPI_FACT_TARGETS: {sorted(missing)}"
    assert not extra, f"Extra IDs in KPI_FACT_TARGETS not in FK-60 AKTIV set: {sorted(extra)}"


# ---------------------------------------------------------------------------
# (b) Per-KPI field validation against FK-60 §60.4
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("kpi_id", sorted(_EXPECTED_AKTIV_IDS))
def test_kpi_has_non_empty_decision_question(kpi_id: str, catalog: KpiCatalog) -> None:
    """FK-60 §60.2 P1: every KPI must have a non-empty decision_question."""
    defn = catalog.get(kpi_id)
    assert defn is not None, f"KPI {kpi_id!r} not registered"
    assert defn.decision_question.strip(), (
        f"KPI {kpi_id!r} has empty decision_question (FK-60 §60.2 P1)"
    )


@pytest.mark.parametrize("kpi_id", sorted(_EXPECTED_AKTIV_IDS))
def test_kpi_has_non_empty_name(kpi_id: str, catalog: KpiCatalog) -> None:
    """Each KPI must have a non-empty human-readable name."""
    defn = catalog.get(kpi_id)
    assert defn is not None
    assert defn.name.strip(), f"KPI {kpi_id!r} has empty name"


@pytest.mark.parametrize("kpi_id", sorted(_EXPECTED_AKTIV_IDS))
def test_kpi_has_non_empty_formula_repr(kpi_id: str, catalog: KpiCatalog) -> None:
    """Each KPI must have a non-empty declarative formula."""
    defn = catalog.get(kpi_id)
    assert defn is not None
    assert defn.formula_repr.strip(), f"KPI {kpi_id!r} has empty formula_repr"


@pytest.mark.parametrize("kpi_id", sorted(_EXPECTED_AKTIV_IDS))
def test_kpi_granularity_is_valid(kpi_id: str, catalog: KpiCatalog) -> None:
    """Each KPI must have a valid FK-60 §60.2 P5 granularity."""
    defn = catalog.get(kpi_id)
    assert defn is not None
    assert defn.granularity in set(KpiGranularity), (
        f"KPI {kpi_id!r} has invalid granularity {defn.granularity!r}"
    )


@pytest.mark.parametrize("kpi_id", sorted(_EXPECTED_AKTIV_IDS))
def test_kpi_collection_point_hook_is_not_empty(kpi_id: str, catalog: KpiCatalog) -> None:
    """FK-61: no KPI may have an empty hook_or_event (always an error)."""
    defn = catalog.get(kpi_id)
    assert defn is not None
    assert defn.collection_point.hook_or_event.strip(), (
        f"KPI {kpi_id!r} has empty collection_point.hook_or_event"
    )


# ---------------------------------------------------------------------------
# Domain balance assertions (FK-60 §60.4.12): 7/5/7/1/7/1/2/2/2/6 = 40
# ---------------------------------------------------------------------------

_DOMAIN_EXPECTED_COUNTS: dict[str, int] = {
    "STORY_SIZING": 7,
    "LLM_SELECTION": 5,
    "GOVERNANCE": 7,
    "DOC_FIDELITY": 1,
    "QA_EFFECTIVENESS": 7,
    "REVIEW_QUALITY": 1,
    "VECTORDB": 2,
    "ARE_INTEGRATION": 2,
    "FAILURE_CORPUS": 2,
    "PROCESS_EFFICIENCY": 6,
}


def test_domain_balance_matches_fk60_4_12(catalog: KpiCatalog) -> None:
    """FK-60 §60.4.12: domain counts must be 7/5/7/1/7/1/2/2/2/6."""
    actual: dict[str, int] = {}
    for defn in catalog.list_definitions():
        actual[defn.domain.value] = actual.get(defn.domain.value, 0) + 1
    for domain_value, expected_count in _DOMAIN_EXPECTED_COUNTS.items():
        actual_count = actual.get(domain_value, 0)
        assert actual_count == expected_count, (
            f"Domain {domain_value}: expected {expected_count} KPIs, got {actual_count}"
        )


# ---------------------------------------------------------------------------
# [R]/[N] data_available alignment spot-checks
# ---------------------------------------------------------------------------


def test_r_kpis_have_data_available_true(catalog: KpiCatalog) -> None:
    """[R] KPIs (existing data) must have data_available=True."""
    r_kpis = {
        "qa_round_count",
        "processing_time_by_type_and_size",
        "feedback_loop_convergence",
        "blocked_ac_distribution",
        "policy_required_stage_miss_rate",
        "llm_response_time_p50",
        "llm_call_count_per_story",
        "guard_violation_count_by_type",
        "quorum_trigger_rate",
        "first_pass_success_rate",
        "finding_survival_rate",
        "check_effectiveness_by_id",
        "adversarial_hit_rate",
        "adversarial_findings_count",
        "adversarial_tests_created_count",
        "are_gate_result",
        "incident_volume_per_month",
        "pattern_to_check_conversion_rate",
        "processing_time_trend",
        "qa_round_trend",
        "files_changed_per_story",
        "increment_count_per_story",
        "review_template_effectiveness",
    }
    for kpi_id in r_kpis:
        defn = catalog.get(kpi_id)
        assert defn is not None, f"[R] KPI {kpi_id!r} not registered"
        assert defn.collection_point.data_available is True, (
            f"[R] KPI {kpi_id!r} must have data_available=True"
        )


def test_n_kpis_have_data_available_false(catalog: KpiCatalog) -> None:
    """[N] KPIs (new event/enrichment needed) must have data_available=False."""
    n_kpis = {
        "compaction_count_per_story",
        "execution_vs_exploration_ratio",
        "llm_verdict_adoption_rate",
        "llm_finding_precision",
        "guard_violation_rate_by_guard",
        "prompt_integrity_violation_by_stage",
        "governance_escape_detection_count",
        # orchestrator_governance_violation_count: FK-60 §60.4.4 marks [N];
        # Class 1 source (subset filter of existing events) but data_available=False per AC2.
        "orchestrator_governance_violation_count",
        "impact_violation_rate",
        "integrity_gate_block_rate",
        "doc_fidelity_conflict_rate_by_level",
        "finding_resolution_quality",
        "vectordb_similarity_threshold_calibration",
        "vectordb_duplicate_detection_rate",
        "are_evidence_coverage_rate",
        "phase_time_distribution",
        "story_predictability",
    }
    for kpi_id in n_kpis:
        defn = catalog.get(kpi_id)
        assert defn is not None, f"[N] KPI {kpi_id!r} not registered"
        assert defn.collection_point.data_available is False, (
            f"[N] KPI {kpi_id!r} must have data_available=False"
        )


# ---------------------------------------------------------------------------
# (c) Fail-closed: all KPI_FACT_TARGETS columns resolve in FK-62 Pydantic models
#
# KPI_FACT_TARGETS maps each KPI id to a *tuple* of FactTarget entries.
# This test iterates EVERY entry and checks EVERY (table, column) pair so
# multi-table KPIs (e.g. execution_vs_exploration_ratio) are fully covered.
# ---------------------------------------------------------------------------

# Map FactTable enum to the corresponding Pydantic record model class.
# FactStory/FactGuardPeriod/etc. are the canonical FK-62 Pydantic records
# from AG3-117 (kpi_analytics/fact_store/models.py).
_TABLE_TO_MODEL: dict[FactTable, type[BaseModel]] = {
    FactTable.FACT_STORY: FactStory,
    FactTable.FACT_GUARD_PERIOD: FactGuardPeriod,
    FactTable.FACT_POOL_PERIOD: FactPoolPeriod,
    FactTable.FACT_PIPELINE_PERIOD: FactPipelinePeriod,
    FactTable.FACT_CORPUS_PERIOD: FactCorpusPeriod,
}

# Build the table-to-fields map once for all AC3 resolution calls.
_TABLE_TO_FIELDS: dict[FactTable, frozenset[str]] = {
    table: frozenset(model_cls.model_fields.keys())
    for table, model_cls in _TABLE_TO_MODEL.items()
}


@pytest.mark.parametrize("kpi_id", sorted(_EXPECTED_AKTIV_IDS))
def test_kpi_fact_target_columns_resolve_in_fk62_schema(kpi_id: str) -> None:
    """Contract AC3 (fail-closed): every (table, column) target must exist in FK-62 Pydantic model.

    Resolution source: kpi_analytics/fact_store/models.py — the AG3-117
    Pydantic record models are the canonical typed representation of the
    FK-62 §62.2 column set (see module docstring for rationale).

    A column listed in KPI_FACT_TARGETS that is absent from the model
    indicates a mapping error or an unapplied FK-62 reconciliation.

    Multi-table KPIs (e.g. execution_vs_exploration_ratio) carry more than
    one FactTarget entry; ALL entries are checked here.

    Uses ``resolve_kpi_fact_columns`` from ``fact_target`` so that the same
    typed resolution logic is exercised in both positive and negative tests.
    """
    missing = resolve_kpi_fact_columns(kpi_id, _TABLE_TO_FIELDS)
    assert not missing, (
        f"KPI {kpi_id!r} targets columns that do NOT exist in the FK-62 Pydantic schema"
        f" (AG3-117): {missing}"
    )


def test_execution_vs_exploration_ratio_has_two_fact_targets() -> None:
    """Contract: execution_vs_exploration_ratio spans two fact tables (FK-61 §61.2.2).

    Raw source: fact_story.pipeline_mode (pre-aggregation).
    Aggregated result: fact_pipeline_period.execution_count / exploration_count.
    Both must be present as separate FactTarget entries.
    """
    targets = KPI_FACT_TARGETS["execution_vs_exploration_ratio"]
    assert len(targets) == 2, (
        f"execution_vs_exploration_ratio must have 2 FactTarget entries"
        f" (fact_story + fact_pipeline_period); got {len(targets)}"
    )
    tables = {ft.table for ft in targets}
    assert FactTable.FACT_STORY in tables, (
        "execution_vs_exploration_ratio must target fact_story (pipeline_mode)"
    )
    assert FactTable.FACT_PIPELINE_PERIOD in tables, (
        "execution_vs_exploration_ratio must target fact_pipeline_period"
        " (execution_count, exploration_count)"
    )
    # Verify specific columns
    story_target = next(ft for ft in targets if ft.table == FactTable.FACT_STORY)
    assert "pipeline_mode" in story_target.columns
    period_target = next(ft for ft in targets if ft.table == FactTable.FACT_PIPELINE_PERIOD)
    assert "execution_count" in period_target.columns
    assert "exploration_count" in period_target.columns


# ---------------------------------------------------------------------------
# (d) Source-owner class: class assignments, completeness, and true negatives
# ---------------------------------------------------------------------------

# Per-class KPI id sets (FK-61 §61.2–§61.11, story.md §2.1.3).
# Completeness assertion below ensures union == _EXPECTED_AKTIV_IDS (no KPI omitted).

_CLASS1_EXISTING_EVENT: frozenset[str] = frozenset({
    # [R] or [N] — data sourced from existing events / read-models (no new event type needed)
    # Class 1 may be [R] or [N] per story AG3-118 §2.1.3
    "qa_round_count",
    "processing_time_by_type_and_size",
    "feedback_loop_convergence",
    "blocked_ac_distribution",
    "policy_required_stage_miss_rate",
    "llm_response_time_p50",
    "llm_call_count_per_story",
    "guard_violation_count_by_type",
    # orchestrator_governance_violation_count: Class 1 (subset filter of existing guard events,
    # FK-61 §61.4.2:174) but FK-60 §60.4.4 marks [N] → data_available=False (AC2).
    "orchestrator_governance_violation_count",
    "quorum_trigger_rate",
    "first_pass_success_rate",
    "finding_survival_rate",
    "check_effectiveness_by_id",
    "adversarial_hit_rate",
    "adversarial_findings_count",
    "adversarial_tests_created_count",
    "are_gate_result",
    "incident_volume_per_month",
    "pattern_to_check_conversion_rate",
    "processing_time_trend",
    "qa_round_trend",
    "files_changed_per_story",
    "increment_count_per_story",
    "review_template_effectiveness",
})

_CLASS2_NEW_AG3081_EVENT: frozenset[str] = frozenset({
    # [N] — requires new AG3-081 event type
    "compaction_count_per_story",   # compaction_event (FK-61 §61.2.2)
    "impact_violation_rate",         # impact_violation_check (FK-61 §61.4.2)
    "doc_fidelity_conflict_rate_by_level",  # doc_fidelity_check (FK-61 §61.5.1)
    "vectordb_similarity_threshold_calibration",  # vectordb_search (FK-61 §61.8.1)
    "vectordb_duplicate_detection_rate",          # subset of vectordb_search (FK-61 §61.8.1)
})

_CLASS3_ENRICHED_AG3081_PAYLOAD: frozenset[str] = frozenset({
    # [N] — enriched payload of existing AG3-081 event
    "llm_verdict_adoption_rate",         # review_response.verdict (FK-61 §61.3.2)
    "integrity_gate_block_rate",         # integrity_gate_result.blocked_dimensions (FK-61 §61.4.2/§61.12.2)
    "prompt_integrity_violation_by_stage",  # integrity_violation.stage (FK-61 §61.4.2)
    "governance_escape_detection_count",    # subset of integrity_violation (FK-61 §61.4.2)
    "are_evidence_coverage_rate",           # are_gate_result.total_requirements (FK-61 §61.9.2/§61.12.2)
})

_CLASS4_RUNTIME_METRIC: frozenset[str] = frozenset({
    # [N] — runtime metric / read-model / projection, no new AG3-081 event
    "execution_vs_exploration_ratio",  # runtime.story_metrics.mode (FK-61 §61.2.2)
    "phase_time_distribution",         # phase_state_projection (FK-61 §61.11.2)
    "story_predictability",            # story_metrics.processing_time_min variance (FK-61 §61.11.2)
    # FK-61 §61.6.2: FK-34 StructuredEvaluator output — NOT an AG3-081 event
    "finding_resolution_quality",
    # FK-61 §61.3.2: RefreshWorker correlates qa_findings across rounds — no new event
    "llm_finding_precision",
})

_CLASS5_SCRATCHPAD: frozenset[str] = frozenset({
    # [N] — scratchpad counter, intentionally NOT an event type
    "guard_violation_rate_by_guard",  # runtime.guard_invocation_counters (FK-61 §61.4.3)
})


def test_source_owner_class_sets_are_mutually_exclusive() -> None:
    """No KPI appears in more than one source-owner class."""
    all_classes = [
        ("class1", _CLASS1_EXISTING_EVENT),
        ("class2", _CLASS2_NEW_AG3081_EVENT),
        ("class3", _CLASS3_ENRICHED_AG3081_PAYLOAD),
        ("class4", _CLASS4_RUNTIME_METRIC),
        ("class5", _CLASS5_SCRATCHPAD),
    ]
    seen: dict[str, str] = {}
    for class_name, kpi_ids in all_classes:
        for kpi_id in kpi_ids:
            if kpi_id in seen:
                pytest.fail(
                    f"KPI {kpi_id!r} appears in both {seen[kpi_id]} and {class_name};"
                    " source-owner classes must be mutually exclusive"
                )
            seen[kpi_id] = class_name


def test_source_owner_class_union_covers_all_40_aktiv_kpis() -> None:
    """Completeness: union of per-class KPI id sets == full 40 AKTIV frozenset.

    This assertion ensures that every KPI has exactly one assigned class.
    A future change that adds or reclassifies a KPI must update the class
    sets above — this test will catch any omission.
    """
    all_classified = (
        _CLASS1_EXISTING_EVENT
        | _CLASS2_NEW_AG3081_EVENT
        | _CLASS3_ENRICHED_AG3081_PAYLOAD
        | _CLASS4_RUNTIME_METRIC
        | _CLASS5_SCRATCHPAD
    )
    missing_from_classes = _EXPECTED_AKTIV_IDS - all_classified
    extra_in_classes = all_classified - _EXPECTED_AKTIV_IDS
    assert not missing_from_classes, (
        f"KPIs in AKTIV set but not assigned to any source-owner class: "
        f"{sorted(missing_from_classes)}"
    )
    assert not extra_in_classes, (
        f"KPIs assigned to a source-owner class but not in AKTIV set: "
        f"{sorted(extra_in_classes)}"
    )


def test_catalog_source_owner_class_matches_test_class_sets(
    catalog: KpiCatalog,
) -> None:
    """Faithful class-pin: every KPI's catalog-declared source_owner_class must equal
    the class this test file assigns it to (via the per-class frozensets above).

    This test derives the expected class from the test's own per-class sets and
    compares it against the machine-readable ``source_owner_class`` field on each
    ``KpiCollectionPoint`` in the catalog.  Any catalog-vs-test drift (a KPI moved
    to the wrong class set, or the catalog field updated without moving the KPI in
    this test, or vice versa) causes a deterministic failure here.

    FK-61 §61.2–§61.11 / story AG3-118 §2.1.3: classes 1–5.
    """
    expected_class_map: dict[str, int] = {}
    for class_int, class_set in (
        (1, _CLASS1_EXISTING_EVENT),
        (2, _CLASS2_NEW_AG3081_EVENT),
        (3, _CLASS3_ENRICHED_AG3081_PAYLOAD),
        (4, _CLASS4_RUNTIME_METRIC),
        (5, _CLASS5_SCRATCHPAD),
    ):
        for kpi_id in class_set:
            expected_class_map[kpi_id] = class_int

    mismatches: list[str] = []
    for defn in catalog.list_definitions():
        expected = expected_class_map.get(defn.kpi_id)
        if expected is None:
            mismatches.append(
                f"{defn.kpi_id!r}: not found in any test class set"
                f" (catalog declares class {defn.collection_point.source_owner_class})"
            )
            continue
        actual = defn.collection_point.source_owner_class
        if actual != expected:
            mismatches.append(
                f"{defn.kpi_id!r}: catalog source_owner_class={actual}"
                f" but test assigns class {expected}"
            )

    assert not mismatches, (
        "Catalog source_owner_class diverges from test class-set assignment"
        f" for {len(mismatches)} KPI(s):\n"
        + "\n".join(f"  {m}" for m in mismatches)
    )


def test_finding_resolution_quality_is_class4_not_class2(catalog: KpiCatalog) -> None:
    """finding_resolution_quality is Class 4 (FK-34 evaluator output), NOT Class 2 (AG3-081 event).

    FK-61 §61.6.2: source is StructuredEvaluator remediation mode (FK-34) —
    a new field in its structured output. FK-34 is explicitly listed as an
    FK-61 defers_to target for finding-resolution events (FK-61 YAML header).
    AG3-081 owns event/payload infrastructure; FK-34 owns evaluation outputs.
    The collection_point.notes must NOT claim 'Class 2' or 'AG3-081 event'.
    """
    defn = catalog.get("finding_resolution_quality")
    assert defn is not None
    assert "finding_resolution_quality" in _CLASS4_RUNTIME_METRIC, (
        "finding_resolution_quality must be in CLASS4 per FK-61 §61.6.2"
    )
    assert "finding_resolution_quality" not in _CLASS2_NEW_AG3081_EVENT, (
        "finding_resolution_quality must NOT be in CLASS2"
    )
    notes = defn.collection_point.notes.lower()
    assert "class 2" not in notes, (
        "finding_resolution_quality notes must not claim Class 2 (AG3-081 event)"
    )
    assert "class 4" in notes, (
        "finding_resolution_quality notes must declare Class 4 (FK-34 evaluator output)"
    )


def test_class2_new_event_kpis_reference_ag3081_event(catalog: KpiCatalog) -> None:
    """Class 2 (new event, AG3-081): hook_or_event must name the new event type.

    FK-61 §61.2.2/§61.4.2/§61.5.1/§61.8.1 — new events built by AG3-081:
    compaction_event, impact_violation_check, doc_fidelity_check, vectordb_search.
    """
    class2_kpis: dict[str, str] = {
        "compaction_count_per_story": "compaction_event",
        "impact_violation_rate": "impact_violation_check",
        "doc_fidelity_conflict_rate_by_level": "doc_fidelity_check",
        "vectordb_similarity_threshold_calibration": "vectordb_search",
        "vectordb_duplicate_detection_rate": "vectordb_search",
    }
    for kpi_id, expected_event_fragment in class2_kpis.items():
        defn = catalog.get(kpi_id)
        assert defn is not None, f"Class 2 KPI {kpi_id!r} not registered"
        assert expected_event_fragment in defn.collection_point.hook_or_event, (
            f"Class 2 KPI {kpi_id!r}: hook_or_event must reference"
            f" {expected_event_fragment!r};"
            f" got {defn.collection_point.hook_or_event!r}"
        )


def test_class3_enriched_payload_kpis_reference_ag3081_fields(
    catalog: KpiCatalog,
) -> None:
    """Class 3 (enriched payload, AG3-081): hook_or_event must name the payload field.

    FK-61 §61.12.2 canonical wire-keys:
    integrity_gate_result.blocked_dimensions, are_gate_result.total_requirements,
    are_gate_result.covered_requirements.
    """
    class3_kpis: dict[str, str] = {
        "integrity_gate_block_rate": "integrity_gate_result.blocked_dimensions",
        "are_evidence_coverage_rate": "are_gate_result.total_requirements",
        "prompt_integrity_violation_by_stage": "integrity_violation.stage",
        "governance_escape_detection_count": "integrity_violation.stage",
        "llm_verdict_adoption_rate": "review_response",
    }
    for kpi_id, expected_fragment in class3_kpis.items():
        defn = catalog.get(kpi_id)
        assert defn is not None, f"Class 3 KPI {kpi_id!r} not registered"
        assert expected_fragment in defn.collection_point.hook_or_event, (
            f"Class 3 KPI {kpi_id!r}: hook_or_event must reference"
            f" {expected_fragment!r};"
            f" got {defn.collection_point.hook_or_event!r}"
        )


def test_class4_runtime_metric_kpis_do_not_require_ag3081_event(
    catalog: KpiCatalog,
) -> None:
    """Class 4 (runtime metric/projection): hook_or_event is a read-model reference.

    FK-61 §61.2.2/§61.11.2/§61.6.2: these KPIs explicitly say 'Kein neues Event noetig'
    or reference FK-34 evaluator output (not an AG3-081 event).
    """
    class4_kpis: dict[str, str] = {
        "execution_vs_exploration_ratio": "runtime.story_metrics.mode",
        "phase_time_distribution": "phase_state_projection",
        "story_predictability": "story_metrics.processing_time_min",
        "finding_resolution_quality": "layer2_remediation_output.resolution_status",
    }
    for kpi_id, expected_fragment in class4_kpis.items():
        defn = catalog.get(kpi_id)
        assert defn is not None, f"Class 4 KPI {kpi_id!r} not registered"
        assert expected_fragment in defn.collection_point.hook_or_event, (
            f"Class 4 KPI {kpi_id!r}: hook_or_event must reference"
            f" {expected_fragment!r};"
            f" got {defn.collection_point.hook_or_event!r}"
        )
        # Class 4: data_available=False (new aggregation needed, no new event)
        assert defn.collection_point.data_available is False, (
            f"Class 4 KPI {kpi_id!r}: data_available must be False"
        )


def test_class5_scratchpad_kpi_does_not_use_event_type(catalog: KpiCatalog) -> None:
    """Class 5 (scratchpad counter): guard_violation_rate_by_guard uses scratchpad, not event.

    FK-61 §61.4.3: guard_invocation is intentionally NOT an event type.
    Source is runtime.guard_invocation_counters.
    """
    defn = catalog.get("guard_violation_rate_by_guard")
    assert defn is not None
    assert "guard_invocation_counters" in defn.collection_point.hook_or_event, (
        "Class 5 KPI guard_violation_rate_by_guard: hook_or_event must reference"
        " guard_invocation_counters scratchpad"
    )
    # Scratchpad-based KPIs need new data paths: data_available=False
    assert defn.collection_point.data_available is False, (
        "Class 5 KPI guard_violation_rate_by_guard: data_available must be False"
        " (scratchpad counter, not existing event)"
    )


# ---------------------------------------------------------------------------
# True negative tests (AC4): crafted-invalid inputs prove fail-closed behavior
#
# These tests construct INVALID definitions / mappings and assert the typed
# validator callables raise or return non-empty error lists.  They do NOT
# scan the (valid) catalog — they prove that the validation logic itself
# rejects bad inputs.
# ---------------------------------------------------------------------------


def test_negative_empty_decision_question_is_rejected() -> None:
    """True negative: validate_kpi_definition rejects empty decision_question.

    FK-60 §60.2 P1: every KPI must have a non-empty decision question.
    Constructs an invalid input and asserts the validator returns an error.
    """
    errors = validate_kpi_definition(
        decision_question="",
        hook_or_event="some_event",
    )
    assert errors, (
        "validate_kpi_definition must return at least one error for"
        " empty decision_question"
    )
    assert any("decision_question" in e for e in errors), (
        f"Error list {errors!r} must mention 'decision_question'"
    )


def test_negative_whitespace_only_decision_question_is_rejected() -> None:
    """True negative: validate_kpi_definition rejects whitespace-only decision_question."""
    errors = validate_kpi_definition(
        decision_question="   \t  ",
        hook_or_event="some_event",
    )
    assert errors, (
        "validate_kpi_definition must return errors for whitespace-only decision_question"
    )


def test_negative_empty_hook_or_event_is_rejected() -> None:
    """True negative: validate_kpi_definition rejects empty hook_or_event.

    FK-61: no KPI without a source; an empty hook_or_event is always invalid.
    Constructs an invalid input and asserts the validator returns an error.
    """
    errors = validate_kpi_definition(
        decision_question="Is this KPI useful?",
        hook_or_event="",
    )
    assert errors, (
        "validate_kpi_definition must return at least one error for empty hook_or_event"
    )
    assert any("hook_or_event" in e for e in errors), (
        f"Error list {errors!r} must mention 'hook_or_event'"
    )


def test_negative_class2_missing_ag3081_event_fragment_is_rejected() -> None:
    """True negative: validate_class2_or_3_source rejects a Class-2 KPI whose
    hook_or_event does not contain the required AG3-081 event fragment.

    A KPI claiming Class 2 (new AG3-081 event) but providing a hook_or_event
    that does not name the event type must be flagged as invalid.
    """
    errors = validate_class2_or_3_source(
        kpi_id="hypothetical_class2_kpi",
        hook_or_event="story_metrics.some_field",   # does NOT reference the expected event
        required_event_fragment="compaction_event",
    )
    assert errors, (
        "validate_class2_or_3_source must return errors when the required AG3-081"
        " event fragment is absent from hook_or_event"
    )
    assert any("compaction_event" in e for e in errors), (
        f"Error list {errors!r} must mention the missing event fragment"
    )


def test_negative_class2_empty_hook_or_event_is_rejected() -> None:
    """True negative: validate_class2_or_3_source rejects empty hook_or_event for Class-2/3 KPI."""
    errors = validate_class2_or_3_source(
        kpi_id="hypothetical_kpi",
        hook_or_event="",
        required_event_fragment="some_event",
    )
    assert errors, (
        "validate_class2_or_3_source must return errors for empty hook_or_event"
    )


def test_negative_unknown_fact_column_is_rejected() -> None:
    """True negative: resolve_kpi_fact_columns detects a column absent from FK-62 schema.

    Constructs a temporary entry in KPI_FACT_TARGETS pointing at a
    column that does not exist in the Pydantic model and asserts the
    resolver returns it as missing.
    """
    import agentkit.kpi_analytics.fact_target as ft_module

    nonexistent_column = "this_column_does_not_exist_in_any_fk62_model"
    fake_target: tuple[ft_module.FactTarget, ...] = (
        ft_module.FactTarget(
            table=ft_module.FactTable.FACT_STORY,
            columns=frozenset({nonexistent_column}),
        ),
    )

    # Build a table-to-fields map from the Pydantic models
    table_to_fields: dict[ft_module.FactTable, frozenset[str]] = {
        table: frozenset(model_cls.model_fields.keys())
        for table, model_cls in _TABLE_TO_MODEL.items()
    }

    # Temporarily patch KPI_FACT_TARGETS to include a fake KPI with invalid column
    original = ft_module.KPI_FACT_TARGETS.get("_neg_test_kpi_")
    ft_module.KPI_FACT_TARGETS["_neg_test_kpi_"] = fake_target
    try:
        missing = resolve_kpi_fact_columns("_neg_test_kpi_", table_to_fields)
    finally:
        if original is None:
            ft_module.KPI_FACT_TARGETS.pop("_neg_test_kpi_", None)
        else:
            ft_module.KPI_FACT_TARGETS["_neg_test_kpi_"] = original

    assert missing, (
        "resolve_kpi_fact_columns must return missing entries for a column"
        " that does not exist in the FK-62 Pydantic schema"
    )
    assert any(nonexistent_column in m for m in missing), (
        f"Missing list {missing!r} must contain the nonexistent column name"
    )


# ---------------------------------------------------------------------------
# (e) P95 is INVENTAR — absent from catalog
# ---------------------------------------------------------------------------


def test_llm_response_time_p95_is_not_registered(catalog: KpiCatalog) -> None:
    """Contract AC-e: llm_response_time_p95 is INVENTAR and must not be registered.

    FK-60 §60.4.3: P95 is INVENTAR. P95 activation is a separate future story.
    """
    assert catalog.get("llm_response_time_p95") is None, (
        "llm_response_time_p95 is INVENTAR (FK-60 §60.4.3) and must NOT be registered"
    )


def test_no_inventar_kpi_ids_registered(catalog: KpiCatalog) -> None:
    """No INVENTAR KPI ID is registered (only the exact 40 AKTIV IDs)."""
    registered_ids = frozenset(d.kpi_id for d in catalog.list_definitions())
    # Spot-check known INVENTAR IDs from FK-60 §60.4.2–§60.4.11
    inventar_ids = {
        "llm_response_time_p95",
        "compaction_recovery_count",
        "preflight_gate_pass_rate",
        "functional_failure_escalation_rate",
        "merge_conflict_rate",
        "llm_availability_rate",
        "pool_slot_utilization_trend",
        "llm_dissent_rate",
        "adversarial_sandbox_escape_count",
        "incident_to_pattern_conversion_rate",
        "worker_drift_detection_rate",
        "doc_fidelity_escalation_count",
    }
    found_inventar = registered_ids & inventar_ids
    assert not found_inventar, (
        f"INVENTAR KPIs must not be registered: {sorted(found_inventar)}"
    )


# ---------------------------------------------------------------------------
# (f) Canonical wire-key pins (FK-61 §61.12.2) + FK-62 resolution
# ---------------------------------------------------------------------------


def test_integrity_gate_result_blocked_dimensions_wire_key(catalog: KpiCatalog) -> None:
    """FK-61 §61.12.2: integrity_gate_result.blocked_dimensions is the canonical wire-key."""
    defn = catalog.get("integrity_gate_block_rate")
    assert defn is not None
    assert "integrity_gate_result.blocked_dimensions" in defn.collection_point.hook_or_event, (
        "integrity_gate_block_rate must reference wire-key"
        " 'integrity_gate_result.blocked_dimensions' (FK-61 §61.12.2)"
    )
    # Target columns must be in FK-62 Pydantic schema (multi-target aware)
    targets = KPI_FACT_TARGETS["integrity_gate_block_rate"]
    all_columns = {col for ft in targets for col in ft.columns}
    assert "integrity_gate_block_count" in all_columns
    assert "integrity_gate_total_count" in all_columns
    model_fields = set(FactPipelinePeriod.model_fields.keys())
    assert "integrity_gate_block_count" in model_fields
    assert "integrity_gate_total_count" in model_fields


def test_are_gate_result_total_requirements_wire_key(catalog: KpiCatalog) -> None:
    """FK-61 §61.12.2: are_gate_result.total_requirements is a canonical wire-key."""
    defn = catalog.get("are_evidence_coverage_rate")
    assert defn is not None
    assert "are_gate_result.total_requirements" in defn.collection_point.hook_or_event, (
        "are_evidence_coverage_rate must reference wire-key"
        " 'are_gate_result.total_requirements' (FK-61 §61.12.2)"
    )
    targets = KPI_FACT_TARGETS["are_evidence_coverage_rate"]
    all_columns = {col for ft in targets for col in ft.columns}
    assert "are_total_requirements" in all_columns
    model_fields = set(FactStory.model_fields.keys())
    assert "are_total_requirements" in model_fields


def test_are_gate_result_covered_requirements_wire_key(catalog: KpiCatalog) -> None:
    """FK-61 §61.12.2: are_gate_result.covered_requirements is a canonical wire-key."""
    defn = catalog.get("are_evidence_coverage_rate")
    assert defn is not None
    assert "are_gate_result.covered_requirements" in defn.collection_point.hook_or_event, (
        "are_evidence_coverage_rate must reference wire-key"
        " 'are_gate_result.covered_requirements' (FK-61 §61.12.2)"
    )
    targets = KPI_FACT_TARGETS["are_evidence_coverage_rate"]
    all_columns = {col for ft in targets for col in ft.columns}
    assert "are_covered_requirements" in all_columns
    model_fields = set(FactStory.model_fields.keys())
    assert "are_covered_requirements" in model_fields


# ---------------------------------------------------------------------------
# (g) llm_response_time_p50 AKTIV + target; llm_response_time_p95 absent
# ---------------------------------------------------------------------------


def test_llm_response_time_p50_is_aktiv_and_maps_to_pool_period(
    catalog: KpiCatalog,
) -> None:
    """Contract AC6: llm_response_time_p50 is AKTIV, maps to fact_pool_period.response_time_p50_ms."""
    defn = catalog.get("llm_response_time_p50")
    assert defn is not None, "llm_response_time_p50 must be registered as AKTIV"
    assert defn.collection_point.data_available is True  # [R]

    targets = KPI_FACT_TARGETS["llm_response_time_p50"]
    assert len(targets) == 1
    target = targets[0]
    assert target.table == FactTable.FACT_POOL_PERIOD
    assert "response_time_p50_ms" in target.columns

    # Resolve against FK-62 Pydantic schema (fail-closed)
    assert "response_time_p50_ms" in set(FactPoolPeriod.model_fields.keys())


def test_llm_response_time_p95_absent_from_fact_targets() -> None:
    """P95 is INVENTAR: must not appear in KPI_FACT_TARGETS."""
    assert "llm_response_time_p95" not in KPI_FACT_TARGETS, (
        "llm_response_time_p95 is INVENTAR and must not appear in KPI_FACT_TARGETS"
    )


# ---------------------------------------------------------------------------
# FK-61 ↔ FK-62 divergence pin: prompt_integrity_violation_by_stage
# ---------------------------------------------------------------------------


def test_prompt_integrity_violation_by_stage_uses_fk62_names_without_count_suffix() -> None:
    """Contract (story.md §2.1.2): FK-62 column names are authoritative — no _count suffix.

    FK-61 §61.4.2 mistakenly names violation_stage_escape_count etc. (with _count).
    FK-62 §62.2.2 is authoritative: violation_stage_escape, violation_stage_schema,
    violation_stage_template (without _count). The catalog must use FK-62 names.
    """
    targets = KPI_FACT_TARGETS["prompt_integrity_violation_by_stage"]
    all_columns = {col for ft in targets for col in ft.columns}
    # Must use FK-62 names (no _count suffix)
    assert "violation_stage_escape" in all_columns
    assert "violation_stage_schema" in all_columns
    assert "violation_stage_template" in all_columns
    # Must NOT use the FK-61 drift names (with _count suffix)
    assert "violation_stage_escape_count" not in all_columns
    assert "violation_stage_schema_count" not in all_columns
    assert "violation_stage_template_count" not in all_columns

    # All three columns must resolve in FK-62 Pydantic model
    model_fields = set(FactGuardPeriod.model_fields.keys())
    assert "violation_stage_escape" in model_fields
    assert "violation_stage_schema" in model_fields
    assert "violation_stage_template" in model_fields
    # And the _count variants must NOT be in the schema
    assert "violation_stage_escape_count" not in model_fields
    assert "violation_stage_schema_count" not in model_fields
    assert "violation_stage_template_count" not in model_fields


# ---------------------------------------------------------------------------
# CatalogStatus.COMPLETE contract
# ---------------------------------------------------------------------------


def test_catalog_status_is_complete(catalog: KpiCatalog) -> None:
    """AG3-118: catalog_status must be COMPLETE (not SKELETON) after population."""
    from agentkit.kpi_analytics.catalog import CatalogStatus

    assert catalog.catalog_status == CatalogStatus.COMPLETE
