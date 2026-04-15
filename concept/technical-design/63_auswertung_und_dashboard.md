---
concept_id: FK-63
title: Auswertung und Dashboard
module: dashboard
status: active
doc_kind: core
parent_concept_id:
authority_over:
  - scope: dashboard
defers_to:
  - target: FK-62
    scope: analytics-data-model
    reason: Fact-table schemas and refresh logic defined in FK-62; dashboard consumes these
supersedes: []
superseded_by:
tags: [dashboard, analytics, visualization, chart-js]
---

# 63 — Auswertung und Dashboard

## 63.1 Zweck

Dieses Dokument definiert die Auswertungs- und Darstellungsschicht
fuer die Analytics-Daten aus FK-62. Es beschreibt das bestehende
Dashboard, die geplanten Erweiterungen und die Moeglichkeiten fuer
den Nutzer, eigene Auswertungen vorzunehmen.

Es ist das vierte und letzte Dokument des Analytics-Blocks
(FK-60 bis FK-63).

**Status**: Kurzfassung. Die weitere Ausdetaillierung der
Dashboard-Applikation erfolgt in einer spaeteren Iteration,
sobald FK-61 und FK-62 implementiert sind und die Fact-Tabellen
mit realen Daten befuellt werden.

---

## 63.2 Ist-Zustand

### 63.2.1 Bestehende Applikation

Das AgentKit QA Dashboard ist eine Single-Page-Applikation:

- **Technologie**: Python stdlib HTTP-Server + Chart.js 4.4.7 (CDN)
- **Start**: `agentkit dashboard [--port 9700]`
- **Datenquelle**: Liest read-only aus PostgreSQL (runtime/analytics)
- **5 Tabs**: QA Findings, Stage Results, Story Metrics,
  Failure Corpus, Trends
- **11 API-Endpoints** mit vorgefertigten SQL-Queries
- **KPI-Summary**: Stories completed, QA pass rate, avg QA rounds,
  blocking findings, open incidents

### 63.2.2 Einschraenkungen des Ist-Zustands

- Liest bislang noch nicht aus den geplanten Analytics-Rollups
- Keine Perzentile, keine Raten, keine Trend-Berechnung in SQL
- Keine frei definierbaren Zeitraeume oder Filter
- Keine Guard-, Pool- oder Template-spezifischen Sichten
- Kein Drill-Down von Periode → Story → Event

---

## 63.3 Zielzustand

### 63.3.1 Zwei Datenquellen

Das Dashboard liest aus zwei Quellen:

1. **analytics schema** (primaer): Fact-Tabellen mit vorberechneten
   KPIs, Perzentilen, Raten, Trend-Werten
2. **runtime schema** (ergaenzend): Live-Sicht fuer laufende Stories
   (aktueller Phase-Status, bisherige Laufzeit, bisherige Events)

Alle Dashboard-Abfragen sind projektgebunden. Die zentrale
PostgreSQL-Instanz wird nie ungefiltert ueber alle Projekte
ausgewertet; jede Session arbeitet gegen genau einen `project_key`.

### 63.3.2 Geplante Erweiterungen (Ueberblick)

| Bereich | Beschreibung |
|---------|--------------|
| **Story-KPI-Tab** | Tabelle aller abgeschlossenen Stories mit KPI-Spalten aus `fact_story`. Sortier-/filterbar nach Typ, Groesse, Zeitraum. |
| **Guard-Health-Tab** | Violation-Raten pro Guard ueber Zeit (aus `fact_guard_period`). Chart: Violation-Rate-Trend pro Guard. |
| **LLM-Performance-Tab** | Antwortzeiten (P50/P95), Verdict-Adoption, Finding-Precision pro Pool (aus `fact_pool_period`). |
| **Pipeline-Trends-Tab** | First-Pass-Rate, QA-Runden-Trend, Processing-Time-Trend, Execution/Exploration-Ratio (aus `fact_pipeline_period`). |
| **Failure-Corpus-Tab** | Incident-Volumen-Trend, Conversion-Funnel, Pattern-Status (aus `fact_corpus_period`). |
| **Live-Sicht** | Laufende Stories mit aktuellem Phase-Status (aus dem Runtime-Schema). |

