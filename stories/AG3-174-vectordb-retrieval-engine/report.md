# AG3-174 — Story Report (post Codex review r9 remediation; concurrency residual carved out)

- **Story:** AG3-174 VektorDB-Retrieval-Engine
- **Branch:** `feat/ag3-174-vectordb-retrieval-engine`
- **Status:** implemented, NOT landed (landing gated on AG3-172, orchestrator's
  job). **11 ACs pass; AC6 is PARTIALLY met** with one named, unratified residual that
  the PO cap carved out into a follow-up story (proposal at the end of this report). Q2
  remains open, and D9's mechanism still awaits the PO's re-confirmation.
- **A note on how AC status is reported here.** In r7 this report claimed all 12 ACs.
  Codex found 9, and it was right: AC3's proof ran through a FIXTURE-shaped identity
  (the test built its uuid the same wrong way the code did), and AC10 had a fresh
  coercion regression. From here an AC is only called met when its proof runs through
  the REAL production path -- the projection, the port, the store and the transport as
  production wires them -- and not when a fixture agrees with the code.
- **AC3 (story/research indexing): MET, now on the real path.** Story export, split
  and repair no longer index through a second write path (`story_sync` is removed from
  the adapter, N38), and the TYPED identity survives the port (N42): `chunk_id` is
  carried through instead of being re-derived from `content_hash`, which had made
  production reject every normally projected story. The proof runs
  `export_story_md` -> `WeaviateStoryIndex` -> `WeaviateCorpusStore` -> `SyncService`
  with the double only at the Weaviate client seam, and the objects come from
  `story_file_to_objects` over a written `story.md`.
- **AC10 (strict validation): MET again.** The conditional-delete counters were a
  REGRESSION of R12 -- `getattr(..., 0)`, `or 0`, `int(...)` -- introduced in code
  written to fix something else. They are now exact: both counters must exist as
  non-boolean integers, negatives and impossible totals are faults, and a reported
  failure is fail-closed (N44). A new transport call inherits the AC10 obligation.
- **AC6 (bounded window / concurrency): PARTIALLY MET.** What holds, and is
  revert-verified: a superseded holder can never DELETE a newer generation's data (in
  either race order, storage-side, bound to its own generation), it can never pull
  reported freshness back (completions are insert-only, position-bound and
  generation-ordered), every required destructive step now precedes the receipt (N46),
  legacy rows converge instead of blocking every retry (N43), and every corpus delete
  carries project/source isolation (N48). **What does NOT hold:** a stale write landing
  AFTER the required final delete stays visible until the next sync of that source, and
  that moment is not time-bounded -- one finite pass cannot cover a later arrival. The
  residual is named precisely below and is owned by a follow-up story; it is **not**
  presented as an accepted contract, because the PO has not ratified one. The earlier
  claim in this report that AC6 was met is **withdrawn**.
- **Question ledger.** Every question this story raised is now either ratified and
  implemented, or explicitly out of the story's hands:

  | # | Subject | State |
  |---|---|---|
  | Q1 (N23) | authority scope for `concept_search` | **RATIFIED as D7**, implemented |
  | Q4 (N36) | rule 4 vs. the single-status filter | **RATIFIED as D8**, implemented |
  | Q3 (N33) | residual check-then-mutate window on the destructive step | **RATIFIED as D9**, implemented |
  | Q2 (N20) | `doc_kind` vocabulary vs. AK3's own corpus | **STILL PENDING** with the PO |

  Q2 does not block this story: neither the CLI nor the MCP entry point guesses the
  corpus directory any more, and D7 recorded it as non-blocking. It does keep the
  two LLM-backed nightly concept gates from producing a signal (see Q2 below).

  D9 stays RATIFIED as to its invariant; what needs a PO re-confirmation is the
  REPLACEMENT MECHANISM (persistent monotonic source generation), because the
  mechanism first implemented under D9 was wrong. The decision record says so
  explicitly.
- **AC5 (authority ranking): MET, and now proven filter-faithfully.** All five
  FK-13 §13.9.11 rules are active. Rules 1/2 became productive with **D7**; rule 4
  became *observable* with **D8**, which ratified `concept_status` as a status SET
  so a result set can legitimately be mixed. The earlier r6 statement "AC5 blocked
  on the N36 ratification" is superseded by D8, and the earlier D7-era statement
  "AC5 met" was correctly rejected at the time: back then rule 4 could not fire and
  the test that appeared to prove it only worked because the recording double
  ignored the transport filters. **The double now applies every filter exactly like
  Weaviate**, and the rule-4 proof runs on a genuinely mixed result set.

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
- **Authority scope (superseded by r4, then ratified as D7).** Binding the
  resolver's authority scope to the `module` filter was rejected by Codex as
  needing ratification. The code keeps the two separate, and the PO subsequently
  ratified an explicit `authority_scope` parameter (D7) as the scope source; see
  "D7 implementation" below.

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
was confirmed right, and no scope source was invented — the ratification that
followed (D7) supplied one explicitly.

## Codex review r6 remediation (3 code fixes; 2 items parked with the PO)

r6 reduced 18 open items to four root causes plus one P2, and passed D7. The three
items that needed no decision are fixed here; N33 and N36 are with the PO and were
deliberately NOT touched (see Q3/Q4).

**N34 (= N17/N29) -- the pre-mutation gate now covers the RECEIPT'S INPUTS.**
`sync_source` validated the objects but not `corpus_revision`, so a run with valid
objects and `corpus_revision=""` claimed the source, wrote the new generation and
deleted the old one, and only failed when the sealed receipt was verified at
publication time — a mutated corpus with no publishable completion. Every
caller-supplied mandatory completion field (`project_id`, `source_file`,
`source_type`, `corpus_revision`) is now validated BEFORE the claim, in all three
sync paths: `sync_source` directly, and `reconcile_sources` / `full_reindex` inside
`_validate_matrix`, which runs before the vanished-source delete. The mandatory
field list is one constant shared by the gate and `SyncReceipt.verify`, and both now
reject whitespace-only values (a strengthening, not a relaxation).

