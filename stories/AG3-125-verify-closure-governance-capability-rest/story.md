# AG3-125: `verify_system` + `closure` + `governance` `http` — 503-Stubs zu realen server-seitigen Capability-Routen

**Typ:** Implementation / **Groesse:** L / **Bounded Context:** `verify_system`, `closure`, `governance` / BFF-Capability-Routen (FK-72 §72.8.2). Die drei Capability-Routen (`/v1/projects/{key}/verify`, `/closure`, `/governance`) sind heute 503-Stubs (`service_available=False`) — BFF-Huellen ohne reale Vermittlung. Diese Story aktiviert sie als **reale server-seitige Capability-Routen**, die QA-Subflow/VerifySystem, Closure-Sequenz und Governance ueber den deterministischen Kern treiben — keine in-process Dev-Ausfuehrung. Gleicher Aktivierungs-Schnitt wie AG3-124, nur fuer die drei weiteren Capabilities. Baut auf dem Backend-resolved Workspace aus **AG3-123** auf.

**Quell-Konzepte (autoritativ):**
- `FK-10 §10.1.0 I3` (`10-1-laufzeitkomponenten-001`) — kanonische Operationen (State, **Gates**, Phasenfortschritt) laufen ausschliesslich per REST ueber den Kern.
- `FK-10 §10.2.3` (`10-2-deployment-modell-002`) — QA-Subflow, Closure, Governance, Policy sind der AK3-Kern und laufen im Backend; Autoritaet wird nicht delegiert.
- `FK-72 §72.8 / §72.8.2` (`72-8-bff-topologie-008`) — Modul-Topologie/Mounts: `verify_system/http -> /v1/projects/{key}/verify`, `closure/http -> /closure`, `governance/http -> /governance`; ein Server-Prozess, pro BC ein Routes-Modul. FK-72 §72.8.2 ist **nur Topologie**; „der offizielle API-Vertrag im Detail liegt in FK-91".
- **Konzept/Code-Contract-Lücke (zu beachten):** FK-91 §91.1a fuehrt die konkreten Endpunkt-Vertraege fuer `/verify`, `/closure`, `/governance` **noch nicht** auf (nur die `story-runs`-Phasen-/Closure-Routen + Topic `gates`). Diese Story erfindet **keinen** zweiten kanonischen Vertrag: die Routen sind BC-Adapter ueber den bestehenden Kern-Pfad (Closure: bestehender `story-runs/.../closure/complete`). Eine echte FK-72↔FK-91-Kollision ist als Konzept-Konflikt zu **melden** (CLAUDE.md), nicht durch Doppel-Endpunkt aufzuloesen.
- `concept/_meta/bc-cut-decisions.md` „Verify als Capability (Variante Y)" + `00_index.md §9.13` — `verify-system` ist **Capability-BC**, kein Phase-Owner: aus `ExplorationPhase` (Exit-Gate, FK-23 §23.5) und `ImplementationPhase` (QA-Subflow, FK-27) aufgerufen; eine Top-Phase `verify` existiert nicht.
- `FK-91 §91.2` (`91-2-telemetrie-event-typen-003-02`) — REST-Aufrufe sind nur Producer-Pfade auf den Event-Katalog; keine abweichenden Event-Namen/Payloads. / `FK-91 §91.8` (`91-8-live-event-streams-sse-009`) — Topic `gates` (Owner `verify_system`, Wire `gate_evaluated`).
- `FK-10 §10.6` (`10-6-fehlerbehandlung-und-recovery-006`) — Fail-closed bei nicht erreichbarem/aufloesbarem Kern.

---

## 1. Kontext / Ist-Zustand (belegt)

Re-verifiziert am aktuellen Code (`src/agentkit/backend/`):

