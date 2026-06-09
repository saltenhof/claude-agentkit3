OVERALL CHANGES-REQUESTED

**Per-Dimension Verdict**
- Konzept-Vollstaendigkeit: PASS. R1-ERRORs zu Linkzielen, Entity-Feldset, voller Surface, Events-Routing und ProjectionKind-Konflikt sind in der Story sauber adressiert.
- AC-Schaerfe: FAIL. Ein neuer Must-Fix bleibt bei den Read-Methoden.
- Klarheit/Eindeutigkeit: PASS. `resolve_task`/`dismiss_task` sind getrennt, §77-Referenzen stimmen, Artefakt-Links sind entfernt.
- Kontext-Sinnhaftigkeit: PASS. Freestyle-/No-Pipeline-Grenze haelt: keine Phasen, Gates, Worktrees, `PipelineEngine`-Kopplung; ProjectionKind wird nicht still erweitert, AG3-081-Routing ist ehrlich.

**Remaining Must-Fix ERRORs**
- ERROR: Read-Surface ist nicht tenant-sicher spezifiziert. `Task` ist per `(project_key, task_id)` identifiziert, und `story_id` ist laut Konzept nicht systemweit ausreichend; die Story pinnt aber `get_task(task_id)` und `list_tasks_for_target(target_kind, target_id)` ohne `project_key` ([story.md](T:/codebase/claude-agentkit3/stories/AG3-096-task-management-bc/story.md:44), [story.md](T:/codebase/claude-agentkit3/stories/AG3-096-task-management-bc/story.md:63)). Das kollidiert mit der Task-Identitaet ([story.md](T:/codebase/claude-agentkit3/stories/AG3-096-task-management-bc/story.md:37), [FK-77](T:/codebase/claude-agentkit3/concept/technical-design/77_task_management.md:49)) und der Mandantenregel ([02_domaenenmodell](T:/codebase/claude-agentkit3/concept/technical-design/02_domaenenmodell_zustaende_artefakte.md:164)). Fix: entweder Read-Methoden explizit `project_key`-scoped machen (`get_task(project_key, task_id)`, `list_tasks_for_target(project_key, target_kind, target_id)`) oder einen autoritativen ambient project context in Story/FK-77 festschreiben und testen.

R1-ERRORs selbst sind genuine resolved; der Blocker ist die neu sichtbare Tenant-Scope-Luecke in der Read-Surface.
