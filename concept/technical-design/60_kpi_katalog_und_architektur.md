---
concept_id: FK-60
title: KPI-Katalog und Analytics-Architektur
module: kpi-catalog
status: active
doc_kind: core
parent_concept_id:
authority_over:
  - scope: kpi-catalog
defers_to:
  - target: FK-14
    scope: event-infrastructure
    reason: Event model, event catalog, and SQLite schema defined in FK-14; FK-60 consumes events as raw data source
supersedes: []
superseded_by:
tags: [kpi, analytics, architecture, sqlite, metrics]
---

# 60 — KPI-Katalog und Analytics-Architektur

## 60.1 Zweck

Dieses Dokument definiert den vollstaendigen Katalog aller KPIs fuer
AgentKit, die Infrastruktur-Architektur fuer deren Speicherung und
die Designprinzipien fuer Erhebung, Aggregation und Auswertung.

Es ist das Meta-Dokument des Analytics-Blocks (Nummernkreis 60-69):

| Dokument | Scope |
|----------|-------|
| **FK-60** (dieses) | KPI-Katalog, Architektur-Ueberblick, Designprinzipien, Abgrenzungen |
| FK-61 | KPI-Erhebung nach Domaenen (Hooks, Events, Rohdatenerfassung) |
| FK-62 | KPI-Aggregation (Berechnungslogik, Fact-Tabellen, Refresh) |
| FK-63 | Auswertung und Dashboard (UI, Query-Workbench, Analyse-Moeglichkeiten) |

### 60.1.1 Nummernkreise der technischen Konzepte

| Nummernkreis | Domaene | Beschreibung |
|---|---|---|
| 00-09 | Foundation | Systemkontext, Domaenenmodell, Konfiguration |
| 10-19 | Infrastruktur | Runtime, LLM-Pools, GitHub, VektorDB, Event-Infrastruktur, Security |
| 20-29 | Pipeline & Workflow | Story-Creation, Setup, Exploration, Implementation, Verify, Evidence |
| 30-39 | Governance & Guards | Hooks, Guards, Dokumententreue, Checks, LLM-Bewertungen, Integrity-Gate |
| 40-49 | Integrationen | ARE, Failure Corpus, CCAG, Skills |
| 50-59 | Operations & Betrieb | Installer, Upgrade, Monitoring |
| **60-69** | **Analytics, KPIs & Dashboard** | **KPI-Katalog, Erhebung, Aggregation, Auswertung** |
| 90-99 | Referenz & Kataloge | Schemata, API-Katalog, Konventionen, Schwellwerte |

### 60.1.2 Abgrenzung zu bestehenden Konzepten

| Konzept | Autoritaet fuer | Beziehung zu FK-60ff |
|---------|-----------------|----------------------|
| FK-14 (Event-Infrastruktur) | Event-Modell, Event-Katalog, SQLite-Schema (`events`-Tabelle), Hook-Mechanik | FK-60ff konsumiert Events als Rohdatenquelle. FK-14 definiert WAS ein Event ist. FK-60ff definiert WAS eine KPI ist. |
| FK-16 (QA-/FC-Raw-Store) | Querybare SQLite-Spiegel (`qa_findings`, `story_metrics`, `fc_*`) in raw.db | FK-62 baut die Analytics-Schicht (analytics.db) auf diesen Raw-Tabellen auf. Dashboard-Autoritaet wandert von FK-16 nach FK-63. |
| FK-41 (Failure Corpus) | Incident-Lifecycle, Pattern-Promotion, Check-Ableitung, Taxonomie | FK-60ff aggregiert UEBER FC-Entitaeten (Incidents, Patterns, Checks), definiert aber nicht deren Semantik oder Lifecycle. Analytics misst — Failure Corpus lernt. |
| FK-30 (Hook-Adapter) | Hook-Architektur, Registration, Matcher | FK-61 definiert neue Events/Erhebungspunkte. FK-30 definiert den Hook-Mechanismus ueber den sie transportiert werden. |
| FK-52 (Betrieb, Monitoring) | Operatives Monitoring (Pool-Health, Disk, Locks), CLI-Queries | FK-60ff ist analytisch (Trends, Optimierung). FK-52 ist operativ (Ist der Service gesund?). |

