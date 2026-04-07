---
concept_id: FK-16
title: QA- und Failure-Corpus-Raw-Store
module: qa-telemetry
status: active
doc_kind: core
parent_concept_id:
authority_over:
  - scope: qa-telemetry
  - scope: qa-raw-store
defers_to:
  - target: FK-14
    scope: telemetry
    reason: Baut auf der events-Tabelle aus FK-14 auf
supersedes: []
superseded_by:
tags: [qa-aggregation, raw-store, sqlite, failure-corpus, metriken]
---

# 16 — QA- und Failure-Corpus-Raw-Store

## 16.1 Zweck

Die bestehende Telemetrie-Infrastruktur (FK-14) erfasst Events
in einer `events`-Tabelle. QA-Ergebnisse, Story-Metriken und
Failure-Corpus-Daten liegen jedoch als verstreute JSON/JSONL-Dateien
im Dateisystem:

- QA-Artefakte: `_temp/qa/{story_id}/structural.json`, `qa_review.json`,
  `semantic_review.json`, `adversarial.json`, `policy.json`
- Metriken: nur in `closure.json`
- Failure Corpus: `.agentkit/failure-corpus/incidents.jsonl`,
  `patterns.jsonl`
- Check-Proposals: `.agentkit/failure-corpus/checks/CHK-*/proposal.json`

**Loesung:** Zusaetzliche SQLite-Tabellen in derselben DB
(`_temp/agentkit.db` / raw.db), die QA-Ergebnisse pro Check
strukturiert erfassen, Story-Metriken querybar machen und
Failure-Corpus-Metadaten in SQL bringen.

### 16.1.1 Scope und Abgrenzung

FK-16 definiert die **Raw-Spiegel-Tabellen** in raw.db:
`qa_findings`, `qa_stage_results`, `story_metrics`,
`fc_incidents`, `fc_patterns`, `fc_check_proposals`.

**Nicht in FK-16**: Dashboard-Semantik, Analytics-Aggregation,
KPI-Berechnung, Fact-Tabellen. Diese Themen sind seit FK-60ff
im Analytics-Block verortet:
- KPI-Katalog und Architektur → FK-60
- KPI-Aggregation und Fact-Tabellen → FK-62
- Dashboard und Auswertung → FK-63

### 16.1.2 Designgrundsaetze

1. **Die bestehende `events`-Tabelle bleibt unveraendert.**
   Neue Tabellen kommen dazu, aendern aber kein bestehendes Schema.
2. **Dateisystem-Artefakte bleiben primaer.** Die JSON/JSONL-Dateien
   sind die authoritativen Artefakte (Rueckwaertskompatibilitaet).
   Die DB ist die sekundaere, querybare Kopie.
3. **Keine verschachtelten JSON-Spalten fuer querybare Daten.**
   Alles was man aggregieren, filtern oder gruppieren will, ist
   eine eigene Spalte. JSON-Spalten sind nur fuer opake Zusatzdaten
   erlaubt, die nicht aggregiert werden.
4. **Alle Writes nutzen `_open_connection()`** mit WAL-Modus +
   `busy_timeout=5000ms` (identisch zur events-Tabelle).
5. **Schema-Versionierung** ueber eine `schema_version`-Tabelle.

### 16.1.3 Auswertungsszenarien

Die folgenden Szenarien motivierten die Raw-Store-Tabellen.
Analytische Auswertungen (Trends, Raten, Vergleiche) sind
seit FK-60ff im Analytics-Block definiert.

| Szenario | Frage | Tabelle |
|----------|-------|---------|
| QA-Finding-Suche | Welche Checks haben fuer Story X FAIL gemeldet? | `qa_findings` |
| Stage-Ergebnis-Lookup | Welche Stages sind in Runde 2 fehlgeschlagen? | `qa_stage_results` |
| Story-Metriken-Abfrage | Wie lange hat Story X gedauert? | `story_metrics` |
| Incident-Recherche | Welche Incidents gibt es fuer Kategorie Y? | `fc_incidents` |
| Pattern-Status | Welche Patterns sind als candidate offen? | `fc_patterns` |
| Check-Wirksamkeit-Rohdaten | Wie viele TP/FP hat Check Z? | `fc_check_proposals` |

---

## 16.2 Schema-Versionierung

### 16.2.1 Versionstabelle

```sql
CREATE TABLE IF NOT EXISTS schema_versions (
    schema_name    TEXT NOT NULL,
    version        INTEGER NOT NULL,
    applied_at     TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (schema_name, version)
);
```

| Spalte | Typ | Beschreibung |
|--------|-----|-------------|
| `schema_name` | TEXT | Logischer Schema-Name (z.B. `'events'`, `'qa_aggregation'`) |
| `version` | INTEGER | Aufsteigende Versionsnummer (1, 2, 3, ...) |
| `applied_at` | TEXT | ISO 8601 Zeitstempel der Migration |

**F-16-001 — Schema-Versionierung (FK-16-001):** Jede Schema-
Erweiterung wird in `schema_versions` mit Namen und Versionsnummer
registriert. Migrationen pruefen `SELECT MAX(version) FROM
schema_versions WHERE schema_name = ?` und fuehren nur fehlende
Versionen aus.

**F-16-002 — Bestehende events-Tabelle (FK-16-002):** Die
`events`-Tabelle (Kap. 14) wird nachtraeglich mit einem Eintrag
`('events', 1)` in `schema_versions` registriert. Ihr Schema wird
nicht veraendert.

**F-16-003 — Initiale QA-Aggregation-Version (FK-16-003):** Alle
Tabellen dieses Kapitels werden unter dem Schema-Namen
`'qa_aggregation'` mit Version `1` registriert.

### 16.2.2 Migrations-Mechanismus

```python
def ensure_qa_aggregation_schema(db_path: str = DB_PATH) -> None:
    """Erstellt oder migriert die QA-Aggregation-Tabellen."""
    with _open_connection(db_path) as conn:
        conn.execute(_CREATE_SCHEMA_VERSIONS)
        current = _current_version(conn, "qa_aggregation")
        if current < 1:
            _apply_v1(conn)
            conn.execute(
                "INSERT INTO schema_versions (schema_name, version) VALUES (?, ?)",
                ("qa_aggregation", 1),
            )
        conn.commit()
```

---

## 16.3 Tabelle: `qa_findings`

### 16.3.1 Zweck

Erfasst **jeden einzelnen Check-Befund** aus jeder QA-Stufe.
Ein Finding ist das atomare Ergebnis eines einzelnen Checks
(z.B. `build.test_execution` FAIL oder `ac_fulfilled` PASS).

### 16.3.2 Schema

```sql
CREATE TABLE IF NOT EXISTS qa_findings (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    story_id        TEXT NOT NULL,
    run_id          TEXT NOT NULL,
    attempt         INTEGER NOT NULL DEFAULT 1,
    stage_id        TEXT NOT NULL,
    check_id        TEXT NOT NULL,
    status          TEXT NOT NULL,
    severity        TEXT NOT NULL,
    blocking        INTEGER NOT NULL DEFAULT 0,
    source_agent    TEXT NOT NULL,
    category        TEXT NOT NULL DEFAULT '',
    reason          TEXT NOT NULL DEFAULT '',
    description     TEXT NOT NULL DEFAULT '',
    detail          TEXT NOT NULL DEFAULT '',
    metadata        TEXT,
    ts              TEXT NOT NULL,
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_qa_findings_story
    ON qa_findings(story_id, attempt);
CREATE INDEX IF NOT EXISTS idx_qa_findings_stage
    ON qa_findings(stage_id, status);
CREATE INDEX IF NOT EXISTS idx_qa_findings_check
    ON qa_findings(check_id, status);
CREATE INDEX IF NOT EXISTS idx_qa_findings_ts
    ON qa_findings(ts);
CREATE INDEX IF NOT EXISTS idx_qa_findings_severity
    ON qa_findings(severity, blocking);
```

### 16.3.3 Spaltenbeschreibung

| Spalte | Typ | NULL | Beschreibung | Beispielwerte |
|--------|-----|------|-------------|---------------|
| `id` | INTEGER | Nein | Auto-Increment Primary Key | 1, 2, 3 |
| `story_id` | TEXT | Nein | Story-ID | `"ODIN-042"` |
| `run_id` | TEXT | Nein | Run-UUID (korrespondiert mit `events.run_id`) | `"a1b2c3d4-..."` |
| `attempt` | INTEGER | Nein | QA-Runde (1 = erster Versuch, 2 = nach Remediation, ...) | 1, 2, 3 |
| `stage_id` | TEXT | Nein | Stage-ID aus der Stage-Registry (Kap. 33) | `"structural"`, `"qa_review"`, `"semantic_review"`, `"adversarial"`, `"policy"` |
| `check_id` | TEXT | Nein | Individueller Check innerhalb der Stage | `"build.test_execution"`, `"ac_fulfilled"`, `"scope_compliance"` |
| `status` | TEXT | Nein | Ergebnis des Checks | `"PASS"`, `"FAIL"`, `"PASS_WITH_CONCERNS"`, `"SKIP"` |
| `severity` | TEXT | Nein | Schweregrad des Checks | `"BLOCKING"`, `"MAJOR"`, `"MINOR"`, `"INFO"` |
| `blocking` | INTEGER | Nein | 1 = dieser Check blockiert bei FAIL, 0 = nicht | 0, 1 |
| `source_agent` | TEXT | Nein | Welcher QA-Agent/Producer diesen Befund erzeugt hat | `"qa-structural-check"`, `"qa-llm-review"`, `"qa-semantic-review"`, `"qa-adversarial"`, `"qa-policy-engine"` |
| `category` | TEXT | Nein | Check-Kategorie (bei Structural Checks) | `"artifact"`, `"branch"`, `"build"`, `"test"`, `"security"`, `"hygiene"`, `"guard"`, `""` |
| `reason` | TEXT | Nein | Einzeiler-Begruendung (bei LLM-Bewertungen) | `"Timeout wird verschluckt"` |
| `description` | TEXT | Nein | Detailbeschreibung (max 300 Zeichen bei LLM-Checks) | `"BrokerClient.send() faengt TimeoutException..."` |
| `detail` | TEXT | Nein | Menschenlesbarer Detail-Text (bei Structural Checks) | `"3 tests failed: test_broker_adapter, ..."` |
| `metadata` | TEXT | Ja | Opakes JSON fuer check-spezifische Zusatzdaten (nicht aggregierbar) | `'{"exit_code": 1, "failed_tests": 3}'` |
| `ts` | TEXT | Nein | ISO 8601 Zeitstempel der QA-Ausfuehrung | `"2026-03-17T11:00:00+00:00"` |
| `created_at` | TEXT | Ja | Insert-Zeitstempel (DB-Default) | `"2026-03-17 11:00:05"` |

