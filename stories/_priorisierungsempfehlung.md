# Priorisierungsempfehlung: Fundament-Themen aus 17 GAP-Analysen

> Generiert von einem Opus-Analyse-Agent (Stand 2026-05-16).
> Quelle: alle `<bc-id>-gap-analyse.md` im Stories-Root.

## 1. Befund-ID-Schema

Globale Referenz pro GAP-Befund: `<bc-id>.<A|B|C><nr>` aus der jeweiligen BC-Markdown.
Themen-IDs: `THEME-NNN` (dreistellig, in Priorisierungsreihenfolge).

## 2. Uebersicht der Themen

| Prio | THEME-ID | Titel | Voraussetzungen | Betroffene BCs |
|---:|---|---|---|---:|
| 1 | THEME-001 | Modul-Prefix-Konsolidierung und Repo-Hygiene (Single Source of Truth) | - | 11 |
| 2 | THEME-002 | Typisierte Kern-Enums (Severity, QaContext, PauseReason, ArtifactClass u.a.) | - | 10 |
| 3 | THEME-003 | Artefakt-BC: ArtifactEnvelope, ArtifactManager, ProducerRegistry | THEME-001, THEME-002 | 8 |
| 4 | THEME-004 | PhaseEnvelope, AttemptRecord, Write-Ordering Crash-Safety | THEME-002 | 4 |
| 5 | THEME-005 | Top-Surfaces der Capability-BCs (VerifySystem, PromptRuntime, Skills u.a.) | THEME-001, THEME-002, THEME-003 | 9 |
| 6 | THEME-006 | Principal-Capability-Modell, Guard-Dispatch, Preflight-10, Branch-/Self-Protection | THEME-001, THEME-002 | 5 |
| 7 | THEME-007 | Telemetrie-Hooks, TelemetryContract, ProjectionAccessor, Reset-Purge | THEME-001, THEME-002, THEME-003 | 9 |
| 8 | THEME-008 | Persistenz-Topologie: PostgreSQL analytics-Schema und kanonische Stores | THEME-001, THEME-002 | 6 |
| 9 | THEME-009 | QA-Zyklus-Kernlogik: Layer-1-Pflichtchecks, Layer-2 echte LLM-Aufrufe, worker-manifest, advance_qa_cycle | THEME-002, THEME-003, THEME-004, THEME-005, THEME-006 | 5 |
| 10 | THEME-010 | Exploration-Phase-Handler (Drafting, Review, MandateClassification) | THEME-002, THEME-005, THEME-006, THEME-009 | 4 |

## 3. Themen im Detail

### THEME-001: Modul-Prefix-Konsolidierung und Repo-Hygiene (Single Source of Truth)

**Voraussetzungen:** keine
**Warum jetzt?** Solange Code unter falschen Modul-Pfaden liegt, importieren alle nachfolgenden BCs gegen tote oder ambivalente Pfade. Jede weitere Story auf bestehendem Doppel-Code (z.B. `guard_system` + `governance.guard_system`) verfestigt den Drift. Klassischer v2-Wiederholungsfehler.
**Umfasste Befunde:**
- `pipeline-framework.B1` — Migration `agentkit.pipeline` -> `agentkit.pipeline_engine` (Facades aufloesen)
- `pipeline-framework.C5` — Doppel-Facade `phase_state_store` vs. `pipeline.state`
- `prompt-runtime.C1` — Gesamt-BC unter `prompt_composer` statt `prompt_runtime`
- `kpi-and-dashboard.C2` — Code unter `agentkit.dashboard` + `agentkit.telemetry.kpis` statt `agentkit.kpi_analytics`
- `governance-and-guards.C1` — Duplikat `guard_system` vs. `governance.guard_system`
- `governance-and-guards.C2` — `governance.monitoring` leer statt `governance.governance_observer`
- `governance-and-guards.C3` — `doc_fidelity` und `policies` faelschlich unter `governance/`
- `verify-system.C4` — Legacy `agentkit.llm_evaluator` als Shim
- `telemetry-and-events.C1` — `telemetry_service/` als Pass-Through-Facade ohne Schreibgrenze
- `exploration-and-design.C1` — `pipeline_engine/verify_phase` mit `.pyc`-Resten ohne Quellcode
- `agent-skills.C2` — `project_ops/install/__pycache__` mit `.pyc` ohne Quellcode
- `artifacts.C1` — QA-Artefakt-Persistenz faelschlich Owner-Position in `verify_system/artifacts.py`
- `artifacts.C2` — `PROTECTED_QA_ARTIFACTS` in `state_backend/paths.py` statt `governance-and-guards`

