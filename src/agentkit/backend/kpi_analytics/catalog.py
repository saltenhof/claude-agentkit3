"""KPI catalog: typed registry of all 40 active KPI definitions (FK-60 §60.4).

``KpiCatalog`` is fully populated with exactly the 40 AKTIV-KPIs from
FK-60 §60.4 (AG3-118).  ``catalog_status`` is ``CatalogStatus.COMPLETE``
once all 40 definitions are registered.  Consumers may rely on
``list_definitions()`` returning the complete set.

Domain balance (FK-60 §60.4.12): 7/5/7/1/7/1/2/2/2/6 = 40 AKTIV.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class KpiGranularity(StrEnum):
    """Aggregation granularity for a KPI (FK-60 §60.2 P5).

    STORY        — one row per completed story.
    ENTITY_PERIOD — one row per entity (guard/pool/template) per period.
    PERIOD       — one row per period (global, no entity dimension).
    """

    STORY = "STORY"
    ENTITY_PERIOD = "ENTITY_PERIOD"
    PERIOD = "PERIOD"


class KpiDomain(StrEnum):
    """Fachliche Domaene einer KPI (FK-60 §60.4, Domaenen 1-10).

    Exactly ten domains are defined in FK-60 §60.4.
    NOTE: The story specification mentions twelve values, but FK-60 §60.4
    is the authoritative source and defines exactly ten domains.
    All names map to their FK-60 section headings.
    """

    STORY_SIZING = "STORY_SIZING"
    """Domain 1: story sizing and pipeline control"""

    LLM_SELECTION = "LLM_SELECTION"
    """Domain 2: LLM selection and performance"""

    GOVERNANCE = "GOVERNANCE"
    """Domain 3: governance health"""

    DOC_FIDELITY = "DOC_FIDELITY"
    """Domain 4: document fidelity and concept conformance"""

    QA_EFFECTIVENESS = "QA_EFFECTIVENESS"
    """Domain 5: QA effectiveness"""

    REVIEW_QUALITY = "REVIEW_QUALITY"
    """Domain 6: review quality and evidence assembly"""

    VECTORDB = "VECTORDB"
    """Domain 7: vector DB and knowledge management"""

    ARE_INTEGRATION = "ARE_INTEGRATION"
    """Domain 8: ARE integration"""

    FAILURE_CORPUS = "FAILURE_CORPUS"
    """Domain 9: failure corpus and learning loop"""

    PROCESS_EFFICIENCY = "PROCESS_EFFICIENCY"
    """Domain 10: process efficiency and trends"""


class CatalogStatus(StrEnum):
    """Population completeness status of a KpiCatalog."""

    SKELETON = "SKELETON"
    """Catalog is typed and testable but not fully populated."""

    COMPLETE = "COMPLETE"
    """All KPIs from FK-60 §60.4 are registered."""


class KpiCollectionPoint(BaseModel):
    """Declares where and how raw data for a KPI is collected (FK-61).

    Google-style:
        hook_or_event: Identifier of the hook or event that feeds this KPI.
        data_available: Whether raw data already exists ([R]) or needs a
            new event/hook ([N]) per FK-61 legend.
        source_owner_class: Machine-readable source-owner class (1–5) per
            story AG3-118 §2.1.3 and FK-61 §61.2–§61.11.  Values:
              1 — existing event / read-model (may be [R] or [N]);
              2 — new AG3-081 event type;
              3 — enriched payload of existing AG3-081 event;
              4 — runtime metric / read-model / projection, no new event;
              5 — scratchpad counter (intentionally not an event type).
        notes: Optional free-text notes about the collection point.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    hook_or_event: str
    data_available: bool
    source_owner_class: int
    notes: str = ""


