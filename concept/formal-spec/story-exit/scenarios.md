---
id: formal.story-exit.scenarios
title: Story Exit Scenarios
status: active
doc_kind: spec
context: story-exit
spec_kind: scenario-set
version: 1
prose_refs:
  - concept/technical-design/58_story_exit_human_takeover_handoff.md
---

# Story Exit Scenarios

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.story-exit.scenarios
schema_version: 1
kind: scenario-set
context: story-exit
scenarios:
  - id: story-exit.scenario.human-takeover-exit-returns-to-ai-augmented
    start:
      status: story-exit.status.eligible
    trace:
      - command: story-exit.command.exit-story
      - command: story-exit.command.run-exit-gate
      - command: story-exit.command.revoke-binding
    expected_end:
      status: story-exit.status.ai_augmented_resumed
  - id: story-exit.scenario.invalid-exit-request-is-rejected
    start:
      status: story-exit.status.exit_requested
    trace:
      - command: story-exit.command.run-exit-gate
    expected_end:
      status: story-exit.status.exit_rejected
```
<!-- FORMAL-SPEC:END -->
