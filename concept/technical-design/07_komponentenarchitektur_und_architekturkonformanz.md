---
concept_id: FK-07
title: "Komponentenarchitektur und Architektur-Konformanz"
module: architecture-conformance
cross_cutting: true
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
  - FK-62
  - FK-63
supersedes: []
superseded_by:
tags: [komponentenarchitektur, architecture, conformance, static-analysis, import-graph]
prose_anchor_policy: strict
formal_refs:
  - formal.architecture-conformance.entities
  - formal.architecture-conformance.invariants
---

# 7 — Komponentenarchitektur und Architektur-Konformanz

<!-- PROSE-FORMAL: formal.architecture-conformance.entities, formal.architecture-conformance.invariants -->

## 7.1 Zweck

Dieses Kapitel zieht den normativen Komponentenschnitt von AK3 scharf
und definiert die erste deterministische Architektur-Pruefschicht gegen
den Python-Code.

Es ersetzt keine fachlichen Ownership-Regeln aus FK-17/FK-18. Es macht
sie aber fuer den Komponentenschnitt maschinell pruefbar:

- welche Komponenten fachlich existieren
- welche Bausteine A-, R- oder T-Code sind
- welche Abhaengigkeiten architektonisch erlaubt oder verboten sind
- welche Regeln CI-fail-closed gegen den Code pruefen muss

## 7.2 Grundregeln

1. Komponenten werden entlang fachlicher Domaenengrenzen geschnitten,
   nicht entlang technischer Schichten oder Pipeline-Positionen.
2. Adapter sind keine Fachkomponenten.
3. Persistenztreiber sind keine Fachkomponenten.
4. Jeder kanonische Runtime-Record hat genau einen schreibenden Owner.
5. Querschnittsvertraege wie `op_id`, `correlation_id`,
   API-Versionierung und Fehlervertraege werden komponentenuebergreifend
   behandelt und nicht in einzelne HTTP-Dateien ausgelagert.

## 7.3 Blutgruppen

Im Sinne der Architektur-Guardrails (ARCH-22) gilt fuer AK3:

- `A-Code`: fachliche Komponenten mit Geschaeftsregeln, technologie-frei,
  ohne Infra-Setup testbar
- `R-Code`: Repraesentations-Ueberfuehrung zwischen Domaene und Aussen
  (Anti-Korruptions-Schicht ist eine Rolle, nicht der Kern)
- `T-Code`: Bindung an konkrete technische Laufzeit-Umgebung ausserhalb
  der Kernfachlichkeit
- `0` / `Null-Code`: domaenen- und projektunabhaengig wiederverwendbar;
  darf generische technische Anteile haben (z. B. Logging-Framework)

AT-Mischungen sind kein generelles Antipattern, sondern an dafuer
vorgesehenen Mediation-Schichten konstitutiv (typisch:
Datenbank-Zugriffsschicht, UI-Anwendungsrahmen). Die Norm ist nicht
„AT vermeiden", sondern **AT lokalisieren** — die AT-Inseln klein,
fachlich benannt, klar abgegrenzt halten, damit der A-Kern AT-frei
und unabhaengig testbar bleibt.

Volldefinition mit Heuristiken, Erkennungstests und Beispielen:
**`concept/methodology/software-blutgruppen.md`**.

## 7.4 Normativer Top-Level-Schnitt

> **Port-Nomenklatur (§7.4.1–§7.4.6):** Die in den Spalten „Provided
> Contracts" gefuehrten Port-Namen benennen die fachlichen
> Ziel-Vertraege je Komponente. Sie sind Vertrags-Zielbild; eine
> konkrete Implementierung darf ihre Symbole funktionsbezogen anders
> benennen, solange der Vertrag erfuellt ist. Maschinell erzwungen
> werden die Import- und Mutationsgrenzen (§7.7–§7.9), nicht die
> literalen Port-Symbolnamen.

### 7.4.1 Story- und Ausfuehrungskern

