# Projektstruktur-Guardrails

Dieses Dokument ist verbindlich fuer alle Agents, die in dieser Codebase arbeiten.
Jeder Agent MUSS diese Regeln einhalten. Verstoesse sind Deliverable-Blocker.

---

## Architekturprinzip: Dreifache Entkopplung

AgentKit existiert in zwei Formen. Diese Dualitaet bestimmt die gesamte Struktur.

| Form | Beschreibung |
|---|---|
| **Development-Codebase** (dieses Repo) | Python-Paket mit src-Layout, Tests, CI — hier wird AgentKit entwickelt |
| **Installiert im Zielprojekt** | AgentKit deployt `.agentkit/`, Prompts, Skills, Hooks, Config in ein fremdes Projekt |

Die Codebase ist in drei Ebenen entkoppelt:

| Ebene | Ort | Zweck |
|---|---|---|
| Package-Code | `src/agentkit/` | Implementierung der Orchestrierungsmaschine |
| Deployte Assets | `src/agentkit/resources/target_project/` | Einzige Source of Truth fuer alles was ins Zielprojekt geht |
| Test-Sandboxes | `tests/integration/target_project_sim/` | Simulierte Zielprojekte in Temp-Verzeichnissen |

---

## Verzeichnisstruktur — Regeln

### Root-Ebene

| Verzeichnis | Zweck | Regeln |
|---|---|---|
| `src/agentkit/` | Package-Code | Einziger Ort fuer Produktionscode. Kein Produktionscode ausserhalb. |
| `tests/` | Alle Tests | Vier Ebenen: `unit/`, `integration/`, `contract/`, `e2e/`. Details unten. |
| `stories/` | Story-Artefakte | Hier landen Story-bezogene Arbeitsergebnisse waehrend der Ausfuehrung. |
| `concept/` | Autoritative Fachkonzepte | Nur Markdown. Aenderungen nur mit explizitem User-Consent. |
| `docs/` | Publizierte Entwicklerdoku | Architecture, API, Guides, ADRs. |
| `examples/` | Demo-Zielprojekte | Lauffaehige Beispiele wie ein installiertes Zielprojekt aussieht. |
| `scripts/` | Dev/CI/Release-Hilfsskripte | Unterteilt in `dev/`, `ci/`, `release/`. |
| `frontend/` | Frontend-Module | Aktuell nur `frontend/prototype/` (UI-Prototyp, normative Quelle fuer UI-Verhalten gemaess FK-72 §72.13). `node_modules/` und Build-Output gitignored. |
| `var/` | Lokale ephemere Daten | **Gitignored.** Temp-Files, Logs, Sandboxes. Nie Source of Truth. |

### VERBOTEN auf Root-Ebene

- Keine Zielprojekt-Struktur im Root spiegeln (kein `.agentkit/` im Root)
- Keine losen Python-Dateien im Root
- Keine neuen Top-Level-Verzeichnisse ohne expliziten User-Consent

### `concept/` - interne Struktur

Unter `concept/` existieren drei autoritative Bereiche mit
unterschiedlicher Aufgabe:

```text
concept/
  domain-design/              # Fachliche Prosa-Konzepte
  technical-design/           # Technische Feinkonzepte
  formal-spec/                # Deterministisch pruefbare Formalspezifikation
```

**Regeln:**

1. `domain-design/` und `technical-design/` bleiben menschenlesbare
   Prosa-Konzepte.
2. `formal-spec/` enthaelt nur die normative, maschinenpruefbare
   Spezifikationsschicht.
3. `formal-spec/` bleibt ebenfalls **Markdown-only**, aber in
   strukturiertem, linterbarem Format gemaess
   `concept/formal-spec/00_meta/meta-contract.md`.
4. Generierte, abgeleitete oder kompilierte Artefakte aus der
   Formalspezifikation gehoeren **nie** nach `concept/`, sondern nach
   `var/`.

---

## src/agentkit/ — Package-Module

### Strukturprinzip: Komponenten vor Technik

Die Namespace-Struktur von AK3 folgt dem fachlichen
Komponentenmodell. Package-Namen werden aus der fachlichen
Verantwortung abgeleitet, nicht aus technischen Querschnitten wie
"pipeline", "qa" oder "governance", sofern diese nur
Implementierungs-Sammelcontainer waeren.

