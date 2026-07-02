# Codex Review R1 — AG3-137 (`b2b3d0bd` vs `695775c1`)

Pruefbasis: `git diff 695775c1..b2b3d0bd`, Story `stories/AG3-137-run-ownership-schema-foundation/story.md`, Rubric `git show 695775c1:stories/_worker-review-rubric.md`. Concept-MCP war nicht als `mcp__agentkit3-concepts__concept_*` Tool exponiert; ich habe die read-only Funktionen aus `tools.concept_mcp.server` ueber `.venv\Scripts\python` verwendet. `concept_status` meldete 1267 Chunks / 274 Glossar-Terme remote und lokal.

Targeted tests run: `.venv\Scripts\python -m pytest tests/unit/control_plane/test_ownership_records.py tests/contract/control_plane/test_ownership_record_formats.py -q` -> `28 passed`.

## 1. AK1 partial-unique active ownership — PASS

Die DB-Invariante ist echt als Partial-Unique-Index angelegt: `src/agentkit/backend/state_backend/postgres_schema.sql:300`-`302` erzeugt `run_ownership_records_active_uidx ON (project_key, story_id) WHERE status = 'active'`. Der Store-Writer nutzt einen plain `INSERT`, kein Upsert: `src/agentkit/backend/state_backend/postgres_store.py:2303`-`2339`; der Kommentar sagt explizit, dass Duplicate identity oder zweiter Active-Record als Constraint-Verletzung durchfallen.

Der Integrationstest prueft genau den zweiten aktiven Insert mit `psycopg.errors.UniqueViolation`: `tests/integration/state_backend/test_run_ownership_schema_postgres.py:146`-`160`. Konzepttreue: FK-56 §56.8a fordert DB-erzwungen hoechstens einen aktiven Ownership-Record pro `(project_key, story_id)`; FK-17 §17.3.15 sagt dasselbe fuer die Persistenzschicht.

## 2. Takeover same-row CAS / `transferred` no writer — PASS with scope note

`run_ownership_records` hat `PRIMARY KEY (project_key, story_id, run_id)` (`postgres_schema.sql:281`-`298`), also genau eine Zeile pro Run. In diesem Commit existiert kein produktiver Takeover-Vollzug; die spaetere CAS-Operation ist laut Story AG3-148/AG3-142. Fuer den Schema-Foundation-Scope ist wichtig, dass kein zweiter Insert als Takeover-Pfad existiert.

`transferred` ist im Enum-Vokabular vorhanden (`ownership.py:56`-`68`), aber der Fassade-Writer weist es ab: `store/facade.py:801`-`825`. Der Contract-Test prueft das: `tests/contract/control_plane/test_ownership_record_formats.py:155`-`170`. Konzept: FK-56 §56.13c beschreibt Takeover als Umschreiben desselben Ownership-Records mit `ownership_epoch + 1`; kein Statuswechsel auf `transferred`.

## 3. Claim / transfer field exactness, no TTL, no snapshot — PASS

`object_mutation_claims` enthaelt exakt `project_key`, `serialization_scope`, `scope_key`, `op_id`, `backend_instance_id`, `instance_incarnation`, `acquired_at`, `queue_position`; kein TTL/Expiry (`postgres_schema.sql:309`-`319`). `takeover_transfer_records` ist pro Repo keyed durch `(project_key, story_id, run_id, ownership_epoch, repo_id)` und enthaelt die formalen Attribute (`postgres_schema.sql:327`-`339`).

Die Mapper geben dieselben Felder aus (`store/mappers.py:1312`-`1324`, `1355`-`1374`). Tests pinnen Feldmengen und negative Feldsuche: `tests/contract/control_plane/test_ownership_record_formats.py:108`-`142`; `tests/unit/control_plane/test_ownership_records.py:162`-`220`. Konzept: `formal.state-storage.entities` v5 nennt dieselben Identity Keys und Attribute; `formal.state-storage.invariants` fordert instance-bound Claims ohne Wall-Clock-/TTL-/Heartbeat-Expiry.

## 4. `binding_version` monotone integer / CAS capability — ERROR

FK-17 §17.3a.16 ist eindeutig: `binding_version` ist `Integer`, Pflicht, `>= 1`, und wechselt bei jeder Neubindung. Der Commit laesst die Boundary aber weiterhin beliebige Strings durch:

- `SessionRunBindingRecord.binding_version` bleibt `str` ohne `__post_init__`-Validierung (`src/agentkit/backend/control_plane/records.py:58`-`88`).
- Der Mapper persistiert und liest es unveraendert als String (`src/agentkit/backend/state_backend/store/mappers.py:1048`-`1088`).
- Das frische Schema hat nur `binding_version TEXT NOT NULL`, ohne Check auf Integer-Form oder `>= 1` (`src/agentkit/backend/state_backend/postgres_schema.sql:184`-`190`).
- Reale Produktions-/Testpfade halten alte Tokens weiter fuer gueltig: `story_exit/service.py:521`-`538` erzeugt bei fehlender Bindung `exit-<id>`; bestehende Contract-/Unit-Tests schreiben `bind-NEW`, `bind-001`, `bind-1` weiter (`tests/contract/state_backend/test_control_plane_operation_store_postgres.py:1015`, `tests/unit/story_exit/test_story_exit_service.py:155`).