### 16.3.4 Datenherkunft

| Quelle | Wann | Was wird geschrieben |
|--------|------|---------------------|
| Structural-Check-Skript (`qa-structural-check`) | Nach Schicht-1-Ausfuehrung | Je ein Row pro Check aus `structural.json → checks[]` |
| LLM-Review-Evaluator (`qa-llm-review`) | Nach Schicht-2-Ausfuehrung | Je ein Row pro Check aus `qa_review.json → checks[]` (12 Checks) |
| Semantic-Review-Evaluator (`qa-semantic-review`) | Nach Schicht-2-Ausfuehrung | Ein Row fuer den Semantic-Review-Gesamtbefund |
| Adversarial Agent (`qa-adversarial`) | Nach Schicht-3-Ausfuehrung | Ein Row fuer das Adversarial-Gesamtergebnis, plus je ein Row pro Finding |
| Policy Engine (`qa-policy-engine`) | Nach Schicht-4-Aggregation | Ein Row fuer die Gesamtentscheidung |

**F-16-004 — Dual-Write-Prinzip (FK-16-004):** Jeder QA-Producer
schreibt sowohl die JSON-Artefakt-Datei (primaer) als auch die
entsprechenden Rows in `qa_findings` (sekundaer). Die DB-Writes
erfolgen im selben Prozess unmittelbar nach dem Datei-Write.

**F-16-005 — Attempt-Tracking (FK-16-005):** Das `attempt`-Feld
wird aus dem `attempt`-Feld in `phase-state.json` uebernommen.
Bei jedem neuen QA-Durchlauf (nach Remediation) wird `attempt`
inkrementiert. Damit sind die Findings verschiedener QA-Runden
derselben Story unterscheidbar.

### 16.3.5 Dashboard-Queries

**Query 1 — Woechentlicher Review: Alle FAIL-Findings der letzten 7 Tage**
```sql
SELECT story_id, stage_id, check_id, severity, reason, detail
FROM qa_findings
WHERE status = 'FAIL'
  AND ts >= datetime('now', '-7 days')
ORDER BY ts DESC;
```

**Query 2 — Agent-Vergleich: Blocking Findings pro QA-Agent**
```sql
SELECT source_agent,
       COUNT(*) AS total_findings,
       SUM(CASE WHEN status = 'FAIL' AND blocking = 1 THEN 1 ELSE 0 END) AS blocking_fails
FROM qa_findings
WHERE ts >= datetime('now', '-30 days')
GROUP BY source_agent
ORDER BY blocking_fails DESC;
```

**Query 3 — Coverage-Tracking: Meistfehlende Checks**
```sql
SELECT check_id,
       COUNT(*) AS fail_count,
       COUNT(DISTINCT story_id) AS affected_stories
FROM qa_findings
WHERE status = 'FAIL'
  AND ts >= datetime('now', '-30 days')
GROUP BY check_id
ORDER BY fail_count DESC
LIMIT 20;
```

**Query 4 — Prompt-Wirksamkeit: Findings nach Stage ueber Zeit**
```sql
SELECT strftime('%Y-%W', ts) AS week,
       stage_id,
       SUM(CASE WHEN status = 'FAIL' THEN 1 ELSE 0 END) AS fails,
       SUM(CASE WHEN status = 'PASS' THEN 1 ELSE 0 END) AS passes,
       COUNT(*) AS total
FROM qa_findings
GROUP BY week, stage_id
ORDER BY week DESC, stage_id;
```

**Query 5 — Story-Detail: Alle Findings einer Story pro Attempt**
```sql
SELECT attempt, stage_id, check_id, status, severity, reason, detail
FROM qa_findings
WHERE story_id = ?
ORDER BY attempt, stage_id, check_id;
```

**Query 6 — Severity-Verteilung pro Woche**
```sql
SELECT strftime('%Y-%W', ts) AS week,
       severity,
       COUNT(*) AS count
FROM qa_findings
WHERE status = 'FAIL'
GROUP BY week, severity
ORDER BY week DESC;
```

---

## 16.4 Tabelle: `qa_stage_results`

### 16.4.1 Zweck

Erfasst das **Gesamtergebnis jeder QA-Stage** pro Story und Attempt.
Waehrend `qa_findings` die atomaren Check-Ergebnisse enthaelt,
liefert `qa_stage_results` die aggregierte Stage-Ebene fuer
schnelle Dashboard-Uebersichten.

### 16.4.2 Schema

```sql
CREATE TABLE IF NOT EXISTS qa_stage_results (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    story_id        TEXT NOT NULL,
    run_id          TEXT NOT NULL,
    attempt         INTEGER NOT NULL DEFAULT 1,
    stage_id        TEXT NOT NULL,
    layer           INTEGER NOT NULL,
    kind            TEXT NOT NULL,
    producer        TEXT NOT NULL,
    status          TEXT NOT NULL,
    blocking        INTEGER NOT NULL DEFAULT 1,
    total_checks    INTEGER NOT NULL DEFAULT 0,
    passed          INTEGER NOT NULL DEFAULT 0,
    failed          INTEGER NOT NULL DEFAULT 0,
    skipped         INTEGER NOT NULL DEFAULT 0,
    blocking_failures INTEGER NOT NULL DEFAULT 0,
    major_failures  INTEGER NOT NULL DEFAULT 0,
    minor_failures  INTEGER NOT NULL DEFAULT 0,
    duration_ms     INTEGER,
    ts              TEXT NOT NULL,
    created_at      TEXT DEFAULT (datetime('now')),
    UNIQUE(story_id, run_id, attempt, stage_id)
);

CREATE INDEX IF NOT EXISTS idx_qa_stage_results_story
    ON qa_stage_results(story_id, attempt);
CREATE INDEX IF NOT EXISTS idx_qa_stage_results_status
    ON qa_stage_results(stage_id, status);
CREATE INDEX IF NOT EXISTS idx_qa_stage_results_ts
    ON qa_stage_results(ts);
```

### 16.4.3 Spaltenbeschreibung

| Spalte | Typ | NULL | Beschreibung | Beispielwerte |
|--------|-----|------|-------------|---------------|
| `id` | INTEGER | Nein | Auto-Increment Primary Key | 1, 2, 3 |
| `story_id` | TEXT | Nein | Story-ID | `"ODIN-042"` |
| `run_id` | TEXT | Nein | Run-UUID | `"a1b2c3d4-..."` |
| `attempt` | INTEGER | Nein | QA-Runde | 1, 2, 3 |
| `stage_id` | TEXT | Nein | Stage-ID aus Stage-Registry | `"structural"`, `"qa_review"` |
| `layer` | INTEGER | Nein | Verify-Schicht (1-4) | 1, 2, 3, 4 |
| `kind` | TEXT | Nein | Stage-Art | `"deterministic"`, `"llm_evaluation"`, `"agent"`, `"policy"` |
| `producer` | TEXT | Nein | Producer-Name | `"qa-structural-check"` |
| `status` | TEXT | Nein | Gesamtstatus der Stage | `"PASS"`, `"FAIL"` |
| `blocking` | INTEGER | Nein | Stage blockiert bei FAIL (1/0) | 1 |
| `total_checks` | INTEGER | Nein | Anzahl Checks in dieser Stage | 18 |
| `passed` | INTEGER | Nein | Davon PASS | 17 |
| `failed` | INTEGER | Nein | Davon FAIL | 1 |
| `skipped` | INTEGER | Nein | Davon SKIP | 0 |
| `blocking_failures` | INTEGER | Nein | Davon FAIL + BLOCKING | 1 |
| `major_failures` | INTEGER | Nein | Davon FAIL + MAJOR | 0 |
| `minor_failures` | INTEGER | Nein | Davon FAIL + MINOR | 0 |
| `duration_ms` | INTEGER | Ja | Ausfuehrungsdauer in Millisekunden (wenn verfuegbar) | 4523 |
| `ts` | TEXT | Nein | ISO 8601 Zeitstempel | `"2026-03-17T11:00:00+00:00"` |
| `created_at` | TEXT | Ja | DB-Default-Timestamp | `"2026-03-17 11:00:05"` |

### 16.4.4 Datenherkunft