**Konzept-Anker:** `concept/_meta/bc-cut-decisions.md §Konzept-Refactor-Liste` (Punkte 1-8), `concept/_meta/bc-cut-decisions.md §BC 1`, `§BC 8`, `§BC 10`, `§BC 11`, `§BC 16`, `CLAUDE.md §SINGLE SOURCE OF TRUTH`
**Betroffene BCs:** pipeline-framework, prompt-runtime, kpi-and-dashboard, governance-and-guards, verify-system, telemetry-and-events, exploration-and-design, agent-skills, artifacts, implementation-phase (indirekt), story-closure (indirekt)

---

### THEME-002: Typisierte Kern-Enums (Severity, QaContext, PauseReason, ArtifactClass u.a.)

**Voraussetzungen:** keine
**Warum jetzt?** Mehrere BCs warten auf identische Typ-Definitionen (BLOCKING/MAJOR/MINOR vs. CRITICAL/HIGH/MEDIUM, vier QaContext-Werte, ExplorationGateStatus, PauseReason). Bis diese stehen, kann jede Stage-Registry, Policy-Engine, Telemetrie-Projektion, Gate-Guard und Audit-Trail nur gegen freie Strings arbeiten. Spaeter koordinieren ist 5x teurer als jetzt definieren.
**Umfasste Befunde:**
- `verify-system.C1` — Severity-Schema CRITICAL/HIGH/MEDIUM statt BLOCKING/MAJOR/MINOR
- `verify-system.C2` — `PASS_WITH_WARNINGS` konzeptlos
- `exploration-and-design.A6` — `ExplorationGateStatus`-StrEnum fehlt
- `exploration-and-design.B2` — `gate_status: str | None` ungetypt
- `exploration-and-design.C2` — `VerifyContext`/QaContext: nur 2 von 4 Werten, falsche Namen
- `pipeline-framework.C2` — `PauseReason` als freier String
- `pipeline-framework.C4` — `AttemptRecord` ohne `failure_cause`, falsche Felder
- `pipeline-framework.B2` — `AttemptOutcome` und `FailureCause` als StrEnum fehlen
- `story-lifecycle.C1` — `StorySize` (small/medium/large/epic) vs. konzeptuell XS/S/M/L/XL; `WireStorySize` zusaetzlich XXL
- `story-lifecycle.C2` — `StoryMode.NOT_APPLICABLE` nicht im Konzept normiert
- `story-closure.A9` — `ClosureVerdict`, `MergePolicy` fehlen
- `implementation-phase.A4` — `BlockingCategory`-StrEnum fehlt
- `implementation-phase.C2` — `SpawnReason` wird als String-Literal verglichen
- `execution-planning.C1` — `StoryDependencyKind`-Vokabular weicht ab (blocks/derives_from/branches_off statt 8 normierter Typen)
- `artifacts.B3` — `EnvelopeStatus`-Werte uneinheitlich

**Konzept-Anker:** `FK-27 §27.4.2`, `FK-27 §27.7.2`, `FK-23 §23.5.0`, `FK-39 §39.2.2`, `FK-39 §39.4.2/39.4.3`, `FK-71 §71.1.1/71.2`, `FK-24 §24.3.2`, `FK-29 §29.1.5`, `FK-70 §70.4.2`, `concept/_meta/bc-cut-decisions.md §QaContext-Werte`
**Betroffene BCs:** verify-system, exploration-and-design, pipeline-framework, story-lifecycle, story-closure, implementation-phase, execution-planning, artifacts, governance-and-guards (indirekt), telemetry-and-events (indirekt)

---

### THEME-003: Artefakt-BC — ArtifactEnvelope, ArtifactManager, ProducerRegistry