- `verify_system/http/routes.py:35` — `VerifySystemRoutes.service_available: bool = False`; `handle_get` (`:47-52`)/`handle_post` (`:69-74`) liefern bei Default eine strukturierte 503 `verify_unavailable` ueber `bc_unavailable_response`.
- `closure/http/routes.py:35` — `ClosureRoutes.service_available: bool = False`; 503 `closure_unavailable` (`:47-52`/`:69-74`).
- `governance/http/routes.py:35` — `GovernanceRoutes.service_available: bool = False`; 503 `governance_unavailable` (`:47-52`/`:69-74`).
- `control_plane_http/app.py:197` (`VerifySystemRoutes()`), `:203` (`GovernanceRoutes()`), `:209` (`ClosureRoutes()`) — alle drei **ohne Argument** instanziiert -> `service_available=False` -> in Produktion 503-Stubs.
- `control_plane/models.py:126-141` — `bc_unavailable_response(...)` -> `HTTPStatus.SERVICE_UNAVAILABLE` (503), fail-closed; Wire-Vertrag etabliert von **AG3-090** (`completed`).
- **Reale Teil-Vermittlung existiert nur fuer Closure-Abschluss:** `control_plane_http/app.py:81` (`POST /v1/projects/{key}/story-runs/{run_id}/closure/complete`), Handler `:775-781` ueber `self._runtime_service` (`:414`). Fuer `verify`/`governance` gibt es **keine** reale BC-Route (D1).
- **Voraussetzung AG3-123:** der Kern-Dispatch war an `ctx.project_root` (dev-lokal) gekoppelt (`dispatch.py:835-841`, `runtime.py:843-847`); AG3-123 macht ihn Backend-resolved. Erst damit sind echte server-seitige Capability-Routen ohne Dev-FS-Annahme moeglich.

**Konsequenz:** `verify_system`, `closure` und `governance` haben (bis auf den Closure-Complete-Record) keine reale BC-REST-Vermittlung (WP-D, D1). Diese Story aktiviert die drei Capability-Routen auf dem Kern-Pfad — kein in-process Dev-Run.

## 2. Scope

### 2.1 In Scope

