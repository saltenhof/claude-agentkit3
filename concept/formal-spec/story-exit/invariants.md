---
id: formal.story-exit.invariants
title: Story Exit Invariants
status: active
doc_kind: spec
context: story-exit
spec_kind: invariant-set
version: 1
prose_refs:
  - concept/technical-design/58_story_exit_human_takeover_handoff.md
  - concept/technical-design/56_ai_augmented_mode_and_story_execution_separation.md
  - concept/technical-design/55_principal_capability_model_story_scope_enforcement.md
---

# Story Exit Invariants

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.story-exit.invariants
schema_version: 1
kind: invariant-set
context: story-exit
invariants:
  - id: story-exit.invariant.exit_requires_human_cli
    scope: governance
    rule: story exit may only be initiated by human_cli and never by orchestrator self-decision
  - id: story-exit.invariant.exit_requires_minimal_artifacts
    scope: governance
    rule: a story exit requires a system-prepared viability dossier exit record and exit manifest snapshot but does not require extensive human-authored documentation
  - id: story-exit.invariant.exit_must_revoke_story_binding_before_free_mode
    scope: governance
    rule: a session may not return to ai_augmented until story lock run binding and local story-regime exports have been revoked or invalidated
  - id: story-exit.invariant.exit_must_not_replace_split_or_normal_replan_without_reason
    scope: governance
    rule: story exit is only valid for approved human-takeover reasons and must not silently replace normal split reset or replan paths
  - id: story-exit.invariant.story_becomes_cancelled_not_done
    scope: governance
    rule: a successful story exit ends the story administratively as cancelled with viability handoff semantics and never as done
```
<!-- FORMAL-SPEC:END -->
