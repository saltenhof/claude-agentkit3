OVERALL CHANGES-REQUESTED

**1. Konzept-Vollstaendigkeit: WARNING**

AG3-103 now names the assigned stale prose, including FK-68 §68.2.2 `review_divergence`, and it names the Permission-TTL 600 vs. 1800 owner question. The coverage is mostly complete.

Finding: §68.2.2 is included, but the story overstates its grounding. Current real code still emits `score`/`routing` in [divergence_hook.py](t:/codebase/claude-agentkit3/src/agentkit/telemetry/hooks/divergence_hook.py:93), while AG3-103 says the “real emittierte” payload schema is Code/FK-34 authority in [story.md](t:/codebase/claude-agentkit3/stories/AG3-103-concept-nachzug-schema-catalog-defaults/story.md:52). That is only true after AG3-066, not in current code.

**2. AC-Schaerfe: ERROR**

The ACs are not executable as written. AC1/AC4/AC4a require FK prose to be rewritten in `concept/`, but the story also says “keine `concept/`-Aenderung” in [story.md](t:/codebase/claude-agentkit3/stories/AG3-103-concept-nachzug-schema-catalog-defaults/story.md:5), repeats that for §68.2.2 in [story.md](t:/codebase/claude-agentkit3/stories/AG3-103-concept-nachzug-schema-catalog-defaults/story.md:52), and tells the sub-agent not to edit the `concept/` file in [story.md](t:/codebase/claude-agentkit3/stories/AG3-103-concept-nachzug-schema-catalog-defaults/story.md:81).

For a concept/doc-only story, “doc-only” must mean concept docs only, no `src/`/`tests/` diff. As written, the story blocks its own ACs.

**3. Klarheit: ERROR**

The story mixes two meanings of “this story”: story-spec editing vs. actual AG3-103 execution. DoD says “Konzept-Prosa-Aenderung + Commit” in [story.md](t:/codebase/claude-agentkit3/stories/AG3-103-concept-nachzug-schema-catalog-defaults/story.md:68), while the instructions say the story only describes the concept change and does not execute it. That ambiguity is operationally dangerous.

**4. Kontext-Sinnhaftigkeit: ERROR**

The schema/default/code-reality grounding is mostly good: no `*.schema.json` files exist, FK-93 TTL is 1800 while code default is 600 in [requests.py](t:/codebase/claude-agentkit3/src/agentkit/governance/ccag/requests.py:42), `governance_observer` and `llm_pools` are empty, FK-91 conflicts with project-scoped routes in [routes.py](t:/codebase/claude-agentkit3/src/agentkit/execution_planning/http/routes.py:40).

But §68.2.2 does not currently align FK prose to code reality; it aligns FK-68 prose to FK-34 plus intended AG3-066 code. That can be valid only if the story explicitly models sequencing or states it is aligning to the AG3-066 target after code migration. Right now it rejects a hard AG3-066 dependency while claiming current code authority.

**Must-Fix**

1. Remove or rewrite every “keine `concept/`-Aenderung” instruction. AG3-103 must allow `concept/` edits and forbid only `src/`/`tests/` changes.

2. Fix §68.2.2 wording: do not claim the current real emitted code payload is already FK-34-shaped. Either add a real dependency/ordering note on AG3-066 or phrase it as “FK-68 prose aligns to FK-34 and the AG3-066 target schema.”

3. Keep Permission-TTL as explicit PO clarification: FK 1800 vs. code 600, with AG3-086/AG3-070 as code/config owners. Do not let AG3-103 silently pick a value.

4. AC6 should say concept gates/frontmatter green and no `src/`/`tests/` diff; `concept/` diff is expected for this story.