Der normative Top-Level-Schnitt ist definiert in
`concept/formal-spec/architecture-conformance/entities.md`.

**Sollzustand:** 16 fachliche Bounded Contexts + shared + Boundary-Module (schema_version 2)

```text
src/agentkit/
  # ---- BC 1: pipeline-framework ----
  pipeline_engine/
    flow_orchestrator/         # FlowOrchestrator: Knotenkomposition + Uebergangssteuerung
    phase_executor/            # PhaseExecutor: Ausfuehrung einzelner Phasenknoten
    phase_envelope_store/      # PhaseEnvelopeStore: Persistenz von Phasen-Envelopes
    pipeline_registry/         # PipelineRegistry: Registrierung ausfuehrbarer Pipelines
    compaction_resilience/     # CompactionResilience: Kontext-Kompaktierung + Resilienz
    phase_state_store/         # PhaseStateStore: Schema-Owner fuer FlowExecution und PhaseState

  # ---- BC 2: verify-system ----
  verify_system/
    stage_registry/            # StageRegistry: autoritativer Stage-Katalog
    qa_read_models/            # QaReadModels: Schema-Owner fuer QA-Read-Models
    llm_evaluator/             # LlmEvaluator: strukturierte schema-validierte LLM-Bewertungen
    conformance_service/       # ConformanceService: gestufte Dokumententreue-Pruefung
    evidence_assembler/        # EvidenceAssembler: QA-Evidenz-Aggregation
    adversarial_orchestrator/  # AdversarialOrchestrator: gezielte Edge-Case-Pruefung
    policy_engine/             # PolicyEngine: deterministische Trust-Aggregation
    qa_cycle_coordinator/      # QaCycleCoordinator: Koordination des mehrschichtigen QA-Zyklus

  # ---- BC 3: story-lifecycle ----
  story_context_manager/
    story_types/               # StoryTypes: Story-Domaenentypen (ehem. story/-Stub)
    story_identity/            # StoryIdentity: kanonische Story-Identifier und Typen
    story_creation_flow/       # StoryCreationFlow: Erstellung und initiale Bindung
    story_contract_matrix/     # StoryContractMatrix: Story-Typen und Vertragsregeln
    story_administration/      # StoryAdministration: administrative Lifecycle-Mutationen
    operating_mode_resolver/   # OperatingModeResolver: Betriebsmodus-Aufloesung
    story_storage_backend/     # StoryStorageBackend: Persistenz-Abbildung von Stories

  # ---- BC 4: governance-and-guards ----
  governance/
    guard_system/              # GuardSystem: harte Guard- und Capability-Enforcement-Regeln
    hookruntime/               # HookRuntime: Claude-Code-Adapter fuer Guard-Ketten
    ccag_permission_runtime/   # CcagPermissionRuntime: lernfaehige sessionpersistente Permissions
    governance_observer/       # GovernanceObserver: verdichtet Governance-Signale zu Incidents
    integrity_gate/            # IntegrityGate: deterministisches Integritaets-Gate vor Closure
    principal_capability/      # PrincipalCapability: Capability-Definitionen und -Pruefungen
    setup_preflight_gate/      # SetupPreflightGate: Kontext-Vorpruefung vor Phase 1
    escalation_mechanism/      # EscalationMechanism: Eskalations- und Adjudikationspfade

  # ---- BC 5: exploration-and-design ----
  exploration/
    mode_router/               # ModeRouter: Routing zwischen Explorations-Typen
    drafting/                  # ExplorationDrafting: Entwurfsartefakt-Erzeugung
    review/                    # ExplorationReview: Entwurfsbewertung
    mandate_classification/    # MandateClassification: Klassifikation des Explorationsauftrags

  # ---- BC 6: implementation-phase ----
  implementation/
    worker_session/            # WorkerSession: Worker-Session-Binding und Lifecycle
    worker_loop/               # WorkerLoop: iterative Implementierungs-Iteration
    handover_packager/         # HandoverPackager: Handover-Artefakt-Erzeugung
    worker_health/             # WorkerHealthMonitor: Health-Ueberwachung des Workers

  # ---- BC 7: story-closure ----
  closure/
    gates/                     # ClosureGates: Integrity-Gate-Pruefungen vor Merge
    merge_sequence/            # MergeSequence: deterministischer Merge-Ablauf
    post_merge_finalization/   # PostMergeFinalization: Aufraeum- und Abschlussschritte
    execution_report/          # ExecutionReport: Abschluss-Telemetrie und KPI-Materialiserung

  # ---- BC 8: artifacts ----
  artifacts/
    producer_registry/         # ProducerRegistry: Artefakt-Producer und Envelope-Vertraege

  # ---- BC 9: telemetry-and-events ----
  telemetry/
    hooks/                     # TelemetryHooks: Event-Emission-Schnittstellen
    projection_accessor/       # ProjectionAccessor: Lese-Zugriff auf Telemetrie-Projektionen
    contract/                  # TelemetryContract: Event-Schema-Definitionen und Versioning

  # ---- BC 10: prompt-runtime ----
  prompt_runtime/
    bundle_store/              # BundleStore: Speicherung von Prompt-Bundles
    bundle_pinning/            # BundlePinning: Versionspinning von Prompt-Bundles
    materialization/           # Materialization: Prompt-Rendering aus Bundle + Kontext

  # ---- BC 11: agent-skills ----
  skills/
    bundle_store/              # SkillBundleStore: Speicherung von Skill-Bundles
    binding/                   # SkillBinding: Skill-Bindung an Zielprojekt
    quality_metric/            # SkillQualityMetric: Qualitaetsmetriken fuer Skills

  # ---- BC 12: installation-and-bootstrap ----
  installer/
    checkpoint_engine/         # CheckpointEngine: idempotente Checkpoint-Ausfuehrung
    bootstrap_checkpoints/     # BootstrapCheckpoints: Erstregistrierungs-Checkpoints
    integration_checkpoints/   # IntegrationCheckpoints: Integrations-spezifische Checkpoints
    upgrade/                   # Upgrade: Upgrade bestehender Installationen

  # ---- BC 13: failure-corpus ----
  failure_corpus/
    incident_triage/           # IncidentTriage: Aufnahme und Klassifikation von Incidents
    pattern_promotion/         # PatternPromotion: Muster-Promotion aus Incidents
    check_factory/             # CheckFactory: Erzeugung deterministischer Pruefregeln

  # ---- BC 14: execution-planning ----
  execution_planning/
    planning_model/            # PlanningModel: Planungsmodell-Typen und Invarianten
    proposal_ingest/           # ProposalIngest: Aufnahme von Planungsvorschlaegen
    readiness_assessment/      # ReadinessAssessment: Story-Bereitschaftspruefung
    scheduling_policy/         # SchedulingPolicy: Scheduling-Policy zwischen Backlog und Orchestrator
    plan_derivation/           # PlanDerivation: Ableitung des Ausfuehrungsplans

  # ---- BC 15: requirements-and-scope-coverage ----
  requirements_coverage/
    are_client/                # AreClient: ARE-Adapter fuer Requirements-Zugriff
    scope_mapping/             # ScopeMapping: Story-zu-Requirement-Abbildung
    are_integration/           # AreIntegration: ARE-Integrations-Logik

  # ---- BC 16: kpi-and-dashboard ----
  kpi_analytics/
    catalog/                   # KpiCatalog: kanonischer KPI-Katalog
    fact_store/                # FactStore: KPI-Faktentabellen
    aggregation/               # Aggregation: KPI-Rollup und Aggregationsregeln
    dashboard/                 # Dashboard: Story-Liste, Board, Live-Sichten
    design_system/             # DesignSystem: Dashboard-Designsystem

  # ---- Shared ----
  worktree_manager/            # WorktreeManager [shared]: Worktree-/Branch-Lifecycle

  # ---- Boundary-Module (in entities.md schema_version 2 modelliert) ----
  # entry_boundary (R): Eingangs-Punkte, rufen fachliche BCs auf
  cli/                         # CommandLineInterface: CLI-Entrypoints und Command-Routing
  control_plane/
    http.py                    # ControlPlaneHttp: HTTP-Transport-Schicht (entry_boundary)
    models.py                  # ControlPlaneRecords: Pydantic-Modelle (adapter_boundary)
    records.py                 # ControlPlaneRecords: Persistenz-Records (adapter_boundary)
    runtime.py                 # ControlPlaneRuntime: Runtime-Service (adapter_boundary)
    repository.py              # ControlPlaneRuntime: Repository-Adapter (adapter_boundary)
    telemetry.py               # ControlPlaneRuntime: Telemetrie-Adapter (adapter_boundary)

  # adapter_boundary (R): duenne Wrapper; werden von BCs genutzt
  integrations/                # Integrations: Adapter zu externen Systemen (GitHub, LLM, ARE, VectorDB, MCP)
  projectedge/                 # ProjectEdge: lokaler Projekt-Adapter fuer Sync und Bundle-Publish
  state_backend/
    store.py                   # StateBackendRepository: Repository-Schicht, Anti-Korruptions-Schicht (adapter_boundary, R)
    scope.py                   # StatePersistenceScope: Cross-BC-Persistenz-Identitaet (adapter_boundary, R)
    paths.py                   # Filesystem: Pfad-Konstanten; konzeptionell boundary.filesystem (infrastructure_io, R)
    postgres_store.py          # StateBackendDrivers: Postgres-Treiber (infrastructure_driver, T)
    sqlite_store.py            # StateBackendDrivers: SQLite-Treiber (infrastructure_driver, T)
    config.py                  # StateBackendDrivers: Driver-Konfiguration (infrastructure_driver, T)

  # infrastructure_io (R): Filesystem-Writer; trennt Builder (A) von Writer (R/T)
  boundary/
    filesystem/                # Filesystem: Atomic-Write-Helpers, Artifact-Writer
      atomic.py
      read.py
    shared/                    # (Unter-Namespace von boundary; kein eigenes boundary_module)
      time.py

  # config_foundation (R) + shared_foundation (A)
  config/                      # Config: Pydantic-v2-Konfigurationsmodelle, Loader, Schema-Validierung
  shared/                      # Shared: fachneutrale Basistypen, Exceptions, stateless Hilfen

  # kein Python-Code
  resources/                   # Deployte Assets und interne Prompts/Schemas
```

