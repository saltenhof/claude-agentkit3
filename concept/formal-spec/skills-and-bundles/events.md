---
id: formal.skills-and-bundles.events
title: Skills and Bundles Events
status: active
doc_kind: spec
context: skills-and-bundles
spec_kind: event-set
version: 1
prose_refs:
  - concept/technical-design/43_skills_system_task_automation.md
  - concept/technical-design/50_installer_checkpoint_engine_bootstrap.md
  - concept/technical-design/51_upgrade_migration_customization_preservation.md
---

# Skills and Bundles Events

Diese Events machen Profilwahl, Bundleselection und Binding auditierbar.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.skills-and-bundles.events
schema_version: 1
kind: event-set
context: skills-and-bundles
events:
  - id: skills-and-bundles.event.profile.resolved
    producer: installer
    payload:
      - project_key
      - runtime_profile
      - selected_variant
    role: project profile resolved to one concrete skill variant
  - id: skills-and-bundles.event.bundle.selected
    producer: installer
    payload:
      - project_key
      - bundle_kind
      - bundle_version
      - variant
    role: concrete immutable bundle version selected
  - id: skills-and-bundles.event.binding.applied
    producer: installer
    payload:
      - project_key
      - skill_name
      - target_path
      - bundle_version
    role: project-local symlink binding applied
  - id: skills-and-bundles.event.binding.verified
    producer: installer
    payload:
      - project_key
      - binding_count
      - verification_result
    role: binding set verified against profile and bundle version
  - id: skills-and-bundles.event.binding.rebound
    producer: installer
    payload:
      - project_key
      - previous_bundle_version
      - new_bundle_version
      - variant
    role: project rebound to a new pinned bundle version
  - id: skills-and-bundles.event.binding.rejected
    producer: installer or guard
    payload:
      - project_key
      - rejection_reason
      - attempted_binding_mode
    role: illegal or unsupported bundle binding rejected
```
<!-- FORMAL-SPEC:END -->
