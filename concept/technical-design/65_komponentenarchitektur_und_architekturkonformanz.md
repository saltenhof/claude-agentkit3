---
concept_id: FK-65
title: "Komponentenarchitektur und Architektur-Konformanz"
module: architecture-conformance
status: active
doc_kind: detail
parent_concept_id: FK-01
authority_over:
  - scope: component-architecture
  - scope: architecture-conformance
  - scope: architecture-checker
defers_to:
  - FK-01
  - FK-17
  - FK-18
  - FK-60
  - FK-63
supersedes: []
superseded_by:
tags: [komponentenarchitektur, architecture, conformance, static-analysis, import-graph]
prose_anchor_policy: strict
formal_refs:
  - formal.architecture-conformance.entities
  - formal.architecture-conformance.invariants
---

# 65 - Komponentenarchitektur und Architektur-Konformanz

<!-- PROSE-FORMAL: formal.architecture-conformance.entities, formal.architecture-conformance.invariants -->

## 65.1 Zweck

Dieses Kapitel zieht den normativen Komponentenschnitt von AK3 scharf
und definiert die erste deterministische Architektur-Pruefschicht gegen
den Python-Code.

Es ersetzt keine fachlichen Ownership-Regeln aus FK-17/FK-18. Es macht
sie aber fuer den Komponentenschnitt maschinell pruefbar:

- welche Komponenten fachlich existieren
- welche Bausteine A-, R- oder T-Code sind
- welche Abhaengigkeiten architektonisch erlaubt oder verboten sind
- welche Regeln CI-fail-closed gegen den Code pruefen muss

## 65.2 Grundregeln

1. Komponenten werden entlang fachlicher Domaenengrenzen geschnitten,
   nicht entlang technischer Schichten oder Pipeline-Positionen.
2. Adapter sind keine Fachkomponenten.
3. Persistenztreiber sind keine Fachkomponenten.
4. Jeder kanonische Runtime-Record hat genau einen schreibenden Owner.
5. Querschnittsvertraege wie `op_id`, `correlation_id`,
   API-Versionierung und Fehlervertraege werden komponentenuebergreifend
   behandelt und nicht in einzelne HTTP-Dateien ausgelagert.

## 65.3 Blutgruppen

Im Sinne der Architektur-Guardrails gilt fuer AK3:

- `A-Code`: fachliche Komponenten mit Geschaeftsregeln
- `R-Code`: Adapter an Systemgrenzen
- `T-Code`: Persistenz- und Infrastrukturtreiber
- `Null-Code`: generische Utilities ohne Fachsemantik

AT-Mischzonen sind zu vermeiden. Fachcode darf Infrastruktur benutzen,
aber nicht in eine technische Mega-Fassade hineinmodelliert werden.

## 65.4 Normativer Top-Level-Schnitt

### 65.4.1 Story- und Ausfuehrungskern

| Komponente | Blutgruppe | Fachliche Verantwortung | Provided Contracts |
| --- | --- | --- | --- |
| `StoryContextManager` | A | owns `Story`, `StoryContext` und Story-Custom-Fields; liefert Story-nahe Read-Modelle und Story-Lifecycle ausserhalb der Flow-Orchestrierung | `StoryReadPort`, `StoryLifecyclePort`, `StoryContextPort` |
| `ExecutionPlanningService` | A | owns Backlog-Readiness, Abhaengigkeitsgraph, Blocker, kritischen Pfad, Ausfuehrungswellen und Scheduling-Policy zwischen Backlog und Orchestrator | `DependencyGraphPort`, `ReadinessAssessmentPort`, `ExecutionPlanPort`, `SchedulingPolicyPort` |
| `PipelineEngine` | A | owns `FlowExecution`, `NodeExecution`, `AttemptRecord` und den 5-Phasen-Kontrollfluss | `StoryExecutionPort`, `RunTransitionPort` |
| `StoryExecutionLifecycleService` | A | owns Session-/Run-Binding, Story-Execution-Lock, Edge-Bundle-Metadaten und idempotente Lifecycle-Mutationen | `SessionBindingPort`, `StoryExecutionLockPort`, `EdgeBundlePort`, `ExecutionLifecycleMutationPort` |
| `WorktreeManager` | A | owns Worktree- und Branch-Lifecycle fuer Story-Ausfuehrungen und administrative Story-Eingriffe | `WorktreePort` |