| Quelle | Wann |
|--------|------|
| Structural-Check-Skript | Nach Schicht-1: Liest `summary` aus `structural.json` |
| LLM-Review-Evaluator | Nach Schicht-2: Aggregiert Check-Ergebnisse |
| Semantic-Review-Evaluator | Nach Schicht-2: Gesamtergebnis |
| Adversarial Agent | Nach Schicht-3: Gesamtergebnis + Test-Statistik |
| Policy Engine | Nach Schicht-4: Finale Aggregation |

**F-16-006 — Stage-Result-Write (FK-16-006):** Jeder QA-Producer
schreibt nach Abschluss seiner Stage genau einen Row in
`qa_stage_results` mit den aggregierten Zaehlerstaenden.

**F-16-007 — UNIQUE Constraint (FK-16-007):** Die Kombination
`(story_id, run_id, attempt, stage_id)` ist unique. Ein
erneuter Write mit identischem Key wird per `INSERT OR REPLACE`
behandelt.

### 16.4.5 Dashboard-Queries

**Query 1 — QA-Effektivitaet: Durchschnittliche Attempts pro Story-Typ (letzte 30 Tage)**
```sql
SELECT sm.story_type,
       ROUND(AVG(qsr.attempt), 1) AS avg_attempts,
       MAX(qsr.attempt) AS max_attempts,
       COUNT(DISTINCT qsr.story_id) AS story_count
FROM qa_stage_results qsr
JOIN story_metrics sm ON qsr.story_id = sm.story_id
WHERE qsr.stage_id = 'policy'
  AND qsr.status = 'PASS'
  AND qsr.ts >= datetime('now', '-30 days')
GROUP BY sm.story_type;
```

**Query 2 — Stage-Failure-Rate: Welche Stage failt am haeufigsten?**
```sql
SELECT stage_id,
       COUNT(*) AS total_runs,
       SUM(CASE WHEN status = 'FAIL' THEN 1 ELSE 0 END) AS fails,
       ROUND(100.0 * SUM(CASE WHEN status = 'FAIL' THEN 1 ELSE 0 END) / COUNT(*), 1)
           AS fail_rate_pct
FROM qa_stage_results
WHERE ts >= datetime('now', '-30 days')
GROUP BY stage_id
ORDER BY fail_rate_pct DESC;
```

**Query 3 — Wochenbericht: Stage-Ergebnisse aggregiert**
```sql
SELECT strftime('%Y-%W', ts) AS week,
       stage_id,
       SUM(CASE WHEN status = 'PASS' THEN 1 ELSE 0 END) AS passes,
       SUM(CASE WHEN status = 'FAIL' THEN 1 ELSE 0 END) AS fails
FROM qa_stage_results
GROUP BY week, stage_id
ORDER BY week DESC;
```

**Query 4 — Duration-Tracking: Langsamste Stages**
```sql
SELECT stage_id,
       ROUND(AVG(duration_ms) / 1000.0, 1) AS avg_sec,
       MAX(duration_ms) / 1000.0 AS max_sec,
       COUNT(*) AS runs
FROM qa_stage_results
WHERE duration_ms IS NOT NULL
  AND ts >= datetime('now', '-30 days')
GROUP BY stage_id
ORDER BY avg_sec DESC;
```

**Query 5 — Story-Timeline: Alle Stages einer Story chronologisch**
```sql
SELECT attempt, stage_id, layer, status, blocking_failures, ts
FROM qa_stage_results
WHERE story_id = ?
ORDER BY attempt, layer;
```

---

## 16.5 Tabelle: `story_metrics`

### 16.5.1 Zweck

Erfasst die **Workflow-Metriken und Experiment-Tags** pro
abgeschlossener Story. Macht die Daten aus `closure.json`
querybar und aggregierbar.

### 16.5.2 Schema

```sql
CREATE TABLE IF NOT EXISTS story_metrics (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    story_id                TEXT NOT NULL UNIQUE,
    run_id                  TEXT NOT NULL,
    story_type              TEXT NOT NULL DEFAULT '',
    story_size              TEXT NOT NULL DEFAULT '',
    mode                    TEXT NOT NULL DEFAULT '',
    processing_time_min     REAL NOT NULL DEFAULT 0.0,
    qa_rounds               INTEGER NOT NULL DEFAULT 0,
    adversarial_findings    INTEGER NOT NULL DEFAULT 0,
    adversarial_tests_created INTEGER NOT NULL DEFAULT 0,
    files_changed           INTEGER NOT NULL DEFAULT 0,
    increments              INTEGER NOT NULL DEFAULT 0,
    final_status            TEXT NOT NULL DEFAULT '',
    agentkit_version        TEXT NOT NULL DEFAULT '',
    agentkit_commit         TEXT NOT NULL DEFAULT '',
    config_version          TEXT NOT NULL DEFAULT '',
    llm_roles               TEXT,
    completed_at            TEXT NOT NULL DEFAULT '',
    created_at              TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_story_metrics_type
    ON story_metrics(story_type);
CREATE INDEX IF NOT EXISTS idx_story_metrics_completed
    ON story_metrics(completed_at);
CREATE INDEX IF NOT EXISTS idx_story_metrics_version
    ON story_metrics(agentkit_version);
CREATE INDEX IF NOT EXISTS idx_story_metrics_config
    ON story_metrics(config_version);
```

### 16.5.3 Spaltenbeschreibung

| Spalte | Typ | NULL | Beschreibung | Beispielwerte |
|--------|-----|------|-------------|---------------|
| `id` | INTEGER | Nein | Auto-Increment Primary Key | 1 |
| `story_id` | TEXT | Nein | Story-ID (UNIQUE — eine Zeile pro Story) | `"ODIN-042"` |
| `run_id` | TEXT | Nein | Run-UUID des finalen (erfolgreichen) Runs | `"a1b2c3d4-..."` |
| `story_type` | TEXT | Nein | Story-Typ aus `context.json` | `"implementation"`, `"bugfix"`, `"concept"`, `"research"` |
| `story_size` | TEXT | Nein | Story-Groesse aus `context.json` | `"XS"`, `"S"`, `"M"`, `"L"`, `"XL"` |
| `mode` | TEXT | Nein | Ausfuehrungsmodus aus `phase-state.json` | `"execution"`, `"exploration"` |
| `processing_time_min` | REAL | Nein | Bearbeitungsdauer in Minuten (F-14-047) | 42.5 |
| `qa_rounds` | INTEGER | Nein | Anzahl QA-Runden (verify->implementation Uebergaenge) | 1, 2, 3 |
| `adversarial_findings` | INTEGER | Nein | Adversarial-Befunde (findings_count) | 0, 2 |
| `adversarial_tests_created` | INTEGER | Nein | Adversarial-erzeugte Tests | 3 |
| `files_changed` | INTEGER | Nein | Geaenderte Dateien (git diff --stat) | 7 |
| `increments` | INTEGER | Nein | Anzahl Commits (increment_commit Events) | 4 |
| `final_status` | TEXT | Nein | Endstatus der Story | `"PASS"`, `"ESCALATED"`, `"WARN"` |
| `agentkit_version` | TEXT | Nein | AgentKit-Version bei Closure | `"1.2.0"` |
| `agentkit_commit` | TEXT | Nein | AgentKit-Commit-SHA bei Closure | `"abc123def"` |
| `config_version` | TEXT | Nein | Pipeline-Config-Version | `"2.1"` |
| `llm_roles` | TEXT | Ja | JSON-Mapping von Rolle -> Pool (opak, Experiment-Tag) | `'{"qa_review":"chatgpt","semantic_review":"gemini"}'` |
| `completed_at` | TEXT | Nein | ISO 8601 Abschluss-Zeitstempel | `"2026-03-17T11:15:00+00:00"` |
| `created_at` | TEXT | Ja | DB-Default-Timestamp | `"2026-03-17 11:15:05"` |

**Hinweis zu `llm_roles`:** Dies ist die einzige JSON-Spalte in
`story_metrics`. Sie wird nicht aggregiert, sondern nur fuer
Experiment-Tagging gespeichert (Welche LLM-Konfiguration lief?).
Aggregation erfolgt ueber `config_version`.

### 16.5.4 Datenherkunft

| Quelle | Wann |
|--------|------|
| Closure-Skript (`agentkit.closure.closure`) | Bei erfolgreichem Story-Abschluss, als Teil des Closure-Ablaufs (Kap. 25.9.2, nach Merge + Issue Close) |

**F-16-008 — Metrics-Write bei Closure (FK-16-008):** Das
Closure-Skript schreibt nach dem Metriken-Compute (Schritt 5,
Kap. 25.9.2) einen Row in `story_metrics`. Der Write erfolgt
nach dem `closure.json`-Write, aber vor dem Postflight.

**F-16-009 — UNIQUE on story_id (FK-16-009):** Pro Story existiert
genau eine Zeile. Ein erneuter Closure-Run fuer dieselbe Story
(z.B. nach Recovery) ueberschreibt per `INSERT OR REPLACE`.

**F-16-010 — Experiment-Tags inline (FK-16-010):** Die sieben
Experiment-Tags (F-14-048) werden als flache Spalten gespeichert
(nicht als verschachteltes JSON), damit sie direkt in WHERE- und
GROUP-BY-Klauseln verwendbar sind. Einzige Ausnahme: `llm_roles`
als JSON-Spalte, da das Mapping variabel viele Eintraege haben
kann.

### 16.5.5 Dashboard-Queries

