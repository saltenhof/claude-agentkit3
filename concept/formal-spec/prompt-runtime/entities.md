---
id: formal.prompt-runtime.entities
title: Prompt Runtime Entities
status: active
doc_kind: spec
context: prompt-runtime
spec_kind: entity-set
version: 1
prose_refs:
  - concept/technical-design/44_prompt_bundles_materialization_audit.md
---

# Prompt Runtime Entities

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.prompt-runtime.entities
schema_version: 1
kind: entity-set
context: prompt-runtime
entities:
  - id: prompt-runtime.entity.prompt-bundle
    identity_key: bundle_id
    attributes:
      - bundle_id
      - bundle_version
      - manifest_digest
      - root_path
      - immutable
  - id: prompt-runtime.entity.project-prompt-binding
    identity_key: project_key
    attributes:
      - project_key
      - binding_lock_path
      - binding_root
      - bundle_root
      - prompt_bundle_version
      - binding_digest
      - updated_at
  - id: prompt-runtime.entity.run-prompt-pin
    identity_key: run_id
    attributes:
      - run_id
      - project_key
      - resolved_prompt_bundle_version
      - resolved_prompt_bundle_manifest_digest
      - pinned_at
  - id: prompt-runtime.entity.prompt-instance
    identity_key: prompt_instance_id
    attributes:
      - prompt_instance_id
      - run_id
      - invocation_id
      - logical_prompt_id
      - template_relpath
      - render_mode
      - template_sha256
      - render_input_digest
      - output_sha256
      - artifact_path
```
<!-- FORMAL-SPEC:END -->
