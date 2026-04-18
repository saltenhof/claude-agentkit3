---
id: formal.story-creation.commands
title: Story Creation Commands
status: active
doc_kind: spec
context: story-creation
spec_kind: command-set
version: 1
prose_refs:
  - concept/technical-design/21_story_creation_pipeline.md
  - concept/technical-design/12_github_integration_repo_operationen.md
  - concept/technical-design/91_api_event_katalog.md
  - concept/technical-design/54_story_split_service_scope_explosion.md
---

# Story Creation Commands

Story-Creation ist ein offizieller Skill- und Pipeline-Pfad, kein
freies `gh issue create` durch Agents.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.story-creation.commands
schema_version: 1
kind: command-set
context: story-creation
commands:
  - id: story-creation.command.create
    signature: create-userstory
    allowed_statuses:
      - story-creation.status.draft
    requires:
      - story-creation.invariant.validation_requires_vectordb_and_goal_fidelity
      - story-creation.invariant.classification_requires_required_fields
    emits:
      - story-creation.event.creation.started
      - story-creation.event.story.validated
      - story-creation.event.story.classified
      - story-creation.event.story.backlog_created
  - id: story-creation.command.export-story-md
    signature: agentkit export-story-md --story-id <story_id> --issue-nr <issue_nr> --story-dir <story_dir>
    allowed_statuses:
      - story-creation.status.backlog
    requires:
      - story-creation.invariant.story_md_export_after_issue_creation
    emits:
      - story-creation.event.story_md.exported
      - story-creation.event.story_md.indexed
  - id: story-creation.command.approve
    signature: human project status change to Approved
    allowed_statuses:
      - story-creation.status.exported
    requires:
      - story-creation.invariant.approval_requires_human_decision
    emits:
      - story-creation.event.story.approved
  - id: story-creation.command.illegal-export-before-issue
    signature: export story.md before GitHub issue/backlog creation
    allowed_statuses: []
    requires:
      - story-creation.invariant.story_md_export_after_issue_creation
    emits:
      - story-creation.event.creation.rejected
```
<!-- FORMAL-SPEC:END -->