1. **`VerifySystemRoutes`, `ClosureRoutes`, `GovernanceRoutes` real verdrahten.** `service_available` wird produktiv `True`, sobald die jeweilige Kern-Capability (VerifySystem/QA-Subflow, Closure-Sequenz, Governance, Backend-resolved per AG3-123) injiziert ist. Die Routen delegieren an den Kern — **keine** Fachlogik im Adapter (duenne `http/`-Adapter).
2. **Capability-Injektion** in `control_plane_http/app.py:197/203/209`: statt der Default-Stubs werden die Routen mit den realen Capability-Ports gebaut. Wo der Kern aufloesbar ist, `service_available=True`; sonst bleibt der **fail-closed** 503-Pfad (FK-10 §10.6).
3. **`verify_system/http` (`/verify`)** vermittelt VerifySystem als **Capability** (BC-Cut „Verify als Capability"): Aufruf-Punkte sind Exit-Gate der Exploration (FK-23 §23.5) und QA-Subflow der Implementation (FK-27) — die Route fuehrt **keine** eigenstaendige Top-Phase `verify` ein und erzeugt keinen zweiten QA-Executor. Gate-Ergebnisse folgen dem Event-Katalog (Topic `gates`/`gate_evaluated`, FK-91 §91.8), keine abweichenden Namen (FK-91 §91.2).
4. **`closure/http` (`/closure`)** vermittelt die Closure-Sequenz (Integrity-Gate, Merge/Cleanup, Abschluss) ueber den Kern. Verhaeltnis zum bestehenden `story-runs/.../closure/complete`-Record (`app.py:81`, `:775-781`) wird **SSOT-konform** aufgeloest: kein zweiter paralleler Closure-Executor; beide Oberflaechen treiben denselben Kern-Pfad.
5. **`governance/http` (`/governance`)** vermittelt Governance-Capability-Reads/-Operationen ueber den Kern (kanonischer Permission-/Guard-State liegt zentral, I5/§10.2.0); der Adapter haelt keine projektlokale kanonische Wahrheit.
6. **Fail-closed-Vertrag erhalten** fuer alle drei: Capability absent/nicht aufloesbar -> strukturierte 503 `verify_unavailable` / `closure_unavailable` / `governance_unavailable` (kein 200-Leer-OK, kein bare-500), AG3-090-Wire-Vertrag (`bc_unavailable_response`).
7. **Tests** (Pflicht, §3): reale Route trifft den Kern (je Capability), Negativpfad (Capability absent -> 503, je Capability), SSOT-Beleg (kein zweiter Executor fuer Verify/Closure), Phasengrenzen-Negativtest (z. B. Closure-Gate blockt fail-closed bei nicht erfuellter Vorbedingung), Vertragstest fuer Gate-Event-Vokabular.

### 2.2 Out of Scope (mit Owner)

- **`project_root`-Entkopplung des Dispatch** — **AG3-123** (`depends_on`); vorausgesetzt, nicht gebaut.
- **`pipeline_engine/http` Aktivierung** — **AG3-124** (Phasen-Capability; gleiche Achse, eigene Story).
- **Drittsystem-Vermittlung selbst (Sonar/Jenkins/ARE im QA-/Pre-Merge-Pfad, WP-B)** — **AG3-132** (baut auf dieser Capability-Aktivierung auf). Diese Story aktiviert die Route, nicht die 3rd-party-Vermittlung dahinter.
- **LLM-Hub-Eval-Locus / Verify-Layer-2 produktive Anbindung (WP-C, C5)** — **AG3-133** (baut auf dieser Aktivierung auf).
- **Konkrete Read-Model-Payloads / KPI / SSE-Producer** — AG3-08x/AG3-09x.
- **`artifacts/http`, `failure_corpus/http`, `requirements_coverage/http`** (weitere 503-Stubs) — ausserhalb dieses Schnitts.

### 2.3 Betroffene Dateien

| Datei | Aenderungsart |
|---|---|
| `src/agentkit/backend/verify_system/http/routes.py` | Aendern (`service_available` real; Delegation an VerifySystem-Capability) |
| `src/agentkit/backend/closure/http/routes.py` | Aendern (Delegation an Closure-Sequenz-Kern; SSOT mit `closure/complete`) |
| `src/agentkit/backend/governance/http/routes.py` | Aendern (Delegation an Governance-Kern; zentraler State) |
| `src/agentkit/backend/control_plane_http/app.py` | Aendern (`VerifySystemRoutes/ClosureRoutes/GovernanceRoutes` mit realen Ports statt Default-Stub `:197/203/209`) |
| `src/agentkit/backend/{verify_system,closure,governance}/` (Capability-Ports/DTO, falls noetig) | Neu/Aendern |
| `tests/unit/{verify_system,closure,governance}/http/test_routes.py` | Aendern (Real-Delegation statt `service_available`-Toggle) |
| `tests/integration/control_plane_http/**`, `tests/contract/**` | Neu/Aendern (echte HTTP-Routing-Integration je BC; 503-Negativpfade; Gate-Event-Vokabular) |

## 3. Akzeptanzkriterien

1. `VerifySystemRoutes`, `ClosureRoutes`, `GovernanceRoutes` sind in `control_plane_http` mit den realen Kern-Capabilities verdrahtet; bei aufloesbarem Kern treiben `/verify`, `/closure`, `/governance` die jeweilige Capability ueber den Kern. **Echter HTTP-Routing-Integrationstest je Modul (keine Stub-Absicherung):** ein realer Request durch `ControlPlaneApplication` erreicht den **realen injizierten Capability-Port** und der Test verifiziert die Wirkung (Gate-Ergebnis/Closure-Record/Governance-Read) — **nicht** ein `service_available=True`-Toggle mit Dummy-200/202.
2. **Keine in-process Dev-Ausfuehrung:** alle drei Routen fuehren ihre Capability ueber den server-seitigen Kern aus (Backend-resolved Workspace aus AG3-123); kein Code-Pfad fuehrt Verify/Closure/Governance im Dev-/CLI-Prozess aus, um die Route zu bedienen (SSOT-Test je Capability).
3. **Fail-closed:** Capability absent/nicht aufloesbar -> strukturierte 503 `verify_unavailable`/`closure_unavailable`/`governance_unavailable` (kein 200-Leer-OK, kein bare-500) — Negativtest je Modul.
4. **`verify` ist Capability, keine Top-Phase (BC-Cut „Verify als Capability"):** die Route ruft VerifySystem als Capability (Exploration-Exit-Gate / Implementation-QA-Subflow); kein zweiter QA-Executor und keine neue Top-Phase `verify` entstehen (Architektur-/SSOT-Beleg).
5. **SSOT der Closure-Ausfuehrung:** `closure/http` und der bestehende `story-runs/.../closure/complete`-Pfad (`app.py:81`, `:775-781`) treiben denselben Kern-Closure-Pfad; kein zweiter paralleler Closure-Executor (Test/Architektur-Beleg).
6. **Vertrags-/Vokabular-Treue:** Gate-/Verify-Ergebnis-Events folgen dem Event-Katalog (FK-91 §91.8, Topic `gates`/`gate_evaluated`); keine abweichenden Event-Namen/Payloads (FK-91 §91.2) — Contract-Test pinnt das Vokabular.
7. **Phasengrenzen-/Negativpfad-Pflicht (testing-guardrails):** mindestens ein gueltiger und ein ungueltiger Uebergang sind verprobt — z. B. Closure-/Integrity-Gate blockt fail-closed bei nicht erfuellter Vorbedingung; QA-Subflow-Gate liefert nur bei erfuellter Evidenz PASS.
8. `X-Correlation-Id`- und `BcRouteResponse`/`ApiErrorResponse`-Form gelten unveraendert fuer alle drei Routen (Test: Fehlerantwort traegt Correlation-Id + `error_code`).
9. **ARCH-55:** alle Pfadsegmente, Modul-/Methodennamen, `error_code`-Werte, Bezeichner und Kommentare englisch. Keine `noqa`/`type: ignore` ohne Begruendung.
10. **Quality-Gates gruen** (Repo-Root, via `.venv`, GAC-konform):
    - `.venv\Scripts\python -m pip install -e ".[dev]"`; `.venv\Scripts\python -m pytest tests/unit -n0`, `tests/integration -n0`, `tests/contract -n0`; Coverage >= 85 % (`--cov=agentkit --cov-fail-under=85`).
    - `.venv\Scripts\python -m mypy src` **und** `--platform linux` (strict); `.venv\Scripts\python -m ruff check src tests`.
    - Konzept-/Architektur-Gates (GAC-1): `scripts/ci/check_architecture_conformance.py`, `scripts/ci/check_concept_frontmatter.py`, `scripts/ci/check_concept_code_contracts.py`, `scripts/ci/compile_formal_specs.py`.
    - **Remote-Gates** (`pwsh scripts/ci/check_remote_gates.ps1`): **Jenkins-Build gruen** und **SonarQube Zero-Violation** (`violations=0`, `critical_violations=0`, `security_hotspots=0` auf New Code).

## 4. Definition of Done

- AK 1–10 erfuellt; QA-Gate (Codex-Review) **PASS** + Standard-Pflichtbefehle + Remote-Gates (Jenkins/Sonar) gruen. Implementierung/Commit erst nach Execution-Plan-Freigabe. Entblockt AG3-129, AG3-132, AG3-133.

## 5. Guardrail-Referenzen

- **FIX THE MODEL / SINGLE SOURCE OF TRUTH:** je Capability **eine** Ausfuehrungs-Wahrheit (Kern-Pfad); die Routen sind Vermittler, kein zweiter Executor (besonders kritisch bei Closure und Verify).
- **FAIL CLOSED:** Capability absent -> strukturierte 503; nie stilles Leer-OK (FK-10 §10.6, `bc_unavailable_response`).
- **KEINE FACHLOGIK IN ADAPTERN:** `verify_system/http`, `closure/http`, `governance/http` bleiben duenne Adapter; QA-/Closure-/Governance-Fachlogik bleibt im Kern.
- **TYPISIERT STATT STRINGS:** Gate-/Ergebnis-Vertraege typisiert; Event-Vokabular aus FK-91 §91.8/§91.2.
- **NO ERROR BYPASSING:** QA-/Integrity-/Permission-Gates bleiben scharf ueber die Routen; QA-Artefakte bleiben geschuetzt (Worker manipuliert eigene QA-Ergebnisse nicht).
- **WORKFLOW-/STATE-DISZIPLIN:** `verify` bleibt Capability (BC-Cut „Verify als Capability"), keine neue Top-Phase; Governance-State zentral (I5).
- **GAC-2 / ARCH-NN:** `guardrails/architecture-guardrails.md` einhalten; ARCH-55 (Englisch) verbindlich.

## 6. Hinweise fuer den Sub-Agent

- Read T:/codebase/claude-agentkit3/CLAUDE.md first — all project rules apply to you.
- Ankerpunkte (aktueller Code unter `src/agentkit/backend/`): `verify_system/http/routes.py:35`, `closure/http/routes.py:35`, `governance/http/routes.py:35` (alle `service_available=False`, 503-Pfade `:47-52`/`:69-74`); `control_plane_http/app.py:197/203/209` (Stub-Instanziierung), `:81`/`:775-781` (realer Closure-Complete-Record ueber `RuntimeService`), `:414`; `control_plane/models.py:126-141` (`bc_unavailable_response` -> 503).
- **Reihenfolge zwingend:** AG3-123 (Backend-resolved Workspace) muss `completed` sein. Diese Story fuehrt **keine** Dispatch-Entkopplung durch.
- SSOT-Falle (kritisch): NICHT einen zweiten Verify- oder Closure-Executor neben dem Kern bauen. `verify` ist Capability, keine Top-Phase (BC-Cut „Verify als Capability") — keine neue Phase einziehen.
- Abgrenzung: Die **3rd-party-Vermittlung** (Sonar/Jenkins/ARE) im QA-/Pre-Merge-Pfad ist **AG3-132**, die **Hub-Eval-Locus**-Frage **AG3-133** — beide bauen auf dieser Aktivierung auf, gehoeren aber NICHT in diese Story.
- 503-Hinweis: Der literale `503`-Statuscode ist **kein** im Konzept woertlich verankerter Vertrag (FK-10 §10.6 fordert nur Fail-closed-Verhalten). Der `503 *_unavailable`-Wire-Vertrag ist der von **AG3-090** (`completed`) etablierte Adapter-Standard; beibehalten, nicht neu erfinden.
- AK2 NICHT veraendern. `.mcp.json` NICHT anfassen. Kein globaler `pip install`. Kein Commit ohne Auftrag.
- „done" nur mit Beleg: Diff-Zusammenfassung, gruene Pflichtbefehle + Remote-Gates, Real-Route-Tests (3x), 503-Negativtests (3x), SSOT-Belege (Verify/Closure), Gate-Event-Contract-Test, Phasengrenzen-Negativtest.

## 7. Vorbedingungen

- `depends_on: AG3-123` — startet erst, wenn AG3-123 `completed` ist (Backend-resolved Workspace vorhanden).
- Kern-Capabilities (VerifySystem/QA-Subflow, Closure-Sequenz, Governance) sind vorhanden und ueber den Backend-Resolver aufloesbar.
- `unblocks`: AG3-129, AG3-132, AG3-133 (Dokumentation; autoritativ ist deren `depends_on`).

---

## Globale Akzeptanzkriterien (verbindlich)

Zusaetzlich zu den obigen Akzeptanzkriterien gelten die **globalen Akzeptanzkriterien** aus `stories/_GLOBAL_ACCEPTANCE.md` (Single Source of Truth):

- **GAC-1:** `scripts/ci/check_architecture_conformance.py` laeuft mit **0 Errors** (Exit 0, fail-closed) — `PYTHONPATH=src .venv\Scripts\python scripts/ci/check_architecture_conformance.py`.
- **GAC-2:** Die Architektur-Guardrails `guardrails/architecture-guardrails.md` (ARCH-NN) werden eingehalten; Konflikt = hart stoppen und melden.
