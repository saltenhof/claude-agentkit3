# AG3-038: PostgreSQL analytics-Schema + 5 Fact-Tabellen + sync_state + Migrations-Strategie

**Typ:** Implementation
**Groesse:** L
**Abhaengigkeiten:** AG3-021 (Enums), AG3-029 (KpiAnalytics-Paket-Struktur)
**Quell-Konzepte (autoritativ, in dieser Reihenfolge):**
- `FK-62 §62.2.1-62.2.5` (fuenf Fact-Tabellen + sync_state)
- `FK-62 §62.2.6` (guard_invocation_counters)
- `FK-62 §62.4` (Schema-Migrations-Strategie)
- `FK-60 §60.2 P8/P4` (PostgreSQL als Plattform)
- `FK-62 §62.3` (FactStore-Sub + RefreshWorker — RefreshWorker out of scope)

---

## 1. Kontext

THEME-008 aus `stories/_priorisierungsempfehlung.md`. Befunde:

- `kpi-and-dashboard.A4`: PostgreSQL analytics-Schema mit fuenf Fact-Tabellen + sync_state fehlt komplett.
- `kpi-and-dashboard.A3`: FactStore-Sub fehlt (Modul `agentkit.kpi_analytics.fact_store`).
- `kpi-and-dashboard.A6`: guard_invocation_counters-Scratchpad-Tabelle fehlt.
- `kpi-and-dashboard.A12`: Schema-Migrations-Strategie (`_ensure_column`, `schema_version`-Cursor) fehlt.

Diese Story liefert das **Schema-Layer**: Tabellen + FactStore-Sub mit minimaler Lese-API. RefreshWorker (sync_analytics-Aggregation, `kpi-and-dashboard.A5`) ist eine Folge-Story.

## 2. Scope

### 2.1 In Scope

#### 2.1.1 PostgreSQL analytics-Schema (FK-62 §62.2)

`src/agentkit/state_backend/postgres_schema.sql` wird um neue Schema-Definition erweitert:

```sql
CREATE SCHEMA IF NOT EXISTS analytics;

CREATE TABLE IF NOT EXISTS analytics.fact_story (
    project_key VARCHAR NOT NULL,
    story_id VARCHAR NOT NULL,
    story_type VARCHAR NOT NULL,
    story_size VARCHAR NOT NULL,
    story_mode VARCHAR NULL,
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ NULL,
    qa_rounds INT NOT NULL,
    compaction_count INT NULL,
    llm_call_count INT NULL,
    adversarial_findings INT NULL,
    adversarial_tests_created INT NULL,
    files_changed INT NULL,
    feedback_converged BOOLEAN NULL,
    phase_setup_ms BIGINT NULL,
    phase_implementation_ms BIGINT NULL,
    phase_closure_ms BIGINT NULL,
    are_gate_status VARCHAR NULL,
    agentkit_version VARCHAR NOT NULL,
    agentkit_commit VARCHAR NOT NULL,
    PRIMARY KEY (project_key, story_id)
);

CREATE TABLE IF NOT EXISTS analytics.fact_guard_period (
    project_key VARCHAR NOT NULL,
    guard_id VARCHAR NOT NULL,
    period_start TIMESTAMPTZ NOT NULL,
    period_end TIMESTAMPTZ NOT NULL,
    invocation_count BIGINT NOT NULL,
    violation_count BIGINT NOT NULL,
    PRIMARY KEY (project_key, guard_id, period_start)
);

CREATE TABLE IF NOT EXISTS analytics.fact_pool_period (
    project_key VARCHAR NOT NULL,
    llm_role VARCHAR NOT NULL,
    period_start TIMESTAMPTZ NOT NULL,
    period_end TIMESTAMPTZ NOT NULL,
    call_count BIGINT NOT NULL,
    token_input_total BIGINT NOT NULL,
    token_output_total BIGINT NOT NULL,
    avg_latency_ms BIGINT NULL,
    PRIMARY KEY (project_key, llm_role, period_start)
);

CREATE TABLE IF NOT EXISTS analytics.fact_pipeline_period (
    project_key VARCHAR NOT NULL,
    period_start TIMESTAMPTZ NOT NULL,
    period_end TIMESTAMPTZ NOT NULL,
    stories_completed INT NOT NULL,
    stories_escalated INT NOT NULL,
    avg_qa_rounds NUMERIC NULL,
    avg_phase_implementation_ms BIGINT NULL,
    PRIMARY KEY (project_key, period_start)
);

CREATE TABLE IF NOT EXISTS analytics.fact_corpus_period (
    project_key VARCHAR NOT NULL,
    period_start TIMESTAMPTZ NOT NULL,
    period_end TIMESTAMPTZ NOT NULL,
    incidents_recorded INT NOT NULL,
    patterns_promoted INT NOT NULL,
    checks_approved INT NOT NULL,
    PRIMARY KEY (project_key, period_start)
);

CREATE TABLE IF NOT EXISTS analytics.sync_state (
    table_name VARCHAR PRIMARY KEY,
    last_synced_at TIMESTAMPTZ NOT NULL,
    last_synced_event_id UUID NULL
);

CREATE TABLE IF NOT EXISTS analytics.guard_invocation_counters (
    project_key VARCHAR NOT NULL,
    guard_id VARCHAR NOT NULL,
    counter_value BIGINT NOT NULL,
    last_updated_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (project_key, guard_id)
);
```

