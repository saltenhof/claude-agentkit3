---
concept_id: FK-90
title: Schema-Katalog
module: schema-catalog
status: active
doc_kind: core
parent_concept_id:
authority_over:
  - scope: schema-catalog
defers_to: []
supersedes: []
superseded_by:
tags: [schema, json-schema, katalog, referenz]
prose_anchor_policy: strict
formal_refs:
  - formal.state-storage.entities
  - formal.state-storage.invariants
  - formal.principal-capabilities.entities
  - formal.principal-capabilities.invariants
  - formal.integration-stabilization.entities
  - formal.story-exit.entities
  - formal.story-contracts.entities
  - formal.story-contracts.invariants
---

# 90 — Schema-Katalog

<!-- PROSE-FORMAL: formal.state-storage.entities, formal.state-storage.invariants, formal.principal-capabilities.entities, formal.principal-capabilities.invariants, formal.integration-stabilization.entities, formal.story-exit.entities, formal.story-contracts.entities, formal.story-contracts.invariants -->

## 90.1 Übersicht

Alle JSON Schemas mit Owning-Chapter und Kurzbeschreibung.
Detaillierte Felddefinitionen stehen im jeweiligen Owning-Chapter.

Der relationale PostgreSQL-State gehoert bewusst nicht in diesen
JSON-Schema-Katalog. Fuer den kanonischen Speicherschnitt sind FK-18
und `formal.state-storage.*` maßgeblich.

Konsolidierte Vertragsregel gemaess FK-59:

- `story_type` und `implementation_contract` sind kanonische
  Story-Vertragsfelder
- `operating_mode` ist **kein** kanonisches Story-Hauptfeld
- `exit_class` ist **kein** freies Story-Hauptfeld, sondern nur in
  offiziellen Exit-/Split-/Reset-Records zulaessig

| Schema | Datei | Owning Chapter | Beschreibung |
|--------|-------|---------------|-------------|
| Envelope | `envelope.schema.json` | 02 | Gemeinsame Metadaten aller QA-Artefakte |
| Context | `context.schema.json` | 22 | Story-Context (autoritativer Snapshot) |
| Structural | `structural.schema.json` | 33 | Deterministische Check-Ergebnisse |
| QA-Review | `qa_review.schema.json` | 34 | LLM-Bewertung (12 Checks) |
| Semantic-Review | `semantic_review.schema.json` | 34 | Systemische Angemessenheit |
| Doc-Fidelity | `doc_fidelity_impl.schema.json` | 32 | Umsetzungstreue |
| Adversarial | `adversarial.schema.json` | 34 | Adversarial-Testing-Ergebnisse |
| Policy | `policy.schema.json` | 33 | Policy-Entscheidung |
| Closure | `closure.schema.json` | 25 | Closure-Ergebnis mit Metriken |
| Phase-State | `phase_state.schema.json` | 20 | Pipeline-Zustand |
| Worker-Manifest | `worker_manifest.schema.json` | 24 | Technische Worker-Deklaration |
| Handover | `handover.schema.json` | 24 | Fachliche Übergabe an Verify |
| Entwurfsartefakt | `entwurfsartefakt.schema.json` | 23 | Change-Frame (Exploration) |
| Bugfix-Reproducer | `bugfix_reproducer.schema.json` | 24 | Bugfix-Reproducer |
| Guardrail | `guardrail.schema.json` | 33 | Guardrail-Prüfung |
| ARE-Evidence | `are_evidence.schema.json` | 40 | ARE-Evidence-Einreichung |
| Story-Reset-Record | `story_reset_record.schema.json` | 53 | Auditierbarer Reset-Vorgang |
| Story-Split-Plan | `story_split_plan.schema.json` | 54 | Menschlich freigegebener Plan fuer Nachfolger, Rebinding und Cancel-Pfad |
| Story-Split-Record | `story_split_record.schema.json` | 54 | Auditierbarer Split-Vorgang |
| Capability-Freeze-Record | `capability_freeze_record.schema.json` | 55 | Storybezogener Freeze bei HARD-STOP-/Normkonflikten |
| Conflict-Resolution-Record | `conflict_resolution_record.schema.json` | 55 | Auditierbare menschliche oder offizielle Konfliktaufloesung |
| Permission-Request-Record | `permission_request_record.schema.json` | 55 | Auditierbarer Einzelfall fuer unbekannte Freigaben mit TTL und Resolution |
| Permission-Lease-Record | `permission_lease_record.schema.json` | 55 | Befristete, story-/run-scoped Freigabe ausserhalb einer Dauerregel |
| Integration-Scope-Manifest | `integration_scope_manifest.schema.json` | 57 | Freigegebener Integrationsraum fuer systemische E2E-/Stabilisierungsstories |
| Manifest-Approval-Record | `manifest_approval_record.schema.json` | 57 | Attestierte menschliche oder administrative Freigabe eines Integrations-Manifests |
| Stabilization-Budget | `stabilization_budget.schema.json` | 57 | Harte Schleifen-, Surface- und Regressionsgrenzen fuer Integrationsstabilisierung |
| Story-Exit-Record | `story_exit_record.schema.json` | 58 | Audit-Record fuer administrativen Story-Exit in Human-Takeover |
| Exit-Manifest-Snapshot | `exit_manifest_snapshot.schema.json` | 58 | Letzter gebundener Story-/Manifest-/Budget-Stand beim Exit |
| ARE-Gate-Result | `are_gate_result.schema.json` | 40 | ARE-Gate-Prüfergebnis |
| Concept-Feedback | `concept_feedback.schema.json` | 24 | Konzept-Feedback-Loop-Ergebnis |
| Incident | `incident.schema.json` | 41 | Failure-Corpus-Incident |
| Pattern | `pattern.schema.json` | 41 | Failure-Corpus-Pattern |
| Check-Proposal | `check_proposal.schema.json` | 41 | Failure-Corpus-Check-Proposal |
| Story-Search-Result | `story_search_result.schema.json` | 13 | VektorDB-Suchergebnisse |
| Feedback | `feedback.schema.json` | 25 | Mängelliste für Remediation |
| Governance-Adjudication | `governance_adjudication.schema.json` | 35 | Incident-Klassifikation |
| Story-Reset-Record | `story_reset_record.schema.json` | 53 | Auditierbarer Reset-Vorgang mit Actor, Grund und Fortschritt |

## 90.2 Namenskonvention

**Stage-ID = Dateiname:** Alle QA-Artefakte heißen `{stage_id}.json`
(Kap. 33.2.3). Die Schema-Dateien folgen demselben Muster:
`{stage_id}.schema.json`.
