# AG3-141 — Objekt-Serialisierung: durable Story-Claims vor Dispatch, bounded Warte-Semantik (K4)

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
- **Quell-Konzept:** FK-91 §91.1a Regel 13 (Deklarationspflicht; das
  serialisierte Objekt ist die Story `(project_key, story_id)`, durabler
  Objekt-Claim vor Dispatch; „Reads nehmen niemals Sperren"; kein
  projektweites Sperrobjekt/keine Lock-Sets); FK-10 §10.5.4 + §10.1.3
  (durable Objekt-Mutation-Claims vor Dispatch; xact-Locks nur für
  Ein-Transaktions-Mutationen); FK-17 §17.5 (Objekt-Serialisierung neben
  Single-Writer); `formal.state-storage.invariants`
  (`object_mutation_claims_are_instance_bound_and_never_expire_by_wall_clock`);
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
- Es fehlt: der durable per-**Story**-Objekt-Claim vor Dispatch mit einer
  deklarierten Warte-Semantik. (Ein projektweites Sperrobjekt, Lock-Sets und
  Queue-Fairness sind **nicht** nötig — keine Mutation braucht
  whole-project-Exklusivität über einen Dispatch; verifiziert 2026-07-04,
  Codex- + Fable-Analyse. Projektweit-atomare Vorgänge — Mode-Lock,
  Story-Nummernvergabe — bleiben Ein-Transaktion.)
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
2. **Deklarationspflicht (SOLL-048, Regel 13):** jede mutierende Story-Operation
   deklariert die **Story** `(project_key, story_id)` als Serialisierungsobjekt
   (an das Objekt gebunden, nicht an den Aufrufer). Die Deklaration wird am
   `inflight-operation-record` (`declared_serialization_scope`, AG3-137)
   persistiert. Reads deklarieren nichts und nehmen nie Sperren.
   **Kein projektweites Sperrobjekt, keine Lock-Sets:** es gibt kein
   `(project_key)`-Serialisierungsobjekt und keine Mehr-Objekt-Lock-Sets — keine
   Mutation braucht Exklusivität über das ganze Projekt hinweg über einen
   Dispatch (verifiziert 2026-07-04, Codex- + Fable-Analyse). Die früher hier
   geforderten SOLL-049 (Lock-Sets/globale Erwerbsordnung) und SOLL-050
   (Queue-Fairness) sind **entfallen**, ebenso die Invariante
   `pending_project_claims_are_not_overtaken_by_younger_story_claims` (FK-91
   Regel 13 und `formal.state-storage.invariants` entsprechend entschlackt).
3. **Warte-Semantik unter K4 (IMPL-016):** bei besetzter Story deterministisches
   `409` mit `Retry-After` — **kein Thread-Blocking** (thread-per-request +
   12-s-Frontend-Timeout). Die Antwortform ist Teil des Fehlervertrags (Regel 8:
   `error_code`, strukturierte `detail`); das Budget ist als Konstante gepinnt.
4. **Reads sperrenfrei (SOLL-048/053/055):** Verifikation, dass kein Read-Pfad
   einen Claim erwirbt oder auf einen wartet (inkl.
   `GET /v1/project-edge/operations/{op_id}`).
5. **Instanzbindung + Verwaisungs-Anschluss (SOLL-066, object-claims-Anteil):**
   Objekt-Claims tragen `backend_instance_id`/`instance_incarnation` und
   werden von der AG3-138-Start-Rekonsiliierung mit finalisiert (Erweiterung
   des Reconcile-Scans um `object_mutation_claims`); `admin_abort` gibt den
   Objekt-Claim der abgebrochenen Operation frei. **Kein** TTL, **kein**
   Wanduhr-Verfall.
6. **Abgrenzung Ein-Transaktions-Muster (SOLL-053/055):** `mode_lock`- und
   Story-Nummern-Pfade bleiben xact-basiert (dokumentierte, konzeptkonforme
   Ausnahme: Mutation vollständig in einer Transaktion — das sind die einzigen
   projektweit-atomaren Vorgänge und sie brauchen keinen durablen Claim); die
   Abgrenzung wird im Code dokumentiert und per Regressionstest gepinnt.
