---
concept_id: FK-62
title: KPI-Aggregation
module: kpi-aggregation
status: active
doc_kind: core
parent_concept_id:
authority_over:
  - scope: kpi-aggregation
defers_to:
  - target: FK-60
    scope: kpi-catalog
    reason: KPI definitions, formulas, and granularity defined in FK-60
  - target: FK-61
    scope: kpi-collection
    reason: Data collection points and event sources defined in FK-61
supersedes: []
superseded_by:
tags: [kpi, aggregation, fact-tables, refresh-worker, postgres]
---

# 62 — KPI-Aggregation

## 62.1 Zweck

Dieses Dokument definiert das Datenmodell der Analytics-Schicht im
PostgreSQL-Schema `analytics`, die Berechnungslogik des
Refresh-Workers und die Schema-Migrations-Strategie.

Es ist das dritte Dokument des Analytics-Blocks (FK-60 bis FK-63).

---

## 62.2 Fact-Tabellen — Schema

Alle Tabellen liegen im zentralen PostgreSQL-Store.
Primaerschluessel sind natuerliche Schluessel, keine Surrogate.

**Mandantenregel:** Jede Fact- oder Scratchpad-Tabelle traegt
`project_key` als fuehrenden Scope-Schluessel. Analytics ist damit
pro Projekt isolierbar, obwohl die Datenbankinstanz zentral ist.

### 62.2.1 fact_story

Koernung: 1 Zeile pro abgeschlossener Story. Wird bei Story-Closure
geschrieben oder aktualisiert.

```sql
CREATE TABLE fact_story (
    project_key                 TEXT NOT NULL,
    story_id                    TEXT NOT NULL,
    story_type                  TEXT NOT NULL,
    story_size                  TEXT NOT NULL,
    pipeline_mode               TEXT NOT NULL,
    opened_at                   TEXT,
    closed_at                   TEXT,

    -- Domaene 1: Story-Dimensionierung
    processing_time_ms          INTEGER,
    compaction_count            INTEGER NOT NULL DEFAULT 0,
    qa_round_count              INTEGER NOT NULL DEFAULT 0,
    feedback_converged          INTEGER NOT NULL DEFAULT 0,
    blocked_ac_count            INTEGER NOT NULL DEFAULT 0,
    blocked_ac_detail_json      TEXT,

    -- Domaene 2: LLM-Selektion
    llm_call_count              INTEGER NOT NULL DEFAULT 0,

    -- Domaene 5: QA-Effektivitaet
    adversarial_findings_count  INTEGER NOT NULL DEFAULT 0,
    adversarial_tests_created   INTEGER NOT NULL DEFAULT 0,
    adversarial_hit_rate        REAL,
    findings_fully_resolved     INTEGER NOT NULL DEFAULT 0,
    findings_partially_resolved INTEGER NOT NULL DEFAULT 0,
    findings_not_resolved       INTEGER NOT NULL DEFAULT 0,

    -- Status (auch fuer eskalierte/pausierte Stories)
    final_status                TEXT,

    -- Domaene 8: ARE
    are_gate_passed             INTEGER,
    are_total_requirements      INTEGER,
    are_covered_requirements    INTEGER,

    -- Domaene 10: Prozess-Effizienz
    files_changed               INTEGER NOT NULL DEFAULT 0,
    increment_count             INTEGER NOT NULL DEFAULT 0,
    phase_setup_ms              INTEGER,
    phase_exploration_ms        INTEGER,
    phase_implementation_ms     INTEGER,
    phase_verify_ms             INTEGER,
    phase_closure_ms            INTEGER,

    -- Meta
    computed_at                 TEXT NOT NULL,
    PRIMARY KEY (project_key, story_id)
);
```

### 62.2.2 fact_guard_period

Koernung: 1 Zeile pro Guard pro Woche.

