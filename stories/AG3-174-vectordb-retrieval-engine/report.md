# AG3-174 Story-Bericht — VektorDB-Retrieval-Engine

## Status

Implementierung abgeschlossen (Engine-Umfang). Landevoraussetzung AG3-172 bleibt
als Workflow-Merge-Gate (Entwicklung parallel ok).

## SSOT-Adapter-Entscheidung

| Schicht | Ort | Rolle |
|---------|-----|--------|
| Domain-Kern (SSOT) | `src/agentkit/concepts/` | Discovery, Frontmatter, Chunking, Hashing, Profiles, `.conceptignore`, CLI |
| App-Ingest-Adapter | `src/agentkit/backend/vectordb/ingest/` | Story/Research/Concept → StoryContext-Chunks, Producer/Delete-Closure |
| Corpus-Lifecycle | `src/agentkit/backend/vectordb/concept_corpus/` | validate, build, graph, resolver, bounded-window sync, receipts |
| Transport | `src/agentkit/integration_clients/vectordb/` | dünner Weaviate-Adapter (keine Business-Rules) |
| MCP | `src/agentkit/backend/vectordb/mcp*` | fünf FK-13-Tools, Runtime-Bindung als SSOT |
| AK3-Tooling | `tools/concept_ingester/` | bleibt AK3-internes Rich-Discovery (Glossary/Domain-Registry) für Governance; FK-13-Ingest-Pfad läuft über `agentkit.concepts` |

`discover_concept_files()` in `agentkit.concepts.parser` ist der Owner für
Validate/Build/Graph/Sync (FK-13 §13.9.13).

## Umgesetzte Teilvertikalen

1. **Packaging/Tokenizer** — `weaviate-client>=4.9,<5.0`, `tokenizers==0.21.0`,
   Asset unter `backend/vectordb/assets/tokenizer/all-minilm-l6-v2/` mit
   DIGESTS.json + LICENSE (Apache-2.0), fail-closed Digest vor Parse.
2. **Projekt-/Runtime-Bindung** — `project_binding.py`, `runtime_binding.py`
   (`McpServerSpec`/`RuntimeBinding`), kein localhost-Default in MCP-Env.
3. **concepts/-Kern** — transportfrei, Profile `fk13_concept`/`fk13_story`/`ak3_tool`.
4. **StoryContext-Schema** — alle §13.3.1/§13.9.3-Properties, idempotent.
5. **Ingest** — Source/Producer/Delete-Closure, deterministische UUID5.
6. **Corpus-Lifecycle** — validate (Exit 0/1/2/3), build, Authority-Ranking,
   Bounded-Window-Sync + digestgebundenes Receipt.
7. **CLI** — `agentkit-concept` lint/doctor/validate/build/sync.
8. **Integrationsgate** — Memory-Port-Tests (Source-Closure, Isolation, Receipt).
9. **MCP** — fünf Tools, drei Suchmodi, strikte Args, Fremd-`project_id` rejected.
10. **Adapter-Härtung** — kein Score-0.0-Default, `search_mode` wirksam.

## Folge-Auflage (DoD)

**FK-13 §13.6 — P6-Kontextselektion (semantische Ergänzung):**  
Kein produktiver Consumer in AG3-174..176. **Benannter Folge-Owner:**
nachgelagerte Story **„P6-Kontextselektion über VektorDB“** (semantische
Ergänzung zum Manifest-Indexer, FK-13 §13.6 / FK-04-021..023). Darf nicht still
als „durch MCP vorhanden“ abgehakt werden.

## Out of Scope (Owner)

- Harness-Registrierung → **AG3-175**
- Installer/CP10a/Preflight/Skills → **AG3-176**
- E2E-Retrieval-Qualität live Weaviate → PO nachgelagert
- Landevoraussetzung → **AG3-172** muss vor Merge grün gelandet sein

## Evidenz (Gates)

| Gate | Ergebnis |
|------|----------|
| `pytest` full suite | **10054 passed**, 14 skipped (0 failed) |
| `mypy src` | Success: no issues found in 1005 source files |
| `ruff check src tests` | All checks passed |
| AG3-174 targeted suite | 76+ unit/integration/contract tests green |
| Tokenizer offline | Digest OK; `count_tokens("hello world")==4` ohne Netz |

### Kernmodule (neu)

- `src/agentkit/concepts/` — SSOT Discovery/Parser/Chunking/CLI
- `src/agentkit/backend/vectordb/` — binding, schema, ingest, concept_corpus, mcp, tokenizer assets
- `src/agentkit/integration_clients/vectordb/weaviate_adapter.py` — gehärtet (search_mode, strict hits)
- `pyproject.toml` — hard deps `weaviate-client>=4.9,<5.0`, `tokenizers==0.21.0`

### Landevoraussetzung

AG3-172 muss vor Merge gelandet sein (Workflow-Gate; nicht nur Kommentar).
