---
id: formal.deterministic-checks.state-machine
title: Deterministic Checks State Machine
status: active
doc_kind: spec
context: deterministic-checks
spec_kind: state-machine
version: 1
prose_refs:
  - concept/technical-design/33_deterministische_checks_stage_registry_policy_engine.md
  - concept/technical-design/27_verify_pipeline_closure_orchestration.md
---

# Deterministic Checks State Machine

Stage-Registry und Policy-Engine bilden zusammen einen kleinen Plan-
und Aggregationsprozess.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.deterministic-checks.state-machine
schema_version: 1
kind: state-machine
context: deterministic-checks
states:
  - id: deterministic-checks.status.requested
    initial: true
  - id: deterministic-checks.status.plan_materialized
  - id: deterministic-checks.status.stages_executed
  - id: deterministic-checks.status.policy_evaluated
  - id: deterministic-checks.status.passed
    terminal: true
  - id: deterministic-checks.status.failed
    terminal: true
transitions:
  - id: deterministic-checks.transition.requested_to_plan_materialized
    from: deterministic-checks.status.requested
    to: deterministic-checks.status.plan_materialized
    guard: deterministic-checks.invariant.stage-plan-derived-from-registry
  - id: deterministic-checks.transition.plan_materialized_to_stages_executed
    from: deterministic-checks.status.plan_materialized
    to: deterministic-checks.status.stages_executed
    guard: deterministic-checks.invariant.only-applicable-stages-execute
  - id: deterministic-checks.transition.stages_executed_to_policy_evaluated
    from: deterministic-checks.status.stages_executed
    to: deterministic-checks.status.policy_evaluated
  - id: deterministic-checks.transition.policy_evaluated_to_passed
    from: deterministic-checks.status.policy_evaluated
    to: deterministic-checks.status.passed
    guard: deterministic-checks.invariant.blocking-stage-failure-prevents-pass
  - id: deterministic-checks.transition.policy_evaluated_to_failed
    from: deterministic-checks.status.policy_evaluated
    to: deterministic-checks.status.failed
compound_rules:
  - id: deterministic-checks.rule.failure-corpus-enters-via-registry
    description: Promoted checks from the Failure Corpus become active only through StageRegistry materialization, not by direct hardcoding in Verify.
```
<!-- FORMAL-SPEC:END -->
