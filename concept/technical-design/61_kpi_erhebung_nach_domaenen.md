---
concept_id: FK-61
title: KPI-Erhebung nach Domaenen
module: kpi-collection
domain: kpi-and-dashboard
status: active
doc_kind: core
parent_concept_id:
authority_over:
  - scope: kpi-collection
defers_to:
  - target: FK-60
    scope: kpi-definitions
    reason: KPI names, formulas, granularity, and decision questions defined exclusively in FK-60
  - target: FK-68
    scope: event-infrastructure
    reason: Erhebungspunkte und neue Events bauen auf dem Event-Modell aus FK-68 auf
  - target: FK-21
    scope: story-creation
    reason: Story-Creation-Pipeline emittiert Erhebungs-Events fuer KPI-Domaenen wie VektorDB-Kalibrierung
  - target: FK-27
    scope: verify-and-closure
    reason: Verify-/Closure-Strecke ist eine zentrale Erhebungsdomaene fuer KPI-Events
  - target: FK-30
    scope: hook-infrastructure
    reason: Die Erhebung nutzt den FK-30 Hook-Mechanismus als Transport
  - target: FK-32
    scope: dokumententreue
    reason: Doc-Fidelity-Events stammen aus dem FK-32 Conformance-Service
  - target: FK-33
    scope: stage-registry
    reason: Required-Stage- und Impact-Violation-Erhebung referenziert die FK-33 Policy-Engine
  - target: FK-34
    scope: llm-evaluations
    reason: Finding-Resolution-Events werden vom StructuredEvaluator (FK-34) emittiert
supersedes: []
superseded_by:
tags: [kpi, collection, events, hooks, telemetry]
prose_anchor_policy: strict
formal_refs:
  - formal.telemetry-analytics.commands
  - formal.telemetry-analytics.events
  - formal.telemetry-analytics.invariants
---

# 61 — KPI-Erhebung nach Domaenen

<!-- PROSE-FORMAL: formal.telemetry-analytics.commands, formal.telemetry-analytics.events, formal.telemetry-analytics.invariants -->

## 61.1 Zweck

Dieses Dokument definiert fuer jede aktive KPI (siehe FK-60 §60.4)
den konkreten Erhebungspunkt: Welches Event speist die KPI, wo im
Prozess entsteht das Event, und welche Aenderungen an Hooks oder
Pipeline-Code sind noetig.

Es ist das zweite Dokument des Analytics-Blocks (FK-60 bis FK-63).

### 61.1.1 Legende

| Symbol | Bedeutung |
|--------|-----------|
| `[R]` | Rohdaten bereits vorhanden — KPI kann aus bestehenden Events abgeleitet werden |
| `[N]` | Neues Event oder angereichertes Payload noetig |
| `→ fact_*` | Ziel-Fact-Tabelle im Analytics-Schema (FK-62) |

### 61.1.2 Authority-Split (Erinnerung)

Dieses Dokument beschreibt WO und WANN Daten entstehen. Die
KPI-Definition (Name, Formel, Koernung, Entscheidungsfrage) steht
ausschliesslich in FK-60. Domain-FKs (FK-27, FK-30, FK-34, etc.)
beschreiben das Laufzeitverhalten, aus dem Events entstehen — sie
werden hier referenziert, nicht dupliziert.

**Projekt-Scope-Regel:** Alle Erhebungspunkte schreiben oder lesen
kanonische Daten immer unter `project_key`. KPI-Formeln koennen
weiterhin von `story_id`, `guard_key` oder `pool_key` sprechen, die
physische Speicherung im Runtime-/Analytics-Schema ist jedoch immer
projektgebunden.

**Reset-Regel:** Eine vollstaendig zurueckgesetzte Story-Umsetzung gilt
fuer FK-61 als ungueltige Quelle. Ihre `execution_events`,
Read-Models und daraus abgeleiteten KPI-Beitraege sind aktiv zu
entfernen oder bei der naechsten Aggregation neu zu berechnen. Ein
spaeteres Herausfiltern in einzelnen KPI-Queries ist unzulaessig.

---

## 61.2 Domaene 1 — Story-Dimensionierung

### 61.2.1 Bereits erhebbar [R]

