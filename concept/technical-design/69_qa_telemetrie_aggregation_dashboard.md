---
concept_id: FK-69
title: QA- und Failure-Corpus-Read-Models
module: qa-telemetry
domain: telemetry-and-events
status: active
doc_kind: core
parent_concept_id:
authority_over:
  - scope: qa-read-models
  - scope: read-model-projections
defers_to:
  - target: FK-68
    scope: telemetry
    reason: "`execution_events` und Event-Semantik werden in FK-68 definiert"
  - target: FK-17
    scope: fachliches-datenmodell
    reason: Entitaeten, Ownership und Aggregate sind dort normiert
  - target: FK-18
    scope: relationales-abbildungsmodell
    reason: Tabellenfamilien, Schluessel und Constraints sind dort normiert
  - target: FK-60
    scope: kpi-architektur
    reason: KPI-Facts und Analytics-Rollups gehoeren nicht zu FK-69
supersedes: []
superseded_by:
tags: [qa, failure-corpus, read-models, postgres, projections]
prose_anchor_policy: strict
formal_refs:
  - formal.state-storage.state-machine
  - formal.state-storage.commands
  - formal.state-storage.events
  - formal.state-storage.invariants
  - formal.state-storage.scenarios
  - formal.telemetry-analytics.entities
  - formal.telemetry-analytics.state-machine
  - formal.telemetry-analytics.commands
  - formal.telemetry-analytics.events
  - formal.telemetry-analytics.invariants
  - formal.telemetry-analytics.scenarios
glossary:
  exported_terms:
    - id: failure-corpus-read-model
      definition: >
        Querybare Projektions-Schicht der Failure-Corpus-Daten im
        State-Backend (fc_incidents, fc_patterns, fc_check_proposals).
        Schema-Owner und fachliche Definition liegen in BC failure-corpus
        (FK-41). telemetry-and-events.ProjectionAccessor stellt nur die
        DB-Zugriffsschicht bereit; Schreib-Owner ist failure-corpus.
        Operativ append-only fuer gueltige Runs; wird bei vollstaendigem
        Story-Reset der korrupten Umsetzung mitentfernt.
      see_also:
        - term: qa-read-model
          domain: telemetry-and-events
    - id: phase-state-projection
      definition: >
        Querybare Read-Model-Sicht auf den aktuellen Phasenzustand einer
        Story-Umsetzung im State-Backend. Liefert attempt_no, phase, status
        und mode fuer Story-Abfragen und Metrikbildung (qa_rounds). Ist
        eine abgeleitete Projektion aus dem kanonischen PhaseState der
        Pipeline-Engine; nie direkt von Agents beschreibbar.
      see_also:
        - term: phase-state-core
          domain: pipeline-framework
        - term: qa-read-model
          domain: telemetry-and-events
    - id: qa-read-model
      definition: >
        Querybare Projektions-Schicht operativer QA-Ergebnisse im
        State-Backend: qa_stage_results, qa_findings, qa_check_outcomes
        und story_metrics.
        Verdichtet execution_events zu Story- und Stage-Sichten fuer
        Laufzeit-Dashboards und Drill-Downs, ohne in die periodische
        KPI-Analytics-Schicht (FK-60 bis FK-63) einzugreifen. Jede
        Tabelle hat genau einen definierten Writer; bei vollstaendigem
        Story-Reset werden alle Zeilen des betroffenen run_id entfernt.
      see_also:
        - term: execution-event
          domain: telemetry-and-events
        - term: qa-check-outcome
          domain: telemetry-and-events
    - id: story-metric
      definition: >
        Operativer Abschlussmetriken-Datensatz pro Story-Run in der
        Tabelle story_metrics. Pflichtfelder: project_key, story_id, run_id,
        story_type, story_size, mode, processing_time_min, qa_rounds,
        increments, final_status, completed_at. Wird erst bei Story-Abschluss
        final; Quellen sind execution_events, phase_state_projection,
        StoryContext und Closure-Artefakte.
      see_also:
        - term: workflow-metric
          domain: telemetry-and-events
        - term: qa-read-model
          domain: telemetry-and-events
    - id: qa-check-outcome
      definition: >
        Per-check outcome row in `qa_check_outcomes`. Records the result of
        every individual check executed by verify-system: triggered (finding
        produced), clean (PASS, no finding), or overridden (suppressed by
        override). Owner: verify-system. DB-Owner: telemetry-and-events via
        ProjectionAccessor. The composite key
        (project_key, run_id, stage_id, attempt_no, check_id) is unique;
        stage_id and attempt_no are mandatory identity fields to disambiguate
        the same check_id running across stages or remediation attempts.
        check_id is the executed-check identifier (e.g. artifact.protocol,
        qa_review, branch.story, ac_fulfilled, impl_fidelity) -- NOT a
        fc_check_proposals CHK-NNNN proposal identifier. The optional
        check_proposal_ref links an FC-derived executed check back to its
        fc_check_proposals.check_id (CHK-NNNN); it is conditionally mandatory
        (non-NULL for FC-derived checks, NULL for native/built-in checks,
        §69.15.6 rule 4 / §69.11 rule 10). FK-69 owns only the raw outcome
        enum; the mapping of outcomes to effectiveness categories (true/false
        positive, no finding) is failure-corpus-owned (FK-41 §41.6.7.1).
      see_also:
        - term: qa-read-model
          domain: telemetry-and-events
  internal_terms:
    - id: qa-stage-result-record
      reason: >
        Konkretes Tabellen-Tupel in qa_stage_results. Implementierungsdetail
        der FK-69-Persistenzschicht; der exportierte Begriff ist qa-read-model.
    - id: reset-purge-job
      reason: >
        Interner Bereinigungsprozess, der bei vollstaendigem Story-Reset alle
        FK-69-Zeilen des betroffenen run_id loescht. Implementierungsdetail
        ohne eigene Vertragsflaeche.
