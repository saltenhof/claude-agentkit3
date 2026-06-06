---
id: formal.sonar-accept-application.state-machine
title: Sonar Accept Application State Machine
status: active
doc_kind: spec
context: sonar-accept-application
spec_kind: state-machine
version: 1
prose_refs:
  - concept/technical-design/27_verify_pipeline_closure_orchestration.md
---

# Sonar Accept Application State Machine

Der Lebenszyklus eines Accept-Antrags: `requested → pending → accepted |
rejected`. Einstimmigkeit beider LLMs fuehrt nach `accepted`; mindestens ein
`no` fuehrt nach `rejected` mit sofortigem Feedback an den Worker.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.sonar-accept-application.state-machine
schema_version: 1
kind: state-machine
context: sonar-accept-application
states:
  - id: sonar-accept-application.status.requested
    initial: true
  - id: sonar-accept-application.status.pending
  - id: sonar-accept-application.status.accepted
    terminal: true
  - id: sonar-accept-application.status.rejected
    terminal: true
transitions:
  - id: sonar-accept-application.transition.requested_to_pending
    from: sonar-accept-application.status.requested
    to: sonar-accept-application.status.pending
    guard: sonar-accept-application.invariant.request_requires_rule_file_and_rationale
  - id: sonar-accept-application.transition.pending_to_accepted
    from: sonar-accept-application.status.pending
    to: sonar-accept-application.status.accepted
    guard: sonar-accept-application.invariant.accept_requires_unanimous_yes
  - id: sonar-accept-application.transition.pending_to_rejected
    from: sonar-accept-application.status.pending
    to: sonar-accept-application.status.rejected
    guard: sonar-accept-application.invariant.any_no_returns_feedback_immediately
compound_rules:
  - id: sonar-accept-application.rule.accepted-means-ak3-flipped-flag-with-ledger
    description: An issue counts as Accepted only when the terminal status is accepted, which AK3 reaches solely on unanimous yes of the two distinct-model LLMs and which always records a ledger entry; the worker never reaches this state by itself.
```
<!-- FORMAL-SPEC:END -->
