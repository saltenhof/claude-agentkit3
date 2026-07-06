# Review d8a7da41 - P1/P2/P3 Follow-ups

Rolle: adversarial QA reviewer. Diff-Basis: `git diff b4d557df..d8a7da41`.

Uncommitted `stories/*.md`-Loeschungen im Arbeitsbaum wurden ignoriert.

## 1. P1 Deadlock/Verschachtelung

Status: **PASS**

Keine echte size-1-Pool-Selbstverschachtelung gefunden.

Evidenz:

- `src/agentkit/backend/state_backend/postgres_store.py:277` setzt `_DEFAULT_STATE_POOL_MAX_SIZE = 1`; `src/agentkit/backend/state_backend/postgres_store.py:323` nutzt `max_size=_resolve_state_pool_max_size()`.
- `src/agentkit/backend/state_backend/postgres_store.py:396` bis `429` ist der neue `borrow_repository_connection()`-Helper; er leiht genau `with pool.connection() as conn`, yielded die Verbindung und committed danach.
- Store -> Repo-Umschluss geprueft:
  - Kommando: `rg "^from agentkit\.backend\.state_backend\.store|^import agentkit\.backend\.state_backend\.store|facade\." src\agentkit\backend\state_backend\postgres_store.py -n`
  - Ausgabe: `NO_MATCHES`
- Externe `_connect_global()`-Nutzung geprueft:
  - Kommando: `rg "with _connect_global\(" src\agentkit\backend -g "*.py" -n | rg -v "postgres_store.py"`
  - Ausgabe: `NO_MATCHES`
- Frische Repo-`psycopg.connect()`-Aufrufe in `state_backend/store` geprueft:
  - Kommando: `rg "psycopg\.connect\(" src\agentkit\backend\state_backend\store -g "*.py" -n`
  - Ausgabe: `NO_MATCHES`
- Kritische Repo-Pfade gelesen:
  - `src/agentkit/backend/state_backend/store/guard_counter_repository.py:232` faengt nach einem fehlgeschlagenen `_postgres_connect()`-Block erst ausserhalb des Blocks den Replay-Pfad ab; `_read_idempotency_key()` leiht erst danach erneut.
  - `src/agentkit/backend/state_backend/store/custom_field_repository.py:189`, `203`, `213`, `266` leihen nur sequenziell; `write_agentkit_value()` ruft `get_definition()`, `get_value()` und `save_value()` nacheinander, ohne gehaltene Verbindung.
  - `src/agentkit/backend/state_backend/store/projection_repositories.py:1577` ruft `GuardCounterService(...).flush_on_story_reset(...)` ohne umgebenden `_postgres_connect()`-Block.

## 2. P1 Semantik-Erhalt

Status: **PASS**

Die Connection-Akquisition wurde zentralisiert; Bootstrap, Row-Shape, Commit/Rollback und Session-Reset bleiben erhalten.

Evidenz:

- Pool-Default fuer dict rows: `src/agentkit/backend/state_backend/postgres_store.py:324` `kwargs={"row_factory": dict_row}`.
- Pool-Reset gegen Session-State-Leak: `src/agentkit/backend/state_backend/postgres_store.py:303` bis `316` ruft `conn.rollback()`, `RESET ALL`, `conn.commit()`.
- Store-Bootstrap bleibt mit Zwischen-Commits: `src/agentkit/backend/state_backend/postgres_store.py:378` bis `385` ruft `_ensure_versioned_schema`, `conn.commit()`, `_ensure_schema_once`, `conn.commit()`, `yield`, `conn.commit()`.
- Repo-Bootstrap bleibt pro Repo:
  - `src/agentkit/backend/state_backend/store/custom_field_repository.py:80` bis `82`: `borrow_repository_connection()`, `ensure_versioned_schema(conn)`, `yield conn`.
  - `src/agentkit/backend/state_backend/store/guard_counter_repository.py:95` bis `99`: `borrow_repository_connection()`, `ensure_versioned_schema(conn)`, `_ensure_schema_once(...)`, `conn.commit()`, `yield conn`.
  - `src/agentkit/backend/state_backend/store/governance_hook_repository.py:189` bis `196`: `borrow_repository_connection()`, `ensure_versioned_schema(conn)`, `_ensure_postgres_schema(conn)`, `CREATE TABLE`.
