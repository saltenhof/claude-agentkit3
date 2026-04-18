---
id: formal.llm-evaluations.state-machine
title: LLM Evaluations State Machine
status: active
doc_kind: spec
context: llm-evaluations
spec_kind: state-machine
version: 1
prose_refs:
  - concept/technical-design/34_llm_bewertungen_adversarial_testing_runtime.md
---

# LLM Evaluations State Machine

Der Evaluate-Kontext reicht von den drei parallelen Layer-2-Reviews
bis zum abgeschlossenen Adversarial-Run.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.llm-evaluations.state-machine
schema_version: 1
kind: state-machine
context: llm-evaluations
states:
  - id: llm-evaluations.status.pending
    initial: true
  - id: llm-evaluations.status.layer2_running
  - id: llm-evaluations.status.layer2_aggregated
  - id: llm-evaluations.status.layer3_running
  - id: llm-evaluations.status.completed
    terminal: true
  - id: llm-evaluations.status.failed
    terminal: true
transitions:
  - id: llm-evaluations.transition.pending_to_layer2_running
    from: llm-evaluations.status.pending
    to: llm-evaluations.status.layer2_running
  - id: llm-evaluations.transition.layer2_running_to_layer2_aggregated
    from: llm-evaluations.status.layer2_running
    to: llm-evaluations.status.layer2_aggregated
    guard: llm-evaluations.invariant.layer2_requires_three_verdict_sources
  - id: llm-evaluations.transition.layer2_aggregated_to_layer3_running
    from: llm-evaluations.status.layer2_aggregated
    to: llm-evaluations.status.layer3_running
    guard: llm-evaluations.invariant.layer3_requires_clean_layer2_pass
  - id: llm-evaluations.transition.layer3_running_to_completed
    from: llm-evaluations.status.layer3_running
    to: llm-evaluations.status.completed
    guard: llm-evaluations.invariant.adversarial_requires_sparring_and_test_execution
  - id: llm-evaluations.transition.layer2_running_to_failed
    from: llm-evaluations.status.layer2_running
    to: llm-evaluations.status.failed
  - id: llm-evaluations.transition.layer3_running_to_failed
    from: llm-evaluations.status.layer3_running
    to: llm-evaluations.status.failed
compound_rules:
  - id: llm-evaluations.rule.remediation-rounds-carry-forward-open-findings
    description: In remediation rounds the previous blocking findings must re-enter Layer 2 through explicit finding-resolution context and may not disappear silently.
```
<!-- FORMAL-SPEC:END -->
