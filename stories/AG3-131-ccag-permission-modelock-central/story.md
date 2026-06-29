# AG3-131: CCAG-Permission-Requests/Leases und Mode-Lock zentral im Backend-State (kein projektlokaler Owner)

**Typ:** Implementation / **Groesse:** L / **Bounded Context:** `governance-and-guards` / CCAG-Permission-Runtime (FK-42) und Setup-Preflight-Mode-Lock. Permission-Requests und -Leases sind kanonischer Laufzeit-State und gehoeren zentral in das Backend-State-Backend (I5) — heute liegen sie in projektlokalen SQLite-DBs ohne Postgres-Owner. Der projektweite Mode-Lock kennt zentral nur einen `holder_count`, nicht **welche** Story den Lock haelt; die Recovery-Wahrheit ist ein lokaler Marker. Diese Story etabliert die zentralen Postgres-Owner und macht die lokalen Dateien zu reinen Read-Projektionen.

**Quell-Konzepte (autoritativ):**
- `FK-10 §10.1.0 I5` — „Kein lokaler kanonischer State": Der Project Space haelt nur Bundle und projektlokale Konfiguration, keinen kanonischen Laufzeit-State; lokale Laufzeitdateien sind **ausschliesslich Read-Projektionen**.
- `FK-10 §10.3.1` — „**Nicht mehr im Projekt vorgesehen:** keine projektlokalen kanonischen CCAG-/Permission-DBs". CCAG-Permission-Note: Permission-**Regeln** sind projektlokale Konfiguration (FK-42), Permission-**Requests/Leases** sind kanonischer Laufzeit-State und liegen **zentral im Backend-State (I5)**.
- `FK-10 §10.3.2` — State-/Ownership-Tabelle, Zeile *State-Backend: CCAG Permission-Requests/Leases*: Schreiber = Governance-Fachlogik im Backend; Leser = Frontend-Inbox, Hooks (REST); „kanonisch zentral (kein projektlokaler SQLite-Owner; FK-42)". Zeile *Governance/Locks*: „Nur Backend mutiert; Dev-Seite nur lesend". Zeile *Lokale Read-Projektionen*: „**Nicht kanonisch** (I5); verwerfbar, kurze TTL".
- `FK-42 §42.1 / §42.5 / §42.7` — CCAG ist eigene Top-Level-Permission-Runtime (`agentkit.backend.governance.ccag_permission_runtime`); Gate-Keeper-Hook emittiert Permission-Requests; in `project.yaml` keine CCAG-Konfig, nur projektlokale YAML-**Regeln** (`.agentkit/ccag/rules/`) — Requests/Leases sind davon getrennt.
- `FK-55 §55.9a` — Permission-Request-/Lease-Modell (Request = offener auditierbarer Einzelfall; Lease = befristete Ausnahme; Run-Zustandsregeln). `FK-55 §55.10.4` — „nicht kanonisch / fail-closed" (der lokale State ist nicht die Wahrheit; fehlt/inkonsistent → fail-closed). `FK-55 §55.10.4a` — der lokale `permission_state.json`-Export ist ein Hook-Hilfsartefakt.

> **Aufbauend auf AG3-129:** Der Hook ist ab AG3-129 REST-Anforderer am Kern (I1/I3). AG3-131 nutzt dieses Fundament: die Permission-Requests/Leases werden **vom Backend** geschrieben, der Hook ist REST-Requester/Leser (I5). Daher `depends_on: AG3-129`.

---

## 1. Kontext / Ist-Zustand (belegt)

Re-verifiziert gegen `src/agentkit/backend/` (Abweichungskarte WP-E notiert Pfade ohne `backend/`-Praefix):

- **Permission-Requests lokal (E1):** `src/agentkit/backend/governance/ccag/requests.py:111` `CREATE TABLE IF NOT EXISTS ccag_permission_requests (...)` in einer SQLite-DB; der DB-Pfad ist `{project_root}/.agentkit/ccag/ccag_requests.db` (`governance/ccag/runtime.py:282-284`; `governance/runner.py:2014` und `:2223`). Es gibt **keinen** Postgres-Owner (kein Eintrag in `state_backend/store/`, kein Schema in `state_backend/postgres_schema.sql`).
- **Permission-Leases lokal (E2):** `src/agentkit/backend/governance/ccag/leases.py:81` `CREATE TABLE IF NOT EXISTS ccag_permission_leases (...)` in der per-Story-State-DB (`state_backend_dir`, vgl. `leases.py:12`). Kein Postgres-Owner.
- **Mode-Lock-Marker lokal + unvollstaendige Zentral-Tabelle (E3):** `src/agentkit/backend/governance/setup_preflight_gate/mode_lock_marker.py:34` `_MARKER_FILE = "mode-lock-acquired"` (lokale Datei je Story-Dir; `clear_mode_lock_marker` `:87`, genutzt in `setup_preflight_gate/phase.py:239/330/363-377`). Die zentrale Tabelle `project_mode_lock` (`src/agentkit/backend/state_backend/postgres_schema.sql:912-920`) haelt nur `project_key`, `active_mode` (`standard`/`fast`), `holder_count`, `updated_at` — **nicht**, welche Story den Lock haelt. Der lokale Marker ist damit die Recovery-Wahrheit.
- **Folge:** Kanonischer Laufzeit-State (Permission-Requests/Leases) lebt projektlokal ohne zentralen Owner; SQLite-Pfade sind teils test-gated und produktiv ggf. wirkungslos. Direkter Verstoss gegen FK-10 I5 / §10.3.1 / §10.3.2.

