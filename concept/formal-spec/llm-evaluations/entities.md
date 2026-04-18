---
id: formal.llm-evaluations.entities
title: LLM Evaluations Entities
status: active
doc_kind: spec
context: llm-evaluations
spec_kind: entity-set
version: 1
prose_refs:
  - concept/technical-design/34_llm_bewertungen_adversarial_testing_runtime.md
---

# LLM Evaluations Entities

Layer 2 und Layer 3 erzeugen Evidence-Artefakte, keine finalen
Closure-Entscheidungen.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.llm-evaluations.entities
schema_version: 1
kind: entity-set
context: llm-evaluations
entities:
  - id: llm-evaluations.entity.layer2-batch
    identity_key: batch_id
    attributes:
      - batch_id
      - story_id
      - run_id
      - status
      - remediation_round
  - id: llm-evaluations.entity.evaluation-result
    identity_key: result_id
    attributes:
      - result_id
      - batch_id
      - review_role
      - check_set
      - status
  - id: llm-evaluations.entity.adversarial-run
    identity_key: adversarial_id
    attributes:
      - adversarial_id
      - batch_id
      - sandbox_path
      - status
      - mandatory_targets
  - id: llm-evaluations.entity.finding-resolution
    identity_key: resolution_id
    attributes:
      - resolution_id
      - batch_id
      - prior_finding_id
      - resolution_status
```
<!-- FORMAL-SPEC:END -->
