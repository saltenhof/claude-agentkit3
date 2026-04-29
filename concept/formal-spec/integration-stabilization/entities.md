---
id: formal.integration-stabilization.entities
title: Integration Stabilization Entities
status: active
doc_kind: spec
context: integration-stabilization
spec_kind: entity-set
version: 1
prose_refs:
  - concept/technical-design/05_integration_stabilization_contract.md
---

# Integration Stabilization Entities

Die Integrationsstabilisierung arbeitet mit eigenem Manifest und Budget,
bleibt aber Teil einer normalen Implementation-Story.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.integration-stabilization.entities
schema_version: 1
kind: entity-set
context: integration-stabilization
entities:
  - id: integration-stabilization.entity.integration-scope-manifest
    category: aggregate-root
    description: approved manifest defining target seams allowed productive paths integration targets and budget for the stabilization contract
  - id: integration-stabilization.entity.manifest-approval-record
    category: entity
    description: attested approval record binding manifest hash version and run identity to explicit human or admin authority
  - id: integration-stabilization.entity.integration-target
    category: child-entity
    description: one declared end-to-end or cross-component target that must pass before closure is allowed
  - id: integration-stabilization.entity.stabilization-budget
    category: child-entity
    description: hard budget limiting loop count newly touched surfaces and declared contract change classes
  - id: integration-stabilization.entity.stabilization-cycle
    category: child-entity
    description: one stabilize then re-verify iteration inside the approved contract
  - id: integration-stabilization.entity.manifest-amendment-request
    category: entity
    description: explicit human-reviewed request to widen or amend the approved integration scope manifest
```
<!-- FORMAL-SPEC:END -->
