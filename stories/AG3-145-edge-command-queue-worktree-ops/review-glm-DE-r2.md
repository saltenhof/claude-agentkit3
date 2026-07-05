# AG3-145 D+E r2 review (GLM half of the redundant review)

- Reviewer: GLM (independent adversarial half; Codex runs in parallel)
- Scope: sub-step D (AC7, AC8) + sub-step E (AC11) at HEAD `a71238e1`
  (base `8a0db444`); full D+E delta reviewed via
  `git --no-pager diff 8a0db444..a71238e1`
- Method: static read of the diff + targeted grep over `src/agentkit/backend`;
  no control-plane DB tests run. `mypy src` (755 files, clean) and
  `ruff check src tests` (clean) executed via the project venv.
- R1 baseline reviewed: the 3 findings raised against `db6e6cc0` (CRITICAL
  silent leak, MAJOR non-atomic commission, MINOR ARCH-55) and the claimed
  remediations in `e0ff1c86` + `e58ac3a8` + `a71238e1`.

## Summary

The 3 R1 findings are genuinely closed at `a71238e1`. AC7 and AC8 are met
with file:line evidence. AC11 is met for the surfaces the story actually
moved (worktree provisioning / teardown / governance writes / path
authority); the SOLL-136 conformance test is sound but its docstring
slightly overstates exhaustiveness (one MINOR finding flagged, not
blocking — the residual hit is in AG3-146 territory, predates this story,
and is a metadata read, not a worktree op). Teardown has exactly ONE truth
(the edge-commissioned `teardown_worktree` command); both call-paths
(reset-detach and setup-failure cleanup) flow through
`commission_teardown_worktree`. No surviving consumer of
`StateBackendWorktreeRepository` / the removed `WorktreeRepository` port.
No silent leak path remains.

## R1 findings — closure status

### R1-1 CRITICAL (silent leak on setup-failure teardown) — CLOSED

Trace (`src/agentkit/backend/governance/setup_preflight_gate/phase.py`):

- `_setup_worktrees_if_needed` returns FAILED on a partial provisioning
  outcome; the FAILED branch now wraps the result through
  `_with_failure_teardown` (phase.py:335-340). The post-provisioning
  `lock_error` path is likewise wrapped (phase.py:351-356) — both
  post-provision failure paths are covered, no residual unwrapped leak.
- `_with_failure_teardown` (phase.py:750-772) calls
  `_commission_failure_teardown` and, when it returns a non-None cleanup
  message, RECONSTRUCTS a FAILED `HandlerResult` carrying
  `errors=(*failure.errors, cleanup_error)` — the cleanup failure is
  surfaced as an ADDITIONAL typed error, not swallowed. The original
  setup failure is preserved as `errors[0]`.
- `_commission_failure_teardown` (phase.py:774-823) returns `None` only
  on the genuine no-leak paths (`not uses_worktree`, `not repos`,
  `self._edge_provisioning is None` — i.e. nothing was provisioned);
  on a real edge/DB commission fault it catches the exception, logs at
  `ERROR`, and returns a NAMED `worktree_teardown_cleanup_failed: ...`
  message. With the atomically-idempotent `commission_command`, a
  concurrent duplicate is no longer an error here; the residual failure
  modes are genuine edge/DB faults which must surface (and do).

Test evidence (the r1 finding demanded a test that actually asserts the
surfacing — not silent):

- `tests/unit/governance/setup_preflight_gate/test_phase.py::
  TestSetupPhaseHandlerWorktree::test_teardown_commission_failure_is_surfaced_not_silent`
  scripts the coordinator to raise `RuntimeError("edge command queue
  insert failed")` from `ensure_teardown`, drives the real
  `SetupPhaseHandler.on_enter`, and asserts:
  (a) `result.status is PhaseStatus.FAILED`,
  (b) `coordinator.teardown_calls == [("repo",)]` (the cleanup WAS
  attempted), and
  (c) `any("worktree_teardown_cleanup_failed" in e for e in result.errors)`
  — i.e. the cleanup failure is auditable on the returned FAILED result,
  not swallowed.
- The matching positive path `test_provision_failure_commissions_teardown`
  proves the cleanup IS commissioned on a plain provisioning failure.

No residual path where a provisioned worktree ends with neither a visible
open `teardown_worktree` command nor a surfaced cleanup-failure error.

