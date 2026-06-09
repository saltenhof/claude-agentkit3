# AG3-090: BFF-Topologie-Vollausbau (`control_plane_http` + 8 fehlende BC-`http/`-Module)

**Typ:** Implementation
**Groesse:** L
**Bounded Context:** `frontend`/BFF-Topologie (cross-cutting, FK-72) — die serverseitige Web-Schicht (ein Prozess, BC-aligned Routes-Module). Andockpunkt fuer alle Frontend-Sichten (AG3-093/094/105) und die API-Read-Models (AG3-091).
**Quell-Konzepte (autoritativ):**
- `FK-72 §72.8` — BFF-Topologie: **ein** Server-Prozess, pro BC ein Routes-Modul; `control_plane_http` hostet App, Auth, Tenant-Scope-Middleware, Router-Registry.
- `FK-72 §72.8.1` — URL-Konvention: projekt-skopiert `/v1/projects/{project_key}/<bc>/<resource>`; `project_key` ist Pflicht-Pfadparameter und wird in der Middleware validiert (Projekt existiert/nicht archiviert); nicht-projektbezogene Endpunkte unter `/v1/<bc>/<resource>`.
- `FK-72 §72.8.2` — Modul-Aufteilung: namentlich `agentkit/control_plane_http/` + je `http/`-Modul fuer `pipeline_engine`, `verify_system`, `governance`, `closure`, `artifacts`, `kpi_analytics`, `failure_corpus`, `requirements_coverage` (die acht fehlenden); bestehende: `project_management`, `story_context_manager`, `execution_planning`, `telemetry`, `concept_catalog`, `multi_llm_hub`. Hinweis: `telemetry/http/` existiert bereits (AG3-003, `completed`) und ist daher **nicht** Teil der „acht fehlenden".

> **ENTSCHIEDEN — kanonischer KPI-Routen-Root = Singular `/kpi/{dimension}` (PO-Entscheidung 2026-06-08).** Die fuenf KPI-Read-Endpoints liegen unter `/v1/projects/{project_key}/kpi/{stories|guards|pools|pipeline|corpus}` (Singular + Sub-Resource). Das deckt sich mit AG3-084 AC1 (`story.md:54`) und AG3-094 (`story.md:49`); FK-63 nutzt dieselbe Singular-Form. Die einzige abweichende Quelle ist die FK-72-§72.8.2-Prosa (`72_frontend_architektur.md:222`, Modul-Mount `/kpis`) — diese wird per doc-only-Nachzug **AG3-103** auf `/kpi` angeglichen (FK-Prosa folgt der Entscheidung, FIX THE MODEL). AG3-090 mountet das `kpi_analytics/http/`-Modul daher unter `/v1/projects/{key}/kpi` und macht die Endpoints erreichbar (kein offener Root mehr).

---

## 1. Kontext / Ist-Zustand (belegt)

Es existiert **ein** Routing-Aggregator, aber **nicht** unter dem normativen Namen `control_plane_http`, und die projekt-skopierte URL-Konvention sowie die Tenant-Scope-Middleware fehlen:

- Aggregator/Transport: `src/agentkit/control_plane/http.py` — `ControlPlaneApplication.handle_request(...)` dispatcht GET/POST/PUT/PATCH/DELETE an die vorhandenen BC-Routes (`:185`-`:483`). Das ist faktisch die App/Router-Registry, liegt aber im Paket `control_plane`, nicht in einem dedizierten `control_plane_http`-Namespace (FK-72 §72.8.2).
- Vorhandene BC-`http/`-Module (Glob `src/agentkit/**/http/`): `auth`, `concept_catalog`, `execution_planning`, `multi_llm_hub`, `project_management`, `story_context_manager`, `telemetry`. Es fehlen **acht**: `pipeline_engine`, `verify_system`, `governance`, `closure`, `artifacts`, `kpi_analytics`, `failure_corpus`, `requirements_coverage`.
- URL-Konvention: Bestand nutzt **nicht** das projekt-skopierte Schema. Beispiele aus `control_plane/http.py`: `_STORY_PATH_PATTERN = ^/v1/stories/(?P<story_id>[^/]+)$` (`:70`), `/v1/stories` mit `project_key` als **Query**-Parameter (`:296`, `:692`-`:694`), `/v1/dashboard/board` (`:298`). FK-72 §72.8.1 verlangt `project_key` als **Pfad**-Segment (`/v1/projects/{project_key}/...`).
- Tenant-Scope-Middleware: existiert nicht. Es gibt nur die Auth-Middleware (`AuthMiddleware`, `control_plane/http.py:202`-`:210`). Eine Komponente, die `project_key` aus dem Pfad zieht, gegen die Projekt-Existenz/Archivierung prueft und fail-closed blockt, fehlt.

