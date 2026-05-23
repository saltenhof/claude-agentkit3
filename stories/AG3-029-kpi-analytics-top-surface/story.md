# AG3-029: KpiAnalytics BC — Top-Klasse + Paket-Migration

**Typ:** Implementation
**Groesse:** M
**Abhaengigkeiten:** AG3-021 (Enums), AG3-022 (Envelope-Bezug)
**Quell-Konzepte (autoritativ, in dieser Reihenfolge):**
- `concept/_meta/bc-cut-decisions.md §BC 16 kpi-and-dashboard`
- `FK-60 §60.1/60.4` (KpiAnalytics-Top, KpiCatalog)
- `FK-63 §63.2.1` (Transport-Agnostizitaet)
- `FK-64 §64.11` (Kanban-Statusspalten Backlog/Approved/InProgress/Done/Cancelled)

---

## 1. Kontext

THEME-005 aus `stories/_priorisierungsempfehlung.md`. Befunde:

- `kpi-and-dashboard.A1`: Modul `agentkit.kpi_analytics` mit Top-Klasse `KpiAnalytics` fehlt komplett.
- `kpi-and-dashboard.C2`: vorhandener `agentkit.dashboard`-Code liegt im falschen Paket; das Modul-Praefixsystem `agentkit.kpi_analytics.*` ist nicht hergestellt.
- `kpi-and-dashboard.C1`: `DashboardService` liest direkt aus `StoryService` statt aus Fact-Tabellen — Trust-Boundary-Verletzung; gleichzeitig fehlen die Fact-Tabellen.
- `kpi-and-dashboard.C3`: Kanban-Statusspalten weichen ab (`defined/active/failed/blocked` statt `Backlog/Approved/In Progress/Done/Cancelled`).

Diese Story stellt die **Top-Surface** und das **Paket-Skelett** her. Die fuenf Fact-Tabellen, der RefreshWorker, das DesignSystem und alle Dashboard-Tabs sind separate Stories der Erstwellen-Folge (KpiAnalytics-Vollausbau ist Detail, siehe Out of Scope). Das analytics-Schema selbst kommt mit THEME-008 (AG3-038).

## 2. Scope

### 2.1 In Scope

#### 2.1.1 Neues Paket `src/agentkit/kpi_analytics/`

Struktur:

- `__init__.py` — Re-Export `KpiAnalytics`, `KpiDefinition`, `KpiCollectionPoint`, `DashboardView`
- `top.py` — `KpiAnalytics`-Top-Klasse
- `catalog.py` — `KpiCatalog`, `KpiDefinition`, `KpiCollectionPoint` Skelett (KPIs werden hier deklarativ registriert; Vollausbau der 40 KPIs ist Folge-Story)
- `views.py` — `DashboardView` Pydantic-Modell
- `errors.py` — typisierte Exceptions

#### 2.1.2 `KpiAnalytics`-Top-Klasse (bc-cut-decisions.md §BC 16)

```python
class KpiAnalytics:
    def __init__(self, catalog: KpiCatalog, fact_store: FactStore | None = None, refresh_worker: RefreshWorker | None = None) -> None: ...

    def list_kpis(self) -> list[KpiDefinition]:
        return self._catalog.list_definitions()

    def refresh_analytics(self, project_key: str, hint_story_id: str | None = None) -> RefreshResult:
        # AG3-029 Pass-3 W-A: Signatur aus bc-cut-decisions.md §BC 16 Z. 1581 uebernommen.
        # AG3-029 deep-review: kein stiller Erfolg. Wenn FactStore/Worker None -> SKIPPED-Status.
        if self._fact_store is None or self._refresh_worker is None:
            return RefreshResult(
                status=RefreshStatus.SKIPPED,
                reason="fact_store_or_refresh_worker_not_configured",
                refreshed_facts=0,
                errors=[],
            )
        ...

    def get_dashboard_view(self, project_key: str, view_kind: str) -> DashboardView:
        # AG3-029 Pass-3 W-A: Signatur aus bc-cut-decisions.md §BC 16 Z. 1582 uebernommen.
        # AG3-029 deep-review: kein stilles rows=[] (das wuerde "keine Daten" statt
        # "Datenquelle fehlt" signalisieren). Entweder typisierte Exception oder
        # explizites UNAVAILABLE-Status.
        if self._fact_store is None:
            raise AnalyticsNotConfiguredError(
                "DashboardView requires FactStore; implemented in AG3-038+"
            )
        ...

    def query(self, project_key: str, sql: str) -> KpiResult:
        # AG3-029 Pass-3 W-A: Signatur aus bc-cut-decisions.md §BC 16 Z. 1583 uebernommen.
        # AG3-038-FOLLOWUP: rohes SQL ist Sicherheits-Risiko; die produktive Folge-Story
        # muss ein typisiertes KPI-Query mitbringen statt rohem SQL (Injection-Schutz).
        raise NotImplementedError("KpiAnalytics.query is part of follow-up story for FactStore + RefreshWorker")

    def get_design_tokens(self) -> DesignTokens:
        # AG3-029 deep-review: leere DesignTokens sind nicht konzepttreu (FK-64:
        # DesignSystem ist nicht runtime-dynamisch). Entweder Methode aus AG3-029
        # entfernen oder hart NotImplementedError werfen. Aktuelle Wahl: hard-fail.
        raise NotImplementedError(
            "DesignSystem tokens are implemented in follow-up story (FK-64)"
        )
```

