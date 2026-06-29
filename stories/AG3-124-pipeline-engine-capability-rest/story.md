# AG3-124: `pipeline_engine/http` — 503-Stub zur realen server-seitigen Capability-Route (Phasen-Ausfuehrung via Kern)

**Typ:** Implementation / **Groesse:** L / **Bounded Context:** `pipeline_engine` / BFF-Capability-Route (FK-72 §72.8.2). Die `pipeline_engine/http`-Route (`/v1/projects/{key}/phases`) ist heute ein 503-Stub (`service_available=False`) — eine BFF-Huelle ohne reale Capability-Vermittlung. Diese Story aktiviert sie als **reale server-seitige Capability-Route**, die die Phasen-Ausfuehrung ueber den deterministischen Kern (`ControlPlaneRuntimeService`/`PhaseDispatcher`) treibt — ohne in-process Dev-Ausfuehrung. Sie baut direkt auf dem in **AG3-123** geschaffenen Backend-resolved Workspace auf.

**Quell-Konzepte (autoritativ):**
- `FK-10 §10.1.0 I3` (`10-1-laufzeitkomponenten-001`) — kanonische Operationen (State, Gates, **Phasenfortschritt**) laufen ausschliesslich per REST ueber den Kern.
- `FK-10 §10.2.3` (`10-2-deployment-modell-002`) — die 4-Phasen-Pipeline ist der AK3-Kern und laeuft im Backend; ihre Autoritaet wird nicht nach aussen delegiert.
- `FK-72 §72.8 / §72.8.2` (`72-8-bff-topologie-008`) — BFF-Topologie: ein Server-Prozess, pro BC ein Routes-Modul; `agentkit/pipeline_engine/http/ -> /v1/projects/{key}/phases`. „Der offizielle API-Vertrag im Detail liegt in FK-91."
- `FK-45 §45.1` (`45-1-service-api-eintrittspunkt-und-phasen-dispatch-001`) — Standard-Eintrittspunkt des Phase Runners ist die Control-Plane-API; vier Top-Phasen `setup, exploration, implementation, closure`; normative Aufruf-Parameter (`story_id, phase, mode, op_id`) als Schema-Owner in `FK-91 §91.1a`.
- **`FK-91 §91.1a` (Phasen-Mutations-Vertrag):** der normative Endpunkt-Vertrag fuer Phasenfortschritt ist `POST /v1/story-runs/{run_id}/phases/{phase}/{start|complete|fail}` (`91_..:99`) — **nicht** `/v1/projects/{key}/phases`. **Konzept-Spannung (zu beachten, nicht still aufloesen):** FK-72 §72.8.2 mountet das `pipeline_engine/http`-Modul unter `/v1/projects/{key}/phases`, FK-91 §91.1a fuehrt den Mutations-Vertrag aber unter `story-runs/{run_id}/phases/{phase}`. Diese Story erfindet **keinen** neuen Mutations-Endpunkt: die `pipeline_engine`-Capability-Route ist BC-Adapter **ueber** den bestehenden normativen `story-runs`-Vertrag (Read-/BC-Mount-Surface), die kanonische Phasen-Mutation bleibt der bestehende `story-runs`-Pfad. Falls FK-72 und FK-91 hier wirklich kollidieren, ist das als Konzept-Konflikt zu **melden** (CLAUDE.md: hart stoppen, nicht implizit abweichen), nicht durch einen zweiten Vertrag aufzuloesen.
- `FK-91 §91.2` (`91-2-telemetrie-event-typen-003-02`) — „Hooks, CLI und kuenftige REST-Aufrufe sind nur Producer-Pfade auf diesen Katalog; sie duerfen keine abweichenden Event-Namen oder Payload-Formate einfuehren." / `FK-91 §91.5` (`91-5-phase-state-status-werte-006`) — kanonische Phase-Status-Werte `PENDING, IN_PROGRESS, COMPLETED, FAILED, ESCALATED, PAUSED`.
- `FK-10 §10.6` (`10-6-fehlerbehandlung-und-recovery-006`) — Fail-closed bei nicht erreichbarem/aufloesbarem Kern.

