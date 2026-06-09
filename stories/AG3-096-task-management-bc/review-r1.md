OVERALL: CHANGES-REQUESTED

**Konzept-Vollstaendigkeit: FAIL**

- ERROR: Story modelliert falsche Link-Ziele. Evidence: [story.md](T:/codebase/claude-agentkit3/stories/AG3-096-task-management-bc/story.md:28) sagt `Task <-> Stories/Artefakte`; [story.md](T:/codebase/claude-agentkit3/stories/AG3-096-task-management-bc/story.md:65) wiederholt `Stories UND Artefakte`. FK-77 sagt aber `target_kind` ist `task | story` und verbindet Task mit Task oder Story: [77_task_management.md](T:/codebase/claude-agentkit3/concept/technical-design/77_task_management.md:61), [entities.md](T:/codebase/claude-agentkit3/concept/formal-spec/task-management/entities.md:100). Fix: Artefakt-Links entfernen oder FK-77/formal spec vorher aendern; Story muss `task|story` inklusive Task-zu-Task abdecken.

- ERROR: Top-Surface unvollstaendig. Story nennt nur `create_task`, `link_task`, `resolve_task`: [story.md](T:/codebase/claude-agentkit3/stories/AG3-096-task-management-bc/story.md:31). FK-77 fordert schreibend `create_task`, `link_task`, `unlink_task`, `resolve_task`, `dismiss_task` und lesend `get_task`, `list_tasks`, `list_tasks_for_target`: [77_task_management.md](T:/codebase/claude-agentkit3/concept/technical-design/77_task_management.md:132). Fix: Scope und AC um `unlink_task`, `dismiss_task`, alle drei Read-Methoden und Tests erweitern.

- ERROR: Entity-Scope ist nicht FK-77-vollstaendig. Story beschreibt `id`, `title/description`, `state`, `owner/note`: [story.md](T:/codebase/claude-agentkit3/stories/AG3-096-task-management-bc/story.md:28). FK-77/formal spec fordert `task_id`, `kind`, `type`, `title`, `body`, `priority`, `status`, `origin`, `source_story_id`, `execution_report_ref`, `created_at`, `resolved_at`, `resolved_by`: [77_task_management.md](T:/codebase/claude-agentkit3/concept/technical-design/77_task_management.md:48), [entities.md](T:/codebase/claude-agentkit3/concept/formal-spec/task-management/entities.md:34). Fix: Felder exakt aus FK-77/formal spec uebernehmen; keine undefinierten `owner/note`.

- WARNING: Formal command/event semantics fehlen. FK-77 bindet `formal.task-management.*`: [77_task_management.md](T:/codebase/claude-agentkit3/concept/technical-design/77_task_management.md:38). Formal commands emittieren `task_created`, `task_linked`, `task_unlinked`, `task_resolved`, `task_dismissed`: [commands.md](T:/codebase/claude-agentkit3/concept/formal-spec/task-management/commands.md:31), [events.md](T:/codebase/claude-agentkit3/concept/formal-spec/task-management/events.md:25). Fix: entweder Event-Emission + Tests aufnehmen oder explizit autoritativ klaeren, dass Events trotz formal spec nicht Teil AG3-096 sind.

**AC-Schaerfe: FAIL**

- ERROR: AC1 ist fachlich falsch testbar: `TaskLink` gegen Stories und Artefakte [story.md](T:/codebase/claude-agentkit3/stories/AG3-096-task-management-bc/story.md:42) widerspricht FK-77 `task | story`. Fix: AC1 auf `target_kind in {task, story}` plus Validierung existierender Ziel-Entitaet und gleicher `project_key` bei Task-Ziel umstellen.

- ERROR: AC5 testet nicht die volle Surface. Evidence: [story.md](T:/codebase/claude-agentkit3/stories/AG3-096-task-management-bc/story.md:46) nennt nur `create/link/resolve`; FK-77 verlangt auch unlink/dismiss/read APIs. Fix: AC fuer jede Surface-Methode mit Positiv-/Negativpfad aufnehmen.

