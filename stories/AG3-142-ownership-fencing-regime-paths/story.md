# AG3-142 — Ownership-Fencing der Regime-Pfade: Record-Schreiben im Setup, `ownership_epoch`-Fence in start/complete/fail/closure/Executor, Ablösung von `_run_admission_evidence`, Ex-Owner-Fehlerbild

- **Typ:** implementation
- **Größe:** L
- **depends_on:** [AG3-137] — die Records und Repositories, gegen die diese
  Story fenct (`RunOwnershipRecord` mit `ownership_epoch`/`status`/
  `acquired_via`, Binding-`status` + Revocation-Grund-Vokabular inkl.
  `ownership_transferred`, monotone `binding_version`), entstehen in AG3-137
  (GAP §4: ST-01 → ST-06). Diese Story ändert das VERHALTEN, nicht das Schema.
- **Quell-Konzept:** FK-56 §56.7/§56.7a/§56.8/§56.8a (+ §56.13c nur
  Fence-/Fehlerbild-Wirkung auf den Ex-Owner); FK-91 §91.1a Regeln 15
  (Ownership-Prädikate), 17 (Reads/Reconcile), 18 (Ex-Owner-Fehlerbild);
  FK-17 §17.3.15/§17.3.16/§17.4; `formal.operating-modes.invariants`
  (`historical_ownership_records_are_never_admission_evidence`,
  `story_execution_mutations_require_current_ownership_epoch`)
- **Herkunft:** GAP-Analyse Session-Ownership v4 (`_temp/gap-analyse-session-ownership.md`),
  Story-Kandidat GAP-ST-06; normative Basis Commits 3ae011e4 / 1bb4ed8a / 58c190b7
  (+ Decision-Records unter `concept/_meta/decisions/`).

## Kontext / Problem

FK-56 §56.8a verlangt, dass **jeder** mutierende Pfad des Execution-Regimes —
ausdrücklich auch `complete_phase`, `fail_phase`, die Closure und die
serverseitigen Executor-Pfade — gegen `owner_session_id` + `ownership_epoch`
des aktiven Run-Ownership-Records fenct. Heute fenct **kein einziger** Pfad
(am Code verifiziert 2026-07-02; Grep `ownership_epoch`/`owner_session_id` in
`src/agentkit/`: null Treffer):

- Die Run-Admission ist eine **committed-op-Heuristik**:
  `_run_admission_evidence` (`src/agentkit/backend/control_plane/runtime.py:1051-1092`)
  admittiert bei Binding-Match (:1082-1089) ODER bei **irgendeiner** committed
  Run-Operation (:1090, `has_committed_operation_for_run`); geblockt wird nur
  über die Exit-Fence (:1078, `has_committed_story_exit_operation_for_run`).
  Ein entmündigter Ex-Owner könnte sich damit über seine eigenen historischen
  committed Ops **re-admittieren** — exakt der Verstoß gegen
  `historical_ownership_records_are_never_admission_evidence`. Tatsächliche
  Call-Sites: `_start_phase_after_claim` (:446), `_dispatch_phase` (:865),
  `_run_was_admitted` (:1024, gemeinsamer complete/fail-Pfad
  `_mutate_admitted_phase` :915) und `_closure_run_was_admitted` (:1044).
  (gap-02 nannte :846/:961 — das sind Docstring-Erwähnung bzw. der
  `_mutate_phase`-Aufruf; Divergenz im Ergebnisbericht gemeldet, Substanz
  unverändert.)
- Die Regime-Pfade `start_phase` (:304), `complete_phase` (:887), `fail_phase`
  (:901), `complete_closure` (:1123) und `resume_phase` (:1222) kennen weder
  Ownership-Record noch Epoche.
- `complete`/`fail` **re-materialisieren die Bindung** über den Planner:
  `_mutate_phase` (:1759) nutzt `_plan_story_scoped_materialization`
  (Binding-Bau :1969-1979) — ein Ex-Owner-complete würde die fremde Bindung
  neu schreiben statt abgewiesen zu werden.
- Es gibt **kein Ex-Owner-Fehlerbild**: keine `ownership_transferred`-Payload,
  kein 409/403-Vertrag nach FK-91 Regel 18 (Grep `ownership_transferred` in
  `src/agentkit/`: null Treffer).
- Der Edge kennt drei `binding_invalid`-Gründe
  (`src/agentkit/harness_client/projectedge/runtime.py` —
  `session_binding_mismatch` :214, `inactive_story_execution_lock` :226,
  `worktree_root_mismatch` :234); der Grund `ownership_transferred`
  (FK-56 §56.7a) fehlt.

