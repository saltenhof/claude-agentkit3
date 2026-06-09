CHANGES-REQUESTED

**1) Konzept-Vollstaendigkeit: FAIL**

- ERROR: FK-77 is no longer missing, but AG3-105 still treats it as prospective/nonexistent.
  Evidence: [story.md](t:/codebase/claude-agentkit3/stories/AG3-105-task-management-ui-freestyle/story.md:7), [story.md](t:/codebase/claude-agentkit3/stories/AG3-105-task-management-ui-freestyle/story.md:72) vs. existing [77_task_management.md](t:/codebase/claude-agentkit3/concept/technical-design/77_task_management.md:2).
  Fix: replace the “FK-77 existiert noch nicht” premise with concrete FK-77/formal-spec anchors.

- ERROR: Link targets are wrong against current FK-77/AG3-096. AG3-105 requires links to Stories/Artefakten; FK-77/formal spec and AG3-096 define `target_kind ∈ {task, story}` and explicitly no artifacts.
  Evidence: [story.md](t:/codebase/claude-agentkit3/stories/AG3-105-task-management-ui-freestyle/story.md:27), [story.md](t:/codebase/claude-agentkit3/stories/AG3-105-task-management-ui-freestyle/story.md:45); conflict with [entities.md](t:/codebase/claude-agentkit3/concept/formal-spec/task-management/entities.md:100), [story.md](t:/codebase/claude-agentkit3/stories/AG3-096-task-management-bc/story.md:59), [story.md](t:/codebase/claude-agentkit3/stories/AG3-096-task-management-bc/story.md:83).
  Fix: change AG3-105 to story/task links, or first change FK-77/AG3-096 authoritatively.

**2) AC-Schaerfe: FAIL**

- ERROR: Wrong close/dismiss API. AG3-105 says “Verwerfen -> `resolve_task` target `dismissed`”; AG3-096/FK-77 split `resolve_task` for done and `dismiss_task` for dismissed.
  Evidence: [story.md](t:/codebase/claude-agentkit3/stories/AG3-105-task-management-ui-freestyle/story.md:28), [story.md](t:/codebase/claude-agentkit3/stories/AG3-105-task-management-ui-freestyle/story.md:46); conflict with [77_task_management.md](t:/codebase/claude-agentkit3/concept/technical-design/77_task_management.md:132), [commands.md](t:/codebase/claude-agentkit3/concept/formal-spec/task-management/commands.md:57), [commands.md](t:/codebase/claude-agentkit3/concept/formal-spec/task-management/commands.md:65).
  Fix: ACs must require `resolve_task` only for `done`, `dismiss_task` only for `dismissed`.

- WARNING: Read-surface is underspecified. AG3-096 requires project-scoped `get_task`, `list_tasks`, `list_tasks_for_target`; AG3-105 only says “Read-Zugriff” and leaves project scope open.
  Evidence: [story.md](t:/codebase/claude-agentkit3/stories/AG3-105-task-management-ui-freestyle/story.md:67), [story.md](t:/codebase/claude-agentkit3/stories/AG3-105-task-management-ui-freestyle/story.md:74); AG3-096 defines exact project-scoped read methods at [story.md](t:/codebase/claude-agentkit3/stories/AG3-096-task-management-bc/story.md:44).
  Fix: add ACs for `list_tasks(project_key, ...)`, `get_task(project_key, task_id)`, `list_tasks_for_target(project_key, target_kind, target_id)` and tenant partition tests.

**3) Klarheit: WEAK**

- ERROR: Story says AG3-096 “liefert” the BC, but the dependency is still `draft/review_pending`, and AG3-096 itself states no production code exists.
  Evidence: [status.yaml](t:/codebase/claude-agentkit3/stories/AG3-096-task-management-bc/status.yaml:4), [story.md](t:/codebase/claude-agentkit3/stories/AG3-096-task-management-bc/story.md:16), [story.md](t:/codebase/claude-agentkit3/stories/AG3-096-task-management-bc/story.md:18). I also found no `src/agentkit` matches for `task_management`, `tm_tasks`, `create_task`, `TaskLink`, etc.
  Fix: state AG3-105 is blocked until AG3-096 is implemented, or describe AG3-096 as a dependency contract rather than real delivered code.

**4) Kontext-Sinnhaftigkeit: FAIL**

- PASS: Freestyle boundary is intact in the prose and AC6; the story explicitly excludes phases/gates/worktrees/pipeline endpoints.
  Evidence: [story.md](t:/codebase/claude-agentkit3/stories/AG3-105-task-management-ui-freestyle/story.md:9), [story.md](t:/codebase/claude-agentkit3/stories/AG3-105-task-management-ui-freestyle/story.md:32), [story.md](t:/codebase/claude-agentkit3/stories/AG3-105-task-management-ui-freestyle/story.md:47).

- ERROR: Backend fit is not intact because AG3-105 follows stale index wording for artifacts and stale/misleading surface wording, while current FK-77/AG3-096 define task/story links and `dismiss_task`.
  Fix: align AG3-105 with current FK-77 + AG3-096, then update stale index wording if needed.

**Must-Fix List**

1. Remove the false “FK-77 does not exist” section and anchor AG3-105 to current FK-77 §§77.1-77.7 plus formal specs.
2. Replace all artifact-link requirements with current valid link targets `task | story`, unless FK-77/AG3-096 are changed first.
3. Replace `resolve_task(... dismissed)` with `dismiss_task`; keep `resolve_task` strictly for `done`.
4. Specify exact project-scoped read APIs and tenant-scope tests.
5. Clarify that AG3-105 cannot execute until AG3-096 backend code exists and passes, or mark all AG3-096 references as contractual dependency only.