**N35 (= N12/N30) -- named-vector `source_properties` are part of the contract.**
`configured_vectorizer_model` compared only `model`, so a collection that embeds
only `title` instead of the SSOT-selected narrative properties passed composition
as long as pooling and `vectorizeClassName` matched — semantic search would then
answer from titles alone. The pinned client's `_NamedVectorizerConfig` has exactly
three behaviour-defining fields (`vectorizer`, `model`, `source_properties`, verified
by introspection and pinned by a class-shape test); ALL THREE are now compared.
`FK13_VECTOR_SOURCE_PROPERTIES` is derived from the schema SSOT (the properties
declared `vectorized`), declared explicitly at creation and compared on read-back.
Two asymmetries of the installed client are worth recording: the CREATE model
carries the selection as `_VectorConfigCreate.properties` (the inner
`_Text2VecTransformersConfig` has no such field), while the READ model exposes it as
`_NamedVectorizerConfig.source_properties`; and a read-back `None` means
"server-derived from the per-property `skip_vectorization` flags", which are
verified property by property in the same call — so `None` is deliberately NOT
treated as drift, and that decision is pinned by its own test.

**P2-3 -- stale lease wording removed** from `corpus_doubles.corpus_store` and the
`test_sync` section header; both now describe timestamp-only, no-expiry semantics.

## D7 implementation -- `authority_scope` (closes Q1)