| Komponente | Blutgruppe | Fachliche Verantwortung | Provided Contracts |
| --- | --- | --- | --- |
| `StoryContextManager` | A | owns `Story`, `StoryContext` und Story-Attribute; liefert Story-nahe Read-Modelle und Story-Lifecycle ausserhalb der Flow-Orchestrierung | `StoryReadPort`, `StoryLifecyclePort`, `StoryContextPort` |
| `ExecutionPlanningService` | A | owns Backlog-Readiness, Abhaengigkeitsgraph, Blocker, kritischen Pfad, Ausfuehrungswellen, Planning-Proposals und Scheduling-Policy zwischen Backlog und Orchestrator | `DependencyGraphPort`, `ReadinessAssessmentPort`, `ExecutionPlanPort`, `SchedulingPolicyPort`, `PlanningProposalPort` |
| `PipelineEngine` | A | owns `FlowExecution`, `NodeExecution`, `AttemptRecord` und den 4-Phasen-Kontrollfluss (Setup, Exploration, Implementation inkl. QA-Subflow, Closure) | `StoryExecutionPort`, `RunTransitionPort` |
| `StoryExecutionLifecycleService` | A | owns Session-/Run-Binding, Story-Execution-Lock, Edge-Bundle-Metadaten und idempotente Lifecycle-Mutationen | `SessionBindingPort`, `StoryExecutionLockPort`, `EdgeBundlePort`, `ExecutionLifecycleMutationPort` |
| `WorktreeManager` | A | owns Worktree- und Branch-Lifecycle fuer Story-Ausfuehrungen und administrative Story-Eingriffe | `WorktreePort` |

> **`WorktreeManager`:** Der Soll-Schnitt ist eine **shared Komponente**
> `agentkit.worktree_manager` (`component_kind: shared`, importierbar durch
> `PipelineEngine` und `StoryContextManager`, exportierte Symbole
> `WorktreeManager.create`/`.merge`/`.cleanup`/`.exists`) mit Owner-Gruppe
> `architecture-conformance.group.story_context_manager` (BC
> `story-lifecycle`); siehe `bc-cut-decisions.md` und PROJECT_STRUCTURE.md.
> Der Port-Name `WorktreePort` ist — wie die uebrigen Port-Namen —
> Vertrags-Zielbild.

### 7.4.2 Governance- und QA-Kern

| Komponente | Blutgruppe | Fachliche Verantwortung | Provided Contracts |
| --- | --- | --- | --- |
| `GuardSystem` | A | harte Guard- und Capability-Enforcement-Regeln fuer Hook-Entscheidungen; intern aufgeteilt in `GuardEvaluation` (harness-neutraler A-Kern) und `HarnessAdapters.{Harness}` (pro Harness eine bewusst lokalisierte AT-Mediation-Insel, z.B. `claude_code` und `codex`; FK-76 §76.4) | `GuardDecisionPort` |
| `CcagPermissionRuntime` | A | lernfaehige, sessionpersistente Permission-Pfade ausserhalb der harten Guards | `PermissionDecisionPort` |
| `ConformanceService` | A | gestufte Dokument- und Konzepttreuepruefung an definierten Prozesszeitpunkten | `ConformancePort` |
| `StageRegistry` | A | autoritativer Stage-Katalog mit Producer-, Trust- und Blocking-Vertraegen | `StageRegistryPort` |
| `GovernanceObserver` | A | verdichtet Governance-Signale zu Incidents und Mustern | `GovernanceObservationPort` |
| `FailureCorpus` | A | sammelt Fehlmuster und bereitet Promotions vor | `FailureCorpusPort` |

### 7.4.3 Inhalts- und Runtime-Services

| Komponente | Blutgruppe | Fachliche Verantwortung | Provided Contracts |
| --- | --- | --- | --- |
| `ArtifactManager` | A | owns Artefakt-Referenzen sowie Envelope- und Producer-Vertraege | `ArtifactWritePort`, `ArtifactReadPort` |
| `PromptComposer` | A | komponiert Prompt-Bundles und Prompt-Modelle aus Story-Kontext und Ressourcen | `PromptCompositionPort` |
| `LlmEvaluator` | A | fuehrt strukturierte schema-validierte LLM-Evaluationen aus, ohne selbst Fachsemantik zu besitzen | `LlmEvaluationPort` |
| `TelemetryService` | A | owns `ExecutionEvent` und alle fachlichen Event-Abfragen | `TelemetryEventWritePort`, `TelemetryQueryPort` |
| `PhaseStateStore` | A | owns ausschliesslich `phase_state_projection` und nie `FlowExecution` oder `NodeExecution` | `PhaseStateProjectionPort`, `PhaseStateProjectionQueryPort` |

