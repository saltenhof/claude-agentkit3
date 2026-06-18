"""Unit tests for KpiCatalog, KpiDefinition, and related enums.

AG3-118: catalog_status is now COMPLETE with 40 registered KPIs (FK-60 §60.4).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from agentkit.kpi_analytics.catalog import (
    CatalogStatus,
    KpiCatalog,
    KpiCollectionPoint,
    KpiDefinition,
    KpiDomain,
    KpiGranularity,
)


def _sample_definition(kpi_id: str = "qa_round_count") -> KpiDefinition:
    return KpiDefinition(
        kpi_id=kpi_id,
        name="QA Round Count",
        decision_question="Are stories well-specified?",
        formula_repr="count(qa_rounds) per story",
        granularity=KpiGranularity.STORY,
        collection_point=KpiCollectionPoint(
            hook_or_event="story_closure_event",
            data_available=True,
            source_owner_class=1,
        ),
        domain=KpiDomain.STORY_SIZING,
    )


# ---------------------------------------------------------------------------
# KpiGranularity
# ---------------------------------------------------------------------------


def test_kpi_granularity_values_are_str_enum() -> None:
    assert KpiGranularity.STORY == "STORY"
    assert KpiGranularity.ENTITY_PERIOD == "ENTITY_PERIOD"
    assert KpiGranularity.PERIOD == "PERIOD"


# ---------------------------------------------------------------------------
# KpiDomain
# ---------------------------------------------------------------------------


def test_kpi_domain_has_ten_values() -> None:
    """FK-60 §60.4 defines exactly ten domains."""
    assert len(KpiDomain) == 10


def test_kpi_domain_covers_all_fk60_domains() -> None:
    expected = {
        "STORY_SIZING",
        "LLM_SELECTION",
        "GOVERNANCE",
        "DOC_FIDELITY",
        "QA_EFFECTIVENESS",
        "REVIEW_QUALITY",
        "VECTORDB",
        "ARE_INTEGRATION",
        "FAILURE_CORPUS",
        "PROCESS_EFFICIENCY",
    }
    assert {d.value for d in KpiDomain} == expected


# ---------------------------------------------------------------------------
# KpiCollectionPoint
# ---------------------------------------------------------------------------


def test_kpi_collection_point_is_frozen() -> None:
    point = KpiCollectionPoint(
        hook_or_event="story_closure_event",
        data_available=True,
        source_owner_class=1,
    )
    with pytest.raises(ValidationError):
        point.hook_or_event = "other"  # type: ignore[misc]


def test_kpi_collection_point_notes_defaults_to_empty() -> None:
    point = KpiCollectionPoint(hook_or_event="evt", data_available=False, source_owner_class=2)
    assert point.notes == ""


# ---------------------------------------------------------------------------
# KpiDefinition
# ---------------------------------------------------------------------------


def test_kpi_definition_is_frozen() -> None:
    defn = _sample_definition()
    with pytest.raises(ValidationError):
        defn.kpi_id = "other"  # type: ignore[misc]


def test_kpi_definition_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        KpiDefinition(  # type: ignore[call-arg]
            kpi_id="x",
            name="X",
            decision_question="?",
            formula_repr="count(x)",
            granularity=KpiGranularity.STORY,
            collection_point=KpiCollectionPoint(
                hook_or_event="evt",
                data_available=True,
                source_owner_class=1,
            ),
            domain=KpiDomain.GOVERNANCE,
            unknown_field="boom",
        )


# ---------------------------------------------------------------------------
# KpiCatalog — AG3-118: status is COMPLETE with 40 KPIs
# ---------------------------------------------------------------------------


def test_catalog_status_is_complete() -> None:
    """AG3-118: catalog_status is COMPLETE (was SKELETON in skeleton era)."""
    catalog = KpiCatalog()
    assert catalog.catalog_status == CatalogStatus.COMPLETE


def test_catalog_contains_exactly_40_kpis() -> None:
    """AG3-118: exactly 40 AKTIV-KPIs registered (FK-60 §60.4.12)."""
    catalog = KpiCatalog()
    assert len(catalog.list_definitions()) == 40


def test_catalog_register_and_list() -> None:
    """Register adds a definition; list_definitions returns it."""
    catalog = KpiCatalog()
    initial_count = len(catalog.list_definitions())
    defn = _sample_definition("test_extra_kpi")
    catalog.register(defn)

    result = catalog.list_definitions()

    assert len(result) == initial_count + 1
    assert any(d.kpi_id == "test_extra_kpi" for d in result)


def test_catalog_register_multiple_definitions() -> None:
    catalog = KpiCatalog()
    initial_count = len(catalog.list_definitions())
    catalog.register(_sample_definition("kpi_extra_a"))
    catalog.register(_sample_definition("kpi_extra_b"))

    assert len(catalog.list_definitions()) == initial_count + 2


def test_catalog_get_returns_definition() -> None:
    catalog = KpiCatalog()
    # qa_round_count is a real registered KPI
    result = catalog.get("qa_round_count")

    assert result is not None
    assert result.kpi_id == "qa_round_count"


def test_catalog_get_returns_none_for_unknown_id() -> None:
    catalog = KpiCatalog()
    assert catalog.get("nonexistent") is None


def test_catalog_register_overwrites_duplicate_id() -> None:
    catalog = KpiCatalog()
    initial_count = len(catalog.list_definitions())
    updated = KpiDefinition(
        kpi_id="qa_round_count",
        name="Updated Name",
        decision_question="Updated question?",
        formula_repr="count(x)",
        granularity=KpiGranularity.PERIOD,
        collection_point=KpiCollectionPoint(
            hook_or_event="evt",
            data_available=False,
            source_owner_class=1,
        ),
        domain=KpiDomain.QA_EFFECTIVENESS,
    )
    catalog.register(updated)

    result = catalog.list_definitions()
    # Overwrite should not increase count
    assert len(result) == initial_count
    assert catalog.get("qa_round_count").name == "Updated Name"  # type: ignore[union-attr]
