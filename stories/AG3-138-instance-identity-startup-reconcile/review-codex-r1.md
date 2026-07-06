# AG3-138 Codex Adversarial QA Review R1

Reviewed range: `git diff 7db13952..852fce52`, with remediation focus on `dc12040e..852fce52`.

Concept sources used from the checked-in concept corpus because no `agentkit3-concepts` MCP tools were exposed in this session:
`concept/technical-design/91_api_event_katalog.md`, `concept/technical-design/10_runtime_deployment_speicher.md`, `concept/formal-spec/state-storage/invariants.md`, `concept/formal-spec/state-storage/entities.md`, `concept/formal-spec/operating-modes/invariants.md`.

## Attack Surface Assessment

### 1. P1 - Partial-write detection bound to claim window, `run_id` filter removed

Severity: **ERROR**

The remediation removed `run_id` and now classifies any `flow_executions`/`phase_states` write for the story at or after the claim timestamp as this operation's partial write:

- `src/agentkit/backend/control_plane/startup_reconcile.py:151-152` uses `repo.has_engine_writes_since(op.story_id, since)`.
- `src/agentkit/backend/control_plane/runtime.py:2103-2104` uses the same story+since probe for `admin_abort`.
- `src/agentkit/backend/state_backend/postgres_store.py:3606-3618` queries `flow_executions WHERE story_id = ? AND started_at >= ?` and `phase_states WHERE story_id = ? AND updated_at >= ?`.
- `src/agentkit/backend/state_backend/postgres_store.py:3584-3590` documents the required premise: at-most-one-active-operation-per-story means any story write after `since` belongs to this claim.

That premise is not enforced in the landed code. Control-plane in-flight claims are keyed only by `op_id`:

- `src/agentkit/backend/state_backend/postgres_schema.sql:249-253` defines `control_plane_operations` with `op_id TEXT PRIMARY KEY`.
- `src/agentkit/backend/state_backend/postgres_store.py:2993-3028` acquires a claim with `INSERT ... ON CONFLICT (op_id) DO NOTHING`.
- `src/agentkit/backend/control_plane/runtime.py:2568-2592` only stamps `declared_serialization_scope`; it does not acquire the object claim before dispatch.

The actual durable story/object serialization mechanism is explicitly still future work:

- `src/agentkit/backend/state_backend/postgres_schema.sql:315-324` defines `object_mutation_claims` with `PRIMARY KEY (project_key, serialization_scope, scope_key)`.
- `src/agentkit/backend/state_backend/postgres_store.py:2558-2564` says the productive claim-acquisition / queue logic is AG3-141.

This conflicts with the normative model:

- `concept/technical-design/10_runtime_deployment_speicher.md:883-889` requires durable object-mutation-claim acquisition before dispatch for lifecycle/story mutations because engine writes and control-plane finalization span separate DB transactions.
- `concept/formal-spec/state-storage/entities.md:77-87` defines the object-mutation-claim entity.

Impact: a clean orphaned claim for story S can be classified as `repair` because a different operation for S wrote `flow_executions` or `phase_states` after the orphan's `claimed_at`. The false-positive is not harmless: it creates an open repair lock and, because no real repair exit exists (see item 5), can deadlock the story. The integration test even models attribution by story+window rather than operation identity: it commits `op-350-start`, then seeds a distinct claimed `op-350-crash` and aborts it to `repair` based on the earlier operation's write (`tests/integration/control_plane/test_startup_reconcile_pg.py:425-454`).

Assessment of the documented residual risk: this is **not** safely out of scope for AG3-150/AG3-141. AG3-141 may own the full object-claim acquisition implementation, but AG3-138 already relies on that serialization invariant to decide `failed` vs `repair`. Until the invariant is enforced or the detector has a real operation binding, P1 is a live defect in AG3-138.

`phase_states` is indeed story-keyed with no `run_id` (`src/agentkit/backend/state_backend/postgres_schema.sql:77-87`), and `flow_executions` is also story-keyed with `story_id TEXT PRIMARY KEY` despite having a `run_id` column (`src/agentkit/backend/state_backend/postgres_schema.sql:124-135`). Removing the `run_id` filter avoids one false-negative class, but the replacement predicate is unsound without the missing story/object claim.

### 2. P2 - `rejected` mutation results map to 409

Severity: **PASS**

The HTTP mapping is now centralized for the requested mutation entrypoints:

- `src/agentkit/backend/control_plane_http/app.py:1242-1290` routes start/complete/fail/resume through `_mutation_result_response`.
- `src/agentkit/backend/control_plane_http/app.py:1299-1329` routes closure through the same helper.
- `src/agentkit/backend/control_plane_http/app.py:1729-1750` maps `result.status == "rejected"` to `409 CONFLICT`, otherwise `201 CREATED`.

This includes repair-lock rejections and other fail-closed rejections such as unadmitted-run. I did not find a phase/closure mutation path still returning 2xx for `rejected`.

Concept citation: FK-91 rule 18 expects deterministic `409`/`403` fail-closed rejection payloads for invalid mutating story calls (`concept/technical-design/91_api_event_katalog.md:298-305`).

### 3. P3 - `operation_epoch` CAS in startup orphan finalize

Severity: **ERROR**

The productive startup path passes the scanned epoch:

- `src/agentkit/backend/control_plane/startup_reconcile.py:123-130` calls `finalize_orphaned_operation(... owner_operation_epoch=op.operation_epoch)`.
- `src/agentkit/backend/state_backend/postgres_store.py:3499-3513` appends the epoch predicate and bumps `operation_epoch` when a non-`None` epoch is supplied.

But the row/facade API still has an identity-only finalize escape hatch:

- `src/agentkit/backend/state_backend/store/facade.py:1312-1320` exposes `owner_operation_epoch: int | None = None`.
- `src/agentkit/backend/state_backend/postgres_store.py:3475-3493` also defaults `owner_operation_epoch` to `None` and documents that `None` keeps the legacy identity-only fence.
- `src/agentkit/backend/state_backend/postgres_store.py:3516-3527` returns an empty SQL fragment when `owner_operation_epoch is None`.

This violates the invariant that operation finalize requires CAS on unchanged `operation_epoch`:

- `concept/formal-spec/state-storage/invariants.md:67-69` requires finalize only by compare-and-swap while the operation is still in-flight with unchanged `operation_epoch`.
- FK-91 also lists `operation_epoch` among the commit fencing predicates (`concept/technical-design/91_api_event_katalog.md:274-277`).

Even if the main startup caller normally supplies an epoch, a nullable/public no-CAS path remains and malformed/legacy rows with identity but `operation_epoch = NULL` would finalize without the epoch fence instead of failing closed.

### 4. P4 - ARCH-55 English in wire-facing keys/admin notes/comments

Severity: **ERROR**

The remediation mostly converted German strings, but a German code docstring/comment remains:

- `src/agentkit/backend/control_plane/startup_reconcile.py:3-4` includes the German sentence `"der Server muss über seinen eigenen Absturz nicht spekulieren; über das Schweigen eines Clients schon"`.

ARCH-55 applies to comments too:

- `CLAUDE.md:202` requires source code, identifiers, data models, wire keys, schema fields, event/API contracts, and code comments to be English only.

I did not find German in the new wire keys or `admin_note` payload strings; the remaining failure is the code comment/docstring.

### 5. Repair exit / no deadlock

Severity: **ERROR**

There is no real, tested production path out of `repair`.

The lock predicate is a raw open `status = 'repair'` row:

- `src/agentkit/backend/state_backend/postgres_store.py:3630-3644` treats any `control_plane_operations` row for the story with `status = 'repair'` as open.
- `src/agentkit/backend/state_backend/postgres_store.py:3635-3637` explicitly says resolving/clearing repair is follow-on AG3-150 scope.

`admin_abort` cannot resolve that state:

- `src/agentkit/backend/control_plane/runtime.py:2067-2072` rejects any target whose status is not `claimed`.
- `src/agentkit/backend/state_backend/postgres_store.py:3555-3560` updates only `WHERE status = 'claimed'`.
- `src/agentkit/backend/control_plane_http/app.py:1404-1410` maps that non-abortable state to 409.

The "reversible" unit test does not exercise a real service path; it directly mutates fake repository state from `repair` to `aborted`:

- `tests/unit/control_plane/test_runtime.py:3491-3497` hand-edits `state.operations["op-repair-open"]`.

This violates AG3-138 AC10's requirement that mutations are blocked "until the state [is] resolved via `admin_abort`/Repair" (`stories/AG3-138-instance-identity-startup-reconcile/story.md:184-188`) and the user-specified repair-exit guarantee. A false-positive repair from P1 becomes a permanent story mutation lock.

