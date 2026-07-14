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
      project_registry_row: present
      visible_project_row: present
    requires:
      - installer.invariant.system_installation_precedes_project_registration
      - installer.invariant.cp7_project_registration_makes_project_visible
      - installer.invariant.state_backend_registration_precedes_bundle_binding
      - installer.invariant.bundle_bindings_are_version_pinned
      - installer.invariant.project_edge_launcher_is_adapter_only
  - id: installer.scenario.project-edge-launcher-installed
    start:
      status: installer.status.project_registered
    trace:
      - command: installer.command.register-project
    expected_end:
      status: installer.status.verified
      launcher:
        target_path: tools/agentkit/projectedge.py
        invocation_prefix: python
        adapter_only: true
    requires:
      - installer.invariant.project_edge_launcher_is_adapter_only
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
  - id: installer.scenario.third-party-light-validation-is-backend-mediated
    start:
      status: installer.status.project_registered
    trace:
      - command: installer.command.validate-third-party
        parameters:
          project_key: acme-trading
          sonar_token_env: SONARQUBE_TOKEN
          ci_token_env: JENKINS_TOKEN
    expected_end:
      status: installer.status.verified
      cp10d:
        verdict: PASS
        dev_sonar_client_constructed: false
        dev_jenkins_client_constructed: false
        heavy_self_test_started: false
    requires:
      - installer.invariant.third_party_validation_is_backend_owned
      - installer.invariant.third_party_secrets_never_cross_the_wire
      - installer.invariant.local_sonar_profile_check_stays_dev_side
  - id: installer.scenario.third-party-backend-unreachable-fails
    start:
      status: installer.status.project_registered
    trace:
      - command: installer.command.validate-third-party
        parameters:
          backend_reachable: false
    expected_end:
      status: installer.status.failed
      exit_nonzero: true
      dev_fallback_used: false
    requires:
      - installer.invariant.third_party_validation_fails_closed
  - id: installer.scenario.third-party-system-unreachable-fails
    start:
      status: installer.status.project_registered
    trace:
      - command: installer.command.validate-third-party
        parameters:
          sonar_reachable: false
    expected_end:
      status: installer.status.failed
      error_code: sonar_unreachable
    requires:
      - installer.invariant.third_party_validation_fails_closed
  - id: installer.scenario.branch-plugin-selftest-explicit-async
    start:
      status: installer.status.bindings_applied
    trace:
      - command: installer.command.run-branch-plugin-self-test
        parameters:
          op_id: branch-self-test-1
      - command: installer.command.run-branch-plugin-self-test
        parameters:
          op_id: branch-self-test-1
    expected_end:
      status: installer.status.verified
      operation_status: succeeded
      operation_rows: 1
      jenkins_scan_count: 2
    requires:
      - installer.invariant.heavy_self_test_is_explicit_async_only
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
