# AG3-138 Codex Adversarial QA Review R2

Reviewed range: `git diff 7db13952..e8c58ef8`; remediation focus:
`git diff 852fce52..e8c58ef8`. Uncommitted working-tree story-file churn was
ignored.

Prior review input: `stories/AG3-138-instance-identity-startup-reconcile/review-codex-r1.md`.

## R1 Error Re-Verification

### 1. Repair Exit

Status: **FIXED**

Evidence:

- `src/agentkit/backend/control_plane/runtime.py:1437-1449` now routes
  `admin_abort_inflight_operation` on `status == "repair"` to
  `_resolve_repair_operation`, not to the old not-abortable path.
- `src/agentkit/backend/control_plane/runtime.py:1484-1516` builds an audited
  `ControlPlaneMutationResult(status="resolved")` and persists it through the
  repository CAS resolve path.
- `src/agentkit/backend/state_backend/postgres_store.py:3665-3706` implements the
  productive CAS transition `WHERE op_id = ? AND status = 'repair'` to
  `status = 'resolved'`.
- `src/agentkit/backend/state_backend/postgres_store.py:3653-3662` keeps the
  mutation lock predicate scoped to `status = 'repair'`, so `resolved` is no
  longer open.
- `tests/integration/control_plane/test_startup_reconcile_pg.py:459-509` proves
  the real path: partial-write abort enters `repair`, a fresh mutating start is
  rejected, `admin_abort_inflight_operation` resolves the repair to `resolved`,
  and a fresh mutating start then commits.
- `tests/unit/control_plane/test_runtime.py:3537-3556` proves a truly terminal
  `resolved` operation still raises `OperationNotAbortableError` (HTTP 409 via
  `src/agentkit/backend/control_plane_http/app.py:1532-1539`).

### 2. E3 Epoch CAS Escape Hatch

Status: **FIXED**

Evidence:

- `src/agentkit/backend/state_backend/store/facade.py:1312-1320` now requires
  `owner_operation_epoch: int`; the nullable default is gone.
- `src/agentkit/backend/state_backend/postgres_store.py:3468-3476` requires
  `owner_operation_epoch: int`.
- `src/agentkit/backend/state_backend/postgres_store.py:3503-3524` always includes
  `AND operation_epoch = ?`; there is no `None` branch and no identity-only
  finalize.
- `src/agentkit/backend/control_plane/startup_reconcile.py:141-155` fails closed
  with `StartupReconciliationError` when a scanned own orphan has
  `operation_epoch is None`.
- `tests/unit/control_plane/test_startup_reconcile.py:220-241` pins the NULL-epoch
  own-orphan failure; the row stays `claimed`.
- `tests/integration/control_plane/test_startup_reconcile_pg.py:271-322` proves
  stale epoch is fenced out and matching epoch finalizes with an epoch bump.

### 3. E4 ARCH-55 German Docstring

Status: **FIXED**

Evidence:

- `src/agentkit/backend/control_plane/startup_reconcile.py:1-40` is now English,
  including the FK-10 sentence that was German in r1.
- Targeted grep over the changed AG3-138 code found no remaining German prose or
  German wire keys. The only remaining German token in changed source is `Regel`
  inside FK-91 citation labels (for example
  `src/agentkit/harness_client/projectedge/client.py:530-533`), not a wire key or
  executable contract.

### 4. E1 P1 Soundness Judgment

Status: **FIXED / ACCEPTABLE FOR AG3-138**

Ruling: the remediated posture is acceptable for AG3-138. The detector is still
not precise without durable object-claim serialization, but that imprecision is
fail-closed and recoverable, not fail-open.

Reasoning:

- The dangerous failure mode for IMPL-005 is a false negative: a real partial
  engine write silently finalized as `failed`. The current predicate deliberately
  avoids that by treating any `phase_states` / `flow_executions` write for the
  story in the claim window as repair:
  `src/agentkit/backend/state_backend/postgres_store.py:3564-3635`.
- The docs now state the safety/precision split honestly:
  `src/agentkit/backend/state_backend/postgres_store.py:3581-3613` says the probe
  is fail-closed-biased, may false-positive to `repair`, and needs AG3-141 for
  full precision.
- `src/agentkit/backend/control_plane/startup_reconcile.py:13-27` says the same
  thing at the service level and explicitly points precision to AG3-141.
- The story assigns object-claim acquisition / queue fairness and the
  `object_mutation_claims` reconciliation attachment to AG3-141:
  `stories/AG3-138-instance-identity-startup-reconcile/story.md:118-119`.
- The previously blocking consequence is gone: an over-conservative repair is now
  unlockable through the audited `admin_abort` repair-resolve path, and
  `tests/integration/control_plane/test_startup_reconcile_pg.py:481-509` proves
  that path re-admits later mutation.

Against IMPL-005, AC5 and AC10, this is a fail-closed handling state with a real
exit. It can over-lock, but it does not silently drop a partial write. That is no
longer an AG3-138 blocking ERROR; full precision remains AG3-141 scope.

## Regression Review

### 5. Class Splits

Severity: **PASS**

