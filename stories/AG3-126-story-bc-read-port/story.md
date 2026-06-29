# AG3-126: Story-BC — echter veroeffentlichter Read-Port statt generischem State-Backend-Re-Export

**Typ:** Implementation / **Groesse:** L / **Bounded Context:** `story-lifecycle` (Story-BC, A-Code). Der BC besitzt die Story-Read-Sicht (StoryContext, PhaseState, FlowExecution, StoryMetrics, `execution_events`). Heute exportiert `story/repository.py` die generischen `load_*_global`-Loader des State-Backends nur durch und bietet damit **keine** echte fachliche Kapselung; die BFF-Read-Endpunkte (Stories-Liste/Detail) haengen ueber diesen Durchgriff faktisch an der `state_backend.store`-Mega-Fassade. Diese Story gibt dem Story-BC einen echten Repository-Vertrag (Protocol-Read-Port) und macht ihn zur **einzigen** Read-Kante.

**Quell-Konzepte (autoritativ):**
- `FK-07 §7.6` (`concept/technical-design/07_komponentenarchitektur_und_architekturkonformanz.md`) — Repository-Regel: „Fachkomponenten haengen nicht an `agentkit.backend.state_backend.store` als generischer Mega-Fassade. Die Zielarchitektur verlangt komponentenspezifische Repository-Vertraege." `StoryService`/Dashboard-Read-Modelle haengen an einer fachlich benannten Repository-Kante statt an der technischen Fassade.
- `FK-07 §7.7.5` — Pflichtabdeckung: Read-Surface-Grenzen. Globale Story-Reads (Story-Kontext, Phase-State, FlowExecution, Closure-/Story-Metriken **und** globale `execution_events`) laufen ausschliesslich ueber die fachlich benannte Repository-Kante; direkte Read-Kopplung an die globale `state_backend`-Fassade laeuft fail-closed auf.
- `FK-07 §7.8 Punkt 6` — Import-Grenze: globale Story-Read-Loader duerfen nur aus `agentkit.backend.story.repository` oder innerhalb von `agentkit.backend.state_backend` selbst importiert werden.
- `FK-07 §7.9 Punkt 8 + Punkt 10` — messbare Invarianten: Story-Read-Loader nur auf der expliziten Read-Surface `agentkit.backend.story.repository`; BFF-/HTTP-Entry-Boundaries komponieren Read-Modelle aus veroeffentlichten BC-Ports, nie ueber Persistenz-Durchgriff.
- `FK-72 §72.2` — kein „Cockpit"-Aggregator, kein God-View; Cross-BC-Sichten sind Composer-Sichten, deren Inhalt aus den BC-Slices stammt.
- `FK-72 §72.8` (`72-8-bff-topologie-008`, Z.191-206) — **normativer BFF-Anker:** der BFF/Control-Plane liest UI-Sichten ueber **veroeffentlichte Read-/Query-Ports der BCs**, nicht durch Persistenz-Durchgriff.
- Implementiertes **Code-Vorbild** (kein normativer Story-BC-Owner): der KPI-`FactRepository`-Protocol-Read-Port (`kpi_analytics/fact_store/repository.py`, Docstring nennt die „AC8 architecture-conformance boundary": FactStore haengt nur am Protocol, nie an der `state_backend.store`-Fassade; Adapter lebt in `state_backend.store`, Verdrahtung im Composition-Root) — analog `installer.repository`. `FK-62 §62.6` wird **nur** als KPI-spezifisches Ownership-/Top-Surface-Vorbild zitiert; der normative Owner dieser Story ist `FK-07 §7.6/§7.7.5/§7.8/§7.9` + `FK-72 §72.8`.

---

## 1. Kontext / Ist-Zustand (belegt) — gegen den CURRENT-Code re-verifiziert

- `src/agentkit/backend/story/repository.py:8-15` importiert die generischen Loader **direkt** aus `agentkit.backend.state_backend.store` (`load_story_context_global`, `load_story_contexts_global`, `load_phase_state_global`, `load_flow_execution_global`, `load_latest_story_metrics_global`, `load_execution_events_global`) und re-exportiert sie via `__all__` (`:17-25`). `StoryRepository` (`:51-72`) ist ein `@dataclass(frozen=True)`, dessen Felder lediglich auf diese Loader als Default-Callables zeigen — **kein** Protocol, **kein** Adapter-Seam, keine echte Kapselung (genau der von FK-07 §7.6 verbotene „Re-Export statt Repository-Vertrag").
- `src/agentkit/backend/story/service.py:16,31-32` konsumiert `StoryRepository`; `list_stories`/`get_story` (`:34-40`) lesen die Story-Sicht ueber dieses Re-Export-Objekt.
- BFF-Anbindung: `src/agentkit/backend/control_plane_http/app.py:33` importiert `StoryService`, instanziiert den Default (`:415`) und ruft `list_stories`/`get_story` (`:1134`, `:1174`). Der BFF importiert `state_backend.store` heute **nicht** mehr direkt (bereits durch fruehere Topologie-Arbeit bereinigt) — der verbleibende Durchgriff sitzt **innerhalb** des Story-BC im Re-Export.
- Formal-Spec-Stand (re-verifiziert): `concept/formal-spec/architecture-conformance/invariants.md:148-160` (`read_surface_rules.story_read_surface`) pinnt die sechs Loader bereits auf `agentkit.backend.state_backend` + `agentkit.backend.story.repository`. Die Regel erlaubt also genau diese Re-Export-Kante — sie erzwingt aber **nicht**, dass `story.repository` ein echter Port ist. Genau diese Luecke (FK-07 §7.6: „vollumfaengliche maschinelle Durchsetzung … als Soll definiert, aber nicht Teil der maschinell erzwungenen Invarianten") schliesst spaeter AG3-128.
- Vorbild zum Nachbauen: `src/agentkit/backend/kpi_analytics/fact_store/repository.py:1-45` (`@runtime_checkable FactRepository(Protocol)`), produktiver Adapter in `state_backend.store.fact_repository`, Verdrahtung im Composition-Root (`bootstrap/composition_root.py` rund um `:480-518`).

## 2. Scope

### 2.1 In Scope

1. **`StoryReadPort` als echtes Protocol** im Story-BC (`story/repository.py` oder ein dediziertes Port-Modul des BC) — ein `@runtime_checkable Protocol` mit den fachlichen Read-Methoden (`list_story_contexts`, `load_story_context`, `load_phase_state`, `load_flow_execution`, `load_latest_story_metrics`, `load_recent_execution_events`). Der Story-BC haengt nur noch am Protocol, **nicht** mehr an `state_backend.store`-Loadern.
2. **Produktiven Adapter ins State-Backend verlagern:** der konkrete, `load_*_global`-gestuetzte Adapter implementiert das Protocol und lebt in `agentkit.backend.state_backend.store` (analog `state_backend.store.fact_repository`). `story/repository.py` importiert die generischen Loader danach **nicht** mehr direkt.
3. **Composition-Root-Verdrahtung + alle Caller migrieren:** der Adapter wird im Composition-Root in `StoryRepository`/`StoryService` injiziert (analog der `FactRepository`-Verdrahtung). Kein Default-Callable mehr, das auf `state_backend.store` zeigt. **Vollstaendige Caller-Inventur (keine halbe Migration):** alle heutigen `StoryRepository()`/`load_*_global`-Aufrufer werden auf den Port umgestellt oder explizit als kompatibel begruendet — mindestens `bootstrap/composition_root.py:196`, `control_plane/repository.py:27`, `project_management/read_model_routes.py:48`. Kein verwaister oder paralleler Read-Pfad bleibt zurueck (ZERO DEBT).
4. **BFF liest ueber den Port:** `StoryService` (und damit `control_plane_http/app.py:1134/:1174`) liest StoryContext/PhaseState/FlowExecution/StoryMetrics/`execution_events` ausschliesslich ueber den `StoryReadPort` (FK-07 §7.9 Punkt 10).
5. **Fail-closed-Vertrag erhalten:** ein Read gegen eine fehlende Tabelle/fehlenden Zustand propagiert den darunterliegenden Fehler bzw. liefert `None`/leere Liste exakt wie heute fachlich definiert — **kein** stilles Leer-OK als Maskierung eines fehlenden Backends (analog FactRepository-Fail-closed-Vertrag).
6. **Tests:** Unit-Test, dass `StoryService` ausschliesslich gegen das Protocol arbeitet (Fake-Port injizierbar, kein State-Backend noetig); Test, dass der produktive Adapter das Protocol erfuellt (`isinstance`/`runtime_checkable`); Test, dass `story/repository.py` die `load_*_global`-Loader **nicht** mehr direkt importiert (Import-/AST-Assertion als Regressionsschutz).

### 2.2 Out of Scope (mit Owner)

- **Telemetrie-Read-Port (Events/SSE-Source) + project_management-Read-Port** — **AG3-127** (`depends_on: AG3-126`). Diese Story fasst den `telemetry`-/`project_management`-Durchgriff nicht an.
- **Maschinelle Durchsetzung des Repository-Vertrags** (Konformanz-Suite + Formal-Spec-Invarianten, FK-07 §7.6-Luecke) — **AG3-128** (`depends_on: AG3-126, AG3-127`). AG3-126 baut den Port; AG3-128 pinnt ihn maschinell.
- **Control-Plane-Runtime-Read-Port** (`control_plane.repository`, FK-07 §7.9 Punkt 9) — bereits vorhandene Read-Surface; nicht Teil dieser Story.
- **Aenderung der Wire-/Read-Model-Schemas** (`StorySummary`/`StoryDetail`/`formal.frontend-contracts.*`) — unveraendert; diese Story aendert die Read-Kante, nicht den Vertrag nach aussen.

### 2.3 Betroffene Dateien

| Datei | Aenderungsart |
|---|---|
| `src/agentkit/backend/story/repository.py` | Aendern (Re-Export raus; `StoryReadPort`-Protocol bzw. Port-Modul) |
| `src/agentkit/backend/story/service.py` | Aendern (konsumiert den Port via DI) |
| `src/agentkit/backend/state_backend/store/` (neuer `StoryReadPort`-Adapter) | Neu |
| `src/agentkit/backend/bootstrap/composition_root.py` | Aendern (Adapter injizieren; `:196`) |
| `src/agentkit/backend/control_plane/repository.py` | Aendern/Pruefen (`:27` Caller migrieren oder Kompatibilitaet begruenden) |
| `src/agentkit/backend/project_management/read_model_routes.py` | Aendern/Pruefen (`:48` Caller) |
| `src/agentkit/backend/control_plane_http/app.py` | Pruefen (Default-Wiring `:415`, falls betroffen) |
| `tests/unit/story/**`, `tests/integration/**`, `tests/contract/**` | Neu/Aendern (Protocol-Conformance gegen echtes State-Backend, AST-Import-Regression, BFF-Through-Port-Routing) |

## 3. Akzeptanzkriterien (nummeriert, testbar)

1. `story/repository.py` (bzw. das Story-BC-Port-Modul) definiert ein `@runtime_checkable`-Protocol als veroeffentlichten Read-Port; der Story-BC importiert die generischen `load_*_global`-Loader **nicht** mehr direkt (AST-/Import-Test belegt die Abwesenheit des `from agentkit.backend.state_backend.store import load_*`-Imports im BC).
2. Der produktive Adapter (Implementierung des Ports) lebt in `agentkit.backend.state_backend.store` und erfuellt das Protocol. **Echter Verhaltenstest gegen das reale State-Backend (keine reine `isinstance`-Pruefung):** der produktive Adapter liefert fuer eine real persistierte Story die korrekten StoryContext/PhaseState/FlowExecution/StoryMetrics/`execution_events`-Reads (struktureller `runtime_checkable`-Check **zusaetzlich**, nicht als Ersatz).
3. `StoryService` wird ueber Dependency-Injection mit dem Port versorgt; ein Unit-Test treibt `list_stories`/`get_story` gegen einen Fake-Port **ohne** State-Backend.
4. Die BFF-Routen `control_plane_http/app.py:1134`/`:1174` liefern unveraendert dieselben `StorySummary`/`StoryDetail`-Wire-Modelle, jetzt **durch den injizierten Port** — belegt durch einen Routing-/Integrationstest, der die Through-Port-Verdrahtung beweist (nicht nur ein Fake-`StoryService`); keine Verhaltensaenderung nach aussen.
5. Fail-closed: ein Read gegen fehlenden Story-Zustand verhaelt sich wie heute fachlich definiert (kein neues stilles Leer-OK); Negativpfad-Test belegt es.
6. **ARCH-55:** alle neuen Bezeichner (Protocol-Name, Methoden, Adapter-Klasse, Wire-/Symbolnamen) englisch; keine `noqa`/`type: ignore` ohne Begruendung.
7. **Quality-Gates gruen** (Repo-Root, via `.venv`, GAC-konform):
   - `.venv\Scripts\python -m pip install -e ".[dev]"`; `pytest` unit/integration/contract (`-n0`); Coverage `>= 85 %` (`--cov=agentkit --cov-fail-under=85`).
   - `mypy src` (default + `--platform linux`); `ruff check src tests`.
   - Konzept-/Architektur-Gates (GAC-1): `scripts/ci/check_architecture_conformance.py` (Exit 0; neuer Port verletzt keine bestehende Invariante), `scripts/ci/check_concept_frontmatter.py`, `scripts/ci/check_concept_code_contracts.py`, `scripts/ci/compile_formal_specs.py`.
   - **Remote-Gates** (`pwsh scripts/ci/check_remote_gates.ps1`): **Jenkins-Build gruen** und **SonarQube Zero-Violation** (`violations=0`, `critical_violations=0`, `security_hotspots=0` auf New Code).

## 4. Definition of Done

- AK 1-7 erfuellt; Diff + gruene Pflichtbefehle + GAC-1 als Beleg; QA-Gate (Codex-Review) PASS.
- Kein paralleler Alt-Pfad: der Re-Export verschwindet, es entsteht **keine** zweite Story-Read-Wahrheit neben dem Port (FIX THE MODEL / SSOT).
- `unblocks: AG3-127, AG3-128` werden erst `ready`, wenn diese Story `completed` ist.

## 5. Guardrail-Referenzen

- **FIX THE MODEL, NOT THE SYMPTOM:** der Re-Export ist das Symptom; der fehlende Repository-Vertrag ist das Modellproblem. Der Port wird gebaut, der Durchgriff entfernt — kein Schatten-Loader bleibt erhalten.
- **SINGLE SOURCE OF TRUTH:** genau **eine** Story-Read-Kante (`StoryReadPort`); der produktive Adapter ist die einzige Stelle, die `state_backend.store`-Loader kennt.
- **ZERO DEBT / FAIL-CLOSED:** keine halbe Migration mit altem und neuem Pfad parallel; kein stilles Leer-OK bei fehlendem Backend.
- **ARCH-55:** Quellcode/Bezeichner englisch.
- **GAC-2 / ARCH-NN:** `guardrails/architecture-guardrails.md` bleibt verbindlich; Konflikt = hart stoppen und melden.

## 6. Hinweise fuer den Sub-Agent

- Read T:/codebase/claude-agentkit3/CLAUDE.md first — all project rules apply to you.
- Vorbild 1:1 nachbauen: `src/agentkit/backend/kpi_analytics/fact_store/repository.py` (Protocol im BC) + `state_backend.store.fact_repository` (Adapter) + Composition-Root-Verdrahtung. Der Docstring des FactRepository nennt explizit die Boundary-Begruendung.
- IST-Anker vor der Arbeit re-verifizieren: `story/repository.py:8-15/51-72`, `story/service.py:16,31-32`, `control_plane_http/app.py:33,415,1134,1174`, `bootstrap/composition_root.py` (`build_*`-Story-Wiring, rund um `:981`).
- Formal-Spec **nicht** eigenmaechtig anfassen — die maschinelle Durchsetzung ist AG3-128. Hier nur Code + Tests. Falls der Umbau eine bestehende `read_surface_rule` brechen wuerde (z. B. weil der Adapter woanders liegt), **stoppen und melden** statt die Regel aufzuweichen.
- Kein Commit ohne expliziten Auftrag. „done" nur mit Beleg: Diff, Testnamen (inkl. Import-Regressionstest + Fake-Port-Test), gruene Pflichtbefehle + GAC-1.

## 7. Vorbedingungen

- Keine offenen Abhaengigkeiten (`depends_on: []`). `status: ready`.
- Venv-Pflicht: alle Python-Befehle ueber `.venv\Scripts\python` (AK2/AK3 teilen den Paketnamen `agentkit`; keine globalen Installs).

---

## Globale Akzeptanzkriterien (verbindlich)

Zusaetzlich gelten die **globalen Akzeptanzkriterien** aus `stories/_GLOBAL_ACCEPTANCE.md` (Single Source of Truth):

- **GAC-1:** `scripts/ci/check_architecture_conformance.py` laeuft mit **0 Errors** (Exit 0, fail-closed) — `PYTHONPATH=src .venv\Scripts\python scripts/ci/check_architecture_conformance.py`.
- **GAC-2:** Die Architektur-Guardrails `guardrails/architecture-guardrails.md` (ARCH-NN) werden eingehalten; Konflikt = hart stoppen und melden.
