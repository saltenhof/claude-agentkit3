---
id: formal.frontend-contracts.commands
title: Frontend Contracts Commands
status: active
doc_kind: spec
context: frontend-contracts
spec_kind: command-set
version: 2
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

## Fehler-Vertrag

Jeder Command kann fehlschlagen. Die Antwort folgt dem Fehler-Vertrag
aus FK-91 §91.1a Regel 8 (`error_code`, `error`, `correlation_id`,
optional strukturiertes `detail`). Jedes Kommando unten listet in
`error_codes` die fachlichen Fehlerklassen, die das Frontend
behandeln muss; jede Klasse traegt einen `http_status`-Hint. Ein
nicht gelisteter `error_code` ist ein Backend-Bug, kein
Konsumenten-Pfad.

UI-Verhalten bei Fehler:

- **`validation_failed`** (400): Frontend zeigt die fehlerhaften
  Felder im Formular/Sheet inline an, das Optimistic-Update wird
  revertiert.
- **`story_not_found`** (404): Frontend invalidiert die lokale
  Story-Kopie, zeigt einen "Story wurde entfernt"-Hinweis und
  schliesst Inspector, falls die betroffene Story selected war.
- **`invalid_transition`** (422): Frontend zeigt einen
  Klartext-Hinweis (z. B. "Eine laufende Story kann nicht direkt
  abgebrochen werden"), revertiert das Optimistic-Update.
- **`idempotency_mismatch`** (409): Das gleiche `op_id` wurde mit
  abweichendem Payload zweimal genutzt — Frontend-Bug. UI zeigt
  einen generischen Fehler.
- **`conflict`** (409): Generischer Concurrency-Conflict (siehe
  pro-Command-Spalte).
- **`forbidden`** (403): Projekt archiviert oder Auth-Scope fehlt.
  Frontend deaktiviert mutierende UI-Elemente fuer dieses Projekt.
- **`internal_error`** (500): Frontend zeigt einen Retry-Hinweis;
  revertiert Optimistic-Update.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.frontend-contracts.commands
schema_version: 2
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
    error_codes:
      - code: validation_failed
        http_status: 400
        reason: Pflichtfelder fehlen oder Enums ungueltig (title leer, type nicht im Enum, repos leer).
      - code: forbidden
        http_status: 403
        reason: Projekt archiviert oder Auth-Scope fehlt.
      - code: idempotency_mismatch
        http_status: 409
        reason: Gleiche op_id wurde mit abweichendem Body wiederverwendet.
      - code: internal_error
        http_status: 500
        reason: Backend-Fehler; Retry mit derselben op_id erlaubt.

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
    error_codes:
      - code: validation_failed
        http_status: 400
        reason: Felder enthalten ungueltige Werte (z. B. repos leer, size nicht im Enum).
      - code: story_not_found
        http_status: 404
        reason: Story existiert nicht mehr; Frontend invalidiert die Karte.
      - code: forbidden
        http_status: 403
        reason: Projekt archiviert oder Auth-Scope fehlt.
      - code: forbidden_field
        http_status: 422
        reason: Verbotenes Feld im Body (status, created_at, completed_at).
      - code: idempotency_mismatch
        http_status: 409
        reason: Gleiche op_id wurde mit abweichendem Body wiederverwendet.
      - code: internal_error
        http_status: 500
        reason: Backend-Fehler; Retry mit derselben op_id erlaubt.

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
    error_codes:
      - code: story_not_found
        http_status: 404
      - code: invalid_transition
        http_status: 422
        reason: Story ist nicht in Backlog (z. B. bereits Approved, In Progress, Done, Cancelled).
      - code: forbidden
        http_status: 403
      - code: idempotency_mismatch
        http_status: 409
      - code: internal_error
        http_status: 500

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
    error_codes:
      - code: story_not_found
        http_status: 404
      - code: invalid_transition
        http_status: 422
        reason: Story ist nicht in Approved.
      - code: forbidden
        http_status: 403
      - code: idempotency_mismatch
        http_status: 409
      - code: internal_error
        http_status: 500

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
    error_codes:
      - code: story_not_found
        http_status: 404
      - code: invalid_transition
        http_status: 422
        reason: Story ist In Progress oder Done; offizieller Pfad ist Story-Reset (FK-53) bzw. Story-Exit (FK-58).
      - code: forbidden
        http_status: 403
      - code: idempotency_mismatch
        http_status: 409
      - code: internal_error
        http_status: 500
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
    concurrency: last_writer_wins
    error_codes:
      - code: validation_failed
        http_status: 400
        reason: Mindestens ein Cap negativ oder kein Integer.
      - code: forbidden
        http_status: 403
        reason: Projekt archiviert oder Auth-Scope fehlt.
      - code: idempotency_mismatch
        http_status: 409
      - code: internal_error
        http_status: 500
    notes:
      - >
        Reale Implementierung darf Optimistic-Update am Frontend
        nutzen; der Vertrag verlangt aber den `PUT` als
        autoritativen Schritt.
      - >
        Concurrency-Modell ist `last_writer_wins`: paralleles `PUT`
        zweier Strategen ueberschreibt sich. Der Vertrag fuehrt
        bewusst kein ETag/Version. Hintergrund: das Stratege-Tool
        bedient nur sehr wenige Nutzer, die Caps werden selten und
        nicht von mehreren parallel veraendert. Beide Strategen
        sehen das Endergebnis ueber `limits_changed`.

  # ---- Ownership-Takeover --------------------------------------------

  - id: frontend-contracts.command.request_story_run_takeover
    description: >
      Menschlich initiierter Ownership-Takeover-Request aus der UI
      (FK-56 §56.13a, FK-72 §72.14.7). Die Antwort ist nie der
      Vollzug, sondern der versionierte Challenge mit der
      Eigentumslage; der anschliessende Confirm bestaetigt exakt
      diesen Challenge-Stand per Echo.
    transport:
      method: POST
      endpoint: /v1/project-edge/story-runs/{run_id}/ownership/takeover-request
    inputs:
      - name: run_id
        kind: string
        required: true
      - name: reason
        kind: string
        required: true
        notes:
          - Begruendungspflicht, auditiert (FK-56 §56.13a).
      - name: op_id
        kind: string
        required: true
    owner_bc: story-lifecycle
    error_codes:
      - code: validation_failed
        http_status: 400
        reason: Begruendung fehlt oder ist leer.
      - code: story_not_found
        http_status: 404
        reason: Run bzw. Story existiert nicht oder hat keinen aktiven Ownership-Record.
      - code: conflict
        http_status: 409
        reason: Story ist nicht takeover-admissible (aktiver Freeze-Zustand, FK-56 §56.13f).
      - code: forbidden
        http_status: 403
      - code: idempotency_mismatch
        http_status: 409
      - code: internal_error
        http_status: 500
    notes:
      - >
        Dieses Kommando emittiert kein Frontend-Event: Der Challenge
        kommt synchron als Antwort aus dem Owner-BC. Das Event
        `takeover_approval_changed` gehoert zum agenteninitiierten
        Pfad, der nicht vom Frontend ausgeloest wird.

  - id: frontend-contracts.command.confirm_story_run_takeover
    description: >
      Vollzug eines Ownership-Takeovers per Challenge-Echo
      (FK-56 §56.13a/§56.13c; Operationsklasse `admin_transition`,
      FK-55 §55.5). Derselbe Command vollzieht die Freigabe eines
      agenteninitiierten Requests aus dem globalen
      Takeover-Freigabe-Overlay (FK-72 §72.14.7).
    transport:
      method: POST
      endpoint: /v1/project-edge/story-runs/{run_id}/ownership/takeover-confirm
    inputs:
      - name: run_id
        kind: string
        required: true
      - name: challenge_echo
        kind: string
        required: true
        notes:
          - >
            Echo des versionierten Challenge (mindestens
            `ownership_epoch` und `binding_version`); der Vollzug ist
            ein CAS auf diese Versionen (FK-56 §56.13a).
      - name: op_id
        kind: string
        required: true
    emits:
      - frontend-contracts.event.takeover_approval_changed
    owner_bc: story-lifecycle
    error_codes:
      - code: conflict
        http_status: 409
        reason: >
          Challenge veraltet oder invalidiert (zwischenzeitlicher
          Transfer, Exit, Reset, Split, Closure oder Freeze-Eintritt)
          — deterministischer fail-closed Fehlschlag ohne Vollzug;
          erneuter Request gegen die aktuelle Eigentumslage noetig.
      - code: story_not_found
        http_status: 404
      - code: forbidden
        http_status: 403
        reason: >
          Auch die Ping-Pong-Schranke faellt hierunter: eine disowned
          Session kann nicht unmittelbar zurueckuebernehmen
          (FK-55 §55.8.4).
      - code: idempotency_mismatch
        http_status: 409
      - code: internal_error
        http_status: 500
    notes:
      - >
        `takeover_approval_changed` wird emittiert, wenn der Confirm
        eine ausstehende agenteninitiierte Freigabe aufloest; bei rein
        menschlich initiierten Takeovers existiert kein
        Approval-Objekt und damit kein solches Event.
```
<!-- FORMAL-SPEC:END -->
