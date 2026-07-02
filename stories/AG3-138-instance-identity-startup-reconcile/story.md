# AG3-138 — Instanz-Identität + Startup-Rekonsiliierung + `admin_abort_inflight_operation`

- **Typ:** implementation
- **Größe:** L
- **depends_on:** [AG3-137] — die Instanz-/Epoch-Spalten (`operation_epoch`,
  `backend_instance_id`, `instance_incarnation` am `inflight-operation-record`)
  und die persistente Ablage der Instanz-Identität, auf denen Rekonsiliierung
  und CAS-Finalize arbeiten, entstehen in AG3-137 (GAP §4: ST-01 → ST-02).
- **Quell-Konzept:** FK-91 §91.1a Regeln 16/17 + Endpoint
  `POST /v1/project-edge/operations/{op_id}/admin-abort`; FK-10 §10.5.4;
  FK-55 §55.5 (op-class `admin_transition`);
  `formal.state-storage.invariants`
  (`object_mutation_claims_are_instance_bound_and_never_expire_by_wall_clock`,
  `orphaned_claims_are_finalized_only_by_same_instance_startup_reconciliation_or_admin_abort`,
  `operation_finalize_requires_cas_on_operation_epoch`)
- **Herkunft:** GAP-Analyse Session-Ownership v4 (`_temp/gap-analyse-session-ownership.md`),
  Story-Kandidat GAP-ST-02; normative Basis Commits 3ae011e4 / 1bb4ed8a / 58c190b7
  (+ Decision-Records unter `concept/_meta/decisions/`).

## Kontext / Problem

Regel 2 des Session-Ownership-Strangs (stories/README.md §6.7): **Ownership und
Claims laufen NIE automatisch ab** — kein TTL, kein Heartbeat, keine
PID-Heuristik. Damit braucht das System einen anderen, deterministischen Endweg
für verwaiste serverseitige In-Flight-Claims: die **Start-Rekonsiliierung der
eigenen Instanz** plus den **expliziten administrativen Abbruch**. Beides fehlt
heute vollständig (am Code verifiziert 2026-07-02):

- `serve_control_plane` (`src/agentkit/backend/control_plane_http/app.py:1433-1473`)
  baut den `ThreadingHTTPSServer` und ruft direkt `serve_forever()` (:1471) —
  **kein** Pre-Serve-/Startup-Hook, keine Rekonsiliierung. Andockpunkt existiert
  (zwischen App-Bau und :1471; IMPL-003).
- Es gibt **keine** `backend_instance_id` und **keine** Boot-Inkarnation im
  Code (Grep: null Treffer in `src/agentkit/`). Ohne Instanz-Identität sind
  „eigene verwaiste Claims" nicht von fremden unterscheidbar (IMPL-004).
- Deployment-Realität: **ein** Multi-Thread-Prozess; UI-BFF und Project-API
  sind derselbe Control-Plane-Listener (`backend/cli/serve.py:1-15`, Ports
  9701/9702 :28-32) — die normative Ein-Writer-Betriebsannahme (FK-91 Regel 16,
  FK-10 §10.5.4) passt zur Ist-Topologie und wird hier **technisch markiert**
  (Instanzbindung der Claims), nicht neu entschieden (SOLL-064-Anteil).
- **Teil-Write-Problem:** `dispatch()` (`control_plane/dispatch.py:246`) führt
  `engine.run_phase`/`resume_phase` aus (:416/:424), die `phase_states`/
  `flow_executions` in **eigenen** Transaktionen persistieren, **bevor**
  `_finalize_start_phase` (`control_plane/runtime.py:684`) committet
  (bestätigt durch den Atomicity-Kommentar
  `state_backend/postgres_store.py:2747-2762`). Ein Crash dazwischen
  hinterlässt Engine-Teil-Writes ohne finalisierte Operation → braucht einen
  expliziten, auditierten Reconcile-/Repair-Zustand (IMPL-005, SOLL-068).
