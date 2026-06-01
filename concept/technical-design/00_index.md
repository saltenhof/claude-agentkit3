---
concept_id: FK-00
title: Technisches Feinkonzept
module: meta
cross_cutting: true
status: active
doc_kind: core
parent_concept_id:
authority_over:
  - scope: technical-overview
  - scope: frontmatter-contract
defers_to: []
supersedes: []
superseded_by:
tags: [feinkonzept, index, dokumentenstruktur, architekturrahmen]
formal_scope: prose-only
---

# AgentKit — Technisches Feinkonzept

## Dokumentenuebersicht

Dieses Feinkonzept detailliert das fachliche Domaenenkonzept
(`agentkit-domain-concept.md`) so weit technisch aus, dass ein
Entwickler sofort Code schreiben kann. Es ist in thematische
Kapitel-Dokumente und Referenzanhaenge gegliedert.

Grundlage fuer die Priorisierung und Vollstaendigkeitspruefung ist die
Fachkonzept-Checkliste (`fachkonzept-checkliste.md`) mit 568 atomaren
Anforderungen.

Der Index ist nach Bounded Contexts (BCs) sektioniert, in der Reihenfolge
wie in `concept/formal-spec/architecture-conformance/entities.md` festgelegt.
Foundation- und cross_cutting-Konzepte haben eine eigene Sektion.
Referenzanhaenge folgen am Ende.

---

## 1. Foundation und cross_cutting Konzepte

| Dokument | BC/Domain | Inhalt |
|----------|-----------|--------|
| `01_systemkontext_und_architekturprinzipien.md` | cross_cutting | Zielbild, Systemgrenzen, Architekturprinzipien, Fail-Closed, Trust Boundaries |
| `02_domaenenmodell_zustaende_artefakte.md` | cross_cutting | Kanonische Begriffe, Zustandsmodelle, Identifikatoren, Artefaktklassen |
| `03_konfigurationsmodell_schemas_versionierung.md` | cross_cutting | Config-Hierarchie, Dateiformate, Defaults, Validierung |
| `04_betrieb_monitoring_audit_runbooks.md` | cross_cutting | Monitoring, Audit-Logs, Runbooks, SLOs |
| `05_integration_stabilization_contract.md` | cross_cutting | Integrationsstabilisierung fuer breite E2E-/Systemstories, Manifest, Budget, Stability-Gate, kontrollierte Cross-Scope-Arbeit |
| `06_truth_boundary_and_concept_code_contract_checker.md` | cross_cutting | Harte Wahrheitsgrenze DB vs. Exportdatei und Concept-to-Code-Contract-Checker |
| `07_komponentenarchitektur_und_architekturkonformanz.md` | cross_cutting | Normativer Komponentenschnitt, Blutgruppen, Importgrenzen und deterministische Architektur-Konformanz |
| `10_runtime_deployment_speicher.md` | cross_cutting | Laufzeitkomponenten, Verzeichnisstruktur, Persistenz, Locking |
| `11_llm_provider_browser_pools_prompt_execution.md` | cross_cutting | Pool-Abstraktion, Modellzuordnung, Request/Response, Retry, JSON-Enforcement |
| `12_github_integration_repo_operationen.md` | cross_cutting | GitHub API, Project Board, Branching, Worktree, Merge, Fehlerbehandlung |
| `13_retrieval_vektordb_wissenszugriff.md` | cross_cutting | Weaviate, Chunking, Embedding, Similarity, zweistufiger Abgleich |
| `15_security_secrets_identity_zugriffsmodell.md` | cross_cutting | Secrets, Rollenidentitaeten, Berechtigungsmodell, Audit |
| `17_fachliches_datenmodell_ownership.md` | cross_cutting | Fachliche Entitaeten, Aggregat-Grenzen, Owner-Komponenten, Persistenzmodell-Tags |
| `18_relationales_abbildungsmodell_postgres.md` | cross_cutting | Tabellenfamilien, Pflicht- und optionale Spalten, Single-Writer, Reset-Closure |

### Boundary-Module (schema_version 2)

