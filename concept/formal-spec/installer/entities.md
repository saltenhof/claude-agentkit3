---
id: formal.installer.entities
title: Installer Entities
status: active
doc_kind: spec
context: installer
spec_kind: entity-set
version: 1
prose_refs:
  - concept/technical-design/50_installer_checkpoint_engine_bootstrap.md
  - concept/technical-design/51_upgrade_migration_customization_preservation.md
  - concept/domain-design/08-installation-und-bootstrap.md
---

# Installer Entities

Der Installer benoetigt nur wenige, aber stabile Kernentitaeten.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.installer.entities
schema_version: 1
kind: entity-set
context: installer
entities:
  - id: installer.entity.project-registration
    identity_key: project_key
    attributes:
      - project_key
      - project_root
      - gh_owner
      - gh_repo
      - runtime_profile
      - registration_status
      - registered_bundle_version
      - config_digest
  - id: installer.entity.bundle-binding
    identity_key: binding_id
    attributes:
      - binding_id
      - project_key
      - bundle_kind
      - bundle_version
      - variant
      - target_path
      - binding_mode
  - id: installer.entity.checkpoint-run
    identity_key: checkpoint_run_id
    attributes:
      - checkpoint_run_id
      - project_key
      - execution_mode
      - current_checkpoint
      - started_at
      - completed_at
      - outcome
  - id: installer.entity.customization-footprint
    identity_key: project_key
    attributes:
      - project_key
      - config_digest
      - customization_detected
      - preserved_keys
      - bundle_override_refs
```
<!-- FORMAL-SPEC:END -->
