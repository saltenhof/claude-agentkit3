# AG3-105 — Remediation r1 (hostile Codex review-r1.md)

Scope of this remediation: `story.md` only. `status.yaml` was reviewed and left
unchanged (no field is genuinely wrong — see §status.yaml). No production code,
tests, or concept files touched, and no other story's files touched. Every anchor
below was re-verified against the real tree at remediation time and corrected to
`file:line`. Cut held strictly to AG3-105 (frontend Task-Slice consuming the
AG3-096 surface); the freestyle / not-pipeline-managed boundary is preserved and
strengthened.

## Must-Fix ERRORs

### MF1 — False "FK-77 existiert noch nicht" premise (review §1, §Must-Fix 1)
**Finding:** Story claimed FK-77 was not in the corpus and treated it as
prospective (old story.md:7, :72). FK-77 now exists.
**Resolution:** FK-77 is real at `concept/technical-design/77_task_management.md`
(§§77.1-77.8) with formal specs `concept/formal-spec/task-management/{entities,
state-machine,commands,events,invariants,scenarios}.md`. The "Quell-Konzepte"
block now anchors to concrete FK-77 §§77.1-77.7 + formal-spec paths; the false
"§7 Offene Punkte: FK-77 existiert noch nicht" section is removed and replaced by
a "Vorbedingungen und offene fachliche Punkte" section that points at the real
docs. (Resolved in-story.)

### MF2 — Wrong link targets `Stories/Artefakte` (review §1/§4, §Must-Fix 2)
**Finding:** Story required links to "Stories/Artefakten" (old story.md:27, :45).
Authoritative model is `target_kind ∈ {task, story}`, artifacts explicitly
excluded.
**Resolution:** All link wording changed to `target_kind ∈ {task, story}` with
typed relation `kind` (`relates_to | spawned_story | duplicate_of`); artifacts are
explicitly not a valid link target. Anchored to
`formal.task-management.entities:100`-`:110` and FK-77 §77.3, consistent with
`stories/AG3-096-task-management-bc/story.md:59`. Scope 2.1.4 and AC4 rewritten.
(Resolved in-story.)

### MF3 — Wrong close/dismiss API `resolve_task(... dismissed)` (review §2, §Must-Fix 3)
**Finding:** Story bound "Verwerfen" to `resolve_task` target `dismissed` (old
story.md:29, :46). FK-77/AG3-096 split the surface: `resolve_task` for `done`,
`dismiss_task` for `dismissed`.
**Resolution:** Scope 2.1.3 and AC5 now require `resolve_task` strictly for `done`
and `dismiss_task` strictly for `dismissed` — separate commands, no mixed path. AC5
adds a negative assertion (Verwerfen never calls `resolve_task`). Anchored to
`formal.task-management.commands:57`-`:71` (`resolve_task` allowed_from open ->
done; `dismiss_task` allowed_from open -> dismissed) and FK-77 §77.2. `unlink_task`
(present in the surface, missing before) is added to scope/AC4/hints for surface
completeness. (Resolved in-story.)

### MF4 — Read-surface underspecified / project scope open (review §2 WARNING, §Must-Fix 4)
**Finding (WARNING in review §2):** Story only said "Read-Zugriff" with project
scope left open (old story.md:67, :74). AG3-096 defines exact project-scoped read
methods.
**Resolution:** New AC6 specifies the exact tenant-scoped read surface —
`get_task(project_key, task_id)`, `list_tasks(project_key, filter:
status|type|kind|origin)`, `list_tasks_for_target(project_key, target_kind,
target_id)` — and requires a cross-tenant partition test (same `task_id` under two
`project_key` -> strictly partitioned, no leak in the UI read path). Anchored to
FK-77 §77.7, `stories/AG3-096-task-management-bc/story.md:44`, and the identity
`(project_key, task_id)` at `formal.task-management.entities:28`. The open
"projekt-skopiert?" question is thereby resolved authoritatively (tasks are
project-scoped, per the formal-spec identity). (Resolved in-story.)

### MF5 — "AG3-096 liefert" but it is draft/unimplemented (review §3, §Must-Fix 5)
**Finding:** Story stated AG3-096 "liefert" the BC, but AG3-096 is
`draft`/`review_pending` and states no production code exists.
**Resolution:** §1 reframes AG3-096 as a **dependency contract**, not delivered
code, citing `stories/AG3-096-task-management-bc/status.yaml:4`-`:5` and
`stories/AG3-096-task-management-bc/story.md:16`-`:18` (Grep = 0 hits in
`src/agentkit`). §4 (DoD) and §7 state AG3-105 cannot be implemented/executed until
AG3-096 is implemented and green. All surface references are marked contractual.
(Resolved in-story.)