Die Story baut also auf einem **vorhandenen** Transport/Router auf (kein Neubau der HTTP-Maschinerie), zieht aber Namespace, URL-Konvention, Middleware und die acht fehlenden BC-Routes-Module nach.

## 2. Scope

### 2.1 In Scope
1. **Namespace `control_plane_http`** (FK-72 §72.8.2), **Migrationsvariante verbindlich entschieden:** Die App-/Auth-/Tenant-Scope-/Router-Registry-Schicht wird unter `src/agentkit/control_plane_http/` der **neue Import-Owner** (kanonischer Move des `ControlPlaneApplication`-Transports aus `control_plane/http.py` nach `control_plane_http/`). `control_plane` behaelt **genau einen** Compat-Re-Export auf die migrierten Symbole, damit kein Import bricht; es entsteht **keine** zweite App-/Transport-Definition (FIX-THE-MODEL / SINGLE SOURCE OF TRUTH: **eine** App-Schicht). Alle internen Importe der App-Schicht (Bootstrap/Composition-Root, Tests) werden vollstaendig auf den neuen Namespace umgestellt — **kein** halber Uebergang, kein Parallelbetrieb alter und neuer Pfade. Begruendung der Variante: Es existiert bereits genau **ein** Transport (`control_plane/http.py:185`), der nur fachlich falsch verortet ist; eine reine „Web-Abspaltung neben `control_plane`" wuerde zwei Transport-Heimaten erzeugen (verboten). Der kanonische Move + Compat-Re-Export ist daher die einzige Variante, die FK-72 §72.8.2 und FIX-THE-MODEL gleichzeitig erfuellt.
2. **Projekt-skopierte URL-Konvention** (FK-72 §72.8.1): kanonische Form `/v1/projects/{project_key}/<bc>/<resource>`. `project_key` ist Pflicht-Pfadparameter **aller** projektbezogenen Endpunkte. Die **vollstaendige Altpfad-Inventur** ist Teil dieser Story: alle heutigen projektbezogenen Pfade des Bestand-Transports werden auf die Pfad-Form gehoben — Collection, Detail, Mutationen und Sub-Ressourcen. Belegte Altpfade (`control_plane/http.py`):
   - `/v1/stories` (Query-`project_key`, `:296`/`:692`) — Collection + `POST`-Mutation.
   - `/v1/stories/{story_id}` und Sub-Pfade (`_STORY_PATH_PATTERN` `:70`; Detail/`approve`/`reject`/`cancel`/`fields`/`fields/{key}` in `story_context_manager/http/routes.py:49`-`:57`) — Detail, Mutationen, Fields.
   - `/v1/dashboard/board`, `/v1/dashboard/story-metrics` (`:298`/`:300`).
   - `/v1/story-runs/{run_id}/phases/{phase}/{action}` (`_PHASE_PATH_PATTERN` `:61`) und `/v1/story-runs/{run_id}/closure/complete` (`_CLOSURE_PATH_PATTERN` `:64`) — Phase-/Closure-Pfade.
   Diese Hebung erfolgt vollstaendig; **kein** projektbezogener Altpfad bleibt als impliziter Fallthrough erreichbar. Soll ein konkreter Altpfad bewusst als Legacy weiterleben, ist das eine **explizite** Legacy-Entscheidung (dokumentiert, nicht still). Nicht-projektbezogene Endpunkte (`/v1/concepts`, `/v1/hub`, `/v1/events/hub`) bleiben ohne Projekt-Praefix.

   **Klarstellung `/v1/projects` (kein projektneutraler Sammeltopf):** Die Projekt-Verwaltungs-Ressourcen — `GET /v1/projects` (Liste), `POST /v1/projects` (Anlegen), `GET /v1/projects/{key}` (Detail), `PATCH /v1/projects/{key}` (Konfig-Update), `POST /v1/projects/{key}/archive` (FK-73 §73.3, `73_project_management.md:73`-`:77`) — sind die **`project_management`-Sonderoberflaeche**. Detail/Patch/Archive tragen den `project_key` bereits als erstes Pfadsegment; sie bekommen **keinen** doppelten Projekt-Praefix (`/v1/projects/{key}/projects/...` waere falsch) und fallen daher **nicht** unter die `<bc>`-Mittel-Schicht-Konvention, gehoeren aber sehr wohl zum Project-Management (nicht „projektneutral"). Liste/Anlegen sind projektneutral.
3. **Tenant-Scope-Middleware** in `control_plane_http`: extrahiert `project_key` aus dem Pfad, validiert gegen Projekt-Existenz/Archivierungsstatus (project_management), blockt fail-closed mit strukturierter Fehlerantwort (404 fuer unbekanntes Projekt; 403/`forbidden` fuer archiviertes Projekt bei Mutationen). Lese- und Schreibpfade filtern ueber `project_key` (FK-73 §73.5: `project_key` durchzieht alle BC-Tabellen als Filter-Spalte; Durchsetzung im `control_plane_http`).
4. **Die acht fehlenden BC-`http/`-Routes-Module** als duenne Adapter (CLAUDE.md: `integrations/`/Adapter bleiben duenn; keine Fachlogik im http-Layer), je mit `handle_get/handle_post/...`-Signatur analog den bestehenden Modulen (`project_management/http/routes.py`, `story_context_manager/http/routes.py`):
   - `pipeline_engine/http/` -> `/v1/projects/{key}/phases`
   - `verify_system/http/` -> `/v1/projects/{key}/verify`
   - `governance/http/` -> `/v1/projects/{key}/governance`
   - `closure/http/` -> `/v1/projects/{key}/closure`
   - `artifacts/http/` -> `/v1/projects/{key}/artifacts`
   - `kpi_analytics/http/` -> `/v1/projects/{key}/kpi` (kanonischer Root **entschieden**, Singular, PO 2026-06-08; Endpoints `/kpi/{stories|guards|pools|pipeline|corpus}` deckungsgleich mit AG3-084/AG3-094). Modul registriert + Root erreichbar; die KPI-Endpoint-Fachlogik bleibt AG3-084 (§2.2).
   - `failure_corpus/http/` -> `/v1/projects/{key}/failure-corpus`
   - `requirements_coverage/http/` -> `/v1/projects/{key}/coverage` (inkl. `/coverage/stories/{story_id}/are-evidence`, FK-40 §40.10)
   Jedes Modul wird in der Router-Registry des `control_plane_http` registriert; die Routen-Skelette sind real verdrahtet (kein 501-Stub als „done"). Wo das konsumierende Service noch fehlt, liefert der Adapter eine strukturierte 503-`*_unavailable`-Antwort analog `_backend_requirement_response` (`control_plane/http.py:982`), **kein** stilles Leer-OK.
5. **Korrelations-/Fehlerkontrakt erhalten**: `X-Correlation-Id`, `ApiErrorResponse`-Form, fail-closed-Defaults aus dem Bestand bleiben fuer alle neuen Routen gueltig.

### 2.2 Out of Scope (mit Owner)
- **Konkrete Read-Model-/Execution-Input-Payloads** (`mode-lock`, `stories/counters`, `stories/{id}/flow`, `execution-input/snapshot|next`, `coverage/...`) — **AG3-091** (baut auf dieser Topologie auf; `depends_on`). Diese Story liefert nur die Module/Routing-Huelle + Middleware.
- **SSE-Backend-Endpoint** `/v1/projects/{key}/events` (serverseitiger `?topics=`-Filter, Lossy, Heartbeat, Cross-Project-Isolation) — **AG3-003** (`completed`). Er existiert **bereits** und ist im `telemetry`-BC verortet: `telemetry/http/routes.py:22` (Pfad-Pattern `^/v1/projects/(?P<project_key>[^/]+)/events$`), `:48` (`handle_get`), registriert ueber den Bestand-Transport (`control_plane/http.py:57` importiert `TelemetryRoutes`). AG3-090 baut **keinen** SSE-Endpoint und faechert ihn auch nicht neu auf. Diese Story sichert ausschliesslich, dass der bestehende SSE-Pfad mit der neuen Tenant-Scope-Middleware **kompatibel** bleibt (das `project_key`-Pfadsegment des Events-Pfads durchlaeuft dieselbe Existenz-/Archiv-Validierung; siehe §2.1.3 + §3 AC8) — kein Bruch des AG3-003-Vertrags.
- **SSE-Producer / Event-Emission + offene Topic-Wire-Schemas** (`kpi`/`failure_corpus`) — **AG3-081** (Event-Vollausbau; Single-Producer `telemetry`, FK-72 §72.12.3). Weder Endpoint noch Producer sind AG3-090.
- **Frontend-SSE-Consumer** (Browser-`EventSource`, Initial-GET-Re-Sync, Topic-Sets pro Sicht) — **AG3-094** (FK-72 §72.12). AG3-094 baut **nur** den Frontend-Consumer und aendert keine Backend-Endpoints.
- **Design-Token-Endpoint/`get_design_tokens`** — **AG3-092**; FK-64 §64.2 stellt klar: `DesignSystem` betreibt **keinen** eigenen HTTP-Endpunkt, die Boundary-Control liegt bei `control_plane` — dieser Schnitt ist hier zu respektieren.
- **KPI-Endpoint-Fachlogik** (KPI-Rollups, `KpiQueryFilter`, Fact-Reads) — **AG3-084** (Dashboard-Backend); hier nur das `kpi_analytics/http/`-Modul-Skelett + Registrierung.
- **FK-72-§72.8.2-Prosa-Nachzug** (`/kpis` -> `/kpi`, FK-72↔FK-63-Pfad-Konsistenz) — doc-only **AG3-103** (`_STORY_INDEX.md:144`). Der kanonische Root selbst ist entschieden (Singular `/kpi/*`, PO 2026-06-08, siehe Kopf); AG3-090 setzt ihn erreichbar um, der reine Konzept-Text-Abgleich bleibt AG3-103.
- **Frontend-TS-App** (App-Shell/Views) — **AG3-093**.

## 3. Akzeptanzkriterien
1. Namespace `control_plane_http` existiert und ist der **Import-Owner** von App + Auth + Tenant-Scope-Middleware + Router-Registry; `control_plane` haelt nur einen Compat-Re-Export, es gibt **keine** zweite parallele App-/Transport-Definition (Test: Import/Smoke ueber den neuen Namespace; alte Importe loesen via Re-Export dieselbe Klasse auf, nicht eine duplizierte; Bootstrap/Composition-Root importieren aus `control_plane_http`).
2. **Vollstaendige Migration aller projektbezogenen Altpfade** auf die Pfad-`project_key`-Form (FK-72 §72.8.1): Collection, Detail, Mutationen, Fields, Phase- und Closure-Pfade sowie die Dashboard-Pfade werden gehoben — je ein Routing-Test, dass die neue Pfad-Form aufloest und keine projektbezogene Query-`project_key`-Form als impliziter Fallthrough erreichbar bleibt. Abgedeckt mindestens: `/v1/stories` (Collection + `POST`), `/v1/stories/{id}` + `approve`/`reject`/`cancel`/`fields`/`fields/{key}` (Detail/Mutationen/Fields), `/v1/dashboard/board` + `/v1/dashboard/story-metrics`, `/v1/story-runs/{run_id}/phases/{phase}/{action}` und `/v1/story-runs/{run_id}/closure/complete`. Jeder bewusst als Legacy belassene Altpfad ist **explizit** als Legacy-Entscheidung dokumentiert (kein stiller Fallthrough).
3. Tenant-Scope-Middleware: unbekanntes `project_key` -> 404; archiviertes Projekt bei Mutation -> 403/`forbidden`; gueltiges Projekt -> Durchlauf (drei Tests, inkl. Negativpfad).
4. Alle acht BC-`http/`-Module existieren, sind in der Router-Registry registriert und auf den FK-72-§72.8.2-Pfaden erreichbar (Test pro Modul: Route trifft das Modul, nicht den 404-Fallthrough). Fuer `kpi_analytics/http/` ist der kanonische Root **entschieden** (Singular `/v1/projects/{key}/kpi`, PO 2026-06-08); der Test belegt, dass das Modul unter `/kpi` erreichbar ist (deckungsgleich mit AG3-084/AG3-094).
5. Fehlt das konsumierende Backend eines Moduls, liefert der Adapter eine strukturierte 503-`*_unavailable` (kein 200-Leer-OK, kein nackter 500) — Test mit nicht verfuegbarem Backend.
6. `requirements_coverage/http/` bedient `/coverage/stories/{story_id}/are-evidence` (read-only) gemaess FK-40 §40.10 (Route trifft, Methode GET).
7. `X-Correlation-Id` und `ApiErrorResponse`-Form gelten unveraendert fuer alle neuen Routen (Test: Fehlerantwort traegt Correlation-Id + `error_code`).
8. **Bestehender SSE-Pfad bleibt mit der Tenant-Scope-Middleware kompatibel:** der von AG3-003 (`completed`) gebaute Endpoint `/v1/projects/{key}/events` (`telemetry/http/routes.py:22`/`:48`) durchlaeuft die neue Middleware mit demselben `project_key`-Pfadsegment ohne Bruch (Test: gueltiges Projekt -> SSE-Pfad erreichbar/200; unbekanntes Projekt -> 404). AG3-090 aendert den SSE-Endpoint selbst **nicht**.
9. **Pflichtbefehle + Remote-Gates gruen** (alle aus dem Repo-Root `T:/codebase/claude-agentkit3`):
   - Python: `.venv\Scripts\python -m pytest tests/unit -n0`, `.venv\Scripts\python -m pytest tests/integration -n0`, `.venv\Scripts\python -m pytest tests/contract -n0` (in Chunks bei Bedarf).
   - `.venv\Scripts\python -m mypy src` und `.venv\Scripts\python -m mypy src --platform linux`.
   - `.venv\Scripts\python -m ruff check src tests`.
   - Konzept-Gates: `.venv\Scripts\python scripts/ci/check_concept_frontmatter.py` und `.venv\Scripts\python scripts/ci/compile_formal_specs.py` (beide gruen; diese Story aendert keine `concept/`-Dateien).
   - Coverage >= 85 %: `.venv\Scripts\python -m pytest --cov=agentkit --cov-fail-under=85`.
   - **Pflicht-Remote-Gates (AGENTS.md):** `scripts/ci/check_remote_gates.ps1` gruen (Jenkins `http://localhost:9900/job/claude-agentkit3/` + Sonar `http://192.168.0.20:9901`; Sonar strikt `violations=0`, `critical_violations=0`, `security_hotspots=0`).

## 4. Definition of Done
- AK 1–9 erfuellt; giftige Codex-Review PASS; der KPI-Routen-Root ist entschieden (Singular `/kpi/*`, PO 2026-06-08) und so umgesetzt; (Implementierung/Commit erst nach Execution-Plan-Freigabe).

## 5. Guardrail-Referenzen
- **FIX THE MODEL / SINGLE SOURCE OF TRUTH:** genau **eine** App-/Transport-Schicht (`control_plane_http`); kein zweiter paralleler Router. `project_key`-Filterung ist die eine durchgesetzte Tenant-Grenze, kein per-Endpoint-Flickwerk.
- **FAIL CLOSED:** unbekanntes/archiviertes Projekt blockt; fehlendes Backend -> strukturierte 503, nie stilles Leer-OK.
- **KEINE FACHLOGIK IN ADAPTERN:** `http/`-Module bleiben duenne Adapter; Geschaeftslogik bleibt in den BC-Services.
- **TYPISIERT STATT STRINGS:** Routen-/Fehlerkontrakte typisiert (Pydantic-Responses), keine Ad-hoc-Dicts.
- **ARCH-55:** alle Pfadsegmente, Modulnamen, `error_code`-Werte, Bezeichner englisch.
- **ZERO DEBT:** keine 501-/TODO-Routen als „done"; jedes Modul ist real verdrahtet.

## 6. Hinweise fuer den Sub-Agent
- Read T:/codebase/claude-agentkit3/CLAUDE.md first — all project rules apply to you.
- Kritischer Anknuepfungspunkt: `src/agentkit/control_plane/http.py` ist die **vorhandene** App/Router-Registry — nutze sie als Basis, baue keine zweite. Bestehende BC-Routes-Module (`project_management/http/routes.py`, `story_context_manager/http/routes.py`) sind das Muster fuer die acht neuen.
- Spot-Check `src/agentkit/bootstrap/composition_root.py` (in der Arbeitskopie modifiziert) auf Importe der App-Schicht, falls der Namespace-Umzug Composition-Root beruehrt — sauber nachziehen, nicht parallel laufen lassen.
- Namespace-Variante ist **entschieden** (§2.1.1): kanonischer Move `control_plane/http.py` -> `control_plane_http/` mit **einem** Compat-Re-Export in `control_plane`; Importe vollstaendig umstellen. Nicht erneut zur Diskussion stellen — keine „Web-Abspaltung neben `control_plane`" (erzeugt zwei Transport-Heimaten).
- SSE-Endpoint **NICHT** bauen/aendern: `/v1/projects/{key}/events` ist AG3-003 (`completed`) und lebt in `telemetry/http/routes.py:22`/`:48`. AG3-090 sichert nur die Middleware-Kompatibilitaet dieses Pfads (AC8). Producer/Topics sind AG3-081, der Frontend-Consumer ist AG3-094.
- KPI-Pfad-Root ist **entschieden** (Singular `/v1/projects/{key}/kpi`, PO 2026-06-08, deckungsgleich AG3-084/AG3-094). Modul unter `/kpi` mounten + erreichbar machen. Der FK-72-§72.8.2-Prosa-Abgleich (`/kpis`->`/kpi`) ist doc-only AG3-103 — hier keine `concept/`-Datei anfassen.
- AK2 NICHT veraendern. `.mcp.json` NICHT anfassen. **Kein Commit** ohne expliziten Auftrag.
- „done" nur mit Beleg: Diff-Zusammenfassung, gruene Pflichtbefehle + Remote-Gates, Routing-Tests pro Modul + Middleware-Negativtests + SSE-Kompatibilitaetstest.

## 7. Fachliche Entscheidungen (geklaert)
- **Kanonischer KPI-Routen-Root — ENTSCHIEDEN (PO 2026-06-08): Singular `/v1/projects/{key}/kpi/{stories|guards|pools|pipeline|corpus}`.** Deckungsgleich mit AG3-084 AC1 (`story.md:54`), AG3-094 (`story.md:49`) und FK-63. AG3-090 setzt den Root erreichbar um. Der reine FK-72-§72.8.2-Prosa-Abgleich (`/kpis`->`/kpi`) bleibt doc-only **AG3-103** (`_STORY_INDEX.md:144`). Kein offener Cross-Story-Prerequisite mehr.

---

## Globale Akzeptanzkriterien (verbindlich)

Zusaetzlich zu den obigen Akzeptanzkriterien gelten die **globalen Akzeptanzkriterien**
aus `stories/_GLOBAL_ACCEPTANCE.md` (Single Source of Truth):

- **GAC-1:** `scripts/ci/check_architecture_conformance.py` laeuft mit **0 Errors**
  (Exit 0, fail-closed) — `PYTHONPATH=src .venv\Scripts\python scripts/ci/check_architecture_conformance.py`.
- **GAC-2:** Die Architektur-Guardrails `guardrails/architecture-guardrails.md`
  (ARCH-NN) werden eingehalten; Konflikt = hart stoppen und melden.