### 65.4.2 Governance- und QA-Kern

| Komponente | Blutgruppe | Fachliche Verantwortung | Provided Contracts |
| --- | --- | --- | --- |
| `GuardSystem` | A | harte Guard- und Capability-Enforcement-Regeln fuer Hook-Entscheidungen | `GuardDecisionPort` |
| `CcagPermissionRuntime` | A | lernfaehige, sessionpersistente Permission-Pfade ausserhalb der harten Guards | `PermissionDecisionPort` |
| `ConformanceService` | A | gestufte Dokument- und Konzepttreuepruefung an definierten Prozesszeitpunkten | `ConformancePort` |
| `StageRegistry` | A | autoritativer Stage-Katalog mit Producer-, Trust- und Blocking-Vertraegen | `StageRegistryPort` |
| `GovernanceObserver` | A | verdichtet Governance-Signale zu Incidents und Mustern | `GovernanceObservationPort` |
| `FailureCorpus` | A | sammelt Fehlmuster und bereitet Promotions vor | `FailureCorpusPort` |

### 65.4.3 Inhalts- und Runtime-Services

| Komponente | Blutgruppe | Fachliche Verantwortung | Provided Contracts |
| --- | --- | --- | --- |
| `ArtifactManager` | A | owns Artefakt-Referenzen sowie Envelope- und Producer-Vertraege | `ArtifactWritePort`, `ArtifactReadPort` |
| `PromptComposer` | A | komponiert Prompt-Bundles und Prompt-Modelle aus Story-Kontext und Ressourcen | `PromptCompositionPort` |
| `LlmEvaluator` | A | fuehrt strukturierte schema-validierte LLM-Evaluationen aus, ohne selbst Fachsemantik zu besitzen | `LlmEvaluationPort` |
| `TelemetryService` | A | owns `ExecutionEvent` und alle fachlichen Event-Abfragen | `TelemetryEventWritePort`, `TelemetryQueryPort` |
| `PhaseStateStore` | A | owns ausschliesslich `phase_state_projection` und nie `FlowExecution` oder `NodeExecution` | `PhaseStateProjectionPort`, `PhaseStateProjectionQueryPort` |

### 65.4.4 Analytics- und Produktoberflaeche

| Komponente | Blutgruppe | Fachliche Verantwortung | Provided Contracts |
| --- | --- | --- | --- |
| `KpiAnalyticsEngine` | A | owns KPI-Semantik, Rollups und Fact-Tabellen gemaess FK-60 bis FK-62 | `KpiQueryPort`, `AnalyticsSyncPort` |
| `DashboardApplication` | A | liefert Story-Liste, Board, Story-Detail und Live-Sichten; besitzt keine KPI-Semantik | `DashboardQueryPort` |

### 65.4.5 Bootstrap und Projektbindung

| Komponente | Blutgruppe | Fachliche Verantwortung | Provided Contracts |
| --- | --- | --- | --- |
| `Installer` | A | Projektregistrierung, Bootstrap, Hook- und Wrapper-Bindung, Scaffold-Verifikation | `ProjectBootstrapPort` |

## 65.5 Adapter und technische Infrastruktur

Diese Bausteine sind notwendig, aber keine Fachkomponenten:

| Baustein | Blutgruppe | Rolle |
| --- | --- | --- |
| `ControlPlaneHttp` | R | HTTPS-Adapter fuer externe API-Aufrufe |
| `ProjectEdgeClient` | R | lokaler Projekt-Adapter fuer Sync und Bundle-Publish |
| `HookRuntime` | R | Claude-Code-Adapter fuer Guard- und Permission-Ketten |
| `GitHubAdapter` | R | Tracker- und Repo-Integration |
| `LlmPoolAdapter` | R | LLM-Pool-Transport |
| `AreAdapter` | R | ARE-Integration |
| `VectorDbAdapter` | R | semantische Retrieval-Integration |
| `StateBackendDriver` | T | physischer Postgres-/SQLite-Treiber, Transaktionen, SQL und Serialisierung |

