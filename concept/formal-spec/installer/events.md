---
id: formal.installer.events
title: Installer Events
status: active
doc_kind: spec
context: installer
spec_kind: event-set
version: 1
prose_refs:
  - concept/technical-design/50_installer_checkpoint_engine_bootstrap.md
  - concept/technical-design/51_upgrade_migration_customization_preservation.md
  - concept/technical-design/91_api_event_katalog.md
---

# Installer Events

Diese Events machen Registrierung, Verifikation und Re-Bindung
auditierbar.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.installer.events
schema_version: 1
kind: event-set
context: installer
events:
  - id: installer.event.registration.requested
    producer: cli
    payload:
      - project_key
      - gh_owner
      - gh_repo
      - execution_mode
    role: project registration explicitly requested
  - id: installer.event.registration.started
    producer: installer
    payload:
      - project_key
      - checkpoint_run_id
      - execution_mode
    role: checkpoint engine started an actual registration run
  - id: installer.event.registration.completed
    producer: installer
    payload:
      - project_key
      - checkpoint_run_id
      - bundle_version
    role: registration and bundle binding completed successfully
  - id: installer.event.registration.verified
    producer: installer
    payload:
      - project_key
      - verification_result
    role: read-only registration verification completed
  - id: installer.event.registration.dry_run_completed
    producer: installer
    payload:
      - project_key
      - checkpoint_preview
    role: dry-run preview completed without mutating project or backend
  - id: installer.event.binding.rebound
    producer: installer
    payload:
      - project_key
      - bundle_kind
      - bundle_version
      - variant
    role: existing project rebound to a concrete bundle version
  - id: installer.event.customization.preserved
    producer: installer
    payload:
      - project_key
      - preserved_keys
      - config_digest
    role: detected project customization preserved during upgrade or rebind
  - id: installer.event.registration.failed
    producer: installer
    payload:
      - project_key
      - checkpoint_run_id
      - failure_reason
    role: installer flow failed and left registration incomplete
```
<!-- FORMAL-SPEC:END -->