```sql
CREATE TABLE fact_guard_period (
    project_key                 TEXT NOT NULL,
    guard_key                   TEXT NOT NULL,
    period_start                TEXT NOT NULL,
    period_grain                TEXT NOT NULL DEFAULT 'week',

    -- Domaene 3: Governance
    invocation_count            INTEGER NOT NULL DEFAULT 0,
    violation_count             INTEGER NOT NULL DEFAULT 0,
    violation_rate              REAL,
    violation_stage_escape      INTEGER NOT NULL DEFAULT 0,
    violation_stage_schema      INTEGER NOT NULL DEFAULT 0,
    violation_stage_template    INTEGER NOT NULL DEFAULT 0,
    escape_detection_count      INTEGER NOT NULL DEFAULT 0,

    -- Meta
    computed_at                 TEXT NOT NULL,

    PRIMARY KEY (project_key, guard_key, period_start)
);
```

### 62.2.3 fact_pool_period

Koernung: 1 Zeile pro LLM-Pool pro Woche.

```sql
CREATE TABLE fact_pool_period (
    project_key                 TEXT NOT NULL,
    pool_key                    TEXT NOT NULL,
    period_start                TEXT NOT NULL,
    period_grain                TEXT NOT NULL DEFAULT 'week',

    -- Domaene 2: LLM-Performance
    call_count                  INTEGER NOT NULL DEFAULT 0,
    response_time_p50_ms        INTEGER,
    -- response_time_p95_ms: INVENTAR, wird bei Aktivierung ergaenzt
    verdict_adopted_count       INTEGER NOT NULL DEFAULT 0,
    verdict_total_count         INTEGER NOT NULL DEFAULT 0,
    finding_true_positive_count INTEGER NOT NULL DEFAULT 0,
    finding_false_positive_count INTEGER NOT NULL DEFAULT 0,
    quorum_triggered_count      INTEGER NOT NULL DEFAULT 0,

    -- Domaene 6: Review-Qualitaet
    template_finding_rate_json  TEXT,

    -- Meta
    computed_at                 TEXT NOT NULL,

    PRIMARY KEY (project_key, pool_key, period_start)
);
```

### 62.2.4 fact_pipeline_period

Koernung: 1 Zeile pro Woche (globale Prozess-KPIs).

```sql
CREATE TABLE fact_pipeline_period (
    project_key                 TEXT NOT NULL,
    period_start                TEXT NOT NULL,
    period_grain                TEXT NOT NULL DEFAULT 'week',

    -- Domaene 1: Story-Dimensionierung
    story_count                 INTEGER NOT NULL DEFAULT 0,
    story_count_closed          INTEGER NOT NULL DEFAULT 0,
    execution_count             INTEGER NOT NULL DEFAULT 0,
    exploration_count           INTEGER NOT NULL DEFAULT 0,
    stage_miss_count            INTEGER NOT NULL DEFAULT 0,
    stage_miss_detail_json      TEXT,

    -- Domaene 3: Governance
    impact_violation_count      INTEGER NOT NULL DEFAULT 0,
    impact_check_count          INTEGER NOT NULL DEFAULT 0,
    integrity_gate_block_count  INTEGER NOT NULL DEFAULT 0,
    integrity_gate_total_count  INTEGER NOT NULL DEFAULT 0,

    -- Domaene 4: Dokumententreue
    doc_fidelity_conflict_by_level_json TEXT,

    -- Domaene 5: QA-Effektivitaet
    first_pass_count            INTEGER NOT NULL DEFAULT 0,
    finding_survival_count      INTEGER NOT NULL DEFAULT 0,
    finding_total_count         INTEGER NOT NULL DEFAULT 0,
    effective_check_ids_json    TEXT,

    -- Domaene 7: VektorDB
    vectordb_total_hits         INTEGER NOT NULL DEFAULT 0,
    vectordb_above_threshold    INTEGER NOT NULL DEFAULT 0,
    vectordb_classified_conflict INTEGER NOT NULL DEFAULT 0,
    vectordb_duplicate_detected INTEGER NOT NULL DEFAULT 0,

    -- Domaene 10: Prozess-Effizienz
    processing_time_avg_ms      INTEGER,
    processing_time_variance_ms2 REAL,
    qa_round_avg                REAL,

    -- Meta
    computed_at                 TEXT NOT NULL,
    PRIMARY KEY (project_key, period_start)
);
```

### 62.2.5 fact_corpus_period

Koernung: 1 Zeile pro Monat.

