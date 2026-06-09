# AG3-094 — Remediation R2 (Antwort auf review-r2.md)

**Scope der Remediation:** ausschliesslich `story.md` rewrite (+ Pruefung `status.yaml`). Kein Produktionscode, keine Tests, keine `concept/`-Dateien, keine fremden Story-Dateien beruehrt. Prototyp (`AnalyticsView.tsx`/`storySelectors.ts`) bleibt normative Soll-Quelle.

**Methodik:** Jeden Review-Befund gegen die realen Quellen gegengelesen — den lieferbaren Vertrag der Dependency-Story (`stories/AG3-084-.../story.md`), FK-72 §72.5/§72.12, FK-63 §63.3.3/§63.4.2, FK-91 §91.8.3, AGENTS.md/`.githooks/pre-commit` und `_STORY_INDEX.md`. Alle vier Must-Fix-ERRORs sind belegt eingetreten und wurden korrigiert; die WARNING ist in der Story gefixt.

---

## Must-Fix ERROR 1 — KPI-Endpoint/Filter-Vertrag gegen AG3-084/FK-72 nicht buildbar (`/api/*` statt `/v1/...`)

**Befund (bestaetigt):** AG3-094 hardcodierte `/api/kpi/*` und behandelte `/api/live/stories` als konsumierbaren Backend-Scope. Real liefert AG3-084 (AC1, `stories/AG3-084-.../story.md:54`) die fuenf KPI-Endpoints final unter `/v1/...` (gemappt analog `control_plane/http.py:298-301`); FK-72 §72.8.2 fuehrt durchgaengig `/v1/projects/{key}/...`. `/api/live/stories` ist in AG3-084 §2.2/AC8 **explizit out-of-scope** und an AG3-081 geroutet (kein Live-Read-Port: `telemetry/projection_accessor.py:56-70`).

**Resolution:**
- Alle konsumierten KPI-Pfade auf `GET /v1/.../kpi/{stories|guards|pools|pipeline|corpus}` umgestellt (Ist-Zustand Z.20, Scope 2.1.1, AC2, AC5, AC7, Out of Scope, Hinweise). `/api/kpi/*` bleibt nur noch als negativ markierte „NICHT konsumiert"-Klarstellung stehen.
- `/api/live/stories` aus dem konsumierten Scope entfernt; eigener Out-of-Scope-Eintrag mit Owner **AG3-081** + Begruendung (AG3-084 liefert ihn bewusst nicht). Board-Aktualitaet jetzt sauber ueber Story-Read-Models + `stories`/`phases`, nicht ueber eine Live-Stories-Sonderroute. AG3-084 nicht mehr faelschlich als `/api/live/stories`-Owner benannt (frueher Scope-OOS-Zeile + Producer-Zeile).

## Must-Fix ERROR 2 — FK-63-Filter-UI ueber den AG3-084-Vertrag hinaus (Templates + Pipeline-Modus)

**Befund (bestaetigt):** AG3-094 forderte Templates- und Pipeline-Modus-Pass-through-Filter. AG3-084s `KpiQueryFilter` bindet exakt `project_key/from/to/guard/pool/story_type/story_size` + `comparison_period` (AG3-084 §2.1.4/AC5). FK-63 §63.4.2 (Z.218-227) fuehrt **keinen** `pipeline_mode`-Query-Parameter und haelt Template-Analytik „nicht ueber einen eigenen Filter ansteuerbar" (JSON-Feld in `fact_pool_period`; eigene Fact-Tabelle = „INVENTAR-Punkt fuer spaetere Iterationen").

**Resolution:**
- Scope 2.1.5 + AC7 auf die buildbaren Dimensionen verengt: Custom-Zeitraum (`from`/`to`), Guard (`guard`), Pool (`pool`), Story-Typ (`story_type`), Story-Groesse (`story_size`), Vergleich (`comparison_period`) — je an die natuerliche Endpoint-Koernung gebunden.
- **Template-Entity-Filter** und **Pipeline-Modus-Story-Filter** explizit als „NICHT in dieser Story buildbar" markiert (kein Backend-Vertrag), **kein** toter UI-Schalter (FAIL-CLOSED). An den Backend-Owner geroutet: neuer Out-of-Scope-Hinweis + Offener-Punkt-Eintrag (Owner AG3-084 bzw. Folge-Story mit Template-Fact-Tabelle, FK-63 §63.4.2 Z.221-227). Es wird **nicht** behauptet, AG3-084 liefere diese Filter.

