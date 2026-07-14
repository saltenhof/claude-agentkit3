# AG3-159 — Concept-Authority-Prose-Check (W2): DESIGN FREEZE

Authoritative design contract for the Codex worker. Story:
`stories/AG3-159-concept-authority-prose-check/story.md`. Size L, ONE story — ships as one unit;
the internal review→fix loop is normal. This freeze FIXES the decisions the story delegates
("Design dieser Story"): module placement, LLM transport seam, deterministic policy, scope
vocabulary, baseline format, prompt/model versioning, nightly/pre-merge wiring, and the first-baseline
approach. Grounded in the scout brief (facts file:line-cited there); do not re-derive.

## 0. Feasibility (confirmed) + the core determinism rule
Hub reachable: `GET http://127.0.0.1:9600/api/health` → status `degraded`, backends chatgpt/grok/qwen/
kimi = `ok` (gemini login_required). So AC7 (first-baseline triage via the LLM) is executable.
**HARD determinism rule:** W2 calls an LLM → it is NOT deterministic and NOT hub-free, therefore it
MUST NOT be added to the blocking per-push CI (which stays fully deterministic — W1/W4 only). W2 runs
(a) as a NON-blocking nightly Jenkins stage and (b) as a documented pre-concept-merge CLI invocation.
The blocking regular CI proves ONLY the deterministic parts (chunking, policy, baseline mechanic) via
unit tests with FIXED evaluations (no hub). The real LLM runs only in nightly + the one-time
first-baseline generation the worker performs locally.

## 1. Module placement + CI entry (scout §9)
- New sibling package `tools/concept_governance/` (does not exist yet), split into small cohesive
  modules like AG3-158's `decision_record*.py` family (module-level code ≤100 LOC; function-level lazy
  imports). Blood types: policy/scope-vocab/finding+baseline models = **A**; LLM-response parsing +
  finding serialization = **R**; hub transport + file/CI mechanics = **T**.
- CI entry `scripts/ci/check_concept_authority_prose.py` replicating the sys.path bootstrap the sibling
  gates use (`SRC_ROOT = parents[2]/"src"`, `TOOLS_ROOT = parents[2]/"tools"`, insert both), then
  `from concept_governance import ...`. argparse: `--repo-root`, `--concept-root` (default `concept`),
  `--baseline` (default `concept/_meta/authority-prose-baseline.yaml`), `--mode {nightly,pre-merge}`,
  `--base <ref>` (pre-merge diff scoping, default `origin/main`), and an OFFLINE/injection switch for
  tests. Exit `0` pass / `1` on findings; `raise SystemExit(main())`.

## 2. Deterministic chunk source (scout §1; AC3)
Use `concept_ingester.discovery.discover(concept_root, max_chars) -> DiscoveryResult` (working-tree
only, NO Weaviate/MCP). Consume `ConceptChunk`: `chunk_id` (stable uuid5 of `rel_path#anchor`),
`rel_path`, `section_anchor`, `heading`, `content`, and `metadata["authority_over_full"]` /
`metadata["defers_to_full"]` (JSON of the scope-qualified entries) as the authorization source. Two
runs on an identical tree → identical chunk_ids (AC3). There must be NO code path that requires the
external index (negative test: run with no reachable index).

## 3. LLM evaluation — the transport seam + fail-closed parse (scout §2,§3; AC1,AC6)
- **Seam for fakes:** define a thin W2-local port `AuthorityProseEvaluator` (Protocol) with a single
  method returning a typed `ChunkClassification` for one chunk. Policy/CLI depend on the PORT, never on
  the hub, so AC1 policy tests inject a scripted fake (mirror `_ScriptedLlmClient`,
  test_structured_evaluator.py:41-53).
- **Productive impl (T):** reuse the existing `LlmClient` port + `HubLlmClient`
  (verify_system/llm_evaluator/llm_client.py:225) if a governance role/pool binds cleanly; otherwise a
  thin governance transport that drives `multi_llm_hub.HubClient` acquire→send→release itself
  (release best-effort in `finally`, queued-retry bounded) — do NOT reinvent the lifecycle if reuse
  works. Keep the FK-75 adapter thin; all eval/policy logic lives in the tool.
