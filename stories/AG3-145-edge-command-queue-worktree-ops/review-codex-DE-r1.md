Summary

REJECT. AC7 is not met because setup-failure cleanup still has a fail-open path:
if teardown command commissioning itself fails, the setup phase only logs a
warning and returns the original setup failure with no visible open
`teardown_worktree` command. Reset detach is materially better: it commissions an
auditable command and verifies clean only after the command exists. AC8 and AC11
are otherwise largely complete: the removed worktree path-authority surfaces are
gone, governance no longer writes `.agent-guard` files into worktrees, and the
remaining physical git/worktree backend call-sites are confined to the named
closure / verification evidence owners.

AC7 Verdict: NOT MET

Evidence:

- Setup failure after provisioning calls cleanup on both provisioning failure and
  lock / begin-progress failure:
  `src/agentkit/backend/governance/setup_preflight_gate/phase.py:334`-`340`,
  `src/agentkit/backend/governance/setup_preflight_gate/phase.py:348`-`355`.
- The cleanup path explicitly treats teardown commissioning as best-effort:
  `src/agentkit/backend/governance/setup_preflight_gate/phase.py:747`-`757`.
  It returns without action when no coordinator is present:
  `src/agentkit/backend/governance/setup_preflight_gate/phase.py:759`-`761`.
  It catches all exceptions from `ensure_teardown` and only logs:
  `src/agentkit/backend/governance/setup_preflight_gate/phase.py:762`-`775`.
- `ensure_teardown` requires an active ownership record and commissions via the
  edge command queue:
  `src/agentkit/backend/bootstrap/edge_provisioning_adapter.py:233`-`259`.
  Missing / foreign ownership raises `ConfigError`:
  `src/agentkit/backend/bootstrap/edge_provisioning_adapter.py:261`-`279`.
- Reset detach fails closed on missing active ownership:
  `src/agentkit/backend/bootstrap/story_reset_adapters.py:248`-`269`.
  It commissions `teardown_worktree` instead of backend deletion:
  `src/agentkit/backend/bootstrap/story_reset_adapters.py:274`-`283`.
  `has_live_worktree` reports dirty until every repo has a commissioned command:
  `src/agentkit/backend/bootstrap/story_reset_adapters.py:285`-`305`.
- Reset verifies the command-backed clean state before completion:
  `src/agentkit/backend/story_reset/service.py:542`-`550`.
- Edge execution is physically idempotent: first teardown removes, second returns
  `no_op`:
  `src/agentkit/harness_client/projectedge/command_executor.py:169`-`199`.
- Reset does not block on physical removal but leaves an open auditable command,
  as proven by the reset integration test:
  `tests/integration/story_reset/test_reset_worktree_teardown_edge.py:277`-`291`.

AC8 Verdict: MET

Evidence:

- `StateBackendWorktreeRepository` and the production `WorktreeRepository` port
  have no production references. The only grep hits are the new contract proof
  and test prose.
- `Governance.__init__` now takes only `hook_repo`, `lock_repo`, `project_key`,
  and `project_root`; no `worktree_repo` remains:
  `src/agentkit/backend/governance/runner.py:232`-`244`.
- Deactivation no longer reads worktree paths or writes worktree
  `.agent-guard` files; it purges edge bundles and QA lock export, then only
  writes the backend-local legacy tombstone when present:
  `src/agentkit/backend/governance/runner.py:360`-`378`,
  `src/agentkit/backend/governance/runner.py:442`-`489`.
- The dev-local lock-export tombstone is implemented in the edge publisher:
  `src/agentkit/harness_client/projectedge/client.py:401`-`433`.
- `workspace_locator.project_root` is documented and implemented as a backend
  state anchor, not a worktree anchor:
  `src/agentkit/backend/control_plane/workspace_locator.py:13`-`17`,
  `src/agentkit/backend/control_plane/workspace_locator.py:44`-`58`.
- The reset adapter reads only `worktree_map` repo names and does not derive
  physical worktree paths from `project_root`:
  `src/agentkit/backend/bootstrap/story_reset_adapters.py:307`-`320`.

AC11 Verdict: MET

Evidence:

- The SOLL-136 contract scans all backend Python files for removed surfaces and
  remaining `utils.git` / `remove_worktree` callers:
  `tests/contract/backend/test_soll136_execution_location.py:30`-`31`,
  `tests/contract/backend/test_soll136_execution_location.py:68`-`88`,
  `tests/contract/backend/test_soll136_execution_location.py:122`-`150`.
- `utils/git.py` retains only `tree_hash_of_commit` and `remove_worktree`:
  `src/agentkit/backend/utils/git.py:1`-`12`,
  `src/agentkit/backend/utils/git.py:65`-`100`,
  `src/agentkit/backend/utils/git.py:103`-`152`.