**Query 1 — QA-Runden-Trend nach Story-Typ und Woche**
```sql
SELECT strftime('%Y-%W', completed_at) AS week,
       story_type,
       ROUND(AVG(qa_rounds), 1) AS avg_qa_rounds,
       MAX(qa_rounds) AS max_qa_rounds,
       COUNT(*) AS stories
FROM story_metrics
GROUP BY week, story_type
ORDER BY week DESC;
```

**Query 2 — Prompt-Wirksamkeit: Vergleich nach Config-Version**
```sql
SELECT config_version,
       COUNT(*) AS stories,
       ROUND(AVG(qa_rounds), 1) AS avg_rounds,
       ROUND(AVG(processing_time_min), 0) AS avg_time_min,
       ROUND(AVG(adversarial_findings), 1) AS avg_adv_findings
FROM story_metrics
GROUP BY config_version
ORDER BY config_version DESC;
```

**Query 3 — Story-Typ-Analyse: Bearbeitungsdauer nach Typ und Groesse**
```sql
SELECT story_type, story_size,
       COUNT(*) AS count,
       ROUND(AVG(processing_time_min), 1) AS avg_min,
       ROUND(AVG(qa_rounds), 1) AS avg_rounds,
       ROUND(AVG(files_changed), 0) AS avg_files
FROM story_metrics
GROUP BY story_type, story_size
ORDER BY story_type, story_size;
```

**Query 4 — Woechentlicher Durchsatz**
```sql
SELECT strftime('%Y-%W', completed_at) AS week,
       COUNT(*) AS stories_completed,
       SUM(CASE WHEN final_status = 'PASS' THEN 1 ELSE 0 END) AS passed,
       SUM(CASE WHEN final_status != 'PASS' THEN 1 ELSE 0 END) AS issues,
       ROUND(AVG(processing_time_min), 0) AS avg_time_min
FROM story_metrics
GROUP BY week
ORDER BY week DESC;
```

**Query 5 — Agentkit-Version-Vergleich**
```sql
SELECT agentkit_version,
       COUNT(*) AS stories,
       ROUND(AVG(qa_rounds), 1) AS avg_rounds,
       ROUND(AVG(adversarial_findings), 1) AS avg_findings
FROM story_metrics
GROUP BY agentkit_version
ORDER BY agentkit_version DESC;
```

**Query 6 — Exploration vs. Execution Mode**
```sql
SELECT mode,
       COUNT(*) AS count,
       ROUND(AVG(qa_rounds), 1) AS avg_rounds,
       ROUND(AVG(processing_time_min), 1) AS avg_min
FROM story_metrics
GROUP BY mode;
```

---

## 16.6 Tabelle: `fc_incidents`

### 16.6.1 Zweck

Spiegelt die Metadaten aus `.agentkit/failure-corpus/incidents.jsonl`
in eine querybare SQL-Tabelle. Die JSONL-Datei bleibt die autoritative
Quelle; die DB-Tabelle ist die sekundaere Abfrageschicht.

### 16.6.2 Schema

```sql
CREATE TABLE IF NOT EXISTS fc_incidents (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    incident_id     TEXT NOT NULL UNIQUE,
    story_id        TEXT NOT NULL,
    run_id          TEXT NOT NULL DEFAULT '',
    timestamp       TEXT NOT NULL,
    category        TEXT NOT NULL,
    severity        TEXT NOT NULL,
    phase           TEXT NOT NULL DEFAULT 'implementation',
    role            TEXT NOT NULL DEFAULT 'worker',
    model           TEXT NOT NULL DEFAULT '',
    symptom         TEXT NOT NULL,
    impact          TEXT NOT NULL DEFAULT '',
    status          TEXT NOT NULL DEFAULT 'open',
    tags            TEXT,
    evidence_refs   TEXT,
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_fc_incidents_category
    ON fc_incidents(category);
CREATE INDEX IF NOT EXISTS idx_fc_incidents_severity
    ON fc_incidents(severity);
CREATE INDEX IF NOT EXISTS idx_fc_incidents_story
    ON fc_incidents(story_id);
CREATE INDEX IF NOT EXISTS idx_fc_incidents_ts
    ON fc_incidents(timestamp);
CREATE INDEX IF NOT EXISTS idx_fc_incidents_status
    ON fc_incidents(status);
CREATE INDEX IF NOT EXISTS idx_fc_incidents_phase
    ON fc_incidents(phase);
```

### 16.6.3 Spaltenbeschreibung

| Spalte | Typ | NULL | Beschreibung | Beispielwerte |
|--------|-----|------|-------------|---------------|
| `id` | INTEGER | Nein | Auto-Increment Primary Key | 1 |
| `incident_id` | TEXT | Nein | Incident-ID, UNIQUE (Format: FC-YYYY-NNNN) | `"FC-2026-0017"` |
| `story_id` | TEXT | Nein | Story-ID (FK logisch zu events/story_metrics) | `"ODIN-042"` |
| `run_id` | TEXT | Nein | Run-UUID | `"a1b2c3d4-..."` |
| `timestamp` | TEXT | Nein | ISO 8601 Zeitstempel des Incidents | `"2026-03-17T14:00:00+01:00"` |
| `category` | TEXT | Nein | FailureCategory-Wert (Kap. 41.4.1) | `"scope_drift"`, `"hallucination"`, `"test_omission"` |
| `severity` | TEXT | Nein | Schweregrad | `"mittel"`, `"hoch"`, `"kritisch"`, `"sicherheitskritisch"` |
| `phase` | TEXT | Nein | Pipeline-Phase in der der Incident auftrat | `"implementation"`, `"verify"`, `"closure"` |
| `role` | TEXT | Nein | Agent-Rolle | `"worker"`, `"orchestrator"`, `"qa"`, `"adversarial"` |
| `model` | TEXT | Nein | LLM-Modell-Identifier | `"claude-opus"`, `"chatgpt-4o"` |
| `symptom` | TEXT | Nein | Menschenlesbare Symptom-Beschreibung | `"Worker hat Logging-Framework gewechselt..."` |
| `impact` | TEXT | Nein | Downstream-Impact-Beschreibung | `"Regression in 3 bestehenden Log-Assertions"` |
| `status` | TEXT | Nein | Incident-Lifecycle-Status | `"open"`, `"reviewed"`, `"closed"` |
| `tags` | TEXT | Ja | JSON-Array mit freien Tags (nicht aggregierbar) | `'["opportunistic_refactor", "bugfix_scope"]'` |
| `evidence_refs` | TEXT | Ja | JSON-Array mit Evidenz-Referenzen (nicht aggregierbar) | `'["commit a1b2c3d: replaced log4j..."]'` |
| `created_at` | TEXT | Ja | DB-Default-Timestamp | `"2026-03-17 14:00:05"` |

### 16.6.4 Datenherkunft

| Quelle | Wann |
|--------|------|
| `append_incident()` in `agentkit.failure_corpus.storage` | Bei jeder Incident-Erfassung (Kap. 41.4.2) |

**F-16-011 — Incident-Dual-Write (FK-16-011):** Die Funktion
`append_incident()` schreibt nach dem JSONL-Append zusaetzlich
einen Row in `fc_incidents`. Der JSONL-Append bleibt primaer.

**F-16-012 — Tags und Evidence als JSON (FK-16-012):** Die Spalten
`tags` und `evidence_refs` sind JSON-Arrays. Sie werden nicht
aggregiert (keine GROUP BY / SUM darauf). Aggregation erfolgt
ueber die flachen Spalten `category`, `severity`, `phase`, `role`.

### 16.6.5 Dashboard-Queries

**Query 1 — Failure-Corpus-Trends: Incidents pro Kategorie und Monat**
```sql
SELECT strftime('%Y-%m', timestamp) AS month,
       category,
       COUNT(*) AS incident_count
FROM fc_incidents
GROUP BY month, category
ORDER BY month DESC, incident_count DESC;
```

**Query 2 — Haeufigste Kategorien (letzte 90 Tage)**
```sql
SELECT category,
       severity,
       COUNT(*) AS count
FROM fc_incidents
WHERE timestamp >= datetime('now', '-90 days')
GROUP BY category, severity
ORDER BY count DESC;
```

**Query 3 — Incidents pro Story-Phase**
```sql
SELECT phase,
       COUNT(*) AS count,
       COUNT(DISTINCT story_id) AS stories_affected
FROM fc_incidents
GROUP BY phase
ORDER BY count DESC;
```

**Query 4 — Offene Incidents (Prioritaetsliste fuer Review)**
```sql
SELECT incident_id, story_id, category, severity, symptom, timestamp
FROM fc_incidents
WHERE status = 'open'
ORDER BY
    CASE severity
        WHEN 'sicherheitskritisch' THEN 1
        WHEN 'kritisch' THEN 2
        WHEN 'hoch' THEN 3
        WHEN 'mittel' THEN 4
        ELSE 5
    END,
    timestamp ASC;
```

**Query 5 — Monatlicher Incident-Zaehler (Ziel: unter 20, FK-10-017)**
```sql
SELECT strftime('%Y-%m', timestamp) AS month,
       COUNT(*) AS count,
       CASE WHEN COUNT(*) > 20 THEN 'OVER_BUDGET' ELSE 'OK' END AS budget_status
FROM fc_incidents
GROUP BY month
ORDER BY month DESC;
```

**Query 6 — Incidents nach LLM-Modell**
```sql
SELECT model,
       category,
       COUNT(*) AS count
FROM fc_incidents
WHERE model != ''
  AND timestamp >= datetime('now', '-90 days')
GROUP BY model, category
ORDER BY count DESC;
```