- 17 direkt geaenderte Repo-Dateien bestaetigt:
  - Kommando: `git diff --name-only b4d557df..d8a7da41 -- src/agentkit/backend/state_backend/store/*.py | Measure-Object`
  - Ausgabe: `Count = 17`
- Diff-Beispiel fuer Semantik-Verschiebung:
  - `src/agentkit/backend/state_backend/store/custom_field_repository.py`: `psycopg.connect(..., row_factory=dict_row)` + `commit/rollback/close` entfernt, ersetzt durch `postgres_store.borrow_repository_connection()`; `ensure_versioned_schema(conn)` bleibt.
  - `src/agentkit/backend/state_backend/store/guard_counter_repository.py`: gleicher Austausch; `_ensure_schema_once(...)` und Zwischen-`conn.commit()` bleiben.

## 3. CAS/Fencing Unberuehrt

Status: **PASS**

`postgres_store.py` aendert im Diff nur den neuen Helper; keine CAS-/Fencing-Zeile wurde veraendert.

Evidenz:

- Kommando: `git diff --unified=0 b4d557df..d8a7da41 -- src/agentkit/backend/state_backend/postgres_store.py`
- Relevante Ausgabe: nur Addition ab `@@ -394,0 +395,37 @@` fuer `borrow_repository_connection()`.
- Kommando: `git diff b4d557df..d8a7da41 -- src/agentkit/backend/state_backend/postgres_store.py | rg "^[+-].*(operation_epoch|object_mutation_claim|run_ownership|takeover|finalize|claimed_by|owner_token)"`
- Ausgabe: `NO_MATCHES`

## 4. P2 schema_versions-TRUNCATE-Ausnahme

Status: **PASS**

Keine Test-Kreuzkontamination gefunden: `schema_versions` ist ein Migrationscursor, keine per-test Nutzdaten-Tabelle. Struktur-Drift-Canaries bleiben aktiv.

Evidenz:

- `tests/fixtures/postgres_backend.py:74` definiert `_MIGRATION_MARKER_TABLES = {"schema_versions"}`.
- `tests/fixtures/postgres_backend.py:373` bis `377` filtert `_truncate_schema()` diese Marker aus der TRUNCATE-Liste.
- Drift-Canary bleibt mehrstufig:
  - `src/agentkit/backend/state_backend/postgres_store.py:493` `_schema_is_bootstrapped(...)`.
  - `src/agentkit/backend/state_backend/postgres_store.py:542` prueft `_analytics_versions_are_recorded(...)`.
  - `src/agentkit/backend/state_backend/postgres_store.py:544` prueft `_fact_tables_are_fk62_shaped(...)`.
  - `src/agentkit/backend/state_backend/postgres_store.py:629` bis `649` verlangt `schema_versions` mit `3.4`, `3.5`, `3.6`.
- Fokussierter Canary-Lauf:
  - Kommando: `.venv\Scripts\python.exe -m pytest tests\contract\state_backend\test_analytics_schema.py -q`
  - Ausgabe: `23 passed in 12.48s`

## 5. P3 Skip-Guard

Status: **PASS**

Der Guard skippt bei nicht erreichbarem PG schnell und laeuft bei erreichbarem PG in den echten Fixture-Pfad.

Evidenz:

- `tests/fixtures/postgres_backend.py:396` `shared_postgres_reachable(connect_timeout: float = 2.0)`.
- `tests/fixtures/postgres_backend.py:431` bis `440` nutzt dieselbe DSN-Auswahl und `psycopg.connect(url, connect_timeout=connect_timeout)` plus `SELECT 1`.
- `tests/unit/state_backend/store/test_runtime_execution_purge.py:121` bis `124` skippt nur bei `not shared_postgres_reachable()` und ruft sonst `postgres_isolated_schema`.
- Direkte Probe:
  - Kommando: `.venv\Scripts\python.exe -c "... closed port ... pg.shared_postgres_reachable() ..."`
  - Ausgabe: `reachable_closed_port_default=False elapsed=2.041s`
  - Kommando: `.venv\Scripts\python.exe -c "... current shared PG ... pg.shared_postgres_reachable() ..."`
  - Ausgabe: `reachable_current_default=True elapsed=0.038s`
- Fokussierter Testlauf:
  - Kommando: `.venv\Scripts\python.exe -m pytest tests\unit\state_backend\store\test_runtime_execution_purge.py -q`
  - Ausgabe: `52 passed in 48.21s`

## 6. Gates

Status: **PASS**

Lokale Gates:

- `.venv\Scripts\python.exe -m pytest tests\unit tests\contract -q --cov=agentkit --cov-report=term-missing`
  - Ausgabe: `7708 passed, 12 skipped, 9 warnings in 329.59s`
  - Coverage: `TOTAL 46803 5375 89%`; `Required test coverage of 85.0% reached. Total coverage: 88.52%`
- `.venv\Scripts\python.exe -m pytest tests\integration\control_plane -q`
  - Ausgabe: `11 passed in 8.82s`
- `.venv\Scripts\python.exe -m ruff check src tests`
  - Ausgabe: `All checks passed!`
- `.venv\Scripts\python.exe -m mypy src`
  - Ausgabe: `Success: no issues found in 745 source files`
- `.venv\Scripts\python.exe -m mypy src --platform linux`
  - Ausgabe: `Success: no issues found in 745 source files`
- `.venv\Scripts\python.exe scripts\ci\check_concept_frontmatter.py`
  - Ausgabe: `[concept-frontmatter] OK: 88 docs, all lints passed. Bounded-context layer: active.`
- `.venv\Scripts\python.exe scripts\ci\compile_formal_specs.py`
  - Ausgabe: `[formal-spec] OK: 186 documents, 1620 ids, 1982 references, 135 scenarios, 440 prose links`
- `.venv\Scripts\python.exe scripts\ci\check_concept_code_contracts.py`
  - Ausgabe: `[concept-code-contracts] OK: no truth-boundary contract violations`
- `.venv\Scripts\python.exe scripts\ci\check_architecture_conformance.py`
  - Ausgabe: `[architecture-conformance] OK: no architecture contract violations`
- `git diff --check b4d557df..d8a7da41`
  - Ausgabe: keine Ausgabe, Exit 0.

Remote-Gates:

- Erster offizieller Scriptlauf ohne geladene Secrets:
  - Ausgabe: `Sonar credentials missing. Load T:\seu\agentkit3-secrets.cmd or set environment variables.`
- Nach Laden von `T:\seu\agentkit3-secrets.cmd` und Warten auf Jenkins Build `956`:
  - Jenkins BuildData: `SHA1 = d8a7da418d8d8f1262ff67455765ed0fca8693c5`, Branch `refs/remotes/origin/main`, Result `SUCCESS`.
- Finaler offizieller Remote-Gate-Lauf:
  - Kommando: `.\scripts\ci\check_remote_gates.ps1`
  - Ausgabe:
    - `sonar_quality_gate: OK`
    - `sonar_violations: 0`
    - `sonar_critical_violations: 0`
    - `sonar_security_hotspots: 0`
    - `jenkins_color: blue`
    - `jenkins_last_build.number: 956`
    - `jenkins_last_build.result: SUCCESS`
    - `jenkins_last_completed_build.number: 956`
    - `jenkins_last_completed_build.result: SUCCESS`

## Gesamtbefund

Keine blockierenden oder aufschiebbaren Defekte gefunden.

VERDICT: APPROVE
