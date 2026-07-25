# AG3-174 — Story Report (post Codex review r4 remediation)

- **Story:** AG3-174 VektorDB-Retrieval-Engine
- **Branch:** `feat/ag3-174-vectordb-retrieval-engine`
- **Status:** implemented (NOT landed; landing gated on AG3-172, orchestrator's job)

## SSOT-adapter decision (recorded per DoD)

The discovery/parser/chunking/hashing/frontmatter core lives ONCE in
`src/agentkit/concepts/` (transport-free). `backend/vectordb/ingest/`,
`backend/vectordb/mcp_server.py`, `backend/vectordb/cli.py` and
`tools/concept_ingester` are all CONSUMERS/ADAPTERS of that core -- there is no
second parser. After the r1 remediation, `tools/concept_ingester/discovery.py`
was migrated to delegate to `agentkit.concepts.parser.discover_concept_files`
(verified by a drift test: identical doc/content set). The richer
`Ak3ConceptChunk`/glossary shape survives only as an explicit BC/glossary
PROJECTION layered over the SSOT result, not as a parallel discovery path.

## Codex review r1 remediation summary

All 13 P0 + 1 P1 findings closed at the root (see the
R01-R14 -> fix table in the orchestrator return). Highlights: the MCP server now
advertises real per-tool input schemas (R01); a productive Weaviate-backed
engine (`engine.py`) with env-bound composition, idempotent collection creation
and a stdio entry point exists (R02); both endpoints are required + strict (R03);
story export routes through the typed StoryContext projection (R04); story_sync
uses the canonical classifier with incremental delete-closure (R05); the
ingester is a thin SSOT adapter (R06); the CLI sync composes the real engine
(R07); `validate --staged` is fail-closed exit-3 on git faults (R08); the full
validator catalog + real exit-3 are implemented (R09); the resolver ranks against
an explicit query scope (R10); chunks carry a content-bearing shadow identity
for a real bounded window (R11); the sync verifies exact transport counters +
persisted should-set before delete/receipt (R12); contracts strictly validate
allowed keys + every optional type (R13).

## FK-13 §13.6 P6 context-selection -- CONCRETE downstream follow-owner

**Follow-owner: proposed story `AG3-177` (P6-Kontextselektion-Consumer).**

The semantic P6 context selection (FK-13 §13.6: "VektorDB ergaenzt [den
Manifest-Index] um semantische Suche ... relevante Abschnitte nach Aehnlichkeit")
has NO productive consumer in AG3-174..176. AG3-174 delivers the retrieval
capability (story_search / concept_search) but does not wire the P6
context-selection CONSUMER that would feed a filtered context bundle into a
story/exploration prompt (FK-04-021..023). Per the story's "Uebergreifende
Folge-Auflage" this is carried as a NAMED downstream owner, not silently closed
via "MCP provides it".

- **Concrete owner:** a new story `AG3-177` (P6-Kontextselektion-Consumer), to
  be cut by the PO, whose scope is: consume `concept_search`/`story_search` as
  the semantic complement to the deterministic manifest index and emit a
  context-bundle (FK-13 §13.6 step 4) for the create-userstory / exploration
  skills. Until `AG3-177` lands, the P6 obligation is OPEN and tracked here.
- **Why not in AG3-174:** wiring the consumer would expand scope into the
  create/exploration skills (AG3-176 territory + the prompt-runtime), which the
  PO-Neuschnitt deliberately excluded. The retrieval engine is the prerequisite;
  the consumer is a separate, reviewable unit.

## Codex review r3 remediation (18 findings)

The r3 verdict named 13 still-open findings plus 5 new P0. All were closed at the
root; the recurring cause of the r1/r2 churn -- tests that did not pin real
behaviour -- was addressed structurally:

1. **One recording double at the deepest seam.** `tests/unit/vectordb/
   corpus_doubles.py` stands in for the thin Weaviate CLIENT only, so
   `WeaviateCorpusStore`, `SyncService`, `WeaviateRetrievalPort` and
   `McpToolService` all execute productively above it. The double validates its
   own returned hits with the REAL adapter helper, so it can never be more
   permissive than the transport.
2. **Transport-level tests bind against the REAL library signature.**
   `tests/unit/integrations/vectordb/test_weaviate_transport.py` fakes only the
   Weaviate `collections` facade / `connect_*` factory and binds every faked call
   against the installed `weaviate-client` signature. That is exactly what R03
   needed: `connect_to_local` cannot take a distinct `grpc_host`, and the old
   `**kwargs` double hid the resulting `TypeError`.
3. **Every fix was revert-checked.** For all 18 findings the production fix was
   temporarily undone and the pinning test confirmed RED (23 revert scenarios,
   all red).

Production bugs fixed (not symptom patches): `connect_to_custom` (R03), the
`story_search` limit/ranking contract (N09), per-hit ranking identity (N10), no
`setdefault` repair default for hits (N11), collection-drift verification (N12),
per-object target validation before the first write (N13), the `delete_by_id`
bool + full-reindex counters (R12), an ATOMIC store claim (N03), a story corpus
revision distinct from the concept digest and a completion-ordered "latest
receipt" (N04), verified receipts (N08), strict absence semantics for EVERY
optional MCP argument (R13), real caller paths for the story ingest (R04),
rejected absent/coerced story frontmatter (N05), an authoritative project-id
binding for export/repair (N06), a fail-closed concept ingester (R06), a
reachable appendix-detail rule and an asserted module-match boost (R10), and the
advertised input schema plus real calls for all five tools (R01).

Two gaps found while remediating and closed in the same pass:

- **`concept_path` was accepted and ignored** (FK-13 §13.9.5 defines it). It now
  syncs the selected document only, and `concept_path` + `full_reindex` is a
  named rejection (a full reindex would delete the rest of the corpus).
- **Filtered corpus reads used a single capped `limit`**, which would silently
  truncate a large corpus and make the delete closure miss objects. Reads are now
  fully paged with a fail-closed ceiling (AC10 pagination axis).

### Interpretations recorded (no concept deviation)

- **Rule-3 detail.** The interface/test DETAIL is derived deterministically from
  the query TEXT (`derive_query_detail`), since FK-13 §13.9.5 defines no detail
  parameter. Codex accepted this in r4.
- **Canonical story source path.** The indexed `source_file` of an exported story
  is the canonical `stories/<story>/story.md` (FK-13 §13.3.2). Since r4 it is
  VERIFIED against the real directory instead of derived from its name alone
  (N21).
- **Env key.** The CLI export/repair authority is `PROJECT_ID` (FK-13 §13.4.3).
  The previously accepted `AGENTKIT_PROJECT_ID` fallback was removed (it had no
  other reader in the repo) rather than kept as a second truth.
- **Authority scope (superseded by r4).** Binding the resolver's authority scope
  to the `module` filter was rejected by Codex as needing ratification. The code
  now keeps the two separate; see the ratification question Q1 below.

## Codex review r4 remediation (11 still-open + 2 regressions + 12 new)

r4 was the first review that probed the INSTALLED `weaviate-client 4.22.0` and
AK3's REAL corpus, which surfaced defects the fakes had hidden. Two were
regressions from the r3 remediation itself and are called out as such.

**Regressions repaired.** N19/N01/R05: the N11 retrieval profiles had dropped
`module`/`epic`, which `story_search` still advertises -- both are requested and
validated again, and a test asserts EVERY advertised response field of both search
tools arrives through the real retrieval path. N24/R05: research ingestion had
been made to require exported-story frontmatter -- story and research now have
SEPARATE strict metadata profiles (story.md keeps the mandatory export
frontmatter, a research note derives its identity from the canonical path, its
title from an optional frontmatter title or its own heading, and carries
`story_type=research`; a `story_id` contradicting the path is a hard error). This
also RESOLVES the r3 WARNING about a research note failing the whole sync -- Codex
adjudicated it as a defect, and it is fixed rather than deferred.

**Real defects against the installed library / corpus.** N14: `data.insert` routes
a duplicate object id through `UnexpectedStatusCodeError`, not
`ObjectAlreadyExistsException`; the duplicate response is now identified strictly
(documented status code + `already exists` body) with an authoritative
`data.exists` probe as the second signal, and the test raises a REAL exception
instance built from a real 422 response. N18/N02: every property was created with
`Tokenization.FIELD`, so "Vector retrieval engine" was ONE token and the `keyword`
mode could not match "retrieval" -- tokenisation, per-property vectorisation,
searchability and filterability are now part of the schema SSOT. N12: existing
collections are verified against the FULL read-back configuration. N25: paging
probes one further object instead of rejecting the exact ceiling, and detects a
repeated page.

**Fail-closed / ordering.** N17/N13: the COMPLETE incoming matrix is validated
before ANY mutation (the claim record is a mutation too). N15/N03: claims carry
owner + epoch + a bounded operation lease, a stale claim is reconciled by CREATING
the next epoch, the holder is FENCED before the delete and before the receipt, and
every vanished-source delete acquires the same claim. N16/N04/N08: the completion
order is reserved with a conditional-create token per number, the digest binds
every identity AND ordering field, the timestamp must be a UTC instant, and an
unknown receipt state is rejected rather than skipped. N22/N06: absence and
invalidity of the project configuration are strictly separated. N21/R04: the
canonical story path is verified, not fabricated.

### Bounded claim lease vs. CLAUDE.md §6.7

§6.7's "ownership never expires automatically" governs STORY/SESSION ownership.
The N15 lease is an OPERATION lease for ONE source sync (900 s) and exists because
a crashed sync must not wedge a corpus source forever. It is documented as such in
`sync.SourceClaim`, and the takeover is fenced, so a resurrected holder can
neither delete nor publish. No story/session ownership is affected.

## Ratification needed -- NOT decided in this story

### Q1 -- an authority-scope input for `concept_search` (N23)

FK-13 §13.9.11 rules 1 and 2 rank against the `authority_over` SCOPE being asked
about, but §13.9.5 defines NO scope parameter for `concept_search`. The code no
longer conflates it with `module` (the r4 finding); the explicit
`query_authority_scope` input therefore stays UNPOPULATED in production, so rules
1/2 are inert while rules 3/4/5 work.

**Question:** should `concept_search` gain a ratified authority-scope parameter
(e.g. `authority_scope: String, optional` in the §13.9.5 table), or should the
scope come from another ratified source (e.g. a module -> scope mapping)? Until
that is ratified, rules 1 and 2 cannot fire in production; everything else about
them is implemented and tested (including the tiered precedence).

### Q2 -- the `doc_kind` vocabulary of §13.9.6 vs. AK3's own corpus (N20)

Measured on the real `concept/` directory (347 markdown files):

| state | documents parsed | parse errors |
|---|---|---|
| before this remediation | 0 | 347 |
| after the r4 code fixes | 75 (2075 chunks) | 272 |

The remaining 272: **253x `doc_kind` outside `core|appendix`** (the repo uses
`spec` 195, `context` 30, `decision-record` 18, `detail` 4, `policy` 2, `meta` 2,
`decision-log` 1, `methodology` 1), 10x `defers_to` as a bare string list instead
of the qualified `{target, scope, reason}` entries §13.9.6 mandates, 6x missing
mandatory fields, 3x no frontmatter at all (README files that belong on a
`.conceptignore`).

**Question:** is §13.9.6's `doc_kind` vocabulary to be EXTENDED (making AK3's own
corpus a valid FK-13 corpus), or is AK3's development corpus a SEPARATE corpus
class with its own profile (so the FK-13 tooling only ever reads a target
project's `concepts_dir`)? Both are concept changes; this story implemented
neither. Nothing silently points at the wrong corpus in the meantime: the CLI
argument is required and the MCP entry point demands `AGENTKIT_CONCEPTS_DIR`.

## Validators (project venv only)

- `.venv\Scripts\python -m pip install -e ".[dev]"` -- OK
- `.venv\Scripts\python -m ruff check src tests tools/concept_ingester` -- clean
- `.venv\Scripts\python -m mypy src` -- clean (998 files)
- `.venv\Scripts\python -m pytest` (project addopts `-n 4 --dist loadfile`) --
  after the r4 remediation: **4 failed, 9824 passed, 40 skipped, 521 errors**;
  total coverage **86.47 %** (gate 85 % reached). The same 4 failures as before,
  i.e. r4 introduced none.
  - The 4 failures are all `tests/unit/concept_toolchain` baseline-digest /
    byte-count drift against the committed blob -- PRE-EXISTING (reproduced at
    `96a21dbb` with this story's files reverted) and named out of scope.
  - The 521 errors are the Docker/Postgres-backed suites; Docker Desktop is not
    available in this environment (`_ping` 500), so every `*_pg` / postgres
    fixture errors at setup. Unrelated to this story.
  - Before this remediation the same suite had **29** non-infra failures; 26 of
    them were caused by this story's own earlier `concept_ingester` SSOT
    migration (lost qualified authority metadata) and are now fixed.
- Scoped run of the AG3-174 modules + their callers (vectordb, concepts,
  story_creation, cli, story_split, tools, concept_authority_prose): **877
  passed**.
- Revert-check: for all 18 r3 findings AND all r4 findings the production fix was
  temporarily undone and the pinning test confirmed RED (23 + 28 scenarios, all
  red).