### 6. Regression across story-runs / dispatch / finalize / admission / AG3-137 ownership

Severity: **WARNING**

No broad signature regression was found for the `has_engine_writes_since` removal: the repository port is now two-argument (`src/agentkit/backend/control_plane/repository.py:180-190`), runtime/startup callers use the new form, and the HTTP mutation paths still reach runtime admission.

However, the P1 remediation creates a cross-cutting regression risk in dispatch/finalize semantics: `start_phase` claims only the `op_id` before running the dispatcher (`src/agentkit/backend/control_plane/runtime.py:472-486`), while `_start_phase_after_claim` runs dispatch before the control-plane finalize (`src/agentkit/backend/control_plane/runtime.py:594-674`). Without the object claim required by FK-10, two different operation ids for the same story can overlap in the exact window P1 uses as proof of operation identity.

This is listed as WARNING here only because the blocking manifestation is already captured as the P1 ERROR.

### 7. ACs, normative traps, K5 spot-check

Severity: **ERROR**

Spot-check result:

- AC1 / AC9 startup hook: **PASS**. `serve_control_plane` runs the hook before binding the `ThreadingHTTPSServer` socket (`src/agentkit/backend/control_plane_http/app.py:1622-1629`), and the hook propagates failures (`src/agentkit/backend/control_plane_http/app.py:667-704`).
- AC2 own-vs-foreign identity: **PASS**. Orphan scan filters same `backend_instance_id` and earlier incarnation (`src/agentkit/backend/state_backend/postgres_store.py:3454-3464`).
- AC3 identity stamping: **PASS**. Fresh claims stamp `backend_instance_id`, `instance_incarnation`, and `operation_epoch` (`src/agentkit/backend/control_plane/runtime.py:2568-2592`).
- AC4 epoch fence: **ERROR** because the orphan finalize API still permits `owner_operation_epoch=None`; see item 3.
- AC5 partial-write repair: **ERROR** because story+since attribution is unsound without durable object-claim serialization; see item 1.
- AC6 admin-abort contract: **PASS** for 404/409/repair payload mapping (`src/agentkit/backend/control_plane_http/app.py:1397-1424`), but it is not a repair resolver.
- AC7 CLI adapter: **PASS** by inspection of the changed CLI/client path; no direct DB path found in the admin-abort CLI tests (`tests/unit/cli/test_admin_abort_cli.py`).
- AC8 TTL untouched / no new wall-clock: **PASS with known story debt**. The existing `_CLAIM_LEASE_TTL` remains (`src/agentkit/backend/control_plane/runtime.py:89`, `src/agentkit/backend/control_plane/runtime.py:789-815`), matching AG3-138's "do not remove TTL yet" trap, and P1 uses recorded timestamps rather than current wall-clock for detection. The existing TTL takeover remains AG3-139 debt.
- AC10 mutation lock: **ERROR** because the lock can be entered with a false-positive repair and has no production exit; see items 1 and 5.
- AC11 ARCH-55: **ERROR** because a German code docstring remains; see item 4.
- K5 Postgres-only: **PASS**. Runtime default-store entrypoints fail closed unless the control-plane Postgres backend is available (`src/agentkit/backend/control_plane/runtime.py:380-394`, `src/agentkit/backend/control_plane/runtime.py:2497-2525`), and facade ownership/control-plane functions require the control-plane backend (`src/agentkit/backend/state_backend/store/facade.py:153-172`).

Concept citations: `formal.state-storage.invariants` forbids wall-clock/TTL/heartbeat release of instance-bound claims (`concept/formal-spec/state-storage/invariants.md:61-66`) and requires epoch CAS (`concept/formal-spec/state-storage/invariants.md:67-69`); FK-91 rule 16 requires instance-bound in-flight claims and no wall-clock ownership semantics (`concept/technical-design/91_api_event_katalog.md:280-291`); FK-10 §10.5.4 requires durable object mutation claims before dispatch (`concept/technical-design/10_runtime_deployment_speicher.md:883-889`).

## Out-of-Scope Defects

None separated. The object-claim acquisition itself may be assigned to AG3-141, but AG3-138's landed P1 logic already depends on the serialization guarantee. That makes the current unsound repair classification in-scope for this review and verdict.

VERDICT: REJECT
