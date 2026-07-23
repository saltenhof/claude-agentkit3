# AG3-174 — Binding Internal Implementation Plan (Review 174-P2-1)

Status: BINDING. Produced before `status: in_progress` as required by the DoD.
Source of truth: FK-13 (§13.2/§13.3/§13.4/§13.9 incl. §13.9.7/§13.9.9-13),
FK-43, FK-21 §21.4.3, FK-50 CP10b, Decision Record 2026-07-21, po-decisions
D1-D6. No concept conflict found during reading.

## Architectural spine

- **SSOT discovery/parser core** lives ONCE in `src/agentkit/concepts/`
  (transport-free; usable for lint/validate WITHOUT Weaviate). It is owned by
  `discover_concept_files()` in `agentkit/concepts/parser.py` (FK-13 §13.9.13).
- `backend/vectordb/ingest/` and `tools/concept_ingester` are **consumers/
  adapters** on that core — no second discovery/parser path.
- `integration_clients/vectordb/weaviate_adapter.py` stays a **thin** transport
  adapter; the fail-closed repair defaults (empty-string substitution) are
  removed. **Mocks/fakes ONLY at the external Weaviate adapter port.**
- One `StoryContext` collection (FK-13 §13.9.2) holds Story- AND Concept-
  properties; `project_id` is the multi-tenant discriminator.

## Sub-verticals (each = own module + test budget)

### V1 — Packaging / Tokenizer
- `pyproject.toml`: promote `mcp>=1.0` and `weaviate-client>=4.9,<5.0` to real
  `[project.dependencies]` (drop optional `>=4.0` extra); add `tokenizers==0.21.0`.
- Tokenizer asset: versioned package asset under
  `src/agentkit/resources/tokenizer/` (`tokenizer.json`, vocab) + bound
  SHA-256 digest file + pinned revision record + Apache-2.0 license notice.
  Loader checks digest BEFORE parsing; fail-closed on missing/divergent/semantic
  mismatch; no network fetch, no char fallback.
- Module: `src/agentkit/concepts/tokenizer.py` (+ asset metadata).
- Tests: unit `test_tokenizer.py` (digest gate, no-network, semantic-incompat);
  contract `test_packaging.py` (pins/asset list/license recorded).
- AC: 1.

### V2 — Project / Runtime binding (SSOT, Review 174-P0-4)
- `backend/vectordb/project_binding.py`: typed `ProjectBinding`
  (authoritative `project_root`, containment check for all write paths,
  project-local `cwd`, `project_id`, endpoint as config value). No global
  identity registry.
- `backend/vectordb/runtime_binding.py`: `McpServerSpec`/`RuntimeBinding` —
  the SINGLE source of truth for the started process, consumed unchanged by
  AG3-175. `PROJECT_ID` + endpoint come ONLY from registered `env`; `cwd` is
  containment boundary; no localhost/default fallback; missing/empty/wrong-
  typed binding stops fail-closed.
- Tests: unit binding tests (containment rejection, no-default-fallback,
  foreign project_id rejection incl. for `story_list_sources`).
- AC: 4, 11.

### V3 — Ingest/Corpus core SSOT under `src/agentkit/concepts/`
- `concepts/frontmatter.py`: STRICT YAML frontmatter parse — fail-closed, no
  coercion (`errors="replace"`, Pydantic coercion, `.get(default)`, YAML-last-
  wins) — covers the AC10 frontmatter negativematrix.
- `concepts/chunking.py`: heading-based split (`##`/`###`) + overflow split
  under heading level (deterministic, token-bounded via the bound tokenizer).
- `concepts/hashing.py`: SHA-256 chunk/document hashes + `corpus_revision`
  (`SHA-256(sorted(file_hashes)+parser_version)`).
- `concepts/ignore.py`: `.conceptignore` glob matching with correct `**`
  semantics (the 4 boundary cases; NOT bare `Path.match`).
- `concepts/parser.py`: `discover_concept_files()` — THE owner; yields typed
  `ConceptDocument`/`ConceptChunk` carrying all FK-13 §13.9.3 properties.
- Tests: unit per helper + a drift-free equality test that validate/build/sync
  observe the SAME discovery set.
- AC: 5 (discovery equality), 9 (SSOT location + no-Weaviate lint/validate),
  10 (frontmatter strictness).

### V4 — StoryContext schema (complete, idempotent)
- `backend/vectordb/schema.py`: all FK-13 §13.3.1 + §13.9.3 properties
  (`content`, `story_id`, `title`, `status`, `story_type`, `module`, `epic`,
  `source_type`, `source_file`, `section_heading`, `content_hash`,
  `project_id`, `concept_id`, `is_appendix`, `parent_concept_id`, `defers_to`,
  `authority_over`, `section_number`, `normative_rules`, `concept_status`).
  Deterministic UUID (uuid5 from project_id+source_file+chunk_id); idempotent
  collection creation.
- Tests: contract `test_storycontext_schema.py` binding field set to FK-13.
- AC: 2, 8.

