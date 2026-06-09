# AG3-084 — Remediation R2 (Antwort auf Round-2-Review `review-r2.md`)

**Datum:** 2026-06-08
**Geaenderte Dateien:** `story.md` (und dieser Report). `status.yaml` bewusst **unveraendert** (alle Felder belegt korrekt — Begruendung unten). Kein Produktionscode, keine Tests, keine `concept/`-Dateien beruehrt; `_STORY_INDEX.md` **nicht** angefasst (nur story.md/status.yaml/remediation erlaubt — der autoritative Index ist Single Source of Truth fuer den Schnitt und wird vom PO/Index-Owner korrigiert, nicht story-seitig ueberschrieben).
**Scope-Disziplin:** strikt im AG3-084-Cut geblieben (KPI-Analytics-Read-Endpoints + DRIFT-AG3-038-Trust-Boundary-Fix + typisierter Filter). Round-1 hatte versucht, eine offene PO/Index-Frage **story-lokal** zu schliessen und eine nicht-implementierbare Live-View zu mandatieren — beides Round-2-ERRORs. R2 korrigiert das, indem die Konflikte ehrlich als offene Index-/PO-Punkte ausgewiesen und an die korrekten Owner geroutet werden, statt sie zu verstecken oder eigenmaechtig zu „schliessen".

---

## Remaining/New Must-Fix ERRORs

### E1 (Review §"Remaining" Nr. 1) — AG3-084-Scope kollidiert mit `_STORY_INDEX.md` (Design-Tokens)
**Befund:** `_STORY_INDEX.md:90` listet weiterhin `FK-64 §64.2` + `get_design_tokens` fuer AG3-084; `_STORY_INDEX.md:175` (Offene Schnitt-Frage Nr. 4) rahmt die Token-Endpoint-Zuordnung als **offene PO-Frage**. Round-1 behauptete in `story.md` Zeile 11, das sei „hier geschlossen" — eine story-lokale Schliessung einer Frage, deren Owner der Index/PO ist. Eine `story.md` kann den autoritativen Backlog-Index nicht ueberschreiben.
**Verifikation am Code/Konzept:** FK-64 §64.2 (`64_control_plane_design_system.md:91-99`) verboten: „`DesignSystem` gibt keine Tokens dynamisch aus und betreibt keinen eigenen HTTP-Endpunkt; Boundary-Control liegt bei `control_plane`." `_STORY_INDEX.md:117` weist `get_design_tokens` AG3-092 zu; AG3-092 `depends_on` AG3-084 → die Vorversions-Konstruktion (AG3-084 baut Endpoint, konsumiert spaeter AG3-092-Token-Owner) waere zyklisch.
**Resolution:** Story-Kopf ersetzt den falschen „hier geschlossen"-Claim durch einen expliziten **Scope-/Index-Konflikt Nr. 1**, der (a) den Befund konzept-belegt darlegt, (b) die Token-Lieferung (Modell **und** HTTP) als Owner-Scope von **AG3-092** ausweist, (c) die konkrete **PO/Index-Aktion** benennt (`_STORY_INDEX.md:90` FK-64+`get_design_tokens` entfernen, `:175` Frage schliessen) und (d) festhaelt: bis zur Index-Korrektur liefert AG3-084 keinen Token-Endpoint und keinen FK-64-§64.2-Claim. Out-of-Scope-Eintrag (§2.2) entsprechend praezisiert. **Damit ist nichts mehr story-lokal „geschlossen", sondern korrekt an den Index/PO geroutet.** DoD (§4) verlangt die Index-Aufloesung oder eine explizite Blocker-Meldung vor finaler Autorisierung.

### E2 (Review §"Remaining" Nr. 2) — `/api/live/stories` via `ProjectionAccessor` ist wie geschnitten nicht implementierbar
**Befund:** AC5 (alt) verlangte Live-Reads ueber `telemetry-and-events.ProjectionAccessor` fuer `execution_events`/`flow_executions`/`phase_state_projection`. Der reale Port kann das nicht:
- `ProjectionKind` kennt nur 7 FK-69-Werte (`src/agentkit/telemetry/projection_accessor.py:56-70`); `execution_events`/`flow_executions` sind **keine** FK-69-Read-Models (FK-68-Telemetrie-Tabellen) und existieren dort nicht.
- `read_projection(PHASE_STATE_PROJECTION)` ist fail-closed abgewiesen mit Owner-Benennung `pipeline_engine.PhaseExecutor` (`projection_accessor.py:105-111`, `:394-403`).
- Repo-Adapter bestaetigt: „kein Read via ProjectionAccessor derzeit" (`src/agentkit/state_backend/store/projection_repositories.py:1035-1040`).
Es gibt also **keinen** projekt-skopierten Live-Read-Port. FK-63 §63.4.1/§63.5 verlangt zwar genau diese Quelle — aber das benannte Port-Konzept ist im Code noch nicht erfuellt (Upstream-Luecke).
**Resolution (Review-Option 2 gewaehlt):** `/api/live/stories` aus dem **lieferbaren** AG3-084-Scope entfernt und an den Runtime-Schema-Owner geroutet. Story-Kopf (Scope-/Index-Konflikt Nr. 2) + §1 (Ist-Zustand) + §2.2 (Out of Scope) belegen die Nicht-Implementierbarkeit mit `file:line` und benennen den Owner: die FK-68/FK-69-Telemetrie-Story (naheliegend **AG3-081**, traegt den typisierten `phase_state_projection`-Record + FK-69-Reads) muss zuerst einen projekt-skopierten Live-Read-Port liefern. Titel/Quell-Konzept-Block auf `/api/kpi/*` reduziert; FK-63 §63.4-Zitat ohne `/api/live/stories`. AC1 spricht jetzt von **fuenf** `/api/kpi/*`-Endpoints. Frueheres AC5 (Live ueber ProjectionAccessor) gestrichen; neues **AC8** verlangt explizit, dass **kein** Live-Endpoint und **kein** Ersatz-Live-Pfad (ueber `StoryService` oder Rollups) gebaut wird (FAIL-CLOSED statt falscher Live-Quelle). **PO/Index muss `_STORY_INDEX.md:90` korrigieren** (Live aus AG3-084 entfernen, einer Live-Read-Port-Story zuordnen) — DoD-Bedingung.