---

## 16.7 Tabelle: `fc_patterns`

### 16.7.1 Zweck

Spiegelt die Metadaten aus `.agentkit/failure-corpus/patterns.jsonl`
in eine querybare SQL-Tabelle.

### 16.7.2 Schema

```sql
CREATE TABLE IF NOT EXISTS fc_patterns (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    pattern_id      TEXT NOT NULL UNIQUE,
    category        TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'candidate',
    invariant       TEXT NOT NULL,
    promotion_rule  TEXT NOT NULL,
    risk_level      TEXT NOT NULL DEFAULT 'mittel',
    owner           TEXT NOT NULL DEFAULT '',
    incident_count  INTEGER NOT NULL DEFAULT 0,
    confirmed_at    TEXT NOT NULL DEFAULT '',
    confirmed_by    TEXT NOT NULL DEFAULT '',
    incident_refs   TEXT,
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_fc_patterns_category
    ON fc_patterns(category);
CREATE INDEX IF NOT EXISTS idx_fc_patterns_status
    ON fc_patterns(status);
CREATE INDEX IF NOT EXISTS idx_fc_patterns_risk
    ON fc_patterns(risk_level);
```

### 16.7.3 Spaltenbeschreibung

| Spalte | Typ | NULL | Beschreibung | Beispielwerte |
|--------|-----|------|-------------|---------------|
| `id` | INTEGER | Nein | Auto-Increment Primary Key | 1 |
| `pattern_id` | TEXT | Nein | Pattern-ID, UNIQUE (Format: FP-NNNN) | `"FP-0003"` |
| `category` | TEXT | Nein | FailureCategory-Wert | `"scope_drift"` |
| `status` | TEXT | Nein | Pattern-Status | `"candidate"`, `"confirmed"`, `"rejected"` |
| `invariant` | TEXT | Nein | Die praesize deterministische Regel | `"Bugfix-Stories: keine Dateien ausserhalb..."` |
| `promotion_rule` | TEXT | Nein | Welche Promotionsregel gegriffen hat | `"wiederholung"`, `"hohe_schwere"`, `"guenstige_checkbarkeit"` |
| `risk_level` | TEXT | Nein | Risikobewertung | `"niedrig"`, `"mittel"`, `"hoch"`, `"kritisch"` |
| `owner` | TEXT | Nein | Verantwortliches Team/Person | `"team-trading"` |
| `incident_count` | INTEGER | Nein | Anzahl zugeordneter Incidents (denormalisiert fuer Performance) | 3 |
| `confirmed_at` | TEXT | Nein | ISO 8601 Bestaetigungszeitpunkt | `"2026-03-20T09:00:00+01:00"` |
| `confirmed_by` | TEXT | Nein | Wer hat bestaetigt | `"human"` |
| `incident_refs` | TEXT | Ja | JSON-Array der Incident-IDs (opak) | `'["FC-2026-0012","FC-2026-0015"]'` |
| `created_at` | TEXT | Ja | DB-Default-Timestamp | `"2026-03-20 09:00:05"` |

### 16.7.4 Datenherkunft

| Quelle | Wann |
|--------|------|
| `append_pattern()` in `agentkit.failure_corpus.storage` | Bei Pattern-Erstellung/Bestaetigung |

**F-16-013 — Pattern-Dual-Write (FK-16-013):** Die Funktion
`append_pattern()` schreibt nach dem JSONL-Append zusaetzlich
einen Row in `fc_patterns`.

**F-16-014 — Incident-Count denormalisiert (FK-16-014):** Das
Feld `incident_count` ist die Laenge von `incident_refs`. Es ist
denormalisiert, um die haeufige Query "Patterns mit den meisten
Incidents" ohne JSON-Parsing zu ermoeglichen.

### 16.7.5 Dashboard-Queries

**Query 1 — Pattern-Pipeline: Offene Kandidaten**
```sql
SELECT pattern_id, category, invariant, incident_count, risk_level
FROM fc_patterns
WHERE status = 'candidate'
ORDER BY incident_count DESC, risk_level DESC;
```

**Query 2 — Bestaetigte Patterns nach Kategorie**
```sql
SELECT category,
       COUNT(*) AS pattern_count,
       SUM(incident_count) AS total_incidents
FROM fc_patterns
WHERE status = 'confirmed'
GROUP BY category
ORDER BY pattern_count DESC;
```

**Query 3 — Promotion-Regel-Verteilung**
```sql
SELECT promotion_rule,
       COUNT(*) AS count
FROM fc_patterns
WHERE status = 'confirmed'
GROUP BY promotion_rule;
```

**Query 4 — Patterns ohne Owner**
```sql
SELECT pattern_id, category, invariant, risk_level
FROM fc_patterns
WHERE owner = '' AND status = 'confirmed';
```

**Query 5 — Pattern-Wachstum pro Monat**
```sql
SELECT strftime('%Y-%m', confirmed_at) AS month,
       COUNT(*) AS new_patterns
FROM fc_patterns
WHERE status = 'confirmed' AND confirmed_at != ''
GROUP BY month
ORDER BY month DESC;
```

---

## 16.8 Tabelle: `fc_check_proposals`

### 16.8.1 Zweck

Spiegelt die Metadaten aus
`.agentkit/failure-corpus/checks/CHK-*/proposal.json` in eine
querybare SQL-Tabelle. Ermoeglicht Wirksamkeits-Tracking und
Status-Uebersicht ueber alle Checks.

### 16.8.2 Schema

```sql
CREATE TABLE IF NOT EXISTS fc_check_proposals (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    check_id            TEXT NOT NULL UNIQUE,
    pattern_ref         TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'draft',
    check_type          TEXT NOT NULL,
    invariant           TEXT NOT NULL,
    pipeline_stage      TEXT NOT NULL DEFAULT 'structural',
    pipeline_layer      INTEGER NOT NULL DEFAULT 1,
    owner               TEXT NOT NULL DEFAULT '',
    false_positive_risk TEXT NOT NULL DEFAULT 'niedrig',
    true_positives      INTEGER NOT NULL DEFAULT 0,
    false_positives     INTEGER NOT NULL DEFAULT 0,
    no_findings         INTEGER NOT NULL DEFAULT 0,
    effectiveness_period_days INTEGER NOT NULL DEFAULT 90,
    last_triggered_at   TEXT NOT NULL DEFAULT '',
    created_at          TEXT DEFAULT (datetime('now')),
    updated_at          TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_fc_checks_status
    ON fc_check_proposals(status);
CREATE INDEX IF NOT EXISTS idx_fc_checks_pattern
    ON fc_check_proposals(pattern_ref);
CREATE INDEX IF NOT EXISTS idx_fc_checks_type
    ON fc_check_proposals(check_type);
```

### 16.8.3 Spaltenbeschreibung

| Spalte | Typ | NULL | Beschreibung | Beispielwerte |
|--------|-----|------|-------------|---------------|
| `id` | INTEGER | Nein | Auto-Increment Primary Key | 1 |
| `check_id` | TEXT | Nein | Check-ID, UNIQUE (Format: CHK-NNNN) | `"CHK-0012"` |
| `pattern_ref` | TEXT | Nein | Pattern-Referenz (FK logisch zu fc_patterns) | `"FP-0003"` |
| `status` | TEXT | Nein | Check-Lifecycle-Status | `"draft"`, `"approved"`, `"rejected"`, `"active"`, `"tuned"`, `"retired"` |
| `check_type` | TEXT | Nein | Deterministischer Check-Typ | `"Changed-File-Policy"`, `"Artifact-Completeness"`, `"Test-Obligation"` |
| `invariant` | TEXT | Nein | Die zu pruefende Invariante | `"Bugfix-Stories: keine Dateien ausserhalb..."` |
| `pipeline_stage` | TEXT | Nein | Stage in der der Check laueft | `"structural"`, `"pre_merge"` |
| `pipeline_layer` | INTEGER | Nein | Verify-Schicht | 1 |
| `owner` | TEXT | Nein | Verantwortliches Team/Person | `"team-trading"` |
| `false_positive_risk` | TEXT | Nein | Einschaetzung des FP-Risikos | `"niedrig"`, `"mittel"`, `"hoch"` |
| `true_positives` | INTEGER | Nein | Echte Funde (kumulativ) | 5 |
| `false_positives` | INTEGER | Nein | False Positives (kumulativ) | 1 |
| `no_findings` | INTEGER | Nein | Clean Runs ohne Fund (kumulativ) | 42 |
| `effectiveness_period_days` | INTEGER | Nein | Zeitraum in Tagen fuer Effectiveness-Tracking | 90 |
| `last_triggered_at` | TEXT | Nein | Letzter Zeitpunkt an dem der Check einen Fund hatte | `"2026-03-15T10:00:00+00:00"` |
| `created_at` | TEXT | Ja | Erstellungszeitpunkt | `"2026-03-10 09:00:00"` |
| `updated_at` | TEXT | Ja | Letzter Update-Zeitpunkt | `"2026-03-20 09:00:00"` |

### 16.8.4 Datenherkunft

| Quelle | Wann |
|--------|------|
| `write_check_proposal()` in `agentkit.failure_corpus.storage` | Bei Check-Erstellung und Status-Aenderungen |
| `write_check_metrics()` in `agentkit.failure_corpus.storage` | Bei Wirksamkeits-Update |
| Structural-Check-Skript | Nach jedem Check-Run: Inkrementiert `true_positives`, `false_positives`, oder `no_findings` |

