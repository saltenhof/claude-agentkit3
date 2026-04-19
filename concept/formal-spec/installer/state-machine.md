---
id: formal.installer.state-machine
title: Installer State Machine
status: active
doc_kind: spec
context: installer
spec_kind: state-machine
version: 1
prose_refs:
  - concept/technical-design/50_installer_checkpoint_engine_bootstrap.md
  - concept/technical-design/51_upgrade_migration_customization_preservation.md
  - concept/domain-design/08-installation-und-bootstrap.md
---

# Installer State Machine

Der Installer ist ein eigenstaendiger Bootstrap- und
Registrierungsprozess ausserhalb der Story-Pipeline.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.installer.state-machine
schema_version: 1
kind: state-machine
context: installer
states:
  - id: installer.status.requested
    initial: true
  - id: installer.status.preconditions_checked
  - id: installer.status.github_bound
  - id: installer.status.config_prepared
  - id: installer.status.project_registered
  - id: installer.status.bindings_applied
  - id: installer.status.verified
    terminal: true
  - id: installer.status.dry_run_completed
    terminal: true
  - id: installer.status.failed
    terminal: true
transitions:
  - id: installer.transition.requested_to_preconditions_checked
    from: installer.status.requested
    to: installer.status.preconditions_checked
    guard: installer.invariant.system_installation_precedes_project_registration
  - id: installer.transition.preconditions_checked_to_github_bound
    from: installer.status.preconditions_checked
    to: installer.status.github_bound
  - id: installer.transition.github_bound_to_config_prepared
    from: installer.status.github_bound
    to: installer.status.config_prepared
  - id: installer.transition.config_prepared_to_project_registered
    from: installer.status.config_prepared
    to: installer.status.project_registered
    guard: installer.invariant.state_backend_registration_precedes_bundle_binding
  - id: installer.transition.project_registered_to_bindings_applied
    from: installer.status.project_registered
    to: installer.status.bindings_applied
    guard: installer.invariant.bundle_bindings_are_version_pinned
  - id: installer.transition.bindings_applied_to_verified
    from: installer.status.bindings_applied
    to: installer.status.verified
    guard: installer.invariant.verify_project_is_read_only
  - id: installer.transition.preconditions_checked_to_dry_run_completed
    from: installer.status.preconditions_checked
    to: installer.status.dry_run_completed
  - id: installer.transition.requested_to_failed
    from: installer.status.requested
    to: installer.status.failed
  - id: installer.transition.preconditions_checked_to_failed
    from: installer.status.preconditions_checked
    to: installer.status.failed
  - id: installer.transition.github_bound_to_failed
    from: installer.status.github_bound
    to: installer.status.failed
  - id: installer.transition.config_prepared_to_failed
    from: installer.status.config_prepared
    to: installer.status.failed
  - id: installer.transition.project_registered_to_failed
    from: installer.status.project_registered
    to: installer.status.failed
  - id: installer.transition.bindings_applied_to_failed
    from: installer.status.bindings_applied
    to: installer.status.failed
compound_rules:
  - id: installer.rule.verify-does-not-mutate-registration
    description: Verification may confirm or reject registration state, but may not create or mutate bundle bindings or project registration rows.
```
<!-- FORMAL-SPEC:END -->
