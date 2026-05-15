---
id: formal.frontend-contracts.commands
title: Frontend Contracts Commands
status: active
doc_kind: spec
context: frontend-contracts
spec_kind: command-set
version: 1
prose_refs:
  - concept/technical-design/72_frontend_architektur.md
  - concept/technical-design/91_api_event_katalog.md
---

# Frontend Contracts Commands

Diese Spec definiert die schreibenden Operationen, die das
AK3-Web-Frontend gegen die Control-Plane ausloest. Jedes Kommando
ist auf genau einen HTTP-Endpoint gebunden (FK-91 §91.1a) und
verweist auf den Owner-BC, der das fachliche Verhalten besitzt.

Read-Operationen sind hier **nicht** als Commands gefuehrt; sie
laufen ueber `GET` auf die in `entities.md` modellierten Read-Models.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.frontend-contracts.commands
schema_version: 1
kind: command-set
context: frontend-contracts

commands:

  # ---- Story-Anlage --------------------------------------------------

  - id: frontend-contracts.command.create_story
    description: >
      Neue Story in der Control-Plane anlegen. Owner ist
      `story_context_manager`. Der Story-ID-Praefix kommt aus
      `project_management.Project`.
    transport:
      method: POST
      endpoint: /v1/stories
    inputs:
      - name: project_key
        kind: string
        required: true
      - name: title
        kind: string
        required: true
      - name: type
        kind: enum
        required: true
        values: [implementation, bugfix, concept, research]
      - name: epic
        kind: string
        required: false
      - name: module
        kind: string
        required: false
      - name: size
        kind: enum
        required: false
        values: [XS, S, M, L, XL, XXL]
      - name: mode
        kind: enum
        required: false
        values: [standard, fast]
      - name: repos
        kind: list<string>
        required: true
        notes:
          - >
            Mindestens ein Repo, kein fachlicher Primary. Siehe
            `frontend-contracts.entity.story_summary.repos`.
      - name: labels
        kind: list<string>
        required: false
      - name: op_id
        kind: string
        required: true
        notes:
          - >
            Idempotenzschluessel (FK-91 §91.1a Regel 5). Wiederholungen
            mit demselben `op_id` liefern dasselbe Ergebnis, ohne eine
            zweite Story zu erzeugen.
    allowed_initial_status: Backlog
    emits:
      - frontend-contracts.event.story_upserted
    owner_bc: story-lifecycle

  # ---- Story-Stammdaten-Pflege --------------------------------------

  - id: frontend-contracts.command.update_story_fields
    description: >
      Bearbeitung der Story-Stammdaten aus dem Sheet-Inline-Editor
      und aehnlichen UI-Pfaden. Schreibt **keine** Status-Transition.
    transport:
      method: PATCH
      endpoint: /v1/stories/{story_id}
    inputs:
      - name: story_id
        kind: string
        required: true
      - name: title
        kind: string
        required: false
      - name: epic
        kind: string
        required: false
      - name: module
        kind: string
        required: false
      - name: type
        kind: enum
        required: false
        values: [implementation, bugfix, concept, research]
      - name: size
        kind: enum
        required: false
        values: [XS, S, M, L, XL, XXL]
      - name: mode
        kind: enum
        required: false
        values: [standard, fast]
      - name: repos
        kind: list<string>
        required: false
        notes:
          - >
            Wenn gesetzt: Vollersatz der bisherigen `repos`-Liste der
            Story. Min ein Eintrag erforderlich; eine leere Liste ist
            unzulaessig.
      - name: change_impact
        kind: enum
        required: false
        values: [Local, Component, Cross-Component, Architecture Impact]
      - name: concept_quality
        kind: enum
        required: false
        values: [High, Medium, Low]
      - name: owner
        kind: string
        required: false
      - name: labels
        kind: list<string>
        required: false
      - name: op_id
        kind: string
        required: true
    forbidden_inputs:
      - name: status
        reason: >
          Status-Transitionen laufen ausschliesslich ueber die
          dedizierten Endpunkte (`approve`, `reject`, `cancel`,
          Phase-Lifecycle). Ein Frontend, das `status` per PATCH
          mitschickt, ist fehlerhaft. Sheet- und Inspector-UIs, die
          eine Status-Auswahl anbieten, MUSSEN intern auf die
          dedizierten Endpunkte dispatchen (siehe
          `frontend-contracts.invariant.status_transitions_only_via_endpoints`).
      - name: created_at
        reason: >
          System-managed beim Anlegen. Eine UI-seitige Editierbarkeit
          im Sheet-Prototyp ist Anzeigefreiheit ohne Backend-Wirkung.
      - name: completed_at
        reason: >
          System-managed beim Erreichen von `Done`. Eine UI-seitige
          Editierbarkeit ist nicht persistierend.
    emits:
      - frontend-contracts.event.story_upserted
    owner_bc: story-lifecycle

  # ---- Status-Transitionen ------------------------------------------

  - id: frontend-contracts.command.approve_story
    description: >
      Menschliche Freigabe einer Story (Status `Backlog` -> `Approved`).
      Wird im Kanban via Drag&Drop oder Status-Selector ausgeloest.
    transport:
      method: POST
      endpoint: /v1/stories/{story_id}/approve
    inputs:
      - name: story_id
        kind: string
        required: true
      - name: op_id
        kind: string
        required: true
    allowed_initial_status: Backlog
    resulting_status: Approved
    emits:
      - frontend-contracts.event.story_upserted
    owner_bc: story-lifecycle

  - id: frontend-contracts.command.reject_story
    description: >
      Zuruecksetzen einer freigegebenen Story zur Nacharbeit
      (`Approved` -> `Backlog`).
    transport:
      method: POST
      endpoint: /v1/stories/{story_id}/reject
    inputs:
      - name: story_id
        kind: string
        required: true
      - name: op_id
        kind: string
        required: true
    allowed_initial_status: Approved
    resulting_status: Backlog
    emits:
      - frontend-contracts.event.story_upserted
    owner_bc: story-lifecycle

  - id: frontend-contracts.command.cancel_story
    description: >
      Administrative Beendigung einer Story (`Cancelled`). Vom
      Kanban-Pfad nur fuer Stories ausserhalb laufender Pipeline
      zulaessig.
    transport:
      method: POST
      endpoint: /v1/stories/{story_id}/cancel
    inputs:
      - name: story_id
        kind: string
        required: true
      - name: reason
        kind: string
        required: false
      - name: op_id
        kind: string
        required: true
    allowed_initial_status:
      - Backlog
      - Approved
    forbidden_initial_status:
      - In Progress
      - Done
    resulting_status: Cancelled
    emits:
      - frontend-contracts.event.story_upserted
    owner_bc: story-lifecycle
    notes:
      - >
        `In Progress`-Cancel laeuft offiziell ueber Story-Reset
        (FK-53) oder Story-Exit (FK-58); das Frontend bietet hier
        keine direkte Cancel-Aktion an.

  # ---- Execution-Limits ---------------------------------------------

  - id: frontend-contracts.command.update_execution_limits
    description: >
      Anpassung der projektweiten Caps (FK-70 §70.6.2). Triggert
      Re-Plan (§70.6.2a) und damit eine frische Triage-Auswertung.
    transport:
      method: PUT
      endpoint: /v1/projects/{project_key}/execution-input/limits
    inputs:
      - name: project_key
        kind: string
        required: true
      - name: repo_parallel_cap
        kind: integer
        required: true
      - name: merge_risk_cap
        kind: integer
        required: true
      - name: max_parallel_agent_cap
        kind: integer
        required: true
      - name: llm_pool_cap
        kind: integer
        required: true
      - name: ci_capacity_cap
        kind: integer
        required: true
      - name: op_id
        kind: string
        required: true
    invariants_to_respect:
      - >
        Alle Caps sind non-negative Integer; 0 bedeutet
        "Cap blockiert" und ist zulaessig.
    emits:
      - frontend-contracts.event.limits_changed
      - frontend-contracts.event.execution_input_changed
    owner_bc: execution-planning
    notes:
      - >
        Reale Implementierung darf Optimistic-Update am Frontend
        nutzen; der Vertrag verlangt aber den `PUT` als
        autoritativen Schritt.
```
<!-- FORMAL-SPEC:END -->