- Das heutige **einzige** Verwaisungs-Handling ist die Claim-TTL
  (`_CLAIM_LEASE_TTL = 5min`, `control_plane/runtime.py:83`;
  CAS-Takeover in `_acquire_claim` :534-627). **Deshalb die harte
  Migrationsreihenfolge (IMPL-006): diese Story MUSS vor AG3-139 (TTL-Entfall)
  landen — sonst gäbe es einen Deployment-Zustand ohne jedes
  Verwaisungs-Handling.** Diese Story entfernt die TTL noch NICHT; sie baut den
  Ersatzmechanismus daneben auf.
- Die op-class `admin_transition` existiert
  (`governance/principal_capabilities/matrix_data.py`); FK-55 §55.5 führt
  `admin_abort_inflight_operation` bereits normativ in dieser Klasse (:356).
  Der Endpoint, das CAS-Fencing und das CLI-Kommando fehlen im Code komplett
  (Grep `admin-abort`/`admin_abort`: null in `src/agentkit/`).

## Scope

### In Scope

1. **Erzeugung + Persistenz der Instanz-Identität** (IMPL-004,
   Erzeugung/Boot-Inkarnation): stabile `backend_instance_id` je
   Backend-Installation; `instance_incarnation` wird bei jedem Boot monoton
   inkrementiert (persistente Ablage aus AG3-137). Deterministisch, kein
   Wanduhr-Bezug.
2. **Pre-Serve-Startup-Hook** (IMPL-003): definierter Hook zwischen App-Bau
   und `serve_forever()` (`app.py:1433-1473`; beide Serve-Profile aus
   `cli/serve.py` laufen durch denselben Pfad). Der Listener nimmt erst
   Requests an, wenn der Hook erfolgreich durchlaufen ist; ein Fehlschlag
   verhindert den Start (fail-closed).
3. **Start-Rekonsiliierung** (SOLL-065, SOLL-067): im Hook werden verwaiste
   `claimed`-In-Flight-Operationen **der eigenen `backend_instance_id` aus
   früheren Inkarnationen** deterministisch als gescheitert finalisiert.
   Claims fremder Identität werden nie angefasst. Der Mechanismus ist so
   geschnitten, dass AG3-141 die `object_mutation_claims` an dieselbe
   Rekonsiliierung anschließen kann.
4. **Engine-Teil-Write-Repair** (IMPL-005, SOLL-068-Teil): eine verwaiste
   Operation, deren Engine-Writes (`phase_states`/`flow_executions`) bereits
   persistiert sind, wird nicht still `failed`, sondern in einen expliziten,
   auditierten **Reconcile-/Repair-Zustand** überführt (abfragbar über
   `GET /v1/project-edge/operations/{op_id}`).
5. **`operation_epoch`-CAS-Finalize** (SOLL-068): Finalize/Abort einer
   In-Flight-Operation erfordert Compare-and-Swap auf `operation_epoch` des
   eigenen Claims. Ein Late-Executor, dessen Operation administrativ
   abgebrochen wurde, scheitert deterministisch am Fence und registriert
   höchstens einen No-op-/Abort-Vermerk. (Das bestehende CAS-Finalize-Muster
   `_finalize_start_phase` trägt und wird auf den Epoch-Fence gehoben.)
6. **Instanzbindung der In-Flight-Claims** (SOLL-063, SOLL-066
   operation-claims-Anteil): jeder neue Claim wird mit
   `backend_instance_id` + `instance_incarnation` gestempelt; als Endwege
   existieren ausschließlich Start-Rekonsiliierung der eigenen Instanz und
   `admin_abort` — es wird **kein** neuer Wanduhr-Mechanismus eingeführt.
7. **Endpoint `POST /v1/project-edge/operations/{op_id}/admin-abort`**
   (SOLL-069, IMPL-023): `admin_abort_inflight_operation`, op-class
   `admin_transition` (SOLL-038, admin_abort-Anteil; FK-55 §55.5); wirkt nur
   auf servereigene Claims; auditiert; `operation_epoch`-CAS-Fence gegen
   Late-Commits; Teil-Writes → Reconcile-/Repair-Zustand statt still `failed`.
8. **CLI-Kommando `admin-abort`** als dünner menschlicher Adapter auf den
   Endpoint (FK-91 Regel 10; kein Zweitpfad, keine eigene Semantik).
