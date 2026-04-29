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
  - scope: failure-corpus-read-models
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

FK-69 autorisiert diese Tabellen:

- `qa_stage_results`
- `qa_findings`
- `story_metrics`
- `fc_incidents`
- `fc_patterns`
- `fc_check_proposals`

## 69.4 Schreib-Ownership

| Tabelle | Owner / Writer | Fachliche Rolle |
|---------|----------------|-----------------|
| `qa_stage_results` | `stage_registry` / Verify-Runner | Ergebnis je Stage und Attempt |
| `qa_findings` | `stage_registry` / jeweiliger Stage-Adapter | Atomare Findings je Check |
| `story_metrics` | Closure-Projektion | Story-nahe Abschlussmetriken |
| `fc_incidents` | `failure_corpus` | Laufende Incident-Erfassung |
| `fc_patterns` | `failure_corpus` | Pattern-Lifecycle |
| `fc_check_proposals` | `failure_corpus` | Check-Vorschlaege und Wirksamkeit |

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

### 69.6.1 Zweck

`qa_stage_results` speichert das Ergebnis einer einzelnen Verify-Stage
fuer genau einen Attempt einer Story.

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

### 69.7.1 Zweck

`qa_findings` macht einzelne Check-Befunde querybar, ohne das jeweilige
JSON-Artefakt parsen zu muessen.

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

### 69.8.1 Zweck

`story_metrics` haelt operative Abschlussmetriken pro Story-Run, die
fuer Story-Detailansichten und einfache Projektsteuerung benoetigt
werden, aber noch keine periodische KPI-Aggregation sind.

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

## 69.9 Failure Corpus

### 69.9.1 Tabelle `fc_incidents`

Reprasentiert einzelne Failure-Corpus-Incidents.

**Pflichtattribute:**

- `project_key`
- `incident_id`
- `story_id`
- `run_id`
- `category`
- `phase`
- `title`
- `status`
- `recorded_at`

**Fachregel:** Incidents sind operativ append-only, solange die
zugrunde liegende Story-Umsetzung gueltig bleibt. Wird diese
vollstaendig zurueckgesetzt, werden die zugehoerigen
`fc_incidents` entfernt. Statusaenderungen einer gueltigen Umsetzung
erfolgen ueber neue Lifecycle-Felder oder Nachfolgerecords, nicht ueber
stilles Umschreiben der Evidenz.

### 69.9.2 Tabelle `fc_patterns`

Reprasentiert verdichtete Pattern-Kandidaten und bestaetigte Pattern.

**Pflichtattribute:**

- `project_key`
- `pattern_id`
- `category`
- `invariant`
- `status`
- `incident_count`
- `updated_at`

**Fachregel:** `incident_count` ist eine bewusst denormalisierte,
rebuildbare Projektion aus Incident-Zuordnungen. Nach einem
vollstaendigen Story-Reset muessen betroffene Pattern-Projektionen neu
berechnet oder gezielt korrigiert werden; ein zurueckgesetzter Run darf
nicht weiter in `incident_count` oder `status` hineinwirken.

### 69.9.3 Tabelle `fc_check_proposals`

Reprasentiert deterministische Check-Vorschlaege und deren
Wirksamkeitsbeobachtung.

**Pflichtattribute:**

- `project_key`
- `check_id`
- `pattern_ref`
- `status`
- `check_type`
- `pipeline_stage`
- `pipeline_layer`
- `true_positives`
- `false_positives`
- `no_findings`
- `updated_at`

**Fachregel:** Wirksamkeitszaehler gehoeren zu diesem Proposal und
werden nicht als separates Faktenschema modelliert.

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