### 60.1.3 Authority-Split-Regel

Querschnittsthema KPIs wird ueber einen zentralen semantischen
Vertrag plus lokale Bindungspunkte behandelt:

- **FK-60-63** ist autoritativ fuer: KPI-Definition, Formel,
  Dimensionen, Aggregationslogik, Fact-Schema, Dashboard-Semantik
- **Domain-FKs** (25, 30, 34, etc.) sind autoritativ fuer:
  lokales Laufzeitverhalten, aus dem Events entstehen
- **FK-61** buendelt die Erhebungspunkte zentral (nicht in den
  Domain-FKs verstreut), verweist aber auf die Domain-FKs fuer
  die Prozess-Semantik

**Harte Regel**: Die KPI-Definition (Name, Formel, Koernung,
Entscheidungsfrage) steht ausschliesslich im Analytics-Block.
Domain-FKs wiederholen sie nicht. Sie beschreiben nur den
Producer-Vertrag: "An Stelle X wird Event Y emittiert."

---

## 60.2 Designprinzipien

### P1: Jede KPI beantwortet eine Entscheidungsfrage

Keine KPI ohne zugehoerige Handlung. Wenn nicht klar ist, welche
Entscheidung eine KPI informiert, wird sie nicht erhoben.

### P2: Erhebung am Hot Path, Aggregation im Batch

Rohdaten werden synchron im Hook-/Pipeline-Kontext geschrieben
(niedrige Latenz, kein Netzwerk). Aggregationen laufen asynchron
bei Story-Closure oder Dashboard-Start.

### P3: Zwei Datenbanken, eine Wahrheit

`raw.db` zusammen mit den kanonischen Pipeline-Artefakten
(`context.json`, `phase-state.json`, `handover.json`,
`decision.json` im Story-Verzeichnis) bilden die kanonische
Datenquelle. `analytics.db` ist vollstaendig aus diesen Quellen
ableitbar und jederzeit neu berechenbar. Kein Datenverlust bei
Analytics-Verlust.

**Hinweis**: Die Pipeline-Artefakte sind Dateisystem-Objekte,
keine SQLite-Daten. Die Snapshot-Konsistenz zwischen raw.db und
den Artefakten ist nur bei Story-Closure gegeben (alle Artefakte
sind zu diesem Zeitpunkt finalisiert). Fuer laufende Stories
gibt es keine atomare Sicht ueber beide Quellen.

### P4: Breite Fact-Tabellen statt EAV

KPIs werden als typisierte Spalten in koernungsspezifischen
Fact-Tabellen gespeichert, nicht in einer generischen
Entity-Attribute-Value-Struktur. Das ergibt einfache Queries,
gute Dashboard-Tauglichkeit und Typsicherheit.

### P5: Drei Aggregationsebenen

Jede KPI hat genau eine primaere Koernung:

| Koernung | Granularitaet | Beispiel |
|----------|---------------|----------|
| **Pro Story** | 1 Zeile pro abgeschlossener Story | `qa_round_count`, `adversarial_hit_rate` |
| **Pro Entitaet + Periode** | 1 Zeile pro Guard/Pool/Template pro Woche | `guard_violation_rate_by_guard`, `llm_availability_rate` |
| **Pro Periode** | 1 Zeile pro Woche/Monat (global) | `first_pass_success_rate`, `incident_volume_per_month` |

### P6: Perzentile in Python, nicht in SQL

SQLite hat kein natives `percentile_cont()`. KPIs die Perzentile
oder statistische Masse erfordern (`llm_response_time_p50`,
`story_predictability` als Varianz) werden
im Refresh-Worker in Python berechnet und als fertige Werte in
die Fact-Tabellen geschrieben.

### P7: Evolutionsfaehigkeit

Neue KPIs werden als `ALTER TABLE ADD COLUMN` in die bestehenden
Fact-Tabellen aufgenommen. Migrationen sind idempotent via
`PRAGMA table_info`-Introspection. Das Schema waechst mit dem
KPI-Katalog, ohne Rebuild.

