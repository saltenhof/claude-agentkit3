---
id: formal.guard-system.invariants
title: Guard System Invariants
status: active
doc_kind: spec
context: guard-system
spec_kind: invariant-set
version: 1
prose_refs:
  - concept/technical-design/30_hook_adapter_guard_enforcement.md
  - concept/technical-design/31_branch_guard_orchestrator_guard_artefaktschutz.md
  - concept/technical-design/35_integrity_gate_governance_beobachtung_eskalation.md
---

# Guard System Invariants

Diese Invarianten definieren die harte Enforcement-Semantik des
GuardSystems.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.guard-system.invariants
schema_version: 1
kind: invariant-set
context: guard-system
invariants:
  - id: guard-system.invariant.fail_closed_for_unknown_or_crashing_hooks
    scope: governance
    rule: unknown hook outcomes, crashes, or non-declared exits block the tool invocation instead of permitting it implicitly
  - id: guard-system.invariant.only_official_exceptions_may_bypass_default_denial
    scope: governance
    rule: a blocked operation may be allowed only through an explicit official exception path declared by AgentKit concepts
  - id: guard-system.invariant.branch-guard-allows-official-closure-path
    scope: governance
    rule: the branch guard must allow the official closure push and official no_ff fallback path
  - id: guard-system.invariant.manual-history-rewrite-blocked
    scope: governance
    rule: manual rebase, reset and force-push on active story scope remain blocked even when official closure or split paths exist
  - id: guard-system.invariant.story-creation-must-use-official-path
    scope: governance
    rule: direct gh issue creation by agents remains blocked outside the official story-creation or split service path
```
<!-- FORMAL-SPEC:END -->
