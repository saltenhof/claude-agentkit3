"""Incident-Modelle des Failure-Corpus-BC (FK-41 §41.3.1/§41.4.1).

Blatt-Modul (KONFLIKT-2, AG3-028): ``Incident`` ist der Record-Typ, den der
``ProjectionAccessor`` ueber das ``_KIND_TO_RECORD_TYPE``-Mapping fuer
``ProjectionKind.FC_INCIDENTS`` aufloest. Damit dort kein Import-Zyklus
``failure_corpus`` <-> ``telemetry`` entsteht, importiert dieses Modul
ausschliesslich Foundation-Typen (``core_types``) und die BC-eigenen
``types`` — analog ``verify_system.stage_registry.records``, das telemetry
importiert, ohne telemetry zu importieren.

Schema-Treue zu FK-41 §41.3.1/§41.4.1 (Codex-r1 Remediation 2026-06-01):
- Pflichtfelder: project_key, incident_id (FC-YYYY-NNNN), run_id, story_id,
  category, severity, phase, role, model, symptom, evidence (list[str]),
  recorded_at, incident_status.
- Optional: tags, impact, pattern_ref.
- ``evidence`` ist eine Liste von Strings (FK-41 §41.4.1), kein dict.
- ``incident_id`` wird DB-seitig in der Schreibtransaktion vergeben
  (``FC-YYYY-NNNN``, gap-free pro (project_key, Jahr)); die Triage erzeugt
  daher zunaechst einen ``IncidentDraft`` ohne id.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from agentkit.core_types import FailureCategory, IncidentStatus
from agentkit.failure_corpus.types import IncidentId, IncidentRole, IncidentSeverity


class IncidentCandidate(BaseModel):
    """Eingehender Incident-Kandidat (Input fuer ``record_incident``, FK-41 §41.4.1/§41.4.2).

    Frozen/extra-forbid: ein Kandidat ist ein unveraenderlicher Eingabewert; ein
    unbekanntes Zusatzfeld ist ein Vertragsbruch (FAIL-CLOSED).

    Neben den FK-41-§41.4.1-Persistenzfeldern traegt der Kandidat die
    **Gate-Inputs** fuer die Aufnahmekriterien (FK-41 §41.4.3): ``merge_blocked``
    und ``rework_minutes``. Diese werden NICHT in ``fc_incidents`` gespeichert —
    sie steuern nur die ``IngressCriteria``-Entscheidung.

    Attributes:
        project_key: Projekt-Schluessel (Pflicht; Abfragen sind stets
            projektgebunden, FK-41 §41.3.1).
        story_id: Story-Anker des Incidents.
        run_id: Run-Anker (Pflicht, FK-41 §41.3.1).
        category: Failure-Kategorie (FK-41 §41.4.1, 12 Werte).
        severity: Incident-Schwere (FK-41 §41.3.1, 4 Stufen).
        phase: Betroffene Pipeline-Phase.
        role: Ausfuehrender Akteur (worker | qa | governance, FK-41 §41.3.1).
        model: Verwendetes LLM-Modell.
        symptom: Freitextbeschreibung des Fehlerbildes.
        evidence: Liste von Evidenz-Strings (FK-41 §41.4.1).
        tags: Optionale Schlagworte.
        impact: Optionale Auswirkungsbeschreibung.
        merge_blocked: Gate-Input (FK-41 §41.4.3) — ob der Befund den Merge
            blockiert hat. NICHT persistiert.
        rework_minutes: Gate-Input (FK-41 §41.4.3) — Rework-Aufwand in Minuten.
            NICHT persistiert.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    project_key: str
    story_id: str
    run_id: str
    category: FailureCategory
    severity: IncidentSeverity
    phase: str
    role: IncidentRole
    model: str
    symptom: str
    evidence: list[str] = Field(default_factory=list)
    tags: list[str] | None = None
    impact: str | None = None
    # Gate-Inputs (FK-41 §41.4.3) — nicht Bestandteil von fc_incidents.
    merge_blocked: bool = False
    rework_minutes: int = 0


class IncidentDraft(BaseModel):
    """Normalisierter, noch nicht persistierter Incident (vor id-Allokation).

    Traegt alle FK-41-§41.3.1-Persistenzfelder ausser ``incident_id`` (das wird
    DB-seitig in der Schreibtransaktion als ``FC-YYYY-NNNN`` vergeben) und
    ``recorded_at`` ist gesetzt (Normalisierungszeitpunkt). Die Gate-Inputs des
    Kandidaten (``merge_blocked``/``rework_minutes``) sind hier bewusst NICHT
    mehr enthalten — sie sind kein Persistenz- und kein Read-Model-Bestandteil.

    Frozen/extra-forbid.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    project_key: str
    story_id: str
    run_id: str
    category: FailureCategory
    severity: IncidentSeverity
    phase: str
    role: IncidentRole
    model: str
    symptom: str
    evidence: list[str] = Field(default_factory=list)
    recorded_at: datetime
    incident_status: IncidentStatus = IncidentStatus.OBSERVED
    tags: list[str] | None = None
    impact: str | None = None
    pattern_ref: str | None = None


class Incident(BaseModel):
    """Persistierter Incident (FK-41 §41.3.1, fc_incidents-Zeile).

    Frozen/extra-forbid: ein Incident ist append-only (genau ein Datensatz pro
    ``incident_id``); nach der Normalisierung wird er nicht mehr veraendert.

    Attributes:
        project_key: Projekt-Schluessel (Pflicht, FK-41 §41.3.1).
        incident_id: Eindeutige Incident-Identitaet (PK, Format ``FC-YYYY-NNNN``).
        run_id: Run-Anker (Pflicht, FK-41 §41.3.1).
        story_id: Story-Anker.
        category: Failure-Kategorie.
        severity: Incident-Schwere.
        phase: Betroffene Pipeline-Phase.
        role: Ausfuehrender Akteur (worker | qa | governance).
        model: Verwendetes LLM-Modell.
        symptom: Symptombeschreibung (normalisiert).
        evidence: Liste von Evidenz-Strings.
        recorded_at: Erfassungszeitpunkt.
        incident_status: Lebenszyklus-Zustand (Default ``OBSERVED``, FK-41 §41.3.1).
        tags: Optionale Schlagworte.
        impact: Optionale Auswirkungsbeschreibung.
        pattern_ref: Optionaler Verweis auf fc_patterns.pattern_id (nach Clustering).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    project_key: str
    incident_id: IncidentId
    run_id: str
    story_id: str
    category: FailureCategory
    severity: IncidentSeverity
    phase: str
    role: IncidentRole
    model: str
    symptom: str
    evidence: list[str] = Field(default_factory=list)
    recorded_at: datetime
    incident_status: IncidentStatus = IncidentStatus.OBSERVED
    tags: list[str] | None = None
    impact: str | None = None
    pattern_ref: str | None = None


__all__ = [
    "Incident",
    "IncidentCandidate",
    "IncidentDraft",
]
