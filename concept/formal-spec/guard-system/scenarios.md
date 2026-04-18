---
id: formal.guard-system.scenarios
title: Guard System Scenarios
status: active
doc_kind: spec
context: guard-system
spec_kind: scenario-set
version: 1
prose_refs:
  - concept/technical-design/30_hook_adapter_guard_enforcement.md
  - concept/technical-design/31_branch_guard_orchestrator_guard_artefaktschutz.md
---

# Guard System Scenarios

Diese Traces pruefen die haeufigsten Allow-/Deny-Faelle.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.guard-system.scenarios
schema_version: 1
kind: scenario-set
context: guard-system
scenarios:
  - id: guard-system.scenario.official-closure-allowed
    start:
      status: guard-system.status.received
    trace:
      - command: guard-system.command.official-closure-push
    expected_end:
      status: guard-system.status.allowed
    requires:
      - guard-system.invariant.branch-guard-allows-official-closure-path
  - id: guard-system.scenario.manual-rewrite-blocked
    start:
      status: guard-system.status.received
    trace:
      - command: guard-system.command.illegal-manual-history-rewrite
    expected_end:
      status: guard-system.status.blocked
    requires:
      - guard-system.invariant.manual-history-rewrite-blocked
  - id: guard-system.scenario.hook-crash-blocks
    start:
      status: guard-system.status.received
    trace:
      - command: guard-system.command.evaluate-hook-invocation
    expected_end:
      status: guard-system.status.blocked
    requires:
      - guard-system.invariant.fail_closed_for_unknown_or_crashing_hooks
```
<!-- FORMAL-SPEC:END -->