---

## 1. Kontext / Ist-Zustand (belegt)

Re-verifiziert am aktuellen Code (`src/agentkit/backend/`):

- `pipeline_engine/http/routes.py:38` — `PipelineEngineRoutes.service_available: bool = False` (Default). `handle_get` (`:50-55`) und `handle_post` (`:72-77`) liefern bei `service_available=False` eine strukturierte 503 `phases_unavailable` ueber `bc_unavailable_response`.
- `control_plane_http/app.py:191` — die Route wird mit `PipelineEngineRoutes()` **ohne Argument** instanziiert, also `service_available=False` -> in Produktion ein 503-Stub. Der Modul-Docstring (`pipeline_engine/http/routes.py:1-8`) haelt fest: „Where the consuming pipeline-engine service is absent the adapter returns a structured 503 `phases_unavailable`".
- `control_plane/models.py:126-141` — `bc_unavailable_response(...)` liefert `HTTPStatus.SERVICE_UNAVAILABLE` (503), fail-closed (kein Silent-Empty-200, kein bare-500). Dieser Wire-Vertrag ist von **AG3-090** (`completed`) etabliert.
- **Die reale Phasen-Arbeit** existiert bereits server-vermittelt parallel dazu: `control_plane_http/app.py:76-81` (`POST /v1/projects/{key}/story-runs/{run_id}/phases/{phase}/{start|complete|fail}`), Handler `:765-773` ueber `self._runtime_service` (`ControlPlaneRuntimeService`, `:414`). D.h. es gibt zwei Oberflaechen fuer dieselbe Capability: die **realen** `story-runs/.../phases`-Routen und den **leeren** `pipeline_engine/http`-BC-Stub.
- **Voraussetzung AG3-123:** der Dispatch hinter `RuntimeService` war an `ctx.project_root` (dev-lokal) gekoppelt (`dispatch.py:835-841`, `runtime.py:843-847`); AG3-123 macht ihn Backend-resolved. Erst damit ist eine echte server-seitige Capability-Route ohne Dev-FS-Annahme moeglich.

**Konsequenz:** Die `pipeline_engine`-Capability hat keine reale BC-REST-Vermittlung (WP-D, D1). Diese Story aktiviert sie und verankert sie auf dem Kern-Pfad — kein in-process Dev-Run.

## 2. Scope

### 2.1 In Scope

1. **`PipelineEngineRoutes` real verdrahten.** `service_available` wird produktiv `True`, sobald die konsumierende Capability (Kern-Phasen-Ausfuehrung via `ControlPlaneRuntimeService`/`PhaseDispatcher`, Backend-resolved per AG3-123) injiziert ist. Die Route delegiert an den Kern — **keine** eigene Phasen-Fachlogik im Adapter (CLAUDE.md: `http/`-Module bleiben duenne Adapter).
2. **Capability-Injektion in `control_plane_http/app.py:191`.** Statt `PipelineEngineRoutes()` (Default-Stub) wird die Route mit dem realen Capability-Port gebaut. Wo der Kern aufloesbar ist, ist `service_available=True`; wo nicht, bleibt der **fail-closed** 503-Pfad erhalten (FK-10 §10.6).
3. **Phasen-Ausfuehrungs-Endpunkte** unter `/v1/projects/{key}/phases` (FK-72 §72.8.2) treiben die Phasen-Ausfuehrung ueber den Kern. Aufruf-Parameter (`story_id, phase, mode, op_id`) folgen dem Schema-Owner `FK-91 §91.1a`; Phasen-Namen sind die vier Top-Phasen aus FK-45 §45.1; zurueckgegebene Phase-Status-Werte folgen `FK-91 §91.5` (kein abweichendes Vokabular, FK-91 §91.2).
4. **Verhaeltnis zu den `story-runs/.../phases`-Routen klaeren (SSOT).** Es darf **keine** zweite operative Wahrheit fuer die Phasen-Ausfuehrung entstehen: die `pipeline_engine/http`-Capability und die bestehenden `story-runs`-Phasenrouten muessen denselben Kern-Pfad (`RuntimeService`) treiben. Ein paralleler zweiter Ausfuehrungspfad **oder** ein zweiter Mutations-Vertrag ist verboten (FIX THE MODEL). **Vorgabe:** der bestehende `story-runs/{run_id}/phases/{phase}`-Vertrag (FK-91 §91.1a) bleibt die kanonische Phasen-Mutation; das `pipeline_engine/http`-Modul aktiviert die BC-Read-/Mount-Surface bzw. delegiert intern auf denselben `RuntimeService`. Die FK-72↔FK-91-Pfaddiskrepanz wird im Execution-Plan benannt; eine echte Kollision ist als Konzept-Konflikt zu melden, nicht durch Doppel-Endpunkt aufzuloesen.
5. **Fail-closed-Vertrag erhalten.** Ist die Capability nicht verfuegbar/aufloesbar, liefert der Adapter weiterhin strukturierte 503 `phases_unavailable` (kein 200-Leer-OK, kein bare-500) — der von AG3-090/`bc_unavailable_response` etablierte Vertrag bleibt gueltig.
6. **Tests** (Pflicht, §3): reale Route trifft den Kern (200/202 mit Phase-Status), Negativpfad (Capability absent -> 503), Phasengrenzen-Negativtest (ungueltiger Phasenuebergang ueber die Route blockiert), Vertragstest fuer Phase-Status-Vokabular (FK-91 §91.5).