9. **Mutations-Sperre bei offenem Reconcile-/Repair-Zustand** (fail-closed):
   Runs/Stories mit offenem Reconcile-/Repair-Zustand sind
   mutations-gesperrt — neue mutierende Operationen auf diese Story werden am
   Dispatch-/Operations-Layer mit 409 + maschinenlesbarem Grund abgewiesen,
   bis der Zustand via `admin_abort`/Repair aufgelöst ist. Kein stilles
   Weiterarbeiten auf Teil-Write-Stand.

### Out of Scope (mit Owner)

- **TTL-/Lease-Rückbau** (`_CLAIM_LEASE_TTL`, `_claim_is_expired`,
  `takeover_operation`): **AG3-139** — erst nachdem diese Story das
  Verwaisungs-Handling ersetzt hat (IMPL-006). Diese Story lässt die
  TTL-Mechanik bewusst unangetastet in Betrieb.
- **Objekt-Claim-Erwerb/Queue-Fairness/Warte-Semantik** und der Anschluss der
  `object_mutation_claims` an die Rekonsiliierung: **AG3-141**.
- **Ownership-Fencing der Regime-Pfade** (`ownership_epoch`-Fence,
  `_run_admission_evidence`-Ablösung): **AG3-142**.
- **Einheitlicher Idempotenz-Vertrag** (op_id-Minten, idempotency_keys):
  **AG3-140**.
- **Takeover-Request/-Confirm-Kommandos, `recover-story`, Edge-Tool-Verteilung**
  und die generelle HTTP-Principal-Attestierungs-Infrastruktur der
  Ownership-Endpoints (IMPL-018): **AG3-154** bzw. **AG3-148**. Hier nur die
  minimale Autorisierung des admin-abort-Pfads als `admin_transition`.
- **Generalisierung der Reconcile-Mutations-Sperre zur
  freeze_epoch-Familie**: **AG3-150** — diese Story baut nur die
  story-scoped Sperre für den Repair-Zustand.
- **Betriebs-Runbook** (Startup-Reconcile/Abort/Migrationsreihenfolge
  dokumentieren): **AG3-155**.

## Betroffene Dateien

| Datei | Änderungsart | Zweck |
|---|---|---|
| `src/agentkit/backend/control_plane_http/app.py` | ändern | Pre-Serve-Startup-Hook vor `serve_forever()` (:1433-1473); Route `POST /v1/project-edge/operations/{op_id}/admin-abort` |
| `src/agentkit/backend/control_plane/instance_identity.py` | neu | Erzeugung/Laden der `backend_instance_id`, monotone Boot-Inkarnation (Persistenzform aus AG3-137) |
| `src/agentkit/backend/control_plane/startup_reconcile.py` | neu | Verwaisten-Finalisierung eigener Inkarnationen + Teil-Write-Erkennung → Repair-Zustand |
| `src/agentkit/backend/control_plane/runtime.py` | ändern | Claim-Stempelung mit Instanz-Identität; Finalize auf `operation_epoch`-CAS heben; admin-abort-Service-Pfad |
| `src/agentkit/backend/control_plane/models.py` | ändern | Request-/Response-Modelle admin-abort; Repair-Zustandsform in der Operations-Antwort |
| `src/agentkit/backend/control_plane/repository.py` | ändern | Ports: Verwaisten-Query (eigene Identität), Epoch-CAS-Finalize, Abort |
| `src/agentkit/backend/state_backend/postgres_store.py` + `store/facade.py` (+ `_public_api_names.py`, `__init__.pyi`) | ändern | Row-Funktionen: orphan-scan je Instanz-Identität, `operation_epoch`-CAS, Abort-/Repair-Übergänge |
| `src/agentkit/backend/cli/main.py` | ändern | `admin-abort`-Kommando als dünner REST-Adapter |
| `tests/unit/control_plane/**` | neu/ändern | Reconcile-/CAS-/Abort-Logik über Ports/Fakes (injizierbare Identität) |
| `tests/integration/**` | neu | Postgres: präparierte verwaiste Claims → Boot finalisiert; Teil-Write → Repair; fremde Identität unangetastet; Server startet nicht bei Reconcile-Fehler |
| `tests/contract/**` | neu/ändern | Fehler-/Antwortvertrag admin-abort (404/409/Repair-Payload) |