### P8: Postgres als spaetere Evolutionsstufe

Die Architektur ist so gestaltet, dass ein spaeterer
One-Way-Export nach Postgres (fuer ad-hoc Analytics, freie
Slice-and-Dice-Exploration, Percentile-Aggregationen direkt
in SQL) moeglich ist, ohne das Grundmodell zu aendern.
Postgres wird erst eingefuehrt, wenn mindestens eines dieser
Kriterien zutrifft:

- Regelmaessige ad-hoc Percentile/Funnel-Analysen ueber lange
  Historien
- Mehrere Konsumenten greifen parallel auf Analytics zu
- Dashboard-Queries werden trotz Rollups unhandlich

---

## 60.3 Infrastruktur-Architektur

### 60.3.1 Zwei-Datei-Modell

```
Hook-Hot-Path (synchron, latenzkritisch)
    │
    ▼
┌──────────────┐     ┌─────────────────────────┐
│   raw.db     │     │ Pipeline-Artefakte       │
│              │     │ (Dateisystem, pro Story)  │
│  - events    │     │  - context.json           │
│  - qa_*      │     │  - phase-state.json       │
│  - story_*   │     │  - handover.json          │
│  - fc_*      │     │  - decision.json          │
└──────┬───────┘     └──────────┬──────────────┘
       │                        │
       └────────┬───────────────┘
                │  Refresh-Worker (Python, bei Closure / Dashboard-Start)
                │  liest read-only aus beiden Quellen
                ▼
┌──────────────┐
│ analytics.db │  SQLite, WAL-Modus, STRICT-Tabellen
│              │  - fact_story
│              │  - fact_guard_period
│              │  - fact_pool_period
│              │  - fact_pipeline_period
│              │  - fact_corpus_period
│              │  - sync_state
└──────────────┘
                │
                ▼
┌──────────────┐
│  Dashboard   │  liest read-only aus analytics.db
│  (Chart.js)  │  + Live-Sicht aus raw.db fuer laufende Stories
└──────────────┘
```

### 60.3.2 Begruendung des Zwei-Datei-Modells

**Problem**: Hooks schreiben synchron in SQLite (WAL, ein Writer).
Ein Refresh-Job der gleichzeitig Rollup-Tabellen aktualisiert
wuerde mit dem Hook um den Write-Lock konkurrieren. SQLite hat
genau einen Writer pro Datei.

**Loesung**: Separate Dateien isolieren den Hot Path (raw.db) vom
Analytics-Refresh (analytics.db). Kein Writer-Contention.

**Verworfene Alternativen**:

| Alternative | Verworfen weil |
|-------------|----------------|
| Eine SQLite-DB fuer alles | Writer-Contention zwischen Hooks und Refresh-Job |
| Postgres als sofortige zweite Schicht | Over-Engineering bei 10k-100k Events/Jahr, doppelte Wahrheitsschicht, ETL-Komplexitaet |
| EAV-Tabelle (`metric_value`) | Schlechtes Serving-Modell, Query-Komplexitaet, keine Typsicherheit |

### 60.3.3 raw.db (bestehend, unveraendert)

Die bestehende `_temp/agentkit.db` wird zu `raw.db` (logischer
Name; der physische Pfad bleibt `_temp/agentkit.db` fuer
Rueckwaertskompatibilitaet).

Schema: Unveraendert. Alle bestehenden Tabellen und Indexe
bleiben. Neue Events (FK-61) werden als neue `EventType`-Werte
hinzugefuegt, das Tabellenschema aendert sich nicht.

**Invariante**: `events` ist append-only. Keine Updates, keine
Deletes an historischen Events. Korrekturen nur ueber neue
kompensierende Events.

### 60.3.4 analytics.db (neu)

Pfad: `_temp/agentkit-analytics.db`

Alle Tabellen werden als `STRICT` angelegt (SQLite >= 3.37.0)
fuer Typ-Enforcement.

**Fact-Tabellen** (Detail-Schema in FK-62):

