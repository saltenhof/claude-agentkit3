# AG3-094: Dashboards + Live-Updates (ECharts + Frontend-SSE-Consumer)

**Typ:** Implementation
**Groesse:** M
**Bounded Context:** `kpi_analytics` (Analytics-Slice, Composer; FK-72 §72.6 Z.136) + App-Shell-Live-Hook-Komposition. **Kein** `frontend`-BC — FK-72 §72.3 (Z.56) stellt klar: „Es gibt **keinen** UI-BC". Diese Story baut den Analytics-Slice (Charts auf echten KPI-Endpoints) und den **Frontend-SSE-Consumer** als Shell-/Slice-Hook. Backend-SSE-Endpoint und KPI-Endpoints sind fertig (siehe Out of Scope). Baut auf der App-Shell (AG3-093), den KPI-Endpoints (AG3-084) und der Design-System-Token-Familie (AG3-092) auf.
**Quell-Konzepte (autoritativ):**
- `frontend/prototype/src/components/AnalyticsView.tsx` — **normative funktionale Soll-Quelle** (Concept-as-Code; FK-72 §72.13 Z.383-385: „was im Prototyp lebt, ist Soll. Konzept-Aussagen … duerfen ihm **nicht** widersprechen"). Definiert die Chart-Lib (ECharts) und die Feature-Menge.
- `FK-63 §63.2-§63.4` (`concept/technical-design/63_auswertung_und_dashboard.md`) — Dashboard-/KPI-Auswertungssichten; §63.3.3 (Z.142-154) Nutzer-Auswertungen: Zeitraum, Entity-/Story-Filter, Zwei-Zeitraum-Vergleich.
- `FK-72 §72.12` (`concept/technical-design/72_frontend_architektur.md` Z.264-312) — Live-Updates: SSE als einheitlicher Mechanismus (kein Frontend-Polling-Loop); §72.12.1 (Z.270) Pattern Initial-GET + SSE-Subscribe mit `?topics=`-Filter; §72.12.2 (Z.287) projekt-skopierter Stream `/v1/projects/{key}/events`; §72.12.3 (Z.294) Single-Producer `telemetry`; §72.12.4 (Z.306) lossy mit Re-Sync (frischer Initial-GET bei jedem (Re-)Connect).
- `FK-72 §72.14.6` (Z.503) — Edge-Cases/UI-Verhalten (Mutation-Fehler, Story-verschwindet, Empty-States).
- `FK-91 §91.8.3` (`concept/technical-design/91_api_event_katalog.md` Z.506-518) — projekt-skopierter Topic-Katalog.

---

## 1. Kontext / Ist-Zustand (belegt)

Charts existieren im Prototyp, aber **nicht** auf echten KPI-Endpoints und **ohne** Live-Mechanik:

- Analytics-Sicht: `frontend/prototype/src/components/AnalyticsView.tsx` rendert zwei Sub-Tabs (Overview + Timeseries) mit **ECharts** (`echarts-for-react`, `:15`; `import type { EChartsOption } from 'echarts'`, `:16`), Multi-Series-Auswahl (`metric-chip`, `:186`-`:202`), Zeitraum-Presets (7/14/30/60 Tage, `:27`-`:32`), Min/Max-Band-Toggle (`showBand`, `:148`/`:284`-`:316`), Zoom/Brush (`dataZoom` inside+slider, `:382`-`:398`), Cross-Tooltip (`axisPointer: { type: 'cross' }`, `:342`; Band-Helper-Filter im Formatter, `:344`-`:356`).
- Datenquelle ist **synthetisch/clientseitig**: `frontend/prototype/src/store/storySelectors.ts:590` `selectProjectKpiStats` (avg/min/max/p90 ueber 12 KPI-Keys) und `:652` `selectKpiDailySeries` (seeded-noise-Synthese um einen fixen „today" = `2026-05-11`, `:655`). FK-63 §63.3 verlangt echte KPI-Aggregat-Endpoints (Owner AG3-084). AG3-084 liefert die fuenf Endpoints `stories/guards/pools/pipeline/corpus` final unter der Control-Plane-Konvention `/v1/...` (AG3-084 AC1: die FK-63-`/api/...`-Pfade werden auf `/v1/...` gemappt, analog `control_plane/http.py:298-301`), **nicht** unter `/api/kpi/*`.
- **Keine** SSE-Anbindung: der Prototyp hat keinen Event-Stream; alle Sichten leben auf statischen Fixtures. FK-72 §72.12.1 (Z.270) verlangt Initial-GET + SSE-Subscribe; FK-91 §91.8.3 katalogisiert die Topics.
- Vergleichs-/Filter-UI (FK-63 §63.3.3) existiert nur rudimentaer (Metrik-Overlay-Auswahl `:184`-`:203`, Zeitraum-Preset) — **kein** beliebiger Zeitraum, **keine** Entity-/Story-Filter, **kein** Zwei-Zeitraum-Vergleich.

## 2. Scope

### 2.1 In Scope

1. **Dashboard-Tabs/Charts auf den echten KPI-Endpoints** (FK-63 §63.2-§63.3, AG3-084): Analytics-Overview (Aggregat-KPI-Karten avg/min/max/p90) + Timeseries (Multi-Series-Linien mit Zeitraum-Presets, Metrik-Overlay-Auswahl, Min/Max-Band, Zoom/Brush, Cross-Tooltip), funktional 1:1 zum Prototyp, aber Daten aus den finalen AG3-084-KPI-Endpoints `GET /v1/.../kpi/{stories|guards|pools|pipeline|corpus}` (Control-Plane-`/v1/...`-Konvention, AG3-084 AC1) statt clientseitiger Synthese. Der konkrete finale Pfad wird von AG3-084/AG3-091 verbindlich fixiert; AG3-094 konsumiert ihn und baut **keinen** Eigen-Pfad. **Nicht** konsumiert: `/api/kpi/*` (das ist die FK-63-Entwurfsschreibweise; final ist `/v1/...`).
2. **Chart-Lib verbindlich: ECharts (`echarts-for-react`).** Der Prototyp ist die normative Soll-Quelle (FK-72 §72.13 Z.383-385: Prototyp ist Soll, Konzept zieht bei Konflikt nach), und er nutzt ECharts mit Features (`dataZoom`-Brush, gestapeltes Min/Max-Band, Cross-Tooltip-Formatter), deren 1:1-Port nicht-trivial waere. Die „Chart.js"-Erwaehnung im Master-Index (`var/concept-gap-analysis/_STORY_INDEX.md:119`) und in FK-63 §63.x (Z.85) bezieht sich auf das **alte** stdlib-QA-Dashboard (Ist-Zustand), **nicht** auf die Soll-App. Index-/FK-Prosa-Nachzug auf ECharts wird an **AG3-103** (doc-only Konzept-Nachzug, owner u. a. FK-91↔FK-72-Konsistenz) gespiegelt; diese Story baut Code auf ECharts.
3. **Frontend-SSE-Consumer + Live-Hooks** (FK-72 §72.12.1, AG3-003 liefert den Backend-Endpoint): Initial-GET + SSE-Subscribe auf `GET /v1/projects/{key}/events?topics=...` pro Sicht via Browser-`EventSource`. Topic-Sets pro Sicht **strikt nach FK-72 §72.5 (Z.128-144) ↔ FK-91 §91.8.3 (Owner-BC pro Topic)**:
   - **Analytics** (`kpi_analytics`-Composer, mitliefernd `telemetry`/`failure_corpus`, FK-72 §72.5 Z.136) → `kpi,telemetry,failure_corpus` (KPI-Aggregate + Mode-Lock/Execution-Events + Failure-Corpus-Funnel, FK-72 §72.11.3 Z.258 „failure_corpus — Funnel in Analytics").
   - **Kanban/Board** (`story_context_manager`, FK-72 §72.5 Z.134) → `stories,phases` (Story-Lifecycle + Phasen-Uebergaenge).
   - **Graph** (Top-Sicht + Sub-Tabs `graph`/`ready`/`limits`, **Owner-BC `execution_planning`**, FK-72 §72.5 Z.130-133 und Z.143-144 „werden ueber denselben SSE-Topic `planning` live aktuell gehalten") → `planning`. Das Wire-Schema `dependency_graph_changed` liegt laut FK-91 §91.8.3 (Z.516) unter dem `planning`-Topic — Graph-Aenderungen kommen also **nicht** ueber `stories,phases`.

   Lossy-Re-Sync (FK-72 §72.12.4 Z.306): bei jedem (Re-)Connect frischer Initial-GET; **kein** Frontend-REST-Polling-Loop; kein Sequence-Cursor/Acknowledge.
4. **Live-Patch/Re-Fetch-Logik** (FK-72 §72.12.1 Z.280): bei relevantem Event lokal patchen oder gezielt re-fetchen. Topic-Filter wird serverseitig durchgesetzt (AG3-003); das Frontend bestellt nur die Topics, die die Sicht braucht. Event-Typen/Topics als typisierte Sets (ARCH-55, englische Identifier), nicht als freie Strings. **Topics mit offenem Wire-Schema (`kpi` und `failure_corpus`, FK-91 §91.8.3 Z.515/Z.517 = „offen") werden ausschliesslich per Re-Fetch (Initial-GET-Re-Sync) der jeweiligen Analytics-Sicht behandelt — kein feldgranulares Event-Payload-Patching**, solange das Schema offen ist (siehe Out of Scope). Topics mit definiertem Wire-Schema (`stories`, `phases`, `planning`, `telemetry`) duerfen feldgranular gepatcht **oder** re-fetcht werden.
5. **Vergleichs-/Filter-UI nach FK-63 §63.3.3 — gebunden an den lieferbaren AG3-084-Query-Vertrag.** AG3-084 bindet im typisierten `KpiQueryFilter` exakt die FK-63-§63.4.2-Parameter (`project_key`, `from`, `to`, `guard`, `pool`, `story_type`, `story_size`) plus `comparison_period` (AG3-084 §2.1.4 / AC5). AG3-094 baut **nur** UI-Steuerung + Durchreichung fuer genau diese Dimensionen — kein clientseitiges Nachrechnen:
   - **Zeitraum**: beliebige Start-/End-Daten (Custom-Range, → `from`/`to`), zusaetzlich zu den Prototyp-Presets 7/14/30/60.
   - **Entity-Filter**: Einschraenkung auf **Guards** (→ `guard`, nur `/v1/.../kpi/guards`) und **Pools** (→ `pool`, nur `/v1/.../kpi/pools`), je gebunden an die natuerliche Koernung des Endpoints (FK-63 §63.4.2 Z.216-217).
   - **Story-Filter**: **Story-Typ** (→ `story_type`, `/v1/.../kpi/stories` + `/pipeline`) und **Story-Groesse** (→ `story_size`, `/v1/.../kpi/stories`) (FK-63 §63.4.2 Z.218-219).
   - **Vergleichsmodus**: Zwei Zeitraeume nebeneinander (vorher/nachher, → `comparison_period`) **plus** der Metrik-Overlay-Vergleich des Prototyps. Alle Filter/Vergleichs-Parameter werden als serverseitige Query-Parameter an die AG3-084-`/v1/.../kpi/*`-Endpoints durchgereicht; das Frontend rechnet **nicht** clientseitig nach.
   - **NICHT in dieser Story buildbar (kein Backend-Vertrag, siehe 2.2):** **Template-Entity-Filter** (FK-63 §63.4.2 Z.221-227: Template-Analytik liegt als JSON-Feld in `fact_pool_period` und ist „nicht ueber einen eigenen Filter ansteuerbar"; AG3-084 bindet keinen Template-Param) und **Pipeline-Modus-Story-Filter** (FK-63 §63.3.3 nennt ihn als UI-Wunsch, aber §63.4.2 fuehrt **keinen** `pipeline_mode`-Query-Parameter und AG3-084 bindet ihn nicht). Diese beiden FK-63-§63.3.3-UI-Dimensionen sind ohne neuen Backend-Vertrag nicht durchreichbar; sie werden **nicht** als toter UI-Schalter gebaut (FAIL-CLOSED statt clientseitiger Kompensation) und an den Backend-Owner geroutet (siehe 2.2).
   - **Explizit Out of Scope** (siehe 2.2): projekt-/story-**uebergreifender** Cross-Entity-Vergleich (mehrere Projekte/Stories nebeneinander).
6. **Chart-Theming ueber Design-Tokens** (FK-64 §64.17, AG3-092): Serien-/Achsen-/Grid-Farben aus der Token-Familie (bzw. der mit AG3-092 geklaerten `chart.series.*`-Familie), keine losen Hex ausserhalb der Token-Definition. Der Prototyp haelt Farben noch als Hex-Konstanten (`SERIES_COLORS`, `AnalyticsView.tsx:38`-`:51`); produktiv werden diese durch Token-Referenzen ersetzt.
7. **Empty-/Error-/Reconnect-Verhalten** (FK-72 §72.14.6 Z.503): SSE-Abbruch → automatischer `EventSource`-Reconnect + Initial-GET-Re-Sync; Total-Offline → mutierende UI disabled + „Verbindung verloren"-Indikator an der Topbar; leere KPI-Daten → Hinweis statt leerer Chart-Container.

### 2.2 Out of Scope (mit Owner)

- **KPI-Endpoints `/v1/.../kpi/{stories|guards|pools|pipeline|corpus}` (inkl. typisiertem `KpiQueryFilter`: Zeitraum/Entity-/Story-Filter + `comparison_period`) + Fact-Rollups** (Backend) — **AG3-084** (`depends_on`). Diese Story konsumiert sie. Die buildbaren FK-63-§63.3.3-Filter (Custom-Zeitraum, Guard/Pool/Story-Typ/Story-Groesse, Zwei-Zeitraum-Vergleich) werden serverseitig von AG3-084 bereitgestellt; AG3-094 baut nur die UI-Steuerung + Durchreichung. Pfad final `/v1/...` (AG3-084 AC1), **nicht** `/api/kpi/*`.
- **Live-Read-Endpoint fuer laufende Stories (`/api/live/stories` aus dem Runtime-Schema)** — **NICHT von AG3-084 geliefert.** AG3-084 §2.2/AC8 schliesst `/api/live/stories` explizit aus und routet ihn an die Runtime-Schema-Live-Read-Port-Story (**AG3-081**), weil aktuell kein projekt-skopierter Live-Read-Port existiert (`telemetry/projection_accessor.py:56-70`). AG3-094 konsumiert **keinen** `/api/live/stories`-Endpoint; die Live-Aktualitaet von Board/Kanban kommt aus dem Initial-GET der Story-Read-Models (AG3-091/AG3-093) plus SSE-`stories`/`phases`, nicht aus einer Live-Stories-Sonderroute.
- **Backend-SSE-Endpoint `/v1/projects/{key}/events` (serverseitiger Topics-Filter, Lossy, Heartbeat, Cross-Project-Isolation)** — **AG3-003** (`depends_on`, `completed`). AG3-094 aendert **keine** Backend-Endpoints und baut **nur** den Frontend-Consumer.
- **SSE-Producer/Event-Emission backend-seitig** (Single-Producer `telemetry`, Topic-Befuellung inkl. `kpi`- und `failure_corpus`-Wire-Schema-Erstdefinition) — Owner ist die Event-Story **AG3-081** (Event-Vollausbau); siehe AK-Block zum offenen `kpi`/`failure_corpus`-Topic.
- **`kpi`-Live-Patch auf Event-Ebene** — **zurueckgestellt**, solange das `kpi`-Topic-Wire-Schema offen ist (FK-91 §91.8.3 Z.515: `kpi` = „offen (folgt mit der Analytics-Hauptsicht)"). AG3-094 abonniert das `kpi`-Topic und **re-fetcht** bei einem `kpi`-Event den Initial-GET der Analytics-Sicht (re-sync), patcht aber **nicht** feldgranular aus dem Event-Payload. Sobald AG3-081 das `kpi`-Wire-Schema + Formal-Spec liefert, kann feldgranulares Patching nachgeschoben werden — das ist **nicht** Scope dieser Story.
- **`failure_corpus`-Live-Patch auf Event-Ebene** — **zurueckgestellt**, solange das `failure_corpus`-Topic-Wire-Schema offen ist (FK-91 §91.8.3 Z.517: `failure_corpus` = „offen (folgt mit dem Failure-Corpus-Browser)"). AG3-094 abonniert `failure_corpus` und **re-fetcht** bei einem Event den Analytics-Funnel (Initial-GET-Re-Sync), patcht aber **nicht** feldgranular aus dem Event-Payload. Owner des Wire-Schemas + des Failure-Corpus-Vollausbaus ist **AG3-078** (Failure-Corpus Stufe 2/3); feldgranulares Patching folgt mit dessen Browser-Wire-Schema.
- **App-Shell + Analytics-Sicht-Struktur/Slice-Schnitt** — **AG3-093** (`depends_on`). Hier nur Charts + Live-Hooks innerhalb des bestehenden Slices.
- **Hub-SSE-Stream `/v1/events/hub`** — bewusst zurueckgestellt (FK-91 §91.8.4 Z.520; Hub-View Prototyp-Stand).
- **Design-Token-Owner/Conformance** — **AG3-092**.
- **Projekt-/Story-uebergreifender Cross-Entity-Vergleich** (mehrere Projekte/Stories nebeneinander) — **nicht** Scope; FK-63 §63.3.3 fordert „Zwei Zeitraeume nebeneinander", keinen Cross-Entity-Vergleich. Falls spaeter gewuenscht: eigene Folge-Story.
- **Eigenes Failure-Corpus-Browser-View** — **AG3-078** (Failure-Corpus Stufe 2/3). AG3-094 zeigt `failure_corpus` nur als **Funnel in Analytics** (FK-72 §72.11.3 Z.258: „kein eigenes Browser-View in v1").

## 3. Akzeptanzkriterien

1. Analytics-Overview + Timeseries rendern mit **ECharts** funktional 1:1 zum Prototyp: Aggregat-Karten avg/min/max/p90; Multi-Series-Linien mit Preset- und Custom-Zeitraum, Metrik-Overlay, Min/Max-Band-Toggle, `dataZoom` (inside + slider), Cross-`axisPointer`-Tooltip mit Band-Helper-Filter. Komponententest pro Feature (Karten-Werte, Overlay-Toggle, Band-Toggle, Zeitraumwechsel, Tooltip-Formatter blendet Band-Helper-Serien aus).
2. Chart-Daten stammen aus den finalen AG3-084-KPI-Endpoints (`/v1/.../kpi/*`), **nicht** aus clientseitiger Synthese; ein Test belegt, dass die Sicht gegen einen gemockten `/v1/.../kpi/*`-Response rendert und `selectKpiDailySeries`/`selectProjectKpiStats` nicht mehr die Produktiv-Datenquelle sind.
3. SSE: jede Live-Sicht macht beim Oeffnen Initial-GET **und** `EventSource`-Subscribe mit korrektem `?topics=`-Filter (Test pro Sicht, Topic-Set strikt nach FK-72 §72.5 ↔ FK-91 §91.8.3): **Analytics** → `kpi,telemetry,failure_corpus`; **Kanban/Board** → `stories,phases`; **Graph** (inkl. Sub-Tabs `graph`/`ready`/`limits`) → `planning` (**nicht** `stories,phases`; `dependency_graph_changed` ist ein `planning`-Topic, FK-91 §91.8.3 Z.516).
4. Lossy-Re-Sync: simulierter `EventSource`-(Re-)Connect loest einen frischen Initial-GET aus; es gibt **keinen** Frontend-REST-Polling-Loop (Test: kein periodisches Refetch ohne Event).
5. Relevantes Event aktualisiert die betroffene Sicht (Tests):
   - eingespeistes `stories`-Event aktualisiert Board/Counters (Kanban);
   - eingespeistes `planning`-Event aktualisiert die Graph-Sicht: `dependency_graph_changed` aktualisiert den Dependency-Graph-Sub-Tab; `execution_input_changed`/`limits_changed` aktualisieren `ready`/`limits` (FK-91 §91.8.3 Z.516);
   - eingespeistes **`kpi`**-Event auf der Analytics-Sicht loest einen **Re-Fetch** (Initial-GET-Re-Sync) aus, sodass KPI-Karten/Charts den neuen `/v1/.../kpi/*`-Stand zeigen (Re-Sync, **kein** feldgranulares Event-Patching — siehe Out of Scope);
   - eingespeistes **`failure_corpus`**-Event auf der Analytics-Sicht loest einen **Re-Fetch** (Initial-GET-Re-Sync) des Funnels aus (Re-Sync, **kein** feldgranulares Event-Patching, da Wire-Schema offen — siehe Out of Scope);
   - eingespeistes **`telemetry`**-Event (Mode-Lock-Projektion) aktualisiert den davon abhaengigen UI-Anteil.
6. Reconnect/Offline (FK-72 §72.14.6): SSE-Abbruch → automatischer `EventSource`-Reconnect + Re-Sync; Total-Offline → mutierende UI disabled + „Verbindung verloren"-Indikator (Interaktions-Assertion).
7. Vergleichs-/Filter-UI gebunden an den AG3-084-`KpiQueryFilter`-Vertrag: Custom-Zeitraum (→ `from`/`to`), Entity-Filter **Guards** (→ `guard`) und **Pools** (→ `pool`), Story-Filter **Story-Typ** (→ `story_type`) und **Story-Groesse** (→ `story_size`) sowie Zwei-Zeitraum-Vergleich (→ `comparison_period`) werden als serverseitige Query-Parameter an die `/v1/.../kpi/*`-Endpoints (AG3-084) durchgereicht; ein Test belegt, dass die UI-Auswahl exakt diese Query-Parameter erzeugt und **nicht** clientseitig nachgerechnet wird. **Template-Entity-Filter und Pipeline-Modus-Story-Filter sind nicht enthalten** (kein AG3-084-/FK-63-§63.4.2-Query-Parameter; an den Backend-Owner geroutet, siehe 2.2); es wird **kein** toter UI-Schalter dafuer gebaut.
8. Chart-Farben kommen aus Design-Tokens (AG3-092); keine losen Hex ausserhalb der Token-Definition (Token-Conformance gruen).
9. **Pflichtbefehle gruen** (genaue Befehle, alle aus dem Repo-Root `T:/codebase/claude-agentkit3`):
   - Python: `.venv\Scripts\python -m pytest tests/unit -n0`, `.venv\Scripts\python -m pytest tests/integration -n0`, `.venv\Scripts\python -m pytest tests/contract -n0` (jeweils in Chunks bei Bedarf).
   - `.venv\Scripts\python -m mypy src` und `.venv\Scripts\python -m mypy src --platform linux`.
   - `.venv\Scripts\python -m ruff check src tests`.
   - Konzept-Gates (exakte Befehle, AGENTS.md §„Konzept-Aenderungen" + `.githooks/pre-commit`): `.venv\Scripts\python scripts/ci/check_concept_frontmatter.py` und `.venv\Scripts\python scripts/ci/compile_formal_specs.py` (beide gruen). Diese Story aendert keine `concept/`-Dateien; die Gates laufen dennoch gruen.
   - Coverage ≥ 85 %: `.venv\Scripts\python -m pytest --cov=agentkit --cov-fail-under=85`.
   - Pflicht-Remote-Gates (AGENTS.md): `scripts/ci/check_remote_gates.ps1` gruen (Jenkins `http://localhost:9900/job/claude-agentkit3/` + Sonar `http://192.168.0.20:9901`; Sonar strikt `violations=0`, `critical_violations=0`, `security_hotspots=0`).
   - Frontend-TS (Arbeitsverzeichnis = der mit AG3-093 etablierte Frontend-App-Ordner, Package-Manager wie dort festgelegt; im Prototyp `frontend/prototype` ist es `npm`): `npm run build`, `npm run test`, `npm run lint` gruen.

## 4. Definition of Done

- AK 1–9 erfuellt; giftige Codex-Review PASS; (Implementierung/Commit erst nach Execution-Plan-Freigabe — diese Story wird zunaechst nur autorisiert/reviewt).

## 5. Guardrail-Referenzen

- **SINGLE SOURCE OF TRUTH:** KPI-Daten aus den Backend-Endpoints (AG3-084), nicht aus einer clientseitigen Zweitberechnung; SSE-Single-Producer `telemetry` (FK-72 §72.12.3 Z.294). Filter/Vergleich serverseitig via Query-Parameter, kein zweites clientseitiges Aggregat.
- **FAIL CLOSED:** SSE ist lossy → Pflicht-Re-Sync per Initial-GET (FK-72 §72.12.4 Z.306); Offline → mutierende UI disabled, kein optimistisches Schreiben ins Leere (FK-72 §72.14.6 Z.503).
- **KEIN FRONTEND-POLLING:** ausschliesslich Initial-GET + `EventSource`-Subscribe; kein Frontend-REST-Polling-Loop (FK-72 §72.12.1 Z.281). Der serverseitige Event-Store-Poll im Backend-SSE-Stream ist Sache von AG3-003 und **nicht** Gegenstand dieser Story.
- **TYPISIERT STATT STRINGS:** Topics/Event-Typen als typisierte Sets, nicht als freie Strings.
- **KEIN UI-BC:** Analytics ist `kpi_analytics`-Composer (FK-72 §72.6 Z.136), Live-Hooks sind App-Shell-/Slice-Komposition (FK-72 §72.3 Z.56).
- **ARCH-55:** Topic-Namen, Event-Felder, Endpunkt-Pfade, Enum-/Set-Werte englisch; deutsche UI-Label sind Lokalisierung.

## 6. Hinweise fuer den Sub-Agent

- Read T:/codebase/claude-agentkit3/CLAUDE.md first — all project rules apply to you.
- Normative funktionale Soll-Quelle (Concept-as-Code): `frontend/prototype/src/components/AnalyticsView.tsx` (Overview + Timeseries, Presets/Overlay/Band/Zoom/Tooltip) und die Selektoren `selectProjectKpiStats`/`selectKpiDailySeries` (`frontend/prototype/src/store/storySelectors.ts:590`/`:652`) als **funktionale** Vorlage — die Synthese-Logik beschreibt, was das Backend (AG3-084) liefern muss; sie wird **nicht** als Produktiv-Datenquelle uebernommen.
- Chart-Lib ist mit dieser Story **entschieden: ECharts** (Begruendung im Scope 2.1.2, Anker FK-72 §72.13 Z.383-385). Nicht erneut zur Diskussion stellen; der Index-/FK-Prosa-Nachzug auf ECharts ist an AG3-103 delegiert.
- SSE-Mechanik: FK-72 §72.12 (Pattern, Z.270-312) + FK-91 §91.8.3 (Topic-Katalog, Z.506-518) sind normativ. Browser-`EventSource` reconnectet selbst; das Frontend muss nur den Initial-GET-Re-Sync ausloesen. Der Backend-Endpoint existiert bereits (AG3-003, `completed`) — **nicht** anfassen.
- Topic-Sets je Sicht strikt aus FK-72 §72.5 (Owner-BC) ableiten, nicht raten: **Graph** (Owner `execution_planning`) hoert auf `planning` (inkl. `dependency_graph_changed`), **nicht** auf `stories,phases`; **Kanban/Board** (Owner `story_context_manager`) hoert auf `stories,phases`; **Analytics** (`kpi_analytics`-Composer) auf `kpi,telemetry,failure_corpus`.
- Offene Wire-Schemas (`kpi` FK-91 §91.8.3 Z.515, `failure_corpus` Z.517): in dieser Story **nur Re-Fetch-on-event** (Re-Sync), kein feldgranulares Patchen aus dem Event-Payload. Feldgranulares `kpi`-Patching folgt mit AG3-081; feldgranulares `failure_corpus`-Patching mit AG3-078.
- KPI-Endpoint-Pfad: final `/v1/.../kpi/*` (AG3-084 AC1), **nicht** `/api/kpi/*`. **Keinen** `/api/live/stories`-Endpoint konsumieren — den liefert AG3-084 bewusst nicht (an AG3-081 geroutet); Board-Aktualitaet kommt aus den Story-Read-Models + `stories`/`phases`.
- Anknuepfung Frontend: diese Story setzt auf den BC-Slices/der Shell aus AG3-093 auf; Charts gehoeren in den `kpi_analytics`-Slice, der Live-Subscribe als Shell-/Slice-Hook.
- AK2 NICHT veraendern. `.mcp.json` NICHT anfassen. **Kein Commit** ohne expliziten Auftrag.
- „done" nur mit Beleg: Diff, gruene Pflichtbefehle, Frontend-Build/-Tests, SSE-Re-Sync-/Event-Patch-Tests.

## 7. Offene fachliche Punkte (an Owner geroutet, nicht in dieser Story entschieden)

- **`kpi`-Topic-Wire-Schema:** FK-91 §91.8.3 (Z.515) fuehrt `kpi` als „offen (folgt mit der Analytics-Hauptsicht)". Das konkrete Event-Schema legen **AG3-081 + die Formal-Spec** fest. AG3-094 ist gegen diese Offenheit robust geschnitten (Re-Fetch statt feldgranulares Patchen) und braucht das Schema **nicht** vorab.
- **`failure_corpus`-Topic-Wire-Schema:** FK-91 §91.8.3 (Z.517) fuehrt `failure_corpus` als „offen (folgt mit dem Failure-Corpus-Browser)". Owner ist **AG3-078** (Failure-Corpus Stufe 2/3). AG3-094 ist auch hier robust geschnitten (Re-Fetch des Funnels statt feldgranulares Patchen).
- **Index-/FK-Prosa-Nachzug Chart-Lib (Chart.js → ECharts):** der Master-Index nennt „Chart.js" (`_STORY_INDEX.md:119`) und FK-63 §63.x (Z.85) beschreibt das alte stdlib-QA-Dashboard mit Chart.js. Der Soll-Stand ist ECharts (Prototyp = normativ). Der reine **Doc-Nachzug** ist **AG3-103** (doc-only) — kein Code-Anteil dieser Story.
- **FK-91↔FK-72 Planning-Pfad-/Topic-Konsistenz (Graph = `planning`):** Die Zuordnung „Graph live ueber `planning`" ist durch FK-72 §72.5 (Z.130-133/143-144) und FK-91 §91.8.3 (Z.516, `dependency_graph_changed` unter `planning`) bereits eindeutig; sollte FK-Prosa anderswo davon abweichen, ist der **doc-only-Nachzug AG3-103** (Scope laut `_STORY_INDEX.md:144` ausdruecklich „FK-91↔FK-72 Planning-Pfade") zustaendig — kein Code-Anteil dieser Story.
- **AG3-084-Filter-Query-Parameter-Vertrag:** die genauen Query-Parameter fuer Zeitraum / Guard-/Pool-/Story-Typ-/Story-Groesse-Filter / Zwei-Zeitraum-Vergleich definiert **AG3-084** (typisierter `KpiQueryFilter`). AG3-094 reicht sie nur durch; bei Abweichung der Parameter-Form ist der Vertrag mit AG3-084 abzustimmen, nicht clientseitig zu kompensieren.
- **Template-Entity-Filter / Pipeline-Modus-Story-Filter (FK-63 §63.3.3-UI-Wuensche ohne Backend-Vertrag):** FK-63 §63.4.2 (Z.221-227) haelt Template-Analytik als JSON-Feld in `fact_pool_period` „nicht ueber einen eigenen Filter ansteuerbar" und fuehrt **keinen** `pipeline_mode`-Query-Parameter; AG3-084 bindet beide nicht. Eine eigene Template-Fact-Tabelle ist laut FK-63 §63.4.2 ein „INVENTAR-Punkt fuer spaetere Iterationen". Diese beiden Filter sind daher **erst** baubar, wenn der Backend-Owner (**AG3-084** bzw. eine Folge-Story mit Template-Fact-Tabelle) den Query-Vertrag erweitert; AG3-094 baut sie nicht und faelscht keinen clientseitigen Ersatz vor.

---

## Globale Akzeptanzkriterien (verbindlich)

Zusaetzlich zu den obigen Akzeptanzkriterien gelten die **globalen Akzeptanzkriterien**
aus `stories/_GLOBAL_ACCEPTANCE.md` (Single Source of Truth):

- **GAC-1:** `scripts/ci/check_architecture_conformance.py` laeuft mit **0 Errors**
  (Exit 0, fail-closed) — `PYTHONPATH=src .venv\Scripts\python scripts/ci/check_architecture_conformance.py`.
- **GAC-2:** Die Architektur-Guardrails `guardrails/architecture-guardrails.md`
  (ARCH-NN) werden eingehalten; Konflikt = hart stoppen und melden.
