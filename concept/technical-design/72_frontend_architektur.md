---
concept_id: FK-72
title: Frontend-Architektur — BC-aligned Schnitt, App-Shell und Foundation-Bereiche
module: frontend
cross_cutting: true
status: active
doc_kind: core
parent_concept_id:
authority_over:
  - scope: frontend-cut
  - scope: app-shell
  - scope: bff-topology
  - scope: frontend-views-inventory
  - scope: frontend-wire-contracts
defers_to:
  - target: FK-07
    scope: component-architecture
    reason: BC-Schnitt und Bluttypen werden in FK-07 normiert
  - target: FK-91
    scope: api-catalog
    reason: BFF-Endpunkte werden im API-Katalog dokumentiert
  - target: FK-64
    scope: control-plane-design-system
    reason: Design-System bleibt eigenes Konzept
supersedes: []
superseded_by:
tags: [frontend, app-shell, bff, ui, react, multi-bc]
prose_anchor_policy: strict
formal_refs:
  - formal.frontend-contracts.entities
  - formal.frontend-contracts.commands
  - formal.frontend-contracts.events
  - formal.frontend-contracts.invariants
---

# 72 — Frontend-Architektur

## 72.1 Zweck

Das AK3-Frontend ist die Mensch-Maschine-Schnittstelle, durch die ein
Stratege die agentische Software-Entwicklung supervisiert, steuert und
auswertet. Es ist nicht „Story-Cockpit" als Selbstzweck, sondern die
Sichtbarmachung des Kernauftrags von AK3: Agenten unterstuetzen,
ueberwachen, korrigieren und so Skalierbarkeit ermoeglichen.

Das Frontend lebt im selben Monorepo, aber in einem **getrennten
Source-Tree** (TypeScript/React, kein Python).

## 72.2 Schnittprinzip — BC-aligned vertikal

Das Frontend ist gespiegelt zum Backend geschnitten: jeder
fachliche BC, der UI-Belange traegt, liefert seinen eigenen
**Frontend-Slice**. Eine separate **Klammer** (App-Shell)
haelt das Ganze zusammen.

Es gibt **keinen** UI-BC, kein „Cockpit"-Aggregator, keinen God-View.
Cross-BC-Sichten (Story-Inspector, Story-Board, Story-Sheet) sind
Composer-Sichten in der App-Shell, deren Inhalt aus den
BC-Slices stammt.

## 72.3 Source-Tree

```
frontend/src/
  app_shell/                  # Klammer (R, kein A-BC)
    routing/                  # URL-Hash → ViewMode
    layout/                   # Sidebar, Topbar, Workspace-Frame
    inspector/                # DetailInspector inkl. globaler Selection-/Escape-Tastatur
    search/                   # globale Suche, Cross-BC-Dispatch

  design_system/              # Tokens, Primitives, Badge, Sparkline, ak-panel etc.

  contexts/                   # BC-aligned Slices
    project_management/
    story_context_manager/
    execution_planning/
    pipeline_engine/
    verify_system/
    governance/
    closure/
    artifacts/
    telemetry/
    kpi_analytics/
    failure_corpus/
    requirements_coverage/

  foundation/                 # parallel zu BCs: eigene R-Foundation-Bereiche
    concept_catalog/
    multi_llm_hub/
```

BCs ohne Frontend-Slice in der ersten Iteration: `exploration`,
`implementation`, `prompt_runtime`, `skills`, `installer`. Diese haben
heute keine eigenstaendigen Sichten oder Inspector-Tab-Beitraege.

## 72.4 App-Shell als R-Klammer

Die Shell ist Bluttyp **R** (kein A-BC). Sie traegt **keine**
fachlichen Aussagen. Was sie leistet:

- Routing, Layout, Theme, Auth, Tenant-Scope (`project_key`)
- DetailInspector als Composer-Wirt — die Tabs holen Inhalt aus den
  BC-Slices und reihen sie auf
- Globale Suche dispatcht parallel an mehrere BC-API-Slices und
  reiht die Treffer
