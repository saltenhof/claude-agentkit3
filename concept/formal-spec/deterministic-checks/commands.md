---
id: formal.deterministic-checks.commands
title: Deterministic Checks Commands
status: active
doc_kind: spec
context: deterministic-checks
spec_kind: command-set
version: 1
prose_refs:
  - concept/technical-design/33_deterministische_checks_stage_registry_policy_engine.md
  - concept/technical-design/27_verify_pipeline_closure_orchestration.md
  - concept/technical-design/91_api_event_katalog.md
---

# Deterministic Checks Commands

Registry und Policy werden nur ueber den offiziellen Verify-Pfad
materialisiert und ausgewertet.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.deterministic-checks.commands
schema_version: 1
kind: command-set
context: deterministic-checks
commands:
  - id: deterministic-checks.command.materialize-stage-plan
    signature: internal materialize_stage_plan <story_type> <gate_id>
    allowed_statuses:
      - deterministic-checks.status.requested
    requires:
      - deterministic-checks.invariant.stage-plan-derived-from-registry
    emits:
      - deterministic-checks.event.stage-plan.materialized
  - id: deterministic-checks.command.execute-deterministic-stages
    signature: internal execute_deterministic_stages <gate_id>
    allowed_statuses:
      - deterministic-checks.status.plan_materialized
    requires:
      - deterministic-checks.invariant.only-applicable-stages-execute
    emits:
      - deterministic-checks.event.stage.executed
      - deterministic-checks.event.stage.failed
  - id: deterministic-checks.command.evaluate-policy
    signature: agentkit policy
    allowed_statuses:
      - deterministic-checks.status.stages_executed
    requires:
      - deterministic-checks.invariant.blocking-stage-failure-prevents-pass
    emits:
      - deterministic-checks.event.policy.evaluated
```
<!-- FORMAL-SPEC:END -->