```sql
CREATE TABLE fact_corpus_period (
    project_key                 TEXT NOT NULL,
    period_start                TEXT NOT NULL,
    period_grain                TEXT NOT NULL DEFAULT 'month',

    -- Domaene 9: Failure Corpus
    new_incident_count          INTEGER NOT NULL DEFAULT 0,
    patterns_total_count        INTEGER NOT NULL DEFAULT 0,
    patterns_with_active_check  INTEGER NOT NULL DEFAULT 0,

    -- Meta
    computed_at                 TEXT NOT NULL,
    PRIMARY KEY (project_key, period_start)
);
```

### 62.2.6 guard_invocation_counters (im Runtime-Schema, nicht im Analytics-Schema)

Scratchpad-Tabelle fuer Guard-Invokations-Zaehler. Liegt in
`runtime.guard_invocation_counters` (nicht im Analytics-Schema),
weil sie vom Hook-Hot-Path
geschrieben wird. Siehe FK-61 §61.4.3 fuer Design-Begruendung.

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

Der Refresh-Worker liest diese Tabelle, uebertraegt die Werte
in `analytics.fact_guard_period` und loescht die verarbeiteten
Eintraege.

### 62.2.7 sync_state

```sql
CREATE TABLE sync_state (
    project_key TEXT NOT NULL,
    key         TEXT NOT NULL,
    value_int   INTEGER,
    value_text  TEXT,
    updated_at  TEXT NOT NULL,
    PRIMARY KEY (project_key, key)
);
```

Eintraege:
- `last_event_id` (monotoner Cursor ueber `events.id`)
- `last_synced_at` (ISO 8601)

Jeder Sync-Cursor ist projektbezogen. Es gibt keinen globalen
Refresh-Zeiger ueber alle Projekte hinweg.

---

## 62.3 Refresh-Worker

### 62.3.1 Ausloeser

Kein Daemon, kein Cron. Zwei event-getriebene Trigger:

1. **Story-Closure** (primaer): `sync_analytics(trigger='closure',
   hint_story_id='BB2-056')` wird am Ende der Closure-Phase
   aufgerufen, nach MetricsCollector und JSONL-Export.
2. **Dashboard-Start** (Catch-up): `sync_analytics(trigger='dashboard')`
   wird beim Start von `agentkit dashboard` aufgerufen. Bei Lock
   auf dem Analytics-Schema wird mit vorhandenem Stand gestartet.

### 62.3.2 Ablauf

```python
def sync_analytics(
    trigger: str,
    hint_story_id: str | None = None,
    client,
) -> SyncResult:
    """Idempotenter Repair-Worker: Delta lesen, Dirty Sets
    ableiten, betroffene Slices komplett neu berechnen."""

    # 1. Read-Snapshot + Write-Transaktion vorbereiten
    runtime_snapshot = client.open_runtime_snapshot()
    analytics_tx = client.open_analytics_transaction()

    # 2. Cursor lesen
    last_event_id = _read_sync_cursor(analytics_tx)

    # 3. Watermark bestimmen (konsistenter Snapshot)
    watermark = _get_watermark(runtime_snapshot)
    if watermark <= last_event_id:
        return SyncResult(status="up_to_date")

    # 4. Delta-Events lesen
    delta_events = _read_delta(runtime_snapshot, last_event_id, watermark)

    # 5. Dirty Sets ableiten
    dirty = _derive_dirty_sets(delta_events, hint_story_id)

    # 6. Fuer jedes Dirty Set: Slices komplett neu berechnen
    new_facts = _recompute_all(runtime_snapshot, dirty)

    # 7. Atomare Transaktion auf dem Analytics-Schema
    try:
        _upsert_fact_story(analytics_tx, new_facts.stories)
        _replace_fact_guard_period(analytics_tx, new_facts.guards)
        _replace_fact_pool_period(analytics_tx, new_facts.pools)
        _replace_fact_pipeline_period(analytics_tx, new_facts.pipeline)
        _replace_fact_corpus_period(analytics_tx, new_facts.corpus)
        _update_sync_cursor(analytics_tx, watermark)
        analytics_tx.commit()
    except Exception:
        analytics_tx.rollback()
        raise

    return SyncResult(
        status="synced",
        events_processed=len(delta_events),
        watermark=watermark,
    )
```

### 62.3.3 Dirty Sets

