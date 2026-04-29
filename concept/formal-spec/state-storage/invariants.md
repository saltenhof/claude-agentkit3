---
id: formal.state-storage.invariants
title: State Storage Invariants
status: active
doc_kind: spec
context: state-storage
spec_kind: invariant-set
version: 1
prose_refs:
  - concept/technical-design/17_fachliches_datenmodell_ownership.md
  - concept/technical-design/18_relationales_abbildungsmodell_postgres.md
  - concept/technical-design/69_qa_telemetrie_aggregation_dashboard.md
  - concept/technical-design/53_story_reset_service_recovery_flow.md
---

# State Storage Invariants

Diese Invarianten beschreiben die fachlich harte Speicherseite von AK3.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.state-storage.invariants
schema_version: 1
kind: invariant-set
context: state-storage
invariants:
  - id: state-storage.invariant.tenant_scoped_families_require_project_key
    scope: storage
    rule: every tenant-scoped canonical or derived family must carry project_key as mandatory scope component
  - id: state-storage.invariant.cross_project_reference_requires_explicit_global_family
    scope: storage
    rule: no canonical or derived family may normatively reference another project scope unless the target family is explicitly declared global
  - id: state-storage.invariant.exactly_one_canonical_family_per_fact
    scope: canonicality
    rule: each storage fact may have exactly one canonical record family and must not be duplicated as canonical in json, sqlite, telemetry, analytics, or projection families
  - id: state-storage.invariant.derived_families_never_become_source_of_truth
    scope: canonicality
    rule: derived, telemetry, analytics, and projection families may never act as source of truth for runtime or governance decisions
  - id: state-storage.invariant.export_json_never_trusted_by_runtime
    scope: canonicality
    rule: filesystem json exports of canonical, derived, or projected families may act only as export, audit, debug, or compatibility material and must never be trusted as runtime or governance truth
  - id: state-storage.invariant.mutating_families_have_single_writer
    scope: ownership
    rule: each mutating record family must have exactly one owner context with mutation authority unless the family is explicitly append_only
  - id: state-storage.invariant.telemetry_never_blocks_story_start
    scope: liveness
    rule: telemetry append or telemetry degradation must never block story start, story resume, or canonical state persistence
  - id: state-storage.invariant.reset_policy_declared_for_every_family
    scope: reset
    rule: every record family must declare one explicit reset policy of delete, invalidate, retain, or rebuild_required
  - id: state-storage.invariant.reset_closure_cleans_dependent_families
    scope: reset
    rule: when canonical story runtime state is reset all dependent runtime, telemetry, projection, and analytics families must be deleted, invalidated, or marked rebuild_required in the same official reset flow
  - id: state-storage.invariant.noncanonical_families_must_not_survive_reset_as_active
    scope: reset
    rule: no non-canonical family affected by a story reset may remain active and interpretable as current state after the reset completes
  - id: state-storage.invariant.rebuild_only_families_require_canonical_source
    scope: rebuild
    rule: read-model and analytics rebuild is legal only from canonical families of the same scope and never from telemetry or other derived families
```
<!-- FORMAL-SPEC:END -->
