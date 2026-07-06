# kpi-and-dashboard — GAP-Analyse

> Generiert von einem dedizierten Sonnet-Sub-Agent (Stand 2026-05-16).

## Header

| Feld | Wert |
|---|---|
| BC-ID | `kpi-and-dashboard` |
| Display-Name | `KPI und Dashboard` |
| Analyse-Datum | `2026-05-16` |
| Konzept-Quellen (autoritativ) | `DK-13, FK-60, FK-61, FK-62, FK-63, FK-64, bc-cut-decisions.md §BC-16` |
| Codebase-Hauptpfade | `src/agentkit/dashboard/`, `src/agentkit/telemetry/kpis/` |

## 1. Executive Summary

Der BC `kpi-and-dashboard` ist konzeptionell vollstaendig und detailliert ausgearbeitet (FK-60 bis FK-64, bc-cut-decisions.md §BC-16), aber in der Codebase nahezu vollstaendig nicht umgesetzt. Die vorhandene `src/agentkit/dashboard/`-Implementierung entspricht nicht dem konzipierten BC-Schnitt: Sie liest aus Story-Read-Models statt aus PostgreSQL-Fact-Tabellen, kennt weder KpiAnalytics-Top noch FactStore, RefreshWorker oder KpiCatalog. Das definierte Modul-Praefixsystem `agentkit.backend.kpi_analytics.*` existiert nicht. Das analytics-Schema in PostgreSQL, alle fuenf Fact-Tabellen sowie der Sync-State-Mechanismus fehlen vollstaendig. Es handelt sich damit um den BC mit dem groessten absoluten Implementierungsrueckstand im gesamten AK3-System.

| Kategorie | Anzahl |
|---|---|
| A — Nicht umgesetzt | 12 |
| B — Teilweise umgesetzt | 4 |
| C — Drift / Fehler | 3 |

## 2. Konzept-Soll (Kurzfassung)

- **Top-Klasse `KpiAnalytics` als BC-Entry-Point** mit Top-Surface `list_kpis`, `refresh_analytics`, `get_dashboard_view`, `query`, `get_design_tokens` — `bc-cut-decisions.md §BC-16`
- **KpiCatalog-Sub**: vollstaendiger, versionierter Katalog von 40 aktiven und 33 Inventar-KPIs, jeweils mit Formel, Koernung, Entscheidungsfrage und Collection-Point — `FK-60 §60.4`
- **FactStore-Sub**: fuenf Fact-Tabellen im PostgreSQL-analytics-Schema (`fact_story`, `fact_guard_period`, `fact_pool_period`, `fact_pipeline_period`, `fact_corpus_period`) plus `sync_state` und `guard_invocation_counters` — `FK-62 §62.2`
- **Aggregation/RefreshWorker-Sub**: idempotenter Repair-Worker mit Dirty-Set-Ableitung, atomarer Transaktion, Crash-Sicherheit; ausgeloest event-getrieben bei Story-Closure und Dashboard-Start — `FK-62 §62.3`
- **Drei Aggregationsebenen** (pro Story / pro Entitaet+Periode / pro Periode) als primaere Koernungen — `FK-60 §60.5 P5, DK-13 §13.1.3`
- **PostgreSQL als verbindliche Datenbankplattform** fuer Runtime- und Analytics-Schema; kein SQLite, keine EAV-Struktur — `FK-60 §60.2 P8, P4`
- **Mandantenfaehigkeit ueber `project_key`** als fuehrender Scope-Schluessel in allen Fact- und Scratchpad-Tabellen — `FK-62 §62.2 (Mandantenregel)`
- **Reset-Purge-Mechanismus**: vollstaendige Ruecksetzung einer Story muss aus Fact-Tabellen und Read-Models aktiv entfernt werden — `FK-60 §60.3.6, FK-62 §62.2.8`
- **Dashboard-Sub**: sechs geplante Tabs (Story-KPI-Tab, Guard-Health-Tab, LLM-Performance-Tab, Pipeline-Trends-Tab, Failure-Corpus-Tab, Live-Sicht) mit projektgebundenen API-Endpoints — `FK-63 §63.3`
- **Transport-Agnostizitaet**: `KpiAnalytics`-Top-Surface stellt Daten bereit, HTTP-Serving liegt bei `control_plane` — `FK-63 §63.2.1, bc-cut-decisions.md §BC-16`
- **DesignSystem-Sub**: normatives Design System (FK-64) mit Token-Skalen, Typografie, Komponentenregeln fuer Story Cockpit, Kanban, Inspector, Dependency-Graph — `FK-64 §64.1`
- **Guard-Invocation-Scratchpad**: leichtgewichtige Counter-Tabelle statt High-Volume-Events fuer Guard-Aufrufzaehlung — `FK-61 §61.4.3, FK-62 §62.2.6`
- **KPI-Erhebungspunkte deklarativ**: KpiCatalog.KpiCollectionPoint ist Mapping-Aussage, Hook-Logik liegt in telemetry-and-events.TelemetryHooks — `bc-cut-decisions.md Punkt 73`