- Globale Tastatur (ArrowUp/Down zur Auswahl, Escape zum Schliessen)
  als Implementierungsdetail von `inspector/`
- Komposition der Cross-BC-Karten in Kanban und Sheet (Inhalt aus
  mehreren BCs, Layout in der Shell)

Harte Regel: **sobald die Shell etwas wie „Story ist ready fuer
Closure" berechnet, ist der Schnitt falsch.** Solche Aussagen gehoeren
in den jeweiligen Owner-BC.

Der Topbar-Projekt-Selector wird vom `contexts/project_management/`
als Slot-Komponente in der App-Shell-Layout-Region gerendert. Die
Shell stellt nur den Slot.

## 72.5 Sichten-Inventar und BC-Mapping

Die Hauptnavigation der Web-App fuehrt **fuenf** Top-Sichten:
Graph, Kanban, Sheet, Analytics und Hub. Die Sichten 6/7
(Wave-/Readiness, Konfiguration praktische Parallelisierbarkeit)
sind keine eigenstaendigen Hauptmenue-Eintraege, sondern
**Sub-Tabs** unter Graph. Der Concept-Browser ist eine
Foundation-Sicht und nicht zwingend Teil der Hauptnavigation.

| # | Sicht | Primaerer BC / Foundation | Mitliefernd | Charakter |
|---|---|---|---|---|
| 1 | Graph (Top-Sicht mit Sub-Tabs) | `execution_planning` | `story_context_manager` | Single-BC + Composer |
| 1a | Sub-Tab `graph` (Dependency-Graph) | `execution_planning` | `story_context_manager` | Single-BC |
| 1b | Sub-Tab `ready` (Execution-Input) | `execution_planning` | `story_context_manager` | Composer, Lese-Pfad |
| 1c | Sub-Tab `limits` (Execution-Limits) | `execution_planning` | — | Single-BC, Schreibpfad |
| 2 | Kanban | `story_context_manager` | `pipeline_engine`, `verify_system`, `governance` | Composer |
| 3 | Sheet | `story_context_manager` | viele | Composer |
| 4 | Analytics | `kpi_analytics` (Komposition) | `telemetry`, `verify_system`, `failure_corpus`, `pipeline_engine` | Composer |
| 5 | Hub | Foundation `multi_llm_hub` | — | Foundation |
| 6 | Concept-Browser | Foundation `concept_catalog` | viele Konsumenten | Foundation |

Der `ready`-Sub-Tab projiziert die Execution-Input-Top-Surface aus
FK-70 §70.8a.1; der `limits`-Sub-Tab ist die Schreib-Sicht auf
dieselbe Caps-Sphaere. Beide Sub-Tabs teilen denselben deterministischen
Selektor (FK-70 §70.8a.3) und werden ueber denselben SSE-Topic
`planning` live aktuell gehalten.

Die App-Shell rendert zusaetzlich eine **Topbar-Komposition**, die
nicht als eigene Sicht zaehlt:

| Element | BC-Quelle | Charakter |
|---|---|---|
| Project-Selector (Dropdown) | `project_management` | Schreibpfad: aktives Projekt waehlen |
| ModeIndicator (Standard/Fast/Idle) | `story_context_manager` (Mode-Lock) | Lese-Pfad, abgeleitet aus laufenden Stories (FK-24 §24.3.3) |
| Global Search | App-Shell, dispatcht an mehrere BCs | Lese-Pfad |
| `+Story`-Button | `story_context_manager` | Schreibpfad: Anlage |

## 72.6 Inspector-Tabs

Der Story-Inspector traegt **vier** Tabs in fester Reihenfolge.

| Tab | Primaerer BC | Mitliefernd |
|---|---|---|
| Spezifikation | `story_context_manager` | `requirements_coverage`, `governance`, `concept_catalog` |
| Ergebnis (Evidence) | `artifacts` | `pipeline_engine`, `verify_system`, `telemetry`, `governance`, `requirements_coverage` |
| KPIs | `kpi_analytics` | `telemetry` |
| Ablauf (Flow) | `pipeline_engine` | `story_context_manager`, `exploration`, `verify_system`, `closure` |

