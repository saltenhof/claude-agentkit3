---
concept_id: FK-91
title: API- und Event-Katalog
module: api-catalog
status: active
doc_kind: core
parent_concept_id:
authority_over:
  - scope: api-catalog
defers_to: []
supersedes: []
superseded_by:
tags: [api, events, cli, hooks, reference]
prose_anchor_policy: strict
formal_refs:
  - formal.installer.commands
  - formal.installer.events
  - formal.deterministic-checks.commands
  - formal.deterministic-checks.events
  - formal.guard-system.commands
  - formal.guard-system.events
  - formal.conformance.commands
  - formal.conformance.events
  - formal.llm-evaluations.commands
  - formal.llm-evaluations.events
  - formal.integrity-gate.commands
  - formal.integrity-gate.events
  - formal.governance-observation.commands
  - formal.governance-observation.events
  - formal.escalation.commands
  - formal.escalation.events
  - formal.setup-preflight.commands
  - formal.setup-preflight.events
  - formal.verify.commands
  - formal.verify.events
  - formal.exploration.commands
  - formal.exploration.events
  - formal.story-creation.commands
  - formal.story-creation.events
  - formal.dependency-rebinding.events
  - formal.story-closure.commands
  - formal.story-closure.events
  - formal.story-workflow.commands
  - formal.story-workflow.events
  - formal.story-split.commands
  - formal.story-split.events
  - formal.story-reset.state-machine
  - formal.story-reset.commands
  - formal.story-reset.events
  - formal.principal-capabilities.commands
  - formal.principal-capabilities.events
  - formal.operating-modes.commands
  - formal.operating-modes.events
  - formal.state-storage.commands
  - formal.state-storage.events
  - formal.telemetry-analytics.commands
  - formal.telemetry-analytics.events
  - formal.integration-stabilization.commands
  - formal.integration-stabilization.events
  - formal.story-exit.commands
  - formal.story-exit.events
  - formal.story-contracts.events
---

# 91 — API- und Event-Katalog

## 91.1 CLI-Befehle (agentkit)

<!-- PROSE-FORMAL: formal.installer.commands, formal.deterministic-checks.commands, formal.guard-system.commands, formal.conformance.commands, formal.llm-evaluations.commands, formal.integrity-gate.commands, formal.governance-observation.commands, formal.escalation.commands, formal.setup-preflight.commands, formal.verify.commands, formal.exploration.commands, formal.story-creation.commands, formal.story-closure.commands, formal.story-workflow.commands, formal.story-split.commands, formal.story-reset.commands, formal.principal-capabilities.commands, formal.operating-modes.commands, formal.state-storage.commands, formal.telemetry-analytics.commands, formal.integration-stabilization.commands, formal.story-exit.commands -->