**Regeln:**

1. Ein fachlicher Top-Level-Namespace unter `src/agentkit/`
   repraesentiert genau eine fachliche Komponente.
2. Subkomponenten werden als Unterpakete **nur dann** angelegt, wenn
   sie ausschliesslich der uebergeordneten Komponente dienen.
3. Querschnittsmodule wie `utils/`, `workers/`, `qa/`, `governance/`
   oder `pipeline/` sind als dauerhafte Zielstruktur **nicht**
   zulaessig, wenn sie mehrere fachliche Komponenten vermischen.
4. `integrations/` bleibt als technischer Adapter-Schnitt bestehen,
   weil dies bewusst eine Infrastrukturgrenze und keine Fachkomponente
   ist.
5. `shared/` ist streng minimal zu halten: Basistypen, Exceptions,
   kleine stateless Hilfen. Keine Geschaeftslogik.

### Modulstruktur und Verantwortlichkeiten

Normativer Schnitt gemaess `concept/formal-spec/architecture-conformance/entities.md`.

| Namespace | Verantwortlichkeit | Abhaengigkeitsrichtung |
|---|---|---|
| `pipeline_engine/` | 5-Phasen-Orchestrierung, Knotenkomposition, Run-Steuerung, Transitionen (BC 1) | Nutzt StoryContext, Worktree, VerifySystem, Telemetrie, State |
| `verify_system/` | Mehrschichtige QA-Capability: Stages, LLM-Evaluationen, Konformanz, Policy-Aggregation (BC 2) | Nutzt Telemetrie, Artifacts, FailureCorpus |
| `story_context_manager/` | Autoritativer Story-Kontext, Story-Lifecycle, Story-Identity und Vertragsmatrix (BC 3) | Wird von Pipeline, PromptRuntime, Governance genutzt |
| `governance/` | Guards, Permissions, Governance-Observation, Integrity-Gate, Setup-Preflight (BC 4) | Nutzt Telemetrie, Artifacts, Config |
| `exploration/` | Explorations-Routing, Entwurfsartefakt-Erzeugung, Mandats-Klassifikation (BC 5) | Nutzt StoryContext, PromptRuntime, Artifacts |
| `implementation/` | Worker-Session, iterative Implementierungsschleife, Handover-Erzeugung (BC 6) | Nutzt StoryContext, PromptRuntime, Artifacts, Governance |
| `closure/` | Integrity-Gate-Pruefungen, Merge-Ablauf, Post-Merge-Finalisierung, Abschluss-Report (BC 7) | Nutzt StoryContext, Governance, Telemetrie, Worktree |
| `artifacts/` | Artefakt-Envelopes, Producer-Registry, Envelope-Vertraege (BC 8) | Wird von Pipeline, Verify, Governance, Implementation genutzt |
| `telemetry/` | ExecutionEvents, Telemetrie-Emission, Projektion-Lesezugriff, Event-Vertraege (BC 9) | Wird von Pipeline, Governance, Closure genutzt |
| `prompt_runtime/` | Prompt-Bundle-Speicher, Versionspinning, Prompt-Materialisierung (BC 10) | Nutzt StoryContext, Resources |
| `skills/` | Skill-Bundle-Speicher, Skill-Bindung ans Zielprojekt, Qualitaetsmetriken (BC 11) | Nutzt Resources, Installer |
| `installer/` | Projektregistrierung, Bootstrap-Checkpoints, Integrations-Checkpoints, Upgrade (BC 12) | Nutzt Config, Integrationen, Resources |
| `failure_corpus/` | Incident-Triage, Muster-Promotion, Pruefregeln-Erzeugung (BC 13) | Nutzt VerifySystem.StageRegistry |
| `execution_planning/` | Planungsmodell, Proposal-Ingest, Bereitschaftspruefung, Scheduling-Policy, Plan-Ableitung (BC 14) | Nutzt StoryContext, Integrationen |
| `requirements_coverage/` | ARE-Client, Story-zu-Requirement-Mapping, ARE-Integration (BC 15) | Nutzt Integrationen |
| `kpi_analytics/` | KPI-Katalog, Faktentabellen, Aggregation, Dashboard-Serving (BC 16) | Nutzt Telemetrie |
| `worktree_manager/` | Worktree- und Branch-Lifecycle [shared] | Wird von Pipeline, StoryContextManager genutzt |
| `cli/` | CLI-Entrypoints und Command-Routing [boundary: entry_boundary, R] | Ruft fachliche Top-Level-Namespaces auf; nichts importiert cli von innen |
| `control_plane/` | HTTP-Transport, Pydantic-Modelle, Runtime-Service, Repository, Telemetrie [boundary: entry_boundary + adapter_boundary, R] | http.py ist entry_boundary; models/records/runtime/repository/telemetry sind adapter_boundary |
| `integrations/` | Duenne Adapter zu externen Systemen [boundary: adapter_boundary, R] | Wird von BCs genutzt; importiert keine BCs |
| `projectedge/` | Lokaler Projekt-Adapter fuer Sync und Bundle-Publish [boundary: adapter_boundary, R] | Wird von BCs genutzt; importiert keine BCs |
| `state_backend/` | Repository-Schicht, Persistenz-Identitaet, Pfade, Postgres-/SQLite-Treiber [boundary: adapter_boundary + infrastructure_io + infrastructure_driver] | store.py/scope.py sind R; paths.py ist infrastructure_io (R); postgres_store.py/sqlite_store.py/config.py sind T |
| `boundary/filesystem/` | Filesystem-Writer und Atomic-Write-Helpers [boundary: infrastructure_io, R] | Trennt Builder (A) von Writer; A-BCs importieren keinen direkten Filesystem-I/O |
| `config/` | Pydantic-v2-Konfigurationsmodelle, Loader, Schema-Validierung [boundary: config_foundation, R] | Wird gelesen, nie geschrieben; keine Domain-Logik |
| `shared/` | Fachneutrale Basistypen, Exceptions, stateless Hilfen [boundary: shared_foundation, A] | Importiert nichts Fachliches und keine Boundary-Module mit I/O |

