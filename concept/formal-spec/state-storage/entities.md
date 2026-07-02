---
id: formal.state-storage.entities
title: State Storage Entities
status: active
doc_kind: spec
context: state-storage
spec_kind: entity-set
version: 3
prose_refs:
  - concept/technical-design/17_fachliches_datenmodell_ownership.md
  - concept/technical-design/18_relationales_abbildungsmodell_postgres.md
  - concept/technical-design/15_security_secrets_identity_zugriffsmodell.md
  - concept/technical-design/10_runtime_deployment_speicher.md
---

# State Storage Entities

Der Storage-Kontext modelliert keine SQL-Tabellen als Primaerobjekte,
sondern fachliche Record-Families.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.state-storage.entities
schema_version: 3
kind: entity-set
context: state-storage
entities:
  - id: state-storage.entity.record-family
    identity_key: family_id
    attributes:
      - family_id
      - scope_key
      - canonicality
      - owner_context
      - writer_mode
      - reset_policy
      - blocking_class
      - source_of_truth_for
      - derived_from
  - id: state-storage.entity.identity-contract
    identity_key: identity_id
    attributes:
      - identity_id
      - entity_name
      - scope_components
      - natural_key
      - canonical_family_id
  - id: state-storage.entity.storage-operation
    identity_key: operation_id
    attributes:
      - operation_id
      - project_key
      - story_id
      - target_family_id
      - operation_kind
      - initiated_by
      - resulting_status
  - id: state-storage.entity.storage-dependency
    identity_key: dependency_id
    attributes:
      - dependency_id
      - source_family_id
      - target_family_id
      - dependency_kind
      - reset_follow_up
  - id: state-storage.entity.inflight-operation-record
    identity_key: op_id
    attributes:
      - op_id
      - status
      - operation_epoch
      - backend_instance_id
      - instance_incarnation
      - declared_serialization_scope
      - claimed_at
      - finalized_at
  - id: state-storage.entity.object-mutation-claim
    identity_key: project_key + serialization_scope + scope_key
    attributes:
      - project_key
      - serialization_scope
      - scope_key
      - op_id
      - backend_instance_id
      - instance_incarnation
      - acquired_at
      - queue_position
  - id: state-storage.entity.takeover-worktree-snapshot
    identity_key: project_key + story_id + run_id + ownership_epoch
    attributes:
      - project_key
      - story_id
      - run_id
      - ownership_epoch
      - repo_id
      - worktree_path
      - head_sha
      - index_status
      - binary_diff_ref
      - untracked_manifest_ref
```
<!-- FORMAL-SPEC:END -->
