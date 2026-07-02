# Codex Review R3 — AG3-137 (`5c1176c3..a0faa581`)

Pruefbasis: Remediation delta `git diff 5c1176c3..a0faa581` (3 Dateien) mit Rueckgriff auf r2-Review `stories/AG3-137-run-ownership-schema-foundation/review-codex-r2.md`. Uncommitted `stories/*.md`-Reorganisation wurde ignoriert.

Concept check: `tools.concept_mcp.server` read-only genutzt. `concept_status()` meldet 1267 Chunks / 274 Glossar-Terme. FK-17 §17.3a.16 bleibt normativ `binding_version` Integer `>= 1`; FK-56 §56.8a fordert DB-erzwungen hoechstens einen aktiven Ownership-Record pro `(project_key, story_id)`; FK-56 §56.13a fordert CAS-Challenge-Material mit `ownership_epoch` / `binding_version`.

## Re-verification

### r2 surviving ERROR: `_schema_is_bootstrapped()` skipped missing binding CHECK constraints — FIXED

`_ensure_schema_once()` still short-circuits only after `_schema_is_bootstrapped()` says true (`src/agentkit/backend/state_backend/postgres_store.py:290`-`307`). The canary now explicitly calls `_ag3_137_binding_constraints_present()` before the analytics/fact-table checks (`src/agentkit/backend/state_backend/postgres_store.py:362`-`368`).

The new constraint canary names BOTH remediation constraints (`session_run_bindings_status_check`, `session_run_bindings_binding_version_check`) at `src/agentkit/backend/state_backend/postgres_store.py:422`-`425`, reads `pg_constraint`, joins through `pg_class`/`pg_namespace`, and scopes to `n.nspname = current_schema()` (`src/agentkit/backend/state_backend/postgres_store.py:438`-`450`). Therefore a b2b3d0bd-shaped DB with all AG3-137 tables/additive columns but missing either named CHECK returns `False` and cannot be cached as bootstrapped.

The real-path integration test now models exactly that r1 shape by dropping both named CHECKs and inserting legacy `binding_version="bind-001"` while the process cache still prevents accidental re-bootstrap (`tests/integration/state_backend/test_run_ownership_schema_postgres.py:647`-`684`). It then proves `_schema_is_bootstrapped()` returns `False` on that shape (`tests/integration/state_backend/test_run_ownership_schema_postgres.py:686`-`692`), clears the bootstrap cache, and drives `_connect_global()` / `_ensure_schema_once()` rather than manual helpers (`tests/integration/state_backend/test_run_ownership_schema_postgres.py:694`-`699`). Postconditions cover both constraints restored, legacy row normalized to `"1"`, raw `bind-again` rejected with `CheckViolation`, and a second real connect idempotent (`tests/integration/state_backend/test_run_ownership_schema_postgres.py:701`-`728`).

### r2 target-3 SSOT drift: SQL regex duplicated in `postgres_store.py` — FIXED

`postgres_store.py` imports only the scalar constant `BINDING_VERSION_SQL_CHECK` from `control_plane.ownership` (`src/agentkit/backend/state_backend/postgres_store.py:30`-`33`). The backfill normalization now uses that constant in the SQL regex (`src/agentkit/backend/state_backend/postgres_store.py:821`-`831`), and the existing-schema ALTER helper uses the same constant for `session_run_bindings_binding_version_check` (`src/agentkit/backend/state_backend/postgres_store.py:911`-`938`). `rg` found no remaining embedded `^[1-9][0-9]*$` literal in `postgres_store.py`; the only static DDL literal remains in `postgres_schema.sql` (`src/agentkit/backend/state_backend/postgres_schema.sql:192`-`194`).

The static fresh-schema literal is pinned to the constant by `test_postgres_schema_binding_version_check_is_single_sourced()` (`tests/contract/control_plane/test_ownership_record_formats.py:157`-`181`). Direct import probe confirmed `postgres_store.BINDING_VERSION_SQL_CHECK` and `ownership.BINDING_VERSION_SQL_CHECK` are the same scalar string; architecture conformance reports zero violations.

