# Codex Review R2 — AG3-137 (`695775c1..5c1176c3`)

Pruefbasis: Full story delta `git diff 695775c1..5c1176c3`, mit besonderem Fokus auf Remediation `git diff b2b3d0bd..5c1176c3`. Uncommitted `stories/*.md`-Reorganisation wurde ignoriert.

Concept check: `mcp__agentkit3-concepts__concept_*` war nicht als Tool exponiert; ich habe wie in r1 die read-only Funktionen aus `tools.concept_mcp.server` ueber `.venv\Scripts\python` genutzt. `concept_status` meldete 1267 Chunks / 274 Glossar-Terme. FK-17 §17.3a.16 bleibt normativ `binding_version` Integer `>= 1`; FK-56 §56.8a fordert Partial-Unique active ownership; FK-56 §56.13a fordert CAS-Challenge-Material mit `ownership_epoch` / `binding_version`.

Checks ausgefuehrt:

- Direct boundary probe: `SessionRunBindingRecord(..., binding_version='bind-not-int')` -> `ValueError`.
- `.venv\Scripts\python -m pytest tests/unit/control_plane/test_ownership_records.py tests/unit/control_plane/test_runtime.py::test_next_binding_version_is_db_monotone_not_wall_clock tests/unit/control_plane/test_runtime.py::test_start_then_complete_increments_binding_version_db_monotone tests/unit/control_plane_http/test_version_handshake.py::test_governance_bare_mutations_require_handshake_classifier tests/unit/control_plane_http/test_version_handshake.py::test_route_classifier_governance_is_method_aware -q` -> `45 passed`.
- `.venv\Scripts\python -m pytest tests/unit/cli/test_operator_recovery_cli.py::TestRunPhaseNegativePaths::test_invalid_base_url_fails_closed_structured -q` -> `1 passed`.
- `.venv\Scripts\python -m pytest tests/integration/state_backend/test_run_ownership_schema_postgres.py -q` -> `19 passed`.

## Re-verification of r1 findings

### §4 / §10 binding_version monotone integer / blast radius — STILL-BROKEN (ERROR)

Fixed at the record boundary: `SessionRunBindingRecord.__post_init__` rejects non-canonical values via `is_canonical_binding_version` (`src/agentkit/backend/control_plane/records.py:109`-`117`), and my direct constructor probe with `binding_version='bind-not-int'` now raises `ValueError`. The new negative tests hit the real constructor boundary (`tests/unit/control_plane/test_ownership_records.py:266`-`296`).

Fixed for fresh schema: the fresh Postgres DDL has `session_run_bindings_binding_version_check CHECK (binding_version ~ '^[1-9][0-9]*$')` (`src/agentkit/backend/state_backend/postgres_schema.sql:192`-`194`), and raw DB negative tests cover `bind-not-int`, `0`, and `01` (`tests/integration/state_backend/test_run_ownership_schema_postgres.py:466`-`491`).

Fixed in the mint function itself: `_next_binding_version(previous_version)` now returns `previous + 1` or `1`, with no wall-clock or process-local counter (`src/agentkit/backend/control_plane/runtime.py:2459`-`2493`). The old `_LAST_BINDING_VERSION` / clock mint is gone; targeted grep found no `_LAST_BINDING_VERSION`, `_BINDING_VERSION_LOCK`, or `_next_binding_version()` clock mint under `src/agentkit/backend/control_plane`.

Still broken on the real remediation upgrade path: `_ensure_session_binding_constraints()` is only called from `_ensure_schema()` (`src/agentkit/backend/state_backend/postgres_store.py:712`-`725`), but `_ensure_schema_once()` skips `_ensure_schema()` whenever `_schema_is_bootstrapped()` returns true (`src/agentkit/backend/state_backend/postgres_store.py:288`-`298`). The canary checks tables and additive columns, but not the new binding CHECK constraints (`src/agentkit/backend/state_backend/postgres_store.py:308`-`357`). A DB already migrated by r1/b2b3d0bd has the four AG3-137 tables and additive columns (`git show b2b3d0bd:...postgres_schema.sql`: `binding_version TEXT NOT NULL` at line 189, AG3 tables at lines 281/309/327/345, `operation_epoch` at line 262) but no `session_run_bindings_binding_version_check` or `session_run_bindings_status_check`. On that exact existing-schema state, the remediation process declares the schema bootstrapped and never adds the constraints or normalizes legacy `bind-*` rows.