Der `Ablauf`-Tab projiziert die kanonische
`phase-state-projection` (FK-39) in eine Wire-Sicht mit
Phasen-, Substep- und Loop-Iteration-Zustaenden (siehe
§72.14). Im Fast-Mode bleibt die Exploration-Phase sichtbar,
aber als `skipped` gefuehrt und ohne Substeps (FK-24 §24.3.3).

## 72.7 Schreibpfade

UI-Aktionen mit Effekt gehen vom BFF **direkt** an den Owner-BC,
nicht ueber einen Composer:

| Aktion | Owner-BC |
|---|---|
| `+Story` (Anlage) | `story_context_manager` (zieht Praefix aus `project_management`) |
| Status-Drag&Drop | `pipeline_engine` (Lifecycle) |
| Sheet-Inline-Editing | `story_context_manager` (Stammdaten) |
| Parallelisierungs-Konfig | `execution_planning` |

## 72.8 BFF-Topologie

**Ein** Server-Prozess, BC-aligned Module. Pro BC ein Routes-Modul.

### 72.8.1 URL-Konvention

Die kanonische URL-Form ist **projekt-skopiert** im Pfad:

```
/v1/projects/{project_key}/<bc>/<resource>
```

Der `project_key` ist Pflicht-Pfadparameter auf allen Endpunkten,
die mit Projekt-bezogenen Ressourcen arbeiten (Stories, Phasen,
KPIs, Coverage, Telemetrie, Closure, Artefakte etc.). Cross-Cutting
gilt: jeder dieser Endpunkte filtert lesend und mutierend ueber
`project_key`. Die Middleware in `control_plane_http` validiert
`project_key` und blockiert, falls das Projekt nicht existiert oder
archiviert ist.

Endpunkte, die *nicht* projekt-bezogen sind (z. B. Liste aller Projekte,
Hub-Status, Concept-Browser), liegen unter `/v1/<bc>/<resource>` ohne
Projekt-Praefix.

### 72.8.2 Modul-Aufteilung

```
agentkit/control_plane_http/        # App, Auth, Tenant-Scope-Middleware, Router-Registry
agentkit/project_management/http/   # /v1/projects (nicht projekt-skopiert; Liste/CRUD)
agentkit/story_context_manager/http/  # /v1/projects/{key}/stories
agentkit/execution_planning/http/   # /v1/projects/{key}/planning, /v1/projects/{key}/planning/next-ready, /v1/projects/{key}/planning/config
agentkit/pipeline_engine/http/      # /v1/projects/{key}/phases
agentkit/verify_system/http/        # /v1/projects/{key}/verify
agentkit/governance/http/           # /v1/projects/{key}/governance
agentkit/closure/http/              # /v1/projects/{key}/closure
agentkit/artifacts/http/            # /v1/projects/{key}/artifacts
agentkit/telemetry/http/            # /v1/projects/{key}/telemetry
agentkit/kpi_analytics/http/        # /v1/projects/{key}/kpi
agentkit/failure_corpus/http/       # /v1/projects/{key}/failure-corpus
agentkit/requirements_coverage/http/  # /v1/projects/{key}/coverage (inkl. /coverage/stories/{story_id}/are-evidence)
agentkit/concept_catalog/http/      # /v1/concepts (projektneutral, Konzept-Korpus ist Repository-weit)
agentkit/multi_llm_hub/http/        # /v1/hub (projektneutral, Hub-Mechanik nicht projekt-skopiert)
```

`control_plane_http` hostet App, Auth, Tenant-Scope, Router-Registry.
Keine Microservices. Der offizielle API-Vertrag im Detail liegt in
**FK-91**.

## 72.9 Foundation-Bereiche

Zwei Foundation-Bereiche stehen **parallel** zu den BC-Slices:

- **`concept_catalog`** (FK-74) — FK-Doc-Verlinkung, conceptRefs-Resolver, Markdown-Rendering, Backlinks. Wird von governance, requirements_coverage, story_context_manager und Frontend (Concept-Browser) konsumiert.
- **`multi_llm_hub`** (FK-75) — Adapter zum externen Multi-LLM-Hub (Pflicht-Dependency). Liefert Sessions, Backend-Metriken, proxy-iert Send-Operationen.

Beide sind Bluttyp **R**, keine A-BCs.

## 72.10 Was nicht zur Frontend-Architektur gehoert

- **KPI-Definitionen** — bleiben in `kpi_analytics` (FK-60). Frontend zeigt sie nur.
- **Story-Lifecycle-Regeln** — bleiben in `pipeline_engine`. Frontend triggert nur Aktionen.
- **Konzepte** — die Markdown-Dokumente selbst sind nicht UI; das Frontend ist nur ihr Browser-Konsument.
- **Lint-/Conformance-Regeln** — `entities.md` traegt heute keine Frontend-Slices als formale Eintraege. Frontend-Code ist nicht Python und nicht im Scope der Architektur-Konformanz.

## 72.11 Kontext-Sichten ohne eigene Hauptansicht

Einige BC-Beitraege erscheinen ausschliesslich als Panels in
Composer-Sichten oder als Inspector-Tab-Anteile, nicht als
eigenstaendige Hauptsicht:

- `governance` — Guard-/Hook-Status als Kanban-Beitrag und im Inspector-Evidence
- `closure` — Closure-Anteil im Inspector-Evidence
- `artifacts` — Bundle-Liste/Manifest im Inspector-Evidence
- `failure_corpus` — Funnel in Analytics, kein eigenes Browser-View in v1

Wenn fuer einen dieser Bereiche eine eigene Hauptansicht entstehen
soll, kann sie nachgeschoben werden — der Schnitt erlaubt das ohne
Aenderung der Klammer.

## 72.12 Live-Updates: SSE als einheitlicher Mechanismus

Frontend und BFF kommunizieren Live-Updates ueber **Server-Sent
Events (SSE)** — ein einheitlicher Mechanismus fuer alle Sichten,
kein Polling.

### 72.12.1 Pattern: Initial-GET plus SSE-Subscribe

Jede Sicht macht beim Oeffnen genau zwei Dinge:

1. **Initial-GET** auf den fachlichen REST-Endpoint (z. B.
   `GET /v1/projects/{key}/stories`) holt den aktuellen Snapshot.
2. **SSE-Subscribe** auf einen Event-Stream mit Topics-Filter
   (z. B. `GET /v1/projects/{key}/events?topics=stories,phases`)
   empfaengt Updates.

Bei einem relevanten Event entweder lokal patchen oder gezielt
re-fetchen. Ein Polling-Loop existiert nicht.

### 72.12.2 Endpoint-Form

| Endpoint | Skoping | Inhalt |
|---|---|---|
| `GET /v1/projects/{key}/events` | projekt-skopiert | alle projektbezogenen Events: Story-Lifecycle, Phasen, QA-Pruefungen, Telemetrie, Closure |
| `GET /v1/events/hub` | projektneutral | Hub-spezifische Events (Backend-Status, Slot-Belegung, Session-Antworten) |

`?topics=`-Filter ist eine Komma-getrennte Liste der Event-Topics, die
die Sicht braucht. Server filtert serverseitig, Frontend bekommt nur,
was es bestellt hat.

### 72.12.3 Producer

Der Single-Producer fuer projektbezogene Events ist
**`telemetry`**: andere BCs schreiben Events in `telemetry`, der
SSE-Endpoint liest aus `telemetry` und serialisiert. Damit gibt es
genau eine Quelle und genau eine Reihenfolge fuer projektbezogene
Live-Daten.

Der Hub-Stream (`/v1/events/hub`) ist die Ausnahme: er wird vom
`multi_llm_hub`-Adapter bedient, weil die Daten im externen Hub
entstehen und nicht ueber `telemetry` laufen.

### 72.12.4 Lossy mit Re-Sync

