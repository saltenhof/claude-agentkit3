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
---

# 90 — Schema-Katalog

## 90.1 Übersicht

Alle JSON Schemas mit Owning-Chapter und Kurzbeschreibung.
Detaillierte Felddefinitionen stehen im jeweiligen Owning-Chapter.

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
| ARE-Gate-Result | `are_gate_result.schema.json` | 40 | ARE-Gate-Prüfergebnis |
| Concept-Feedback | `concept_feedback.schema.json` | 24 | Konzept-Feedback-Loop-Ergebnis |
| Incident | `incident.schema.json` | 41 | Failure-Corpus-Incident |
| Pattern | `pattern.schema.json` | 41 | Failure-Corpus-Pattern |
| Check-Proposal | `check_proposal.schema.json` | 41 | Failure-Corpus-Check-Proposal |
| Story-Search-Result | `story_search_result.schema.json` | 13 | VektorDB-Suchergebnisse |
| Feedback | `feedback.schema.json` | 25 | Mängelliste für Remediation |
| Governance-Adjudication | `governance_adjudication.schema.json` | 35 | Incident-Klassifikation |

## 90.2 Namenskonvention

**Stage-ID = Dateiname:** Alle QA-Artefakte heißen `{stage_id}.json`
(Kap. 33.2.3). Die Schema-Dateien folgen demselben Muster:
`{stage_id}.schema.json`.
