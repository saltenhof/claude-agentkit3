Summary

REJECT. The r1 CRITICAL teardown leak is closed and the r1 teardown-specific
atomic commissioning finding is closed for `teardown_worktree`. AC7 and AC8 are
met for reset/setup teardown and removed path-authority surfaces. AC11 is not
met: the SOLL-136 proof is not exhaustive, and a current backend `git -C`
call-site remains in `governance/guard_system/secret_scan.py` without an
AG3-147/AG3-152 assignment. ARCH-55 is also not clean because the D+E delta adds
German wording in test comments/docstrings.

Allowed static checks run:

- `.venv\Scripts\python -m ruff check src tests` -> passed.
- `.venv\Scripts\python -m mypy src` -> passed.

R1 Findings

1. CRITICAL setup-failure teardown leak: CLOSED.

Evidence: setup failure after provisioning calls `_with_failure_teardown` for
both edge provisioning failure and later lock/begin-progress failure
(`src/agentkit/backend/governance/setup_preflight_gate/phase.py:334`,
`:338`, `:350`, `:356`). `_with_failure_teardown` preserves the original
FAILED result and appends a cleanup error when `_commission_failure_teardown`
returns one (`phase.py:769`, `:774`, `:778`). `_commission_failure_teardown`
now catches commissioning faults only to return the named
`worktree_teardown_cleanup_failed` message (`phase.py:800`, `:808`, `:815`).
The not-silent unit test asserts the extra error and original first error
(`tests/unit/governance/setup_preflight_gate/test_phase.py:431`, `:476`,
`:479`, `:483`).

2. MAJOR non-atomic idempotent teardown commissioning: CLOSED for teardown;
not globally closed for every edge-command insert.

Evidence: `commission_edge_command_record_global_row` is a real
`INSERT ... ON CONFLICT (command_id) DO NOTHING` (`src/agentkit/backend/state_backend/postgres_store.py:2900`,
`:2917`, `:2924`). The facade exposes it as a boolean idempotent commission
port (`src/agentkit/backend/state_backend/store/facade.py:1079`, `:1090`,
`:1093`), `EdgeCommandRepository.commission_command` wires it
(`src/agentkit/backend/control_plane/repository.py:350`, `:353`), and
`commission_teardown_worktree` uses `commission_command`, not load-then-insert
(`src/agentkit/backend/bootstrap/edge_provisioning_adapter.py:95`, `:97`).
The concurrency test asserts exactly one `True`, five `False`, and no raise
(`tests/integration/state_backend/test_edge_command_records_postgres.py:178`,
`:187`, `:190`, `:191`).

Residual: `preflight_probe` / `provision_worktree` still use `_commission_and_load`,
which does `load_command` then strict `insert_command` (`edge_provisioning_adapter.py:290`,
`:296`, `:298`). That is a remaining racy edge-command insert path, though not
the teardown path remediated by r1.

3. MINOR ARCH-55 German comments: NOT CLOSED.

The new SOLL-136 contract adds German wording in comments/docstrings:
`"Ausführungsort-Inventar"` at
`tests/contract/backend/test_soll136_execution_location.py:13` and line `39`.

AC7 Verdict: MET

Evidence: reset detach commissions `teardown_worktree` via the edge command port
and fails closed when the active ownership record is missing or does not match
the reset run (`src/agentkit/backend/bootstrap/story_reset_adapters.py:248`,
`:262`, `:264`, `:274`). Reset clean-state treats the auditable commissioned
command as the non-blocking completion condition (`story_reset_adapters.py:285`,
`:299`; `src/agentkit/backend/story_reset/service.py:537`, `:541`). The reset
integration test proves reset completes without physical removal and leaves an
open command (`tests/integration/story_reset/test_reset_worktree_teardown_edge.py:277`,
`:281`, `:284`, `:288`). Edge execution is physically idempotent:
missing worktree returns `no_op` (`src/agentkit/harness_client/projectedge/command_executor.py:169`,
`:183`, `:189`, `:194`, `:196`).

Setup-failure cleanup is also non-silent after remediation: failures in teardown
commission are surfaced on the returned FAILED `HandlerResult`
(`phase.py:769`, `:774`, `:778`, `:815`).

AC8 Verdict: MET