SSE ist **lossy**: bei Backpressure droppt der Server Events. Das
Frontend muss bei jedem Connection-Aufbau (initial oder Reconnect)
einen frischen Initial-GET machen, um den vollstaendigen Stand zu
holen. Reconnect-Logik ist im Browser-EventSource-Standard
enthalten und funktioniert automatisch.

Kein Sequence-ID-/Cursor-Mechanismus, kein Acknowledge-Protokoll. Der
Re-Sync ueber Initial-GET reicht fuer einen lokalen Stratege-Tool.

### 72.12.5 Auth fuer SSE

Der SSE-Endpoint folgt der Auth-Regel der jeweiligen Schicht (siehe
FK-15 §15.10): UI-BFF-SSE-Streams nutzen das Strategen-Cookie,
Project-API-SSE-Streams (sofern noetig) nutzen das Thin-Client-Token.

### 72.12.6 Event-Catalog

Der vollstaendige Katalog der ueber SSE gestreamten Event-Topics und
Event-Schemas ist Teil von **FK-91 (API- und Event-Katalog)**.
FK-72 legt nur den Mechanismus fest, nicht das Ereignisinventar.

## 72.13 Prototyp als normative Quelle fuer UI-Verhalten

Frontend-UI-Verhalten — Funktionen, Layout, UX-Bedienung, visuelle
Konventionen — wird **nicht im Konzept-Korpus auf Markdown-Ebene
spezifiziert**. Stattdessen ist der **versionierte UI-Prototyp**
unter `frontend/prototype/` die normative Quelle.

### 72.13.1 Begruendung

UI-Verhalten ist auf Papier nur eingeschraenkt definierbar. Aufwand
und Genauigkeit eines Prototyps in Code sind in Summe niedriger als
ein vollstaendiges schriftliches Pflichtenheft jeder Sicht. Der
Prototyp ist gleichzeitig:

- Funktionsumfang (welche Sichten, welche Aktionen)
- Layout-Definition (welche Komposition)
- UX-Vertrag (welche Tastatur, welcher Drag&Drop, welche Resize-,
  Filter- und Group-by-Verhalten)
- visuelle Sprache (Farben, Abstaende, Typografie — soweit nicht
  durch FK-64 Design System abgedeckt)

### 72.13.2 Verortung im Repository

- Pfad: **`frontend/prototype/`** (versioniert, im Hauptzweig).
- Stack: TypeScript + React + Vite (analog zum bisherigen
  Prototyp). Die Stack-Wahl ist Implementierungsdetail; ein
  spaeterer Engineering-Refactor kann den Stack revidieren, ohne
  die normative Funktion des Prototyps zu beruehren.
- Daten: aktuell Mocks. Mit fortschreitendem Backend-Bau wandert
  der Prototyp Schritt fuer Schritt auf echte BFF-Endpunkte
  (siehe 72.13.4).

Der Prototyp ist seit dem Umzug aus `var/ui-prototype/` unter
`frontend/prototype/` versioniert. `node_modules/` und der
Vite-Build-Output sind gitignored.

### 72.13.3 Iterationsmodus

Der Prototyp wird **iterativ und gemeinsam mit dem Stratege**
weiterentwickelt: ein Agent fuehrt UI-Aenderungen durch, der
Stratege gibt Feedback im Browser, der Prototyp wird angepasst.
Die jeweils committete Form ist normativ.

### 72.13.4 Engineering-Refactor (spaetere Welle)

Sobald der Prototyp funktional und in der UX stabil ist, folgt eine
**eigene Welle Engineering-Refactor**:

- Komponentenarchitektur sauber ziehen (BC-aligned Slices, Shell,
  Foundation-Bereiche gemaess 72.3)
- Mocks durch echte BFF-Aufrufe ersetzen
- State-Management strukturieren
- Tests, Performance, Accessibility nachziehen

Bis dahin gilt: was im Prototyp lebt, ist Soll. Konzept-Aussagen in
diesem Dokument oder anderen FKs duerfen ihm **nicht** widersprechen
— bei Konflikt wird hier nachgezogen, nicht der Prototyp angepasst.