## 2. Scope

### 2.1 In Scope
1. **Zentraler Postgres-Owner fuer CCAG-Permission-Requests** als State-Backend-Tabelle + Repository: neues Schema in `state_backend/postgres_schema.sql` (plus identisches Parallel-Schema im SQLite-Test-Store, wie bei den anderen Tabellen), neues `state_backend/store/*_repository.py`, gespeist ausschliesslich vom Backend. Felder gemaess FK-55 §55.9a (mind. `request_id`, `project_key`, `story_id`, `run_id`, `principal_type`, `tool_name`, `operation_class`, `path_class`, `request_fingerprint`, `status`, `requested_at`, `expires_at`, `resolution`).
2. **Zentraler Postgres-Owner fuer CCAG-Permission-Leases** analog: Tabelle + Repository, befristete Ausnahme gebunden an `project_key + story_id + run_id + principal_type + tool_name + operation_class + path_class + request_fingerprint` (FK-55 §55.9a), inkl. `consumed`/`max_uses`-Semantik.
3. **Backend-REST-Endpunkte** (`control_plane_http`, duenne Routen ueber die Governance-Fachlogik) zum Oeffnen/Lesen/Aufloesen von Permission-Requests und zum Erteilen/Konsumieren von Leases; der **Hook ist REST-Requester/Leser** (I5, baut auf AG3-129). Schreiber bleibt das Backend.
4. **Mode-Lock zentral vervollstaendigen:** `project_mode_lock` (oder eine zugehoerige Tabelle) wird so erweitert, dass **welche Story** den Lock haelt, zentral und autoritativ festgehalten wird (Holder-Identitaet, nicht nur `holder_count`). Die atomare Setzung/Freigabe laeuft ueber das Backend.
5. **Lokale Dateien werden Read-Projektionen** (I5 / FK-55 §55.10.4a): `ccag_requests.db`, die per-Story-Lease-SQLite und der `mode-lock-acquired`-Marker sind **nicht mehr** kanonische Wahrheit. Sie duerfen als verwerfbare, kurz-TTL Hook-Hilfsartefakte bestehen bleiben (Hook-schnelle Lesbarkeit), aber die kanonische Wahrheit ist das zentrale State-Backend; fehlt/inkonsistent die Projektion → fail-closed (kein stilles Weiterlaufen auf lokaler Wahrheit).
6. **Tests inkl. Negativpfade** (Pipeline-/Governance-Logik, Testing-Guardrails): zentraler Owner schreibt/liest Requests+Leases server-vermittelt; Mode-Lock-Holder zentral nachvollziehbar; Negativpfad: lokale Projektion fehlt/divergiert → fail-closed, **kein** Zurueckfallen auf den lokalen SQLite-/Marker-State als Wahrheit; Request-Expiry deterministisch (FK-55 §55.9a/§55.10.9a, lazy).

### 2.2 Out of Scope (mit Owner)
- **Hook-Prozess → Backend-REST-Grundvermittlung** (Guard-Counter/Worker-Health/Telemetrie) — **AG3-129** (Vorbedingung; liefert den Hook-als-REST-Anforderer).
- **CCAG-Regel-Engine / YAML-Regeldateien** (`.agentkit/ccag/rules/`) — bleiben projektlokale **Konfiguration** (FK-42 §42.7); diese Story zentralisiert **nur** Requests/Leases, nicht die Regeln.
- **Capability-/Principal-Matrix-Entscheidungslogik** (FK-55 §55.10) — nicht Gegenstand; AG3-131 betrifft Persistenz-Ownership von Requests/Leases/Mode-Lock.
- **Operator-CLI `run-phase`/`resume` ueber REST** — **AG3-130**.
- **Frontend-Permission-Inbox-Sicht** — eigene Frontend-Story (diese Story stellt nur die zentrale REST-Lesbarkeit bereit).

### 2.3 Betroffene Dateien