Dirty Sets werden aus zwei Quellen abgeleitet: Delta-Events im
Runtime-Schema UND dem Closure-Hint (hint_story_id). Nicht alle KPIs
basieren auf Events — einige lesen aus Raw-Tabellen
(`qa_findings`, `fc_incidents`) oder Pipeline-Artefakten
(`context.json`, `phase-state.json`). Diese Nicht-Event-Quellen
werden nur bei Story-Closure konsistent, deshalb ist Closure der
primaere Sync-Trigger.

| Dirty Set | Abgeleitet aus | Typ | Hinweis |
|-----------|---------------|-----|---------|
| `dirty_story_ids` | `(project_key, story_id)` aus Delta-Events + `hint_story_id` | `set[tuple[str, str]]` | Story-Facts lesen auch aus Pipeline-Artefakten — diese sind nur bei Closure finalisiert |
| `dirty_guard_weeks` | `(project_key, guard_key, week_start(ts))` aus `integrity_violation` und Guard-Scratchpad | `set[tuple[str, str, str]]` | Rein runtime-basiert, konsistent |
| `dirty_pool_weeks` | `(project_key, pool_key, week_start(ts))` aus `llm_call` / `review_*` Events | `set[tuple[str, str, str]]` | Rein event-basiert, konsistent |
| `dirty_pipeline_weeks` | `(project_key, week_start(ts))` aus allen Delta-Events + `week_start(closed_at)` der hint_story | `set[tuple[str, str]]` | Schliesst die Woche der gerade geschlossenen Story ein |
| `dirty_corpus_months` | Immer `(project_key, current_month)` bei jedem Sync | `set[tuple[str, str]]` | FC-Tabellen (`fc_incidents`, `fc_patterns`) haben keinen Event-Cursor — Corpus-Perioden werden bei jedem Sync fuer den aktuellen Monat komplett neu berechnet |

**Begruendung fuer den Corpus-Sonderfall**: `fc_incidents` und
`fc_patterns` werden nicht ueber die `events`-Tabelle getrackt.
Sie sind eigenstaendige Tabellen im Runtime-Schema, die durch den
Failure-Corpus-Lifecycle (FK-41) befuellt werden. Da das Volumen
gering ist (Ziel: <20 Incidents/Monat) und die Koernung monatlich
ist, ist ein Full-Recompute des aktuellen Monats bei jedem
Sync-Lauf vertretbar.

### 62.3.4 Slice-Neuberechnung

Pro Dirty Set wird der betroffene Slice **komplett aus dem Runtime-Schema
neu berechnet**, nicht inkrementell hochgezaehlt.

Beispiel `fact_story` fuer eine dirty Story:
```python
def _compute_fact_story(runtime_snapshot, project_key: str, story_id: str) -> FactStoryRow:
    # Liest story_metrics, qa_findings, context.json,
    # phase-state.json, events fuer diese Story
    # Berechnet alle Spalten frisch
    # Berechnet adversarial_hit_rate als Division
    # Kein Carry-Over von vorherigen Werten
    ...
```

Beispiel `fact_pool_period` fuer eine dirty Pool-Woche:
```python
def _compute_fact_pool_period(
    runtime_snapshot, project_key: str, pool_key: str, week_start: str,
) -> FactPoolPeriodRow:
    # Liest ALLE Events dieser Woche fuer diesen Pool
    # Berechnet response_time_p50/p95 in Python:
    times = [row.duration_ms for row in ...]
    p50 = _percentile(times, 50)
    p95 = _percentile(times, 95)
    # Zaehlt Verdicts, Findings, Quorum-Triggers
    ...
```

### 62.3.5 Perzentil-Berechnung

```python
def _percentile(values: list[float], p: int) -> float | None:
    """Berechnet Perzentil ohne externe Abhaengigkeit."""
    if not values:
        return None
    sorted_vals = sorted(values)
    k = (len(sorted_vals) - 1) * (p / 100)
    f = int(k)
    c = f + 1
    if c >= len(sorted_vals):
        return sorted_vals[f]
    return sorted_vals[f] + (k - f) * (sorted_vals[c] - sorted_vals[f])
```