## 3. Code-Stand (Ist-Bild)

- `src/agentkit/dashboard/models.py:BoardColumn` — Kanban-Spalte mit Status und StorySummary-Liste; liest aus Story-Read-Models, kein Bezug zu Fact-Tabellen
- `src/agentkit/dashboard/models.py:DashboardBoardResponse` — Projekt-scoped Board-Antwort; Datenquelle: StoryService, nicht PostgreSQL analytics-Schema
- `src/agentkit/dashboard/models.py:DashboardStoryMetricsItem` — Story-Metriken-Summary (processing_time_min, qa_rounds, increments); entspricht nicht dem `fact_story`-Schema
- `src/agentkit/dashboard/models.py:DashboardStoryMetricsResponse` — Read-only Closure-Metrics-Liste; kein Bezug zu FK-62-Fact-Tabellen
- `src/agentkit/dashboard/service.py:DashboardService` — baut Board und Metrics-Listen aus StoryService; kein RefreshWorker, kein sync_analytics
- `src/agentkit/dashboard/service.py:DashboardService.get_board` — liest via `StoryService.list_stories`, gruppiert nach lifecycle_status
- `src/agentkit/dashboard/service.py:DashboardService.get_story_metrics` — liest `story.latest_metrics`, filtert auf `latest_metrics is not None`
- `src/agentkit/telemetry/metrics.py:PipelineMetrics` — Event-basierte Metriken-Aggregation (total_duration, phase_durations, qa_rounds); In-Memory, kein Fact-Store-Bezug
- `src/agentkit/telemetry/metrics.py:compute_pipeline_metrics` — pure Funktion auf Event-Stream; SQLite-unabhaengig, kein PostgreSQL
- `src/agentkit/telemetry/kpis/__init__.py` — leere Datei (1 Zeile: implizit leer)

Das Modul-Praefixsystem `agentkit.backend.kpi_analytics.*` (KpiCatalog, FactStore, Aggregation, Dashboard, DesignSystem) existiert nicht. Kein `kpi_analytics/`-Paket in `src/agentkit/`.

## 4. GAP-Analyse

> **Wichtig:** Jede Zeile in einer der drei Tabellen muss mindestens
> eine konkrete Doc-Referenz tragen. Code-Referenzen sind in den
> Tabellen B und C Pflicht, in Tabelle A optional (weil dort gerade
> kein Code existiert).

### 4.1 A — Nicht umgesetzt

