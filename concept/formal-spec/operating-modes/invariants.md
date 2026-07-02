---
id: formal.operating-modes.invariants
title: Operating Mode Invariants
status: active
doc_kind: spec
context: operating-modes
spec_kind: invariant-set
version: 3
prose_refs:
  - concept/technical-design/56_ai_augmented_mode_and_story_execution_separation.md
  - concept/technical-design/30_hook_adapter_guard_enforcement.md
  - concept/technical-design/35_integrity_gate_governance_beobachtung_eskalation.md
---

# Operating Mode Invariants

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.operating-modes.invariants
schema_version: 3
kind: invariant-set
context: operating-modes
invariants:
  - id: operating-modes.invariant.no_story_governance_without_explicit_run_binding
    scope: governance
    rule: no story scoped guard or integrity obligation may activate without an explicit session run binding plus valid story_execution lock
  - id: operating-modes.invariant.interactive_agent_is_not_orchestrator
    scope: governance
    rule: the main agent outside an explicit run binding is an interactive_agent and must not inherit orchestrator-only restrictions
  - id: operating-modes.invariant.ai_augmented_has_no_workflow_obligations
    scope: governance
    rule: in ai_augmented mode there are no verify closure integrity or story telemetry obligations
  - id: operating-modes.invariant.baseline_guards_apply_in_all_modes
    scope: governance
    rule: destructive git protections self protection secrets protection and ccag remain active in all operating modes
  - id: operating-modes.invariant.story_mode_fast_disables_story_scoped_guards_only
    scope: governance
    rule: story mode fast disables only the story scoped guards and story lock records while the baseline guards destructive git protections self protection secrets protection and ccag stay active
  - id: operating-modes.invariant.story_execution_requires_lock_binding_and_worktree_match
    scope: governance
    rule: story_execution may only activate when a valid run binding a valid story_execution lock and a matching worktree root are all present
  - id: operating-modes.invariant.invalid_bound_session_must_not_fall_back_to_free_mode
    scope: governance
    rule: if a session is already bound to a story run and lock or worktree consistency is lost the session enters binding_invalid instead of silently degrading to ai_augmented
  - id: operating-modes.invariant.local_edge_bundle_is_derived_not_authoritative
    scope: governance
    rule: local edge bundles are derived projections for hook decisions and must never replace the central session binding or central story lock as canonical truth
  - id: operating-modes.invariant.hooks_read_only_current_pointer_to_complete_bundle
    scope: governance
    rule: hook mode resolution reads only the current bundle pointer and the referenced complete bundle and must not derive operating mode from individual marker files or partial exports
  - id: operating-modes.invariant.story_mutations_require_fresh_or_resynced_bundle
    scope: governance
    rule: story scoped mutating allow decisions require a fresh or successfully resynchronized local edge bundle and must fail closed on stale or inconsistent local materialization
  - id: operating-modes.invariant.story_scoped_guard_decisions_require_explicit_local_lock_signals
    scope: governance
    rule: story scoped guard decisions that depend on auxiliary locks such as qa_artifact_write must read those signals from the complete local edge bundle and must fail closed when the required local lock materialization is missing
  - id: operating-modes.invariant.uncertain_remote_mutation_must_be_reconciled_by_op_id
    scope: governance
    rule: if the remote result of a mutating operation is unknown the local system must reconcile the operation by op_id before further local materialization or free-mode fallback
  - id: operating-modes.invariant.at_most_one_active_ownership_per_story
    scope: governance
    rule: at most one run ownership record per project_key and story_id may hold status active and this uniqueness must be enforced by the persistence layer
  - id: operating-modes.invariant.historical_ownership_records_are_never_admission_evidence
    scope: governance
    rule: run ownership records with a status other than active are audit history and must never be accepted as admission evidence for story execution mutations
  - id: operating-modes.invariant.story_execution_mutations_require_current_ownership_epoch
    scope: governance
    rule: every mutating story execution path including complete_phase fail_phase closure and the server side executor paths must fence against the owner_session_id and ownership_epoch of the currently active run ownership record
  - id: operating-modes.invariant.ownership_transfer_requires_explicit_confirmed_request
    scope: governance
    rule: run ownership changes owner only through an explicit reasoned challenge confirm takeover an official end path or recovery and never through timeout lease expiry heartbeat loss or any other automatic inference from client silence
  - id: operating-modes.invariant.agent_initiated_takeover_requires_human_frontend_approval
    scope: governance
    rule: an agent initiated takeover request must not execute before a human approves it in the frontend and the requesting agent receives pending_human_approval and observes the outcome by op_id while the approval which may lapse like any open permission request is outstanding
  - id: operating-modes.invariant.takeover_confirm_fences_in_flight_mutations
    scope: governance
    rule: takeover confirm is serialized behind in flight mutations of the same story and is a compare and swap on ownership_epoch and binding_version so any interim ownership change exit reset split or closure invalidates open challenges
  - id: operating-modes.invariant.disowned_session_cannot_immediately_reclaim
    scope: governance
    rule: a session disowned by takeover cannot immediately reconfirm ownership and a repeated transfer of the same story shortly afterwards requires a privileged principal and an explicit reason
  - id: operating-modes.invariant.freeze_states_are_admission_blockers_and_invalidate_challenges
    scope: governance
    rule: story scoped freeze states carry freeze_epoch and freeze_reason block mutating admissions in addition to the active ownership record invalidate open takeover challenges on entry and make takeover confirm fail while the story is not takeover admissible
```
<!-- FORMAL-SPEC:END -->