**Voraussetzungen:** THEME-001, THEME-002
**Warum jetzt?** Das Paket `agentkit.artifacts` existiert nicht. Jede QA-, Prompt-, Worker- und Closure-Schreiblogik baut deshalb rohe dicts ohne Envelope-Pflichtfelder. Ohne ArtifactEnvelope kann das IntegrityGate keine Pflichtfelder pruefen, die Producer-Registry kein LLM-Status-Mapping liefern und keine BC-Grenze fuer QA-Artefakte sauber gezogen werden. Direkter v2-Wiederholungsfehler (JSON-Wildwuchs ohne Owner).
**Umfasste Befunde:**
- `artifacts.A1` — Paket `agentkit.artifacts` fehlt
- `artifacts.A2` — `ArtifactManager` fehlt
- `artifacts.A3` — `ArtifactEnvelope`-Pydantic-Modell fehlt
- `artifacts.A4` — `EnvelopeValidator` fehlt
- `artifacts.A5` — `ProducerRegistry` mit LLM-Status-Mapping fehlt
- `artifacts.A6` — `Producer`, `ProducerType`, `ProducerId` fehlen
- `artifacts.A7` — `ArtifactReference` fehlt
- `artifacts.B1` — Nur 2 von 8 Artefaktklassen
- `artifacts.B2` — QA-Persistenz im falschen BC (verify_system)
- `artifacts.B4` — IntegrityGate prueft nur Existenz, keine Pflichtfelder
- `artifacts.C3` — `SCHEMA_VERSION="3.3.0"` verwechselbar mit Envelope-`schema_version="3.0"`
- `prompt-runtime.A5` — `AuditRecord`-Persistenz braucht `ArtifactManager`
- `requirements-and-scope-coverage.A3` — `are_bundle.json` braucht `ArtifactManager`

**Konzept-Anker:** `FK-71 §71.1/71.2`, `concept/_meta/bc-cut-decisions.md §BC 8`, `CLAUDE.md §SINGLE SOURCE OF TRUTH`, `CLAUDE.md §FIX THE MODEL`
**Betroffene BCs:** artifacts, verify-system, prompt-runtime, requirements-and-scope-coverage, governance-and-guards (IntegrityGate), implementation-phase (handover), story-closure (ExecutionReport), telemetry-and-events (Envelope-Verbindung)

---

### THEME-004: PhaseEnvelope, AttemptRecord, Write-Ordering Crash-Safety

**Voraussetzungen:** THEME-002
**Warum jetzt?** Crash-Safety-Bug in `_handle_completed_result` (save_phase_state vor save_attempt) verletzt FK-39 §39.4.4 jetzt schon. PhaseEnvelope und RuntimeMetadata sind Voraussetzung fuer korrekte Persistenz/Recovery-Verteilung; QA-Zyklus-Identitaeten (qa_cycle_id/round, evidence_epoch) bauen auf der gleichen Persistenz-Grenze auf. Reparatur jetzt vermeidet Datenverlust und blockiert THEME-009 nicht.
**Umfasste Befunde:**
- `pipeline-framework.C1` — `PhaseEnvelope` und `RuntimeMetadata` fehlen
- `pipeline-framework.B4` — Write-Ordering Bug
- `pipeline-framework.C4` — `AttemptRecord` Felder konzeptfremd, kein `failure_cause`/`ended_at`
- `verify-system.A2` — QA-Zyklus-Identitaeten und Artefakt-Invalidierung fehlen

**Konzept-Anker:** `FK-39 §39.1/39.3/39.4.1-39.4.4`, `FK-27 §27.2`, `formal.verify.state-machine`
**Betroffene BCs:** pipeline-framework, verify-system, implementation-phase, story-closure

---

### THEME-005: Top-Surfaces der Capability-BCs

