"""Incident-Modelle des Failure-Corpus-BC (FK-41 §41.3.1/§41.4).

Blatt-Modul (KONFLIKT-2, AG3-028): ``Incident`` ist der Record-Typ, den der
``ProjectionAccessor`` ueber das ``_KIND_TO_RECORD_TYPE``-Mapping fuer
``ProjectionKind.FC_INCIDENTS`` aufloest. Damit dort kein Import-Zyklus
``failure_corpus`` <-> ``telemetry`` entsteht, importiert dieses Modul
ausschliesslich Foundation-Typen (``core_types``) und die BC-eigenen
``types`` — analog ``verify_system.stage_registry.records``, das telemetry
importiert, ohne telemetry zu importieren.

Quellen:
- FK-41 §41.3.1 -- fc_incidents-Felder (append-only, ein Datensatz pro incident_id)
- FK-41 §41.4 -- IncidentCandidate (Input) / Incident (Persistenz)
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from agentkit.core_types import FailureCategory, IncidentStatus
from agentkit.failure_corpus.types import IncidentId, IncidentSeverity


class IncidentCandidate(BaseModel):
    """Eingehender Incident-Kandidat (Input fuer ``record_incident``, FK-41 §41.4).

    Frozen/extra-forbid: ein Kandidat ist ein unveraenderlicher Eingabewert; ein
    unbekanntes Zusatzfeld ist ein Vertragsbruch (FAIL-CLOSED).

    Attributes:
        category: Failure-Kategorie (FK-41 §41.4.1, 12 Werte).
        severity: Incident-Schwere (FK-41 §41.4).
        source_bc: Erzeugender Bounded Context (governance-and-guards /
            verify-system / story-closure / implementation-phase).
        story_id: Story-Anker des Incidents.
        run_id: Run-Anker (NULL fuer run-uebergreifende Beobachtungen).
        summary: Verdichtete Symptombeschreibung.
        evidence: Frei strukturierte Belege (Verfeinerung in Folge-Stories).
        observed_at: Zeitpunkt der Beobachtung.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    category: FailureCategory
    severity: IncidentSeverity
    source_bc: str
    story_id: str
    run_id: str | None = None
    summary: str
    evidence: dict[str, Any] = Field(default_factory=dict)
    observed_at: datetime


class Incident(BaseModel):
    """Persistierter Incident (FK-41 §41.3.1, fc_incidents-Zeile).

    Frozen/extra-forbid: ein Incident ist append-only (genau ein Datensatz pro
    ``incident_id``); nach der Normalisierung wird er nicht mehr veraendert.

    Attributes:
        incident_id: Eindeutige Incident-Identitaet (PK).
        category: Failure-Kategorie (uebernommen vom Kandidaten).
        severity: Incident-Schwere (uebernommen vom Kandidaten).
        source_bc: Erzeugender Bounded Context.
        story_id: Story-Anker.
        run_id: Run-Anker (NULL moeglich).
        summary: Normalisierte Symptombeschreibung.
        evidence: Frei strukturierte Belege.
        observed_at: Zeitpunkt der Beobachtung.
        normalized_at: Zeitpunkt der Normalisierung durch die Triage.
        incident_status: Lebenszyklus-Zustand (Default ``OBSERVED``, FK-41 §41.3.1).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    incident_id: IncidentId
    category: FailureCategory
    severity: IncidentSeverity
    source_bc: str
    story_id: str
    run_id: str | None = None
    summary: str
    evidence: dict[str, Any] = Field(default_factory=dict)
    observed_at: datetime
    normalized_at: datetime
    incident_status: IncidentStatus = IncidentStatus.OBSERVED


__all__ = [
    "Incident",
    "IncidentCandidate",
]
