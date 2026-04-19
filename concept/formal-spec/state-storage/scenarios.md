---
id: formal.state-storage.scenarios
title: State Storage Scenarios
status: active
doc_kind: spec
context: state-storage
spec_kind: scenario-set
version: 1
prose_refs:
  - concept/technical-design/18_relationales_abbildungsmodell_postgres.md
  - concept/technical-design/16_qa_telemetrie_aggregation_dashboard.md
  - concept/technical-design/53_story_reset_service_recovery_flow.md
---

# State Storage Scenarios

Diese Traces pruefen den formalen Speicherschnitt und seine kritischen
Betriebsfaelle.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.state-storage.scenarios
schema_version: 1
kind: scenario-set
context: state-storage
scenarios:
  - id: state-storage.scenario.canonical-write-then-derived-materialization
    start:
      status: state-storage.status.ready
    trace:
      - command: state-storage.command.persist-canonical-state
      - command: state-storage.command.materialize-derived-families
    expected_end:
      status: state-storage.status.derived_current
    requires:
      - state-storage.invariant.tenant_scoped_families_require_project_key
      - state-storage.invariant.exactly_one_canonical_family_per_fact
      - state-storage.invariant.derived_families_never_become_source_of_truth
  - id: state-storage.scenario.telemetry-degradation-does-not-block-progress
    start:
      status: state-storage.status.canonical_current
    trace:
      - command: state-storage.command.append-telemetry
      - command: state-storage.command.materialize-derived-families
    expected_end:
      status: state-storage.status.derived_current
    requires:
      - state-storage.invariant.telemetry_never_blocks_story_start
  - id: state-storage.scenario.derived-family-becomes-stale-then-rebuilds
    start:
      status: state-storage.status.derived_current
    trace:
      - command: state-storage.command.mark-derived-stale
      - command: state-storage.command.materialize-derived-families
    expected_end:
      status: state-storage.status.derived_current
    requires:
      - state-storage.invariant.rebuild_only_families_require_canonical_source
  - id: state-storage.scenario.story-reset-purges-dependent-families
    start:
      status: state-storage.status.derived_current
    trace:
      - command: state-storage.command.purge-story-runtime
    expected_end:
      status: state-storage.status.purged
    requires:
      - state-storage.invariant.reset_closure_cleans_dependent_families
      - state-storage.invariant.noncanonical_families_must_not_survive_reset_as_active
  - id: state-storage.scenario.derived-family-used-as-truth-is-blocked
    start:
      status: state-storage.status.derived_current
    trace:
      - command: state-storage.command.illegal-use-derived-as-truth
    expected_end:
      status: state-storage.status.blocked
    requires:
      - state-storage.invariant.derived_families_never_become_source_of_truth
  - id: state-storage.scenario.cross-project-write-is-blocked
    start:
      status: state-storage.status.ready
    trace:
      - command: state-storage.command.illegal-cross-project-write
    expected_end:
      status: state-storage.status.blocked
    requires:
      - state-storage.invariant.cross_project_reference_requires_explicit_global_family
```
<!-- FORMAL-SPEC:END -->