`ControlPlaneRuntimeService` now has MRO
`ControlPlaneRuntimeService -> _AdminTransitionMixin -> _ControlPlaneRuntimeAdmissionBase -> _ClaimLeaseMixin`
(`src/agentkit/backend/control_plane/runtime.py:264-360`,
`src/agentkit/backend/control_plane/runtime.py:517-568`,
`src/agentkit/backend/control_plane/runtime.py:1373-1544`,
`src/agentkit/backend/control_plane/runtime.py:1546`). The concrete base still
initializes `_repo`, `_now_fn`, `_token_factory`, `_instance_identity`, and
`_phase_dispatcher`.

`ControlPlaneApplication` now has MRO
`ControlPlaneApplication -> _StoryDashboardHandlersMixin -> _GovernanceMediationHandlers`
(`src/agentkit/backend/control_plane_http/app.py:527-695`), and the concrete
constructor still initializes the mixin dependencies before routing:
`src/agentkit/backend/control_plane_http/app.py:717-738`.

Live import/MRO smoke checks succeeded; no missing runtime attribute was found.

### 6. `_route_patterns.py` Extraction

Severity: **PASS**

The remediation moved the route regexes verbatim into
`src/agentkit/backend/control_plane_http/_route_patterns.py:13-68` and imports
them under the same names in `src/agentkit/backend/control_plane_http/app.py:40-55`.
The route order still checks story/search/dashboard/operation/admin-abort/phase/
closure as before (`src/agentkit/backend/control_plane_http/app.py:1075-1184`).
No mismatched route was found.

### 7. New `resolved` Terminal Status

Severity: **PASS**

`resolved` is present in the shared mutation result Literal and no-edge-bundle
set (`src/agentkit/backend/control_plane/models.py:552-582`). The HTTP endpoint
returns the shared model on success (`src/agentkit/backend/control_plane_http/app.py:1552-1555`),
the CLI treats `resolved` as a successful `admin-abort` exit
(`src/agentkit/backend/cli/main.py:2176-2224`), and the ProjectEdge client parses
it through `ControlPlaneMutationResult`
(`src/agentkit/harness_client/projectedge/client.py:522-556`). Contract tests
cover it (`tests/contract/control_plane/test_admin_abort_contract.py:87-115`).

### 8. Gates, K5, Normative Traps

Severity: **ERROR**

The official remote gate is not green. Running
`cmd /c "call T:\seu\agentkit3-secrets.cmd && pwsh -NoProfile -ExecutionPolicy Bypass -File scripts\ci\check_remote_gates.ps1"`
twice reported:

- `sonar_quality_gate = ERROR`
- `sonar_violations = 6`
- `sonar_critical_violations = 1`
- `sonar_security_hotspots = 0`
- Jenkins `color = red_anime`; build 944 still running; last completed build 943
  failed.

Per the repo's mandatory gates, this is blocking even though the AG3-138 code
remediation itself looks functionally correct.

Other checks:

- Targeted unit/contract suite passed: `138 passed`.
- Live Postgres reconciliation integration passed: `7 passed`.
- `ruff check src tests`: passed.
- `mypy src`: passed.
- `scripts/ci/check_concept_frontmatter.py`: passed.
- `scripts/ci/compile_formal_specs.py`: passed.

K5 and normative trap spot-check:

- K5 Postgres-only still fails closed through the runtime/store paths:
  `src/agentkit/backend/control_plane/runtime.py:2604-2618` and
  `src/agentkit/backend/state_backend/store/facade.py:1303-1334`.
- Pre-serve startup reconciliation still runs before socket bind:
  `src/agentkit/backend/control_plane_http/app.py:1598-1605`.
- TTL removal is still not part of AG3-138; `_ClaimLeaseMixin` still contains the
  pre-existing lease/takeover protocol (`src/agentkit/backend/control_plane/runtime.py:315-428`),
  matching the story's AG3-139 out-of-scope boundary
  (`stories/AG3-138-instance-identity-startup-reconcile/story.md:114-117`).
- Own-vs-foreign orphan filtering still matches only the same
  `backend_instance_id` and earlier incarnation:
  `src/agentkit/backend/state_backend/postgres_store.py:3454-3465`.
- Mutating rejected results, including the repair lock, still map to HTTP 409:
  `src/agentkit/backend/control_plane_http/app.py:1705-1726`.
- CLI remains a thin REST adapter, not a DB/runtime second path:
  `src/agentkit/harness_client/projectedge/client.py:522-556` and
  `src/agentkit/backend/cli/main.py:2162-2224`.

### Documentation Drift

Severity: **WARNING**

`src/agentkit/backend/state_backend/postgres_store.py:3648-3650` still says
resolving/clearing repair is follow-on AG3-150 scope, but
`src/agentkit/backend/state_backend/postgres_store.py:3665-3706` now implements
the AG3-138 repair resolve transition. This is not behavioral, but the stale
comment should be corrected so future reviewers do not infer the old r1 defect.

## Out-of-Scope Defects

None found beyond the explicit AG3-141 precision work for object-claim
serialization. That work should not change this verdict because the current
AG3-138 detector is fail-closed and recoverable.

VERDICT: REJECT