**Voraussetzungen:** THEME-001, THEME-002, THEME-003
**Warum jetzt?** Acht BCs haben keine aufrufbare Top-Surface. Ohne `VerifySystem.run_qa_subflow`, `PromptRuntime.materialize_prompt`, `Skills.bind_skill`, `FailureCorpus.record_incident`, `KpiAnalytics`, `ArtifactManager.write`, `RequirementsCoverage` und `Governance.register_hooks/deactivate_locks` koennen die Konsumenten-BCs (pipeline-framework, implementation-phase, story-closure, installation-and-bootstrap) nicht typsicher integrieren. Diese Surfaces sind die fachlichen API-Vertraege, die der ganze Rest braucht — sie zuerst zu fixieren stabilisiert alle Aufrufpfade.
**Umfasste Befunde:**
- `verify-system.A1` — `VerifySystem.run_qa_subflow(ctx, story_id, qa_context, target) -> PolicyVerdict`
- `requirements-and-scope-coverage.A6`, `requirements-and-scope-coverage.C1` — `RequirementsCoverage`-Top-Surface
- `agent-skills.A1` — `Skills` mit vier Top-Methoden
- `agent-skills.C1` — Installer ruft `Skills.bind_skill` nicht
- `prompt-runtime.A1`, `prompt-runtime.A2` — `PromptRuntime`-Paket und vier Top-Methoden
- `failure-corpus.A1`, `failure-corpus.A10` — `FailureCorpus` Top-Surface inkl. `record_incident`-Empfaenger
- `kpi-and-dashboard.A1` — `KpiAnalytics`-Top-Klasse
- `governance-and-guards.A5` — `Governance.register_hooks` und `Governance.deactivate_locks`
- `artifacts.A2` — `ArtifactManager`-Top (deckt sich mit THEME-003)
- `installation-and-bootstrap.B5`, `installation-and-bootstrap.B2`, `installation-and-bootstrap.C2` — Installer braucht Top-Surfaces als Delegationsziel

**Konzept-Anker:** `concept/_meta/bc-cut-decisions.md §BC 2`, `§BC 8`, `§BC 10`, `§BC 11`, `§BC 13`, `§BC 14`, `§BC 15`, `§BC 16`, `FK-30 §30.3.1/30.6.0`, `FK-44 §44.3/44.4`, `FK-43 §43.4.1`
**Betroffene BCs:** verify-system, prompt-runtime, agent-skills, failure-corpus, kpi-and-dashboard, requirements-and-scope-coverage, artifacts, governance-and-guards, installation-and-bootstrap

---

### THEME-006: Principal-Capability-Modell, Guard-Dispatch, Preflight-10, Branch-/Self-Protection

**Voraussetzungen:** THEME-001, THEME-002
**Warum jetzt?** Aktuell laufen alle Guards (`branch_guard`, `orchestrator_guard`, `qa_agent_guard`, `self_protection_guard`, `health_monitor` ...) pauschal durch denselben Dispatcher. Sieben von zehn Preflight-Checks fehlen. Principal/PathClass/OperationClass aus FK-55 sind nicht implementiert; CCAG laeuft vor der harten Capability-Matrix. Ohne diese Schicht ist die Trust-Boundary lueckenhaft; Worker und Orchestrator koennen Artefakte und Branches manipulieren, die das Konzept als hart geschuetzt vorsieht. Direkter Angriffsvektor auf die BC-Disziplin von AK3.
**Umfasste Befunde:**
- `governance-and-guards.A3` — FK-55 Principal/PathClass/OperationClass/Matrix/Freeze fehlen
- `governance-and-guards.A4` — Conflict-Freeze-Overlay fehlt
- `governance-and-guards.A6` — Self-Protection-Guard fehlt
- `governance-and-guards.A7` — Story-Creation-Guard fehlt
- `governance-and-guards.B1` — Preflight-Checks 2, 5-10 fehlen
- `governance-and-guards.B2` — IntegrityGate nur 4 von 8 Dimensionen
- `governance-and-guards.B3` — Modus-Ermittlung (4 Trigger REF-032) fehlt
- `governance-and-guards.B4` — Orchestrator-Guard kein eigenes Modul
- `governance-and-guards.B5` — CCAG vor harter Capability-Matrix
- `governance-and-guards.C4` — IntegrityGate behandelt CONCEPT/RESEARCH wie IMPLEMENTATION
- `governance-and-guards.C5` — Hook-Dispatch pauschal auf `evaluate_pre_tool_use`
- `pipeline-framework.B3` — Phase-Transition-Enforcement keine FK-45-Semantik