### 7.4.4 Analytics- und Produktoberflaeche

| Komponente | Blutgruppe | Fachliche Verantwortung | Provided Contracts |
| --- | --- | --- | --- |
| `KpiAnalyticsEngine` | A | owns KPI-Semantik, Rollups und Fact-Tabellen gemaess FK-60 bis FK-62 | `KpiQueryPort`, `AnalyticsSyncPort` |

Die Frontend-Klammer (App-Shell, Composer-Sichten wie Story-Inspector,
Story-Board, Story-Sheet, Dependency-Graph) ist **kein** A-BC und
**keine** Top-Level-Fachkomponente. Sie ist als R-Klammer in
**FK-72** verortet; die KPI-Sicht selbst bleibt Single-BC-Sicht von
`KpiAnalyticsEngine`. Es gibt bewusst **keine**
`DashboardApplication`-A-Komponente, die Story-Liste, Board oder
Story-Detail aggregiert — das waere der vom User abgelehnte
Cockpit-A-BC.

### 7.4.5 Bootstrap und Projektbindung

| Komponente | Blutgruppe | Fachliche Verantwortung | Provided Contracts |
| --- | --- | --- | --- |
| `Installer` | A | Projektregistrierung, Bootstrap, Hook- und Wrapper-Bindung, Scaffold-Verifikation | `ProjectBootstrapPort` |

### 7.4.6 Projektverwaltung

| Komponente | Blutgruppe | Fachliche Verantwortung | Provided Contracts |
| --- | --- | --- | --- |
| `ProjectManagement` | A | owns `Project`-Entitaet, Story-ID-Praefix-Schema und projektbezogene Konfiguration; ist Quelle des Projekt-Kontextes fuer alle anderen BCs (Cross-Cutting `project_key`) | `ProjectDirectoryPort`, `ProjectConfigurationPort`, `ProjectLifecyclePort` |

## 7.5 Adapter und technische Infrastruktur

Diese Bausteine sind notwendig, aber keine Fachkomponenten:

| Baustein | Blutgruppe | Rolle |
| --- | --- | --- |
| `ControlPlaneHttp` | R | HTTPS-Adapter fuer externe API-Aufrufe |
| `ProjectEdgeClient` | R | lokaler Projekt-Adapter fuer Sync und Bundle-Publish |
| `GitHubAdapter` | R | Tracker- und Repo-Integration |
| `LlmPoolAdapter` | R | LLM-Pool-Transport |
| `MultiLlmHubClient` | R | Foundation-Adapter zum externen Multi-LLM-Hub (FK-75) |
| `AreAdapter` | R | ARE-Integration |
| `VectorDbAdapter` | R | semantische Retrieval-Integration |
| `ConceptCatalog` | R | Foundation-Adapter zum Markdown-Konzept-Korpus, FK-Doc-Resolver (FK-74) |
| `StateBackendDriver` | T | physischer Postgres-/SQLite-Treiber, Transaktionen, SQL und Serialisierung |

`HookRuntime` ist hier **keine** eigene Komponente, weil die
Hook-Auswertung in zwei Subs von `GuardSystem` lebt:
`GuardEvaluation` (A-Kern, harness-neutral) und
`HarnessAdapters.{Harness}` (pro Harness eine lokalisierte AT-Mediation
— z.B. `claude_code` und `codex` (FK-76 §76.4); weitere Harnesses wie
`qwen_code` oder `gemini_code` sind anschliessbar).
`agentkit.backend.governance.hookruntime` ist Backward-Compat-Pfad fuer den
Claude-Code-Adapter und gehoert zur AT-Insel.