### Boundary-Module (schema_version 2)

Die Boundary-Module sind in
`concept/formal-spec/architecture-conformance/entities.md` (schema_version 2)
als `boundary_modules` neben den `component_groups` modelliert. Sie sind
keine fachlichen BCs, sondern Eingangs-, Adapter-, Infrastruktur- und
Foundation-Schichten mit klar definierten Importregeln.

Sechs Boundary-Module-Arten (`boundary_module_kinds`):

| Art | Code | Bedeutung |
|---|---|---|
| Eingangs-Boundary | `entry_boundary` | Ruft fachliche BCs auf, hat keine Geschaeftslogik; nichts importiert sie von innen |
| Adapter-Boundary | `adapter_boundary` | Duenne Wrapper ueber externe APIs; werden von BCs aufgerufen, importieren keine BCs |
| Konfigurations-Foundation | `config_foundation` | Konfiguration und Schema-Validierung; wird gelesen, nie geschrieben |
| Shared-Foundation | `shared_foundation` | Fachneutrale Basistypen, Exceptions, stateless Hilfen; importiert nichts Fachliches |
| Infrastruktur-Driver | `infrastructure_driver` | Persistenz-/Infrastrukturtreiber (T-Bluttyp); nur von R-Adaptern aufgerufen |
| Infrastruktur-IO | `infrastructure_io` | Filesystem-Writer; trennt Builder (A) von Writer (R/T) |

