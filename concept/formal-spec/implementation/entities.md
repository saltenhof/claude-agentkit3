---
id: formal.implementation.entities
title: Implementation Entities
status: active
doc_kind: spec
context: implementation
spec_kind: entity-set
version: 1
prose_refs:
  - concept/technical-design/20_workflow_engine_state_machine.md
  - concept/domain-design/02-pipeline-orchestrierung.md
  - concept/technical-design/27_verify_pipeline_closure_orchestration.md
---

# Implementation Entities

Die Implementation benoetigt wenige fachlich stabile Kernentitaeten.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.implementation.entities
schema_version: 1
kind: entity-set
context: implementation
entities:
  - id: implementation.entity.attempt
    identity_key: run_id
    attributes:
      - run_id
      - story_id
      - project_key
      - mode
      - status
  - id: implementation.entity.worker-manifest
    identity_key: run_id
    attributes:
      - run_id
      - story_id
      - worker_status
      - claims
      - blocker_reason
  - id: implementation.entity.handover
    identity_key: run_id
    attributes:
      - run_id
      - story_id
      - risks_for_qa
      - drift_log
      - output_refs
```
<!-- FORMAL-SPEC:END -->
