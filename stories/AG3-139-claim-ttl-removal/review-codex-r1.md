# AG3-139 - Codex adversarial QA review R1

Review scope: `git diff 7dd7259c..5f1c6ca9` on branch `main`.
Uncommitted `stories/*.md` moves were ignored as requested.

MCP note: I attempted to discover the requested `agentkit3-concepts` tools via
`tool_search` for `concept_search` / `concept_get` /
`concept_glossary_search`; no callable tools were exposed in this session. I
therefore used the local `concept/` files as fallback.

## Concept baseline

- `concept/technical-design/91_api_event_katalog.md:282-289`: in-flight
  claims end only by own-instance startup reconciliation or
  `admin_abort_inflight_operation`, never by wall clock, TTL, or lease expiry.
- `concept/technical-design/10_runtime_deployment_speicher.md:898-904`:
  object-mutation claims and in-flight operation claims are instance-bound, not
  wall-clock-bound: no lease, no TTL, no PID heuristic.
- `concept/technical-design/10_runtime_deployment_speicher.md:931-939`:
  stale display is information only; inactivity is not a diagnosis and there is
  no automatic stale release.
- `concept/technical-design/02_domaenenmodell_zustaende_artefakte.md:489`:
  ownership ends never automatically.
- `concept/formal-spec/operating-modes/invariants.md:69-71`:
  ownership transfer requires explicit confirmed request / official end path /
  recovery and never timeout, lease expiry, heartbeat loss, or other inference
  from client silence.

## Pruefschwerpunkt 1 - Nullbestand vollstaendig

Status: **ERROR**

The hard symbol nullbestand is satisfied, but ZERO DEBT is not: productive code
still contains stale lease terminology in comments, docstrings, and user-facing
error text that is exclusively from the removed claim-lease model. This violates
the story's in-scope point 5 ("Kommentare/Dokumentation im Code angleichen")
and the review focus "Keine verwaiste Lease-Terminologie/Kommentare".

Hard nullbestand command:

```text
> rg -n "_CLAIM_LEASE_TTL|_claim_is_expired|takeover_operation|takeover_control_plane_operation_global" src/agentkit
<no output; rg exit code 1>
```

Public API cleanup evidence:

- `src/agentkit/backend/control_plane/repository.py:1-160`: import and
  dataclass field for `takeover_operation` are gone.
- `src/agentkit/backend/state_backend/store/_public_api_names.py:43-55`:
  startup/admin-abort/finalize/release names remain, but
  `takeover_control_plane_operation_global` is absent.
- `src/agentkit/backend/state_backend/store/__init__.pyi:1-335`: no dead
  `takeover_control_plane_operation_global` stub remains.

Blocking leftover terminology evidence:

- `src/agentkit/backend/control_plane/runtime.py:292`: ConfigError text still
  says `"leased owner-scoped claim"`.
- `src/agentkit/backend/control_plane/runtime.py:333-337`: `_acquire_claim`
  Args/Returns still call the owner token / outcome a "lease".
- `src/agentkit/backend/control_plane/runtime.py:349-352`: `claimed_at` is
  still described as "RAW lease epoch" / "THIS lease generation".
- `src/agentkit/backend/control_plane/runtime.py:424-426`: release CAS still
  says "lease epoch".
- `src/agentkit/backend/control_plane/runtime.py:2592-2603`: claim placeholder
  still says "in-flight leased" and "leased reservation".
- `src/agentkit/backend/state_backend/store/facade.py:1059-1070` and
  `src/agentkit/backend/state_backend/store/facade.py:1228-1243`: public store
  facade docstrings still use "leased claim", "RAW lease epoch", and "NEWER
  lease".
- `src/agentkit/backend/state_backend/postgres_store.py:2914-2926`,
  `src/agentkit/backend/state_backend/postgres_store.py:2980-2988`,
  `src/agentkit/backend/state_backend/postgres_store.py:2993-3001`,
  `src/agentkit/backend/state_backend/postgres_store.py:3053-3071`,
  `src/agentkit/backend/state_backend/postgres_store.py:3114-3137`,
  `src/agentkit/backend/state_backend/postgres_store.py:3294-3333`,
  `src/agentkit/backend/state_backend/postgres_store.py:3672-3689`,
  `src/agentkit/backend/state_backend/postgres_store.py:3728-3734`, and
  `src/agentkit/backend/state_backend/postgres_store.py:3804-3820`: real
  Postgres claim/finalize/release paths still refer to live claimed rows as
  leases and to `claimed_at` as lease epoch / lease generation.