Ab `concept/formal-spec/architecture-conformance/entities.md` schema_version 2
sind nicht-fachliche Module als `boundary_modules` neben den `component_groups`
modelliert. Es gibt 14 Boundary-Module in 6 Arten
(`boundary_module_kinds`): `entry_boundary`, `adapter_boundary`,
`config_foundation`, `shared_foundation`, `infrastructure_io`,
`infrastructure_driver`. Die normative Quelle ist die Formalspezifikation;
FK-07 beschreibt die Importregeln und Blutgruppen-Semantik.

## 2. BC: pipeline-framework

| Dokument | BC/Domain | Inhalt |
|----------|-----------|--------|
| `20_workflow_engine_state_machine.md` | pipeline-framework | State Machine, Phasen, Feedback-Loop, Eskalation, Recovery, Scheduling |
| `36_compaction_resilience_prompt_persistence.md` | pipeline-framework | Compaction-Schutz, Resume-Kapsel, Prompt-Persistenz fuer Sub-Agenten |
| `39_phase_state_persistenz.md` | pipeline-framework | Vierschichtiges State-Modell, PhaseEnvelope, phase-state-projection, PhasePayload (discriminated union), PhaseMemory (carry-forward), AttemptRecord (Outcome + FailureCause), PauseReason-Enum, Lese-/Schreibprotokoll |
| `45_phase_runner_cli.md` | pipeline-framework | Phase Runner Service (Service-API-Eintrittspunkt `POST /phases/{phase}/start`), Phasen-Dispatch, Phase-Transition-Enforcement (Graph + Status + semantische Preconditions), Orchestrator-Reaktionstabelle; Recovery-CLI als Spezialfall (§45.4) |

## 3. BC: verify-system

`verify-system` ist ein **Capability-Bounded-Context**, kein Phase-Owner. Die Capability `VerifySystem` wird sowohl von `ExplorationPhase` (Exit-Gate, FK-23 §23.5) als auch von `ImplementationPhase` (QA-Subflow, FK-27) aufgerufen. Eine eigenstaendige Top-Phase `verify` existiert nicht — Output-QA ist interner Subflow innerhalb der Implementation-Phase. Siehe `concept/_meta/bc-cut-decisions.md` "Verify als Capability (Variante Y)".

| Dokument | BC/Domain | Inhalt |
|----------|-----------|--------|
| `27_verify_pipeline_closure_orchestration.md` | verify-system | QA-Subflow innerhalb Implementation-Phase: atomarer QA-Zyklus, 4-Schichten-QA (Layer 1 Deterministisch, Layer 2 LLM, Layer 3 Adversarial, Layer 4 Policy), Artefakt-Invalidierung. Capability-Charakter: aus `ExplorationPhase` und `ImplementationPhase` aufgerufen |
| `28_evidence_assembly_review_vorbereitung.md` | verify-system | Evidence Assembly, Import-Resolver, Autoritaetsklassen, Request-DSL, Preflight-Turn, BundleManifest |
| `32_dokumententreue_conformance_service.md` | verify-system | 4 Pruefebenen, Referenzdokumente, JSON-Schema, Trigger |
| `33_deterministische_checks_stage_registry_policy_engine.md` | verify-system | Stage-Registry, Check-Typen, Trust-Klassen, Aggregation |
| `34_llm_bewertungen_adversarial_testing_runtime.md` | verify-system | LLM-Evaluator, 12 QA-Checks, Adversarial-Sandbox, Sparring |
| `37_verify_context_und_qa_bundle.md` | verify-system | VerifyContext (POST_IMPLEMENTATION/POST_REMEDIATION) als Subflow-internes Diskriminator-Feld auf `ImplementationPayload`, Context Sufficiency Builder, Section-aware Bundle-Packing, Vertragsprofil integration_stabilization, HARD-BLOCKER fuer fehlende LLM-Reviews |
| `38_verify_feedback_und_doctreue_schleife.md` | verify-system | QA-Subflow-Feedback-Mechanismus, Maengelliste, Subflow-interner Remediation-Loop / Max-Rounds-Eskalation, Mandatory-Target-Rueckkopplung, Umsetzungstreue (Ebene 3), Rueckkopplungstreue (Ebene 4) |
| `46_import_resolver.md` | verify-system | Sprachspezifische Import-Extraktion (Python, TypeScript, Java) fuer Stufe 2 der Evidence Assembly, Confidence-Labels, Spring-Heuristiken, Barrel-Aufloesung |
| `47_request_dsl_und_preflight_turn.md` | verify-system | 7 Request-Typen (NEED_FILE, NEED_SCHEMA, ...), RequestResolver, Mehrdeutigkeitsregel, Preflight-Turn-Architektur, `review-preflight.md`-Template |
| `48_adversarial_testing_runtime.md` | verify-system | Adversarial Agent (Schicht 3 des QA-Subflows) mit Sandbox, Sparring-Protokoll, Test-Promotion + Mandatory Adversarial Targets (Motivation, Datenmodell, Gate-Rueckkopplung) |