### R1-2 MAJOR (non-atomic idempotent commissioning) — CLOSED

- `src/agentkit/backend/state_backend/postgres_store.py::
  commission_edge_command_record_global_row` (lines ~2898-2943) is a true
  `INSERT INTO edge_command_records (...) VALUES (...) ON CONFLICT
  (command_id) DO NOTHING` returning `int(cursor.rowcount) == 1`.
- `src/agentkit/backend/state_backend/store/facade.py::
  commission_edge_command_record_global` (lines ~1079-1095) fail-closes
  on non-Postgres (`_require_control_plane_backend()`) and delegates to
  the row function.
- `src/agentkit/backend/control_plane/repository.py:353-355` binds the
  `EdgeCommandRepository.commission_command` port to that facade
  function (return type `bool`).
- `src/agentkit/backend/bootstrap/edge_provisioning_adapter.py::
  commission_teardown_worktree` (lines ~58-105) calls
  `edge_commands.commission_command(EdgeCommandRecord(...))` per repo —
  NO load-then-insert race; the prior load-then-insert pattern is gone
  from the teardown path.

Concurrency proof: `tests/integration/state_backend/
test_edge_command_records_postgres.py::test_concurrent_commission_of_same_id_never_raises`
runs 6 threads through a `threading.Barrier` commissioning the SAME
deterministic `command_id` at the same instant and asserts
`results.count(True) == 1`, `results.count(False) == 5`, no exception —
exactly the "one True, rest False, none raises" contract. The
`test_commission_is_idempotent_on_duplicate_command_id` test covers the
serial double-commission case.

Other edge-command inserts: the provisioning path
(`SetupEdgeProvisioningCoordinator._commission_and_load`,
edge_provisioning_adapter.py:294-313) still uses STRICT `insert_command`
(load-then-insert). This is by design — `provision_worktree` /
`preflight_probe` are NOT the idempotent-replay surface (FK-10 §10.5.3
idempotency is specifically the teardown path); a duplicate provision
attempt is correctly an error, and the provision path is fenced by the
setup phase itself. No residual race on the path R1-2 demanded.

### R1-3 MINOR ARCH-55 (German in delta) — CLOSED

`git diff 8a0db444..a71238e1 | grep '^\+'` over the delta leaves exactly
two German hits, both the concept-term reference
`"Ausführungsort-Inventar"` in
`tests/contract/backend/test_soll136_execution_location.py` (a comment +
a docstring referencing the story's inventory section title). ARCH-55
explicitly permits German in concept/prose references
("Fach-/Konzept-Prosa darf weiter deutsch sein"). The previously-flagged
`Teilschritt` was uniformly replaced with `sub-step` across the delta
(phase.py, edge_provisioning.py, edge_provisioning_adapter.py,
test_phase.py, test_deactivate_locks.py docstrings). No German
identifiers, wire keys, DB columns, or code comments remain in the
delta.

## Per-AC verdict

### AC7 (teardown-as-edge-command) — MET

- Reset-detach commissions the edge command, never calls
  `remove_worktree`: `src/agentkit/backend/bootstrap/
  story_reset_adapters.py::WorktreePurgeAdapter.detach_worktrees`
  (lines ~252-293) imports and calls `commission_teardown_worktree`,
  scoped to the run's OWN active ownership record (loaded via
  `ownership_repo.load_active_ownership`). A missing/non-matching
  ownership record raises `StoryResetWorktreeError` (fail-closed, never
  a silent skip). `has_live_worktree` (lines ~295-309) treats the
  commissioned teardown command as the §53.8 end-state — the reset does
  NOT block on the physical removal.
- Setup-failure cleanup commissions the same edge command via
  `SetupEdgeProvisioningCoordinator.ensure_teardown`
  (edge_provisioning_adapter.py:231-256) → `commission_teardown_worktree`.
  Both teardown call-paths converge on the single helper — teardown has
  exactly ONE truth (the edge-commissioned command; FK-10 §10.4.2).
- Idempotency: deterministic `edge_command_id(run_id, "teardown_worktree",
  repo)` + `INSERT ... ON CONFLICT DO NOTHING` → a double-detach is one
  visible command / no error (concurrency test above).
- Non-blocking + auditable: fire-and-forget; the commissioned command
  stays visibly open per SOLL-165 / Rule 16 (no TTL/expiry field in the
  delta; verified by absense).