## 72.14 Frontend-Datenvertraege

<!-- PROSE-FORMAL: formal.frontend-contracts.entities, formal.frontend-contracts.commands, formal.frontend-contracts.events, formal.frontend-contracts.invariants -->

Die Wire-Sicht zwischen Frontend und BFF — Read-Models, Mutationen,
Live-Events und ihre Konsistenzregeln — ist formal in
`formal.frontend-contracts.*` festgelegt. Die hier in Prosa
beschriebene Sichten-, Tab- und Schreibpfad-Struktur (§72.5..§72.8)
projiziert auf diese formale Schicht; die einzelnen Endpunkte
werden in FK-91 §91.1a aufgefuehrt.

### 72.14.1 Geltungsbereich

Die formale Schicht deckt ab:

- **Read-Models** als `entity-set` in
  `formal.frontend-contracts.entities`: ProjectSummary,
  ProjectDetail, ProjectModeLock, StoryCounters, StorySummary,
  StoryRuntimeState, StoryDetail (inkl. Specification, Evidence,
  TelemetrySummary, Gates, Phases, Events), StoryFlowSnapshot
  (inkl. Phasen und Substeps mit Loop-Iterationen),
  ExecutionInputSnapshot, ExecutionInputStack, ExecutionLimits,
  DependencyGraphSnapshot.
- **Mutationen** als `command-set` in
  `formal.frontend-contracts.commands`: `create_story`,
  `update_story_fields`, `approve_story`, `reject_story`,
  `cancel_story`, `update_execution_limits`. Jeder Command ist
  auf den Endpoint aus FK-91 §91.1a gebunden, traegt einen
  `op_id`-Idempotenzschluessel und nennt den fachlichen Owner-BC.
- **Live-Events** als `event-set` in
  `formal.frontend-contracts.events`: pro SSE-Topic
  (`stories`, `phases`, `gates`, `governance`, `closure`,
  `artifacts`, `planning`, `telemetry`, `coverage`) das konkrete
  Wire-Schema des Frontends. Producer bleibt `telemetry` als
  Single-Producer (§72.12.3).
- **Konsistenz-Invarianten** als `invariant-set` in
  `formal.frontend-contracts.invariants`: Initial-GET-plus-Subscribe,
  Lossy-Re-Sync, kein Polling, Triage-Determinismus, Mode-Lock-
  Ableitung, Status-Transitionen nur via dedizierte Endpoints,
  Counters-Klassifikation, Flow-Snapshot-Konsistenz.

### 72.14.2 Was bewusst nicht formal ist

Bewusst **nicht** im formalen Vertrag:

- **LLM-Hub-Integration** (Sicht 5 in §72.5). Hub-Cockpit und der
  separate SSE-Stream `/v1/events/hub` bleiben zurueckgestellt,
  bis die Hub-View produktiv ist. Heute Prototyp-Stand.
- **Analytics-Hauptsicht** (Sicht 4 in §72.5). KPI-Definitionen
  und Aggregat-Endpoints sind Eigentum von `kpi-and-dashboard`
  (FK-60..63) und werden dort formalisiert, sobald die View
  produktiv ist.
- **Inspector-KPI-Tab-Lieferform**: Read-Modell entsteht aus
  `kpi-and-dashboard`-Projektionen; im Frontend-Contract sind nur
  `story_telemetry_summary`-Aggregate enthalten, die fuer das
  Inspector-Rendering ausreichen, ohne KPI-Semantik zu
  duplizieren.

### 72.14.3 Aenderungsregel

Jede Erweiterung der Web-Schnittstelle ist Pflicht-Erweiterung der
formalen Schicht:

1. Neuer Endpoint -> Eintrag in FK-91 §91.1a **und** Command bzw.
   Entity in `formal.frontend-contracts.*`.
2. Neues SSE-Event -> Eintrag in FK-91 §91.8 (Topic) **und** Event
   in `formal.frontend-contracts.events`.