**Konzept-Anker:** `FK-22 §22.3/22.8`, `FK-30 §30.2.6/30.5/30.3.1`, `FK-31 §31.2/31.5`, `FK-35 §35.2`, `FK-55 §55.3-55.10`, `DK-03`, `formal.principal-capabilities.*`, `formal.setup-preflight.*`
**Betroffene BCs:** governance-and-guards, pipeline-framework, story-lifecycle, implementation-phase, story-closure

---

### THEME-007: Telemetrie-Hooks, TelemetryContract, ProjectionAccessor, Reset-Purge

**Voraussetzungen:** THEME-001, THEME-002, THEME-003
**Warum jetzt?** Die harness-basierten Hooks (`AgentLifecycleHook`, `CommitHook`, `ReviewSentinelHook`, `ReviewGuard`, `BudgetEventEmitter`, `DriftCheckHook`, `DivergenceHook`) sind die Hauptquelle fuer Pflicht-Events. Ohne sie kann IntegrityGate keine Telemetrie-Compliance pruefen, GovernanceObserver kein Rolling-Window scoren und KpiAnalytics keine Fact-Tabellen befuellen. Zudem fehlt ein zentraler `ProjectionAccessor`, sodass FK-69 Read-Models heute aus `verify_system` und `closure` heraus geschrieben werden — SoT-Drift. Reset-Purge fehlt fail-closed.
**Umfasste Befunde:**
- `telemetry-and-events.A1` — Harness-Hooks fehlen
- `telemetry-and-events.A2` — `DivergenceHook` fehlt
- `telemetry-and-events.A3` — NormalizedEvent fuer Risk-Window fehlt
- `telemetry-and-events.A4` — JSONL-Audit-Bundle-Export fehlt
- `telemetry-and-events.A5` — `ProjectionAccessor` zentralisieren
- `telemetry-and-events.A6` — Reset-Purge fuer FK-69-Tabellen fehlt
- `telemetry-and-events.B1` — `TelemetryContract` fehlt
- `telemetry-and-events.B2` — Preflight-Telemetrie-Stream nur Event-Typen
- `telemetry-and-events.B3` — Workflow-Metriken-Felder leer
- `telemetry-and-events.B4` — FK-69 Read-Models verteilt
- `telemetry-and-events.B5` — SSE-Topic-Mapping heuristisch
- `telemetry-and-events.C2` — `qa_rounds`-Berechnung nicht konzeptkonform
- `exploration-and-design.A7` — `mandate_classification`, `fine_design_decision` Event-Typen fehlen
- `implementation-phase.B3` — `WORKER_HEALTH_SCORE`/`_INTERVENTION` Event-Typen fehlen
- `execution-planning.A10` — Planning-Events fehlen vollstaendig
- `requirements-and-scope-coverage.A8` — ARE-Events fehlen
- `failure-corpus.A6` — `fc_*`-Persistenz via Telemetry.write_projection

**Konzept-Anker:** `FK-68 §68.2-68.10`, `FK-69 §69.3/69.4/69.10.1`, `DK-05`, `formal.telemetry-analytics.*`
**Betroffene BCs:** telemetry-and-events, verify-system, exploration-and-design, implementation-phase, execution-planning, requirements-and-scope-coverage, failure-corpus, governance-and-guards (GovernanceObserver), kpi-and-dashboard

---

### THEME-008: Persistenz-Topologie — PostgreSQL analytics-Schema und kanonische Stores

