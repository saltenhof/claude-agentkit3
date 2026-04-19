---
id: formal.skills-and-bundles.commands
title: Skills and Bundles Commands
status: active
doc_kind: spec
context: skills-and-bundles
spec_kind: command-set
version: 1
prose_refs:
  - concept/technical-design/43_skills_system_task_automation.md
  - concept/technical-design/50_installer_checkpoint_engine_bootstrap.md
  - concept/technical-design/51_upgrade_migration_customization_preservation.md
---

# Skills and Bundles Commands

Dies sind die offiziellen Schritte fuer Variantenwahl und Binding.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.skills-and-bundles.commands
schema_version: 1
kind: command-set
context: skills-and-bundles
commands:
  - id: skills-and-bundles.command.resolve-profile
    signature: internal determine project runtime profile and variant before bundle binding
    allowed_statuses:
      - skills-and-bundles.status.requested
    requires:
      - skills-and-bundles.invariant.profile_selects_one_variant_before_binding
    emits:
      - skills-and-bundles.event.profile.resolved
  - id: skills-and-bundles.command.select-bundle
    signature: internal choose one concrete immutable bundle version for the selected variant
    allowed_statuses:
      - skills-and-bundles.status.profile_resolved
    requires:
      - skills-and-bundles.invariant.bundle_binding_points_to_concrete_version
      - skills-and-bundles.invariant.live-source-checkout-is-never-a-production-bundle
    emits:
      - skills-and-bundles.event.bundle.selected
  - id: skills-and-bundles.command.bind-project-skills
    signature: internal create project-local Claude-Code-compatible symlink bindings to selected bundles
    allowed_statuses:
      - skills-and-bundles.status.bundle_selected
    requires:
      - skills-and-bundles.invariant.project_binding_is_symlink_only
      - skills-and-bundles.invariant.project_local_repo_never_contains_canonical_skill_source
    emits:
      - skills-and-bundles.event.binding.applied
  - id: skills-and-bundles.command.verify-bindings
    signature: internal verify profile, bundle version, and symlink bindings
    allowed_statuses:
      - skills-and-bundles.status.bound
      - skills-and-bundles.status.verified
    emits:
      - skills-and-bundles.event.binding.verified
  - id: skills-and-bundles.command.rebind-to-new-version
    signature: internal rebind project from one pinned bundle version to another pinned bundle version
    allowed_statuses:
      - skills-and-bundles.status.bound
      - skills-and-bundles.status.verified
    requires:
      - skills-and-bundles.invariant.bundle_binding_points_to_concrete_version
      - skills-and-bundles.invariant.customized_bundle_bindings_are_never_silently_replaced
    emits:
      - skills-and-bundles.event.binding.rebound
  - id: skills-and-bundles.command.illegal-bind-latest
    signature: illegal project binding against latest or moving alias
    allowed_statuses:
      - skills-and-bundles.status.profile_resolved
      - skills-and-bundles.status.bundle_selected
    requires:
      - skills-and-bundles.invariant.bundle_binding_points_to_concrete_version
    emits:
      - skills-and-bundles.event.binding.rejected
  - id: skills-and-bundles.command.illegal-copy-skill-source
    signature: illegal copy of canonical skill source into project workspace
    allowed_statuses:
      - skills-and-bundles.status.bundle_selected
      - skills-and-bundles.status.bound
    requires:
      - skills-and-bundles.invariant.project_local_repo_never_contains_canonical_skill_source
    emits:
      - skills-and-bundles.event.binding.rejected
```
<!-- FORMAL-SPEC:END -->