| Datei | Aenderungsart |
|---|---|
| `src/agentkit/backend/state_backend/postgres_schema.sql` + SQLite-Parallel-Schema | Aendern (neue Tabellen `ccag_permission_requests`/`-_leases` zentral; `project_mode_lock` Holder-Identitaet) |
| `src/agentkit/backend/state_backend/store/` (neue Permission-Request-/Lease-Repositories; `mode_lock_repository.py`) | Neu/Aendern |
| `src/agentkit/backend/governance/ccag/{requests.py,leases.py,runtime.py}`, `governance/runner.py` | Aendern (lokale SQLite → REST/zentral; Hook = Requester) |
| `src/agentkit/backend/governance/setup_preflight_gate/{mode_lock_marker.py,phase.py}` | Aendern (Marker → Read-Projektion; Holder zentral) |
| `src/agentkit/backend/control_plane_http/app.py` + Governance-`http/`-Routen | Neu/Aendern (open/read/resolve/grant/consume) |
| `concept/technical-design/91_api_event_katalog.md` + `concept/formal-spec/**` | Aendern (neue Permission-/Lease-Endpunkt-Vertraege) |
| `tests/integration/governance/**`, `tests/unit/**`, `tests/contract/**` | Neu/Aendern (echte Postgres-Persistenz, Backend-REST, Projektion-Negativpfad) |

## 3. Akzeptanzkriterien
1. CCAG-Permission-Requests haben einen **zentralen Postgres-Owner** (Tabelle + Repository in `state_backend/`), geschrieben ausschliesslich vom Backend; `ccag_requests.db` ist nicht mehr kanonischer Owner. **Echter Postgres-Integrationstest (keine SQLite-/Mock-only-Absicherung):** Request gegen ein reales Postgres-State-Backend server-vermittelt persistiert und gelesen.
2. CCAG-Permission-Leases haben einen **zentralen Postgres-Owner** (Tabelle + Repository); Lease-Fingerprint-Bindung und `consumed`/`max_uses` gemaess FK-55 §55.9a. Test: Lease erteilt, konsumiert, server-vermittelt.
3. Backend-REST-Endpunkte bedienen Open/Read/Resolve (Requests) und Grant/Consume (Leases); der Hook ist REST-Requester/Leser (kein lokaler kanonischer Schreibpfad). **Echter Hook→REST-Integrationstest** (kein Mock der Route). **Kein Best-Effort-No-op:** das Oeffnen eines Permission-Requests **persistiert zentral**; eine Persistenz-/REST-Fehlersituation **failt sichtbar closed** — der heutige Pfad, der den Fehler schluckt und „blocked aber kein Request" (`permission_request_opened=False`) zurueckmeldet, ist beseitigt (eigener Test, der den Persistenz-Fehler als sichtbaren Fehler statt stillen Downgrade belegt).
4. Der projektweite Mode-Lock haelt **zentral und autoritativ**, welche Story den Lock haelt (nicht nur `holder_count`); Setzung/Freigabe ueber das Backend. Test: Holder-Identitaet zentral nachvollziehbar; Konkurrenz/Re-Entry korrekt.
5. Lokale Dateien (`ccag_requests.db`, Lease-SQLite, `mode-lock-acquired`-Marker) sind **Read-Projektionen** (I5): nicht kanonisch, verwerfbar. **Negativpfad-Pflicht:** fehlt/divergiert die Projektion, gilt fail-closed; **kein** Zurueckfallen auf lokalen State als Wahrheit (eigener Test).
6. Request-Expiry ist deterministisch/lazy (FK-55 §55.9a/§55.10.9a) und vom zentralen Owner getragen; Test fuer abgelaufenen Request.
7. ARCH-55: alle Tabellen-/Spalten-/Endpunkt-/Wire-Key-Bezeichner englisch; keine unbegruendeten `noqa`/`type: ignore`. State-/Schema-Aenderungen ziehen Contract-/Golden-Tests mit (CLAUDE.md: Telemetrie-/State-Formate nur mit Contract-Tests aendern).
8. **Quality-Gates gruen** (Repo-Root, via `.venv`, GAC-konform). **AC 1-6 sind NICHT durch SQLite-only-/Mock-only-Tests erfuellbar** — die Kernpersistenz braucht echtes Postgres (SQLite-Parallel-Schema nur fuer Unit-Paritaet):
   - `.venv\Scripts\python -m pip install -e ".[dev]"`; `.venv\Scripts\python -m pytest` (unit/integration/contract, `-n0`); Coverage >= 85 % (`--cov=agentkit --cov-fail-under=85`).
   - `.venv\Scripts\python -m mypy src` **und** `--platform linux` (strict); `.venv\Scripts\python -m ruff check src tests`.
   - Konzept-/Architektur-Gates (GAC-1): `scripts/ci/check_architecture_conformance.py`, `scripts/ci/check_concept_frontmatter.py`, `scripts/ci/check_concept_code_contracts.py`, `scripts/ci/compile_formal_specs.py`.
   - **Remote-Gates** (`pwsh scripts/ci/check_remote_gates.ps1`): **Jenkins-Build gruen** und **SonarQube Zero-Violation** (`violations=0`, `critical_violations=0`, `security_hotspots=0` auf New Code).