**Tragfähige Präzedenz:** Das atomare CAS-Finalize-Muster
`_finalize_start_phase` (:684-755, CAS :738 — Verlierer schreibt keine
Side-Effects) trägt und ist der Andockpunkt, an dem der Ownership-Record
atomar mit dem Setup-Start-Commit geschrieben wird. Die Control-Plane ist
fail-closed Postgres-only (`_require_postgres_control_plane_backend`,
`runtime.py:2119`, Check :2139).

Ohne diese Story bleiben AG3-144 (Job-/Upsert-Fences), AG3-145
(Command-Queue-Result-Fencing) und AG3-148 (Transfer-Kern) ohne die
Fence-Fläche, gegen die sie committen.

## Scope

### In Scope

1. **RunOwnershipRecord-Schreiben im Setup-Start** (SOLL-015-Basis): Der
   committete Setup-Start eines Runs schreibt den aktiven Record
   (`ownership_epoch=1`, `acquired_via='setup'`, `owner_session_id` =
   Session des Starts, `audit_ref` = op_id) **atomar in derselben
   Transaktion** wie das Claim-CAS-Finalize (`_finalize_start_phase`
   :684-755). Gilt für Standard-, Exploration- UND Fast-Starts — auch der
   Fast-Start (der keine Bindung materialisiert) erhält damit
   Record-Evidenz. Der Claim-CAS-Verlierer schreibt keinen Record.
2. **`ownership_epoch`-Fence in ALLEN Regime-Mutationspfaden** (SOLL-015):
   `start_phase` (:304), `complete_phase` (:887), `fail_phase` (:901),
   `resume_phase` (:1222), `complete_closure` (:1123) und der serverseitige
   Executor-Pfad (`dispatch()` `control_plane/dispatch.py:246`,
   Engine-Einstiege :416/:424) prüfen am Commit-Zeitpunkt in derselben
   Transaktion: aktiver Record existiert, `owner_session_id` passt,
   `ownership_epoch` unverändert. System-Principals
   (`pipeline_deterministic`, `admin_service`) sind **gefencte Executor im
   Auftrag des Regimes**, keine konkurrierenden Owner (SOLL-016) — ihre
   Commits laufen durch denselben Fence.
3. **Ablösung `_run_admission_evidence`** (IMPL-021, SOLL-014): Die
   **positive committed-op-Evidenz** (:1090) entfällt ersatzlos; Admission-
   Evidenz ist ausschließlich der aktive Ownership-Record (plus dessen
   Bindungs-Projektion). Records mit `status != 'active'` sind reine
   Audit-Fakten und admittieren nie. **Übergangsschutz:** die
   Exit-Fence-Negativprüfung (:1078) bleibt bestehen, bis AG3-149 den
   Disown-Baustein den Record-Status (`ended`/`reset`/`split`) pflegen
   lässt — abgelöst wird die positive Heuristik, nicht der Exit-Block.
4. **Widerspruchsregel Bindung vs. Record** (SOLL-018, SOLL-019): Die
   Bindung bleibt session-seitige Projektion; bei Widerspruch zwischen
   Bindung und aktivem Record entscheidet der Record. Die Binding-
   Re-Materialisierung in `_mutate_phase`/`_plan_story_scoped_materialization`
   (:1759/:1969-1979) ist nur noch für den gefencten, admittierten Owner
   erreichbar.
5. **Ex-Owner-Fehlerbild** (SOLL-033 Fehlerbild-Anteil, SOLL-042, IMPL-019):
   Mutierende Calls einer Session, deren Run-Ownership nicht (mehr) dem
   aktiven Record entspricht, werden deterministisch mit `409` bzw. `403`
   und einer strukturierten `ownership_transferred`-Payload abgewiesen —
   mindestens Grund, neuer Owner, Transfer-Zeitpunkt — eingebettet in den
   Fehlervertrag aus FK-91 Regel 8 (`error_code`/`error`/`correlation_id`).
   Kein stiller Rückfall auf `ai_augmented`. Reads — einschließlich
   `GET /v1/project-edge/operations/{op_id}` zur Rekonsiliierung eigener
   früherer Mutationen (`get_operation` :1749) — bleiben erlaubt
   (FK-91 Regel 17/18).
6. **`binding_invalid`-Grund `ownership_transferred` als Verhalten**
   (SOLL-034 Verhaltens-Anteil): Der Edge-Resolve
   (`harness_client/projectedge/runtime.py:210-236`) und die serverseitige
   Bindungs-Auflösung liefern bei revozierter Bindung mit Grund
   `ownership_transferred` deterministisch `binding_invalid` mit
   maschinenlesbarem `block_reason='ownership_transferred'` (Grund ist
   Attribut, kein Status pro Ursache — FK-56 §56.7a; das Vokabular kommt
   aus dem AG3-137-Schema).
