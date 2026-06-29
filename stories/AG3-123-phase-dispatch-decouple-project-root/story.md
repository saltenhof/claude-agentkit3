# AG3-123: Phase-Dispatch / RuntimeService vom dev-lokalen `project_root` entkoppeln (Backend-resolved Workspace)

**Typ:** Implementation / **Groesse:** L / **Bounded Context:** `pipeline_engine` / Control-Plane-Runtime (deterministischer Kern, FK-10 §10.2.3). Diese Story adressiert die **WP-D-Wurzel (Invariante I3)**: die kanonische Phasen-Ausfuehrung (`PhaseDispatcher`/`ControlPlaneRuntimeService`) ist heute an einen `StoryContext.project_root` gekoppelt, der als **dev-lokaler** Worktree-/Dateisystem-Pfad gedacht ist. Da Backend und Dev getrennte Installationen sind und das Backend lokal **oder** remote laufen kann (FK-10 §10.2.0/§10.2.4), darf der Kern nicht voraussetzen, dass ein dev-lokaler `project_root` im selben Prozess greifbar ist. Die Worktree-/FS-Bindung wird **Backend-resolved** (eigener Locator), fail-closed bei Nicht-Aufloesbarkeit. Diese Story ist das **Fundament** fuer die Capability-Routen-Aktivierung (AG3-124/AG3-125).

**Quell-Konzepte (autoritativ):**
- `FK-10 §10.1.0 I3` (`10-1-laufzeitkomponenten-001`) — „AK3-verantwortete kanonische Operationen (State, Gates, Phasenfortschritt) laufen ausschliesslich per REST ueber den Kern" — fail-closed, kein Bypass am Kern vorbei.
- `FK-10 §10.2.3` (`10-2-deployment-modell-002`) — „AgentKit hat **keine kanonische projektlokale Runtime**. Die gesamte deterministische Fachlogik (4-Phasen-Pipeline, QA-Subflow, Closure, Governance, Policy) ist der AK3-Kern und laeuft im Backend."
- `FK-10 §10.2.4` (`10-2-deployment-modell-002`) — Deployment-Topologie (Ko-Lokalisierung vs. Remote): „Die in-process-Kopplung an einen lokalen `project_root`/Worktree gehoert auf die **Backend-Seite** und ist kein Dev-seitiger Fachlogik-Anker."
- `FK-10 §10.2.0` (`10-2-deployment-modell-002`) — Dreifaltigkeit: drei getrennte Ebenen; „Kanonischer Zustand lebt nur auf Ebene 1" (Backend/Postgres), Ebene 3 (Projektraum) haelt nur Bundle + projektlokale Konfiguration.
- `FK-10 §10.6` (`10-6-fehlerbehandlung-und-recovery-006`) — Fail-closed bei nicht aufloesbaren kanonischen Vorbedingungen: „Read-Projektionen sind nur lesend und werden nicht zur Ersatzwahrheit."
- `FK-01 §1.1a` (git-Mechanik-Carve-out) — git/Worktree-Mechanik ist fs-gebunden und gehoert auf die Backend-Seite; nur dort darf der FS-Anker materialisieren.
- `FK-45 §45.1.2/§45.2/§45.3` — Phase-Runner-Eintrittspunkt: die Phase wird ueber `(project_key, story_id, run_id)` adressiert; der Workspace-Ort ist Backend-Resolved, kein Dev-Parameter.
- `FK-91 §91.1/§91.1a` — Service-API-Vertrag der projekt-skopierten Phasenrouten (`/v1/projects/{project_key}/story-runs/{run_id}/phases/{phase}/...`); Correlation-/Fehlervertrag bleibt erhalten.
- `FK-20 §20.8.2` + `formal.story-workflow.invariant.phase_start_requires_release_and_readiness` — Run-Admission (Approved + READY) ist die Start-Vorbedingung; sie wird **unabhaengig** von der Workspace-Aufloesung gefuehrt.

---

## 1. Kontext / Ist-Zustand (belegt)

Die kanonische Phasen-Arbeit laeuft serverseitig ueber `ControlPlaneRuntimeService`, **aber** der Dispatch zieht den Story-Workspace zwingend aus `StoryContext.project_root` — gedacht als lokaler Worktree-Pfad. Re-verifiziert am aktuellen Code (`src/agentkit/backend/`):