**F-16-015 — Check-Dual-Write (FK-16-015):** `write_check_proposal()`
und `write_check_metrics()` schreiben nach dem Datei-Write
zusaetzlich in `fc_check_proposals`.

**F-16-016 — Effectiveness-Counters inline (FK-16-016):** Die
Counter aus `CheckEffectivenessMetrics` sind direkt in der Tabelle
statt in einer separaten Tabelle, da sie immer zusammen mit dem
Check-Proposal abgefragt werden.

### 16.8.5 Dashboard-Queries

**Query 1 — Check-Status-Uebersicht**
```sql
SELECT status,
       COUNT(*) AS count
FROM fc_check_proposals
GROUP BY status
ORDER BY
    CASE status
        WHEN 'active' THEN 1
        WHEN 'draft' THEN 2
        WHEN 'approved' THEN 3
        WHEN 'tuned' THEN 4
        WHEN 'retired' THEN 5
        WHEN 'rejected' THEN 6
    END;
```

**Query 2 — Wirksamkeit aktiver Checks**
```sql
SELECT check_id, check_type, invariant,
       true_positives, false_positives, no_findings,
       CASE
           WHEN true_positives + false_positives = 0 THEN 0
           ELSE ROUND(100.0 * true_positives / (true_positives + false_positives), 1)
       END AS precision_pct,
       last_triggered_at
FROM fc_check_proposals
WHERE status = 'active'
ORDER BY false_positives DESC;
```

**Query 3 — Kandidaten fuer Auto-Deaktivierung (FK-10-080)**
```sql
SELECT check_id, check_type, invariant, false_positives, no_findings,
       last_triggered_at
FROM fc_check_proposals
WHERE status = 'active'
  AND last_triggered_at < datetime('now', '-90 days')
  AND false_positives > 3;
```

**Query 4 — Check-Typ-Verteilung**
```sql
SELECT check_type,
       COUNT(*) AS total,
       SUM(CASE WHEN status = 'active' THEN 1 ELSE 0 END) AS active,
       SUM(CASE WHEN status = 'retired' THEN 1 ELSE 0 END) AS retired
FROM fc_check_proposals
GROUP BY check_type;
```

**Query 5 — Checks nach Pattern-Referenz (Traceability)**
```sql
SELECT cp.check_id, cp.status, cp.check_type,
       p.category, p.risk_level, p.incident_count
FROM fc_check_proposals cp
LEFT JOIN fc_patterns p ON cp.pattern_ref = p.pattern_id
WHERE cp.status IN ('active', 'approved', 'draft')
ORDER BY p.risk_level DESC, cp.status;
```

---

## 16.9 Integritaets-Checks

### 16.9.1 Zweck

Deterministische Checks die sicherstellen, dass die DB-Kopie
konsistent mit den Primaer-Artefakten und der Telemetrie ist.
Diese Checks laufen als Teil des Postflight (Kap. 25.11) und
koennen auch manuell via CLI ausgefuehrt werden.

### 16.9.2 Check-Katalog

**F-16-017 — QA-Findings-Vollstaendigkeit (FK-16-017):** Fuer
jede JSON-Artefaktdatei in `_temp/qa/{story_id}/` muss
mindestens ein korrespondierender Row in `qa_findings` existieren.

```sql
-- Check: Gibt es eine Stage-Datei ohne DB-Eintrag?
-- Input: story_id, attempt
SELECT stage_id FROM qa_stage_results
WHERE story_id = ? AND attempt = ?;
-- Vergleich mit vorhandenen JSON-Dateien im Dateisystem.
-- Fehlende DB-Eintraege fuer vorhandene Dateien = Integritaetsfehler.
```

**F-16-018 — Pflichtfeld-Validierung (FK-16-018):** Kein NOT-NULL-
Feld darf leer sein wo es semantisch gefuellt sein muss.

```python
def check_mandatory_fields(story_id: str, db_path: str = DB_PATH) -> list[str]:
    """Prueft ob alle Pflichtfelder in qa_findings befuellt sind."""
    violations = []
    with _open_connection(db_path) as conn:
        # check_id darf nicht leer sein
        count = conn.execute(
            "SELECT COUNT(*) FROM qa_findings WHERE story_id = ? AND check_id = ''",
            (story_id,),
        ).fetchone()[0]
        if count > 0:
            violations.append(f"{count} qa_findings rows with empty check_id")

        # source_agent darf nicht leer sein
        count = conn.execute(
            "SELECT COUNT(*) FROM qa_findings WHERE story_id = ? AND source_agent = ''",
            (story_id,),
        ).fetchone()[0]
        if count > 0:
            violations.append(f"{count} qa_findings rows with empty source_agent")

        # stage_id darf nicht leer sein
        count = conn.execute(
            "SELECT COUNT(*) FROM qa_findings WHERE story_id = ? AND stage_id = ''",
            (story_id,),
        ).fetchone()[0]
        if count > 0:
            violations.append(f"{count} qa_findings rows with empty stage_id")
    return violations
```

**F-16-019 — Event-Konsistenz (FK-16-019):** Jeder Row in
`qa_stage_results` muss eine korrespondierende `run_id` in der
`events`-Tabelle haben (mindestens ein Event mit dieser run_id).

```sql
-- Verwaiste qa_stage_results ohne Events:
SELECT qsr.story_id, qsr.run_id, qsr.stage_id
FROM qa_stage_results qsr
WHERE NOT EXISTS (
    SELECT 1 FROM events e WHERE e.run_id = qsr.run_id
);
-- Ergebnis muss leer sein.
```

**F-16-020 — Metriken-Vollstaendigkeit bei Closure (FK-16-020):**
Bei Story-Closure muss ein Row in `story_metrics` existieren.

```sql
-- Check bei Closure (story_id = ?):
SELECT COUNT(*) FROM story_metrics WHERE story_id = ?;
-- Ergebnis muss >= 1 sein.
```

**F-16-021 — Incident-JSONL-DB-Paritaet (FK-16-021):** Die Anzahl
Incidents in `fc_incidents` muss der Zeilenanzahl in
`incidents.jsonl` entsprechen.

```python
def check_incident_parity(corpus_dir: str = CORPUS_DIR, db_path: str = DB_PATH) -> bool:
    """Vergleicht Incident-Count zwischen JSONL und DB."""
    jsonl_count = sum(1 for line in open(Path(corpus_dir) / "incidents.jsonl")
                      if line.strip())
    with _open_connection(db_path) as conn:
        db_count = conn.execute("SELECT COUNT(*) FROM fc_incidents").fetchone()[0]
    return jsonl_count == db_count
```

**F-16-022 — Stage-Result-Finding-Konsistenz (FK-16-022):** Die
Summe der `failed`-Zaehler in `qa_stage_results` muss mit der
Anzahl FAIL-Rows in `qa_findings` fuer dieselbe Story/Attempt/Stage
uebereinstimmen.

```sql
-- Inkonsistenz-Erkennung:
SELECT qsr.story_id, qsr.attempt, qsr.stage_id,
       qsr.failed AS stage_claims,
       COALESCE(f.actual_fails, 0) AS actual_fails
FROM qa_stage_results qsr
LEFT JOIN (
    SELECT story_id, attempt, stage_id, COUNT(*) AS actual_fails
    FROM qa_findings
    WHERE status = 'FAIL'
    GROUP BY story_id, attempt, stage_id
) f ON qsr.story_id = f.story_id
   AND qsr.attempt = f.attempt
   AND qsr.stage_id = f.stage_id
WHERE qsr.failed != COALESCE(f.actual_fails, 0);
-- Ergebnis muss leer sein.
```

### 16.9.3 Ausfuehrung

**F-16-023 — Postflight-Integration (FK-16-023):** Die
Integritaets-Checks werden als zusaetzlicher Postflight-Check
ausgefuehrt (Kap. 25.11). FAIL fuehrt zu einer Warnung (nicht
Blockade, da Primaer-Artefakte intakt sind).

**F-16-024 — CLI-Befehl (FK-16-024):** Die Checks sind manuell
ausfuehrbar via:

```bash
agentkit db-integrity --story ODIN-042
agentkit db-integrity --all  # Alle Stories pruefen
```

---

## 16.10 Write-API

### 16.10.1 Architektur

Jeder QA-Producer erhaelt eine duenne Write-Funktion, die nach
dem JSON-Artefakt-Write die korrespondierenden DB-Rows schreibt.

**F-16-025 — Write-Modul (FK-16-025):** Alle DB-Write-Funktionen
fuer die QA-Aggregation liegen in einem eigenen Modul:
`agentkit.telemetry.qa_store`. Dieses Modul importiert
`_open_connection` und `DB_PATH` aus `agentkit.telemetry.events`.

### 16.10.2 Funktionssignaturen