| Befehl | Kapitel | Beschreibung |
|--------|---------|-------------|
| `agentkit register-project --gh-owner {owner} --gh-repo {repo}` | 50 | Projekt registrieren bzw. idempotent erneut registrieren |
| `agentkit register-project --gh-owner {owner} --gh-repo {repo} --dry-run` | 50 | Checkpoint-Vorschau ohne Mutation |
| `agentkit verify-project` | 50 | Read-only Verifikation des Registrierungszustands |
| `agentkit run-phase {phase}` | 20 | Pipeline-Phase ausführen |
| `agentkit structural` | 33 | Structural Checks ausführen |
| `agentkit policy` | 33 | Policy-Evaluation ausführen |
| `agentkit stages` | 33 | Stage-Registry anzeigen |
| `agentkit status` | 52 | Systemstatus anzeigen |
| `agentkit cleanup --story {story_id}` | 20 | Stale Worktree/Branch/Locks aufräumen |
| `agentkit resume --story {story_id}` | 35 | Pausierte Story fortsetzen |
| `agentkit reset-escalation --story {story_id}` | 35 | Eskalation zurücksetzen |
| `agentkit reset-story --story {story_id}` | 53 | Vollständige korrupt gewordene Umsetzung administrativ zurücksetzen |
| `agentkit split-story --story {story_id}` | 54 | Scope-Explosion kontrolliert in Nachfolger-Stories überführen |
| `agentkit resolve-conflict --story {story_id} --decision {decision}` | 55 | Autoritativen Snapshot-/Normkonflikt offiziell auflösen |
| `agentkit approve-integration-manifest --story {story_id} --manifest {path}` | 57 | Integrations-Scope-Manifest fuer systemische E2E-/Stabilisierungsstory offiziell freigeben |
| `agentkit amend-integration-manifest --story {story_id} --manifest {path}` | 57 | Erweiterung oder Rekonfiguration eines laufenden Integrations-Manifests offiziell anfordern |
| `agentkit exit-story --story {story_id} --reason {reason}` | 58 | Story-Execution offiziell beenden und in Human-Takeover uebergeben |
| `agentkit approve-permission-request --request {request_id}` | 55 | Offenen Permission-Einzelfall als Mensch freigeben, optional als Lease |
| `agentkit reject-permission-request --request {request_id}` | 55 | Offenen Permission-Einzelfall als Mensch ablehnen |
| `agentkit guard-status` | 56 | Aktuellen Betriebsmodus, Run-Bindung und aktives Guard-Regime anzeigen |
| `agentkit override-integrity --story {story_id}` | 35 | Integrity-Gate bewusst overriden |
| `agentkit query-telemetry` | 52 | Telemetrie-Events abfragen |
| `agentkit dashboard [--port {port}]` | 63 | Read-only Dashboard für Runtime- und Analytics-Daten starten |
| `agentkit weekly-review` | 52 | Wöchentlichen Review-Slot anzeigen |
| `agentkit failure-corpus suggest-patterns` | 41 | Pattern-Kandidaten vorschlagen |
| `agentkit failure-corpus review-patterns` | 41 | Patterns reviewen |
| `agentkit failure-corpus review-checks` | 41 | Check-Proposals reviewen |
| `agentkit failure-corpus effectiveness-report` | 41 | Wirksamkeits-Report |
| `agentkit failure-corpus list-checks` | 41 | Aktive Checks anzeigen |
| `agentkit failure-corpus add-incident` | 41 | Incident manuell erfassen |
| `agentkit evidence assemble` | 26 | Evidence-Bundle für Review assemblieren (3-Stufen: Git-Diff, Import-Resolver, Worker-Hints) |

## 91.1a Service-API-Endpunkte (Control Plane)

Diese Endpunkte beschreiben die **normative Zielgrenze** der zentralen
AgentKit-Control-Plane. Die lokale CLI ist aktuell ein Adapterpfad und
kann diese Operationen intern aufrufen; fachlich autoritativ ist der
API-Vertrag.

| Endpoint | Methode | Beschreibung |
|----------|---------|--------------|
| `/v1/story-runs/{run_id}/phases/{phase}/start` | `POST` | Offiziellen Start einer Phase anfordern |
| `/v1/story-runs/{run_id}/phases/{phase}/complete` | `POST` | Erfolgreichen Phasenabschluss melden |
| `/v1/story-runs/{run_id}/phases/{phase}/fail` | `POST` | Fehlerhaften Phasenabschluss melden |
| `/v1/story-runs/{run_id}/closure/complete` | `POST` | Offiziellen Closure-Abschluss anfordern |
| `/v1/project-edge/sync` | `POST` | Lokalen Edge-Bundle-Stand fuer einen Projekt-Client bounded neu abgleichen |
| `/v1/project-edge/operations/{op_id}` | `GET` | Unklare Remote-Lage eines mutierenden Requests ueber `op_id` reconciliieren |
| `/v1/telemetry/events` | `POST` | Kanonisches Telemetrie-Event ingestieren |
| `/v1/stories` | `GET` | Projektgebundene Story-Liste für Web- und Agent-Clients |
| `/v1/stories/{story_id}` | `GET` | Story-Detailansicht mit Status, Laufzeit- und Telemetriebezug |
| `/v1/dashboard/board` | `GET` | Board- oder Listenansicht für die Story-Steuerung |
| `/v1/dashboard/story-metrics` | `GET` | Read-only Story-Metriken aus Runtime- und Analytics-Sicht |

