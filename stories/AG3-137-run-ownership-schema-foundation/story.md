# AG3-137 — Ownership-Schema-Fundament: `run_ownership_records`, `object_mutation_claims`, `takeover_transfer_records`, Instanz-Spalten + Backfill (additiv, Postgres-only)

- **Typ:** implementation
- **Größe:** L
- **depends_on:** [] — startbar: baut ausschließlich additiv auf der gelandeten
  Schema-Bootstrap-/Store-Mechanik von `main` auf; keine Vorgänger-Story nötig
  (GAP §4: ST-01 ist die Wurzel des Bauplans).
- **Quell-Konzept:** FK-17 §17.2/§17.3.15/§17.3.16/§17.3a.15/§17.3a.16/§17.4/§17.5/§17.7a;
  FK-56 §56.7/§56.7a/§56.8/§56.8a; FK-53 §53.7.3a;
  `formal.operating-modes.entities` (`run-ownership-record`, `session-run-binding`);
  `formal.operating-modes.invariants` (`at_most_one_active_ownership_per_story`);
  `formal.state-storage.entities` (`object-mutation-claim`, `inflight-operation-record`,
  `takeover-transfer-record`); FK-91 §91.1a Regeln 13/16 (Spaltenbasis)
- **Herkunft:** GAP-Analyse Session-Ownership v4 (`_temp/gap-analyse-session-ownership.md`),
  Story-Kandidat GAP-ST-01; normative Basis Commits 3ae011e4 / 1bb4ed8a / 58c190b7
  (+ Decision-Records unter `concept/_meta/decisions/`).

## Kontext / Problem

Der Kern des Session-Ownership-Modells ist **Neubau**: In `src/agentkit/` gibt es
null Treffer für `ownership_epoch`, `RunOwnershipRecord`, `owner_session_id`,
`backend_instance_id`, `operation_epoch` (Grep-verifiziert 2026-07-02; Treffer nur
in `concept/` und `stories/`). Konkrete, am Code verifizierte Lücken:

- `session_run_bindings` hat PK **nur `session_id`**, kein `status`, keine
  Revocation, keine Aktiv-Invariante
  (`src/agentkit/backend/state_backend/postgres_schema.sql:177-186`;
  Record `src/agentkit/backend/control_plane/records.py:35-47`).
- `binding_version` ist ein Zufallswert `bind-{uuid4.hex}`
  (`src/agentkit/backend/control_plane/runtime.py:2422`), **nicht monoton** und
  damit nicht CAS-fähig — verletzt den Attributvertrag FK-17 §17.3a.16
  (`binding_version >= 1`, wechselt bei jeder Neubindung).
- `control_plane_operations` trägt nur `claimed_by`/`claimed_at`
  (`postgres_schema.sql:231-245`); die Spalten des formalen
  `inflight-operation-record` (`operation_epoch`, `backend_instance_id`,
  `instance_incarnation`, `declared_serialization_scope`, `finalized_at`) fehlen
  vollständig.
- Es gibt keine Tabellen für `run-ownership-record`, `object-mutation-claim`,
  `takeover-transfer-record`.
- Es gibt **kein Daten-Backfill-Werkzeug** für laufende Runs: das einzige
  Reconcile-Muster ist datenverwerfend
  (`_reconcile_fact_tables_fk62`, `state_backend/postgres_store.py:703`);
  der `MigrationRunner` ist analytics-only (`postgres_store.py:782`,
  `replay_ddl=False`).

**Tragfähige Präzedenz existiert:** idempotenter Schema-Bootstrap je Connect
unter Advisory-Lock (`state_backend/schema_bootstrap.py:97`,
`postgres_store.py:625-630`) plus additive `_schema_alter_statements()` mit
`ADD COLUMN IF NOT EXISTS` (`postgres_store.py:383` ff.). Die Control-Plane ist
bereits fail-closed auf Postgres festgelegt
(`_require_postgres_control_plane_backend`,
`control_plane/runtime.py:2119`, Check :2139) — die neuen Tabellen folgen dieser
Festlegung (K5).

Ohne dieses Fundament kann keine der Folge-Stories (Fencing AG3-142,
Startup-Rekonsiliierung AG3-138, Objekt-Serialisierung AG3-141,
Idempotenz-Konsolidierung AG3-140, Digest AG3-143, Edge-Command-Queue AG3-145)
gebaut werden.

## Scope

### In Scope

