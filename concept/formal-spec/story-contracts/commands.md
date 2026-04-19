---
id: formal.story-contracts.commands
title: Story Contract Commands
status: active
doc_kind: spec
context: story-contracts
spec_kind: command-set
version: 1
prose_refs:
  - concept/technical-design/59_story_contract_axes_and_combination_matrix.md
---

# Story Contract Commands

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.story-contracts.commands
schema_version: 1
kind: command-set
context: story-contracts
commands:
  - id: story-contracts.command.classify-story-contract
    actor: deterministic_system
  - id: story-contracts.command.derive-runtime-classification
    actor: deterministic_system
  - id: story-contracts.command.mark-story-done
    actor: deterministic_system
  - id: story-contracts.command.cancel-story-administratively
    actor: human_cli
```
<!-- FORMAL-SPEC:END -->