**Normative Regeln:**

1. Jeder mutierende Endpoint ist tenant-scoped und verlangt
   `project_key` explizit oder implizit aus dem authentisierten
   Projektkontext.
2. Die Control Plane exponiert mutierende Endpunkte nur ueber HTTPS;
   Plain-HTTP-Listener sind fachlich unzulaessig.
3. Agents sollen offizielle lokale Wrapper bzw. den offiziellen
   `Project Edge Client` verwenden statt frei formulierte
   `curl`-Kommandos.
4. Jeder mutierende Endpoint muss neben dem zentralen Commit-Resultat
   ein lokales Materialisierungs-Bundle fuer den `Project Edge Client`
   bereitstellen. Dieses Bundle umfasst mindestens `current.json`,
   `session.json`, den `story_execution`-Lock und alle fuer lokale
   Guard-Entscheidungen erforderlichen Zusatzlocks wie
   `qa_artifact_write`.
5. Jeder mutierende Endpoint muss `op_id` als Idempotenzschluessel
   akzeptieren; Wiederholungen mit derselben `op_id` duerfen keine
   zweite Mutation erzeugen.
6. Die API erzeugt keine zweite Befehls- oder Event-Semantik neben der
   CLI; sie ist die Zielgrenze, die CLI ist nur ein aktueller Adapter.
7. Jede HTTP-Antwort der Control Plane traegt eine stabile
   `correlation_id`; bei HTTP-Transport wird sie ueber
   `X-Correlation-Id` propagiert oder, falls nicht vorhanden, von der
   Control Plane erzeugt.
8. Fehlerantworten folgen einem stabilen Vertrag mit mindestens
   `error_code`, `error` und `correlation_id`; optionale strukturierte
   `detail`-Daten duerfen diesen Vertrag nur erweitern, nicht ersetzen.

## 91.2 Telemetrie-Event-Typen

<!-- PROSE-FORMAL: formal.installer.events, formal.deterministic-checks.events, formal.guard-system.events, formal.conformance.events, formal.llm-evaluations.events, formal.integrity-gate.events, formal.governance-observation.events, formal.escalation.events, formal.setup-preflight.events, formal.verify.events, formal.exploration.events, formal.story-creation.events, formal.dependency-rebinding.events, formal.story-closure.events, formal.story-workflow.events, formal.story-split.events, formal.story-reset.state-machine, formal.story-reset.events, formal.principal-capabilities.events, formal.operating-modes.events, formal.state-storage.events, formal.telemetry-analytics.events, formal.integration-stabilization.events, formal.story-exit.events, formal.story-contracts.events -->

