# AG3-127: Telemetry- und project_management-Read-Ports — BFF-Durchgriff auf `state_backend.store` entkoppeln

**Typ:** Implementation / **Groesse:** M / **Bounded Context:** `telemetry-and-events` und `project-management` (A-Code), Read-Seite. Beide BCs liefern UI-Read-Sichten (Telemetrie-Events/SSE, Projektliste/-Felder). Heute haengt die Telemetrie-Event-Read-Quelle BC-intern direkt an der `state_backend.store`-Fassade; project_management hat bereits Protocol-Ports, aber die Read-Kante muss als veroeffentlichter Port konsolidiert und der Adapter-Besitz sauber ins State-Backend gezogen werden. Diese Story gibt beiden BCs eine echte Read-Port-Kante analog dem Story-Port aus AG3-126.

**Quell-Konzepte (autoritativ):**
- `FK-07 §7.6` (`concept/technical-design/07_komponentenarchitektur_und_architekturkonformanz.md`) — Repository-Regel: Telemetrie-/Projekt-Read-Zustand wird ausschliesslich ueber die fachlichen Read-/Query-Ports der owning Component gelesen, nicht ueber die generische Mega-Fassade.
- `FK-07 §7.7.5` — Pflichtabdeckung Read-Surface-Grenzen: globale Reads (inkl. `execution_events`) nur ueber die fachlich benannte Repository-Kante.
- `FK-07 §7.8 Punkt 8` — Import-Grenze: A-Komponenten/BFF duerfen die generischen `state_backend.store`-Loader nicht direkt importieren; nur ueber die freigegebene Komponentenoberflaeche.
- `FK-07 §7.9 Punkt 10` — BFF-/HTTP-Entry-Boundaries komponieren Cross-BC-Read-Models aus veroeffentlichten BC-Ports, nie ueber Persistenz-Durchgriff; analog Punkt 9 (Read-Surface-Disziplin der `*.repository`-Kanten).
- `FK-72 §72.8` (`72-8-bff-topologie-008`, Z.187-206) — **normativer BFF-Anker:** der BFF liest UI-Sichten ueber veroeffentlichte Read-/Query-Ports der BCs.
- `FK-62 §62.6.1` — Komponenten-Ownership (Read-Seite): der KPI-/Dashboard-Bereich liest Runtime-Zustand ausschliesslich ueber einen benannten Read-Accessor (`ProjectionAccessor`), nicht ueber Direktzugriff — das Muster „benannter Read-Port statt Direktkopplung" gilt sinngemaess fuer die Telemetrie-Event-Read-Quelle.
- `FK-72 §72.2` — kein God-View/Cockpit-Aggregator; `FK-72 §72.14` — Frontend-Datenvertraege (Read-Models, Live-Events) sind in `formal.frontend-contracts.*` formalisiert; die BFF-Read-Kante muss diese Vertraege ueber BC-Ports bedienen.

---

## 1. Kontext / Ist-Zustand (belegt) — gegen den CURRENT-Code re-verifiziert

> **Drift-Hinweis (belegt):** `var/abweichungskarte-zentralisierung.md` (WP-I, I-2/I-3/I-4) verortet den Durchgriff teils noch im BFF (`control_plane_http/app.py` direkte `state_backend.store.*`-Imports, `read_model_routes.py` injiziert `StateBackend*`-Adapter). Gegen den **aktuellen** Code stimmt das nicht mehr: der BFF importiert `state_backend.store` nicht mehr direkt, und `read_model_routes.py` konsumiert bereits Protocol-Ports. Der verbleibende echte Durchgriff sitzt **BC-intern** in der Telemetrie-Event-Read-Quelle. Diese Story arbeitet gegen den aktuellen Stand, nicht gegen die Karte.

**Telemetry (Hauptdelta):**
- `src/agentkit/backend/telemetry/sse_stream.py:10` importiert `load_execution_events_for_project_global` **direkt** aus `agentkit.backend.state_backend.store.facade`.
- `:48-58` definiert das Protocol `ProjectTelemetryEventSource` (Read-Seam vorhanden), aber `:61-71` `StateBackendProjectTelemetryEventSource` ist ein konkreter, an die `state_backend.store`-Fassade gekoppelter Adapter, der **innerhalb** des Telemetrie-BC lebt.
- `src/agentkit/backend/telemetry/http/routes.py:38-39` defaultet die SSE-Route direkt auf `StateBackendProjectTelemetryEventSource()` — der Telemetrie-BC verdrahtet seinen eigenen State-Backend-Adapter, statt ihn per Composition-Root injiziert zu bekommen. Es gibt **kein** `telemetry/repository.py` als veroeffentlichten Read-Port.