7. **Accountability-Stempel** (SOLL-017): Committete Regime-Operationen und
   ihre Lifecycle-Events tragen den `ownership_epoch`, unter dem sie
   committet wurden; fachliche Kontinuität (Artefakte/Attempts/QA) bleibt
   am `run_id`.

### Out of Scope (mit Owner)

- **Schema, Records, Repositories, Backfill** (Tabellen, Enums, Partial-
  Unique, Binding-Status, monotone Version): **AG3-137**.
- **Transfer selbst** (Challenge/Confirm, CAS auf `ownership_epoch+1`,
  Approval-Queue, `pending_human_approval`, atomarer Vollzug): **AG3-148**.
  Bis dahin entsteht der Zustand „transferred" nur in Tests über die
  sanktionierte AG3-137-Schreibfläche des Single-Writers.
- **Disown-VERHALTEN von SOLL-033** (Owner-Notification beim nächsten
  Kontakt, Edge-Tombstone-Vereinheitlichung, deterministische
  Reconcile-Antwort, Exit-/Reset-/Split-Reuse, Record-Status-Pflege durch
  die Beendigungspfade) sowie Ping-Pong-Schranke: **AG3-149**.
- **Freeze-Zustände als Admission-Blocker** (`freeze_epoch`,
  Challenge-Invalidierung): **AG3-150**.
- **Job-Ergebnis-Fences auf artifact-/QA-/closure-Upserts** (nutzt die hier
  gebaute Fence-Fläche): **AG3-144**.
- **Edge-Command-Queue-Result-Fencing** (FK-91 §91.1b, prüft gegen den
  aktiven Record): **AG3-145**.
- **TTL-Entfall**: **AG3-139**; **Objekt-Serialisierung/Claims**: **AG3-141**;
  **einheitlicher Idempotenz-Vertrag**: **AG3-140**;
  **Frontend-Takeover-Sichten**: **AG3-153**.

## Betroffene Dateien

| Datei | Änderungsart | Zweck |
|---|---|---|
| `src/agentkit/backend/control_plane/runtime.py` | ändern | Record-Write atomar in `_finalize_start_phase` (:684-755, CAS :738); `_run_admission_evidence` (:1051-1092) auf Record-Evidenz umstellen (positive committed-op-Evidenz :1090 entfernen, Exit-Fence :1078 als Übergangsschutz belassen); Fence in start (:304)/complete (:887)/fail (:901)/closure (:1123)/resume (:1222); Ex-Owner-Rejection-Konstruktion |
| `src/agentkit/backend/control_plane/repository.py` | ändern | Port-Erweiterung: aktiven Record laden + Fence-Prüfung transaktional mit Finalize/Commit (Ownership-Repository-Ports aus AG3-137 konsumieren) |
| `src/agentkit/backend/control_plane/models.py` | ändern | Typisierte `ownership_transferred`-Fehler-Payload (Grund, neuer Owner, Transfer-Zeitpunkt) als Response-Detail |
| `src/agentkit/backend/control_plane/dispatch.py` | ändern | Executor-Pfad als gefencte Ausführung: `run_admitted`-Evidenz aus dem Record-Fence-Kontext (dispatch :246, Engine-Einstiege :416/:424) |
| `src/agentkit/backend/control_plane_http/app.py` | ändern | HTTP-Mapping 409/403 + `ownership_transferred`-Payload im Regel-8-Fehlervertrag (Phase-Mutation-Handler :1134-1200, Closure-Handler) |
| `src/agentkit/backend/state_backend/postgres_store.py` + `store/facade.py` (+ `_public_api_names.py`, `__init__.pyi`) | ändern | Transaktionale Row-Funktionen: Finalize+Record-Write atomar; Fence-Prüfung im selben Commit (kein TOCTOU) |
| `src/agentkit/harness_client/projectedge/runtime.py` | ändern | `block_reason`-Vokabular um `ownership_transferred` (resolve() :210-236) — deterministisch `binding_invalid`, kein Rückfall `ai_augmented` |
| `tests/unit/control_plane/**` | neu/ändern | Fence-/Admission-Entscheidungslogik über Ports/Fakes (präparierte Record-Zustände) |
| `tests/integration/**` | neu | Postgres: Setup-Start schreibt Record atomar; Ex-Owner-Mutationen an allen fünf Regime-Pfaden abgewiesen; Executor-Fence an der Phasengrenze dispatch→finalize; Reads bleiben erlaubt |
| `tests/contract/**` | neu/ändern | Contract-Pin der `ownership_transferred`-Fehlerform (409/403-Payload, Regel 8/18) |

