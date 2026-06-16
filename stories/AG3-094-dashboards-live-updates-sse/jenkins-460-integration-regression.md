# AG3-094 — Jenkins #459/#460 post-merge regression: E9 fail-closed over-reach

Codex APPROVED AG3-094 r3. Then Jenkins caught a real regression the local gates missed
(my verification was too narrow — ran only tests/unit subsets, not full tests/unit + integration).

## Root cause
The E9 "fix the model" change made the SQLite global store resolve via fail-closed
`resolve_sqlite_store_root(AGENTKIT_STORE_DIR)` (ConfigError when unset), NOT `Path.cwd()`.
The worker applied this to the SHARED `_project_store_dir(None)` / `_global_store_dir()`
resolver, which is used not only by the NEW execution-event global store (AG3-094's actual
addition for the SSE E2E) but also by PRE-EXISTING global reads:
- `load_story_context_global_row` / `load_story_context_rows_global` (sqlite_store.py:1651/1670)
- the phase-state load behind `read_model_routes.py:414`
- the analytics productive-refresh path

These pre-existing reads previously resolved via the implicit Path.cwd() default and worked.
With fail-closed they raise ConfigError → broke:

### Jenkins #459 (tests/unit) — fixed surgically (commit 52ba65e)
- tests/unit/control_plane_http/test_app.py::test_project_scoped_story_collection_get_resolves
- tests/unit/control_plane_http/test_app.py::test_project_scoped_story_detail_get_unknown_returns_404

### Jenkins #460 (tests/integration) — STILL failing
- tests/integration/project_management/test_ag3_091_read_model_endpoints.py::
  test_story_flow_done_story_all_phases_done / _existing_story_returns_snapshot /
  _all_phases_pending_when_no_phase_state  (phase-state load → 503, read_model_routes.py:414)
- tests/integration/kpi_analytics/aggregation/test_productive_wiring.py::
  test_productive_refresh_analytics_no_longer_returns_skipped / _reaches_worker_not_skipped
  (ConfigError directly)

## Decision: NARROW the fail-closed (Option B)
The broad fail-closed is OUT OF AG3-094's scope (a frontend dashboards story must not change
the resolution semantics of unrelated pre-existing backend global reads). Restore the
pre-existing global reads to their pre-AG3-094 behavior; keep the explicit-root fail-closed
ONLY for the NEW execution-event global store (which AG3-094 added and which has no legacy
callers). This still satisfies Codex's actual E9 finding (no CWD hidden state for the new SSE
event store) and the AG3-094 SSE E2E (harness sets AGENTKIT_STORE_DIR for the event store).

The broad "no implicit Path.cwd() global state ANYWHERE" hardening is a legitimate but SEPARATE
backend story (own scope, full unit+integration+postgres verification) — not a side effect here.

## Verification lesson
state_backend is broadly-effective core; local verification MUST run the full tests/unit AND
tests/integration (+ contract), not just the changed modules (CLAUDE.md "breit wirksame
Pipeline-Logik … nicht nur ein schmaler Ausschnitt"). Postgres/integration tests need Docker
(not available locally) → Jenkins is the validator; minimize blast radius accordingly.