## 4. BC: story-lifecycle

| Dokument | BC/Domain | Inhalt |
|----------|-----------|--------|
| `21_story_creation_pipeline.md` | story-lifecycle | Story-Erstellung, VektorDB-Abgleich, Feldbelegung, fachliche Labels, Repo-Affinitaet, Freigabe |
| `24_story_type_mode_terminalitaet.md` | story-lifecycle | Kanonische Story Types, Mode-vs-Typ-Vertrag, Exploration als Vorzustand, terminale Abschlussregeln |
| `53_story_reset_service_recovery_flow.md` | story-lifecycle | Vollstaendiger Story-Reset, Purge-Reihenfolge, Worktree-/Branch-Behandlung, Endzustand |
| `54_story_split_service_scope_explosion.md` | story-lifecycle | Scope-Explosion, Story-Split, Cancelled-Pfad, Nachfolger-Stories, Dependency-Rebinding |
| `56_ai_augmented_mode_and_story_execution_separation.md` | story-lifecycle | Betriebsmodi, explizite Run-Bindung, freier AI-Augmented-Modus vs. Story-Execution-Regime |
| `58_story_exit_human_takeover_handoff.md` | story-lifecycle | Leichtgewichtiger offizieller Exit aus Story-Execution in menschlich gefuehrten AI-Augmented-Modus bei grossen Loesungsvorschlagsfaellen |
| `59_story_contract_axes_and_combination_matrix.md` | story-lifecycle | Konsolidierte Vertragsachsen, gueltige/ungueltige Kombinationen, Trennung von Story-Vertrag, Laufzeitableitung und Ergebnisachsen |

## 5. BC: governance-and-guards

| Dokument | BC/Domain | Inhalt |
|----------|-----------|--------|
| `22_setup_preflight_worktree_guard_activation.md` | governance-and-guards | Preflight-Gates, Multi-Repo-Worktrees (Participating Repos), Context, Guard-Aktivierung (4 Guards) |
| `30_hook_adapter_guard_enforcement.md` | governance-and-guards | Harness-Hooks (Claude Code, Codex; harness-spezifisch via Adapter, FK-76 §76.4), Registrierung, Event-Normalisierung |
| `31_branch_guard_orchestrator_guard_artefaktschutz.md` | governance-and-guards | Regelssaetze, Pfadklassifikation, opake Fehlercodes, Prompt-Integrity-Guard |
| `35_integrity_gate_governance_beobachtung_eskalation.md` | governance-and-guards | 9 Dimensionen, Anomalie-Sensorik, Incident-Kandidaten, Massnahmen |
| `42_ccag_tool_governance_permission_runtime.md` | governance-and-guards | Regelmodell, Persistenz, Auswertung, LLM-Generierung |
| `55_principal_capability_model_story_scope_enforcement.md` | governance-and-guards | Principals, Capability-Profile, storybezogene Pfad- und Operationsklassen, Freeze-Modell, offizielle Servicepfade |

## 6. BC: exploration-and-design

| Dokument | BC/Domain | Inhalt |
|----------|-----------|--------|
| `23_modusermittlung_exploration_change_frame.md` | exploration-and-design | 6-Kriterien-Routing, Entwurfsartefakt, Freeze, Dokumententreue |
| `25_mandatsgrenzen_feindesign_autonomie.md` | exploration-and-design | Mandatsprinzip, 4 Eskalationsklassen, Feindesign-Subprozess (Multi-LLM), Scope-Explosion-Erkennung, Tragweiten-Vergleich |