Ich habe den Boundary-Bypass lokal reproduziert, ohne DB: `SessionRunBindingRecord(..., binding_version='bind-not-int', status='bogus')` konstruiert erfolgreich und druckt `bind-not-int bogus`. Damit sind AK4, Rubric-Kategorie 3 (Durchsetzung an der Grenze), Kategorie 4 (Blast Radius) und Kategorie 7 (Negativtests am echten Gate) verletzt.

Die Designentscheidung "#1: str mit monotone-integer values" ist nur defensibel, wenn die Value-Domain an Record/Mapper/DB-Grenze hart validiert wird. Das passiert nicht. "#2: wall-clock microseconds" ist ebenfalls nicht tragfaehig: `_next_binding_version()` leitet den Wert aus `datetime.now(...).timestamp() * 1_000_000` ab und schuetzt nur pro Prozess mit `_LAST_BINDING_VERSION` (`runtime.py:2430`-`2454`). Das ist kein DB-monotones, multi-instance-sicheres CAS-Versioning und fuehrt eine versteckte Clock-Abhaengigkeit in das Ownership-/Takeover-Challenge-Material ein. FK-56 §56.13a verlangt CAS auf `ownership_epoch`/`binding_version`; ein prozesslokaler Clock-Token ist dafuer kein belastbares Fundament.

## 5. Additive legacy columns lossless — WARNING

`control_plane_operations` ist additiv und nullable erweitert (`postgres_schema.sql:255`-`266`; `postgres_store.py:534`-`552`). Der Legacy-Test fuer Operation rows belegt lossless Bootstrap (`tests/integration/state_backend/test_run_ownership_schema_postgres.py:313`-`354`).

Bei `session_run_bindings` gibt es aber zwei Luecken:

- Existing-schema ALTER fuegt `status` ohne CHECK-Constraint hinzu (`postgres_store.py:526`-`531`), waehrend fresh schema den Check hat (`postgres_schema.sql:195`-`196`). Bestehende Produktions-DBs bekommen damit eine weichere Grenze als neue DBs.
- Der atomare Start-/Mutationspfad nutzt `_insert_session_binding_row`, aber dieser Insert/Upsert schreibt nur die alten Spalten und ignoriert `status`/`revocation_reason` (`postgres_store.py:2880`-`2921`), obwohl der Mapper diese Felder bereitstellt (`store/mappers.py:1048`-`1064`). Diese Helper sind produktiv erreichbar in `finalize_control_plane_start_phase_global_row` und `atomic_finalize_control_plane_operation_global_row` (`postgres_store.py:3103`-`3106`, `3227`-`3229`).

Fuer aktuelle Inserts rettet der DB-Default `active`; fuer Updates einer bestehenden same-run Binding bleiben Status/Reason aber stale. Das ist noch kein eigenstaendiger Reject neben ERROR #4, muss aber vor Folge-Stories geklaert werden.

## 6. Backfill / canary / IMPL-007 — WARNING

Der Backfill ist idempotent und fail-closed modelliert: Legacy nonnumeric `binding_version` wird auf `'1'` gehoben (`postgres_store.py:711`-`721`), ambiguous active bindings werden verweigert (`725`-`736`), orphan active locks ohne derivable owner werden verweigert (`738`-`758`), und Insert nutzt `NOT EXISTS` + `ON CONFLICT DO NOTHING` (`760`-`774`). Tests decken happy path, idempotence, orphan und ambiguity ab (`tests/integration/state_backend/test_run_ownership_schema_postgres.py:362`-`425`).

Designentscheidung "#4: `_schema_is_bootstrapped` canary extension" ist fuer eine echte pre-AG3-137 Produktion plausibel: eine DB ohne `run_ownership_records` erzwingt Full Bootstrap (`postgres_store.py:308`-`323`). Die Canary ist aber minimal: Wenn `run_ownership_records` existiert, aber andere AG3-137 Tabellen/Columns/Constraints fehlen (partial failed rollout oder manuelle Reparatur), kann `_schema_is_bootstrapped` weiter true liefern und `_ensure_schema` samt Backfill auslassen. Angesichts ZERO DEBT sollte die Canary alle neuen Tabellen plus additive Columns oder eine explizite schema-version marker condition pruefen.

## 7. K5 Postgres-only / SQLite fail-closed — PASS

`sqlite_store.py` ist im Commit nicht geaendert und enthaelt keine neuen Ownership-Tabellen. Neue Entry Points gehen ueber die Store-Fassade und rufen `_require_control_plane_backend()`, die bei nicht-Postgres `ConfigError` wirft (`store/facade.py:152`-`176`, `801`-`825`, `860`ff., `903`ff.). Der Contract-Test prueft alle neuen Entry Points auf SQLite (`tests/contract/control_plane/test_ownership_record_formats.py:190`-`247`).

## 8. Single-writer / facade / conformance — PASS with unverified gate

