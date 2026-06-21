# Review Preflight Context Sufficiency Check

[PREFLIGHT:review-preflight-v1:{story_id}]

You receive a review bundle with classified evidence. Before the actual review,
check whether the attached context is sufficient to verify the change against
the story specification and architecture references.

{BUNDLE_MANIFEST_HEADER}

## Task

Review the attached files and answer only with JSON.

If context is missing, request at most 8 deterministic additions:

```json
{{
  "requests": [
    {{"type": "NEED_FILE", "target": "path/or/pattern", "reason": "Why this is needed"}},
    {{"type": "NEED_SCHEMA", "target": "SymbolName", "reason": "Why this is needed"}},
    {{"type": "NEED_CALLSITE", "target": "function_name", "reason": "Why this is needed"}},
    {{"type": "NEED_RUNTIME_BINDING", "target": "config_key", "reason": "Why this is needed"}},
    {{"type": "NEED_TEST_EVIDENCE", "target": "pytest path/", "reason": "Why this is needed"}},
    {{"type": "NEED_CONCEPT_SOURCE", "target": "document section", "reason": "Why this is needed"}},
    {{"type": "NEED_DIFF_EXPANSION", "target": "file.py", "region": "method", "reason": "Why this is needed"}}
  ]
}}
```

If the bundle is sufficient, answer with:

```json
{{"requests": []}}
```

Important:
- Request only information that cannot be derived from the attached files.
- Respect authority classes: PRIMARY_NORMATIVE is authoritative,
  WORKER_ASSERTION has the lowest evidence strength.