## 4. Definition of Done
- AK 1–8 erfuellt; QA-/Code-Gate (Codex-Review) PASS; Status-Update gemaess `stories/README.md` §4.4. Implementierung/Commit erst nach Freigabe.
- Globale Akzeptanzkriterien (siehe unten) erfuellt.

## 5. Guardrail-Referenzen
- **FIX THE MODEL, NOT THE SYMPTOM:** Kanonischer Owner ist das zentrale State-Backend; **keine** zweite operative Wahrheit in projektlokalen SQLite-DBs/Markern. Lokale Dateien werden zu Projektionen, nicht zu Schattentabellen.
- **FAIL-CLOSED:** Fehlende/inkonsistente lokale Projektion **und** ein nicht persistierbarer/zentral nicht erreichbarer Request → fail-closed mit **sichtbarer** Fehlersemantik; **kein** stilles „blocked aber kein Request" (Best-Effort-No-op), kein Weiterlaufen auf lokaler Wahrheit (FK-55 §55.10.4).
- **SINGLE SOURCE OF TRUTH IST PFLICHT:** Permission-Requests/Leases und Mode-Lock-Holder leben genau einmal — zentral (I5, §10.3.2).
- **NO ERROR BYPASSING / Artefakt-Ownership:** Hook ist REST-Requester, nicht Schreiber kanonischen States; QA-/Governance-State bleibt geschuetzt.
- **ARCH-55** und **GAC-2 / ARCH-NN** (`guardrails/architecture-guardrails.md`).

## 6. Hinweise fuer den Sub-Agent
- Read T:/codebase/claude-agentkit3/CLAUDE.md first — all project rules apply to you.
- Ist-Anker (re-verifizieren): `src/agentkit/backend/governance/ccag/requests.py:111` (CREATE TABLE), `governance/ccag/runtime.py:282-284` + `governance/runner.py:2014`/`:2223` (DB-Pfad `.agentkit/ccag/ccag_requests.db`); `governance/ccag/leases.py:81` (CREATE TABLE) + `:12` (per-Story-State-DB); `governance/setup_preflight_gate/mode_lock_marker.py:34` (Marker) + `setup_preflight_gate/phase.py:239/330/363-377`; `state_backend/postgres_schema.sql:912-920` (`project_mode_lock`, nur `holder_count`).
- Schema-Owner: governance-and-guards. Neue Tabellen sowohl in `postgres_schema.sql` als auch im SQLite-Parallel-Schema (Unit-Tests) anlegen; Repositories analog den bestehenden `state_backend/store/*_repository.py` (Postgres ist kanonisch).
- Hook bleibt REST-Requester (baut auf AG3-129); **keinen** lokalen kanonischen Schreibpfad neu einfuehren.
- Lokale YAML-**Regeln** (`.agentkit/ccag/rules/`) **nicht** anfassen — nur Requests/Leases/Mode-Lock zentralisieren.
- Negativpfad ist Pflicht (Projektion fehlt → fail-closed). Contract-/Golden-Tests bei Schemaaenderung mitziehen. Kein Commit ohne Auftrag. „done" nur mit Beleg: Diff, Test-Namen (inkl. Negativpfade), gruene Pflichtbefehle.

## 7. Vorbedingungen
- `depends_on: AG3-129` muss `completed` sein (Hook ist REST-Anforderer am Kern). Solange offen: `status: blocked`, nicht starten.
- Erreichbares zentrales State-Backend fuer Integrationstests; Test-DB auf ephemerem Port (nie 5432), siehe `tests/fixtures/postgres_backend.py`.

---

## Globale Akzeptanzkriterien (verbindlich)

Zusaetzlich zu den obigen Akzeptanzkriterien gelten die **globalen Akzeptanzkriterien** aus `stories/_GLOBAL_ACCEPTANCE.md` (Single Source of Truth):

- **GAC-1:** `scripts/ci/check_architecture_conformance.py` laeuft mit **0 Errors** (Exit 0, fail-closed) — `PYTHONPATH=src .venv\Scripts\python scripts/ci/check_architecture_conformance.py`.
- **GAC-2:** Die Architektur-Guardrails `guardrails/architecture-guardrails.md` (ARCH-NN) werden eingehalten; Konflikt = hart stoppen und melden.
