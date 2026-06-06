---
id: formal.sonar-accept-application.entities
title: Sonar Accept Application Entities
status: active
doc_kind: spec
context: sonar-accept-application
spec_kind: entity-set
version: 1
prose_refs:
  - concept/technical-design/27_verify_pipeline_closure_orchestration.md
---

# Sonar Accept Application Entities

Der Accept-Self-Assessment-Schritt (World 2 des Zwei-Welten-Modells, FK-27
§27.6b) braucht wenige fachlich stabile Kernentitaeten fuer den Lifecycle:
`accept-request` und `llm-vote`. Owner ist das verify-system. Der
**geschriebene Ledger-Eintrag** ist *keine* eigene Entitaet dieses Kontexts:
das Ledger-Schema gehoert FK-33 §33.6.4 und ist dort formal als
`deterministic-checks.entity.accepted-exception-ledger-entry`
(`concept/formal-spec/deterministic-checks/entities.md`) modelliert. Dieser
Kontext referenziert diesen kanonischen Eintrag und beschreibt seine Felder
nicht erneut (Single Source of Truth, keine abweichenden Feldnamen).

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.sonar-accept-application.entities
schema_version: 1
kind: entity-set
context: sonar-accept-application
entities:
  - id: sonar-accept-application.entity.accept-request
    identity_key: request_id
    attributes:
      - request_id
      - story_id
      - rule_key
      - file_path
      - rationale
      - status
  - id: sonar-accept-application.entity.llm-vote
    identity_key: vote_id
    attributes:
      - vote_id
      - request_id
      - model_id
      - verdict
      - reasoning
```
<!-- FORMAL-SPEC:END -->
