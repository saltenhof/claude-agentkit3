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
    reason: Event model, event catalog, and PostgreSQL schema defined in FK-14; FK-60 consumes events as raw data source
supersedes: []
superseded_by:
tags: [kpi, analytics, architecture, postgres, metrics]
prose_anchor_policy: strict
formal_refs:
  - formal.telemetry-analytics.entities
  - formal.telemetry-analytics.invariants
---

# 60 — KPI-Katalog und Analytics-Architektur

<!-- PROSE-FORMAL: formal.telemetry-analytics.entities, formal.telemetry-analytics.invariants -->

## 60.1 Zweck

Dieses Dokument definiert den vollstaendigen Katalog aller KPIs fuer
AgentKit, die Infrastruktur-Architektur fuer deren Speicherung und
die Designprinzipien fuer Erhebung, Aggregation und Auswertung.

**Architekturzuordnung:** Der Analytics-Block FK-60 bis FK-63 bildet
zusammen die Top-Level-Komponente `KpiAnalyticsEngine`. Das ist kein
einzelnes Runtime-Objekt, sondern das fachliche Buendel aus
Datenerhebung, Aggregation und Dashboard-Serving.

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
| FK-14 (Event-Infrastruktur) | Event-Modell, Event-Katalog, PostgreSQL-Schema (`execution_events`), Hook-Mechanik | FK-60ff konsumiert Events als Rohdatenquelle. FK-14 definiert WAS ein Event ist. FK-60ff definiert WAS eine KPI ist. |
| FK-16 (QA-/FC-Raw-Store) | Querybare Raw-/Mirror-Tabellen im zentralen PostgreSQL-Store | FK-62 baut die Analytics-Schicht auf diesen Raw-Tabellen auf. Dashboard-Autoritaet wandert von FK-16 nach FK-63. |
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

### P3: Ein Datenbanksystem, getrennte Schemas

Der kanonische AgentKit-Zustand liegt in PostgreSQL. Rohdaten,
Workflow-State und Analytics liegen im selben DBMS, aber logisch
getrennt in dedizierten Schemas bzw. Tabellengruppen. Analytics ist
aus den Rohdaten jederzeit neu berechenbar.

**P3b: Vollstaendiger Story-Reset purgt auch Analytics-Ableitungen**

Wird eine Story-Umsetzung vollstaendig zurueckgesetzt, werden nicht nur
Runtime-State und `execution_events`, sondern auch alle daraus
abgeleiteten Read Models und Facts der korrupten Umsetzung entfernt
oder aus den verbleibenden gueltigen Daten neu berechnet. Analytics
darf keine spaet herauszufilternden Invalid-Run-Reste enthalten.

**P3a: Mandantenfaehigkeit ueber `project_key`**

Die zentrale PostgreSQL-Instanz ist projektuebergreifend, aber alle
kanonischen Runtime- und Analytics-Daten sind logisch an einen
`project_key` gebunden. `story_id` ist damit keine systemweite
Identitaet, sondern nur innerhalb eines Projekts eindeutig.

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

### P6: Perzentile bevorzugt in SQL, Python nur wenn fachlich sinnvoll

PostgreSQL kann analytische Aggregationen deutlich besser tragen als
SQLite. KPIs wie `llm_response_time_p50` koennen daher direkt in SQL
oder in materialisierten Rollups berechnet werden; Python bleibt fuer
komplexere, nicht rein relationale Berechnungen zulaessig.

### P7: Evolutionsfaehigkeit

Neue KPIs werden als `ALTER TABLE ADD COLUMN` in die bestehenden
Fact-Tabellen aufgenommen. Migrationen sind idempotent via
`ALTER TABLE ... ADD COLUMN IF NOT EXISTS` oder Introspection gegen
`information_schema`. Das Schema waechst mit dem
KPI-Katalog, ohne Rebuild.

### P8: PostgreSQL als verbindliche Plattformentscheidung

PostgreSQL ist die verbindliche Datenbankplattform fuer AgentKit.
Begruendung:

- eine systemweite AgentKit-Installation braucht eine systemweite,
  langlebige Datenhaltung
- Rechte und Principal-Zugriffe lassen sich in PostgreSQL sauberer
  modellieren als in SQLite-Dateien
- Analytics, Audit-Trail und State-Verwaltung profitieren von einem
  echten Mehrbenutzer-DBMS

---

## 60.3 Infrastruktur-Architektur

### 60.3.1 PostgreSQL-Schema-Modell

