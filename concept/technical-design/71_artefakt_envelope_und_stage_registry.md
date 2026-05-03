---
concept_id: FK-71
title: Artefakt-Klassen, Envelope und Producer-Registry
module: artifact-envelope
domain: artifacts
status: active
doc_kind: core
parent_concept_id:
authority_over:
  - scope: artefakt-envelope
  - scope: producer-registry
defers_to:
  - target: FK-02
    scope: domain-model
    reason: Fachliches Domaenenmodell und Zustandsmodelle liegen in FK-02
  - target: FK-33
    scope: stage-registry
    reason: Stage-Registry-Verarbeitung und Policy-Aggregation liegen in FK-33
  - target: FK-31
    scope: artifact-protection
    reason: Hook-Enforcement fuer QA-Artefaktschutz und Lock-Mechanismus liegen in FK-31
  - target: FK-10
    scope: state-backend
    reason: Lock-Records werden zentral im State-Backend gehalten (FK-10)
supersedes: []
superseded_by:
tags: [artefakte, ownership, envelope, producer-registry]
formal_scope: prose-only
glossary:
  exported_terms:
    - id: artifact-class
      definition: >
        Klassifikation eines Story-Artefakts nach Erzeuger.
        Definierte Klassen: Worker-Artefakt, QA-Artefakt, Pipeline-Artefakt,
        Telemetrie, Governance-Artefakt, Entwurfsartefakt, Handover-Artefakt,
        Adversarial-Test-Sandbox. Jede Klasse legt fest, wer schreiben darf.
        Schutzmechanismen sind in governance-and-guards (FK-31) definiert.
    - id: artifact-envelope
      definition: >
        Gemeinsames Metadaten-Schema, das alle QA-Artefakte umhuellt.
        Pflichtfelder sind schema_version, story_id, run_id, stage, attempt,
        producer (type + name), started_at, finished_at und status. Das
        Integrity-Gate validiert Envelope-Felder bei Closure.
    - id: artifact-reference
      definition: >
        Typisierter Verweis auf ein konkret erzeugtes Artefakt, bestehend
        aus artifact_class, story_id, run_id und dem kanonischen Pfad oder
        Record-ID im State-Backend. Ermoeglicht Producer-Registry-Pruefung
        ohne direkten Dateizugriff.
    - id: producer-id
      definition: >
        Eindeutiger Name des erzeugenden Prozesses oder Agenten, der ein
        Artefakt materialisiert hat. Der Wert wird im Envelope-Feld
        producer.name gefuehrt und gegen die Producer-Registry validiert,
        die jedem Export-Artefakt genau einen erlaubten Producer zuordnet.
  internal_terms:
    - id: lock-record
      reason: >
        Interner Zustandstraeger des QA-Artefakt-Schutzmechanismus im
        State-Backend. Enforcement-Vertrag und Detail-Modell liegen bei
        governance-and-guards (FK-31). FK-71 referenziert nur.
    - id: protected-artifacts-list
      reason: >
        Implementierungsdetail des Integrity-Hooks. Liste der konkreten
        Dateinamen gehoert zur Hook-Konfiguration in BC 4
        (governance.guard_system, FK-31). FK-71 referenziert nur.
---

# 71 — Artefakt-Klassen, Envelope und Producer-Registry

Dieses Kapitel beschreibt die Datenmodelle fuer Story-Artefakte im
Bounded Context `artifacts` (BC 8): Klassifikation nach Erzeuger,
Envelope-Schema und Producer-Registry.

Der QA-Artefakt-Schutz via Lock-Record und Hook-Enforcement wird
in **FK-31** (BC 4: governance-and-guards) gefuehrt. Die typisierte
Stage-Registry (`StageDefinition`-Klasse) gehoert zu
**verify-system.StageRegistry** (FK-33, BC 2). Das uebergreifende
Domaenenmodell (Begriffe, Story-Status-Modell, Identifikatoren,
Invarianten) liegt in **FK-02**.

## 71.1 Artefaktklassen und Ownership

### 71.1.1 Artefaktklassen

Schutzmechanismen (Lock-Record, Hook-Konfiguration, PROTECTED_ARTIFACTS-Liste)
werden in BC 4 (governance-and-guards, FK-31) gefuehrt. Diese Tabelle
klassifiziert ausschliesslich nach Erzeuger und typischen Beispielen.

| Klasse | Erzeuger | Beispiele |
|--------|----------|-----------|
| **Worker-Artefakte** | Worker-Agent | `worker-manifest.json`, `protocol.md`, Quellcode |
| **QA-Artefakte** | Pipeline-Skripte, QA-Agenten | kanonisch `artifact_records`; optionale Exporte wie `structural.json`, `policy.json`, `semantic_review.json` |
| **Pipeline-Artefakte** | Phase Runner, Preflight, Postflight | kanonisch `story_contexts`, `flow_executions`, `phase_state_projection`; materialisierte Exporte wie `phase-state.json`, `context.json` sind nur Projektionen |
| **Telemetrie** | `telemetry_service` | `execution_events` (Laufzeit), Export-Bundle (Archiv) |
| **Governance-Artefakte** | Guards, Integrity-Gate | `integrity-violations.log` |
| **Entwurfsartefakte** | Worker (Exploration) | `entwurfsartefakt.json` |
| **Handover-Artefakte** | Worker (Implementation) | `handover.json` |
| **Adversarial-Test-Sandbox** | Adversarial Agent | `_temp/adversarial/{story_id}/` — Tests werden hier geschrieben und ausgefuehrt. Promotion ins Repo nur durch Pipeline-Skript (schema-valide, ausfuehrbar, dedupliziert). |