## Must-Fix ERROR 3 — Graph-Live-Routing mit falschem Topic-Set (`stories,phases` statt `planning`)

**Befund (bestaetigt):** AG3-094 koppelte „Board/Graph → `stories,phases`". FK-72 §72.5 (Z.130-133) ordnet Graph (inkl. Sub-Tabs `graph`/`ready`/`limits`) dem BC `execution_planning` zu; Z.143-144 „werden ueber denselben SSE-Topic `planning` live aktuell gehalten". FK-91 §91.8.3 (Z.516) fuehrt `dependency_graph_changed` unter `planning`. Graph haette ueber `stories,phases` nie live aktualisiert.

**Resolution:**
- Topic-Sets in Scope 2.1.3, AC3 und Hinweisen getrennt und korrigiert: **Analytics** → `kpi,telemetry,failure_corpus`; **Kanban/Board** (`story_context_manager`) → `stories,phases`; **Graph** (`execution_planning`, alle Sub-Tabs) → `planning`. Die alte „Board/Graph"-Klammer und „Execution-Input → planning"-Zeile entfernt.
- AC5 um Graph-Live-Tests ergaenzt: `dependency_graph_changed` aktualisiert den Dependency-Graph-Sub-Tab, `execution_input_changed`/`limits_changed` aktualisieren `ready`/`limits` (FK-91 §91.8.3 Z.516).
- FK-91↔FK-72-Konsistenz-Routing als Offener-Punkt an AG3-103 gespiegelt (dessen Scope nennt laut `_STORY_INDEX.md:144` ausdruecklich „FK-91↔FK-72 Planning-Pfade") — doc-only, kein Code hier.

## Must-Fix ERROR 4 — `failure_corpus` abonniert, aber Verhalten/AC fehlten bei offenem Schema

**Befund (bestaetigt):** FK-91 §91.8.3 (Z.517) fuehrt `failure_corpus` als „offen (folgt mit dem Failure-Corpus-Browser)". AG3-094 abonnierte es in Analytics, AC5 testete aber nur `stories/planning/kpi/telemetry`.

**Resolution:**
- `failure_corpus` analog zu `kpi` als Topic mit **offenem** Wire-Schema behandelt: nur Re-Fetch (Initial-GET-Re-Sync des Funnels), **kein** feldgranulares Event-Patching (Scope 2.1.4, eigener Out-of-Scope-Eintrag, Hinweise, Offener-Punkt).
- AC5 um einen `failure_corpus`-Re-Fetch-Test erweitert.
- Owner des Wire-Schemas + Failure-Corpus-Vollausbaus korrekt als **AG3-078** (Failure-Corpus Stufe 2/3, `_STORY_INDEX.md:79`) benannt; eigenes Browser-View bleibt out-of-scope an AG3-078.

## WARNING — AC9 ohne exakte Konzept-Gate-Befehle

**Befund (bestaetigt):** AC9 sagte „Vier Konzept-Gates … exakte Subcommands wie in Vorgaenger-Stories" und nannte ein nicht existentes `agentkit concept-lint`.

**Resolution:** AC9 nennt jetzt die realen Befehle aus AGENTS.md + `.githooks/pre-commit`: `.venv\Scripts\python scripts/ci/check_concept_frontmatter.py` und `.venv\Scripts\python scripts/ci/compile_formal_specs.py` (die kanonischen Konzept-Gates; es sind **zwei**, nicht vier). Zusaetzlich die Remote-Gates (`scripts/ci/check_remote_gates.ps1`, Jenkins+Sonar strikt) wie in AG3-098 AC12 ergaenzt. Klarstellung, dass diese Story keine `concept/`-Dateien aendert, die Gates aber dennoch gruen laufen.

---

## Befund→Resolution-Matrix

| # | Befund (review-r2.md) | Status | Wo in story.md |
|---|---|---|---|
| ERROR 1 | KPI-/Live-Pfad `/api/*` statt `/v1/...`; `/api/live/stories` faelschlich AG3-084 | RESOLVED | Z.20, Scope 2.1.1, OOS (KPI + neuer Live-Read-Eintrag), AC2/AC5/AC7, Hinweise |
| ERROR 2 | Templates+Pipeline-Modus-Filter ohne AG3-084-Vertrag | RESOLVED | Scope 2.1.5, OOS-/Offener-Punkt-Routing, AC7 |
| ERROR 3 | Graph live ueber `stories,phases` statt `planning` | RESOLVED | Scope 2.1.3, AC3, AC5, Hinweise, Offener-Punkt (AG3-103) |
| ERROR 4 | `failure_corpus` ohne Verhalten/AC bei offenem Schema | RESOLVED | Scope 2.1.4, OOS, AC5, Hinweise, Offener-Punkt (AG3-078) |
| WARNING | AC9 ohne exakte Gate-Befehle | RESOLVED (in Story gefixt) | AC9 |

## Anker-Verifikation (real gegengelesen)

- AG3-084 liefert `/v1/...`, kein `/api/kpi/*`: `stories/AG3-084-.../story.md:54` (AC1).
- AG3-084 `/api/live/stories` out-of-scope → AG3-081: `stories/AG3-084-.../story.md:43`, `:61` (AC8).
- AG3-084 `KpiQueryFilter`-Parametersatz: `stories/AG3-084-.../story.md:37`, `:58` (AC5).
- FK-63 §63.3.3 Filter-Wuensche (Templates/Pipeline-Modus): `63_auswertung_und_dashboard.md:147-154`.
- FK-63 §63.4.2 kein `pipeline_mode`-Param + Template nicht filterbar: `63_auswertung_und_dashboard.md:218-227`.
- FK-72 §72.5 Graph=`execution_planning`, Sub-Tabs ueber `planning`: `72_frontend_architektur.md:130-133`, `:143-144`.
- FK-91 §91.8.3 `dependency_graph_changed` unter `planning`; `failure_corpus` offen: `91_api_event_katalog.md:516`, `:517`; `kpi` offen `:515`.
- Konzept-Gate-Befehle real: `AGENTS.md:46-50`, `.githooks/pre-commit:38-41`.
- AG3-078 = Failure-Corpus-Owner; AG3-103-Scope nennt FK-91↔FK-72 Planning-Pfade: `_STORY_INDEX.md:79`, `:144`.

## status.yaml

Geprueft, **nicht geaendert**. `status: draft`, `phase: review_pending`, `depends_on: [AG3-084, AG3-093, AG3-003]`, `type: implementation`, `size: M` sind alle korrekt und mit dem korrigierten Scope konsistent (kein neues `depends_on` noetig: AG3-081/AG3-078 sind reine Owner-Routings fuer out-of-scope Punkte, keine harte Bauabhaengigkeit dieser Story). Der generische `title` („Charts + SSE") bleibt; die praezisere ECharts-Formulierung steht in story.md. Kein Feld falsch.

## Geaenderte/geschriebene Dateien (nur AG3-094)

- `stories/AG3-094-dashboards-live-updates-sse/story.md` — rewrite (AG3-057-Template-Struktur beibehalten).
- `stories/AG3-094-dashboards-live-updates-sse/remediation-r2.md` — dieser Report.
- `status.yaml` — **nicht** geaendert (alle Felder korrekt).

Scope strikt innerhalb des AG3-094-Schnitts gehalten (`_STORY_INDEX.md:119`): Dashboards/Charts auf den finalen KPI-Endpoints + Frontend-SSE-Consumer mit korrekten Topic-Sets + buildbare Filter-/Vergleichs-UI. Keine Scope-Erweiterung; alles ueber den Schnitt hinaus an Owner-Stories geroutet (AG3-003/078/081/084/092/093/103). Es wird **nicht** behauptet, eine andere Story liefere etwas ausserhalb ihres Scopes.
