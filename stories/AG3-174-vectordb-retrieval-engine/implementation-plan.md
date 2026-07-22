# AG3-174 — Interner Implementierungsplan (verbindlich vor in_progress)

Status: freigegeben für Umsetzung · 2026-07-21  
Norm: FK-13 + Decision Record 2026-07-21-vectordb-edge-sharpening · keine Neuentscheidungen.

## Teilvertikalen (je Modul- + Testbudget)

| # | Vertikale | Module (Produktion) | Testbudget | Gate |
|---|-----------|---------------------|------------|------|
| V1 | Packaging + Tokenizer-Asset | `pyproject.toml`; `backend/vectordb/assets/tokenizer/`; `backend/vectordb/tokenizer.py` | unit: digest/load/fail-closed; packaging-smoke | deps installierbar, Digest fail-closed |
| V2 | Projekt- + Runtime-Bindung | `backend/vectordb/project_binding.py`, `runtime_binding.py` | unit: containment, env-SSOT, fail-closed | typisierte Bindung ohne Defaults |
| V3 | Ingest-Kern SSOT `concepts/` | `concepts/{parser,discovery,frontmatter,chunking,hashing,profiles,conceptignore,errors}.py` | unit: discovery/ignore/chunk/hash/profiles; lint ohne Weaviate | `discover_concept_files()` ist einziger Owner |
| V4 | StoryContext-Schema | `backend/vectordb/schema.py` | contract: Feldliste ↔ FK-13 §13.3.1/§13.9.3; unit: idempotent ensure | eine Collection |
| V5 | Drei Ingest-Profile (Adapter) | `backend/vectordb/ingest/{__init__,models,source_routing,story,research,concept,identity}.py`; `story_md_export`/`weaviate_index` anbinden | unit+integration: Source-Closure, negative Research, Delete-Scope, idempotent Re-Sync | Producer/Delete-Closure |
| V6 | Corpus-Lifecycle | `backend/vectordb/concept_corpus/{validate,build,graph,resolver,freshness,sync,receipts}.py` | unit+contract: Error/Warning/Exit-Codes, Authority 5 Regeln, ignore-Globs, Bounded-Window | validate blockiert Sync |
| V7 | Drei-Ringe-CLI | `concepts/cli.py` (+ entrypoint) | unit: lint/doctor/validate staged+strict/build/sync | gleicher Discovery-SSOT |
| **IG** | **Integrationsgate VOR MCP** | — | integration: Story+Concept ingest + search + full_reindex both orders + project isolation über echten Port (In-Memory-Port am Adapter-Rand) | grün bevor V8 |
| V8 | MCP-Oberfläche | `backend/vectordb/mcp_server.py`, `mcp/{contracts,tools,server}.py`; Adapter-Härtung | unit+contract: tools/list=5, 3 Suchmodi, Envelopes, Runtime-Bindung, Fremd-project abgelehnt | AC 7–11 |
| V9 | Adapter-Härtung | `integration_clients/vectordb/weaviate_adapter.py` | unit: kein Score-0.0-Default, search_mode wirksam, strikte Hit-Coercion | fail-closed Grenzen |

## Integrationsgate (Pflicht vor MCP)

Vor V8 muss grün sein:

1. Discovery-Menge Validate == Build == Sync (gleicher SSOT).
2. `story_sync` + `concept_sync` in beiden `full_reindex`-Reihenfolgen lassen beide Source-Klassen stehen.
3. Zwei-Projekt-Isolation (keine Cross-Project Writes/Reads/Deletes).
4. `concept_validate` mit Error → Sync startet nicht.
5. Bounded-Window: Write → Validate-Sollmenge → Delete alt → Receipt mit `corpus_revision`.
6. Tokenizer-Digest + Schema-ensure ohne Netz.

## Nicht-Ziele (Owner)

- Harness-Registrierung → AG3-175  
- Installer/Preflight/CP10a → AG3-176  
- E2E-Retrieval-Qualität mit live Weaviate → PO nachgelagert  
- P6-Consumer → benannter Folge-Owner (Story-Bericht)

## SSOT-Adapter-Entscheidung

- Domain-Kern: `src/agentkit/concepts/` (transportfrei).  
- `backend/vectordb/ingest/` und `tools/concept_ingester/` sind dünne Adapter/Konsumenten.  
- Kein zweiter Discovery-/Parser-Pfad.  
- Weaviate bleibt in `integration_clients/vectordb/` dünner Transport.

## Landevoraussetzung

AG3-172 muss vor Merge gelandet sein (Workflow-Gate; Entwicklung parallel ok).
