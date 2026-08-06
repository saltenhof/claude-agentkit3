---
id: formal.principal-capabilities.entities
title: Principal Capability Entities
status: active
doc_kind: spec
context: principal-capabilities
spec_kind: entity-set
version: 1
prose_refs:
  - concept/technical-design/55_principal_capability_model_story_scope_enforcement.md
  - concept/technical-design/31_branch_guard_orchestrator_guard_artefaktschutz.md
---

# Principal Capability Entities

Die Capability-Schicht arbeitet auf expliziten Principal- und
Scope-Objekten statt auf freien Prompt-Labels.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.principal-capabilities.entities
schema_version: 1
kind: entity-set
context: principal-capabilities
entities:
  - id: principal-capabilities.entity.principal-profile
    identity: principal_type
    attributes:
      - principal_type
      - capability_profile
      - path_classes
      - operation_classes
      - attestation_source
  - id: principal-capabilities.entity.story-scope-binding
    identity: project_key + story_id + run_id
    attributes:
      - participating_repo_roots
      - allowed_story_roots
      - sandbox_roots
      - content_plane_roots
      - governance_roots
  - id: principal-capabilities.entity.capability-freeze
    identity: freeze_id
    attributes:
      - project_key
      - story_id
      - run_id
      - freeze_type
      - freeze_version
      - state
      - activated_by_principal
  - id: principal-capabilities.entity.official-service-path
    identity: command_signature
    attributes:
      - owning_principal
      - requires_service_attestation
      - allowed_path_classes
      - allowed_operation_classes
      - human_authorization_required
  - id: principal-capabilities.entity.capability-decision
    identity: decision_id
    attributes:
      - principal_type
      - path_class
      - operation_class
      - story_scope_ref
      - freeze_ref
      - verdict
```
<!-- FORMAL-SPEC:END -->