**project_management (Teil-konform — konsolidieren):**
- `src/agentkit/backend/project_management/repository.py:11-21` definiert bereits `ProjectRepository(Protocol)` (Read-Port vorhanden).
- `src/agentkit/backend/project_management/read_model_routes.py:48,53,55,57` konsumiert injizierte Protocol-Ports (`StoryRepository`, `ParallelizationConfigRepository`, `ProjectRepository`, `StoryAreLinkRepository`); die `StateBackend*`-Adapter werden im Composition-Root (`bootstrap/composition_root.py:547` `project_management_repository`, `:557` `parallelization_config_repository`, `:560` `story_are_link_repository`) verdrahtet. Die Tenant-Scope-Middleware (`control_plane_http/tenant_scope.py:49-54`) zieht `ProjectRepository` ueber `build_project_repository` — bereits portbasiert.
- Restarbeit project_management: bestaetigen/konsolidieren, dass `ProjectRepository`, `ParallelizationConfigRepository` (`execution_planning/repository.py`), `StoryAreLinkRepository` (`requirements_coverage/repository.py`) die **einzige** BFF-Read-Kante sind und kein Read-Pfad mehr direkt an `state_backend.store`-Repos haengt; die `StoryRepository`-Nutzung in `read_model_routes.py:48` laeuft nach AG3-126 ueber den dortigen Port.

## 2. Scope

### 2.1 In Scope

1. **Telemetrie-Read-Port veroeffentlichen:** ein benannter Read-Port fuer projekt-skopierte Execution-Event-Reads (z. B. `telemetry`-Read-Surface-Modul mit dem `ProjectTelemetryEventSource`-Protocol als Vertrag). Der konkrete, `load_execution_events_for_project_global`-gestuetzte Adapter wird **aus dem Telemetrie-BC heraus** nach `agentkit.backend.state_backend.store` verlagert (analog Story-Adapter AG3-126) und im Composition-Root injiziert.
2. **`telemetry/http/routes.py` entkoppeln:** die SSE-Route bekommt den Event-Source-Port per Injection (Composition-Root-Default), statt `StateBackendProjectTelemetryEventSource()` selbst zu instanziieren. `telemetry/sse_stream.py` importiert `state_backend.store.facade` danach **nicht** mehr.
3. **project_management-Read-Port konsolidieren (kein Greenfield):** `ProjectRepository` (`repository.py:11-21`) existiert bereits; die Arbeit ist Konsolidierung/Injection-Cleanup. Sicherstellen, dass `control_plane_http` + `read_model_routes.py` Projektliste/-Detail/-Felder/Caps/`are-evidence` ausschliesslich ueber die veroeffentlichten Protocol-Ports lesen. **Konkret einzubeziehen:** der Default-Adapter in `project_management/http/routes.py:135` (Projektliste/-Detail defaultet heute auf einen State-Backend-Adapter innerhalb des BC) wird per Composition-Root injiziert oder explizit als out-of-scope mit Owner deklariert. Adapter-Besitz liegt im Composition-Root/State-Backend, nicht im BC.
4. **Tests:** Telemetrie-SSE-Route gegen einen Fake-Event-Source-Port ohne State-Backend; Conformance-Test, dass der produktive Telemetrie-Adapter den Port erfuellt; AST-/Import-Test, dass `telemetry/sse_stream.py` `state_backend.store.facade` **nicht** mehr importiert; Test, dass die project_management-Read-Routen unveraendert dieselben Read-Modelle liefern.
5. **Fail-closed-Vertrag erhalten:** fehlende Event-Tabelle/fehlender Projektzustand verhaelt sich wie heute fachlich definiert; kein stilles Leer-OK.

### 2.2 Out of Scope (mit Owner)