---

# 69 — QA- und Failure-Corpus-Read-Models

## 69.1 Zweck

<!-- PROSE-FORMAL: formal.state-storage.state-machine, formal.state-storage.commands, formal.state-storage.events, formal.state-storage.invariants, formal.state-storage.scenarios, formal.telemetry-analytics.entities, formal.telemetry-analytics.state-machine, formal.telemetry-analytics.commands, formal.telemetry-analytics.events, formal.telemetry-analytics.invariants, formal.telemetry-analytics.scenarios -->

FK-69 definiert die **operativen Read Models** fuer QA-Ergebnisse,
Story-Metriken und Failure-Corpus-Daten auf dem zentralen
PostgreSQL-State-Backend.

Diese Modelle dienen:

- gezielten Story- und Stage-Abfragen waehrend Laufzeit und Review
- operativen Dashboards und Drill-Downs
- Failure-Corpus-Pflege und Check-Wirksamkeitsbeobachtung

FK-69 definiert **nicht**:

- den kanonischen Event-Vertrag (`execution_events`) → FK-68
- das fachliche Datenmodell und Ownership → FK-17
- die relationale Normstruktur, Schluessel und Constraints → FK-18
- KPI-Facts, periodische Aggregation und Dashboard-Semantik → FK-60 bis FK-63

## 69.2 Grundregeln

1. **Kanonischer Laufzeitstate liegt nie in Projektdateien.**
   `_temp/qa/...`, `closure.json`, `incidents.jsonl` und aehnliche
   Dateien sind Exporte, Importquellen oder Arbeitsartefakte, aber
   nicht operative Hauptwahrheit.
2. **Alle Tabellen sind projektgebunden.**
   `project_key` ist Pflicht auf allen QA- und Failure-Corpus-Modellen.
3. **Single Writer pro Tabelle.**
   Jede Tabelle hat genau eine verantwortliche Komponente oder einen
   klar abgegrenzten Projektionsjob.