1. **Tabelle `run_ownership_records`** (Postgres-only): Identität
   `(project_key, story_id, run_id)`; Attribute `owner_session_id`,
   `ownership_epoch` (Integer, `>= 1`, monoton steigend, beginnend mit Setup),
   `status` (`active|transferred|ended|reset|split|closed`), `acquired_via`
   (`setup|takeover|recovery`), `acquired_at`, `audit_ref` (Pflicht).
   **DB-erzwungene Partial-Unique-Invariante**: höchstens ein `status='active'`
   pro `(project_key, story_id)` (`at_most_one_active_ownership_per_story`,
   FK-56 §56.8a, FK-17 §17.3.15). Der Takeover-Vollzug ist ein **In-Place-CAS
   auf derselben Zeile** (`owner_session_id`-Wechsel, `ownership_epoch+1`,
   `acquired_via='takeover'`; Record bleibt `status='active'`) — DB-erzwungen
   genau eine Zeile pro Run, nie ein zweiter Insert (FK-56 §56.8a); das
   Statusvokabular-Element `transferred` wird durch den Run-fortführenden
   Takeover NICHT gesetzt. `transferred` bleibt Teil des kanonischen
   FK-17-§17.2-Vokabulars, hat aber in diesem Strang **keinen Writer**:
   Kein Pfad (Takeover/Disown/Recovery) setzt ihn; seine Verwendung ist
   bis zu einer normativen Konkretisierung gesperrt (Enum-Wert vorhanden,
   Setzen fail-closed abgewiesen — kein stiller Missbrauch als
   Takeover-Status). [SOLL-001, 002, 005, 006, 007, 013]
2. **Tabelle `object_mutation_claims`**: Identität
   `(project_key, serialization_scope, scope_key)`; Attribute `op_id`,
   `backend_instance_id`, `instance_incarnation`, `acquired_at`,
   `queue_position` — exakt nach `state-storage.entity.object-mutation-claim`.
   **Kein** TTL-/Expiry-Feld. [SOLL-051]
3. **Tabelle `takeover_transfer_records`**: Identität
   `(project_key, story_id, run_id, ownership_epoch, repo_id)` — **eine Zeile
   je teilnehmendem Repo** (state-storage entities v5); je teilnehmendem Repo
   `repo_id`, `takeover_base_sha`, `last_push_at`, `push_lag_hint`,
   `base_quality`, `challenge_ref`, `confirm_ref` — exakt nach
   `state-storage.entity.takeover-transfer-record`. **SOLL-147: der
   Transfer-Record ERSETZT den früheren `takeover-worktree-snapshot`** — es wird
   keinerlei Snapshot-Infrastruktur (binary-diff, Index-Status,
   Untracked-Manifest) gebaut.
4. **Erweiterung `control_plane_operations` → `inflight-operation-record`**:
   additive Spalten `operation_epoch`, `backend_instance_id`,
   `instance_incarnation`, `declared_serialization_scope`, `finalized_at`
   (Identität `op_id` bleibt PK; `status`/`claimed_at` bestehen). Nur Schema +
   Record + Repository — Befüllung/Semantik kommt in AG3-138/AG3-141. [SOLL-052]
5. **Erweiterung `session_run_bindings`**: `status` (aktiv/revoked) +
   maschinenlesbarer Revocation-Grund (Vokabular inklusive
   `ownership_transferred` — **Schema-Anteil von SOLL-034**; der
   `binding_invalid`-Grund ist Attribut, kein Status pro Ursache, FK-56 §56.7a)
   sowie Umstellung `binding_version` auf **monotone Integer-Version `>= 1`**
   (CAS-fähig; SOLL-008). Reine Repräsentationsänderung: die Schreib-Anlässe
   der Bindung bleiben unverändert, es wird keine Admission-/Fencing-Semantik
   geändert. [SOLL-003, 008]
6. **Typisierte Enums/Records/Repositories** in `control_plane`:
   `SessionId`-Typ (SOLL-004), `OwnershipStatus`- und
   `OwnershipAcquisition`-Enums (SOLL-005/006), `RunOwnershipRecord`,
   Transfer-/Claim-Records, erweiterter `SessionRunBindingRecord`;
   Repository-Ports + Postgres-Implementierung über die sanktionierte
   `state_backend.store`-Fassade. Beziehungsregeln nach FK-17 §17.4 (Story hat
   viele Records, max. ein aktiver; Bindung projiziert genau einen aktiven
   Record; SOLL-009). Beide Entitäten sind eigene kleine Aggregate-Roots
   (SOLL-010); Single-Writer ist `control_plane_runtime` im Auftrag des BC
   story-lifecycle (SOLL-011); Persistenzmodell-Tags
   `canonical_runtime_ledger` / `canonical_runtime_snapshot` (SOLL-012).
   Status-Wert `reset` im Enum + Record-Semantik „Audit-Fakt, nie
   Admission-Evidenz" als Datenmodell-Zusicherung (**Schema-Anteil von
   SOLL-083**; Verhalten in AG3-149/Reset-Pfad).