class KpiDefinition(BaseModel):
    """Typed definition of a single KPI (FK-60 §60.4).

    All fields are mandatory. Pydantic v2 frozen model — instances are
    immutable after construction.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    kpi_id: str
    """Canonical machine-readable identifier, e.g. ``story_throughput_per_period``."""

    name: str
    """Human-readable KPI name."""

    decision_question: str
    """The decision this KPI informs (FK-60 P1: no KPI without a decision question)."""

    formula_repr: str
    """Declarative formula representation (no executable code)."""

    granularity: KpiGranularity
    """Primary aggregation granularity."""

    collection_point: KpiCollectionPoint
    """Where raw data originates."""

    domain: KpiDomain
    """Thematic domain from FK-60 §60.4."""


class KpiCatalog:
    """In-memory registry for all 40 active KPI definitions (FK-60 §60.4).

    ``catalog_status`` is ``CatalogStatus.COMPLETE`` — the catalog is fully
    populated with exactly the 40 AKTIV-KPIs from FK-60 §60.4.12 (domain
    balance 7/5/7/1/7/1/2/2/2/6).  Consumers may rely on
    ``list_definitions()`` returning the complete set.

    Google-style:
        Attributes:
            catalog_status: ``CatalogStatus.COMPLETE`` — all 40 KPIs registered.
    """

    catalog_status: CatalogStatus = CatalogStatus.COMPLETE

    def __init__(self) -> None:
        self._definitions: dict[str, KpiDefinition] = {}
        _register_all(self)

    def register(self, definition: KpiDefinition) -> None:
        """Register a KPI definition.

        Args:
            definition: The KpiDefinition to add. Overwrites any existing
                entry with the same ``kpi_id``.
        """
        self._definitions[definition.kpi_id] = definition

    def list_definitions(self) -> list[KpiDefinition]:
        """Return all registered KPI definitions.

        Returns:
            Snapshot list; order is insertion order.
        """
        return list(self._definitions.values())

    def get(self, kpi_id: str) -> KpiDefinition | None:
        """Retrieve a single KPI definition by id.

        Args:
            kpi_id: The ``kpi_id`` to look up.

        Returns:
            The matching ``KpiDefinition``, or ``None`` if not found.
        """
        return self._definitions.get(kpi_id)


def _cp(
    hook_or_event: str,
    data_available: bool,
    source_owner_class: int,
    notes: str = "",
) -> KpiCollectionPoint:
    """Shorthand for KpiCollectionPoint construction."""
    return KpiCollectionPoint(
        hook_or_event=hook_or_event,
        data_available=data_available,
        source_owner_class=source_owner_class,
        notes=notes,
    )


def _kpi(
    kpi_id: str,
    name: str,
    decision_question: str,
    formula_repr: str,
    granularity: KpiGranularity,
    collection_point: KpiCollectionPoint,
    domain: KpiDomain,
) -> KpiDefinition:
    """Shorthand for KpiDefinition construction."""
    return KpiDefinition(
        kpi_id=kpi_id,
        name=name,
        decision_question=decision_question,
        formula_repr=formula_repr,
        granularity=granularity,
        collection_point=collection_point,
        domain=domain,
    )


_S = KpiGranularity.STORY
_EP = KpiGranularity.ENTITY_PERIOD
_P = KpiGranularity.PERIOD

_D1 = KpiDomain.STORY_SIZING
_D2 = KpiDomain.LLM_SELECTION
_D3 = KpiDomain.GOVERNANCE
_D4 = KpiDomain.DOC_FIDELITY
_D5 = KpiDomain.QA_EFFECTIVENESS
_D6 = KpiDomain.REVIEW_QUALITY
_D7 = KpiDomain.VECTORDB
_D8 = KpiDomain.ARE_INTEGRATION
_D9 = KpiDomain.FAILURE_CORPUS
_D10 = KpiDomain.PROCESS_EFFICIENCY

# ---------------------------------------------------------------------------
# Shared string constants (Sonar S1192: no duplicate literals)
# ARCH-55: English identifiers; FK-60/FK-61 section refs preserved in value.
# ---------------------------------------------------------------------------

_HOOK_STORY_METRICS_PROCESSING_TIME_MIN = "story_metrics.processing_time_min"
"""Canonical hook_or_event identifier for processing-time fields (FK-61 §61.2/§61.11)."""

_NOTE_CLOSURE_VIA_METRICS_COLLECTOR_D5 = (
    "Closure via MetricsCollector (FK-61 §61.6.1, Class 1)"
)
"""Collection-point note for Domain 5 KPIs sourced from MetricsCollector at story closure."""


def _register_all(catalog: KpiCatalog) -> None:
    """Register all 40 AKTIV-KPIs (FK-60 §60.4) into ``catalog``.

    Domain balance per FK-60 §60.4.12: D1=7, D2=5, D3=7, D4=1, D5=7,
    D6=1, D7=2, D8=2, D9=2, D10=6 → total 40 AKTIV.

    Delegates to one private helper per FK-60 domain so each helper stays
    within the Sonar LOC limit (S138/PY_FUNCTION_MAX_LOC_500).
    """
    _register_story_sizing(catalog)
    _register_llm_selection(catalog)
    _register_governance(catalog)
    _register_doc_fidelity(catalog)
    _register_qa_effectiveness(catalog)
    _register_review_quality(catalog)
    _register_vectordb(catalog)
    _register_are(catalog)
    _register_failure_corpus(catalog)
    _register_process_efficiency(catalog)


# ---------------------------------------------------------------------------
# Per-domain registration helpers (FK-60 §60.4 domains 1–10)
# ---------------------------------------------------------------------------


def _register_story_sizing(catalog: KpiCatalog) -> None:
    """Register Domain 1 — Story Sizing (7 AKTIV, FK-60 §60.4.2)."""
    catalog.register(_kpi(
        kpi_id="compaction_count_per_story",
        name="Compaction Count per Story",
        decision_question="Are stories too large, causing frequent context compaction?",
        formula_repr="COUNT(compaction_event) per (project_key, story_id)",
        granularity=_S,
        collection_point=_cp(
            "compaction_event",
            False,
            2,
            "PostCompact-Hook (epoch_writer.py) writes compaction_event into execution_events"
            " (FK-61 §61.2.2, Class 2: new event, AG3-081)",
        ),
        domain=_D1,
    ))

    catalog.register(_kpi(
        kpi_id="qa_round_count",
        name="QA Round Count",
        decision_question="Are stories well-specified (low remediation cycles)?",
        formula_repr="story_metrics.qa_rounds per story",
        granularity=_S,
        collection_point=_cp(
            "story_metrics.qa_rounds",
            True,
            1,
            "MetricsCollector at story closure (FK-61 §61.2.1, Class 1: existing data)",
        ),
        domain=_D1,
    ))

    catalog.register(_kpi(
        kpi_id="processing_time_by_type_and_size",
        name="Processing Time by Type and Size",
        decision_question="Does processing time calibrate correctly for story type and size?",
        formula_repr=(
            "story_metrics.processing_time_min grouped by (story_type, story_size)"
        ),
        granularity=_S,
        collection_point=_cp(
            _HOOK_STORY_METRICS_PROCESSING_TIME_MIN,
            True,
            1,
            "Closure: MetricsCollector reads story_contexts (FK-61 §61.2.1, Class 1)",
        ),
        domain=_D1,
    ))

    catalog.register(_kpi(
        kpi_id="feedback_loop_convergence",
        name="Feedback Loop Convergence",
        decision_question="Are findings resolved across QA rounds (worker understands the problem)?",
        formula_repr="Findings(round N+1) < Findings(round N) per story",
        granularity=_S,
        collection_point=_cp(
            "artifact_records",
            True,
            1,
            "Read-model over artifact_records per (project_key, story_id, run_id)"
            " (FK-61 §61.2.1, Class 1)",
        ),
        domain=_D1,
    ))

    catalog.register(_kpi(
        kpi_id="execution_vs_exploration_ratio",
        name="Execution vs Exploration Ratio",
        decision_question="Is the pipeline over-exploring rather than executing stories?",
        formula_repr=(
            "execution_count / (execution_count + exploration_count) per period"
        ),
        granularity=_P,
        collection_point=_cp(
            "runtime.story_metrics.mode",
            False,
            4,
            "No new event needed; RefreshWorker reads story_metrics.mode at closure"
            " (FK-61 §61.2.2, Class 4: runtime metric/projection)",
        ),
        domain=_D1,
    ))

    catalog.register(_kpi(
        kpi_id="blocked_ac_distribution",
        name="Blocked AC Distribution",
        decision_question="Which acceptance criteria fail systematically (unclear AC formulation)?",
        formula_repr="blocked_acs from handover.json grouped by ac_id",
        granularity=_S,
        collection_point=_cp(
            "handover.blocked_acs",
            True,
            1,
            "Closure reads handover.json artifact (FK-61 §61.2.1, Class 1)",
        ),
        domain=_D1,
    ))

    catalog.register(_kpi(
        kpi_id="policy_required_stage_miss_rate",
        name="Policy Required Stage Miss Rate",
        decision_question="Which pipeline stages are skipped (execution gaps)?",
        formula_repr="COUNT(missing_required_stages) / total_stories per period",
        granularity=_P,
        collection_point=_cp(
            "decision.missing_required_stages",
            True,
            1,
            "Policy-Engine (FK-33) documents missing stages in decision.json"
            " (FK-61 §61.2.1, Class 1)",
        ),
        domain=_D1,
    ))


def _register_llm_selection(catalog: KpiCatalog) -> None:
    """Register Domain 2 — LLM Selection (5 AKTIV, FK-60 §60.4.3)."""
    catalog.register(_kpi(
        kpi_id="llm_response_time_p50",
        name="LLM Response Time P50",
        decision_question="Which LLM pools have the best median response latency?",
        formula_repr="PERCENTILE_50(review_response.occurred_at - review_request.occurred_at) per pool per week",
        granularity=_EP,
        collection_point=_cp(
            "review_request / review_response",
            True,
            1,
            "Events exist; RefreshWorker computes P50 in Python (FK-61 §61.3.1, Class 1)",
        ),
        domain=_D2,
    ))

    catalog.register(_kpi(
        kpi_id="llm_verdict_adoption_rate",
        name="LLM Verdict Adoption Rate",
        decision_question="Are LLM verdicts adopted by the policy decision?",
        formula_repr="adopted_verdicts / total_verdicts per pool per week",
        granularity=_EP,
        collection_point=_cp(
            "review_response.verdict / policy_decision.adopted_verdicts",
            False,
            3,
            "Enriched payload: review_guard.py adds verdict field;"
            " policy-engine adds adopted_verdicts[] (FK-61 §61.3.2, Class 3: AG3-081)",
        ),
        domain=_D2,
    ))

    catalog.register(_kpi(
        kpi_id="llm_finding_precision",
        name="LLM Finding Precision",
        decision_question="Which LLM pools produce high-precision findings (low false-positive rate)?",
        formula_repr="true_positive_findings / (true_positive + false_positive) per pool per week",
        granularity=_EP,
        collection_point=_cp(
            "qa_findings.source_agent",
            False,
            4,
            "RefreshWorker correlates findings across rounds;"
            " no new event (FK-61 §61.3.2, Class 4: runtime metric)",
        ),
        domain=_D2,
    ))

    catalog.register(_kpi(
        kpi_id="llm_call_count_per_story",
        name="LLM Call Count per Story",
        decision_question="What is the LLM cost proxy per story?",
        formula_repr=(
            "COUNT(execution_events WHERE event_type='llm_call') per (project_key, story_id)"
        ),
        granularity=_S,
        collection_point=_cp(
            "execution_events[event_type='llm_call']",
            True,
            1,
            "Events exist (FK-61 §61.3.1, Class 1)",
        ),
        domain=_D2,
    ))

    catalog.register(_kpi(
        kpi_id="quorum_trigger_rate",
        name="Quorum Trigger Rate",
        decision_question="How often does review divergence force mediation?",
        formula_repr="quorum_triggered_count / total_reviews per pool per week",
        granularity=_EP,
        collection_point=_cp(
            "review_divergence.quorum_triggered",
            True,
            1,
            "review_divergence event exists (FK-68); RefreshWorker aggregates"
            " (FK-61 §61.3.2, Class 1: existing event)",
        ),
        domain=_D2,
    ))


def _register_governance(catalog: KpiCatalog) -> None:
    """Register Domain 3 — Governance (7 AKTIV, FK-60 §60.4.4)."""
    catalog.register(_kpi(
        kpi_id="guard_violation_count_by_type",
        name="Guard Violation Count by Type",
        decision_question="Which guard types fire most often?",
        formula_repr=(
            "COUNT(execution_events WHERE event_type='integrity_violation') GROUP BY guard"
        ),
        granularity=_EP,
        collection_point=_cp(
            "execution_events[event_type='integrity_violation'].guard",
            True,
            1,
            "Events exist (FK-61 §61.4.1, Class 1)",
        ),
        domain=_D3,
    ))

    catalog.register(_kpi(
        kpi_id="guard_violation_rate_by_guard",
        name="Guard Violation Rate by Guard",
        decision_question="Which guards block the highest fraction of their invocations?",
        formula_repr="blocks / invocations per (guard_key, week) from guard_invocation_counters",
        granularity=_EP,
        collection_point=_cp(
            "runtime.guard_invocation_counters",
            False,
            5,
            "Scratchpad UPSERT — no event (guard_invocation is intentionally NOT an event type,"
            " FK-61 §61.4.3); Class 5: scratchpad counter",
        ),
        domain=_D3,
    ))

    catalog.register(_kpi(
        kpi_id="prompt_integrity_violation_by_stage",
        name="Prompt Integrity Violation by Stage",
        decision_question="Which prompt-integrity check stage triggers most blocks?",
        formula_repr=(
            "COUNT(integrity_violation WHERE stage IN"
            " {escape_detection, schema_validation, template_integrity})"
            " per (guard_key, week)"
        ),
        granularity=_EP,
        collection_point=_cp(
            "integrity_violation.stage",
            False,
            3,
            "Enriched payload: prompt_integrity_guard.py sets stage field"
            " (FK-61 §61.4.2, Class 3: AG3-081 payload enrichment)."
            " Targets FK-62 column names without _count suffix"
            " (FK-62 §62.2.2 authoritative; FK-61 §61.4.2 has documentation drift — story.md §2.1.2)",
        ),
        domain=_D3,
    ))

    catalog.register(_kpi(
        kpi_id="governance_escape_detection_count",
        name="Governance Escape Detection Count",
        decision_question="How many prompt-injection attempts are detected?",
        formula_repr=(
            "COUNT(integrity_violation WHERE stage='escape_detection') per (guard_key, week)"
        ),
        granularity=_EP,
        collection_point=_cp(
            "integrity_violation.stage[escape_detection]",
            False,
            3,
            "Subset of prompt_integrity_violation_by_stage; no separate event"
            " (FK-61 §61.4.2, Class 3: AG3-081 payload enrichment)",
        ),
        domain=_D3,
    ))

    catalog.register(_kpi(
        kpi_id="orchestrator_governance_violation_count",
        name="Orchestrator Governance Violation Count",
        decision_question="Does the orchestrator illegally read or write code?",
        formula_repr=(
            "COUNT(integrity_violation WHERE guard='orchestrator_guard') per (guard_key, week)"
        ),
        granularity=_EP,
        collection_point=_cp(
            "integrity_violation[guard='orchestrator_guard']",
            False,
            1,
            "Subset filter of existing guard events → fact_guard_period.violation_count"
            " WHERE guard_key='orchestrator_guard' (FK-61 §61.4.2, Class 1)."
            " FK-60/FK-61 tension: FK-60 §60.4.4 classifies [N] (data_available=False);"
            " FK-61 §61.4.2 says derived by filtering existing events (reads [R]-like)."
            " AC2 makes FK-60 [N] authoritative for data_available; FK-61 'derived-from-existing'"
            " wording is a documentation nuance to be reconciled by the FK owner.",
        ),
        domain=_D3,
    ))

    catalog.register(_kpi(
        kpi_id="impact_violation_rate",
        name="Impact Violation Rate",
        decision_question="How often does implementation exceed the declared impact level?",
        formula_repr="impact_violation_count / impact_check_count per week",
        granularity=_P,
        collection_point=_cp(
            "impact_violation_check",
            False,
            2,
            "New event: Structural-Check Layer 1 QA-Subflow within Implementation"
            " (FK-61 §61.4.2, Class 2: new event, AG3-081)",
        ),
        domain=_D3,
    ))

    catalog.register(_kpi(
        kpi_id="integrity_gate_block_rate",
        name="Integrity Gate Block Rate",
        decision_question="How often does the integrity gate block a story, and on which dimensions?",
        formula_repr="integrity_gate_block_count / integrity_gate_total_count per week",
        granularity=_P,
        collection_point=_cp(
            "integrity_gate_result.blocked_dimensions",
            False,
            3,
            "Enriched payload: integrity.py adds blocked_dimensions[]"
            " to existing integrity_gate_result event (FK-61 §61.4.2/§61.12.2,"
            " Class 3: AG3-081 payload enrichment)",
        ),
        domain=_D3,
    ))


def _register_doc_fidelity(catalog: KpiCatalog) -> None:
    """Register Domain 4 — Doc Fidelity (1 AKTIV, FK-60 §60.4.5)."""
    catalog.register(_kpi(
        kpi_id="doc_fidelity_conflict_rate_by_level",
        name="Doc Fidelity Conflict Rate by Level",
        decision_question="At which documentation fidelity level do conflicts arise?",
        formula_repr=(
            "conflict_count / check_count per level"
            " in {goal, design, implementation, feedback} per week"
        ),
        granularity=_P,
        collection_point=_cp(
            "doc_fidelity_check",
            False,
            2,
            "New event: Doc-Fidelity-Service (FK-32) emits per check level"
            " (FK-61 §61.5.1, Class 2: new event, AG3-081)",
        ),
        domain=_D4,
    ))


def _register_qa_effectiveness(catalog: KpiCatalog) -> None:
    """Register Domain 5 — QA Effectiveness (7 AKTIV, FK-60 §60.4.6)."""
    catalog.register(_kpi(
        kpi_id="first_pass_success_rate",
        name="First Pass Success Rate",
        decision_question="What fraction of stories pass QA in the first round?",
        formula_repr="COUNT(qa_rounds == 1 AND final_status='PASS') / story_count per week",
        granularity=_P,
        collection_point=_cp(
            "story_metrics.qa_rounds / story_metrics.final_status",
            True,
            1,
            "RefreshWorker aggregates from story_metrics (FK-61 §61.6.1, Class 1)",
        ),
        domain=_D5,
    ))

    catalog.register(_kpi(
        kpi_id="finding_survival_rate",
        name="Finding Survival Rate",
        decision_question="Do findings persist across multiple QA rounds?",
        formula_repr=(
            "COUNT(qa_findings with same check_id across attempts) / finding_total per week"
        ),
        granularity=_P,
        collection_point=_cp(
            "qa_findings.check_id",
            True,
            1,
            "RefreshWorker compares findings across attempt_no (FK-61 §61.6.1, Class 1)",
        ),
        domain=_D5,
    ))

    catalog.register(_kpi(
        kpi_id="check_effectiveness_by_id",
        name="Check Effectiveness by ID",
        decision_question="Which QA check IDs surface blocking issues?",
        formula_repr="COUNT(qa_findings WHERE blocking=1) GROUP BY check_id per week",
        granularity=_EP,
        collection_point=_cp(
            "qa_findings.check_id",
            True,
            1,
            "RefreshWorker aggregates from qa_findings (FK-61 §61.6.1, Class 1)",
        ),
        domain=_D5,
    ))

    catalog.register(_kpi(
        kpi_id="adversarial_hit_rate",
        name="Adversarial Hit Rate",
        decision_question="Are adversarial tests effective (findings / tests ratio)?",
        formula_repr=(
            "story_metrics.adversarial_findings / story_metrics.adversarial_tests_created"
        ),
        granularity=_S,
        collection_point=_cp(
            "story_metrics.adversarial_findings / story_metrics.adversarial_tests_created",
            True,
            1,
            _NOTE_CLOSURE_VIA_METRICS_COLLECTOR_D5,
        ),
        domain=_D5,
    ))

    catalog.register(_kpi(
        kpi_id="adversarial_findings_count",
        name="Adversarial Findings Count",
        decision_question="How many adversarial findings are generated per story?",
        formula_repr="story_metrics.adversarial_findings per story",
        granularity=_S,
        collection_point=_cp(
            "story_metrics.adversarial_findings",
            True,
            1,
            _NOTE_CLOSURE_VIA_METRICS_COLLECTOR_D5,
        ),
        domain=_D5,
    ))

    catalog.register(_kpi(
        kpi_id="adversarial_tests_created_count",
        name="Adversarial Tests Created Count",
        decision_question="How many adversarial tests are generated per story?",
        formula_repr="story_metrics.adversarial_tests_created per story",
        granularity=_S,
        collection_point=_cp(
            "story_metrics.adversarial_tests_created",
            True,
            1,
            _NOTE_CLOSURE_VIA_METRICS_COLLECTOR_D5,
        ),
        domain=_D5,
    ))

    catalog.register(_kpi(
        kpi_id="finding_resolution_quality",
        name="Finding Resolution Quality",
        decision_question="Are QA findings fully resolved or only partially addressed?",
        formula_repr=(
            "COUNT(resolution_status IN {fully_resolved, partially_resolved, not_resolved})"
            " per story"
        ),
        granularity=_S,
        collection_point=_cp(
            "layer2_remediation_output.resolution_status",
            False,
            4,
            "StructuredEvaluator remediation mode (FK-34) sets resolution_status per finding"
            " in its structured output — NOT an AG3-081 event/payload."
            " (FK-61 §61.6.2, Class 4: FK-34 structured evaluator output, no new event needed)",
        ),
        domain=_D5,
    ))


def _register_review_quality(catalog: KpiCatalog) -> None:
    """Register Domain 6 — Review Quality (1 AKTIV, FK-60 §60.4.7)."""
    catalog.register(_kpi(
        kpi_id="review_template_effectiveness",
        name="Review Template Effectiveness",
        decision_question="Which review templates produce the highest finding yield?",
        formula_repr=(
            "qa_findings_count / reviews_using_template per (template_name, pool, week)"
        ),
        granularity=_EP,
        collection_point=_cp(
            "review_compliant.template_name",
            True,
            1,
            "RefreshWorker correlates review_compliant with qa_findings"
            " (FK-61 §61.7.1, Class 1)",
        ),
        domain=_D6,
    ))


def _register_vectordb(catalog: KpiCatalog) -> None:
    """Register Domain 7 — VectorDB (2 AKTIV, FK-60 §60.4.8)."""
    catalog.register(_kpi(
        kpi_id="vectordb_similarity_threshold_calibration",
        name="VectorDB Similarity Threshold Calibration",
        decision_question="Is the VectorDB similarity threshold calibrated correctly (FP/FN balance)?",
        formula_repr=(
            "hits_above_threshold / total_hits, hits_classified_conflict / total_hits per week"
        ),
        granularity=_P,
        collection_point=_cp(
            "vectordb_search",
            False,
            2,
            "New event: Story-Creation-Pipeline (FK-21) emits after VectorDB query"
            " (FK-61 §61.8.1, Class 2: new event, AG3-081)",
        ),
        domain=_D7,
    ))

    catalog.register(_kpi(
        kpi_id="vectordb_duplicate_detection_rate",
        name="VectorDB Duplicate Detection Rate",
        decision_question="How often does the VectorDB flag real duplicates or conflicts?",
        formula_repr="COUNT(vectordb_search WHERE hits_classified_conflict > 0) / total_searches per week",
        granularity=_P,
        collection_point=_cp(
            "vectordb_search.hits_classified_conflict",
            False,
            2,
            "Subset of vectordb_search event (FK-61 §61.8.1, Class 2: new event, AG3-081)",
        ),
        domain=_D7,
    ))


def _register_are(catalog: KpiCatalog) -> None:
    """Register Domain 8 — ARE Integration (2 AKTIV, FK-60 §60.4.9)."""
    catalog.register(_kpi(
        kpi_id="are_gate_result",
        name="ARE Gate Result",
        decision_question="Does the story pass the ARE requirements gate?",
        formula_repr="are_gate_result.result in {PASS, FAIL} per story",
        granularity=_S,
        collection_point=_cp(
            "execution_events[event_type='are_gate_result'].result",
            True,
            1,
            "ARE telemetry exists (are/telemetry.py) (FK-61 §61.9.1, Class 1)",
        ),
        domain=_D8,
    ))

    catalog.register(_kpi(
        kpi_id="are_evidence_coverage_rate",
        name="ARE Evidence Coverage Rate",
        decision_question="What fraction of must-cover requirements have evidence?",
        formula_repr="are_gate_result.covered_requirements / are_gate_result.total_requirements per story",
        granularity=_S,
        collection_point=_cp(
            "are_gate_result.total_requirements / are_gate_result.covered_requirements",
            False,
            3,
            "Enriched payload: are/telemetry.py adds total_requirements,"
            " covered_requirements (FK-61 §61.9.2/§61.12.2, Class 3: AG3-081)",
        ),
        domain=_D8,
    ))


def _register_failure_corpus(catalog: KpiCatalog) -> None:
    """Register Domain 9 — Failure Corpus (2 AKTIV, FK-60 §60.4.10)."""
    catalog.register(_kpi(
        kpi_id="incident_volume_per_month",
        name="Incident Volume per Month",
        decision_question="Is the system generating fewer incidents over time (target: <20/month)?",
        formula_repr="COUNT(fc_incidents WHERE created_at >= month_start) per (project_key, month)",
        granularity=_P,
        collection_point=_cp(
            "runtime.fc_incidents",
            True,
            1,
            "RefreshWorker aggregates from fc_incidents table (FK-61 §61.10.1, Class 1)",
        ),
        domain=_D9,
    ))

    catalog.register(_kpi(
        kpi_id="pattern_to_check_conversion_rate",
        name="Pattern to Check Conversion Rate",
        decision_question="Do patterns get converted to active checks (learning loop closure)?",
        formula_repr=(
            "COUNT(fc_patterns WITH active check_ref)"
            " / COUNT(fc_patterns) per (project_key, month)"
        ),
        granularity=_P,
        collection_point=_cp(
            "fc_patterns / fc_check_proposals",
            True,
            1,
            "RefreshWorker joins fc_patterns with fc_check_proposals (FK-61 §61.10.1, Class 1)",
        ),
        domain=_D9,
    ))


def _register_process_efficiency(catalog: KpiCatalog) -> None:
    """Register Domain 10 — Process Efficiency (6 AKTIV, FK-60 §60.4.11)."""
    catalog.register(_kpi(
        kpi_id="phase_time_distribution",
        name="Phase Time Distribution",
        decision_question="Where is pipeline time spent across the five phases?",
        formula_repr=(
            "phase_state_projection: closed_at - phase_start per phase"
            " in {setup, exploration, implementation, verify, closure}"
        ),
        granularity=_S,
        collection_point=_cp(
            "phase_state_projection",
            False,
            4,
            "No new event; RefreshWorker reads phase_state_projection timestamps"
            " (FK-61 §61.11.2, Class 4: runtime metric/projection)",
        ),
        domain=_D10,
    ))

    catalog.register(_kpi(
        kpi_id="story_predictability",
        name="Story Predictability",
        decision_question="How predictable is processing time for stories of the same type and size?",
        formula_repr=(
            "VARIANCE(processing_time_min) GROUP BY (story_type, story_size) per period"
        ),
        granularity=_P,
        collection_point=_cp(
            _HOOK_STORY_METRICS_PROCESSING_TIME_MIN,
            False,
            4,
            "No new event; RefreshWorker computes variance in Python"
            " (FK-61 §61.11.2, Class 4: runtime metric/projection)",
        ),
        domain=_D10,
    ))

    catalog.register(_kpi(
        kpi_id="processing_time_trend",
        name="Processing Time Trend",
        decision_question="Is average story processing time improving over time?",
        formula_repr="ROLLING_AVG(story_metrics.processing_time_min) per week",
        granularity=_P,
        collection_point=_cp(
            _HOOK_STORY_METRICS_PROCESSING_TIME_MIN,
            True,
            1,
            "RefreshWorker computes rolling average (FK-61 §61.11.1, Class 1)",
        ),
        domain=_D10,
    ))

    catalog.register(_kpi(
        kpi_id="qa_round_trend",
        name="QA Round Trend",
        decision_question="Is the average QA round count improving over time?",
        formula_repr="ROLLING_AVG(story_metrics.qa_rounds) per week",
        granularity=_P,
        collection_point=_cp(
            "story_metrics.qa_rounds",
            True,
            1,
            "RefreshWorker computes rolling average (FK-61 §61.11.1, Class 1)",
        ),
        domain=_D10,
    ))

    catalog.register(_kpi(
        kpi_id="files_changed_per_story",
        name="Files Changed per Story",
        decision_question="How many files does a story change on average (diff size trend)?",
        formula_repr="story_metrics.files_changed per story",
        granularity=_S,
        collection_point=_cp(
            "story_metrics.files_changed",
            True,
            1,
            "Closure via MetricsCollector (FK-61 §61.11.1, Class 1)",
        ),
        domain=_D10,
    ))

    catalog.register(_kpi(
        kpi_id="increment_count_per_story",
        name="Increment Count per Story",
        decision_question="How many increments does a story require (trend analysis)?",
        formula_repr="story_metrics.increments per story",
        granularity=_S,
        collection_point=_cp(
            "story_metrics.increments",
            True,
            1,
            "Closure via MetricsCollector (FK-61 §61.11.1, Class 1)",
        ),
        domain=_D10,
    ))
