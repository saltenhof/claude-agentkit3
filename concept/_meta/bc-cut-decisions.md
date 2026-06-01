---
concept_id: META-BC-CUT
title: BC-Komponenten-Schnitt — Decision Log
module: meta
cross_cutting: true
status: active
doc_kind: decision-log
authority_over:
  - scope: bc-cut-decisions
defers_to: []
supersedes: []
superseded_by:
tags: [bc-cut, architecture, bounded-context, decision-log]
formal_scope: prose-only
---

# BC-Komponenten-Schnitt — Decision Log

## Status

Stand: 16/16 BCs geschnitten (2026-05-01) -- alle BCs geschnitten.

Quelle: Mehrrundige Architektur-Diskussion (User + Hauptagent). Dieses
Dokument ist die persistierte Entscheidungsbasis. Aenderungen nur per
explizitem User-Trigger im Product-Owner-Modus.

---

## Uebergreifende Entscheidungen

### Vokabular-Disziplin

- Erlaubt: Komponente, Klasse, Schnittstelle
- Verboten: Port, Adapter (als Architektur-Pattern-Begriff), Hexagonal,
  Onion, Clean Architecture
- Begruendung: User-Direktive — stereotypische Homogenitaet geht vor
  Pattern-Mix. Einheitliche Sprache reduziert Missverstaendnisse in
  Konzepten und Code.

### Zero Debt Policy

- Kein Legacy, kein Deprecated, kein Migrationspfad
- Lints schlagen rot bis Code passt — das ist erwuenscht
- Konzepte mit alten Begriffen werden refactored, nicht toleriert

### Hierarchie-Schnitt

- BC = eine Top-Komponente (kein Monolith-BC)
- Initial max Top + Sub-1 (keine Sub-2 in Konzeptphase)
- Sub-2 entsteht iterativ zur Implementierungszeit, wenn eine Sub-1-Komponente
  die Heuristik von ~3-10 Klassen ueberschreitet
- Heuristik: ~3-10 Klassen pro Blatt-Komponente; darunter kein Sub, darueber
  aufteilen

### Sichtbarkeitsregel

- Default: Kommunikation laeuft gegen die Top-Surface der BC-Komponente
- Sub-Komponenten kommunizieren untereinander frei (kein intra-BC-Grenzschutz
  jenseits der Layer-Order)
- Andere BCs kommunizieren gegen die Top-Surface — Ausnahme `sub_exposed`
  nur bei nachgewiesenem Komplexitaetsbedarf (nicht als Default)

### Verify als Capability (Variante Y)

Status: **eingearbeitet** (2026-05-03) -- Konzeptebene umgesetzt
in FK-20, FK-27, FK-29, FK-37, FK-38, FK-39, FK-45, DK-00, DK-02,
DK-04 sowie CLAUDE.md. Formal-Spec-Anpassungen (formal.story-workflow,
formal.verify) bleiben offen.

- Phase `verify` als eigenstaendige Top-Phase entfaellt
- 4 Top-Phasen: Setup, Exploration, Implementation, Closure
- Output-QA wird interner Subflow innerhalb produktiver Phasen (Exploration
  und Implementation)
- `verify-system` ist Capability-BC, kein Phase-Owner
- Phase-Transition-Graph bleibt linear vorwaerts ohne eigenstaendigen
  Verify-Knoten

### QA-Subflow-Vertrag

Der oeffentliche Vertrag von VerifySystem:

```python
class VerifySystem:
    def run_qa_subflow(
        self,
        ctx: StoryContext,
        story_id: str,
        qa_context: QaContext,
        target: ArtifactReference,
    ) -> PolicyVerdict:
        ...
```

QaContext-Werte: `IMPLEMENTATION_INITIAL`, `IMPLEMENTATION_REMEDIATION`,
`EXPLORATION_INITIAL`, `EXPLORATION_REMEDIATION`.

### Boundary-Controls

- Wie ein BC aufgerufen wird (HTTP, MCP, CLI, sonstiges Transportprotokoll)
  gehoert in das Konzept des AUFRUFENDEN BCs (z.B. control-plane), nicht
  des aufgerufenen
- PhaseExecutor in pipeline-framework ist transport-agnostisch — er weiss
  nichts ueber den Aufrufkanal

### Bluttypen-Modell

- A = Fachlogik (Geschaeftsregeln, Capabilities)
- R = Adapter an Systemgrenzen
- T = Persistenz- und Infrastrukturtreiber
- Mischzonen per `mix_allowed: [T]` erlaubt (z.B. CompactionResilience,
  StoryStorageBackend, AdversarialOrchestrator)
- Anti-Laundering-Regel: A -> R -> T erlaubt, aber R-Schnittstelle darf
  keine T-Typen exponieren

### Refresh-Prozess

- User in Product-Owner-Rolle gibt Trigger (neue BC-Schnitt-Runde)
- Umsetzung durch (Sub-)Agent gemaess diesem Dokument als Eingabe
- Kein implizites Nachziehen — jede Aenderung braucht expliziten Auftrag

---

## Pro BC

### BC 1: pipeline-framework

**Top-Komponente:** `PipelineEngine`
- Prefix: `agentkit.pipeline_engine`
- Bloodgroup: A
- Exposure: top
- Entities-ID: `architecture-conformance.group.pipeline_engine`

**Layer-Order (niedrig=Fundament, hoch=Orchestrierung):**
1. `PhaseEnvelopeStore` — Envelope-Speicher (Fundament)
2. `CompactionResilience` — Kompaktierungs-Schutz (mix_allowed: T)
3. `FlowOrchestrator` — Kontrollfluss zwischen Phasen
4. `PipelineRegistry` — Registrierung von Pipelines
5. `PhaseExecutor` — Ausfuehrung einzelner Phasen (sub_exposed)

**Sub-Komponenten:**

| Name | Exposure | Prefix |
|------|----------|--------|
| FlowOrchestrator | internal | `agentkit.pipeline_engine.flow_orchestrator` |
| PhaseExecutor | sub_exposed | `agentkit.pipeline_engine.phase_executor` |
| PhaseEnvelopeStore | internal | `agentkit.pipeline_engine.phase_envelope_store` |
| PipelineRegistry | internal | `agentkit.pipeline_engine.pipeline_registry` |
| CompactionResilience | sub_exposed | `agentkit.pipeline_engine.compaction_resilience` |

**Klassen-Skizzen:**
- `PipelineEngine`: Koordiniert Setup -> Exploration? -> Implementation -> Closure
- `FlowOrchestrator`: Uebergang zwischen Phasen-Knoten, Retry-Policy
- `PhaseExecutor`: Ausfuehrung einer einzelnen Phase, AttemptRecord, PhaseStateProjection (Pydantic-Schema gehoert hierher; FK-69 §69.4 Owner-Cut)
- `PhaseEnvelopeStore`: Speichert und laedt Phase-Envelopes
- `PipelineRegistry`: Haelt registrierte Pipeline-Definitionen
- `CompactionResilience`: Schutz vor Context-Kompaktierungsverlusten (T-Affinitaet)

**Beziehungen:**
- Ruft `VerifySystem.run_qa_subflow` auf (ueber Top-Surface)
- Ruft `WorktreeManager` auf (shared component)
- Liest `StoryContextManager` ueber Top-Surface

| Andere BC | Richtung | Was |
|---|---|---|
| `telemetry-and-events` | PF -> T | `Telemetry.write_projection` fuer PhaseStateProjection-Records aus PhaseExecutor |

**Konzept-Refactor-Liste:**
- FK-20 (Workflow-Engine): Modul-Pfade von `agentkit.pipeline` auf
  `agentkit.pipeline_engine` migrieren
- FK-36 (CompactionResilience): Prefix-Aktualisierung
- FK-39 (Phase-State-Persistenz): Prefix-Aktualisierung
- FK-45 (Phase-Runner-CLI): Prefix-Aktualisierung

---

### BC 2: verify-system

**Top-Komponente:** `VerifySystem`
- Prefix: `agentkit.verify_system`
- Bloodgroup: A
- Exposure: top
- Entities-ID: `architecture-conformance.group.verify_system`

**Layer-Order:**
1. `StageRegistry` — Stufen-Definitionen (sub_exposed)
2. `EvidenceAssembler` — Beweise-Zusammenfuehrung (internal)
3. `LlmEvaluator` — LLM-basierte Bewertung (sub_exposed)
4. `ConformanceService` — Konformanzpruefung (sub_exposed)
5. `AdversarialOrchestrator` — Adversarial-Tests (internal, mix_allowed: T)
6. `PolicyEngine` — Policy-Aggregation (internal)
7. `QaCycleCoordinator` — QA-Zyklus-Koordination (internal)

**Sub-Komponenten:**

| Name | Exposure | Prefix |
|------|----------|--------|
| StageRegistry | sub_exposed | `agentkit.verify_system.stage_registry` |
| LlmEvaluator | sub_exposed | `agentkit.verify_system.llm_evaluator` |
| ConformanceService | sub_exposed | `agentkit.verify_system.conformance_service` |
| EvidenceAssembler | internal | `agentkit.verify_system.evidence_assembler` |
| AdversarialOrchestrator | internal | `agentkit.verify_system.adversarial_orchestrator` |
| PolicyEngine | internal | `agentkit.verify_system.policy_engine` |
| QaCycleCoordinator | internal | `agentkit.verify_system.qa_cycle_coordinator` |

**Klassen-Skizzen:**
- `VerifySystem`: Einstiegspunkt; delegiert an QaCycleCoordinator
- `StageRegistry`: VerifyStage-Definitionen, TrustClass-Zuordnung, QaStageResult, QaFinding (Pydantic-Schemas gehoeren hierher; FK-69 §69.4 Owner-Cut)
- `LlmEvaluator`: QA-Review und Semantic/Guardrail-Bewertungsfunktionen
- `ConformanceService`: Artefakt- und Struktur-Konformanz
- `EvidenceAssembler`: Zusammenfuehren von Pruef-Ergebnissen zu EvidenceAssembly
- `AdversarialOrchestrator`: Edge-Case-Tests fuer codeproduzierte Artefakte
- `PolicyEngine`: Aggregation entlang Trust-Klassen, PolicyVerdict
- `QaCycleCoordinator`: RemediationLoop, Zyklus-Steuerung, Ergebnisprotokoll

**Beziehungen:**
- Wird von PipelineEngine aufgerufen (ueber Top-Surface)
- Liest Artefakte ueber ArtifactReference (BC: artifacts, noch nicht geschnitten)

| Andere BC | Richtung | Was |
|---|---|---|
| `telemetry-and-events` | VS -> T | `Telemetry.write_projection` fuer QaStageResult/QaFinding-Records aus StageRegistry |

**Konzept-Refactor-Liste:**
- Modul-Pfade von `agentkit.governance.doc_fidelity` auf
  `agentkit.verify_system.conformance_service` migrieren
- Modul-Pfade von `agentkit.governance.policies` auf
  `agentkit.verify_system.stage_registry` migrieren
- Modul-Pfade von `agentkit.llm_evaluator` auf
  `agentkit.verify_system.llm_evaluator` migrieren

---

### BC 3: story-lifecycle

**Top-Komponente:** `StoryContextManager`
- Prefix: `agentkit.story_context_manager`
- Bloodgroup: A
- Exposure: top
- Entities-ID: `architecture-conformance.group.story_context_manager`

**Layer-Order:**
1. `StoryIdentity` — StoryId, StoryStatus, StoryType (sub_exposed)
2. `StoryStorageBackend` — Speicher-Abstraktion (internal, mix_allowed: T)
3. `OperatingModeResolver` — Mode-Routing-Entscheidung (internal)
4. `StoryContractMatrix` — Vertragsachsen-Matrix (sub_exposed)
5. `StoryCreationFlow` — Erstellungs-Ablauf (sub_exposed)
6. `StoryAdministration` — Reset/Split/Exit-Verwaltung (sub_exposed)

**Sub-Komponenten:**

| Name | Exposure | Prefix |
|------|----------|--------|
| StoryIdentity | sub_exposed | `agentkit.story_context_manager.story_identity` |
| StoryCreationFlow | sub_exposed | `agentkit.story_context_manager.story_creation_flow` |
| StoryContractMatrix | sub_exposed | `agentkit.story_context_manager.story_contract_matrix` |
| StoryAdministration | sub_exposed | `agentkit.story_context_manager.story_administration` |
| OperatingModeResolver | internal | `agentkit.story_context_manager.operating_mode_resolver` |
| StoryStorageBackend | internal | `agentkit.story_context_manager.story_storage_backend` |

**Klassen-Skizzen:**
- `StoryContextManager`: Top-Surface; delegiert Lifecycle-Operationen
- `StoryIdentity`: StoryId, StoryStatus, StoryType, Terminality
- `StoryCreationFlow`: Creation-Ablauf inkl. Validierung und Initial-State
- `StoryContractMatrix`: Vertragsachsen (FK-59-Owner), mode/type/execution_route
- `StoryAdministration`: Reset, Split, Exit-Klassen-Logik
- `OperatingModeResolver`: ExecutionRoute-Entscheidung (OperatingMode)
- `StoryStorageBackend`: Abstraktion ueber GitHub vs. interne DB (T-Affinitaet)

**Shared Component: WorktreeManager**
- Prefix: `agentkit.worktree_manager`
- component_kind: shared
- owner_group_id: `architecture-conformance.group.story_context_manager`
- allowed_importers: `PipelineEngine`, `StoryContextManager`
- exported_symbols: `WorktreeManager.create`, `.merge`, `.cleanup`, `.exists`
- Begruendung: WorktreeManager ist kein Fachkonzept von pipeline-framework,
  gehoert aber in die Nutzung beider BCs; shared-Modellierung vermeidet
  Ownership-Ambiguitaet

**Beziehungen:**
- Wird von PipelineEngine via Top-Surface abgefragt
- WorktreeManager wird von PipelineEngine und StoryContextManager genutzt

---

### BC 4: governance-and-guards

**Top-Komponente:** `Governance`
- Prefix: `agentkit.governance`
- Bloodgroup: A
- Exposure: top
- Entities-ID: `architecture-conformance.group.governance`

**Layer-Order:**
1. `PrincipalCapability` — Principal, Rollen, CapabilityToken (sub_exposed)
2. `EscalationMechanism` — Eskalations-Mechanik (internal)
3. `GuardSystem` — Hooks, Branch-Schutz, GuardDecision (sub_exposed)
4. `CcagPermissionRuntime` — CCAG-Tool-Governance, PermissionVerdict (sub_exposed)
5. `IntegrityGate` — Closure-Integritaet (sub_exposed)
6. `GovernanceObserver` — Beobachtung, Monitoring (sub_exposed)
7. `SetupPreflightGate` — Preflight-Checks fuer Setup-Phase (sub_exposed)

**Sub-Komponenten:**

| Name | Exposure | Prefix |
|------|----------|--------|
| GuardSystem | sub_exposed | `agentkit.governance.guard_system` |
| CcagPermissionRuntime | sub_exposed | `agentkit.governance.ccag_permission_runtime` |
| GovernanceObserver | sub_exposed | `agentkit.governance.governance_observer` |
| IntegrityGate | sub_exposed | `agentkit.governance.integrity_gate` |
| PrincipalCapability | sub_exposed | `agentkit.governance.principal_capability` |
| SetupPreflightGate | sub_exposed | `agentkit.governance.setup_preflight_gate` |
| EscalationMechanism | internal | `agentkit.governance.escalation_mechanism` |

**Klassen-Skizzen:**
- `Governance`: Top-Surface; koordiniert Guard/Permission/Gate-Entscheidungen
- `GuardSystem`: Hooks aktivieren, Branch-Artefakt-Schutz, GuardDecision
- `CcagPermissionRuntime`: Tool-Freigaben, CCAG-Policy, PermissionVerdict
- `GovernanceObserver`: Monitoring von Guard-Ereignissen, Audit-Trail
- `IntegrityGate`: Pre-Merge-Integritaetspruefung (FK-20 Drift-Aufloesung: Sub
  von Governance, nicht ClosurePhase)
- `PrincipalCapability`: Principal-Identitaet, Rollen, Capability-Tokens
- `SetupPreflightGate`: Vorbedingungen vor Setup-Ausfuehrung (FK-22: gehoert zu
  Governance, nicht pipeline-framework)
- `EscalationMechanism`: Eskalations-Ablauf bei Mandatsgrenzen-Ueberschreitung

**Beziehungen:**
- Wird von PipelineEngine aufgerufen (GuardDecision, IntegrityGate)
- SetupPreflightGate wird in Setup-Phase von PipelineEngine genutzt

**Konzept-Refactor-Liste:**
- `agentkit.guard_system` und `agentkit.governance.guards` auf
  `agentkit.governance.guard_system` konsolidieren
- `agentkit.governance.monitoring` und `agentkit.governance.integrity_gate`
  auf `agentkit.governance.governance_observer` und
  `agentkit.governance.integrity_gate` aufteilen
- FK-22 (SetupPreflight): Modul-Pfad bestaetigen unter
  `agentkit.governance.setup_preflight_gate`

---

### BC 5: exploration-and-design

**Status:** geschnitten (2026-05-01)
**Quellen:** FK-23, FK-25
**BC-Verantwortung:** Konzeptarbeit fuer Stories ohne belastbaren Loesungsrahmen
inkl. eigenem Check/Remediation-Subgraph. Eskalations-Mechanik **excluded**
(geht zu governance-and-guards).

**Top:** `Exploration` (A, top, prefix=`agentkit.exploration`)

Kapselt die Exploration-Phase als produktive Phase (Variante Y — siehe
uebergreifende Entscheidungen). Erstellt Change-Frame-Artefakt, validiert
ueber Drei-Stufen-Review, fuehrt Mandate-Klassifikation durch. Registriert
sich bei `pipeline-framework.PipelineRegistry` als Phase-Handler.

**Top-Surface:**
- `Exploration.run_phase(ctx, state) -> HandlerResult` — Phase-Handler-Vertrag
- `Exploration.resolve_mode(story_metadata) -> ModeRoutingDecision` — Setup-Subflow

**Sub-1-Komponenten (4):**

| Sub | Bluttyp | Exposure | Verantwortung |
|---|---|---|---|
| `ModeRouter` | A | sub_exposed | Modus-Ermittlung (FK-23 §23.2). Deterministisch, fail-closed Default Exploration. Vom Setup-Subflow vor Exploration aufgerufen. |
| `ExplorationDrafting` | A | internal | Kreative Erforschung + Draft-Entwurfsartefakt: Story-Verdichtung, Referenzdokument-Recherche, Aenderungsflaeche-Lokalisierung, Loesungsrichtung-Wahl, Selbst-Konformitaetspruefung, Change-Frame-Schreiben (7 Pflicht-Bestandteile), DesignFreeze nach Gate-PASS. |
| `ExplorationReview` | A | internal | Drei-Stufen-Validierung (Stufe 1 Doc-Fidelity, 2a Design-Review, 2b Design-Challenge). Verwaltet ExplorationGateStatus, ruft `verify-system.LlmEvaluator` und `verify-system.ConformanceService` als QA-Capabilities. |
| `MandateClassification` | A | internal | H1-Aggregation + H2-Nachklassifikation (FK-25). MandateClass 1-4, FineDesign-Subprozess (Klasse 2 autonom), ScopeExplosionDetector (Klasse 3). Eskalation an `governance-and-guards.EscalationMechanism`. |

**Klassen-Skizzen:**

