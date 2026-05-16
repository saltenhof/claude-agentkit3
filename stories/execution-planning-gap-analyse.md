# execution-planning — GAP-Analyse

> Generiert von einem dedizierten Sonnet-Sub-Agent (Stand 2026-05-16).

## Header

| Feld | Wert |
|---|---|
| BC-ID | `execution-planning` |
| Display-Name | `Execution-Planning` |
| Analyse-Datum | `2026-05-16` |
| Konzept-Quellen (autoritativ) | `FK-70`, `formal.execution-planning.entities`, `formal.execution-planning.state-machine`, `formal.execution-planning.commands`, `formal.execution-planning.events`, `formal.execution-planning.invariants`, `formal.execution-planning.scenarios` |
| Codebase-Hauptpfade | `src/agentkit/execution_planning/` |

## 1. Executive Summary

Der BC `execution-planning` ist in einem sehr fruehen, partiellen Zustand: Ein Kern-Teilpfad (Dependency-Graph-Aufbau, einfache Readiness-Auswertung gegen `hard_story_dependency` und `max_parallel_stories`) ist implementiert und per HTTP-Routes exponiert. Die zentralen fachlichen Konzepte des BC sind jedoch noch nicht vorhanden: Es fehlen `PlannedStory` mit vollstaendigem Planungsstatus-Modell, `BlockingCondition`, `HumanGate`, `ExternalGate`, `PlanningProposal`-Handover, `SchedulingPolicy` (Feasibility-/Scheduling-Trennung), `PlanDerivation` (critical_path, ExecutionWave, recommended_batch), Rulebook-Compile-Pfad, Re-Plan-Trigger sowie die Execution-Input-Top-Surface. Der implementierte `DependencyKind` deckt nur 3 von 8 im Konzept geforderten Kantentypen ab; der implementierte `ParallelizationConfig` ist ein vereinfachter Ersatz fuer den normativen `parallelism-budget`-Vertrag. Telemetrie-Events fuer Planungsentscheidungen fehlen vollstaendig.

| Kategorie | Anzahl |
|---|---|
| A — Nicht umgesetzt | 11 |
| B — Teilweise umgesetzt | 5 |
| C — Drift / Fehler | 4 |

## 2. Konzept-Soll (Kurzfassung)

- **`ExecutionPlanningService` als A-Komponente mit vier Top-Surfaces** (`DependencyGraph`, `ReadinessAssessment`, `PlanDerivation`, `SchedulingPolicy`) — `FK-70 §70.10.1`, `bc-cut-decisions.md §BC-14`
- **`PlannedStory`-Entitaet mit vollstaendigem Planungsmetadaten-Vertrag** (story_type, story_size, participating_repos, human_touchpoints, external_prerequisites, planning_status) — `FK-70 §70.4.1`, `formal.execution-planning.entities`
- **Acht typisierte `DependencyEdge`-Kantentypen** (hard_story_dependency, soft_story_dependency, serial_execution_constraint, mutex_constraint, shared_contract_dependency, shared_file_conflict, external_dependency, human_gate_dependency) — `FK-70 §70.4.2`
- **`BlockingCondition` als erstklassiges Objekt** (Klassen: blocked_internal_dependency, blocked_external, blocked_human, blocked_capacity, blocked_conflict, blocked_contract) — `FK-70 §70.4.3`, `formal.execution-planning.entities`
- **`HumanGate` und `ExternalGate` als erstklassige Planungsobjekte** mit direkter Wirkung auf Readiness- und Scheduling-Zustand — `FK-70 §70.5.3`
- **Strikte Trennung ExecutionFeasibility vs. ExecutionSchedulingPolicy** (`can_parallelize` vs. `may_parallelize_now`) — `FK-70 §70.4.4`, `formal.execution-planning.invariants §feasibility_and_scheduling_policy_are_distinct`
- **Fuenf Budget-Cap-Dimensionen** (repo_parallel_cap, merge_risk_cap, api_rate_limit_cap, llm_pool_cap, ci_capacity_cap) — `FK-70 §70.6.2`
- **`PlanDerivation`: critical_path, ready_set, blocked_set, execution_wave, recommended_batch, max_allowed_batch** — `FK-70 §70.6.4`
- **`ExecutionWave` mit eigenem Lifecycle** (planned, active, completed, collapsed) und Wave-Collapse-Pfad — `FK-70 §70.6.4`, `formal.execution-planning.entities`
- **`PlanningProposal`-Handover-Vertrag** (versioniert, mit Provenienz/Evidenz, kanonische AK3-Ableitung, kein Blindpassthrough) — `FK-70 §70.7b`
- **Rulebook-Compile-Pfad** (DSL -> kanonisches Modell, versioniert, nur ueber Admin-Pfade) — `FK-70 §70.7d`
- **Debounced, revisionsbasierter Re-Plan-Trigger** bei Story-DONE, Blocker-Aenderung, Cap-Wechsel, Rulebook-Update — `FK-70 §70.6.2a`
- **Execution-Input-Top-Surface** (`/v1/projects/{project_key}/execution-input/snapshot` + `/next`, deterministischer Triage-Selektor) — `FK-70 §70.8a`
- **Orchestrator-Vertrag**: PipelineEngine MUSS `evaluate_scheduling` vor jedem Story-Start aufrufen — `FK-70 §70.8`
- **Telemetrie-Events** fuer Planungsentscheidungen (dependency_recorded, story_ready, story_blocked, plan_revised, scheduling_decided, gate_resolved, rulebook_compiled, wave_collapsed) — `FK-70 §70.10.3`
- **Auditierbare Planungsrevisionen** (idempotent, revisionsgebunden) — `formal.execution-planning.invariants §plan_revisions_are_auditable`
- **Zyklus-/Deadlock-Quarantaene und Eskalation** (fail-closed, kein stilles Bypassing) — `FK-70 §70.11`, `formal.execution-planning.invariants §deadlocked_subgraphs_are_quarantined_before_remainder_progresses`

