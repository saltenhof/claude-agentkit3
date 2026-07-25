# AG3-174 — Story Report (post Codex review r5 remediation)

- **Story:** AG3-174 VektorDB-Retrieval-Engine
- **Branch:** `feat/ag3-174-vectordb-retrieval-engine`
- **Status:** **PENDING RATIFICATION** — implemented and NOT landed. Two concept
  points must be ratified by the PO before this story can be called done:
  Q1 (the authority-scope input of `concept_search`) and Q2 (the `doc_kind`
  vocabulary vs. AK3's own corpus), both below. Landing is additionally gated on
  AG3-172 (orchestrator's job).
- **AC5 (authority ranking): PENDING RATIFICATION — not met.** FK-13 §13.9.11
  rules 3/4/5 are implemented, tested and active. Rules 1 and 2 rank against the
  `authority_over` SCOPE being asked about, and FK-13 defines no ratified source
  for that scope (§13.9.5 has no such parameter). The explicit
  `query_authority_scope` input therefore stays UNPOPULATED in production and the
  two rules are INERT. No scope source was invented; see Q1.

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

### Claim ownership never expires (r5 supersedes the r4 lease rationale)

The r4 remediation defended a bounded 900 s OPERATION lease as compatible with
CLAUDE.md §6.7. Codex r5 adjudicated that PO decision D3 ("concurrent syncs of the
same source fail closed") admits NO time-based exception, and that adjudication is
now implemented: **`SourceClaim` has no expiry field at all.** A claim is released
only by its holder completing, or by an EXPLICIT administrative reclaim
(`concept sync --reclaim`, i.e. an operator asserting the previous writer is dead),
which creates the next epoch and records `reclaimed_from` + the reclaim reason. A
crashed sync therefore parks the source until a human decides, which is the
fail-closed behaviour §6.7 and D3 both ask for; the previous design would have let
a paused writer resume after 900 s. The r4 lease text above is superseded.

## Codex review r5 remediation (11 still-open + 7 new P0 + 2 P2)

r5's pattern was explicit: the r4 fixes were directionally right but the ORDER of
operations or the CLIENT MODEL was wrong. Each item below is a root-cause fix with
a test that was verified RED by temporarily reverting the production change.

**Ordering.** N27/N15: the wall-clock takeover is gone (see above) and the holder
is now fenced BEFORE the first write, BEFORE the vanished-source delete and BEFORE
the completion -- the r4 code fenced only after the upsert and checked the delete
fence after deleting, so a writer resuming past the lease still wrote stale chunks
and could destroy a live generation. N28/N04/N08/N16: reserving a number was not
establishing completion order (A reserved 1, stalled, B published 2, A published
last and won), and the stable per-source record could be overwritten by a replayed
older receipt. The successful CONDITIONAL CREATE is now ITSELF the completion
record: its uuid is `uuid5(project|sequence)` and its properties carry the fully
digest-bound receipt, so position and content are established by ONE immutable
write. Completions are insert-only, a record stored at a position it does not bind
to is rejected, and freshness is selected only from verified immutable completions.
N29/N17: an EMPTY per-source matrix entry slipped through the pre-mutation gate (it
validated over zero objects, derived `source_type=""`, claimed, deleted the
persisted generation and wrote a malformed receipt before `verify()` finally
rejected it). Empty entries are rejected, producer/source-type closure is validated
for the WHOLE matrix, and the sealed receipt is verified BEFORE it is persisted.

**Paths and identity.** N31/R04: `story_dir` and `source_file` are validated
against the AUTHORITATIVE project root BEFORE anything is rendered or written; the
r4 check was purely lexical, so an absolute path from anywhere on disk produced a
`stories/<name>` source_file no consumer could resolve, and the rejection happened
after the file existed. The tests assert a rejected path leaves NO file on disk,
and a supplied `source_file` is a cross-check, never a bypass. N32/N24: the story
directory convention now has exactly ONE parser (`classify.STORY_DIR_RE` /
`story_id_from_story_dir_name`), shared by the ingest adapter and the export path;
the research ingester used `parts[1]` verbatim, so every slugged directory
(`stories/AG3-174-vectordb-retrieval-engine/...`) was mis-identified and its own
CORRECT frontmatter was rejected as contradictory. N26/N06: the split composition
resolves the authoritative binding ONCE and injects that `project_id` into BOTH
export paths; it previously passed `project_key`, so with `project_key: acme` /
`project_prefix: AC` it indexed under `acme` while the MCP server queries `AC`.

**Client model.** N30/N12: the drift check targeted an attribute the installed
client does not have. Introspection of `weaviate-client 4.22.0` shows
`_NamedVectorizerConfig` carries `{vectorizer, model, source_properties}` -- there
is no `vectorize_collection_name`; `vectorizeClassName`/`poolingStrategy` live
inside `model`. The required model is part of the schema SSOT
(`FK13_VECTORIZER_MODEL`) and is compared against the REAL read-back surfaces
(named + legacy), and the tests build their fixtures from the INSTALLED
`_NamedVectorConfig`/`_NamedVectorizerConfig` classes.

**P2.** P2-1: the N14 assertion no longer greps a docstring; it asserts behaviour
for the second real duplicate-exception shape. P2-2: the residual-corpus taxonomy
in Q2 below is corrected to FIRST ERROR PER FILE.

**Adjudications carried over unchanged.** The N20 parser boundary was confirmed
CORRECT, so no further parser relaxation was added. The N23 authority-scope split
was confirmed right; rules 1+2 stay inert pending PO ratification, and no scope
source was invented.

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

**Consequence for the story:** this is exactly why **AC5 is reported as PENDING
RATIFICATION and NOT met** (see the header). The story does not claim AC5 as
satisfied, and it does not invent a scope source to make it appear satisfied.

### Q2 -- the `doc_kind` vocabulary of §13.9.6 vs. AK3's own corpus (N20)

Measured on the real `concept/` directory (347 markdown files):

| state | documents parsed | parse errors |
|---|---|---|
| before this remediation | 0 | 347 |
| after the r4 code fixes | 75 (2075 chunks) | 272 |

The remaining 272 files, counted as **FIRST ERROR PER FILE** (P2-2 correction --
the r4 table mixed levels and mis-attributed the residue; re-measured on
`concept/` with `discover_concept_files`):

| first error in the file | files |
|---|---|
| `doc_kind` outside `core\|appendix` | 253 |
| `defers_to` given as a bare string instead of the qualified `{target, scope, reason}` entry §13.9.6 mandates | 10 |
| mandatory `concept_id` missing (all 5 in `formal-spec/00_meta/`) | 5 |
| no frontmatter block at all | 3 |
| `supersedes` entry shaped as a mapping instead of a string | 1 |
| **total** | **272** |

The `doc_kind` values actually used are `spec` 195, `context` 30,
`decision-record` 18, `detail` 4, `policy` 2, `meta` 2, `decision-log` 1,
`methodology` 1. Two notes on the table: only ONE of the three frontmatter-less
files is a README (`formal-spec/principal-capabilities/README.md`) -- the other two
(`methodology/software-blutgruppen.md`, `testing-standards.md`) are real concept
documents that simply have no frontmatter, so a `.conceptignore` would not cover
them. And because this is first-error-per-file, repairing the leading error may
expose further errors in the SAME file; the table bounds the number of affected
files, not the total number of repairs.

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
  after the r5 remediation: **4 failed, 9851 passed, 40 skipped, 521 errors**;
  total coverage **85.87 %** (gate 85 % reached). The same 4 failures as before,
  i.e. neither r4 nor r5 introduced any.
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
- Revert-check: for the r3, r4 AND r5 findings each production fix was temporarily
  undone and the pinning test confirmed RED (23 + 28 + 17 scenarios, all red). Four
  of the r5 scenarios came back GREEN on the first pass -- those tests were WEAK,
  are named as such here, and were strengthened until they went red:
  `N27` vanished-delete fence (the test only proved claim rejection; it now forces
  an administrative takeover at the claim seam mid-sync), `N29` empty matrix entry
  (the raise came from an outer guard anyway; it now asserts ZERO mutation of a
  seeded vanished source), `N29` verify-before-persist (the receipt was verified
  later regardless; it now asserts a malformed receipt is never stored) and `N26`
  (a source grep passed without the fix; the authority resolution was extracted so
  the test drives real production code).
- Evidence integrity: a revert patch that only REORDERS statements keeps the file
  size identical, and the restore lands in the same clock second, so the `.pyc`
  header still validated and Python loaded the PATCHED bytecode for the restored
  source. That produced one phantom failure
  (`test_n17_no_claim_is_written_before_objects_are_validated`) which is NOT a code
  defect -- with the bytecode caches purged the whole selection is green. The
  harness now purges `__pycache__` around every case, and all r5 reverts were
  re-confirmed RED under that regime.
- Regression guard on the r4 set: the r4 harness re-run gives 18 RED and 8
  "pattern not found", the latter because r5 REWROTE exactly those code regions
  (N12 -> N30, N15 -> N27, N16 -> N28, N17 -> N29, N21 -> N31); the r5 harness
  covers the same behaviour on the new code and is red. Three r4 test names were
  retired with named successors, none silently: `test_n12_existing_collection_that_
  vectorises_the_name_fails_closed` -> `test_n30_drifted_vectorizer_model_fails_
  closed` (same assertion, now against the REAL client surface instead of a
  non-existent attribute), `test_n16_two_concurrent_completions_get_distinct_
  sequences` -> `test_n28_two_concurrent_completions_get_distinct_positions`, and
  `test_n15_expired_claim_of_a_crashed_writer_is_reclaimed_with_a_new_epoch`, which
  pinned behaviour the D3 adjudication now FORBIDS and is replaced by
  `test_n27_a_claim_never_expires_by_time` plus
  `test_n27_explicit_administrative_reclaim_takes_over_and_fences`.