## 7. BC: implementation-phase

| Dokument | BC/Domain | Inhalt |
|----------|-----------|--------|
| `26_implementation_runtime_worker_loop.md` | implementation-phase | Inkrement-Loop, Worker-Manifest, Handover-Paket |
| `49_worker_health_monitor.md` | implementation-phase | Worker-Health-Monitor: Scoring-Engine (PostToolUse), Interventions-Gate (PreToolUse), LLM-Assessment-Sidecar, Hook-Commit-Failure-Klassifikation, Persistenz-Artefakte, Konfiguration |

## 8. BC: story-closure

| Dokument | BC/Domain | Inhalt |
|----------|-----------|--------|
| `29_closure_sequence.md` | story-closure | Closure-Phase mit Substates, Finding-Resolution-Gate, Postflight-Gates, Execution Report, Guard-Deaktivierung |

## 9. BC: artifacts

| Dokument | BC/Domain | Inhalt |
|----------|-----------|--------|
| `71_artefakt_envelope_und_stage_registry.md` | artifacts | Artefaktklassen + Ownership, Envelope-Schema mit LLM-Status-Mapping, Producer-Registry; Stage-Registry und Lock-Record-Mechanismus: siehe FK-33 / FK-31 |

## 10. BC: telemetry-and-events

| Dokument | BC/Domain | Inhalt |
|----------|-----------|--------|
| `68_telemetrie_eventing_workflow_metriken.md` | telemetry-and-events | Event-Modell, JSONL-Schema, Workflow-Metriken, Telemetry-Hooks, EventTypeId-Catalog |
| `69_qa_telemetrie_aggregation_dashboard.md` | telemetry-and-events | QA- und Failure-Corpus-Read-Models, Read-Model-Projektionen, Verdichtung |

## 11. BC: prompt-runtime

| Dokument | BC/Domain | Inhalt |
|----------|-----------|--------|
| `44_prompt_bundles_materialization_audit.md` | prompt-runtime | Kanonische Prompt-Bundles, Run-Pinning, Materialisierung, Audit |

## 12. BC: agent-skills

| Dokument | BC/Domain | Inhalt |
|----------|-----------|--------|
| `43_skills_system_task_automation.md` | agent-skills | Skill-Format, Registry, Versionierung, Kontext-Uebergabe |

## 13. BC: installation-and-bootstrap

| Dokument | BC/Domain | Inhalt |
|----------|-----------|--------|
| `50_installer_checkpoint_engine_bootstrap.md` | installation-and-bootstrap | 14 Checkpoints (inkl. ARE-Scope-Validierung), Manifest, Idempotenz, Verifikation |
| `51_upgrade_migration_customization_preservation.md` | installation-and-bootstrap | Upgrade-Strategie, Anpassungsschutz, Schema-Migration |

## 14. BC: failure-corpus

| Dokument | BC/Domain | Inhalt |
|----------|-----------|--------|
| `41_failure_corpus_pattern_promotion_check_factory.md` | failure-corpus | Incident→Pattern→Check, 12 Kategorien, Wirksamkeit |

## 15. BC: execution-planning

| Dokument | BC/Domain | Inhalt |
|----------|-----------|--------|
| `70_story_planung_abhaengigkeiten_ausfuehrungsplanung.md` | execution-planning | Planungsdomaene fuer Abhaengigkeiten, Readiness, Scheduling-Policy, kritischen Pfad und Ausfuehrungswellen |

## 16. BC: requirements-and-scope-coverage

| Dokument | BC/Domain | Inhalt |
|----------|-----------|--------|
| `40_are_integration_anforderungsvollstaendigkeit.md` | requirements-and-scope-coverage | Scope-Zuordnung (Repo→Scope, Modul→Scope), ARE-Andock-Punkte, must_cover, Evidence, ARE-Gate, Fallback |

## 17. BC: kpi-and-dashboard