Keine numpy/scipy-Abhaengigkeit. Fuer unser Volumen
(10-100 Werte pro Slice) ist die lineare Interpolation
ausreichend.

### 62.3.6 Crash-Sicherheit

- Read-Snapshot auf dem Runtime-Schema fuer den gesamten Sync-Lauf
- Write-Transaktion auf dem Analytics-Schema vor allen Writes
- Cursor (`sync_state.last_event_id`) wird als letzter Schritt
  innerhalb derselben Transaktion aktualisiert
- Bei Crash vor COMMIT: Nichts sichtbar. Naechster Lauf
  verarbeitet denselben Delta-Bereich erneut (idempotent)
- Kein Cross-DB-Commit erforderlich

**Einschraenkung**: Die Konsistenz zwischen Runtime-Schema und
Pipeline-Artefakten (Dateisystem) ist nicht transaktional
gesichert. Der Refresh-Worker geht davon aus, dass
Artefakte bei Story-Closure finalisiert sind und sich danach
nicht mehr aendern. Fuer laufende Stories gibt es keine
Garantie — deshalb erscheinen laufende Stories nicht in
den Fact-Tabellen.

### 62.3.7 Eskalierte und pausierte Stories (Survivorship-Bias)

**Problem**: Stories die in `ESCALATED` oder `PAUSED` verharren,
werden nie geschlossen. `sync_analytics(trigger='closure')` feuert
nicht. `fact_story` bleibt leer. Trend-KPIs wie
`processing_time_trend` oder `qa_round_trend` werden systematisch
verzerrt, weil nur erfolgreiche Stories gemessen werden.

**Loesung**: Der Dashboard-Catch-up-Sync (`trigger='dashboard'`)
materialisiert auch nicht-geschlossene Stories:

1. Identifiziere alle `(project_key, story_id)` mit Events im Runtime-Schema,
   die KEINEN `fact_story`-Eintrag im Analytics-Schema haben
2. Fuer diese Stories: `fact_story` mit den verfuegbaren Daten
   befuellen (Laufzeit bis jetzt, QA-Runden bis jetzt, etc.)
3. `final_status` = `'RUNNING'`, `'ESCALATED'` oder `'PAUSED'`
   (abgeleitet aus `phase-state.json`)
4. Bei spaeterer Closure wird der Eintrag per UPSERT aktualisiert

**Konsequenz fuer Trend-KPIs**: Perioden-Aggregationen in
`fact_pipeline_period` koennen `final_status`-Filter anbieten:
- `story_count` = alle Stories (inkl. eskalierte)
- `story_count_closed` = nur erfolgreich geschlossene
- Raten (first_pass_rate, etc.) werden auf `closed` berechnet
- Absolute Zahlen (story_count, qa_round_avg) schliessen alle ein

---

## 62.4 Schema-Migration

### 62.4.1 Strategie

Neue KPIs werden als `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`
hinzugefuegt. PostgreSQL erlaubt damit idempotente Erweiterungen
ohne eigenen Dateidatenbank-Migrationspfad.

### 62.4.2 Idempotente Migration

```python
def _ensure_column(
    conn,
    table: str,
    column: str,
    col_type: str,
    default: str = "",
) -> None:
    """Fuegt Spalte hinzu wenn sie nicht existiert."""
    default_clause = f" DEFAULT {default}" if default else ""
    conn.execute(
        f"ALTER TABLE analytics.{table} "
        f"ADD COLUMN IF NOT EXISTS {column} {col_type}{default_clause}"
    )
```

### 62.4.3 Versionierung

`sync_state` enthaelt einen Eintrag `schema_version` (INTEGER).
Jede Migration prueft die aktuelle Version und fuehrt nur
fehlende Schritte aus.

---

## 62.5 Abgrenzung zu FK-16

FK-16 definiert die Raw-Spiegel-Tabellen (`qa_findings`,
`qa_stage_results`, `story_metrics`, `fc_*`) im Runtime-Schema.
Diese Tabellen sind **Eingabedaten** fuer den Refresh-Worker.

FK-62 definiert die **Ausgabedaten** (Fact-Tabellen im
Analytics-Schema). Es gibt keine Ueberschneidung:
das Runtime-Schema wird gelesen, das Analytics-Schema geschrieben.