### 71.1.2 Schutzmechanismus (Referenz)

Die vollstaendige Liste geschuetzter Export-Dateinamen (`PROTECTED_ARTIFACTS`),
der Lock-Record-Mechanismus und die CCAG-Hook-Konfiguration gehoeren
zur Hook-Konfiguration in BC 4 (governance.guard_system).

Siehe **FK-31** — Hook-Enforcement und QA-Artefaktschutz.

## 71.2 Artefakt-Envelope-Schema

Alle QA-Artefakte nutzen ein gemeinsames Envelope-Schema. Das
Envelope trägt Metadaten, die das Integrity-Gate validiert.

```json
{
  "schema_version": "3.0",
  "story_id": "PROJ-042",
  "run_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "stage": "qa_structural",
  "attempt": 1,
  "producer": {
    "type": "script",
    "name": "qa-structural-check"
  },
  "started_at": "2026-03-16T14:00:00+01:00",
  "finished_at": "2026-03-16T14:01:23+01:00",
  "status": "PASS",
  "...": "stage-spezifische Felder"
}
```

**Pflichtfelder:**

| Feld | Typ | Validierung |
|------|-----|-------------|
| `schema_version` | String | Muss `"3.0"` sein |
| `story_id` | String | Muss FK-Story-ID-Pattern matchen |
| `run_id` | String | UUID v4 |
| `stage` | String | Einer der definierten Stage-IDs |
| `attempt` | Integer | ≥ 1 |
| `producer.type` | String | `"script"` oder `"agent"` |
| `producer.name` | String | Bekannter Producer-Name |
| `started_at` | String | ISO 8601 mit Zeitzone |
| `finished_at` | String | ISO 8601, ≥ started_at |
| `status` | String | `PASS`, `FAIL`, `WARN`, `ERROR` |

**Mapping LLM-Check-Status zu Artefakt-Status:**

LLM-Bewertungen (QA-Review, Semantic Review, Dokumententreue) liefern
pro Check einen von drei Werten: `PASS`, `PASS_WITH_CONCERNS`, `FAIL`
(FK-05-159..166). Bei der Aggregation zum Artefakt-Envelope wird
`PASS_WITH_CONCERNS` auf `WARN` gemappt:

| LLM-Check-Status | Artefakt-Envelope-Status | Semantik |
|-------------------|--------------------------|----------|
| `PASS` | `PASS` | Check bestanden |
| `PASS_WITH_CONCERNS` | `WARN` | Grundsätzlich ok, aber Hinweise — blockiert nicht, fließt als Warnung in Policy + Adversarial (FK-05-165/166) |
| `FAIL` | `FAIL` | Check nicht bestanden — blockiert Story (FK-05-164) |

`ERROR` ist kein LLM-Ergebnis, sondern ein Infrastruktur-Fehler
(z.B. LLM nicht erreichbar, Schema-Parsing gescheitert nach Retry).

**Producer-Registry** (welcher Producer darf welchen Export
materialisieren):

| Export-Artefakt | Erlaubter Producer |
|-----------------|-------------------|
| `structural.json` | `qa-structural-check` |
| `policy.json` / Legacy-Export `decision.json` | `qa-policy-engine` |
| `phase-state.json` | `run-phase` (Export der `phase_state_projection`) |
| `context.json` | `compute-story-context` (Export aus `StoryContext`) |
| `qa_review.json` | `qa-llm-review` |
| `semantic_review.json` | `qa-semantic-review` |
| `adversarial.json` | `qa-adversarial` |
| `closure.json` | `story-closure` |
| `are_bundle.json` | `qa-are-context-loader` |

Das Integrity-Gate prüft bei Closure kanonisch die Producer- und
Provenienzfelder der zugrunde liegenden Records. Exportdateien werden
höchstens konsistenzhalber oder für menschliche Audit-Pakete geprüft,
nicht als operative Wahrheitsquelle.

## 71.3 Lock-Mechanismus fuer QA-Artefaktschutz (Referenz)

Der vollstaendige Lock-Mechanismus — Lock-Record-Schema, Lebenszyklus,
Stale-Erkennung, CCAG-Regel, Scoping (nur Sub-Agents gesperrt) — ist
Owner des BC 4 (governance-and-guards).

Siehe **FK-31** — Hook-Enforcement, Guard-Aktivierung und
QA-Artefakt-Lock-Record.

Fuer BC 8 (artifacts) gilt: Die `artifact_class`-Zuordnung bestimmt,
welche Artefakte schutzwuerdig sind. Der Schutzmechanismus selbst wird
ausschliesslich in governance-and-guards ausgefuehrt und konfiguriert.

## 71.4 Typisierte Stage-Registry (Referenz)

Die `StageDefinition`-Klasse und die Standard-Stages-Tabelle gehoeren
zu **verify-system.StageRegistry** (BC 2).

Siehe **FK-33** — Stage-Registry, `StageDefinition`-Datenstruktur
und Policy-Aggregation.

Fuer BC 8 (artifacts) gilt: Das Envelope-Feld `stage` nimmt eine
bekannte Stage-ID auf. Die Validierung, welche IDs zulaessig sind,
obliegt verify-system.

