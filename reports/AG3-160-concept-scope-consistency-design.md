# AG3-160 — Concept-Scope-Consistency-Sweep (W3): DESIGN FREEZE

Authoritative design contract for the Codex worker. Story:
`stories/AG3-160-concept-scope-consistency-sweep/story.md`. Size M, ONE story. Last of the
concept-gate sequence (W1/W4/W2 landed). W3 is a clean ADDITION on top of the landed W2 infra
(`tools/concept_governance/`). This freeze bakes in the AG3-159 lesson from the start: NO full-corpus
load test — bounded by design + smoke-test proof.

## 0. Bounded-by-design + AC7 RESCOPE (apply the AG3-159 lesson up front, PO-authorized)
W3 makes ONE LLM call per `authority_over` **scope-set** (or per deterministic partition of a large
set) — NOT one per chunk. The scope universe is the L5-disjoint union of `authority_over` scopes
(order of dozens), so a full sweep is ~dozens of calls, not ~1271. Still, per the AG3-159 rescope:
- **AC7 real proof = a bounded SMOKE TEST** over a HANDFUL of scope-sets against the real hub
  (chatgpt/gemini/grok/qwen, skip kimi), iterable if needed. NOT a full all-scopes sweep as a closure
  gate.
- **Baseline starts EMPTY** (reuse the W2 baseline file/mechanic; W3 adds its own finding kind, no
  second format). Bestand population is INCREMENTAL (nightly / pre-merge for touched scopes), a
  separate operational activity — NOT this tool-story's acceptance.
The tool is developed with ZERO hub calls (fixed LLM answers in tests). This directly satisfies the
story's O(n²)-avoidance (AC3) AND avoids the load-test trap.

## 1. Deterministic set-building (AC1, AC3) — no full-corpus classification
For each `authority_over` scope in the live vocabulary, gather its candidate assertion-chunks
DETERMINISTICALLY from the repo-local discovery source (`concept_ingester.discovery`) by INVERTING the
landed `concept_governance.chunks.authorization_scopes(chunk)` (chunks.py:33 — authority_over ∪
scope-qualified defers_to from the chunk's projected metadata): a chunk belongs to scope X's set iff X
is in that chunk's authority scopes. One closed set per scope. Reproducible, ID-stable, NO LLM, NO
external Weaviate/MCP (AC5). Do NOT run a full per-chunk W2 LLM classification to build sets — the
sweep reads the set text directly.

## 2. LLM sweep per scope-set (AC2) — LLM never decides
One structured LLM call per scope-set via the REUSED epoch-rotation transport
(`concept_governance.hub_batch.HubBatchSession` — open/send/checkpoint/close, bounded lease epochs,
one lease per backend, fencing). Prompt: the closed assertion-set → structured contradiction
pairs/groups WITH the quoted assertion text + anchors. LARGE sets are DETERMINISTICALLY partitioned
(stable partition boundaries), never silently truncated (AC1/AC6). The LLM output is ONLY the
classification input; the ERROR/PASS decision is made in the deterministic policy (mirror
`concept_governance.policy.evaluate_policy` — the landed W2 pattern where the code, not the LLM,
decides). Prompt asset `tools/concept_governance/prompts/scope_consistency_v1.md`, versioned
(prompt_version + sha, mirror W2).

## 3. Deterministic policy + P4 (AC2, AC4)
A reported contradiction between two assertions of the SAME scope → deterministic ERROR finding
(`SCOPE_CONTRADICTION` or similar) with both loci (doc, anchor, assertion text), scope, prompt/model
version — compared against the baseline; new/non-baselined = ERROR until triage. Each triaged finding
carries the MANDATORY P4 field (formalization check: yes/no + reason) — a required field of the
finding/baseline entry, not advisory (META §3/P4). Decision in policy, never LLM.

## 4. Baseline reuse (AC4) — ONE mechanic, no second format
Reuse the landed W2 `concept_governance.baseline` (`BaselineEntry` with mandatory non-empty `reason`,
unique keys, `load_baseline`, keyed suppression, stale detection). W3 findings are a distinct finding
KIND in the SAME baseline file/mechanic (SINGLE SOURCE OF TRUTH of governance findings). Unjustified
entry → run fails (INVALID_BASELINE). New finding → ERROR until triage. Extend the baseline
entry/key only if genuinely needed for the W3 kind + the P4 field; keep it one format.

## 5. Fail-closed operation (AC5, AC6)
Hub unreachable / unparseable response / INCOMPLETE sweep (any scope-set or partition left unchecked
— timeout/failure) → a NAMED run finding with exit ≠ 0; NO partial baseline mutation; NO "empty PASS".
Explicitly: an incomplete sweep is a named `INCOMPLETE_SWEEP` finding, never silent omission (AC6).
The run works with NO reachable external index (AC5; only the LLM hub is an external dependency).

## 6. Nightly wiring (AC7-operations) — regular CI unchanged
CI entry `scripts/ci/check_concept_scope_consistency.py` (sys.path bootstrap like the siblings; argparse
incl. a `--scope` filter for the scope-filtered pre-merge call + a `--limit`/smoke switch). Nightly
stage next to the W2 nightly (non-blocking); scope-filtered pre-merge invocation documented in
AGENTS.md + governance §6. W3 is NOT a blocking per-push CI gate and NEVER calls the hub in per-push
CI (deterministic parts only there, fixed evaluations). W1/W4 blocking stages unchanged.

## 7. Tests (AC1-6) — deterministic, no live hub in CI
Unit-test with fixed LLM answers (scripted evaluator, NO hub): (1) set-building — per scope exactly
the expected chunks, no foreign, stable across two runs; (2) a same-scope contradiction fixture →
ERROR with both loci; policy decides (no LLM); (3) O(n²)-avoidance — assert LLM-call count == number
of scope-sets/partitions, NOT quadratic in chunk count, and never cross-scope pairs; (4) baseline —
unjustified entry fails, new finding ERROR, P4 field required; (5) run with no external index still
works; (6) incomplete sweep (a partition fails) → INCOMPLETE_SWEEP, exit≠0, no baseline mutation;
hub-unreachable → named run finding. One REAL-hub smoke over a HANDFUL of scope-sets (evidence to
var/evidence/), NOT a full all-scopes sweep. No generated files under tests/fixtures/.

## 8. Green-on-main + review plan
Worker owns green: pytest --ignore=tests/e2e, ruff, mypy strict native + --platform linux, concept
gates (W1/W4 green; W2/W3 not blocking gates), coverage ≥85%. Blood types: set-building/partition/
policy/finding+P4 model = A; parsing/serialization = R; hub transport + file/CI = T. Then Codex
read-only review + orchestrator code-adjudication (focus: LLM-never-decides in the policy; bounded
call-count = set/partition count; only same-scope sets, never cross-scope pairs; baseline one-mechanic
reuse + P4 required; incomplete-sweep fail-closed) → whole-story Fable finale → Jenkins + Sonar 0/0/0
on the final commit + a bounded real-hub smoke (a handful of calls). Serialize: no orchestrator
git/gate ops while the worker is active on the shared tree.