- `ModeRouter` (≈4): `ModeRouter`, `ExplorationMode`, `ExecutionMode`, `ModeRoutingDecision`
- `ExplorationDrafting` (≈7): `StoryDistillation`, `ReferenceResolver`, `ChangeAreaLocator`, `SolutionDirection`, `SelfConformanceCheck`, `ChangeFrame`, `DesignFreezeMarker`
- `ExplorationReview` (≈6): `ExplorationReview` (Coordinator), `ExplorationGateStatus`, `ReviewStage`, `ReviewAggregation`, `ExplorationVerdict`, `ExplorationPayload`
- `MandateClassification` (≈7): `MandateClassifier`, `MandateClass`, `EscalationClass`, `ScopeExplosionDetector`, `ScopeExplosionFinding`, `FineDesignWorkflow`, `FineDesignDiscussion`

Total: ≈24 Klassen.

**intra_bc_layer_order:**

```
Layer 0: ModeRouter (isolierte Routing-Logik vor der Phase)
Layer 1: ExplorationDrafting
Layer 2: MandateClassification (Foundation fuer Review-Bewertung)
Layer 3: ExplorationReview (nutzt ChangeFrame + Mandate)
```

**Beziehungen zu anderen BCs:**

| Andere BC | Richtung | Was |
|---|---|---|
| `pipeline-framework` | E → PF (Registrierung) | `PipelineRegistry.register_phase_handler("exploration", ExplorationHandler)` |
| `pipeline-framework` | PF → E | Phase-Handler-Aufruf via FlowOrchestrator |
| `verify-system` | E → VS | `LlmEvaluator` (Stufe 2a/2b), `ConformanceService` (Stufe 1 Doc-Fidelity), QA-Subflow `run_qa_subflow(qa_context=EXPLORATION_INITIAL\|REMEDIATION)` |
| `governance-and-guards` | E → GG | `EscalationMechanism` fuer Klasse-1/3/4 (PAUSED/ESCALATED) |
| `prompt-runtime` | E → PR | Prompt-Bundles (worker-exploration.md) |
| `artifacts` | E → A | ArtifactManager fuer Change-Frame-Envelope |
| `story-context-manager` | E → SLC | `StoryIdentity.load_story_context()` fuer concept_paths, story_type |
| `Integrations.llm_pools` | E → LLM | Multi-LLM fuer Fine-Design-Diskussion |

**Konzept-Refactor-Liste:**

- FK-23 vs. FK-25 Freeze-Position-Drift: FK-25 ueberschreibt FK-23 (Freeze nach Gate-PASS, nicht davor). FK-23 muss nachgezogen werden — Mermaid-Flowchart in §23.3.1 entsprechend.
- Eskalation-Mechanik in FK-23/FK-25 raus — gehoert zu governance-and-guards. Nur fachliche Erkennung (MandateClass, ScopeExplosion) bleibt hier; PAUSED/ESCALATED-Mechanik wird nur referenziert.
- CLI-Beispiele raus (Boundary-Controls).

**Eigenstaendige Detail-Entscheidungen:**

- Top-Name `Exploration` statt `ExplorationDesign` oder `ExplorationOrchestrator` — kuerzer, BC-konform.
- `MandateClassification` als ein Sub (statt Mandates + FineDesign + ScopeExplosion getrennt): "verteile nicht wenn nicht muss". Sub-Subs spaeter bei Bedarf.
- `ModeRouter` `sub_exposed` weil Setup-Subflow direkt ruft (nicht den ganzen `Exploration.run_phase()` durchlaufen).
- Naming: `ExplorationDrafting` und `ExplorationReview` (statt urspruenglich `ChangeFrameAuthoring` und `ExplorationGate`) — User-Korrektur 2026-05-01: die kreative Erforschung muss als eigene Sub explizit sichtbar sein.

---

### BC 6: implementation-phase

**Status:** geschnitten (2026-05-01)
**Quellen:** FK-26, FK-49
**BC-Verantwortung:** Worker-Loop, Inkrement-Disziplin, Handover,
Worker-Health. Owns: WorkerSession, Handover-Schnittstelle, Increment,
WorkerHealth-Signal.

**Top:** `Implementation` (A, top, prefix=`agentkit.implementation`)

Kapselt die Implementation-Phase als produktive Phase (Variante Y).
Wertet `worker-manifest.json` aus und gibt bei `status=BLOCKED` ein
HandlerResult mit `PhaseStatus.ESCALATED` + `escalation_reason="worker_blocked"`
zurueck. Registriert sich bei `pipeline-framework.PipelineRegistry` als
Phase-Handler.

**Top-Surface:**
- `Implementation.run_phase(ctx, state) -> HandlerResult` — Phase-Handler-Vertrag,
  registriert sich bei `pipeline-framework.PipelineRegistry`. Wertet
  `worker-manifest.json` aus und gibt bei `status=BLOCKED` HandlerResult
  mit `PhaseStatus.ESCALATED` + `escalation_reason="worker_blocked"` zurueck.

**Sub-1-Komponenten (4):**

| Sub | Bluttyp | Exposure | Verantwortung |
|---|---|---|---|
| `WorkerSession` | A | internal | Spawn-Protokoll, WorkerContext-Resolution/Validation/Composition (FK-26 §26.2). SpawnReason, Worker-Variants (implementation/bugfix/remediation), Session-Lifecycle (agent_start/agent_end). |
| `WorkerLoop` | A | internal | Inkrement-Disziplin (Vier-Schritt-Zyklus), deterministische Drift-Erkennung Stufe 1 (Diff vs. Entwurf/Konzept, FK-26 §26.3.5), TestStrategie-Wahl (TDD/Test-After), Final Build/Test-Aufruf-Vertrag. |
| `HandoverPackager` | A | internal | `handover.json` (FK-26 §26.7), `worker-manifest.json` (§26.8), `protocol.md`. Status-Enums (COMPLETED/COMPLETED_WITH_ISSUES/BLOCKED), BlockingCategory, AC-Status. Validierung der BLOCKED-Pflichtfelder. |
| `WorkerHealthMonitor` | A, mix_allowed: [T] | sub_exposed | Scoring-Engine (PostToolUse), Interventions-Gate (PreToolUse), LLM-Assessment-Sidecar, Hook-Commit-Failure-Klassifikation, agent-health.json/tool-call-log.jsonl (FK-49). |

**Klassen-Skizzen:**

- `WorkerSession` (ca. 7): `WorkerSession`, `WorkerContextResolver`,
  `WorkerContextValidator`, `WorkerContextItem`, `WorkerContextItemKey`,
  `SpawnReason`, `WorkerVariant`
- `WorkerLoop` (ca. 6): `WorkerLoop`, `IncrementCycle`, `IncrementStep`,
  `DriftEvaluator`, `DriftDecision`, `TestStrategy`
- `HandoverPackager` (ca. 9): `HandoverPackager`, `HandoverPackage`,
  `WorkerManifest`, `WorkerManifestStatus`, `BlockingCategory`,
  `AcceptanceCriteriaStatus`, `Increment`, `WorkerArtifactDescriptor`,
  `WorkerArtifactKind`
- `WorkerHealthMonitor` (ca. 9): `WorkerHealthMonitor`, `HealthScoring`,
  `HealthHeuristic`, `AgentHealthState`, `InterventionGate`,
  `InterventionDecision`, `LlmAssessmentSidecar`, `CommitFailureClassifier`,
  `ToolCallLog`

Total: ca. 31 Klassen.

**intra_bc_layer_order:**

```
Layer 0: HandoverPackager (Schemata — Fundament)
Layer 1: WorkerSession (Spawn-/Kontext-Setup)
Layer 2: WorkerHealthMonitor (parallele Beobachtungs-Capability)
Layer 3: WorkerLoop (orchestriert Inkremente, schreibt Handover)
```

**Beziehungen zu anderen BCs:**

| Andere BC | Richtung | Was |
|---|---|---|
| `pipeline-framework` | I -> PF (Reg.) | `PipelineRegistry.register_phase_handler("implementation", ImplementationHandler)` |
| `pipeline-framework` | PF -> I | Phase-Handler-Aufruf via FlowOrchestrator |
| `verify-system` | I -> VS | `run_qa_subflow(qa_context=IMPLEMENTATION_INITIAL\|REMEDIATION)` mit handover.json als Target |
| `governance-and-guards` | GG -> I (Hooks) | HookRuntime ruft `agentkit.implementation.worker_health.scoring_hook` + `intervention_hook` direkt (daher `sub_exposed` fuer WorkerHealthMonitor) |
| `governance-and-guards` | I -> GG | CCAG-PermissionRuntime fuer Worker-Tool-Freigaben |
| `story-context-manager` | I -> SCM | `StoryIdentity` fuer Worker-Kontext-Aufbau |
| `artifacts` | I -> A | ArtifactManager fuer handover/manifest/protocol/agent-health |
| `telemetry-and-events` | I -> T | agent_start/end, increment_commit, drift_check, review_*, worker_health_score, worker_health_intervention |
| `prompt-runtime` | I -> PR | Worker-Prompt-Bundles (worker-implementation/-bugfix/-remediation.md), REVIEW_TEMPLATE_REGISTRY |
| `Integrations.llm_pools` | I (Sidecar) -> LLM | Multi-LLM-Hub fuer LLM-Assessment |

**Konzept-Refactor-Liste:**

- FK-26 §26.5a/§26.5b: Modul-Pfad-Aktualisierung wenn von
  `agentkit.verify_system.evidence_assembler` gesprochen wird (korrekt
  per FK-28, Evidence Assembler im verify-system).
- FK-26 §26.10 Telemetrie-Tabelle: Events bleiben referenziert, sind
  Owner-Sache von telemetry-and-events.
- FK-49 §49.1.6 review_guard-Verweis: bleibt unter
  `agentkit.governance.guard_system`.
- FK-49 §49.1.7 `worker_health.*`-Konfiguration: in implementation-phase
  definiert, FK-93 (Defaults-Foundation) referenziert nur.
- BLOCKED-Eskalation §26.11.2: Wording in FK-26 §26.11.2 praeziser
  machen ("ImplementationHandler signalisiert ESCALATED via HandlerResult").

**Eigenstaendige Detail-Entscheidungen:**

1. Top-Name `Implementation` (kurz, BC-konform, parallel zu `Exploration`
   aus BC 5).
2. Kein eigener `ReviewCoordinator`-Sub: Reviews sind Worker-Verhalten via
   Prompt; Templates leben in `prompt-runtime` (REVIEW_TEMPLATE_REGISTRY);
   Sentinel-Hook (`review_compliant`) in `governance.guard_system`; Events
   in `telemetry-and-events`; Bundle-Vorbereitung in
   `verify-system.evidence_assembler`. implementation-phase haette nur
   einen leeren Schatten — "verteile nicht wenn nicht musst".
3. Konsistenz vs. AdversarialOrchestrator (BC 2): Asymmetrie ist
   gerechtfertigt durch "wer orchestriert". Reviews — Worker selbst
   (kein BC-Code noetig). Adversarial — Verify-System spawnt Sub-Agent
   mit Sandbox-Setup, Mandatory-Targets, Findings-Aggregation (echte
   Klassen-Substanz). Programmatische Subkomponente entsteht da, wo
   der BC selbst orchestriert.
4. `WorkerHealthMonitor` `sub_exposed`: HookRuntime (governance) muss
   `scoring_hook` und `intervention_hook` direkt importieren.
   Top-Surface-Indirektion waere ueberkomplex.
5. `WorkerHealthMonitor` mit `mix_allowed: [T]`: Sidecar-Prozess-Lifecycle
   und tool-call-log.jsonl-Sliding-Window haben T-Affinitaet, auch wenn
   Persistenz-Schicht ueber FK-10-State-Backend delegiert ist.
6. Drift-Detection Stage 2 (Worker-Selbsteinschaetzung) ist
   Prompt-Inhalt — kein Code. Nur Stage 1 (deterministischer Diff)
   lebt in `WorkerLoop.DriftEvaluator`.
7. BLOCKED -> ESCALATED: kein BC-Drift. `HandoverPackager` validiert
   Pflichtfelder, `Implementation.run_phase` mappt auf `HandlerResult`.
   PhaseExecutor (pipeline-framework) reagiert generisch.
8. WorkerSession + WorkerLoop bleiben getrennt: Session = Spawn/Context,
   Loop = Increment-Verhalten. Keine Verschmelzung.
9. WorkerHealthMonitor 9 Klassen knapp am oberen Heuristik-Rand. Erstmal
   beieinander; Sub-2-Aufteilung in `worker_health.scoring/`,
   `worker_health.intervention/`, `worker_health.sidecar/` moeglich,
   falls Bedarf.

---

### BC 7: story-closure

**Status:** geschnitten (2026-05-01)
**Quellen:** FK-29 (contract). Sekundaer betroffen: FK-27
(Splits-Liste — Closure-Anteile gehoeren hierher).
**BC-Verantwortung:** Closure-Sequence mit irreversiblen Seiteneffekten
— Finding-Resolution, Branch-Push, Merge, Worktree-Cleanup, Story-Close,
Postflight, VektorDB-Sync, Guard-Deaktivierung. Owns: ClosurePayload,
ClosureProgress, ClosureVerdict, ClosureSequence. Excluded: IntegrityGate
(gehoert zu governance-and-guards, BC 4).

**Top:** `Closure` (A, top, prefix=`agentkit.closure`)

Kapselt die Closure-Phase als produktive Phase. Verantwortet:
Concept/Research-Verzweigung (direkte Substates), Recovery-Dispatching
basierend auf `ClosureProgress`-Booleans, Closure-Verdict-Aggregation.
Registriert sich bei `pipeline-framework.PipelineRegistry` als
Phase-Handler.

Top enthaelt direkt (Datenmodell, kein Sub): `ClosurePayload`,
`ClosureProgress`, `ClosureVerdict` (StrEnum: COMPLETED, ESCALATED),
`MergePolicy` (StrEnum: ff_only, no_ff). Begruendung: ca. 4 Klassen
unter Heuristik-Mindestgroesse fuer eigenen Sub; Top hat ohnehin
Phase-Handler-Logik + Recovery-Dispatching als Substanz. Abweichung
von BC 6 begruendet: dort hatte das Datenmodell eigene Validator-Logik
(BLOCKED-Pflichtfelder), hier ist es reines Schema.

**Top-Surface:**
- `Closure.run_phase(ctx, state) -> HandlerResult` — Phase-Handler-Vertrag,
  registriert sich bei `pipeline-framework.PipelineRegistry`. Verantwortet:
  Concept/Research-Verzweigung (direkte Substates), Recovery-Dispatching
  basierend auf `ClosureProgress`-Booleans, Closure-Verdict-Aggregation.

**Sub-1-Komponenten (4):**

| Sub | Bluttyp | Exposure | Verantwortung |
|---|---|---|---|
| `ClosureGates` | A | internal | Pre-Merge-Pruefungen. Finding-Resolution-Gate (FK-29 §29.2 — eigene Pruefung gegen Layer-2-Artefakte qa_review/semantic_review/doc_fidelity). Integrity-Gate-Aufruf an `governance-and-guards.IntegrityGate`. |
| `MergeSequence` | A | internal | Schritte 3-6 — irreversible Effects. Branch-Push, Merge (ff_only/no_ff), Worktree-Teardown, Story-Close. Recovery-Idempotenz pro Substate. |
| `PostMergeFinalization` | A | internal | Schritte 7-11 — Nach-Merge-Validierung + Cleanup. Metriken, Rueckkopplungstreue (FK-38 Doctreue Ebene 4), Postflight-Gates (5 Checks), VektorDB-Sync, Guard-Deaktivierung. Alle non-blocking. |
| `ExecutionReport` | A | internal | Markdown-Bilanz fuer den Menschen (FK-29 §29.4). Wird fuer JEDE Story-Bearbeitung erzeugt — auch bei FAILED/ESCALATED. Graceful Degradation bei fehlenden Quellen. |

Modul-Prefixes:
- `ClosureGates`: `agentkit.closure.gates`
- `MergeSequence`: `agentkit.closure.merge_sequence`
- `PostMergeFinalization`: `agentkit.closure.post_merge_finalization`
- `ExecutionReport`: `agentkit.closure.execution_report`

**Klassen-Skizzen:**

- Top-Datenmodell (ca. 4): `ClosurePayload`, `ClosureProgress`,
  `ClosureVerdict`, `MergePolicy`
- `ClosureGates` (ca. 5): `ClosureGateChain` (Coordinator),
  `FindingResolutionGate`, `FindingResolutionVerdict`,
  `ResolutionStatus` (StrEnum: fully_resolved, partially_resolved,
  not_resolved, not_applicable), `IntegrityGateInvoker`
- `MergeSequence` (ca. 6): `MergeSequenceCoordinator`,
  `StoryBranchPush`, `MergeExecutor`, `MergePolicySelector`,
  `WorktreeTeardown`, `IssueCloseExecutor`
- `PostMergeFinalization` (ca. 7): `PostMergeFinalization`
  (Coordinator), `MetricsRecorder`, `FeedbackFidelityCheck`,
  `PostflightGate`, `PostflightCheck` (StrEnum: story_dir_exists,
  story_closed, metrics_set, telemetry_complete, artifacts_complete),
  `VectorDbSyncTrigger`, `GuardDeactivator`, `WorkflowMetricCalculator`, `StoryMetric`, `ExperimentTags` (Pydantic-Schemas + Aggregations-Logik gehoeren hierher; FK-69 §69.4 Owner-Cut)
- `ExecutionReport` (ca. 3): `ExecutionReport`, `ExecutionReportSection`,
  `ReportRenderer`

Total: ca. 25 Klassen.

**intra_bc_layer_order:**

```
Layer 1: ClosureGates (Pre-Merge-Pruefungen)
Layer 2: MergeSequence (irreversible Effects)
Layer 3: PostMergeFinalization (Nach-Merge-Validierung + Cleanup)
Layer 4: ExecutionReport (am Ende — auch bei FAIL/ESCALATED)
```

**Beziehungen zu anderen BCs:**

| Andere BC | Richtung | Was |
|---|---|---|
| `pipeline-framework` | C -> PF (Reg.) | `PipelineRegistry.register_phase_handler("closure", ClosureHandler)` |
| `pipeline-framework` | PF -> C | Phase-Handler-Aufruf via FlowOrchestrator |
| `governance-and-guards` | C -> GG | `IntegrityGate` (Pre-Merge), `Governance.deactivate_locks(story_id)` (Schritt 11) |
| `verify-system` | C -> VS | Layer-2-Artefakte (qa_review/semantic_review/doc_fidelity) lesen, Doctreue-Ebene-4 via `LlmEvaluator` |
| `story-context-manager` | C -> SCM | `StoryIdentity` Status auf Done setzen |
| `artifacts` | C -> A | Layer-2-Artefakte lesen, `closure.json` schreiben, `execution-report.md` schreiben |
| `telemetry-and-events` | C -> T | Closure-Events, Telemetry-Event-Counts fuer Report, schreibt StoryMetric via `Telemetry.write_projection` aus PostMergeFinalization |
| `kpi-and-dashboard` | C -> K | Metriken (QA Rounds, Completed At, Phase-Durations) |
| `failure-corpus` | C -> FC | Postflight-FAIL und Doctreue-FAIL erzeugen Incident-Kandidaten (FK-41) |
| `implementation-phase` | C <- I | Worker-Manifest-Stand wird konsumiert (FK-26 §26.7-26.8) |
| `Integrations.github` | C -> R | Branch-Push, Merge, Story-Close (FK-12) |
| `Integrations.vector_db` | C -> R | VektorDB-Sync (async fire-and-forget, FK-13) |