| KPI | Quelle | Erhebungspunkt | Ziel |
|-----|--------|----------------|------|
| `qa_round_count` | `story_metrics.qa_rounds` | Bereits bei Closure durch `MetricsCollector` berechnet | → `fact_story.qa_round_count` |
| `processing_time_by_type_and_size` | `story_metrics.processing_time_min` + `story_contexts` / `StoryContext` (story_type, story_size) | Bereits bei Closure berechnet | → `fact_story.processing_time_ms`, `fact_story.story_type`, `fact_story.story_size` |
| `feedback_loop_convergence` | Read-Model ueber `artifact_records` der Verify-Runden, verglichen ueber `attempt_no` | Findings pro Runde aus den Verify-Artefakten je `(project_key, story_id, run_id)`. Convergence = Findings(N+1) < Findings(N) | → `fact_story.feedback_converged` (boolean) |
| `blocked_ac_distribution` | `handover.json` → `blocked_acs` Feld | Gelesen bei Closure aus dem Handover-Artefakt | → `fact_story.blocked_ac_count`, Payload in `fact_story.blocked_ac_detail_json` |
| `policy_required_stage_miss_rate` | `decision.json` → fehlende Required-Stages | Policy-Engine (FK-33) prueft Required Stages. Fehlende werden in `decision.json` dokumentiert | → `fact_pipeline_period.stage_miss_count`, `fact_pipeline_period.stage_miss_detail_json` |

### 61.2.2 Neu zu erheben [N]

| KPI | Neues Event / Payload | Erhebungspunkt | Aenderung |
|-----|----------------------|----------------|-----------|
| `compaction_count_per_story` | **Neues Event**: `compaction_event` im Scope `(project_key, story_id, run_id)` | PostCompact-Hook (`epoch_writer.py`) schreibt bereits Epoch-Counter. Zusaetzlich wird ein `compaction_event` in `execution_events` geschrieben. | → `fact_story.compaction_count` |
| `execution_vs_exploration_ratio` | Kein neues Event noetig. `runtime.story_metrics.mode` enthaelt den Wert (execution/exploration/not_applicable). Wird bei Closure durch `upsert_workflow_metrics()` geschrieben. | Refresh-Worker liest `runtime.story_metrics.mode` | → `fact_story.pipeline_mode`, aggregiert in `fact_pipeline_period.execution_count`, `fact_pipeline_period.exploration_count` |

**Fachregel:** `story_metrics` aus vollstaendig zurueckgesetzten Runs
duerfen nicht in `fact_story` oder periodische Pipeline-KPIs
einfließen.

---

## 61.3 Domaene 2 — LLM-Selektion

### 61.3.1 Bereits erhebbar [R]

| KPI | Quelle | Erhebungspunkt | Ziel |
|-----|--------|----------------|------|
| `llm_response_time_p50` | Zeitstempel-Delta: `review_request.occurred_at` → `review_response.occurred_at` pro `pool` | Events existieren bereits. Refresh-Worker berechnet Perzentile in Python | → `fact_pool_period.response_time_p50_ms` |
| `llm_call_count_per_story` | `COUNT(execution_events WHERE project_key = ? AND story_id = ? AND event_type = 'llm_call')` | Events existieren bereits | → `fact_story.llm_call_count` |

### 61.3.2 Neu zu erheben [N]

| KPI | Neues Event / Payload | Erhebungspunkt | Aenderung |
|-----|----------------------|----------------|-----------|
| `llm_verdict_adoption_rate` | Neues Feld in `review_response` Payload: `verdict` (PASS/PASS_WITH_CONCERNS/REWORK/FAIL). Neues Feld in Policy-Decision: `adopted_verdicts[]` mit Pool-Zuordnung. | `review_guard.py` extrahiert Verdict aus LLM-Antwort. Policy-Engine dokumentiert welche Verdicts uebernommen wurden. | → `fact_pool_period.verdict_adopted_count`, `fact_pool_period.verdict_total_count` |
| `llm_finding_precision` | Korrelation: Finding aus `qa_findings` (source_agent = Pool-Name) gegen Finding-Status in naechster Runde (resolved/survived). | Refresh-Worker korreliert Findings ueber Runden hinweg | → `fact_pool_period.finding_true_positive_count`, `fact_pool_period.finding_false_positive_count` |
| `quorum_trigger_rate` | Neues Event `review_divergence` existiert bereits (FK-68). Payload hat `quorum_triggered` Flag. | `divergence.py` emittiert bereits. Refresh-Worker aggregiert | → `fact_pool_period.quorum_triggered_count` |

