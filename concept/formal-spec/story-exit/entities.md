---
id: formal.story-exit.entities
title: Story Exit Entities
status: active
doc_kind: spec
context: story-exit
spec_kind: entity-set
version: 1
prose_refs:
  - concept/technical-design/58_story_exit_human_takeover_handoff.md
  - concept/technical-design/90_schema_katalog.md
---

# Story Exit Entities

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.story-exit.entities
schema_version: 1
kind: entity-set
context: story-exit
entities:
  - id: story-exit.entity.story-exit-record
    category: aggregate-root
    description: canonical audit record for an administratively approved story exit into human takeover
  - id: story-exit.entity.viability-dossier
    category: child-entity
    description: lightweight system-prepared dossier summarizing why the story contract is being ended
  - id: story-exit.entity.exit-manifest-snapshot
    category: child-entity
    description: last bound story scope manifest budget and run snapshot captured at exit time
```
<!-- FORMAL-SPEC:END -->