```python
# agentkit/telemetry/qa_store.py

def insert_qa_findings(
    story_id: str,
    run_id: str,
    attempt: int,
    stage_id: str,
    source_agent: str,
    checks: list[dict],
    ts: str,
    *,
    db_path: str = DB_PATH,
) -> int:
    """Schreibt eine Liste von Check-Ergebnissen in qa_findings.

    Args:
        checks: Liste von Dicts mit mindestens:
            check_id, status, severity, blocking.
            Optional: category, reason, description, detail, metadata.

    Returns:
        Anzahl geschriebener Rows.
    """

def insert_stage_result(
    story_id: str,
    run_id: str,
    attempt: int,
    stage_id: str,
    layer: int,
    kind: str,
    producer: str,
    status: str,
    summary: dict,
    ts: str,
    *,
    duration_ms: int | None = None,
    db_path: str = DB_PATH,
) -> bool:
    """Schreibt ein Stage-Gesamtergebnis in qa_stage_results.

    Args:
        summary: Dict mit total_checks, passed, failed, skipped,
                 blocking_failures, major_failures, minor_failures.

    Returns:
        True bei Erfolg, False bei Fehler.
    """

def insert_story_metrics(
    story_id: str,
    run_id: str,
    metrics: WorkflowMetrics,
    *,
    final_status: str = "PASS",
    db_path: str = DB_PATH,
) -> bool:
    """Schreibt Workflow-Metriken + Experiment-Tags in story_metrics.

    Returns:
        True bei Erfolg, False bei Fehler.
    """

def insert_fc_incident(
    incident: Incident,
    *,
    db_path: str = DB_PATH,
) -> bool:
    """Schreibt einen Failure-Corpus-Incident in fc_incidents.

    Returns:
        True bei Erfolg, False bei Fehler.
    """

def insert_fc_pattern(
    pattern: Pattern,
    *,
    db_path: str = DB_PATH,
) -> bool:
    """Schreibt ein Failure-Corpus-Pattern in fc_patterns.

    Returns:
        True bei Erfolg, False bei Fehler.
    """

def upsert_fc_check_proposal(
    proposal: CheckProposal,
    metrics: CheckEffectivenessMetrics | None = None,
    *,
    db_path: str = DB_PATH,
) -> bool:
    """Schreibt oder aktualisiert ein Check-Proposal in fc_check_proposals.

    Returns:
        True bei Erfolg, False bei Fehler.
    """
```

### 16.10.3 Fehlerbehandlung

**F-16-026 — Non-Blocking Writes (FK-16-026):** Alle Write-
Funktionen fangen `sqlite3.OperationalError` und
`sqlite3.DatabaseError`, loggen eine Warnung und geben `False`
zurueck. Ein DB-Write-Fehler darf die Pipeline nie blockieren —
die JSON-Artefakte sind primaer.

```python
try:
    with _open_connection(db_path) as conn:
        ensure_qa_aggregation_schema(db_path)
        conn.executemany(...)
except (sqlite3.OperationalError, sqlite3.DatabaseError) as exc:
    _log.warning("qa_store: write failed — %s", exc)
    return False
return True
```

**F-16-027 — Schema-Ensure bei jedem Write (FK-16-027):** Jede
Write-Funktion ruft `ensure_qa_aggregation_schema()` auf, bevor
sie Rows einfuegt. Das ist idempotent und stellt sicher, dass
die Tabellen existieren, auch wenn die DB neu erstellt wurde.

---

## 16.11 Backfill-Mechanismus

### 16.11.1 Zweck

Bestehende JSON/JSONL-Artefakte koennen nachtraeglich in die
DB importiert werden (fuer historische Daten vor Einfuehrung
der DB-Tabellen).

**F-16-028 — Backfill-CLI (FK-16-028):** Ein CLI-Befehl
importiert historische Daten:

```bash
# QA-Artefakte aller Stories im _temp/qa/ Verzeichnis importieren
agentkit db-backfill --qa-artifacts

# Failure Corpus importieren
agentkit db-backfill --failure-corpus

# Story-Metriken aus closure.json-Dateien importieren
agentkit db-backfill --metrics

# Alles
agentkit db-backfill --all
```

**F-16-029 — Idempotenter Backfill (FK-16-029):** Der Backfill
nutzt `INSERT OR IGNORE` fuer Tabellen mit UNIQUE-Constraints
(story_metrics, fc_incidents, fc_patterns, fc_check_proposals)
und ist daher wiederholbar.

### 16.11.2 Backfill-Ablauf

```python
def backfill_qa_artifacts(qa_dir: Path, db_path: str = DB_PATH) -> int:
    """Importiert QA-Artefakt-JSON-Dateien in qa_findings + qa_stage_results.

    Iteriert ueber alle story_id-Unterverzeichnisse in qa_dir.
    Pro Story: Liest jede {stage_id}.json, extrahiert Checks,
    schreibt in DB.

    Returns:
        Anzahl importierter Stories.
    """

def backfill_failure_corpus(corpus_dir: Path, db_path: str = DB_PATH) -> int:
    """Importiert incidents.jsonl und patterns.jsonl in fc_incidents + fc_patterns.

    Returns:
        Anzahl importierter Records.
    """

def backfill_metrics(closure_dirs: list[Path], db_path: str = DB_PATH) -> int:
    """Importiert closure.json-Dateien in story_metrics.

    Returns:
        Anzahl importierter Metriken-Records.
    """
```

---

## 16.12 Zusammenfassung: Tabellen-Uebersicht

| Tabelle | Zeilen pro | Primaer-Artefakt | Haupt-Aggregationen |
|---------|-----------|------------------|---------------------|
| `schema_versions` | 1 pro Schema+Version | — | Schema-Migrations-Status |
| `qa_findings` | 1 pro Check pro Stage pro Attempt | `_temp/qa/{id}/{stage}.json` | Check-Failure-Rate, Agent-Vergleich, Severity-Verteilung |
| `qa_stage_results` | 1 pro Stage pro Attempt | `_temp/qa/{id}/{stage}.json` | Stage-Failure-Rate, Duration-Tracking, Schicht-Uebersicht |
| `story_metrics` | 1 pro Story | `_temp/closure/{id}/closure.json` | Typ-Analyse, Trends, Config-Vergleich |
| `fc_incidents` | 1 pro Incident | `.agentkit/failure-corpus/incidents.jsonl` | Kategorie-Trends, Monatszaehler, Phase-Analyse |
| `fc_patterns` | 1 pro Pattern | `.agentkit/failure-corpus/patterns.jsonl` | Pattern-Pipeline, Kategorie-Verteilung |
| `fc_check_proposals` | 1 pro Check | `.agentkit/failure-corpus/checks/CHK-*/proposal.json` + `metrics.json` | Wirksamkeit, Status-Uebersicht, Auto-Deaktivierung |

### 16.12.1 Beziehungen (logische Foreign Keys)

```
events.run_id           ←→ qa_findings.run_id
events.run_id           ←→ qa_stage_results.run_id
events.story_id         ←→ story_metrics.story_id
qa_findings.story_id    ←→ qa_stage_results.story_id (+ attempt, stage_id)
qa_findings.story_id    ←→ story_metrics.story_id
fc_incidents.story_id   ←→ story_metrics.story_id
fc_incidents.incident_id ∈  fc_patterns.incident_refs (JSON-Array)
fc_patterns.pattern_id  ←→ fc_check_proposals.pattern_ref
```

**F-16-030 — Keine FOREIGN KEY Constraints (FK-16-030):** SQLite
Foreign Keys sind nicht enforced per Default und erfordern
`PRAGMA foreign_keys = ON` pro Connection. Da die DB-Tabellen
sekundaere Kopien sind und die Schreib-Reihenfolge nicht
garantiert werden kann (z.B. Incident vor Story-Closure), werden
Foreign Keys als logische, nicht als technische Constraints
implementiert. Die Integritaets-Checks (16.9) pruefen die
Referenzen deterministisch.

---

## 16.13 Performance-Ueberlegungen

**F-16-031 — WAL-Modus fuer Concurrent Access (FK-16-031):**
Alle Connections nutzen `_open_connection()` mit WAL-Modus +
`busy_timeout=5000ms`. Das erlaubt einen Writer und beliebig
viele Reader gleichzeitig (Kap. 14.3.4).

**F-16-032 — Batch-Insert fuer Findings (FK-16-032):**
`insert_qa_findings()` nutzt `executemany()` statt einer
Schleife von `execute()`-Aufrufen. Eine Structural-Check-Stage
kann 18+ Checks haben — Batch-Insert ist deutlich effizienter.

**F-16-033 — Index-Strategie (FK-16-033):** Indexes sind auf
die haeufigsten Dashboard-Queries ausgelegt:
- `qa_findings`: story_id+attempt (Story-Drill-Down),
  stage_id+status (Stage-Analyse), check_id+status (Check-Trend),
  ts (Zeitfilter), severity+blocking (Severity-Report)
- `qa_stage_results`: story_id+attempt, stage_id+status, ts
- `story_metrics`: story_type, completed_at, agentkit_version,
  config_version
- `fc_incidents`: category, severity, story_id, timestamp,
  status, phase
- `fc_patterns`: category, status, risk_level
- `fc_check_proposals`: status, pattern_ref, check_type

**F-16-034 — DB-Groessen-Abschaetzung (FK-16-034):** Bei
geschaetzten 20 Stories/Monat mit je ~30 QA-Findings pro Attempt
und durchschnittlich 1.5 Attempts: ~900 Finding-Rows/Monat.
Nach einem Jahr: ~10.800 Finding-Rows + ~360 story_metrics-Rows
+ ~240 Incident-Rows. SQLite skaliert problemlos bis zu
mehreren Millionen Rows pro Tabelle. Kein Partitioning oder
Archivierung noetig.

---

## 16.14 Installer-Integration

**F-16-035 — Bootstrap bei Install (FK-16-035):** Der Installer
(Kap. 50, Checkpoint 6) ruft nach `bootstrap_db()` zusaetzlich
`ensure_qa_aggregation_schema()` auf. Die neuen Tabellen werden
gemeinsam mit der `events`-Tabelle bootstrapped.

