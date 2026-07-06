# AG3-139 - Codex adversarial QA review R2

Review scope: remediation diff `git diff 5f1c6ca9..3c0e82c0`.
Reference scope: total story diff `git diff 7dd7259c..3c0e82c0`.
HEAD verified locally as `3c0e82c068b32a5f0247644901022f22d57924cd`.
Uncommitted `stories/*.md` movements in the worktree were ignored as requested.

## Pruefpunkt 1 - R1-ERROR Remediation

Status: **ERROR**

The r1-listed productive locations were remediated correctly: the old live-claim
lease wording in `runtime.py`, `facade.py`, and the `postgres_store.py` claim /
finalize / release clusters is now phrased as owner-scoped claim / claim instant /
claim generation. The r1-listed `tests/unit/control_plane/test_runtime.py`
section was also renamed to claim terminology.

Evidence for fixed r1 locations:

- `src/agentkit/backend/control_plane/runtime.py:292`: owner token error now says
  `"owner-scoped claim"`, not leased claim.
- `src/agentkit/backend/control_plane/runtime.py:333-337`: `_acquire_claim`
  Args/Returns now say owner token / won claim.
- `src/agentkit/backend/control_plane/runtime.py:349-352`: `claimed_at` is now
  described as the raw claim instant / claim generation.
- `src/agentkit/backend/control_plane/runtime.py:424-426`: release CAS now says
  claim instant / newer claim generation.
- `src/agentkit/backend/control_plane/runtime.py:2592-2603`: placeholder text now
  says in-flight `claimed` placeholder / reservation, not leased reservation.
- `src/agentkit/backend/state_backend/store/facade.py:1059-1070` and
  `src/agentkit/backend/state_backend/store/facade.py:1228-1243`: public facade
  docstrings now use owner-scoped claim / raw claim instant / claim generation.
- `src/agentkit/backend/state_backend/postgres_store.py:2914-2922`,
  `src/agentkit/backend/state_backend/postgres_store.py:2980-2988`,
  `src/agentkit/backend/state_backend/postgres_store.py:2993-3001`,
  `src/agentkit/backend/state_backend/postgres_store.py:3060-3071`,
  `src/agentkit/backend/state_backend/postgres_store.py:3114-3122`,
  `src/agentkit/backend/state_backend/postgres_store.py:3323-3333`,
  `src/agentkit/backend/state_backend/postgres_store.py:3672-3689`,
  `src/agentkit/backend/state_backend/postgres_store.py:3728-3734`, and
  `src/agentkit/backend/state_backend/postgres_store.py:3810-3820`: the old
  lease wording is gone from the real store claim/finalize/release paths.
- `tests/unit/control_plane/test_runtime.py:2263-2310`: section/helper names are
  now `owner-scoped claim`, `claim/CAS protocol`, `_Clock`, and `_claim_service`.

Blocking residual in the remediation diff:

- `tests/contract/state_backend/test_control_plane_operation_store_postgres.py:780`
  still names the test `test_finalize_release_are_lease_epoch_scoped_real_store`.
- `tests/contract/state_backend/test_control_plane_operation_store_postgres.py:783`
  still says `finalize/release CAS key on owner AND lease epoch`.

This is the same class of dead model terminology as r1: a claim-path test still
uses the removed lease model for the `claimed_at` CAS generation. It is not a
behavioral bug, but it is in a remediated AG3-139 claim-path test and violates
the ZERO DEBT cleanup criterion.

Command output:

```text
> rg -n "test_finalize_release_are_lease_epoch_scoped_real_store|lease epoch" tests/contract/state_backend/test_control_plane_operation_store_postgres.py
780:def test_finalize_release_are_lease_epoch_scoped_real_store(
783:    """WARNING-4 (#4): finalize/release CAS key on owner AND lease epoch.
```

Old r1/productive-string phrases are gone:

```text
> rg -n "LIVE 'claimed' lease|LIVE ``claimed`` start lease|live 'claimed' lease|held by a live 'claimed' lease|held by a LIVE 'claimed' lease|claimed' start lease" src tests
<no output; rg exit code 1>
```

## Pruefpunkt 2 - Gegenprobe Source Lease Terminology