| Dokument | BC/Domain | Inhalt |
|----------|-----------|--------|
| `60_kpi_katalog_und_architektur.md` | kpi-and-dashboard | KPI-Inventar, Architektur der Erhebungs- und Aggregationsschicht |
| `61_kpi_erhebung_nach_domaenen.md` | kpi-and-dashboard | Domaenenspezifische Erhebung, Quellen, Pflichtfelder |
| `62_kpi_aggregation.md` | kpi-and-dashboard | Aggregations-Regeln, Fact-Tabellen, Idempotenz, Reset-Closure |
| `63_auswertung_und_dashboard.md` | kpi-and-dashboard | Read-only Auswertung, Dashboard-Schnittstellen, Berechtigungsgrenzen |
| `64_control_plane_design_system.md` | kpi-and-dashboard | Normatives Design System fuer Story Cockpit, Dashboard, Sheet, Kanban, Dependency-Graph und Story Inspector |

## 18. BC: project-management

| Dokument | BC/Domain | Inhalt |
|----------|-----------|--------|
| `73_project_management.md` | project-management | Project-Datenmodell, Lifecycle-Uebergaenge, API, Storage; Owner des Story-ID-Praefix-Schemas und der Projekt-Konfiguration |

## 19. BC: harness-integration

| Dokument | BC/Domain | Inhalt |
|----------|-----------|--------|
| `76_agent_harness_integration.md` | harness-integration | Harness-spezifische Anbindung (Claude Code, Codex): Adapter (AT), CLI-Wrapper, Settings-Schemas (`.claude/settings.json`, `.codex/hooks.json`), Subagent-Hybrid-Lifecycle. Harness-neutrale Hook-/Guard-Definition + Enforcement bleiben FK-30 |

## 20. Frontend-Architektur und Foundation-Adapter (cross_cutting)

| Dokument | BC/Domain | Inhalt |
|----------|-----------|--------|
| `72_frontend_architektur.md` | cross_cutting | BC-aligned vertikaler Frontend-Schnitt, App-Shell als R-Klammer, Composer-Sichten, BFF-Topologie, Sichten-Inventar |
| `74_concept_catalog.md` | cross_cutting | Foundation-Adapter zum Markdown-Konzept-Korpus: ConceptRef-Resolver, Cross-Reference-Graph, Backlinks, API fuer Concept-Browser |
| `75_multi_llm_hub.md` | cross_cutting | Foundation-Adapter zum externen Multi-LLM-Hub: Sessions, Backend-Status, Send-Operationen, Hub-Cockpit-Read-Models |

## 21. Referenzanhaenge

| Dokument | BC/Domain | Inhalt |
|----------|-----------|--------|
| `90_schema_katalog.md` | cross_cutting | Alle JSON Schemas mit Felddefinitionen und Beispielen |
| `91_api_event_katalog.md` | cross_cutting | Interne/externe APIs, Eventtypen, Fehlercodes |
| `92_verzeichnis_namenskonventionen.md` | cross_cutting | Repo-Struktur, Run-Verzeichnisse, Naming-Schemata |
| `93_standardwerte_schwellwerte_timeouts.md` | cross_cutting | Defaults, Budgets, Timeouts, Retry-Limits, Cooldowns |

## 22. Frontmatter-Vertrag

Dieses Kapitel ist **normativ** fuer jedes Dokument unter
`concept/technical-design/`. Es ergaenzt FK-00 um den
Frontmatter-Vertrag und nimmt damit `authority_over:
frontmatter-contract`.

### 19.1 Pflichtfelder (alle FK-Dokumente)

```yaml
concept_id:        FK-NN              # Pflicht, Pattern: ^FK-\d{2}$
title:             <string>           # Pflicht
module:            <kebab-case>       # Pflicht, kleinbuchstaben mit Bindestrichen
status:            active | draft     # Pflicht
doc_kind:          core | detail      # Pflicht; "detail" verlangt parent_concept_id
parent_concept_id: FK-NN | <leer>     # Pflichtfeld; bei doc_kind=detail nicht leer
authority_over:                        # Pflicht; Liste mit mindestens einem Eintrag
  - scope: <kebab-case>
defers_to:         [FK-NN, ...]       # Pflichtfeld; Liste (ggf. leer)
supersedes:        [FK-NN, ...]       # Pflichtfeld; Liste (ggf. leer)
superseded_by:     FK-NN | <leer>     # Pflichtfeld; bei Wert reziproker supersedes
tags:              [..., ...]         # Pflicht; mindestens ein Eintrag
```