4. **Read Models bleiben fachlich schmal.**
   Operative Read Models sind nicht die Analytics-Fact-Schicht.
5. **Artefaktbezug erfolgt ueber Referenzen.**
   Wenn ein QA-Ergebnis aus einer Datei materialisiert wurde, zeigt das
   Read Model auf `artifact_records`, nicht umgekehrt.
6. **Vollstaendiger Story-Reset purgt alle abgeleiteten Read Models der
   korrupten Umsetzung.**
   FK-69-Tabellen duerfen keinen Zustand einer vollstaendig
   zurueckgesetzten Story-Umsetzung behalten.

## 69.3 Tabellenumfang

FK-69 autorisiert folgende Tabellen (DB-Zugriffsschicht via
`agentkit.backend.telemetry.read_models`):

**QA-Read-Models (Schema-Owner: verify-system):**

- `qa_stage_results` — `agentkit.backend.telemetry.read_models.qa_stage_results`
- `qa_findings` — `agentkit.backend.telemetry.read_models.qa_findings`
- `qa_check_outcomes` — `agentkit.backend.telemetry.read_models.qa_check_outcomes`

**Story-Metriken (Schema-Owner: story-closure):**

- `story_metrics` — `agentkit.backend.telemetry.read_models.story_metrics`

**Failure-Corpus-Read-Models (Schema-Owner: failure-corpus, FK-41):**

- `fc_incidents` — `agentkit.backend.telemetry.read_models.fc_incidents`
- `fc_patterns` — `agentkit.backend.telemetry.read_models.fc_patterns`
- `fc_check_proposals` — `agentkit.backend.telemetry.read_models.fc_check_proposals`

`phase_state_projection` — `agentkit.backend.telemetry.read_models.phase_state_projection`
(Schema-Owner: pipeline-framework)

**Hinweis:** telemetry-and-events ist fuer alle Tabellen der **DB-Owner**
(Zugriffsschicht via ProjectionAccessor). Schema-Definitions-Verantwortung
liegt bei den jeweiligen Owner-BCs wie oben angegeben.

## 69.4 Schreib-Ownership

| Tabelle | Schema-Owner BC | Writer-Komponente | Fachliche Rolle |
|---------|----------------|-------------------|-----------------|
| `qa_stage_results` | verify-system | `verify_system.StageRegistry` / Verify-Runner | Ergebnis je Stage und Attempt |
| `qa_findings` | verify-system | `verify_system.StageRegistry` / jeweiliger Stage-Adapter | Atomare Findings je Check |
| `qa_check_outcomes` | verify-system | `verify_system.CheckOutcomeEmitter` / Verify-Runner | Per-Check-Outcome for every executed check (triggered/clean/overridden) |
| `story_metrics` | story-closure | `story_closure.PostMergeFinalization` | Story-nahe Abschlussmetriken |
| `phase_state_projection` | pipeline-framework | `pipeline_engine.PhaseExecutor` | Laufzeitphasenstatus und Attempt-Zaehler |
| `fc_incidents` | failure-corpus | `failure_corpus.FailureCorpus` | Laufende Incident-Erfassung |
| `fc_patterns` | failure-corpus | `failure_corpus.FailureCorpus` | Pattern-Lifecycle |
| `fc_check_proposals` | failure-corpus | `failure_corpus.FailureCorpus` | Check-Vorschlaege und Wirksamkeit |

**DB-Owner fuer alle Tabellen:** telemetry-and-events (`agentkit.backend.telemetry.projection_accessor`).
Schema-Owner ist das jeweilige BC; FK-69 definiert nur die Zugriffsschicht und Konsistenzregeln.

## 69.5 Abgrenzung zu anderen Schichten

### 69.5.1 Gegenueber `execution_events`