| Tabelle | Koernung | Primaerschluessel |
|---------|----------|-------------------|
| `fact_story` | 1 Zeile pro Story | `story_id` |
| `fact_guard_period` | 1 Zeile pro Guard pro Woche | `(guard_key, period_start)` |
| `fact_pool_period` | 1 Zeile pro Pool pro Woche | `(pool_key, period_start)` |
| `fact_pipeline_period` | 1 Zeile pro Woche | `period_start` |
| `fact_corpus_period` | 1 Zeile pro Monat | `period_start` |

**Sync-State**:

```sql
CREATE TABLE sync_state (
    key         TEXT PRIMARY KEY,
    value_int   INTEGER,
    value_text  TEXT,
    updated_at  TEXT NOT NULL
) STRICT;
```

Eintraege: `last_event_id` (monotoner Cursor), `last_synced_at`
(ISO 8601).

### 60.3.5 Sync-Mechanismus

**Trigger**: Kein Daemon, kein Cron. Zwei event-getriebene
Ausloeser:

1. **Story-Closure** (primaer): Nach Metriken-Berechnung und
   JSONL-Export ruft die Closure-Phase `sync_analytics()` auf.
2. **Dashboard-Start** (Catch-up): `agentkit dashboard` ruft
   beim Start `sync_analytics()` auf (best-effort, bei Lock
   wird mit vorhandenem Stand gestartet).

**Ablauf von `sync_analytics()`**:

1. Read-only Connection auf `raw.db` oeffnen
2. Read-write Connection auf `analytics.db` oeffnen
3. `sync_state.last_event_id` lesen
4. Konsistenten Snapshot auf `raw.db`: `watermark = MAX(event_id)`
5. Delta-Events lesen: `WHERE event_id > last_event_id AND event_id <= watermark`
6. **Dirty Sets** ableiten:
   - `dirty_story_ids`: Story-IDs aus Delta-Events
   - `dirty_guard_weeks`: `(guard_key, week_start)` aus Delta-Events
   - `dirty_pool_weeks`: `(pool_key, week_start)` aus Delta-Events
   - `dirty_pipeline_weeks`: `week_start` aus Delta-Events
   - `dirty_corpus_months`: `month_start` aus Delta-Events
7. Pro Dirty Set: Betroffene Slices **komplett neu berechnen**
   aus `raw.db` (kein inkrementelles Hochzaehlen)
8. **Eine Transaktion** auf `analytics.db`:
   - UPSERT `fact_story` fuer dirty Stories
   - DELETE+INSERT `fact_guard_period` fuer dirty Guard-Wochen
   - DELETE+INSERT `fact_pool_period` fuer dirty Pool-Wochen
   - DELETE+INSERT `fact_pipeline_period` fuer dirty Wochen
   - DELETE+INSERT `fact_corpus_period` fuer dirty Monate
   - UPDATE `sync_state` SET `last_event_id = watermark`
9. COMMIT

**Crash-Sicherheit**: Wenn der Prozess vor COMMIT crasht, ist
nichts sichtbar in `analytics.db`. Beim naechsten Lauf wird
derselbe Delta-Bereich erneut verarbeitet (idempotent).

**Laufende Stories**: Erscheinen nicht in `fact_story`. Das
Dashboard zeigt laufende Stories ueber eine separate Live-Sicht
direkt aus `raw.db` (aktueller Phasen-Status, bisherige
Laufzeit, bisherige Events).

---

## 60.4 KPI-Katalog

### 60.4.1 Legende

| Symbol | Bedeutung |
|--------|-----------|
| **AKTIV** | KPI wird in FK-61/62 ausgearbeitet und implementiert |
| INVENTAR | KPI ist identifiziert, aber nicht im ersten Release |
| `[R]` | Rohdaten bereits erhoben (Event existiert in raw.db) |
| `[N]` | Neues Event oder neuer Erhebungspunkt noetig |

### 60.4.2 Domaene 1 — Story-Dimensionierung und Pipeline-Steuerung

Entscheidungsfrage: Sind unsere Stories richtig geschnitten?
Funktioniert die Pipeline-Steuerung?

