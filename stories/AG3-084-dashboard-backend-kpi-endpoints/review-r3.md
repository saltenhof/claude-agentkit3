OVERALL APPROVE

**Per-Dimension Verdict**
- Konzept-Vollständigkeit: PASS. AG3-084 now limits deliverable scope to five `/api/kpi/*` analytics endpoints and the KPI trust-boundary fix. FK-64 tokens are explicitly routed to AG3-092; `/api/live/stories` is explicitly routed out until a real runtime live-read port exists.
- AC-Schärfe: PASS. The former unbuildable live AC is gone. AC8 is now a testable negative boundary: no live endpoint and no fallback via `StoryService` or facts.
- Klarheit/Eindeutigkeit: PASS. The story no longer claims to close the index conflict locally. It flags `_STORY_INDEX.md:90/:175` as PO/Index-owned conflicts and makes resolution/blocker reporting part of DoD.
- Kontext-Sinnhaftigkeit: PASS. The real code supports the stated cut: `ProjectionAccessor` cannot read `execution_events`/`flow_executions` and rejects `PHASE_STATE_PROJECTION`; KPI facts and current `StoryService` drift are accurately represented.

**Round-2 ERROR Verification**
- Design tokens: resolved for AG3-084. Story routes data model and HTTP token delivery out to AG3-092 and explicitly says AG3-084 must not build `get_design_tokens`.
- `/api/live/stories`: resolved for AG3-084. Story removes it from deliverable scope and routes the missing prerequisite to a runtime live-read-port story, with no replacement owner invented inside AG3-084.
- Index conflicts: resolved as honest routing. `_STORY_INDEX.md` is still stale, but AG3-084 now treats that as an external PO/Index blocker, not as a story-local override.

**Remaining Must-Fix ERRORs**
None for AG3-084.

Residual cross-story note: AG3-092’s current draft still says the HTTP `get_design_tokens` endpoint belongs to AG3-084. That must be corrected when the PO/Index routing is applied, but AG3-084 now reports the conflict honestly instead of baking in the wrong scope.