`execution_events` bleiben der Audit- und Beobachtungsstrom
**gueltiger** Story-Umsetzungen. FK-69 verdichtet diesen Strom nicht zu
KPI-Facts, sondern zu operativ nutzbaren Story-/Stage-Sichten. Wird
eine Story-Umsetzung vollstaendig zurueckgesetzt, werden ihre
`execution_events` und alle daraus abgeleiteten FK-69-Read-Models
mitentfernt.

### 69.5.2 Gegenueber `artifact_records`

`artifact_records` verwalten Artefakte generisch mit Status,
Provenienz und Speicherreferenz. FK-69 verwaltet daraus abgeleitete,
fachlich querybare Sichten wie Findings, Stage-Ergebnisse oder
Check-Wirksamkeit.

### 69.5.3 Gegenueber FK-60 bis FK-63

FK-69 endet vor periodischen Rollups, Perzentilen und Trend-KPIs.
Diese gehoeren in die Analytics-Schicht.

## 69.6 Tabelle `qa_stage_results`

**Modul:** `agentkit.backend.telemetry.read_models.qa_stage_results`
**Schema-Owner:** verify-system

### 69.6.1 Zweck

`qa_stage_results` speichert das Ergebnis einer einzelnen Verify-Stage
fuer genau einen Attempt einer Story. Die Pflichtattribute sind hier als
Read-Model-Kontrakt definiert; die fachliche Schema-Verantwortung liegt
bei verify-system (FK-33).

### 69.6.2 Pflichtattribute

- `project_key`
- `story_id`
- `run_id`
- `attempt_no`
- `stage_id`
- `layer`
- `producer_component`
- `status`
- `blocking`
- `total_checks`
- `failed_checks`
- `warning_checks`
- `artifact_id`
- `recorded_at`

### 69.6.3 Fachregeln

- Pro `(project_key, run_id, attempt_no, stage_id)` gibt es genau ein
  aktuelles Stage-Ergebnis.
- `artifact_id` verweist auf das materialisierte Stage-Artefakt
  in `artifact_records`.
- `status` ist ein Stage-Gesamtstatus, nicht die Summe der Findings.
- `attempt_no` folgt dem Verify-Loop aus `phase_state_projection`.
- Ein vollstaendiger Story-Reset loescht alle `qa_stage_results` des
  betroffenen `run_id`.

## 69.7 Tabelle `qa_findings`

**Modul:** `agentkit.backend.telemetry.read_models.qa_findings`
**Schema-Owner:** verify-system

### 69.7.1 Zweck

`qa_findings` macht einzelne Check-Befunde querybar, ohne das jeweilige
JSON-Artefakt parsen zu muessen. Schema-Verantwortung liegt bei verify-system
(FK-33); FK-69 definiert die Zugriffsschicht.

### 69.7.2 Pflichtattribute

- `project_key`
- `story_id`
- `run_id`
- `attempt_no`
- `stage_id`
- `finding_id`
- `check_id`
- `status`
- `severity`
- `blocking`
- `source_component`
- `artifact_id`
- `occurred_at`

### 69.7.3 Optionale Attribute

- `category`
- `reason`
- `description`
- `detail`
- `metadata`

### 69.7.4 Fachregeln

- Findings sind **nicht** die kanonische Wahrheit der Stage, sondern
  eine querybare Projektion aus dem Stage-Artefakt.
- Pro `(project_key, run_id, attempt_no, stage_id, finding_id)` gibt es
  genau einen aktuellen Finding-Record.
- `finding_id` ist stage-lokal stabil und darf nicht aus Freitext
  abgeleitet werden.
- Ein vollstaendiger Story-Reset loescht alle `qa_findings` des
  betroffenen `run_id`.

## 69.8 Tabelle `story_metrics`

**Modul:** `agentkit.backend.telemetry.read_models.story_metrics`
**Schema-Owner:** story-closure

### 69.8.1 Zweck