### 19.2 Klassifikation (mutually exclusive)

Jedes FK-Dokument traegt **genau eine** der folgenden Varianten:

| Variante | Bedingung | Pflichtfelder zusaetzlich |
|----------|-----------|--------------------------|
| **A — formale Spec** | Doc verweist auf eine oder mehrere `formal-spec/`-Dateien | `prose_anchor_policy: strict` und `formal_refs: [formal.x.y, ...]` (non-empty) |
| **B — reine Prosa** | Doc hat keine maschinell pruefbare Spec | `formal_scope: prose-only` |

Beides gleichzeitig oder keins von beidem ist **fail-closed verboten**.

### 19.3 Maschinell erzwungene Regeln

Die folgenden Regeln werden durch `scripts/ci/compile_formal_specs.py`
(Funktionen `audit_concept_doc_classification` und
`audit_formal_prose_links`) erzwungen:

1. Frontmatter parsebar.
2. Genau eine der beiden Varianten 19.2.
3. Jeder Eintrag in `formal_refs` referenziert eine kompilierte
   formale Spec (`doc_id` aus dem `formal-spec/`-Korpus).
4. Reziprozitaet: die referenzierte formale Spec listet das
   FK-Dokument in ihrem `prose_refs`.
5. Bei `prose_anchor_policy: strict` muss jeder `formal_refs`-Eintrag
   im Body als `<!-- PROSE-FORMAL: ... -->` Anker auftauchen.

### 19.4 Schema-Detail-Regeln

Die folgenden Regeln werden vom Frontmatter-Lint
(`scripts/ci/check_concept_frontmatter.py`) deterministisch erzwungen.
Severity ist **immer Error** — Warnings sind unzulaessig, weil sie in
der Praxis untergehen. Ein nicht-fehlerfreier Stand ist
Handlungsauftrag, kein Hintergrundrauschen.

| Regel | Bedeutung |
|-------|-----------|
| `concept_id` Pattern | `^FK-\d{2}$` (technical-design) oder `^DK-\d{2}$` (domain-design) |
| `concept_id` Eindeutigkeit | jede ID darf hoechstens einmal vorkommen (ueber alle Layer) |
| `parent_concept_id` Target | wenn gesetzt: muss existierendes `FK-` oder `DK-` sein |
| `parent_concept_id` Pflicht bei `doc_kind: detail` | Detail-Dokumente brauchen einen Eltern-Eintrag |
| `defers_to` Targets | jeder Eintrag (string oder dict.target) muss existieren |
| `supersedes` Form | string oder `{target, scope, reason}`; Eintrag mit `scope` ist Teil-Supersession |
| `superseded_by` Reciprocity | nur fuer **vollstaendige** Supersession (Eintrag ohne `scope`): das Ziel-Doc muss `superseded_by` zurueckzeigen |
| Authority-Graph | `parent_concept_id` + `defers_to` zusammen muessen zyklenfrei sein |
| Authority-Disjunktheit | kein `authority_over.scope` darf von zwei Konzepten gehalten werden, ausser sie sind durch Voll-Supersession verbunden |
| Authority-Typkompatibilitaet | `defers_to` und `parent_concept_id` duerfen nicht auf einen Index- oder Anhang-Doc zeigen; `supersedes`/`superseded_by` muessen gleiche `doc_kind`-Familie haben |
| Index-Vollstaendigkeit | jede Datei in `concept/technical-design/*.md` muss in §1-§18 dieses Index referenziert sein, und umgekehrt |
| Body-Referenz-Existenz | jede `FK-NN`/`DK-NN`-Erwaehnung im Doc-Body muss zu einem existierenden Konzept passen |
| `formal_refs` ↔ Body-Anker | bei `prose_anchor_policy: strict`: jeder formal_refs-Eintrag im Body als `<!-- PROSE-FORMAL: ... -->` Anker (lokale Pruefung vor `audit_formal_prose_links`) |

### 19.5 Tag-Korpus