## Akzeptanzkriterien

1. **Record-Write im Setup-Start:** Nach committetem Setup-Start existiert
   genau ein aktiver `run_ownership_records`-Eintrag (`ownership_epoch=1`,
   `acquired_via='setup'`, `owner_session_id` = startende Session), atomar
   mit dem Claim-CAS-Finalize geschrieben; der Verlierer eines parallelen
   Claim-CAS schreibt **keinen** Record (Concurrency-Integrationstest analog
   `_finalize_start_phase`-Atomicity).
2. **Fast-Start-Evidenz:** Ein Fast-Run (materialisiert keine Bindung) wird
   über seinen aktiven Record admittiert; die positive committed-op-Evidenz
   ist entfernt — eine committed Operation eines alten Runs derselben Story
   admittiert einen complete/fail/closure-Call nicht mehr (Negativtest;
   Code-Beweis: kein Admission-Aufruf von `has_committed_operation_for_run`).
3. **Historische Records sind nie Admission-Evidenz (SOLL-014):** Record mit
   `status != 'active'` (präpariert über die sanktionierte
   AG3-137-Single-Writer-Schreibfläche) → complete/fail/closure/resume
   deterministisch abgewiesen; **keine** Side-Effects (keine
   Binding-Re-Materialisierung, keine Locks, keine Events, keine stored op).
4. **Epoch-/Owner-Fence in allen fünf Regime-Pfaden (SOLL-015):** Mutation
   mit `session_id != owner_session_id` des aktiven Records oder mit
   veralteter Epoche wird an start/complete/fail/resume/closure einzeln
   getestet deterministisch abgewiesen — fail-closed, ohne State-Write.
5. **Executor gefenct (SOLL-016):** Ein Executor-Commit
   (dispatch→finalize), dessen Record sich zwischen Dispatch und Commit
   geändert hat, schreibt keinen State und wird deterministisch abgewiesen
   (Negativpfad an der Phasengrenze; Pipeline-State über den echten
   Dispatch-Pfad erzeugt, nicht manuell zusammengesetzt).
6. **Ex-Owner-Fehlerbild (SOLL-042, IMPL-019):** Die Ablehnung trägt
   `409`/`403` + strukturierte Payload mit mindestens Grund, neuem Owner,
   Transfer-Zeitpunkt, eingebettet in den Regel-8-Fehlervertrag;
   Contract-Test pinnt das Format.
7. **Reads bleiben erlaubt (SOLL-033-Anteil, Regel 17/18):**
   `GET /v1/project-edge/operations/{op_id}` und Read-Models liefern für
   die entmündigte Session weiterhin Ergebnisse (Positivtest).
8. **`binding_invalid`-Verhalten (SOLL-034-Anteil):** Edge-`resolve()`
   liefert bei revozierter Bindung mit Grund `ownership_transferred` den
   Modus `binding_invalid` mit `block_reason='ownership_transferred'` —
   kein stiller Rückfall auf `ai_augmented` (Unit-Test harness_client;
   fehlender/unbekannter Grund bleibt fail-closed `binding_invalid`).
9. **Widerspruchsregel (SOLL-019):** Divergenz präpariert (Bindung zeigt
   Session A, aktiver Record Owner B) → der Record entscheidet: Mutationen
   von A werden abgewiesen.
10. **Accountability (SOLL-017):** Committete Regime-Operationen/Events
    tragen den `ownership_epoch` ihres Commits; Artefakte/Attempts/QA
    bleiben `run_id`-kontinuierlich (bestehende Kontinuitäts-Tests grün).
11. **Exit-Übergangsschutz:** Nach Story-Exit (echter Exit-Pfad) gibt es
    weiterhin keine Re-Admission (Regressionstest auf die Exit-Fence :1078).
12. Coverage ≥ 85 % gehalten; `mypy` strict (+ `--platform linux`) und
    `ruff` ohne neue Ausnahmen; ARCH-55 (englische Bezeichner, Wire-Keys,
    Fehlercodes).

## Definition of Done

- Alle Akzeptanzkriterien erfüllt; Gate-Suite grün (`pytest -n0`
  unit/integration/contract, Coverage ≥ 85, `mypy src` + `--platform linux`,
  `ruff`, 4 Konzept-Gates).
