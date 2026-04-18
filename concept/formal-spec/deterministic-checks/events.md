---
id: formal.deterministic-checks.events
title: Deterministic Checks Events
status: active
doc_kind: spec
context: deterministic-checks
spec_kind: event-set
version: 1
prose_refs:
  - concept/technical-design/33_deterministische_checks_stage_registry_policy_engine.md
  - concept/technical-design/91_api_event_katalog.md
---

# Deterministic Checks Events

Diese Events bilden Registry-Planung und Policy-Entscheidung fachlich
ab.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.deterministic-checks.events
schema_version: 1
kind: event-set
context: deterministic-checks
events:
  - id: deterministic-checks.event.stage-plan.materialized
    producer: stage-registry
    role: lifecycle
    payload:
      required:
        - gate_id
        - flow_id
        - stage_ids
  - id: deterministic-checks.event.stage.executed
    producer: deterministic-checks
    role: lifecycle
    payload:
      required:
        - qa_cycle_id
        - stage_id
  - id: deterministic-checks.event.stage.failed
    producer: deterministic-checks
    role: lifecycle
    payload:
      required:
        - qa_cycle_id
        - stage_id
        - failure_reason
  - id: deterministic-checks.event.policy.evaluated
    producer: policy-engine
    role: lifecycle
    payload:
      required:
        - qa_cycle_id
        - outcome
        - blocking_stage_ids
```
<!-- FORMAL-SPEC:END -->