## Akzeptanzkriterien

1. **Rekonsiliierung vor Request-Annahme:** Integrationstest — Datenbank mit
   verwaisten `claimed`-Operationen der eigenen `backend_instance_id` aus einer
   früheren Inkarnation; nach dem Boot sind sie deterministisch als gescheitert
   finalisiert, **bevor** der Listener den ersten Request annimmt (SOLL-065).
2. **Nur eigene Identität:** verwaiste Claims einer **fremden**
   `backend_instance_id` bleiben unangetastet (Negativtest); ihr einziger
   anderer Endweg ist `admin_abort` (SOLL-063/067 — fail-closed, kein
   Raten über fremde Prozesse).
3. **Instanz-Identität:** `backend_instance_id` ist über Neustarts stabil;
   `instance_incarnation` steigt bei jedem Boot streng monoton; jeder neu
   erworbene Claim trägt beide Werte (SOLL-063, IMPL-004).
4. **CAS-Fence:** ein Finalize mit veralteter `operation_epoch` (nach
   `admin_abort`) schlägt deterministisch fehl und hinterlässt höchstens einen
   No-op-/Abort-Vermerk — niemals ein zweites Ergebnis, niemals eine stille
   Zustandsänderung (SOLL-068; Test mit simuliertem Late-Executor).
5. **Teil-Write-Repair:** eine verwaiste/abgebrochene Operation mit bereits
   persistierten Engine-Writes geht in einen expliziten auditierten
   Reconcile-/Repair-Zustand über (nicht still `failed`); der Zustand ist über
   `GET /v1/project-edge/operations/{op_id}` sichtbar (IMPL-005; Test an der
   Phasengrenze dispatch→finalize).
6. **admin-abort-Endpoint:** bricht nur servereigene In-Flight-Claims ab;
   unbekannte `op_id` → 404, terminale Operation → 409 (deterministisch,
   fail-closed); Klasse `admin_transition`; jeder Abort ist auditiert
   (SOLL-069, SOLL-038-Anteil).
7. **CLI-Adapter:** `admin-abort` ruft ausschließlich den Endpoint (Regel 10);
   kein eigener DB-/Runtime-Pfad (Test pinnt die Delegation).
8. **Kein Wanduhr-Mechanismus:** diese Story fügt keinen TTL-/Lease-/
   Heartbeat-Pfad hinzu und entfernt die bestehende TTL **nicht**
   (`_CLAIM_LEASE_TTL` bleibt bis AG3-139 unverändert in Betrieb — Ist-Stand
   `runtime.py:83`; IMPL-006-Reihenfolge im Briefing dokumentiert).
9. **Fail-closed-Start:** schlägt die Start-Rekonsiliierung fehl, startet der
   Server nicht (kein Betrieb mit unklarem Claim-Bestand; Negativtest).
10. **Mutations-Sperre bei offenem Repair-Zustand:** eine Story/ein Run mit
    offenem Reconcile-/Repair-Zustand weist neue mutierende Operationen am
    Dispatch-/Operations-Layer deterministisch mit 409 + maschinenlesbarem
    Grund ab, bis der Zustand via `admin_abort`/Repair aufgelöst ist
    (fail-closed; Negativpfad-Test: mutierender Dispatch gegen eine Story im
    offenen Repair-Zustand wird abgewiesen, kein stilles Weiterarbeiten auf
    Teil-Write-Stand).
11. Coverage ≥ 85 %, `mypy` strict (+ `--platform linux`), `ruff` clean,
    ARCH-55 (englische Bezeichner/Wire-Keys/Fehlercodes).

## Definition of Done

- Alle Akzeptanzkriterien erfüllt; Gate-Suite grün (`pytest -n0`
  unit/integration/contract, Coverage ≥ 85, `mypy src` + `--platform linux`,
  `ruff`, 4 Konzept-Gates).
- Codex-Review PASS.
- Auf `origin/main` gemerged; `status.yaml` → `completed` (entsperrt AG3-139);
  README-Backlog-Snapshot (§6.7) nachgezogen.

## Abdeckung (Traceability)