---

## 61.4 Domaene 3 — Governance

### 61.4.1 Bereits erhebbar [R]

| KPI | Quelle | Erhebungspunkt | Ziel |
|-----|--------|----------------|------|
| `guard_violation_count_by_type` | `execution_events WHERE event_type = 'integrity_violation'`, Payload-Feld `guard` | Events existieren. Gruppierung nach `guard`-Feld | → `fact_guard_period.violation_count` |

### 61.4.2 Neu zu erheben [N]

| KPI | Neues Event / Payload | Erhebungspunkt | Aenderung |
|-----|----------------------|----------------|-----------|
| `guard_violation_rate_by_guard` | **Kein Event** — Scratchpad-Counter statt High-Volume-Events. Siehe §61.4.3. | Jeder Guard-Hook inkrementiert einen UPSERT-Counter in `runtime.guard_invocation_counters`. Bei Closure und Week-Rollover wird der Counter in die Analytics-Schicht uebernommen. | → `fact_guard_period.invocation_count`, `fact_guard_period.violation_rate` (= blocks/invocations) |
| `prompt_integrity_violation_by_stage` | Angereichertes Payload im `integrity_violation` Event: neues Feld `stage` (escape_detection / schema_validation / template_integrity). | `prompt_integrity_guard.py` setzt das `stage`-Feld je nachdem welche Pruefstufe den Block ausgeloest hat | → `fact_guard_period.violation_stage_escape_count`, `...schema_count`, `...template_count` |
| `governance_escape_detection_count` | Teilmenge von `prompt_integrity_violation_by_stage` WHERE `stage = 'escape_detection'` | Keine separate Erhebung — wird aus dem angereicherten Payload abgeleitet | → `fact_guard_period.escape_detection_count` (Subset) |
| `orchestrator_governance_violation_count` | Teilmenge von `guard_violation_count_by_type` WHERE `guard = 'orchestrator_guard'` | Keine separate Erhebung — wird aus bestehenden Events gefiltert | → `fact_guard_period.violation_count` WHERE `guard_key = 'orchestrator_guard'` |
| `impact_violation_rate` | **Neues Event**: `impact_violation_check` mit Feldern `declared_impact`, `actual_impact`, `result` (pass/violation). | Structural Check in Verify-Phase (FK-33). Der Impact-Violation-Check vergleicht deklarierte und tatsaechliche Impact-Stufe. | → `fact_pipeline_period.impact_violation_count`, `fact_pipeline_period.impact_check_count` |
| `integrity_gate_block_rate` | **Neues Event**: `integrity_gate_result` existiert bereits. Angereichertes Payload: `blocked_dimensions[]` (Liste der fehlgeschlagenen Dimensionen). | `integrity.py` bei Gate-Evaluation. Das Event existiert, aber das Payload braucht die Dimensionen-Aufschluesselung. | → `fact_pipeline_period.integrity_gate_block_count`, `fact_pipeline_period.integrity_gate_total_count` |

### 61.4.3 Guard-Invocation-Counter (Scratchpad-Architektur)

**Problem**: Guards feuern bei jedem Tool-Call (PreToolUse).
Bei 5 aktiven Guards und 500-2000 Tool-Calls/Story waeren das
2500-10000 `guard_invocation` Events PRO STORY — ca. 1.2 Mio.
Events/Jahr. Das ueberschreitet die Volumenabschaetzung
(FK-60 §60.3) um Faktor 12-120 und gefaehrdet die
Hot-Path-Latenz.

**Loesung**: Kein `guard_invocation` Event-Typ. Stattdessen eine
leichtgewichtige Scratchpad-Tabelle im Runtime-Schema:

