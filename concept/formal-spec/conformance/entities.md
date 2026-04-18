---
id: formal.conformance.entities
title: Conformance Entities
status: active
doc_kind: spec
context: conformance
spec_kind: entity-set
version: 1
prose_refs:
  - concept/technical-design/32_dokumententreue_conformance_service.md
---

# Conformance Entities

Der ConformanceService bewertet einen Gegenstand gegen kuratierte
Referenzen und erzeugt ein normatives Verdikt.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.conformance.entities
schema_version: 1
kind: entity-set
context: conformance
entities:
  - id: conformance.entity.assessment
    identity_key: assessment_id
    attributes:
      - assessment_id
      - story_id
      - run_id
      - level
      - subject_kind
      - status
  - id: conformance.entity.reference-bundle
    identity_key: bundle_id
    attributes:
      - bundle_id
      - assessment_id
      - reference_sources
      - size_bytes
      - transfer_mode
  - id: conformance.entity.fidelity-result
    identity_key: result_id
    attributes:
      - result_id
      - assessment_id
      - level
      - status
      - reason
      - references_used
```
<!-- FORMAL-SPEC:END -->