Uebersicht der 12 Boundary-Module:

| Namespace | Boundary-ID | Art | Bluttyp |
|---|---|---|---|
| `cli/` | `boundary.cli` | entry_boundary | R |
| `control_plane/http.py` | `boundary.control_plane_http` | entry_boundary | R |
| `control_plane/models.py` + `records.py` | `boundary.control_plane_records` | adapter_boundary | R |
| `control_plane/runtime.py` + `repository.py` + `telemetry.py` | `boundary.control_plane_runtime` | adapter_boundary | R |
| `integrations/` | `boundary.integrations` | adapter_boundary | R |
| `projectedge/` | `boundary.projectedge` | adapter_boundary | R |
| `state_backend/store.py` | `boundary.state_backend_repository` | adapter_boundary | R |
| `state_backend/scope.py` | `boundary.state_persistence_scope` | adapter_boundary | R |
| `config/` | `boundary.config` | config_foundation | R |
| `shared/` + `exceptions/` | `boundary.shared` | shared_foundation | A |
| `boundary/filesystem/` + `state_backend/paths.py` | `boundary.filesystem` | infrastructure_io | R |
| `state_backend/postgres_store.py` + `sqlite_store.py` + `config.py` | `boundary.state_backend_drivers` | infrastructure_driver | T |