## 3. Code-Stand (Ist-Bild)

- `src/agentkit/execution_planning/entities.py:StoryDependencyKind` — 3 Kantentypen (blocks, derives_from, branches_off); konzeptfremde Benennung statt FK-70-Typen
- `src/agentkit/execution_planning/entities.py:StoryDependency` — einfache Kante (story_id, depends_on_story_id, kind, created_at); kein `strictness`, kein `rationale`, kein `dependency_kind` nach Formal-Spec
- `src/agentkit/execution_planning/entities.py:ParallelizationConfig` — vereinfachter Ersatz fuer `parallelism-budget` (nur max_parallel_stories, max_parallel_stories_per_repo); fehlt repo_parallel_cap, merge_risk_cap, api_rate_limit_cap, llm_pool_cap, ci_capacity_cap
- `src/agentkit/execution_planning/entities.py:StoryRefForPlanning` — minimales Read-Model (kein planning_status, kein story_type, kein story_size, keine participating_repos als Liste)
- `src/agentkit/execution_planning/entities.py:ReadinessAssessment` — Antwortmodell fuer einfache Readiness-Auswertung (next_ready, next_wave_after, theoretical_parallelism, practical_parallelism); kein blocked_set, kein critical_path, kein recommended_batch
- `src/agentkit/execution_planning/dependency_graph.py:DependencyGraph` — DAG-Algorithmen (topological_layers, has_cycle, transitive_predecessors/successors); kein Unterschied hard vs. soft Kante
- `src/agentkit/execution_planning/readiness.py:compute_readiness` — berechnet ready/wave-after auf Basis aller vorhandenen Kanten (kein hard/soft-Unterschied, keine Gates, keine Blocker)
- `src/agentkit/execution_planning/lifecycle.py:add_dependency` — validiert Zyklusfreiheit, persistiert Kante; keine Telemetrie-Events, kein PlanningProposal-Handover
- `src/agentkit/execution_planning/lifecycle.py:assess_readiness` — orchestriert compute_readiness; kein Re-Plan-Trigger, keine SchedulingPolicy
- `src/agentkit/execution_planning/errors.py` — StoryDependencyCycleError (mit path), StoryDependencyNotFoundError, StoryDependencyConflictError, ParallelizationConfigError
- `src/agentkit/execution_planning/repository.py:StoryDependencyRepository` — Protocol fuer Kantenspeicher (list, add, remove)
- `src/agentkit/execution_planning/repository.py:ParallelizationConfigRepository` — Protocol fuer Config-Speicher
- `src/agentkit/execution_planning/http/routes.py:ExecutionPlanningRoutes` — HTTP-Handler fuer dependency-graph (GET), dependencies (POST/DELETE), next-ready (GET), config (GET/PUT); keine execution-input-Endpoints, kein PlanningProposal-Endpoint

