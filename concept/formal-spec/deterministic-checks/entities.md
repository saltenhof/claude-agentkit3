---
id: formal.deterministic-checks.entities
title: Deterministic Checks Entities
status: active
doc_kind: spec
context: deterministic-checks
spec_kind: entity-set
version: 1
prose_refs:
  - concept/technical-design/33_deterministische_checks_stage_registry_policy_engine.md
  - concept/technical-design/27_verify_pipeline_closure_orchestration.md
  - concept/technical-design/40_are_integration_anforderungsvollstaendigkeit.md
---

# Deterministic Checks Entities

Dieser Kontext benoetigt wenige, aber stabile Kernentitaeten.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.deterministic-checks.entities
schema_version: 1
kind: entity-set
context: deterministic-checks
entities:
  - id: deterministic-checks.entity.stage-definition
    identity_key: stage_id
    attributes:
      - stage_id
      - layer
      - kind
      - applies_to
      - blocking
      - producer
      - execution_policy
      - override_policy
  - id: deterministic-checks.entity.stage-execution-plan
    identity_key: gate_id
    attributes:
      - gate_id
      - flow_id
      - invocations
  - id: deterministic-checks.entity.policy-decision
    identity_key: qa_cycle_id
    attributes:
      - qa_cycle_id
      - story_id
      - outcome
      - blocking_stage_ids
      - stage_results
```
<!-- FORMAL-SPEC:END -->