| # | Thema | Konzept-Referenz | Anmerkung |
|---|---|---|---|
| A1 | Modul `agentkit.backend.kpi_analytics` mit Top-Klasse `KpiAnalytics` | `bc-cut-decisions.md §BC-16` | Kein `kpi_analytics/`-Paket in `src/agentkit/`. Die Top-Surface (`list_kpis`, `refresh_analytics`, `get_dashboard_view`, `query`, `get_design_tokens`) existiert nicht. |
| A2 | Sub-Komponente `KpiCatalog` (Modul `agentkit.backend.kpi_analytics.catalog`) | `FK-60 §60.4, bc-cut-decisions.md §BC-16` | Kein KpiDefinition, kein KpiCollectionPoint, kein KpiCatalogStore. 40 aktive KPIs aus FK-60 Katalog nicht maschinenlesbar modelliert. |
| A3 | Sub-Komponente `FactStore` (Modul `agentkit.backend.kpi_analytics.fact_store`) | `FK-62 §62.2, bc-cut-decisions.md §BC-16` | Keine Fact-Tabellen-Modelle: FactStory, FactGuardPeriod, FactPoolPeriod, FactPipelinePeriod, FactCorpusPeriod. T-Driver auf analytics-Schema nicht implementiert. |
| A4 | PostgreSQL analytics-Schema mit allen fuenf Fact-Tabellen | `FK-62 §62.2.1–62.2.5` | `fact_story`, `fact_guard_period`, `fact_pool_period`, `fact_pipeline_period`, `fact_corpus_period` nicht angelegt. Kein `sync_state`. |
| A5 | Sub-Komponente `Aggregation` / RefreshWorker (`agentkit.backend.kpi_analytics.aggregation`) | `FK-62 §62.3, bc-cut-decisions.md §BC-16` | `sync_analytics()` fehlt. Kein Dirty-Set-Mechanismus, kein event-getriebener Trigger bei Story-Closure oder Dashboard-Start. |
| A6 | `guard_invocation_counters` Scratchpad-Tabelle | `FK-61 §61.4.3, FK-62 §62.2.6` | Tabelle nicht existierend. Guard-Invokationszaehler fehlen vollstaendig. |
| A7 | Reset-Purge-Mechanismus (`purge_story_analytics`) | `FK-60 §60.3.6, FK-62 §62.2.8, §62.3.3` | Kein aktives Entfernen von Analytics-Ableitungen bei Story-Reset. |
| A8 | KPI-Erhebungspunkte fuer neue Event-Typen (FK-61) | `FK-61 §61.12.1` | Neue Event-Typen `impact_violation_check`, `doc_fidelity_check`, `vectordb_search`, `compaction_event` nicht implementiert. |
| A9 | Angereicherte Payloads fuer bestehende Events | `FK-61 §61.12.2` | Felder `stage` in `integrity_violation`, `blocked_dimensions[]` in `integrity_gate_result`, `verdict` in `review_response`, Coverage-Felder in `are_gate_result` fehlen. |
| A10 | Sub-Komponente `Dashboard` (Modul `agentkit.backend.kpi_analytics.dashboard`) | `FK-63 §63.3, bc-cut-decisions.md §BC-16` | Geplante sechs Tabs und sechs API-Endpoints (`/api/kpi/stories`, `/api/kpi/guards` etc.) nicht implementiert. |
| A11 | Sub-Komponente `DesignSystem` (Modul `agentkit.backend.kpi_analytics.design_system`) | `FK-64, bc-cut-decisions.md §BC-16` | Design-System-Tokens, Typografie-Skala, Komponentenregeln (FK-64) nicht als Python/CSS-Artefakt realisiert. |
| A12 | Schema-Migrations-Strategie (`_ensure_column`, `schema_version`) | `FK-62 §62.4` | Idempotente Migration via `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` und Versions-Cursor nicht vorhanden. |

### 4.2 B — Teilweise umgesetzt

| # | Thema | Code-Referenz | Konzept-Referenz | Was fehlt |
|---|---|---|---|---|
| B1 | Story-Metriken-Auswertung im Dashboard | `src/agentkit/dashboard/service.py:DashboardService.get_story_metrics` | `FK-62 §62.2.1, FK-63 §63.3.2` | Liest aus `story.latest_metrics` (StoryService) statt aus `fact_story` im PostgreSQL analytics-Schema. Felder `compaction_count`, `feedback_converged`, `blocked_ac_count`, `llm_call_count`, `adversarial_*`, `are_*`, `phase_*_ms` fehlen. Kein Zeitraum-Filter, kein `project_key`-Scoping ueber Fact-Store. |
| B2 | Board-Ansicht (Kanban-Spalten) | `src/agentkit/dashboard/service.py:DashboardService.get_board` | `FK-63 §63.3.2 (Live-Sicht), FK-64 §64.11` | Statusmapping weicht vom Konzept ab: `_COLUMN_ORDER` enthaelt `defined`, `active`, `failed` die im FK-64 §64.11 nicht als Kanban-Statusspalten normiert sind. Live-Sicht aus Runtime-Schema (laufende Stories) fehlt. Design-Token-Konformitaet gemaess FK-64 nicht pruefsbar. |
| B3 | Event-basierte Metriken-Berechnung | `src/agentkit/telemetry/metrics.py:compute_pipeline_metrics` | `FK-62 §62.3.5, FK-61 §61.11` | Pure Funktion auf In-Memory-Event-List; kein Schreiben in Fact-Tabellen, kein Bezug zu PostgreSQL, kein `project_key`-Scope. `qa_rounds` zaehlt `NODE_RESULT` fuer Phase `implementation` — Konzept (FK-61 §61.2.1) setzt `story_metrics.qa_rounds` aus dem Closure-Schritt, nicht aus Event-Zaehlung. Mapping nicht konform. |
| B4 | KPIs-Modul-Platzhalter | `src/agentkit/telemetry/kpis/__init__.py` | `FK-60 §60.1, bc-cut-decisions.md §BC-16` | Datei ist leer (1 Zeile). Kein Inhalt, kein Export, kein Bezug zu `agentkit.backend.kpi_analytics`. Liegt im falschen Paket (`agentkit.backend.telemetry.kpis` statt `agentkit.backend.kpi_analytics`). |

