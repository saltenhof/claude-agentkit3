# AG3-174 — Story Report (post Codex review r1 remediation)

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

## Validators (project venv only)

- `.venv\Scripts\python -m pip install -e ".[dev]"` -- OK
- `.venv\Scripts\python -m ruff check src tests` -- clean
- `.venv\Scripts\python -m mypy src` -- clean (998 files)
- `.venv\Scripts\python -m pytest` (AG3-174 scope) -- 294 passed; coverage >= 85%
