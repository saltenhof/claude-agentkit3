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
    rule: rerunning register-project for the same project key must converge on one consistent registration state instead of duplicating bindings, project_registry rows, or visible project-management project rows
  - id: installer.invariant.cp7_project_registration_makes_project_visible
    scope: registration
    rule: a successful CP 7 must persist both the installation registration in project_registry and the project-management project row consumed by GET /v1/projects; if either write cannot be made consistent, CP 7 fails closed
  - id: installer.invariant.state_backend_registration_precedes_bundle_binding
    scope: ordering
    rule: project registration in the central state backend, including the visible project-management project row, must complete before project-local bundle bindings become active
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
    rule: in the default scaffold, temp/ must be ignored by the root repository and codebase/ must be ignored exactly in multi_repo mode; codebase/ must remain trackable in single_repo mode; empty persistent scaffold directories must carry neutral .gitkeep placeholders so the intended layout is visible in Git, while temp/ must not carry such a placeholder
  - id: installer.invariant.multi_repo_requires_explicit_repositories
    scope: filesystem
    rule: multi_repo mode requires explicit code repository declarations and must not invent synthetic repository names or paths such as codebase/app
  - id: installer.invariant.default_scaffold_existing_repo_dirs_fail_closed
    scope: filesystem
    rule: creating default-scaffold repository directories must fail closed when an existing non-empty directory has an incompatible Git state; existing valid Git repository directories are skipped unchanged on rerun
  - id: installer.invariant.cp10d_branch_plugin_selftest_uses_operational_ci_scan_path
    scope: integration-precondition
    rule: when explicitly requested, the backend-owned Community-Branch-Plugin conformance self-test must provision a throwaway Sonar project bound to the dedicated self-test quality gate, execute scans through the configured Jenkins pipeline, and read the Jenkins-archived scanner report-task; the dev installer host must not require a local sonar-scanner binary or a Sonar/Jenkins client
  - id: installer.invariant.third_party_validation_is_backend_owned
    scope: integration-precondition
    rule: register-project and verify-project must request the synchronous typed Sonar/Jenkins/feature-gated-ARE verdict only through the official Project Edge Client and the project-scoped Control-Plane route; the dev process must instantiate no Sonar or Jenkins client and must have no direct fallback or second transport
  - id: installer.invariant.third_party_secrets_never_cross_the_wire
    scope: secrets
    rule: third-system configuration crossing Dev to Core carries token_env references only; the backend resolves them in its own environment and redacts resolved tokens and authorization headers from responses, details, telemetry, and logs
  - id: installer.invariant.local_sonar_profile_check_stays_dev_side
    scope: filesystem
    rule: the default Sonar quality-profile file-existence check remains a dev-local pre-send configuration validation, while third-system probes run only in the backend; no dev repo_root is sent to the backend
  - id: installer.invariant.heavy_self_test_is_explicit_async_only
    scope: integration-precondition
    rule: branch-plugin conformance is started only by the explicit project-scoped on-demand command, returns 202 plus op_id, persists one idempotent ControlPlaneOperationRecord lifecycle, and is never triggered implicitly by register-project or verify-project
  - id: installer.invariant.third_party_validation_fails_closed
    scope: integration-precondition
    rule: an unreachable backend or any applicable unreachable or invalid third system produces a visible failed checkpoint and nonzero installer outcome; no dev-side fallback, bypass, or silent skip is legal
  - id: installer.invariant.bundle_bindings_are_version_pinned
    scope: bundle-binding
    rule: skill and prompt bindings must point to one concrete immutable bundle version and never to a live source checkout or latest alias
  - id: installer.invariant.customizations_are_never_silently_overwritten
    scope: upgrade
    rule: detected project-specific customizations must be preserved or explicitly surfaced and may never be silently overwritten by an installer rerun or upgrade
  - id: installer.invariant.verify_project_is_read_only
    scope: verification
    rule: verify-project may inspect registration state and run backend-mediated live reachability reads, but must not mutate configuration, backend registration rows, bundle bindings, or third systems and must never start the heavy branch-plugin self-test
  - id: installer.invariant.dry_run_never_mutates_runtime_or_project_state
    scope: dry-run
    rule: a dry-run may preview checkpoint work but may not change project files, backend state, hooks, or bindings
```
<!-- FORMAL-SPEC:END -->
