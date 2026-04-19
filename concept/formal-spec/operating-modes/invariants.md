---
id: formal.operating-modes.invariants
title: Operating Mode Invariants
status: active
doc_kind: spec
context: operating-modes
spec_kind: invariant-set
version: 1
prose_refs:
  - concept/technical-design/56_ai_augmented_mode_and_story_execution_separation.md
  - concept/technical-design/30_hook_adapter_guard_enforcement.md
  - concept/technical-design/35_integrity_gate_governance_beobachtung_eskalation.md
---

# Operating Mode Invariants

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.operating-modes.invariants
schema_version: 1
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
  - id: operating-modes.invariant.story_execution_requires_lock_binding_and_worktree_match
    scope: governance
    rule: story_execution may only activate when a valid run binding a valid story_execution lock and a matching worktree root are all present
  - id: operating-modes.invariant.invalid_bound_session_must_not_fall_back_to_free_mode
    scope: governance
    rule: if a session is already bound to a story run and lock or worktree consistency is lost the session enters binding_invalid instead of silently degrading to ai_augmented
```
<!-- FORMAL-SPEC:END -->