`resources/` enthaelt deployte Assets und interne Prompts/Schemas; **kein Python-Code**.

### Regeln fuer Module

1. **Keine zirkulaeren Imports.** Abhaengigkeitsrichtung ist top-down: `cli` -> fachliche Top-Level-Namespaces -> `integrations|config|resources|shared`.
2. **Neue Namespaces** nur mit fachlicher Begruendung. Keine technischen Sammelcontainer ohne eigene Verantwortung.
3. **Fachliche Top-Level-Namespaces sind der Normalfall fuer Produktionslogik.** Neue Fachlogik gehoert dorthin, nicht in querschnittige Restkategorien.
4. **`resources/` enthaelt keinen Python-Code.** Nur Templates, Prompts, Schemas, Config-Dateien.
5. **`integrations/` sind Adapter.** Geschaeftslogik gehoert in die fachlichen Komponenten, nicht in die Adapter.
6. **`shared/` bleibt klein.** Wenn ein Modul Fachwissen ueber Pipeline, Guards, QA, Storys oder Installer enthaelt, gehoert es nicht nach `shared/`.

### tools/ — Architektur- und Build-Tooling

```text
tools/
  concept_compiler/            # Compiler/Linter/Scenario-Runner fuer formale Konzept-Spezifikationen
```

**Regeln:**

1. Tooling unter `tools/` ist **kein** Produktivcode und darf nicht
   unter `src/agentkit/` liegen.
2. Der `concept_compiler` liest aus `concept/formal-spec/` und
   schreibt nur abgeleitete Artefakte nach `var/`.
3. Tests fuer Tooling liegen unter `tests/`, nicht unter `tools/`.

### Installer-Komponente

`installer/` (BC 12) ist die fachliche Komponente fuer Projektregistrierung
und Bootstrap. Substruktur gemaess `entities.md`:

- `checkpoint_engine/` — idempotente Checkpoint-Ausfuehrung
- `bootstrap_checkpoints/` — Erstregistrierungs-Checkpoints
- `integration_checkpoints/` — Integrations-spezifische Checkpoints
- `upgrade/` — Upgrade bestehender Installationen