### 63.3.3 Nutzerseitige Auswertungen

Der Nutzer soll ueber das Dashboard eigene Auswertungen
vornehmen koennen:

- **Zeitraum-Auswahl**: Beliebige Start-/End-Daten fuer
  Perioden-basierte KPIs
- **Entity-Filter**: Einschraenkung auf bestimmte Guards, Pools
  oder Templates
- **Story-Filter**: Einschraenkung auf Story-Typ, Story-Groesse
  oder Pipeline-Modus
- **Vergleichsmodus**: Zwei Zeitraeume nebeneinander (vorher/nachher
  einer Aenderung)

Die technische Realisierung (serverseitige Query-Parameter vs.
clientseitige Filterung, gespeicherte Views, Query-Builder)
wird in einer spaeteren Iteration definiert.

---

## 63.4 API-Erweiterungen (Entwurf)

### 63.4.1 Neue Endpoints

| Endpoint | Quelle | Beschreibung |
|----------|--------|--------------|
| `GET /api/kpi/stories` | `fact_story` | Story-KPIs mit Filter/Sort |
| `GET /api/kpi/guards` | `fact_guard_period` | Guard-Health ueber Zeit |
| `GET /api/kpi/pools` | `fact_pool_period` | LLM-Performance ueber Zeit |
| `GET /api/kpi/pipeline` | `fact_pipeline_period` | Pipeline-Trends |
| `GET /api/kpi/corpus` | `fact_corpus_period` | Failure-Corpus-Trends |
| `GET /api/live/stories` | runtime schema (events, workflow_state) | Laufende Stories |

### 63.4.2 Query-Parameter

Nicht alle Parameter sind auf alle Endpoints anwendbar. Jeder
Endpoint hat seine natuerliche Koernung (siehe FK-62 Fact-Tabellen).

| Parameter | Typ | Anwendbar auf | Beschreibung |
|-----------|-----|---------------|--------------|
| `project_key` | String | Alle Endpoints (pflichtig oder implizit aus Projektkontext) | Zielprojekt / Mandanten-Scope |
| `from` | ISO 8601 Date | Alle Endpoints | Beginn des Zeitraums |
| `to` | ISO 8601 Date | Alle Endpoints | Ende des Zeitraums |
| `guard` | String | `/api/kpi/guards` | Filter auf bestimmten Guard |
| `pool` | String | `/api/kpi/pools` | Filter auf bestimmten LLM-Pool |
| `story_type` | String | `/api/kpi/stories`, `/api/kpi/pipeline` | Filter auf Story-Typ |
| `story_size` | String | `/api/kpi/stories` | Filter auf Story-Groesse |

**Hinweis**: Template-basierte Analytik ist in der aktuellen
Modellierung als JSON-Feld in `fact_pool_period` abgelegt und
daher nicht ueber einen eigenen Filter ansteuerbar. Fuer
detaillierte Template-Analyse ist ein Drill-Down in die
Rohdaten des Runtime-Schemas noetig. Eine Erweiterung um eine eigene
Template-Fact-Tabelle ist ein INVENTAR-Punkt fuer spaetere
Iterationen.

---

## 63.5 Abgrenzung

- **FK-62** definiert WAS im Analytics-Schema steht (Schema,
  Refresh-Logik, Berechnung). FK-63 definiert WIE es dem
  Nutzer praesentiert wird.
- **FK-52** (Betrieb, Monitoring) definiert operative Sichten
  (Pool-Health, Disk-Space, Locks). FK-63 definiert analytische
  Sichten (Trends, Raten, Vergleiche).
- Das Dashboard ist **Consumer** des Analytics-Modells, nicht
  Eigentuemer der KPI-Semantik. KPI-Definitionen stehen
  ausschliesslich in FK-60.

---

## 63.6 Offene Punkte (spaetere Iteration)

- Query-Builder vs. vordefinierte Filter-Kombinationen
- Gespeicherte Auswertungen (User-definierte Views)
- Export-Formate (CSV, JSON)
- Alerting/Schwellenwert-Benachrichtigungen
- Multi-User-Faehigkeit (aktuell Single-User)
- Drill-Down-Navigation (Periode → Stories → Events)