## 4. GAP-Analyse

### 4.1 A — Nicht umgesetzt

| # | Thema | Konzept-Referenz | Anmerkung |
|---|---|---|---|
| A1 | `BlockingCondition` als erstklassiges typisiertes Objekt | `FK-70 §70.4.3`, `formal.execution-planning.entities` | Kein Modell, kein Repository, keine Auswertungslogik; fehlt komplett |
| A2 | `HumanGate` und `ExternalGate` als erstklassige Planungsobjekte | `FK-70 §70.5.3`, `formal.execution-planning.entities` | Nicht modelliert; Gates beeinflussen weder Readiness noch Scheduling |
| A3 | `PlanningProposal`-Handover-Vertrag (Agenten-Eingang, Provenienz, Validation) | `FK-70 §70.7b`, `formal.execution-planning.commands §submit-planning-proposal` | Kein PlanningProposal-Modell, keine Ingest-Schicht, kein ProposalValidator |
| A4 | Rulebook-Compile-Pfad (DSL -> kanonisches Modell, versioniert) | `FK-70 §70.7d`, `formal.execution-planning.commands §compile-rulebook` | Keine DSL-Compile-Implementierung; kein RulebookRevision-Modell |
| A5 | `ExecutionWave` mit eigenem Lifecycle (planned/active/completed/collapsed) und Wave-Collapse-Pfad | `FK-70 §70.6.4`, `formal.execution-planning.entities` | Kein Wave-Entity, kein Wave-Lifecycle, kein Collapse-Handler |
| A6 | `SchedulingPolicy` (Feasibility-Trennung, fuenf Budget-Caps, `evaluate_scheduling`, `why_not_now`) | `FK-70 §70.4.4`, `FK-70 §70.6.2`, `bc-cut-decisions.md §BC-14` | Keine SchedulingPolicy-Komponente; nur max_parallel_stories als einziger Cap |
| A7 | `PlanDerivation` (critical_path, blocked_set, recommended_batch, max_allowed_batch) | `FK-70 §70.6.4`, `bc-cut-decisions.md §BC-14` | Kein critical_path, kein blocked_set, kein recommended_batch; ReadinessAssessment fehlt diese Felder |
| A8 | Debounced Re-Plan-Trigger bei Story-DONE, Blocker-/Cap-/Rulebook-Aenderung | `FK-70 §70.6.2a` | Kein Re-Plan-Mechanismus vorhanden |
| A9 | Execution-Input-Top-Surface (`/execution-input/snapshot` + `/next`, Triage-Selektor) | `FK-70 §70.8a` | Keine dieser Endpoints; kein deterministischer Triage-Selektor implementiert |
| A10 | Telemetrie-Events fuer Planungsentscheidungen (dependency_recorded, story_ready, story_blocked, plan_revised, scheduling_decided, gate_resolved, rulebook_compiled, wave_collapsed) | `FK-70 §70.10.3`, `formal.execution-planning.events` | Kein einziger Telemetrie-Event wird erzeugt |
| A11 | Auditierbare, idempotente Planungsrevisionen (revisionsgebunden, keine konkurrierenden Wahrheiten) | `FK-70 §70.11`, `formal.execution-planning.invariants §plan_revisions_are_auditable` | Keine Revisionslogik, keine Audit-Trails fuer Planungsaenderungen |

### 4.2 B — Teilweise umgesetzt

