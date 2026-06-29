# Worker-Prompt: Exploration fuer {story_id}

## Auftrag
Erstelle ein Design-Artefakt (FK-23 ChangeFrame) fuer \
**{story_id}: {title}** BEVOR die Implementierung beginnt.

## Story-Details
- **Story:** {story_id}
- **Modus:** Exploration

## Anforderungen
{body}

## Deliverables
1. Design-Dokument mit Architekturentscheidungen
2. Betroffene Dateien identifizieren
3. Risiken und Abhaengigkeiten benennen
4. KEINE Implementierung - nur Design

## Final step (MANDATORY): write the ChangeFrame draft
As your FINAL step, write your completed FK-23 seven-part ChangeFrame as a single
JSON object to this exact path (relative to the project root):

```
_temp/qa/{story_id}/change_frame.draft.json
```

The JSON object MUST use these English keys (ARCH-55) and structure. Identity
fields:

- `schema_version`: `"3.0"`
- `story_id`: `"{story_id}"`
- `run_id`: the run correlation id (UUID) of this run
- `created_at`: ISO-8601 timestamp, tz-aware (UTC)
- `frozen`: `false`

The seven mandatory parts (FK-23 §23.4.1):

- `goal_and_scope`: `{{ "changes": "...", "does_not_change": "..." }}`
- `affected_building_blocks`: `{{ "affected": ["..."], "untouched": ["..."] }}`
- `solution_direction`: `{{ "pattern": "...", "anchoring": "...", "rationale": "..." }}`
- `contract_changes`: `{{ "interfaces": [...], "data_model": [...], "events": [...], "external_integrations": [...] }}` (at least one array non-empty; use a `"none"` marker entry to declare no contract change)
- `conformance_statement`: `{{ "reference_documents": ["..."], "conformant": ["..."], "deviations": ["..."] }}` (>= 1 reference document)
- `verification_sketch`: `{{ "unit": "...", "integration": "...", "e2e": null }}` (at least one level described)
- `open_points`: `{{ "decided": [...], "assumptions": [...], "approval_needed": [...] }}` (all three arrays present, may be empty)

Write ONLY the JSON object to that file. Do NOT write the canonical
`change_frame.json` (the engine validates your draft and materializes it).

[SENTINEL:worker-exploration-v1:{story_id}]