| KPI | Status | Daten | Koernung | Beschreibung |
|-----|--------|-------|----------|--------------|
| `compaction_count_per_story` | **AKTIV** | `[N]` | Story | Anzahl Context-Compactions pro Story. Hoch → Stories zu gross. Neues Event `compaction_event` noetig. |
| `qa_round_count` | **AKTIV** | `[R]` | Story | Verify-Remediation-Zyklen. Steigend → unterspezifizierte Stories |
| `processing_time_by_type_and_size` | **AKTIV** | `[R]` | Story | Durchlaufzeit nach Typ/Groesse. Kalibriert Schaetzer |
| `feedback_loop_convergence` | **AKTIV** | `[R]` | Story | Werden Findings in Runde N+1 geloest? Divergenz → Worker versteht Problem nicht |
| `execution_vs_exploration_ratio` | **AKTIV** | `[N]` | Periode | Anteil Execution vs. Exploration. 90% Exploration → unterkonzipiert |
| `blocked_ac_distribution` | **AKTIV** | `[R]` | Story | Welche ACs scheitern systematisch? → ACs unklar formuliert |
| `policy_required_stage_miss_rate` | **AKTIV** | `[R]` | Periode | Welche Pipeline-Stages werden uebersprungen? → Luecke in Execution |
| `compaction_recovery_count` | INVENTAR | `[N]` | Story | Resume-Capsule-Injections. Korrelation mit Story-Groesse |
| `preflight_gate_pass_rate` | INVENTAR | `[N]` | Periode | PASS/FAIL der 8 Setup-Preflight-Gates |
| `functional_failure_escalation_rate` | INVENTAR | `[N]` | Periode | Stories die max. Runden erreichen und eskalieren |
| `merge_conflict_rate` | INVENTAR | `[N]` | Periode | Closure-Versuche mit Merge-Konflikten |

### 60.4.3 Domaene 2 — LLM-Selektion und -Performance

Entscheidungsfrage: Welche LLMs setzen wir fuer welche Aufgaben ein?

| KPI | Status | Daten | Koernung | Beschreibung |
|-----|--------|-------|----------|--------------|
| `llm_response_time_p50` | **AKTIV** | `[R]` | Entitaet+Periode | Median-Antwortzeit pro Pool. In Python berechnet (P6) |
| `llm_verdict_adoption_rate` | **AKTIV** | `[N]` | Entitaet+Periode | Wurde LLM-Verdict in Policy-Decision uebernommen? |
| `llm_finding_precision` | **AKTIV** | `[N]` | Entitaet+Periode | True-Positive vs. False-Positive-Rate pro Pool |
| `llm_call_count_per_story` | **AKTIV** | `[R]` | Story | LLM-Aufrufe pro Story. Kosten-Proxy |
| `quorum_trigger_rate` | **AKTIV** | `[R]` | Entitaet+Periode | Wie oft Mediation noetig? Pro Story-Typ. Event `review_divergence` existiert bereits. |
| `llm_response_time_p95` | INVENTAR | `[R]` | Entitaet+Periode | 95. Perzentil. Ausreisser identifizieren |
| `llm_availability_rate` | INVENTAR | `[N]` | Entitaet+Periode | Acquire-Failures, Timeouts pro Pool |
| `pool_slot_utilization_trend` | INVENTAR | `[N]` | Entitaet+Periode | Pool-Auslastung ueber Zeit |
| `llm_dissent_rate` | INVENTAR | `[R]` | Entitaet+Periode | Divergenz-Rate zwischen Review-Paaren |

### 60.4.4 Domaene 3 — Governance-Gesundheit

Entscheidungsfrage: Funktionieren unsere Guards? Sind die Prompts
gut genug?