3. Neue Sicht oder Tab -> Eintrag in §72.5 bzw. §72.6, mit Verweis
   auf die Read-Model-Entitaeten, die sie konsumiert.

Eine zweite Wahrheitsquelle (z. B. Prosa-Tabelle eines Schemas
ohne Formal-ID) ist ausgeschlossen.

### 72.14.4 Status-Mutationen — UI-Verbindlichkeit

Story-Status-Wechsel sind keine PATCH-Operation auf Stammdaten,
sondern Aufrufe der dedizierten Endpunkte. Die UI-Verbindlichkeit
folgt der formalen Spec:

- **Sheet** (Status-Cell): Auch wenn die Cell editierbar wirkt, wird
  ein Status-Wechsel intern auf `approve_story`, `reject_story` bzw.
  `cancel_story` dispatcht — niemals als `PATCH /v1/stories/{id}` mit
  `status`-Feld. Siehe `frontend-contracts.invariant.status_transitions_only_via_endpoints`
  und `forbidden_inputs.status` im `update_story_fields`-Command.
- **Kanban** (Drag&Drop): Erlaubt ausschliesslich die Pfade
  `Backlog -> Approved`, `Approved -> Backlog`, `Backlog -> Cancelled`,
  `Approved -> Cancelled`. Terminale (`Done`, `Cancelled`) und
  laufende (`In Progress`) Karten sind nicht draggable.
  Pipeline-getriebene Uebergaenge (`Approved -> In Progress`,
  `In Progress -> Done`) gehoeren der Pipeline, nicht dem UI. Siehe
  `frontend-contracts.invariant.kanban_drag_drop_constrained_transitions`.
- **Administrative Mutationen** auf laufende oder fertige Stories
  laufen ueber `story-reset` (FK-53), `story-split` (FK-54) und
  `story-exit` (FK-58); sie sind kein direkter Kanban- oder
  Sheet-Pfad.

### 72.14.5 Inspector-KPI-Tab — Phasenaufteilung

Der Inspector-KPI-Tab liefert Werte phasenaufgeteilt, soweit der
Stratege die Phasen-Leistung eines Agents bewerten koennen muss
(Exploration loesen vs. Implementation loesen):

- **Laufzeit**: getrennt fuer Setup, Exploration, Implementation,
  Closure plus Total. Exploration ist im Fast-Mode `null` (Phase
  ausgelassen, FK-24 §24.3.3).
- **Solving Rate**: getrennt fuer Exploration und Implementation,
  als Anteil der QA-Findings, die im Subflow-Remediation-Loop
  abgearbeitet wurden.
- **Tokens** (Total/In/Out/Cached): nicht phasenaufgeteilt, pro
  Story. `tokens_cached` ist Pflicht und stammt aus der echten
  Cache-Messung der LLM-Pools, nicht aus einer Frontend-Heuristik.

Schema: `frontend-contracts.entity.story_telemetry_summary`. Eine
Frontend-Synthese aus rohen Totals (wie aktuell im Prototyp) ist
mit dieser Lieferung nicht mehr notwendig und nicht mehr zulaessig.

### 72.14.6 Edge-Cases und UI-Verhalten

Diese Sektion deckt das UI-Verhalten an Vertragsgrenzen ab —
Fehlerantworten, Race-Bedingungen, Empty-States. Die Pflicht-Regeln
sind formal in `formal.frontend-contracts.invariants` festgelegt;
hier die UI-Lesart.

**Mutation fehlgeschlagen** (HTTP 4xx/5xx):

- Optimistic-Update wird revertiert
  (`frontend-contracts.invariant.optimistic_update_revert`).
