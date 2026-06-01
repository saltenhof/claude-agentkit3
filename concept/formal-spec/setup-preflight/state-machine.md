---
id: formal.setup-preflight.state-machine
title: Setup Preflight State Machine
status: active
doc_kind: spec
context: setup-preflight
spec_kind: state-machine
version: 1
prose_refs:
  - concept/technical-design/22_setup_preflight_worktree_guard_activation.md
  - concept/technical-design/45_phase_runner_cli.md
  - concept/domain-design/02-pipeline-orchestrierung.md
---

# Setup Preflight State Machine

Setup ist ein deterministischer Startfaehigkeitsprozess.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.setup-preflight.state-machine
schema_version: 1
kind: state-machine
context: setup-preflight
states:
  - id: setup-preflight.status.requested
    initial: true
  - id: setup-preflight.status.preflight_running
  - id: setup-preflight.status.context_materialized
  - id: setup-preflight.status.worktrees_ready
  - id: setup-preflight.status.guards_active
  - id: setup-preflight.status.mode_routed
  - id: setup-preflight.status.completed
    terminal: true
  - id: setup-preflight.status.failed
    terminal: true
transitions:
  - id: setup-preflight.transition.requested_to_preflight_running
    from: setup-preflight.status.requested
    to: setup-preflight.status.preflight_running
  - id: setup-preflight.transition.preflight_running_to_context_materialized
    from: setup-preflight.status.preflight_running
    to: setup-preflight.status.context_materialized
    guard: setup-preflight.invariant.all_ten_checks_pass_before_context
  # Main-green precondition (FK-22 §22.4c): only a GREEN sonarqube_gate
  # main attestation (read by analysisId, revision-matched) advances code
  # stories to worktree creation. RED/STALE and unreachable each have their
  # own fail-closed edge with a distinct failure invariant — the positive
  # green invariant is no longer (ab)used as a failure guard.
  - id: setup-preflight.transition.context_materialized_to_worktrees_ready
    from: setup-preflight.status.context_materialized
    to: setup-preflight.status.worktrees_ready
    guard: setup-preflight.invariant.code_stories_require_green_main_attestation
  - id: setup-preflight.transition.context_materialized_to_failed_on_red_or_stale_main
    from: setup-preflight.status.context_materialized
    to: setup-preflight.status.failed
    guard: setup-preflight.invariant.main_green_refusal_emits_active_cleanup_proposal
  - id: setup-preflight.transition.context_materialized_to_failed_on_unreachable_main
    from: setup-preflight.status.context_materialized
    to: setup-preflight.status.failed
    guard: setup-preflight.invariant.main_green_unreachable_fails_closed
  - id: setup-preflight.transition.worktrees_ready_to_guards_active
    from: setup-preflight.status.worktrees_ready
    to: setup-preflight.status.guards_active
  - id: setup-preflight.transition.guards_active_to_mode_routed
    from: setup-preflight.status.guards_active
    to: setup-preflight.status.mode_routed
  - id: setup-preflight.transition.mode_routed_to_completed
    from: setup-preflight.status.mode_routed
    to: setup-preflight.status.completed
  - id: setup-preflight.transition.preflight_running_to_failed
    from: setup-preflight.status.preflight_running
    to: setup-preflight.status.failed
    guard: setup-preflight.invariant.fail_closed_on_any_preflight_failure
compound_rules:
  - id: setup-preflight.rule.concept-research-shortcut
    description: Concept and research stories complete setup without worktree creation and without mode routing for execution or exploration.
  - id: setup-preflight.rule.main-green-precondition-gates-worktree-creation
    description: For implementation and bugfix stories the main-green precondition (FK-22 22.4c) is checked between context_materialized and worktree creation; only a GREEN sonarqube_gate main attestation read by analysisId plus revision-match advances to worktrees_ready, while RED, STALE, or unreachable refuses setup fail-closed and transitions to failed with an active blame-free out-of-story cleanup-worker proposal.
```
<!-- FORMAL-SPEC:END -->