**Deckt ab:** SOLL-038 (admin_abort-Anteil), SOLL-063, SOLL-064 (technische Instanz-Markierung), SOLL-065, SOLL-066 (operation-claims), SOLL-067–069; IMPL-003, IMPL-004 (Erzeugung/Boot-Inkarnation), IMPL-005, IMPL-023.

## Konzept-Referenzen

- FK-91 §91.1a Regel 16 (Instanzbindung, Start-Rekonsiliierung,
  Ein-Writer-Betriebsannahme), Regel 17 (Transport-Timeouts fachlich
  bedeutungslos; Reconcile via `GET operations/{op_id}`), Endpoint-Zeile
  `POST /v1/project-edge/operations/{op_id}/admin-abort`
- FK-10 §10.5.4 (Objekt-Serialisierung und Ein-Writer-Betriebsannahme;
  Start-Rekonsiliierung „der Server muss über seinen eigenen Absturz nicht
  spekulieren; über das Schweigen eines Clients schon")
- FK-55 §55.5 (op-class `admin_transition` inkl.
  `admin_abort_inflight_operation`)
- `formal.state-storage.invariants` →
  `object_mutation_claims_are_instance_bound_and_never_expire_by_wall_clock`,
  `orphaned_claims_are_finalized_only_by_same_instance_startup_reconciliation_or_admin_abort`,
  `operation_finalize_requires_cas_on_operation_epoch`
- `formal.state-storage.entities` → `state-storage.entity.inflight-operation-record`

## Guardrail-Referenzen

- **FAIL-CLOSED:** Kein Server-Start mit unklarem Claim-Bestand; fremde Claims
  werden nie „großzügig" mitbereinigt; Teil-Writes werden nie stillschweigend
  als `failed` wegerklärt.
- **FIX THE MODEL, NOT THE SYMPTOM:** Der Ersatz für die TTL ist ein
  deterministisches Identitäts-/Rekonsiliierungs-Modell — nicht eine weitere
  Heuristik (PID/Heartbeat) über fremde Prozesse.
- **NO ERROR BYPASSING:** `admin_abort` ist der einzige manuelle Endweg;
  keine Hintertür, die Claims „freiräumt".
- **SEVERITY-SEMANTIK:** Der Repair-Zustand ist ein Handlungsauftrag
  (sichtbar, auditiert), kein weggeklickter Zustand.
- **Sub-Agent-/Testregeln (CLAUDE.md §Tests):** Negativpfade an der
  Phasengrenze dispatch→finalize sind Pflicht; Pipeline-State nicht manuell
  zusammenfantasieren — die Teil-Write-Fixtures entstehen über den echten
  Dispatch-Pfad.

## Querschnitts-Auflagen

- **K5 Postgres-only:** Rekonsiliierungs-/Abort-Queries laufen ausschließlich
  gegen die Postgres-Control-Plane-Tabellen (fail-closed via
  `_require_postgres_control_plane_backend`, `control_plane/runtime.py:2119`);
  Integrationstests über die Postgres-Fixture, Unit-Tests über Ports/Fakes.
- **Kritische Ordnungs-Kante (Auflage §3):** ST-02 → ST-03 ist im Briefing
  begründet (IMPL-006): Die TTL ist heute das einzige Verwaisungs-Handling;
  erst wenn diese Story die Start-Rekonsiliierung produktiv ersetzt hat, darf
  AG3-139 die TTL entfernen. Kein Deployment-Zustand ohne Verwaisungs-Handling.
- **Blutgruppen-Klassifikation:** Rekonsiliierungs-/CAS-Entscheidungslogik
  (`startup_reconcile.py`-Kern, Epoch-Fence-Regeln) = **A**;
  Identitäts-Persistenz-Adapter + Row-Funktionen = **AT/T** (lokalisiert in
  `state_backend`); HTTP-Route/CLI-Adapter = **R**.
- **Bundle-Assets:** Keine betroffen (verifiziert: der admin-abort-Endpoint
  ist ein Server-/CLI-Pfad; das Bundle-Tool
  `bundles/target_project/tools/agentkit/projectedge.py` erhält
  Takeover-/Abort-Kommandos erst in AG3-154).