`story_metrics` haelt operative Abschlussmetriken pro Story-Run, die
fuer Story-Detailansichten und einfache Projektsteuerung benoetigt
werden, aber noch keine periodische KPI-Aggregation sind.
Schema-Verantwortung liegt bei story-closure (FK-29); FK-69 definiert
die Zugriffsschicht.

### 69.8.2 Pflichtattribute

- `project_key`
- `story_id`
- `run_id`
- `story_type`
- `story_size`
- `mode`
- `processing_time_min`
- `qa_rounds`
- `increments`
- `final_status`
- `completed_at`

### 69.8.3 Optionale Attribute

- `adversarial_findings`
- `adversarial_tests_created`
- `files_changed`
- `agentkit_version`
- `agentkit_commit`
- `config_version`
- `llm_roles`

### 69.8.4 Fachregeln

- `story_metrics` ist pro `(project_key, run_id)` eindeutig.
- Die Tabelle wird erst bei Story-Abschluss final.
- Quellen sind `execution_events`, `phase_state_projection`,
  `StoryContext` und Closure-Artefakte.
- Ein vollstaendiger Story-Reset loescht den `story_metrics`-Satz der
  korrupten Umsetzung.
- `story_metrics` enthaelt **keine** `check_ref`- oder
  Per-Check-Outcome-Spalten und ist **keine** Quelle der
  Per-Check-Effektivitaet. Die Per-Check-Outcome-Wahrheit liegt ausschliesslich
  in `qa_check_outcomes` (§69.15); `story_metrics` bleibt run-level (eine Zeile
  pro `(project_key, run_id)`).

## 69.9 Failure-Corpus-Read-Models

**Schema-Owner:** failure-corpus (FK-41)
**Modul (DB-Zugriffsschicht):** `agentkit.backend.telemetry.read_models.fc_*`

Die Tabellen `fc_incidents`, `fc_patterns` und `fc_check_proposals`
gehoeren **fachlich zu BC failure-corpus** (FK-41). Ihre inhaltliche
Definition — Pflichtattribute, Fachregeln, Lifecycle — ist
ausschliesslich in **FK-41 §41.3** normiert.

telemetry-and-events.ProjectionAccessor ist der **DB-Owner**: er stellt
die Zugriffsschicht (Lesen und Schreiben via `Telemetry.write_projection`
bzw. `Telemetry.read_projection`) bereit, trifft aber keine
fachlichen Schema-Entscheidungen.

Fuer Attribute, Fachregeln und Reset-Semantik der drei Tabellen:

> Siehe **FK-41 §41.3** (Failure Corpus, Pattern-Promotion und
> Check-Factory — Speicherung und Datenmodell).

**Reset-Regel (analog §69.10.1):** Wird ein `run_id` vollstaendig
zurueckgesetzt, muessen alle `fc_incidents`-Zeilen dieses `run_id`
entfernt werden. Betroffene `fc_patterns`-Projektionen (incident_count)
muessen neu berechnet oder korrigiert werden (Patterns werden korrigiert,
nicht geloescht). `fc_check_proposals` bleiben unberuehrt (FK-41 §41.3).
Klarstellung: Dies ist KEINE "Failure-Corpus ueberlebt Reset"-Regel — die
Incidents des zurueckgesetzten Runs werden aktiv entfernt; nur der
aggregierte Pattern-/Proposal-Bestand bleibt (korrigiert) erhalten. Der
fc_*-Purge-/Recompute-Pfad wird mit den fc-Repos in **AG3-028** umgesetzt
(in AG3-035 existieren die fc_*-Tabellen noch nicht).

## 69.10 Quellen und Materialisierung

### 69.10.1 Eingangsquellen

FK-69 darf Daten aus diesen Quellen materialisieren:

- `execution_events`
- `phase_state_projection`
- `StoryContext`
- `artifact_records`
- kanonische Failure-Corpus-Entitaeten
- Legacy-Dateien nur in expliziten Import-/Backfill-Pfaden