- Der Stratege bekommt eine kurze Fehler-Pille mit dem
  `error_code` als Klartext (z. B. „Story-Status hat sich
  zwischenzeitlich geaendert"). Stilles Schlucken ist
  unzulaessig.
- Spezialfall Kanban-Drop mit `invalid_transition`: die Karte
  springt sichtbar auf die reale Spalte zurueck
  (`frontend-contracts.invariant.kanban_drop_handles_backend_rejection`).
- Spezialfall Sheet-Inline-Edit mit `validation_failed`: die
  Cell behaelt den Draft-Stand sichtbar und markiert das Feld
  rot, bis der Stratege korrigiert oder verwirft.

**Story verschwindet** (`story_deleted` oder 404 auf Detail-GET):

- Wenn die Story im Inspector selected war: Inspector schliesst
  sich, Hinweis-Pille „Story wurde entfernt"
  (`frontend-contracts.invariant.stale_selected_story`).
- Karten in Kanban/Sheet/Graph verschwinden ohne Animation;
  Counters werden neu geladen.
- Reset (FK-53) und cancel (UI-Aktion) sind **keine** Loesch-
  Faelle — die Story bleibt sichtbar mit neuem Status.

**Race beim schnellen Wechseln**:

- Inspector wechselt schnell zwischen Stories: spaet eintreffende
  Detail-Antworten ueberschreiben die aktuelle Selection nicht
  (`frontend-contracts.invariant.last_request_wins_per_inspector`).
- SSE-Events koennen in jeder Reihenfolge kommen
  (`frontend-contracts.invariant.no_global_event_ordering`); per-
  Story-Konsistenz entsteht durch Re-Fetch nach Event.

**Empty-States** (alle Sichten):

- Leere Story-Liste: alle Sichten zeigen einen kurzen Hinweis
  („Noch keine Stories — `+Story` zum Anlegen").
- Leere Execution-Input-Sektionen: PlaceholderColumn (FK-72
  bereits in §72.5 als Layout-Invariante beschrieben).
- Leere Akzeptanzkriterien/Dependencies/Bundle-Entries im
  Inspector: kurze „keine …"-Zeile, kein leerer Container.
- Kein QA-Cycle gestartet: Inspector-Ergebnis-Tab zeigt
  „QA-Subflow noch nicht gelaufen", keine Bundle-Liste.

**Phase im Halte-Zustand** (`escalated` / `paused` / `failed`):

- Flow-Tab markiert die Phase farblich und zeigt
  `state_reason` als Hinweistext.
- Kein „active"-Marker mehr auf dieser Phase; die Iteration-
  Anzeige verbleibt auf dem letzten Stand.
- Inspector-Header zeigt eine globale Pille „pausiert" /
  „eskaliert", damit der Strateg ohne Tab-Wechsel sieht, dass
  Eingriff noetig ist.

**Project-Switch**:

- Beim Wechsel ueber den Topbar-Project-Selector werden alle
  SSE-Subscriptions auf das alte Projekt geschlossen, der
  Inspector wird zugeklappt, lokale Drafts (Sheet) gehen
  verloren mit einer Warnung. Eine View-Selection (`graph` /
  `kanban` / ...) bleibt erhalten.
- Archivierte Projekte erscheinen in der Liste, ihre mutierenden
  UI-Elemente sind disabled (`forbidden` ist die Backend-
  Antwortklasse, das UI praeventiert).

**Concurrency bei Limits**:

- Zwei Strategen aendern parallel die Caps: `last_writer_wins`
  (siehe `command.update_execution_limits.concurrency`). Beide
  sehen das Endergebnis ueber `limits_changed`-Event. Es gibt
  kein ETag, keine Konflikt-Warnung. Begruendung: das Stratege-
  Tool bedient wenige Nutzer, parallele Cap-Aenderungen sind
  selten und nicht eskalationspflichtig.

**Reconnect / Network Loss**:

- SSE bricht ab: der Browser-EventSource reconnectet
  automatisch. Beim Reconnect macht das Frontend einen frischen
  Initial-GET aller geoeffneten Sichten
  (`frontend-contracts.invariant.lossy_resync_on_reconnect`).
- Total-Offline: alle mutierenden UI-Elemente werden disabled,
  ein dezenter „Verbindung verloren"-Indikator am Topbar
  signalisiert den Stand. Optimistic-Updates werden nicht
  gestartet.