- Codex-Review PASS.
- Auf `origin/main` gemerged; `status.yaml` → `completed` (Vorbedingung für
  AG3-144, AG3-145, AG3-148); README-Backlog-Snapshot (§6.7) nachgezogen.

## Abdeckung (Traceability)

**Deckt ab:** SOLL-014–019, SOLL-033 (Fehlerbild-Anteil), SOLL-034 (Verhaltens-Anteil), SOLL-042; IMPL-019, IMPL-021.

## Konzept-Referenzen

- FK-56 §56.8a (Fencing **aller** Regime-Mutationspfade inkl.
  complete/fail/Closure/Executor; historische Records audit-only;
  System-Principals als gefencte Executor; Accountability an
  `run_id + ownership_epoch`)
- FK-56 §56.7/§56.8 (Bindung als session-seitige Projektion; bei Widerspruch
  gilt der Ownership-Record), §56.7a (`binding_invalid` trägt
  maschinenlesbaren Grund als Attribut; Grund `ownership_transferred`;
  Reads inkl. `GET operations/{op_id}` bleiben erlaubt)
- FK-56 §56.13c (nur die Fence-/Fehlerbild-Wirkung auf den Ex-Owner: „Fence
  auf `owner_session_id`/`ownership_epoch` in allen Regime-Mutationspfaden,
  ausdrücklich auch `complete_phase`/`fail_phase`/Closure")
- FK-91 §91.1a Regel 15 (Prädikate „aktiver Ownership-Record,
  `ownership_epoch`/`binding_version`" — diese Story baut die
  Durchsetzungsfläche), Regel 17 (Transport-Timeouts fachlich bedeutungslos;
  Reconcile via op_id), Regel 18 (Ex-Owner-Fehlerbild 409/403 +
  `ownership_transferred`-Payload im Regel-8-Fehlervertrag)
- FK-17 §17.3.15/§17.3.16 (kanonische Entitäten), §17.4 (Bindung projiziert
  genau einen aktiven Record)
- `formal.operating-modes.invariants` →
  `historical_ownership_records_are_never_admission_evidence`,
  `story_execution_mutations_require_current_ownership_epoch`

## Guardrail-Referenzen

- **FIX THE MODEL, NOT THE SYMPTOM:** Die committed-op-Heuristik wird durch
  das typisierte Ownership-Modell **ersetzt**, nicht um weitere
  Sonderfall-Prüfungen ergänzt; die Binding-Re-Materialisierung für
  Nicht-Owner wird geschlossen statt kaschiert.
- **FAIL-CLOSED:** Kein aktiver Record ⇒ keine Regime-Mutation; unbekannter
  Revocation-Grund ⇒ `binding_invalid`; abgewiesene Mutationen hinterlassen
  keinerlei Side-Effects.
- **NO ERROR BYPASSING:** Es gibt keinen Fence-Bypass für System-Principals
  — `pipeline_deterministic`/`admin_service` mutieren nur als gefencte
  Executor.
- **SINGLE SOURCE OF TRUTH:** Der aktive Ownership-Record ist die eine
  Eigentums-Wahrheit; die Bindung bleibt Projektion (Widerspruchsregel).
- **Testing-Guardrails:** Negativpfade an den Phasengrenzen
  (start/complete/fail/closure/resume, dispatch→finalize) sind Pflicht;
  Pipeline-State wird über echte Vorgängerpfade erzeugt.

## Querschnitts-Auflagen

- **K5 Postgres-only:** Alle Fence-/Record-Queries laufen gegen die
  Postgres-Control-Plane (fail-closed via
  `_require_postgres_control_plane_backend`, `control_plane/runtime.py:2119`);
  kein SQLite-Spiegel. Integrationstests über die Postgres-Fixture,
  Unit-Tests über Ports/Fakes. Diese Story fügt kein neues Schema hinzu
  (Schema-Owner: AG3-137).
- **Blutgruppen-Klassifikation**
  (`concept/methodology/software-blutgruppen.md`): Fence-/Admission-
  Entscheidungslogik und Widerspruchsregel = **A** (reine Domänenregeln);
  HTTP-Fehler-Mapping + Payload-Mapper = **R**; transaktionale
  Fence-/Record-Row-Funktionen im `state_backend` = **AT/T** (dort
  lokalisiert). Der A-Kern bleibt AT-frei.
- **Bundle-Assets:** Keine betroffen (verifiziert:
  `bundles/target_project/tools/agentkit/projectedge.py` delegiert an den
  `harness_client` und behandelt Ablehnungen generisch über den
  Regel-8-Fehlervertrag; Takeover-/Abort-Kommandos für Agents kommen erst
  mit AG3-154).
