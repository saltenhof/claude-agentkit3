---
id: formal.skills-and-bundles.state-machine
title: Skills and Bundles State Machine
status: active
doc_kind: spec
context: skills-and-bundles
spec_kind: state-machine
version: 1
prose_refs:
  - concept/technical-design/43_skills_system_task_automation.md
  - concept/technical-design/50_installer_checkpoint_engine_bootstrap.md
  - concept/technical-design/51_upgrade_migration_customization_preservation.md
---

# Skills and Bundles State Machine

Die State-Machine bildet die Auswahl und Bindung konkreter Bundle-
Varianten ab.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.skills-and-bundles.state-machine
schema_version: 1
kind: state-machine
context: skills-and-bundles
states:
  - id: skills-and-bundles.status.requested
    initial: true
  - id: skills-and-bundles.status.profile_resolved
  - id: skills-and-bundles.status.bundle_selected
  - id: skills-and-bundles.status.bound
  - id: skills-and-bundles.status.verified
    terminal: true
  - id: skills-and-bundles.status.rejected
    terminal: true
transitions:
  - id: skills-and-bundles.transition.requested_to_profile_resolved
    from: skills-and-bundles.status.requested
    to: skills-and-bundles.status.profile_resolved
    guard: skills-and-bundles.invariant.profile_selects_one_variant_before_binding
  - id: skills-and-bundles.transition.profile_resolved_to_bundle_selected
    from: skills-and-bundles.status.profile_resolved
    to: skills-and-bundles.status.bundle_selected
    guard: skills-and-bundles.invariant.bundle_binding_points_to_concrete_version
  - id: skills-and-bundles.transition.bundle_selected_to_bound
    from: skills-and-bundles.status.bundle_selected
    to: skills-and-bundles.status.bound
    guard: skills-and-bundles.invariant.project_binding_is_symlink_only
  - id: skills-and-bundles.transition.bound_to_verified
    from: skills-and-bundles.status.bound
    to: skills-and-bundles.status.verified
  - id: skills-and-bundles.transition.requested_to_rejected
    from: skills-and-bundles.status.requested
    to: skills-and-bundles.status.rejected
  - id: skills-and-bundles.transition.profile_resolved_to_rejected
    from: skills-and-bundles.status.profile_resolved
    to: skills-and-bundles.status.rejected
  - id: skills-and-bundles.transition.bundle_selected_to_rejected
    from: skills-and-bundles.status.bundle_selected
    to: skills-and-bundles.status.rejected
  - id: skills-and-bundles.transition.bound_to_rejected
    from: skills-and-bundles.status.bound
    to: skills-and-bundles.status.rejected
compound_rules:
  - id: skills-and-bundles.rule.rebind-keeps-same-contract
    description: An upgrade or rebind uses the same profile and bundle-binding contract as the initial registration and may only change the pinned bundle version intentionally.
```
<!-- FORMAL-SPEC:END -->