Indizes nach Bedarf (z.B. `fact_story(project_key, completed_at)` fuer Dashboard-Queries).

Mandantenregel (FK-62 §62.2 "Mandantenregel"): `project_key` ist immer fuehrender Schluessel.

#### 2.1.2 `FactStore`-Sub `src/agentkit/kpi_analytics/fact_store/`

```python
class FactStore:
    """
    T-Driver auf das analytics-Schema. Liest und schreibt
    Fact-Tabellen (analytics.fact_*) und sync_state.
    """
    def __init__(self, repository: FactRepository) -> None: ...

    def list_fact_stories(self, project_key: str, period: PeriodFilter | None = None) -> list[FactStory]: ...
    def list_fact_guards(self, project_key: str, period: PeriodFilter) -> list[FactGuardPeriod]: ...
    def list_fact_pool(self, project_key: str, period: PeriodFilter) -> list[FactPoolPeriod]: ...
    def list_fact_pipeline(self, project_key: str, period: PeriodFilter) -> list[FactPipelinePeriod]: ...
    def list_fact_corpus(self, project_key: str, period: PeriodFilter) -> list[FactCorpusPeriod]: ...
    def get_sync_state(self, table_name: str) -> SyncState | None: ...
    def upsert_fact_story(self, fact: FactStory) -> None: ...
    # weitere upsert-Methoden analog
```

Pydantic-Modelle: `FactStory`, `FactGuardPeriod`, `FactPoolPeriod`, `FactPipelinePeriod`, `FactCorpusPeriod`, `SyncState`, `PeriodFilter`.

#### 2.1.3 Schema-Migrations-Strategie (FK-62 §62.4)

Neues Modul `src/agentkit/state_backend/migration/`:

- `migration_runner.py`: idempotenter Runner, der `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` / `CREATE TABLE IF NOT EXISTS` Statements ausfuehrt
- `versions/v_3_4_analytics.sql`: SQL-Datei mit den neuen Tabellen (analog AG3-005-Mechanik fuer Side-by-Side)
- Versions-Cursor: Tabelle `state_backend.schema_versions` (PK `version`, `applied_at`) wird ergaenzt; ein Lauf der Migration setzt `applied_at` ein
- Idempotent re-runnable: doppelter Lauf produziert keine Fehler und keine Duplikate

`state_backend.config.SCHEMA_VERSION`-Bump entsprechend (AG3-005-Mechanik).