- Real-executor end-to-end proof:
  `tests/integration/story_reset/test_reset_worktree_teardown_edge.py`
  drives the REAL `WorktreePurgeAdapter` against a REAL Postgres
  Edge-Command-Queue + ownership record + persisted `StoryContext`,
  then feeds the open command through the REAL
  `harness_client.projectedge.command_executor.execute_command` and
  asserts the reported `result_payload["outcome"] == "no_op"` for an
  already-absent worktree (FK-10 §10.5.3 idempotent edge execution).

### AC8 (path-authority rollback) — MET

- `StateBackendWorktreeRepository` deleted
  (`src/agentkit/backend/state_backend/store/worktree_repository.py`
  removed in the delta).
- `WorktreeRepository` Protocol removed from
  `src/agentkit/backend/governance/repository.py` (the deleted lines
  366-400 in the diff).
- No surviving production consumer: grep over the whole tree returns
  only doc/story/concept/test-assertion hits (the contract test
  `test_soll136_execution_location.py` itself asserts
  `StateBackendWorktreeRepository` is unreferenced in
  `src/agentkit/backend`).
- `Governance.__init__` no longer takes `worktree_repo`
  (governance/runner.py:236-242); `_restore_ai_augmented_mode`
  (runner.py:443-487) no longer iterates worktree paths, no longer
  writes `.agent-guard/lock.json` or `.agent-guard/mode.json`. The
  legacy backend-local `_temp/governance/locks/{story_id}/mode.json`
  tombstone is retained (NOT a worktree write). All composition-root
  instantiations of `StateBackendWorktreeRepository` removed
  (composition_root.py: build_story_exit_service,
  build_story_split_service, build_story_reset_service,
  _build_guard_deactivation_port).
- Dev-local projection proven edge-side by the pre-existing
  `tests/unit/projectedge/test_client.py::
  test_local_edge_publisher_removes_tombstoned_lock_export`, which
  feeds `tombstone_worktree_roots=[str(worktree)]` through
  `LocalEdgePublisher.publish` and asserts the worktree's
  `.agent-guard/lock.json` is removed. The new
  `tests/unit/governance/test_deactivate_locks.py::
  TestDeactivateLocksDoesNotTouchWorktrees::test_worktree_agent_guard_files_are_untouched`
  proves the BACKEND no longer reaches into the worktree (lock export
  survives deactivate_locks; no mode.json written there).
- `workspace_locator.project_root` is now documented as a pure
  backend-local state anchor (workspace_locator.py:5-11, 42-52,
  110-119); grep for
  `workspace_locator\.project_root|locator\.project_root|workspace\.project_root`
  in `src/agentkit` returns only `control_plane/dispatch.py` uses that
  set `ctx.project_root` (state anchor) and build story_dir / gate
  guards — NO consumer derives a physical worktree path from it.

### AC11 (SOLL-136 grep-proof) — MET (with one MINOR caveat)

Independent grep over `src/agentkit/backend`:

- `create_worktree` (post-removal): every hit is either a docstring
  comment (`utils/git.py:7`, `edge_provisioning.py:5`,
  `setup_preflight_gate/phase.py:229`), a `SetupConfig.create_worktree`
  flag (legitimate config field, phase.py:139/149/634), or a
  composition-root comment (`composition_root.py:2726-2740`). No
  `def create_worktree(` definition, no caller.
- `branch_exists`: every hit is in
  `installer/integration_checkpoints/*` (the AG3-146 provider-adapter
  self-test harnesses, signature `branch_exists(project_key, branch)` —
  NOT the removed `utils.git.branch_exists(repo_root, branch)`). No
  `def branch_exists(` definition in `utils/git.py`, no caller of the
  removed primitive.
- `remove_worktree`: hits are exactly the AG3-152 closure block
  (`closure/multi_repo_saga.py:19/72/91/94/335`,
  `closure/phase.py:1088/1096/1099` — the duck-type config check), the
  `utils/git.py:103` primitive definition, and a `principal_capabilities/
  operations.py:465` docstring. The reset adapter and setup-failure
  cleanup NO LONGER appear. Matches `_REMOVE_WORKTREE_CALLERS` in the
  contract test.
