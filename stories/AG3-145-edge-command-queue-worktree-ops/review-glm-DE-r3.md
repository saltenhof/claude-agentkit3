# GLM r3 Confirmation Review — AG3-145 (D+E), HEAD a3aa7d12

Independent adversarial CONFIRMATION pass on the incremental fix delta
`a71238e1..a3aa7d12`. Scope: SOLL-136 conformance proof exhaustiveness (item 1),
`_commission_and_load` design note (item 2), ARCH-55 English-only (item 3),
regression watch (item 4). Static checks only — no Postgres/DB-touching pytest run.

## Summary

The r2 overclaim is **closed**. The rewritten
`tests/contract/backend/test_soll136_execution_location.py` now scans the
GENERAL backend git-subprocess surface (argv-list `["git", ...]` + GitPython)
and asserts `scanned == assigned` against an explicit 12-entry
`_GIT_SUBPROCESS_INVENTORY`. I independently re-grepped `src/agentkit/backend`
for every adversarial git-invocation form (argv list, shell-string, `os.system`,
`Popen`, `shell=True`, GitPython) and cross-checked the result against the
inventory: **exact match, 12 == 12, no missing site, no stale entry**. Each
assignment is honest (no worktree-provisioning/teardown op mislabelled as a
read/scan). The strict-insert design note is accurate and behaviour-preserving.
ARCH-55 is clean. `ruff`, `mypy --strict`, and the 10 contract tests pass.

## Item 1 — SOLL-136 proof: exhaustive + honest? **YES**

### Scan reach (adversarial)

`_GIT_ARGV_INVOCATION = re.compile(r"""\[\s*["']git["']""")`
(test_soll136_execution_location.py:62) matches the argv-list form on a single
line AND across a newline (`\s` includes `\n` in Python regex), so a multiline

```python
command = [
    "git",
    "diff",
```

is correctly captured (verified: `verify_system/evidence/request_resolver.py:202`
hits the scan with that exact shape).

`_GITPYTHON = re.compile(r"^\s*(?:import\s+git\b|from\s+git\s+import\b)|(?<![\w.])git\.Repo\s*\(", re.M)`
(test_soll136_execution_location.py:64-66) covers the GitPython surface
(`import git`, `from git import ...`, `git.Repo(...)`); none exists today, the
guard keeps the proof honest if one is introduced.

Forms the regex set does NOT match by construction, and the independent
adversarial grep I ran to close each gap:

| Adversarial form | Backend occurrence | Result |
|---|---|---|
| `subprocess.run("git ...", shell=True)` | none | the only `shell=True` is `verify_system/evidence/request_resolver.py:162` and runs `request.target` (an arbitrary test command from a reviewer request), NOT git; the git call in the same file is the argv-list `["git","diff",...]` at line 202, which IS scanned |
| `os.system("git ...")` | none anywhere under `src/agentkit/backend` | clean |
| `subprocess.Popen(...)` with a shell git string | zero `Popen` calls in the entire backend | clean |
| shell-string `"git foo"` literals | only in error messages / f-strings / command-classification tokens (`closure/runtime_ports.py:155`, `code_backend/git_protocol.py:92-130`, `governance/ccag/generalization.py:50,168`, `implementation/worker_loop/loop.py:292`, `telemetry/hooks/commit_hook.py:28`, etc.) — none is an invocation | clean |

Independent exhaustive scan reproducing the test's `_git_subprocess_sites()`:

```
bootstrap/composition_root.py
closure/multi_repo_saga.py
closure/runtime_ports.py
code_backend/git_protocol.py
governance/guard_system/secret_scan.py
installer/bootstrap_checkpoints/cp11_to_12.py
installer/github_coordinates.py
installer/runner.py
utils/git.py
verify_system/evidence/request_resolver.py
verify_system/qa_cycle/fingerprint.py
verify_system/sonarqube_gate/runtime_wiring.py
TOTAL 12
```

### Inventory completeness (12 == 12)

`_GIT_SUBPROCESS_INVENTORY` (test_soll136_execution_location.py:71-96) lists
exactly those 12 files. `set(scanned) == set(_GIT_SUBPROCESS_INVENTORY)` holds;
`test_every_backend_git_subprocess_site_is_assigned_in_the_inventory`
(test_soll136_execution_location.py:230) asserts equality with a diff that
reports `UNASSIGNED` (new, no owner) and `STALE` (assigned, gone) separately —
a NEW unassigned backend git site FAILS the test (drift proof), and so does a
stale entry. The `all(owner.strip() ...)` clause (line 248) additionally
prevents an empty-rationale cheat. This is the honest exhaustive proof AC11
demands; the prior r2 overclaim (scan limited to `create_worktree` /
`branch_exists` / `remove_worktree` / `utils.git` importers) is genuinely
fixed.

### Assignment honesty (no mislabelled provisioning/teardown op)

Spot-checked each site's actual argv against its owner label:

| File:line | Actual op | Label | Honest? |
|---|---|---|---|
| `utils/git.py:85` | `git rev-parse <sha>^{tree}` | AG3-152 tree-hash primitive | yes |
| `utils/git.py:124-133` | `git worktree remove --force <path>` | AG3-152 remove_worktree | yes (teardown, not provisioning) |
| `utils/git.py:153` | `git worktree prune` | AG3-152 (metadata cleanup inside `remove_worktree`) | yes — `prune` is teardown-bookkeeping, not `add` |
| `closure/multi_repo_saga.py:81` | `["git","-C",cwd,*args]` SubprocessGitBackend | AG3-152 closure saga | yes |
| `closure/runtime_ports.py:369,377` | `git -C ... diff HEAD~1..HEAD` | AG3-152 diff reads | yes |
| `verify_system/sonarqube_gate/runtime_wiring.py:301` | `git -C <root> *args` (rev-parse/ls-tree reads) | AG3-152 worktree-HEAD attestation | yes |
| `verify_system/evidence/request_resolver.py:202` | `git diff --unified=...` | AG3-147 QA diff evidence | yes |
| `verify_system/qa_cycle/fingerprint.py:230` | `git *_PINNED_GIT_CONFIG *args` (diff fingerprint) | AG3-147 | yes |
| `bootstrap/composition_root.py:1449` | `_git(...)` helper, rev-parse/merge-base | AG3-147/AG3-152 wiring | yes |
| `code_backend/git_protocol.py:81` | `git ls-remote --exit-code` | AG3-146 network read (FK-10 §10.2.4a(b)) | yes |
| `installer/github_coordinates.py:159` | `git remote get-url origin` | AG3-146 metadata read | yes |
| `governance/guard_system/secret_scan.py:83` | `git -C <root> *args` (history scan) | governance-secret-scan | yes |
| `installer/runner.py:1346` | `git clone <remote> <target>` | installer-bootstrap | yes |
| `installer/bootstrap_checkpoints/cp11_to_12.py:51,69` | `git config core.hooksPath` | installer-bootstrap | yes |

No site is a worktree provisioning/path op dressed up as a read. The two
legitimate teardown primitives (`worktree remove`, `worktree prune`) sit inside
`remove_worktree` and are correctly attributed to AG3-152 — i.e. they are the
*retained* backend teardown surface, not a regression of AG3-145.

### `test_no_backend_site_runs_git_worktree_add`

`worktree_add = re.compile(r"""["']worktree["']\s*,\s*["']add["']""")`
(test_soll136_execution_location.py:259) matches the argv form
`[..., "worktree", "add", ...]` and deliberately excludes prose mentions in
comments/docstrings/error strings. I confirmed zero offenders — no backend
file constructs a `"worktree", "add"` argv. The neighbouring `"worktree",
"remove"` (utils/git.py:129-132) and `"worktree", "prune"` (utils/git.py:153)
are correctly NOT flagged (teardown is intentionally retained). Sound.

### Stale `on_enter` docstring

`phase.py:229-233` now reads "Commission the Project Edge to provision the
worktree (`provision_worktree`, FK-10 §10.2.4a) ... The backend runs no
`git worktree add` itself." The previous false claim that the backend runs
`git worktree add` is gone. Honest.

## Item 2 — `_commission_and_load` design note: accurate? **YES**

`edge_provisioning_adapter.py:291-304` adds a docstring-only change; the method
body (lines 305-331) is byte-identical to `a71238e1` — strict
`load_command` → `insert_command` (line 309 → 311), no `commission_command`,
no `ON CONFLICT`. The note's claims check out:

- "setup phase executes serially PER RUN ... NOT a concurrent-replay surface" —
  consistent with the PAUSE/resume loop in `SetupPhaseHandler.on_enter`; one
  owning session per run, re-entry goes through `load_command` which returns
  the existing record (line 309), so idempotent re-entry is already handled.
- "FK-10 §10.5.3 scopes idempotent (`ON CONFLICT DO NOTHING`) commissioning to
  the TEARDOWN path" — matches `commission_teardown_worktree`, the only
  atomic-idempotent commissioning site (introduced in `e0ff1c86`).
- "genuine duplicate `command_id` ... MUST fail loudly (primary-key violation)" —
  `insert_command` raises on PK conflict; no silent no-op.

No behaviour change slipped in (docstring-only diff, verified by reading the
full method). Honest and accurate.

## Item 3 — ARCH-55: any German in the delta? **NO**

Grepped the three touched files for `[ÄÖÜäöüß]`, `Ausführungsort`, `Inventar`:
zero hits. The prior `Ausführungsort-Inventar` heading was reworded to
"Execution-location inventory (SOLL-136)" (test_soll136_execution_location.py:51).
The two FK-10 §... section references are coordinate identifiers, not German
prose. ARCH-55 clean.

## Item 4 — Regression watch

- `ruff check src tests` — All checks passed.
- `mypy --strict src` — Success: no issues found in 755 source files.
- `pytest tests/contract/backend/test_soll136_execution_location.py` — 10 passed.
- No production-code body changed (item 1 is test-only; item 2 is a docstring;
  item 3 is the same docstring reworded). AC7/AC8 surfaces (the
  `_UTILS_GIT_REMAINING_CONSUMERS`, `_REMOVE_WORKTREE_CALLERS`,
  `test_utils_git_importers_are_exactly_the_ag3152_consumers`,
  `test_remove_worktree_callers_are_only_the_ag3152_closure_block` tests) are
  untouched and still pass. No new fail-open: the strict-insert path still
  raises on duplicate `command_id`; the exhaustive scan fails loudly on any
  drift in either direction.

## Findings

None at CRITICAL / MAJOR / MINOR. The fix delta closes the r2 overclaim with an
honest, drift-proof exhaustive scan; the inventory matches the actual backend
git-subprocess surface 1:1; assignments are truthful; the design note is
accurate and behaviour-preserving; ARCH-55 is clean; no regression.

VERDICT: APPROVE
