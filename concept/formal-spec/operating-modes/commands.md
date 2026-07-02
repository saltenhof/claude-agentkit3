---
id: formal.operating-modes.commands
title: Operating Mode Commands
status: active
doc_kind: spec
context: operating-modes
spec_kind: command-set
version: 3
prose_refs:
  - concept/technical-design/56_ai_augmented_mode_and_story_execution_separation.md
  - concept/technical-design/91_api_event_katalog.md
---

# Operating Mode Commands

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.operating-modes.commands
schema_version: 3
kind: command-set
context: operating-modes
commands:
  - id: operating-modes.command.resolve-operating-mode
    signature: internal resolve session mode from local edge bundle session binding story lock and worktree
    allowed_statuses:
      - operating-modes.status.unresolved
      - operating-modes.status.ai_augmented
      - operating-modes.status.story_execution
      - operating-modes.status.binding_invalid
    emits:
      - operating-modes.event.operating_mode_resolved
  - id: operating-modes.command.materialize-local-edge-bundle
    signature: internal publish locally readable operating mode bundle after a committed central state transition including required auxiliary lock signals for local guard decisions
    allowed_statuses:
      - operating-modes.status.ai_augmented
      - operating-modes.status.story_execution
      - operating-modes.status.binding_invalid
    emits:
      - operating-modes.event.local_edge_bundle_materialized
  - id: operating-modes.command.bind-session-to-run
    signature: internal bind current session to explicit story run
    allowed_statuses:
      - operating-modes.status.ai_augmented
      - operating-modes.status.unresolved
    emits:
      - operating-modes.event.session_run_binding_created
  - id: operating-modes.command.unbind-session-from-run
    signature: internal remove active session binding after closure cleanup reset or split
    allowed_statuses:
      - operating-modes.status.story_execution
      - operating-modes.status.binding_invalid
    emits:
      - operating-modes.event.session_run_binding_removed
      - operating-modes.event.story_execution_regime_deactivated
  - id: operating-modes.command.activate-story-execution-regime
    signature: internal activate story execution after valid binding lock and worktree verification
    allowed_statuses:
      - operating-modes.status.ai_augmented
      - operating-modes.status.unresolved
    requires:
      - operating-modes.invariant.story_execution_requires_lock_binding_and_worktree_match
    emits:
      - operating-modes.event.story_execution_regime_activated
  - id: operating-modes.command.reconcile-edge-operation
    signature: internal reconcile uncertain mutation result by op_id before further local materialization
    allowed_statuses:
      - operating-modes.status.ai_augmented
      - operating-modes.status.story_execution
      - operating-modes.status.binding_invalid
    emits:
      - operating-modes.event.edge_operation_reconciled
  - id: operating-modes.command.request-run-ownership-takeover
    signature: internal request explicit run ownership takeover for a story in active story execution returning a versioned challenge or for agent initiated requests a pending human frontend approval
    allowed_statuses:
      - operating-modes.status.ai_augmented
      - operating-modes.status.unresolved
    emits:
      - operating-modes.event.run_ownership_takeover_offered
      - operating-modes.event.run_ownership_takeover_approval_requested
  - id: operating-modes.command.confirm-run-ownership-takeover
    signature: internal confirm run ownership takeover by compare and swap on ownership_epoch and binding_version transferring the run binding with unchanged run_id to the requesting session materializing the takeover transfer record with the pushed takeover_base_sha per participating repo rebinding worktree_roots to the edge reported roots of the new session and disowning the previous owner
    allowed_statuses:
      - operating-modes.status.ai_augmented
      - operating-modes.status.unresolved
    requires:
      - operating-modes.invariant.at_most_one_active_ownership_per_story
      - operating-modes.invariant.ownership_transfer_requires_explicit_confirmed_request
      - operating-modes.invariant.agent_initiated_takeover_requires_human_frontend_approval
      - operating-modes.invariant.takeover_confirm_fences_in_flight_mutations
      - operating-modes.invariant.disowned_session_cannot_immediately_reclaim
      - operating-modes.invariant.freeze_states_are_admission_blockers_and_invalidate_challenges
    emits:
      - operating-modes.event.session_run_binding_transferred
      - operating-modes.event.session_disowned
```
<!-- FORMAL-SPEC:END -->