| Event-Typ | Kapitel | Quelle | Beschreibung |
|-----------|---------|--------|-------------|
| `project_registration_requested` | 50 | CLI | Projektregistrierung explizit angefordert |
| `project_registration_started` | 50 | Installer | Checkpoint-Engine für Registrierung gestartet |
| `project_registration_completed` | 50 | Installer | Registrierung und Bundle-Bindung erfolgreich abgeschlossen |
| `project_registration_verified` | 50 | Installer | Read-only Verifikation abgeschlossen |
| `project_registration_dry_run_completed` | 50 | Installer | Dry-Run ohne Mutation abgeschlossen |
| `bundle_binding_rebound` | 51 | Installer | Bundle-Bindung im Upgrade-/Rebind-Pfad neu gesetzt |
| `project_customization_preserved` | 51 | Installer | Projektspezifische Anpassungen aktiv erhalten |
| `project_registration_failed` | 50 | Installer | Registrierung oder Rebind abgebrochen/gescheitert |
| `agent_start` | 14 | Hook (PostToolUse Agent) | Worker/Adversarial Agent gestartet |
| `agent_end` | 14 | Hook (PostToolUse Agent) | Agent regulär beendet |
| `increment_commit` | 14 | Hook (PreToolUse Bash) | Worker committet Inkrement |
| `drift_check` | 14 | Hook (PreToolUse Bash) | Drift-Prüfung Ergebnis |
| `review_request` | 14 | Hook (PreToolUse Pool-Send) | Worker fordert Review an |
| `review_response` | 14 | Hook (PostToolUse Pool-Send) | Review-Antwort empfangen |
| `review_compliant` | 14 | Review-Guard (PostToolUse) | Review über freigegebenes Template |
| `llm_call` | 14 | LLM-Evaluator / Hook | LLM über Pool aufgerufen |
| `conformance_assessment_started` | 32 | ConformanceService | Dokumententreue-Bewertung begonnen |
| `conformance_level_evaluated` | 32 | ConformanceService | Dokumententreue-Ebene bewertet |
| `conformance_assessment_completed` | 32 | ConformanceService | Dokumententreue-Bewertung abgeschlossen |
| `llm_evaluation_started` | 34 | Verify Layer 2/3 Runner | Layer-2- oder Layer-3-Bewertung gestartet |
| `llm_evaluation_completed` | 34 | Verify Layer 2/3 Runner | Layer-2- oder Layer-3-Bewertung abgeschlossen |
| `adversarial_start` | 14 | Hook (PostToolUse Agent) | Adversarial Agent gestartet |
| `adversarial_sparring` | 14 | Hook (PostToolUse Pool-Send) | Sparring-LLM aufgerufen |
| `adversarial_test_created` | 14 | Hook (PostToolUse Write) | Neuer Test in Sandbox |
| `adversarial_test_executed` | 14 | Hook (PostToolUse Bash) | Test ausgeführt |
| `adversarial_end` | 14 | Hook (PostToolUse Agent) | Adversarial Agent beendet |
| `integrity_violation` | 14 | Guard-Hooks (PreToolUse) | Guard hat blockiert |
| `web_call` | 14 | Budget-Hook (PostToolUse) | Web-Aufruf |
| `governance_signal` | 35 | Hooks (normalisiert) | Governance-Anomalie-Signal |
| `governance_adjudication` | 35 | Governance-Beobachtung | LLM-Klassifikation eines Incidents |
| `governance_incident_opened` | 35 | Governance-Beobachtung | Incident-Kandidat eröffnet |
| `governance_measure_applied` | 35 | Governance-Beobachtung | Pause oder Eskalation deterministisch gesetzt |
| `run_paused` | 35 | Eskalationslogik / CLI | Story-Run auf `PAUSED` gesetzt |
| `run_escalated` | 35 | Eskalationslogik / CLI | Story-Run auf `ESCALATED` gesetzt |
| `run_resumed` | 35 | CLI | Pausierter Run desselben `run_id` fortgesetzt |
| `run_reopened` | 35 | CLI | Eskalierter Fall über neuen `run_id` wieder geöffnet |
| `run_redirected` | 35 | CLI | Eskalierter oder pausierter Fall in offiziellen Folgeprozess umgeleitet |
| `integrity_gate_started` | 35 | Phase Runner (Closure) | Integrity-Gate gestartet |
| `integrity_gate_result` | 35 | Phase Runner (Closure) | Integrity-Gate PASS/FAIL |
| `integrity_override` | 35 | CLI (Mensch) | Manueller Override |
| `story_reset_requested` | 53 | CLI / StoryResetService | Menschlicher Reset-Vorgang angefordert |
| `story_reset_started` | 53 | StoryResetService | Reset-Fencing und Purge begonnen |
| `story_reset_completed` | 53 | StoryResetService | Reset vollständig abgeschlossen, Story in sauberem Neustartzustand |
| `story_reset_failed` | 53 | StoryResetService | Reset unvollständig gescheitert, Story bleibt administrativ blockiert |
| `story_split_requested` | 54 | CLI / StorySplitService | Menschlicher Story-Split angefordert |
| `story_split_started` | 54 | StorySplitService | Story gefenced, Split-Plan-Ausführung begonnen |
| `story_split_completed` | 54 | StorySplitService | Ausgangs-Story beendet, Nachfolger-Stories angelegt |
| `story_split_failed` | 54 | StorySplitService | Split unvollständig gescheitert, Story bleibt administrativ blockiert |
| `capability_context_resolved` | 55 | GuardSystem / Capability Layer | Principal-, Pfad-, Operations- und Story-Scope-Kontext aufgeloest |
| `capability_allowed` | 55 | GuardSystem / Capability Layer | Tool-Aufruf nach harter Capability-Prüfung erlaubt |
| `capability_denied` | 55 | GuardSystem / Capability Layer | Tool-Aufruf nach harter Capability-Prüfung blockiert |
| `unauthorized_mutation_detected` | 55 | GuardSystem / Integrity Layer | Erfolgreiche oder nachtraeglich festgestellte unzulaessige Mutation erkannt |
| `conflict_freeze_entered` | 55 | GuardSystem / Eskalationslogik | Storybezogener Freeze fuer HARD-STOP-/Normkonflikt aktiviert |
| `conflict_freeze_released` | 55 | offizieller Resolution-Pfad | Freeze offiziell aufgehoben |
| `conflict_resolution_requested` | 55 | CLI / Admin-Service | Offizielle Konfliktaufloesung angefordert |
| `conflict_resolution_applied` | 55 | CLI / Admin-Service | Konfliktaufloesung auditiert angewendet |
| `conflict_resolution_rejected` | 55 | CLI / Admin-Service | Konfliktaufloesung abgelehnt oder unzulaessig |
| `permission_request_opened` | 55 | GuardSystem / CCAG | Unbekannte Freigabe als auditierbarer Einzelfall geoeffnet |
| `permission_request_approved` | 55 | CLI (Mensch) | Mensch hat einen Permission-Einzelfall freigegeben |
| `permission_request_rejected` | 55 | CLI (Mensch) | Mensch hat einen Permission-Einzelfall abgelehnt |
| `permission_request_expired` | 55 | GuardSystem / CLI | Offener Permission-Einzelfall ist lazy ohne Antwort in `DENIED` ausgelaufen |
| `permission_lease_issued` | 55 | CLI (Mensch) | Befristete story-/run-scoped Permission-Lease wurde ausgestellt |
| `external_permission_interference_detected` | 55 | Telemetrie / Supervisor / manueller Audit-Pfad | Hostseitiges Permission-/TTY-Verhalten stoert den deterministischen Story-Run |
| `operating_mode_resolved` | 56 | GuardSystem | Aktueller Betriebsmodus fuer die Session wurde bestimmt |
| `interactive_mode_assumed` | 56 | GuardSystem | Session arbeitet frei ausserhalb eines Story-Runs |
| `session_run_binding_created` | 56 | Setup / Runtime | Session wurde explizit an einen Story-Run gebunden |
| `session_run_binding_removed` | 56 | Closure / Cleanup / Reset / Split | Session-Bindung an einen Story-Run geloest |
| `story_execution_regime_activated` | 56 | Setup / Runtime | Storygebundene Guards und Workflow-Pflichten sind aktiv |
| `story_execution_regime_deactivated` | 56 | Closure / Cleanup / Reset / Split | Session faellt auf freien AI-Augmented-Modus zurueck |
| `binding_invalid_detected` | 56 | GuardSystem | Inkonsistenter Lock-/Bindungszustand wurde als blockierende inkonsistente Story-Bindung erkannt |
| `local_edge_bundle_materialized` | 56 | offizieller lokaler Project Edge Client | Lokales Edge-Bundle fuer Hooks und Guards atomar publiziert |
| `edge_operation_reconciled` | 56 | offizieller lokaler Project Edge Client / Control Plane | Unklare Remote-Lage einer Mutation ueber `op_id` reconciliiert |
| `story_contract_classified` | 59 | Setup / Story-Metadata | Persistenter Story-Vertrag aus `story_type` und optionalem `implementation_contract` wurde konsolidiert |
| `runtime_classification_derived` | 59 | Setup / GuardSystem | Laufzeitklassifikation aus `operating_mode` und `execution_route` wurde abgeleitet |
| `story_marked_done` | 59 | Closure | Story wurde erfolgreich geliefert und auf `Done` gesetzt |
| `story_cancelled_administratively` | 59 | Admin-Pfad | Story wurde ueber Split, Exit oder Reset administrativ auf `Cancelled` gesetzt |
| `invalid_contract_combination_detected` | 59 | Setup / GuardSystem | Ungueltige Vertragskombination oder verbotene Achsenmischung wurde fail-closed erkannt |
| `integration_manifest_approved` | 57 | CLI / human_cli | Integrations-Scope-Manifest fuer eine systemische E2E-/Stabilisierungsstory freigegeben |
| `stabilization_campaign_started` | 57 | Pipeline / Verify | Budgetierte Integrations-Stabilisierungsschleife gestartet |
| `integration_verify_passed` | 57 | Verify / Stability Gate | Integrationszielmatrix und Stability-Gate erfolgreich passiert |
| `integration_verify_failed` | 57 | Verify / Stability Gate | Integrations-Verify gescheitert; weiterer Zyklus oder Replan noetig |
| `undeclared_surface_detected` | 57 | GuardSystem | Produktiver Pfad ausserhalb des freigegebenen Integrations-Manifests beruehrt |
| `stabilization_budget_exhausted` | 57 | GuardSystem / Verify | Freigegebenes Stabilisierungshaushalt erschopft; normaler Weiterlauf blockiert |
| `manifest_amendment_requested` | 57 | CLI / human_cli | Erweiterung eines laufenden Integrations-Manifests offiziell beantragt |
| `stability_gate_passed` | 57 | Verify / Closure Precondition | Zusätzliche Integrations-Stabilitätsbedingungen für Closure erfüllt |
| `story_exit_requested` | 58 | CLI / human_cli | Offizieller Human-Takeover-Exit fuer eine Story angefordert |
| `story_exit_gate_passed` | 58 | Admin-Service | Leichtgewichtiges Exit-Gate bestanden |
| `story_exit_rejected` | 58 | Admin-Service | Exit-Voraussetzungen oder Exit-Grund waren unzulaessig |
| `story_exit_binding_revoked` | 58 | Admin-Service | Story-Lock und Session-Bindung fuer den beendeten Run wurden geloest |
| `story_exit_completed` | 58 | Admin-Service | Story ist administrativ beendet und Session wieder im freien Modus |
| `dependency_rebinding_started` | 54 | StorySplitService / DependencyRebinding | Rebinding der expliziten Story-Abhaengigkeiten begonnen |
| `dependency_rebinding_completed` | 54 | StorySplitService / DependencyRebinding | Alle expliziten Dependency-Kanten gemaess Split-Plan umgebogen |
| `dependency_rebinding_rejected` | 54 | StorySplitService / DependencyRebinding | Rebinding wegen unvollständigem Mapping oder Graph-Verletzung abgelehnt |
| `canonical_state_persisted` | 18 | PipelineEngine / StoryContextManager | Kanonischer PostgreSQL-Zustand einer Story- oder Runtime-Identität persistiert |
| `derived_storage_materialized` | 18 | PhaseStateStore / Analytics | Projektion oder Read-Model aus kanonischen Familien erzeugt |
| `derived_storage_rebuilt` | 18 | PhaseStateStore / Analytics | Stale oder rebuild-pending Family neu aus kanonischer Quelle aufgebaut |
| `derived_storage_stale` | 18 | PhaseStateStore / Analytics | Projektion oder Read-Model als stale markiert |
| `derived_storage_invalidated` | 18 | StoryResetService | Nicht-kanonische Family durch Reset invalidiert oder gelöscht |
| `telemetry_append_degraded` | 18 | TelemetryService | Telemetrie konnte nur degradiert verarbeitet werden, ohne den kanonischen Fortschritt zu blockieren |
| `runtime_storage_purged` | 18 | StoryResetService | Runtime-, Telemetrie- und Projektionsfamilien einer Story bereinigt |
| `storage_policy_violation` | 18 | GuardSystem / Runtime Check | Kanonizitäts-, Single-Writer- oder Scope-Verletzung am Speicherschnitt erkannt |
| `telemetry_collection_completed` | 14 | TelemetryService / Analytics Intake | Gültige Runtime-Events für Weiterverarbeitung gesammelt |
| `analytics_read_models_materialized` | 16 | QA-/Failure-Corpus-Projektion | Operative Read Models aus gültigen Quellen materialisiert |
| `analytics_facts_refreshed` | 62 | Analytics Refresh Worker | Fact-Familien aus gültigen Quellen neu berechnet |
| `analytics_data_invalidated` | 16 | StoryResetService / Analytics Worker | Telemetrie-/Analytics-Daten eines resetbetroffenen Runs invalidiert |
| `dashboard_query_served` | 63 | Dashboard Service | Read-only Ergebnis aus Runtime-/Analytics-Daten ausgeliefert |
| `analytics_policy_violation` | 63 | Dashboard Service / Guard | Ungültiger Auswertungspfad oder Serve-Versuch über invalidierte Daten erkannt |
| `preflight_passed` | 22 | Setup / Preflight | Alle Preflight-Checks bestanden |
| `preflight_failed` | 22 | Setup / Preflight | Mindestens ein Preflight-Check gescheitert |
| `setup_completed` | 22 | Setup / Preflight | Setup abgeschlossen, Mode und Spawn-Vertrag gesetzt |
| `verify_started` | 27 | Verify | QA-Zyklus gestartet |
| `verify_passed` | 27 | Verify | Vollständige 4-Schichten-QA erfolgreich abgeschlossen |
| `verify_failed` | 27 | Verify | QA-Befunde erfordern Remediation |
| `verify_escalated` | 27 | Verify | Verify wegen harter Verletzung oder Impact-Violation eskaliert |
| `preflight_request` | 14 | Hook (PreToolUse Pool-Send) | Preflight-Prompt an LLM-Pool gesendet (Preflight-Sentinel) |
| `preflight_response` | 14 | Hook (PostToolUse Pool-Send) | Preflight-Antwort vom LLM empfangen |
| `preflight_compliant` | 14 | Review-Guard (PostToolUse) | Preflight verwendete genehmigtes Template (Preflight-Sentinel) |
| `review_divergence` | 14 | `telemetry/divergence.py` | Divergenz zwischen zwei Reviewern gemessen |
| `are_requirements_linked` | 40 | Pipeline-Skript | ARE: Anforderungen verlinkt |
| `are_evidence_submitted` | 40 | Worker/QA-Prozess | ARE: Evidence eingereicht |
| `are_gate_result` | 40 | Pipeline-Skript | ARE: Gate PASS/FAIL |