Evidence: `src/agentkit/backend/state_backend/store/worktree_repository.py` no
longer exists, and `rg` over `src/agentkit/backend` finds no
`StateBackendWorktreeRepository` / `WorktreeRepository` production consumer.
`Governance` no longer accepts a `worktree_repo` dependency
(`src/agentkit/backend/governance/runner.py:224`, `:232`, `:238`). Governance
deactivation documents that worktree `.agent-guard` projection is edge-owned and
only writes the backend-local legacy tombstone (`runner.py:367`, `:442`, `:449`,
`:477`, `:480`). `workspace_locator.project_root` is documented as a pure
backend-local state anchor and explicitly not a worktree anchor
(`src/agentkit/backend/control_plane/workspace_locator.py:13`, `:44`, `:48`,
`:109`, `:113`, `:115`). Reset reads only `StoryContext.worktree_map` keys, not
physical paths derived from `project_root`
(`src/agentkit/backend/bootstrap/story_reset_adapters.py:307`, `:310`, `:317`).

AC11 Verdict: NOT MET

Evidence: the new contract claims all remaining backend git call-sites are
exactly the story inventory (`tests/contract/backend/test_soll136_execution_location.py:12`,
`:13`, `:15`), but it only scans `agentkit.backend.utils.git` importers and
`remove_worktree` string hits (`test_soll136_execution_location.py:122`,
`:128`, `:140`, `:145`). It does not scan raw backend `git -C`, `show-ref`, or
GitPython forms. A fresh grep found a live unassigned backend `git -C` caller in
the governance secret scan (`src/agentkit/backend/governance/guard_system/secret_scan.py:43`,
`:52`, `:80`, `:82`, `:83`). That file is not in the AG3-147/AG3-152 inventory
and would not fail the contract test.

Other grep results checked: closure `remove_worktree` remains AG3-152
(`src/agentkit/backend/closure/multi_repo_saga.py:76`, `:91`, `:94`, `:324`,
`:335`); verify evidence git reads are AG3-147/AG3-152
(`src/agentkit/backend/bootstrap/composition_root.py:1223`, `:1344`, `:1448`;
`src/agentkit/backend/verify_system/evidence/request_resolver.py:196`, `:210`;
`src/agentkit/backend/verify_system/qa_cycle/fingerprint.py:229`;
`src/agentkit/backend/verify_system/sonarqube_gate/runtime_wiring.py:297`,
`:300`); provider-neutral `git ls-remote` is AG3-146 and not a local worktree
git operation (`src/agentkit/backend/code_backend/git_protocol.py:49`, `:52`,
`:80`, `:81`). The remaining `branch_exists` hits are Sonar branch-analysis
checks, not git branch probes (`src/agentkit/backend/installer/integration_checkpoints/branch_plugin_self_test.py:88`,
`:154`; `scanner_harness.py:79`; `jenkins_selftest_harness.py:100`).

Findings

MAJOR: AC11 proof is not exhaustive and misses an unassigned backend `git -C`
call-site.

Failure scenario: a new or existing backend-local git command outside the
AG3-147/AG3-152 inventory can survive because the contract does not scan raw
`git -C` execution forms. This is not hypothetical: `secret_scan.py` shells out
to `["git", "-C", str(repo_root), *args]` (`secret_scan.py:80`, `:82`, `:83`) and
is not assigned in the story inventory. The contract would still pass because it
only checks `utils.git` importers and `remove_worktree` string hits
(`test_soll136_execution_location.py:122`, `:140`).

MAJOR: Non-teardown edge-command commissioning still has a load-then-strict-insert
race.

Failure scenario: two setup entries concurrently commission the same
`preflight_probe` or `provision_worktree` command. `_commission_and_load` first
loads the deterministic command id and then calls strict `insert_command`
(`edge_provisioning_adapter.py:290`, `:296`, `:298`). One caller can win and the
other can raise a duplicate-key error instead of returning a clean idempotent
no-op. The teardown path is fixed, but the broader edge-command insert surface is
not race-proof.

MINOR: ARCH-55 remains violated by added German wording.

The D+E delta adds `"Ausführungsort-Inventar"` in a test docstring/comment
(`tests/contract/backend/test_soll136_execution_location.py:13`, `:39`).

Internal-Cut Integrity

Teardown has one operational truth for setup/reset: these paths commission
`teardown_worktree` and do not call backend `remove_worktree`. The remaining
backend `remove_worktree` path is closure-owned AG3-152
(`src/agentkit/backend/closure/multi_repo_saga.py:91`, `:94`, `:335`). K5 is met
for command paths because edge-command facade methods call the Postgres-only
backend guard before store access (`src/agentkit/backend/state_backend/store/facade.py:1067`,
`:1072`, `:1079`, `:1090`).

VERDICT: REJECT