Status: **PASS**

I grepped the required productive areas:

```text
> rg -n -i "\b(lease|leases|leased|leasing|ttl|expiry|expired|expires|expiration)\b|takeover" src/agentkit/backend/control_plane src/agentkit/backend/state_backend
```

Remaining productive hits are acceptable:

- FK-91 / negative invariant wording, e.g.
  `src/agentkit/backend/control_plane/runtime.py:167-168`,
  `src/agentkit/backend/control_plane/runtime.py:323-327`,
  `src/agentkit/backend/control_plane/runtime.py:384-385`,
  `src/agentkit/backend/control_plane/records.py:193-195`,
  `src/agentkit/backend/state_backend/postgres_schema.sql:242`, and
  `src/agentkit/backend/state_backend/store/mappers.py:1194-1196`.
- Removed-model negative pins, e.g.
  `src/agentkit/backend/control_plane/runtime.py:252`,
  `src/agentkit/backend/control_plane/runtime.py:355`,
  `src/agentkit/backend/state_backend/postgres_store.py:3008-3010`.
- Explicit AG3-137 takeover-transfer surfaces, not the removed AG3-139 claim TTL
  takeover path, e.g. `takeover_transfer_records` and
  `save_takeover_transfer_record_global`.

No productive source hit describes a live claimed row as a lease or implements a
wall-clock/TTL/lease-expiry ownership end path.

## Pruefpunkt 3 - Kein Verhaltensdelta Durch Remediation

Status: **PASS**

The remediation diff is wording/private-name cleanup only. It changes comments,
docstrings, error strings, private test helper names, and private local names.
The actual claim/CAS/fencing behavior is unchanged:

- `git diff --stat 5f1c6ca9..3c0e82c0`: 10 files, `126 insertions(+)`,
  `125 deletions(-)`.
- `src/agentkit/backend/state_backend/postgres_store.py:2993-3050` still uses
  `INSERT ... ON CONFLICT (op_id) DO NOTHING`; no age predicate was added.
- `src/agentkit/backend/state_backend/postgres_store.py:3114-3127` still builds
  the raw `claimed_at IS NOT DISTINCT FROM ?` CAS fragment.
- `src/agentkit/backend/state_backend/postgres_store.py:3130-3146` still adds the
  `operation_epoch = ?` fence when supplied.
- `src/agentkit/backend/control_plane/runtime.py:247` and
  `src/agentkit/backend/control_plane/runtime.py:456`: private mixin rename is
  complete (`_ClaimMixin`).
- `src/agentkit/backend/state_backend/postgres_store.py:3142-3146`: local rename
  to `claim_clause` / `claim_params` is complete and still feeds the same SQL
  fragment.

Private old names are gone from the reviewed paths:

```text
> rg -n "_ClaimLeaseMixin|_leased_service|_leased_op|lease_clause|lease_params" src/agentkit/backend/control_plane src/agentkit/backend/state_backend tests/unit/control_plane/test_runtime.py tests/contract/state_backend/test_control_plane_operation_store_postgres.py
<no output; rg exit code 1>
```

Reference integrity is also proven by mypy:

```text
> .venv\Scripts\python -m mypy src
Success: no issues found in 745 source files

> .venv\Scripts\python -m mypy src --platform linux
Success: no issues found in 745 source files
```

## Pruefpunkt 4 - User-Sichtbarer Error-Text

Status: **PASS**

The `ControlPlaneClaimCollisionError` text no longer says `LIVE 'claimed' lease`.
It now says `LIVE 'claimed' row` in both productive collision paths:

- `src/agentkit/backend/state_backend/postgres_store.py:2984-2988`
- `src/agentkit/backend/state_backend/postgres_store.py:3728-3734`

The unit fake mirrors the new wording:

- `tests/unit/control_plane/test_runtime.py:180-182`
- `tests/unit/control_plane/test_runtime.py:268-270`

No test or code assert still pins the old string:

```text
> rg -n "LIVE 'claimed' lease|LIVE ``claimed`` start lease|live 'claimed' lease|held by a live 'claimed' lease|held by a LIVE 'claimed' lease|claimed' start lease" src tests
<no output; rg exit code 1>
```

