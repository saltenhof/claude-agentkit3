---
id: formal.skills-and-bundles.entities
title: Skills and Bundles Entities
status: active
doc_kind: spec
context: skills-and-bundles
spec_kind: entity-set
version: 1
prose_refs:
  - concept/technical-design/43_skills_system_task_automation.md
  - concept/technical-design/10_runtime_deployment_speicher.md
  - concept/technical-design/50_installer_checkpoint_engine_bootstrap.md
  - concept/technical-design/51_upgrade_migration_customization_preservation.md
---

# Skills and Bundles Entities

Dieser Kontext modelliert keine einzelnen Skill-Dateien als
Primaerobjekte, sondern Bundles, Varianten und Bindungen.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.skills-and-bundles.entities
schema_version: 1
kind: entity-set
context: skills-and-bundles
entities:
  - id: skills-and-bundles.entity.bundle
    identity_key: bundle_id
    attributes:
      - bundle_id
      - bundle_kind
      - bundle_version
      - variant
      - root_path
      - immutable
  - id: skills-and-bundles.entity.skill-binding
    identity_key: binding_id
    attributes:
      - binding_id
      - project_key
      - skill_name
      - bundle_id
      - target_path
      - binding_mode
  - id: skills-and-bundles.entity.profile-selection
    identity_key: project_key
    attributes:
      - project_key
      - runtime_profile
      - selected_variant
      - are_enabled
      - resolved_at
  - id: skills-and-bundles.entity.bundle-override
    identity_key: override_id
    attributes:
      - override_id
      - project_key
      - bundle_kind
      - requested_bundle_version
      - effective_bundle_version
      - override_reason
```
<!-- FORMAL-SPEC:END -->