### 2.2 Out of Scope (mit Owner)

- **`project_root`-Entkopplung des Dispatch** — **AG3-123** (`depends_on`); diese Story setzt sie voraus, baut sie nicht.
- **`verify_system/http` + `closure/http` + `governance/http` Aktivierung** — **AG3-125** (gleiche Aktivierung fuer die anderen Capabilities).
- **Drittsystem-Vermittlung (Sonar/Jenkins/ARE, WP-B)** innerhalb der Phasen — eigenes Arbeitspaket (u. a. AG3-132).
- **LLM-Hub-Eval-Locus / Verify-Layer-2 produktive Anbindung (WP-C)** — **AG3-133** und Verwandte.
- **KPI-/Read-Model-Payloads, SSE-Producer** — AG3-08x/AG3-09x (BFF-Read-Seite), nicht hier.
- **`artifacts/http`, `failure_corpus/http`, `requirements_coverage/http`** (weitere 503-Stubs) — ausserhalb dieses Capability-Schnitts; eigene Stories.

### 2.3 Betroffene Dateien

| Datei | Aenderungsart |
|---|---|
| `src/agentkit/backend/pipeline_engine/http/routes.py` | Aendern (`service_available` real; Delegation an Kern-Capability statt 503-Default) |
| `src/agentkit/backend/control_plane_http/app.py` | Aendern (`PipelineEngineRoutes(...)` mit realem Capability-Port statt Default-Stub `:191`) |
| `src/agentkit/backend/pipeline_engine/` (Capability-Port/DTO, falls noetig) | Neu/Aendern |
| `tests/unit/pipeline_engine/http/test_routes.py` | Aendern (Real-Capability statt `service_available`-Stub) |
| `tests/integration/control_plane_http/**`, `tests/integration/pipeline_engine/**`, `tests/contract/**` | Neu/Aendern (echte HTTP-Routing-Integration; 503-Negativpfad; Phase-Status-Vokabular) |

## 3. Akzeptanzkriterien