**Reset-Regel:** Wird ein `run_id` vollstaendig zurueckgesetzt, muessen
alle FK-69-Projektionen dieses `run_id` aktiv entfernt oder aus den
verbleibenden gueltigen Quellen neu aufgebaut werden. Spaeteres
Herausfiltern in Queries ist unzulaessig.

### 69.10.2 Exportdateien

Die bekannten Dateien bleiben als Arbeits- oder Exportformate
erlaubt, z. B.:

- `_temp/qa/{story_id}/structural.json`
- `_temp/qa/{story_id}/qa_review.json`
- `_temp/qa/{story_id}/semantic_review.json`
- `_temp/qa/{story_id}/adversarial.json`
- `_temp/closure/{story_id}/closure.json`

Diese Dateien sind jedoch nie die alleinige operative Wahrheit.

## 69.11 Konsistenzregeln

1. Jedes `qa_stage_result` mit `artifact_id` muss auf einen
   existierenden `artifact_record` zeigen.
2. `qa_findings` duerfen nur zu existierenden Stage-Ergebnissen
   derselben Kombination aus `(project_key, run_id, attempt_no, stage_id)`
   existieren.
3. `story_metrics.qa_rounds` muss aus `phase_state_projection`
   reproduzierbar sein.
4. Failure-Corpus-Read-Models muessen rebuildbar bleiben; Dateiexporte
   sind keine exklusive Wahrheit.
5. Ein vollstaendiger Story-Reset darf keine FK-69-Zeile der
   korrupten Umsetzung zuruecklassen.
6. Every `qa_check_outcomes` row MUST have a non-empty `check_id`. A row
   with a blank or NULL `check_id` is a schema violation (fail-closed).
7. An `overridden` outcome row MUST reference a valid `override_id`
   (non-NULL). An `override_id` set on a `triggered` or `clean` row is a
   schema violation.
8. Every `qa_check_outcomes` row MUST belong to an existing
   `qa_stage_results` row for the same `(project_key, run_id, attempt_no,
   stage_id)` combination. Outcome rows without a parent stage result are
   invalid.
9. For `outcome=triggered`, at least one matching `qa_findings` row
   for the same `(project_key, run_id, attempt_no, stage_id, check_id)`
   MUST exist (the finding is the evidence that triggered the outcome).
10. For every `qa_check_outcomes` row whose executed check originated from
    an `fc_check_proposals` proposal (CheckFactory, FK-41 §41.6.6),
    `check_proposal_ref` MUST be non-NULL and equal to that proposal's
    `CHK-NNNN` id. For native/built-in checks it MUST be NULL. Missing linkage
    for an FC-derived check is an emitter/schema violation (fail-closed).

## 69.15 Tabelle `qa_check_outcomes`

**Modul:** `agentkit.backend.telemetry.read_models.qa_check_outcomes`
**Schema-Owner:** verify-system

### 69.15.1 Zweck

`qa_check_outcomes` records the result of every individual check executed by
verify-system, across all QA layers and all remediation attempts. Unlike
`qa_findings` (which only captures non-PASS results), `qa_check_outcomes`
records a row for EVERY executed check regardless of outcome — including
clean (PASS) checks and overridden checks.

This provides a complete, queryable audit trail of check execution suitable
for effectiveness analysis (AG3-078) and override attribution without
requiring reconstruction from aggregates.

`qa_check_outcomes` is the canonical per-check outcome source. FK-69 owns only
the RAW `outcome` enum (telemetry fact: what happened). The INTERPRETATION of
outcomes into effectiveness categories (true positive / false positive / no
finding) and the resulting check auto-deactivation are failure-corpus business
semantics, defined canonically in FK-41 §41.6.7 / §41.6.7.1 — FK-69 does not
duplicate that mapping. `story_metrics` (§69.8) is run-level and is NOT a source
of per-check effectiveness.

### 69.15.2 Pflichtattribute

