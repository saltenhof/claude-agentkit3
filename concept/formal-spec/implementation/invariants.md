---
id: formal.implementation.invariants
title: Implementation Invariants
status: active
doc_kind: spec
context: implementation
spec_kind: invariant-set
version: 1
prose_refs:
  - concept/technical-design/39_phase_state_persistenz.md
  - concept/domain-design/02-pipeline-orchestrierung.md
  - concept/technical-design/27_verify_pipeline_closure_orchestration.md
---

# Implementation Invariants

Diese Invarianten definieren den zulaessigen Herstellungsprozess.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.implementation.invariants
schema_version: 1
kind: invariant-set
context: implementation
invariants:
  - id: implementation.invariant.start_requires_setup_or_exploration_gate
    scope: process
    rule: implementation may start only after setup completed for execution mode or after exploration gate approved for exploration mode
  - id: implementation.invariant.completed_requires_manifest_and_handover
    scope: outcome
    rule: implementation may complete only after worker manifest and handover artifacts exist and are structurally valid
  - id: implementation.invariant.worker_blocked_escalates
    scope: governance
    rule: a worker manifest with BLOCKED status escalates implementation instead of leaving the phase in a resumable in-progress state
  - id: implementation.invariant.implementation-does-not-verify
    scope: boundary
    rule: implementation records produced outputs and handover but does not decide verification outcome or story closure
```
<!-- FORMAL-SPEC:END -->
