---
id: formal.setup-preflight.invariants
title: Setup Preflight Invariants
status: active
doc_kind: spec
context: setup-preflight
spec_kind: invariant-set
version: 1
prose_refs:
  - concept/technical-design/22_setup_preflight_worktree_guard_activation.md
  - concept/technical-design/45_phase_runner_cli.md
  - concept/domain-design/02-pipeline-orchestrierung.md
---

# Setup Preflight Invariants

Diese Invarianten definieren die zulaessige Startfaehigkeit einer Story.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.setup-preflight.invariants
schema_version: 1
kind: invariant-set
context: setup-preflight
invariants:
  - id: setup-preflight.invariant.all_nine_checks_pass_before_context
    scope: process
    rule: story context materialization is legal only after all nine preflight checks have completed and passed
  - id: setup-preflight.invariant.fail_closed_on_any_preflight_failure
    scope: process
    rule: any failed preflight check prevents setup completion and terminates setup with failed status
  - id: setup-preflight.invariant.no_active_runtime_residue_before_start
    scope: process
    rule: active runtime residue, stale worktrees, stale story branches, or overlapping active scope prevent a new setup run
  - id: setup-preflight.invariant.code_stories_require_worktree_setup
    scope: process
    rule: implementation and bugfix stories require participating repo worktrees and branch setup before setup may complete
  - id: setup-preflight.invariant.noncode-stories-skip-worktrees
    scope: process
    rule: concept and research stories complete setup without worktree or code mode routing
```
<!-- FORMAL-SPEC:END -->