| KPI | Status | Daten | Koernung | Beschreibung |
|-----|--------|-------|----------|--------------|
| `guard_violation_count_by_type` | **AKTIV** | `[R]` | Entitaet+Periode | Violations pro Guard-Typ |
| `guard_violation_rate_by_guard` | **AKTIV** | `[N]` | Entitaet+Periode | Violations / Invokationen pro Guard |
| `prompt_integrity_violation_by_stage` | **AKTIV** | `[N]` | Entitaet+Periode | Welche der 3 Pruefstufen greift? |
| `governance_escape_detection_count` | **AKTIV** | `[N]` | Entitaet+Periode | Prompt-Injection-Versuche |
| `orchestrator_governance_violation_count` | **AKTIV** | `[N]` | Entitaet+Periode | Orchestrator liest/schreibt Code |
| `impact_violation_rate` | **AKTIV** | `[N]` | Periode | Implementierung ueberschreitet deklarierten Impact |
| `integrity_gate_block_rate` | **AKTIV** | `[N]` | Periode | Wie oft blockiert das Integrity-Gate? |
| `adversarial_sandbox_escape_count` | INVENTAR | `[N]` | Entitaet+Periode | Sandbox-Ausbruchsversuche |
| `compaction_agent_spawn_deny_count` | INVENTAR | `[N]` | Periode | Blockierte Agent-Spawns im Recovery |
| `integrity_gate_block_by_dimension` | INVENTAR | `[N]` | Periode | Aufschluesselung nach 7 Gate-Dimensionen |
| `guard_story_resolution_ambiguity_rate` | INVENTAR | `[N]` | Periode | Violations mit story_id=unknown |
| `risk_score_threshold_breach_frequency` | INVENTAR | `[N]` | Periode | Governance-Schwellenwert-Ueberschreitungen |

### 60.4.5 Domaene 4 — Dokumententreue und Konzept-Konformitaet

Entscheidungsfrage: Halten sich Agents an die konzeptionellen
Vorgaben?

| KPI | Status | Daten | Koernung | Beschreibung |
|-----|--------|-------|----------|--------------|
| `doc_fidelity_conflict_rate_by_level` | **AKTIV** | `[N]` | Periode | PASS/FAIL der 4 Dokumententreue-Ebenen |
| `doc_fidelity_escalation_count` | INVENTAR | `[N]` | Periode | Eskalationen wegen Dokumententreue-Konflikten |
| `worker_drift_detection_rate` | INVENTAR | `[R]` | Periode | Wie oft meldet drift_check ein drift_detected? |

### 60.4.6 Domaene 5 — QA-Effektivitaet

Entscheidungsfrage: Wird unser QA-Prozess mit der Zeit besser?

| KPI | Status | Daten | Koernung | Beschreibung |
|-----|--------|-------|----------|--------------|
| `first_pass_success_rate` | **AKTIV** | `[R]` | Periode | Stories die in Runde 1 PASS bekommen |
| `finding_survival_rate` | **AKTIV** | `[R]` | Periode | Findings die ueber mehrere Runden bestehen |
| `check_effectiveness_by_id` | **AKTIV** | `[R]` | Entitaet+Periode | Welche check_ids finden blocking Issues? |
| `adversarial_hit_rate` | **AKTIV** | `[R]` | Story | Findings / Tests created pro Story. Niedrig → zu konservativ. Wird zusaetzlich als Perioden-Durchschnitt in `fact_pipeline_period` aggregiert. |
| `adversarial_findings_count` | **AKTIV** | `[R]` | Story | Adversarial-Befunde pro Story |
| `adversarial_tests_created_count` | **AKTIV** | `[R]` | Story | Erzeugte Tests pro Story |
| `finding_resolution_quality` | **AKTIV** | `[N]` | Story | fully/partially/not_resolved pro Finding |
| `adversarial_test_pass_rate` | INVENTAR | `[R]` | Periode | Tests pass vs. fail. Immer pass → zu zahm |
| `mandatory_adversarial_target_fulfillment` | INVENTAR | `[N]` | Story | Tests fuer mandatory targets vs. UNRESOLVABLE |
| `worker_claim_reliability` | INVENTAR | `[N]` | Periode | ADDRESSED-Claims vs. Layer-2-Resolution |

### 60.4.7 Domaene 6 — Review-Qualitaet und Evidence Assembly

Entscheidungsfrage: Liefern wir den Reviewern die richtigen
Informationen?