- PASS: No-pipeline boundary ist als AC testbar. Evidence: [story.md](T:/codebase/claude-agentkit3/stories/AG3-096-task-management-bc/story.md:47) fordert verbotene Imports + Verhaltenstest; FK-77 fordert nie `PipelineEngine`, kein Phase-Handler: [77_task_management.md](T:/codebase/claude-agentkit3/concept/technical-design/77_task_management.md:122). Kein Fix.

**Klarheit/Eindeutigkeit: FAIL**

- ERROR: `resolve_task (-> done/dismissed)` ist widerspruechlich. Evidence: [story.md](T:/codebase/claude-agentkit3/stories/AG3-096-task-management-bc/story.md:31). Formal spec trennt `resolve_task` nach `done` und `dismiss_task` nach `dismissed`: [commands.md](T:/codebase/claude-agentkit3/concept/formal-spec/task-management/commands.md:57). Fix: `resolve_task` nur done; `dismiss_task` fuer dismissed.

- ERROR: Abschnittsreferenzen sind falsch. Story sagt State-Machine `§77.5` und Tabellen `§77.6`: [story.md](T:/codebase/claude-agentkit3/stories/AG3-096-task-management-bc/story.md:29), [story.md](T:/codebase/claude-agentkit3/stories/AG3-096-task-management-bc/story.md:30). FK-77 hat Lifecycle in §77.2, Speicher in §77.5, Abgrenzung in §77.6: [77_task_management.md](T:/codebase/claude-agentkit3/concept/technical-design/77_task_management.md:66), [77_task_management.md](T:/codebase/claude-agentkit3/concept/technical-design/77_task_management.md:99). Fix: Abschnittsanker korrigieren.

**Kontext-Sinnhaftigkeit: FAIL**

- ERROR: ProjectionKind-Erweiterung kollidiert mit Ist-Code. Story fordert dedizierten `ProjectionKind`: [story.md](T:/codebase/claude-agentkit3/stories/AG3-096-task-management-bc/story.md:30). Code sagt `ProjectionKind (FK-69 §69.3 — exakt 7 Tabellen)` und listet nur sieben Werte: [projection_accessor.py](T:/codebase/claude-agentkit3/src/agentkit/telemetry/projection_accessor.py:51). Fix: vor Implementierung Konzept-/Code-Entscheidung festschreiben: FK-69/ProjectionKind auf Task-Projektionen erweitern oder FK-77 auf separaten Task-Projection-Port anpassen.

- WARNING: Story benennt `Telemetry.write_projection`, aber real existieren `ProjectionAccessor.write_projection/read_projection`: [projection_accessor.py](T:/codebase/claude-agentkit3/src/agentkit/telemetry/projection_accessor.py:249), [projection_accessor.py](T:/codebase/claude-agentkit3/src/agentkit/telemetry/projection_accessor.py:329). Fix: konkrete Code-Surface und Wiring nennen, keine nicht existierende Klasse importieren lassen.

- NIT: Ist-Zustand ist teilweise sauber belegt: kein `src/agentkit/task_management`, keine `tm_tasks/tm_task_links` in `src/agentkit`; FK-77-Anker §77.1-§77.8 existieren. Aber die repo-weite Null-Treffer-Formulierung in [story.md](T:/codebase/claude-agentkit3/stories/AG3-096-task-management-bc/story.md:16) ist unpraezise, weil Stories/var Treffer enthalten. Fix: auf `src/agentkit` bzw. produktiven Code/State-Backend einschraenken.

**Must-Fix ERRORs**

- Artefakt-Links aus AG3-096 entfernen oder FK-77/formal spec vorher aendern.
- FK-77-vollstaendige Entity-Felder aufnehmen.
- Surface um `unlink_task`, `dismiss_task`, `get_task`, `list_tasks`, `list_tasks_for_target` plus Tests erweitern.
- AC1/AC5 fachlich korrigieren.
- `resolve_task` vs. `dismiss_task` eindeutig trennen.
- Falsche §77.x-Referenzen korrigieren.
- ProjectionKind/FK-69-Konflikt vor Implementierung explizit entscheiden.