```
Hook-Hot-Path (synchron, latenzkritisch)
    │
    ▼
┌───────────────────────────────────────────────┐
│ PostgreSQL                                    │
│                                               │
│  schema runtime                               │
│   - execution_events                          │
│   - workflow_state                            │
│   - qa_*                                      │
│   - story_*                                   │
│   - fc_*                                      │
│                                               │
│  schema analytics                             │
│   - fact_story                                │
│   - fact_guard_period                         │
│   - fact_pool_period                          │
│   - fact_pipeline_period                      │
│   - fact_corpus_period                        │
│   - sync_state                                │
└───────────────────────────────────────────────┘
                │
                ▼
┌──────────────┐
│  Dashboard   │  liest read-only aus analytics-Schema
│  (Chart.js)  │  + Live-Sicht aus runtime-Schema fuer laufende Stories
└──────────────┘
```

### 60.3.2 Begruendung des PostgreSQL-Modells

**Problem des alten SQLite-Modells**: Dateibasierte State- und
Analytics-Speicher erschweren Rechtevergabe, Mehrbenutzerzugriffe,
Retention und systemweite Betriebsfuehrung.

**Loesung**: Ein zentrales PostgreSQL-DBMS mit logisch getrennten
Schemas isoliert Rollen und Datenbereiche, ohne auf mehrere
Dateidatenbanken ausweichen zu muessen.

**Verworfene Alternativen**:

| Alternative | Verworfen weil |
|-------------|----------------|
| Mehrere dateibasierte DBs | Verteilte Wahrheitsschicht, schwache Rechteverwaltung, schwieriger Betrieb |
| SQLite als Primärmodell | Unsaubere Rechtegrenzen und unpassend für systemweite AgentKit-Installation |
| EAV-Tabelle (`metric_value`) | Schlechtes Serving-Modell, Query-Komplexitaet, keine Typsicherheit |

### 60.3.3 Runtime-Schema

Das Runtime-Schema enthaelt die kanonischen Tabellen fuer `execution_events`,
Workflow-State, QA-Resultate und Failure-Corpus-Rohdaten.

**Invariante**: `execution_events` ist append-only innerhalb einer
gueltigen Story-Umsetzung. Wird eine Umsetzung vollstaendig
zurueckgesetzt, werden ihre Events zusammen mit den abgeleiteten
Runtime-/Read-Model-Daten physisch entfernt.

### 60.3.4 Analytics-Schema

Das Analytics-Schema enthaelt die abgeleiteten Fact-Tabellen und
den Sync-State.

**Invariante**: Das Analytics-Schema enthaelt nur Daten gueltiger,
nicht vollstaendig zurueckgesetzter Story-Umsetzungen.

**Fact-Tabellen** (Detail-Schema in FK-62):

| Tabelle | Koernung | Primaerschluessel |
|---------|----------|-------------------|
| `fact_story` | 1 Zeile pro Story | `(project_key, story_id)` |
| `fact_guard_period` | 1 Zeile pro Guard pro Woche | `(project_key, guard_key, period_start)` |
| `fact_pool_period` | 1 Zeile pro Pool pro Woche | `(project_key, pool_key, period_start)` |
| `fact_pipeline_period` | 1 Zeile pro Woche | `(project_key, period_start)` |
| `fact_corpus_period` | 1 Zeile pro Monat | `(project_key, period_start)` |

**Sync-State**:

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

Eintraege: `last_event_id` (monotoner Cursor), `last_synced_at`
(ISO 8601). Der Cursor ist projektgebunden; `sync_state` wird daher
pro `project_key` geführt.

### 60.3.5 Sync-Mechanismus

**Trigger**: Kein Daemon, kein Cron. Zwei event-getriebene
Ausloeser:

1. **Story-Closure** (primaer): Nach Metriken-Berechnung und
   Abschluss der kanonischen Runtime-Persistenz ruft die Closure-Phase
   `sync_analytics()` auf. Optionale JSONL-Exports sind davon getrennt.
2. **Dashboard-Start** (Catch-up): `agentkit dashboard` ruft
   beim Start `sync_analytics()` auf (best-effort, bei Lock
   wird mit vorhandenem Stand gestartet).

### 60.3.6 Reset-Purge-Mechanismus

Ein vollstaendiger Story-Reset darf **nicht** nur ueber spaetere
Dashboard-Filter oder periodische Aggregation kompensiert werden.
Stattdessen gilt:

1. runtime-nahe Daten des betroffenen `run_id` werden entfernt
2. FK-16-Read-Models des betroffenen `run_id` werden entfernt
3. betroffene Analytics-Facts werden aktiv geloescht oder aus den
   verbleibenden gueltigen Quellen neu berechnet

`sync_state` oder Event-Cursor allein genuegen dafuer nicht, weil die
Quell-Events des korrupten Runs bereits geloescht werden.