- `git -C`: 2 hits — `utils/git.py:107` (docstring of the retained
  primitive) and `installer/github_coordinates.py:159`
  (`derive_github_coordinates` runs `git -C <project_root> remote
  get-url origin`). The latter is AG3-146 territory (the provider-adapter
  story), predates this story, is a read-only remote-URL metadata probe,
  and is NOT in the SOLL-136 inventory (which scopes to worktree +
  closure/push). See MINOR-1 below.
- GitPython: no hits in `src/agentkit/backend`.

The contract gate
`tests/contract/backend/test_soll136_execution_location.py` is a genuine
source-scan (no runtime imports of the scanned modules) and asserts the
moved surfaces are gone AND the remaining `utils.git` importers /
`remove_worktree` callers equal exactly the AG3-152 closure set. Each
asserted neighbour site is also asserted to still exist
(`test_inventory_neighbour_sites_still_exist`).

### Internal-cut invariants

- Teardown has exactly ONE truth: both the reset path
  (`WorktreePurgeAdapter.detach_worktrees`) and the setup-failure path
  (`SetupEdgeProvisioningCoordinator.ensure_teardown`) import and call
  the SAME `commission_teardown_worktree` helper
  (edge_provisioning_adapter.py:__all__ exports it).
- K5 Postgres-only for command paths:
  `commission_edge_command_record_global` calls
  `_require_control_plane_backend()` (facade.py:1090); the existing
  strict `insert_command` / `commit_result` paths are already gated.
- ARCH-55: closed (see R1-3 above).

## Findings

### MINOR-1 — WARNING: SOLL-136 conformance test docstring overstates scope
(`tests/contract/backend/test_soll136_execution_location.py:14-15`)

The module docstring claims: *"the REMAINING backend git call-sites are
EXACTLY the ones the story's 'Ausführungsort-Inventar' assigns to the
neighbour stories -- the AG3-152 closure/merge block ... and the AG3-147
push/QA-evidence block. There is NO unassigned finding."* The test body,
however, only greps for `create_worktree` / `branch_exists` /
`remove_worktree` / `agentkit.backend.utils.git` importers. It does NOT
grep for general backend git subprocess patterns (`subprocess.run(...
"git" ...)`, `git -C`), so a future regression introducing a NEW backend
git subprocess unrelated to those three primitives would slip past this
gate while the docstring still claims exhaustiveness.

Concrete residual hit the test does not cover:
`src/agentkit/backend/installer/github_coordinates.py:159`
`derive_github_coordinates` runs `subprocess.run(["git", "-C",
str(project_root), "remote", "get-url", "origin"], ...)`. This is a
backend git subprocess not assigned to AG3-147 or AG3-152 in the
SOLL-136 inventory.

Mitigating context (why WARNING, not ERROR/REJECT):
- `derive_github_coordinates` was introduced by AG3-146 (commit
  `6f408218`), NOT by AG3-145. It is not a regression this story
  introduced.
- It is a read-only remote-URL metadata probe, not a worktree
  provisioning / teardown / push-evidence operation. The literal subject
  of SOLL-136 (worktree ops AG3-145 moves + the listed closure/push
  sites) IS fully covered.
- AG3-146 is the designated provider-adapter neighbour story; reading
  remote-URL metadata is in that story's scope, not AG3-145's.

Failure scenario if left unaddressed: a future story could add a NEW
backend `git -C ...` worktree-mutating subprocess; the SOLL-136 gate as
written would not catch it because it only checks the three named
primitives, yet the docstring would still advertise "NO unassigned
finding".

Recommended action (mirror to Auftraggeber per SEVERITY-SEMANTIK /
ZERO DEBT): either (a) tighten the conformance test docstring to "no
unassigned `create_worktree` / `branch_exists` / `remove_worktree` /
`utils.git` importer finding" (narrow the claim to what is actually
checked), or (b) extend the test to enumerate `git -C` / generic
`subprocess` git patterns and explicitly assign
`installer/github_coordinates.py` and the
`installer/integration_checkpoints/*` harness probes to AG3-146 in the
asserted inventory. Option (b) makes the AC11 wording literally true.

This finding does not block the story: the three R1 findings are fully
closed, teardown has one truth, no surviving consumer of removed
surfaces, and the surfaces AG3-145 actually moved are gone with a sound
proof.

## Final verdict

VERDICT: APPROVE