**Voraussetzungen:** THEME-001, THEME-002
**Warum jetzt?** FK-60 §60.2 P8 schreibt PostgreSQL zwingend vor. Das analytics-Schema mit fuenf Fact-Tabellen fehlt komplett; `project_registry` aus FK-50 ebenfalls; `postgres_store` deckt `project_management` nur unvollstaendig ab; `fc_*`-Tabellen sind unangelegt; `PhaseEnvelopeStore` als BC-eigener Sub fehlt. Ohne fixierte Persistenz-Topologie laufen Stories, KPIs und Failure-Corpus weiter auf SQLite + verteilten JSON-Dateien. Cross-BC-Blocker fuer THEME-007 (ProjectionAccessor), THEME-009 (QA-Zyklus-Persistenz) und Produktionsbetrieb.
**Umfasste Befunde:**
- `pipeline-framework.A2` — `PhaseEnvelopeStore` als Sub fehlt
- `kpi-and-dashboard.A3` — `FactStore`-Sub fehlt
- `kpi-and-dashboard.A4` — fuenf Fact-Tabellen + `sync_state` fehlen
- `kpi-and-dashboard.A5` — `RefreshWorker` fehlt
- `kpi-and-dashboard.A6` — `guard_invocation_counters`-Scratchpad fehlt
- `kpi-and-dashboard.A12` — Schema-Migrations-Strategie
- `installation-and-bootstrap.A2` — `project_registry`-Tabelle + `ProjectRegistration` fehlt
- `project-management.B2` — `postgres_store` fuer project_management unvollstaendig
- `failure-corpus.A6` — `fc_incidents`/`fc_patterns`/`fc_check_proposals`-Tabellen

**Konzept-Anker:** `FK-60 §60.2 P8`, `FK-62 §62.2-62.4`, `FK-41 §41.3`, `FK-50 §50.3 CP 7`, `FK-73 §73.4`, `concept/_meta/bc-cut-decisions.md §BC 1 Layer 1`
**Betroffene BCs:** pipeline-framework, kpi-and-dashboard, installation-and-bootstrap, project-management, failure-corpus, telemetry-and-events

---

### THEME-009: QA-Zyklus-Kernlogik (Layer-1-Pflichtchecks, Layer-2 echte LLM-Aufrufe, worker-manifest, advance_qa_cycle)

**Voraussetzungen:** THEME-002, THEME-003, THEME-004, THEME-005, THEME-006
**Warum jetzt?** Layer 2 und Layer 3 sind heute Passthrough-Stubs (immer PASS); Layer 1 prueft nur Meta-Checks (keine Artefakte, Branch, Build, Test, Hygiene, Recurring Guards); `worker-manifest.json` wird vom ImplementationHandler ignoriert (Invariante `worker_blocked_escalates` verletzt). Solange QA leer laeuft, ist der Kernauftrag von AK3 (autonome QA der Worker-Arbeit) nicht erfuellt. Eine vorhandene QA ohne Substanz ist gefaehrlicher als sichtbar fehlende QA.
**Umfasste Befunde:**
- `verify-system.A2` — QA-Zyklus-Mechanik (advance_qa_cycle, evidence_epoch, Invalidierung)
- `verify-system.A8` — Adversarial-Spawn via agents_to_spawn, Sandbox, Mandatory Targets
- `verify-system.B1` — Layer 1: Artefakt-Checks, Branch-Checks, Build/Test, Hygiene, Recurring Guards, ARE-Gate
- `verify-system.B2` — Layer 2: StructuredEvaluator, ParallelEvalRunner, drei Rollen, fail-closed
- `verify-system.B3` — Policy-Engine: Stage-Registry-Bindung, BLOCKING/MAJOR/MINOR
- `verify-system.B5` — Finding-Resolution-Status fehlt
- `verify-system.B6` — Remediation-Loop-Zaehler ohne ESCALATED-Pfad
- `verify-system.B7` — Prompt-Templates `qa-semantic`/`qa-adversarial` Stubs
- `verify-system.C3` — `guard.llm_reviews`/`guard.multi_llm` als BLOCKING-Gates fehlen
- `implementation-phase.C1` — Handler liest `worker-manifest.json` nicht
- `implementation-phase.A1` — `WorkerSession`, Spawn-Protokoll, Context-Resolution
- `implementation-phase.A2` — `WorkerLoop`, Vier-Schritt-Inkrement, Drift-Check Stufe 1
- `implementation-phase.A3` — `HandoverPackager`
- `implementation-phase.A4` — `WorkerManifest`, `BlockingCategory`
- `implementation-phase.B1` — BLOCKED-Exit liest kein Manifest
- `implementation-phase.B5` — Structural-Checker prueft keine Worker-Artefakte

