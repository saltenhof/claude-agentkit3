"""KPI catalog: typed registry of KPI definitions.

KpiCatalog is a skeleton in AG3-029. The full 40-KPI population
is a follow-up story. CatalogStatus.SKELETON signals that
consumers MUST NOT rely on completeness.
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
    """Domaene 1: Story-Dimensionierung und Pipeline-Steuerung"""

    LLM_SELECTION = "LLM_SELECTION"
    """Domaene 2: LLM-Selektion und -Performance"""

    GOVERNANCE = "GOVERNANCE"
    """Domaene 3: Governance-Gesundheit"""

    DOC_FIDELITY = "DOC_FIDELITY"
    """Domaene 4: Dokumententreue und Konzept-Konformitaet"""

    QA_EFFECTIVENESS = "QA_EFFECTIVENESS"
    """Domaene 5: QA-Effektivitaet"""

    REVIEW_QUALITY = "REVIEW_QUALITY"
    """Domaene 6: Review-Qualitaet und Evidence Assembly"""

    VECTORDB = "VECTORDB"
    """Domaene 7: VektorDB und Wissensmanagement"""

    ARE_INTEGRATION = "ARE_INTEGRATION"
    """Domaene 8: ARE-Integration"""

    FAILURE_CORPUS = "FAILURE_CORPUS"
    """Domaene 9: Failure Corpus und Lernschleife"""

    PROCESS_EFFICIENCY = "PROCESS_EFFICIENCY"
    """Domaene 10: Prozess-Effizienz und Trends"""


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
        notes: Optional free-text notes about the collection point.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    hook_or_event: str
    data_available: bool
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
    """In-memory registry for KPI definitions.

    In AG3-029 this is a skeleton only.  ``catalog_status`` is pinned to
    ``CatalogStatus.SKELETON`` until a follow-up story populates all 40 KPIs
    from FK-60 §60.4.  Consumers MUST NOT rely on ``list_definitions()``
    returning a complete set.

    Google-style:
        Attributes:
            catalog_status: Always ``SKELETON`` in AG3-029.
    """

    catalog_status: CatalogStatus = CatalogStatus.SKELETON

    def __init__(self) -> None:
        self._definitions: dict[str, KpiDefinition] = {}

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