```sql
CREATE TABLE guard_invocation_counters (
    project_key TEXT NOT NULL,
    story_id    TEXT NOT NULL,
    guard_key   TEXT NOT NULL,
    week_start  TEXT NOT NULL,
    invocations INTEGER NOT NULL DEFAULT 0,
    blocks      INTEGER NOT NULL DEFAULT 0,
    updated_at  TEXT NOT NULL,
    PRIMARY KEY (project_key, story_id, guard_key, week_start)
);
```

**Hot Path**: Jeder Guard-Hook fuehrt am Ende (vor `sys.exit()`)
ein einzelnes UPSERT aus:

```python
INSERT INTO guard_invocation_counters
    (project_key, story_id, guard_key, week_start, invocations, blocks, updated_at)
VALUES ($1, $2, $3, $4, 1, $5, CURRENT_TIMESTAMP)
ON CONFLICT(project_key, story_id, guard_key, week_start) DO UPDATE SET
    invocations = invocations + 1,
    blocks = blocks + EXCLUDED.blocks,
    updated_at = CURRENT_TIMESTAMP;
```

Latenz: ~0.05-0.1ms pro UPSERT. Kein Volumen-Problem
(5-10 Rows/Story statt 5000 Events).

**Flush-Strategie**:
- **Closure**: `sync_analytics()` liest Counter, schreibt in
  `fact_guard_period`, loescht Counter der betroffenen Story.
- **Week-Rollover**: Wenn ein Hook eine neue Woche erkennt,
  koennen aeltere Wochenbuckets derselben Story geflusht werden.
- **Housekeeping**: Counter aelter als 24h ohne Update werden
  geflusht (fuer abgebrochene/eskalierende Stories).
- **Vollstaendiger Story-Reset**: Counter des betroffenen `run_id`
  beziehungsweise `story_id` werden purgt und ihre bereits in
  `fact_guard_period` eingerechneten Beitraege muessen neu
  aggregiert werden.

**Audit bleibt intakt**: `integrity_violation` Events (exit 2)
werden weiterhin in `execution_events` geschrieben. Der
Scratchpad-Counter ersetzt nur die Volumen-KPI (Nenner der
Violation-Rate), nicht den Audit-Trail.

**Sparring-Referenz**: Dieses Design entstand aus einem
3-LLM-Sparring (Claude + ChatGPT + Qwen). Alle drei
konvergierten auf Counter-statt-Events. ChatGPT schlug
die Wochen-Granularitaet im Key vor, Qwen das UPSERT-Pattern
und `WITHOUT ROWID`.

---

## 61.5 Domaene 4 — Dokumententreue

### 61.5.1 Neu zu erheben [N]

| KPI | Neues Event / Payload | Erhebungspunkt | Aenderung |
|-----|----------------------|----------------|-----------|
| `doc_fidelity_conflict_rate_by_level` | **Neues Event**: `doc_fidelity_check` mit Feldern `level` (goal_fidelity / design_fidelity / implementation_fidelity / feedback_fidelity), `result` (pass/conflict/skipped). | Dokumententreue-Service (FK-32). Pro Pruefebene wird ein Event emittiert. Bei Concept/Research-Stories werden nicht-anwendbare Ebenen als `skipped` emittiert. | → `fact_pipeline_period.doc_fidelity_conflict_by_level_json` |

---

## 61.6 Domaene 5 — QA-Effektivitaet

### 61.6.1 Bereits erhebbar [R]

| KPI | Quelle | Erhebungspunkt | Ziel |
|-----|--------|----------------|------|
| `first_pass_success_rate` | `story_metrics.qa_rounds == 1` UND `story_metrics.final_status = 'PASS'` | Refresh-Worker berechnet Rate ueber abgeschlossene Stories der Periode | → `fact_pipeline_period.first_pass_count`, `fact_pipeline_period.story_count` |
| `finding_survival_rate` | `qa_findings` mit gleicher `check_id` ueber mehrere `attempt`-Werte derselben Story | Refresh-Worker vergleicht Findings ueber Runden | → `fact_pipeline_period.finding_survival_count`, `fact_pipeline_period.finding_total_count` |
| `check_effectiveness_by_id` | `qa_findings WHERE blocking = 1 GROUP BY check_id` | Refresh-Worker aggregiert | → `fact_pipeline_period.effective_check_ids_json` |
| `adversarial_hit_rate` | `story_metrics.adversarial_findings / story_metrics.adversarial_tests_created` | Refresh-Worker berechnet Ratio | → `fact_story.adversarial_hit_rate` |
| `adversarial_findings_count` | `story_metrics.adversarial_findings` | Bereits bei Closure erhoben | → `fact_story.adversarial_findings_count` (Spalte: `adversarial_findings_count`) |
| `adversarial_tests_created_count` | `story_metrics.adversarial_tests_created` | Bereits bei Closure erhoben | → `fact_story.adversarial_tests_created` |

