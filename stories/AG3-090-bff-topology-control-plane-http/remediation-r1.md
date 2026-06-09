# AG3-090 — Remediation R1 (Antwort auf hostile Codex-Review `review-r1.md`)

**Datum:** 2026-06-08
**Geaenderte Dateien:** `story.md`, `status.yaml` (und dieser Report). Kein Produktionscode, keine Tests, keine `concept/`-Dateien, keine fremden Story-Dateien beruehrt.
**Scope-Disziplin:** Schnitt aus `_STORY_INDEX.md:115` strikt eingehalten — Namespace `control_plane_http`, projekt-skopierte URL-Konvention + Tenant-Scope-Middleware, die acht fehlenden BC-`http/`-Module. Kein Scope-Ausbau; alle ueber den Schnitt hinausgehenden Punkte (SSE-Backend/-Producer/-Consumer, KPI-Fachlogik, KPI-Pfad-Root) an Owner-Stories bzw. Index/PO geroutet.
**Methodik:** Jeder zitierte Anker gegen die echte Datei:Zeile gegengelesen (`control_plane/http.py`, `telemetry/http/routes.py`, `story_context_manager/http/routes.py`, FK-72/FK-73, AG3-003/084/094-Stories, `_STORY_INDEX.md`). Die vom Review als PASS bestaetigten Ist-Zustand-Anker (§1) wurden nachgeprueft und unveraendert/praezisiert belassen.

---

## ERRORs (Must-Fix)