**Explizite Nicht-Komponente:** `IntegrationHub` ist kein normativ
zulaessiger Top-Level-Baustein. GitHub, LLM-Pools, ARE und VectorDB
bleiben getrennte Adapter und duerfen nicht durch ein Kategorielabel zu
einer scheinfachlichen Komponente zusammengefasst werden.

**Bluttypen der `boundary_modules`:** `shared` ist als Bluttyp `0`
(Null-Software) modelliert (`entities.md` `boundary.shared`). Die
uebrigen `boundary_modules` (`config`, `filesystem`,
`state_persistence_scope`) sind so zu schneiden, dass ihre
fachneutralen Anteile sauber von ihren Konventions-Anteilen trennbar
sind, und werden entlang dieser Trennung klassifiziert.

## 7.6 Repository-Regel

Fachkomponenten haengen nicht an `agentkit.backend.state_backend.store` als
generischer Mega-Fassade. Die Zielarchitektur verlangt
komponentenspezifische Repository-Vertraege.

Diese Regel ist normativ. Maschinell erzwungen werden in diesem Kapitel
robuste Import- und Adaptergrenzen (§7.7–§7.9); die vollumfaengliche
maschinelle Durchsetzung der komponentenspezifischen
Repository-Vertraege ist als Soll definiert, aber nicht Teil der
maschinell erzwungenen Invarianten dieses Kapitels.

## 7.7 Deterministische Architektur-Pruefung

### 7.7.1 Warum deterministisch

Architekturtreue darf nicht nur als Review-Meinung existieren. Die
Soll-Architektur (Blutgruppen-Klassifikation und Komponentenschnitt) ist
maschinell pruefbar und wird deshalb CI-fail-closed erzwungen.

AK3 enthaelt dazu als festen Bestandteil eine deterministische
Architektur-Konformanz-Suite. Sie ist nicht optional und kein einmaliger
Migrationsschritt: AK3 wird kontinuierlich weiterentwickelt, und die
Suite stellt dauerhaft sicher, dass die Soll-Architektur dabei gewahrt
bleibt. Als Werkzeug ist sie auch in Projekten einsetzbar, die mit AK3
gemanagt werden. Festgeschrieben ist der Zielzustand: eine Suite, die die
Architektur sicher, vollstaendig und effizient prueft und fail-closed
durchsetzt — keine Ausbaustufe, die nur einen Teil abdeckt.

### 7.7.2 Pflichtabdeckung: Klassifikation und Kopplung

Die Konformanz-Suite prueft:

- Komponentenklassifikation ueber Namespace-Prefixe
- verbotene Import-Richtungen zwischen A-, R- und T-Code
- verbotene direkte Kopplung von A-Code an Hook-/Transport-Adapter
- Azyklizitaet zwischen stabilen Komponenten

### 7.7.3 Pflichtabdeckung: Write-Surface-Ownership

Die Konformanz-Suite erzwingt Single-Writer-Ownership der kanonischen
Record-Familien: jede Familie hat eine definierte erlaubte Write-Surface,
und Mutationen sind nur aus den dafuer freigegebenen Moduloberflaechen
zulaessig. Jede Abweichung laeuft fail-closed auf.

Sie prueft importbasiert:

- welche Module Story-Kontext mutieren duerfen
- welche Module Flow-, Node-, Attempt- und Override-Ledger mutieren
  duerfen
- welche Module `execution_events` appenden duerfen
- welche Module Session-/Lock-/Operationstabellen der Control Plane
  mutieren duerfen
- welche Module Closure-Metriken und Closure-Reports materialisieren
  duerfen

### 7.7.4 Erweiterte Pflichtabdeckung der Suite

Die Konformanz-Suite deckt darueber hinaus verbindlich ab:

- Single-Writer-Ownership einzelner Tabellen-/Record-Familien auf AST-
  oder SQL-Ebene, auch jenseits des import- und mutationsradius-basierten
  Checks
- vollstaendige Repository-Konformanz fuer alle A-Komponenten
- `op_id`-/`correlation_id`-Pflicht fuer jede einzelne externe
  Kontaktflaeche
- deletability-Deadlines als harter Compile-Fehler

Diese Pruefungen sind verbindlicher Bestandteil der Suite, nicht nur
deklaratorisches Soll.

