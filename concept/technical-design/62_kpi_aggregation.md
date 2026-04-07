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
tags: [kpi, aggregation, fact-tables, refresh-worker, sqlite]
---

# 62 — KPI-Aggregation

## 62.1 Zweck

Dieses Dokument definiert das Datenmodell der Analytics-Schicht
(analytics.db), die Berechnungslogik des Refresh-Workers und die
Schema-Migrations-Strategie.

Es ist das dritte Dokument des Analytics-Blocks (FK-60 bis FK-63).

---

## 62.2 Fact-Tabellen — Schema

Alle Tabellen werden als `STRICT` angelegt (SQLite >= 3.37.0).
Primaerschluessel sind natuerliche Schluessel, keine Surrogate.

### 62.2.1 fact_story

Koernung: 1 Zeile pro abgeschlossener Story. Wird bei Story-Closure
geschrieben oder aktualisiert.

```sql
CREATE TABLE fact_story (
    story_id                    TEXT PRIMARY KEY,
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
    computed_at                 TEXT NOT NULL
) STRICT;
```

### 62.2.2 fact_guard_period

Koernung: 1 Zeile pro Guard pro Woche.

```sql
CREATE TABLE fact_guard_period (
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

    PRIMARY KEY (guard_key, period_start)
) STRICT;
```

### 62.2.3 fact_pool_period

Koernung: 1 Zeile pro LLM-Pool pro Woche.

```sql
CREATE TABLE fact_pool_period (
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

    PRIMARY KEY (pool_key, period_start)
) STRICT;
```

### 62.2.4 fact_pipeline_period

Koernung: 1 Zeile pro Woche (globale Prozess-KPIs).

```sql
CREATE TABLE fact_pipeline_period (
    period_start                TEXT PRIMARY KEY,
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
    computed_at                 TEXT NOT NULL
) STRICT;
```

### 62.2.5 fact_corpus_period

Koernung: 1 Zeile pro Monat.

```sql
CREATE TABLE fact_corpus_period (
    period_start                TEXT PRIMARY KEY,
    period_grain                TEXT NOT NULL DEFAULT 'month',

    -- Domaene 9: Failure Corpus
    new_incident_count          INTEGER NOT NULL DEFAULT 0,
    patterns_total_count        INTEGER NOT NULL DEFAULT 0,
    patterns_with_active_check  INTEGER NOT NULL DEFAULT 0,

    -- Meta
    computed_at                 TEXT NOT NULL
) STRICT;
```

### 62.2.6 guard_invocation_counters (in raw.db, nicht analytics.db)

Scratchpad-Tabelle fuer Guard-Invokations-Zaehler. Liegt in
**raw.db** (nicht analytics.db), weil sie vom Hook-Hot-Path
geschrieben wird. Siehe FK-61 §61.4.3 fuer Design-Begruendung.

```sql
CREATE TABLE guard_invocation_counters (
    story_id    TEXT NOT NULL,
    guard_key   TEXT NOT NULL,
    week_start  TEXT NOT NULL,
    invocations INTEGER NOT NULL DEFAULT 0,
    blocks      INTEGER NOT NULL DEFAULT 0,
    updated_at  TEXT NOT NULL,
    PRIMARY KEY (story_id, guard_key, week_start)
) WITHOUT ROWID;
```

Der Refresh-Worker liest diese Tabelle, uebertraegt die Werte
in `fact_guard_period` (analytics.db) und loescht die verarbeiteten
Eintraege.

### 62.2.7 sync_state

```sql
CREATE TABLE sync_state (
    key         TEXT PRIMARY KEY,
    value_int   INTEGER,
    value_text  TEXT,
    updated_at  TEXT NOT NULL
) STRICT;
```

Eintraege:
- `last_event_id` (monotoner Cursor ueber `events.id`)
- `last_synced_at` (ISO 8601)

---

## 62.3 Refresh-Worker

### 62.3.1 Ausloeser