### E1 — SSE-Owner falsch geschnitten (Review §1, Must-Fix 2)
**Befund:** Alte Out-of-Scope-Zeile wies den gesamten SSE-Block (`/v1/projects/{key}/events`, `?topics=`) pauschal **AG3-094** zu. Real: der Backend-SSE-Endpoint ist **AG3-003** (`status.yaml: completed`) und existiert bereits in `telemetry/http/routes.py:22` (Pfad-Pattern) / `:48` (`handle_get`), registriert via `control_plane/http.py:57`. AG3-094 baut laut eigener Story (`story.md:51`) **nur** den Frontend-Consumer; der Producer/Topics-Owner ist AG3-081.
**Resolution:** §2.2 in **drei** korrekte Owner-Zeilen gesplittet: Backend-Endpoint = **AG3-003** (`completed`, mit realen Ankern `telemetry/http/routes.py:22`/`:48`); Producer/Event-Emission + offene Topic-Wire-Schemas (`kpi`/`failure_corpus`) = **AG3-081**; Frontend-Consumer = **AG3-094**. AG3-090 baut/aendert **keinen** SSE-Endpoint, sondern sichert nur die Tenant-Middleware-**Kompatibilitaet** des bestehenden Pfads (neues §3 AC8). Sub-Agent-Hinweis ergaenzt („SSE NICHT bauen/aendern").

### E2 — AC2 zu schwach: nur „mind. ein Endpunkt" statt vollstaendiger Altpfad-Migration (Review §2, Must-Fix 1)
**Befund:** FK-72 §72.8.1 (`72_frontend_architektur.md:197`) verlangt **alle** projektbezogenen Ressourcen pfadgescoped. AC2 (alt) bewies nur die Stories-Collection. Mehrere ungescopte projektbezogene Altpfade bestehen: `/v1/stories*` (`story_context_manager/http/routes.py:49`-`:57`), `/v1/story-runs/...` (`control_plane/http.py:61`/`:64`), `/v1/dashboard/*` (`:298`/`:300`).
**Resolution:** Scope §2.1.2 um die **vollstaendige Altpfad-Inventur** mit belegten Ankern erweitert (Collection, Detail, Mutationen, Fields, Phase-/Closure-Pfade, Dashboard-Pfade). **AC2** neu gefasst: vollstaendige Migration mit Routing-Test je Pfadklasse, **kein** projektbezogener Query-`project_key`-Fallthrough; bewusste Legacy-Pfade nur als **explizite**, dokumentierte Entscheidung.

### E3 — KPI-Route-Root-Konflikt `/kpis` vs `/kpi/*` (Review §1, §2, Must-Fix 3)
**Befund:** FK-72 §72.8.2 (`72_frontend_architektur.md:222`) verankert `kpi_analytics/http/` -> `/v1/projects/{key}/kpis` (Plural). AG3-084 AC1 (`story.md:54`) fixiert `/v1/projects/{project_key}/kpi/{stories|...}` (Singular + Sub-Resource); AG3-094 (`story.md:49`) konsumiert `/v1/.../kpi/*`. Echter Cross-Story-Konflikt, von AG3-090 nicht einseitig zu entscheiden (NO ERROR BYPASSING).
**Resolution:** Kopf-Block „OFFENER CROSS-STORY-KONFLIKT" eingefuegt; Scope §2.1.4 `kpi_analytics`-Zeile entschaerft (Modul-Mount registriert, **kein** finaler Pfad fixiert); §2.2-Out-of-Scope-Zeile + neues §7 routen den kanonischen Root an **Index/PO**, den FK-Prosa-Nachzug an doc-only **AG3-103** (`_STORY_INDEX.md:144`). **AC4** trägt die `kpi_analytics`-Ausnahme (Registrierung testbar, umstrittener Pfad nicht). DoD um die Konflikt-Aufloesung/Meldung ergaenzt.

### E4 — Pflicht-Gates unvollstaendig (Review §2, Must-Fix 4)
**Befund:** AC8 (alt) nannte nur lokale Tests/ruff/mypy/Konzept-Gates; AGENTS.md (`:33`/`:43`) verlangt Jenkins, Sonar und `scripts/ci/check_remote_gates.ps1`.
**Resolution:** Zu **AC9** (vorher AC8) ausgebaut mit exakten Befehlen (Repo-Root) inkl. der **Pflicht-Remote-Gates**: `scripts/ci/check_remote_gates.ps1` gruen (Jenkins `http://localhost:9900/job/claude-agentkit3/` + Sonar `http://192.168.0.20:9901`) mit Sonar-Zielwerten **strikt** `violations=0`, `critical_violations=0`, `security_hotspots=0`.

### E5 — Namespace-Migrationsvariante unverbindlich (Review §3 WARNING, Must-Fix 5)
**Befund:** Scope (alt §2.1.1) erlaubte „Move **oder** Re-Export", Sub-Agent-Hinweis delegierte die Entscheidung erneut an den Owner — keine bindende Variante.
**Resolution:** §2.1.1 **verbindlich entschieden**: kanonischer **Move** `control_plane/http.py` -> `control_plane_http/` als neuer Import-Owner + **genau ein** Compat-Re-Export in `control_plane`; alle internen Importe (Bootstrap/Composition-Root, Tests) vollstaendig umgestellt. Begruendung: es existiert bereits **ein** Transport (`control_plane/http.py:185`); eine „Web-Abspaltung neben `control_plane`" wuerde zwei Transport-Heimaten erzeugen (verboten). **AC1** auf „Import-Owner + Compat-Re-Export, keine Duplikat-Definition" geschaerft; Sub-Agent-Hinweis von „Klaere mit Owner" auf „entschieden, nicht erneut zur Diskussion" umgestellt.

---

## WARNINGs

### W1 — `/v1/projects` faelschlich als „projektneutral" bezeichnet (Review §3)
**Befund:** FK-73 §73.3 (`73_project_management.md:73`-`:77`) beschreibt Detail/Patch/Archive als Project-Management-Ressourcen; sie tragen `project_key` bereits als erstes Pfadsegment.
**Resolution (im Story gefixt):** §2.1.2 Klarstellung ergaenzt: `/v1/projects[/{key}/...]` ist die **`project_management`-Sonderoberflaeche ohne doppelten Projekt-Praefix** — Detail/Patch/Archive gehoeren zum Project-Management (nicht „projektneutral"), bekommen aber **keinen** zweiten `/projects/{key}/`-Praefix; nur Liste/Anlegen sind projektneutral.

### W2 — `status.yaml unblocks: []` still leer (Review §4)
**Befund:** `_STORY_INDEX.md:116` (AG3-091 `depends_on: AG3-090, AG3-098`) und `:118` (AG3-093 `depends_on: AG3-090, AG3-092`) haengen direkt von AG3-090 ab.
**Resolution (im status gefixt):** `unblocks: []` → `unblocks: [AG3-091, AG3-093]` (reziprok zu den Index-Kanten). **AG3-094** (`_STORY_INDEX.md:119`, `depends_on: AG3-084, AG3-093, AG3-003`) haengt **nicht** direkt von AG3-090 ab und ist bewusst **nicht** in `unblocks` aufgenommen (keine Falschbehauptung).

### W3 — Namespace-Owner-Klaerung offen
Durch E5 erledigt (bindende Variante + AC1 + Sub-Agent-Hinweis).

---

## Anker-Korrekturen (falsch/ungenau/fehlend → real)
- **SSE-Endpoint** neu korrekt verankert: `telemetry/http/routes.py:22` (Pfad-Pattern), `:48` (`handle_get`), `control_plane/http.py:57` (Import `TelemetryRoutes`) — vorher fehlte der reale Ort komplett (faelschliche AG3-094-Zuweisung).
- **Altpfad-Inventur** mit realen Ankern hinterlegt: `_STORY_PATH_PATTERN` `:70`, `_PHASE_PATH_PATTERN` `:61`, `_CLOSURE_PATH_PATTERN` `:64`, Stories-Sub-Pfade `story_context_manager/http/routes.py:49`-`:57`, Dashboard `:298`/`:300`.
- **FK-72 §72.8.2** KPI-Mount-Anker `72_frontend_architektur.md:222`; **FK-73 §73.3** `73_project_management.md:73`-`:77`.
- **Cross-Story-Anker** ergaenzt: AG3-084 `story.md:54`, AG3-094 `story.md:49`/`:51`, AG3-103 `_STORY_INDEX.md:144`.
- Die in §1 der Story zitierten Ist-Zustand-Anker (`handle_request` `:185`, Auth-Middleware `:202`, `/v1/stories` Query-`project_key` `:692`, `_backend_requirement_response` `:982`) wurden vom Review als PASS bestaetigt und unveraendert beibehalten.

---

## Must-Fix ERROR-Liste (1:1 Abgleich mit review-r1.md §„Must-Fix")
| # | Must-Fix | Status | Wo |
|---|---|---|---|
| 1 | AC2 auf vollstaendige Migration aller projektbezogenen Altpfade schaerfen | RESOLVED | §2.1.2, AC2 |
| 2 | SSE-Out-of-Scope-Owner korrigieren: AG3-003/AG3-081/AG3-094 | RESOLVED | §2.2 (3 Zeilen), AC8, Sub-Agent-Hinweis |
| 3 | KPI-Root-Konflikt `/kpis` vs `/kpi/*` vor Freigabe entscheiden/routen | RESOLVED (geroutet an Index/PO + AG3-103) | Kopf-Konflikt, §2.1.4, §2.2, §7, AC4, DoD |
| 4 | Remote-Gates/Jenkins/Sonar in AC aufnehmen | RESOLVED | AC9 |
| 5 | Namespace-Migrationsvariante verbindlich festlegen | RESOLVED | §2.1.1, AC1, Sub-Agent-Hinweis |

## Warnings (1:1 Abgleich)
| Warning | Status | Wo |
|---|---|---|
| Namespace-Strategie offen | RESOLVED (in Story gefixt) | §2.1.1, AC1 |
| `/v1/projects` als „nicht-projektbezogen" | RESOLVED (in Story gefixt) | §2.1.2 Klarstellung |
| `status.yaml unblocks: []` | RESOLVED (in status gefixt) | `status.yaml` |

---

## Echte Cross-Story-Prerequisites (zu melden, nicht story-seitig zu schliessen)
- **Kanonischer KPI-Routen-Root (`/kpis` vs `/kpi/*`):** Index/PO muss den Root festlegen und AG3-084/AG3-090/AG3-094 + FK-72/FK-63-Prosa angleichen; doc-only-Nachzug = **AG3-103**. Bis dahin registriert AG3-090 das `kpi_analytics/http/`-Modul, fixiert aber keinen erreichbaren KPI-Pfad (siehe §7). Dies ist der einzige genuine, story-extern zu loesende Prerequisite; alle anderen Befunde sind in-story behoben.

## status.yaml — Aenderung
- `unblocks: []` → `unblocks: [AG3-091, AG3-093]` (reziprok zu `_STORY_INDEX.md:116`/`:118`). `depends_on: [AG3-002]`, `status: draft`, `phase: review_pending`, `type: implementation`, `size: L` gegen den Index gegengeprueft und korrekt — unveraendert.

## Bestaetigung
Geschrieben wurden ausschliesslich AG3-090-Dateien: `stories/AG3-090-bff-topology-control-plane-http/story.md`, `.../status.yaml`, `.../remediation-r1.md`. Produktionscode, Tests, `concept/`-Dateien und fremde Story-Dateien wurden **nicht** angefasst. Template-Struktur (AG3-057) beibehalten: Kopf + §1 Kontext/Ist-Zustand + §2 Scope (In/Out) + §3 Akzeptanzkriterien + §4 DoD + §5 Guardrails + §6 Sub-Agent-Hinweise (+ §7 Offene fachliche Punkte). ARCH-55: alle neuen Pfadsegmente/Bezeichner/`error_code`-Werte englisch.