**Ablauf von `sync_analytics()`**:

1. Read-only Snapshot auf Runtime-Schema oeffnen
2. Read-write Transaktion auf Analytics-Schema oeffnen
3. `sync_state.last_event_id` lesen
4. Konsistenten Snapshot auf Runtime-Schema: `watermark = MAX(event_id)`
5. Delta-Events lesen: `WHERE event_id > last_event_id AND event_id <= watermark`
6. **Dirty Sets** ableiten:
   - `dirty_story_ids`: `(project_key, story_id)` aus Delta-Events
   - `dirty_guard_weeks`: `(project_key, guard_key, week_start)` aus Delta-Events
   - `dirty_pool_weeks`: `(project_key, pool_key, week_start)` aus Delta-Events
   - `dirty_pipeline_weeks`: `(project_key, week_start)` aus Delta-Events
   - `dirty_corpus_months`: `(project_key, month_start)` aus Delta-Events
7. Pro Dirty Set: Betroffene Slices **komplett neu berechnen**
   aus dem Runtime-Schema (kein inkrementelles Hochzaehlen)
8. **Eine Transaktion** auf dem Analytics-Schema:
   - UPSERT `fact_story` fuer dirty Stories
   - DELETE+INSERT `fact_guard_period` fuer dirty Guard-Wochen
   - DELETE+INSERT `fact_pool_period` fuer dirty Pool-Wochen
   - DELETE+INSERT `fact_pipeline_period` fuer dirty Wochen
   - DELETE+INSERT `fact_corpus_period` fuer dirty Monate
   - UPDATE `sync_state` SET `last_event_id = watermark`
9. COMMIT

**Crash-Sicherheit**: Wenn der Prozess vor COMMIT crasht, ist
nichts sichtbar im Analytics-Schema. Beim naechsten Lauf wird
derselbe Delta-Bereich erneut verarbeitet (idempotent).

**Laufende Stories**: Erscheinen nicht in `fact_story`. Das
Dashboard zeigt laufende Stories ueber eine separate Live-Sicht
direkt aus dem Runtime-Schema (aktueller Phasen-Status, bisherige
Laufzeit, bisherige Events).

---

## 60.4 KPI-Katalog

### 60.4.1 Legende

| Symbol | Bedeutung |
|--------|-----------|
| **AKTIV** | KPI wird in FK-61/62 ausgearbeitet und implementiert |
| INVENTAR | KPI ist identifiziert, aber nicht im ersten Release |
| `[R]` | Rohdaten bereits erhoben (Event/Record existiert im Runtime-Schema) |
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

- **Claude (Opus)**: KPI-Katalog, Sync-Mechanismus, Slicing
- **ChatGPT**: Gegenpositionen zu Schema-Schnitt und Serving-Modell

### 60.5.1 Sparring-Verlauf (4 Runden)

| Runde | Thema | Ergebnis |
|-------|-------|----------|
| 1 | Zentrales Runtime-Backend | Alternative lokale DB-/Dateimodelle verworfen; zentrale PostgreSQL-Instanz als kanonische Runtime-Wahrheit |
| 2 | Concurrent Access, Perzentile, Schema-Evolution | SQLite-Varianten verworfen zugunsten klarer Writer-/Reader-Trennung auf PostgreSQL |
| 3 | EAV vs. breite Fact-Tabellen | Claude challenged metric_value EAV. ChatGPT stimmt zu: Breite Fact-Tabellen sind besseres Serving-Modell |
| 4 | Sync-Mechanismus | Konvergenz auf idempotenten Repair-Worker mit Dirty Sets und atomarer Transaktion |

### 60.5.2 Verworfene Alternativen

| Alternative | Verworfen in Runde | Begruendung |
|-------------|-------------------|-------------|
| Projektlokale DB-/Datei-Wahrheiten | 1 | Bricht zentrale Ownership, Mandantenfaehigkeit und Zugriffssteuerung |
| Eine SQLite-DB fuer Raw + Analytics | 2 | Writer-Contention, schwache Rechtegrenzen, kein sauberes System-Backend |
| EAV `metric_value`-Tabelle | 3 | Self-Join-Queries, keine Typsicherheit, schlechtes Dashboard-Serving |
| Perzentile ausschliesslich im SQL-Layer | 2 | Python-/Batch-Berechnung bleibt fuer komplexe Kennzahlen sauberer |
| Materialized Views als Primaermodell | 1 | Rebuildbare Fact-Tabellen und Projektionen sind expliziter und steuerbarer |
| Inkrementelles Hochzaehlen bei Sync | 4 | Fragil bei Crashes. Komplett-Neuberechnung der Dirty Slices ist robuster |
