---
id: formal.guard-system.state-machine
title: Guard System State Machine
status: active
doc_kind: spec
context: guard-system
spec_kind: state-machine
version: 1
prose_refs:
  - concept/technical-design/30_hook_adapter_guard_enforcement.md
  - concept/technical-design/31_branch_guard_orchestrator_guard_artefaktschutz.md
---

# Guard System State Machine

Ein Guard-Check ist ein kleiner Entscheidungsprozess vor der
Tool-Ausfuehrung.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.guard-system.state-machine
schema_version: 1
kind: state-machine
context: guard-system
states:
  - id: guard-system.status.received
    initial: true
  - id: guard-system.status.evaluated
  - id: guard-system.status.allowed
    terminal: true
  - id: guard-system.status.blocked
    terminal: true
transitions:
  - id: guard-system.transition.received_to_evaluated
    from: guard-system.status.received
    to: guard-system.status.evaluated
  - id: guard-system.transition.evaluated_to_allowed
    from: guard-system.status.evaluated
    to: guard-system.status.allowed
    guard: guard-system.invariant.only_official_exceptions_may_bypass_default_denial
  - id: guard-system.transition.evaluated_to_blocked
    from: guard-system.status.evaluated
    to: guard-system.status.blocked
compound_rules:
  - id: guard-system.rule.hook-crash-is-block
    description: Hook crashes and non-zero unknown exits are treated as blocked under fail-closed semantics.
```
<!-- FORMAL-SPEC:END -->