#### 2.1.4 SQLite-Aequivalent

Fuer Tests und Sandboxes wird das analytics-Schema in SQLite gespiegelt (gleiche Tabellen ohne Schema-Praefix, da SQLite kein Schema-Konzept hat). Tests laufen parametrisiert auf beiden Backends.

#### 2.1.5 `_artifact_class_for`-Heuristik final entfernen (B1 bereits Teil von AG3-023)

Diese Story sollte fertig sein, nachdem AG3-023 die Heuristik bereits entfernt hat. Hier kein Doppelaufwand; nur sicherstellen.

#### 2.1.6 KpiAnalytics-Integration

`KpiAnalytics.refresh_analytics` aus AG3-029 (Stub) bekommt jetzt Zugriff auf FactStore via `__init__`. Voller Refresh-Mechanismus (Dirty-Set, Re-Aggregation) ist weiter `NotImplementedError` mit Verweis auf Folge-Story.

`KpiAnalytics.get_dashboard_view` kann FactStore lesen — Stub wird auf Read-Pfade verkabelt, die existing-Tabellen lesen koennen. (Vollausbau separate Story.)

#### 2.1.7 Tests

- Unit-Tests fuer `FactStore.list_*` und `upsert_*` (parametrisiert SQLite + Postgres)
- Unit-Tests fuer `FactStory`, `FactGuardPeriod`, ... Pydantic-Modelle
- Migration-Test: Migration-Runner laeuft idempotent; doppelter Lauf produziert keine Fehler
- Integration-Test: Insert von Test-Daten in alle fuenf Tabellen + Roundtrip via FactStore
- Contract-Test `tests/contract/state_backend/test_analytics_schema.py`: alle fuenf Tabellen + sync_state + guard_invocation_counters existieren mit den Pflicht-Spalten

### 2.2 Out of Scope

- RefreshWorker (`kpi-and-dashboard.A5`) — Folge-Story (sync_analytics-Aggregation, Dirty-Set, atomare Transaktion)
- Reset-Purge fuer analytics-Tabellen (`A7`) — gehoert in `ProjectionAccessor.purge_for_story` (AG3-035) — Folge-Story-Erweiterung
- Volle 40-KPI-Definitionen — Folge-Story
- Sechs Dashboard-Tabs — Folge-Story
- DesignSystem — Folge-Story
- Statussynchronisation Dashboard <-> FactStore (Drift aus `kpi-and-dashboard.C1`) — Folge-Story
- Event-driven Trigger fuer sync_analytics — Folge-Story

## 3. Betroffene Dateien

| Datei | Aenderungsart | Beschreibung |
|---|---|---|
| `src/agentkit/state_backend/postgres_schema.sql` | Modifiziert | analytics-Schema + sieben Tabellen |
| `src/agentkit/state_backend/sqlite_store.py` | Modifiziert | analytics-Tabellen-Aequivalent (ohne Schema-Prefix) |
| `src/agentkit/state_backend/migration/__init__.py` | Neu | |
| `src/agentkit/state_backend/migration/migration_runner.py` | Neu | Idempotenter Runner |
| `src/agentkit/state_backend/migration/versions/v_3_4_analytics.sql` | Neu | DDL |
| `src/agentkit/state_backend/config.py` | Modifiziert | SCHEMA_VERSION-Bump auf 3.4 |
| `src/agentkit/state_backend/store/fact_repository.py` | Neu | `FactRepository`-Protocol + SQLite/Postgres-Impl |
| `src/agentkit/kpi_analytics/fact_store/__init__.py` | Neu | |
| `src/agentkit/kpi_analytics/fact_store/store.py` | Neu | `FactStore`-Klasse |
| `src/agentkit/kpi_analytics/fact_store/models.py` | Neu | `FactStory`, `FactGuardPeriod`, `FactPoolPeriod`, `FactPipelinePeriod`, `FactCorpusPeriod`, `SyncState`, `PeriodFilter` |
| `src/agentkit/kpi_analytics/top.py` | Modifiziert | KpiAnalytics nutzt FactStore in `get_dashboard_view`/`refresh_analytics` (Stub bleibt fuer `refresh_analytics`) |
| `tests/unit/kpi_analytics/fact_store/...` | Neu | |
| `tests/unit/state_backend/migration/test_migration_runner.py` | Neu | Idempotenz |
| `tests/integration/kpi_analytics/test_fact_store_roundtrip.py` | Neu | E2E |
| `tests/contract/state_backend/test_analytics_schema.py` | Neu | Schema-Pinning |

