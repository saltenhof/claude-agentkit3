---
id: formal.llm-evaluations.commands
title: LLM Evaluations Commands
status: active
doc_kind: spec
context: llm-evaluations
spec_kind: command-set
version: 1
prose_refs:
  - concept/technical-design/48_adversarial_testing_runtime.md
  - concept/technical-design/91_api_event_katalog.md
---

# LLM Evaluations Commands

Layer 2 und Layer 3 werden ausschliesslich ueber die offiziellen
Verify-Pfade gestartet.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.llm-evaluations.commands
schema_version: 1
kind: command-set
context: llm-evaluations
commands:
  - id: llm-evaluations.command.run-layer2-reviews
    signature: run qa_review semantic_review and doc_fidelity in parallel after layer1 PASS
    allowed_statuses:
      - llm-evaluations.status.pending
    requires:
      - llm-evaluations.invariant.layer2_requires_three_verdict_sources
    emits:
      - llm-evaluations.event.layer2.started
      - llm-evaluations.event.layer2.completed
  - id: llm-evaluations.command.aggregate-layer2-results
    signature: aggregate all layer2 checks into one blocking verdict set
    allowed_statuses:
      - llm-evaluations.status.layer2_running
    requires:
      - llm-evaluations.invariant.layer2_fail_is_blocking
    emits:
      - llm-evaluations.event.layer2.aggregated
  - id: llm-evaluations.command.run-adversarial
    signature: spawn adversarial sub-agent in sandbox with mandatory targets and sparring duty
    allowed_statuses:
      - llm-evaluations.status.layer2_aggregated
    requires:
      - llm-evaluations.invariant.layer3_requires_clean_layer2_pass
      - llm-evaluations.invariant.mandatory_targets_propagate_from_layer2
    emits:
      - llm-evaluations.event.adversarial.started
      - llm-evaluations.event.adversarial.completed
  - id: llm-evaluations.command.rerun-layer2-remediation
    signature: rerun layer2 with prior findings and resolution statuses after remediation
    allowed_statuses:
      - llm-evaluations.status.pending
    requires:
      - llm-evaluations.invariant.remediation_round_requires_resolution_tracking
    emits:
      - llm-evaluations.event.layer2.started
      - llm-evaluations.event.layer2.completed
```
<!-- FORMAL-SPEC:END -->
