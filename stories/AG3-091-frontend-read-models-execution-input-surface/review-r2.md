OVERALL CHANGES-REQUESTED

**Per-Dimension Verdict**
- Konzept-Vollstaendigkeit: FAIL
- AC-Schaerfe: FAIL
- Klarheit: FAIL
- Kontext-Sinnhaftigkeit: FAIL

**Resolved R1 Checks**
`execution-input/limits`, mode-lock wire shape without `holder_count`, snake_case wire fields, real planning routes, and “no standalone project-config GET” are genuinely corrected in AG3-091.

**Remaining Must-Fix ERRORs**
1. `execution-input/next` still has no full formal endpoint entity while AG3-091 still plans to ship typed reason fields. Binding only the returned story to `story_summary`/snapshot does not satisfy FK-72 §72.14.3 for the full response payload. Evidence: [story.md](T:/codebase/claude-agentkit3/stories/AG3-091-frontend-read-models-execution-input-surface/story.md:34), [story.md](T:/codebase/claude-agentkit3/stories/AG3-091-frontend-read-models-execution-input-surface/story.md:66), [entities.md](T:/codebase/claude-agentkit3/concept/formal-spec/frontend-contracts/entities.md:669), [72_frontend_architektur.md](T:/codebase/claude-agentkit3/concept/technical-design/72_frontend_architektur.md:445). Fix: either make AG3-091 depend on the AG3-100 formal entity before implementing `next`, or remove/defer `next` reason fields from AG3-091.

2. AG3-091 and current AG3-100 both own the same `snapshot`/`next` endpoints and the same “one deterministic selector” implementation. That violates the single-owner/single-selector rule and is not buildable without duplicate ownership. Evidence: [story.md AG3-091](T:/codebase/claude-agentkit3/stories/AG3-091-frontend-read-models-execution-input-surface/story.md:32), [story.md AG3-091](T:/codebase/claude-agentkit3/stories/AG3-091-frontend-read-models-execution-input-surface/story.md:50), [story.md AG3-100](T:/codebase/claude-agentkit3/stories/AG3-100-evaluate-scheduling-execution-input-surface/story.md:28), [story.md AG3-100](T:/codebase/claude-agentkit3/stories/AG3-100-evaluate-scheduling-execution-input-surface/story.md:29). Fix: make one story own the selector/endpoints and the other explicitly consume/reuse it, with status dependencies aligned.