- **Story-BC-Read-Port** — **AG3-126** (`depends_on`); diese Story baut darauf auf und fasst `story/repository.py` nicht an (nur Nutzung des dortigen Ports in `read_model_routes.py`).
- **Maschinelle Durchsetzung** (Konformanz-Suite + Formal-Spec-Invarianten fuer die neuen Telemetrie-/Projekt-Read-Surfaces) — **AG3-128** (`depends_on: AG3-126, AG3-127`).
- **SSE-Producer / Topic-Wire-Schemas / Event-Emission** — bestehende Telemetrie-Verantwortung (AG3-081-Linie); diese Story aendert nur die **Read**-Quelle, nicht den Producer.
- **Control-Plane-Runtime-Read-Port** (`control_plane.repository`, FK-07 §7.9 Punkt 9) — bereits vorhanden, nicht Teil dieser Story.
- **Aenderung der Frontend-Datenvertraege** (`formal.frontend-contracts.*`, FK-72 §72.14) — die Read-Kante wird entkoppelt, der Vertrag nach aussen bleibt unveraendert.

### 2.3 Betroffene Dateien

| Datei | Aenderungsart |
|---|---|
| `src/agentkit/backend/telemetry/` (neues Read-Surface/Port-Modul) | Neu |
| `src/agentkit/backend/telemetry/sse_stream.py` | Aendern (kein `state_backend.store.facade`-Import; Adapter raus) |
| `src/agentkit/backend/telemetry/http/routes.py` | Aendern (Port per Injection statt Selbst-Instanziierung `:38-39`) |
| `src/agentkit/backend/state_backend/store/` (Telemetrie-Event-Adapter) | Neu (Adapter-Verlagerung) |
| `src/agentkit/backend/bootstrap/composition_root.py` | Aendern (Telemetrie-Port-Builder; BFF-Default-Wiring) |
| `src/agentkit/backend/project_management/http/routes.py` | Aendern/Pruefen (`:135` Default-Adapter injizieren oder out-of-scope) |
| `tests/unit/telemetry/**`, `tests/integration/telemetry/**`, `tests/contract/**` | Neu/Aendern (Fake-Port-Route, **echter State-Backend-Roundtrip**, AST-Import-Regression, project_management-Read-Regression) |

## 3. Akzeptanzkriterien (nummeriert, testbar)

1. Es existiert ein veroeffentlichter Telemetrie-Read-Port (Protocol) fuer projekt-skopierte Execution-Event-Reads; `telemetry/sse_stream.py` importiert `agentkit.backend.state_backend.store.facade` **nicht** mehr (AST-/Import-Test belegt die Abwesenheit). Analoger Import-Test fuer den project_management-Read-Pfad.
2. Der produktive Telemetrie-Event-Adapter lebt in `agentkit.backend.state_backend.store` und erfuellt den Port. **Echter State-Backend-Roundtrip (keine reine Fake-Absicherung):** ein Integrationstest persistiert Execution-Events und liest sie ueber den produktiven Adapter/SSE-Source real zurueck (Conformance-`runtime_checkable`-Check zusaetzlich, nicht als Ersatz); `telemetry/http/routes.py` erhaelt den Port per Injection statt Selbst-Instanziierung.
3. Die SSE-Route ist gegen einen Fake-Event-Source-Port **ohne** State-Backend testbar; ein Unit-Test treibt sie so.
4. project_management-Read-Pfad: `control_plane_http`/`read_model_routes.py` lesen Projekt-Read-Modelle ausschliesslich ueber die Protocol-Ports; kein direkter `state_backend.store`-Import im project_management-Read-Pfad (Import-Test). Die Read-Routen liefern unveraendert dieselben Modelle (Routing-/Integrations-Test gruen).
5. Fail-closed: fehlender Telemetrie-/Projekt-Zustand verhaelt sich wie heute fachlich definiert; Negativpfad-Test belegt es (kein neues stilles Leer-OK).
6. **ARCH-55:** alle neuen Bezeichner englisch; keine `noqa`/`type: ignore` ohne Begruendung.
7. **Quality-Gates gruen** (Repo-Root, via `.venv`, GAC-konform):
   - `.venv\Scripts\python -m pip install -e ".[dev]"`; `pytest` unit/integration/contract (`-n0`); Coverage `>= 85 %` (`--cov=agentkit --cov-fail-under=85`).
   - `mypy src` (default + `--platform linux`); `ruff check src tests`.
   - Konzept-/Architektur-Gates (GAC-1): `scripts/ci/check_architecture_conformance.py`, `scripts/ci/check_concept_frontmatter.py`, `scripts/ci/check_concept_code_contracts.py`, `scripts/ci/compile_formal_specs.py`.
   - **Remote-Gates** (`pwsh scripts/ci/check_remote_gates.ps1`): **Jenkins-Build gruen** und **SonarQube Zero-Violation** (`violations=0`, `critical_violations=0`, `security_hotspots=0` auf New Code).

