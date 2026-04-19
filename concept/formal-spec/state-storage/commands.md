---
id: formal.state-storage.commands
title: State Storage Commands
status: active
doc_kind: spec
context: state-storage
spec_kind: command-set
version: 1
prose_refs:
  - concept/technical-design/18_relationales_abbildungsmodell_postgres.md
  - concept/technical-design/16_qa_telemetrie_aggregation_dashboard.md
  - concept/technical-design/91_api_event_katalog.md
---

# State Storage Commands

Diese Commands beschreiben fachliche Speicheroperationen, nicht
konkrete SQL-Befehle.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.state-storage.commands
schema_version: 1
kind: command-set
context: state-storage
commands:
  - id: state-storage.command.persist-canonical-state
    signature: internal persist canonical runtime or catalog state for one project-scoped identity
    allowed_statuses:
      - state-storage.status.ready
      - state-storage.status.canonical_current
    requires:
      - state-storage.invariant.tenant_scoped_families_require_project_key
      - state-storage.invariant.exactly_one_canonical_family_per_fact
      - state-storage.invariant.mutating_families_have_single_writer
    emits:
      - state-storage.event.canonical.persisted
  - id: state-storage.command.materialize-derived-families
    signature: internal rebuild or refresh derived read-model and projection families from canonical state
    allowed_statuses:
      - state-storage.status.canonical_current
      - state-storage.status.derived_stale
    requires:
      - state-storage.invariant.derived_families_never_become_source_of_truth
      - state-storage.invariant.rebuild_only_families_require_canonical_source
    emits:
      - state-storage.event.derived.materialized
      - state-storage.event.derived.rebuilt
  - id: state-storage.command.append-telemetry
    signature: internal append runtime observation for the current story execution
    allowed_statuses:
      - state-storage.status.canonical_current
      - state-storage.status.derived_current
      - state-storage.status.derived_stale
    requires:
      - state-storage.invariant.telemetry_never_blocks_story_start
    emits:
      - state-storage.event.telemetry.appended
      - state-storage.event.telemetry.degraded
  - id: state-storage.command.mark-derived-stale
    signature: internal invalidate or mark stale all affected derived families for one story or project
    allowed_statuses:
      - state-storage.status.derived_current
    requires:
      - state-storage.invariant.derived_families_never_become_source_of_truth
    emits:
      - state-storage.event.derived.stale
  - id: state-storage.command.purge-story-runtime
    signature: internal delete or invalidate all runtime, telemetry, projection, and analytics families affected by story reset
    allowed_statuses:
      - state-storage.status.canonical_current
      - state-storage.status.derived_current
      - state-storage.status.derived_stale
      - state-storage.status.resetting
    requires:
      - state-storage.invariant.reset_closure_cleans_dependent_families
      - state-storage.invariant.noncanonical_families_must_not_survive_reset_as_active
    emits:
      - state-storage.event.runtime.purged
      - state-storage.event.derived.invalidated
  - id: state-storage.command.illegal-use-derived-as-truth
    signature: illegal runtime decision based on derived or telemetry family instead of canonical state
    allowed_statuses:
      - state-storage.status.canonical_current
      - state-storage.status.derived_current
      - state-storage.status.derived_stale
    requires:
      - state-storage.invariant.derived_families_never_become_source_of_truth
    emits:
      - state-storage.event.policy.violation
  - id: state-storage.command.illegal-cross-project-write
    signature: illegal write or reference from one project scope into another project scope
    allowed_statuses:
      - state-storage.status.ready
      - state-storage.status.canonical_current
      - state-storage.status.derived_current
      - state-storage.status.derived_stale
    requires:
      - state-storage.invariant.cross_project_reference_requires_explicit_global_family
    emits:
      - state-storage.event.policy.violation
```
<!-- FORMAL-SPEC:END -->