### 61.6.2 Neu zu erheben [N]

| KPI | Neues Event / Payload | Erhebungspunkt | Aenderung |
|-----|----------------------|----------------|-----------|
| `finding_resolution_quality` | Neues Feld in Layer-2-Remediation-Output: `resolution_status` (fully_resolved / partially_resolved / not_resolved) pro Finding-ID. | StructuredEvaluator im Remediation-Modus (FK-34, DIV-Korrektur 1). Der Evaluator bewertet jedes Vorrunden-Finding. | → `fact_story.findings_fully_resolved`, `fact_story.findings_partially_resolved`, `fact_story.findings_not_resolved` |

---

## 61.7 Domaene 6 — Review-Qualitaet

### 61.7.1 Bereits erhebbar [R]

| KPI | Quelle | Erhebungspunkt | Ziel |
|-----|--------|----------------|------|
| `review_template_effectiveness` | `review_compliant` Events (Feld `template_name`) korreliert mit `qa_findings` (Findings pro Story pro Template) | Refresh-Worker korreliert Template-Nutzung mit Finding-Ausbeute | → `fact_pool_period.template_finding_rate_json` |

---

## 61.8 Domaene 7 — VektorDB

### 61.8.1 Neu zu erheben [N]

| KPI | Neues Event / Payload | Erhebungspunkt | Aenderung |
|-----|----------------------|----------------|-----------|
| `vectordb_similarity_threshold_calibration` | **Neues Event**: `vectordb_search` mit Feldern `total_hits`, `hits_above_threshold`, `hits_classified_conflict` (vom LLM), `threshold_value`. | Story-Creation-Pipeline (FK-21). Nach dem VektorDB-Abgleich wird das Event emittiert. Konzept 02 §2.1 mandatiert diese Erhebung explizit. | → `fact_pipeline_period.vectordb_total_hits`, `...above_threshold`, `...classified_conflict` |
| `vectordb_duplicate_detection_rate` | Abgeleitet aus `vectordb_search`: `hits_classified_conflict > 0` | Teilmenge des obigen Events | → `fact_pipeline_period.vectordb_duplicate_detected` |

---

## 61.9 Domaene 8 — ARE

### 61.9.1 Bereits erhebbar [R]

| KPI | Quelle | Erhebungspunkt | Ziel |
|-----|--------|----------------|------|
| `are_gate_result` | `execution_events WHERE event_type = 'are_gate_result'`, Payload `result` (PASS/FAIL) | ARE-Telemetrie existiert (`are/telemetry.py`) | → `fact_story.are_gate_passed` (boolean) |

### 61.9.2 Neu zu erheben [N]

| KPI | Neues Event / Payload | Erhebungspunkt | Aenderung |
|-----|----------------------|----------------|-----------|
| `are_evidence_coverage_rate` | Angereichertes Payload im `are_gate_result` Event: `total_requirements`, `covered_requirements`, `uncovered_requirement_types[]`. | `are/telemetry.py` bei Gate-Evaluation. Die ARE-API liefert diese Daten bereits — sie muessen nur ins Event-Payload aufgenommen werden. | → `fact_story.are_total_requirements`, `fact_story.are_covered_requirements` |

---

## 61.10 Domaene 9 — Failure Corpus

### 61.10.1 Bereits erhebbar [R]

