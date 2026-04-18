---
id: formal.integrity-gate.invariants
title: Integrity Gate Invariants
status: active
doc_kind: spec
context: integrity-gate
spec_kind: invariant-set
version: 1
prose_refs:
  - concept/technical-design/35_integrity_gate_governance_beobachtung_eskalation.md
---

# Integrity Gate Invariants

Diese Invarianten definieren die nicht verhandelbaren Closure-
Voraussetzungen.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.integrity-gate.invariants
schema_version: 1
kind: invariant-set
context: integrity-gate
invariants:
  - id: integrity-gate.invariant.mandatory_artifacts_checked_first
    scope: process
    rule: mandatory artifact validation must run before any dimension or telemetry check and a missing mandatory artifact immediately fails the gate
  - id: integrity-gate.invariant.only_current_valid_run_is_evaluated
    scope: run
    rule: the gate may evaluate only artifact records and execution events of the current valid run_id for the story
  - id: integrity-gate.invariant.implementation_requires_llm_and_adversarial_evidence
    scope: mode
    rule: implementation and bugfix stories require llm review semantic review and adversarial evidence before the gate may pass
  - id: integrity-gate.invariant.override_requires_explicit_human_reason
    scope: governance
    rule: a gate override requires an explicit human-issued reason and may not be synthesized automatically by the orchestrator
  - id: integrity-gate.invariant.gate_failures_are_auditable
    scope: audit
    rule: every failed gate produces audit-visible fail codes before any human may decide on override or recovery
```
<!-- FORMAL-SPEC:END -->