## 4. Definition of Done

- AK 1-7 erfuellt; Diff + gruene Pflichtbefehle + GAC-1; QA-Gate (Codex-Review) PASS.
- Kein paralleler Alt-Pfad: der BC-interne State-Backend-Adapter der Telemetrie-Event-Quelle verschwindet, es entsteht **keine** zweite Read-Wahrheit.
- `unblocks: AG3-128` wird erst `ready`, wenn AG3-126 **und** AG3-127 `completed` sind.

## 5. Guardrail-Referenzen

- **FIX THE MODEL, NOT THE SYMPTOM:** der BC-interne State-Backend-Adapter ist das Symptom; der fehlende veroeffentlichte Read-Port das Modellproblem.
- **SINGLE SOURCE OF TRUTH:** genau **eine** Read-Kante je BC; der produktive Adapter (im State-Backend) ist die einzige Stelle mit Fassaden-Wissen.
- **ZERO DEBT / FAIL-CLOSED:** keine halbe Migration; kein stilles Leer-OK bei fehlendem Backend.
- **ARCH-55 / GAC-2:** Bezeichner englisch; `guardrails/architecture-guardrails.md` verbindlich; Konflikt = hart stoppen und melden.

## 6. Hinweise fuer den Sub-Agent

- Read T:/codebase/claude-agentkit3/CLAUDE.md first — all project rules apply to you.
- Den Story-Port aus **AG3-126** als unmittelbares Muster verwenden (gleiches Protocol-im-BC + Adapter-im-State-Backend + Composition-Root-Verdrahtung). Telemetrie hat den Protocol-Seam (`ProjectTelemetryEventSource`) bereits — es fehlt die Adapter-Verlagerung + Injection.
- IST vor der Arbeit re-verifizieren: `telemetry/sse_stream.py:10,48-58,61-71`, `telemetry/http/routes.py:38-39`, `project_management/repository.py:11-21`, `project_management/read_model_routes.py:48-57`, `bootstrap/composition_root.py:547,557,560`, `control_plane_http/tenant_scope.py:49-54`. **Drift gegen `var/abweichungskarte-zentralisierung.md` aktiv im Bericht spiegeln** (Karte verortet den Durchgriff noch im BFF; aktuell BC-intern).
- Formal-Spec **nicht** anfassen — maschinelle Durchsetzung ist AG3-128. Bei Konflikt mit einer bestehenden `read_surface_rule`/`dependency_rule`: stoppen und melden.
- Kein Commit ohne Auftrag. „done" nur mit Beleg: Diff, Testnamen (inkl. Import-Regressionstests + Fake-Port-Tests), gruene Pflichtbefehle + GAC-1.

## 7. Vorbedingungen

- `depends_on: AG3-126` muss `completed` sein (`StoryReadPort` existiert) — bis dahin `status: blocked`.
- Venv-Pflicht: alle Python-Befehle ueber `.venv\Scripts\python`; keine globalen Installs (AK2/AK3 teilen `agentkit`).

---

## Globale Akzeptanzkriterien (verbindlich)

Zusaetzlich gelten die **globalen Akzeptanzkriterien** aus `stories/_GLOBAL_ACCEPTANCE.md` (Single Source of Truth):

- **GAC-1:** `scripts/ci/check_architecture_conformance.py` laeuft mit **0 Errors** (Exit 0, fail-closed) — `PYTHONPATH=src .venv\Scripts\python scripts/ci/check_architecture_conformance.py`.
- **GAC-2:** Die Architektur-Guardrails `guardrails/architecture-guardrails.md` (ARCH-NN) werden eingehalten; Konflikt = hart stoppen und melden.