| # | Thema | Code-Referenz | Konzept-Referenz | Was fehlt |
|---|---|---|---|---|
| B1 | Typisierte `DependencyEdge`-Kantentypen | `src/agentkit/execution_planning/entities.py:StoryDependencyKind` | `FK-70 §70.4.2`, `formal.execution-planning.entities` | Nur 3 Typen (blocks, derives_from, branches_off) statt 8 normierter (hard_story_dependency, soft_story_dependency, serial_execution_constraint, mutex_constraint, shared_contract_dependency, shared_file_conflict, external_dependency, human_gate_dependency); Benennung weicht von Konzept-Vokabular ab |
| B2 | `PlannedStory`-Entitaet mit Planungsmetadaten | `src/agentkit/execution_planning/entities.py:StoryRefForPlanning` | `FK-70 §70.4.1`, `formal.execution-planning.entities` | Kein planning_status, kein story_type, kein story_size, keine participating_repos als vollstaendige Liste, keine human_touchpoints, keine external_prerequisites |
| B3 | Readiness-Auswertung | `src/agentkit/execution_planning/readiness.py:compute_readiness` | `FK-70 §70.6.1`, `formal.execution-planning.invariants §ready_requires_all_hard_dependencies_and_no_open_blocker` | Kein Unterschied zwischen hard und soft Kanten; keine Gate-Pruefung; keine Blocker-Auswertung; soft_dependency blockiert derzeit wie eine hard_dependency (verletzt Invariante) |
| B4 | Zyklus-Erkennung und Eskalation | `src/agentkit/execution_planning/dependency_graph.py:DependencyGraph.has_cycle`, `src/agentkit/execution_planning/lifecycle.py:add_dependency` | `FK-70 §70.11`, `formal.execution-planning.invariants §dependency_cycles_require_human_escalation` | Zyklus wird bei `add_dependency` korrekt abgewiesen; aber keine Quarantaene-Logik, keine Eskalation via typisiertem BlockingCondition, kein `dependency_cycle_detected`-Event |
| B5 | Parallelisierungs-Budget | `src/agentkit/execution_planning/entities.py:ParallelizationConfig` | `FK-70 §70.6.2`, `formal.execution-planning.entities §parallelism-budget` | Nur max_parallel_stories und max_parallel_stories_per_repo; fehlt repo_parallel_cap, merge_risk_cap, api_rate_limit_cap, llm_pool_cap, ci_capacity_cap; kein Triage-Selektor-Einsatz |

### 4.3 C — Drift / Fehler

| # | Thema | Code-Referenz | Konzept-Referenz | Drift / Fehler |
|---|---|---|---|---|
| C1 | `StoryDependencyKind`-Benennung weicht von FK-70-Vokabular ab | `src/agentkit/execution_planning/entities.py:StoryDependencyKind` | `FK-70 §70.4.2` | Konzept definiert hard_story_dependency, soft_story_dependency usw.; Code implementiert `blocks`, `derives_from`, `branches_off`; das ist konzeptfremdes Vokabular und laesst die normative hard/soft-Trennung verschwinden |
| C2 | `compute_readiness` behandelt alle Kanten gleich (kein hard/soft-Unterschied) | `src/agentkit/execution_planning/readiness.py:compute_readiness` | `FK-70 §70.11`, `formal.execution-planning.invariants §soft_dependencies_do_not_block_pure_feasibility` | Verletzt Invariante: soft_story_dependency darf nie allein Feasibility blockieren. Aktuell blockiert jede Kante unabhaengig von ihrem Typ die Readiness, was fuer soft-Abhaengigkeiten konzeptwidrig ist |
| C3 | `planning/next-ready`-Endpoint exponiert `ReadinessAssessment` ohne Feasibility-/Scheduling-Trennung | `src/agentkit/execution_planning/http/routes.py:ExecutionPlanningRoutes._handle_next_ready` | `FK-70 §70.4.4`, `formal.execution-planning.invariants §feasibility_and_scheduling_policy_are_distinct` | Der Endpoint vermischt theoretische Feasibility (theoretical_parallelism) und operative Scheduling-Einschraenkung (practical_parallelism) in einem Feld; es gibt kein separates evaluate_scheduling; `can_parallelize` und `may_parallelize_now` sind nicht getrennt auswertbar |
| C4 | `assess_readiness` setzt fehlenden Config-Eintrag auf `max(1, active_story_count)` | `src/agentkit/execution_planning/lifecycle.py:assess_readiness` | `FK-70 §70.11`, `formal.execution-planning.invariants §capacity_policy_may_reduce_parallelism_without_negating_feasibility` | Wenn kein Config-Eintrag vorhanden ist, wird max_parallel_stories implizit auf die Anzahl aller aktiven Stories gesetzt — das entspricht de facto keiner Kapazitaetsbeschraenkung. Das Konzept verlangt, dass Budget-Caps zentral und explizit konfiguriert sind; ein stiller Default, der alle Stories freigibt, widerspricht dem Fail-Closed-Prinzip |

## 5. Ableitungen / Empfehlungen

1. **Kantentypen auf FK-70-Vokabular umstellen (C1/B3-Blocker):** `StoryDependencyKind` auf `hard_story_dependency`, `soft_story_dependency` usw. umbenennen und in `compute_readiness` die hard/soft-Unterscheidung einbauen. Ohne diese Korrektur verletzt jede Readiness-Berechnung die Invariante `soft_dependencies_do_not_block_pure_feasibility`. Dies ist die dringlichste Aenderung, weil sie alle Folge-Implementierungen (Scheduling, Blocking) fundiert.