| KPI | Quelle | Erhebungspunkt | Ziel |
|-----|--------|----------------|------|
| `incident_volume_per_month` | `runtime.fc_incidents` Tabelle, `COUNT WHERE created_at >= month_start` | Refresh-Worker aggregiert aus dem Runtime-Schema | → `fact_corpus_period.new_incident_count` |
| `pattern_to_check_conversion_rate` | `fc_patterns` (status = 'check_active') / `fc_patterns` (total) | Refresh-Worker berechnet Ratio | → `fact_corpus_period.patterns_with_active_check`, `fact_corpus_period.patterns_total_count` |

**Fachregel:** Failure-Corpus-KPIs duerfen nur auf `fc_incidents` und
`fc_patterns` aus gueltigen, nicht vollstaendig zurueckgesetzten Runs
basieren.

---

## 61.11 Domaene 10 — Prozess-Effizienz

### 61.11.1 Bereits erhebbar [R]

| KPI | Quelle | Erhebungspunkt | Ziel |
|-----|--------|----------------|------|
| `processing_time_trend` | `story_metrics.processing_time_min` rollierender Durchschnitt | Refresh-Worker berechnet gleitenden Mittelwert ueber die letzten N Stories | → `fact_pipeline_period.processing_time_avg_ms` |
| `qa_round_trend` | `story_metrics.qa_rounds` rollierender Durchschnitt | Analog | → `fact_pipeline_period.qa_round_avg` |
| `files_changed_per_story` | `story_metrics.files_changed` | Bereits erhoben | → `fact_story.files_changed` |
| `increment_count_per_story` | `story_metrics.increments` | Bereits erhoben | → `fact_story.increment_count` |

### 61.11.2 Neu zu erheben [N]

| KPI | Neues Event / Payload | Erhebungspunkt | Aenderung |
|-----|----------------------|----------------|-----------|
| `phase_time_distribution` | Kein neues Event. `phase_state_projection` enthaelt Timestamps pro Phase (setup_started, implementation_started, verify_started, closure_started, closed_at). | Refresh-Worker liest `phase_state_projection` bei Story-Closure und berechnet Deltas | → `fact_story.phase_setup_ms`, `fact_story.phase_exploration_ms`, `fact_story.phase_implementation_ms`, `fact_story.phase_verify_ms`, `fact_story.phase_closure_ms` |
| `story_predictability` | Kein neues Event. Varianz der `processing_time_min` fuer Stories mit gleichem `(story_type, story_size)`. | Refresh-Worker berechnet Varianz in Python | → `fact_pipeline_period.processing_time_variance_ms2` |

---

## 61.12 Zusammenfassung der Aenderungen

### 61.12.1 Neue Event-Typen

| Event-Typ | Emittent | Hook/Prozess |
|-----------|----------|-------------|
| `impact_violation_check` | Structural Check | Verify-Phase Layer 1 |
| `doc_fidelity_check` | Dokumententreue-Service | Exploration/Verify-Phase |
| `vectordb_search` | Story-Creation-Pipeline | Story-Erstellung |
| `compaction_event` | PostCompact-Hook | PostCompact |

**Hinweis**: `guard_invocation` ist bewusst KEIN Event-Typ.
Guard-Invokationen werden ueber die Scratchpad-Tabelle
`guard_invocation_counters` erfasst (siehe §61.4.3), um das
Volumen in `execution_events` nicht um Faktor 12-120 zu
erhoehen.

### 61.12.2 Angereicherte Payloads (bestehende Events)

| Event-Typ | Neues Feld | Quelle |
|-----------|-----------|--------|
| `integrity_violation` | `stage` (fuer prompt_integrity_guard) | prompt_integrity_guard.py |
| `integrity_gate_result` | `blocked_dimensions[]` | integrity.py |
| `review_response` | `verdict` (PASS/REWORK/FAIL) | review_guard.py |
| `are_gate_result` | `total_requirements`, `covered_requirements` | are/telemetry.py |

### 61.12.3 Keine Aenderung noetig (nur Aggregation)

25 von 40 aktiven KPIs benoetigen keine neuen Events oder
Payload-Aenderungen. Sie werden ausschliesslich durch den
Refresh-Worker in FK-62 aus bestehenden Rohdaten abgeleitet.
15 KPIs benoetigen neue Event-Typen (5) oder angereicherte
Payloads (4) oder beides (6).
