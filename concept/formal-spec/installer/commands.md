---
id: formal.installer.commands
title: Installer Commands
status: active
doc_kind: spec
context: installer
spec_kind: command-set
version: 1
prose_refs:
  - concept/technical-design/50_installer_checkpoint_engine_bootstrap.md
  - concept/technical-design/51_upgrade_migration_customization_preservation.md
  - concept/technical-design/91_api_event_katalog.md
---

# Installer Commands

Dies sind die offiziellen registrierungs- und verifikationsbezogenen
CLI-Pfade.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.installer.commands
schema_version: 1
kind: command-set
context: installer
commands:
  - id: installer.command.register-project
    signature: agentkit register-project --gh-owner <owner> --gh-repo <repo>
    allowed_statuses:
      - installer.status.requested
      - installer.status.preconditions_checked
      - installer.status.github_bound
      - installer.status.config_prepared
      - installer.status.project_registered
      - installer.status.bindings_applied
    requires:
      - installer.invariant.system_installation_precedes_project_registration
      - installer.invariant.register_project_is_idempotent
    emits:
      - installer.event.registration.requested
      - installer.event.registration.started
      - installer.event.registration.completed
      - installer.event.registration.failed
  - id: installer.command.register-project-dry-run
    signature: agentkit register-project --gh-owner <owner> --gh-repo <repo> --dry-run
    allowed_statuses:
      - installer.status.requested
      - installer.status.preconditions_checked
    requires:
      - installer.invariant.dry_run_never_mutates_runtime_or_project_state
    emits:
      - installer.event.registration.dry_run_completed
  - id: installer.command.verify-project
    signature: agentkit verify-project
    allowed_statuses:
      - installer.status.bindings_applied
      - installer.status.verified
    requires:
      - installer.invariant.verify_project_is_read_only
    emits:
      - installer.event.registration.verified
      - installer.event.registration.failed
  - id: installer.command.rebind-bundles
    signature: internal installer bundle rebind during upgrade or cleanup
    allowed_statuses:
      - installer.status.project_registered
      - installer.status.bindings_applied
    requires:
      - installer.invariant.bundle_bindings_are_version_pinned
      - installer.invariant.customizations_are_never_silently_overwritten
    emits:
      - installer.event.binding.rebound
      - installer.event.customization.preserved
  - id: installer.command.illegal-overwrite-customization
    signature: illegal installer overwrite of project customization without explicit preservation path
    allowed_statuses:
      - installer.status.config_prepared
      - installer.status.project_registered
      - installer.status.bindings_applied
    requires:
      - installer.invariant.customizations_are_never_silently_overwritten
    emits:
      - installer.event.registration.failed
```
<!-- FORMAL-SPEC:END -->
