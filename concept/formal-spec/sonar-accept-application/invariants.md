---
id: formal.sonar-accept-application.invariants
title: Sonar Accept Application Invariants
status: active
doc_kind: spec
context: sonar-accept-application
spec_kind: invariant-set
version: 1
prose_refs:
  - concept/technical-design/27_verify_pipeline_closure_orchestration.md
  - concept/technical-design/41_failure_corpus_pattern_promotion_check_factory.md
---

# Sonar Accept Application Invariants

Diese Invarianten normieren den synchronen, worker-initiierten
Accept-Self-Assessment-Schritt (FK-27 §27.6b). Prosa-SSOT des Verfahrens bleibt
FK-27 §27.6b; das Ledger-Schema gehoert FK-33 §33.6.4 und wird hier nur
referenziert.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.sonar-accept-application.invariants
schema_version: 1
kind: invariant-set
context: sonar-accept-application
invariants:
  - id: sonar-accept-application.invariant.request_requires_rule_file_and_rationale
    scope: process
    rule: the synchronous worker-initiated accept-self-assessment request (FK-27 27.6b) must carry at minimum the sonar rule_key, the code file_path where the issue was raised, and the worker rationale before the request may move from requested to pending
  - id: sonar-accept-application.invariant.two_distinct_models_one_goal_prompt
    scope: process
    rule: the accept assessment asks exactly two LLMs that are two distinct models with one shared goal-oriented prompt from a single prompt-template whose only injected variable is the worker rationale plus the issue context; the prompt is not skeptical or adversarial but judges by the goal of high-quality software, neither artificial Sonar-green nor reflexive rejection
  - id: sonar-accept-application.invariant.accept_requires_unanimous_yes
    scope: outcome
    rule: an issue transitions to accepted only when both LLMs return yes; the quorum is the proposing worker plus the two LLMs and requires unanimity (requested then pending then accepted)
  - id: sonar-accept-application.invariant.only_ak3_sets_accepted
    scope: governance
    rule: only AK3 sets the accepted flag via a scoped admin token; the worker has no sonar admin rights and no agent self-approves its own acceptance
  - id: sonar-accept-application.invariant.any_no_returns_feedback_immediately
    scope: process
    rule: if any LLM returns no the request transitions to rejected and the two reasonings are returned synchronously and immediately to the worker as feedback so the worker fixes now, avoiding a forced separate remediation cycle
  - id: sonar-accept-application.invariant.accept_writes_ledger_entry
    scope: process
    rule: a successful acceptance produces exactly one canonical FK-33-owned ledger entry (the deterministic-checks accepted-exception-ledger-entry); this context does not define its own ledger schema and does not restate its fields
  - id: sonar-accept-application.invariant.accept_frequency_is_failure_corpus_signal
    scope: process
    rule: rule-acceptance frequency is tracked across all stories never per single story and when the share of stories accepting a rule exceeds the configurable threshold field sonarqube.accept_frequency_fc_threshold (FK-03) the rule becomes a light signal to the failure corpus (FK-41 41.10); it is deliberately light with no tamper-proof or fortress mechanism
```
<!-- FORMAL-SPEC:END -->
