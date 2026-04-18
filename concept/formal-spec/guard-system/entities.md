---
id: formal.guard-system.entities
title: Guard System Entities
status: active
doc_kind: spec
context: guard-system
spec_kind: entity-set
version: 1
prose_refs:
  - concept/technical-design/30_hook_adapter_guard_enforcement.md
  - concept/technical-design/31_branch_guard_orchestrator_guard_artefaktschutz.md
---

# Guard System Entities

Das GuardSystem benoetigt wenige, aber fachlich stabile Kernentitaeten.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.guard-system.entities
schema_version: 1
kind: entity-set
context: guard-system
entities:
  - id: guard-system.entity.guard-check
    identity_key: check_id
    attributes:
      - check_id
      - guard_id
      - tool_name
      - operation_signature
      - story_id
      - decision
  - id: guard-system.entity.guard-rule
    identity_key: guard_id
    attributes:
      - guard_id
      - scope
      - matcher
      - enforcement_mode
  - id: guard-system.entity.official-exception
    identity_key: exception_id
    attributes:
      - exception_id
      - guard_id
      - allowed_operation
      - reason
```
<!-- FORMAL-SPEC:END -->
