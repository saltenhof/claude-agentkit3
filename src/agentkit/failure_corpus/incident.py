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
  (``FC-YYYY-NNNN``, global eindeutig, gap-free pro Jahr); die Triage erzeugt
  daher zunaechst einen ``IncidentDraft`` ohne id.
"""

from __future__ import annotations

import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from agentkit.core_types import FailureCategory, IncidentStatus
from agentkit.failure_corpus.types import IncidentId, IncidentRole, IncidentSeverity

# FK-41 §41.3.1/§41.4.1: incident_id ist ``FC-YYYY-NNNN`` (Jahr 4-stellig,
# Sequenz mindestens 4-stellig). Codex-r2: FAIL-CLOSED erzwingen.
_INCIDENT_ID_PATTERN = re.compile(r"^FC-\d{4}-\d{4,}$")


def _validate_evidence_list(value: object) -> list[str]:
    """FAIL-CLOSED: evidence MUSS eine Liste von Strings sein (FK-41 §41.4.1).

    Pydantic v2 wuerde ein ``dict`` sonst je nach Modus still durchwinken oder
    unklar koerzieren. Codex-r2: explizit hart machen — dict/freie JSON ist ein
    Vertragsbruch.
    """
    if not isinstance(value, list):
        raise ValueError(  # noqa: TRY004 — pydantic wraps ValueError into ValidationError
            f"evidence must be a list of strings (FK-41 §41.4.1), got {type(value)!r}"
        )
    if not all(isinstance(item, str) for item in value):
        raise ValueError("evidence items must all be strings (FK-41 §41.4.1)")
    return list(value)


def _validate_incident_id(value: str) -> str:
    """FAIL-CLOSED: incident_id MUSS ``FC-YYYY-NNNN`` sein (FK-41 §41.3.1)."""
    if _INCIDENT_ID_PATTERN.fullmatch(value) is None:
        raise ValueError(
            f"incident_id must match FC-YYYY-NNNN (FK-41 §41.3.1), got {value!r}"
        )
    return value


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

    @field_validator("evidence", mode="before")
    @classmethod
    def _check_evidence(cls, value: object) -> list[str]:
        return _validate_evidence_list(value)


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

    @field_validator("evidence", mode="before")
    @classmethod
    def _check_evidence(cls, value: object) -> list[str]:
        return _validate_evidence_list(value)


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

    @field_validator("incident_id", mode="before")
    @classmethod
    def _check_incident_id(cls, value: object) -> str:
        return _validate_incident_id(str(value))

    @field_validator("evidence", mode="before")
    @classmethod
    def _check_evidence(cls, value: object) -> list[str]:
        return _validate_evidence_list(value)


__all__ = [
    "Incident",
    "IncidentCandidate",
    "IncidentDraft",
]