7. **Persistenz der Backend-Instanz-Identität** (**IMPL-004,
   Persistenz-Anteil**): persistente Ablage für `backend_instance_id` +
   monoton zählbare Boot-Inkarnation (Tabellenform ist Design dieser Story,
   additiv, Postgres-only), sodass AG3-138 beim Boot nur noch
   erzeugen/inkrementieren muss.
8. **Backfill laufender Runs** (**IMPL-007**): idempotenter,
   deterministischer Bootstrap-Schritt, der für jeden laufenden Run mit
   aktiver Bindung einen `run_ownership_records`-Eintrag mit
   `ownership_epoch=1`, `status='active'`, `acquired_via='setup'` erzeugt
   (Owner aus der bestehenden Bindung abgeleitet) und Bestands-Bindungen auf
   das neue `status`/`binding_version`-Format hebt. Kein datenverwerfender
   Pfad.

### Out of Scope (mit Owner)

- **Fencing/Verhalten der Regime-Pfade** — `ownership_epoch`-Fence in
  start/complete/fail/closure/Executor, Ablösung `_run_admission_evidence`,
  Record-Schreiben im Setup, Ex-Owner-Fehlerbild: **AG3-142**. Diese Story
  ändert das Laufzeitverhalten der Pipeline-Pfade NICHT.
- **Erzeugung der Instanz-Identität, Boot-Inkarnation, Pre-Serve-Hook,
  Startup-Rekonsiliierung, `admin_abort`**: **AG3-138**.
- **TTL-Rückbau** (`_CLAIM_LEASE_TTL`-Familie bleibt hier unangetastet):
  **AG3-139**.
- **Einheitlicher Idempotenz-Vertrag** (Client-op_id-Pflicht, Konsolidierung
  `idempotency_keys`): **AG3-140**.
- **Per-Story-Claim-Erwerbslogik + Warte-Semantik** (Objekt-Serialisierung
  zur Laufzeit): **AG3-141**.
- **Transfer-Endpoints/Challenge/Approval/atomarer Vollzug** (befüllt
  `takeover_transfer_records` produktiv): **AG3-148**.
- **Disown-Verhalten (Reset/Exit/Split)**: **AG3-149**.

## Betroffene Dateien

| Datei | Änderungsart | Zweck |
|---|---|---|
| `src/agentkit/backend/state_backend/postgres_schema.sql` | ändern | Neue Tabellen `run_ownership_records`, `object_mutation_claims`, `takeover_transfer_records`, Instanz-Identitäts-Ablage; additive Spalten auf `control_plane_operations` (:231-245) und `session_run_bindings` (:177-186); Partial-Unique-Index |
| `src/agentkit/backend/state_backend/postgres_store.py` | ändern | Additive ALTERs in `_schema_alter_statements()` (:383 ff.); neue Row-Level-Funktionen (Insert/Load/Status-Übergänge); Backfill-Schritt im Bootstrap (Präzedenz: idempotenter Bootstrap :625-630) |
| `src/agentkit/backend/state_backend/store/facade.py`, `store/_public_api_names.py`, `store/__init__.pyi`, `store/mappers.py` | ändern | Veröffentlichte Loader/Saver + Mapper der neuen Records über die sanktionierte Fassade |
| `src/agentkit/backend/control_plane/records.py` | ändern | `RunOwnershipRecord`, Claim-/Transfer-Records, `SessionRunBindingRecord` um `status`/Revocation-Grund/monotone Version erweitern (:35-47) |
| `src/agentkit/backend/control_plane/repository.py` | ändern | Neue Repository-Ports (ownership, claims, transfer, instance identity) |
| `src/agentkit/backend/control_plane/ownership.py` (o. ä., PROJECT_STRUCTURE: Control-Plane Runtime/Records) | neu | `SessionId`-Typ, `OwnershipStatus`/`OwnershipAcquisition`-Enums, Invarianten-Konstanten |
| `src/agentkit/backend/control_plane/runtime.py` | ändern (minimal) | `bind-{uuid4}`-Minting (:2422) auf monotone Version umstellen — gleiche Schreib-Anlässe, keine Semantik-Änderung |
| `src/agentkit/backend/state_backend/sqlite_store.py` | **nicht** ändern | K5: kein SQLite-Spiegel der neuen Tabellen; fail-closed Festlegung bleibt (`runtime.py:2119`) |
| `tests/unit/control_plane/**`, `tests/integration/**`, `tests/contract/**` | neu/ändern | Repository-Unit-Tests (Ports/Fakes), Schema-/Constraint-/Backfill-Integrationstests (Postgres-Fixture), Contract-Pins der neuen Record-Formate |

