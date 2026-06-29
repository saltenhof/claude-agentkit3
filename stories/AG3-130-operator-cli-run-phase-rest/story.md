# AG3-130: Operator-CLI `run-phase`/`resume` ruft die Control-Plane ueber REST statt in-process Runtime

**Typ:** Implementation / **Groesse:** M / **Bounded Context:** `control-plane` / Operator-Einstieg (CLI als Dev-Seite, FK-10 §10.1.2). Die `agentkit`-CLI ist im Topologie-Bild ein Dev-Client/Edge, kein Kern. Heute faehrt `run-phase` (und analog `resume`) die `ControlPlaneRuntimeService`/Pipeline-Engine **in-process** im CLI-Prozess hoch und greift darueber direkt auf den kanonischen State zu. Diese Story zieht den Operator-Einstieg auf die Soll-Rolle „REST-Anforderer am Kern" zurueck (I3): kanonische Phasen-Operationen laufen ausschliesslich per REST ueber das Backend.

**Quell-Konzepte (autoritativ):**
- `FK-10 §10.1.0 I3` — „Kanonische Ops nur via Kern": AK3-verantwortete kanonische Operationen (State, Gates, Phasenfortschritt) laufen **ausschliesslich per REST** ueber den Kern; innerhalb dieser Vorgaenge kein Bypass auf DB/Dienste/kanonischen State.
- `FK-10 §10.1.0 I1` — kein Dev-Prozess oeffnet eine direkte DB-Verbindung; PostgreSQL ist ausschliesslich Speicher des Kerns.
- `FK-10 §10.1.2` — Prozesslandschaft: die `agentkit` CLI ist Teil der duennen Dev-Seite (Operator-Einstieg), der deterministische Kern (4-Phasen-Pipeline) laeuft im Backend.
- `FK-10 §10.3.2` — State-/Ownership-Tabelle: Workflow-State wird von der **Pipeline-Fachlogik im Backend** geschrieben; Orchestrator/Status-Abfragen sind REST-Leser; „kein Direkt-DB-Zugriff (I1)".
- `FK-45` (`45_phase_runner_cli.md`) — Phase-Runner/Operator-Recovery-CLI ist Adapter auf die Control-Plane-API; AG3-076 hat die Verben in-process angedockt, AG3-130 zieht sie hinter REST.
- `FK-91 §91.1a` — REST-Endpunkt-Katalog: `phases/{phase}/{start|complete|fail}` existiert; **ein `resume`-Endpunkt fehlt** und wird in dieser Story ergaenzt (FK-91 + formale Command-Contracts mitziehen).

---

## 1. Kontext / Ist-Zustand (belegt)

Re-verifiziert gegen `src/agentkit/backend/cli/main.py` (Pfad in `var/abweichungskarte-zentralisierung.md` A6/D3 ohne `backend/`-Praefix notiert — korrekt ist `src/agentkit/backend/cli/main.py`):

- **`run-phase` faehrt die Runtime in-process:** `cli/main.py:1797` `_cmd_run_phase(...)`; `:1809` `from agentkit.backend.control_plane.runtime import ControlPlaneRuntimeService`; `:1851` `service = ControlPlaneRuntimeService()` direkt im CLI-Prozess. Der dispatchte Lauf greift ueber die Runtime auf das State-Backend zu (PostgreSQL via `postgres_store._connect_global()`), d. h. der DB-Zugriff ist **nicht** auf den Server-Prozess beschraenkt — die CLI umgeht die REST-Grenze.
- **`resume` ebenfalls in-process:** `cli/main.py:1886` `_cmd_resume(...)` baut ueber `agentkit.backend.bootstrap.composition_root` (`build_pipeline_engine`, `build_phase_envelope_store`, `cli_load_story_context`, `:1899-1903`) die Pipeline-Engine lokal auf und ruft `resume_phase` — gleicher in-process State-Zugriff im CLI-Prozess.
- **Vorhandene Hebel:** Es existiert bereits eine real bediente Server-Seite fuer Phasen-Uebergaenge (Phase start/complete/fail) ueber `control_plane_http` (WP-D4 der Abweichungskarte; `control_plane_http/app.py`). Der Phasen-Dispatch im Backend ist heute an einen lokalen `project_root`/Worktree gekoppelt (WP-D2) — die Deployment-Aufloesung dieser Kopplung ist **Out of Scope** dieser Story (siehe §2.2); AG3-130 stellt nur den CLI-Eintritt von in-process auf REST um.
- **Folge:** Der Operator-Einstieg ist ein zweiter, dev-seitiger Ausfuehrungsort des Kerns — Verstoss gegen FK-10 I1/I3.

