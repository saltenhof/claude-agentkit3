---
id: formal.truth-boundary-checker.invariants
title: Truth Boundary Checker Invariants
status: active
doc_kind: spec
context: truth-boundary-checker
spec_kind: invariant-set
version: 1
prose_refs:
  - concept/technical-design/06_truth_boundary_and_concept_code_contract_checker.md
---

# Truth Boundary Checker Invariants

Diese Invarianten definieren die scharfe Code-Grenze gegen
Datei-als-Wahrheit-Regressionspfade.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.truth-boundary-checker.invariants
schema_version: 1
kind: invariant-set
context: truth-boundary-checker
protected_module_prefixes:
  - agentkit.governance
  - agentkit.pipeline
  - agentkit.qa.structural
allowed_module_prefixes:
  - agentkit.cli
  - agentkit.migrations
  - agentkit.utils.io
  - tests
forbidden_loader_symbols:
  - load_json_object
  - load_json_safe
  - load_verify_decision_artifact
  - load_phase_state
  - load_story_context
forbidden_import_modules:
  - agentkit.pipeline.state
  - agentkit.qa.artifacts
forbidden_json_truth_filenames:
  - context.json
  - decision.json
  - verify-decision.json
  - structural.json
  - qa_review.json
  - semantic_review.json
  - semantic-review.json
  - adversarial.json
  - phase-state.json
  - closure.json
forbidden_json_truth_globs:
  - phase-state-*.json
invariants:
  - id: truth-boundary-checker.invariant.protected_modules_must_not_read_story_export_json
    scope: static-analysis
    rule: protected runtime and governance modules may not read AK3 story export json files directly
  - id: truth-boundary-checker.invariant.protected_modules_must_not_import_export_loaders
    scope: static-analysis
    rule: protected runtime and governance modules may not import file-based AK3 export loader helpers
  - id: truth-boundary-checker.invariant.filesystem_exports_never_become_truth
    scope: architecture
    rule: story export files may only act as export, projection, debug, audit, or compatibility artifacts and never as canonical truth
```
<!-- FORMAL-SPEC:END -->