## Akzeptanzkriterien

1. `run_ownership_records` existiert mit DB-erzwungener
   Partial-Unique-Invariante: der Versuch, einen zweiten `status='active'`-Record
   für dieselbe `(project_key, story_id)` einzufügen, schlägt im
   Postgres-Integrationstest deterministisch mit Constraint-Verletzung fehl —
   kein stilles Überschreiben, kein Anwendungs-Workaround (SOLL-013,
   fail-closed).
2. `object_mutation_claims` und `takeover_transfer_records` entsprechen
   feldgenau den formalen Entitäten (`state-storage.entity.object-mutation-claim`,
   `.takeover-transfer-record`); Identitäts-Duplikate werden vom
   Schema abgewiesen. Es existiert **kein** Snapshot-Artefakt und **kein**
   TTL-/Expiry-Feld an Claims (Review-Grep als Beleg; SOLL-147, SOLL-051).
3. `control_plane_operations` trägt die additiven Spalten `operation_epoch`,
   `backend_instance_id`, `instance_incarnation`,
   `declared_serialization_scope`, `finalized_at`; eine mit Altdaten befüllte
   Datenbank übersteht den Bootstrap verlustfrei (Integrationstest mit
   vorbefüllten Bestandszeilen; SOLL-052).
4. `session_run_bindings` trägt `status` + maschinenlesbaren Revocation-Grund
   (Vokabular enthält `ownership_transferred`); `binding_version` ist monotone
   Integer-Version `>= 1`. Bestehende Regime-Pfade verhalten sich unverändert:
   die bestehende Test-Suite (insb. Admission/Resolve/Binding-Tests) bleibt
   ohne Semantik-Anpassung grün (SOLL-003/008/034-Schema; „rein additiv" belegt).
5. Enums/Records/Repositories sind typisiert (Pydantic v2 bzw. frozen
   dataclasses analog Bestand), englisch (ARCH-55), mit Single-Writer
   `control_plane_runtime`; kein zweiter Schreibpfad an der
   `state_backend.store`-Fassade vorbei (Konformanz-Suite bleibt 0 Violations).
6. **Backfill bewiesen:** Integrationstest mit vorbefüllter Datenbank
   (laufender Run + aktive Bindung, ohne Ownership-Record) — nach Bootstrap
   existiert genau ein `active`-Record mit `ownership_epoch=1`,
   `acquired_via='setup'`; erneuter Bootstrap erzeugt keine Duplikate
   (Idempotenz); ein Run ohne ableitbaren Owner wird nicht geraten, sondern
   deterministisch als Befund gemeldet (fail-closed, IMPL-007).
7. **Postgres-only fail-closed:** Zugriff auf die neuen Repositories über ein
   Nicht-Postgres-Backend scheitert als expliziter `ConfigError` (Muster
   `_require_postgres_control_plane_backend`); es existiert keine
   SQLite-Implementierung der neuen Tabellen (expliziter Negativtest, K5).
8. Negativpfade an Phasengrenzen: ungültiger `status`-/`acquired_via`-Wert,
   `ownership_epoch < 1`, fehlender `audit_ref` und Claim ohne
   Instanz-Identität werden bei Record-Validierung bzw. Schema abgewiesen
   (testing-guardrails: Negativpfad-Pflicht).
9. Coverage ≥ 85 % gehalten; `mypy` strict (inkl. `--platform linux`) und
   `ruff` ohne neue Ausnahmen.

## Definition of Done

- Alle Akzeptanzkriterien erfüllt; Gate-Suite grün (`pytest -n0`
  unit/integration/contract, Coverage ≥ 85, `mypy src` + `--platform linux`,
  `ruff`, 4 Konzept-Gates).
- Codex-Review PASS.
- Auf `origin/main` gemerged; `status.yaml` → `completed`;
  README-Backlog-Snapshot (§6.7) nachgezogen.

## Abdeckung (Traceability)

**Deckt ab:** SOLL-001–013, SOLL-034 (Schema-Anteil), SOLL-051, SOLL-052, SOLL-083 (Schema-Anteil), SOLL-147; IMPL-004 (Persistenz-Anteil), IMPL-007.

## Konzept-Referenzen

- FK-17 §17.2 (`SessionId`, `OwnershipStatus`, `OwnershipAcquisition`),
  §17.3.15/§17.3.16 (kanonische Entitäten), §17.3a.15/§17.3a.16
  (Attributverträge inkl. `ownership_epoch >= 1`, `binding_version >= 1`),
  §17.4 (Beziehungsregeln), §17.5 (Aggregate-Roots, Single-Writer
  `control_plane_runtime`, Persistenzmodell-Tags), §17.7a (Reset-Purge-Domäne;
  Record wird nie gelöscht)
- FK-56 §56.7/§56.8 (Bindung als session-seitige Projektion; bei Widerspruch
  gilt der Ownership-Record), §56.7a (`binding_invalid`-Grund als Attribut,
  `ownership_transferred`), §56.8a (Run-Ownership-Record, Partial-Unique,
  Epochen-Semantik)
- FK-53 §53.7.3a (Reset: `status = reset` als Audit-Fakt — Schema-Anteil)
- `formal.operating-modes.entities` → `operating-modes.entity.run-ownership-record`,
  `.session-run-binding`; `formal.operating-modes.invariants` →
  `at_most_one_active_ownership_per_story`
- `formal.state-storage.entities` → `state-storage.entity.object-mutation-claim`,
  `.inflight-operation-record`, `.takeover-transfer-record`;
  `formal.state-storage.invariants` →
  `object_mutation_claims_are_instance_bound_and_never_expire_by_wall_clock`
  (Schema-Konsequenz: kein Expiry-Feld)
- FK-91 §91.1a Regel 13 (`declared_serialization_scope`-Spaltenbasis),
  Regel 16 (Instanzbindung als Spaltenbasis)
- FK-02 §2.6 (Invariantenzeile „Eine Story-Umsetzung gehört höchstens einer
  Session"; DB-erzwungene Aktiv-Invariante)

## Guardrail-Referenzen

- **SINGLE SOURCE OF TRUTH:** Der Ownership-Record ist die eine kanonische
  Eigentums-Wahrheit; die Bindung ist Projektion. Keine Schattenfelder neben
  dem definierten State-Modell.
- **FAIL-CLOSED:** Aktiv-Invariante DB-erzwungen (nicht nur
  Anwendungs-Konvention); Postgres-only-Zugriff scheitert explizit; Backfill
  rät nie.
- **FIX THE MODEL, NOT THE SYMPTOM:** Eigentum wird als typisiertes
  Datenmodell verankert — nicht als weitere committed-op-Heuristik neben
  `_run_admission_evidence` (deren Ablösung AG3-142 gehört).
- **ZERO DEBT:** Der Backfill laufender Runs gehört zum Scope — kein
  „Migration später"-Rest.
- **State-/Artefakt-Disziplin (CLAUDE.md):** State-Formate nur mit
  mitgezogenen Contract-/Golden-Tests ändern; keine ungetypten Zustandsdateien.

## Querschnitts-Auflagen

- **K5 Postgres-only:** Alle neuen Tabellen sind Postgres-only, fail-closed
  über das `_require_postgres_control_plane_backend`-Muster
  (`control_plane/runtime.py:2119`). Kein SQLite-Spiegel. Teststrategie:
  Contract-/Integrationstests über die Postgres-Fixture, Unit-Tests über
  Ports/Fakes.
- **Blutgruppen-Klassifikation** (`concept/methodology/software-blutgruppen.md`):
  Enums/Records/Invarianten-Typen (`ownership.py`, `records.py`-Erweiterung) = **A**
  (technologiefreies Domänenmodell); Mapper Wire/Row ↔ Record = **R**;
  Repository-Implementierung inkl. Transaktions-/Constraint-Mechanik in
  `state_backend` = **AT** (konstitutive Mediation, dort lokalisiert);
  SQL-DDL/Row-Funktionen = **T**. Der A-Kern bleibt AT-frei.
- **Bundle-Assets:** Keine betroffen (verifiziert: reine Backend-Persistenz;
  `bundles/target_project/tools/agentkit/projectedge.py` konsumiert keine der
  neuen Tabellen und ändert sich nicht).