### Phasen als eigenstaendige Bounded Contexts

Die 5 Phasen der Pipeline sind in v3 **eigenstaendige fachliche BCs**,
keine Subverzeichnisse unter `pipeline_engine/`:

| Phase | BC | Namespace |
|---|---|---|
| 1 — Setup | BC 4 governance | `governance/setup_preflight_gate/` |
| 2 — Exploration | BC 5 exploration | `exploration/` |
| 3 — Implementation | BC 6 implementation | `implementation/` |
| 4 — Verify | BC 2 verify_system | `verify_system/` |
| 5 — Closure | BC 7 closure | `closure/` |

`pipeline_engine/` (BC 1) ist die Orchestrierungsmaschine, die diese BCs
aufruft — nicht ihr Container. Neue Phasen-Logik gehoert in den jeweiligen
BC, nicht in `pipeline_engine/`.

### resources/ — Single Source of Truth

```
resources/
  target_project/     # Was ins Zielprojekt deployt wird
    .agentkit/        # Prompts, Hooks, Config, Manifests
    .claude/          # Skills, Context
    templates/        # Jinja2-Templates (CLAUDE.md.j2, project.yaml.j2, ...)
    tools/
      agentkit/
        projectedge.py  # Zielprojekt-Code (kein AgentKit3-Produktionscode)
  internal/           # Interne Prompts und Schemas (werden NICHT deployt)
```

**Regeln:**
- Jede deployte Datei existiert GENAU EINMAL unter `resources/target_project/`.
- Keine Kopien in `tests/fixtures/` — Tests lesen aus `resources/` oder vergleichen gegen `tests/golden/`.
- Aenderungen an deploybaren Assets erfordern Aktualisierung der Golden Files.
- `resources/target_project/tools/agentkit/projectedge.py` ist Zielprojekt-Code, kein
  AgentKit3-Produktionscode. Es wird ins Zielprojekt deployt und laeuft dort als lokaler
  Projekt-Adapter (entspricht `boundary.projectedge` auf der Zielseite).

---

## tests/ — Vier Testebenen

### Ueberblick

| Ebene | Verzeichnis | Geschwindigkeit | CI | Zweck |
|---|---|---|---|---|
| Unit | `tests/unit/` | Sekunden | Jeder PR | Reine Logik, keine I/O |
| Integration | `tests/integration/` | Minuten | Jeder PR | Simulierte Zielprojekte, echte Dateisystem-Ops |
| Contract | `tests/contract/` | Sekunden | Jeder PR | Schema-Stabilitaet, Snapshot-Vergleiche |
| E2E | `tests/e2e/` | Minuten-Stunden | Manuell/Nightly | Live-Systeme (GitHub, VectorDB, MCP, ...) |

### Regeln

1. **Unit-Tests spiegeln die Code-Heimat.** `src/agentkit/pipeline_engine/` ->
   `tests/unit/pipeline_engine/`. Analog fuer alle BCs.
2. **Integration-Tests sind szenariobasiert**, nicht modulbasiert. Beispiel: `install_fresh/`, `upgrade_preserve_local_edits/`.
3. **Contract-Tests schuetzen Stabilitaet.** Prompt-Sentinels, Schema-Versionen, Manifest-Formate. Brechen wenn sich ein oeffentliches Format aendert.
4. **E2E-Tests sind IMMER opt-in.** Marker: `@pytest.mark.e2e`. Nie in Standard-CI. Brauchen echte Credentials.
5. **Golden Files** (`tests/golden/`) sind versioniert. Aktualisierung erfordert bewussten Review.
6. **Fixtures** (`tests/fixtures/`) enthalten statische Testdaten. Keine generierten Dateien — die gehoeren in `var/` oder `tmp_path`.
7. **Neue Tests** gehoeren in die richtige Ebene. Im Zweifel: Unit vor Integration, Integration vor E2E.

### Test-Verzeichnisse