Kein Daemon, kein Cron. Zwei event-getriebene Trigger:

1. **Story-Closure** (primaer): `sync_analytics(trigger='closure',
   hint_story_id='BB2-056')` wird am Ende der Closure-Phase
   aufgerufen, nach MetricsCollector und JSONL-Export.
2. **Dashboard-Start** (Catch-up): `sync_analytics(trigger='dashboard')`
   wird beim Start von `agentkit dashboard` aufgerufen. Bei Lock
   (analytics.db busy) wird mit vorhandenem Stand gestartet.

### 62.3.2 Ablauf

```python
def sync_analytics(
    trigger: str,
    hint_story_id: str | None = None,
    raw_db_path: str = RAW_DB_PATH,
    analytics_db_path: str = ANALYTICS_DB_PATH,
) -> SyncResult:
    """Idempotenter Repair-Worker: Delta lesen, Dirty Sets
    ableiten, betroffene Slices komplett neu berechnen."""

    # 1. Connections
    raw_conn = sqlite3.connect(raw_db_path, uri=True)
    raw_conn.execute("PRAGMA query_only = ON")
    raw_conn.execute("BEGIN")  # Expliziter Read-Snapshot
    analytics_conn = sqlite3.connect(analytics_db_path)
    analytics_conn.execute("PRAGMA busy_timeout = 5000")

    # 2. Cursor lesen
    last_event_id = _read_sync_cursor(analytics_conn)

    # 3. Watermark bestimmen (konsistenter Snapshot)
    watermark = _get_watermark(raw_conn)
    if watermark <= last_event_id:
        return SyncResult(status="up_to_date")

    # 4. Delta-Events lesen
    delta_events = _read_delta(raw_conn, last_event_id, watermark)

    # 5. Dirty Sets ableiten
    dirty = _derive_dirty_sets(delta_events, hint_story_id)

    # 6. Fuer jedes Dirty Set: Slices komplett neu berechnen
    new_facts = _recompute_all(raw_conn, dirty)

    # 7. Atomare Transaktion auf analytics.db
    analytics_conn.execute("BEGIN IMMEDIATE")
    try:
        _upsert_fact_story(analytics_conn, new_facts.stories)
        _replace_fact_guard_period(analytics_conn, new_facts.guards)
        _replace_fact_pool_period(analytics_conn, new_facts.pools)
        _replace_fact_pipeline_period(analytics_conn, new_facts.pipeline)
        _replace_fact_corpus_period(analytics_conn, new_facts.corpus)
        _update_sync_cursor(analytics_conn, watermark)
        analytics_conn.commit()
    except Exception:
        analytics_conn.rollback()
        raise

    return SyncResult(
        status="synced",
        events_processed=len(delta_events),
        watermark=watermark,
    )
```

### 62.3.3 Dirty Sets

Dirty Sets werden aus zwei Quellen abgeleitet: Delta-Events in
raw.db UND dem Closure-Hint (hint_story_id). Nicht alle KPIs
basieren auf Events — einige lesen aus Raw-Tabellen
(`qa_findings`, `fc_incidents`) oder Pipeline-Artefakten
(`context.json`, `phase-state.json`). Diese Nicht-Event-Quellen
werden nur bei Story-Closure konsistent, deshalb ist Closure der
primaere Sync-Trigger.

| Dirty Set | Abgeleitet aus | Typ | Hinweis |
|-----------|---------------|-----|---------|
| `dirty_story_ids` | `story_id` aus Delta-Events + `hint_story_id` | `set[str]` | Story-Facts lesen auch aus Pipeline-Artefakten — diese sind nur bei Closure finalisiert |
| `dirty_guard_weeks` | `(guard_key, week_start(ts))` aus `guard_invocation` / `integrity_violation` Events | `set[tuple[str, str]]` | Rein event-basiert, konsistent |
| `dirty_pool_weeks` | `(pool_key, week_start(ts))` aus `llm_call` / `review_*` Events | `set[tuple[str, str]]` | Rein event-basiert, konsistent |
| `dirty_pipeline_weeks` | `week_start(ts)` aus allen Delta-Events + `week_start(closed_at)` der hint_story | `set[str]` | Schliesst die Woche der gerade geschlossenen Story ein |
| `dirty_corpus_months` | Immer der aktuelle Monat bei jedem Sync | `set[str]` | FC-Tabellen (`fc_incidents`, `fc_patterns`) haben keinen Event-Cursor — Corpus-Perioden werden bei jedem Sync fuer den aktuellen Monat komplett neu berechnet |