### 4.3 C — Drift / Fehler

> Hier landen Implementierungen, die etwas tun, aber nicht das, was im
> Konzept steht, **oder** offensichtlich fehlerhaft sind (Bug,
> Verletzung einer Invariante, falsche Trust-Boundary, etc.).

| # | Thema | Code-Referenz | Konzept-Referenz | Drift / Fehler |
|---|---|---|---|---|
| C1 | `DashboardService` liest direkt aus StoryService, nicht aus Fact-Tabellen | `src/agentkit/dashboard/service.py:DashboardService` | `FK-62 §62.6.2, bc-cut-decisions.md §BC-16` | Trust-Boundary-Verletzung: `kpi-and-dashboard.Dashboard` soll Daten aus `FactStore` (analytics-Schema, eigener Owner) lesen. Direktzugriff auf StoryService umgeht die Fact-Schicht und erzeugt eine zweite operative Wahrheit neben dem definierten State-Artefaktmodell. Verstoss gegen SINGLE SOURCE OF TRUTH (CLAUDE.md). |
| C2 | Modul-Praefixsystem falsch platziert | `src/agentkit/telemetry/kpis/__init__.py`, `src/agentkit/dashboard/` | `bc-cut-decisions.md §BC-16 (Modul-Prefixes)` | Das BC-Modul soll unter `agentkit.backend.kpi_analytics.*` liegen. Der vorhandene Code liegt unter `agentkit.dashboard` und `agentkit.backend.telemetry.kpis`. Diese Platzierung widerspricht dem BC-Schnitt und erzeugt falsche Modul-Ownership-Signale. `agentkit.dashboard` ist kein registrierter Sub-Praefixname gemaess bc-cut-decisions.md. |
| C3 | Kanban-Statusspalten weichen von FK-64 ab | `src/agentkit/dashboard/service.py:_COLUMN_ORDER` | `FK-64 §64.11` | `_COLUMN_ORDER` enthaelt `"defined"`, `"active"`, `"failed"`, `"blocked"` als Kanban-Status. FK-64 §64.11 normiert ausschliesslich `Backlog`, `Approved`, `In Progress`, `Done`, `Cancelled` als Kanban-Spalten. `Blocked` ist explizit kein eigener Story-Status (FK-64 §64.14). Drift zwischen Implementierung und normalem Konzept. |

## 5. Ableitungen / Empfehlungen

> **Keine Stories anlegen.** Diese Sektion ist eine priorisierte
> Stichpunkt-Liste fuer den nachgelagerten Backlog-Schnitt durch den
> User. Pro Eintrag: Was sollte als naechstes adressiert werden und
> warum (Risiko, Bloecker fuer andere BCs, Konzept-Compliance).

1. **Paket `agentkit.backend.kpi_analytics` anlegen und BC-Modul-Struktur herstellen.** Solange das Paket fehlt, koennen weder KpiCatalog, FactStore, Aggregation noch Dashboard am richtigen Ort implementiert werden. Der aktuelle `agentkit.dashboard`-Code muss migriert oder ersetzt werden. Bloecker fuer alle weiteren Punkte.

2. **PostgreSQL analytics-Schema und Fact-Tabellen erstellen (A4, A5).** Fact-Tabellen sind Voraussetzung fuer RefreshWorker und Dashboard. Ohne sie kann die gesamte KPI-Aggregation nicht gestartet werden. Migrations-Strategie (A12) sollte parallel definiert werden.