```
tests/
  conftest.py                     # Gemeinsame Fixtures, Marker-Registrierung
  unit/                           # Spiegelt src/agentkit/ Struktur
  integration/
    installer/                    # Register/Upgrade-Szenarien
    target_project_sim/           # Verschiedene Projektkonfigurationen
    pipeline_engine/              # Pipeline-Durchlaeufe
    governance_hooks/
    prompts_and_skills/
    artifact_schemas/
  contract/
    scaffold_snapshots/           # Gerenderte Zielprojekt-Dateien
    prompt_templates/             # Prompt-Sentinels
    skill_manifests/
    checkpoint_manifests/
    external_adapter_contracts/
  e2e/
    smoke/                        # Minimaler Durchlauf
    github_live/
    vectordb_live/
    are_live/
    mcp_live/
    llm_pools_live/
  fixtures/                       # Statische Testdaten
  golden/                         # Golden-File-Snapshots
```

---

## stories/ — Story-Artefakte

Das `stories/`-Verzeichnis ist der Ablageort fuer Story-bezogene Arbeitsergebnisse. Hier landen Artefakte die waehrend der Story-Ausfuehrung durch die Pipeline erzeugt werden.

---

## Tool-Caches und generierte Verzeichnisse

### Im Root belassen (Tool-Defaults, gitignored)

Diese Verzeichnisse werden von Python-Tools automatisch erzeugt und bleiben dort wo sie standardmaessig landen:

- `.pytest_cache/`, `.mypy_cache/`, `.ruff_cache/`, `__pycache__/`
- `.coverage`, `htmlcov/`
- `*.egg-info/`, `dist/`, `build/`
- `.venv/`

**Nicht umleiten.** Gegen Tool-Defaults zu arbeiten erzeugt Friction bei Entwicklern, IDEs und CI.

### var/ — Projekt-eigene ephemere Daten

`var/` ist gitignored und reserviert fuer AgentKit-eigene Laufzeitdaten:
- `var/tmp/` — Temporaere Dateien (Merge-Files, Zwischenergebnisse)
- `var/logs/` — Lokale Laufzeit-Logs
- `var/sandboxes/` — Test-Sandboxes, simulierte Zielprojekte

**Regel:** Alles in `var/` ist wegwerfbar. Kein Agent darf `var/` als Source of Truth verwenden.

---

## Verbotene Muster

| Muster | Warum verboten |
|---|---|
| Zielprojekt-Struktur im Repo-Root | Development-Codebase ist nicht das Zielprojekt |
| Deployte Dateien mehrfach vorhalten | Genau eine Source of Truth: `resources/target_project/` |
| Phasen-Logik als Subdirectory von `pipeline_engine/` | Exploration, Implementation, Verify, Closure sind eigenstaendige BCs |
| E2E-Tests in Standard-CI | Brauchen Credentials, sind langsam, nicht deterministic |
| Tool-Caches umleiten | Erzeugt nur Friction, `.gitignore` reicht |
| Geschaeftslogik in `integrations/` | Adapter sind duenn, Logik gehoert in fachliche Komponenten |
| Python-Code in `resources/` | Nur Templates, Prompts, Schemas, Config-Dateien |
| Neue Top-Level-Verzeichnisse ohne Consent | Struktur ist bewusst designed, nicht ad-hoc erweiterbar |
| Lose Python-Dateien im Root | Alles unter `src/agentkit/` |
| Zirkulaere Imports zwischen Modulen | Abhaengigkeitsrichtung ist top-down |

---

## Kurzreferenz fuer Agents

**Ich will neuen Produktionscode schreiben** -> `src/agentkit/<passendes-modul>/`

**Ich will ein neues Modul anlegen** -> Fachliche Begruendung noetig. Kein Modul fuer eine Klasse.

**Ich will einen Test schreiben** -> Richtige Ebene waehlen: `unit/` (Logik), `integration/` (Dateisystem/Szenarien), `contract/` (Stabilitaet), `e2e/` (Live-Systeme).

**Ich will ein Deploy-Asset aendern** -> `src/agentkit/resources/target_project/` aendern, dann Golden Files in `tests/golden/` aktualisieren.

**Ich will temporaere Dateien erzeugen** -> `var/` oder `tmp_path` (in Tests). Nie in `src/` oder `tests/fixtures/`.

**Ich will eine Integration hinzufuegen** -> `src/agentkit/integrations/<name>/` als duenner Adapter. Geschaeftslogik im fachlichen Modul.

**Ich will die Struktur erweitern** -> Dieses Dokument konsultieren. Neue Top-Level-Verzeichnisse nur mit User-Consent.
