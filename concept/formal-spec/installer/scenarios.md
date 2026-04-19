---
id: formal.installer.scenarios
title: Installer Scenarios
status: active
doc_kind: spec
context: installer
spec_kind: scenario-set
version: 1
prose_refs:
  - concept/technical-design/50_installer_checkpoint_engine_bootstrap.md
  - concept/technical-design/51_upgrade_migration_customization_preservation.md
  - concept/domain-design/08-installation-und-bootstrap.md
---

# Installer Scenarios

Diese Traces pruefen Erstregistrierung, Idempotenz, Dry-Run und
Customization-Preservation.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.installer.scenarios
schema_version: 1
kind: scenario-set
context: installer
scenarios:
  - id: installer.scenario.initial-registration-happy-path
    start:
      status: installer.status.requested
    trace:
      - command: installer.command.register-project
    expected_end:
      status: installer.status.verified
    requires:
      - installer.invariant.system_installation_precedes_project_registration
      - installer.invariant.state_backend_registration_precedes_bundle_binding
      - installer.invariant.bundle_bindings_are_version_pinned
  - id: installer.scenario.idempotent-rerun-converges
    start:
      status: installer.status.bindings_applied
    trace:
      - command: installer.command.verify-project
    expected_end:
      status: installer.status.verified
    requires:
      - installer.invariant.register_project_is_idempotent
      - installer.invariant.verify_project_is_read_only
  - id: installer.scenario.dry-run-stops-without-mutation
    start:
      status: installer.status.requested
    trace:
      - command: installer.command.register-project-dry-run
    expected_end:
      status: installer.status.dry_run_completed
    requires:
      - installer.invariant.dry_run_never_mutates_runtime_or_project_state
  - id: installer.scenario.upgrade-rebind-preserves-customization
    start:
      status: installer.status.project_registered
    trace:
      - command: installer.command.rebind-bundles
    expected_end:
      status: installer.status.verified
    requires:
      - installer.invariant.bundle_bindings_are_version_pinned
      - installer.invariant.customizations_are_never_silently_overwritten
  - id: installer.scenario.illegal-customization-overwrite-fails
    start:
      status: installer.status.bindings_applied
    trace:
      - command: installer.command.illegal-overwrite-customization
    expected_end:
      status: installer.status.failed
    requires:
      - installer.invariant.customizations_are_never_silently_overwritten
```
<!-- FORMAL-SPEC:END -->