Produktive neue Repositories defaulten auf die sanktionierte `state_backend.store` Fassade (`tests/unit/control_plane/test_ownership_records.py:259`-`278`; `control_plane/repository.py` nutzt die globalen Facade-Funktionen). Keine neue SQLite-Spiegelung oder fremder DB-Schreibpfad gefunden. Der interne Driver-Helper `_insert_session_binding_row` bleibt jedoch ein bestehender Store-intern Pfad; siehe WARNING #5 fuer die unvollstaendige Spaltenmigration.

Ich habe die Architektur-Conformance-Suite nicht voll ausgefuehrt; ich habe nur den Entry Point `scripts/ci/check_architecture_conformance.py` lokalisiert. Der Worker-Claim "0 violations" ist deshalb nicht von mir bestaetigt.

## 9. AK8 negative paths — ERROR

RunOwnership-, Claim-, Transfer- und BackendInstance-Records haben sinnvolle Negativtests (`tests/unit/control_plane/test_ownership_records.py:117`-`230`), und `transferred` wird am Writer rejected (`tests/contract/control_plane/test_ownership_record_formats.py:155`-`170`).

Die neue `SessionRunBindingRecord`-Achse ist aber ungedeckt und unvalidiert. AK8 nennt invalid status als Negativpfad; `SessionRunBindingRecord.status` ist plain `str` mit Default (`records.py:85`-`88`), kein Enum und keine Validation. Der Test deckt nur den Default-Happy-Path ab (`tests/unit/control_plane/test_ownership_records.py:238`-`251`). Damit kann `status='bogus'`, `revocation_reason` auf active, oder `binding_version='bind-not-int'` bis zum Store-Mapping durchlaufen. Auf bestehenden Postgres-Schemas fehlt zusaetzlich der CHECK aus WARNING #5. Das ist eine Boundary-Enforcement-Luecke, nicht nur ein fehlender Test.

## 10. Cross-cutting rubric / gates / blast radius — ERROR

Rubric-Kategorie 1/3/4/7 fallen wegen `binding_version` und Binding-Status:

- Fail-closed completeness: Binding-Version und Binding-Status werden nicht am Record/Mapper/DB-Boundary erzwungen.
- Single Source / Concept fidelity: Code-Kommentare behaupten "monotone positive-integer", die Typen/Schema/Tests erlauben weiter arbitrary string tokens.
- Blast Radius: `story_exit` und alte binding tests wurden nicht auf die neue Version-Domain migriert.
- Negative tests: kein Test beweist, dass invalid Binding-Status oder non-integer Binding-Version rejected wird.

Gates: Ich habe nur die zwei targeted non-Postgres Tests ausgefuehrt (`28 passed`). Jenkins/Sonar/Full pytest/mypy/ruff/remote gates wurden von mir nicht ausgefuehrt und sind nicht als gruen bestaetigt.

## Worker Design Decisions

Kein Worker-Handover mit einer nummerierten Liste von 6 Designentscheidungen ist Teil des Commit-Ranges; im Commit selbst existieren nur `story.md` und `status.yaml` unter der Story. Ich bewerte daher die sechs aus Prompt, Commit-Message und Code-Kommentaren inferierbaren Entscheidungen:

1. `binding_version` als `str` mit Integer-Werten: **ERROR**. Ohne harte Value-Domain-Validation ist das ein Scope-Dodge gegen FK-17 §17.3a.16.
2. `binding_version` aus Wall-Clock-Mikrosekunden: **ERROR**. Prozesslokal monotone ist nicht DB-/multi-instance-monotone und ist als CAS-Fundament fuer FK-56 §56.13a zu schwach.
3. `binding_version` numeric-column migration auf AG3-142 verschieben: **ERROR** im aktuellen Umfang, weil AG3-137 AK4 selbst `monotone Integer-Version >= 1` fordert. Eine reine Repraesentationsaenderung darf nicht die Boundary offenlassen.
4. `_schema_is_bootstrapped` nur um `run_ownership_records` erweitern: **WARNING**. Fuer echte pre-AG3 DBs ausreichend, fuer partiell migrierte DBs nicht voll fail-closed.
5. Legacy nonnumeric Binding-Versionen auf `'1'` backfillen: **INFO/PASS** als einmalige Startversion fuer pre-contract Rows, solange danach die Integer-Domain erzwungen wird. Genau diese Folge-Erzwingung fehlt aber.
6. Transfer-Record-Attribute optional/upsert, produktiver Writer spaeter: **INFO/PASS** fuer AG3-137 Schema-Foundation, weil AG3-148 den Challenge/Confirm-Writer besitzt; die Identity inkl. `repo_id` ist vorhanden.

## Out-of-scope observations

Die bestehenden AG3-054 Control-Plane-Operation-Lease-Pfade enthalten weiterhin Wall-Clock-Lease-/Expiry-Semantik (`runtime.py` und `postgres_store.py` Treffer zu `lease`, `expired`, `claimed_at`). AG3-137 nimmt TTL-Rueckbau explizit aus dem Scope und weist ihn AG3-139 zu; ich lasse das nicht in das AG3-137 Verdict einfliessen.

VERDICT: REJECT