**Control-Plane-Regel:** Alle Event-Typen bleiben plattformneutral.
Hooks, CLI und kuenftige REST-Aufrufe sind nur Producer-Pfade auf
diesen Katalog; sie duerfen keine abweichenden Event-Namen oder
Payload-Formate einfuehren.

## 91.3 MCP-Tool-Katalog

### LLM-Session-Pools (pro Pool)

| Tool | Kapitel | Beschreibung |
|------|---------|-------------|
| `{pool}_acquire` | 11 | Slot anfordern |
| `{pool}_send` | 11 | Nachricht senden |
| `{pool}_release` | 11 | Slot freigeben |
| `{pool}_health` | 11 | Lebendigkeit prüfen |
| `{pool}_pool_status` | 11 | Pool-Übersicht |

### Story-Knowledge-Base (Weaviate)

| Tool | Kapitel | Beschreibung |
|------|---------|-------------|
| `story_search` | 13 | Semantische Suche |
| `story_list_sources` | 13 | Datenquellen auflisten |
| `story_sync` | 13 | Inkrementelle Indexierung |

### ARE (optional)

| Tool | Kapitel | Beschreibung |
|------|---------|-------------|
| `are_list_requirements` | 40 | Anforderungen auflisten |
| `are_get_recurring` | 40 | Wiederkehrende Pflichtanforderungen |
| `are_load_context` | 40 | must_cover für Worker-Kontext |
| `are_submit_evidence` | 40 | Evidence einreichen |
| `are_check_gate` | 40 | Gate prüfen |