**Konzept-Anker:** `FK-26 §26.1-26.11`, `FK-27 §27.2-27.7`, `FK-32`, `FK-33`, `FK-34`, `FK-37`, `FK-38`, `FK-46`, `FK-47`, `FK-48`, `DK-04 §4.5/4.6`, `formal.implementation.invariants §worker_blocked_escalates`, `formal.verify.state-machine`
**Betroffene BCs:** verify-system, implementation-phase, story-closure, governance-and-guards (IntegrityGate-Dimensionen), exploration-and-design (Verify-Aufruf)

---

### THEME-010: Exploration-Phase-Handler (Drafting, Review, MandateClassification)

**Voraussetzungen:** THEME-002, THEME-005, THEME-006, THEME-009
**Warum jetzt?** `pipeline/phases/exploration/__init__.py` ist leer. Der gesamte Exploration-Mode fuer Implementation- und Bugfix-Stories ist Nicht-Funktional. Ohne ExplorationDrafting/Review/MandateClassification koennen Stories mit unklarem Konzept nicht sauber durchlaufen. Voraussetzung: `VerifySystem.run_qa_subflow` (THEME-005/009), `ExplorationGateStatus` (THEME-002), Story-Branch-Guards (THEME-006). Sobald die Voraussetzungen stehen, ist Exploration der naechste grosse Konzept-Block.
**Umfasste Befunde:**
- `exploration-and-design.A1` — `ExplorationPhaseHandler` Top-Komponente
- `exploration-and-design.A2` — `ExplorationDrafting`-Sub (7 Worker-Schritte)
- `exploration-and-design.A3` — `ExplorationReview`-Sub (3-stufiges Exit-Gate)
- `exploration-and-design.A4` — `MandateClassification` (H2-Nachklassifikation, Klasse 1-4)
- `exploration-and-design.A5` — `DesignFreezeMarker` (Entwurfsartefakt-Freeze)
- `exploration-and-design.A8` — Tests fuer Exploration-Kernlogik
- `exploration-and-design.B1` — `exploration_gate_approved`-Guard ohne Payload-Pruefung
- `exploration-and-design.B3` — Workflow-DSL ohne typisierte Gate-Stufen
- `exploration-and-design.B4` — Drift-Erkennung nur EventType, kein Code
- `exploration-and-design.C3` — Bugfix-Profil blockiert Exploration-Vorlauf

**Konzept-Anker:** `FK-23 §23.1-23.8`, `FK-25 §25.3-25.6`, `formal.exploration.state-machine/entities/commands/events/invariants/scenarios`, `concept/_meta/bc-cut-decisions.md §BC 5`
**Betroffene BCs:** exploration-and-design, pipeline-framework, verify-system, story-lifecycle

---

## 4. Begruendung der Gesamtreihenfolge

Die Reihenfolge folgt dem v3-Zielbild: zuerst die *strukturellen Voraussetzungen* (wo lebt der Code, welche Typen gelten, welcher Envelope schliesst Schreibvorgaenge ab), dann die *fachlichen Top-Surfaces* (was duerfen andere BCs aufrufen), dann die *Trust-Boundary* (was darf wer veraendern), dann die *operative Mechanik* (QA-Zyklus, Worker-Loop, Exploration). THEME-001 und THEME-002 sind echte Vorbedingungen ohne Abhaengigkeiten und koennen parallel begonnen werden. THEME-003 (Artefakte) und THEME-004 (PhaseEnvelope/AttemptRecord) sind voneinander unabhaengig und sollten parallel laufen, da sie verschiedene Persistenz-Schichten betreffen (Artefakt-Records vs. Phase-Persistenz). THEME-005 ist ein paralleler Cluster: VerifySystem, PromptRuntime, Skills, FailureCorpus, KpiAnalytics, RequirementsCoverage koennen alle gleichzeitig ihre Top-Surface zuerst stabilisieren (Stub-Methoden mit korrekter Signatur), bevor sie inhaltlich gefuellt werden. THEME-006 (Governance) ist eigenstaendig genug, um parallel zu THEME-005 zu laufen, sobald THEME-001/002 stehen.