<!-- AG3-029 deep-review: Stub-Pattern an Severity-Semantik angeglichen. Stille leere Returns sind nicht zulaessig (FAIL CLOSED). -->

Zugehoerige Modelle/Enums (Pydantic-v2, frozen):
- `RefreshStatus`: StrEnum `OK`, `SKIPPED`, `FAILED`
- `RefreshResult`: `status: RefreshStatus`, `reason: str | None`, `refreshed_facts: int`, `errors: list[str]`
- `DashboardViewStatus`: StrEnum `OK`, `UNAVAILABLE`
- `AnalyticsNotConfiguredError`: Exception in `errors.py`

`KpiCatalog` ist im Skelett vorhanden — die 40 KPI-Definitionen werden nicht alle hier befuellt; eine Folge-Story migriert sie aus FK-60. Diese Story stellt sicher, dass das Datenmodell `KpiDefinition` korrekt typisiert ist.

<!-- AG3-029 deep-review: KpiCatalog darf nicht suggerieren, vollstaendig zu sein. -->
`KpiCatalog` ist in AG3-029 nur das typisierte Katalogmodell + testbare InMemory-Registry. Es enthaelt KEINE produktive Vollstaendigkeitsbehauptung gegen FK-60 §60.4. Bis zur Befuellungs-Folge-Story MUSS `catalog.is_complete == False` bzw. `catalog_status = CatalogStatus.SKELETON` sichtbar sein. Konsumenten duerfen sich nicht auf vollstaendige KPI-Listen verlassen.

#### 2.1.3 `KpiDefinition`-Datenmodell (FK-60 §60.4)

Pydantic-v2:
- `kpi_id: str` (z.B. `story_throughput_per_period`)
- `name: str`
- `decision_question: str`
- `formula_repr: str` (deklarativ, kein Code)
- `granularity: KpiGranularity` (StrEnum: `STORY`, `ENTITY_PERIOD`, `PERIOD`)
- `collection_point: KpiCollectionPoint`
- `domain: KpiDomain` (StrEnum: zehn Werte aus FK-60 §60.4 — Domaenen 1-10, Sektionen §60.4.2-§60.4.11; z.B. `THROUGHPUT`, `QUALITY`, `WORKFLOW`) <!-- AG3-029 worker 2026-05-19: Story sprach urspruenglich von "zwoelf"; FK-60 §60.4 ist autoritativ und definiert exakt zehn Domaenen. -->


#### 2.1.4 Status-Spalten-Drift behebt (kpi-and-dashboard.C3)

`src/agentkit/dashboard/service.py:_COLUMN_ORDER` wird auf die FK-64-§64.11-Werte korrigiert: `Backlog`, `Approved`, `In Progress`, `Done`, `Cancelled`. Diese Aenderung wird VOR der Paket-Migration durchgefuehrt (siehe 2.1.5 — wir verschieben den Code, korrigieren parallel den Drift).

#### 2.1.5 Migration von `agentkit.dashboard` -> `agentkit.kpi_analytics.dashboard`

`src/agentkit/dashboard/` wird umbenannt und unter `agentkit/kpi_analytics/dashboard/` re-organisiert. Konkret:

- `src/agentkit/dashboard/models.py` -> `src/agentkit/kpi_analytics/dashboard/models.py`
- `src/agentkit/dashboard/service.py` -> `src/agentkit/kpi_analytics/dashboard/service.py`
- Alle Importer werden auf neuen Pfad umgestellt
- `agentkit.dashboard` als Paket wird entfernt (keine Re-Export-Shims — Zero Debt)
- `agentkit.telemetry.kpis` (leere Datei) wird entfernt

`DashboardService` bleibt funktional erhalten (es liest weiter aus `StoryService` — der Drift zur Fact-Tabelle ist nicht in dieser Story zu beheben, weil Fact-Tabellen erst AG3-038 bringt). Aber: die fehlerhaften Statusspalten sind korrigiert.

#### 2.1.6 Tests

- Unit-Tests fuer `KpiAnalytics.list_kpis`, `refresh_analytics` (Stub-Pfade), `get_dashboard_view` (Stub), `get_design_tokens` (leere Tokens)
- `query`-Test mit `NotImplementedError`-Assertion
- Unit-Tests fuer `KpiDefinition`, `KpiCatalog` (mit Sample-KPI-Eintraegen)
- Migration-Tests: alle Importer (Tests + Source) zeigen auf den neuen Pfad; alte `agentkit.dashboard`-Import-Pfade sind nicht mehr existent
- Drift-Korrektur-Test: `_COLUMN_ORDER` enthaelt exakt die fuenf FK-64-Werte (`Backlog`, `Approved`, `In Progress`, `Done`, `Cancelled`)
- Contract-Test `tests/contract/kpi_analytics/test_top_surface.py`: alle fuenf Methoden mit Signaturen

### 2.2 Out of Scope

- PostgreSQL analytics-Schema mit fuenf Fact-Tabellen (`kpi-and-dashboard.A3/A4`) — gehoert zu THEME-008 (AG3-038)
- RefreshWorker (`kpi-and-dashboard.A5`) — Folge-Story nach AG3-038
- Guard-Invocation-Scratchpad (`kpi-and-dashboard.A6`) — AG3-038
- Reset-Purge (`kpi-and-dashboard.A7`) — THEME-007 (AG3-035)
- Neue Event-Typen + angereicherte Payloads (`kpi-and-dashboard.A8/A9`) — THEME-007 (AG3-037)
- Sechs Dashboard-Tabs (`kpi-and-dashboard.A10`) — Folge-Story; explizit in Priorisierungsempfehlung §5 als "spaetere Iteration" markiert
- DesignSystem-Sub (`kpi-and-dashboard.A11`) — explizit "spaetere Iteration"
- Schema-Migrations-Strategie (`kpi-and-dashboard.A12`) — AG3-038
- Volle 40-KPI-Definition (FK-60 §60.4 ausschnitt) — Folge-Story
- `DashboardService`-Drift zur Fact-Tabelle (`kpi-and-dashboard.C1/B1`) — nach AG3-038
- `compute_pipeline_metrics`-qa_rounds-Bug (`kpi-and-dashboard.B3` / `telemetry-and-events.C2`) — THEME-007

## 3. Betroffene Dateien

| Datei | Aenderungsart | Beschreibung |
|---|---|---|
| `src/agentkit/kpi_analytics/__init__.py` | Neu | Re-Export Top-Surface |
| `src/agentkit/kpi_analytics/top.py` | Neu | `KpiAnalytics`-Klasse |
| `src/agentkit/kpi_analytics/catalog.py` | Neu | `KpiCatalog`, `KpiDefinition`, `KpiCollectionPoint`, `KpiGranularity`, `KpiDomain` |
| `src/agentkit/kpi_analytics/views.py` | Neu | `DashboardView`, `DesignTokens`, `RefreshResult`, `KpiResult` |
| `src/agentkit/kpi_analytics/errors.py` | Neu | Exceptions |
| `src/agentkit/kpi_analytics/dashboard/__init__.py` | Neu | Dashboard-Sub |
| `src/agentkit/kpi_analytics/dashboard/models.py` | Verschoben aus `agentkit/dashboard/models.py` | Statusspalten-Drift korrigiert |
| `src/agentkit/kpi_analytics/dashboard/service.py` | Verschoben aus `agentkit/dashboard/service.py` | Statusspalten-Drift korrigiert |
| `src/agentkit/dashboard/` | Geloescht | Migration abgeschlossen |
| `src/agentkit/telemetry/kpis/__init__.py` | Geloescht | leere Datei am falschen Ort |
| Alle Importer | Modifiziert | `agentkit.dashboard` -> `agentkit.kpi_analytics.dashboard` |
| `tests/unit/kpi_analytics/test_top.py` | Neu | KpiAnalytics-Top-Tests |
| `tests/unit/kpi_analytics/test_catalog.py` | Neu | KpiCatalog-Tests |
| `tests/unit/kpi_analytics/dashboard/...` | Verschoben aus `tests/unit/dashboard/...` | Test-Migration |
| `tests/contract/kpi_analytics/test_top_surface.py` | Neu | Vertrags-Pinning |

