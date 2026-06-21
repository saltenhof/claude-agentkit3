# Semantic Review

Evaluate a code contribution with the structured FK-43 §F-43-029 semantic
review schema.

**Invocation:** `/semantic-review <scope>`

**Profile:** CORE

## Contract

`skill_name=semantic-review` is the suffix-free FK-43 skill identity.
`bundle_id=semantic-review-core` is the deployed CORE bundle identity.

The result feeds the QA subflow inside the Implementation phase. It is not a
standalone top-phase and it does not mutate worker output.

## Dimensions

For every dimension, emit a normalized score in the range `0.0..1.0` and a
short reason grounded in concrete evidence.

1. Naming: score + reason for names of modules, classes, functions, variables,
   identifiers, and public contract fields.
2. Error handling: score + reason for fail-closed behavior, exception choice,
   recovery boundaries, and user-visible error semantics.
3. Cyclomatic complexity: score + reason for branching, nesting, and whether
   decomposition keeps behavior understandable.
4. Test coverage: score + reason for positive paths, negative paths, boundary
   cases, regression coverage, and changed contract coverage.
5. Coupling: score + reason for dependency direction, boundary imports, and
   whether the change creates hidden cross-context knowledge.
6. Cohesion: score + reason for whether each module owns one coherent
   responsibility and avoids mixed concerns.
7. Documentation: score + reason for necessary docstrings, resource prose,
   operator-facing notes, and absence of misleading comments.
8. Security: score + reason for secrets handling, injection risks, unsafe I/O,
   auth boundaries, and data exposure.
9. Backward compatibility: score + reason for public API, schema, manifest,
   CLI, config, and persisted-data compatibility.
10. Performance: score + reason for complexity, I/O volume, repeated reads,
    memory use, and runtime impact on common paths.
11. Project standard consistency: score + reason for repository conventions,
    architecture guardrails, lint/type expectations, and naming rules.
12. Requirement fidelity: score + reason for acceptance criteria coverage,
    scope discipline, explicit out-of-scope handling, and concept alignment.

## Aggregate Artifact

Emit one structured QA aggregate artifact:

```json
{
  "artifact_type": "semantic_review_aggregate",
  "skill_name": "semantic-review",
  "profile": "CORE",
  "verdict": "pass|warning|error",
  "dimensions": [
    {
      "dimension": "naming",
      "score": 0.0,
      "reason": "Evidence-backed reason."
    }
  ],
  "aggregate_score": 0.0,
  "blocking_findings": [
    {
      "dimension": "security",
      "severity": "ERROR",
      "reason": "Why this blocks the Implementation QA subflow."
    }
  ],
  "qa_subflow_target": "implementation",
  "verify_system_input": true
}
```

The aggregate artifact is consumed by the Implementation-phase QA subflow and
the `VerifySystem` capability. Unknown or unsupported evidence is reported as
`warning` or `error`; it is never silently converted into a passing score.