- `control_plane/dispatch.py:835-841` — `_resolve_story_dir(ctx)` wirft `PipelineError("Cannot dispatch a phase without a resolved project_root on the StoryContext (fail-closed)")`, wenn `ctx.project_root is None`. Der Story-Dir wird aus `story_dir(ctx.project_root, ctx.story_id)` abgeleitet (`:841`).
- `control_plane/dispatch.py:772-776` — der Engine-Factory-Kommentar haelt fest: „`story_dir` is derived from the story context's `project_root` + story id".
- `control_plane/dispatch.py:809-812` — `_guard_factory(ctx)` baut den Pre-Start-Guard ueber `build_pre_start_guard(ctx.project_root)`; der Store-Root **ist** der Project-Root.
- `control_plane/runtime.py:843-847` — der phasen-mutierende Pfad laedt `ctx = self._repo.load_story_context(...)`; `if ctx is None or ctx.project_root is None: return None`, sonst `resolve_story_dir(ctx.project_root, ctx.story_id)`.
- `control_plane/runtime.py:430-456` — ERROR-1-Fix: die run-admission-Auswertung haengt heute an der `project_root`-Aufloesbarkeit (`_dispatch_phase` liefert `None`, wenn der `StoryContext` „no ctx / no project_root" ist), bevor das Run-Admission-Gate greift; Fresh-Setup-Start ohne `project_root` wird fail-closed abgewiesen (`:453-458`).
- `control_plane_http/app.py:76-81` — die realen REST-Routen sind bereits projekt-skopiert (`POST /v1/projects/{project_key}/story-runs/{run_id}/phases/{phase}/{start|complete|fail}` und `/closure/complete`); der POST-Phasen-Handler ruft serverseitig `self._runtime_service` (`app.py:414`, Dispatch `:765-773`). D.h. der Transport ist server-vermittelt, **die Ausfuehrung haengt aber am lokalen `project_root`** (Kopplung aus dispatch/runtime).

**Konsequenz:** Solange `project_root` ein dev-lokaler Pfad ist, kann ein **remote** laufendes Backend (FK-10 §10.2.4) die Phase nicht dispatchen — der Kern braeuchte das dev-lokale Dateisystem. Das verletzt I3/§10.2.3. Die Worktree-/FS-Aufloesung muss auf die Backend-Seite wandern und aus kanonischem State (Ebene 1) resolved werden.

## 2. Scope

### 2.1 In Scope

1. **Backend-seitiger Workspace-Resolver (Port + Default-Impl) — praezise spezifiziert.**
   - **Port:** ein typisiertes `@runtime_checkable Protocol` `StoryWorkspaceLocator` mit `resolve(project_key: str, story_id: str, run_id: str) -> StoryWorkspace` (Rueckgabemodell `StoryWorkspace` mit dem aufgeloesten FS-Anker + Metadaten).
   - **Owner/Heimat:** der Port lebt im `pipeline_engine`/Control-Plane-Runtime-BC; die Default-Impl liest die **autoritative** Workspace-Quelle aus kanonischem Ebene-1-State (Project-Registry / Story-Context-Repository / Worktree-Binding), **nicht** aus `ctx.project_root`, `cwd` oder dev-seitig hereingereichten Request-Daten.
   - **Verbot:** kein Fallback auf `cwd`, kein dev-lokaler Pfad-Parameter, kein `ctx.project_root` als kanonische Eingabe. `ctx.project_root` darf nur noch das **Backend-resolved Ergebnis** spiegeln (oder entfaellt als Eingabe).
   - **Injektion:** der Port wird im Composition-Root in `PhaseDispatcher`/`ControlPlaneRuntimeService` injiziert (DI, testbar mit Fake-Locator fuer Unit-Ebene).
2. **`_resolve_story_dir` / `_guard_factory` umstellen.** Die Aufloesung in `dispatch.py:835-841` und `dispatch.py:809-812` (`build_pre_start_guard(ctx.project_root)`) sowie `runtime.py:843-847` ziehen den FS-Anker ueber den Resolver. `project_root` bleibt das **Backend-resolved** Ergebnis, nicht eine Dev-Eingabe; es gibt **keine** zweite Quelle fuer den Workspace-Ort.
3. **Run-Admission von der `project_root`-Aufloesbarkeit entkoppeln.** Die run-admission-Auswertung (`runtime.py:430-456`) wird so gefuehrt, dass die Admissions-Invariante (Approved+READY, FK-20 §20.8.2) **unabhaengig** von „ctx hat keinen lokalen `project_root`" entschieden wird. Der bisherige Fail-closed-Reject eines un-admittierten Fresh-Setup-Starts bleibt erhalten — er wird nur nicht mehr ueber die `project_root`-Abwesenheit, sondern ueber den Resolver-/Admission-Pfad begruendet.
4. **Fail-closed bei nicht aufloesbarem Workspace.** Kann der Backend-Resolver den Workspace nicht herstellen, schlaegt der Dispatch mit einem strukturierten, typisierten Fehler fehl (kein stiller No-op, kein Silent-Skip). Die git/Worktree-Mechanik bleibt fs-gebunden auf der Backend-Seite (FK-01 §1.1a Carve-out).
5. **Tests** (Pflicht, siehe §3): Resolver-Happy-Path, Resolver-Fail-closed, Phase-Dispatch ueber `RuntimeService` mit Backend-resolved Workspace, sowie der erhaltene Negativpfad an der Setup-Phasengrenze (un-admittierter Fresh-Setup-Start wird abgewiesen).

### 2.2 Out of Scope (mit Owner)

- **Aktivierung der `pipeline_engine/http`-Capability-Route** (heutiger `service_available=False`/`bc_unavailable_response`-Adapter aus AG3-090 -> reale Server-Route) — **AG3-124** (baut auf diesem Resolver auf; `depends_on AG3-123`). Hinweis: der heutige 503-Status stammt aus dem AG3-090-Adaptervertrag (`bc_unavailable_response`), nicht aus einem Konzept.
- **Aktivierung von `verify_system/http` + `closure/http` + `governance/http`** — **AG3-125** (`depends_on AG3-123`).
- **Physische Remote-Host-Topologie / Transport-Wiring** (tatsaechliches Deployment auf separatem Host, Netzwerk, Auth-Hardening) — Deployment-/Ops-Konfiguration, nicht diese Story. AG3-123 stellt nur sicher, dass der Kern **keine** dev-lokale FS-Annahme mehr traegt.
- **Postgres-Kapselung des Hook-Pfades (WP-A, Invariante I1)** und **Drittsystem-Vermittlung (WP-B)** — eigene Arbeitspakete, nicht hier.
- **`/v1/compat`-Versions-Handshake (WP-G)** — separat.

### 2.3 Betroffene Dateien

| Datei | Aenderungsart |
|---|---|
| `src/agentkit/backend/pipeline_engine/` bzw. Control-Plane-Runtime (neues Port-Modul `StoryWorkspaceLocator` + `StoryWorkspace`-Modell) | Neu |
| `src/agentkit/backend/control_plane/dispatch.py` | Aendern (`_resolve_story_dir:835-841`, `_guard_factory:809-812` ziehen ueber den Resolver) |
| `src/agentkit/backend/control_plane/runtime.py` | Aendern (Phasen-Mutationspfad `:843-847`; Run-Admission `:430-456` von `project_root`-Aufloesbarkeit entkoppelt) |
| `src/agentkit/backend/bootstrap/composition_root.py` | Aendern (Resolver-Default in Dispatcher/Runtime injizieren) |
| `src/agentkit/backend/state_backend/store/` bzw. Project-/Story-Repository | Aendern/Neu (autoritative Workspace-Quelle, falls Lookup-Surface fehlt) |
| `tests/unit/control_plane/**`, `tests/integration/pipeline_engine/**`, `tests/contract/**` | Neu/Aendern (Resolver, echte Phasengrenzen-Flows, SSOT-Static-Check, Routen-Regression) |

## 3. Akzeptanzkriterien

1. `PhaseDispatcher` und `ControlPlaneRuntimeService` loesen den Story-Workspace ueber einen Backend-seitigen `StoryWorkspaceLocator`-Port auf; **kein** Code-Pfad interpretiert mehr einen vom Dev-Prozess hereingereichten `project_root` als kanonische FS-Eingabe (belegt durch Test: Dispatch gelingt mit Backend-resolved Workspace ohne dev-lokalen Pfad-Parameter).
2. `dispatch.py:_resolve_story_dir`, `dispatch.py:_guard_factory` und der Phasen-Mutationspfad in `runtime.py` ziehen den FS-Anker ausschliesslich ueber den Resolver; es existiert **eine** Quelle fuer den Workspace-Ort. **Statischer SSOT-Check (Import/AST-Test):** kein direkter `story_dir(ctx.project_root, ...)`-Aufruf in `dispatch.py`/`runtime.py` mehr (Regressionsschutz gegen Rueckfall auf die dev-lokale Kopplung).
3. **Fail-closed:** Liefert der Resolver keinen Workspace, schlaegt der Dispatch mit strukturiertem typisiertem Fehler fehl (kein No-op, kein Silent-Skip) — reproduzierender Negativtest.
4. **Phasengrenzen-/Negativpfad-Pflicht (testing-guardrails §1/§2/§3):** Die Run-Admission-Invariante (FK-20 §20.8.2) wird unabhaengig von der `project_root`-Aufloesbarkeit gefuehrt; ein un-admittierter Fresh-Setup-Start (nicht Approved+READY) wird weiterhin fail-closed abgewiesen — Negativtest an der Setup-Phasengrenze. Die Tests laufen ueber den **realen `ControlPlaneRuntimeService`**-Phasengrenzen-Flow mit durch Vorgaengerphasen **erzeugtem** (nicht manuell gesetztem) State; Fehlerzustaende werden durch Artefakt-Manipulation erzeugt, **nicht** durch direktes Setzen von Pipeline-State. Mindestens ein gueltiger und ein ungueltiger Phasenuebergang sind verprobt (gueltiger admittierter Start dispatcht, un-admittierter Start blockiert). Die Entkopplung darf **nicht** durch einen Fake-Locator + manuell fabrizierten `StoryContext` allein bewiesen werden.
5. Die bestehenden, bereits server-vermittelten REST-Phasenrouten (`app.py:76-81`, `:765-781`) bleiben unveraendert erreichbar und routen weiter auf `self._runtime_service`; ihr Vertrag bricht nicht (Regressionstest fuer `POST .../phases/{phase}/{start|complete|fail}`).
6. **ARCH-55:** Alle neuen Bezeichner, Port-/Methodennamen, Fehlercodes und Kommentare englisch. Keine `noqa`/`type: ignore` ohne Begruendung.
7. **Quality-Gates gruen** (Repo-Root, alles via `.venv`, GAC-konform):
   - `.venv\Scripts\python -m pip install -e ".[dev]"`; `.venv\Scripts\python -m pytest tests/unit -n0`, `tests/integration -n0`, `tests/contract -n0`; Coverage >= 85 % (`.venv\Scripts\python -m pytest --cov=agentkit --cov-fail-under=85`).
   - `.venv\Scripts\python -m mypy src` **und** `.venv\Scripts\python -m mypy src --platform linux` (strict); `.venv\Scripts\python -m ruff check src tests`.
   - Konzept-/Architektur-Gates (GAC-1): `scripts/ci/check_architecture_conformance.py`, `scripts/ci/check_concept_frontmatter.py`, `scripts/ci/check_concept_code_contracts.py`, `scripts/ci/compile_formal_specs.py`.
   - **Remote-Gates** (`pwsh scripts/ci/check_remote_gates.ps1`): **Jenkins-Build gruen** und **SonarQube Zero-Violation** (`violations=0`, `critical_violations=0`, `security_hotspots=0` auf New Code).

## 4. Definition of Done

- AK 1–7 erfuellt; QA-Gate (Codex-Review als Code-Gate) **PASS** + Standard-Pflichtbefehle + Remote-Gates (Jenkins/Sonar) gruen. Implementierung/Commit erst nach Execution-Plan-Freigabe. Diese Story entblockt AG3-124, AG3-125 (und AG3-130).

## 5. Guardrail-Referenzen

- **FIX THE MODEL, NOT THE SYMPTOM:** Der Workspace-Ort bekommt **einen** Backend-Owner (Resolver-Port); keine zweite operative Wahrheit ueber einen dev-lokalen Pfad. Kein „Schattenfeld" `project_root` parallel zum Resolver.
- **FAIL CLOSED:** Nicht aufloesbarer Workspace -> strukturierter Fehler, nie stiller Dispatch (FK-10 §10.6, I3).
- **SINGLE SOURCE OF TRUTH:** Kanonischer Zustand lebt im Backend (FK-10 §10.2.0/§10.2.3); der Dev-Prozess ist duenner REST-Client und liefert keinen kanonischen FS-Anker.
- **NO ERROR BYPASSING:** Run-Admission-Gates (FK-20 §20.8.2) bleiben scharf; die Entkopplung darf das Admission-Gate nicht aufweichen.
- **WORKFLOW-/STATE-DISZIPLIN:** Phasen-Routing und Gate-Geltung bleiben typisiert; keine String-/Flag-Kaskade fuer den Workspace-Ort.
- **GAC-2 / ARCH-NN:** `guardrails/architecture-guardrails.md` einhalten; `integration_clients/`/Adapter bleiben duenn; Fachlogik bleibt im `pipeline_engine`/Runtime-BC. ARCH-55 (Englisch) verbindlich.

## 6. Hinweise fuer den Sub-Agent

- Read T:/codebase/claude-agentkit3/CLAUDE.md first — all project rules apply to you.
- Kritische Ankerpunkte (aktueller Code unter `src/agentkit/backend/`): `control_plane/dispatch.py:835-841` (`_resolve_story_dir`), `:809-812` (`_guard_factory`), `:772-776` (Engine-Factory-Kommentar); `control_plane/runtime.py:843-847` (Phasen-Mutationspfad) und `:430-456` (Run-Admission-Gate). Das ist die Kopplung, die geloest wird — **nicht** eine zweite Runtime daneben bauen.
- Die REST-Phasenrouten sind bereits server-vermittelt (`control_plane_http/app.py:76-81`, `:414`, `:765-781`). Diese Story baut **keine** neue Route; sie macht den dahinterliegenden Dispatch backend-resolvable.
- Deployment-Entscheidung (PO, var/abweichungskarte §Mark&Ask #4): Backend und Dev sind getrennte Installationen, Backend lokal **oder** remote — die `project_root`/Worktree-Kopplung MUSS geloest werden. Nicht erneut zur Diskussion stellen.
- git/Worktree-Mechanik bleibt fs-gebunden auf der Backend-Seite (FK-01 §1.1a Carve-out) — der Resolver verschiebt den Anker, er schafft ihn nicht ab.
- AK2 NICHT veraendern. `.mcp.json` NICHT anfassen. Kein globaler `pip install` (AK2/AK3 teilen den Paketnamen `agentkit`). Kein Commit ohne expliziten Auftrag.
- „done" nur mit Beleg: Diff-Zusammenfassung, gruene Pflichtbefehle + Remote-Gates, Resolver-Happy-/Fail-closed-Test, Setup-Phasengrenzen-Negativtest, REST-Phasenrouten-Regressionstest.

## 7. Vorbedingungen

- Keine offenen Abhaengigkeiten (`depends_on: []`) — Fundament-Story, sofort startbar.
- Backend-State-Backend (Postgres/Ebene 1) als kanonische Quelle vorhanden (FK-10 §10.2.0); der Resolver liest aus dem kanonischen Story-/Project-State, nicht aus dev-lokaler Konfiguration.
- `unblocks`: AG3-124, AG3-125, AG3-130 (Dokumentation; autoritativ ist deren `depends_on`).

---

## Globale Akzeptanzkriterien (verbindlich)

Zusaetzlich zu den obigen Akzeptanzkriterien gelten die **globalen Akzeptanzkriterien** aus `stories/_GLOBAL_ACCEPTANCE.md` (Single Source of Truth):

- **GAC-1:** `scripts/ci/check_architecture_conformance.py` laeuft mit **0 Errors** (Exit 0, fail-closed) — `PYTHONPATH=src .venv\Scripts\python scripts/ci/check_architecture_conformance.py`.
- **GAC-2:** Die Architektur-Guardrails `guardrails/architecture-guardrails.md` (ARCH-NN) werden eingehalten; Konflikt = hart stoppen und melden.