- `tests/unit/control_plane/test_runtime.py:2263-2310`: test section and
  helper names still encode "leased" / "lease/CAS protocol" / "lease clock".

This is not a behavioral takeover bug, but it is a story-scope blocker: the
code now has the correct model while many comments and error messages still name
the deleted model. Under ZERO DEBT this must be fixed now, not carried as silent
cleanup debt.

## Pruefschwerpunkt 2 - Kein verdeckter Ersatz-Takeover

Status: **PASS**

No remaining path automatically takes over or frees a foreign in-flight claim
based on age, PID, heartbeat, or `claimed_at`.

Evidence:

- `src/agentkit/backend/control_plane/runtime.py:339-388`: `_acquire_claim`
  stamps `now` only for a fresh placeholder. After `claim_operation` loses, a
  stored `status == "claimed"` row directly returns `_in_flight_rejection`; there
  is no `claimed_at` comparison and no takeover call.
- `src/agentkit/backend/control_plane/runtime.py:390-417`: the rejection path
  returns a fail-closed in-flight result and never dispatches.
- `src/agentkit/backend/state_backend/postgres_store.py:2993-3050`: the real
  store acquisition is `INSERT ... ON CONFLICT DO NOTHING`; it does not inspect
  row age.
- `tests/unit/control_plane/test_runtime.py:2458-2507`: 1-minute, 10-minute,
  and 30-day foreign claims are all rejected and dispatcher calls stay empty.
- `tests/contract/state_backend/test_control_plane_operation_store_postgres.py:435-467`:
  a 30-day-old real-store claim blocks a second claim; original claimant remains
  untouched.

Relevant command:

```text
> rg -n "_CLAIM_LEASE_TTL|_claim_is_expired|takeover_operation|takeover_control_plane_operation_global" src/agentkit
<no output; rg exit code 1>
```

## Pruefschwerpunkt 3 - operation_epoch-CAS unberuehrt

Status: **PASS**

The AG3-138 fencing is still present and tested. `claimed_at` remains an audit /
CAS instant only; the claim acquisition path does not interpret it as expiry.

Evidence:

- `src/agentkit/backend/control_plane/runtime.py:354-357`: fresh claims retain
  `operation_epoch`; comments say admin-abort, not wall clock, moves the fence.
- `src/agentkit/backend/control_plane/runtime.py:892-899` and
  `src/agentkit/backend/control_plane/runtime.py:1846-1851`: start/resume
  finalization still passes `owner_operation_epoch`.
- `src/agentkit/backend/state_backend/postgres_store.py:3130-3146`: finalize CAS
  still combines `claimed_at` exact-match with `operation_epoch = ?`.
- `src/agentkit/backend/state_backend/postgres_store.py:3438-3485`: startup
  orphan finalize is identity-fenced and epoch-fenced.
- `tests/unit/control_plane/test_runtime.py:3371-3404`: late finalize after
  admin-abort with stale epoch is fenced and cannot overwrite aborted result.
- `tests/integration/control_plane/test_startup_reconcile_pg.py:222-268` and
  `tests/integration/control_plane/test_startup_reconcile_pg.py:271-322`:
  real-store normal finalize and orphan finalize both enforce stale-epoch
  rejection.

## Pruefschwerpunkt 4 - Endwege intakt

Status: **PASS**

Startup reconciliation and admin-abort remain the productive end paths for
orphaned/stuck in-flight claims.

Evidence:

- `tests/integration/control_plane/test_startup_reconcile_pg.py:154-177`: own
  earlier-incarnation claim is finalized; foreign identity is left claimed.
- `tests/integration/control_plane/test_startup_reconcile_pg.py:180-199`:
  pre-serve startup hook finalizes own orphan before serving.
- `tests/integration/control_plane/test_startup_reconcile_pg.py:398-490`:
  admin-abort routes partial write to `repair`, blocks new mutation, and resolves
  repair through the service path.

Command output:

```text
> .venv\Scripts\python -m pytest tests/integration/control_plane -q
...........                                                              [100%]
11 passed in 17.90s
```

## Pruefschwerpunkt 5 - Tests echt statt fabriziert

Status: **PASS**

The negative pins cover both the runtime path and the real Postgres store. The
unit fake is used for focused runtime control, but the contract/integration
tests exercise the productive store entrypoints and service path.

Evidence:

- `tests/unit/control_plane/test_runtime.py:2458-2507`: real
  `ControlPlaneRuntimeService.start_phase` over repository fake verifies old
  foreign claims reject and do not dispatch.
- `tests/unit/control_plane/test_runtime.py:3058-3099`: naive `claimed_at` does
  not crash and does not trigger takeover.
- `tests/contract/state_backend/test_control_plane_operation_store_postgres.py:435-467`:
  real Postgres `claim_control_plane_operation_global` proves old claims cannot
  be reclaimed at the store.
- `tests/contract/state_backend/test_control_plane_operation_store_postgres.py:539-615`:
  late finalize after admin-abort writes no side effects against the real store.

Command output:

```text
> .venv\Scripts\python -m pytest tests/unit/control_plane tests/contract/control_plane -q
248 passed in 29.59s

> .venv\Scripts\python -m pytest tests/contract/state_backend/test_control_plane_operation_store_postgres.py -q
19 passed in 27.78s
```

Search for old expiry hooks in tested areas:

```text
> rg -n "_CLAIM_LEASE_TTL|_claim_is_expired|takeover_control_plane_operation_global|takeover_operation|expired.*takeover|takeover.*expired" tests/unit/control_plane/test_runtime.py tests/contract/state_backend/test_control_plane_operation_store_postgres.py tests/integration/control_plane
<no output; rg exit code 1>
```

Historical wording remains in explanatory test comments (for example
`tests/unit/control_plane/test_runtime.py:3063-3068`) but there is no test that
depends on wall-clock expiry behavior.

## Pruefschwerpunkt 6 - Gates real

Status: **PASS**

All requested local gates and the project remote gates are green. I used the
project venv only.

Command outputs:

```text
> .venv\Scripts\python -m pytest tests/unit/control_plane tests/contract/control_plane -q
248 passed in 29.59s

> .venv\Scripts\python -m pytest tests/integration/control_plane -q
11 passed in 17.90s

> .venv\Scripts\python -m pytest tests/contract/state_backend/test_control_plane_operation_store_postgres.py -q
19 passed in 27.78s

> .venv\Scripts\python -m mypy src
Success: no issues found in 745 source files

> .venv\Scripts\python -m mypy src --platform linux
Success: no issues found in 745 source files

> .venv\Scripts\python -m ruff check src tests
All checks passed!

> .venv\Scripts\python -m pytest --cov=agentkit --cov-report=term --cov-fail-under=85 -q
8359 passed, 12 skipped, 2 warnings in 318.52s (0:05:18)
Required test coverage of 85% reached. Total coverage: 92.11%
```

Remote gates:

```json
{
  "sonar_quality_gate": "OK",
  "sonar_violations": 0,
  "sonar_critical_violations": 0,
  "sonar_security_hotspots": 0,
  "jenkins_color": "blue",
  "jenkins_last_build": {
    "building": false,
    "number": 947,
    "result": "SUCCESS",
    "url": "http://localhost:9900/job/claude-agentkit3/947/"
  },
  "jenkins_last_completed_build": {
    "number": 947,
    "result": "SUCCESS",
    "url": "http://localhost:9900/job/claude-agentkit3/947/"
  }
}
```

Operational note: direct `scripts\ci\check_remote_gates.ps1` first failed in
the current shell because Sonar env vars were absent. Loading
`T:\seu\agentkit3-secrets.cmd` and using `pwsh` succeeded; Windows PowerShell
5.1 hit a local `Microsoft.PowerShell.Security` typedata/module-load conflict.

## Out-of-scope findings

- **PASS / ignored as requested:** uncommitted `stories/*.md` deletions/moves in
  `git status --short` were not reviewed and not modified.
- **PASS / not AG3-139 auto-takeover:** remaining
  `takeover_transfer_records`, `save_takeover_transfer_record_global`, and
  related `takeover_*` names in `src/agentkit/backend/state_backend/**` belong
  to explicit ownership transfer / AG3-137/AG3-148 surfaces, not the removed
  claim-lease TTL / CAS-auto-takeover path.
- **WARNING / unrelated gate hygiene:** the full coverage run emitted
  `ResourceWarning: unclosed database in <sqlite3.Connection ...>` from
  `tests/unit/multi_llm_hub/test_multi_llm_hub_routes.py::test_post_hub_sessions_acquires_session`.
  This did not fail the gate and is outside AG3-139, but per severity semantics
  it should be mirrored: wie wollen wir hier vorgehen?

VERDICT: REJECT
