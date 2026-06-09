OVERALL CHANGES-REQUESTED

**Per-Dimension Verdict**
- Konzept-Vollstaendigkeit: FAIL
- AC-Schaerfe: FAIL
- Klarheit/Eindeutigkeit: FAIL
- Kontext-Sinnhaftigkeit: FAIL

Round-1 fixes are mostly present on paper: ECharts is now explicit, BC is corrected to `kpi_analytics`, `failure_corpus` is listed, and `kpi` uses re-fetch instead of field-level patching. Still blocking:

**Remaining Must-Fix ERRORs**
1. **KPI endpoint/filter contract is not buildable against AG3-084/FK-72.**  
   AG3-094 still hardcodes `/api/kpi/*` and `/api/live/stories` as consumed backend scope in [story.md](T:/codebase/claude-agentkit3/stories/AG3-094-dashboards-live-updates-sse/story.md:43), while FK-72’s BFF convention is `/v1/projects/{key}/...` and `kpi_analytics/http` is `/v1/projects/{key}/kpis`. AG3-084 also explicitly routes final paths through `/v1/...` and out-scopes `/api/live/stories`. Fix AG3-094 to consume the final AG3-084 `/v1` contract, not `/api/*`.

2. **FK-63 filter UI is claimed, but AG3-084 does not provide the full pass-through contract.**  
   AG3-094 requires Templates and Pipeline-Modus filters in [story.md](T:/codebase/claude-agentkit3/stories/AG3-094-dashboards-live-updates-sse/story.md:34), but AG3-084’s query model only binds `from/to`, `guard`, `pool`, `story_type`, `story_size`, plus comparison; FK-63 §63.4.2 also notes template analytics is not directly filterable. Either extend AG3-084 explicitly or narrow/routable-disable those UI filters.

3. **Graph live routing uses the wrong topic set.**  
   AG3-094 says Board/Graph subscribes to `stories,phases` in [story.md](T:/codebase/claude-agentkit3/stories/AG3-094-dashboards-live-updates-sse/story.md:57). But FK-72 maps Graph to `execution_planning`, and `dependency_graph_changed` is a `planning` topic in the formal frontend events spec. Graph changes would not live-update. Fix topic sets and tests: Graph/ready/limits need `planning` where they consume planning state.

4. **`failure_corpus` was added to Analytics subscribe, but behavior and AC are missing while the schema is open.**  
   FK-91 marks `failure_corpus` wire schema open. AG3-094 subscribes Analytics to it, but AC5 only verifies `stories`, `planning`, `kpi`, and `telemetry`. Define re-fetch-on-`failure_corpus` for the Analytics funnel and add an AC, or remove the topic and route it fully to AG3-078/follow-up.

Non-blocking but still unresolved from R1 as WARNING: AC9 still does not give exact concept-gate commands; it says “exakte Subcommands wie in ... Vorgaenger-Stories” instead of naming them. Read-only review only; no files changed.