**F-16-036 — Upgrade-Kompatibilitaet (FK-16-036):** Bei einem
Upgrade von einer AgentKit-Version ohne QA-Aggregation-Tabellen
auf eine Version mit Tabellen: `ensure_qa_aggregation_schema()`
prueft die schema_versions-Tabelle und erstellt fehlende Tabellen
automatisch. Keine manuelle Migration noetig. Bestehende Daten
bleiben unberuehrt. Der Backfill-CLI-Befehl (16.11) kann
historische Daten nachtraeglich importieren.

---

## 16.15 Komplettes DDL (Referenz)

Das folgende DDL-Skript erstellt alle Tabellen und Indexes dieses
Kapitels. Es ist idempotent (alle Statements nutzen
`IF NOT EXISTS`).

```sql
-- Schema-Versionierung
CREATE TABLE IF NOT EXISTS schema_versions (
    schema_name    TEXT NOT NULL,
    version        INTEGER NOT NULL,
    applied_at     TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (schema_name, version)
);

-- QA Findings (atomare Check-Ergebnisse)
CREATE TABLE IF NOT EXISTS qa_findings (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    story_id        TEXT NOT NULL,
    run_id          TEXT NOT NULL,
    attempt         INTEGER NOT NULL DEFAULT 1,
    stage_id        TEXT NOT NULL,
    check_id        TEXT NOT NULL,
    status          TEXT NOT NULL,
    severity        TEXT NOT NULL,
    blocking        INTEGER NOT NULL DEFAULT 0,
    source_agent    TEXT NOT NULL,
    category        TEXT NOT NULL DEFAULT '',
    reason          TEXT NOT NULL DEFAULT '',
    description     TEXT NOT NULL DEFAULT '',
    detail          TEXT NOT NULL DEFAULT '',
    metadata        TEXT,
    ts              TEXT NOT NULL,
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_qa_findings_story
    ON qa_findings(story_id, attempt);
CREATE INDEX IF NOT EXISTS idx_qa_findings_stage
    ON qa_findings(stage_id, status);
CREATE INDEX IF NOT EXISTS idx_qa_findings_check
    ON qa_findings(check_id, status);
CREATE INDEX IF NOT EXISTS idx_qa_findings_ts
    ON qa_findings(ts);
CREATE INDEX IF NOT EXISTS idx_qa_findings_severity
    ON qa_findings(severity, blocking);

-- QA Stage Results (aggregierte Stage-Ergebnisse)
CREATE TABLE IF NOT EXISTS qa_stage_results (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    story_id        TEXT NOT NULL,
    run_id          TEXT NOT NULL,
    attempt         INTEGER NOT NULL DEFAULT 1,
    stage_id        TEXT NOT NULL,
    layer           INTEGER NOT NULL,
    kind            TEXT NOT NULL,
    producer        TEXT NOT NULL,
    status          TEXT NOT NULL,
    blocking        INTEGER NOT NULL DEFAULT 1,
    total_checks    INTEGER NOT NULL DEFAULT 0,
    passed          INTEGER NOT NULL DEFAULT 0,
    failed          INTEGER NOT NULL DEFAULT 0,
    skipped         INTEGER NOT NULL DEFAULT 0,
    blocking_failures INTEGER NOT NULL DEFAULT 0,
    major_failures  INTEGER NOT NULL DEFAULT 0,
    minor_failures  INTEGER NOT NULL DEFAULT 0,
    duration_ms     INTEGER,
    ts              TEXT NOT NULL,
    created_at      TEXT DEFAULT (datetime('now')),
    UNIQUE(story_id, run_id, attempt, stage_id)
);

CREATE INDEX IF NOT EXISTS idx_qa_stage_results_story
    ON qa_stage_results(story_id, attempt);
CREATE INDEX IF NOT EXISTS idx_qa_stage_results_status
    ON qa_stage_results(stage_id, status);
CREATE INDEX IF NOT EXISTS idx_qa_stage_results_ts
    ON qa_stage_results(ts);

-- Story Metrics (Workflow-Metriken + Experiment-Tags)
CREATE TABLE IF NOT EXISTS story_metrics (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    story_id                TEXT NOT NULL UNIQUE,
    run_id                  TEXT NOT NULL,
    story_type              TEXT NOT NULL DEFAULT '',
    story_size              TEXT NOT NULL DEFAULT '',
    mode                    TEXT NOT NULL DEFAULT '',
    processing_time_min     REAL NOT NULL DEFAULT 0.0,
    qa_rounds               INTEGER NOT NULL DEFAULT 0,
    adversarial_findings    INTEGER NOT NULL DEFAULT 0,
    adversarial_tests_created INTEGER NOT NULL DEFAULT 0,
    files_changed           INTEGER NOT NULL DEFAULT 0,
    increments              INTEGER NOT NULL DEFAULT 0,
    final_status            TEXT NOT NULL DEFAULT '',
    agentkit_version        TEXT NOT NULL DEFAULT '',
    agentkit_commit         TEXT NOT NULL DEFAULT '',
    config_version          TEXT NOT NULL DEFAULT '',
    llm_roles               TEXT,
    completed_at            TEXT NOT NULL DEFAULT '',
    created_at              TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_story_metrics_type
    ON story_metrics(story_type);
CREATE INDEX IF NOT EXISTS idx_story_metrics_completed
    ON story_metrics(completed_at);
CREATE INDEX IF NOT EXISTS idx_story_metrics_version
    ON story_metrics(agentkit_version);
CREATE INDEX IF NOT EXISTS idx_story_metrics_config
    ON story_metrics(config_version);

-- Failure Corpus: Incidents
CREATE TABLE IF NOT EXISTS fc_incidents (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    incident_id     TEXT NOT NULL UNIQUE,
    story_id        TEXT NOT NULL,
    run_id          TEXT NOT NULL DEFAULT '',
    timestamp       TEXT NOT NULL,
    category        TEXT NOT NULL,
    severity        TEXT NOT NULL,
    phase           TEXT NOT NULL DEFAULT 'implementation',
    role            TEXT NOT NULL DEFAULT 'worker',
    model           TEXT NOT NULL DEFAULT '',
    symptom         TEXT NOT NULL,
    impact          TEXT NOT NULL DEFAULT '',
    status          TEXT NOT NULL DEFAULT 'open',
    tags            TEXT,
    evidence_refs   TEXT,
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_fc_incidents_category
    ON fc_incidents(category);
CREATE INDEX IF NOT EXISTS idx_fc_incidents_severity
    ON fc_incidents(severity);
CREATE INDEX IF NOT EXISTS idx_fc_incidents_story
    ON fc_incidents(story_id);
CREATE INDEX IF NOT EXISTS idx_fc_incidents_ts
    ON fc_incidents(timestamp);
CREATE INDEX IF NOT EXISTS idx_fc_incidents_status
    ON fc_incidents(status);
CREATE INDEX IF NOT EXISTS idx_fc_incidents_phase
    ON fc_incidents(phase);

-- Failure Corpus: Patterns
CREATE TABLE IF NOT EXISTS fc_patterns (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    pattern_id      TEXT NOT NULL UNIQUE,
    category        TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'candidate',
    invariant       TEXT NOT NULL,
    promotion_rule  TEXT NOT NULL,
    risk_level      TEXT NOT NULL DEFAULT 'mittel',
    owner           TEXT NOT NULL DEFAULT '',
    incident_count  INTEGER NOT NULL DEFAULT 0,
    confirmed_at    TEXT NOT NULL DEFAULT '',
    confirmed_by    TEXT NOT NULL DEFAULT '',
    incident_refs   TEXT,
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_fc_patterns_category
    ON fc_patterns(category);
CREATE INDEX IF NOT EXISTS idx_fc_patterns_status
    ON fc_patterns(status);
CREATE INDEX IF NOT EXISTS idx_fc_patterns_risk
    ON fc_patterns(risk_level);

-- Failure Corpus: Check Proposals + Effectiveness
CREATE TABLE IF NOT EXISTS fc_check_proposals (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    check_id            TEXT NOT NULL UNIQUE,
    pattern_ref         TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'draft',
    check_type          TEXT NOT NULL,
    invariant           TEXT NOT NULL,
    pipeline_stage      TEXT NOT NULL DEFAULT 'structural',
    pipeline_layer      INTEGER NOT NULL DEFAULT 1,
    owner               TEXT NOT NULL DEFAULT '',
    false_positive_risk TEXT NOT NULL DEFAULT 'niedrig',
    true_positives      INTEGER NOT NULL DEFAULT 0,
    false_positives     INTEGER NOT NULL DEFAULT 0,
    no_findings         INTEGER NOT NULL DEFAULT 0,
    effectiveness_period_days INTEGER NOT NULL DEFAULT 90,
    last_triggered_at   TEXT NOT NULL DEFAULT '',
    created_at          TEXT DEFAULT (datetime('now')),
    updated_at          TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_fc_checks_status
    ON fc_check_proposals(status);
CREATE INDEX IF NOT EXISTS idx_fc_checks_pattern
    ON fc_check_proposals(pattern_ref);
CREATE INDEX IF NOT EXISTS idx_fc_checks_type
    ON fc_check_proposals(check_type);

-- Schema-Version registrieren
INSERT OR IGNORE INTO schema_versions (schema_name, version)
VALUES ('qa_aggregation', 1);
```

---

*FK-Referenzen: FK-16-001 bis FK-16-036 (QA-Telemetrie-Aggregation
und Dashboard-Datenmodell komplett)*
