---
id: formal.guard-system.commands
title: Guard System Commands
status: active
doc_kind: spec
context: guard-system
spec_kind: command-set
version: 1
prose_refs:
  - concept/technical-design/30_hook_adapter_guard_enforcement.md
  - concept/technical-design/31_branch_guard_orchestrator_guard_artefaktschutz.md
  - concept/technical-design/91_api_event_katalog.md
---

# Guard System Commands

Das GuardSystem bewertet Tool-Aufrufe, es fuehrt sie nicht selbst aus.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.guard-system.commands
schema_version: 1
kind: command-set
context: guard-system
commands:
  - id: guard-system.command.evaluate-hook-invocation
    signature: internal evaluate PreToolUse or PostToolUse payload
    allowed_statuses:
      - guard-system.status.received
    requires:
      - guard-system.invariant.fail_closed_for_unknown_or_crashing_hooks
    emits:
      - guard-system.event.guard.allowed
      - guard-system.event.guard.blocked
  - id: guard-system.command.official-closure-push
    signature: agentkit run-phase closure ... internal story-branch push
    allowed_statuses:
      - guard-system.status.received
    requires:
      - guard-system.invariant.branch-guard-allows-official-closure-path
    emits:
      - guard-system.event.guard.allowed
  - id: guard-system.command.illegal-manual-history-rewrite
    signature: manual git rebase/reset/force-push on active story scope
    allowed_statuses:
      - guard-system.status.received
    requires:
      - guard-system.invariant.manual-history-rewrite-blocked
    emits:
      - guard-system.event.guard.blocked
```
<!-- FORMAL-SPEC:END -->
