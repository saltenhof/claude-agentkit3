---
id: formal.story-contracts.entities
title: Story Contract Entities
status: active
doc_kind: spec
context: story-contracts
spec_kind: entity-set
version: 1
prose_refs:
  - concept/technical-design/59_story_contract_axes_and_combination_matrix.md
  - concept/technical-design/24_story_type_mode_terminalitaet.md
---

# Story Contract Entities

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.story-contracts.entities
schema_version: 1
kind: entity-set
context: story-contracts
entities:
  - id: story-contracts.entity.story-contract
    category: aggregate-root
    description: canonical persistent story contract carrying story_type and optional implementation_contract
  - id: story-contracts.entity.runtime-classification
    category: child-entity
    description: derived runtime view carrying operating_mode and execution_route for a concrete run
  - id: story-contracts.entity.story-outcome
    category: child-entity
    description: terminal outcome view carrying terminal_state and optional exit_class
```
<!-- FORMAL-SPEC:END -->

