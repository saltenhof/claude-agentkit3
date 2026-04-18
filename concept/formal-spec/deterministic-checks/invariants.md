---
id: formal.deterministic-checks.invariants
title: Deterministic Checks Invariants
status: active
doc_kind: spec
context: deterministic-checks
spec_kind: invariant-set
version: 1
prose_refs:
  - concept/technical-design/33_deterministische_checks_stage_registry_policy_engine.md
  - concept/technical-design/40_are_integration_anforderungsvollstaendigkeit.md
  - concept/technical-design/41_failure_corpus_pattern_promotion_check_factory.md
---

# Deterministic Checks Invariants

Diese Invarianten definieren den zulaessigen Registry- und
Policy-Prozess.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.deterministic-checks.invariants
schema_version: 1
kind: invariant-set
context: deterministic-checks
invariants:
  - id: deterministic-checks.invariant.stage-plan-derived-from-registry
    scope: process
    rule: stage execution order and applicability must come from the StageRegistry plan, not from ad hoc branching in verify code
  - id: deterministic-checks.invariant.only-applicable-stages-execute
    scope: process
    rule: only stages whose applies_to set contains the current story type may be executed for a given verify gate
  - id: deterministic-checks.invariant.blocking-stage-failure-prevents-pass
    scope: outcome
    rule: a failed blocking stage prevents a PASS outcome from the policy engine
  - id: deterministic-checks.invariant.are-gate-required-only-when-enabled
    scope: process
    rule: the ARE gate stage is mandatory only when the ARE feature is enabled for the project
  - id: deterministic-checks.invariant.failure-corpus-promotions-go-through-registry
    scope: governance
    rule: promoted checks from the Failure Corpus become active only through StageRegistry extension and not through direct verify hardcoding
```
<!-- FORMAL-SPEC:END -->
