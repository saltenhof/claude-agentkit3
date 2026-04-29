---
id: formal.setup-preflight.scenarios
title: Setup Preflight Scenarios
status: active
doc_kind: spec
context: setup-preflight
spec_kind: scenario-set
version: 1
prose_refs:
  - concept/technical-design/22_setup_preflight_worktree_guard_activation.md
  - concept/technical-design/45_phase_runner_cli.md
  - concept/domain-design/02-pipeline-orchestrierung.md
---

# Setup Preflight Scenarios

Diese Traces pruefen die Startfaehigkeit und den fail-closed Pfad.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.setup-preflight.scenarios
schema_version: 1
kind: scenario-set
context: setup-preflight
scenarios:
  - id: setup-preflight.scenario.code-story-happy-path
    start:
      status: setup-preflight.status.requested
    trace:
      - command: setup-preflight.command.run-phase
    expected_end:
      status: setup-preflight.status.completed
    requires:
      - setup-preflight.invariant.all_nine_checks_pass_before_context
      - setup-preflight.invariant.code_stories_require_worktree_setup
  - id: setup-preflight.scenario.preflight-fails
    start:
      status: setup-preflight.status.requested
    trace:
      - command: setup-preflight.command.run-phase
    expected_end:
      status: setup-preflight.status.failed
    requires:
      - setup-preflight.invariant.fail_closed_on_any_preflight_failure
  - id: setup-preflight.scenario.research-shortcut
    start:
      status: setup-preflight.status.requested
    trace:
      - command: setup-preflight.command.run-phase
    expected_end:
      status: setup-preflight.status.completed
    requires:
      - setup-preflight.invariant.noncode-stories-skip-worktrees
```
<!-- FORMAL-SPEC:END -->
