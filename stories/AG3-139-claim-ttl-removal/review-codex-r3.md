# AG3-139 - Codex adversarial QA review R3

Review scope: remediation diff `git diff 3c0e82c0..0b0a7627`.
Reference scope: total story diff `git diff 7dd7259c..0b0a7627`.
HEAD verified locally as `0b0a7627af0715b274dc3db77833e20ce2b1c495`.
Uncommitted `stories/*.md` movements in the worktree were ignored as requested.

## Pruefpunkt 1 - R2-Blocker Remediation

Status: **PASS**

The r2 blocker is remediated. The old `lease epoch` wording in the real
Postgres contract test was replaced by `claim generation` terminology in all
three r2-listed locations:

- `tests/contract/state_backend/test_control_plane_operation_store_postgres.py:643`:
  section comment now says `WARNING-4 (claim-generation scoped finalize/release)`.
- `tests/contract/state_backend/test_control_plane_operation_store_postgres.py:780`:
  the test is now named
  `test_finalize_release_are_claim_generation_scoped_real_store`.
- `tests/contract/state_backend/test_control_plane_operation_store_postgres.py:783`:
  docstring now says `finalize/release CAS key on owner AND claim generation`.

Command output:

```text
> git diff --unified=0 3c0e82c0..0b0a7627 -- tests/contract/state_backend/test_control_plane_operation_store_postgres.py
@@ -643 +643 @@
-# a live claim), WARNING-4 (lease-epoch scoped finalize/release) against the
+# a live claim), WARNING-4 (claim-generation scoped finalize/release) against the
@@ -780 +780 @@
-def test_finalize_release_are_lease_epoch_scoped_real_store(
+def test_finalize_release_are_claim_generation_scoped_real_store(
@@ -783 +783 @@
-    """WARNING-4 (#4): finalize/release CAS key on owner AND lease epoch.
+    """WARNING-4 (#4): finalize/release CAS key on owner AND claim generation.
```

Required terminology grep:

```text
> rg -n -w -i "lease|leases|leased|leasing" tests/contract/state_backend/test_control_plane_operation_store_postgres.py tests/unit/control_plane/test_runtime.py
tests/unit/control_plane/test_runtime.py:2126:    lease (FK-91 §91.1a Regel 16), so this is just an ordinary foreign in-flight
tests/unit/control_plane/test_runtime.py:2461:    Ownership never ends by wall clock / TTL / lease (FK-91 §91.1a Regel 16). A
```

Both remaining word-boundary `lease` hits are the permitted FK-91 negative
invariant wording. The required negative TTL pins remain explicit and acceptable:

- `tests/contract/state_backend/test_control_plane_operation_store_postgres.py:443-444`:
  old foreign real-store claim is well past the `FORMER 5-minute TTL` and still
  blocks because ownership never ends by wall clock.
- `tests/unit/control_plane/test_runtime.py:2490`: `op-old-10m` is past the
  `FORMER 5-minute TTL`.

Old productive removed-model strings are absent:

```text
> rg -n "lease epoch|lease-epoch|test_finalize_release_are_lease_epoch_scoped_real_store|leased owner|leased claim|lease generation|live .*lease|LIVE .*lease" tests/contract/state_backend/test_control_plane_operation_store_postgres.py tests/unit/control_plane/test_runtime.py src/agentkit/backend/control_plane src/agentkit/backend/state_backend
tests/contract/state_backend/test_control_plane_operation_store_postgres.py:643:# a live claim), WARNING-4 (claim-generation scoped finalize/release) against the
tests/unit/control_plane/test_runtime.py:2408:    B holds a live claim that A never owned. A's stale release/finalize (a wrong
tests/unit/control_plane/test_runtime.py:2512:    No half-applied binding/lock/event survives, and the released claim is
```

The non-empty lines above are `release` / `released` substring matches, not live
claim-lease terminology.

Old TTL/takeover symbols remain absent:

```text
> rg -n "_CLAIM_LEASE_TTL|_claim_is_expired|takeover_control_plane_operation_global|takeover_operation|expired.*takeover|takeover.*expired" src/agentkit tests/unit/control_plane/test_runtime.py tests/contract/state_backend/test_control_plane_operation_store_postgres.py tests/integration/control_plane
<no output; rg exit code 1>
```

## Pruefpunkt 2 - Kein Verhaltensdelta im R2-Diff

Status: **PASS**

The r2 remediation diff is pure test terminology:

```text
> git diff --stat 3c0e82c0..0b0a7627
 .../state_backend/test_control_plane_operation_store_postgres.py    | 6 +++---
 1 file changed, 3 insertions(+), 3 deletions(-)

> git diff --name-only 3c0e82c0..0b0a7627
tests/contract/state_backend/test_control_plane_operation_store_postgres.py
```

No logic and no assert changed. The modified lines are only the section comment,
the private test function name, and the docstring. The renamed test still runs
inside the real Postgres contract file:

```text
> .venv\Scripts\python -m pytest tests/contract/state_backend/test_control_plane_operation_store_postgres.py -q
bringing up nodes...
bringing up nodes...

...................                                                      [100%]
19 passed in 24.77s
```

## Pruefpunkt 3 - Kurz-Recheck der R1/R2-PASS-Substanz

Status: **PASS**

No hidden replacement takeover: still PASS. The acquisition path is still the
plain real-store insert path, and the negative real-store pin still documents
`INSERT ... ON CONFLICT (op_id) DO NOTHING` as the only claim attempt
(`tests/contract/state_backend/test_control_plane_operation_store_postgres.py:441`).

Operation-epoch CAS remains intact: still PASS. Evidence remains in
`src/agentkit/backend/state_backend/postgres_store.py:3127` for
`claimed_at IS NOT DISTINCT FROM ?`, `postgres_store.py:3145` for the
`operation_epoch = ?` fence, and the integration tests
`tests/integration/control_plane/test_startup_reconcile_pg.py:222` and `:271`
for normal and startup-orphan epoch fencing.

End paths remain intact: still PASS. Startup reconciliation and explicit
`admin_abort_inflight_operation` are still the productive stuck/orphan claim end
paths, covered by `tests/integration/control_plane/test_startup_reconcile_pg.py`.

Tests are real: still PASS. Runtime unit tests cover admission behavior; the
Postgres contract file covers store entrypoints; integration tests cover the
service/startup paths.

Command outputs:

```text
> .venv\Scripts\python -m pytest tests/unit/control_plane tests/contract/control_plane -q
bringing up nodes...
bringing up nodes...

........................................................................ [ 29%]
........................................................................ [ 58%]
........................................................................ [ 87%]
................................                                         [100%]
248 passed in 30.90s

> .venv\Scripts\python -m pytest tests/integration/control_plane -q
bringing up nodes...
bringing up nodes...

...........                                                              [100%]
11 passed in 16.53s
```

## Pruefpunkt 4 - Local Gates

Status: **PASS for focused local gates; ERROR for full local coverage command stability**

Required focused local gates are green:

```text
> .venv\Scripts\python -m mypy src
Success: no issues found in 745 source files

> .venv\Scripts\python -m mypy src --platform linux
Success: no issues found in 745 source files

> .venv\Scripts\python -m ruff check src tests
All checks passed!
```

The full local coverage command reached the coverage threshold but did not
produce a green local test gate in this environment. First full run failed due
to Docker/Postgres port-race setup errors, not due to an AG3-139 assertion or
coverage threshold:

```text
> .venv\Scripts\python -m pytest --cov=agentkit --cov-report=term --cov-fail-under=85 -q
ERROR ... docker: Error response from daemon: failed to set up container networking:
failed to bind host port 0.0.0.0:59474/tcp: address already in use
...
8322 passed, 12 skipped, 6 warnings, 37 errors in 318.60s (0:05:18)
Required test coverage of 85% reached. Total coverage: 92.01%
```