**Explizite Nicht-Komponente:** `IntegrationHub` ist kein normativ
zulaessiger Top-Level-Baustein. GitHub, LLM-Pools, ARE und VectorDB
bleiben getrennte Adapter und duerfen nicht durch ein Kategorielabel zu
einer scheinfachlichen Komponente zusammengefasst werden.

## 65.6 Repository-Regel

Fachkomponenten haengen nicht an `agentkit.state_backend.store` als
generischer Mega-Fassade. Die Zielarchitektur verlangt
komponentenspezifische Repository-Vertraege.

Die aktuelle Codebasis ist an dieser Stelle noch im Umbau. Solange der
Refactoring-Schnitt `A4` aus dem Architektur-Workbook nicht vollzogen
ist, bleibt diese Regel normativ, aber nicht vollumfaenglich
maschinell erzwungen. Die maschinell erzwungenen Invarianten in diesem
Kapitel konzentrieren sich deshalb zuerst auf robuste Import- und
Adaptergrenzen.

## 65.7 Deterministische Architektur-Pruefung

### 65.7.1 Warum deterministisch

Architekturtreue darf nicht nur als Review-Meinung existieren. Ein Teil
des Sollbilds ist maschinell pruefbar und muss deshalb CI-fail-closed
werden.

### 65.7.2 Was V1 deterministisch prueft

Die erste Architektur-Konformanzschicht prueft:

- Komponentenklassifikation ueber Namespace-Prefixe
- verbotene Import-Richtungen zwischen A-, R- und T-Code
- verbotene direkte Kopplung von A-Code an Hook-/Transport-Adapter
- ausgewaehlte Azyklizitaetsregeln zwischen stabilen Komponenten

### 65.7.3 Was V2 zusaetzlich deterministisch prueft

Die zweite Architektur-Konformanzschicht friert den aktuell
zugelassenen Mutationsradius gegen kanonische Record-Familien ein.

Sie prueft importbasiert:

- welche Module Story-Kontext mutieren duerfen
- welche Module Flow-, Node-, Attempt- und Override-Ledger mutieren
  duerfen
- welche Module `execution_events` appenden duerfen
- welche Module Session-/Lock-/Operationstabellen der Control Plane
  mutieren duerfen
- welche Module Closure-Metriken und Closure-Reports materialisieren
  duerfen

Diese Schicht ist bewusst ein pragmatischer Zwischenschritt:

- sie verhindert neue Architekturdrift sofort fail-closed
- sie fixiert die heutige erlaubte Write-Surface deterministisch
- sie ersetzt noch nicht die spaetere vollstaendige
  Repository-Konformanz je A-Komponente

### 65.7.4 Was bewusst noch nicht voll maschinell erzwungen ist

Noch nicht voll deterministisch geprueft werden:

- Single-Writer-Ownership einzelner Tabellen-/Record-Familien auf AST-
  oder SQL-Ebene jenseits des zugelassenen Import- und
  Mutationsradius
- vollstaendige Repository-Konformanz fuer alle A-Komponenten
- `op_id`-/`correlation_id`-Pflicht fuer jede einzelne externe
  Kontaktflaeche
- deletability-Deadlines als harter Compile-Fehler

Diese Regeln bleiben normativ, werden aber erst nach weiterem
Komponentenschnitt voll maschinell erzwungen.

### 65.7.5 Was V3 zusaetzlich deterministisch prueft

Die dritte Architektur-Konformanzschicht friert ausgewaehlte
komponentenspezifische Read-Surfaces ein.

Sie prueft importbasiert:

- dass globale Story-Read-Loader nicht mehr frei aus
  `agentkit.state_backend` in beliebige A-Komponenten gezogen werden
- dass dazu neben Story-Kontext, Phase-State, FlowExecution und
  Closure-Metriken auch globale `execution_events` gehoeren
- dass globale Lifecycle-Read-Loader der Control Plane nicht mehr frei
  aus `agentkit.state_backend` in `runtime.py` oder andere A-Komponenten
  gezogen werden
- dass diese Loader nur noch innerhalb von `agentkit.state_backend`
  selbst und auf expliziten Surfaces wie
  `agentkit.story.repository` oder
  `agentkit.control_plane.repository`
  importiert werden