### V5 — Three ingest profiles
- `concepts/profiles.py` + `backend/vectordb/ingest/profiles.py`:
  `fk13_concept` / `fk13_story` / `ak3_tool` — token unit, bound tokenizer,
  overflow = deterministic sub-heading split; source-type/producer closure
  (story.md→story→story_sync; research/**→research→story_sync via canonical
  path; concept/arch→concept→concept_sync; review*/closure→NEGATIVE).
- Tests: profile-behaviour equality (drift test vs `tools/concept_ingester`),
  source/producer/delete-closure sequence test (both orders; delete; vanished
  file; incremental; idempotent re-sync; negative research case).
- AC: 3, 9.

### V6 — Corpus lifecycle: validate / build / graph / resolver / freshness
- `backend/vectordb/concept_corpus/validator.py`: `concept_validate` — full
  §13.9.7 error/warning catalog + exit codes 0/1/2/3; `E-CHUNK-001` stays
  blocking even when the generic chunker could split.
- `concept_corpus/graph.py`: candidate-corpus DAG (defers_to, parent_of,
  superseded_by).
- `concept_corpus/builder.py`: `INDEX.yaml` + `concept_graph.json` with shared
  `corpus_revision`; only a validated graph is persisted.
- `concept_corpus/resolver.py`: `ConceptGraphResolver` — the 5 authority-
  ranking rules + deterministic tie-break.
- `concept_corpus/freshness.py`: `corpus_revision` freshness indicator.
- Tests: TABLE-driven contract tests — every error/warning code & exit code,
  all 5 ranking rules + tie-break, core/appendix/archive metadata, the 4
  `.conceptignore` glob boundaries, cyclic/broken authority edges.
- AC: 5, 6 (validate blocks sync; INDEX/graph/revision consistent).

### V7 — Three-rings CLI on the same SSOT
- `backend/vectordb/cli.py`: `concept lint --changed|<file>`, `concept doctor
  --summary`, `concept validate --staged|--corpus --strict`, `concept build`,
  `concept sync`. All call `discover_concept_files()`.
- Tests: `validate --staged` blocks a NEW cross-file error over candidate
  corpus; `--strict` escalates warnings.
- AC: 12. (Firing pre/post-commit install = AG3-176, out of scope.)

### V8 — Bounded-window sync (Review 174-P1-1, D3)
- `backend/vectordb/sync.py`: order (1) write new generation + validate
  should-set; (2) delete old/foreign chunks of the same source AFTER; (3)
  digest-bound sync-receipt with `corpus_revision` ONLY after successful delete;
  (4) crash before receipt leaves the last marker unchanged, retry cleans
  full/partial residue deterministically; (5) concurrent syncs of the same
  `(project_id, source_file)` rejected FAIL-CLOSED (D3, not serialized). No
  CAS, no generation pointer.
- `full_reindex` deletes ONLY the calling tool's source-types within the bound
  `project_id` (story_sync never touches concept chunks & vice-versa).
- Tests: bounded-window sequence test (both orders of full_reindex), crash/
  retry, concurrent-reject.
- AC: 3, 6.

### V9 — Authority resolver (part of V6; called out separately)
- Resolves ranking for `concept_search` (default `active`, app-layer).
- AC: 7 (concept_search ranking), 5 (ranking rules).

### V10 — MCP surface (after integration gate)
- `backend/vectordb/mcp_server.py` + `tools/` + `contracts.py`: the 5 FK-13
  tools (`story_search`, `story_list_sources`, `story_sync`, `concept_search`,
  `concept_sync`); 3 effective search modes; complete result/error envelopes
  (sync counters, `corpus_revision`, no silent partial failure); strict
  argument validation (AC10 MCP axis); `concept_search` defaults to `active`
  + authority ranking; omitted `project_id`→bound id; divergent `project_id`→
  REJECTED (D2); Weaviate outage fail-closed (§13.8).
- Tests: `tools/list` returns exactly 5; search-mode differentiation; envelope
  completeness; arg-validation negativematrix; project-isolation.
- AC: 7, 8, 10, 11.

## Integration gate BEFORE MCP (no integration deferred to the end)

After V1-V9 are green (packaging, binding, SSOT core, schema, profiles, corpus
lifecycle, CLI, sync, resolver), an explicit integration test proves the full
non-MCP pipeline end-to-end against a FAKE at the Weaviate port:
discover→chunk→validate→build→sync (bounded-window)→search, with project
isolation and the producer/delete closure. ONLY then is V10 (MCP) layered on
top of the already-integrated core.

## Scope boundaries (respected)
- Out of scope: AG3-175 harness registration, AG3-176 installer/preflight/CP10a/
  producers/activation/skill, E2E vs real Weaviate, ARE (AG3-173),
  postgres-race (AG3-172).
- Open follow-up (recorded in report): FK-13 §13.6 P6 context-selection has no
  productive consumer — carried as a named downstream owner, NOT silently
  closed via "MCP provides it".

## Validator commands (project venv only)
- `.venv\Scripts\python -m pip install -e ".[dev]"`
- `.venv\Scripts\python -m pytest`
- `.venv\Scripts\python -m mypy src`
- `.venv\Scripts\python -m ruff check src tests`
- Coverage holds >= 85%.
