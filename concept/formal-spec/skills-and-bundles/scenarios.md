---
id: formal.skills-and-bundles.scenarios
title: Skills and Bundles Scenarios
status: active
doc_kind: spec
context: skills-and-bundles
spec_kind: scenario-set
version: 1
prose_refs:
  - concept/technical-design/43_skills_system_task_automation.md
  - concept/technical-design/50_installer_checkpoint_engine_bootstrap.md
  - concept/technical-design/51_upgrade_migration_customization_preservation.md
---

# Skills and Bundles Scenarios

Diese Traces pruefen Variantenwahl, Binding und Rebind-Pfade.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.skills-and-bundles.scenarios
schema_version: 1
kind: scenario-set
context: skills-and-bundles
scenarios:
  - id: skills-and-bundles.scenario.core-profile-binds-core-variant
    start:
      status: skills-and-bundles.status.requested
    trace:
      - command: skills-and-bundles.command.resolve-profile
      - command: skills-and-bundles.command.select-bundle
      - command: skills-and-bundles.command.bind-project-skills
      - command: skills-and-bundles.command.verify-bindings
    expected_end:
      status: skills-and-bundles.status.verified
    requires:
      - skills-and-bundles.invariant.profile_selects_one_variant_before_binding
      - skills-and-bundles.invariant.project_binding_is_symlink_only
  - id: skills-and-bundles.scenario.are-profile-binds-are-variant
    start:
      status: skills-and-bundles.status.requested
    trace:
      - command: skills-and-bundles.command.resolve-profile
      - command: skills-and-bundles.command.select-bundle
      - command: skills-and-bundles.command.bind-project-skills
    expected_end:
      status: skills-and-bundles.status.verified
    requires:
      - skills-and-bundles.invariant.runtime-branching-stays-out-of-skill-contract
      - skills-and-bundles.invariant.bundle_binding_points_to_concrete_version
  - id: skills-and-bundles.scenario.rebind-updates-pinned-version-only
    start:
      status: skills-and-bundles.status.bound
    trace:
      - command: skills-and-bundles.command.rebind-to-new-version
    expected_end:
      status: skills-and-bundles.status.verified
    requires:
      - skills-and-bundles.invariant.bundle_binding_points_to_concrete_version
      - skills-and-bundles.invariant.customized_bundle_bindings_are_never_silently_replaced
  - id: skills-and-bundles.scenario.latest-binding-is-rejected
    start:
      status: skills-and-bundles.status.profile_resolved
    trace:
      - command: skills-and-bundles.command.illegal-bind-latest
    expected_end:
      status: skills-and-bundles.status.rejected
    requires:
      - skills-and-bundles.invariant.bundle_binding_points_to_concrete_version
  - id: skills-and-bundles.scenario.copying-canonical-skill-source-is-rejected
    start:
      status: skills-and-bundles.status.bundle_selected
    trace:
      - command: skills-and-bundles.command.illegal-copy-skill-source
    expected_end:
      status: skills-and-bundles.status.rejected
    requires:
      - skills-and-bundles.invariant.project_local_repo_never_contains_canonical_skill_source
```
<!-- FORMAL-SPEC:END -->