2. **`BlockingCondition`, `HumanGate`, `ExternalGate` als Entitaeten einfuehren (A1/A2):** Diese Objekte sind die Vorbedingung fuer korrekte Readiness-Auswertung (ohne sie ist READY kein regelbasiertes Ergebnis, sondern nur ein Graph-Ergebnis), fuer den Orchestrator-Vertrag und fuer Telemetrie. Sie blockieren alle weiteren BC-internen Faehigkeiten.

3. **`SchedulingPolicy` von `ReadinessAssessment` trennen (C3/A6):** `evaluate_scheduling` als eigene Funktion/Komponente einziehen; `feasibility` und `scheduling_decision` sauber getrennt exponieren. Ohne diese Trennung kann PipelineEngine den normativen Orchestrator-Vertrag (FK-70 §70.8) nicht einhalten.

4. **`PlanDerivation`-Kernfelder hinzufuegen (A7):** critical_path, blocked_set, recommended_batch, max_allowed_batch aus dem Graphen ableiten und als offizielle API-Antwort exponieren. Ermoeglicht erst den normativen Orchestrator-Pull.

5. **Execution-Input-Top-Surface anlegen (A9):** `/execution-input/snapshot` und `/execution-input/next` mit deterministischem Triage-Selektor (FK-70 §70.8a.3). Dies ist die einzige normierte Schnittstelle fuer Frontend und Orchestrator-Skill; die aktuellen `planning/next-ready`-Antworten decken das nicht ab.

6. **Telemetrie-Events anschliessen (A10):** Ohne Events sind Planungsentscheidungen nicht auditierbar; `plan_revisions_are_auditable`-Invariante ist verletzt. Direkt mit `Telemetry.write_event` nach BC-9-Pattern koppeln.

7. **`PlanningProposal`-Handover und Rulebook-Compile-Pfad (A3/A4):** Erst nach Stabilisierung von BlockingCondition/SchedulingPolicy sinnvoll umsetzbar; aber fruh genug konzipieren, da sie die normative Agenten-AK3-Grenze definieren.

## 6. Suchstrategie & Quellen

- **Vollstaendig gelesen:**
  - `concept/technical-design/70_story_planung_abhaengigkeiten_ausfuehrungsplanung.md`
  - `concept/formal-spec/execution-planning/README.md`
  - `concept/formal-spec/execution-planning/entities.md`
  - `concept/formal-spec/execution-planning/state-machine.md`
  - `concept/formal-spec/execution-planning/commands.md`
  - `concept/formal-spec/execution-planning/events.md`
  - `concept/formal-spec/execution-planning/invariants.md`
  - `concept/formal-spec/execution-planning/scenarios.md`
  - `src/agentkit/execution_planning/__init__.py`
  - `src/agentkit/execution_planning/entities.py`
  - `src/agentkit/execution_planning/dependency_graph.py`
  - `src/agentkit/execution_planning/readiness.py`
  - `src/agentkit/execution_planning/lifecycle.py`
  - `src/agentkit/execution_planning/errors.py`
  - `src/agentkit/execution_planning/repository.py`
  - `src/agentkit/execution_planning/http/routes.py`
- **Punktuell via grep:**
  - `concept/_meta/bc-cut-decisions.md §BC-14`: BC-Schnitt, Komponentenschnitt, Ziel-Module, Abhaengigkeiten; gesucht nach `execution.planning`, `ExecutionPlanning`, `PlanningProposal`, `SchedulingPolicy`
  - `concept/technical-design/_meta/domain-registry.yaml`: BC-ID, Display-Name, contract_docs
- **Code-Scan (Glob/Grep):**
  - Glob `src/agentkit/execution_planning/**/*`: vollstaendige Dateiliste des BC
  - Glob `tests/**/*execution*`: alle Unit-Tests fuer den BC (unit only, keine contract/integration)
  - Grep `/execution-input` in `src/agentkit/`: Pruefung ob Execution-Input-Top-Surface bereits implementiert (negativ)
  - Grep `why_not_now|ingest_proposal|evaluate_scheduling|PlanningProposal|BlockingCondition` in `src/agentkit/execution_planning/`: Pruefung auf fehlende Konzepte (allesamt negativ)