## Kurz-Recheck R1-Punkte 2-6

Status: **PASS**

R1 point 2, no hidden replacement takeover: still PASS. The acquisition path
rejects a foreign `claimed` row of any age and never compares `claimed_at` to the
wall clock (`runtime.py:339-388`, `postgres_store.py:2993-3050`). The unit and
real-store pins still pass.

R1 point 3, `operation_epoch` CAS: still PASS. `claimed_at` is a claim-generation
CAS instant, and `operation_epoch` remains the AG3-138 fence
(`postgres_store.py:3130-3146`, `postgres_store.py:3329-3333`).

R1 point 4, end paths intact: still PASS. Startup reconciliation and explicit
`admin_abort_inflight_operation` remain the only productive orphan/stuck-claim
end paths; the integration suite is green.

R1 point 5, tests are real rather than fabricated: still PASS. The runtime fake
tests cover admission behavior; the real Postgres contract test covers the store
entrypoints; the control-plane integration suite covers startup/admin end paths.

R1 point 6, gates: local and remote gates are green after one transient Docker
port-race retry in the full coverage run.

Command outputs:

```text
> .venv\Scripts\python -m pytest tests/unit/control_plane tests/contract/control_plane -q
248 passed in 30.85s

> .venv\Scripts\python -m pytest tests/integration/control_plane -q
11 passed in 21.26s

> .venv\Scripts\python -m pytest tests/contract/state_backend/test_control_plane_operation_store_postgres.py -q
19 passed in 30.77s

> .venv\Scripts\python -m mypy src
Success: no issues found in 745 source files

> .venv\Scripts\python -m mypy src --platform linux
Success: no issues found in 745 source files

> .venv\Scripts\python -m ruff check src tests
All checks passed!
```

Coverage first attempt hit an infrastructure port race, not a coverage miss:

```text
> .venv\Scripts\python -m pytest --cov=agentkit --cov-report=term --cov-fail-under=85 -q
ERROR ... docker: Error response from daemon: failed to bind host port 0.0.0.0:54308/tcp: address already in use
8338 passed, 12 skipped, 8 warnings, 21 errors in 332.62s (0:05:32)
Required test coverage of 85% reached. Total coverage: 92.01%
```

Immediate unchanged retry passed:

```text
> .venv\Scripts\python -m pytest --cov=agentkit --cov-report=term --cov-fail-under=85 -q
8359 passed, 12 skipped, 16 warnings in 331.21s (0:05:31)
Required test coverage of 85% reached. Total coverage: 92.11%
```

Remote gates were checked via `T:\seu\agentkit3-secrets.cmd` and
`scripts\ci\check_remote_gates.ps1`:

```json
{
  "sonar_quality_gate": "OK",
  "sonar_violations": 0,
  "sonar_critical_violations": 0,
  "sonar_security_hotspots": 0,
  "jenkins_color": "blue",
  "jenkins_last_build": {
    "building": false,
    "number": 948,
    "result": "SUCCESS",
    "url": "http://localhost:9900/job/claude-agentkit3/948/"
  },
  "jenkins_last_completed_build": {
    "number": 948,
    "result": "SUCCESS",
    "url": "http://localhost:9900/job/claude-agentkit3/948/"
  }
}
```

Jenkins build 948 was not an older green build; its built revision is the target
remediation commit:

```json
{
  "number": 948,
  "result": "SUCCESS",
  "url": "http://localhost:9900/job/claude-agentkit3/948/",
  "lastBuiltRevision": {
    "SHA1": "3c0e82c068b32a5f0247644901022f22d57924cd",
    "branch": "refs/remotes/origin/main"
  }
}
```

## Out-of-scope / Residual Notes

- **PASS / ignored as requested:** unrelated uncommitted `stories/*.md` moves and
  deletions were not reviewed or modified.
- **WARNING / unrelated gate hygiene:** the full coverage run still emits
  `ResourceWarning: unclosed database in <sqlite3.Connection ...>` warnings from
  unrelated suites. The gate passes, but per severity semantics this should be
  mirrored: wie wollen wir hier vorgehen?

VERDICT: REJECT
