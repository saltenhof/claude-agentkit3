---
id: formal.operating-modes.state-machine
title: Operating Mode State Machine
status: active
doc_kind: spec
context: operating-modes
spec_kind: state-machine
version: 1
prose_refs:
  - concept/technical-design/56_ai_augmented_mode_and_story_execution_separation.md
---

# Operating Mode State Machine

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.operating-modes.state-machine
schema_version: 1
kind: state-machine
context: operating-modes
states:
  - id: operating-modes.status.unresolved
    initial: true
  - id: operating-modes.status.ai_augmented
  - id: operating-modes.status.story_execution
  - id: operating-modes.status.binding_invalid
  - id: operating-modes.status.resolved_ai_augmented
    terminal: true
  - id: operating-modes.status.resolved_story_execution
    terminal: true
  - id: operating-modes.status.resolved_binding_invalid
    terminal: true
transitions:
  - id: operating-modes.transition.unresolved_to_ai_augmented
    from: operating-modes.status.unresolved
    to: operating-modes.status.ai_augmented
  - id: operating-modes.transition.unresolved_to_story_execution
    from: operating-modes.status.unresolved
    to: operating-modes.status.story_execution
  - id: operating-modes.transition.unresolved_to_binding_invalid
    from: operating-modes.status.unresolved
    to: operating-modes.status.binding_invalid
  - id: operating-modes.transition.ai_augmented_to_story_execution
    from: operating-modes.status.ai_augmented
    to: operating-modes.status.story_execution
  - id: operating-modes.transition.story_execution_to_ai_augmented
    from: operating-modes.status.story_execution
    to: operating-modes.status.ai_augmented
  - id: operating-modes.transition.story_execution_to_binding_invalid
    from: operating-modes.status.story_execution
    to: operating-modes.status.binding_invalid
  - id: operating-modes.transition.binding_invalid_to_ai_augmented
    from: operating-modes.status.binding_invalid
    to: operating-modes.status.ai_augmented
  - id: operating-modes.transition.ai_augmented_to_resolved_ai_augmented
    from: operating-modes.status.ai_augmented
    to: operating-modes.status.resolved_ai_augmented
  - id: operating-modes.transition.story_execution_to_resolved_story_execution
    from: operating-modes.status.story_execution
    to: operating-modes.status.resolved_story_execution
  - id: operating-modes.transition.binding_invalid_to_resolved_binding_invalid
    from: operating-modes.status.binding_invalid
    to: operating-modes.status.resolved_binding_invalid
```
<!-- FORMAL-SPEC:END -->
