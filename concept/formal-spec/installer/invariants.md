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
  - id: installer.invariant.project_local_scope_is_config_and_link_only
    scope: filesystem
    rule: project-local installer output is limited to configuration, hook registration, harness-specific link bindings (symlink on POSIX, directory junction on Windows; Claude Code, Codex; FK-76), and official Project Edge Client launcher wrappers under tools/agentkit; when default_project_structure is explicitly enabled, the installer may additionally create the FK-10 default-scaffold directories and the corresponding root .gitignore entries, but must still not copy AgentKit runtime state, canonical skills, canonical prompts, database files, or backend service artifacts into the project
  - id: installer.invariant.project_edge_launcher_is_adapter_only
    scope: filesystem
    rule: project-local Project Edge Client launcher wrappers may be materialized or copied into tools/agentkit only as convenient agent entry points to the installed AgentKit package and Control-Plane API; they must not become a second command semantics, state store, skill source, prompt source, or backend runtime
  - id: installer.invariant.default_scaffold_is_opt_in
    scope: filesystem
    rule: the FK-10 default project scaffold is disabled by default and may be created only when the operator explicitly enables default_project_structure
  - id: installer.invariant.default_scaffold_gitignore_policy
    scope: filesystem
    rule: in the default scaffold, temp/ must be ignored by the root repository and codebase/ must be ignored exactly in multi_repo mode; codebase/ must remain trackable in single_repo mode
  - id: installer.invariant.multi_repo_requires_explicit_repositories
    scope: filesystem
    rule: multi_repo mode requires explicit code repository declarations and must not invent synthetic repository names or paths such as codebase/app
  - id: installer.invariant.default_scaffold_existing_repo_dirs_fail_closed
    scope: filesystem
    rule: creating default-scaffold repository directories must fail closed when an existing non-empty directory has an incompatible Git state; existing valid Git repository directories are skipped unchanged on rerun
  - id: installer.invariant.cp10d_branch_plugin_selftest_uses_operational_ci_scan_path
    scope: integration-precondition
    rule: when sonarqube.available is true and CI is declared available, the CP 10d Community-Branch-Plugin conformance self-test must execute scans through the configured Jenkins pipeline and read the Jenkins-archived scanner report-task; the installer host must not require a local sonar-scanner binary for the normative production path
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
