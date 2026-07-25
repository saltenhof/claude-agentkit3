# AG3-174 — Story Report (post Codex review r6 remediation + D7/D8/D9)

- **Story:** AG3-174 VektorDB-Retrieval-Engine
- **Branch:** `feat/ag3-174-vectordb-retrieval-engine`
- **Status:** implemented, NOT landed (landing gated on AG3-172, orchestrator's
  job). **The code side is complete; Q2 is the only open item.**
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
- `.venv\Scripts\python -m pytest` (project addopts `-n 4 --dist loadfile`) --
  after r6 + D7/D8/D9: **4 failed, 9904 passed, 40 skipped, 521 errors**. The same 4
  failures as in every earlier round, i.e. none of r4, r5, r6, D7, D8 or D9
  introduced any.
- `.venv\Scripts\python -m pytest --cov=agentkit --cov-report=term` -- total
  coverage **86.53 %** (gate 85 % reached, with margin).
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
- Revert-check for D9 (10 scenarios, all RED): the store deleting unconditionally
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