## 4. Akzeptanzkriterien

1. **PostgreSQL `analytics`-Schema existiert** mit den fuenf Fact-Tabellen, `sync_state` und `guard_invocation_counters`.
2. **SQLite-Aequivalent**: gleichnamige Tabellen ohne Schema-Prefix; Tests laufen parametrisiert.
3. **`FactStore`-Klasse existiert** mit Lese-Methoden fuer alle fuenf Fact-Tabellen plus `get_sync_state` plus `upsert_fact_story` (analog fuer andere).
4. **Pydantic-Modelle** fuer jedes Fact-Record (frozen, extra forbid).
5. **`MigrationRunner`** laeuft idempotent: doppelte Ausfuehrung produziert keine Fehler, keine Duplikate, kein DROP/RECREATE.
6. **`SCHEMA_VERSION`-Bump** auf naechste Version; Side-by-Side mit alter Version (AG3-005-Mechanik).
7. **`KpiAnalytics.get_dashboard_view`** kann via FactStore Daten lesen (Stub liefert nicht mehr leere View, sondern liest aktuelle Fact-Daten — wenn leer, dann leere View).
8. **Architecture-Conformance**: `FactStore` (`kpi_analytics.fact_store`) importiert nur ueber `FactRepository`-Protocol; kein direkter `state_backend.store`-Fassaden-Zugriff.
9. **Pflichtbefehle gruen**: pytest unit + integration + contract; mypy --strict; ruff clean; Coverage haelt 85%.

## 5. Definition of Done

- AK 1-9 erfuellt.
- `.venv\Scripts\python -m pytest tests/unit/kpi_analytics tests/integration/kpi_analytics tests/contract/state_backend -q` gruen.
- `mypy --strict` gruen, `ruff check src tests` gruen.
- SQLite + Postgres migriert.
- Aenderungen committed auf `main`.

## 6. Konzept-Referenzen (autoritativ)

- **FK-62 §62.2.1-62.2.5** — fuenf Fact-Tabellen
- **FK-62 §62.2.6** — guard_invocation_counters
- **FK-62 §62.4** — Schema-Migrations-Strategie
- **FK-60 §60.2 P8/P4** — PostgreSQL als Plattform
- **FK-18 §18.9a** — Schema-Versionierung
- **FK-62 §62.3** — FactStore-Sub

## 7. Guardrail-Referenzen

- **FIX THE MODEL, NOT THE SYMPTOM**: Persistenz-Topologie endlich konzept-konform.
- **ZERO DEBT**: alle fuenf Fact-Tabellen + sync_state + Scratchpad in einem Wurf.
- **FAIL CLOSED**: fehlende Tabelle bei Lese-Versuch -> Exception, kein silent empty result.
- **SINGLE SOURCE OF TRUTH**: analytics-Schema ist die Wahrheit fuer aggregierte KPIs.

## 8. Hinweise fuer den Sub-Agent

- Schema-Prefix `analytics.` nur in Postgres; SQLite ignoriert Schemas — Tabellen heissen dort schlicht `fact_story` etc.
- Tests gegen Postgres koennten Test-Container brauchen. Falls noch nicht im Repo: nutze existing-Postgres-Test-Setup (siehe AG3-005-Tests).
- AK2 NICHT veraendern.