---

## WARNINGs (Round-2)

Review-r2 fuehrt unter „Remaining/New Must-Fix ERRORs" nur die zwei ERRORs E1/E2; die Per-Dimension-Verdikte (AC-Schaerfe WEAK wegen AC5, Klarheit/Kontext FAIL wegen Index-Konflikt) sind Auspraegungen derselben zwei Root Causes und mit E1/E2 mitbehoben:
- **AC-Schaerfe (AC5 nicht implementierbar):** durch E2 aufgeloest — die untestbare Live-AC ist entfernt; AC8 ist als Negativ-/Abgrenzungs-AC testbar (kein Live-Endpoint, kein Ersatzpfad).
- **Klarheit/Eindeutigkeit + Kontext-Sinnhaftigkeit (Index sagt das Gegenteil/offen):** durch E1+E2 aufgeloest — die Story behauptet nichts mehr als „geschlossen", sondern spiegelt die Index-Konflikte aktiv mit konkreter PO/Index-Aktion und Owner-Routing (Severity-Semantik: aktiv an den Auftraggeber gespiegelt, nicht still liegengelassen).

Keine eigenstaendigen, separat aufschiebbaren WARNINGs offen. Die Round-1-WARNINGs (W1 Reset-/Gueltigkeitsregel, W2 EMPTY-Status, W3 Pfad-Konvention) wurden bereits in R1 in-story behoben (AC6/AC7/AC8 alt → jetzt AC5/AC6/AC7) und von Round-2 nicht erneut beanstandet; sie bleiben in der neuen AC-Nummerierung erhalten.

---

## Round-2-Status der Round-1-Must-Fixes (zur Nachverfolgung)
- E1/E4 (FK-64-Token-Endpoint): R1 nur in `story.md` geloest, nicht im Index → R2 korrekt als Index-/PO-Konflikt geroutet (kein story-lokales Schliessen mehr). **Erledigt (richtig geroutet).**
- E2 (project/tenant scope), E3 (`PeriodFilter`-Missbrauch), E6 (`DashboardService` zu breit): von Round-2 als resolved bestaetigt — unveraendert beibehalten.
- E5 (offene Schnitt-Frage als entschieden behandelt): war der Kern-Fehler von R1; in R2 behoben (E1 oben).

---

## status.yaml — keine Aenderung (Begruendung)
- `title` enthaelt `/api/live/stories` und spiegelt damit den **autoritativen Index-Titel** (`_STORY_INDEX.md:90`). Eine story-seitige Titel-Aenderung wuerde — analog zum R1-Fehler — eine neue Divergenz zum Index erzeugen und die Index-Korrektur vortaeuschen. Der Titel bleibt index-treu, bis der PO/Index `_STORY_INDEX.md:90` korrigiert; die Scope-Reduktion ist im Story-Body dokumentiert und geroutet.
- `depends_on: [AG3-082, AG3-091]` — korrekt fuer die **reduzierte** lieferbare Schneidung (KPI-Reads + control_plane-Konvention). Der Live-Read-Port (AG3-081) ist **kein** `depends_on`, weil `/api/live/stories` nicht mehr Teil des AG3-084-Deliverables ist; das Routing steht im Body. Index listet AG3-081 dort ebenfalls nicht.
- `unblocks: [AG3-092]` — korrekt (AG3-092 `depends_on` AG3-084, `_STORY_INDEX.md:117`); in R1 gesetzt, unveraendert.
- `status: draft`, `phase: review_pending` — korrekt (Story ist im Review, noch nicht autorisiert).

---

## Bestaetigung
Geschrieben wurden ausschliesslich: `story.md`, `remediation-r2.md`. `status.yaml` blieb unveraendert (begruendet). Produktionscode, Tests, `concept/`-Dateien und `_STORY_INDEX.md` wurden **nicht** angefasst. Template-Struktur (AG3-057) beibehalten: Kopf + §1 Kontext/Ist-Zustand + §2 Scope (In/Out) + §3 Akzeptanzkriterien + §4 DoD + §5 Guardrails + §6 Sub-Agent-Hinweise. Alle Code-Anker gegen die reale Quelle verifiziert (`service.py:14-18`/`:26`/`:96-133`/`:135-161`/`:144`; `top.py:137-141`/`:142`/`:172-184`; `views.py:18-23`; `projection_accessor.py:56-70`/`:105-111`/`:394-403`; `projection_repositories.py:1035-1040`; `control_plane/http.py:296-301`/`:298-301`). ARCH-55: alle vorgeschlagenen Routen/Felder/Enum-Werte englisch.