The `story_execution_locks.binding_version = exit-{id}` token was correctly left on the lock/projection axis only (`src/agentkit/backend/story_exit/service.py:521`-`545`), and `sqlite_store.py` is not in either AG3-137 diff range. Grep found no `SessionRunBindingRecord(... binding_version="bind-*")` writers/tests after remediation.

### §9 binding status/revocation_reason — FIXED at record boundary

`status` is now checked against the `BindingStatus` value set (`src/agentkit/backend/control_plane/records.py:118`-`123`). `revocation_reason` is cross-checked: active bindings reject any reason, revoked bindings require a non-empty reason (`src/agentkit/backend/control_plane/records.py:124`-`134`). Reproducing negative tests hit `SessionRunBindingRecord` construction directly (`tests/unit/control_plane/test_ownership_records.py:299`-`329`).

DB status enforcement is present for fresh schemas and in the helper-level existing-schema constraint function (`src/agentkit/backend/state_backend/postgres_schema.sql:200`-`202`; `src/agentkit/backend/state_backend/postgres_store.py:850`-`876`), but the real upgrade skip described above also means r1-shaped existing DBs do not reliably receive that DB CHECK.

### §5a existing-schema CHECK parity — STILL-BROKEN (ERROR)

The remediation added `_ensure_session_binding_constraints()` and the helper adds both named constraints (`src/agentkit/backend/state_backend/postgres_store.py:830`-`879`). However, it is not wired into the already-bootstrapped path. `_ensure_schema_once()` returns before `_ensure_schema()` when `_schema_is_bootstrapped()` is true (`src/agentkit/backend/state_backend/postgres_store.py:294`-`296`), and `_schema_is_bootstrapped()` does not inspect `pg_constraint` for the two new constraints (`src/agentkit/backend/state_backend/postgres_store.py:308`-`357`). Therefore existing DBs at the r1 AG3-137 shape can remain softer than fresh DBs.

The integration test `test_existing_schema_backfill_normalizes_then_reapplies_checks` proves the helper sequence only when called manually (`tests/integration/state_backend/test_run_ownership_schema_postgres.py:537`-`579`); it does not prove that `_connect_global()` / `_ensure_schema_once()` reaches the helper for a b2b3d0bd-shaped production schema.

### §5b `_insert_session_binding_row` status/reason persistence — FIXED

The atomic insert/upsert now includes `status, revocation_reason` and updates them on same-run conflict (`src/agentkit/backend/state_backend/postgres_store.py:3006`-`3020`, parameters at `3032`-`3035`). The reproducing integration test round-trips a revoked binding through `_insert_session_binding_row` (`tests/integration/state_backend/test_run_ownership_schema_postgres.py:505`-`534`).

### §6 `_schema_is_bootstrapped` AG3-137 canary — FIXED narrowly, incomplete for remediation constraints

The r1-specific request was to check all AG3-137 tables plus additive columns. That is now implemented: all four AG3-137 tables are in `required_tables` (`src/agentkit/backend/state_backend/postgres_store.py:310`-`330`), and `_AG3_137_ADDITIVE_COLUMNS` covers `session_run_bindings.status`, `session_run_bindings.revocation_reason`, and the five additive `control_plane_operations` columns (`src/agentkit/backend/state_backend/postgres_store.py:360`-`373`). Tests cover a missing AG3 table and a missing additive column (`tests/integration/state_backend/test_run_ownership_schema_postgres.py:586`-`621`).

But the canary still omits the new remediation constraints; that omission is the root cause of the surviving ERROR above.

## New remediation targets

### 1. Migration ordering trap — ERROR

Within `_ensure_schema()` itself, the order is correct: `_ensure_run_ownership_backfill()` runs before `_ensure_session_binding_constraints()` (`src/agentkit/backend/state_backend/postgres_store.py:724`-`725`), and the backfill normalizes every non-canonical `binding_version` to `'1'` before constraint addition (`src/agentkit/backend/state_backend/postgres_store.py:763`-`774`). If this function runs, `ALTER TABLE ... ADD CONSTRAINT` will not trip on legacy `bind-*` values.

The real upgrade trap is one level higher: for a database already shaped by b2b3d0bd, `_schema_is_bootstrapped()` returns true because it checks only tables/additive columns, not the new constraints (`src/agentkit/backend/state_backend/postgres_store.py:308`-`357`). `_ensure_schema_once()` then returns without running `_ensure_schema()` (`src/agentkit/backend/state_backend/postgres_store.py:294`-`297`). That means the normalization and `ADD CONSTRAINT` never execute on the most important existing-schema case: the r1 deployment state this remediation is supposed to fix. The current integration test manually calls the helpers and misses this bootstrap short-circuit (`tests/integration/state_backend/test_run_ownership_schema_postgres.py:559`-`562`).

