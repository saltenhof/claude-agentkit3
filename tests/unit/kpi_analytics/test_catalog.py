"""Unit tests for KpiCatalog, KpiDefinition, and related enums."""

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
    point = KpiCollectionPoint(hook_or_event="story_closure_event", data_available=True)
    with pytest.raises(ValidationError):
        point.hook_or_event = "other"  # type: ignore[misc]


def test_kpi_collection_point_notes_defaults_to_empty() -> None:
    point = KpiCollectionPoint(hook_or_event="evt", data_available=False)
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
            collection_point=KpiCollectionPoint(hook_or_event="evt", data_available=True),
            domain=KpiDomain.GOVERNANCE,
            unknown_field="boom",
        )


# ---------------------------------------------------------------------------
# KpiCatalog
# ---------------------------------------------------------------------------


def test_catalog_status_is_skeleton_by_default() -> None:
    catalog = KpiCatalog()
    assert catalog.catalog_status == CatalogStatus.SKELETON


def test_catalog_register_and_list() -> None:
    catalog = KpiCatalog()
    defn = _sample_definition()
    catalog.register(defn)

    result = catalog.list_definitions()

    assert len(result) == 1
    assert result[0].kpi_id == "qa_round_count"


def test_catalog_register_multiple_definitions() -> None:
    catalog = KpiCatalog()
    catalog.register(_sample_definition("kpi_a"))
    catalog.register(_sample_definition("kpi_b"))

    assert len(catalog.list_definitions()) == 2


def test_catalog_get_returns_definition() -> None:
    catalog = KpiCatalog()
    defn = _sample_definition("qa_round_count")
    catalog.register(defn)

    result = catalog.get("qa_round_count")

    assert result is not None
    assert result.kpi_id == "qa_round_count"


def test_catalog_get_returns_none_for_unknown_id() -> None:
    catalog = KpiCatalog()
    assert catalog.get("nonexistent") is None


def test_catalog_register_overwrites_duplicate_id() -> None:
    catalog = KpiCatalog()
    catalog.register(_sample_definition("qa_round_count"))
    updated = KpiDefinition(
        kpi_id="qa_round_count",
        name="Updated Name",
        decision_question="Updated question?",
        formula_repr="count(x)",
        granularity=KpiGranularity.PERIOD,
        collection_point=KpiCollectionPoint(hook_or_event="evt", data_available=False),
        domain=KpiDomain.QA_EFFECTIVENESS,
    )
    catalog.register(updated)

    result = catalog.list_definitions()
    assert len(result) == 1
    assert result[0].name == "Updated Name"