## Regression hunt

### 2. Ordering still safe — PASS

The real bootstrap order remains normalize/backfill before constraint addition: `_ensure_schema()` calls `_ensure_run_ownership_backfill(conn)` before `_ensure_session_binding_constraints(conn)` (`src/agentkit/backend/state_backend/postgres_store.py:766`-`780`). The normalization updates non-canonical legacy `binding_version` values to `"1"` before the ALTER helper can run (`src/agentkit/backend/state_backend/postgres_store.py:814`-`831`), so `ALTER TABLE ... ADD CONSTRAINT` cannot trip on `bind-*` rows on the real path.

### 3b. New import regression — PASS

The production import is a single scalar constant, not a record/type dependency (`src/agentkit/backend/state_backend/postgres_store.py:30`-`33`). The module docstring documents this as the only sanctioned cross-import and explicitly excludes BC records/conversions (`src/agentkit/backend/state_backend/postgres_store.py:3`-`14`). Runtime import probe succeeded without circular import, and `scripts/ci/check_architecture_conformance.py` returned `OK: no architecture contract violations`.

### 4. Stricter canary / collateral behavior — PASS

The stricter canary only forces heavy bootstrap when one of the two required named CHECKs is absent (`src/agentkit/backend/state_backend/postgres_store.py:362`-`365`, `src/agentkit/backend/state_backend/postgres_store.py:438`-`450`). Healthy fresh schemas already contain both named CHECKs in `postgres_schema.sql` (`src/agentkit/backend/state_backend/postgres_schema.sql:192`-`202`), and fully migrated existing schemas get the same names through the idempotent ALTER helper (`src/agentkit/backend/state_backend/postgres_store.py:915`-`938`). Once present, `_ensure_schema_once()` caches the schema name and short-circuits as before (`src/agentkit/backend/state_backend/postgres_store.py:297`-`307`). The new integration test also proves a second real connect is idempotent after remediation (`tests/integration/state_backend/test_run_ownership_schema_postgres.py:723`-`728`).

## Gates / spot checks

- `.venv\Scripts\python -m pytest tests/contract/control_plane/test_ownership_record_formats.py -q` -> `7 passed`.
- `.venv\Scripts\python -m pytest tests/unit/control_plane/test_ownership_records.py tests/unit/control_plane/test_runtime.py::test_next_binding_version_is_db_monotone_not_wall_clock tests/unit/control_plane/test_runtime.py::test_start_then_complete_increments_binding_version_db_monotone -q` -> `43 passed`.
- `.venv\Scripts\python -m ruff check src/agentkit/backend/state_backend/postgres_store.py tests/integration/state_backend/test_run_ownership_schema_postgres.py tests/contract/control_plane/test_ownership_record_formats.py` -> passed.
- `.venv\Scripts\python scripts/ci/check_architecture_conformance.py` -> `OK: no architecture contract violations`.
- `.venv\Scripts\python scripts/ci/check_concept_frontmatter.py` -> passed.
- `.venv\Scripts\python scripts/ci/compile_formal_specs.py` -> passed.
- `git diff 5c1176c3..a0faa581 --check` -> passed.
- Postgres integration test file was not executed in this pass because it requires a live Postgres backend; the new test was reviewed against the real `_connect_global()` path.
- Remote Jenkins/Sonar gate script could not complete in this shell. Without secret loader it failed on missing credentials; with `T:\seu\agentkit3-secrets.cmd` loaded it failed before HTTP calls because Windows PowerShell could not load `Microsoft.PowerShell.Security` (`ConvertTo-SecureString` unavailable / duplicate type-data module-load error). No remote green claim is made.

## Out-of-scope defects

None found in this remediation delta.

VERDICT: APPROVE
