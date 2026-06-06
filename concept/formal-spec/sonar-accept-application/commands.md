---
id: formal.sonar-accept-application.commands
title: Sonar Accept Application Commands
status: active
doc_kind: spec
context: sonar-accept-application
spec_kind: command-set
version: 1
prose_refs:
  - concept/technical-design/27_verify_pipeline_closure_orchestration.md
---

# Sonar Accept Application Commands

Der Worker stellt einen synchronen Antrag (`apply`); AK3 entscheidet auf Basis
der zwei LLM-Voten und setzt entweder `Accepted` (`approve`) oder gibt das
Feedback sofort zurueck (`reject`). Nur AK3 fuehrt `approve`/`reject` aus — der
Worker hat keine Sonar-Admin-Rechte (FK-27 §27.6b.4).

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.sonar-accept-application.commands
schema_version: 1
kind: command-set
context: sonar-accept-application
commands:
  - id: sonar-accept-application.command.apply
    signature: POST /v1/verify/accept-requests {story_id, rule_key, file_path, rationale}
    allowed_statuses:
      - sonar-accept-application.status.requested
    requires:
      - sonar-accept-application.invariant.request_requires_rule_file_and_rationale
      - sonar-accept-application.invariant.two_distinct_models_one_goal_prompt
    emits:
      - sonar-accept-application.event.application-requested
  - id: sonar-accept-application.command.approve
    signature: internal AK3 action on unanimous yes
    allowed_statuses:
      - sonar-accept-application.status.pending
    requires:
      - sonar-accept-application.invariant.accept_requires_unanimous_yes
      - sonar-accept-application.invariant.only_ak3_sets_accepted
      - sonar-accept-application.invariant.accept_writes_ledger_entry
    emits:
      - sonar-accept-application.event.accepted
  - id: sonar-accept-application.command.reject
    signature: internal AK3 action on any no
    allowed_statuses:
      - sonar-accept-application.status.pending
    requires:
      - sonar-accept-application.invariant.any_no_returns_feedback_immediately
    emits:
      - sonar-accept-application.event.rejected
```
<!-- FORMAL-SPEC:END -->
