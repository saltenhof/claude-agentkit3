---
id: formal.llm-evaluations.invariants
title: LLM Evaluations Invariants
status: active
doc_kind: spec
context: llm-evaluations
spec_kind: invariant-set
version: 1
prose_refs:
  - concept/technical-design/34_llm_bewertungen_adversarial_testing_runtime.md
---

# LLM Evaluations Invariants

Diese Invarianten definieren die zwingenden Regeln fuer Layer 2 und
Layer 3.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.llm-evaluations.invariants
schema_version: 1
kind: invariant-set
context: llm-evaluations
invariants:
  - id: llm-evaluations.invariant.layer2_requires_three_verdict_sources
    scope: process
    rule: layer 2 is complete only when qa_review semantic_review and implementation-fidelity all produced verdicts
  - id: llm-evaluations.invariant.layer2_fail_is_blocking
    scope: outcome
    rule: a single FAIL from layer 2 prevents a PASS aggregation and blocks the transition to adversarial testing
  - id: llm-evaluations.invariant.layer3_requires_clean_layer2_pass
    scope: process
    rule: adversarial testing may start only after a non-blocking aggregated layer 2 result
  - id: llm-evaluations.invariant.adversarial_requires_sparring_and_test_execution
    scope: process
    rule: a completed adversarial run must have at least one sparring interaction and at least one executed test
  - id: llm-evaluations.invariant.mandatory_targets_propagate_from_layer2
    scope: process
    rule: mandatory adversarial targets are derived from layer 2 findings and may not be dropped before layer 3 execution
  - id: llm-evaluations.invariant.remediation_round_requires_resolution_tracking
    scope: remediation
    rule: remediation rounds must carry previous blocking findings with explicit resolution statuses into the next layer 2 run
```
<!-- FORMAL-SPEC:END -->
