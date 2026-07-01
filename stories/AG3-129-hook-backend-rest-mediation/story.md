# AG3-129: Hook-Prozess vermittelt Guard-Counter, Worker-Health und Telemetrie ueber Backend-REST statt Direkt-DB

**Typ:** Implementation / **Groesse:** L / **Bounded Context:** `governance-and-guards` / Hook-Adapter-Schicht (FK-30) im Zusammenspiel mit der Dev↔Kern-Topologie (FK-10). Der kurzlebige Hook-Prozess auf der Dev-Seite (Python, via Harness-Adapter; FK-10 §10.1.2/§10.1.3) oeffnet heute selbst PostgreSQL-Verbindungen, um Guard-Invocation-Counter, Worker-Health-State und Execution-Telemetrie zu schreiben. Diese Story zieht den Hook auf die Soll-Rolle „REST-Anforderer am Kern" zurueck (I1): kanonischer Zustand wird ausschliesslich vom Backend geschrieben, die Dev-Seite ruft nur `/v1`-Endpunkte.

**Quell-Konzepte (autoritativ):**
- `FK-10 §10.1.0 I1` — „Der Kern besitzt und beschreibt den kanonischen Zustand; PostgreSQL ist ausschliesslich sein Speicher. **Kein Dev-Prozess oeffnet eine direkte DB-Verbindung.**" (Invariant-Tabelle I1–I6, fail-closed).
- `FK-10 §10.1.0 I3` — „Kanonische Ops nur via Kern": AK3-verantwortete kanonische Operationen (State, Gates, Phasenfortschritt) laufen ausschliesslich per REST ueber den Kern; innerhalb dieser Vorgaenge kein Bypass auf DB.
- `FK-10 §10.1.2` (Prozesslandschaft) / `§10.1.3` (Hook-Rolle/-Detail) — Hook-Prozesse sind die duenne Dev-Seite (kurzlebig, via Harness-Adapter, REST-Client), der Kern kapselt DB und Drittsysteme.
- `FK-10 §10.3.2` — State-/Ownership-Tabelle: „Kanonischer Zustand wird **ausschliesslich vom AK3 Backend** geschrieben (I1). Dev-seitige Komponenten sind **Anforderer per REST**, nicht Schreiber." Zeilen *State-Backend: Telemetrie* („Hooks/Pipeline melden per REST"), *Governance/Locks* („Nur Backend mutiert; Dev-Seite nur lesend"), *kein Direkt-DB-Zugriff (I1)*.
- `FK-30 §30.3 / §30.10` — Hook-Registrierung (neutrale Guard-Engine + duenne Harness-Adapter) und Worker-Health-Monitor-Hooks als Enforcement-Owner. **Beachten:** FK-30 fuehrt Telemetrie-/Observability-Hooks als **nicht-blockierend** („blockieren nie"); diese Story darf das nicht in „alles fail-closed" umdeuten (siehe Scope §2.1.4).
- `FK-91 §91.1a` — Service-API-/Endpunkt-Katalog: **neu zu ergaenzen** sind die REST-Vertraege fuer Guard-Counter-Record/Housekeeping und Worker-Health-Read/Write (heute fuehrt FK-91 nur `/v1/telemetry/events`). FK-91 + die formalen Command-Contracts werden in dieser Story mitgezogen (Konzept-Aenderung in Scope).

> **PO-Entscheidung (Mark & Ask #2, var/abweichungskarte-zentralisierung.md):** Der Hook-Pfad wird **zuerst ueber das Backend gebaut**; **keine** Latenz-/Millisekunden-Ausnahme, **keine** Read-Cache-/Projektions-Sonderkante. Der Hook traegt schlicht den REST-Hop. Eine spaetere Optimierung ist nicht Teil dieser Story und darf den Soll-Schnitt nicht aufweichen.

---

## 1. Kontext / Ist-Zustand (belegt)

Re-verifiziert gegen den aktuellen Code (`src/agentkit/backend/`; die Pfade in `var/abweichungskarte-zentralisierung.md` WP-A sind ohne `backend/`-Praefix notiert — korrekt ist `src/agentkit/backend/...`):

- **Guard-Counter-Record (A1):** `src/agentkit/backend/governance/runner.py:677-695` baut `GuardCounterService(StateBackendGuardCounterRepository(project_root))` und ruft `record_invocation(...)`. Das Repository oeffnet direkt PostgreSQL: `src/agentkit/backend/state_backend/store/guard_counter_repository.py:107` `psycopg.connect(_postgres_database_url(), ...)`; die DSN stammt aus `os.environ["AGENTKIT_STATE_DATABASE_URL"]` (`guard_counter_repository.py:58-67`). Der Hook haelt damit DB-Credentials.
- **Guard-Counter-Housekeeping (A2):** `runner.py:838-844` (`flush_housekeeping()`) ueber dasselbe Repository → dieselbe Direkt-DB.
- **Worker-Health Schreiben/Lesen (A3/A4):** `runner.py:799` (post) und `runner.py:863` (pre) importieren `worker_health_repository`; `src/agentkit/backend/state_backend/store/worker_health_repository.py:124` `psycopg.connect(_postgres_database_url(), ...)`. Der Hook liest und schreibt Health-State direkt.
- **Telemetrie-Emission (A5):** `runner.py:938/972` (und weitere Hook-Pfade `:1230/1256`, `:1351/1376`, `:1419/1438`, `:1528/1561`) konstruieren `StateBackendEmitter(story_dir, ...)` aus `agentkit.backend.telemetry.storage`, der via `postgres_store._connect_global()` (`src/agentkit/backend/state_backend/postgres_store.py:235-236`) direkt in die DB schreibt.
- **Bereits vorhandene Hebel (kein Neubau der HTTP-Maschinerie):**
  - Telemetrie-REST-Endpunkt existiert: `src/agentkit/backend/control_plane_http/app.py:752` bedient `/v1/telemetry/events`.
  - REST-Client-Muster existiert: `src/agentkit/harness_client/projectedge/client.py:91` (`ProjectEdgeClient`, `urllib`-basiert, `base_url`, strukturierte `ApiError`-Behandlung `:147`/`:180`). Dieser Client ist das Vorbild fuer die Hook-Vermittlung; ein zweiter, parallel gebauter HTTP-Client ist zu vermeiden.
- **Folge:** Der Hook ist heute faktisch ein Schreiber des kanonischen Zustands — direkter Verstoss gegen FK-10 I1/I3. Es gibt **keine** Backend-REST-Route fuer Guard-Counter-Record und Worker-Health (nur Telemetrie ist server-vermittelt).

## 2. Scope

### 2.1 In Scope
1. **Hook oeffnet keine PostgreSQL-Verbindung mehr.** In den Hook-Pfaden (`governance/runner.py`) werden die Direkt-DB-Repositories fuer Guard-Counter (A1/A2), Worker-Health (A3/A4) und Telemetrie (A5) durch REST-Aufrufe an den Kern ersetzt. Nach dieser Story enthaelt der Hook-Ausfuehrungspfad **kein** `psycopg`-Import und **keine** `AGENTKIT_STATE_DATABASE_URL`-Aufloesung mehr.
2. **Backend-REST-Endpunkte fuer die drei Vorgaenge bereitstellen** (falls fehlend ergaenzen, sonst wiederverwenden), als duenne `control_plane_http`-Routen ueber die zustaendigen BC-Services:
   - **Guard-Counter-Record/Housekeeping** (`record_invocation`, `flush_week_rollover`, `flush_housekeeping`) — neuer Endpunkt, der serverseitig `GuardCounterService` aufruft (kpi_analytics/governance-Owner).
   - **Worker-Health Read/Write** (pre/post) — neuer Endpunkt, der serverseitig das Worker-Health-Repository bedient.
   - **Telemetrie-Emission** — der **bestehende** `/v1/telemetry/events` (`app.py:752`) wird vom Hook genutzt; der `StateBackendEmitter` im Hook-Pfad wird durch einen REST-Emitter ersetzt. Kein zweiter Telemetrie-Endpunkt.
3. **Hook-seitiger REST-Client** auf Basis des bestehenden `ProjectEdgeClient`-Musters (`harness_client/projectedge/client.py`); kein paralleler HTTP-Stack. Die Backend-Base-URL kommt aus der bestehenden Dev-Konfiguration (kein DB-DSN im Hook).
4. **Fail-closed-Semantik praezise je Vorgang (kein „alles blockt", kein Direkt-DB-Fallback):** I1 gilt fuer **alle** drei Vorgaenge — **kein** Pfad faellt je auf Direkt-DB oder ein stilles „leeres OK" zurueck. Bei der **Blockier**-Wirkung wird differenziert (Konflikt-Aufloesung mit FK-30):
   - **Governance-/Guard-Enforcement und Worker-Health (kanonische Gate-Operationen):** **fail-closed** — ein nicht meldbarer/erreichbarer Vorgang blockt (kein PASS ohne belegte kanonische Operation).
   - **Telemetrie-/Observability-Emission und der reine Volume-Counter:** bleiben **nicht-blockierend** (FK-30 „blockieren nie") — bei unerreichbarem Kern wird das Event **nicht** zur DB-Hintertuer umgeleitet und blockt auch nicht den Tool-Call; es wird sauber verworfen/zurueckgemeldet. Heutige `except Exception` „counter ist nur Volume-KPI"-Pfade (`runner.py:696-699`) bleiben non-blocking, werden aber **nicht** zu einem stillen DB-Fallback umgebaut.
   - Aendert diese Story die Blockier-Wirkung eines Pfades, ist der FK-30/FK-68-Wortlaut entsprechend mitzuziehen (FIX THE MODEL), nicht still abzuweichen.
5. **FK-91 + Formal-Spec mitziehen (Konzept-Aenderung in Scope):** die neuen Guard-Counter- und Worker-Health-REST-Endpunkte werden im FK-91-Endpunkt-Katalog (`91_api_event_katalog.md`) und in den formalen Command-Contracts ergaenzt (englische Pfade/Wire-Keys/`error_code`); die Konzept-Gates (`check_concept_frontmatter.py`, `compile_formal_specs.py`, `check_concept_code_contracts.py`) bleiben gruen.
6. **Echte HTTP-Integrations- + Negativpfad-Tests an der Hook↔Kern-Grenze** (Pipeline-/Hook-Logik, Testing-Guardrails; **keine Stub-Absicherung**): der Hook-Pfad geht real ueber die HTTP-Route an den Kern (kein Mock der Route); Backend nicht erreichbar → fail-closed je kanonischem Vorgang, non-blocking je Telemetrie/Volume-Counter, **kein** Direkt-DB-Zugriff; gueltige Antwort → Vorgang server-vermittelt persistiert (echtes State-Backend). Plus ein **statischer Import-Reachability-Check**, der belegt, dass aus dem Hook-Ausfuehrungspfad **kein** `psycopg`-/`AGENTKIT_STATE_DATABASE_URL`-Pfad mehr erreichbar ist (Regression gegen Zurueckfallen auf Direkt-DB).

### 2.2 Out of Scope (mit Owner)
- **CCAG-Permission-Requests/Leases + Mode-Lock zentralisieren** — **AG3-131** (`depends_on: AG3-129`). AG3-129 liefert das Hook-als-REST-Anforderer-Fundament, auf dem AG3-131 die zentralen Permission-Tabellen aufsetzt.
- **Operator-CLI `run-phase`/`resume` ueber REST** statt in-process Runtime — **AG3-130** (eigene Dev↔Kern-Kante, andere Eintrittsstelle).
- **Latenz-/Read-Cache-Optimierung des Hook-Pfads** — bewusst **nicht** Teil dieser Story (PO-Entscheidung: erst korrekt bauen). Keine Projektions-Sonderkante.
- **Drittsystem-Vermittlung (Sonar/Jenkins/ARE)** — WP-B, andere Stories.
- **Generischer State-Backend-Direkt-DB-Zugriff anderer Server-interner Repos** — bleibt erlaubt, solange er **im Kern** laeuft (I1 betrifft die Dev-Seite, nicht den Backend-Prozess).

### 2.3 Betroffene Dateien

| Datei | Aenderungsart |
|---|---|
| `src/agentkit/backend/governance/runner.py` | Aendern (Hook-Pfade Guard-Counter/Worker-Health/Telemetrie → REST statt Direkt-DB) |
| `src/agentkit/harness_client/` (hook-seitiger REST-Client, `ProjectEdgeClient`-Muster) | Neu/Aendern |
| `src/agentkit/backend/control_plane_http/app.py` + neue BC-`http/`-Routen (guard-counter, worker-health) | Aendern/Neu |
| `src/agentkit/backend/{governance,implementation/worker_health}/` (Backend-Service hinter den neuen Routen) | Aendern |
| `concept/technical-design/91_api_event_katalog.md` + `concept/formal-spec/**` (Command-Contracts) | Aendern (neue Endpunkt-Vertraege) |
| `tests/integration/governance_hooks/**`, `tests/unit/**`, `tests/contract/**` | Neu/Aendern (echte HTTP-Route, Unreachable-fail-closed, Import-Reachability-Check) |

## 3. Akzeptanzkriterien
1. Der Hook-Ausfuehrungspfad (`governance/runner.py` Guard-Counter-, Worker-Health-, Telemetrie-Seiten) oeffnet **keine** PostgreSQL-Verbindung mehr: kein `psycopg`-Import, keine `AGENTKIT_STATE_DATABASE_URL`-Aufloesung im Hook-Pfad (statischer Import-Reachability-Check belegt die Abwesenheit; Regressionspin).
2. Guard-Counter-Record/Housekeeping wird ueber einen Backend-`/v1`-Endpunkt vermittelt; serverseitig ruft der Endpunkt `GuardCounterService` (Persistenz-Akteur = Backend, FK-10 §10.3.2). Test: Hook-Aufruf → Counter ueber REST persistiert (kein Direkt-DB-Pfad).
3. Worker-Health Read/Write (pre/post) wird ueber einen Backend-`/v1`-Endpunkt vermittelt; Test pre+post: Health-State server-vermittelt geschrieben/gelesen.
4. Telemetrie-Emission im Hook-Pfad nutzt den **bestehenden** `/v1/telemetry/events`-Endpunkt (`app.py:752`) ueber einen REST-Emitter; kein `StateBackendEmitter`-Direkt-DB im Hook. Test: Hook-Event landet server-vermittelt.
5. **Fail-closed (Negativpfad-Pflicht):** Backend unerreichbar/Fehlerantwort → der betroffene Hook-Pfad meldet fail-closed und faellt **nicht** auf Direkt-DB oder stilles OK zurueck (eigener Negativpfad-Test je Vorgang oder gebuendelt, mind. ein expliziter Unreachable-Test).
6. Der hook-seitige REST-Client folgt dem `ProjectEdgeClient`-Muster (`harness_client/projectedge/client.py`); es entsteht **kein** zweiter paralleler HTTP-Client/Transport (SINGLE SOURCE OF TRUTH).
7. ARCH-55: alle neuen Endpunkt-Pfade, Bezeichner, `error_code`-Werte, Wire-Keys englisch. Keine unbegruendeten `noqa`/`type: ignore`.
8. **Quality-Gates gruen** (Repo-Root, via `.venv`, GAC-konform):
   - `.venv\Scripts\python -m pip install -e ".[dev]"`; `.venv\Scripts\python -m pytest` (unit/integration/contract, `-n0`); Coverage >= 85 % (`--cov=agentkit --cov-fail-under=85`).
   - `.venv\Scripts\python -m mypy src` **und** `--platform linux` (strict); `.venv\Scripts\python -m ruff check src tests`.
   - Konzept-/Architektur-Gates (GAC-1): `scripts/ci/check_architecture_conformance.py`, `scripts/ci/check_concept_frontmatter.py`, `scripts/ci/check_concept_code_contracts.py`, `scripts/ci/compile_formal_specs.py` (FK-91-Aenderung zieht diese mit).
   - **Remote-Gates** (`pwsh scripts/ci/check_remote_gates.ps1`): **Jenkins-Build gruen** und **SonarQube Zero-Violation** (`violations=0`, `critical_violations=0`, `security_hotspots=0` auf New Code).

## 4. Definition of Done
- AK 1–8 erfuellt; QA-/Code-Gate (Codex-Review) PASS; Status-Update und Entblockung gemaess `stories/README.md` §4.4 (entblockt AG3-131, sobald auch dessen weitere Deps `completed` sind). Implementierung/Commit erst nach Freigabe.
- Globale Akzeptanzkriterien (siehe unten) erfuellt.

## 5. Guardrail-Referenzen
- **FIX THE MODEL, NOT THE SYMPTOM:** Der Hook wird strukturell zum REST-Anforderer; **keine** zweite operative Wahrheit (Direkt-DB neben REST), kein hook-lokaler Schatten-DB-Pfad.
- **FAIL-CLOSED:** Unerreichbarer Kern blockt den kanonischen Vorgang; kein stiller Direkt-DB-Fallback, kein „leeres OK".
- **SINGLE SOURCE OF TRUTH:** Genau ein hook-seitiger REST-Client (`ProjectEdgeClient`-Muster); Telemetrie ueber den **einen** bestehenden Endpunkt.
- **NO ERROR BYPASSING:** Keine Umgehung der REST-Grenze; bestehende `except Exception`-„nur-KPI"-Pfade nicht zu DB-Fallbacks umbauen.
- **ARCH-55** (englische Bezeichner/Wire-Keys) und **GAC-2 / ARCH-NN** (`guardrails/architecture-guardrails.md`): Adapter bleiben duenn, Fachlogik im BC-Service.

## 6. Hinweise fuer den Sub-Agent
- Read T:/codebase/claude-agentkit3/CLAUDE.md first — all project rules apply to you.
- Ist-Anker (re-verifizieren, koennen sich um wenige Zeilen verschoben haben): `src/agentkit/backend/governance/runner.py:677-695` (guard-counter), `:838-844` (housekeeping), `:799`/`:863` (worker-health), `:938/972` (+ weitere Emitter-Stellen, telemetry); `state_backend/store/guard_counter_repository.py:107` + `:58-67` (DSN), `worker_health_repository.py:124`, `postgres_store.py:235-236` (`_connect_global`).
- Vorhandene Hebel nutzen: `control_plane_http/app.py:752` (`/v1/telemetry/events` existiert bereits) und `harness_client/projectedge/client.py:91` (`ProjectEdgeClient` als Client-Muster). Keinen zweiten HTTP-Stack bauen.
- PO-Vorgabe beachten: **kein** Latenz-/Cache-Sonderpfad. Erst korrekt ueber das Backend bauen.
- Negativpfad ist Pflicht (Hook-/Pipeline-Logik): Unreachable-Backend-Test je Vorgang; Abwesenheit von `psycopg`/`AGENTKIT_STATE_DATABASE_URL` im Hook-Pfad pinnen.
- Kein Commit ohne expliziten Auftrag. „done" nur mit Beleg: Diff, Test-Namen (inkl. Negativpfade), gruene Pflichtbefehle.

## 7. Vorbedingungen
- `depends_on: []` (autoritativ, siehe `status.yaml`). Die urspruenglichen Deps
  AG3-124/125 wurden mit der FK-72-§72.8.2-Erdung (Commit 95d5ac1) **superseded**
  und entfernt; die dort erwarteten Vorarbeiten liegen bereits vor: die kanonischen
  Surfaces existieren (`control_plane_http/app.py` mit `/v1/telemetry/events:720`;
  `harness_client/projectedge/client.py` als REST-Client-Muster), und die 7
  redundanten BC-HTTP-Stubs (u.a. `governance/http`) sind rueckgebaut — **kein**
  `governance/http`-Mount wiederbeleben; neue Guard-Counter-/Worker-Health-Routen
  gehen als `control_plane_http`-Routen ueber die zustaendigen BC-Services.
- Erreichbares zentrales State-Backend (PostgreSQL) fuer Integrationstests; Test-DB auf ephemerem Port (nie 5432), siehe `tests/fixtures/postgres_backend.py`.

---

## Globale Akzeptanzkriterien (verbindlich)

Zusaetzlich zu den obigen Akzeptanzkriterien gelten die **globalen Akzeptanzkriterien** aus `stories/_GLOBAL_ACCEPTANCE.md` (Single Source of Truth):

- **GAC-1:** `scripts/ci/check_architecture_conformance.py` laeuft mit **0 Errors** (Exit 0, fail-closed) — `PYTHONPATH=src .venv\Scripts\python scripts/ci/check_architecture_conformance.py`.
- **GAC-2:** Die Architektur-Guardrails `guardrails/architecture-guardrails.md` (ARCH-NN) werden eingehalten; Konflikt = hart stoppen und melden.