- `project_key` — mandatory on all FK-69 tables (§69.2 rule 2)
- `story_id`
- `run_id`
- `stage_id` — the executing stage identifier (e.g. `artifact.protocol`,
  `qa_review`, `semantic_review`, `doc_fidelity_impl`, `branch.story`);
  mandatory identity field because the same `check_id` can run in multiple
  stages across a run
- `attempt_no` — 1-based QA-remediation attempt; mandatory identity field
  because the same `check_id` can run multiple times across remediation
  rounds
- `check_id` — the executed-check identifier (e.g. `artifact.protocol`,
  `qa_review`, `branch.story`, `ac_fulfilled`, `impl_fidelity`);
  NOT `fc_check_proposals.check_id` (those are CHK-NNNN proposal IDs)
- `outcome` — `CheckOutcome` enum: `triggered` (finding produced) |
  `clean` (PASS, no finding) | `overridden` (suppressed by override)
- `occurred_at` — UTC timestamp of check execution

### 69.15.3 Optionale Attribute

- `check_proposal_ref` — reference to `fc_check_proposals.check_id`
  (CHK-NNNN format), set ONLY when the executed check originated from a
  proposal; NULL for all deterministic and built-in LLM-role checks
- `override_id` — correlation to the `OverrideRecord.override_id` that
  caused the `overridden` outcome; NULL for `triggered`/`clean` rows.
  `override_id` is globally unique (PRIMARY KEY on `override_records`),
  so a single column reference is sufficient for deterministic attribution.

### 69.15.4 Composite Key

Primary key: `(project_key, run_id, stage_id, attempt_no, check_id)`

The composite key is intentional: `stage_id` and `attempt_no` are mandatory
identity fields because:

1. The same `check_id` can appear in multiple stages (e.g. `impl_fidelity`
   runs within `doc_fidelity_impl` stage; structural checks run within
   `structural` stage).
2. In QA-remediation runs, the same check reruns across attempts — each
   attempt produces a distinct outcome row.

### 69.15.5 Artifact Traceability

`qa_check_outcomes` rows are emitted by `verify_system.CheckOutcomeEmitter`
at check-execution time within the verify-runner flow. They are NOT
materialized from a QA artifact after the fact (unlike `qa_stage_results`
and `qa_findings`, which are materialized from a stage artifact). Therefore
`qa_check_outcomes` rows carry no `artifact_id` column. Traceability to the
stage artifact is established via the parent `qa_stage_results` row for
`(project_key, run_id, attempt_no, stage_id)` (§69.11 consistency rule 8).

### 69.15.6 Fachregeln

1. **verify-system is the sole writer.** No other BC may write
   `qa_check_outcomes`. Schema-Owner is verify-system; DB-Owner is
   telemetry-and-events (via `ProjectionAccessor`).
2. **Every executed check produces exactly one row per
   `(project_key, run_id, stage_id, attempt_no, check_id)`.** A clean
   check produces `outcome=clean`, not silence.
3. **`check_id` is the executed-check identifier**, as defined in
   `verify_system/stage_registry/data.py` (`stage_id` values e.g.
   `artifact.protocol`, `branch.story`) and
   `llm_evaluator/structured_evaluator.py` check-id whitelists (e.g.
   `qa_review`, `ac_fulfilled`, `impl_fidelity`). It is NOT a
   `fc_check_proposals` CHK-NNNN identifier.
4. **`check_proposal_ref` is conditionally mandatory.** It MUST be non-NULL
   and equal to the originating `fc_check_proposals.check_id` (`CHK-NNNN`) for
   every executed check that was generated from an `fc_check_proposals`
   proposal (CheckFactory, FK-41 §41.6.6). For all native/built-in
   deterministic and LLM-role checks it MUST be `NULL`. Missing linkage for an
   FC-derived check is an emitter/schema violation (fail-closed; see §69.11
   rule 10). It is populated by verify-system echoing
   `StageDefinition.origin_check_ref` (FK-33 §33.2.1) verbatim, without
   interpreting it.