| KPI | Status | Daten | Koernung | Beschreibung |
|-----|--------|-------|----------|--------------|
| `review_template_effectiveness` | **AKTIV** | `[R]` | Entitaet+Periode | Finding-Ausbeute pro Template |
| `skill_compliance_ratio` | INVENTAR | `[N]` | Periode | Anteil Agent-Spawns mit Skill-Attribution vs. ad-hoc. Voraussetzung: `skill_name`-Feld im Spawn-Schema-Header (~8 Zeilen Code-Change in prompt_integrity_guard.py + hook.py). |
| `evidence_assembly_completeness` | INVENTAR | `[N]` | Story | Fehlende cross-repo Dateien im Bundle |
| `preflight_request_resolution_rate` | INVENTAR | `[N]` | Entitaet+Periode | RESOLVED vs. NOT_FOUND pro Request-Typ |
| `preflight_effect_on_review_quality` | INVENTAR | `[N]` | Periode | Vorher/Nachher-Vergleich mit/ohne Preflight |
| `preflight_activation_rate` | INVENTAR | `[N]` | Periode | Wie oft Preflight-Turn ausgeloest? |
| `evidence_bundle_truncation_rate` | INVENTAR | `[N]` | Periode | Bundles ueber 350KB-Grenze |
| `context_sufficiency_level_distribution` | INVENTAR | `[N]` | Periode | Verteilung SUFFICIENT/GAPS/PARTIAL |

### 60.4.8 Domaene 7 — VektorDB und Wissensmanagement

Entscheidungsfrage: Funktioniert die semantische Suche?

| KPI | Status | Daten | Koernung | Beschreibung |
|-----|--------|-------|----------|--------------|
| `vectordb_similarity_threshold_calibration` | **AKTIV** | `[N]` | Periode | FP/FN-Rate des VektorDB-Abgleichs. Konzeptmandatiert (02 §2.1) |
| `vectordb_duplicate_detection_rate` | **AKTIV** | `[N]` | Periode | Echte Duplikate/Ueberschneidungen erkannt |
| `vectordb_conflict_escalation_count` | INVENTAR | `[N]` | Periode | VektorDB-Konflikt erzwingt Exploration-Mode |

### 60.4.9 Domaene 8 — ARE-Integration

Entscheidungsfrage: Funktioniert die Anforderungsverknuepfung?

| KPI | Status | Daten | Koernung | Beschreibung |
|-----|--------|-------|----------|--------------|
| `are_gate_result` | **AKTIV** | `[R]` | Story | PASS/FAIL des ARE-Gates |
| `are_evidence_coverage_rate` | **AKTIV** | `[N]` | Story | Anteil must_cover mit Evidence |
| `are_requirements_per_story` | INVENTAR | `[N]` | Periode | Durchschnittliche Anforderungen pro Story-Typ |

### 60.4.10 Domaene 9 — Failure Corpus und Lernschleife

Entscheidungsfrage: Lernt das System aus Fehlern?

| KPI | Status | Daten | Koernung | Beschreibung |
|-----|--------|-------|----------|--------------|
| `incident_volume_per_month` | **AKTIV** | `[R]` | Periode | Neue Incidents/Monat. Ziel: <20 (konzeptmandatiert 07 §7.3.6) |
| `pattern_to_check_conversion_rate` | **AKTIV** | `[R]` | Periode | Patterns die zu Checks fuehren |
| `incident_to_pattern_conversion_rate` | INVENTAR | `[R]` | Periode | Incidents die zu Patterns promoviert werden |
| `check_true_positive_rate` | INVENTAR | `[N]` | Entitaet+Periode | TP-Rate pro Check. Konzeptmandatiert (07 §7.6.4) |
| `check_false_positive_rate` | INVENTAR | `[N]` | Entitaet+Periode | FP-Rate pro Check. Auto-Deaktivierung bei >3 FP + 0 TP in 90d |
| `check_time_to_activation` | INVENTAR | `[N]` | Periode | Dauer Incident → Check-Aktivierung |
| `incident_category_distribution` | INVENTAR | `[R]` | Periode | Verteilung ueber 12 Top-Level-Kategorien |
| `open_incident_aging_distribution` | INVENTAR | `[R]` | Periode | Alter offener Incidents nach Buckets |

### 60.4.11 Domaene 10 — Prozess-Effizienz und Trends