### 2. DB-monotone mint correctness — PASS

`_next_binding_version(previous_version)` is deterministic, input-derived, and has no wall-clock/process-global state (`src/agentkit/backend/control_plane/runtime.py:2459`-`2493`). The callers read the current persisted binding before planning start/phase mutation materialization (`src/agentkit/backend/control_plane/runtime.py:771`-`796`, `1994`-`2008`). The write still reuses the existing atomic operation/binding paths; no new AG3-142 fence was introduced. Unit coverage proves same-input determinism and start-then-complete `1 -> 2` behavior (`tests/unit/control_plane/test_runtime.py:506`-`552`).

### 3. `binding_version` stays `str` with value-domain enforcement — ERROR

Normal record/store paths now enforce the value domain: the Python predicate is `is_canonical_binding_version` (`src/agentkit/backend/control_plane/ownership.py:126`-`142`), the record boundary calls it (`src/agentkit/backend/control_plane/records.py:109`-`117`), and mappers reconstruct `SessionRunBindingRecord` on read (`src/agentkit/backend/state_backend/store/mappers.py:1067`-`1089`).

The DB value domain is not reliably enforced on existing r1-shaped schemas because the constraint helper can be skipped by `_schema_is_bootstrapped()` as described in target 1. In that state, a raw/non-record writer can still persist non-canonical `binding_version` values because the DB has `binding_version TEXT NOT NULL` without the remediation CHECK.

Secondary drift risk: `BINDING_VERSION_SQL_CHECK = "^[1-9][0-9]*$"` exists (`src/agentkit/backend/control_plane/ownership.py:136`-`139`), but the fresh schema and ALTER helper embed their own string literals (`src/agentkit/backend/state_backend/postgres_schema.sql:192`-`194`; `src/agentkit/backend/state_backend/postgres_store.py:874`-`876`). They currently match, but the SQL regex is not actually single-sourced from the exported constant.

### 4. Sonar Part B regressions — PASS

`control_plane_http/app.py`: handler inventory is preserved. The five governance mediation handlers moved into `_GovernanceMediationHandlers` (`src/agentkit/backend/control_plane_http/app.py:365`-`553`), and `ControlPlaneApplication` subclasses it (`src/agentkit/backend/control_plane_http/app.py:555`). Dispatch still calls the same `_handle_get_telemetry_events`, `_handle_get_worker_health`, `_handle_post_telemetry`, `_handle_post_guard_counter`, and `_handle_post_worker_health` methods (`src/agentkit/backend/control_plane_http/app.py:770`-`970`). `__init__` still initializes service collaborators before route tables; dashboard resolution still uses the already-initialized `_story_service` (`src/agentkit/backend/control_plane_http/app.py:563`-`631`). I found no lost route/handler or newly unset attribute.

`version_handshake.py`: `^/governance/(?:.*)?$` and `^/governance/.*$` are equivalent for this route family: both require `/governance/` plus any tail, both match `/governance/` and `/governance/guard-counters`, and both reject bare `/governance`. The method-aware governance tests still pass (`tests/unit/control_plane_http/test_version_handshake.py:160`-`166`, `525`-`535`).

`cli/main.py`: the reordered exceptions now map `json.JSONDecodeError` to `TransportError` before bare `ValueError`, exactly matching the docstring's "malformed / non-contract response is a transport error"; plain `ValueError` still maps to `InvalidBaseUrl` (`src/agentkit/backend/cli/main.py:2038`-`2053`). I verified both mappings with a direct import probe; the existing invalid-base-url unit test also passes (`tests/unit/cli/test_operator_recovery_cli.py:344`-`364`).

`cli/main.py` S1192 constants and `web_call_budget_guard.py` S1110 are behavior-preserving: the CLI help constants hold the same strings (`src/agentkit/backend/cli/main.py:35`-`41`), and the web-call unavailable detail concatenates to the same message text (`src/agentkit/backend/governance/guard_system/web_call_budget_guard.py:205`-`206`).

## Out-of-scope defects

`SessionRunBindingView` / `StoryExecutionLockView` fixtures still use `binding_version="bind-001"` in view-level tests (`tests/unit/control_plane/test_http.py:67`-`85`; `tests/integration/governance_hooks/test_hook_rest_mediation.py:78`-`96`). These are not `SessionRunBindingRecord` writers and do not persist into `session_run_bindings`; I did not count them against AG3-137. A later wire/view cleanup may still want to align them with the canonical decimal domain to reduce test vocabulary drift.

VERDICT: REJECT
