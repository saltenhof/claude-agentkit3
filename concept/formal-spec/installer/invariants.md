---
id: formal.installer.invariants
title: Installer Invariants
status: active
doc_kind: spec
context: installer
spec_kind: invariant-set
version: 1
prose_refs:
  - concept/technical-design/50_installer_checkpoint_engine_bootstrap.md
  - concept/technical-design/51_upgrade_migration_customization_preservation.md
  - concept/domain-design/08-installation-und-bootstrap.md
---

# Installer Invariants

Diese Invarianten definieren die harte Registrierungs- und
Upgrade-Semantik.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.installer.invariants
schema_version: 1
kind: invariant-set
context: installer
invariants:
  - id: installer.invariant.system_installation_precedes_project_registration
    scope: bootstrap
    rule: project registration is legal only after the system-level AgentKit installation and runtime bundle base are present
  - id: installer.invariant.register_project_is_idempotent
    scope: execution
    rule: rerunning register-project for the same project key must converge on one consistent registration state instead of duplicating bindings or project records
  - id: installer.invariant.state_backend_registration_precedes_bundle_binding
    scope: ordering
    rule: project registration in the central state backend must complete before project-local bundle bindings become active
  - id: installer.invariant.project_local_scope_is_config_and_symlink_only
    scope: filesystem
    rule: project-local installer output is limited to configuration, hook registration, and Claude-Code-compatible symlink bindings and must not copy AgentKit runtime artifacts into the project
  - id: installer.invariant.bundle_bindings_are_version_pinned
    scope: bundle-binding
    rule: skill and prompt bindings must point to one concrete immutable bundle version and never to a live source checkout or latest alias
  - id: installer.invariant.customizations_are_never_silently_overwritten
    scope: upgrade
    rule: detected project-specific customizations must be preserved or explicitly surfaced and may never be silently overwritten by an installer rerun or upgrade
  - id: installer.invariant.verify_project_is_read_only
    scope: verification
    rule: verify-project may inspect registration state but must not mutate configuration, backend registration rows, or bundle bindings
  - id: installer.invariant.dry_run_never_mutates_runtime_or_project_state
    scope: dry-run
    rule: a dry-run may preview checkpoint work but may not change project files, backend state, hooks, or bindings
```
<!-- FORMAL-SPEC:END -->