## 91.4 Hook-Katalog

| Hook-Modul | Typ | Matcher | Kapitel |
|-----------|-----|---------|---------|
| `governance.branch_guard` | PreToolUse | Bash | 31.1 |
| `governance.orchestrator_guard` | PreToolUse | Bash, Read\|Grep\|Glob | 31.2 |
| `governance.integrity` | PreToolUse | Write\|Edit, Bash | 31.3 |
| `governance.qa_agent_guard` | PreToolUse | Write\|Edit | 31.4 |
| `governance.adversarial_guard` | PreToolUse | Write\|Edit | 31.6 |
| `governance.self_protection` | PreToolUse | Write\|Edit\|Bash | 30.5.3 |
| `governance.story_creation_guard` | PreToolUse | Bash | 31.5 |
| `governance.ccag_gatekeeper` | PreToolUse | Bash\|Write\|Edit\|Read\|Grep\|Glob\|Agent | 42.5 |
| `telemetry.hook` | Pre+PostToolUse | Agent, Bash, *_send | 14.3 |
| `telemetry.review_guard` | PostToolUse | *_send | 14.5 |
| `telemetry.budget` | PostToolUse | WebSearch\|WebFetch | 14.6 |

## 91.5 Phase-State Status-Werte

| Status | Bedeutung | Kapitel |
|--------|----------|---------|
| `IN_PROGRESS` | Phase läuft | 20.3.2 |
| `COMPLETED` | Phase erfolgreich abgeschlossen | 20.3.2 |
| `FAILED` | Phase gescheitert (z.B. Preflight) | 20.3.2 |
| `ESCALATED` | Dauerhaft gestoppt, neuer Run nötig | 35.4.3 |
| `PAUSED` | Vorübergehend angehalten, fortsetzbar | 35.4.3 |

