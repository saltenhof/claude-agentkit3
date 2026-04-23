---
concept_id: FK-00
title: Technisches Feinkonzept
module: meta
status: active
doc_kind: core
parent_concept_id:
authority_over:
  - scope: technical-overview
defers_to: []
supersedes: []
superseded_by:
tags: [feinkonzept, index, dokumentenstruktur, architekturrahmen]
formal_scope: prose-only
---

# AgentKit — Technisches Feinkonzept

## Dokumentenübersicht

Dieses Feinkonzept detailliert das fachliche Domänenkonzept
(`agentkit-domain-concept.md`) so weit technisch aus, dass ein
Entwickler sofort Code schreiben kann. Es ist in thematische
Kapitel-Dokumente und Referenzanhänge gegliedert.

Grundlage für die Priorisierung und Vollständigkeitsprüfung ist die
Fachkonzept-Checkliste (`fachkonzept-checkliste.md`) mit 568 atomaren
Anforderungen.

---

## 1. Grundlagen und Architekturrahmen

| Dokument | Inhalt |
|----------|--------|
| `01_systemkontext_und_architekturprinzipien.md` | Zielbild, Systemgrenzen, Architekturprinzipien, Fail-Closed, Trust Boundaries |
| `02_domaenenmodell_zustaende_artefakte.md` | Kanonische Begriffe, Zustandsmodelle, Identifikatoren, Artefaktklassen |
| `03_konfigurationsmodell_schemas_versionierung.md` | Config-Hierarchie, Dateiformate, Defaults, Validierung |

## 2. Plattform, Infrastruktur und externe Anbindungen

| Dokument | Inhalt |
|----------|--------|
| `10_runtime_deployment_speicher.md` | Laufzeitkomponenten, Verzeichnisstruktur, Persistenz, Locking |
| `11_llm_provider_browser_pools_prompt_execution.md` | Pool-Abstraktion, Modellzuordnung, Request/Response, Retry, JSON-Enforcement |
| `12_github_integration_repo_operationen.md` | GitHub API, Project Board, Branching, Worktree, Merge, Fehlerbehandlung |
| `13_retrieval_vektordb_wissenszugriff.md` | Weaviate, Chunking, Embedding, Similarity, zweistufiger Abgleich |
| `14_telemetrie_eventing_workflow_metriken.md` | Event-Modell, JSONL-Schema, Metriken, Experiment-Tags |
| `15_security_secrets_identity_zugriffsmodell.md` | Secrets, Rollenidentitäten, Berechtigungsmodell, Audit |

## 3. Orchestrierung und Pipeline

| Dokument | Inhalt |
|----------|--------|
| `20_workflow_engine_state_machine.md` | State Machine, Phasen, Übergänge, Retry, Recovery |
| `21_story_creation_pipeline.md` | Story-Erstellung, VektorDB-Abgleich, Feldbelegung, fachliche Labels, Repo-Affinität, Freigabe |
| `22_setup_preflight_worktree_guard_activation.md` | Preflight-Gates, Multi-Repo-Worktrees (Participating Repos), Context, Guard-Aktivierung (4 Guards) |
| `23_modusermittlung_exploration_change_frame.md` | 6-Kriterien-Routing, Entwurfsartefakt, Freeze, Dokumententreue |
| `24_story_type_mode_terminalitaet.md` | Kanonische Story Types, Mode-vs-Typ-Vertrag, Exploration als Vorzustand, terminale Abschlussregeln |
| `25_mandatsgrenzen_feindesign_autonomie.md` | Mandatsprinzip, 4 Eskalationsklassen, Feindesign-Subprozess (Multi-LLM), Scope-Explosion-Erkennung, Tragweiten-Vergleich |
| `26_implementation_runtime_worker_loop.md` | Inkrement-Loop, Drift, Reviews, Handover-Paket |
| `27_verify_pipeline_closure_orchestration.md` | Atomarer QA-Zyklus, 4-Schichten-Verify, Artefakt-Invalidierung, Remediation-Loop (max Runden), Closure-Sequenz, Execution Report, Postflight |
| `28_evidence_assembly_review_vorbereitung.md` | Evidence Assembly, Import-Resolver, Autoritätsklassen, Request-DSL, Preflight-Turn, BundleManifest |

## 4. Governance, Guarding und technische Qualitätssicherung