7. **Story-scoped Concurrency-Testmuster (IMPL-017):** wiederverwendbares
   Testmuster „zwei parallele Clients, eine Story" auf der Postgres-Fixture
   (injizierbare Seams analog `now_fn`/`token_factory` in
   `control_plane/runtime.py:243-250`): deterministisch gewinnt genau einer;
   der zweite erhält die deklarierte Warte-Antwort.
8. **`formal.story-workflow`-Serialisierungs-Anteil (SOLL-056/057):**
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
| `src/agentkit/backend/control_plane/object_claims.py` | neu | A-Kern: Story-Serialisierungsobjekt-Deklaration + K4-Warte-Entscheidung (409/Retry-After) |
| `src/agentkit/backend/control_plane/runtime.py` | ändern | Claim-Erwerb vor dem Dispatch (`start_phase` :304, `_mutate_phase` :1107, `complete_closure` :1123; Dispatch-Aufruf :864-871); Freigabe bei Finalize/Abort |
| `src/agentkit/backend/control_plane/models.py` | ändern | serverseitige Scope-Deklaration je Operationsart (kein neues Wire-Feld für Clients) |
| `src/agentkit/backend/control_plane/repository.py` | ändern | Ports: per-Story-Claim acquire/release |
| `src/agentkit/backend/state_backend/postgres_store.py` + `store/facade.py` (+ `_public_api_names.py`, `__init__.pyi`) | ändern | Row-Funktionen für atomaren per-Story-Claim-Erwerb/Freigabe (INSERT … ON CONFLICT auf dem Objekt-PK, konfliktfrei unter Parallellast) |
| `src/agentkit/backend/control_plane/startup_reconcile.py` (aus AG3-138) | ändern | Reconcile-Scan um `object_mutation_claims` erweitern; `admin_abort` gibt Objekt-Claims frei |
| `src/agentkit/backend/control_plane_http/app.py` | ändern | Antwortform `409 + Retry-After` im Fehlervertrag (kein Thread-Blocking) |
| `src/agentkit/backend/state_backend/store/mode_lock_repository.py`, `store/story_repository.py` | nicht ändern (pinnen) | Ein-TX-Ausnahmen bleiben; Regressionstest dokumentiert die Abgrenzung |
| `tests/unit/control_plane/**` | neu | Deklarations-/Warte-Entscheidungslogik über Fakes (deterministisch, ohne DB) |
| `tests/integration/**` | neu | Story-scoped Concurrency-Muster (IMPL-017) auf Postgres: 2 Clients / 1 Story; verschiedene Stories parallel; Crash → Reconcile gibt Claim frei |
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
4. **K4 eingehalten:** kein mutierender Handler blockiert (kein Thread-Blocking);
   bei besetzter Story kommt die deterministische `409 + Retry-After`-Antwort —
   Test mit dauerhaft gehaltenem Claim (IMPL-016); das Retry-After-Budget ist als
   Konstante deutlich < 12 s gepinnt.
5. **Kein Wanduhr-Verfall:** Objekt-Claims haben kein Expiry-Feld und keinen
   zeitbasierten Freigabepfad; der einzige nicht-administrative Endweg ist
   Finalize/Abort der eigenen Operation (SOLL-066, object-claims-Anteil;
   Negativtest: gehaltener Claim bleibt über beliebige Testzeit bestehen).
6. **Ein-TX-Ausnahmen unverändert:** `mode_lock`- und
   Story-Nummern-Serialisierung verhalten sich unverändert (bestehende Tests
   grün); die Abgrenzung (xact-Lock nur bei Ein-Transaktions-Mutation) ist im
   Code dokumentiert (SOLL-053/055).
7. **formal-Wortlaut:** run-phase/resume sind „object-serialized" im Sinne
   der `formal.story-workflow.commands` (Contract-Pin; SOLL-056/057
   Serialisierungs-Anteil).
8. Coverage ≥ 85 %, `mypy` strict (+ `--platform linux`), `ruff`, ARCH-55.

## Definition of Done

- Alle Akzeptanzkriterien erfüllt; Gate-Suite grün (`pytest -n0`
  unit/integration/contract, Coverage ≥ 85, `mypy src` + `--platform linux`,
  `ruff`, 4 Konzept-Gates).
- Codex-Review PASS.
- Auf `origin/main` gemerged; `status.yaml` → `completed` (Beitrag zur
  Entsperrung von AG3-148); README-Backlog-Snapshot (§6.7) nachgezogen.

## Abdeckung (Traceability)