Kanonische Quelle: `concept/technical-design/_meta/tag-corpus.txt`
(eine Tag pro Zeile, alphabetisch sortiert).

**Erweiterung:** ein neuer Tag wird durch eine Zeile in dieser Datei
freigeschaltet. Es gibt keinen Warning-Pfad — entweder der Tag ist
freigegeben oder der Lint blockiert. Tag-Pflege ist eine
Nebenverantwortung von FK-00.

### 19.6 Modul-Registry

Kanonische Quelle: `concept/technical-design/_meta/module-registry.yaml`.

**Bedeutung:** Jedes `module:` im Frontmatter muss in dieser Registry
eingetragen sein. Die Registry ist die Bruecke zwischen Konzept-Welt
und Komponentenarchitektur (FK-07 §65.4 fuehrt den normativen
Top-Level-Schnitt). Pro Eintrag kann optional ein `component_family`
gefuehrt werden, der gegen die FK-07-Familien abgleicht.

### 19.7 Bounded-Context-Felder (optional, scharfgeschaltet via Domain-Registry)

Diese Felder ergaenzen den Stamm aus §19.1, sobald die Domain-Registry
(siehe §19.10) Eintraege fuehrt. Bis dahin sind die Felder zulaessig,
aber nicht maschinell erzwungen.

```yaml
domain:            <kebab-case>          # Pflichtfeld, sobald Domain-Registry aktiv ist
applies_policies:  [policy.x, ...]       # Optional, gegen Policy-Registry §19.9
contract_state:    active | compatible | deprecating | breaking
                                         # Pflicht NUR in Contract-Docs (siehe §19.8)
migration_ack:     <new-contract-id>     # Pflicht im Consumer-Doc, wenn ein referenzierter
                                         # Contract auf contract_state=breaking steht
```

### 19.8 Surface (Vertrag vs. Innenleben)

`surface` ist **abgeleitet, nicht manuell**. Die Lint-Logik bestimmt
den Wert nach folgenden Regeln:

| Bedingung | abgeleitetes `surface` |
|-----------|------------------------|
| Doc steht in `_meta/domain-registry.yaml` als `contract_doc` einer Domaene UND hat mindestens einen `formal_ref` | `contract` |
| sonst | `internal` |

Ein Contract-Doc darf mehrere benannte Vertrags-Sektionen tragen, die
ueber `<!-- CONTRACT-ANCHOR: <slug> -->` im Body markiert werden.
Cross-Domain-Referenzen sollen auf solche Anchors zielen, nicht auf
Doc-IDs allein. Bis Lint L18 scharf ist, gilt diese Regel als Konvention.

### 19.9 Policy-Registry

Kanonische Quelle: `concept/technical-design/_meta/policy-registry.yaml`.

**Bedeutung:** Querschnittskonzepte (Trust Boundaries, Severity-Semantik,
Truth-Boundary-Contract) werden NICHT als Domaene gefuehrt — das waere
eine "Foundation-Sinkhole"-Antipattern. Stattdessen sind sie Policies,
die ein Doc als orthogonalen Constraint via `applies_policies`
referenziert. Authority-Graph (`defers_to`) bleibt damit rein fachlich,
keine Sterntopologie.

### 19.10 Domain-Registry

Kanonische Quelle: `concept/technical-design/_meta/domain-registry.yaml`.

**Bedeutung:** Bounded-Context-Schnitt von AK3. Pro Eintrag:
`id`, `display_name`, `contract_docs: [FK-NN, ...]`,
`member_docs: [FK-NN, ...]`. Solange diese Datei leer ist, laufen die
Bounded-Context-Lints L17-L20 als No-Ops. Sobald Eintraege bestehen,
werden sie scharfgeschaltet — fail-closed wie alle anderen Lints.

### 19.11 Glossar (im Contract-Doc)

Glossare leben **im jeweiligen Contract-Doc** der Domaene als
Frontmatter-Block oder dedizierte `## Glossar`-Sektion mit folgender
Form:

```yaml
glossary:
  exported_terms:
    - id: <Term>
      definition: <string>
      values: [optional, fuer Enums]
      see_also:
        - term: <Other-Term>
          domain: <other-domain-id>      # explizit, fuer deterministische FK-Aufloesung
  internal_terms:
    - id: <implementation-detail>
      reason: <warum nicht exportiert>
```

**Ownership:** Der Domain-Owner pflegt den Glossar-Block ihres
Contract-Docs allein. Niemand ausserhalb darf darin schreiben.
Dezentral, in-Doc, mit referenzieller Integritaet ueber den Lint.

**Aggregierte Sicht:** Lint generiert beim Lauf zwei Read-only-
Artefakte als "ein Blick"-Ansicht:

- `concept/technical-design/_meta/glossary-overview.md` — alphabetisch
  alle exportierten Terms, mit Domain-Tag und Cross-Refs als Hyperlinks.
- `concept/technical-design/_meta/glossary-reverse-index.md` —
  pro Term: wer referenziert ihn (Reverse-Lookup).

Beide Artefakte sind regeneriert; **niemals manuell editieren**.

### 19.12 Lints L17-L20 (Bounded-Context-Layer)

Diese Lints sind aktiv, sobald die Domain-Registry Eintraege fuehrt
(siehe §19.10). Sie ergaenzen §19.4:

| Lint | Bedeutung |
|------|-----------|
| L17 | `domain` Pflicht (oder `cross_cutting: true`, siehe §19.13); Wert muss in Domain-Registry sein. `applies_policies` Eintraege muessen in Policy-Registry sein. `cross_cutting: true` und `domain` schliessen sich gegenseitig aus |
| L18 | Cross-Domain-Referenzen (Body oder `defers_to`) duerfen nur auf `surface: contract`-Docs zeigen. Cross-cutting Docs (§19.13) sind sowohl als Source als auch als Target von dieser Regel ausgenommen |
| L19 | Glossar-FK-Integritaet: jeder `see_also.term` + `domain` ist ueber alle Glossare deterministisch aufloesbar; kein Term darf gleichzeitig `exported` und `internal` sein |
| L20 | Implicit-Leakage: kein `internal_term` aus Domaene X mit normativem Modalverb (`muss`, `ist`, `darf nur`, `Single Source of Truth`) in Doc anderer Domaene |

### 19.13 Cross-Cutting-Marker (`cross_cutting: true`)

Die User-BC-Vorgabe (`bounded-contexts.yaml §foundation_principles`)
modelliert Foundation, Adapter und querschnittliche Referenzkataloge
explizit **nicht** als Bounded Context. Solche Docs haben keine
Sprachgrenze und keinen Owner-BC, sondern sind universell lesbare
Grundlage fuer alle BCs.

Damit L17 ihre fail-closed-Pflicht zur Domain-Zuordnung trotzdem
einhalten kann, fuehrt das Frontmatter den Marker `cross_cutting: true`:

```yaml
cross_cutting: true   # statt `domain: <id>`
```

**Semantik:**

- `cross_cutting: true` befreit den Doc von der `domain`-Pflicht (L17).
- Der Doc wird in keiner Domain-Registry-Liste gefuehrt.
- Andere Docs duerfen ohne Einschraenkung auf cross-cutting-Docs
  zeigen (L18 ist exempt).
- Cross-cutting-Docs sind selbst von L18 als Source ausgenommen —
  sie duerfen frei in alle Domaenen referenzieren.
- L19/L20 (Glossar-Integritaet, Implicit-Leakage) gelten nicht fuer
  cross-cutting-Docs, weil sie keinen Domain-Owner haben.

**Wann cross-cutting?** Foundation- und Adapter-Konzepte (z.B.
Architekturprinzipien, GitHub-/VektorDB-Adapter, Runtime-Rahmen),
Operations-/Runbook-Referenzen, Vertragsachsen-Kataloge,
querschnittliche Referenzanhaenge (Schema-, API-Event-,
Naming-Konventionen-, Defaults-Kataloge) und der Index selbst.

**Wann nicht cross-cutting?** Sobald ein Doc fachliches BC-Vokabular
definiert, BC-spezifische Invarianten beschreibt oder Eigentum einer
Domain ist. Im Zweifel: Domaene zuordnen, nicht cross-cutting.