## 91.6 Story-Reset-Statuswerte

Diese Werte gehoeren **nicht** zum normalen Phase-State, sondern zum
administrativen Reset-Vorgang aus FK-53.

| Status | Bedeutung | Kapitel |
|--------|----------|---------|
| `STARTED` | Reset-Vorgang angelegt, aber noch nicht abgeschlossen | 53.5 |
| `RESETTING` | Story ist gefenced und der Purge-Flow läuft | 53.7 |
| `COMPLETED` | Reset vollständig abgeschlossen | 53.9.3 |
| `RESET_FAILED` | Reset unvollständig gescheitert; Story bleibt blockiert | 53.9.2 |

## 91.7 Story-Split-Statuswerte

Diese Werte gehoeren **nicht** zum normalen Phase-State, sondern zum
administrativen Split-Vorgang aus FK-54.

| Status | Bedeutung | Kapitel |
|--------|----------|---------|
| `STARTED` | Split-Vorgang angelegt | 54.8.1 |
| `SPLITTING` | Story ist gefenced, Nachfolger und Rebindings werden aufgebaut | 54.8 |
| `COMPLETED` | Split vollständig abgeschlossen | 54.5 |
| `SPLIT_FAILED` | Split unvollständig gescheitert; Story bleibt administrativ blockiert | 54.8 |