Two retry attempts did not produce a usable green local coverage result:

```text
> .venv\Scripts\python -m pytest --cov=agentkit --cov-report=term --cov-fail-under=85 -q
command timed out after 904171 milliseconds

> $env:AGENTKIT_STATE_BACKEND='postgres'; $env:AGENTKIT_STATE_DATABASE_URL='postgresql://agentkit:agentkit@127.0.0.1:61741/agentkit_test'; .venv\Scripts\python -m pytest --cov=agentkit --cov-report=term --cov-fail-under=85 -q
command timed out after 1204567 milliseconds
```

Operational cleanup note: the explicitly started retry container
`ak3-postgres-codex-r3-60220` was removed after the timeout:

```text
> docker rm -f ak3-postgres-codex-r3-60220
ak3-postgres-codex-r3-60220
```

## Pruefpunkt 5 - Remote Gates

Status: **ERROR**

Sonar is green with the required zero metrics, but Jenkins is red for the
required target commit. This is a hard Pflicht-Gate failure under `CLAUDE.md` /
`AGENTS.md`.

`scripts\ci\check_remote_gates.ps1` after Build 949 completed:

```json
{
  "sonar_quality_gate": "OK",
  "sonar_violations": 0,
  "sonar_critical_violations": 0,
  "sonar_security_hotspots": 0,
  "jenkins_color": "red",
  "jenkins_last_build": {
    "_class": "org.jenkinsci.plugins.workflow.job.WorkflowRun",
    "building": false,
    "number": 949,
    "result": "FAILURE",
    "url": "http://localhost:9900/job/claude-agentkit3/949/"
  },
  "jenkins_last_completed_build": {
    "_class": "org.jenkinsci.plugins.workflow.job.WorkflowRun",
    "number": 949,
    "result": "FAILURE",
    "url": "http://localhost:9900/job/claude-agentkit3/949/"
  }
}
Exception: scripts\ci\check_remote_gates.ps1:82
throw "Jenkins is not green."
```

Build 949 is not an older green build; it is the requested HEAD commit:

```json
{"number":949,"url":"http://localhost:9900/job/claude-agentkit3/949/","sha":"0b0a7627af0715b274dc3db77833e20ce2b1c495","result":"FAILURE","building":false}
```

Jenkins console failure:

```text
FAILED tests/unit/state_backend/store/test_mode_lock_acquire_release.py::test_concurrent_opposite_acquires_cannot_both_pass
AssertionError: exactly one acquire must win; got {'standard': 'ok'}
sqlite3.OperationalError: no such column: completed_at
Coverage XML written to file coverage.xml
Required test coverage of 85.0% reached. Total coverage: 86.09%
1 failed, 6701 passed, 38 skipped, 28 warnings in 610.70s (0:10:10)
Stage "Postgres Contract + Integration" skipped due to earlier failure(s)
Stage "SonarQube" skipped due to earlier failure(s)
Stage "Quality Gate" skipped due to earlier failure(s)
Finished: FAILURE
```

Local repro of the specific Jenkins-failing test passed once, so I do not treat
this as AG3-139 behavioral evidence. It remains a remote Pflicht-Gate blocker:

```text
> .venv\Scripts\python -m pytest tests/unit/state_backend/store/test_mode_lock_acquire_release.py::test_concurrent_opposite_acquires_cannot_both_pass -q
bringing up nodes...
bringing up nodes...

.                                                                        [100%]
1 passed in 13.20s
```

## Verdict

The r2 terminology blocker is fixed, the AG3-139 behavioral substance still
passes, and Sonar is clean. I cannot approve because Jenkins Build 949 on
`0b0a7627af0715b274dc3db77833e20ce2b1c495` is red, and the project rules make a
green Jenkins gate mandatory before "fertig".

VERDICT: REJECT