- dass `StoryService` und spaetere Dashboard-Read-Modelle dadurch an
  einer fachlich benannten Repository-Kante statt an der technischen
  Mega-Fassade haengen

Diese Schicht ist ebenfalls ein pragmatischer Zwischenschritt:

- sie erzwingt noch nicht die vollstaendige Read-Konformanz aller
  A-Komponenten
- sie verhindert aber neue Direktimporte der globalen Story-Loader
  sofort fail-closed
- sie macht den Rueckbau der `state_backend`-Mega-Fassade auf der
  Leseseite inkrementell und deterministisch pruefbar

## 65.8 V1-Importgrenzen

Die erste formale Checker-Schicht zieht mindestens diese Grenzen:

1. `StoryContextManager`-/`Story`- und `DashboardApplication`-nahe
   Module duerfen nicht direkt an `ControlPlaneHttp`,
   `ProjectEdgeClient` oder `HookRuntime` koppeln.
2. `ProjectEdgeClient` darf nicht von `ControlPlaneHttp` abhaengen.
3. A-Code darf nicht direkt an rohe `postgres_store`-/`sqlite_store`-
   Treiber koppeln, wenn dafuer bereits ein fachnaher Einstiegspunkt
   existiert.
4. Die stabilen Komponenten `story`, `dashboard`, `control_plane` und
   `projectedge` duerfen keine Rueckkopplungszyklen bilden.
5. Kanonische Write-Surfaces gegen `state_backend` und kompatible
   Legacy-Reexporte duerfen nur aus explizit zugelassenen
   Komponentenoberflaechen importiert werden.
6. Globale Story-Read-Loader duerfen nur aus
   `agentkit.story.repository` oder innerhalb von `agentkit.state_backend`
   selbst importiert werden.
   Dazu gehoeren mindestens Story-Kontext-, Phase-State-, FlowExecution-,
   Story-Metrics- und `execution_events`-Reads.
7. Globale Control-Plane-Lifecycle-Reads duerfen nur aus
   `agentkit.control_plane.repository` oder innerhalb von
   `agentkit.state_backend` selbst importiert werden.

## 65.9 Messbare Architektur-Invarianten

Die formale V1-Schicht codiert folgende deterministisch pruefbare
Invarianten:

1. `agentkit.story` und `agentkit.dashboard` importieren nicht
   `agentkit.control_plane.http`.
2. `agentkit.story` und `agentkit.dashboard` importieren nicht
   `agentkit.projectedge.client`.
3. `agentkit.story` und `agentkit.dashboard` importieren nicht
   `agentkit.governance.hookruntime`.
4. `agentkit.story`, `agentkit.dashboard` und `agentkit.control_plane`
   importieren nicht direkt `agentkit.state_backend.postgres_store`
   oder `agentkit.state_backend.sqlite_store`.
5. `agentkit.projectedge` importiert nicht
   `agentkit.control_plane.http`.
6. Zwischen den stabilen Komponenten `story`, `dashboard`,
   `control_plane` und `projectedge` existiert kein Zyklus.
7. Writer-Symbole fuer `story_contexts`, `flow_executions`,
   `node_executions`, `attempt_records`, `override_records`,
   `execution_events`, Session-/Lock-/Operationstabellen sowie
   Closure-Metriken duerfen nur aus den dafuer freigegebenen
   Moduloberflaechen importiert werden.
8. Globale Story-Read-Loader duerfen nur auf der expliziten
   Read-Surface `agentkit.story.repository` importiert werden; direkte
   Kopplung anderer A-Komponenten an diese Loader ist verboten.
9. Globale Control-Plane-Lifecycle-Reads duerfen nur auf der
   expliziten Read-Surface `agentkit.control_plane.repository`
   importiert werden; direkte Kopplung anderer A-Komponenten an diese
   Loader ist verboten.

## 65.10 Beziehung zu anderen Konzepten

- FK-01 beschreibt den Systemkontext und die Prinzipien.
- FK-17/FK-18 definieren fachliche Ownership und kanonische Daten.
- FK-60 bis FK-63 definieren KPI- und Dashboard-Semantik.
- Die formale Auspraegung und der maschinelle Checker liegen in
  `formal.architecture-conformance.*`.