### 7.7.5 Pflichtabdeckung: Read-Surface-Grenzen

Die Konformanz-Suite erzwingt komponentenspezifische
Read-Surface-Grenzen. Sie prueft importbasiert:

- dass globale Story-Read-Loader nicht frei aus
  `agentkit.backend.state_backend` in beliebige A-Komponenten gezogen werden
- dass dazu neben Story-Kontext, Phase-State, FlowExecution und
  Closure-Metriken auch globale `execution_events` gehoeren
- dass globale Lifecycle-Read-Loader der Control Plane nicht frei
  aus `agentkit.backend.state_backend` in `runtime.py` oder andere A-Komponenten
  gezogen werden
- dass diese Loader nur innerhalb von `agentkit.backend.state_backend`
  selbst und auf expliziten Surfaces wie
  `agentkit.backend.story.repository` oder
  `agentkit.backend.control_plane.repository`
  importiert werden
- dass `StoryService` und Dashboard-Read-Modelle dadurch an einer
  fachlich benannten Repository-Kante statt an der technischen
  Mega-Fassade haengen

Direkte Read-Kopplung an die globale `state_backend`-Fassade laeuft
fail-closed auf; der Zugriff erfolgt ausschliesslich ueber die fachlich
benannten Repository-Kanten.

## 7.8 Verbindliche Importgrenzen

Die Konformanz-Suite zieht mindestens diese Grenzen:

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
   `agentkit.backend.story.repository` oder innerhalb von `agentkit.backend.state_backend`
   selbst importiert werden.
   Dazu gehoeren mindestens Story-Kontext-, Phase-State-, FlowExecution-,
   Story-Metrics- und `execution_events`-Reads.
7. Globale Control-Plane-Lifecycle-Reads duerfen nur aus
   `agentkit.backend.control_plane.repository` oder innerhalb von
   `agentkit.backend.state_backend` selbst importiert werden.

## 7.9 Messbare Architektur-Invarianten

Die Konformanz-Suite codiert folgende deterministisch pruefbare
Invarianten:

1. `agentkit.backend.story` und `agentkit.dashboard` importieren nicht
   `agentkit.backend.control_plane.http`.
2. `agentkit.backend.story` und `agentkit.dashboard` importieren nicht
   `agentkit.harness_client.projectedge.client`.
3. `agentkit.backend.story` und `agentkit.dashboard` importieren nicht
   `agentkit.backend.governance.hookruntime`.
4. `agentkit.backend.story`, `agentkit.dashboard` und `agentkit.backend.control_plane`
   importieren nicht direkt `agentkit.backend.state_backend.postgres_store`
   oder `agentkit.backend.state_backend.sqlite_store`.
5. `agentkit.harness_client.projectedge` importiert nicht
   `agentkit.backend.control_plane.http`.
6. Zwischen den stabilen Komponenten `story`, `dashboard`,
   `control_plane` und `projectedge` existiert kein Zyklus.
7. Writer-Symbole fuer `story_contexts`, `flow_executions`,
   `node_executions`, `attempt_records`, `override_records`,
   `execution_events`, Session-/Lock-/Operationstabellen sowie
   Closure-Metriken duerfen nur aus den dafuer freigegebenen
   Moduloberflaechen importiert werden.
8. Globale Story-Read-Loader duerfen nur auf der expliziten
   Read-Surface `agentkit.backend.story.repository` importiert werden; direkte
   Kopplung anderer A-Komponenten an diese Loader ist verboten.
9. Globale Control-Plane-Lifecycle-Reads duerfen nur auf der
   expliziten Read-Surface `agentkit.backend.control_plane.repository`
   importiert werden; direkte Kopplung anderer A-Komponenten an diese
   Loader ist verboten.

## 7.10 Beziehung zu anderen Konzepten

- FK-01 beschreibt den Systemkontext und die Prinzipien.
- FK-17/FK-18 definieren fachliche Ownership und kanonische Daten.
- FK-60 bis FK-63 definieren KPI- und Dashboard-Semantik.
- Die formale Auspraegung und der maschinelle Checker liegen in
  `formal.architecture-conformance.*`.
