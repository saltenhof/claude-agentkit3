# AG3-174 — Codex Review r2

- **Datum:** 2026-07-24
- **Reviewer:** Codex (read-only, Fortsetzung der r1-Session)
- **Branch:** `feat/ag3-174-vectordb-retrieval-engine` (nach 6 Remediation-Commits)
- **Orchestrator-Verifikation:** ruff/mypy clean, 345 Tests gruen; R13 + R03
  per Spot-Check als weiterhin offen bestaetigt.

## VERDICT: REJECT

**Nicht konvergiert.** 12 der 14 r1-Findings weiterhin offen (nur R11, R14
geschlossen); zusaetzlich 8 neue P0 (N01–N08). Kernbefund: der in der
Remediation neu gebaute Produktions-`engine.py` ist ueberwiegend nicht real —
Tests sind falsch-gruen (Fakes, die kein echtes Verhalten asserten;
In-Memory-Factories, die den realen Pfad nie ausfuehren).

## r1-Findings — Status laut r2

| ID | Status | Kurz |
|----|--------|------|
| R01 | OFFEN | Regressiontest asserted nur Fragmente, 0 echte MCP-Calls (`test_remediation_r1.py:50`) |
| R02 | OFFEN | Produktions-Retrieval delegiert alles an `story_search`, ignoriert `source_type`/Filter (`engine.py:162`) |
| R03 | OFFEN | gRPC-Endpunkt geparst, aber nie an Weaviate uebergeben (`engine.py:225`) |
| R04 | OFFEN | `source_file` = absoluter Pfad; UUID/Hash daraus; `title=story_id`, leerer `status` (`ingest/adapter.py:102`) |
| R05 | OFFEN | `story_search` nur `source_type="story"`; Produktions-Port ignoriert `source_type` ganz (`mcp_server.py:82`) |
| R06 | OFFEN | `concept_ingester` chunked lokal neu, `document_hash` statt SSOT-Chunk-Hash, lenient `yaml.safe_load`, schreibt weiter `Ak3ConceptChunk` (`discovery.py:265`) |
| R07 | OFFEN | CLI-Erfolgstest injiziert In-Memory-Factory, uebt `_default_service_factory`/realen Engine nie (`test_cli.py:167`) |
| R08 | OFFEN | Nur `GitOperationError` → Exit 3; Copy-/Pfad-/Decode-/Read-Fehler entkommen; Test monkeypatcht die schon-normalisierte Exception (`cli.py:173`) |
| R09 | OFFEN | Per-Finding-Tabelle unvollstaendig: E-SCHEMA-002/003, E-CYCLE-001, E-AUTH-002, W-BIDIR-001, W-CONTENT-001 nur Konstanten-Assertion (`test_concept_validate.py:465`) |
| R10 | OFFEN | Regel 2 boostet den deferring Source statt das Ziel; Regel 3 boostet jeden Appendix bei leerem `query_detail` (`resolver.py:118`) |
| R11 | **CLOSED** | Shadow-UUID mit content_hash, stabile chunk_id |
| R12 | OFFEN | Partial-Deletes in `reconcile_sources`/`full_reindex` nicht count-gecheckt (`sync.py:202`) |
| R13 | OFFEN | Explizites null/`""`-Optional weiter als weggelassen behandelt; Probe: `project_id=null/""` → gebundenes Projekt (`contracts.py:142`) |
| R14 | **CLOSED** | Story-Bericht + benannter P6-Folge-Owner |

## Neue P0-Findings

- **N01 `engine.py:162`** — Produktions-Concept/Research-Retrieval ist ein story-shaped Relabeling; `source_type`/Filter ignoriert; concept_id/status/module gehen verloren.
- **N02 `schema.py:179`** — Collection ohne den geforderten Vectorizer (`self_provided()` statt FK-13 `text2vec-transformers`); Hybrid/near_text auf frischer Instanz nicht nutzbar. **(Braucht FK-13-Adjudikation.)**
- **N03 `sync.py:137`** — D3-Rejection nur instanz-lokal (In-Flight-Set im Prozess); zwei geteilte Services schreiben denselben Source parallel. Braucht shared/atomaren Source-Claim + echten Zwei-Writer-Test.
- **N04 `engine.py:194`** — `story_list_sources` fabriziert leere Freshness (`last_revision=""`), liest keine Receipts (verletzt D1/AC8).
- **N05 `ingest/adapter.py:97`** — `FrontmatterError` wird gefangen und durch `{}` ersetzt → invalides Frontmatter wird still als Teil-Qualitaet indiziert statt AC10-Fehler.
- **N06 `weaviate_index.py:55`** — `project_id`-Mismatch wird ueberschrieben statt abgelehnt; CLI akzeptiert beliebiges `--project-id`/leeren Env-Fallback.
- **N07 `mcp_server.py:201`** — inkrementeller `concept_sync` ruft nie `reconcile_sources` → geloeschte Concept-Chunks bleiben durchsuchbar.
- **N08 `engine.py:282`** — Receipt-Infrastruktur fail-open: Collection-Erzeugung schluckt alle Exceptions, `set_receipt` ignoriert Count, Receipt-UUIDs akkumulieren mehrere Records/Source.

## Scope/Decisions
Kein Code-Leakage in AG3-175/176/172/173. D4/D5/D6 unberuehrt (D5-Pins vorhanden).
D1/D2/D3 verletzt durch N04 / N02+R13 / N03.
