OVERALL: CHANGES-REQUESTED

**Per-Dimension Verdict**
- Konzept-Vollständigkeit: FAIL. `story.md` removes FK-64/token scope, but `_STORY_INDEX.md` still assigns AG3-084 `FK-64 §64.2` and `get_design_tokens` at line 90, while the story claims the Schnittfrage is “hier geschlossen” at [story.md](T:/codebase/claude-agentkit3/stories/AG3-084-dashboard-backend-kpi-endpoints/story.md:11).
- AC-Schärfe: WEAK. AC2/AC6/AC7/AC8 are now testable. AC5 is not implementable against current code because the named `ProjectionAccessor` port has no live-read API for `execution_events`/`flow_executions` and rejects `phase_state_projection`.
- Klarheit/Eindeutigkeit: FAIL. The story locally closes an open PO/index question, but the authoritative index still states the opposite/open state at [_STORY_INDEX.md](T:/codebase/claude-agentkit3/var/concept-gap-analysis/_STORY_INDEX.md:90) and [_STORY_INDEX.md](T:/codebase/claude-agentkit3/var/concept-gap-analysis/_STORY_INDEX.md:175).
- Kontext-Sinnhaftigkeit: FAIL. FK-63 §63.5 does point to `ProjectionAccessor`, but current `src/agentkit` cannot satisfy the story’s live endpoint without additional telemetry work.

**Round-1 Must-Fix Status**
- E1/E4 FK-64 token endpoint: partially resolved in `story.md`; not resolved in `_STORY_INDEX.md`.
- E2 project/tenant scope: resolved. AC2 requires `project_key` and fail-closed behavior.
- E3 `PeriodFilter` misuse: resolved. AC6 defines `KpiQueryFilter`.
- E5 open Schnittfrage: not genuinely resolved; it was reworded as locally closed, while the index remains open/conflicting.
- E6 `DashboardService` too broad: resolved. Scope is now limited to KPI/story-metrics and preserves `get_board`.

**Remaining/New Must-Fix ERRORs**
1. ERROR: AG3-084 scope conflicts with `_STORY_INDEX.md`.
   Evidence: index line 90 still says AG3-084 includes `FK-64 §64.2` and `get_design_tokens`; index line 175 still frames AG3-084 vs AG3-092 token ownership as an open PO question. Story line 11 claims this is closed and moves all token delivery to AG3-092.
   Fix: update `_STORY_INDEX.md`/decision source to remove FK-64 + token endpoint from AG3-084 and close question 4, or restore token scope in AG3-084 with a concept-consistent owner/path.

2. ERROR: `/api/live/stories` via `ProjectionAccessor` is unimplementable as scoped.
   Evidence: story AC5 requires live reads via `telemetry-and-events.ProjectionAccessor` at [story.md](T:/codebase/claude-agentkit3/stories/AG3-084-dashboard-backend-kpi-endpoints/story.md:54), while `ProjectionAccessor.read_projection()` only reads QA, story_metrics, and fc_incidents; `PHASE_STATE_PROJECTION` is rejected at [projection_accessor.py](T:/codebase/claude-agentkit3/src/agentkit/telemetry/projection_accessor.py:394). The repository adapter explicitly says “kein Read via ProjectionAccessor derzeit” at [projection_repositories.py](T:/codebase/claude-agentkit3/src/agentkit/state_backend/store/projection_repositories.py:1039).
   Fix: either add/require a prior telemetry story that exposes a project-scoped live-read port for `execution_events`/`flow_executions`/`phase_state_projection`, or move `/api/live/stories` out of AG3-084 until that port exists.
