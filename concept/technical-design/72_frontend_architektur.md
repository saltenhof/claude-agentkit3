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
formal_scope: prose-only
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

| # | Sicht | Primaerer BC / Foundation | Mitliefernd | Charakter |
|---|---|---|---|---|
| 1 | Graph (Dependency) | `execution_planning` | `story_context_manager` | Single-BC |
| 2 | Kanban | `story_context_manager` | `pipeline_engine`, `verify_system`, `governance` | Composer |
| 3 | Sheet | `story_context_manager` | viele | Composer |
| 4 | Analytics | `kpi_analytics` (Komposition) | `telemetry`, `verify_system`, `failure_corpus`, `pipeline_engine` | Composer |
| 5 | Hub | Foundation `multi_llm_hub` | — | Foundation |
| 6 | Wave-/Readiness | `execution_planning` | `story_context_manager` | Single-BC |
| 7 | Konfiguration praktische Parallelisierbarkeit | `execution_planning` | — | Single-BC, Schreibpfad |
| 8 | Concept-Browser | Foundation `concept_catalog` | viele Konsumenten | Foundation |

## 72.6 Inspector-Tabs

| Tab | Primaerer BC | Mitliefernd |
|---|---|---|
| Spezifikation | `story_context_manager` | `requirements_coverage`, `governance`, `concept_catalog` |
| Ergebnis (Evidence) | `artifacts` | `pipeline_engine`, `verify_system`, `telemetry`, `governance`, `requirements_coverage` |
| KPIs | `kpi_analytics` | `telemetry` |

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
agentkit/kpi_analytics/http/        # /v1/projects/{key}/kpis
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