| Dokument | Inhalt |
|----------|--------|
| `30_hook_adapter_guard_enforcement.md` | Claude-Code-Hooks, Registrierung, Event-Normalisierung |
| `31_branch_guard_orchestrator_guard_artefaktschutz.md` | Regelsätze, Pfadklassifikation, opake Fehlercodes, Prompt-Integrity-Guard |
| `32_dokumententreue_conformance_service.md` | 4 Prüfebenen, Referenzdokumente, JSON-Schema, Trigger |
| `33_deterministische_checks_stage_registry_policy_engine.md` | Stage-Registry, Check-Typen, Trust-Klassen, Aggregation |
| `34_llm_bewertungen_adversarial_testing_runtime.md` | LLM-Evaluator, 12 QA-Checks, Adversarial-Sandbox, Sparring |
| `35_integrity_gate_governance_beobachtung_eskalation.md` | 7 Dimensionen, Anomalie-Sensorik, Incident-Kandidaten, Maßnahmen |
| `64_truth_boundary_and_concept_code_contract_checker.md` | Harte Wahrheitsgrenze DB vs. Exportdatei und Concept-to-Code-Contract-Checker |
| `65_komponentenarchitektur_und_architekturkonformanz.md` | Normativer Komponentenschnitt, Blutgruppen, Importgrenzen und deterministische Architektur-Konformanz |

## 5. Querschnittskomponenten und Lernschleifen

| Dokument | Inhalt |
|----------|--------|
| `40_are_integration_anforderungsvollstaendigkeit.md` | Scope-Zuordnung (Repo→Scope, Modul→Scope), ARE-Andock-Punkte, must_cover, Evidence, ARE-Gate, Fallback |
| `41_failure_corpus_pattern_promotion_check_factory.md` | Incident→Pattern→Check, 12 Kategorien, Wirksamkeit |
| `42_ccag_tool_governance_permission_runtime.md` | Regelmodell, Persistenz, Auswertung, LLM-Generierung |
| `43_skills_system_task_automation.md` | Skill-Format, Registry, Versionierung, Kontext-Übergabe |
| `44_prompt_bundles_materialization_audit.md` | Kanonische Prompt-Bundles, Run-Pinning, Materialisierung, Audit und Drift-Schutz |

## 6. Installation, Upgrade und Betrieb

| Dokument | Inhalt |
|----------|--------|
| `50_installer_checkpoint_engine_bootstrap.md` | 14 Checkpoints (inkl. ARE-Scope-Validierung), Manifest, Idempotenz, Verifikation |
| `51_upgrade_migration_customization_preservation.md` | Upgrade-Strategie, Anpassungsschutz, Schema-Migration |
| `52_betrieb_monitoring_audit_runbooks.md` | Monitoring, Audit-Logs, Runbooks, SLOs |
| `53_story_reset_service_recovery_flow.md` | Vollstaendiger Story-Reset, Purge-Reihenfolge, Worktree-/Branch-Behandlung, Endzustand |
| `54_story_split_service_scope_explosion.md` | Scope-Explosion, Story-Split, Cancelled-Pfad, Nachfolger-Stories, Dependency-Rebinding |
| `55_principal_capability_model_story_scope_enforcement.md` | Principals, Capability-Profile, storybezogene Pfad- und Operationsklassen, Freeze-Modell, offizielle Servicepfade |
| `56_ai_augmented_mode_and_story_execution_separation.md` | Betriebsmodi, explizite Run-Bindung, freier AI-Augmented-Modus vs. Story-Execution-Regime |
| `57_integration_stabilization_contract.md` | Integrationsstabilisierung fuer breite E2E-/Systemstories, Manifest, Budget, Stability-Gate, kontrollierte Cross-Scope-Arbeit |
| `58_story_exit_human_takeover_handoff.md` | Leichtgewichtiger offizieller Exit aus Story-Execution in menschlich gefuehrten AI-Augmented-Modus bei grossen Loesungsvorschlagsfaellen |
| `59_story_contract_axes_and_combination_matrix.md` | Konsolidierte Vertragsachsen, gueltige/ungueltige Kombinationen, Trennung von Story-Vertrag, Laufzeitableitung und Ergebnisachsen |

## 7. Referenzanhänge

| Dokument | Inhalt |
|----------|--------|
| `90_schema_katalog.md` | Alle JSON Schemas mit Felddefinitionen und Beispielen |
| `91_api_event_katalog.md` | Interne/externe APIs, Eventtypen, Fehlercodes |
| `92_verzeichnis_namenskonventionen.md` | Repo-Struktur, Run-Verzeichnisse, Naming-Schemata |
| `93_standardwerte_schwellwerte_timeouts.md` | Defaults, Budgets, Timeouts, Retry-Limits, Cooldowns |