5. **`override_id` is set for `overridden` outcomes** to enable
   deterministic attribution: which override suppressed which check.
   `override_id` is a globally unique identifier (PRIMARY KEY in
   `override_records`).
6. **A full Story-Reset removes all `qa_check_outcomes` rows** of the
   affected `run_id` (FK-69 §69.10.1 reset rule).
7. **`project_key` is mandatory.** A missing `project_key` is a hard error
   (fail-closed, FK-69 §69.2 rule 2).
8. **closure MUST NOT write `qa_check_outcomes`.** closure reads this
   table for roll-ups; per-check outcome truth belongs exclusively to
   verify-system (the executor).
9. **The mapping of `outcome` to effectiveness categories is NOT defined
   here.** FK-69 owns only the raw `outcome` enum (`triggered | clean |
   overridden`). The interpretation `triggered → true positive`,
   `overridden → false positive`, `clean → no finding` and the resulting
   auto-deactivation are failure-corpus semantics, defined canonically in
   FK-41 §41.6.7.1.
10. **`read_projection` for `qa_check_outcomes` MUST support `check_proposal_ref`
    and an `occurred_at`/`since_days` time-window as filters.** Per-check
    effectiveness aggregation runs over `check_proposal_ref` (the `CHK-NNNN`
    proposal id), NOT over the executed `check_id`; a missing
    `check_proposal_ref` filter capability would force an incorrect
    aggregation and is a contract gap.

## 69.12 Backfill und Migration

Backfill aus Legacy-Artefakten bleibt erlaubt, aber nur als
Migrationspfad:

- JSON/JSONL-Dateien koennen in die FK-69-Tabellen importiert werden
- der Import muss `project_key` explizit setzen
- nach erfolgreichem Import bleibt PostgreSQL die operative Wahrheit

## 69.13 Zusammenfassung

FK-69 definiert die operative Mittelschicht zwischen:

- kanonischem Laufzeitstate (`StoryContext`, `phase_state_projection`,
  `execution_events`, `artifact_records`)
- und analytischen Rollups/Facts (FK-60 bis FK-63)

Damit bleiben QA-, Story- und Failure-Corpus-Daten querybar, ohne
erneut in ein dateibasiertes Parallelmodell wie in AK2 zurueckzufallen.

## 69.14 Beziehung zu kpi-and-dashboard (FK-63)

`telemetry-and-events.ProjectionAccessor` und `kpi-and-dashboard.Dashboard`
(FK-63) erfullen **komplementaere, nicht konkurrierende Rollen**:

| Schicht | Verantwortliche Komponente | Zweck |
|---------|---------------------------|-------|
| DB-Zugriffsschicht | `telemetry-and-events.ProjectionAccessor` (`agentkit.backend.telemetry.projection_accessor`) | Lesen und Schreiben operativer Read-Models; keine Sicht-Semantik |
| Sicht-Schicht | `kpi-and-dashboard.Dashboard` (`agentkit.backend.kpi_analytics`, FK-63) | Visualisierung periodischer KPI-Rollups; liest aus analytics-Facts |

`ProjectionAccessor` ist kein Dashboard. `Dashboard` greift nicht direkt
auf operative Read-Models zu, sondern konsumiert periodisch aggregierte
Fact-Tabellen aus `kpi-and-dashboard.FactStore`.

**Datenfluss:**

```
execution_events
    -> ProjectionAccessor (write_projection)
       -> qa_stage_results, story_metrics, fc_*, phase_state_projection
          -> KpiAnalytics.RefreshWorker (read_projection)
             -> FactStore (analytics-Tabellen)
                -> Dashboard (Sicht)
```

Dieser Fluss stellt sicher, dass telemetry-and-events nie direkt
in Dashboard-Logik eingreift und kpi-and-dashboard nie operative
Read-Models umgeht.
