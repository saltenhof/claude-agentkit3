---
id: formal.frontend-contracts.entities
title: Frontend Contracts Entities
status: active
doc_kind: spec
context: frontend-contracts
spec_kind: entity-set
version: 1
prose_refs:
  - concept/technical-design/72_frontend_architektur.md
  - concept/technical-design/91_api_event_katalog.md
---

# Frontend Contracts Entities

Diese Spec definiert die Read-Models, die das AK3-Web-Frontend aus
der Control-Plane konsumiert. Jede Entitaet ist die Wire-Sicht eines
Endpoints aus FK-91 §91.1a. Identifikatoren und Pflichtattribute
sind kanonisch; optionale Erweiterungen sind erlaubt, duerfen aber
weder Pflichtattribute weglassen noch deren Semantik aendern.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.frontend-contracts.entities
schema_version: 1
kind: entity-set
context: frontend-contracts

entities:

  # ---- Projekt-Ebene ------------------------------------------------

  - id: frontend-contracts.entity.project_summary
    identity: project_key
    description: >
      Kompakte Projekt-Identitaet fuer den Topbar-Project-Selector.
      Wird vom Endpoint `GET /v1/projects` als Liste geliefert.
    attributes:
      - name: project_key
        kind: string
        required: true
      - name: display_name
        kind: string
        required: true
      - name: status
        kind: enum
        required: true
        values: [active, archived]
    notes:
      - Ein archiviertes Projekt erscheint in der Liste, wird aber von
        mutierenden Endpunkten fail-closed blockiert (FK-91 §91.1a
        Regel 1, FK-72 §72.8.1 Middleware).

  - id: frontend-contracts.entity.project_detail
    identity: project_key
    description: >
      Detailsicht eines Projekts inkl. abgeleiteter Indikatoren fuer
      die Topbar und KPI-Bar plus projektweite Konzept-Anker fuer
      den Inspector-Spezifikations-Tab.
    attributes:
      - name: project_key
        kind: string
        required: true
      - name: display_name
        kind: string
        required: true
      - name: status
        kind: enum
        required: true
        values: [active, archived]
      - name: mode_lock
        kind: ref
        required: true
        target: frontend-contracts.entity.project_mode_lock
      - name: story_counters
        kind: ref
        required: true
        target: frontend-contracts.entity.story_counters
      - name: concept_anchors
        kind: list<string>
        required: true
        notes:
          - >
            Projektweite Konzept-Anker, die als statische "Konzeptanker"-
            Sektion im Inspector-Spezifikations-Tab pro Story
            gerendert werden. Inhalt sind kurze normative Verweise
            (z. B. "FK-70: Pflichtsicht ist der Dependency-Graph").
            Leer erlaubt. Aenderungen werden nicht auf einem eigenen
            SSE-Topic propagiert; das Frontend re-fetcht
            `project_detail` bei `mode_lock_changed` oder explizitem
            User-Reload.

  - id: frontend-contracts.entity.project_mode_lock
    identity: project_key
    description: >
      Projektweit aktiver Story-Mode, abgeleitet aus laufenden Stories
      (FK-24 §24.3.3). Wird vom ModeIndicator in der Topbar gerendert.
    attributes:
      - name: project_key
        kind: string
        required: true
      - name: mode
        kind: enum
        required: true
        values: [standard, fast, idle]
        notes:
          - >
            `idle` heisst: keine `In Progress`-Story im Projekt; kein
            Mode aktiv. `standard`/`fast` heisst: mindestens eine
            laufende Story bestimmt die Lock-Klasse.
    notes:
      - >
        Lieferform ist Snapshot. Live-Updates kommen ueber das
        `mode_lock`-Event (siehe events.md).

  - id: frontend-contracts.entity.story_counters
    identity: project_key
    description: >
      Aggregierte Story-Zaehler fuer die KpiBar (Kanban-/Sheet-/
      Graph-Topbar).
    attributes:
      - name: project_key
        kind: string
        required: true
      - name: total
        kind: integer
        required: true
      - name: finished
        kind: integer
        required: true
      - name: running
        kind: integer
        required: true
      - name: ready
        kind: integer
        required: true
      - name: queue
        kind: integer
        required: true
      - name: blocked
        kind: integer
        required: true
    notes:
      - >
        Klassifikation der Zaehler ist deterministisch
        (siehe invariants.md `frontend-contracts.invariant.counters_classification`).

  # ---- Story-Liste und -Detail --------------------------------------

  - id: frontend-contracts.entity.story_summary
    identity: story_id
    description: >
      Kompakte Story-Repraesentation fuer Listen, Karten und Knoten
      (Kanban, Sheet, Graph, ReadyStack). Reicht aus, um eine Story
      ohne Nachladen von Inspector-Daten zu rendern.
    attributes:
      - name: story_id
        kind: string
        required: true
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
      - name: status
        kind: enum
        required: true
        values: [Backlog, Approved, In Progress, Done, Cancelled]
      - name: size
        kind: enum
        required: true
        values: [XS, S, M, L, XL, XXL]
      - name: mode
        kind: enum
        required: false
        values: [standard, fast]
        notes:
          - Default `standard`, wenn nicht gesetzt. `null` ist erlaubt
            und wird wie `standard` interpretiert.
      - name: epic
        kind: string
        required: true
      - name: module
        kind: string
        required: true
      - name: repos
        kind: list<string>
        required: true
        notes:
          - >
            Die Repos, an denen die Story arbeitet. Mindestens ein
            Eintrag. Reihenfolge ist semantisch ohne Bedeutung;
            insbesondere existiert auf der Wire-Sicht kein
            ausgezeichneter "Primary". Die Implementierung des
            Backends darf intern eine Reihenfolge oder Default-
            Worktree-Bindung fuehren (FK-22 Multi-Repo-Worktrees);
            das ist Implementierungsdetail und nicht Teil dieses
            Vertrags.
      - name: change_impact
        kind: enum
        required: true
        values: [Local, Component, Cross-Component, Architecture Impact]
      - name: concept_quality
        kind: enum
        required: true
        values: [High, Medium, Low]
      - name: owner
        kind: string
        required: true
      - name: wave
        kind: integer
        required: true
      - name: critical_path
        kind: bool
        required: true
      - name: risk
        kind: enum
        required: true
        values: [low, medium, high]
      - name: blocker
        kind: string
        required: false
      - name: dependencies
        kind: list<string>
        required: true
        notes:
          - Liste der `story_id`-Vorgaenger. Leer erlaubt.
      - name: labels
        kind: list<string>
        required: false
      - name: qa_rounds
        kind: integer
        required: true
      - name: qa_rounds_exploration
        kind: integer
        required: false
      - name: qa_rounds_implementation
        kind: integer
        required: false
      - name: processing_time
        kind: string
        required: false
        notes:
          - >
            Frei formatierte Anzeige-Repraesentation (z. B. `"42 min"`).
            Kanonisch sind die in `runtime.phase`-Snapshots gefuehrten
            Werte; das Frontend zeigt das hier rein als Liste.
      - name: created_at
        kind: timestamp
        required: false
      - name: completed_at
        kind: timestamp
        required: false
      - name: runtime
        kind: ref
        required: false
        target: frontend-contracts.entity.story_runtime_state
        notes:
          - Nur belegt fuer Stories mit Status `In Progress`.

  - id: frontend-contracts.entity.story_runtime_state
    identity: story_id
    description: >
      Aktueller Laufzeit-Zustand einer laufenden Story (Phase,
      Substep, Loop-Iteration). Quelle: `phase-state-projection`
      (FK-39).
    attributes:
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
        notes:
          - >
            Phase-spezifischer Substep-Identifier. Kanonische Liste
            siehe FK-22/23/26/27/29 sowie die jeweiligen formalen
            Substep-Sets der Owner-BCs.
      - name: iteration
        kind: integer
        required: false
        notes:
          - >
            Aktuelle Iteration innerhalb einer Loop-Gruppe (z. B.
            `remediation` in Implementation). Default 1.

  - id: frontend-contracts.entity.story_detail
    identity: story_id
    description: >
      Vollstaendige Story-Sicht fuer den Inspector. Vereinigt
      Story-Stammdaten, Evidence-Bundle-Sicht, Phasen-Zustaende,
      Gates, Event-Spur und Telemetrie-Aggregate.
    attributes:
      - name: summary
        kind: ref
        required: true
        target: frontend-contracts.entity.story_summary
      - name: spec
        kind: ref
        required: true
        target: frontend-contracts.entity.story_specification
      - name: evidence
        kind: ref
        required: false
        target: frontend-contracts.entity.story_evidence
      - name: telemetry
        kind: ref
        required: false
        target: frontend-contracts.entity.story_telemetry_summary
      - name: gates
        kind: list<ref>
        required: true
        target: frontend-contracts.entity.story_gate_entry
      - name: phases
        kind: list<ref>
        required: true
        target: frontend-contracts.entity.story_phase_entry
      - name: events
        kind: list<ref>
        required: true
        target: frontend-contracts.entity.story_event_entry

  - id: frontend-contracts.entity.story_specification
    identity: story_id
    description: >
      Spezifikations-Tab-Inhalt: Bedarf, Loesungsansatz, Akzeptanz-
      kriterien, Definition of Done und Konzept-/Guardrail-Referenzen.
    attributes:
      - name: need
        kind: string
        required: false
      - name: solution
        kind: string
        required: false
      - name: acceptance
        kind: list<string>
        required: true
      - name: definition_of_done
        kind: list<string>
        required: false
      - name: concept_refs
        kind: list<string>
        required: false
      - name: guardrail_refs
        kind: list<string>
        required: false
      - name: external_sources
        kind: list<string>
        required: false

  - id: frontend-contracts.entity.story_evidence
    identity: story_id
    description: >
      QA-Zyklus-Identitaet plus Evidence-Bundle-Liste fuer den
      Inspector-Ergebnis-Tab. Owner-BC der Inhalte ist
      `artifacts` bzw. `verify-system`; hier nur die Wire-Sicht.
    attributes:
      - name: qa_cycle_id
        kind: string
        required: true
      - name: qa_cycle_round
        kind: integer
        required: true
      - name: evidence_epoch
        kind: string
        required: true
      - name: evidence_fingerprint
        kind: string
        required: true
      - name: manifest_hash
        kind: string
        required: true
      - name: bundle_entries
        kind: list<ref>
        required: true
        target: frontend-contracts.entity.story_evidence_bundle_entry

  - id: frontend-contracts.entity.story_evidence_bundle_entry
    identity: composite(qa_cycle_id, path)
    attributes:
      - name: authority
        kind: enum
        required: true
        values: [STORY_SPEC, CONCEPT, GUARDRAIL, DIFF, HANDOVER, SECONDARY_CONTEXT]
      - name: path
        kind: string
        required: true
      - name: status
        kind: enum
        required: true
        values: [INCLUDED, REQUESTED, UNRESOLVED]

  - id: frontend-contracts.entity.story_telemetry_summary
    identity: story_id
    description: >
      Aggregierte Telemetrie fuer Inspector-KPI-Tab. Tokens werden
      pro Story gefuehrt (keine Phasen-Aufteilung), Laufzeit und
      Solving Rate werden phasenaufgeteilt geliefert, damit
      sichtbar wird, ob ein Agent z. B. Exploration schwer und
      Implementation leicht loest. Detaillierte Analytics-Sichten
      ueber Stories hinweg werden in `kpi-and-dashboard` modelliert
      und sind hier nicht enthalten.
    attributes:
      - name: run_id
        kind: string
        required: true
      - name: tokens_in
        kind: integer
        required: true
      - name: tokens_out
        kind: integer
        required: true
      - name: tokens_cached
        kind: integer
        required: true
        notes:
          - >
            Real von der LLM-Pool-Schicht gemessener Cache-Hit-Anteil
            der Input-Tokens. Keine Frontend-Synthese.
      - name: llm_calls
        kind: integer
        required: false
      - name: adversarial_tests
        kind: integer
        required: false
      - name: web_calls
        kind: integer
        required: false
      - name: runtime_total_minutes
        kind: number
        required: true
      - name: runtime_setup_minutes
        kind: number
        required: true
      - name: runtime_exploration_minutes
        kind: number
        required: false
        notes:
          - >
            `null` im Fast-Mode (Exploration-Phase ausgelassen, FK-24
            §24.3.3). Sonst Pflicht-Wert.
      - name: runtime_implementation_minutes
        kind: number
        required: true
      - name: runtime_closure_minutes
        kind: number
        required: true
      - name: solving_rate_exploration
        kind: number
        required: false
        notes:
          - >
            Anteil der in der Exploration gefundenen Findings, die im
            Subflow-Remediation-Loop abgearbeitet wurden (0..100).
            `null` im Fast-Mode. Quelle ist die QA-Subflow-Aggregation
            (FK-27/FK-38).
      - name: solving_rate_implementation
        kind: number
        required: true
        notes:
          - >
            Anteil der in der Implementation-QA gefundenen Findings,
            die durch Remediation abgearbeitet wurden (0..100).
      - name: pools
        kind: list<ref>
        required: false
        target: frontend-contracts.entity.story_pool_call_summary

  - id: frontend-contracts.entity.story_pool_call_summary
    identity: composite(run_id, pool, role)
    attributes:
      - name: pool
        kind: string
        required: true
        notes:
          - LLM-Pool-Identifier (z. B. `chatgpt`, `gemini`, `grok`).
      - name: role
        kind: string
        required: true
      - name: calls
        kind: integer
        required: true
      - name: status
        kind: enum
        required: true
        values: [PASS, WARNING, FAIL]

  - id: frontend-contracts.entity.story_gate_entry
    identity: composite(story_id, label)
    attributes:
      - name: label
        kind: string
        required: true
      - name: state
        kind: enum
        required: true
        values: [PASS, WARNING, ERROR]

  - id: frontend-contracts.entity.story_phase_entry
    identity: composite(story_id, label)
    description: >
      Pro-Phase-Eintrag fuer die Phasen-Liste im Inspector-Ergebnis-
      Tab. Detaillierte Flow-Sicht liefert
      `frontend-contracts.entity.story_flow_snapshot`.
    attributes:
      - name: label
        kind: string
        required: true
      - name: state
        kind: enum
        required: true
        values: [done, active, blocked, idle, skipped]
      - name: detail
        kind: string
        required: false

  - id: frontend-contracts.entity.story_event_entry
    identity: composite(story_id, time, type)
    attributes:
      - name: time
        kind: timestamp
        required: true
      - name: type
        kind: string
        required: true
      - name: detail
        kind: string
        required: false
      - name: severity
        kind: enum
        required: true
        values: [info, warning, error]

  # ---- Flow-Snapshot (Inspector-Ablauf-Tab) -------------------------

  - id: frontend-contracts.entity.story_flow_snapshot
    identity: story_id
    description: >
      Phasen- und Substep-Zustaende einer Story zum Render-Zeitpunkt.
      Liefert dem FlowTab seine Eingabe; ersetzt **nicht** die
      kanonische Pipeline-State-Projektion (FK-39), sondern projiziert
      sie in die Wire-Sicht des Frontends.
    attributes:
      - name: story_id
        kind: string
        required: true
      - name: mode
        kind: enum
        required: true
        values: [standard, fast]
      - name: phases
        kind: list<ref>
        required: true
        target: frontend-contracts.entity.story_flow_phase

  - id: frontend-contracts.entity.story_flow_phase
    identity: composite(story_id, phase)
    attributes:
      - name: phase
        kind: enum
        required: true
        values: [setup, exploration, implementation, closure]
      - name: state
        kind: enum
        required: true
        values: [done, active, pending, skipped, optional-pending, optional-skipped]
      - name: iteration
        kind: integer
        required: false
        notes:
          - >
            Aktuelle Iteration der aktiven Loop-Gruppe der Phase. Nur
            gesetzt, wenn `state == active` und der aktive Substep
            Teil einer Loop-Gruppe ist.
      - name: iteration_loop_group
        kind: string
        required: false
      - name: substeps
        kind: list<ref>
        required: true
        target: frontend-contracts.entity.story_flow_substep

  - id: frontend-contracts.entity.story_flow_substep
    identity: composite(story_id, phase, substep)
    attributes:
      - name: substep
        kind: string
        required: true
      - name: state
        kind: enum
        required: true
        values: [done, active, pending, skipped, optional-pending, optional-skipped]
      - name: optional
        kind: bool
        required: true
      - name: loop_group
        kind: string
        required: false
      - name: loop_position
        kind: integer
        required: false
        notes:
          - 1-basiert innerhalb der Loop-Region.
      - name: loop_size
        kind: integer
        required: false

  # ---- Execution-Input (FK-70 §70.8a) -------------------------------

  - id: frontend-contracts.entity.execution_input_snapshot
    identity: project_key
    description: >
      Lebende Sicht fuer das Frontend (FK-70 §70.8a.1): laufende
      Stories und Triage-gefilterte delegierbare Stories, jeweils
      mit Predecessor/Successor-Stack.
    attributes:
      - name: project_key
        kind: string
        required: true
      - name: running
        kind: list<ref>
        required: true
        target: frontend-contracts.entity.execution_input_stack
        notes:
          - Bereits delegierte Stories. Leer erlaubt.
      - name: eligible_ready
        kind: list<ref>
        required: true
        target: frontend-contracts.entity.execution_input_stack
        notes:
          - >
            Triage-Ergebnis: Round-Robin pro Repo, Critical-Path
            priorisiert, intern nach Story-Nummer. Determinismus
            siehe invariants.md.
      - name: total_ready
        kind: integer
        required: true
        notes:
          - Anzahl theoretisch ready (vor Triage).
      - name: global_slots_left
        kind: integer
        required: true
        notes:
          - >
            `globalCap - running.length`, lower-bounded auf 0.
            `globalCap = min(merge_risk_cap, max_parallel_agent_cap,
            llm_pool_cap, ci_capacity_cap)`.

  - id: frontend-contracts.entity.execution_input_stack
    identity: composite(project_key, story_id)
    description: >
      Dreikarten-Stack: Vorgaenger / Story / Nachfolger. Vorgaenger
      und Nachfolger sind optional; sie tragen einen
      `story_summary`-Verweis, kein Detail.
    attributes:
      - name: story
        kind: ref
        required: true
        target: frontend-contracts.entity.story_summary
      - name: predecessor
        kind: ref
        required: false
        target: frontend-contracts.entity.story_summary
      - name: successor
        kind: ref
        required: false
        target: frontend-contracts.entity.story_summary

  - id: frontend-contracts.entity.execution_limits
    identity: project_key
    description: >
      Aktive Caps des Projekts (FK-70 §70.6.2). Editierbar ueber
      `frontend-contracts.command.update_execution_limits`.
    attributes:
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
    notes:
      - Alle Werte sind non-negative Integer; 0 bedeutet "Cap blockiert".

  # ---- Dependency-Graph ---------------------------------------------

  - id: frontend-contracts.entity.dependency_graph_snapshot
    identity: project_key
    description: >
      Knoten- und Kanten-Sicht fuer den Graph-Tab. Liest aus
      `execution-planning.DependencyGraph` (FK-70).
    attributes:
      - name: project_key
        kind: string
        required: true
      - name: nodes
        kind: list<ref>
        required: true
        target: frontend-contracts.entity.story_summary
      - name: edges
        kind: list<ref>
        required: true
        target: frontend-contracts.entity.dependency_graph_edge

  - id: frontend-contracts.entity.dependency_graph_edge
    identity: composite(project_key, from_story_id, to_story_id)
    attributes:
      - name: from_story_id
        kind: string
        required: true
      - name: to_story_id
        kind: string
        required: true
      - name: kind
        kind: enum
        required: true
        values: [hard, soft]
        notes:
          - >
            Eine harte Kante blockiert Readiness (FK-70 §70.11). Eine
            weiche Kante ist Plan-Reihenfolge und kein Blocker.
```
<!-- FORMAL-SPEC:END -->