THEME-007 (Telemetrie) und THEME-008 (Persistenz) sind quer durchstossende Themen, die auf THEME-003/005 aufsetzen und parallel laufen koennen, jeweils mit klarer Sub-Aufgabentrennung. THEME-009 muss seriell hinter den meisten anderen Themen liegen — ohne PhaseEnvelope, ohne Artefakt-Envelope, ohne VerifySystem-Top, ohne Governance-Trust-Boundary kann die QA-Kernlogik nicht konzeptkonform gebaut werden. THEME-010 ist die letzte Erstwellen-Position, da Exploration sowohl VerifySystem als auch Governance-Story-Branch-Enforcement und Telemetrie-Events benoetigt.

## 5. Bewusst NICHT in der Erstwelle

- **CompactionResilience-Hooks** (`pipeline-framework.A1`) — wichtig, aber eigenstaendige Sub-Komponente; nachgelagert sobald PhaseEnvelope und Telemetrie-Hooks stehen, da diese Hooks gegen typisierte Strukturen schreiben muessen.
- **WorkerHealthMonitor (Scoring, Interventions-Gate, LLM-Assessment-Sidecar)** (`implementation-phase.A5-A8`, `governance-and-guards.A2`) — fachlich Pflicht laut FK-49, aber operativ erst sinnvoll, sobald Worker-Loop, Telemetrie-Hooks und MCP-Pool stabil sind.
- **EvidenceAssembler, ImportResolver, Request-DSL, Preflight-Turn, ConformanceService, ContextSufficiencyBuilder** (`verify-system.A3-A7`) — sind Detail-Ausbau der QA-Schichten 2/3; bauen auf THEME-009-Kernlogik auf.
- **StoryResetService, StorySplitService, Story-Exit-Flow** (`story-lifecycle.A5-A7`) — administrative Pfade; werden erst beim Operationalbetrieb notwendig.
- **Closure Sub-Komponenten (ClosureGates, MergeSequence, PostMergeFinalization vollstaendig)** (`story-closure.A1-A8`, `story-closure.B3`) — abhaengig von THEME-005 (VerifySystem-Top), THEME-009 (Finding-Resolution-Gate), THEME-008 (StoryMetrics-Persistenz).
- **ExecutionPlanning (BlockingCondition, SchedulingPolicy, PlanDerivation, PlanningProposal, Rulebook-Compile, Execution-Input-Top)** (`execution-planning.A1-A11`) — orthogonaler BC, blockiert in der Erstwelle nichts; folgt erst, wenn KpiAnalytics-Fact-Tabellen und Telemetrie-Hooks stehen.
- **GovernanceObserver** (`governance-and-guards.A1`) — setzt funktionierende Telemetrie-Hooks und Rolling-Window-Storage voraus (THEME-007); nachgelagert.
- **CLI-Refactor `register-project`/`verify-project`, Dry-Run, Customization-Preservation** (`installation-and-bootstrap.A4-A10`, `installation-and-bootstrap.B1-B5`) — Installer-Vollausbau ist abhaengig von THEME-005 (Top-Surfaces Skills/PromptRuntime/Governance) und THEME-008 (project_registry); sinnvolle Erstwellen-Beschraenkung auf Top-Surface-Delegation reicht.
- **Story-Creation-Pipeline (VektorDB-Abgleich, story.md-Export, Zieltreue-Pruefung, Skill-Koordination)** (`story-lifecycle.A1-A4`, `story-lifecycle.A9`) — wichtiger Story-Vorlauf, aber erst sinnvoll, wenn Skills (THEME-005), PromptRuntime (THEME-005) und Telemetrie-Hooks (THEME-007) bereit sind.
- **Dashboard-Tabs und DesignSystem** (`kpi-and-dashboard.A10`, `kpi-and-dashboard.A11`) — wie in FK-63 selbst vermerkt, eine spaetere Iteration nach FK-61/FK-62-Implementierung.
- **Wire-Format-Anpassungen project_summary/project_detail/project_mode_lock/story_counters/concept_anchors** (`project-management.A1-A4`, `project-management.B1`, `project-management.C1`) — Frontend-Kontrakt; blockt nicht die Backend-Disziplin, sollte aber in der zweiten Welle adressiert werden.
