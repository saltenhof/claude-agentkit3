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
  - id: installer.scenario.default-scaffold-single-repo
    start:
      status: installer.status.requested
    trace:
      - command: installer.command.register-project
        parameters:
          default_project_structure: true
          multi_repo: false
    expected_end:
      status: installer.status.verified
      scaffold:
        temp_ignored: true
        codebase_ignored: false
        repository_path: codebase
    requires:
      - installer.invariant.default_scaffold_is_opt_in
      - installer.invariant.default_scaffold_gitignore_policy
  - id: installer.scenario.default-scaffold-multi-repo
    start:
      status: installer.status.requested
    trace:
      - command: installer.command.register-project
        parameters:
          default_project_structure: true
          multi_repo: true
          code_repos:
            - name: frontend
              remote_url: https://git.example/frontend.git
            - name: backend
              remote_url: https://git.example/backend.git
    expected_end:
      status: installer.status.verified
      scaffold:
        temp_ignored: true
        codebase_ignored: true
        repository_paths:
          - codebase/frontend
          - codebase/backend
    requires:
      - installer.invariant.default_scaffold_is_opt_in
      - installer.invariant.default_scaffold_gitignore_policy
      - installer.invariant.multi_repo_requires_explicit_repositories
  - id: installer.scenario.default-scaffold-multi-repo-without-repos-fails
    start:
      status: installer.status.requested
    trace:
      - command: installer.command.register-project
        parameters:
          default_project_structure: true
          multi_repo: true
    expected_end:
      status: installer.status.failed
    requires:
      - installer.invariant.multi_repo_requires_explicit_repositories
  - id: installer.scenario.default-scaffold-existing-repo-dir-is-skipped
    start:
      status: installer.status.requested
      filesystem:
        existing_directory: codebase/frontend
        git_state: valid_repository
    trace:
      - command: installer.command.register-project
        parameters:
          default_project_structure: true
          multi_repo: true
          code_repos:
            - name: frontend
              remote_url: https://git.example/frontend.git
            - name: backend
              remote_url: https://git.example/backend.git
    expected_end:
      status: installer.status.verified
      scaffold:
        skipped_existing:
          - codebase/frontend
        created_or_cloned:
          - codebase/backend
    requires:
      - installer.invariant.default_scaffold_existing_repo_dirs_fail_closed
  - id: installer.scenario.default-scaffold-incompatible-repo-dir-fails
    start:
      status: installer.status.requested
      filesystem:
        existing_directory: codebase/frontend
        git_state: incompatible_non_empty
    trace:
      - command: installer.command.register-project
        parameters:
          default_project_structure: true
          multi_repo: true
          code_repos:
            - name: frontend
              remote_url: https://git.example/frontend.git
    expected_end:
      status: installer.status.failed
    requires:
      - installer.invariant.default_scaffold_existing_repo_dirs_fail_closed
  - id: installer.scenario.sonar-ci-selftest-uses-jenkins
    start:
      status: installer.status.requested
    trace:
      - command: installer.command.register-project
        parameters:
          sonarqube_available: true
          ci_available: true
          cp10d_selftest_runner: jenkins
    expected_end:
      status: installer.status.verified
      cp10d:
        scanner_host: jenkins_agent
        installer_host_local_sonar_scanner_required: false
    requires:
      - installer.invariant.cp10d_branch_plugin_selftest_uses_operational_ci_scan_path
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