## 4. Akzeptanzkriterien

1. **Paket `src/agentkit/kpi_analytics/` existiert** und exportiert `KpiAnalytics`, `KpiDefinition`, `KpiCollectionPoint`, `KpiCatalog`, `DashboardView`, `KpiGranularity`, `KpiDomain`.
2. **Klasse `KpiAnalytics` hat fuenf Top-Methoden** mit den genannten Signaturen: `list_kpis`, `refresh_analytics`, `get_dashboard_view`, `query` (NotImplementedError), `get_design_tokens`.
3. **`KpiDefinition`-Pflichtfelder**: `kpi_id`, `name`, `decision_question`, `formula_repr`, `granularity`, `collection_point`, `domain`. Pydantic-v2 frozen.
4. **`KpiGranularity` und `KpiDomain` sind StrEnums** mit den konzept-normativen Werten.
5. **Paket-Migration abgeschlossen**: `agentkit.dashboard` existiert nicht mehr; Importe auf `agentkit.kpi_analytics.dashboard` umgestellt; `agentkit.telemetry.kpis` entfernt.
6. **Statusspalten-Drift behoben**: `_COLUMN_ORDER` (oder Aequivalent) enthaelt `["Backlog", "Approved", "In Progress", "Done", "Cancelled"]`.
7. **Architecture-Conformance**: `agentkit.kpi_analytics` importiert nur `agentkit.core_types`; alle **neuen** KpiAnalytics-Top-Methoden duerfen nicht direkt aus `state_backend` oder alten Dashboard-/Story-Fassaden lesen. **Uebergangs-Ausnahme** (zeitlich begrenzt): `agentkit.kpi_analytics.dashboard.service` darf bis AG3-038 in einem klar markierten Uebergangspfad (Inline-Kommentar `# DRIFT-AG3-038: temporary StoryService leihe`) den bestehenden `StoryService` lesen. Der Drift zur FactStore-Leseseite ist in AG3-038 zu schliessen und wird nicht als neue Architektur legitimiert. <!-- AG3-029 deep-review: StoryService-Leihe nur fuer dashboard.service, nicht fuer alle neuen Methoden. -->
8. **Pflichtbefehle gruen**: pytest unit + contract; mypy --strict; ruff clean; Coverage haelt 85%.

## 5. Definition of Done

- AK 1-8 erfuellt.
- `.venv\Scripts\python -m pytest tests/unit/kpi_analytics tests/contract/kpi_analytics -q` gruen.
- `mypy --strict` gruen, `ruff check src tests` gruen.
- Aenderungen committed auf `main`.

## 6. Konzept-Referenzen (autoritativ)

- **`concept/_meta/bc-cut-decisions.md §BC 16`** — Modul-Prefix, Top-Surface
- **FK-60 §60.1/60.4** — KpiAnalytics, KpiCatalog
- **FK-63 §63.2.1** — Transport-Agnostizitaet
- **FK-64 §64.11** — Kanban-Statusspalten

## 7. Guardrail-Referenzen

- **FIX THE MODEL, NOT THE SYMPTOM**: Paket-Verschiebung bringt Code an den konzeptionellen Ort.
- **ZERO DEBT**: keine Re-Export-Shims aus altem Paket.
- **SINGLE SOURCE OF TRUTH**: Statusspalten exakt nach Konzept.
- **NO ERROR BYPASSING**: `query` mit NotImplementedError ist explizit; keine stille leere Liste.

## 8. Hinweise fuer den Sub-Agent

- Migration: alle Importer-Stellen via Grep finden (`from agentkit.dashboard`). Wenn der `control_plane`-Layer eine Route exponiert, die `DashboardService` nutzt, anpassen.
- Die Statusspalten-Korrektur ist die einzige tatsaechliche Verhaltensaenderung; alle anderen Aenderungen sind Naming/Paketverschiebung.
- AK2 NICHT veraendern.
