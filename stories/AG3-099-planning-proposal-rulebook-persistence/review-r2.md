OVERALL CHANGES-REQUESTED

**Per-Dimension Verdict**
- Konzept-Vollstaendigkeit: CHANGES-REQUESTED
- AC-Schaerfe: CHANGES-REQUESTED
- Klarheit: PASS for round-1 corrections
- Kontext-Sinnhaftigkeit: CHANGES-REQUESTED

**Round-1 ERROR Verification**
All named R1 ERROR families are resolved in current `story.md`/`status.yaml`: ten schema families are stated correctly, AC6 demands exactly ten round-trip tests, AG3-081 is a hard EventTypeId precondition with no second enum, real write anchors are cited, and `ProjectionAccessor.write_projection` is used instead of inventing `Telemetry.write_projection`.

**Remaining Must-Fix ERROR**
- **ERROR:** AG3-099 is not buildable against the real `ProjectionAccessor` contract. The story says the ten BC14 schema families are created as `ProjectionKind` + `ProjectionRecord` and written via `ProjectionAccessor.write_projection` ([story.md](T:/codebase/claude-agentkit3/stories/AG3-099-planning-proposal-rulebook-persistence/story.md:34)), but the real code pins `ProjectionKind` to exactly seven FK-69 values ([projection_accessor.py](T:/codebase/claude-agentkit3/src/agentkit/telemetry/projection_accessor.py:56)) and contract tests enforce exactly seven ([test_projection_accessor.py](T:/codebase/claude-agentkit3/tests/contract/telemetry/test_projection_accessor.py:32)). `write_projection` also only maps current accessor-owned kinds, not planning records ([projection_accessor.py](T:/codebase/claude-agentkit3/src/agentkit/telemetry/projection_accessor.py:85), [projection_accessor.py](T:/codebase/claude-agentkit3/src/agentkit/telemetry/projection_accessor.py:190)). Fix: AG3-099 must explicitly scope the BC-9 projection registry/accessor expansion or split needed for BC14-owned planning tables, including `ProjectionRepositories`, record union/registry, schema adapters, and contract-test updates. Do not leave this as implicit “add ProjectionKind values”; that currently breaks the pinned FK-69 contract.

Non-blocking note: `_STORY_INDEX.md` still has the old “acht fehlenden” summary at line 135, but the current story/status are internally corrected.