1. `PipelineEngineRoutes` ist in `control_plane_http` mit der realen Kern-Capability verdrahtet; bei aufloesbarem Kern treibt die Route die Phasen-Ausfuehrung ueber `ControlPlaneRuntimeService`/`PhaseDispatcher`. **Echter HTTP-Routing-Integrationstest (keine Stub-Absicherung):** ein realer Request durch `ControlPlaneApplication` erreicht `RuntimeService.start_phase`, fuehrt **eine reale Phase** ueber `PhaseDispatcher` aus und der Test verifiziert den **persistierten/zurueckgegebenen** Phase-Status-Uebergang — nicht ein `service_available=True`-Stub mit Dummy-200.
2. **Keine in-process Dev-Ausfuehrung:** die Route fuehrt die Phase ueber den server-seitigen Kern aus (Backend-resolved Workspace aus AG3-123); kein Code-Pfad fuehrt die Phase im Dev-/CLI-Prozess aus, um die Route zu bedienen (SSOT-Test).
3. **Fail-closed:** Ist die Capability nicht verfuegbar/aufloesbar, liefert die Route strukturierte 503 `phases_unavailable` (kein 200-Leer-OK, kein bare-500) — Negativtest mit nicht verfuegbarer Capability.
4. **SSOT der Phasen-Ausfuehrung:** `pipeline_engine/http` und die `story-runs/.../phases`-Routen treiben denselben Kern-Pfad; es gibt **keinen** zweiten parallelen Ausfuehrungspfad (Test/Architektur-Beleg).
5. **Vertrags-/Vokabular-Treue:** zurueckgegebene Phase-Status-Werte stammen aus `FK-91 §91.5` (`PENDING, IN_PROGRESS, COMPLETED, FAILED, ESCALATED, PAUSED`); Aufruf-Parameter folgen FK-91 §91.1a / FK-45 §45.1 (vier Top-Phasen). Contract-Test pinnt das Vokabular; keine abweichenden Namen (FK-91 §91.2).
6. **Phasengrenzen-/Negativpfad-Pflicht (testing-guardrails §1/§2/§3):** ein gueltiger und ein ungueltiger Phasenuebergang **ueber die HTTP-Route** sind verprobt (gueltiger Start dispatcht; ungueltiger Uebergang / un-admittierter Start blockiert fail-closed). Der State entsteht durch den realen Vorgaenger-Flow, **nicht** durch manuell fabrizierten Pipeline-State (testing-guardrails §2).
7. `X-Correlation-Id`- und `ApiErrorResponse`/`BcRouteResponse`-Form gelten unveraendert (Test: Fehlerantwort traegt Correlation-Id + `error_code`).
8. **ARCH-55:** alle Pfadsegmente, Modul-/Methodennamen, `error_code`-Werte, Bezeichner und Kommentare englisch. Keine `noqa`/`type: ignore` ohne Begruendung.
9. **Quality-Gates gruen** (Repo-Root, via `.venv`, GAC-konform):
   - `.venv\Scripts\python -m pip install -e ".[dev]"`; `.venv\Scripts\python -m pytest tests/unit -n0`, `tests/integration -n0`, `tests/contract -n0`; Coverage >= 85 % (`--cov=agentkit --cov-fail-under=85`).
   - `.venv\Scripts\python -m mypy src` **und** `--platform linux` (strict); `.venv\Scripts\python -m ruff check src tests`.
   - Konzept-/Architektur-Gates (GAC-1): `scripts/ci/check_architecture_conformance.py`, `scripts/ci/check_concept_frontmatter.py`, `scripts/ci/check_concept_code_contracts.py`, `scripts/ci/compile_formal_specs.py`.
   - **Remote-Gates** (`pwsh scripts/ci/check_remote_gates.ps1`): **Jenkins-Build gruen** und **SonarQube Zero-Violation** (`violations=0`, `critical_violations=0`, `security_hotspots=0` auf New Code).

## 4. Definition of Done

- AK 1–9 erfuellt; QA-Gate (Codex-Review) **PASS** + Standard-Pflichtbefehle + Remote-Gates (Jenkins/Sonar) gruen. Implementierung/Commit erst nach Execution-Plan-Freigabe. Entblockt AG3-129, AG3-130.

## 5. Guardrail-Referenzen