Entscheidungsfrage: Wo verbringen wir Zeit? Wird es besser?

| KPI | Status | Daten | Koernung | Beschreibung |
|-----|--------|-------|----------|--------------|
| `phase_time_distribution` | **AKTIV** | `[N]` | Story | Zeitverteilung ueber 5 Pipeline-Phasen |
| `story_predictability` | **AKTIV** | `[N]` | Periode | Varianz der Processing Time bei gleichem Typ/Groesse |
| `processing_time_trend` | **AKTIV** | `[R]` | Periode | Rollierender Durchschnitt Durchlaufzeit |
| `qa_round_trend` | **AKTIV** | `[R]` | Periode | Rollierender Durchschnitt QA-Runden |
| `files_changed_per_story` | **AKTIV** | `[R]` | Story | Dateien im Diff. Trend-Analyse |
| `increment_count_per_story` | **AKTIV** | `[R]` | Story | Inkremente pro Story. Trend-Analyse |

### 60.4.12 Zusammenfassung

| | AKTIV | INVENTAR | Gesamt |
|---|---|---|---|
| Domaene 1: Story-Dimensionierung | 7 | 4 | 11 |
| Domaene 2: LLM-Selektion | 5 | 4 | 9 |
| Domaene 3: Governance | 7 | 5 | 12 |
| Domaene 4: Dokumententreue | 1 | 2 | 3 |
| Domaene 5: QA-Effektivitaet | 7 | 3 | 10 |
| Domaene 6: Review-Qualitaet | 1 | 7 | 8 |
| Domaene 7: VektorDB | 2 | 1 | 3 |
| Domaene 8: ARE | 2 | 1 | 3 |
| Domaene 9: Failure Corpus | 2 | 6 | 8 |
| Domaene 10: Prozess-Effizienz | 6 | 0 | 6 |
| **Gesamt** | **40** | **33** | **73** |

---

## 60.5 Sparring-Referenz

Die Architektur-Entscheidungen in 60.3 wurden in einem
strukturierten Sparring erarbeitet:

- **Claude (Opus)**: Architektur-Entwurf, These (Zwei-Schichten
  SQLite+Postgres), KPI-Katalog-Erstellung
- **ChatGPT**: Gegenposition (SQLite-only), Schema-Design,
  Sync-Mechanismus, EAV-Kritik

### 60.5.1 Sparring-Verlauf (4 Runden)

| Runde | Thema | Ergebnis |
|-------|-------|----------|
| 1 | SQLite vs. Postgres | ChatGPT: Postgres ist Over-Engineering bei 10k-100k Events/Jahr. SQLite-only mit Rollup-Tabellen |
| 2 | Concurrent Access, Perzentile, Schema-Evolution | Claude challenged Writer-Contention. ChatGPT revidiert: Zwei SQLite-Dateien statt einer |
| 3 | EAV vs. breite Fact-Tabellen | Claude challenged metric_value EAV. ChatGPT stimmt zu: Breite Fact-Tabellen sind besseres Serving-Modell |
| 4 | Sync-Mechanismus | Konvergenz auf idempotenten Repair-Worker mit Dirty Sets und atomarer Transaktion |

### 60.5.2 Verworfene Alternativen

| Alternative | Verworfen in Runde | Begruendung |
|-------------|-------------------|-------------|
| Postgres als sofortige zweite Schicht | 1 | Over-Engineering, doppelte Wahrheitsschicht, ETL-Komplexitaet |
| Eine SQLite-DB fuer Raw + Analytics | 2 | Writer-Contention zwischen Hooks und Refresh-Job |
| EAV `metric_value`-Tabelle | 3 | Self-Join-Queries, keine Typsicherheit, schlechtes Dashboard-Serving |
| Perzentile in SQL (SQLite) | 2 | Kein natives `percentile_cont()`. Python-Berechnung ist sauberer |
| Materialized Views in SQLite | 1 | Existieren nicht in SQLite. Explizite Rollup-Tabellen sind steuerbarer |
| Inkrementelles Hochzaehlen bei Sync | 4 | Fragil bei Crashes. Komplett-Neuberechnung der Dirty Slices ist robuster |