## 2. Scope

### 2.1 In Scope
1. **`run-phase` ruft die Control-Plane ueber REST.** `_cmd_run_phase` (`cli/main.py:1797`) instanziiert **keine** `ControlPlaneRuntimeService()` mehr in-process, sondern sendet einen `/v1`-Request an das Backend, das die Phase ausfuehrt. Die CLI sammelt Eingaben (story/run/session/principal/phase/project), validiert sie weiterhin lokal (Argument-/Phasen-Validierung bleibt CLI-seitig zulaessig) und delegiert die **Ausfuehrung** an den Kern.
2. **`resume` ruft die Control-Plane ueber REST.** `_cmd_resume` (`cli/main.py:1886`) baut **keine** Pipeline-Engine mehr in-process (`composition_root.build_pipeline_engine`/`build_phase_envelope_store` raus aus dem CLI-Pfad), sondern delegiert den Resume des PAUSED-Phasenzustands an den Backend-Endpunkt. **Ein `resume`-REST-Endpunkt existiert heute nicht** (nur start/complete/fail) — er wird als duenne `control_plane_http`-Route + `ProjectEdgeClient`-Methode + FK-91-/Formal-Command-Contract ergaenzt (kein Capability-Stub als „done").
3. **Kein Direkt-DB aus dem CLI-Prozess** fuer diese Vorgaenge: nach der Story enthaelt der `run-phase`/`resume`-Pfad keine in-process State-Backend-/Runtime-Instanziierung und keinen `postgres_store`/`_connect_global`-Pfad.
4. **REST-Client** auf dem etablierten Dev-Client-Muster (`harness_client/projectedge/client.py` `ProjectEdgeClient`, `urllib`, strukturierte `ApiError`-Behandlung); kein zweiter paralleler HTTP-Stack. Strukturierte Fehlerantworten des Kerns (4xx/5xx) werden in die bestehenden CLI-Exit-Codes/Meldungen uebersetzt (heute z. B. `:1814/:1825/:1829/:1847/:1858`).
5. **Negativpfad-Tests** (Pipeline-/CLI-Logik, Testing-Guardrails): Backend unerreichbar/Fehlerantwort → CLI gibt fail-closed Exit != 0 mit strukturierter Meldung, kein in-process Fallback; gueltiger Lauf → server-vermittelte Phasenausfuehrung. Plus Regressionspin, dass `run-phase`/`resume` keine `ControlPlaneRuntimeService()`/`build_pipeline_engine`-Instanz im CLI-Prozess mehr erzeugen.

### 2.2 Out of Scope (mit Owner)
- **Aufloesung der `project_root`/Worktree-Kopplung des Backend-Dispatchs** (WP-D2, Mark & Ask #4 Deployment) — **nicht** AG3-130. Diese Story aendert nur den CLI-Eintrittspfad (in-process → REST), nicht das Deployment-Modell des Phasen-Dispatchs.
- **Capability-Routen-Vollausbau (503-Stubs der schweren Capabilities, WP-D1)** — eigene Stories.
- **Hook-Prozess → Backend-REST** (Guard-Counter/Worker-Health/Telemetrie) — **AG3-129** (andere Dev↔Kern-Kante).
- **CCAG/Permission/Mode-Lock-Zentralisierung** — **AG3-131**.
- **Weitere CLI-Verben** (Installer, `register-project` etc.) — nicht betroffen.
- **Weitere in-process Operator-CLI-Pfade (explizit benannt, nicht still gelassen):** `status`, `query-state`, `query-telemetry`, `export-telemetry`, `reset-story`, `split-story`, `exit-story` komponieren heute ebenfalls Backend-/State-Services in-process im CLI-Prozess (`cli/main.py:1032+`). Sie sind **nicht** Teil dieser Story, aber dieselbe I1/I3-Topologie-Schuld; sie werden als **eigene Folge-Story(s)** gezogen (offen, vom PO zu schneiden) — damit die Rest-Schuld dokumentiert und nicht stillschweigend offen bleibt (ZERO DEBT: melden statt verschweigen).

### 2.3 Betroffene Dateien

| Datei | Aenderungsart |
|---|---|
| `src/agentkit/backend/cli/main.py` | Aendern (`_cmd_run_phase:1797`, `_cmd_resume:1886` → REST statt in-process; keine `ControlPlaneRuntimeService()`/`build_pipeline_engine`) |
| `src/agentkit/harness_client/projectedge/client.py` | Aendern (run-phase-/resume-REST-Methoden, `ProjectEdgeClient`-Muster) |
| `src/agentkit/backend/control_plane_http/app.py` (+ ggf. `pipeline_engine/http`) | Aendern/Neu (**neuer `resume`-Endpunkt**; run-phase-Ausfuehrungsroute) |
| `concept/technical-design/91_api_event_katalog.md` + `concept/formal-spec/**` | Aendern (FK-91-Vertrag fuer `resume`/run-phase) |
| `tests/integration/**`, `tests/unit/cli/**`, `tests/contract/**` | Neu/Aendern (echte CLI→HTTP-Route, Unreachable-fail-closed je Verb, Import-Regression) |

## 3. Akzeptanzkriterien
1. `run-phase` (`_cmd_run_phase`) instanziiert **keine** `ControlPlaneRuntimeService()` in-process mehr und ruft die Phasenausfuehrung ueber einen Backend-`/v1`-Endpunkt; **echter Integrationstest** (CLI → reale `ControlPlaneApplication`-Route, kein Mock) belegt den REST-Pfad (kein in-process Runtime-Build).
2. `resume` (`_cmd_resume`) baut **keine** Pipeline-Engine in-process (`build_pipeline_engine`/`build_phase_envelope_store` nicht mehr im CLI-Pfad) und delegiert den Resume an den Kern per REST; Test belegt den REST-Pfad.
3. Der `run-phase`/`resume`-Pfad oeffnet **keine** PostgreSQL-Verbindung im CLI-Prozess (kein `_connect_global`/`postgres_store`-Pfad; Static-/Import-Check + Test).
4. **Fail-closed (Negativpfad-Pflicht):** Backend unerreichbar/Fehlerantwort → CLI-Exit != 0 mit strukturierter Meldung, kein in-process Fallback (eigener Negativpfad-Test je Verb).
5. Strukturierte Kern-Fehlerantworten (4xx/5xx) werden auf die bestehenden CLI-Exit-Code-/Meldungssemantiken abgebildet (Konsistenz mit dem heutigen Verhalten an `:1814`/`:1825`/`:1829`/`:1847`/`:1858`).
6. Der REST-Client folgt dem `ProjectEdgeClient`-Muster; **kein** zweiter paralleler HTTP-Transport (SINGLE SOURCE OF TRUTH).
7. ARCH-55: alle Bezeichner/Wire-Keys/`error_code`-Werte englisch; keine unbegruendeten `noqa`/`type: ignore`.
8. **Quality-Gates gruen** (Repo-Root, via `.venv`, GAC-konform):
   - `.venv\Scripts\python -m pip install -e ".[dev]"`; `.venv\Scripts\python -m pytest` (unit/integration/contract, `-n0`); Coverage >= 85 % (`--cov=agentkit --cov-fail-under=85`).
   - `.venv\Scripts\python -m mypy src` **und** `--platform linux` (strict); `.venv\Scripts\python -m ruff check src tests`.
   - Konzept-/Architektur-Gates (GAC-1): `scripts/ci/check_architecture_conformance.py`, `scripts/ci/check_concept_frontmatter.py`, `scripts/ci/check_concept_code_contracts.py`, `scripts/ci/compile_formal_specs.py` (FK-91-Aenderung zieht diese mit).
   - **Remote-Gates** (`pwsh scripts/ci/check_remote_gates.ps1`): **Jenkins-Build gruen** und **SonarQube Zero-Violation** (`violations=0`, `critical_violations=0`, `security_hotspots=0` auf New Code).

## 4. Definition of Done
- AK 1–8 erfuellt; QA-/Code-Gate (Codex-Review) PASS; Status-Update gemaess `stories/README.md` §4.4. Implementierung/Commit erst nach Freigabe.
- Globale Akzeptanzkriterien (siehe unten) erfuellt.

## 5. Guardrail-Referenzen
- **FIX THE MODEL, NOT THE SYMPTOM:** Der Operator-Einstieg wird strukturell zum REST-Anforderer; kein zweiter Ausfuehrungsort des Kerns im CLI-Prozess.
- **FAIL-CLOSED:** Unerreichbarer Kern → CLI-Fehler, kein in-process Fallback.
- **SINGLE SOURCE OF TRUTH / KEINE FACHLOGIK IN ADAPTERN:** Phasen-Fachlogik bleibt im Backend; die CLI bleibt duenner Client.
- **NO ERROR BYPASSING:** Keine Umgehung der REST-Grenze ueber lokale Runtime-Builds.
- **ARCH-55** und **GAC-2 / ARCH-NN** (`guardrails/architecture-guardrails.md`).

## 6. Hinweise fuer den Sub-Agent
- Read T:/codebase/claude-agentkit3/CLAUDE.md first — all project rules apply to you.
- Ist-Anker (re-verifizieren): `src/agentkit/backend/cli/main.py:1797` (`_cmd_run_phase`), `:1809` Import, `:1851` `ControlPlaneRuntimeService()`; `:1886` (`_cmd_resume`), `:1899-1903` (`composition_root.build_pipeline_engine`/`build_phase_envelope_store`/`cli_load_story_context`). Argparse-Wiring: `:346`/`:347` (Dispatch), `:1679-1699` (`run-phase`), `:1703` (`resume`).
- Server-Seite: die real bedienten Phasen-Routen leben in `control_plane_http` (`app.py`); pruefe, ob ein passender `/v1`-Phasen-/Resume-Endpunkt existiert oder als duenne Route ergaenzt werden muss (kein Capability-Stub als „done").
- **Deployment-Kopplung (`project_root`/Worktree, WP-D2) NICHT aufloesen** — das ist bewusst Out of Scope. Nur den CLI-Eintritt umstellen.
- REST-Client-Muster: `harness_client/projectedge/client.py` (`ProjectEdgeClient`). Keinen zweiten HTTP-Stack bauen.
- Negativpfad ist Pflicht. Kein Commit ohne Auftrag. „done" nur mit Beleg: Diff, Test-Namen (inkl. Negativpfade), gruene Pflichtbefehle.

## 7. Vorbedingungen
- `depends_on: AG3-123, AG3-124` muessen `completed` sein (Phasen-REST-Route bzw. Dev-Client-Vorarbeiten). Solange offen: `status: blocked`, nicht starten.
- Erreichbares zentrales State-Backend fuer Integrationstests; Test-DB auf ephemerem Port (nie 5432).

---

## Globale Akzeptanzkriterien (verbindlich)

Zusaetzlich zu den obigen Akzeptanzkriterien gelten die **globalen Akzeptanzkriterien** aus `stories/_GLOBAL_ACCEPTANCE.md` (Single Source of Truth):

- **GAC-1:** `scripts/ci/check_architecture_conformance.py` laeuft mit **0 Errors** (Exit 0, fail-closed) — `PYTHONPATH=src .venv\Scripts\python scripts/ci/check_architecture_conformance.py`.
- **GAC-2:** Die Architektur-Guardrails `guardrails/architecture-guardrails.md` (ARCH-NN) werden eingehalten; Konflikt = hart stoppen und melden.
