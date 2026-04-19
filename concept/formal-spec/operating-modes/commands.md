---
id: formal.operating-modes.commands
title: Operating Mode Commands
status: active
doc_kind: spec
context: operating-modes
spec_kind: command-set
version: 1
prose_refs:
  - concept/technical-design/56_ai_augmented_mode_and_story_execution_separation.md
  - concept/technical-design/91_api_event_katalog.md
---

# Operating Mode Commands

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.operating-modes.commands
schema_version: 1
kind: command-set
context: operating-modes
commands:
  - id: operating-modes.command.resolve-operating-mode
    signature: internal resolve session mode from run binding story lock and worktree
    allowed_statuses:
      - operating-modes.status.unresolved
      - operating-modes.status.ai_augmented
      - operating-modes.status.story_execution
      - operating-modes.status.binding_invalid
    emits:
      - operating-modes.event.operating_mode_resolved
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
```
<!-- FORMAL-SPEC:END -->