**Konzept-Refactor-Liste:**

1. FK-29 §29.1.2 Mermaid-Flowchart und §29.5: IntegrityGate-Aufruf
   praezisieren — Closure delegiert an `agentkit.governance.integrity_gate`
   (Sub von Governance, BC 4). Kein Closure-eigener IntegrityGate-Sub.
2. FK-29 §29.5 Guard-Deaktivierung: Lock-Record-Verwaltung gehoert zu
   Governance. Closure ruft `Governance.deactivate_locks(story_id)`.
   Wording entsprechend praezisieren.
3. FK-29 referenziert mehrfach Layer-2-Artefakte und Doctreue-Ebene-4 —
   Modul-Pfade aktualisieren auf `agentkit.verify_system.*` (Konsequenz
   BC-2-Refactor).
4. FK-27 (mischt Verify-Pipeline und Closure-Orchestration, bekannt aus
   Splits-Liste): Closure-Anteile (closure-sequence, ClosurePayload,
   Finding-Resolution-Gate-Mechanik) gehoeren ausschliesslich nach FK-29.
   FK-27 darf nur referenzieren.
5. FK-29 §29.4: ExecutionReport wird auch bei FAILED/ESCALATED in fruehen
   Phasen erzeugt — Annahme: Closure-Top wird IMMER als letzter Schritt
   aufgerufen, im Skip-Modus mit nur Report-Erzeugung. Wenn das Konzept
   anders ist (pipeline-framework triggert Report direkt), muss
   `ExecutionReport` `sub_exposed` werden.

**Eigenstaendige Detail-Entscheidungen:**

1. Top-Name `Closure` (kurz, BC-konform, parallel zu
   `Exploration`/`Implementation`).
2. Datenmodelle direkt im Top statt eigener Sub. Begruendung: ca. 4
   Klassen unter Heuristik-Mindestgroesse; Top hat Phase-Handler-Logik
   + Recovery-Dispatching als Substanz. Abweichung von BC 6 begruendet.
3. `IntegrityGate` ist NICHT Sub von Closure. Bereits in BC 4 als Sub
   von Governance entschieden. Closure delegiert nur.