- Remaining `remove_worktree` use is closure-only:
  `src/agentkit/backend/closure/multi_repo_saga.py:76`-`95`,
  `src/agentkit/backend/closure/multi_repo_saga.py:324`-`335`.
- Remaining push / merge backend git call-sites match AG3-152:
  `src/agentkit/backend/closure/multi_repo_saga.py:147`-`188`,
  `src/agentkit/backend/closure/multi_repo_saga.py:264`-`321`,
  `src/agentkit/backend/closure/runtime_ports.py:367`-`386`.
- Remaining verification evidence git call-sites match AG3-147 / AG3-152:
  `src/agentkit/backend/bootstrap/composition_root.py:1223`-`1229`,
  `src/agentkit/backend/bootstrap/composition_root.py:1343`-`1355`,
  `src/agentkit/backend/bootstrap/composition_root.py:1442`-`1458`,
  `src/agentkit/backend/verify_system/evidence/request_resolver.py:196`-`215`,
  `src/agentkit/backend/verify_system/qa_cycle/fingerprint.py:227`-`244`,
  `src/agentkit/backend/verify_system/sonarqube_gate/runtime_wiring.py:284`-`316`.
- The provider-neutral `ls-remote` reader is AG3-146-owned, non-worktree ref
  read, and not one of the moved physical worktree call-sites:
  `src/agentkit/backend/code_backend/git_protocol.py:48`-`57`,
  `src/agentkit/backend/code_backend/git_protocol.py:78`-`93`.

Findings

CRITICAL: Setup-failure cleanup can silently leak a provisioned worktree when
teardown command commissioning fails.

Failure scenario: the edge has already provisioned a worktree, then setup fails
after provisioning, for example in `_acquire_lock_and_begin_progress`. The code
calls `_commission_failure_teardown` before returning the setup failure
(`phase.py:348`-`355`). If `ensure_teardown` raises because the active ownership
row is missing / foreign, the coordinator is unavailable, or the edge command
insert/load fails, `_commission_failure_teardown` catches `Exception` and only
logs a warning (`phase.py:762`-`775`). The returned `HandlerResult` still
contains only the original setup failure; there is no open `teardown_worktree`
command and no typed cleanup failure surfaced to the caller. That violates AC7's
"must not silently leak" requirement and the review instruction to reject
fail-open preflight/reset paths.

MAJOR: AC7 idempotency is sequential, not atomically idempotent at the command
insert boundary.

Failure scenario: two cleanup paths for the same `(run_id, repo)` both call
`commission_teardown_worktree`. The function performs `load_command` then a
plain insert (`edge_provisioning_adapter.py:94`-`114`), while the store documents
and implements duplicate `command_id` as a primary-key failure, not
`ON CONFLICT DO NOTHING` (`postgres_store.py:2860`-`2868`,
`postgres_store.py:2870`-`2879`). A sequential double-detach is covered, but a
concurrent duplicate can raise. This is fail-closed rather than a silent leak
when one command was inserted, so it is not the primary reject reason, but it
does not fully satisfy the "double-detach = one visible command / no error"
property under concurrency.

MINOR: The D+E delta introduces new German wording in production comments /
docstrings, contrary to ARCH-55's English-only rule for comments/docstrings.

Examples: `Teilschritt` in
`src/agentkit/backend/control_plane/workspace_locator.py:13` and
`src/agentkit/backend/control_plane/workspace_locator.py:48`, and `Schritt` in
`src/agentkit/backend/story_reset/service.py:199` and
`src/agentkit/backend/story_reset/service.py:538`-`540`.

Internal-Cut Integrity

Teardown has one operative truth for reset/setup cleanup: those paths commission
`teardown_worktree` commands and no longer call backend `remove_worktree`.
Backend `remove_worktree` remains reachable only through the AG3-152 closure
block (`multi_repo_saga.py:91`-`95`, `multi_repo_saga.py:324`-`335`), so there
are not two operative teardown truths for the D scope. The setup-failure
best-effort swallow above is still a release blocker because the one truth is
not guaranteed to be commissioned or surfaced.

K5 / ARCH-55

K5 is met for the command paths: edge-command repository methods are guarded by
the Postgres-only control-plane backend requirement
(`state_backend/store/facade.py:161`-`185`,
`state_backend/store/facade.py:1067`-`1084`,
`state_backend/store/facade.py:1089`-`1105`). ARCH-55 is not fully met because
new German comments/docstrings were introduced in production files, as listed in
the MINOR finding.

VERDICT: REJECT