- **Structured 2-question eval per chunk** (META §5/W2): (1) does this section make normative
  statements? (2) about which scopes? Response parsed into a FROZEN Pydantic v2 model
  (`ConfigDict(frozen=True, extra="forbid")`) mirroring the StructuredEvaluator response pattern.
  Fail-closed parse: bounded retry with one schema-hint, then raise (never a silent empty result).
- **Unknown scope** named, not dropped: an LLM-named scope not in the corpus vocabulary (§4) is its
  own named result `UNKNOWN_SCOPE_MENTION`, surfaced — never silently discarded (AC scope-vocab).

## 4. Deterministic policy — the LLM NEVER decides (scout §4; AC1,AC2)
- **Authorization set for a doc** = its `authority_over` scopes ∪ its **scope-qualified** `defers_to`
  scopes. A scalar document-level `defers_to` (no scope) authorizes NO specific-scope claim
  (fail-closed). Parse both shapes exactly as `discovery._normalise_defers_to` / the reference-integrity
  loader do (scalar string → scope=None; dict requires non-empty `target`+`scope`).
- **The rule:** a chunk classified as making a normative statement about scope X, in a doc whose
  authorization set does NOT contain X → **ERROR** `UNAUTHORIZED_SCOPE_ASSERTION` ("unzuständige
  Behauptung", §4 P2). The contradiction itself need not be found. The PASS/ERROR decision is made
  purely by this registry comparison in code; the LLM output is only classification input (AC1 —
  proven by policy unit tests running fully on fixed evaluations, no LLM).
- **Counter-probe (AC2):** the same doc with a scope-qualified `defers_to` edge for X → no finding.

## 5. Scope vocabulary (scout §4)
= the live union of all `authority_over[].scope` values across the corpus (there is NO canonical scope
file), globally disjoint by lint L5. Build it deterministically from frontmatter via
`concept_compiler.loader.try_load_frontmatter`. Pass the vocabulary to the evaluator so the LLM answers
against a closed scope list; scopes outside it → `UNKNOWN_SCOPE_MENTION` (§3).

## 6. Idempotent findings + justified baseline (scout §6; AC4,AC5)
Mirror `concept/_meta/reference-integrity-baseline.yaml` mechanics EXACTLY (the proven precedent):
- **Finding reference (idempotent):** `{code, doc (rel_path), anchor (section_anchor), assertion
  (the normative statement text), scope, prompt_version, model}`. Stable across runs on an identical
  tree + identical prompt/model.
- **Baseline file** `concept/_meta/authority-prose-baseline.yaml`: `version: 1` + a list of entries,
  each carrying the finding key fields PLUS a MANDATORY non-empty `reason`. An entry with a
  missing/blank `reason` makes the RUN fail (`INVALID_BASELINE` — copy `_parse_unresolved_baseline`
  reason-enforcement). Keyed suppression (baselined finding is suppressed but still LISTED, never
  silently vanishes). Stale baseline entries (no longer matching any active finding) are surfaced
  (`_stale_baseline_findings` precedent). A new, non-baselined finding is ERROR until triage.

## 7. Prompt/model versioning (scout §5; AC5)
- Prompt asset lives WITH the tool: `tools/concept_governance/prompts/authority_prose_v1.md`
  (NOT under `bundles/` — that is deployed target-project assets; this is repo governance). Its
  identity = an explicit `prompt_version` id (e.g. `authority-prose/v1`) + the SHA-256 of the rendered
  prompt (mirror `template_sha256`). Findings carry `prompt_version` + resolved `model`/backend id.
- A prompt or model change does NOT silently invalidate the baseline: it produces a NAMED
  re-evaluation state (findings whose `prompt_version`/`model` differ from a baseline entry's do not
  match its key → they surface as new, and the stale entry surfaces too). Contract-pin the finding +
  baseline schema in a test.

## 8. Fail-closed operation (scout §3; AC6)
Hub unreachable / timeout (`HubUnavailableError`) / unparseable response after bounded retry →
a NAMED run finding (`EVALUATION_TRANSPORT_FAILURE` / `EVALUATION_PARSE_FAILURE`) with exit ≠ 0. NO
partial result mutates the baseline; NO "empty PASS". The login_required backend (gemini) must not
wedge the run — target only healthy backends / a configured governance pool.

## 9. Nightly + pre-merge wiring (scout §7; AC8) — regular CI UNCHANGED
- Jenkinsfile already has `triggers { cron('H * * * *') }` + `agentkit_mode` param. Add a NON-blocking
  stage that runs W2 only in a nightly mode (e.g. gate on a new `params.agentkit_mode == 'nightly'` or
  a dedicated stage that does not `set -e`-fail the ci build) — do NOT join the blocking W1/W4 stages.
- Pre-merge: document the CLI invocation `python scripts/ci/check_concept_authority_prose.py
  --mode pre-merge --base "${GIT_PREVIOUS_SUCCESSFUL_COMMIT:-HEAD~1}"` (scoped to the changed concept
  docs in the range) in AGENTS.md next to the sibling-gate notes + governance §6. The regular blocking
  CI stage set stays exactly as-is.

## 10. First-baseline (AC7) — document existing state with GENUINE reasons, NO big-bang
The worker runs W2 once locally against the full corpus (hub reachable), triages EVERY finding: fix
the doc OR add a justified baseline entry. Remediation of legacy P1/P2 violations is explicitly OUT of
scope (story "Out of Scope"); the first baseline DOCUMENTS the existing state with a real per-entry
`reason`. **ZERO DEBT adjudication gate (orchestrator):** report the baseline size and the full entry
list; each `reason` must be a genuine, specific justification (why this assertion is acceptable / why
it is a known-accepted existing state / why it is an LLM false-positive), NOT a rubber-stamp
("existing", "accepted"). Rubber-stamp reasons are ZERO-DEBT violations and will be rejected. If the
first run surfaces a very large number of genuine violations such that honest triage is infeasible
within one story, STOP and report to the PO before committing a mass baseline — do not paper over it.

## 11. Tests (AC1-6) — deterministic, no live hub in CI
Policy/core unit tests inject a scripted fake `AuthorityProseEvaluator` (fixed classifications, no
LLM): (2) unauthorized-scope assertion → ERROR with reference + counter-probe with defers_to edge →
clean; unknown-scope → `UNKNOWN_SCOPE_MENTION`; (3) chunk source deterministic — identical chunk_ids
on two runs, and a run with no reachable external index still works; (4) baseline: unjustified entry
fails the run, non-baselined finding is ERROR, baselined finding stays listed, stale entry surfaced;
(5) prompt/model version pin — a version change surfaces new findings + stale entries (schema
contract-pin); (6) transport failure (fake port raising `HubUnavailableError`) → named run finding,
exit≠0, no baseline mutation. Fakes only at the LLM/transport grenze (MOCKS-Regel); all
parsing/policy/baseline logic runs real. A real-hub contract test is OPTIONAL and must be skipped when
the hub is unreachable (never make CI hub-dependent).

## 12. Green-on-main + review plan
Worker owns green: `.venv\Scripts\python -m pytest --ignore=tests/e2e`, ruff, mypy strict native +
`--platform linux`, the concept gates (W1/W4 must stay green; W2 is NOT a blocking gate), coverage
≥85%. The committed first baseline must make the nightly W2 run clean (or list only justified
entries). Then Codex read-only review + orchestrator code-adjudication (focus: LLM-never-decides,
authorization-set correctness incl. scalar-vs-scoped defers_to, baseline reason enforcement + reason
QUALITY, fail-closed transport, and that no hub call entered the blocking CI) → whole-story Fable
finale → Jenkins + Sonar 0/0/0 on the final commit. Serialize: no orchestrator git/gate ops while the
worker is active on the shared tree.
