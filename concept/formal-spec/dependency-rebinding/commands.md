---
id: formal.dependency-rebinding.commands
title: Dependency Rebinding Commands
status: active
doc_kind: spec
context: dependency-rebinding
spec_kind: command-set
version: 1
prose_refs:
  - concept/technical-design/54_story_split_service_scope_explosion.md
---

# Dependency Rebinding Commands

Rebinding ist ein offizieller System-Subflow des Story-Splits, kein
freier manueller Bearbeitungspfad.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.dependency-rebinding.commands
schema_version: 1
kind: command-set
context: dependency-rebinding
commands:
  - id: dependency-rebinding.command.validate
    signature: internal validate_dependency_rebinding <split_id>
    allowed_statuses:
      - dependency-rebinding.status.requested
    requires:
      - dependency-rebinding.invariant.mapping_requires_successors_created
      - dependency-rebinding.invariant.no_silent_drop
    emits:
      - dependency-rebinding.event.rebinding.started
      - dependency-rebinding.event.rebinding.validated
      - dependency-rebinding.event.rebinding.rejected
  - id: dependency-rebinding.command.apply
    signature: internal apply_dependency_rebinding <split_id>
    allowed_statuses:
      - dependency-rebinding.status.validated
    requires:
      - dependency-rebinding.invariant.deterministic_target_selection
      - dependency-rebinding.invariant.graph_integrity_preserved
    emits:
      - dependency-rebinding.event.edge.rebound
      - dependency-rebinding.event.rebinding.completed
      - dependency-rebinding.event.rebinding.rejected
```
<!-- FORMAL-SPEC:END -->