PO decision **D7** (`po-decisions.md`, commit `8fd75656`) ratified an optional
`authority_scope` parameter for `concept_search` and thereby authorised the ONE
bounded concept change this story may make. It rejected both alternatives: a
`module` -> scope mapping ("where a document lives" and "what it governs" are
different things) and landing with three of five rules (a silent quality gap in
the capability's core value, i.e. a ZERO-DEBT violation).

**Concept diff (minimal, two sections + the record).**

- FK-13 §13.9.5: one new row in the normative `concept_search` table
  (`authority_scope`, String, optional) plus a paragraph stating that it is a
  RANKING input and not a filter, that `module` and `authority_scope` are separate
  inputs, that it is never derived from `module`, and that an absent value leaves
  rules 1/2 inert while 3/4/5 stay unchanged.
- FK-13 §13.9.11: a paragraph naming the reference quantity of rules 1 and 2 (the
  `authority_scope` of §13.9.5), that rule 2 credits the deferral TARGET, and that
  the normative precedence of rules 1/2/4 is not outrankable by similarity while
  rules 3/5 act within one precedence level only.
- `concept/_meta/decisions/2026-07-25-concept-search-authority-scope.md`: the P3
  decision record (decision, four rejected alternatives, impact sweep,
  Betroffenheitsmatrix). §13.9.6's `doc_kind` vocabulary is explicitly listed as
  NOT affected — Q2 stays untouched.

**Code.** `authority_scope` is a strictly validated optional in the contract SSOT
(`contracts.TOOL_CONTRACTS`), so the advertised `inputSchema` and the strict
validators move together. `validate_authority_scope` is deliberately NOT part of
`validate_concept_filters`: absence yields `""` (a valid state), while explicit
`null`, an empty/whitespace string and any non-string are named errors like every
other optional. `concept_search` passes it as `query_authority_scope` into
`rank_hits` and never into the transport filters. The `McpToolService`
`query_authority_scope` FIELD was removed — with a ratified per-call input, a
service-level default would have been a second source of truth. The stale
`module` parameter description ("also the queried authority scope") was corrected.

**Gates run** (blocking CI set, all green):
`check_concept_frontmatter` (90 docs), `compile_formal_specs`,
`check_concept_reference_integrity` (0 errors / 55 reports),
`check_concept_decision_record`, `check_concept_code_contracts`,
`check_architecture_conformance`. The two LLM-backed nightly gates (W2 authority
prose, W3 scope consistency) cannot execute in this repo at all: both ingest the
corpus first and abort on the Q2 `doc_kind` gap. That is PRE-EXISTING and
unchanged in nature — the identical abort happens on a clean tree (272 files) and
with this change (273); the one extra file is the new decision record, which fails
for exactly the same reason as all 20 pre-existing decision records
(`doc_kind 'decision-record' is not in appendix|core`). Both stages are
non-blocking by CI design, and repairing that is Q2, not this story.

**Note on the corpus count after D8:** the D8 decision record adds a SECOND
deliberately non-conforming record, so the pre-existing Q2 error class now covers
**274** files instead of 273. Same class, no new class.

## D8 implementation -- mixed status result sets (closes N36, completes AC5)

PO decision **D8** (`po-decisions.md`, commit `558e1242`) resolved the FK-13
self-contradiction Codex found as N36 and authorised the second (and last) bounded
concept change of this story. It chose "allow mixed status sets" over "retire rule 4"
because drafts matter for concept incubation (DK-16/FK-78), and it kept the default
unchanged at `["active"]`.

**Concept diff.** FK-13 §13.9.5 (parameter table + default-filter paragraph),
§13.9.10 (archive handling) and §13.9.11 (rule 4's scope of effect) now describe the
status filter as a SET with default `["active"]`, evaluated as a real transport
condition, with rule 4 ordering within a mixed set and remaining a precedence tier.
`concept/_meta/decisions/2026-07-25-concept-search-mixed-status-result-sets.md`
carries the P3 record (decision, four rejected alternatives, impact sweep,
Betroffenheitsmatrix). §13.9.6 and the `doc_kind` vocabulary stay untouched.

**Code.** `concept_status` is an `array` in the contract SSOT, advertised with the
item enum plus `minItems: 1` and `uniqueItems: true` — the schema now states exactly
what the validator enforces. `validate_concept_status` returns a tuple and rejects,
by name and without coercion: a bare string, explicit null, a non-list container, an
empty list, an unknown value, a duplicate and a non-string element. The adapter turns
a set-valued filter into a real server-side `any_of` of equalities (a single value
keeps the exact equality the default query has always issued) and fails closed on an
empty set; there is no client-side post-filtering, which would have broken `limit`
and the server's own ranking.

**Tests.** The recording double now applies EVERY filter the way the adapter builds
it (set = membership, scalar = equality) — that is the root-cause fix for the sham
proof, and it immediately exposed one further over-permissive assertion elsewhere (a
foreign-module hit that a real `module` filter excludes), which was corrected rather
than worked around. On top: a mixed query proves the transport really returns both
statuses AND that rule 4 puts the active document first despite a 90x worse score; a
draft that OWNS the queried authority scope still loses to an active document (rule 4
beats rule 1, whole-tier); the default returns active only and an `["archived"]`
query returns nothing; and a 7-case strictness matrix covers every rejected shape.

## D9 implementation -- the destructive step is storage-conditional (closes Q3)

PO decision **D9** (`po-decisions.md`, commit `6f190620`) resolved N33. It secured
only the DESTRUCTIVE step storage-side and had the two harmless windows documented
honestly; it rejected accepting the whole window (a real data-loss risk on the
delete) and full fencing of all three steps (needs process supervision this layer
does not own).

**Binding invariant.** A superseded holder must NEVER delete data the newer owner
has written — enforced storage-side, not by a preceding check.

**The proposal did not hold as stated; the mechanism is a corrected form of it.**
The proposal was: stamp the writing ownership epoch on the chunk objects and bind
the delete to "the object's epoch is OLDER than mine". Checking it first (as
instructed) showed the ordering predicate is unsound here: **claim epochs are not
monotonic across runs.** `release_source` discards the claim record, so the next
`try_claim_source` starts at epoch 1 again; only a takeover chain increments
(`reclaim_source` = `active.epoch + 1`). Consequences:

- Normal case: the old chunks were written by a previous COMPLETED sync that also
  held epoch 1, while my fresh claim is epoch 1 -> `1 < 1` is false -> the
  legitimate delete removes NOTHING and vanished sources are never cleaned up
  (silent breach of the delete closure, R05).
- The chain case the coordinator asked about, in reverse: a previous run ended at
  epoch 3 and released; my fresh claim is epoch 1 and must delete objects stamped 3
  -> `3 < 1` is false -> again nothing is deleted.

So the ordering is replaced by **equality against the OBSERVED token**
(compare-and-delete). It needs no monotonicity assumption and still excludes the
new owner's data, because a superseding owner necessarily writes under a DIFFERENT
token: while a delete is pending the claim is unreleased, so the only way to take
it over is `reclaim_source`, which yields a strictly greater epoch.

**And yes, the epoch needs to be paired with the owner.** Epoch values repeat
across runs, so the epoch alone identifies a generation only via the argument "a
repeated epoch cannot coexist with a live holder". The token is therefore
`<epoch>|<owner_id>` (`claim_ownership_token`), which makes the guarantee
structural instead of argued.

**Data model.** `StoryContext` gains `owning_claim` (FK-13 §13.3.1): TEXT,
whole-value tokenised, filterable, **never** vectorised and not part of any tool's
return contract. It is carried through creation AND read-back verification by the
existing N12/N35 machinery (`weaviate_property_specs()` -> `ensure_collection` ->
`_verify_existing_collection`), and a contract test pins all of those properties.
It is explicitly NOT a second ownership truth: the claim record stays authoritative;
this is the marker ON THE DATA that a storage-side condition can reference.

**Code.** `upsert_objects(objects=..., owning_claim=...)` stamps every write in the
store and refuses an unstamped one, so an unstamped object version cannot exist.
`delete_objects_owned_by` groups the candidates by the token they were READ with and
issues one `delete_many(where=by_id ∈ batch AND owning_claim == observed)` per group
via the new adapter method — the one storage-side precondition the pinned client
offers for a destructive operation (verified: `update`/`replace`/`delete_by_id` take
no precondition at all). A short confirmed count is fail-closed
(`ClaimSupersededError`). **Both** destructive deletes now run this way: the
vanished-source delete and the old-generation delete inside the per-source window —
the invariant is about deletion, not about which function performs it, and leaving
the second one unguarded would have kept the identical data-loss risk one function
away. The preceding `assert_claim_held` calls in front of both deletes are **gone**,
deliberately and with no application-side replacement.

**Edge cases checked.** (a) every legitimately deletable chunk is still caught,
including chunks written by SEVERAL different previous generations in one delete;
(b) an object with no readable ownership token is never deleted — fail-closed, and
sound because the capability has no installed base (recorded under D8), while every
object AK3 writes is stamped; (c) the takeover chain (epoch 3 deleting what epoch 1
wrote, and vice versa) works because nothing depends on ordering; (d) the ownership
token pairs epoch and owner, see above.

**Remaining windows, named as known and harmless (D9 point 4).** FK-13 §13.9.9 now
states them normatively: the **chunk write** is idempotent (deterministic uuid5,
identical content, so a late writer rewrites the same object), and the
**completion** is insert-only and position-bound (N28: a superseded holder can only
append a new position, never overwrite one, and reported freshness is built only
from verified completions). No transactional atomicity is claimed anywhere — what is
guaranteed is the non-deletability of a newer owner's data, not the indivisibility
of the window. The bounded-window line of DR 2026-07-21 Rand 5 is continued, not
overridden.

## Codex review r7 remediation (N37, N38, N39, N40 + P2-4/P2-5)

r7 passed 10 of 12 ACs and confirmed AC5 as met and filter-faithful. The two
remaining blockers, AC3 and AC6, had ONE root cause, and it is now removed.

### The root cause: there was no persistent generation identity per source

Two mechanisms failed before this one, both for the same underlying reason:

1. The PO's proposal (**"the object's epoch is older than mine"**) could not work
   because the claim epoch was EPHEMERAL: `release_source` deleted the claim record,
   so the next normal acquisition restarted at 1. Codex confirmed that finding.
2. My replacement (**equality against the OBSERVED token**) was not sound either, and
   the reason is the sharper version of the same point: equality against a value you
   READ closes only the interval between reading and deleting. It never establishes
   WHOSE generation that value is. Counter-scenario (the one my tests did not cover):
   A passes its fence, B reclaims and completes, A resumes, reads B's chunks carrying
   B's token, groups them under exactly that token and deletes B's data. My tests
   covered only the opposite order.

So the fix is at the root: **the source generation is now persistent and strictly
monotonic.**

### The mechanism, and why it holds where the other two did not

- **Ladder.** Every acquisition of a source claim -- normal AND administrative
  reclaim -- allocates the NEXT generation by conditional create. A normal release no
  longer deletes the ladder position: it adds an insert-only `released` marker, and
  housekeeping only prunes strictly BELOW the highest generation, so the ladder can
  never reset. A source is HELD when its highest generation has a `claimed` record
  and no `released` marker -- D3's "a held claim rejects, no matter how old" is
  unchanged. Everything stays in ONE record type: the claim record remains the
  authority on WHO holds a source; the generation only ORDERS.
- **Delete.** Every write stamps `owning_generation` (a numeric `StoryContext`
  property), and both destructive deletes are bound storage-side to
  `owning_generation < my own generation`. The bound is a number the deleter OWNS, so
  there is nothing to mislead it about.
- **Completion.** The receipt carries the publishing generation, the digest binds it,
  and per-source freshness is selected by the highest GENERATION (pruning follows the
  same order). Insert-only prevented an overwrite but not a stale APPEND -- which is
  exactly how a superseded writer could take a later position, become
  freshness-authoritative and prune the newer owner's valid completion.

**Why both race orders hold.** The condition never references anything the newer
generation controls:

| order | what happens | why it is safe |
|---|---|---|
| newer generation writes AFTER this writer read | its objects carry a HIGHER generation | `< mine` cannot match them |
| newer generation writes and COMPLETES BEFORE this writer reads (the r7 counter-scenario) | this writer reads objects of the higher generation | `< mine` still cannot match them; the short count fails the run closed |
| a LATER normal run wrote (no takeover at all) | ladder persisted, so that run is higher | `< mine` cannot match |
| legitimately deletable old chunks, from SEVERAL earlier generations | all strictly below | one condition removes them all |
| a previous run ended on a takeover chain (e.g. generation 3) and released | the next claim is 4, not 1 | ordering still decides -- this is what killed proposal 1 |

Both orders are tested, in both destructive paths.

### N38 -- one write path into `StoryContext` (AC3)

`WeaviateStoryAdapter.story_sync()` upserted objects directly, so an automatically
exported story landed unstamped, took no claim and published no completion; a later
MCP sync or vanished-delete then read no generation and had to refuse it. The
adapter's write method is **removed** (not guarded -- removed), and
`WeaviateStoryIndex` now routes export/split/repair through the claim-aware
`SyncService`: one claim per source, the generation stamp, the verified generation and
a published completion. The collection bootstrap is shared with the MCP runtime
(`ensure_corpus_collections`), so no path can create a collection without the ordering
property. Tested as the full chain export -> resync -> vanished delete, plus a
concurrent export being rejected under D3.

### N40 -- the empty matrix no longer skips the gate

`_validate_matrix` validated the completion inputs INSIDE its loop over the incoming
sources, so an EMPTY matrix reached `_delete_vanished_sources` with a blank
`corpus_revision` unchecked. The run-wide fields are now validated at function ENTRY,
outside the loop, and the tests cover reconcile and full-reindex with an empty matrix,
a blank revision (and a blank project id) and a seeded vanished source.

### P2

P2-4: the claim-release wording is corrected -- every normal sync releases in a
`finally`, and only a CRASHED writer's claim needs an administrative reclaim.
P2-5: `COMPLETION_INPUT_FIELDS` is now DERIVED from `RECEIPT_MANDATORY_FIELDS` minus
the store-sealed fields, so a future mandatory receipt field joins the pre-mutation
gate automatically.

### The D9 decision record is corrected, not quietly patched

The record now carries a dated addendum naming the superseded mechanism, why it fell
(both the delete and the completion side), and what replaced it. The two statements
Codex flagged as substantively wrong -- "newer data cannot be deleted" (of the token
model) and "a stale completion append is harmless" -- are marked FALSE and corrected.
D9's ratified content (the invariant, and securing only the destructive step) is
unchanged; only the delegated mechanism changed. **The replacement model should be
re-confirmed by the PO**, as Codex asked -- that confirmation is not something this
story can grant itself.

## Codex review r8 remediation (N42, N44, N45 + P2-6)

### N44 -- an R12 regression I introduced, in code written to fix something else

The conditional-delete transport read its counters with `getattr(..., 0)`, `or 0` and
`int(...)`. So `successful="1"` with `failed` ABSENT counted as one fully confirmed
delete -- exactly the coercive-default pattern this story spent rounds removing. Now
both counters must be present as exact non-boolean integers, negatives are faults,
a reported failure is fail-closed, and a count that exceeds the request is rejected as
impossible rather than accepted as a bonus. Tested for missing / string / float /
bool / None / negative / over-count, and the strictness is exercised on the REAL
transport call, not only on the helper.

The lesson recorded for the next round: **a new transport call inherits the AC10
strictness obligation.** Starting permissive and tightening later is how a closed
finding comes back.

### N42 -- the typed identity had to survive the port (AC3)

`story_file_to_objects` derives each uuid from `chunk_id = story-<ordinal>-<prefix>`.
The r7 rewrite flattened the projection into property dicts, so the indexer had to
re-derive that identity input and substituted `content_hash` -- which makes
production's identity validation reject EVERY normally projected story. My r7 test
fabricated its uuid from `content_hash` too, so it agreed with the bug: a
fixture-shaped proof, the same failure mode as the earlier sham proofs.

The port now carries the TYPED `StoryContextObject` sequence, so `chunk_id` travels
with the object and nothing is reconstructed. `export_story_md`'s indexing handler
also catches `SyncError` now -- the index routes through the sync owner, so a rejected
claim or an unpublishable generation must block the export like a transport fault
instead of escaping unhandled. The tests build their objects from a written
`story.md` through the real projection, assert that `chunk_id != content_hash` (so the
old substitution cannot silently satisfy them), and drive the export end to end.

### N45 -- a failed claim release is no longer silent

`release_source` suppressed availability AND write errors, so a sync could publish its
completion, fail to persist the release marker, report success -- and leave the source
HELD until an administrative reclaim nobody could explain. The release is now
CONFIRMED: a failure raises `ClaimReleaseFailedError`, an already-existing marker is
success (releasing twice is idempotent), and a store that neither creates nor holds
the marker is a fault. When the sync ITSELF also failed, its exception stays primary
and the release failure is attached as a note -- a plain `finally` used to substitute
the symptom for the diagnosis. Tested after a successful sync, after a failed one, on
the vanished-delete path, for idempotency and for a denied marker.

### P2-6 -- the race-coverage claim is now precise

An end-to-end order-2 test was added for the `sync_source` entry path: A claims,
writes, the takeover happens BEFORE A re-reads, so A genuinely reads B's newer rows,
judges them stale and attempts to delete them -- and the storage condition refuses. For
the `reconcile_sources` path the "read after the newer write" order is structurally
impossible: that read happens BEFORE the claim is acquired, and a newer generation can
only exist via a reclaim OF that claim, so the two orders coincide there. The report
says exactly that instead of claiming symmetric end-to-end coverage.

## N41 -- analysis for the PO (NOT implemented)

**First, the factual question: is the exposure bounded or indefinite? It is BOUNDED,
and the rows are already deterministically removable.**

Traced through the code: A's stale rows carry A's `source_file`/`project_id`, so the
next sync of that source reads them into `persisted`
(`list_objects_for_source` filters exactly on those two). They are not in that sync's
`should` set (changed content -> different chunk ids -> different uuids), so they land
in `stale_rows`; and because the ladder is monotonic, every later claim's generation is
strictly greater than A's, so the conditional delete MATCHES them. The vanished-source
path does the same via `list_objects_for_source_types`. So:

- the rows disappear at the **next successful sync of that source** (normal re-sync,
  full reindex, or the vanished-source delete);
- they are never "stuck" the way the N43 unstamped rows are -- nothing about them is
  unorderable;
- **freshness is not corrupted**: A publishes no completion (the receipt fence rejects
  it, and even an appended one loses on generation, N39).

**What is genuinely wrong in the meantime** is not removability, it is *misreporting*:
between A's stale write and the next sync, retrieval returns B's chunks AND A's, so a
search can surface two contradictory versions of the same section, and
`story_list_sources` counts the extra chunks -- while `corpus_revision` reports B's
revision, i.e. a corpus state the stored rows do not match. And FK-13 §13.9.9 plus the
D9 record still justify this window with "the write is idempotent -- same uuid, same
content", which is FALSE for changed content. Correcting that text is part of whichever
shape is chosen, and I have deliberately not corrected it yet, because the honest
sentence depends on the decision.

**The three shapes, assessed against this seam:**

1. **Make stale-generation writes storage-conditionally impossible.** Not available at
   this seam. Verified against the pinned client: `data.insert` is conditional on the
   object ID only, batch `upsert` has no precondition, and `update`/`replace` have
   none. It could be *emulated* by writing each chunk at a generation-scoped uuid
   (`uuid5(project|source|chunk|generation)`), which makes every write an immutable
   conditional create -- but that replaces the deterministic per-chunk identity that
   the idempotent re-sync, the delete closure and the N42 identity validation are all
   built on, and it multiplies rows per generation (retrieval would then need
   deduplication). That is a different data model, i.e. its own story.
2. **Make stale rows invisible to retrieval.** Mechanically easy (the property is
   filterable), but the discriminator matters, and this is where I would push back on
   the obvious choice: **a generation filter is NOT coherent with the freshness model,
   a `corpus_revision` filter is.** Retrieval spans many sources at once and has no
   per-source generation bound to compare against, so a generation filter would need
   one clause per source in scope plus a ladder read per query -- and it would put an
   internal concurrency ordinal into the query surface, which FK-13 deliberately keeps
   out (`owning_generation` is documented as no tool's return field). Filtering on the
   revision the row was written for, against the revision the authoritative completion
   reports, makes visibility DERIVE from freshness instead of competing with it: A's
   rows carry a revision that never became authoritative, so they are invisible by
   construction, with no mutation and no second ordering. The cost is real: retrieval
   gains a per-query dependency on the completion set, the filter grows with the number
   of sources in scope, and the rows still exist (so `story_list_sources` counts and
   any unfiltered reader still see them).
3. **Keep them deterministically removable after the newer completion.** Per the
   analysis above this is **already true**; what is missing is promptness and honesty.
   The minimal concrete form: after publishing its completion, the completing owner
   performs ONE more conditional sweep of its own source (delete rows of that source
   with `owning_generation < mine` that are not in its should-set). That is the
   existing conditional delete, run once more after the completion, so a stale write
   that landed inside an overlapping window is cleaned immediately instead of at the
   next sync. It cannot catch a write that lands after that sweep -- that one waits for
   the next sync, as today. Cost: one extra read plus one conditional delete per source
   per sync. No new state, no identity change, no retrieval coupling, no query-surface
   change.

**My recommendation, stated as input and not as a decision:** shape 3 plus the
corrected FK-13/D9 text. It is the only one of the three that needs no new state, no
identity change and no coupling of retrieval to the completion set, and it converts the
open question from "can this be cleaned up" (it can) into "how quickly". Shape 2 is
worth it only if the PO wants ZERO visible exposure, and then with `corpus_revision`
as the discriminator, not the generation. Shape 1 should be a separate story if it is
wanted at all.

## N41/N43 remediation (shape 3 + convergent backfill)

### N41 -- shape 3: one post-completion sweep

**What the defect actually was.** The pre-write fence and the upsert are separate
operations, so a superseded writer can append objects of its OWN, lower generation
after this generation's delete has already run. With CHANGED content those objects
carry DIFFERENT uuids, so nothing else in the window touches them -- which is exactly
why the old "the write is idempotent, same uuid, same content" premise hid the defect.

**What was built.** After publishing its completion, the completing owner runs ONE more
pass over its own source: read the source's rows, take those that are not part of this
generation, and delete the ones whose `owning_generation` is strictly BELOW this
claim's -- through the same storage-conditional predicate as the in-window delete, under
the still-held claim, with no application-side check. Rows at a generation >= this
claim's are deliberately NOT candidates: a higher generation means a newer owner took
over after this completion, and its data is not this writer's to remove (its own
completion supersedes this one).

**Why this closes N41 without touching identity or retrieval.** It adds no state, no
property and no contract surface: the predicate, the property and the transport call
are the ones N37 already established, executed once more at a later point. The object
identity model is untouched (still `uuid5(project|source|chunk)`), so idempotent
re-sync, the delete closure and the N42 identity validation are unaffected. Retrieval
is untouched: no query-side filter, no per-source bound, and no internal concurrency
ordinal on the tool surface. What changes is only WHEN the window closes -- at the
completion instead of at the next sync of that source.

**Residual, stated honestly.** A stale write that lands AFTER the sweep still waits for
the next sync of that source, which removes it for the reasons already analysed (its
generation is strictly lower than every later claim's). No transactional atomicity is
claimed anywhere.

**Tests.** The race is driven with DIFFERING content, so the stale rows are genuinely
distinct rows: (a) a superseded writer appends after the takeover and the next owner's
completion sweeps it; (b) the tightest window -- the stale row is injected at the
instant the completion record is created, i.e. after the in-window delete, so only a
post-completion pass can remove it; (c) the sweep cannot delete a newer generation's
rows (driven at the predicate, because a taken-over holder never reaches its own
completion -- the fence rejects it -- so the bound, not the fence, must be what
protects them); (d) every conditional delete in a run, sweep included, uses the
HOLDER'S OWN generation as its bound.

### N43 -- a convergent, claim-owned backfill

**Why it is our debt.** The rows are orphaned because THIS story's schema change
introduced the ordering property; declaring "no installed base" would be exactly the
assumption that bites later.

**What was built.** Before writing, the holder of a source converges that source's
unstamped rows:

- rows that are part of THIS generation need nothing -- the upsert overwrites them and
  thereby stamps them;
- the remaining unstamped rows are deleted under an **IS-NULL** storage condition,
  which structurally cannot match any stamped row -- not the caller's own and not a
  newer owner's. Nothing is adopted: content is either rewritten by this generation or
  genuinely gone from the source;
- a row whose generation is PRESENT but unusable (non-integer, zero, negative) is a
  NAMED error, never a guess: it is neither orderable nor covered by IS-NULL, so
  adopting or deleting it would be an assumption;
- the vanished-source path converges the same way (IS-NULL for legacy rows, the
  ordering predicate for stamped ones), so a legacy source can be removed at all;
- the repair is RECORDED in `SyncResult.backfilled` -- a run that had to repair
  pre-existing rows is visible in its own result. It is deliberately not added to the
  MCP tool envelope: the FK-13 §13.4.1 return fields are a fixed contract.

**Fail-closed boundaries.** The backfill only ever runs under a HELD claim for that
source (a source held by another writer is rejected by D3 before anything is touched);
a partial backfill -- fewer rows confirmed than requested -- raises and publishes no
completion; and the IS-NULL condition is evaluated by the store, so the scope cannot
widen by an application mistake. The new transport call carries the exact-counter
validation from the start (the N44 lesson), not as a follow-up.

**Tests.** The scenario Codex named -- current rows written, then one legacy row -- now
converges on the FIRST run, removes the legacy row, publishes freshness, and a second
run is a clean no-op; a legacy row that is still current is stamped by the write rather
than deleted; a vanished legacy source converges; a vanished source with mixed
stamped/unstamped rows converges; the backfill's uuid list contains ONLY unstamped
rows (the stamped one is removed by the ordering predicate instead); an unclaimed
backfill is impossible; a partial backfill is fail-closed; and the emitted transport
filter really is `by_id CONTAINS_ANY ... AND owning_generation IS NULL`.

### The false premise is corrected in both places

FK-13 §13.9.9 no longer claims the chunk write is harmless "because the content is the
same". It states what the window actually is: the write stays unguarded, changed
content produces DIFFERENT uuids that the newer generation does not overwrite, and the
window is therefore bounded by the post-completion sweep -- with whatever lands after
it removed by the next sync. It also documents the legacy-row convergence. The D9
record gets a second dated addendum that marks the "same content" premise FALSE, records
the analysis that led to shape 3 (removability was never the problem; promptness and
misreporting were), and names the two rejected shapes with the reasons. No atomicity is
claimed in either place, and §13.9.6/`doc_kind` stays untouched.

## Codex review r9 remediation -- pile 1 (ordinary defects)

Six ordering and strictness defects, none of them the structural problem.

**N46 (part 1) -- receipt last.** The completion was published BEFORE the required
final delete, so a failed cleanup returned an error after freshness had already
advanced. The required destructive step now runs from a FRESH read immediately before
the completion: AC6's receipt-last order holds, and reading fresh means the delete
still covers everything that landed up to that moment.

**N47 -- write before delete.** The legacy cleanup deleted old rows BEFORE the upsert,
so a failed write left the source with neither its old rows nor a complete replacement,
and no completion either. The mandated order is restored: prevalidate the complete row
set (no mutation) -> write and verify the should-set -> IS-NULL legacy delete +
ordering delete -> receipt. The intervening write failure is now tested in both forms
(a raising transport and a short confirmed count), which the success test never did.

**N48 -- project isolation on every delete.** The new legacy delete carried neither a
project nor a source predicate. Both conditional deletes now build their filter through
ONE shared scope builder that always adds `project_id` AND `source_file` beside the
operation's own predicate, so a delete never depends on the caller having read
correctly.

**N49 -- validate the vanished set first.** The vanished path deleted null-generation
rows before validating the stamped ones. It now classifies and validates the COMPLETE
row set before the first delete, and reports its legacy repair in
`SyncResult.backfilled`.

**N50 -- the release marker is validated in full.** Any row at the deterministic uuid
counted as a release, so a malformed duplicate carrying `state=claimed` made a sync
report a successful release while the source stayed HELD. State, project, source, owner
and generation are all checked now.

**P2-7/P2-8 -- two false explanations removed, not trimmed.** The production comments
and the module contract no longer carry the refuted "same content" premise. And the
r8 test rationale ("a taken-over holder never reaches its completion, because the
receipt fence rejects it") was **false**: the fence is a read followed by a separate
write, so a takeover landing after it still lets a superseded holder publish a
lower-generation completion and run its own final delete. What protects the newer rows
is ONLY the ordering predicate -- never the fence. The test now says that.

### Transport-call audit (explicitly requested)

Every transport call added across this story, checked against the three obligations:

| call | exact counters | project isolation | generation predicate |
|---|---|---|---|
| `delete_by_ids_if_property_below` (ordering delete) | yes (`_conditional_delete_counts`) | yes -- `project_id` + `source_file` in the condition (added now) | yes -- `< own generation` |
| `delete_by_ids_if_property_absent` (legacy delete) | yes (same validator, from the start) | yes -- added now | n/a by design: it matches ONLY rows with no generation, which is what makes it safe |
| `delete_by_ids` (unconditional) | yes -- counts only confirmed `True` returns | structural: used ONLY on the claim/receipt collections, whose uuids fold in project + source; never on `StoryContext` | n/a (auxiliary records, not corpus rows) |
| `upsert` | yes -- exact confirmed count, partial batch rejected (R12) | every object is validated against the bound target before the write (N13) | writes the stamp itself |
| `insert_object` | conditional create, boolean return, no count to coerce | uuid folds in project + source | n/a |
| `search_objects` / `fetch_by_property*` | n/a (reads) | reads are project-post-filtered; every MUTATION is scoped, which is where AC4 binds | n/a |

Two of these obligations had already been missed once each (N44 counters, N48
isolation), so the rule is now pinned structurally rather than restated: a test asserts
that no `StoryContext` row can be deleted through the unconditional call and that both
conditional deletes pass the authoritative scope. **One observation left open on
purpose:** `fetch_by_property` pages by a single property and post-filters the project
in Python, so a read is broader than strictly necessary. It is not an isolation defect
(no mutation follows without the scoped condition), and narrowing it would change the
read contract, so it is recorded rather than changed in this round.

## Codex review r9 -- pile 2: the carve-out

**The structural finding.** *"One finite sweep cannot close a write that may land
afterwards."* Codex is right, and the correction is mine to own: my r8 wording claimed
the window was bounded "up to the completion" while the cleanup ran AFTER it, and then
admitted later arrivals wait for the next sync. That is neither completion-bounded nor
finite. Both statements are corrected.

**The residual, stated precisely.** After a stall, an administrative reclaim and a
zombie writer resuming, a row of a LOWER generation can land after the newer owner's
final delete and stay visible until the next sync of that source. That moment is not
time-bounded: it can be minutes, days, or never. During it, retrieval can serve two
versions of the same section and `story_list_sources` counts the extra rows, while
`corpus_revision` reports the newer state. What is NOT at risk: deletion of the newer
generation's data, and the direction of reported freshness.

**Where it is now written down.** FK-13 §13.9.9 states what actually holds, names the
residual as open and unratified, and assigns it to a follow-up story -- claiming no
atomicity and no bound. The D9 record carries a third dated addendum recording that
shape 3 narrowed but did not close the window, why a finite pass cannot cover a later
arrival, and that the resolution space is exactly Codex's three options with option 3
requiring PO ratification.

### Follow-up story proposal (NOT created -- a new story needs PO consent)

**Working title.** "Post-completion consistency of the corpus write window".

**Scope.** Close or contractually accept the residual above. It owns the *visibility*
of stale lower-generation rows after a completion; it does NOT reopen the delete
ordering, the generation ladder, the completion ordering or the legacy convergence --
those are closed here and should be treated as its foundation.

**Resolution options, with their costs.**

| # | Option | Cost / consequence | Prerequisite |
|---|---|---|---|
| 1 | Eliminate or storage-fence the stale write | Not available at this seam (verified over three rounds: the pinned client offers no write precondition). Emulating it with generation-scoped uuids destroys the deterministic chunk identity that idempotent re-sync, the delete closure and the identity validation all rest on -- i.e. a new data model plus retrieval deduplication. | A different storage primitive or a deliberate identity-model change |
| 2 | Exclude non-authoritative generations at retrieval | Coherent ONLY with `corpus_revision` as the discriminator, never the generation (retrieval spans many sources with no per-source bound, and FK-13 deliberately keeps that ordinal off the query surface). Couples every query to the completion set, grows the filter with the number of sources in scope, and leaves the rows present for unfiltered readers and counts. | A ratified retrieval-side contract change (§13.9.5) |
| 3 | Ratify a contract that models the bounded-in-practice/unbounded-in-theory inconsistency honestly | Cheapest in code, but it is a normative statement about what the corpus may show; it must say plainly that a search can transiently return superseded rows. | **PO decision** |

**Acceptance criteria it would own.** (a) A stale write that lands after a completion is
either impossible, invisible to retrieval, or covered by a ratified, documented
contract; (b) whichever is chosen, a real-path test drives the stall/reclaim/zombie
sequence and asserts the chosen guarantee; (c) FK-13 §13.9.9 states the resulting
guarantee without an unkeepable bound; (d) no regression of AG3-174's delete ordering,
generation ladder, completion ordering or legacy convergence.

**Dependency.** Depends on AG3-174 (it builds on the persistent generation, the
storage-conditional deletes and the completion ordering). It does not block AG3-174's
landing, which stays gated on AG3-172.

## Ratification needed -- NOT decided in this story

### Q1 -- an authority-scope input for `concept_search` (N23) -- RATIFIED as D7

**Resolved.** The PO ratified the optional `authority_scope` parameter on
2026-07-25 (D7). Rules 1 and 2 are productive and the concept change is anchored in
FK-13 §13.9.5/§13.9.11 with the accompanying decision record. Codex r6 confirmed
the change as "accurate and bounded" and the implementation as strict. AC5 is
nonetheless still open — not because of D7, but because of the rule-4 incoherence
(N36, see the header and Q3). The question below is kept for the record.

*Original question:* should `concept_search` gain a ratified authority-scope
parameter, or should the scope come from another ratified source (e.g. a module ->
scope mapping)? — Answered: an explicit parameter; the mapping was rejected.

### Q3 -- the residual check-then-mutate window (N33) -- RATIFIED as D9

**Resolved.** The PO ratified D9 on 2026-07-25: secure only the DESTRUCTIVE step
storage-side and document the two harmless windows honestly. Implemented as
described under "D9 implementation", including the correction that the proposed
"epoch older than mine" predicate does not hold (claim epochs are not monotonic
across runs) and is replaced by equality against the observed ownership token.

The facts that shaped the decision, kept for the record:

- The pinned client offers no general epoch-conditional mutation: `insert` is
  conditional on the OBJECT ID only, while `update`, `replace` and `delete_by_id`
  take no precondition at all. `delete_many(where=...)` IS filter-conditional --
  which is exactly the step that needed it.
- The three fenced steps carry very different risk: the chunk write is idempotent,
  the completion is insert-only and position-bound (N28), and only the delete is
  destructive.
- A takeover protocol that provably quiesces the old process cannot live in this
  layer: the superseded writer may be another OS process, so quiescing needs
  out-of-band process supervision that the vectordb layer does not own.

### Q4 -- rule 4 vs. the single-`concept_status` filter (N36) -- RATIFIED as D8

**Resolved.** The PO ratified mixed status result sets on 2026-07-25 (D8) and chose
that over retiring rule 4. Implemented as described under "D8 implementation": the
status filter is a strictly validated SET with the default unchanged at
`["active"]`, evaluated server-side, and rule 4 orders within a mixed set as a
precedence tier. As predicted while the question was open, no ranking change was
needed — `_status_tier_penalty` and its whole-tier demotion already worked off the
corpus status; what changed is the tool contract, the transport filter and the
filter faithfulness of the test double.

### Q2 -- the `doc_kind` vocabulary of §13.9.6 vs. AK3's own corpus (N20) -- STILL PENDING

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
neither — D7 explicitly leaves §13.9.6 untouched. Nothing silently points at the
wrong corpus in the meantime: the CLI argument is required and the MCP entry point
demands `AGENTKIT_CONCEPTS_DIR`.

**Operational consequence worth naming:** the two LLM-backed nightly concept gates
(W2 authority prose, W3 scope consistency) ingest `concept/` before they evaluate
anything, so today they abort on this gap instead of running. They are non-blocking
by CI design, but they deliver no signal until Q2 is decided. That is a
pre-existing condition of the repo, not of this story.

## Validators (project venv only)

- `.venv\Scripts\python -m pip install -e ".[dev]"` -- OK
- `.venv\Scripts\python -m ruff check src tests tools/concept_ingester` -- clean
- `.venv\Scripts\python -m mypy src` -- clean (998 files)
- `.venv\Scripts\python -m pytest --cov=agentkit --cov-report=term` (project addopts
  `-n 4 --dist loadfile`) -- after the r9 remediation: **4 failed, 9969 passed,
  40 skipped, 521 errors**; total coverage **86.72 %**, AG3-174 modules **93.21 %**
  (gate 85 % reached, with margin). The same 4 failures as in every earlier round, i.e.
  none of r4-r9, N41/N43 or D7-D9 introduced any.
  - **Correction, stated plainly:** the coverage figures reported in the r5, D7, r6
    and D8 rounds (85.87 / 85.69 / 85.64 / 85.53 %) are NOT trustworthy and are
    withdrawn. The project's `addopts` contain no `--cov`, so a plain `pytest` run
    measures nothing; `coverage report` was therefore re-reading a STALE `.coverage`
    data file while re-parsing the CURRENT sources, which is exactly why the number
    drifted downward as the change added statements. Measured properly with an
    explicit `--cov` run, the total is **86.53 %**.
  - Worth knowing beyond this story: because the default invocation collects no
    coverage, the 85 % guardrail is not enforced by simply running `pytest`. Reported
    rather than fixed here -- changing the project-wide pytest configuration is
    outside AG3-174's scope.
  - `sync.py` shows an apparently low per-file value. Its missing lines are the
    module-level ones (imports, class/def statements), i.e. an xdist/pytest-cov
    import-time measurement artefact, not an untested branch -- the module has 54
    dedicated tests. The artefact can only UNDERSTATE the total, so the gate result
    holds a fortiori.
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
- Revert-check for pile 1 (8 scenarios, all RED): the receipt published before the
  required delete, the missing prevalidation, the legacy delete moved back before the
  upsert, the conditional-delete filter without project/source predicates, the vanished
  path deleting before validating, the vanished path not recording its backfill, the
  release marker accepted on its uuid alone, and an unconditional delete aimed at the
  corpus collection.
  - One case came back GREEN first and is named: my initial `N47-delete-after-write`
    patch was a no-op (`... if False else 0`), so it reverted nothing. Rewritten to
    genuinely reintroduce the pre-write legacy delete, it is RED.
- Revert-check for N41/N43 (9 scenarios, all RED): the sweep not existing, the sweep
  without its ordering bound, the sweep bound not being the holder's own generation, the
  backfill not existing, the backfill also taking the should-set rows, the
  unusable-generation error, the partial-backfill fail-close, the vanished path not
  converging legacy rows, and the transport sending an ordering instead of the IS-NULL
  condition.
  - TWO of these came back GREEN first and are named as such: the sweep-bound case
    (the test never observed the sweep's bound, because the sweep had no candidates ->
    a stale row is now injected at the completion so both conditional deletes are
    observed) and the transport IS-NULL case (no test inspected the emitted filter, so
    changing it was invisible -> a transport test now asserts the real filter, plus the
    exact-counter strictness on that new call).
- Revert-check for r8 (10 scenarios, all RED): the coercive delete counters (missing,
  string, float, bool, None -- on the helper AND on the real transport call), the
  negative-count guard, the impossible-total guard, the confirmed claim release (after a
  successful sync and on the vanished path), the denied release marker, the primary
  sync fault surviving a release failure, the typed identity through the export port,
  the export's `SyncError` handler, the index not re-deriving `chunk_id`, and the
  end-to-end order-2 conditional delete.
- Revert-check for r7 (13 scenarios, all RED): the delete ordering against an
  OBSERVED value instead of the deleter's own generation (both race orders + the
  mid-window path), a destructive release resetting the ladder, a released generation
  wrongly blocking the next writer, the transport sending an equality instead of an
  ordering, the unorderable-object refusal, the schema property, the export bypassing
  the sync owner, freshness ordered by position instead of generation, pruning by
  position, the digest not binding the generation, a completion without a generation
  being accepted, the run-wide gate, and the derived completion-input gate.
  - One further scenario was DROPPED rather than reported as a passing revert: making
    `_highest_generation` ignore `released` markers changes nothing, because the
    generation's `claimed` record is itself retained -- the ladder is carried by not
    deleting the claim record, which the "destructive release" scenario already pins.
    A revert that reverts nothing is not evidence.
- Revert-check for D9 (10 scenarios, all RED -- the D9 mechanism itself was later
  superseded by N37; see the r7 section): the store deleting unconditionally
  instead of through the ownership condition, the write not stamping the token, the
  store accepting an unstamped write, the fail-close on an unreadable owner, the
  token collapsing to the epoch alone, grouping collapsing to one observed token
  (which is what would silently skip old chunks), the short-count fail-close, the
  transport sending a bare id list instead of the AND-condition, a reported failure
  not being fail-closed, and the schema property being removed.
- Revert-check for D8 (7 scenarios, all RED): bare-string coercion, duplicate
  de-duplication, the server-side set condition collapsing to a single equality, the
  empty-set fail-close, the advertised array contract, the double ignoring the
  transport filters (which is what made the old rule-4 proof a sham), and rule 4's
  whole-tier status demotion itself.
- Revert-check for r6 (8 scenarios, all RED): the single-source completion-input
  gate, the matrix completion-input gate (proving the vanished-source delete stays
  unreached), the whitespace-strict receipt verification, the source-property
  comparison, the read-back projection reading the installed field name, the explicit
  declaration at creation, the SSOT list being derived from the schema instead of
  hand-written, and the real CLI composition passing the selection through.
- Revert-check for D7 (7 scenarios, all RED): the scope not being threaded into the
  resolver, the scope being derived from `module` as a fallback, the scope leaking
  into the transport filters, a lenient (coercing) optional validator, the contract
  parameter being dropped, rules 1/2 degraded from a precedence tier to a bonus, and
  rule 2 crediting the deferring source instead of the target.
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
