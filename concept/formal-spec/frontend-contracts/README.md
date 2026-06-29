---
title: Frontend Contracts Formal Spec
status: active
doc_kind: context
---

# Frontend Contracts

Dieser Kontext formalisiert den maschinenpruefbaren Teil der
Schnittstellen zwischen dem AK3-Web-Frontend (FK-72) und dem
BFF/Control-Plane. Er ist die normative Quelle fuer alle
Read-Models, Mutationen und Live-Events, die ein Web-Konsument
gegen die Control-Plane verwendet.

## Scope

Im Scope sind:

- **Read-Models**: Snapshots, die das Frontend per `GET` aus der
  Control-Plane zieht (Stories, Project, Execution-Input, Flow,
  Limits, Counters, Mode-Lock).
- **Mutating-Commands**: alle Operationen, die das Frontend gegen
  die Control-Plane ausloest (Story-Anlage, Status-Transitionen,
  Inline-Stammdaten-Edits, Limits-Update).
- **Live-Events**: die ueber SSE projizierten Event-Schemas pro
  Topic auf `/v1/projects/{key}/events` (FK-72 §72.12, FK-91 §91.8).
- **Konsistenz-Invarianten**: Initial-GET-plus-SSE-Subscribe-Vertrag,
  Lossy-Re-Sync, Determinismus der Execution-Input-Triage und
  Owner-BC-Portquellen fuer jedes Read-Model.

## Out of Scope

Bewusst **nicht** Teil dieses Kontexts:

- **LLM-Hub-Integration**: `/v1/events/hub` und Hub-Cockpit. Hub ist
  ein separater Foundation-Adapter (FK-75). Die Formalisierung
  bleibt zurueckgestellt, solange die Hub-View nicht produktiv ist.
- **Analytics-Dashboard** (Hauptsicht): KPI-Definitionen,
  Zeitverlaeufe und Aggregat-Endpoints. KPI-Semantik ist Eigentum
  von `kpi-and-dashboard` (FK-60..63) und bleibt dort.
- **Story-spezifischer Inspector-KPI-Tab**: Bleibt im Frontend
  sichtbar, die Lieferform wird hier nicht detailliert formalisiert
  (Inhalt entsteht aus `kpi-and-dashboard`-eigenen Read-Models).
- **Backend-internes Producer-Verhalten**: Telemetrie-Erhebung,
  Read-Model-Materialisierung. Das ist Eigentum von
  `telemetry-analytics` (FK-68/69). Hier wird nur der
  Wire-Vertrag ueber SSE festgelegt, nicht wie er entsteht.
- **Project-Edge-Bundle / Agent-Pfad**: Endpunkte, die nur fuer
  Agents oder den `Project Edge Client` relevant sind (z. B.
  `/v1/project-edge/sync`, `/v1/story-runs/.../phases/start`).
  Diese gehoeren zu den jeweiligen BC-Specs, nicht hier.

## Dateien

| Datei | Inhalt |
|---|---|
| `entities.md` | Read-Model-Entitaeten, Identifier, Pflichtattribute |
| `commands.md` | Schreibende Operationen aus dem Frontend, Endpoint-Bindings, erlaubte Vorzustaende |
| `events.md` | SSE-Topics und Event-Schemas auf dem projekt-skopierten Stream |
| `invariants.md` | Konsistenz Snapshot↔Stream, Triage-Determinismus, Mode-Lock-Ableitung |

## Prosa-Quellen

- [FK-72](/T:/codebase/claude-agentkit3/concept/technical-design/72_frontend_architektur.md) — Frontend-Architektur, App-Shell, SSE-Mechanismus
- [FK-91](/T:/codebase/claude-agentkit3/concept/technical-design/91_api_event_katalog.md) — REST-Endpoint-Katalog, SSE-Endpoints
- [FK-70](/T:/codebase/claude-agentkit3/concept/technical-design/70_story_planung_abhaengigkeiten_ausfuehrungsplanung.md) — Execution-Input-Top-Surface (§70.8a)
- [FK-39](/T:/codebase/claude-agentkit3/concept/technical-design/39_phase_state_persistenz.md) — Phase-State-Projektion (Flow-Quelle)
- [FK-24](/T:/codebase/claude-agentkit3/concept/technical-design/24_story_type_mode_terminalitaet.md) — Story-Mode, Mode-Lock
- [FK-59](/T:/codebase/claude-agentkit3/concept/technical-design/59_story_contract_axes_and_combination_matrix.md) — Story-Vertragsachsen

## Verhaeltnis zu anderen formalen Kontexten

- **`telemetry-analytics`**: Producer der projektbezogenen Live-Events.
  `frontend-contracts.events` ist die Wire-Sicht, die das Frontend
  erhaelt; `telemetry-analytics.events` beschreibt die Erhebung.
- **`execution-planning`**: Owner der Triage-Logik fuer den
  Execution-Input-Selektor. `frontend-contracts.entities` traegt das
  Lieferformat, die Logik bleibt in `execution-planning`.
- **`story-workflow`**, **`exploration`**, **`verify`**, **`story-closure`**:
  Owner der Phasen-/Substep-Zustaende. `frontend-contracts.entities`
  projiziert den jeweils aktuellen Zustand fuer die FlowTab; eigene
  Status-Definitionen entstehen hier nicht.

Die Reihenfolge ist: Owner-BC definiert die Semantik, FK-91 listet die
HTTP-Bindung, `frontend-contracts` formalisiert das Wire-Format fuer
den Web-Konsumenten. Jede Read-Model-Quelle bleibt ein fachlicher Port
des Owner-BCs; Control-Plane/BFF darf diese Ports orchestrieren, aber
keine Tabellen, StateBackend-Loader oder Repository-DTOs fremder BCs als
Ersatzschnittstelle verwenden. Keine zweite Wahrheitsquelle.
