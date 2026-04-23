---
id: formal.execution-planning.entities
title: Execution Planning Entities
status: active
doc_kind: spec
context: execution-planning
spec_kind: entity-set
version: 1
prose_refs:
  - concept/technical-design/66_story_planung_abhaengigkeiten_ausfuehrungsplanung.md
---

# Execution Planning Entities

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.execution-planning.entities
schema_version: 1
kind: entity-set
context: execution-planning
entities:
  - id: execution-planning.entity.planned-story
    identity_key: story_id
    attributes:
      - project_key
      - story_id
      - story_type
      - story_size
      - primary_repo
      - participating_repos
      - planning_status
  - id: execution-planning.entity.dependency-edge
    identity_key: edge_id
    attributes:
      - project_key
      - predecessor_story_id
      - successor_story_id
      - dependency_kind
      - strictness
      - rationale
  - id: execution-planning.entity.blocking-condition
    identity_key: blocker_id
    attributes:
      - project_key
      - story_id
      - blocking_kind
      - source_kind
      - human_gate_required
      - external_reference
      - active
  - id: execution-planning.entity.parallelism-budget
    identity_key: budget_id
    attributes:
      - project_key
      - budget_scope(project|tenant)
      - repo_parallel_cap
      - merge_risk_cap
      - api_rate_limit_cap
      - llm_pool_cap
      - ci_capacity_cap
      - human_gate_cap
      - global_orchestrator_cap
  - id: execution-planning.entity.execution-wave
    identity_key: wave_id
    attributes:
      - project_key
      - plan_id
      - wave_order
      - wave_state(planned|active|completed|collapsed)
      - candidate_story_ids
      - repo_mix
      - critical_path_overlap
  - id: execution-planning.entity.execution-plan
    identity_key: plan_id
    attributes:
      - project_key
      - graph_revision
      - readiness_revision
      - scheduling_revision
      - rulebook_revision
      - critical_path_story_ids
      - recommended_batch_story_ids
      - max_allowed_batch_story_ids
```
<!-- FORMAL-SPEC:END -->
