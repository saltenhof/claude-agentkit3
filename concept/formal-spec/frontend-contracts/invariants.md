---
id: formal.frontend-contracts.invariants
title: Frontend Contracts Invariants
status: active
doc_kind: spec
context: frontend-contracts
spec_kind: invariant-set
version: 1
prose_refs:
  - concept/technical-design/72_frontend_architektur.md
  - concept/technical-design/91_api_event_katalog.md
---

# Frontend Contracts Invariants

Harte Regeln fuer die Wire-Konsistenz zwischen Read-Models, Commands
und SSE-Events.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.frontend-contracts.invariants
schema_version: 1
kind: invariant-set
context: frontend-contracts

invariants:

  # ---- Sync-Pattern ------------------------------------------------

  - id: frontend-contracts.invariant.initial_get_then_subscribe
    scope: all_views
    description: >
      Jede Sicht oeffnet sich mit genau einem `Initial-GET` auf ihren
      fachlichen REST-Endpoint und einem `SSE-Subscribe` mit
      Topic-Filter (FK-72 §72.12.1). Ohne den Initial-GET ist der
      Stream nicht ausreichend, weil SSE lossy ist.
    rule: >
      Fuer jede Sicht V gilt:
        open(V) => exists(get) AND exists(subscribe) AND get.before(subscribe)
      mit `get` = Initial-Snapshot, `subscribe` = SSE-Verbindung.

  - id: frontend-contracts.invariant.lossy_resync_on_reconnect
    scope: sse_consumer
    description: >
      Bei jedem (Re-)Connect auf den SSE-Stream MUSS der Konsument
      einen frischen Initial-GET aller geoeffneten Sichten ausfuehren,
      um den Zustand wiederherzustellen (FK-72 §72.12.4). Ein
      Sequence-Cursor- oder Acknowledge-Protokoll existiert nicht.
    rule: >
      forall sse_connection C:
        reconnect(C) => for_each open_view V: refetch_initial_get(V)

  - id: frontend-contracts.invariant.no_polling
    scope: web_frontend
    description: >
      Das Frontend implementiert kein Polling auf Read-Endpoints. Ein
      Re-Fetch laeuft entweder durch User-Aktion, Topic-Event oder
      Reconnect.
    rule: >
      forall http_get G in web_frontend:
        not periodic_call(G)

  # ---- Triage- / Snapshot-Determinismus ----------------------------

  - id: frontend-contracts.invariant.execution_input_deterministic
    scope: execution_input_snapshot
    description: >
      Gleiche Eingabe (Stories, Caps, Stati, Dependencies) liefert
      identische `execution_input_snapshot`-Inhalte (FK-70 §70.8a.4).
      Repo-Iteration ist alphabetisch fuer Determinismus, Story-
      Sortierung intern nach `critical_path DESC, story_number ASC`.
    rule: >
      forall ProjectState s:
        snapshot(s) is_function_of (stories, limits, statuses, deps)

  - id: frontend-contracts.invariant.execution_input_changed_after_limits
    scope: execution_input_snapshot
    description: >
      Eine Mutation der `execution_limits` MUSS innerhalb derselben
      Re-Plan-Welle ein `execution_input_changed`-Event mit
      `trigger=limits_changed` erzeugen.
    rule: >
      command.update_execution_limits.succeeds
        => emits(frontend-contracts.event.limits_changed)
        AND emits(frontend-contracts.event.execution_input_changed
                  WHERE trigger == "limits_changed")

  - id: frontend-contracts.invariant.eligible_ready_subset
    scope: execution_input_snapshot
    description: >
      `eligible_ready.length <= total_ready`. Zusaetzlich:
      `eligible_ready.length <= global_slots_left`.
    rule: >
      snap.eligible_ready.length <= snap.total_ready
      AND snap.eligible_ready.length <= snap.global_slots_left

  - id: frontend-contracts.invariant.running_excludes_eligible_ready
    scope: execution_input_snapshot
    description: >
      Eine Story darf nicht gleichzeitig in `running` und
      `eligible_ready` erscheinen.
    rule: >
      forall story in snap.running: not (story in snap.eligible_ready)
      AND forall story in snap.eligible_ready: not (story in snap.running)

  # ---- Mode-Lock-Ableitung -----------------------------------------

  - id: frontend-contracts.invariant.mode_lock_derived
    scope: project_mode_lock
    description: >
      Der `project_mode_lock` ist aus dem Stories-Korpus abgeleitet
      (FK-24 §24.3.3). Es gilt:
        - keine `In Progress`-Story => `mode == idle`
        - mindestens eine `In Progress`-Story mit `mode == fast`
          => `mode == fast`
        - sonst => `mode == standard`
    rule: >
      project.mode_lock.mode ==
        if (no story in project where status == "In Progress") then "idle"
        else if (exists story in project where status == "In Progress"
                 AND coalesce(story.mode, "standard") == "fast") then "fast"
        else "standard"

  - id: frontend-contracts.invariant.mode_lock_change_emits
    scope: project_mode_lock
    description: >
      Wenn `project_mode_lock` wechselt, MUSS ein
      `mode_lock_changed`-Event auf Topic `telemetry` emittiert werden.
    rule: >
      change(project.mode_lock.mode)
        => emits(frontend-contracts.event.mode_lock_changed)

  # ---- Story-Detail-Vertrag ----------------------------------------

  - id: frontend-contracts.invariant.story_detail_summary_consistency
    scope: story_detail
    description: >
      Die im `story_detail.summary` enthaltene `story_summary` muss
      mit dem letzten `story_upserted`-Event derselben Story
      konsistent sein. Re-Fetch des Detail-Endpoints nach Event-
      Empfang ist erlaubt.
    rule: >
      detail.summary == latest(event.story_upserted, detail.summary.story_id).summary

  - id: frontend-contracts.invariant.flow_snapshot_matches_runtime
    scope: story_flow_snapshot
    description: >
      Im `story_flow_snapshot` gilt:
        - Story `In Progress`: genau eine Phase ist im Zustand
          `active`, **oder** genau eine Phase ist in einem
          Halte-Zustand (`paused`, `escalated`, `failed`).
        - Story `Backlog`/`Approved`: alle Phasen `pending` (Fast-
          Mode-Exploration `skipped`).
        - Story `Done`: alle Phasen `done` (Fast-Mode-Exploration
          `skipped`).
        - Story `Cancelled`: alle bisherigen Phasen tragen ihren
          jeweiligen Abschluss-State (`done`/`failed`/`escalated`/
          `skipped`), nachfolgende Phasen sind `skipped`. UI
          rendert eine "Cancelled"-Pille am Story-Inspector,
          unabhaengig vom Flow.
    rule: >
      if (story.status == "In Progress")
        then count(flow.phases where state in {"active", "paused", "escalated", "failed"}) == 1
      else if (story.status == "Done")
        then forall p in flow.phases:
          p.state in {"done", "skipped"}
      else if (story.status == "Cancelled")
        then forall p in flow.phases:
          p.state in {"done", "failed", "escalated", "skipped"}
      else
        forall p in flow.phases:
          p.state in {"pending", "skipped"}

  - id: frontend-contracts.invariant.flow_skipped_for_fast_mode
    scope: story_flow_snapshot
    description: >
      Im Fast-Mode wird die Exploration-Phase als `skipped` gefuehrt
      und enthaelt keine Substeps (FK-24 §24.3.3).
    rule: >
      flow.mode == "fast"
        => flow.phases[phase=exploration].state == "skipped"
        AND flow.phases[phase=exploration].substeps == []

  # ---- Command-Vorzustandsregeln -----------------------------------

  - id: frontend-contracts.invariant.status_transitions_only_via_endpoints
    scope: web_frontend
    description: >
      Das Frontend AENDERT Story-Status ausschliesslich ueber
      `approve`, `reject` oder `cancel`. Insbesondere darf ein PATCH
      auf `/v1/stories/{id}` kein `status`-Feld tragen (siehe
      `forbidden_inputs` in `command.update_story_fields`).
    rule: >
      forall request R in web_frontend
        where R.method == "PATCH" AND R.path matches "/v1/stories/{id}":
          R.body.status is absent

  - id: frontend-contracts.invariant.kanban_drag_drop_constrained_transitions
    scope: kanban_view
    description: >
      Drag&Drop im Kanban-Board exponiert genau die durch
      `approve_story`, `reject_story` und `cancel_story` erlaubten
      Status-Wechsel. Pipeline-getriebene Uebergaenge (`Approved` ->
      `In Progress`, `In Progress` -> `Done`) sind kein UI-Pfad und
      duerfen nicht per Drag ausgeloest werden. Terminal-Stories
      (`Done`, `Cancelled`) sind nicht draggable.
    rule: >
      forall drag(story s, target_status t) in kanban_view:
        (s.status == "Backlog"  AND t == "Approved")   // approve
        OR (s.status == "Approved" AND t == "Backlog")  // reject
        OR (s.status in {"Backlog", "Approved"} AND t == "Cancelled")  // cancel
        // alle anderen Kombinationen sind UI-seitig zu blockieren
    notes:
      - >
        `In Progress` und `Done` werden ausschliesslich von der
        Pipeline gesetzt (Setup-Phase bzw. Closure-Sequence). Eine
        UI-seitige Mutation auf diese Stati ist semantisch falsch.
      - >
        Administrative Mutationen auf laufende oder fertige Stories
        laufen ueber `story-reset` (FK-53), `story-split` (FK-54) und
        `story-exit` (FK-58) und sind nicht Teil des Kanban-Pfads.

  - id: frontend-contracts.invariant.cancel_not_during_inflight
    scope: cancel_story
    description: >
      Eine `cancel_story`-Mutation ist nur fuer `Backlog` oder
      `Approved` zulaessig. `In Progress`-Cancel laeuft offiziell
      ueber `story-reset` (FK-53) oder `story-exit` (FK-58).
    rule: >
      command.cancel_story.allowed
        iff target_story.status in {Backlog, Approved}

  - id: frontend-contracts.invariant.op_id_required_on_mutations
    scope: mutating_commands
    description: >
      Jeder mutierende Command-Aufruf traegt `op_id` als
      Idempotenzschluessel (FK-91 §91.1a Regel 5).
    rule: >
      forall cmd in commands where cmd is mutating:
        cmd.inputs contains op_id AND op_id.required

  # ---- Race- und Konsistenz-Invarianten ----------------------------

  - id: frontend-contracts.invariant.no_global_event_ordering
    scope: sse_consumer
    description: >
      SSE-Events tragen **keine** globale Reihenfolgegarantie.
      Insbesondere koennen Events ueber unterschiedliche Topics oder
      ueber unterschiedliche Stories in jeder Reihenfolge eintreffen.
      Konsumenten duerfen nicht aus "Event A kam vor Event B"
      ableiten, dass Mutation A vor Mutation B stattfand.
    rule: >
      forall events e1, e2 on the same connection:
        order(e1, e2) does not imply order(mutation(e1), mutation(e2))
    notes:
      - >
        Per-Story-Konsistenz wird ueber Re-Fetch erreicht: nach jedem
        `story_upserted` ist `GET /v1/stories/{id}` autoritativ; nach
        jedem `phase_transitioned` ist `GET /.../stories/{id}/flow`
        autoritativ.

  - id: frontend-contracts.invariant.initial_get_subscribe_race
    scope: all_views
    description: >
      Die Reihenfolge von Initial-GET und SSE-Subscribe ist nicht
      streng vorgeschrieben — Subscribe darf vor, nach oder
      ueberlappend zum Initial-GET starten. Pflicht ist nur, dass
      die Sicht beide erfolgreich abgeschlossen hat, bevor sie als
      "live" gilt. Ein Event, das waehrend des Initial-GET kommt,
      ueberschreibt nicht den nachfolgenden GET-Stand; statt dessen
      gilt der GET-Stand als Baseline, und das Event triggert ggf.
      einen Re-Fetch.
    rule: >
      forall view V: open(V) becomes "live"
        only when (initial_get(V) succeeded AND subscribe(V) succeeded)
    notes:
      - >
        Backend MUSS Initial-GET-Antworten in eine konsistente
        Wahrheit (z. B. via Transaktion oder Snapshot) zustellen;
        zwischenzeitliche Events sind redundante Aktualisierungen.

  - id: frontend-contracts.invariant.optimistic_update_revert
    scope: web_frontend
    description: >
      Wenn das Frontend eine Mutation als Optimistic-Update lokal
      anwendet, MUSS es bei Backend-Fehler (HTTP 4xx oder 5xx) auf
      den Pre-Update-Stand revertieren UND dem Strategen ein
      Fehler-Feedback geben. Ein "still schlucken" ist unzulaessig
      (ZERO DEBT, fail-closed).
    rule: >
      forall mutation M with optimistic_update U:
        response(M).status >= 400
          => revert(U) AND show_error_feedback(M.error_code)

  - id: frontend-contracts.invariant.stale_selected_story
    scope: story_inspector
    description: >
      Wenn der Inspector eine Story selected hat und diese Story
      ueber ein `story_deleted`-Event entfernt wird, MUSS der
      Inspector geschlossen werden und der Stratege eine kurze
      Hinweis-Pille sehen ("Story wurde entfernt"). Re-Fetch auf
      ein 404 `GET /v1/stories/{id}` hat dieselbe Wirkung.
    rule: >
      forall event e == story_deleted(s):
        if (inspector.selected.story_id == s.story_id)
          then close(inspector) AND notify_user("Story wurde entfernt")
      AND forall fetch f == GET /v1/stories/{id}:
        if (response(f).status == 404 AND inspector.selected.story_id == id)
          then close(inspector) AND notify_user("Story wurde entfernt")

  - id: frontend-contracts.invariant.last_request_wins_per_inspector
    scope: story_inspector
    description: >
      Beim schnellen Wechseln zwischen Stories darf eine spaet
      eintreffende Detail-Antwort eine bereits umgestellte Inspector-
      Selection nicht ueberschreiben. Konkrete Umsetzung ist
      Frontend-Detail (z. B. AbortController, last-request-tracker),
      aber die Folge MUSS sein: was im Inspector steht, gehoert zur
      aktuellen Selection.
    rule: >
      forall t: inspector.rendered.story_id == inspector.selected.story_id

  - id: frontend-contracts.invariant.kanban_drop_handles_backend_rejection
    scope: kanban_view
    description: >
      Wenn ein Kanban-Drop ein Backend-`invalid_transition` zurueck
      bekommt (z. B. weil sich der Status der Story zwischenzeitlich
      geaendert hat), MUSS die Karte sichtbar auf den realen Status
      zurueckspringen UND der Stratege einen Hinweis erhalten. Eine
      Karte in einer Spalte zu lassen, in die sie nicht gehoert, ist
      unzulaessig.
    rule: >
      drop(story s, target t) with response.error_code in
        {"invalid_transition", "story_not_found"}
          => render(s) at column(s.status_after_event)
             AND notify_user(...)

  - id: frontend-contracts.invariant.search_lossy
    scope: topbar_search
    description: >
      Die globale Topbar-Suche ist eine Lese-Operation und liefert
      eine `story_summary`-Liste. Veraltete Suchergebnisse, die nach
      einem SSE-Event nicht mehr aktuell sind, sind erlaubt — der
      Stratege klickt sie an und der Inspector liefert dann den
      kanonischen Stand (oder `story_not_found`, siehe
      `stale_selected_story`). Der Search-Endpoint selbst hat keine
      Push-Komponente.
    rule: >
      search.result == snapshot_at(query_time)

  # ---- Story-Counters-Klassifikation -------------------------------

  - id: frontend-contracts.invariant.counters_classification
    scope: story_counters
    description: >
      Die `story_counters` sind deterministisch aus dem Story-Korpus
      abgeleitet:
        - total       = |stories|
        - running     = |{s : s.status == In Progress}|
        - finished    = |{s : s.status == Done}|
        - queue       = |{s : s.status == Approved}|
        - ready       = |{s : s.status == Approved
                            AND no blocker
                            AND all dependencies in Done}|
        - blocked     = |{s : s.status == Backlog}|
                      + |{s : s.status == Approved
                            AND (has blocker OR open dependency)}|
    rule: >
      counters.total    == count(stories)
      AND counters.running  == count(stories where status == "In Progress")
      AND counters.finished == count(stories where status == "Done")
      AND counters.queue    == count(stories where status == "Approved")
      AND counters.ready    == count(stories where status == "Approved"
                                                AND blocker is null
                                                AND all deps in Done)
      AND counters.blocked  == count(stories where status == "Backlog")
                             + count(stories where status == "Approved"
                                                AND (blocker is not null
                                                     OR any dep not in Done))
```
<!-- FORMAL-SPEC:END -->