3. **`DashboardService`-Drift beheben (C1, C2, C3).** Der vorhandene Code liest aus falscher Quelle, liegt im falschen Paket und benutzt nicht-konzeptkonformes Statusmapping. Dieser Drift waechst mit jeder Weiterentwicklung auf dem falschen Fundament und muss vor Erweiterungen beseitigt werden.

4. **RefreshWorker (`sync_analytics`) als Kern der Aggregation implementieren (A5).** Die event-getriebene Ausloesungslogik (Story-Closure + Dashboard-Start) und der Dirty-Set-Mechanismus sind architektonisch zentral. Ohne diese Schicht fehlt der gesamte KPI-Datenpfad.

5. **Neue Event-Typen und angereicherte Payloads aus FK-61 in telemetry-and-events koordinieren (A8, A9).** Diese Aenderungen beruehren `telemetry-and-events`-BCs und brauchen eine abgestimmte Umsetzung. KpiCatalog.KpiCollectionPoint ist dabei nur das deklarative Mapping — die Hook-Logik liegt in telemetry-and-events.TelemetryHooks.

6. **Guard-Invocation-Scratchpad-Tabelle anlegen (A6).** Voraussetzung fuer `guard_violation_rate_by_guard` KPI (Domaene 3). Das Scratchpad-Design ist bereits vollstaendig spezifiziert (FK-61 §61.4.3).

7. **Reset-Purge-Mechanismus implementieren (A7).** Solange `purge_story_analytics` fehlt, enthalten Fact-Tabellen nach einem Story-Reset invalid gebliebene Daten. Verletzt FK-62 §62.2.8 Harte Regel und FAIL-CLOSED-Guardrail.

8. **DesignSystem-Sub (FK-64) und Dashboard-Tabs (FK-63) zuletzt adressieren (A10, A11).** Haengen von funktionierenden Fact-Tabellen und Aggregation ab. FK-63 selbst benennt dies explizit als "spätere Iteration sobald FK-61 und FK-62 implementiert sind".

## 6. Suchstrategie & Quellen

> Volle Transparenz, was der Agent gelesen und wie er gesucht hat.

- **Vollstaendig gelesen:**
  - `concept/domain-design/13-kpis-und-optimierung.md` (DK-13)
  - `concept/technical-design/60_kpi_katalog_und_architektur.md` (FK-60)
  - `concept/technical-design/61_kpi_erhebung_nach_domaenen.md` (FK-61)
  - `concept/technical-design/62_kpi_aggregation.md` (FK-62)
  - `concept/technical-design/63_auswertung_und_dashboard.md` (FK-63)
  - `concept/technical-design/64_control_plane_design_system.md` (FK-64)
  - `src/agentkit/dashboard/models.py`
  - `src/agentkit/dashboard/service.py`
  - `src/agentkit/dashboard/__init__.py`
  - `src/agentkit/telemetry/metrics.py`
  - `src/agentkit/telemetry/kpis/__init__.py`
  - `src/agentkit/telemetry/http/routes.py`
  - `src/agentkit/control_plane/models.py` (punktuell, Nachbar-BC)
- **Punktuell via Grep in `concept/_meta/bc-cut-decisions.md`:**
  - Query `kpi-and-dashboard`: BC-16-Schnitt, Top-Surface, Modul-Prefixes, Sub-Komponenten, Beziehungen, Refactor-Liste, Cross-BC-Drift-Punkte 72-78
- **Code-Scan (Glob/Grep):**
  - Glob `src/agentkit/dashboard/**/*`: vollstaendige Dashboard-Dateien gefunden (3 Python-Module + __pycache__)
  - Glob `src/agentkit/kpi*/**`: kein Treffer (kpi_analytics-Paket nicht vorhanden)
  - Glob `src/agentkit/**/*.py`: vollstaendige Dateiliste gescannt, `agentkit.backend.telemetry.kpis` als einziger KPI-naher Pfad identifiziert
  - Grep `kpi|KpiAnalytics|FactStore|fact_story|sync_analytics|RefreshWorker|kpi_analytics` in `src/agentkit/`: Treffer nur in `multi_llm_hub` (unrelated) und `telemetry/sse_stream.py` (metric card, unrelated)
  - Glob `tests/**/*kpi*`, `tests/**/*dashboard*`: keine Treffer — keine Tests fuer diesen BC vorhanden
  - Glob `concept/technical-design/6*.md`: alle FK-60..64 und FK-68/69 gefunden