## Other review items

### Backend-fit (review §4 ERROR)
Resolved as the union of MF1-MF5: the story now aligns with current FK-77 +
`formal.task-management.*` + AG3-096 (task/story links, split resolve/dismiss,
tenant-scoped reads). The stale-index wording is reported as a doc-only follow-up
(see Cross-story), not silently inherited.

### Freestyle boundary (review §4 PASS)
Confirmed intact and strengthened. Scope 2.1.5, AC7, §5 ABGRENZUNG and the
sub-agent hints keep tasks free of phases/gates/worktrees/QA and bind actions only
to the `task_management` top-surface (FK-77 §77.6). No pipeline coupling
introduced.

## Corrected / verified anchors
Prototype anchors re-verified and made absolute-pathed:
`frontend/prototype/src/App.tsx:76` (`ViewMode`), `:602`-`:618` (nav),
`:853` (`Kanban`), `:2073` (`Badge`), `:2087` (`Info`),
`frontend/prototype/src/store/storyModel.ts` + `storySelectors.ts` (story-only,
no task model), `frontend/prototype/src/design-system.css`, components
`StoryCard.tsx`/`KpiBar.tsx`/`CopyButton.tsx`/`FastBadge.tsx`.
**Corrected:** the inspector-tabs anchor `App.tsx:1715` (that line is the
`DetailInspector` container) was wrong; the tab `useState` is at `:1726` and the
tab-strip buttons at `:1753` — the story now points at `:1726`/`:1753`.
Concept anchors verified: FK-77 §§77.1-77.7
(`concept/technical-design/77_task_management.md`), entities
`concept/formal-spec/task-management/entities.md:28`/`:81-84`/`:100-110`,
commands `concept/formal-spec/task-management/commands.md:57-71`.

## status.yaml
Unchanged. `type: implementation`, `status: draft`, `phase: review_pending`,
`size: M`, and `depends_on: [AG3-093, AG3-096]` are all correct: AG3-093 (App-Shell)
and AG3-096 (BC surface) are genuine prerequisites, and the story is in an active
review cycle. No field is genuinely wrong, so per instruction status.yaml was not
touched.

## Genuine cross-story prerequisites / follow-ups
1. **AG3-096 (Welle 8) — task_management BC must be delivered first.** AG3-096 is
   the surface contract; it is `draft`/`review_pending` with zero production code
   today. AG3-105 is a pure consumer and cannot be implemented until AG3-096 ships
   green. This is already a declared `depends_on` — no scope transfer, just a hard
   ordering constraint now made explicit in §1/§4/§7.
2. **Task-BFF `http/` adapter — REAL GAP, no current owner.** The browser UI needs
   a thin `http/` adapter over the transport-agnostic `task_management` surface
   (FK-77 §77.7). AG3-090 enumerates eight BC `http/` modules
   (`pipeline_engine/verify_system/governance/closure/artifacts/kpi_analytics/
   failure_corpus/requirements_coverage`) — `task_management` is **not** among them
   (`var/concept-gap-analysis/_STORY_INDEX.md:115`); AG3-091 lists no task
   read-models (`:116`). No existing story delivers the task BFF adapter. This must
   be routed to the BFF-wave owners **AG3-090** (routing shell) / **AG3-091**
   (read-model). AG3-105 must not build it and must not invent frontend
   persistence. **Action required: owner decision — extend AG3-090/091 scope to add
   a `task_management` `http/` module / read-model.**
3. **doc-only — `_STORY_INDEX.md` drift (var/, not authoritative).** Index row
   `:120` still says "n:m zu Stories/Artefakten" and surface
   "create_task/link_task/resolve_task". Both are stale vs. the now-authoritative
   FK-77/`formal.task-management.*` (links `task | story`; surface also has
   `unlink_task`/`dismiss_task`). `_STORY_INDEX.md` lives in ephemeral `var/` with
   no authoritative owner, so AG3-105 follows FK-77 + formal-spec and reports the
   drift as a doc-only nachzug — **not** corrected in this story's cut.
