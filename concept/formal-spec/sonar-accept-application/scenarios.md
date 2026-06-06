---
id: formal.sonar-accept-application.scenarios
title: Sonar Accept Application Scenarios
status: active
doc_kind: spec
context: sonar-accept-application
spec_kind: scenario-set
version: 1
prose_refs:
  - concept/technical-design/27_verify_pipeline_closure_orchestration.md
---

# Sonar Accept Application Scenarios

Diese Traces pruefen die beiden Endfaelle: beidseitiges `yes` fuehrt nach
`accepted`; mindestens ein `no` fuehrt nach `rejected` mit Feedback an den
Worker.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.sonar-accept-application.scenarios
schema_version: 1
kind: scenario-set
context: sonar-accept-application
scenarios:
  - id: sonar-accept-application.scenario.both-yes-accepted
    start:
      status: sonar-accept-application.status.requested
    trace:
      - command: sonar-accept-application.command.apply
      - command: sonar-accept-application.command.approve
    expected_end:
      status: sonar-accept-application.status.accepted
    requires:
      - sonar-accept-application.invariant.accept_requires_unanimous_yes
      - sonar-accept-application.invariant.only_ak3_sets_accepted
      - sonar-accept-application.invariant.accept_writes_ledger_entry
  - id: sonar-accept-application.scenario.any-no-rejected
    start:
      status: sonar-accept-application.status.requested
    trace:
      - command: sonar-accept-application.command.apply
      - command: sonar-accept-application.command.reject
    expected_end:
      status: sonar-accept-application.status.rejected
    requires:
      - sonar-accept-application.invariant.any_no_returns_feedback_immediately
```
<!-- FORMAL-SPEC:END -->