**Begruendung fuer den Corpus-Sonderfall**: `fc_incidents` und
`fc_patterns` werden nicht ueber die `events`-Tabelle getrackt.
Sie sind eigenstaendige Tabellen in raw.db die durch den
Failure-Corpus-Lifecycle (FK-41) befuellt werden. Da das Volumen
gering ist (Ziel: <20 Incidents/Monat) und die Koernung monatlich
ist, ist ein Full-Recompute des aktuellen Monats bei jedem
Sync-Lauf vertretbar.

### 62.3.4 Slice-Neuberechnung

Pro Dirty Set wird der betroffene Slice **komplett aus raw.db
neu berechnet**, nicht inkrementell hochgezaehlt.

Beispiel `fact_story` fuer eine dirty Story:
```python
def _compute_fact_story(raw_conn, story_id: str) -> FactStoryRow:
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
    raw_conn, pool_key: str, week_start: str,
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

- `BEGIN` auf raw.db fuer konsistenten Read-Snapshot ueber
  den gesamten Sync-Lauf
- `BEGIN IMMEDIATE` auf analytics.db vor allen Writes
- Cursor (`sync_state.last_event_id`) wird als letzter Schritt
  innerhalb derselben Transaktion aktualisiert
- Bei Crash vor COMMIT: Nichts sichtbar. Naechster Lauf
  verarbeitet denselben Delta-Bereich erneut (idempotent)
- Kein Cross-DB-Commit (`ATTACH` wird nicht verwendet)

**Einschraenkung**: Die Konsistenz zwischen raw.db und
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

1. Identifiziere alle `story_id`s mit Events in raw.db die KEINEN
   `fact_story`-Eintrag in analytics.db haben
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

Neue KPIs werden als `ALTER TABLE ADD COLUMN` hinzugefuegt.
SQLite fuehrt `ADD COLUMN` ohne Datenreorganisation durch
(nur Schema-Text-Aenderung), sofern die Spalte keinen
problematischen Constraint hat.

### 62.4.2 Idempotente Migration

```python
def _ensure_column(
    conn: sqlite3.Connection,
    table: str,
    column: str,
    col_type: str,
    default: str = "",
) -> None:
    """Fuegt Spalte hinzu wenn sie nicht existiert."""
    existing = {
        row[1]
        for row in conn.execute(f"PRAGMA table_info({table})")
    }
    if column not in existing:
        default_clause = f" DEFAULT {default}" if default else ""
        conn.execute(
            f"ALTER TABLE {table} ADD COLUMN {column} "
            f"{col_type}{default_clause}"
        )
```

### 62.4.3 Versionierung

`sync_state` enthaelt einen Eintrag `schema_version` (INTEGER).
Jede Migration prueft die aktuelle Version und fuehrt nur
fehlende Schritte aus.

---

## 62.5 Abgrenzung zu FK-16

FK-16 definiert die Raw-Spiegel-Tabellen (`qa_findings`,
`qa_stage_results`, `story_metrics`, `fc_*`) in `raw.db`.
Diese Tabellen sind **Eingabedaten** fuer den Refresh-Worker.

FK-62 definiert die **Ausgabedaten** (Fact-Tabellen in
`analytics.db`). Es gibt keine Ueberschneidung:
raw.db wird nur gelesen, analytics.db wird nur geschrieben.