- **FIX THE MODEL / SINGLE SOURCE OF TRUTH:** **eine** Phasen-Ausfuehrungs-Wahrheit (Kern-Pfad); die Capability-Route ist Vermittler, kein zweiter Executor. Kein paralleler in-process Dev-Run.
- **FAIL CLOSED:** Capability absent -> strukturierte 503; nie stilles Leer-OK (FK-10 §10.6, `bc_unavailable_response`).
- **KEINE FACHLOGIK IN ADAPTERN:** `pipeline_engine/http` bleibt duenner Adapter; Phasen-Fachlogik bleibt im Kern.
- **TYPISIERT STATT STRINGS:** Phase-Status- und Aufruf-Parameter-Vertraege typisiert (Pydantic/Enum), kein Ad-hoc-Dict; Vokabular aus FK-91 §91.5.
- **NO ERROR BYPASSING:** Admission-/Gate-Regeln (FK-20 §20.8.2) bleiben scharf ueber die Route.
- **WORKFLOW-/STATE-DISZIPLIN:** Phasen-Routing typisiert; keine String-/Flag-Kaskade.
- **GAC-2 / ARCH-NN:** `guardrails/architecture-guardrails.md` einhalten; ARCH-55 (Englisch) verbindlich.

## 6. Hinweise fuer den Sub-Agent

- Read T:/codebase/claude-agentkit3/CLAUDE.md first — all project rules apply to you.
- Ankerpunkte (aktueller Code unter `src/agentkit/backend/`): `pipeline_engine/http/routes.py:38` (`service_available=False`), `:50-55`/`:72-77` (503-Pfad); `control_plane_http/app.py:191` (Stub-Instanziierung), `:76-81`/`:765-773`/`:414` (reale `story-runs`-Phasenrouten ueber `RuntimeService`); `control_plane/models.py:126-141` (`bc_unavailable_response` -> 503).
- **Reihenfolge zwingend:** AG3-123 (Backend-resolved Workspace) muss `completed` sein. Diese Story fuehrt **keine** Dispatch-Entkopplung durch — sie konsumiert sie.
- SSOT-Falle: NICHT eine zweite Phasen-Ausfuehrung neben `RuntimeService` bauen. Die Capability-Route MUSS denselben Kern-Pfad treiben wie die `story-runs`-Routen. Wenn unklar, welche Oberflaeche kanonisch ist: im Execution-Plan klaeren, nicht zwei Executoren materialisieren.
- 503-Hinweis: Der literale `503`-Statuscode ist **kein** im Konzept woertlich verankerter Capability-Vertrag (FK-10 §10.6 fordert nur Fail-closed-Verhalten). Der `503 *_unavailable`-Wire-Vertrag ist der von **AG3-090** (`completed`) etablierte Adapter-Standard (`bc_unavailable_response`); ihn beibehalten, nicht neu erfinden.
- AK2 NICHT veraendern. `.mcp.json` NICHT anfassen. Kein globaler `pip install`. Kein Commit ohne Auftrag.
- „done" nur mit Beleg: Diff-Zusammenfassung, gruene Pflichtbefehle + Remote-Gates, Real-Route-Test, 503-Negativtest, SSOT-Beleg, Phase-Status-Contract-Test, Phasengrenzen-Negativtest.

## 7. Vorbedingungen

- `depends_on: AG3-123` — startet erst, wenn AG3-123 `completed` ist (Backend-resolved Workspace vorhanden).
- Kern-Phasen-Capability (`ControlPlaneRuntimeService`/`PhaseDispatcher`) ist vorhanden und ueber den Backend-Resolver aufloesbar.
- `unblocks`: AG3-129, AG3-130 (Dokumentation; autoritativ ist deren `depends_on`).

---

## Globale Akzeptanzkriterien (verbindlich)

Zusaetzlich zu den obigen Akzeptanzkriterien gelten die **globalen Akzeptanzkriterien** aus `stories/_GLOBAL_ACCEPTANCE.md` (Single Source of Truth):

- **GAC-1:** `scripts/ci/check_architecture_conformance.py` laeuft mit **0 Errors** (Exit 0, fail-closed) — `PYTHONPATH=src .venv\Scripts\python scripts/ci/check_architecture_conformance.py`.
- **GAC-2:** Die Architektur-Guardrails `guardrails/architecture-guardrails.md` (ARCH-NN) werden eingehalten; Konflikt = hart stoppen und melden.
