# AG3-141 — Objekt-Serialisierung: durable Story-/Projekt-Claims vor Dispatch, Lock-Sets, Queue-Fairness, bounded Warte-Semantik

- **Typ:** implementation
- **Größe:** L
- **depends_on:**
  - [AG3-137] — die `object_mutation_claims`-Tabelle und die
    `declared_serialization_scope`-Spalte am `inflight-operation-record`
    entstehen dort (GAP §4: ST-01 → ST-05).
  - [AG3-138] — Objekt-Claims sind instanzgebunden und verfallen nie per
    Wanduhr; ohne die Startup-Rekonsiliierung (+ `admin_abort`) aus AG3-138
    würde ein verwaister Objekt-Claim die Story für immer blockieren — das
    Verwaisungs-Handling ist harte Vorbedingung (GAP §4: „ST-05 ← ST-01,
    ST-02").
- **Quell-Konzept:** FK-91 §91.1a Regel 13 (Deklarationspflicht, Lock-Set,
  Erwerbsordnung, Queue-Fairness, „Reads nehmen niemals Sperren");
  FK-10 §10.5.4 + §10.1.3 (durable Objekt-Mutation-Claims vor Dispatch;
  xact-Locks nur für Ein-Transaktions-Mutationen); FK-17 §17.5
  (Objekt-Serialisierung neben Single-Writer);
  `formal.state-storage.invariants`
  (`pending_project_claims_are_not_overtaken_by_younger_story_claims`,
  `object_mutation_claims_are_instance_bound_and_never_expire_by_wall_clock`);
  `formal.story-workflow.commands` (run-phase/resume:
  „instance-bound, object-serialized" — Serialisierungs-Anteil)
- **Herkunft:** GAP-Analyse Session-Ownership v4 (`_temp/gap-analyse-session-ownership.md`),
  Story-Kandidat GAP-ST-05; normative Basis Commits 3ae011e4 / 1bb4ed8a / 58c190b7
  (+ Decision-Records unter `concept/_meta/decisions/`).

## Kontext / Problem

Regel 4 des Session-Ownership-Strangs (stories/README.md §6.7): die **einzige**
technische Nebenläufigkeits-Garantie ist In-Flight-Idempotenz plus
**Serialisierung pro mutiertem Objekt** — Mutationen laufen sequenziell pro
Objekt (PO-Entscheidung: das gesperrte Objekt ist die **Story**), **an das
Objekt gebunden, nicht an den Aufrufer**; Reads sind immer frei parallel.
Der Ist-Zustand (am Code verifiziert 2026-07-02):

- Serialisiert wird heute nur **pro `op_id`** (PK
  `control_plane_operations.op_id`,
  `state_backend/postgres_schema.sql:231-245`): zwei parallele Mutationen
  derselben Story mit **verschiedenen** `op_id`s laufen ungeordnet
  nebeneinander. Die Engine-Writes passieren dabei in eigenen Transaktionen
  vor dem Finalize (`control_plane/dispatch.py:246` →
  `engine.run_phase`/`resume_phase` :416/:424) — genau deshalb reicht ein
  transaktionsgebundenes Lock nicht und FK-10 §10.5.4 fordert den **durablen**
  Claim, der vor dem Dispatch erworben und bis Finalize/Abort gehalten wird.
- Ein tragfähiges **Ein-Transaktions-Muster existiert** und bleibt: das
  `project_mode_lock` serialisiert per `pg_advisory_xact_lock`
  (`state_backend/store/mode_lock_repository.py:423`, `FOR UPDATE` :428;
  SQLite-Zweig `BEGIN IMMEDIATE` :380) und die Story-Nummernvergabe per
  `FOR UPDATE` (`store/story_repository.py:889`) — beides vollständig in
  einer Transaktion, konzeptkonform (FK-10 §10.5.4).
- Es fehlen vollständig: durable per-Objekt-Claim vor Dispatch, Lock-Sets mit
  globaler Erwerbsordnung, Queue-Fairness, eine deklarierte Warte-Semantik.
- **Constraint K4 (verifiziert):** das Frontend bricht jeden Request nach
  **12 s** ab (`AbortController` + 12000-ms-Timeout,
  `src/agentkit/frontend/app/api.ts:156-186`, Timeout :157) und der Server ist
  thread-per-request (`ThreadingHTTPSServer`,
  `control_plane_http/app.py:1458`). Langes blockierendes Warten auf einen
  Objekt-Claim ist damit ausgeschlossen: die Warte-Semantik ist
  `409 + Retry-After` oder kurzes **bounded** Warten (IMPL-016).

## Scope

### In Scope

1. **Durabler Objekt-Claim vor Dispatch (SOLL-054):** jede mutierende
   Control-Plane-Operation erwirbt VOR dem Dispatch einen durablen Claim in
   `object_mutation_claims` (AG3-137) auf ihr deklariertes
   Serialisierungsobjekt und hält ihn bis Finalize/Abort. Der Claim ist an
   das **Objekt** gebunden (Identität
   `project_key + serialization_scope + scope_key`), nicht an den Aufrufer —
   welcher Client/Principal die Mutation trägt, ist für die Serialisierung
   irrelevant.
2. **Deklarationspflicht (SOLL-048, Regel 13):** jede Mutation deklariert ihr
   Serialisierungsobjekt; Default für umsetzungs-/lifecyclebezogene
   Mutationen ist `(project_key, story_id)`, projektweite Mutationen
   deklarieren `(project_key)`. Die Deklaration wird am
   `inflight-operation-record` (`declared_serialization_scope`, AG3-137)
   persistiert. Reads deklarieren nichts und nehmen nie Sperren.
3. **Lock-Sets + globale Erwerbsordnung (SOLL-049):** Mehr-Objekt-Mutationen
   deklarieren ein Lock-Set; Erwerb strikt in globaler Ordnung — erst der
   Projekt-Claim, dann Story-Claims in lexikographischer
   `story_id`-Reihenfolge; niemals einen Story-Claim halten und danach den
   Projekt-Claim anfordern (strukturell erzwungen, nicht Konvention).
4. **Queue-Fairness (SOLL-050):** ein wartender Projekt-Claim konfligiert
   auch mit später eintreffenden Story-Claims desselben Projekts (jüngere
   Story-Claims überholen ihn nicht); administrative Übergänge haben
   definierte FIFO-Fairness (`queue_position`-Attribut aus AG3-137;
   Invariante `pending_project_claims_are_not_overtaken_by_younger_story_claims`).
5. **Warte-Semantik unter K4 (IMPL-016):** bei besetztem Objekt entweder
   deterministisches `409` mit `Retry-After` oder kurzes bounded Warten mit
   hartem Budget deutlich unter 12 s (konkreter Wert = Designentscheidung der
   Story, testbar gepinnt). Niemals unbegrenztes Blocking; die Antwortform ist
   Teil des Fehlervertrags (Regel 8: `error_code`, strukturierte `detail`).
6. **Reads sperrenfrei (SOLL-048/053/055):** Verifikation, dass kein Read-Pfad
   einen Claim erwirbt oder auf einen wartet (inkl.
   `GET /v1/project-edge/operations/{op_id}`).
7. **Instanzbindung + Verwaisungs-Anschluss (SOLL-066, object-claims-Anteil):**
   Objekt-Claims tragen `backend_instance_id`/`instance_incarnation` und
   werden von der AG3-138-Start-Rekonsiliierung mit finalisiert (Erweiterung
   des Reconcile-Scans um `object_mutation_claims`); `admin_abort` gibt den
   Objekt-Claim der abgebrochenen Operation frei. **Kein** TTL, **kein**
   Wanduhr-Verfall.
8. **Abgrenzung Ein-Transaktions-Muster (SOLL-053/055):** `mode_lock`- und
   Story-Nummern-Pfade bleiben xact-basiert (dokumentierte, konzeptkonforme
   Ausnahme: Mutation vollständig in einer Transaktion); die Abgrenzung wird
   im Code dokumentiert und per Regressionstest gepinnt.
9. **Story-scoped Concurrency-Testmuster (IMPL-017):** wiederverwendbares
   Testmuster „zwei parallele Clients, eine Story" auf der Postgres-Fixture
   (injizierbare Seams analog `now_fn`/`token_factory` in
   `control_plane/runtime.py:243-250`): deterministisch gewinnt genau einer;
   der zweite erhält die deklarierte Warte-Antwort.
10. **`formal.story-workflow`-Serialisierungs-Anteil (SOLL-056/057):**
    run-phase-/resume-Mutationen serialisieren zusätzlich zur
    op_id-Idempotenz pro deklariertem Objekt („instance-bound,
    object-serialized") — Contract-Test gegen den formalen Wortlaut.

### Out of Scope (mit Owner)

- **op_id-Vertragsanteil von SOLL-056/057** (Client-op_id-Pflicht,
  Idempotenz-Konsolidierung): **AG3-140**.
- **Startup-Rekonsiliierungs-Grundgerüst, Instanz-Identität, `admin_abort`**:
  **AG3-138** (hier nur der Anschluss der Objekt-Claims).
- **Ownership-/Epoch-Fencing der Regime-Pfade** (wer mutieren DARF —
  Serialisierung regelt nur WANN): **AG3-142**.
- **Bounded-Pflicht-Registry + 202-Job-Muster + Ergebnisarten** (Regeln
  14/15; Jobs halten zwischen Annahme und Abschluss keine Serialisierung):
  **AG3-144**. Diese Story serialisiert die heute synchronen Mutationen.
- **Ownership-Transfer als objekt-serialisierte Mutation** (Confirm nutzt den
  Story-Claim): **AG3-148** (GAP §4: Kante ST-05 → ST-07a).
- **Frontend-Anpassungen über die bestehende Fehlerbehandlung hinaus**
  (Takeover-UI etc.): **AG3-153**.

## Betroffene Dateien

| Datei | Änderungsart | Zweck |
|---|---|---|
| `src/agentkit/backend/control_plane/object_claims.py` | neu | A-Kern: Deklarationsmodell, Lock-Set-Bildung, globale Erwerbsordnung, Fairness-Regeln, Warte-Entscheidung |
| `src/agentkit/backend/control_plane/runtime.py` | ändern | Claim-Erwerb vor dem Dispatch (`start_phase` :304, `_mutate_phase` :1107, `complete_closure` :1123; Dispatch-Aufruf :864-871); Freigabe bei Finalize/Abort |
| `src/agentkit/backend/control_plane/models.py` | ändern | serverseitige Scope-Deklaration je Operationsart (kein neues Wire-Feld für Clients) |
| `src/agentkit/backend/control_plane/repository.py` | ändern | Ports: acquire/release/queue-Position/Fairness-Query |
| `src/agentkit/backend/state_backend/postgres_store.py` + `store/facade.py` (+ `_public_api_names.py`, `__init__.pyi`) | ändern | Row-Funktionen für atomaren Claim-Erwerb/Queue/Freigabe (konfliktfrei unter Parallellast) |
| `src/agentkit/backend/control_plane/startup_reconcile.py` (aus AG3-138) | ändern | Reconcile-Scan um `object_mutation_claims` erweitern; `admin_abort` gibt Objekt-Claims frei |
| `src/agentkit/backend/control_plane_http/app.py` | ändern | Antwortform `409 + Retry-After` bzw. bounded-Wait-Ergebnis im Fehlervertrag |
| `src/agentkit/backend/state_backend/store/mode_lock_repository.py`, `store/story_repository.py` | nicht ändern (pinnen) | Ein-TX-Ausnahmen bleiben; Regressionstest dokumentiert die Abgrenzung |
| `tests/unit/control_plane/**` | neu | Ordnungs-/Fairness-/Deklarationslogik über Fakes (deterministisch, ohne DB) |
| `tests/integration/**` | neu | Story-scoped Concurrency-Muster (IMPL-017) auf Postgres: 2 Clients / 1 Story; Projekt- vs. Story-Claim-Fairness; Crash → Reconcile gibt Claim frei |
| `tests/contract/**` | neu/ändern | Fehlervertrag der Warte-Semantik (409/Retry-After-Form); formal-Wortlaut-Pins run-phase/resume |

## Akzeptanzkriterien

1. **Claim vor Dispatch:** vor jeder mutierenden Story-Operation existiert
   ein durabler `object_mutation_claims`-Eintrag; ein Crash nach Claim-Erwerb
   und vor Finalize hinterlässt einen Claim, der ausschließlich über die
   AG3-138-Start-Rekonsiliierung bzw. `admin_abort` finalisiert wird
   (Integrationstest an der Phasengrenze Claim→Dispatch→Crash).
2. **Story-Serialisierung bewiesen (IMPL-017):** zwei parallele Mutationen
   derselben Story mit verschiedenen `op_id`s — genau eine dispatcht; die
   zweite erhält deterministisch die deklarierte Warte-Antwort; es entstehen
   keine parallelen Engine-Writes derselben Story (Concurrency-Test auf der
   Postgres-Fixture, wiederholbar deterministisch).
3. **Parallelität bleibt:** Mutationen **verschiedener** Stories desselben
   Projekts laufen parallel (kein globales Lock; Test), und Reads laufen
   uneingeschränkt parallel zu einer laufenden Mutation (Reads nehmen nie
   Sperren — Test + Code-Verifikation).
4. **Erwerbsordnung strukturell erzwungen:** die Lock-Set-Mechanik kann die
   Ordnung Projekt → Stories (lexikographisch) nicht verletzen; der Versuch
   „Story-Claim halten, dann Projekt-Claim anfordern" ist als API nicht
   ausdrückbar bzw. wird fail-closed abgewiesen (Unit-Test; SOLL-049).
5. **Queue-Fairness:** ein wartender Projekt-Claim wird nicht von später
   eintreffenden Story-Claims desselben Projekts überholt
   (Integrationstest gegen
   `pending_project_claims_are_not_overtaken_by_younger_story_claims`);
   administrative Übergänge folgen FIFO (SOLL-050).
6. **K4 eingehalten:** kein mutierender Handler blockiert länger als das
   gewählte bounded-Wait-Budget (hart < 12 s, konkreter Wert gepinnt); bei
   besetztem Objekt kommt die deterministische `409 + Retry-After`-Antwort
   bzw. das bounded Ergebnis — Test mit dauerhaft gehaltenem Claim
   (IMPL-016).
7. **Kein Wanduhr-Verfall:** Objekt-Claims haben kein Expiry-Feld und keinen
   zeitbasierten Freigabepfad; der einzige nicht-administrative Endweg ist
   Finalize/Abort der eigenen Operation (SOLL-066, object-claims-Anteil;
   Negativtest: gehaltener Claim bleibt über beliebige Testzeit bestehen).
8. **Ein-TX-Ausnahmen unverändert:** `mode_lock`- und
   Story-Nummern-Serialisierung verhalten sich unverändert (bestehende Tests
   grün); die Abgrenzung (xact-Lock nur bei Ein-Transaktions-Mutation) ist im
   Code dokumentiert (SOLL-053/055).
9. **formal-Wortlaut:** run-phase/resume sind „object-serialized" im Sinne
   der `formal.story-workflow.commands` (Contract-Pin; SOLL-056/057
   Serialisierungs-Anteil).
10. Coverage ≥ 85 %, `mypy` strict (+ `--platform linux`), `ruff`, ARCH-55.

## Definition of Done

- Alle Akzeptanzkriterien erfüllt; Gate-Suite grün (`pytest -n0`
  unit/integration/contract, Coverage ≥ 85, `mypy src` + `--platform linux`,
  `ruff`, 4 Konzept-Gates).
- Codex-Review PASS.
- Auf `origin/main` gemerged; `status.yaml` → `completed` (Beitrag zur
  Entsperrung von AG3-148); README-Backlog-Snapshot (§6.7) nachgezogen.

## Abdeckung (Traceability)

**Deckt ab:** SOLL-048–050, SOLL-053–055, SOLL-056 (Serialisierungs-Anteil), SOLL-057 (Serialisierungs-Anteil), SOLL-066 (object-claims); IMPL-016, IMPL-017.

## Konzept-Referenzen

- FK-91 §91.1a Regel 13 (Serialisierungsobjekt-Deklarationspflicht; Default
  `(project_key, story_id)`; Lock-Set mit globaler Erwerbsordnung;
  Queue-Fairness; „Reads nehmen niemals Sperren")
- FK-10 §10.5.4 (durable Objekt-Mutation-Claim-Zeile VOR dem Dispatch, weil
  Engine-Writes und Finalize in getrennten Transaktionen laufen; xact-Locks
  nur für Ein-Transaktions-Mutationen; Instanzbindung), §10.1.3
  (Serialisierung ist Aufgabe des Backends; präzisiert auf durable Claims,
  Reads sperrenfrei)
- FK-17 §17.5 (Objekt-Serialisierung neben Single-Writer: Single-Writer
  regelt *wer*, Objekt-Serialisierung *wann*)
- `formal.state-storage.entities` → `state-storage.entity.object-mutation-claim`;
  `formal.state-storage.invariants` →
  `object_mutation_claims_are_instance_bound_and_never_expire_by_wall_clock`,
  `pending_project_claims_are_not_overtaken_by_younger_story_claims`
- `formal.story-workflow.commands` → run-phase/resume („in-flight operation
  claim — instance-bound, object-serialized; mutations additionally serialize
  per declared serialization object, default (project_key, story_id)") —
  **Serialisierungs-Anteil**

## Guardrail-Referenzen

- **FIX THE MODEL, NOT THE SYMPTOM:** Nebenläufigkeit wird am Objekt
  modelliert (Story-Claim), nicht mit Retries, Sleeps oder aufruferbezogenen
  Sperren beruhigt.
- **FAIL-CLOSED:** besetztes Objekt → deterministische, strukturierte
  Ablehnung/bounded Antwort; niemals stilles Überholen, niemals unbegrenztes
  Hängen im Thread-per-Request-Server.
- **WORKFLOW-/STATE-DISZIPLIN:** die Claim-Wahrheit lebt ausschließlich in
  `object_mutation_claims` (AG3-137-Owner); kein zweiter Lock-Mechanismus,
  keine Schatten-Sperrdateien.
- **Tests (CLAUDE.md §Tests):** Concurrency-Verhalten wird an echten
  Phasengrenzen bewiesen (echter Dispatch-Pfad, Postgres-Fixture), nicht an
  zusammengebautem Ersatz-State; gültige UND ungültige Übergänge
  (Fairness-Verletzung, Ordnungs-Verletzung) sind verprobt.

## Querschnitts-Auflagen

- **K4 (Pflicht-Auflage dieser Story):** 12-s-Frontend-Timeout
  (`frontend/app/api.ts:156-186`, AbortController :157) + thread-per-request
  (`ThreadingHTTPSServer`, `control_plane_http/app.py:1458`) verbieten langes
  blockierendes Warten. Umsetzungs-Constraint: `409 + Retry-After` oder
  kurzes bounded Warten mit hartem Budget deutlich unter 12 s; das Budget ist
  im Code als Konstante gepinnt und getestet.
- **K5 Postgres-only:** Claim-Erwerb/Queue laufen ausschließlich gegen die
  Postgres-`object_mutation_claims`-Tabelle (fail-closed,
  `_require_postgres_control_plane_backend`, `control_plane/runtime.py:2119`);
  kein SQLite-Spiegel; Unit-Tests über Ports/Fakes,
  Integration/Contract über die Postgres-Fixture.
- **Blutgruppen-Klassifikation:** `object_claims.py`
  (Deklaration/Ordnung/Fairness-Entscheidungslogik) = **A** (rein, ohne DB
  testbar); Scope-Ableitung je Operationsart = **R**; atomare
  Claim-Row-Funktionen inkl. Queue-Mechanik = **AT** (konstitutive Mediation,
  lokalisiert in `state_backend`).
- **Bundle-Assets:** Keine betroffen (verifiziert: die Serialisierung ist
  serverseitig transparent; Clients sehen nur die dokumentierte
  409/Retry-After-Antwortform. `bundles/target_project/tools/agentkit/projectedge.py`
  behandelt Fehlerantworten bereits generisch und wird nicht geändert).
