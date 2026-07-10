---
id: formal.frontend-contracts.events
title: Frontend Contracts Events
status: active
doc_kind: spec
context: frontend-contracts
spec_kind: event-set
version: 2
prose_refs:
  - concept/technical-design/72_frontend_architektur.md
  - concept/technical-design/91_api_event_katalog.md
---

# Frontend Contracts Events

Diese Spec definiert die Wire-Sicht der Live-Events, die das
AK3-Frontend ueber den projekt-skopierten SSE-Stream
`GET /v1/projects/{project_key}/events` empfaengt. Topics und
Endpoint-Mechanik sind in FK-72 §72.12 / FK-91 §91.8 normiert; diese
Datei haelt die konkreten Event-Schemas pro Topic.

Producer ist `telemetry` als Single-Producer (FK-72 §72.12.3). Die
Events hier sind **Projektionen** auf den Web-Konsumenten und nicht
identisch mit den Roh-Telemetrie-Events aus FK-68/91 §91.2.

Der Hub-Stream (`GET /v1/events/hub`) bleibt out-of-scope, siehe
README.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.frontend-contracts.events
schema_version: 2
kind: event-set
context: frontend-contracts

events:

  # ---- Topic: stories ------------------------------------------------

  - id: frontend-contracts.event.story_upserted
    topic: stories
    description: >
      Eine Story ist angelegt oder geaendert. Empfaenger laden den
      neuen Stand entweder lokal aus dem Payload oder re-fetchen ueber
      `GET /v1/stories/{story_id}`.
    producer:
      bc: telemetry
      source_bc: story-lifecycle
    payload:
      - name: project_key
        kind: string
        required: true
      - name: story_id
        kind: string
        required: true
      - name: summary
        kind: ref
        required: true
        target: frontend-contracts.entity.story_summary

  - id: frontend-contracts.event.story_deleted
    topic: stories
    description: >
      Eine Story wurde aus der projekt-skopierten Liste hart
      entfernt. Selten — der Normalpfad ist, dass abgeschlossene,
      abgebrochene oder zurueckgesetzte Stories sichtbar bleiben und
      ihren Status fuehren. Hard-Delete tritt nur in offiziellen
      Admin-Pfaden (z. B. nicht-rueckholbarer Story-Split, bei dem
      die Original-Story aufgeloest und durch Nachfolger ersetzt
      wird, oder explizite administrative Bereinigung).
    producer:
      bc: telemetry
      source_bc: story-lifecycle
    payload:
      - name: project_key
        kind: string
        required: true
      - name: story_id
        kind: string
        required: true
      - name: reason
        kind: enum
        required: true
        values:
          - split_dissolved
          - admin_purge
        notes:
          - >
            `split_dissolved`: Story wurde im Story-Split (FK-54)
            aufgeloest; Nachfolger werden als separate
            `story_upserted`-Events publiziert.
          - >
            `admin_purge`: Story durch offiziellen Admin-Pfad
            entfernt (selten).
          - >
            **Nicht** in diesem Enum: `reset` (FK-53) — Reset
            entfernt die Story nicht, sondern fuehrt zu
            `story_upserted` mit neuem Status und Run-ID.
            `cancel` (Frontend-Aktion) — fuehrt zu `story_upserted`
            mit Status `Cancelled`.

  # ---- Topic: phases -------------------------------------------------

  - id: frontend-contracts.event.phase_transitioned
    topic: phases
    description: >
      Eine Story hat einen Phasen- oder Substep-Uebergang gemacht.
      Triggert Re-Render des FlowTab; alternativ kann das Frontend
      `GET /v1/projects/{key}/stories/{id}/flow` re-fetchen.
    producer:
      bc: telemetry
      source_bc: pipeline-framework
    payload:
      - name: project_key
        kind: string
        required: true
      - name: story_id
        kind: string
        required: true
      - name: phase
        kind: enum
        required: true
        values: [setup, exploration, implementation, closure]
      - name: substep
        kind: string
        required: true
      - name: iteration
        kind: integer
        required: false
      - name: phase_status
        kind: enum
        required: true
        values: [PENDING, IN_PROGRESS, COMPLETED, FAILED, ESCALATED, PAUSED]

  # ---- Topic: gates --------------------------------------------------

  - id: frontend-contracts.event.gate_evaluated
    topic: gates
    description: >
      Ein QA-Gate hat ein Ergebnis geliefert. Treibt das Status-Pill
      im Inspector-Ergebnis-Tab.
    producer:
      bc: telemetry
      source_bc: verify-system
    payload:
      - name: project_key
        kind: string
        required: true
      - name: story_id
        kind: string
        required: true
      - name: qa_cycle_id
        kind: string
        required: true
      - name: qa_cycle_round
        kind: integer
        required: true
      - name: stage_id
        kind: string
        required: true
      - name: verdict
        kind: enum
        required: true
        values: [PASS, WARNING, FAIL]

  # ---- Topic: governance --------------------------------------------

  - id: frontend-contracts.event.governance_signal
    topic: governance
    description: >
      Verdichtetes Governance-Beobachtungs-Signal (FK-35). Empfaenger
      rendert das ggf. im Inspector-Evidenzlog und in BadgeStreams.
    producer:
      bc: telemetry
      source_bc: governance-and-guards
    payload:
      - name: project_key
        kind: string
        required: true
      - name: story_id
        kind: string
        required: false
      - name: signal_kind
        kind: string
        required: true
      - name: severity
        kind: enum
        required: true
        values: [info, warning, error]
      - name: detail
        kind: string
        required: false

  - id: frontend-contracts.event.takeover_approval_changed
    topic: governance
    description: >
      Eine ausstehende Takeover-Freigabe wurde angelegt oder hat
      ihren Zustand geaendert (approved, denied, expired, invalidated). Loest den
      globalen, benutzeruebergreifenden Takeover-Freigabe-Overlay der
      App-Shell aus bzw. schliesst ihn (FK-72 §72.14.7). Die
      ausstehende Freigabe gehoert zur Permission-Request-Familie
      (FK-56 §56.13b, FK-55 §55.9a).
    producer:
      bc: telemetry
      source_bc: story-lifecycle
    payload:
      - name: project_key
        kind: string
        required: true
      - name: story_id
        kind: string
        required: true
      - name: approval_id
        kind: string
        required: true
      - name: approval
        kind: ref
        required: true
        target: frontend-contracts.entity.takeover_approval_request
    notes:
      - >
        Der Overlay verlaesst sich nicht allein auf das lossy
        SSE-Event: Beim Connection-Aufbau holt das Frontend offene
        Freigaben per Initial-GET (Lossy-Re-Sync, FK-72 §72.12.4).

  # ---- Topic: closure -----------------------------------------------

  - id: frontend-contracts.event.closure_transitioned
    topic: closure
    description: >
      Closure-Substate-Uebergang fuer eine Story. Aktualisiert das
      Phasenstatus-Panel und ggf. das Story-Counter-KpiBar.
    producer:
      bc: telemetry
      source_bc: story-closure
    payload:
      - name: project_key
        kind: string
        required: true
      - name: story_id
        kind: string
        required: true
      - name: substate
        kind: string
        required: true
      - name: result
        kind: enum
        required: false
        values: [PASS, FAIL, ESCALATED]

  # ---- Topic: artifacts ---------------------------------------------

  - id: frontend-contracts.event.artifact_produced
    topic: artifacts
    description: >
      Ein neues Artefakt wurde produziert. Empfaenger refresht ggf.
      die `bundle_entries`-Liste im Inspector-Ergebnis-Tab.
    producer:
      bc: telemetry
      source_bc: artifacts
    payload:
      - name: project_key
        kind: string
        required: true
      - name: story_id
        kind: string
        required: true
      - name: stage_id
        kind: string
        required: true
      - name: envelope_kind
        kind: string
        required: true
      - name: path
        kind: string
        required: true

  # ---- Topic: planning ----------------------------------------------

  - id: frontend-contracts.event.execution_input_changed
    topic: planning
    description: >
      Die Triage-gefilterte Execution-Input-Sicht hat sich geaendert.
      Empfaenger kann den View-Stand entweder ueber den Payload-Hash
      patchen oder via
      `GET /v1/projects/{key}/execution-input/snapshot` re-fetchen.
    producer:
      bc: telemetry
      source_bc: execution-planning
    payload:
      - name: project_key
        kind: string
        required: true
      - name: trigger
        kind: enum
        required: true
        values:
          - story_status_changed
          - story_done
          - blocker_changed
          - limits_changed
          - graph_changed
          - rulebook_compiled
      - name: snapshot_fingerprint
        kind: string
        required: true
        notes:
          - >
            Stabiler Hash der neuen Snapshot-Inhalte. Empfaenger
            koennen entscheiden, ob ein Re-Fetch noetig ist.

  - id: frontend-contracts.event.limits_changed
    topic: planning
    description: >
      Die Caps des Projekts wurden veraendert. Folgeauswirkung ist
      ein `execution_input_changed`-Event mit
      `trigger=limits_changed`, das in derselben Re-Plan-Welle
      versendet wird.
    producer:
      bc: telemetry
      source_bc: execution-planning
    payload:
      - name: project_key
        kind: string
        required: true
      - name: limits
        kind: ref
        required: true
        target: frontend-contracts.entity.execution_limits

  - id: frontend-contracts.event.dependency_graph_changed
    topic: planning
    description: >
      Knoten oder Kanten des Abhaengigkeitsgraphen haben sich
      geaendert. Frontend re-fetcht
      `GET /v1/projects/{key}/planning/graph`.
    producer:
      bc: telemetry
      source_bc: execution-planning
    payload:
      - name: project_key
        kind: string
        required: true
      - name: changed_node_ids
        kind: list<string>
        required: false
      - name: changed_edges
        kind: list<string>
        required: false

  # ---- Topic: telemetry (Mode-Lock-Projektion) ----------------------

  - id: frontend-contracts.event.mode_lock_changed
    topic: telemetry
    description: >
      Projektweiter Story-Mode-Lock hat gewechselt (FK-24 §24.3.3).
      Empfaenger rendert den ModeIndicator in der Topbar neu.
    producer:
      bc: telemetry
      source_bc: story-lifecycle
    payload:
      - name: project_key
        kind: string
        required: true
      - name: mode
        kind: enum
        required: true
        values: [standard, fast, idle]

  # ---- Topic: coverage ----------------------------------------------

  - id: frontend-contracts.event.coverage_updated
    topic: coverage
    description: >
      ARE-Coverage- oder Evidence-Stand fuer eine Story hat sich
      geaendert. Empfaenger refresht
      `GET /v1/projects/{key}/coverage/stories/{story_id}/...`.
    producer:
      bc: telemetry
      source_bc: requirements-and-scope-coverage
    payload:
      - name: project_key
        kind: string
        required: true
      - name: story_id
        kind: string
        required: true
      - name: aspect
        kind: enum
        required: true
        values: [acceptance, are_evidence, gate_result]
```
<!-- FORMAL-SPEC:END -->