**Deckt ab:** SOLL-048 (Story-Scope), SOLL-053–055, SOLL-056 (Serialisierungs-Anteil), SOLL-057 (Serialisierungs-Anteil), SOLL-066 (object-claims); IMPL-016, IMPL-017.

**Entfallen (verifiziert 2026-07-04, Codex- + Fable-Analyse — kein realer Aufrufer für ein projektweites Sperrobjekt):** SOLL-049 (Lock-Sets/globale Erwerbsordnung), SOLL-050 (Queue-Fairness). Projektweit-atomare Vorgänge (Mode-Lock, Story-Nummernvergabe) bleiben Ein-Transaktion (xact-Lock, SOLL-053/055) und brauchen keinen durablen Projekt-Claim. FK-91 Regel 13 und `formal.state-storage.invariants` (Invariante `pending_project_claims_are_not_overtaken_by_younger_story_claims`) wurden entsprechend entschlackt.

## Konzept-Referenzen

- FK-91 §91.1a Regel 13 (Serialisierungsobjekt-Deklarationspflicht; das
  serialisierte Objekt ist die Story `(project_key, story_id)`, durabler
  Objekt-Claim vor Dispatch; „Reads nehmen niemals Sperren"; kein projektweites
  Sperrobjekt / keine Lock-Sets — projektweit-atomare Vorgänge sind
  Ein-Transaktion)
- FK-10 §10.5.4 (durable Objekt-Mutation-Claim-Zeile VOR dem Dispatch, weil
  Engine-Writes und Finalize in getrennten Transaktionen laufen; xact-Locks
  nur für Ein-Transaktions-Mutationen; Instanzbindung), §10.1.3
  (Serialisierung ist Aufgabe des Backends; präzisiert auf durable Claims,
  Reads sperrenfrei)
- FK-17 §17.5 (Objekt-Serialisierung neben Single-Writer: Single-Writer
  regelt *wer*, Objekt-Serialisierung *wann*)
- `formal.state-storage.entities` → `state-storage.entity.object-mutation-claim`;
  `formal.state-storage.invariants` →
  `object_mutation_claims_are_instance_bound_and_never_expire_by_wall_clock`
  (die Invariante `pending_project_claims_are_not_overtaken_by_younger_story_claims`
  ist mit dem projektweiten Sperrobjekt entfallen)
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
  zusammengebautem Ersatz-State; gültige UND ungültige Übergänge (besetzte
  Story → deterministisches `409`; Crash nach Claim-Erwerb → Freigabe nur
  über Reconcile/`admin_abort`) sind verprobt.

## Querschnitts-Auflagen

- **K4 (Pflicht-Auflage dieser Story):** 12-s-Frontend-Timeout
  (`frontend/app/api.ts:156-186`, AbortController :157) + thread-per-request
  (`ThreadingHTTPSServer`, `control_plane_http/app.py:1458`) verbieten langes
  blockierendes Warten. Umsetzungs-Constraint: deterministisches
  `409 + Retry-After`, **kein** Thread-Blocking; das Retry-After-Budget ist
  im Code als Konstante (deutlich unter 12 s) gepinnt und getestet.
- **K5 Postgres-only:** der per-Story-Claim-Erwerb/-Freigabe läuft ausschließlich gegen die
  Postgres-`object_mutation_claims`-Tabelle (fail-closed,
  `_require_postgres_control_plane_backend`, `control_plane/runtime.py:2119`);
  kein SQLite-Spiegel; Unit-Tests über Ports/Fakes,
  Integration/Contract über die Postgres-Fixture.
- **Blutgruppen-Klassifikation:** `object_claims.py`
  (Story-Serialisierungsobjekt-Deklaration + K4-Warte-Entscheidung) = **A** (rein,
  ohne DB testbar); Scope-Ableitung je Operationsart = **R**; atomare per-Story
  Claim-Row-Funktionen (INSERT … ON CONFLICT) = **AT** (konstitutive Mediation,
  lokalisiert in `state_backend`).
- **Bundle-Assets:** Keine betroffen (verifiziert: die Serialisierung ist
  serverseitig transparent; Clients sehen nur die dokumentierte
  409/Retry-After-Antwortform. `bundles/target_project/tools/agentkit/projectedge.py`
  behandelt Fehlerantworten bereits generisch und wird nicht geändert).
