OVERALL: **CHANGES-REQUESTED**

**Round-1 Must-Fix Check**
- E1 Trigger contract: **resolved**. `sync_analytics(trigger, project_key, hint_story_id=None)` + `RefreshTrigger` is explicit in [story.md](T:/codebase/claude-agentkit3/stories/AG3-082-kpi-refresh-worker/story.md:34), facade mapping in [story.md](T:/codebase/claude-agentkit3/stories/AG3-082-kpi-refresh-worker/story.md:35).
- E2 Ownership boundary: **resolved**. ProjectionAccessor/FactStore-only rule is AC6 in [story.md](T:/codebase/claude-agentkit3/stories/AG3-082-kpi-refresh-worker/story.md:65).
- E3 Guard counter drain/delete: **resolved**. Transfer + delete + reset cleanup in [story.md](T:/codebase/claude-agentkit3/stories/AG3-082-kpi-refresh-worker/story.md:43) and AC8 [story.md](T:/codebase/claude-agentkit3/stories/AG3-082-kpi-refresh-worker/story.md:67).
- E4 Dirty sets + atomic rollback: **resolved**. Matrix in [story.md](T:/codebase/claude-agentkit3/stories/AG3-082-kpi-refresh-worker/story.md:37), rollback AC in [story.md](T:/codebase/claude-agentkit3/stories/AG3-082-kpi-refresh-worker/story.md:63).
- E5 Read-model purge scope: **resolved**. AG3-082 calls the AG3-081 port, does not implement it, in [story.md](T:/codebase/claude-agentkit3/stories/AG3-082-kpi-refresh-worker/story.md:36) and [story.md](T:/codebase/claude-agentkit3/stories/AG3-082-kpi-refresh-worker/story.md:51).
- E6 P50/P95 / AG3-083 conflict: **not genuinely resolved**. See ERROR 1.
- E7 FactStore transaction/delete/replace ports: **resolved**. In scope in [story.md](T:/codebase/claude-agentkit3/stories/AG3-082-kpi-refresh-worker/story.md:45), AC11 in [story.md](T:/codebase/claude-agentkit3/stories/AG3-082-kpi-refresh-worker/story.md:70).

**Per-Dimension Verdict**
- Konzept-Vollständigkeit: **FAIL**. Dashboard catch-up materialization from FK-62 is still not owned, and `schema_version` has no initialization path.
- AC-Schärfe: **FAIL**. AC9/AC10 encode fail-closed behavior but leave ordering/seed prerequisites unresolved.
- Klarheit/Eindeutigkeit: **FAIL**. AG3-082/AG3-083 ordering is contradictory; one anchor points to the wrong AC.
- Kontext-Sinnhaftigkeit: **FAIL**. Current code lacks p50/p95 columns and has no `schema_version` seed; downstream stories exclude the routed dashboard materialization.

**Must-Fix ERRORs**
1. **AG3-083/P50 ordering remains contradictory.**  
   Evidence: AG3-082 status depends only on AG3-038/AG3-081 [status.yaml](T:/codebase/claude-agentkit3/stories/AG3-082-kpi-refresh-worker/status.yaml:8), while AG3-082 says p50/p95 target columns are AG3-083-owned and missing columns fail closed [story.md](T:/codebase/claude-agentkit3/stories/AG3-082-kpi-refresh-worker/story.md:48). AG3-083 itself says it provides `response_time_p50_ms` and unblocks AG3-082 [story.md](T:/codebase/claude-agentkit3/stories/AG3-083-kpi-catalog-fact-columns/story.md:43), [status.yaml](T:/codebase/claude-agentkit3/stories/AG3-083-kpi-catalog-fact-columns/status.yaml:11). Current code has only `avg_latency_ms` [models.py](T:/codebase/claude-agentkit3/src/agentkit/kpi_analytics/fact_store/models.py:72), [postgres_schema.sql](T:/codebase/claude-agentkit3/src/agentkit/state_backend/postgres_schema.sql:849).  
   Fix: make ordering coherent. Either add AG3-083 as hard dependency of AG3-082 and align story/status/index, or remove all p50 persistence obligation from AG3-082.

2. **`sync_state.schema_version` fails closed but has no writer/seed owner.**  
   Evidence: AG3-082 requires missing/mismatched `schema_version` to stop the worker [story.md](T:/codebase/claude-agentkit3/stories/AG3-082-kpi-refresh-worker/story.md:44). FK-62 requires the entry [62_kpi_aggregation.md](T:/codebase/claude-agentkit3/concept/technical-design/62_kpi_aggregation.md:610). Current migrations only create the table, no seed [v_3_4_analytics.sql](T:/codebase/claude-agentkit3/src/agentkit/state_backend/migration/versions/v_3_4_analytics.sql:94); code only exposes read/upsert ports [fact_repository.py](T:/codebase/claude-agentkit3/src/agentkit/state_backend/store/fact_repository.py:421).  
   Fix: assign an explicit owner and AC for initializing/updating `(project_key, "schema_version") = EXPECTED_SCHEMA_VERSION` before first refresh, without hidden worker-side migration.

3. **Dashboard catch-up materialization is routed to stories that do not own it.**  
   Evidence: FK-62 requires dashboard sync to materialize non-closed stories [62_kpi_aggregation.md](T:/codebase/claude-agentkit3/concept/technical-design/62_kpi_aggregation.md:562). AG3-082 explicitly excludes it [story.md](T:/codebase/claude-agentkit3/stories/AG3-082-kpi-refresh-worker/story.md:93). AG3-083 excludes RefreshWorker/fill logic [story.md](T:/codebase/claude-agentkit3/stories/AG3-083-kpi-catalog-fact-columns/story.md:68); AG3-084 also excludes RefreshWorker/fill logic [story.md](T:/codebase/claude-agentkit3/stories/AG3-084-dashboard-backend-kpi-endpoints/story.md:42).  
   Fix: keep dashboard materialization in AG3-082 after adding the needed AG3-083 dependency, or create a real owner story with status dependency. Current “AG3-083/084” routing is not valid.

4. **Anchor defect in prerequisite reference.**  
   Evidence: AG3-082 says AG3-081 prerequisite is “siehe §2.3, AK11” [story.md](T:/codebase/claude-agentkit3/stories/AG3-082-kpi-refresh-worker/story.md:29), but ordering gate is AC12 [story.md](T:/codebase/claude-agentkit3/stories/AG3-082-kpi-refresh-worker/story.md:71); AC11 is FactStore ports [story.md](T:/codebase/claude-agentkit3/stories/AG3-082-kpi-refresh-worker/story.md:70). The AG3-081 path is also abbreviated with `...`.  
   Fix: point to AC12 and use the exact `stories/AG3-081-event-buildout-bc14-bc15-integrity-dim8/status.yaml:4-5` anchor.