4. `ExecutionReport` als eigene Sub trotz nur ca. 3 Klassen, weil
   fachlich klar abgegrenzte Verantwortung ("Bilanz fuer den Menschen,
   unabhaengig vom Outcome"). Wird auch bei vorherigem FAILED erzeugt.
5. `PostMergeFinalization` buendelt Schritte 7-11 (Metriken, Doctreue,
   Postflight, VectorDb-Sync, Guard-Off) statt zwei Subs
   `PostMergeValidation` + `ClosureCleanup`. Begruendung: alle
   non-blocking, alle nach Merge, "verteile nicht wenn nicht musst".
   Sub-2-Aufteilung moeglich falls Bedarf.
6. Konsistenz vs. ExecutionReport: BC 6 hatte Reviews NICHT als Sub
   (reines Worker-Verhalten via Prompt). Hier ist ExecutionReport Sub,
   weil programmatisch (Markdown-Generator, Section-Renderer,
   Daten-Aggregator). BC-eigene Substanz, keine Worker-Prompt-Verantwortung.
   Konsistenz-Regel: programmatische Subkomponente entsteht da, wo der
   BC selbst orchestriert.
7. Concept/Research-Pfad mit direkt gesetzten Substates
   (integrity_passed=true, merge_done=true) wird im Closure-Top behandelt
   (Verzweigung), nicht in eigenem Sub.

---

### BC 8: artifacts

**Status:** geschnitten (2026-05-01)
**Quellen:** FK-71
**BC-Verantwortung:** Artefakt-Referenzen, Envelope-Format, Producer-Registry,
Artefakt-Klassen — generische Artefakt-Infrastruktur. Owns: ArtifactReference,
Envelope, ProducerId, ArtifactClass. Excluded: Prompt-Bundle-Komposition
(prompt-runtime), Lock-Mechanik (governance-and-guards),
Stage-Registry-Types (verify-system).

**Top:** `Artifacts` (A, top, prefix=`agentkit.artifacts`)

Kapselt die generische Artefakt-Infrastruktur. Verantwortet:
Schreib-/Lese-Koordination gegen State-Backend-Driver (ArtifactManager),
Klassifikation (ArtifactClass), Referenzierung (ArtifactReference),
Envelope-Schema (ArtifactEnvelope), Producer-Typisierung (Producer,
ProducerType, ProducerId), Pflichtfeld-Pruefung (EnvelopeValidator).

**Top-Surface:**
- `ArtifactManager.write(ref: ArtifactReference, envelope: ArtifactEnvelope, payload: dict) -> None`
- `ArtifactManager.read(ref: ArtifactReference) -> tuple[ArtifactEnvelope, dict]`
- `ArtifactManager.exists(ref: ArtifactReference) -> bool`

Top enthaelt direkt (Datenmodelle + Validator, kein Sub):
`ArtifactManager`, `ArtifactClass`, `ArtifactReference`, `ArtifactEnvelope`,
`EnvelopeStatus`, `Producer`, `ProducerType`, `ProducerId`, `EnvelopeValidator`.
Begruendung: ca. 9 Klassen eng verzahnt; ein separater Schema-Sub waere
kuenstlich. Analog BC 7 (Closure-Datenmodelle im Top).

**Sub-1-Komponenten (1):**

| Sub | Bluttyp | Exposure | Verantwortung |
|---|---|---|---|
| `ProducerRegistry` | A | internal | Mapping Export-Artefakt -> erlaubter Producer-Name (FK-71 §71.2). Producer-Validierung. Status-Mapping LLM-Check-Status -> Envelope-Status (`PASS_WITH_CONCERNS` -> `WARN`). |

Modul-Prefix: `agentkit.artifacts.producer_registry`

**Klassen-Skizzen:**

- Top (ca. 9): `ArtifactManager`, `ArtifactClass`, `ArtifactReference`,
  `ArtifactEnvelope`, `EnvelopeStatus`, `Producer`, `ProducerType`,
  `ProducerId`, `EnvelopeValidator`
- `ProducerRegistry` (ca. 5): `ProducerRegistry`, `ProducerRegistration`,
  `StatusMapper`, `LlmCheckStatus`, `ProducerValidationVerdict`

Total: ca. 14 Klassen.

**intra_bc_layer_order:**

```
Layer 1: ProducerRegistry
```

**Beziehungen zu anderen BCs:**

| Andere BC | Richtung | Was |
|---|---|---|
| `pipeline-framework` | PF -> A | ArtifactManager fuer phase-state.json |
| `verify-system` | VS -> A | ArtifactManager fuer Layer-2-Artefakte (qa_review/semantic_review/doc_fidelity/policy/structural/adversarial) |
| `story-context-manager` | SCM -> A | ArtifactManager fuer context.json |
| `governance-and-guards` | GG -> A | ArtifactManager fuer integrity-violations.log und integrity-gate.json |
| `exploration-and-design` | E -> A | ArtifactManager fuer Change-Frame-Envelope |
| `implementation-phase` | I -> A | ArtifactManager fuer handover/manifest/protocol/agent-health |
| `story-closure` | C -> A | Layer-2-Artefakte lesen, closure.json + execution-report.md schreiben |
| State-Backend-Drivers | A -> SBD | T-Adapter (`agentkit.state_backend.*`) als Persistenz-Schicht |

**Konzept-Refactor-Liste:**

1. FK-71 §71.3 Lock-Mechanismus: gehoert nicht zu artifacts. Inhalt nach
   FK-31 (Hook-Enforcement, governance) verschieben. FK-71 darf nur referenzieren.
2. FK-71 §71.4 Stage-Registry: `StageDefinition`-Klasse gehoert zu
   `verify-system.StageRegistry`-Sub. FK-71 §71.4 zu verify-system
   konsolidieren oder nur referenzieren.
3. FK-71 §71.1.2 PROTECTED_ARTIFACTS-Liste: Implementierungsdetail des
   Integrity-Hooks (governance.guard_system). Liste gehoert zur
   Hook-Konfiguration in BC 4, nicht hier.
4. FK-71 §71.1.1 Schutzgrad-Spalte: Schutz-Information ist
   governance-Verantwortung. Hier bleibt nur Klassifikation (Erzeuger,
   Beispiele); Schutzgrad wird in governance-Doku gefuehrt.
5. FK-71 `authority_over` einschraenken: nur `artefakt-envelope` und
   `producer-registry` bleiben. `lock-mechanismus` und
   `stage-registry-types` entfernen.

**Eigenstaendige Detail-Entscheidungen:**

1. Top-Name `Artifacts` (Plural). Abweichung vom Singular-Pattern
   (`Closure`, `Implementation`, `Exploration`, `Governance`, `VerifySystem`).
   Begruendung: der BC ist die "Artefakt-Welt" — kein einzelnes Konzept,
   sondern eine Sammlung von Klassifikationen + Schemas. Praegnanter als
   `ArtifactSystem`.
2. Datenmodelle und EnvelopeValidator im Top, nicht als eigene Sub —
   analog BC 7. Eng verzahnt; eigener Datenmodell-Sub waere kuenstlich.
3. Nur 1 Sub `ProducerRegistry` — der BC ist klein. Producer-Mapping +
   Status-Mapping bilden eine fachlich abgrenzbare Verantwortung.
   EnvelopeValidator bleibt im Top, weil seine Pflichtfeld-Pruefung
   nicht Producer-spezifisch ist.
4. Lock-Mechanik und Stage-Registry-Types NICHT hier — bewusst
   ausgegliedert. Lock = governance (Hook-Enforcement, Sub-Agent-Sperre),
   Stage-Registry = verify-system (StageRegistry-Sub).
5. State-Backend-Driver bleibt als T-Adapter ausserhalb des BC.
   `agentkit.state_backend.*` ist Querschnitt-Adapter; ArtifactManager
   ist die A-Fassade.

---

### BC 9: telemetry-and-events

**Status:** geschnitten (2026-05-01)
**Quellen:** DK-05, FK-68, FK-69
**BC-Verantwortung:** ExecutionEvent-Stream, Event-Schemata,
Phase-State-Projektionen, QA-Read-Models. Owns: ExecutionEvent,
EventTypeId, PhaseStateProjection, QaReadModel.

**Top:** `Telemetry` (A, top, prefix=`agentkit.telemetry`)

Kapselt die Telemetrie-Infrastruktur. Verantwortet Event-Stream-Schreiben
(TelemetryService gegen Postgres-State-Backend), Audit-Bundle-Export
(AuditBundleExporter bei Closure), Workflow-Metrik-Berechnung
(StoryMetric). Enthaelt direkt (~6 Klassen): TelemetryService,
ExecutionEvent, EventTypeId, Severity, EventPayload, AuditBundleExporter.
Begruendung: TelemetryService ist Schreib-API mit Logik (nicht nur
Datenmodell); 6 Klassen substantielle Top-Verantwortung; konsistent mit
BC 7 (Closure-Datenmodell im Top).

**Top-Surface:**

Spezialfall execution_events:
- `Telemetry.write_event(event: ExecutionEvent) -> None` (delegiert an internen TelemetryService)
- `Telemetry.export_audit_bundle(story_id: str, output_path: Path) -> None`

Generisch fuer alle Projektions-Tabellen (qa_stage_results, qa_findings, story_metrics, phase_state_projection):
- `Telemetry.write_projection(table: ProjectionTable, record: ProjectionRecord) -> None`
- `Telemetry.read_projection(table: ProjectionTable, query) -> list[ProjectionRecord]`
- `Telemetry.update_projection(table: ProjectionTable, key, patch) -> None`
- `Telemetry.purge_run(project_key: str, run_id: str) -> None` (Story-Reset)

**Sub-1-Komponenten (3):**

| Sub | Bluttyp | Exposure | Verantwortung |
|---|---|---|---|
| `TelemetryHooks` | A | sub_exposed | Hook-basierte Producer (FK-68 §68.3.1). Master-TelemetryHook, ReviewGuardHook, BudgetHook, DivergenceCalculator, StoryIdResolver. Wird von `governance.HookRuntime` direkt aufgerufen. |
| `ProjectionAccessor` | A, mix_allowed:[T] | sub_exposed | Generischer Postgres-Accessor fuer alle Telemetrie-Projektions-Tabellen ausser `execution_events`. Pflichtfeld-Vertrag (`ProjectionRecordBase`: project_key, story_id, run_id), Tabellen-Register (welche Tabellen sind kanonisch erlaubt), CRUD-Operationen, Story-Reset-Purger. Plus die BC-eigene Projektion `NormalizedEvent` (Sensor-Daten fuer Governance-Risk-Window) mit Mapper aus execution_events. **telemetry-and-events ownt die DB-Zugriffsschicht, NICHT die domain-spezifischen Schemas pro Tabelle.** |
| `TelemetryContract` | A | sub_exposed | Validierungsregeln (FK-68 §68.4): agent_start/end-Paarung, review_compliant-Deckung, Preflight-Compliance, llm_call-Pflicht-Rollen, web_call <= Budget, integrity_violation == 0. Wird von `governance.IntegrityGate` direkt aufgerufen. |

Modul-Prefixes:
- `TelemetryHooks`: `agentkit.telemetry.hooks`
- `ProjectionAccessor`: `agentkit.telemetry.projection_accessor`
- `TelemetryContract`: `agentkit.telemetry.contract`

**Klassen-Skizzen:**

- Top (~6): `TelemetryService`, `ExecutionEvent`, `EventTypeId`,
  `Severity`, `EventPayload`, `AuditBundleExporter`
- `TelemetryHooks` (~5): `TelemetryHook` (Master), `ReviewGuardHook`,
  `BudgetHook`, `DivergenceCalculator`, `StoryIdResolver`
- `ProjectionAccessor` (~6): `ProjectionAccessor` (CRUD-Coordinator gegen Postgres), `ProjectionRecordBase` (Pflichtfelder), `ProjectionTable` (StrEnum: qa_stage_results, qa_findings, story_metrics, phase_state_projection), `ProjectionRegistry` (Tabellen-Kanon + erlaubte Spalten), `NormalizedEvent`, `NormalizedEventMapper`
- `TelemetryContract` (~7): `TelemetryContractValidator` (Coordinator),
  `AgentLifecycleRule`, `ReviewFrequencyRule`, `PreflightComplianceRule`,
  `LlmCallRule`, `WebCallBudgetRule`, `IntegrityViolationRule`

Total: ~6 (Top) + ~5 (Hooks) + ~6 (ProjectionAccessor) + ~7 (Contract) = ~24 Klassen.

**intra_bc_layer_order:**

```
Layer 1: ProjectionAccessor (DB-Zugriffsschicht)
Layer 2: TelemetryHooks (Producer-Schicht)
Layer 3: TelemetryContract (Validierungs-Schicht)
```

**Beziehungen zu anderen BCs:**

| Andere BC | Richtung | Was |
|---|---|---|
| `pipeline-framework` | PF -> T | `TelemetryService.write_event` fuer flow_start/end/node_result/override_applied, schreibt PhaseStateProjection via `Telemetry.write_projection` |
| `verify-system` | VS -> T | `TelemetryService` fuer llm_call/adversarial_*/doc_fidelity_check/impact_violation_check, schreibt QaStageResult/QaFinding via `Telemetry.write_projection` |
| `story-context-manager` | SCM -> T | `TelemetryService` fuer vectordb_search |
| `governance-and-guards` | GG -> T | `HookRuntime` ruft `TelemetryHooks` direkt (sub_exposed); `IntegrityGate` ruft `TelemetryContract` direkt (sub_exposed); `GovernanceObserver` liest `NormalizedEvent` |
| `exploration-and-design` | E -> T | `TelemetryService` |
| `implementation-phase` | I -> T | `TelemetryService` fuer agent_start/end/increment_commit/drift_check/review_*/worker_health_* |
| `story-closure` | C -> T | `export_audit_bundle`, schreibt StoryMetric via `Telemetry.write_projection` |
| `failure-corpus` | FC -> T | `execution_events` lesen fuer Pattern-Promotion (fc_*-Tabellen werden DORT geschrieben, NICHT hier) |
| `kpi-and-dashboard` | K -> T | `execution_events` + `ProjectionAccessor` lesen fuer KPI-Rollups |
| State-Backend-Drivers | T -> SBD | T-Adapter (`agentkit.state_backend.postgres_*`) fuer events + read_models |

**Konzept-Refactor-Liste:**

1. FK-69-Split: `fc_incidents`, `fc_patterns`, `fc_check_proposals`
   (FK-69 §69.9) gehoeren zu failure-corpus, nicht hierher. FK-69 muss
   inhaltlich aufgeteilt werden.
2. FK-68 §68.8 Governance-Risk-Window: `NormalizedEvent` bleibt hier
   (Sensor), aber Score-Akkumulation gehoert zu
   `governance.GovernanceObserver`. FK-68 §68.8 praezisieren.
3. FK-68 §68.6 Budget-Hook strittig: Hybrid aus Event-Emission
   (telemetry) und Blocking (governance). Konzept klaeren — moegliche
   Aufspaltung in `telemetry.hooks.BudgetEventEmitter` +
   `governance.guard_system.WebCallBudgetGuard`.
4. FK-68 §68.3.1 Hook-Pfad-Tabelle: Modul-Pfade von `telemetry/hook.py`,
   `telemetry/review_guard.py`, `telemetry/budget.py`,
   `telemetry/divergence.py` auf `agentkit.telemetry.hooks.*` aktualisieren.
5. FK-68 `authority_over`: telemetry, eventing, workflow-metriken bleiben.
6. FK-69 §69.6-69.8 (qa_*, story_metrics): bleiben hier, Modul-Pfade auf
   `agentkit.telemetry.read_models.*` aktualisieren.

**Eigenstaendige Detail-Entscheidungen:**

1. Top-Name `Telemetry` (kurz, ohne `-and-events`-Suffix; Events sind
   zentraler Aspekt der Telemetrie, nicht nebenstehend).
2. TelemetryService im Top, nicht als eigene Sub. ~6 Klassen Top-Inhalt;
   Top hat substantielle Verantwortung. Konsistent mit BC 7.
3. 3 Subs statt 4-5: WorkflowMetric-Calculator wandert NICHT in `ProjectionAccessor` — er gehoert zu **story-closure** (`PostMergeFinalization.MetricsRecorder`), weil er bei Closure aus execution_events berechnet. NormalizedEvent + Mapper bleiben in `ProjectionAccessor` als BC-eigene Projektion fuer Governance-Risk-Window.
4. `TelemetryHooks` und `TelemetryContract` `sub_exposed`: HookRuntime und
   IntegrityGate (governance) rufen direkt. Konsistent mit BC 6
   WorkerHealthMonitor.
5. `ProjectionAccessor` mit `mix_allowed:[T]`: starke Postgres-Persistenz-Affinitaet (Accessor schreibt direkt SQL gegen Telemetrie-DB).
6. fc_*-Tabellen NICHT hier: gehoeren zu failure-corpus. Drift in FK-69
   expliziert.
7. Governance-Risk-Window-Score-Akkumulation NICHT hier: gehoert zu
   governance.GovernanceObserver. NormalizedEvent als Sensor-Daten bleibt
   hier.
8. Budget-Hook strittig: bleibt erstmal in `telemetry.hooks.BudgetHook`
   (Status quo aus FK-68). Aufspaltung in spaeterem Refactor.
9. telemetry-and-events ownt die **Telemetrie-Datenbank-Zugriffsschicht** (Accessor + generisches Envelope + Tabellen-Register), NICHT die domain-spezifischen Schemas pro Tabelle. QaStageResult-Schema gehoert zu verify-system, StoryMetric-Schema zu story-closure, PhaseStateProjection-Schema zu pipeline-framework. Owner-BCs nutzen den generischen Accessor (`Telemetry.write_projection`) und uebergeben ihre Records. Single-Writer-Regel pro Tabelle (FK-69 §69.4) bleibt erfuellt durch Owner-BC-Disziplin.

---

### BC 10: prompt-runtime

**Status:** geschnitten (2026-05-01)
**Quellen:** FK-44
**BC-Verantwortung:** Prompt-Bundle-Komposition, Materialisierung, Audit-Hash,
Template-Mechanik. Drift-Vermeidung und Context-Schonung des Orchestrators als
Ausfuehrungs-Pattern. Owns: PromptBundle, BundleMaterialization, PromptAuditHash,
PromptTemplate, BundleVersion. Excluded: Skill-Inhalt (agent-skills), Was im
Prompt steht (anfragende BC).

**Top:** `PromptRuntime` (A, top, prefix=`agentkit.prompt_runtime`)

Koordiniert Bundle-Aufloesungs-, Bindungs- und Materialisierungslogik.
Enthaelt direkt (~5 Klassen): `PromptRuntime`, `PromptInvocation`,
`PromptInstance`, `RunId`, `InvocationId`.

**Top-Surface:**
- `PromptRuntime.create_run_pin(run_id: RunId) -> RunPromptPin` — bei Run-Start, friert Bundle-Bindung ein
- `PromptRuntime.materialize_prompt(invocation: PromptInvocation) -> PromptInstance` — fuer Agent-Spawn / Evaluator-Aufruf
- `PromptRuntime.update_binding(bundle_id, version) -> None` — vom Installer (FK-50) aufgerufen
- `PromptRuntime.compute_audit_hash(invocation_id, output_bytes) -> PromptAuditHash`

**Sub-1-Komponenten (3):**

| Sub | Bluttyp | Exposure | Verantwortung |
|---|---|---|---|
| `BundleStore` | A | internal | Kanonischer system-weiter Bundle-Store. PromptBundle-Schema, PromptTemplate-Schema, Versionierung, Manifest-Digest, Bundle-Pfad-Resolver (`bundle_id`/`bundle_version` -> installerverwalteter Pfad). Read-only fuer Runtime. |
| `BundlePinning` | A | internal | Festschreibungs-Mechanismen fuer die effektive Bundle-Version: ProjectPromptPin (Lock-Datensatz `.agentkit/config/prompt-bundle.lock.json`, projektweit-persistent) UND RunPromptPin (`.agentkit/manifests/prompt-pins/{run_id}.json`, run-lokal-eingefroren). Beide verhindern Drift; Run-Pin hat Vorrang vor Project-Pin. |
| `Materialization` | A, mix_allowed:[T] | internal | Run-scoped Prompt-Instanzen unter `.agentkit/prompts/{run_id}/{invocation_id}/prompt.md`. Static-Materializer (Hardlink/Symlink), Dynamic-Renderer (Template + Render-Input -> Instance). Audit-Hash-Berechnung (template_sha256, render_input_digest, output_sha256). |

Modul-Prefixes:
- `BundleStore`: `agentkit.prompt_runtime.bundle_store`
- `BundlePinning`: `agentkit.prompt_runtime.bundle_pinning`
- `Materialization`: `agentkit.prompt_runtime.materialization`

**Klassen-Skizzen:**

- Top (~5): `PromptRuntime`, `PromptInvocation`, `PromptInstance`, `RunId`, `InvocationId`
- `BundleStore` (~7): `BundleStore` (Resolver), `PromptBundle`, `PromptTemplate`, `BundleVersion`, `BundleId`, `BundleManifestDigest`, `LogicalPromptId`
- `BundlePinning` (~5): `BundlePinning` (Coordinator), `ProjectPromptPin` (Lock), `RunPromptPin`, `PinResolver` (resolves Run-Pin first, fallback Project-Pin), `PinPersistence`
- `Materialization` (~7): `BundleMaterializer` (Coordinator), `StaticPromptMaterializer`, `DynamicPromptRenderer`, `RenderMode` (StrEnum: static, rendered), `RenderInputDigest`, `PromptAuditHash`, `AuditRecord`

Total: ~24 Klassen.

**intra_bc_layer_order:**

```
Layer 1: BundleStore (Bundle-Quelle, Fundament)
Layer 2: BundlePinning (Lock + Pin gegen BundleStore)
Layer 3: Materialization (erzeugt Instanzen aus Bindung + Bundle)
```

**Beziehungen zu anderen BCs:**

| Andere BC | Richtung | Was |
|---|---|---|
| `pipeline-framework` | PF -> PR | `create_run_pin` bei Run-Start, `materialize_prompt` bei jedem Worker/Evaluator-Spawn |
| `exploration-and-design` | E -> PR | `materialize_prompt` fuer worker-exploration.md |
| `implementation-phase` | I -> PR | `materialize_prompt` fuer worker-implementation/-bugfix/-remediation.md, REVIEW_TEMPLATE_REGISTRY |
| `verify-system` | VS -> PR | `materialize_prompt` fuer LlmEvaluator-Templates, Adversarial-Prompt-Spawn (FK-48) |
| `installation-and-bootstrap` | INST -> PR | `update_binding(bundle_id, version)` aktualisiert ProjectPromptPin |
| `agent-skills` | AS -> PR | Skill-Templates werden ueber `materialize_prompt` aufgeloest (FK-43) |
| `story-context-manager` | SCM -> PR | StoryContext liefert Render-Input-Felder |
| `artifacts` | PR -> A | AuditRecord via ArtifactManager (PromptAuditHash als Artefakt-Klasse) |
| `telemetry-and-events` | PR -> T | `Telemetry.write_event` fuer Prompt-Nutzungs-Events (optional) |
| Filesystem-Driver | M -> FS | T-Adapter fuer Hardlink/Symlink/Datei-Erzeugung |

**Konzept-Refactor-Liste:**

1. FK-44 §44.6 "Artefakt-ID" fuer Audit-Records: AuditRecord wird via `artifacts.ArtifactManager` persistiert. Beziehung PR -> A explizit dokumentieren.
2. FK-44 §44.4.2 Evaluator-Prompts: `verify_system.LlmEvaluator` muss alle Templates via `PromptRuntime.materialize_prompt` aufloesen.
3. FK-44 verweist auf FK-50 (Installer): Bundle-Bindungs-Aktualisierung erfolgt durch `installation-and-bootstrap` ueber Top-Surface `PromptRuntime.update_binding`. FK-50 muss diese Schnittstelle dokumentieren.
4. FK-44 §44.5 Modul-Pfade in Code-Beispielen: Filesystem-Konvention; Schema dafuer lebt in `BundlePinning`-Sub.
5. Audit-Hash-Felder (FK-44 §44.6): `template_sha256`, `render_input_digest`, `output_sha256` im `PromptAuditHash`-Pydantic-Schema (Materialization-Sub). FK-44 Schema-Owner-Cut explizit machen.
6. `prompt_used`-Event-Frage offen — falls eingefuehrt, in EventTypeId-Liste (BC 9) ergaenzen.

**Eigenstaendige Detail-Entscheidungen:**

1. Top-Name `PromptRuntime` (kurz, BC-konform, parallel zu Telemetry/Closure/Implementation).
2. Datenmodell (PromptInvocation/PromptInstance) im Top, nicht als eigene Sub. ~5 Klassen Top-Inhalt; Top hat substantielle Coordinator-Verantwortung. Konsistent mit BC 7/9.
3. Lock + Pin in einem `BundlePinning`-Sub konsolidiert — beide sind Festschreibungs-Mechanismen mit identischem Zweck (Drift-Vermeidung), nur mit unterschiedlichem Scope (projektweit vs. run-lokal). "Verteile nicht wenn nicht musst". Klassen-Vokabular einheitlich auf `Pin`-Begriff vereinheitlicht (`ProjectPromptPin` statt `ProjectPromptBinding`), weil FK-44 §44.3 selbst von "Run-Pinning" spricht und beide Mechanismen gleichartig wirken.
4. Static + Dynamic Materializer im selben `Materialization`-Sub — beide arbeiten am gleichen Pfadziel. Audit-Hash-Logik liegt auch hier (eng mit Materialisierung verzahnt).
5. `Materialization` mit `mix_allowed:[T]` (in Prose, nicht Schema): Filesystem-Operations.
6. Lock-Datei wird vom Installer geschrieben, aber ueber Top-Surface (`update_binding`) — keine direkte Datei-Manipulation durch BC `installation-and-bootstrap`.
7. Skill-Inhalt (agent-skills) lebt nicht hier — prompt-runtime ist Bundle-Mechanik; Skills sind andere Schicht.

---

### BC 11: agent-skills

**Status:** geschnitten (2026-05-01)
**Quellen:** DK-01, DK-12, FK-43
**BC-Verantwortung:** Welche Capabilities brauchen Agents jenseits ihrer
Werkseinstellungen, Skill-Definition, Skill-Variants (z.B. core/ARE),
Skill-Profile, Skill-Lifecycle, Skill-Qualitaetssicherung. Owns: SkillId,
SkillVariant, CapabilityProfile, SkillLifecycle, SkillQualityMetric.
Excluded: Bundle-Mechanik (prompt-runtime), Story-Ausfuehrungssemantik
(pipeline-framework).

**Top:** `Skills` (A, top, prefix=`agentkit.skills`)

Koordiniert Skill-Bindung, Profil-Aufloesung und Qualitaets-Beobachtung.
Enthaelt direkt (~5 Klassen): `SkillManager`, `Skill`, `SkillId`,
`SkillVariant`, `CapabilityProfile`.

**Top-Surface:**
- `Skills.bind_skill(skill_id, bundle_version, project_root, profile) -> SkillBinding`
- `Skills.resolve_binding(skill_id, project_root) -> SkillBinding | None`
- `Skills.list_bound_skills(project_root) -> list[SkillBinding]`
- `Skills.collect_quality_metrics(skill_id) -> SkillQualityMetric`

**Sub-1-Komponenten (3):**

| Sub | Bluttyp | Exposure | Verantwortung |
|---|---|---|---|
| `SkillBundleStore` | A | internal | Kanonischer system-weiter Skill-Bundle-Store. SkillBundle-Schema, Versionierung, Manifest-Digest, Bundle-Pfad-Resolver (analog zu `prompt-runtime.BundleStore`, aber fuer Skill-Verzeichnisse). |
| `SkillBinding` | A, mix_allowed:[T] | internal | Symlink-basierte Projekt-Bindung (FK-43 §43.4.1) UND Skill-Lifecycle-State-Machine (Requested -> ProfileResolved -> BundleSelected -> Bound -> Verified/Rejected). PlaceholderSubstitutor fuer Bind-Zeit-Werte (gh_owner, gh_repo, project_prefix, project_key aus PipelineConfig). |
| `SkillQualityMetric` | A | internal | Beobachtungs-Signale fuer Skill-Wirksamkeit (FK-43 §43.6.2). Aggregation aus Workflow-Metric-Daten (telemetry-and-events) und Failure-Corpus-Befunden mit Skill-Experiment-Tags. |

Modul-Prefixes:
- `SkillBundleStore`: `agentkit.skills.bundle_store`
- `SkillBinding`: `agentkit.skills.binding`
- `SkillQualityMetric`: `agentkit.skills.quality_metric`

**Klassen-Skizzen:**

- Top (~5): `SkillManager`, `Skill`, `SkillId`, `SkillVariant`, `CapabilityProfile`
- `SkillBundleStore` (~5): `SkillBundleStore`, `SkillBundle`, `SkillBundleVersion`, `SkillBundleManifest`, `SkillBundleManifestDigest`
- `SkillBinding` (~7): `SkillBinding` (Coordinator + State-Machine), `ProjectSkillBinding` (Pydantic), `SymlinkCreator`, `PlaceholderSubstitutor`, `SkillLifecycleState` (StrEnum: Requested, ProfileResolved, BundleSelected, Bound, Verified, Rejected), `LifecycleTransition`, `BindingPersistence`
- `SkillQualityMetric` (~3): `SkillQualityMetric`, `QualityMetricCollector`, `SkillExperimentTags`

Total: ~20 Klassen.

**intra_bc_layer_order:**

```
Layer 1: SkillBundleStore (Bundle-Quelle, Fundament)
Layer 2: SkillBinding (Lifecycle + Symlink gegen BundleStore)
Layer 3: SkillQualityMetric (Beobachtung post-binding)
```

**Beziehungen zu anderen BCs:**

| Andere BC | Richtung | Was |
|---|---|---|
| `pipeline-framework` | PF -> AS | (indirekt) Worker findet Skill via harness-spezifischen Symlink-Pfad (Claude Code: `.claude/skills/`; Codex: harness-eigenes Aequivalent — siehe FK-43 §43.4.1 und FK-76) |
| `installation-and-bootstrap` | INST -> AS | `Skills.bind_skill` bei Projektregistrierung; Profile-Auswahl (core/are) |
| `prompt-runtime` | AS -> PR | Skill-Templates koennen optional via `PromptRuntime.materialize_prompt` aufgeloest werden (FK-43 frontmatter `defers_to: FK-44`) |
| `story-context-manager` | SCM -> AS | StoryContext fuehrt aktives `CapabilityProfile` als Read-Field |
| `telemetry-and-events` | AS -> T | `Telemetry.write_event` fuer skill_used (falls eingefuehrt); `QualityMetricCollector` liest execution_events + StoryMetric via `Telemetry.read_projection` |
| `failure-corpus` | AS -> FC | `QualityMetricCollector` liest fc_incidents fuer Skill-Wirksamkeits-Beobachtung |
| Configuration (FK-03 Foundation) | AS -> C | `PlaceholderSubstitutor` liest gh_owner/gh_repo/project_prefix/project_key aus PipelineConfig |
| Filesystem-Driver | SB -> FS | T-Adapter fuer Symlink-Erzeugung (SkillBinding) |
| `governance-and-guards` | GG -> AS | (Enforcement F-43-030 Normative Skill-Nutzung) — siehe Drift-Punkt |

**Konzept-Refactor-Liste:**

1. FK-43 §43.4.2 `PlaceholderSubstitutor`: substituiert Werte aus `PipelineConfig` (gh_owner etc.) aus FK-03 Foundation. Konfigurations-Schnittstelle (read-only auf PipelineConfig) dokumentieren.
2. FK-43 §43.5.2 Upgrade-Verhalten: Bundle-Version-Pin-Mechanik. Verhaeltnis zu `prompt-runtime.BundlePinning` klaeren — eigenstaendiger Skill-Pin oder gemeinsamer? Vermutlich eigenstaendig (Skills haben anderen Lifecycle als Prompt-Bundles).
3. FK-43 §43.6.2 Skill-Quality: SkillQualityMetric verwendet Workflow-Metric-Daten (Owner: story-closure.PostMergeFinalization, BC 7) und fc_*-Tabellen (failure-corpus). Lese-Schnittstellen via `Telemetry.read_projection` (sub_exposed) und failure-corpus-Top.
4. FK-43 §43.4.1 Installer-Aufruf: `Skills.bind_skill` als Top-Surface (analog zu `PromptRuntime.update_binding`). FK-50 muss diese Schnittstelle dokumentieren.
5. FK-43 frontmatter `defers_to: FK-44`: Skill-Template-Materialisierung kann ueber prompt-runtime laufen, ist aber nicht zwingend. Wording in FK-43 praezisieren: agent-skills hat eigenes Bundle-Konzept fuer Skill-Verzeichnisse; prompt-runtime wird nur fuer Inhalt-Render bei Run aufgerufen, falls noetig.
6. F-43-030 Normative Skill-Nutzung: Agents MUESSEN Skills nutzen. Enforcement durch `governance.guard_system` oder `verify-system.PolicyEngine`? Aktuell unklar. Cross-BC-Drift-Punkt.

**Eigenstaendige Detail-Entscheidungen:**

1. Top-Name `Skills` (Plural, analog zu `Artifacts` aus BC 8). Alternative: `SkillSystem` analog zu VerifySystem. `Skills` ist kuerzer und matcht den BC-Namen direkt.
2. SkillManager + Datenmodell im Top (~5 Klassen). Konsistent mit BC 7/9/10.
3. SkillBinding + SkillLifecycle in einem Sub konsolidiert — Lifecycle ist Zustandsfolge des Bindings. "Verteile nicht wenn nicht musst".
4. `SkillBinding` mit `mix_allowed:[T]` (in Prose) — Symlink-Erzeugung ist Filesystem-Operation. Konsistent mit `Materialization` aus BC 10.
5. `SkillBundleStore` separat von `prompt-runtime.BundleStore` — beide BCs haben eigenstaendige Bundle-Konzepte (Skills vs. Prompts). Strukturelle Aehnlichkeit ist Konvention, keine Wiederverwendung. Skills sind Verzeichnis-Symlinks, Prompts sind Datei-Materialisierungen.
6. Placeholder-Substitution in agent-skills (Bind-Zeit), NICHT in prompt-runtime. Skill-Placeholder werden zur Bindezeit substituiert (statisch); Prompt-Render-Inputs werden zur Run-Zeit aufgeloest.
7. SkillQualityMetric als eigene Sub trotz nur ~3 Klassen — fachlich klar abgegrenzte Verantwortung. Konsistent mit BC 7 ExecutionReport (~3) und BC 8 ProducerRegistry (~5).
8. F-43-030 Enforcement ist NICHT hier implementiert — pruefe ob Skill genutzt wurde, gehoert zu governance.guard_system (Hook-basiert) oder verify-system.PolicyEngine (Stage-basiert).

---

### BC 12: installation-and-bootstrap

**Status:** geschnitten (2026-05-01)
**Quellen:** DK-08, FK-50, FK-51
**BC-Verantwortung:** Projektregistrierung, Installer-Checkpoints,
Hook/Wrapper-Bindung, Upgrade/Migration, Customization-Preservation.
Owns: BootstrapStatus, InstallerCheckpoint, ManifestContract.

**Top:** `Installer` (A, top, prefix=`agentkit.installer`)

Koordiniert Projektregistrierung, Checkpoint-Durchlauf und Upgrade-Szenarien.
Enthaelt direkt (~4 Klassen): `Installer`, `BootstrapStatus`,
`InstallerCheckpoint`, `ProjectRegistration`.

**Top-Surface:**
- `Installer.register_project(github_owner: str, github_repo: str, dry_run: bool = False) -> CheckpointRun`
- `Installer.verify_project() -> VerificationReport`
- `Installer.upgrade() -> UpgradeResult`

**Sub-1-Komponenten (4):**

| Sub | Bluttyp | Exposure | Verantwortung |
|---|---|---|---|
| `CheckpointEngine` | A | internal | DSL-Flow (FlowDefinition mit level=component, owner=Installer, FK-50 §50.3.1) + Run-Lifecycle + Result-Aggregation. Branch-Knoten fuer feature.are/feature.vectordb. Dry-Run-Modus. |
| `BootstrapCheckpoints` | A, mix_allowed:[R,T] | internal | CP 1-7 — Voraussetzungen pruefen + Setup + State-Backend-Registrierung. Package-Check, Repo-Check, Pipeline-Config-Erzeugung, Profile-Ermittlung, ProjectRegistration-Upsert. |
| `IntegrationCheckpoints` | A, mix_allowed:[T] | internal | CP 8-12 + 10a/b/c — Skill-Bindings (ruft agent-skills + prompt-runtime), Hook-Registration (ruft governance), MCP-Server (ruft Vector-DB-Adapter), ConceptContext-Setup, Concept-Validation-Hook, ARE-Scope-Validierung, Git-Hooks + CLAUDE.md-Skelett, Verifikation. |
| `Upgrade` | A | internal | FK-51 — Upgrade-Szenarien (NoChange, BundleVersionChanged, UserCustomized, NewVariant), Config-Migration zwischen config_versions, .bak-Backup, Customization-Footprint-Erkennung. Nutzt CheckpointEngine fuer Re-Run. |

Modul-Prefixes:
- `CheckpointEngine`: `agentkit.installer.checkpoint_engine`
- `BootstrapCheckpoints`: `agentkit.installer.bootstrap_checkpoints`
- `IntegrationCheckpoints`: `agentkit.installer.integration_checkpoints`
- `Upgrade`: `agentkit.installer.upgrade`

**Klassen-Skizzen:**

- Top (~4): `Installer`, `BootstrapStatus`, `InstallerCheckpoint` (StrEnum: CP_PACKAGE_CHECK, CP_REPO_CHECK, ..., CP_VERIFY), `ProjectRegistration`
- `CheckpointEngine` (~7): `CheckpointEngine` (Coordinator), `CheckpointFlow` (FlowDefinition-Adapter), `CheckpointRun`, `CheckpointResult`, `CheckpointStatus` (StrEnum: PASS, CREATED, UPDATED, SKIPPED, FAILED), `CheckpointBranch`, `DryRunMode`
- `BootstrapCheckpoints` (~7): `PackageCheck` (CP 1), `RepoCheck` (CP 2), `ProjectLookup` (CP 3), `CustomFieldsCheckpoint` (CP 4), `PipelineConfigCheckpoint` (CP 5), `ProfileResolution` (CP 6), `BackendRegistration` (CP 7)
- `IntegrationCheckpoints` (~8): `SkillBindingsCheckpoint` (CP 8), `HookRegistration` (CP 9), `McpRegistration` (CP 10), `ConceptContextSetup` (CP 10a), `ConceptValidationHook` (CP 10b), `AreScopeValidation` (CP 10c), `GitHooksAndClaudeMd` (CP 11), `VerificationCheckpoint` (CP 12)
- `Upgrade` (~6): `UpgradeCoordinator`, `ConfigMigration`, `ConfigDigest`, `CustomizationFootprint`, `BackupCreator`, `UpgradeScenario` (StrEnum)

Total: ~32 Klassen.

**intra_bc_layer_order:**

```
Layer 1: CheckpointEngine (DSL-Flow + Run-Lifecycle, Fundament)
Layer 2: BootstrapCheckpoints (CP 1-7)
Layer 3: IntegrationCheckpoints (CP 8-12 + 10a/b/c)
Layer 4: Upgrade (orthogonal, nutzt Engine fuer Re-Run)
```

**Beziehungen zu anderen BCs:**

| Andere BC | Richtung | Was |
|---|---|---|
| `agent-skills` | INST -> AS | CP 8 ruft `Skills.bind_skill(skill_id, bundle_version, project_root, profile)` |
| `prompt-runtime` | INST -> PR | CP 8 ruft `PromptRuntime.update_binding(bundle_id, version)` |
| `governance-and-guards` | INST -> GG | CP 9 ruft `Governance.register_hooks(hook_definitions)` (siehe Drift-Punkt) |
| `story-context-manager` | INST -> SCM | indirekt (StoryStorageBackend-Initialisierung bei Backend-Registrierung) |
| `telemetry-and-events` | INST -> T | `Telemetry.write_event` fuer CheckpointResult-Events; `Telemetry.write_projection` fuer ProjectRegistration |
| `pipeline-framework` | INST -> PF | nutzt FlowDefinition-DSL (Einheits-DSL FK-20) fuer CheckpointFlow |
| `Integrations.github` | INST -> R | CP 2 (Repo) |
| `Integrations.vector_db` | INST -> R | CP 10/10a (MCP-Server-Registration, Erstindizierung) |
| Filesystem-Driver | INST -> T | Harness-spezifische Skill-Symlinks und Hook-Settings (Claude Code: `.claude/skills/`, `.claude/settings.json`; Codex: harness-eigene Aequivalente — siehe FK-76), `.agentkit/config/project.yaml`, `.bak`-Backup |
| State-Backend-Drivers | INST -> SBD | T-Adapter fuer ProjectRegistration-Upsert |

**Konzept-Refactor-Liste:**

1. FK-50 §50.3.1 Checkpoint-Engine als Komponenten-Flow: nutzt FlowDefinition aus pipeline-framework (Einheits-DSL FK-20). Cross-BC-Beziehung dokumentieren.
2. FK-50 CP 8 Skill-Symlinks: Installer ruft `Skills.bind_skill` (BC 11) und `PromptRuntime.update_binding` (BC 10), erzeugt Symlinks NICHT direkt. Wording in FK-50 praezisieren — Code-Beispiel mit `create_symlink(...)` ist irrefuehrend.
3. FK-50 CP 9 Hook-Registration: Installer schreibt direkt harness-spezifische Settings (Claude Code: `.claude/settings.json`; Codex: harness-eigenes Aequivalent). Konsistente Trennung waere: Installer ruft `Governance.register_hooks(hook_definitions)` (BC 4 Top-Surface), und der Harness-Adapter (FK-76 §76.4) materialisiert die harness-spezifische Settings-Datei. JSON-/TOML-Manipulation gehoert zu governance.guard_system bzw. dem jeweiligen Harness-Adapter.
4. FK-50 CP 7 BackendRegistration: Owner ist installation-and-bootstrap (eigene `project_registry`-Tabelle). Schema lebt hier; Schreib-Adapter via T-Driver. Konsistenz mit BC 9 (telemetry ownt DB-Zugriff, nicht Schemas pro Tabelle).
5. FK-51 Customization-Erkennung: CustomizationFootprint kombiniert PipelineConfig (FK-03), CCAG-Regeln (governance) und Bundle-Bindings (prompt-runtime + agent-skills). Lese-Schnittstellen via Top-Surfaces.
6. FK-50 §50.2 CLI-Aufrufe (`agentkit register-project`): CLI ist Boundary-Control des aufrufenden BC. Installer ist transport-agnostisch.

**Eigenstaendige Detail-Entscheidungen:**

1. Top-Name `Installer` (kurz, BC-konform, matcht FK-50 §50.1).
2. Datenmodell im Top (~4 Klassen). Konsistent mit BC 7/9/10/11.
3. 4 Subs: CheckpointEngine + 2 Handler-Subs (Bootstrap/Integration) + Upgrade. 12+ CP-Handler in einem Sub waeren ueber Heuristik (~15); logische Trennung "before backend registration" (CP 1-7) vs. "integration with adjacent systems" (CP 8-12).
4. Upgrade als eigene Sub trotz Wiederverwendung der CheckpointEngine — FK-51 Mechanik ist eigenstaendige Verantwortung.
5. `BootstrapCheckpoints` mit `mix_allowed:[R,T]` (in Prose) — CP 2-4 rufen GitHub-Adapter (R), CP 5/7 schreiben Filesystem/State-Backend (T).
6. `IntegrationCheckpoints` mit `mix_allowed:[T]` — Filesystem-Operations dominant.
7. CP 9 Hook-Registration: derzeit direkte JSON-Manipulation modelliert. Alternativer Pfad: `Governance.register_hooks` aufrufen. Drift-Punkt.
8. CheckpointEngine nutzt FlowDefinition aus pipeline-framework — strukturelle Cross-BC-Wiederverwendung der Einheits-DSL.

---

### BC 13: failure-corpus

**Status:** geschnitten (2026-05-01)
**Quellen:** DK-07, FK-41
**BC-Verantwortung:** Fehlmuster-Sammlung, Pattern-Promotion, Check-Factory,
Lernschleife in deterministische Guards. Owns: FailurePattern, IncidentStatus,
PatternStatus, CheckStatus, GeneratedCheckProposal, IncidentCandidate.

**Top:** `FailureCorpus` (A, top, prefix=`agentkit.failure_corpus`)

Koordiniert Incident-Aufnahme, Pattern-Aggregation und Check-Ableitung.
Enthaelt direkt: `FailureCorpus`, `IncidentCandidate`,
`FailureCategory`, `IncidentStatus`, `PatternStatus`, `CheckStatus`,
`IncidentId`, `PatternId`, `CheckId`.

**Top-Surface:**
- `FailureCorpus.record_incident(candidate: IncidentCandidate) -> IncidentId`
- `FailureCorpus.suggest_patterns() -> list[PatternCandidate]`
- `FailureCorpus.confirm_pattern(pattern_id, decision) -> Pattern`
- `FailureCorpus.derive_check(pattern_id) -> CheckProposal`
- `FailureCorpus.approve_check(check_id, decision) -> CheckProposal`
- `FailureCorpus.report_effectiveness(window_days=90) -> EffectivenessReport`

**Sub-1-Komponenten (3):**

| Sub | Bluttyp | Exposure | Verantwortung |
|---|---|---|---|
| `IncidentTriage` | A | internal | Befunde aufnehmen, normalisieren, Aufnahmekriterien pruefen, vorsortieren (FK-41 §41.4). Capture-Akteure: Governance/QA/Adversarial/Closure/Mensch. Repository fuer Incident-Daten. Persistierung via `Telemetry.write_projection` in `fc_incidents`. |
| `PatternPromotion` | A | internal | Aus Incidents Muster destillieren und bestaetigen (FK-41 §41.5). Clustering nach Kategorie + Symptom-Aehnlichkeit, Promotion-Regeln (Wiederholung/HoheSchwere/Checkbarkeit), menschliche Bestaetigung als Pflicht. Persistierung via `Telemetry.write_projection` in `fc_patterns`. |
| `CheckFactory` | A | internal | 6-Schritt-Check-Ableitung aus bestaetigten Patterns. Schritt 1+3 ueber verify-system.LlmEvaluator, Schritt 5 ruft GitHub-Adapter, Schritt 6 Wirksamkeitspruefung mit Auto-Deaktivierung. Persistierung via `Telemetry.write_projection` in `fc_check_proposals`. |

Modul-Prefixes:
- `IncidentTriage`: `agentkit.failure_corpus.incident_triage`
- `PatternPromotion`: `agentkit.failure_corpus.pattern_promotion`
- `CheckFactory`: `agentkit.failure_corpus.check_factory`

**Klassen-Skizzen:**

- Top (~6): `FailureCorpus`, `IncidentCandidate`, `FailureCategory` (StrEnum, 12
  Werte: scope_drift, architecture_violation, evidence_fabrication, hallucination,
  test_omission, assertion_weakness, unsafe_refactor, policy_violation, tool_misuse,
  state_desync, requirements_miss, review_evasion), drei entitäts-scoped
  Lifecycle-Enums `IncidentStatus` (observed/promoted/closed_one_off/archived),
  `PatternStatus` (candidate/accepted/rejected/retired), `CheckStatus`
  (draft/approved/active/rejected/retired), `IncidentId`, `PatternId`,
  `CheckId` (NewType)
- `IncidentTriage` (~6): `IncidentTriage` (Coordinator), `Incident`, `IncidentNormalizer`,
  `IngressCriteria`, `ProjectionWriterPort` (schmale write_projection-Sicht; kein
  failure_corpus-eigenes DB-Repo, KONFLIKT-2), `IncidentSeverity` (StrEnum: low,
  medium, high, critical)
- `PatternPromotion` (~7): `PatternPromotion` (Coordinator), `FailurePattern`,
  `PatternClusterer`, `PromotionRule` (StrEnum: Wiederholung, HoheSchwere, Checkbarkeit),
  `PatternConfirmation`, `PatternRepository`, `RiskLevel` (StrEnum: kritisch, hoch,
  mittel)
- `CheckFactory` (~10): `GeneratedCheckProposal`, `CheckType` (StrEnum:
  ChangedFilePolicy, ArtifactCompleteness, TestObligation, SensitivePathGuard,
  ForbiddenDependency, FixtureReplay), `CheckSharpener` (Schritt 1, LLM),
  `CheckTypeMapper` (Schritt 2), `CheckProposalGenerator` (Schritt 3, LLM),
  `CheckApprovalWorkflow` (Schritt 4), `CheckImplementationStoryGenerator`
  (Schritt 5), `CheckEffectivenessTracker` (Schritt 6), `AutoDeactivator`,
  `CheckRepository`

Total: ~27 Klassen.

**intra_bc_layer_order:**
1. `IncidentTriage` (Fundament — Aufnahme + Vorsortierung)
2. `PatternPromotion` (Aggregation aus Incidents zu bestaetigten Mustern)
3. `CheckFactory` (Ableitung deterministischer Guards aus Mustern)

**Beziehungen zu anderen BCs:**

| Andere BC | Richtung | Was |
|---|---|---|
| `governance-and-guards` | GG -> FC | `record_incident` (vom GovernanceObserver bei Schwellenuebersicht) |
| `verify-system` | VS -> FC | `record_incident` (von QaCycleCoordinator bei FAIL, AdversarialOrchestrator, ConformanceService Doctreue-Ebene-4); FC -> VS (CheckFactory ruft `LlmEvaluator` fuer Schritt 1+3) |
| `story-closure` | C -> FC | `record_incident` (Postflight-FAIL und Doctreue-FAIL erzeugen Incident-Kandidaten) |
| `telemetry-and-events` | FC -> T | `Telemetry.write_projection` fuer fc_incidents/fc_patterns/fc_check_proposals; `Telemetry.read_projection` fuer Wirksamkeitspruefung-Daten |
| `agent-skills` | AS -> FC | `QualityMetricCollector` liest fc_incidents fuer Skill-Wirksamkeits-Beobachtung |
| `pipeline-framework` | FC -> PF | CheckFactory Schritt 5 erzeugt GitHub-Story -> Story durchlaeuft Pipeline regulaer |
| `prompt-runtime` | FC -> PR | LlmEvaluator-Aufrufe in Schritt 1+3 ueber `materialize_prompt` |
| `Integrations.github` | FC -> R | CheckImplementationStoryGenerator ruft GitHub-Adapter fuer Story-Erzeugung |

**Konzept-Refactor-Liste:**

1. FK-69 §69.9 fc_*-Tabellen-Schemas: gehoeren zu failure-corpus (Aufloesung des
   BC-9-Drift-Punkts). Schemas (FailurePattern, GeneratedCheckProposal,
   fc_incidents-Schema) leben hier; Postgres-Persistenz via
   `Telemetry.write_projection`. FK-69 muss aufgeteilt oder die fc_*-Sektionen
   verweisen auf failure-corpus als Owner.
2. FK-41 §41.3 Speicherung `.agentkit/failure-corpus/`: JSONL-Dateien als
   Legacy/Export. Kanonische Wahrheit liegt in Postgres-fc_*-Tabellen. FK-41
   wording praezisieren.
3. FK-41 §41.6.2/§41.6.4 LLM-Aufrufe (Schritt 1 Schaerfen, Schritt 3
   Proposal-Generierung): laufen ueber `verify-system.LlmEvaluator` mit
   `prompt-runtime.materialize_prompt`. Modul-Pfade dokumentieren.
4. FK-41 §41.6.6 Schritt 5 (Story-Erzeugung): ruft `Integrations.github`-Adapter.
   Cross-BC-Beziehung zu pipeline-framework dokumentieren.
5. FK-41 §41.4.2 QA-Evaluation als Capture-Akteur (F-41-069): Verify-System ruft
   `FailureCorpus.record_incident` direkt.
6. FK-41 §41.6.7 Auto-Deaktivierung: nutzt Workflow-Metric-Daten (Owner:
   story-closure.PostMergeFinalization). Lese-Schnittstelle via
   `Telemetry.read_projection`.
7. FK-41 §41.9 CLI-Befehle: Boundary-Control des aufrufenden BC. FailureCorpus
   ist transport-agnostisch.

**Eigenstaendige Detail-Entscheidungen:**

1. Top-Name `FailureCorpus` (CamelCase aus zwei Worten; kuerzer als
   `FailureCorpusSystem`). Konsistent mit `VerifySystem`/`PromptRuntime`.
2. Datenmodell + Coordinator im Top (~6 Klassen). Konsistent mit BC 7/9/10/11/12.
3. 3 Subs entlang der 3-Ebenen-Pipeline (Incidents -> Patterns -> CheckFactory).
   Klare Verantwortung pro Ebene.
4. CheckFactory mit ~10 Klassen am oberen Heuristik-Rand akzeptabel, weil
   6-Schritt-Pipeline konzeptionell zusammenhaengend. Sub-2-Aufteilung moeglich
   falls Bedarf.
5. fc_*-Tabellen-Persistenz via `Telemetry.write_projection` — failure-corpus ownt
   Schemas und Schreib-Logik, telemetry-and-events ownt nur DB-Zugriff. Konsistent
   mit BC-9-Korrektur-Pattern.
6. JSONL-Speicherung als Legacy/Export, nicht kanonisch — FK-41 muss nachziehen.
7. CheckFactory Schritt 5 erzeugt GitHub-Story (Integrations.github direkt); Story
   durchlaeuft pipeline-framework regulaer.
8. F-43-030 Skill-Quality-Beobachtung: agent-skills.QualityMetricCollector liest
   fc_incidents — Lese-Beziehung dokumentiert, kein Drift.

---

### BC 14: execution-planning

**Status:** geschnitten (2026-05-01)
**Quellen:** FK-70
**BC-Verantwortung:** Backlog-Readiness, Abhaengigkeitsgraph, Wellen,
Plan-Proposal, Scheduling- und Parallelisierungspolicy. Owns:
ReadinessAssessment, DependencyEdge, Wave, ExecutionPlan,
SchedulingPolicy, ParallelizationPolicy.

**Top:** `ExecutionPlanning` (A, top, prefix=`agentkit.execution_planning`)

Koordiniert Readiness-Auswertung, Scheduling-Entscheidungen und
Plan-Ableitung. Enthaelt direkt (~5 Klassen): `ExecutionPlanning`,
`PlanningStatus`, `DependencyKind`, `BlockingClass`, `WaveStatus`.

**Top-Surface:**
- `ExecutionPlanning.assess_readiness(project_key, story_id) -> ReadinessVerdict`
- `ExecutionPlanning.evaluate_scheduling(project_key, story_id) -> SchedulingDecision`
- `ExecutionPlanning.get_plan(project_key) -> ExecutionPlan`
- `ExecutionPlanning.why_not_now(project_key, story_id) -> list[Reason]`
- `ExecutionPlanning.ingest_proposal(proposal: PlanningProposal) -> ProposalAcceptance`
- `ExecutionPlanning.compile_rulebook(rulebook_text, project_key) -> RulebookRevision`

**Sub-1-Komponenten (5):**

| Sub | Bluttyp | Exposure | Verantwortung |
|---|---|---|---|
| `PlanningModel` | A | internal | Datenmodelle + Repository fuer Planungsdomaene. PlannedStory, DependencyEdge, BlockingCondition, HumanGate, ExternalGate, Repository-CRUD. Persistierung via `Telemetry.write_projection`. |
| `ProposalIngest` | A | internal | Eingangs-Schicht fuer external Updates. PlanningProposal-Vertrag (Agent-Handover), Validation, Rulebook-DSL-Compile in kanonisches Modell, Provenienz. |
| `ReadinessAssessment` | A | internal | Regelbasierte Auswertung READY-Status (FK-70 §70.6.1): hard_story_dependency-Vorgaenger DONE, mutex/serial-Constraints, offene Gates, Konfliktzustaende. Optionale Human-Reviews zaehlen NICHT als Blocker. |
| `SchedulingPolicy` | A | internal | Operative Entscheidung may_parallelize_now (FK-70 §70.6.2). Budget-Caps (repo_parallel, merge_risk, api_rate_limit, llm_pool, ci_capacity, human_gate, global), Trade-off-Regel, why_not_now-Audit-Reason. NORMATIV getrennt von ReadinessAssessment (FK-70 §70.4.4). |
| `PlanDerivation` | A | internal | ExecutionPlan-Ableitung + Wave-Lifecycle. critical_path, ready_set, blocked_set, execution_wave, recommended_batch, max_allowed_batch. Re-Plan-Trigger (debounced, revisionsbasiert). |

Modul-Prefixes:
- `PlanningModel`: `agentkit.execution_planning.planning_model`
- `ProposalIngest`: `agentkit.execution_planning.proposal_ingest`
- `ReadinessAssessment`: `agentkit.execution_planning.readiness_assessment`
- `SchedulingPolicy`: `agentkit.execution_planning.scheduling_policy`
- `PlanDerivation`: `agentkit.execution_planning.plan_derivation`

**Klassen-Skizzen:**

- Top (~5): `ExecutionPlanning`, `PlanningStatus` (StrEnum: UNSTARTED,
  READY, FLIGHT, DONE, BLOCKED_EXTERNAL, BLOCKED_HUMAN,
  BLOCKED_CAPACITY, BLOCKED_CONFLICT), `DependencyKind` (StrEnum:
  hard_story_dependency, soft_story_dependency,
  serial_execution_constraint, mutex_constraint,
  shared_contract_dependency, shared_file_conflict,
  external_dependency, human_gate_dependency), `BlockingClass`
  (StrEnum: blocked_internal_dependency, blocked_external,
  blocked_human, blocked_capacity, blocked_conflict,
  blocked_contract), `WaveStatus` (StrEnum: planned, active,
  completed, collapsed)
- `PlanningModel` (~6): `PlannedStory`, `DependencyEdge`,
  `BlockingCondition`, `HumanGate`, `ExternalGate`,
  `PlanningRepository`
- `ProposalIngest` (~5): `ProposalIngest` (Coordinator),
  `PlanningProposal`, `ProposalValidator`, `RulebookCompiler`,
  `RulebookRevision`
- `ReadinessAssessment` (~5): `ReadinessAssessment` (Coordinator),
  `HardDependencyCheck`, `GateOpenCheck`, `ConflictCheck`,
  `MutexCheck`
- `SchedulingPolicy` (~5): `SchedulingPolicy` (Coordinator),
  `ParallelizationPolicy`, `BudgetCap`, `SchedulingDecision`,
  `WhyNotNow`
- `PlanDerivation` (~6): `PlanDerivation` (Coordinator),
  `ExecutionPlan`, `ExecutionWave`, `CriticalPathCalculator`,
  `BatchRecommender`, `RePlanTrigger`

Total: ~32 Klassen.

**intra_bc_layer_order:**
1. `PlanningModel` (Fundament — Datenmodell + Repository)
2. `ProposalIngest` (Inputs — schreibt in Model)
3. `ReadinessAssessment` (liest Model)
4. `SchedulingPolicy` (liest Model + Readiness-Ergebnisse)
5. `PlanDerivation` (orchestriert alle, leitet Plan ab)

**Beziehungen zu anderen BCs:**

| Andere BC | Richtung | Was |
|---|---|---|
| `pipeline-framework` | PF -> EP | `assess_readiness`, `evaluate_scheduling`, `get_plan` (Orchestrator vor Story-Start, FK-70 §70.8) |
| `story-context-manager` | EP -> SCM | liest StoryStatus zur DONE-Pruefung; PlannedStory-Metadaten (story_type, story_size, participating_repos) aus StoryContext |
| `governance-and-guards` | GG -> EP | Mandate-Eskalation als BlockingCondition (Klasse blocked_human/blocked_contract) |
| `telemetry-and-events` | EP -> T | `Telemetry.write_event` fuer Plan-Events; `Telemetry.write_projection` fuer ExecutionPlan/PlannedStory-Tabellen |
| `artifacts` | EP -> A | ExecutionPlan optional als Artefakt-Snapshot |
| `Integrations.github` | EP <- R | Story- und Board-Metadaten als Importquelle (FK-12) |

**Konzept-Refactor-Liste:**

1. FK-70 §70.10.1 Port-Vokabular: `DependencyGraphPort`,
   `ReadinessAssessmentPort`, `ExecutionPlanPort`,
   `SchedulingPolicyPort` sind Port-Begriffe (Hexagonal). Per
   BC-Vokabular-Disziplin verboten. Umformulieren auf "Komponenten"
   und "Top-Surfaces".
2. FK-70 §70.10.2 Persistenz: ExecutionPlan + PlannedStory +
   DependencyEdge via `Telemetry.write_projection`
   (execution-planning-spezifische Tabellen, Schema-Owner:
   execution-planning). Konsistent mit BC-9-Pattern.
3. FK-70 §70.10.3 Audit-Events: neue EventTypeId-Werte ergaenzen
   FK-68 — `dependency_recorded`, `story_ready`, `story_blocked`,
   `plan_revised`, `scheduling_decided`, `gate_resolved`,
   `rulebook_compiled`, `wave_collapsed`.
4. FK-70 §70.7d Rulebook-DSL: NICHT die FlowDefinition-DSL aus
   FK-20. Verhaeltnis explizit dokumentieren — execution-planning
   hat eigene Rulebook-DSL fuer Scheduling-Hints.
5. FK-70 §70.5.2 READY ist regelbasiert: Konsistenz mit BC 3
   (StoryContextManager.StoryIdentity hat basis-StoryStatus;
   ExecutionPlanning leitet PlanningStatus ab). Wording in
   FK-21/FK-24 nachziehen.
6. FK-70 §70.8 Orchestrator-Vertrag: pipeline-framework.PipelineEngine
   MUSS `ExecutionPlanning.evaluate_scheduling` vor jedem Story-Start
   aufrufen. FK-20 ergaenzen.

**Eigenstaendige Detail-Entscheidungen:**

1. Top-Name `ExecutionPlanning` (matcht FK-70
   `ExecutionPlanningService`; -Service-Suffix entfaellt fuer
   Konsistenz).
2. Status-Enums (PlanningStatus, DependencyKind, BlockingClass,
   WaveStatus) im Top, Pydantic-Schemas in Subs. Konsistent mit
   BC 9/13.
3. 5 Subs — relativ viel, aber FK-70 §70.4.4 fordert NORMATIV
   strikte Trennung Feasibility (ReadinessAssessment) vs. Scheduling
   (SchedulingPolicy). Konsolidierung waere konzeptionelle Schwaechung.
4. ProposalIngest und RulebookCompile in einem Sub konsolidiert —
   beides Eingangs-Schichten fuer external Updates. "Verteile nicht
   wenn nicht musst".
5. Kein "Port"-Vokabular im Code/Konzept — FK-70 §70.10.1 muss
   umformuliert werden.
6. Persistenz via `Telemetry.write_projection` — execution-planning
   ownt Schemas und Schreib-Logik, telemetry-and-events ownt nur
   DB-Zugriff.
7. PlanDerivation orchestriert die anderen Subs — als hoechster Layer
   (4); ruft ReadinessAssessment + SchedulingPolicy ueber deren
   oeffentliche Schnittstelle.

---

### BC 15: requirements-and-scope-coverage

**Status:** geschnitten (2026-05-01)
**Quellen:** DK-06, FK-40
**BC-Verantwortung:** must_cover-Pflichtanforderungen, Evidence-Einreichung,
Scope-Mapping, ARE-Dock-Points, Coverage-Verdict. Vollstaendigkeit, NICHT
Qualitaet. Owns: MustCoverObligation, EvidenceReference, ScopeMapping,
AreDockPoint, CoverageVerdict. Excluded: Stage-Registry (verify-system),
Policy-Engine (verify-system), Blocking-Semantik (verify-system).

**Top:** `RequirementsCoverage` (A, top, prefix=`agentkit.requirements_coverage`)

Koordiniert vier ARE-Andock-Punkte und Aktivierungs-Pruefung. Enthaelt
direkt (~4 Klassen): `RequirementsCoverage`, `AreDockPoint` (StrEnum: LINK,
CONTEXT, EVIDENCE, GATE), `RequirementType` (StrEnum: regulatory,
business_rule, report_mapping, system, quality), `EvidenceType` (StrEnum:
test_report, commit_ref, artifact_ref, manual_note).

**Top-Surface:**
- `RequirementsCoverage.link_requirements(story_id, scope_key) -> list[RequirementLink]` (Andock 1)
- `RequirementsCoverage.load_context(story_id) -> AreBundleResult` (Andock 2)
- `RequirementsCoverage.submit_evidence(story_id, requirement_id, evidence_type, evidence_ref) -> None` (Andock 3)
- `RequirementsCoverage.check_gate(story_id) -> CoverageVerdict` (Andock 4)
- `RequirementsCoverage.is_enabled(project_key) -> bool` — wenn `features.are: false` sind alle anderen Methoden no-op

**Sub-1-Komponenten (3):**

| Sub | Bluttyp | Exposure | Verantwortung |
|---|---|---|---|
| `AreClient` | R | internal | REST-Client zur externen ARE-API (FK-40 §40.4). HTTP-Aufrufe der ARE-Endpunkte (list_requirements, get_recurring, load_context, submit_evidence, check_gate). Konsistent mit GitHub-REST-Adapter (FK-12). MCP ist NICHT der AgentKit-interne Aufruf-Pfad — MCP ist Boundary-Control fuer Harness-Agents (Worker/QA, harness-neutral via Adapter aus FK-76), die direkt mit ARE reden; AgentKit-Code selbst nutzt REST. |
| `ScopeMapping` | A | internal | Konfigurationszeit-Tabellen (FK-40 §40.3): Repo->Scope und Modul->Scope. Scope-Ableitung bei Story-Erstellung mit Zwei-Tier-Prioritaet (Participating Repos primaer, Modul-Feld als Fallback). Lese-Zugriff auf PipelineConfig — geschrieben durch installation-and-bootstrap. |
| `AreIntegration` | A | internal | Implementierungen der vier Andock-Punkte: RequirementLinker (Story-Erstellung), ContextLoader (Setup, schreibt are_bundle.json), EvidenceSubmitter (Implementation/Verify), AreGateChecker (Verify Layer 1). Ruft `AreClient` intern. Vollstaendigkeitspruefung selbst macht ARE — `AreGateChecker` interpretiert Response, erzeugt CoverageVerdict + UncoveredRequirement-Liste, fail-closed bei ARE-Unerreichbarkeit (FK-40 §40.9). |

Modul-Prefixes:
- `AreClient`: `agentkit.requirements_coverage.are_client`
- `ScopeMapping`: `agentkit.requirements_coverage.scope_mapping`
- `AreIntegration`: `agentkit.requirements_coverage.are_integration`

**Klassen-Skizzen:**

- Top (~4): `RequirementsCoverage`, `AreDockPoint`, `RequirementType`,
  `EvidenceType`
- `AreClient` (~5): `AreClient` (REST-Coordinator), `AreEndpoint` (StrEnum:
  list_requirements, get_recurring, load_context, submit_evidence, check_gate),
  `AreRequirement` (Pydantic), `AreRestRequest`, `AreRestResponse`
- `ScopeMapping` (~5): `ScopeMapping` (Coordinator), `RepoScopeMap`,
  `ModuleScopeMap`, `ScopeResolver`, `ScopeKey`
- `AreIntegration` (~10): `AreIntegration` (Coordinator), `RequirementLinker`
  (Andock 1, ruft `AreClient.list_requirements`/`get_recurring`),
  `ContextLoader` (Andock 2, ruft `AreClient.load_context`, schreibt
  are_bundle.json), `AreBundle` (Pydantic), `AreBundleResult`,
  `EvidenceSubmitter` (Andock 3, ruft `AreClient.submit_evidence`),
  `AreGateChecker` (Andock 4, ruft `AreClient.check_gate`, fail-closed bei
  Unerreichbarkeit), `CoverageVerdict`, `UncoveredRequirement`,
  `EvidenceReference`

Total: ~24 Klassen.

**intra_bc_layer_order:**
1. `AreClient` (R-Adapter zur externen ARE — Fundament)
2. `ScopeMapping` (Konfigurationszeit-Tabellen)
3. `AreIntegration` (orchestriert AreClient + ScopeMapping; faengt ARE-Response auf, erzeugt CoverageVerdict)

**Beziehungen zu anderen BCs:**

| Andere BC | Richtung | Was |
|---|---|---|
| `pipeline-framework` | PF -> RC | `link_requirements` bei Story-Erstellung; `load_context` bei Setup-Phase |
| `verify-system` | VS -> RC | `check_gate` als Stage Layer 1 (StageRegistry registriert ARE-Gate mit blocking=true wenn features.are aktiviert) |
| `implementation-phase` | I -> RC | Worker-Agent ruft `submit_evidence` waehrend Implementation |
| `installation-and-bootstrap` | INST -> RC | Setup-Skript ruft `load_context`; CP 5/CP 10c validieren Scope-Mapping bei Installation |
| `story-context-manager` | RC -> SCM | `StoryIdentity` (story_id, story_type, story-specific scope) |
| `artifacts` | RC -> A | `are_bundle.json` (ArtifactClass.QA) und `are_gate.json` via ArtifactManager |
| `telemetry-and-events` | RC -> T | `Telemetry.write_event` fuer are_requirements_linked, are_evidence_submitted, are_gate_result |
| `governance-and-guards` | GG -> RC | IntegrityGate prueft bei Closure dass `are_gate_result` mit `status: PASS` in Telemetrie vorliegt (FK-40 §40.8) |
| Configuration (FK-03) | RC -> C | `features.are`, `are.mcp_server`, `are.module_scope_map`, `repositories[].are_scope` |

**Konzept-Refactor-Liste:**

1. FK-40 §40.4 MCP-Wrapper-Wording ist konzeptionell falsch fuer den
   AgentKit-internen Aufruf-Pfad: `AreClient` ist REST-Client (nicht
   MCP-Wrapper). MCP ist Boundary-Control fuer Harness-Agents (Worker/QA,
   harness-neutral via Adapter aus FK-76),
   die direkt mit ARE reden; AgentKit-Code selbst nutzt REST. FK-40 §40.4 muss
   umformuliert werden — getrennte Aufruf-Pfade fuer "AgentKit-Code (REST)" vs.
   "Harness-Agents (MCP)" dokumentieren. Modul-Pfad
   `agentkit.requirements_coverage.are_client`. Konsistent mit GitHub-REST-Adapter
   (FK-12).
2. FK-40 §40.5 Vier Andock-Punkte sind Top-Surface-Methoden in
   RequirementsCoverage, NICHT eigenstaendige Komponenten. Wording in
   FK-40 praezisieren.
3. FK-40 §40.7 ARE-Stage in StageRegistry: BC verify-system registriert die
   Stage; BC requirements-and-scope-coverage stellt nur die Gate-Logik
   bereit (`check_gate`). Verhaeltnis dokumentieren.
4. FK-40 §40.6 Fallback ohne ARE: wenn `features.are: false`, ist die
   gesamte Top-Surface no-op. Aufrufer-BCs brauchen keinen Fallback-Code.
5. FK-40 §40.3.2 Scope-Mapping wird vom Installer (BC 12 CP 5/CP 10c)
   gepflegt, von requirements-and-scope-coverage gelesen. Schreib-Owner:
   installation-and-bootstrap. Lese-Owner: requirements-and-scope-coverage.
6. FK-40 §40.5.2 `are_bundle.json` Content-Plane-Artefakt via
   `artifacts.ArtifactManager` mit ArtifactClass.QA. Producer-Registry-Eintrag
   in BC 8 ergaenzen — Producer `qa-are-context-loader`.
7. FK-40 §40.8 Telemetrie-Events: neue EventTypeId-Werte in FK-68 ergaenzen
   — `are_requirements_linked`, `are_evidence_submitted`, `are_gate_result`.

**Eigenstaendige Detail-Entscheidungen:**

1. Top-Name `RequirementsCoverage` (matcht BC-Namen; `-and-scope-` weggekuerzt
   fuer Komponenten-Pragmatik).
2. Status-Enums + Coordinator im Top (~4 Klassen). Konsistent mit BC 9/13/14.
3. 3 Subs: AreClient (Adapter), ScopeMapping (Konfigurationstabellen),
   DockPoints (Mechanik). Die 4 Andock-Punkte werden NICHT in 4 mini-Subs
   zerlegt.
4. AreClient mit R-Bluttyp — externer MCP-Adapter zu ARE. Konsistent mit
   GitHub-/VectorDB-Adaptern.
5. AreClient `internal` (kein sub_exposed): nur DockPoints-Sub ruft direkt;
   andere BCs gehen ueber Top-Surface.
6. CoverageVerdict + UncoveredRequirement + EvidenceReference im DockPoints-Sub
   konsolidiert.
7. AreBundle-Pydantic-Schema im DockPoints-Sub. Das `are_bundle.json`-Artefakt
   wird via `artifacts.ArtifactManager` mit `ArtifactClass.QA` persistiert.
8. ARE-Aktivierung/Deaktivierung: wenn `features.are: false`, alle
   Top-Surface-Methoden no-op. Top-Surface bleibt unabhaengig vom
   Feature-Flag stabil.

---

### BC 16: kpi-and-dashboard

**Status:** geschnitten (2026-05-01)
**Quellen:** DK-13, FK-60, FK-61, FK-62, FK-63, FK-64
**BC-Verantwortung:** KPI-Katalog, Erhebung, Aggregation/Rollups,
Fact-Tabellen, Dashboard-Sichten, ControlPlaneDesignSystem. Owns:
KpiDefinition, FactSchema, Rollup, DashboardView, ControlPlaneDesignSystem.

**Top:** `KpiAnalytics` (A, top, prefix=`agentkit.kpi_analytics`)

Koordiniert KPI-Katalog, Fact-Persistierung, Refresh-Aggregation,
Dashboard-Views und Design-Token-Bereitstellung. Enthaelt direkt (~4
Klassen): `KpiAnalytics`, `KpiId`, `KpiGranularity`, `KpiStatus`.

**Top-Surface:**
- `KpiAnalytics.list_kpis() -> list[KpiDefinition]`
- `KpiAnalytics.refresh_analytics(project_key, hint_story_id=None) -> RefreshResult`
- `KpiAnalytics.get_dashboard_view(project_key, view_kind) -> DashboardView`
- `KpiAnalytics.query(project_key, sql) -> QueryResult` (Query-Workbench)
- `KpiAnalytics.get_design_tokens() -> DesignTokenSet`

**Sub-1-Komponenten (5):**

| Sub | Bluttyp | Exposure | Verantwortung |
|---|---|---|---|
| `KpiCatalog` | A | internal | KPI-Definitionen aus FK-60. KpiDefinition, KpiCollectionPoint (deklaratives Mapping zu existierenden Events -- KEINE eigenen Hooks), KpiSourceClass (StrEnum: existing_R, new_N), Decision-Question, Versionierung. |
| `FactStore` | A, mix_allowed:[T] | internal | Fact-Tabellen-Schemas (FK-62 §62.3) im analytics-Schema (Postgres). Schreibt direkt via T-Driver -- kpi-and-dashboard ownt Schema. |
| `Aggregation` | A, mix_allowed:[T] | internal | Refresh-Worker (FK-62). DirtySet-Ableitung aus Delta-Events, Rollup-Berechnung, atomare Slice-Updates. Event-getrieben (Story-Closure + Dashboard-Start), kein Daemon. SyncState-Cursor pro project_key. |
| `Dashboard` | A | internal | Dashboard-Views (FK-63). Transport-agnostisch -- HTTP-Frontend liegt im aufrufenden BC (control_plane). |
| `DesignSystem` | A | internal | Visual-Sprache fuer Control-Plane (FK-64). Tokens, Typografie, Komponentenregeln. Orthogonal zu anderen Subs -- wird vom Frontend konsumiert. |

Modul-Prefixes:
- `KpiCatalog`: `agentkit.kpi_analytics.catalog`
- `FactStore`: `agentkit.kpi_analytics.fact_store`
- `Aggregation`: `agentkit.kpi_analytics.aggregation`
- `Dashboard`: `agentkit.kpi_analytics.dashboard`
- `DesignSystem`: `agentkit.kpi_analytics.design_system`

**Klassen-Skizzen:**

- Top (~4): `KpiAnalytics`, `KpiId`, `KpiGranularity` (StrEnum:
  per_story, per_entity_period, per_period), `KpiStatus` (StrEnum:
  active, inventory)
- `KpiCatalog` (~6): `KpiDefinition`, `KpiSourceClass` (StrEnum:
  existing_R, new_N), `KpiDecisionQuestion`, `KpiCollectionPoint`,
  `KpiVersion`, `KpiCatalogStore`
- `FactStore` (~7): `FactSchema` (generic), `FactStory`,
  `FactGuardPeriod`, `FactPoolPeriod`, `FactPipelinePeriod`,
  `FactCorpusPeriod`, `FactTable` (StrEnum)
- `Aggregation` (~6): `RefreshWorker`, `DirtySet`, `DirtySetType`
  (StrEnum), `SyncState`, `Rollup`, `AggregationTrigger` (StrEnum:
  story_closure, dashboard_start)
- `Dashboard` (~6): `Dashboard` (Coordinator), `DashboardView`,
  `DashboardViewKind` (StrEnum: story_kpi, guard_health,
  llm_performance, pipeline_trends, failure_corpus, live),
  `DashboardQueryService`, `LiveView`, `QueryWorkbench`
- `DesignSystem` (~6): `DesignTokenSet` (Coordinator), `ColorToken`,
  `TypographyToken`, `SemanticAccent` (StrEnum), `ComponentGuideline`,
  `StoryCockpitLayout`

Total: ~35 Klassen.

**intra_bc_layer_order:**
1. `KpiCatalog` (Definitionen, Fundament)
2. `FactStore` (Datenmodell, Postgres-Schema)
3. `Aggregation` (Refresh-Worker schreibt in FactStore)
4. `Dashboard` (liest FactStore, zeigt Views)
5. `DesignSystem` (orthogonale UI-Sprache)

**Beziehungen zu anderen BCs:**

| Andere BC | Richtung | Was |
|---|---|---|
| `telemetry-and-events` | KA -> T | `Telemetry.read_projection` fuer execution_events + qa_*+story_metrics + phase_state_projection (Aggregation-Eingabe) |
| `failure-corpus` | KA -> FC | `Telemetry.read_projection` fuer fc_incidents/fc_patterns/fc_check_proposals (Failure-Corpus-Tab) |
| `execution-planning` | KA -> EP | `Telemetry.read_projection` fuer ExecutionPlan/PlannedStory (Pflichtsichten Dependency-Graph etc., FK-64 §64.2) |
| `story-closure` | C -> KA | Closure triggert `refresh_analytics(project_key, hint_story_id)` |
| `pipeline-framework` | KA -> PF | indirekt (Dashboard-Start triggert refresh_analytics -- Catch-up-Sync) |
| `installation-and-bootstrap` | INST -> KA | CP 5+CP 7 erzeugen analytics-Schema bei Projektregistrierung |
| `governance-and-guards` | KA -> GG | Guard-KPIs basieren auf integrity_violation-Events + guard_invocation_counters |
| State-Backend-Drivers | KA -> SBD | T-Adapter fuer analytics-Schema (Postgres) |
| `control_plane` (R-Frontend) | CP -> KA | HTTP-Aufrufe an Top-Surface; konsumiert `get_design_tokens` fuer UI |

**Konzept-Refactor-Liste:**

1. FK-60 §60.1 Top-Level "KpiAnalyticsEngine" -> BC-Top heisst
   `KpiAnalytics` (kein -Engine-Suffix; konsistent mit anderen Tops).
2. FK-61 Collection-Points sind deklarative Mapping-Aussagen, NICHT
   eigene Hook-Logik. Hooks/Events leben in
   telemetry-and-events.TelemetryHooks. Wording in FK-61 praezisieren.
3. FK-62 Refresh-Worker liest aus runtime-Schema
   (Owner: telemetry-and-events.ProjectionAccessor) und FC-Tabellen
   (Owner: failure-corpus). Lese-Schnittstelle ueber
   `Telemetry.read_projection`. FK-62 muss diese Top-Surface-Nutzung
   dokumentieren.
4. FK-62 §62 Aggregation schreibt in analytics-Schema (Fact-Tabellen).
   Owner: kpi-and-dashboard.FactStore. Schreib-Adapter via T-Driver
   direkt. Konsistent mit BC-9-Pattern.
5. FK-63 Dashboard HTTP-Server: Boundary-Control gehoert in das
   aufrufende BC (control_plane Frontend). KpiAnalytics-Top-Surface ist
   transport-agnostisch. FK-63 wording praezisieren.
6. FK-64 DesignSystem ist UI-Layer: Tokens werden vom Frontend
   (control_plane) konsumiert. DesignSystem-Sub haelt nur die
   Token-Definitionen + Guidelines.
7. FK-69-Verweis auf FK-63 fuer Dashboard-Autoritaet ist konsistent --
   telemetry-and-events.ProjectionAccessor ist DB-Zugriff,
   kpi-and-dashboard.Dashboard ist Sicht-Schicht.

**Eigenstaendige Detail-Entscheidungen:**

1. Top-Name `KpiAnalytics` -- matcht FK-60 `KpiAnalyticsEngine`
   (-Engine weggekuerzt). `Dashboard` ist Sub, nicht Top.
2. Status-Enums + KpiId im Top (~4 Klassen). Konsistent mit BC 9/13/14/15.
3. 5 Subs entlang FK-60..64 -- eng am Konzept-Schnitt. Konsolidierung
   wuerde fachliche Schnittlinien verwischen.
4. `FactStore` separat von `Aggregation` -- Datenmodell (Schemas) vs.
   Worker-Logik (Refresh). Saubere Trennung.
5. `DesignSystem` als orthogonale Sub fuer UI-Sprache. Wird von
   control_plane (Frontend, R-Bluttyp) konsumiert -- nicht von anderen
   Subs.
6. KPI-Erhebung-Hooks liegen NICHT hier sondern in
   telemetry-and-events.TelemetryHooks. KpiCatalog.KpiCollectionPoint
   ist nur deklaratives Mapping.
7. fact_*-Tabellen-Persistenz: kpi-and-dashboard.FactStore ownt Schema
   und schreibt direkt via T-Driver. Konsistent mit BC-9-Korrektur-Pattern.
8. RefreshWorker event-getrieben (Story-Closure + Dashboard-Start),
   kein Daemon/Cron (FK-62 §62).
9. Dashboard-HTTP-Server: Boundary-Control bei aufrufendem BC
   (control_plane Frontend); KpiAnalytics-Top-Surface ist
   transport-agnostisch.

---

## Cross-BC Drift-Punkte

### IntegrityGate

- FK-20 sagt: IntegrityGate ist Sub von ClosurePhase
- bounded-contexts.yaml sagt: IntegrityGate gehoert zu governance-and-guards
- **Entscheidung: bounded-contexts.yaml gewinnt.** IntegrityGate ist Sub von
  Governance (`agentkit.governance.integrity_gate`). FK-20 muss entsprechend
  refactored werden.

### SetupPreflightGate

- FK-22 (setup-preflight formal spec): domain `governance-and-guards` per
  domain-registry.yaml
- **Bestaetigt:** SetupPreflightGate gehoert zu Governance, nicht zu
  pipeline-framework. PipelineEngine ruft SetupPreflightGate ueber
  Sub-Exposed-Surface auf.

### WorktreeManager

- Querschnittliche shared-Komponente
- Owner: story-lifecycle (StoryContextManager)
- Genutzt von: pipeline-framework (PipelineEngine) und story-lifecycle
  (StoryContextManager)
- Modellierung als `component_kind: shared` in entities.md

### FK-23 vs. FK-25 Freeze-Position-Drift (exploration-and-design)

- FK-25 ueberschreibt FK-23: DesignFreeze erfolgt nach Gate-PASS, nicht davor.
- FK-23 Mermaid-Flowchart in §23.3.1 muss nachgezogen werden.
- Eskalations-Mechanik (PAUSED/ESCALATED) gehoert zu governance-and-guards.
  In FK-23/FK-25 nur fachliche Erkennung (MandateClass, ScopeExplosion) behalten;
  operative Mechanik nur referenzieren.

### BLOCKED-Eskalation §26.11.2 (implementation-phase)

- FK-26 §26.11.2 beschreibt die BLOCKED->ESCALATED-Kette ungenaue:
  Phase-Runner-Logik (Mapping auf PhaseStatus.ESCALATED) gehoert zu
  pipeline-framework.PhaseExecutor, nicht zu implementation-phase.
- **Entscheidung:** ImplementationHandler signalisiert ESCALATED via
  HandlerResult. PhaseExecutor reagiert generisch. Wording in FK-26
  §26.11.2 muss praezisiert werden ("ImplementationHandler signalisiert
  ESCALATED via HandlerResult; pipeline-framework.PhaseExecutor reagiert
  generisch auf PhaseStatus.ESCALATED").

### ExecutionReport-Trigger bei vorherigem FAILED (story-closure) — entschieden

- FK-29 §29.4.1 sagt: ExecutionReport wird "am Ende jeder
  Story-Bearbeitung — unabhaengig vom Ergebnis (COMPLETED, ESCALATED,
  FAILED)" erzeugt.
- **Entscheidung: Option A.** `pipeline-framework.PipelineEngine` ruft
  ClosureSequence-Top auch bei FAILED in fruehen Phasen auf — im
  Skip-Modus mit nur Report-Erzeugung. `ClosureProgress`-Felder bleiben
  auf `false`. `ExecutionReport` ist intern in BC 7 (NICHT
  `sub_exposed`); pipeline-framework ruft NICHT direkt auf.
- Begruendung: Single-Owner fuer alle Closure-Anteile;
  pipeline-framework bleibt orchestrierend statt fachlich.
- FK-29 §29.4.1 dokumentiert die Entscheidung explizit.

### ConformanceService und StageRegistry

- Alte Prefixe (`agentkit.governance.doc_fidelity`,
  `agentkit.governance.policies`) stammen aus dem v2-Modell
- Neue Prefixe: `agentkit.verify_system.conformance_service` und
  `agentkit.verify_system.stage_registry`
- Die alten module-Prefixe erzeugen Code-Lints — das ist erwuenscht
  (Zero-Debt-Policy)

### FK-69 mischt telemetry-and-events und failure-corpus

- FK-69 definiert sechs Tabellen: qa_stage_results, qa_findings,
  story_metrics, phase_state_projection (telemetry-and-events) UND
  fc_incidents, fc_patterns, fc_check_proposals (failure-corpus).
- Ownership-Cut: FK-69 §69.4 listet bereits korrekte Owner
  ("failure_corpus" fuer fc_*-Tabellen). Aber FK-69 als Ganzes hat
  domain `telemetry-and-events`.
- Aufloesungs-Vorschlag: FK-69 in zwei Doks aufteilen oder
  fc_*-Sektionen nach failure-corpus-Doc verschieben. Bis dahin:
  Inhalt-Owner pro Sub-Sektion respektieren.

### Projektions-Schema-Ownership (telemetry-and-events vs. Owner-BCs)

- telemetry-and-events ownt die Telemetrie-DB-Zugriffsschicht (ProjectionAccessor) und das generische Envelope, NICHT die domain-spezifischen Schemas pro Tabelle.
- Schema-Owner pro Tabelle (FK-69 §69.4):
  - `qa_stage_results`, `qa_findings` -> verify-system.StageRegistry
  - `story_metrics` -> story-closure.PostMergeFinalization (mit WorkflowMetricCalculator)
  - `phase_state_projection` -> pipeline-framework.PhaseExecutor
- Owner-BCs definieren Pydantic-Schemas, telemetry-and-events haelt nur ProjectionRecordBase + Tabellen-Register.
- Single-Writer-Regel (FK-69 §69.4) bleibt erfuellt durch Owner-BC-Disziplin: jede Tabelle hat genau einen Owner-BC, der via `Telemetry.write_projection` schreibt.
- Konzept-Refactor: FK-68/FK-69 sollten dieses Owner-Modell explizit dokumentieren.

### Budget-Hook Hybrid (telemetry-and-events vs. governance-and-guards)

- FK-68 §68.6 `telemetry/budget.py` emittiert `web_call`-Event
  (Telemetry) UND blockiert bei Schwellwert-Ueberschreitung (Governance).
- Strittig — passt nicht in saubere BC-Trennung.
- Aufloesungs-Vorschlag: Aufspaltung in
  `telemetry.hooks.BudgetEventEmitter` (nur Event) +
  `governance.guard_system.WebCallBudgetGuard` (Blockierung).
  Entscheidung in spaeterem Refactor.

### Governance-Risk-Window-Sensor (telemetry-and-events vs. governance-and-guards)

- FK-68 §68.8 beschreibt NormalizedEvent + Risk-Score +
  Schwellenwert-Pruefung.
- Sensor-Daten (NormalizedEvent-Mapping) gehoeren zu
  telemetry-and-events.ReadModels.
- Score-Akkumulation und Schwellenwert-Pruefung gehoeren zu
  governance.GovernanceObserver (BC 4).
- FK-68 §68.8 wording praezisieren.

### F-43-030 Normative Skill-Nutzung — Enforcement-Owner entschieden

- FK-43 §43.6.2 F-43-030: Agents MUESSEN Skills nutzen, nicht ad-hoc-Methodik einsetzen.
- agent-skills definiert die Norm (Norm-Owner: BC agent-skills).
- **Entscheidung (Option A):** Enforcement-Owner ist BC governance-and-guards
  (`governance.guard_system`, Hook `skill_usage_check`). Erkennung und Blockade
  erfolgen zur Laufzeit vor dem Tool-Call (fail-fast), nicht erst im Verify-Block.
  verify-system.PolicyEngine ist kein Enforcement-Owner fuer F-43-030.
- Dokumentiert in: FK-43 §43.6.2, FK-30 §30.5.1.

### Skill-Bundle vs. Prompt-Bundle (agent-skills vs. prompt-runtime)

- Beide BCs haben eigenstaendige Bundle-Konzepte (Skill-Bundle, Prompt-Bundle) mit
  Versionierung und Pin-aehnlicher Mechanik.
- Skills sind Verzeichnis-Symlinks (harness-spezifischer Pfad: Claude Code `.claude/skills/`, Codex harness-eigenes Aequivalent — siehe FK-43 §43.4.1 und FK-76); Prompts sind Datei-Materialisierungen
  (`.agentkit/prompts/{run_id}/...`).
- Strukturell aehnlich, mechanisch unterschiedlich.
- FK-43 frontmatter `defers_to: FK-44` ist mehrdeutig: Skill-Template-Inhalt kann optional
  via prompt-runtime materialisiert werden, aber Skill-Bundle-Mechanik (Symlinks) bleibt
  agent-skills-eigenstaendig.
- Aufloesung: FK-43 wording praezisieren.

### Hook-Registration Owner (installation-and-bootstrap vs. governance-and-guards)

- FK-50 CP 9: Installer schreibt direkt harness-spezifische Settings-Dateien (Claude Code: `.claude/settings.json`; Codex: harness-eigenes Aequivalent — siehe FK-76 §76.5) mit Hook-Eintraegen.
- Konsistente Trennung waere: Installer ruft `Governance.register_hooks(hook_definitions)`
  (BC 4 Top-Surface), und der Harness-Adapter materialisiert die harness-spezifische Settings-Datei. JSON-/TOML-Manipulation gehoert zu governance.guard_system / HookRuntime bzw. dem jeweiligen Harness-Adapter.
- Aufloesungs-Vorschlag: BC 4 (governance-and-guards) erhaelt Top-Surface-Methode
  `register_hooks`; Installer ruft diese statt direkter JSON-Manipulation.
- FK-50 §50.3 CP 9 entsprechend nachziehen.

### CheckpointEngine nutzt FlowDefinition (installation-and-bootstrap vs. pipeline-framework)

- FK-50 §50.3.1: Checkpoint-Engine modelliert ihren Ablauf ueber
  `FlowDefinition(level="component", owner="Installer")`.
- FlowDefinition-DSL ist Owner pipeline-framework (FK-20).
- Cross-BC-Beziehung: Installer NUTZT die DSL als Mechanik, definiert aber nicht die
  DSL selbst.
- Aufloesung: dokumentieren als zulaessige Cross-BC-Wiederverwendung;
  FlowDefinition-Schnittstelle bleibt pipeline-framework-Top-Surface (sub_exposed).

### Port-Vokabular in FK-70

- FK-70 §70.10.1 nutzt `DependencyGraphPort`, `ReadinessAssessmentPort`,
  `ExecutionPlanPort`, `SchedulingPolicyPort`.
- Per BC-Vokabular-Disziplin (Komponente, Klasse, Schnittstelle — kein
  Port/Adapter/Hexagonal) sind diese Begriffe verboten.
- Aufloesung: FK-70 umformulieren auf "Komponenten" und "Top-Surfaces";
  Klassen heissen direkt nach ihrer Verantwortung.

### Orchestrator-Vertrag (execution-planning vs. pipeline-framework)

- FK-70 §70.8: pipeline-framework.PipelineEngine MUSS
  `ExecutionPlanning.evaluate_scheduling` vor jedem Story-Start aufrufen.
- pipeline-framework darf nicht frei in Backlog greifen.
- Aufloesungs-Vorschlag: FK-20 ergaenzen — PipelineEngine konsumiert
  `ExecutionPlanning`-Top-Surface; PipelineEngine ist transport-agnostisch.

---

## Konzept-Refactor-Liste (konsolidiert)

Die folgende Liste enthaelt alle identifizierten Refactor-Aufgaben
aus den 4 BC-Schnitten. Sie ist nicht abschliessend — weitere Punkte
koennen bei der Implementierungsphase auftauchen.

| Prio | Ziel-BC | Aufgabe |
|------|---------|---------|
| 1 | pipeline-framework | Modul-Pfade von `agentkit.pipeline` auf `agentkit.pipeline_engine` migrieren (FK-20, FK-36, FK-39, FK-45) |
| 2 | verify-system | `agentkit.governance.doc_fidelity` -> `agentkit.verify_system.conformance_service` |
| 3 | verify-system | `agentkit.governance.policies` -> `agentkit.verify_system.stage_registry` |
| 4 | verify-system | `agentkit.llm_evaluator` -> `agentkit.verify_system.llm_evaluator` |
| 5 | governance-and-guards | `agentkit.guard_system` + `agentkit.governance.guards` -> `agentkit.governance.guard_system` |
| 6 | governance-and-guards | `agentkit.governance.monitoring` -> `agentkit.governance.governance_observer` |
| 7 | governance-and-guards | IntegrityGate-Prefix in FK-20 auf `agentkit.governance.integrity_gate` aendern |
| 8 | governance-and-guards | `agentkit.governance.hookruntime` (HookRuntime, BC noch offen) bleibt unveraendert bis HookRuntime-BC geschnitten wird |
| 9 | exploration-and-design | FK-23 §23.3.1 Mermaid-Flowchart: Freeze-Position nach Gate-PASS korrigieren (FK-25 gewinnt) |
| 10 | exploration-and-design | Eskalations-Mechanik aus FK-23/FK-25 auslagern — nur fachliche Erkennung (MandateClass, ScopeExplosion) bleibt |
| 11 | exploration-and-design | CLI-Beispiele aus FK-23/FK-25 entfernen (Boundary-Controls) |
| 12 | implementation-phase | FK-26 §26.5a/§26.5b: Modul-Pfad-Aktualisierung fuer `agentkit.verify_system.evidence_assembler` (FK-28-Referenz korrekt bestaetigen) |
| 13 | implementation-phase | FK-26 §26.10 Telemetrie-Tabelle: Events bleiben referenziert, Owner-Sache von telemetry-and-events (kein Prefix-Konflikt, Wording klaeren) |
| 14 | implementation-phase | FK-49 §49.1.6 review_guard-Verweis: bleibt unter `agentkit.governance.guard_system` (Pfad bestaetigen) |
| 15 | implementation-phase | FK-49 §49.1.7 `worker_health.*`-Konfiguration: in implementation-phase definiert; FK-93 referenziert nur |
| 16 | implementation-phase | FK-26 §26.11.2: Wording praezisieren ("ImplementationHandler signalisiert ESCALATED via HandlerResult; PhaseExecutor reagiert generisch") |
| 17 | story-closure | FK-29 §29.1.2 Mermaid-Flowchart und §29.5: IntegrityGate-Aufruf praezisieren — Closure delegiert an `agentkit.governance.integrity_gate`. Kein Closure-eigener IntegrityGate-Sub. |
| 18 | story-closure | FK-29 §29.5 Guard-Deaktivierung: Lock-Record-Verwaltung gehoert zu Governance. Closure ruft `Governance.deactivate_locks(story_id)`. Wording praezisieren. |
| 19 | story-closure | FK-29 Layer-2-Artefakte und Doctreue-Ebene-4: Modul-Pfade auf `agentkit.verify_system.*` aktualisieren (Konsequenz BC-2-Refactor). |
| 20 | story-closure | FK-27: Closure-Anteile (closure-sequence, ClosurePayload, Finding-Resolution-Gate-Mechanik) ausschliesslich nach FK-29 verschieben. FK-27 darf nur referenzieren. |
| 21 | story-closure | FK-29 §29.4: ExecutionReport-Aufrufpfad bei FAILED in fruehen Phasen praezisieren — Annahme Closure-Top im Skip-Modus; falls pipeline-framework direkt triggert, `ExecutionReport` auf `sub_exposed` aendern. |
| 22 | artifacts | FK-71 §71.3 Lock-Mechanismus auslagern: Inhalt nach FK-31 (governance/Hook-Enforcement) verschieben; FK-71 darf nur referenzieren. |
| 23 | artifacts | FK-71 §71.4 Stage-Registry: `StageDefinition`-Klasse zu `verify-system.StageRegistry`-Sub verschieben; FK-71 §71.4 zu verify-system konsolidieren oder nur referenzieren. |
| 24 | artifacts | FK-71 §71.1.2 PROTECTED_ARTIFACTS-Liste: gehoert zur Hook-Konfiguration in BC 4 (governance.guard_system), nicht zu artifacts. |
| 25 | artifacts | FK-71 §71.1.1 Schutzgrad-Spalte: Schutz-Information in governance-Doku fuehren; artifacts behaelt nur Klassifikation (Erzeuger, Beispiele). |
| 26 | artifacts | FK-71 `authority_over` einschraenken: nur `artefakt-envelope` und `producer-registry` behalten; `lock-mechanismus` und `stage-registry-types` entfernen. |
| 27 | telemetry-and-events | FK-69-Split: `fc_incidents`, `fc_patterns`, `fc_check_proposals` (FK-69 §69.9) gehoeren zu failure-corpus. FK-69 muss inhaltlich aufgeteilt werden. |
| 28 | telemetry-and-events | FK-68 §68.8 Governance-Risk-Window: `NormalizedEvent` bleibt in ReadModels (Sensor); Score-Akkumulation gehoert zu `governance.GovernanceObserver`. FK-68 §68.8 praezisieren. |
| 29 | telemetry-and-events | FK-68 §68.6 Budget-Hook: Hybrid aus Event-Emission (telemetry) und Blocking (governance). Moegliche Aufspaltung in `telemetry.hooks.BudgetEventEmitter` + `governance.guard_system.WebCallBudgetGuard`. |
| 30 | telemetry-and-events | FK-68 §68.3.1 Hook-Pfad-Tabelle: Modul-Pfade auf `agentkit.telemetry.hooks.*` aktualisieren (von `telemetry/hook.py`, `telemetry/review_guard.py`, `telemetry/budget.py`, `telemetry/divergence.py`). |
| 31 | telemetry-and-events | FK-68 `authority_over`: telemetry, eventing, workflow-metriken bleiben; fc_*-Tabellen-Anteile entfernen. |
| 32 | telemetry-and-events | FK-69 §69.6-69.8 (qa_*, story_metrics): bleiben in telemetry-and-events, Modul-Pfade auf `agentkit.telemetry.read_models.*` aktualisieren. |
| 33 | telemetry-and-events / verify-system / story-closure / pipeline-framework | Projektions-Schema-Ownership: ProjectionAccessor in telemetry-and-events ownt nur DB-Zugriffsschicht; QaStageResult/QaFinding-Schemas wandern zu verify-system, StoryMetric/WorkflowMetric zu story-closure, PhaseStateProjection zu pipeline-framework. FK-68/FK-69 entsprechend nachziehen. |
| 34 | prompt-runtime | FK-44 §44.6 "Artefakt-ID" fuer Audit-Records: AuditRecord wird via `artifacts.ArtifactManager` persistiert. Beziehung PR -> A explizit in FK-44 dokumentieren. |
| 35 | prompt-runtime | FK-44 §44.4.2 Evaluator-Prompts: `verify_system.LlmEvaluator` muss alle Templates via `PromptRuntime.materialize_prompt` aufloesen. FK-44 entsprechend praezisieren. |
| 36 | prompt-runtime / installation-and-bootstrap | FK-44 verweist auf FK-50 (Installer): `update_binding(bundle_id, version)` ist Top-Surface von PromptRuntime; FK-50 muss diese Schnittstelle dokumentieren. |
| 37 | prompt-runtime | FK-44 §44.5 Modul-Pfade in Code-Beispielen: Filesystem-Konvention; Schema lebt in `BundlePinning`-Sub (`agentkit.prompt_runtime.bundle_pinning`). Pfade in FK-44 aktualisieren. Vokabular: `project-prompt-binding`-Glossarbegriff in FK-44 entweder beibehalten als fachlicher Begriff oder auf `project-prompt-pin` vereinheitlichen (Klassen heissen `ProjectPromptPin`). |
| 38 | prompt-runtime | FK-44 §44.6 Audit-Hash-Felder (`template_sha256`, `render_input_digest`, `output_sha256`): PromptAuditHash-Pydantic-Schema Owner ist Materialization-Sub. FK-44 Schema-Owner-Cut explizit machen. |
| 39 | prompt-runtime / telemetry-and-events | `prompt_used`-Event-Frage offen: falls eingefuehrt, in EventTypeId-Liste (BC 9 TelemetryContract) ergaenzen und in FK-44 dokumentieren. |
| 40 | agent-skills | FK-43 §43.4.2 `PlaceholderSubstitutor`: Konfigurations-Schnittstelle (read-only auf PipelineConfig) dokumentieren; substituiert gh_owner/gh_repo/project_prefix/project_key aus FK-03 Foundation. |
| 41 | agent-skills | FK-43 §43.5.2 Upgrade-Verhalten: Bundle-Version-Pin-Mechanik klaeren — eigenstaendiger Skill-Pin (Skills haben anderen Lifecycle als Prompt-Bundles); Verhaeltnis zu `prompt-runtime.BundlePinning` explizit machen. |
| 42 | agent-skills | FK-43 §43.6.2 Skill-Quality: Lese-Schnittstellen via `Telemetry.read_projection` (sub_exposed) und failure-corpus-Top dokumentieren; WorkflowMetric-Daten-Owner (story-closure.PostMergeFinalization) referenzieren. |
| 43 | agent-skills / installation-and-bootstrap | FK-43 §43.4.1 Installer-Aufruf: `Skills.bind_skill` als Top-Surface (analog zu `PromptRuntime.update_binding`); FK-50 muss diese Schnittstelle dokumentieren. |
| 44 | agent-skills / prompt-runtime | FK-43 frontmatter `defers_to: FK-44` praezisieren: agent-skills hat eigenes Bundle-Konzept fuer Skill-Verzeichnisse; prompt-runtime wird nur fuer Inhalt-Render bei Run aufgerufen, falls noetig. |
| 45 | agent-skills / governance-and-guards / verify-system | F-43-030 Normative Skill-Nutzung: Enforcement-Owner festlegen (governance.guard_system Hook-basiert vs. verify-system.PolicyEngine Stage-basiert); FK-43 entsprechend praezisieren. |
| 46 | installation-and-bootstrap | FK-50 §50.3.1 Checkpoint-Engine als Komponenten-Flow: nutzt FlowDefinition aus pipeline-framework (Einheits-DSL FK-20). Cross-BC-Beziehung in FK-50 dokumentieren. |
| 47 | installation-and-bootstrap | FK-50 CP 8 Skill-Symlinks: Installer ruft `Skills.bind_skill` (BC 11) und `PromptRuntime.update_binding` (BC 10). Code-Beispiel mit `create_symlink(...)` in FK-50 ist irrefuehrend; Wording praezisieren. |
| 48 | installation-and-bootstrap | FK-50 CP 9 Hook-Registration: konsistente Trennung via `Governance.register_hooks(hook_definitions)` (BC 4 Top-Surface). JSON-Manipulation gehoert zu governance.guard_system. FK-50 §50.3 CP 9 nachziehen. |
| 49 | installation-and-bootstrap | FK-50 CP 7 BackendRegistration: Owner installation-and-bootstrap (eigene `project_registry`-Tabelle). Schema lebt hier; Schreib-Adapter via T-Driver. Konsistenz mit BC 9 Owner-Modell dokumentieren. |
| 50 | installation-and-bootstrap | FK-51 Customization-Erkennung: CustomizationFootprint kombiniert PipelineConfig (FK-03), CCAG-Regeln (governance) und Bundle-Bindings (prompt-runtime + agent-skills). Lese-Schnittstellen via Top-Surfaces dokumentieren. |
| 51 | installation-and-bootstrap | FK-50 §50.2 CLI-Aufrufe (`agentkit register-project`): CLI ist Boundary-Control des aufrufenden BC. Installer ist transport-agnostisch; CLI-Beispiele entsprechend auslagern. |
| 52 | failure-corpus | FK-69 §69.9 fc_*-Tabellen-Schemas: gehoeren zu failure-corpus. Schemas (FailurePattern, GeneratedCheckProposal, fc_incidents-Schema) leben hier; Postgres-Persistenz via `Telemetry.write_projection`. FK-69 muss aufgeteilt oder fc_*-Sektionen verweisen auf failure-corpus als Owner. |
| 53 | failure-corpus | FK-41 §41.3 Speicherung `.agentkit/failure-corpus/`: JSONL-Dateien als Legacy/Export. Kanonische Wahrheit liegt in Postgres-fc_*-Tabellen. FK-41 wording praezisieren. |
| 54 | failure-corpus | FK-41 §41.6.2/§41.6.4 LLM-Aufrufe (Schritt 1 Schaerfen, Schritt 3 Proposal-Generierung): laufen ueber `verify-system.LlmEvaluator` mit `prompt-runtime.materialize_prompt`. Modul-Pfade in FK-41 dokumentieren. |
| 55 | failure-corpus | FK-41 §41.6.6 Schritt 5 (Story-Erzeugung): ruft `Integrations.github`-Adapter. Cross-BC-Beziehung zu pipeline-framework (Story durchlaeuft Pipeline regulaer) in FK-41 dokumentieren. |
| 56 | failure-corpus | FK-41 §41.4.2 QA-Evaluation als Capture-Akteur (F-41-069): Verify-System ruft `FailureCorpus.record_incident` direkt. FK-41 Capture-Akteur-Tabelle entsprechend praezisieren. |
| 57 | failure-corpus | FK-41 §41.6.7 Auto-Deaktivierung: nutzt Workflow-Metric-Daten (Owner: story-closure.PostMergeFinalization). Lese-Schnittstelle via `Telemetry.read_projection` in FK-41 dokumentieren. |
| 58 | failure-corpus | FK-41 §41.9 CLI-Befehle: Boundary-Control des aufrufenden BC. FailureCorpus ist transport-agnostisch; CLI-Beispiele aus FK-41 auslagern. |
| 59 | execution-planning | FK-70 §70.10.1 Port-Vokabular: `DependencyGraphPort`, `ReadinessAssessmentPort`, `ExecutionPlanPort`, `SchedulingPolicyPort` auf "Komponenten" und "Top-Surfaces" umformulieren. |
| 60 | execution-planning | FK-70 §70.10.2 Persistenz: ExecutionPlan + PlannedStory + DependencyEdge via `Telemetry.write_projection`; Schema-Owner: execution-planning. Konsistent mit BC-9-Pattern. |
| 61 | execution-planning | FK-70 §70.10.3 Audit-Events: EventTypeId-Werte ergaenzen FK-68 — `dependency_recorded`, `story_ready`, `story_blocked`, `plan_revised`, `scheduling_decided`, `gate_resolved`, `rulebook_compiled`, `wave_collapsed`. |
| 62 | execution-planning | FK-70 §70.7d Rulebook-DSL: NICHT die FlowDefinition-DSL aus FK-20. Verhaeltnis explizit in FK-70 dokumentieren — execution-planning hat eigene Rulebook-DSL fuer Scheduling-Hints. |
| 63 | execution-planning | FK-70 §70.5.2 READY regelbasiert: Konsistenz mit BC 3 (StoryIdentity hat basis-StoryStatus; ExecutionPlanning leitet PlanningStatus ab). Wording in FK-21/FK-24 nachziehen. |
| 64 | execution-planning / pipeline-framework | FK-70 §70.8 Orchestrator-Vertrag: PipelineEngine MUSS `ExecutionPlanning.evaluate_scheduling` vor jedem Story-Start aufrufen. FK-20 ergaenzen. |
| 65 | requirements-and-scope-coverage | FK-40 §40.4: `AreClient` ist REST-Client zur ARE-REST-API (NICHT MCP-Wrapper). MCP ist Boundary-Control fuer Harness-Agents (harness-neutral via Adapter aus FK-76), die direkt mit ARE reden; AgentKit-Code nutzt REST. FK-40 §40.4 wording umformulieren — getrennte Aufruf-Pfade fuer AgentKit-Code (REST) vs. Harness-Agents (MCP). Konsistent mit GitHub-REST-Adapter (FK-12). |
| 66 | requirements-and-scope-coverage | FK-40 §40.5 Vier Andock-Punkte sind Top-Surface-Methoden in RequirementsCoverage, NICHT eigenstaendige Komponenten. Wording in FK-40 praezisieren. |
| 67 | requirements-and-scope-coverage / verify-system | FK-40 §40.7 ARE-Stage in StageRegistry: BC verify-system registriert die Stage; BC requirements-and-scope-coverage stellt nur die Gate-Logik bereit (`check_gate`). Verhaeltnis dokumentieren. |
| 68 | requirements-and-scope-coverage | FK-40 §40.6 Fallback ohne ARE: wenn `features.are: false`, ist die gesamte Top-Surface no-op. Aufrufer-BCs brauchen keinen Fallback-Code. |
| 69 | requirements-and-scope-coverage / installation-and-bootstrap | FK-40 §40.3.2 Scope-Mapping wird vom Installer (BC 12 CP 5/CP 10c) gepflegt, von requirements-and-scope-coverage gelesen. Schreib-Owner: installation-and-bootstrap. Lese-Owner: requirements-and-scope-coverage. |
| 70 | requirements-and-scope-coverage / artifacts | FK-40 §40.5.2 `are_bundle.json` Content-Plane-Artefakt via `artifacts.ArtifactManager` mit ArtifactClass.QA. Producer-Registry-Eintrag in BC 8 ergaenzen — Producer `qa-are-context-loader`. |
| 71 | requirements-and-scope-coverage / telemetry-and-events | FK-40 §40.8 Telemetrie-Events: neue EventTypeId-Werte in FK-68 ergaenzen — `are_requirements_linked`, `are_evidence_submitted`, `are_gate_result`. |
| 72 | kpi-and-dashboard | FK-60 §60.1 Top-Level "KpiAnalyticsEngine" umbenennen: BC-Top heisst `KpiAnalytics` (kein -Engine-Suffix; konsistent mit anderen Tops). |
| 73 | kpi-and-dashboard | FK-61 Collection-Points sind deklarative Mapping-Aussagen, NICHT eigene Hook-Logik. Hooks/Events leben in telemetry-and-events.TelemetryHooks. Wording in FK-61 praezisieren. |
| 74 | kpi-and-dashboard | FK-62 Refresh-Worker liest aus runtime-Schema (Owner: telemetry-and-events.ProjectionAccessor) und FC-Tabellen (Owner: failure-corpus) ueber `Telemetry.read_projection`. FK-62 muss diese Top-Surface-Nutzung dokumentieren. |
| 75 | kpi-and-dashboard | FK-62 §62 Aggregation schreibt in analytics-Schema (Fact-Tabellen). Owner: kpi-and-dashboard.FactStore. Schreib-Adapter via T-Driver direkt. Konsistent mit BC-9-Pattern. |
| 76 | kpi-and-dashboard | FK-63 Dashboard HTTP-Server: Boundary-Control gehoert in das aufrufende BC (control_plane Frontend). KpiAnalytics-Top-Surface ist transport-agnostisch. FK-63 wording praezisieren. |
| 77 | kpi-and-dashboard | FK-64 DesignSystem ist UI-Layer: Tokens werden vom Frontend (control_plane) konsumiert. DesignSystem-Sub haelt nur Token-Definitionen + Guidelines. |
| 78 | kpi-and-dashboard / telemetry-and-events | FK-69-Verweis auf FK-63 fuer Dashboard-Autoritaet ist konsistent -- telemetry-and-events.ProjectionAccessor ist DB-Zugriff, kpi-and-dashboard.Dashboard ist Sicht-Schicht. Beziehung explizit in FK-69 dokumentieren. |

---

## Noch nicht geschnittene BCs (0/16) -- alle BCs geschnitten

Alle 16 BCs sind geschnitten. Bestehende entities.md-Eintraege fuer
verbleibende Stubs (story, control_plane, projectedge, hook_runtime,
state_backend_drivers, phase_state_store) bleiben unveraendert bis
der jeweilige BC geschnitten wird.
