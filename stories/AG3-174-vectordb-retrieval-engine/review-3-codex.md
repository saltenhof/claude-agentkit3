# AG3-174 — Codex Review r3

- **Datum:** 2026-07-24
- **Reviewer:** Codex (read-only, Fortsetzung r1/r2-Session)
- **Branch:** `feat/ag3-174-vectordb-retrieval-engine` (nach 4 r2-Remediation-Commits)
- **Orchestrator-Verifikation vorab:** ruff/mypy clean (998), 373 Tests gruen.

## VERDICT: REJECT

Fortschritt, aber nicht konvergiert. Offen r1=14 → r2=20 → r3=18. Kernmuster
weiter: Tests pinnen das reale Verhalten nicht vollstaendig; zusaetzlich echte
Produktionsbugs (Cross-Project-Write, Fail-open-Reparatur, falsche Weaviate-API,
Datenverlust).

## Status je Finding

**CLOSED (7):** R02, R05, R07, R08, R09, N01, N07.

**STILL-OPEN (13):**
- **R01** — nur 2 Tools ueber FastMCP getestet; Regressionen der anderen bleiben gruen (`test_engine_realpath_r2.py:543`).
- **R03** — Produktion uebergibt `grpc_host` an `connect_to_local`, das das nicht unterstuetzt; korrekt waere `connect_to_custom`. Der `**kwargs`-Fake verdeckt den `TypeError` (`weaviate_adapter.py:304`). **Echter Bug.**
- **R04** — beide realen Caller lassen `source_file` weg → UUID weiter aus absolutem Pfad; Export-Frontmatter ohne title/status. Der Test nutzte fabrizierten Direkt-Input (`story_md_export.py:92/173`, `mcp_server.py:283`).
- **R06** — `concept_ingester` ignoriert Discovery-Fehler und ingestiert die erfolgreich geparste Teilmenge; Test hat nur validen Korpus (`discovery.py:190`).
- **R10** — Regel 3 ueber `concept_search` unerreichbar (`query_detail=""` fix); Rule-5-Test besteht auch, wenn der positive Boost ganz geloescht wird (`mcp_server.py:166`).
- **R12** — `delete_by_id` gibt bool zurueck (False bei fehlender UUID), Adapter ignoriert das und zaehlt `deleted` bedingungslos hoch; Full-Reindex-Vanished-Deletes fehlen in den Countern (`weaviate_adapter.py:535`, `sync.py:273`).
- **R13** — `_drop_none` loescht explizites JSON-`null` fuer JEDES optionale MCP-Arg; `limit:null`/`full_reindex:null` → Defaults. Probe deckte nur `project_id` (`mcp_server.py:339`).
- **N02** — Test ruft `ensure_story_context_collection`, das Produktion nie aufruft; keyword-Suche ohne Score-Metadaten obwohl Response Score braucht; near_text nutzt faelschlich Score statt Vektordistanz (`weaviate_adapter.py:428`).
- **N03** — Store-Claim ist non-atomarer fetch-then-upsert Race; zwei Prozesse sehen beide keinen Claim und gewinnen beide; Test preclaimt manuell statt zu racen (`engine.py:168`).
- **N04** — Story-Revision weiter der Concept-Corpus-Digest; „latest"-Receipt = lexikografisches Max ueber Hashes statt letzter erfolgreicher Abschluss (`mcp_server.py:292`, `engine.py:280`).
- **N05** — fehlendes Frontmatter akzeptiert; numerische/boolesche Story-Metadaten mit `str()` koerziert (`ingest/adapter.py:94/101`).
- **N06** — `WeaviateStoryIndex` lehnt divergente Objekt-IDs ab, aber export/repair akzeptieren weiter beliebiges CLI `--project-id`/`AGENTKIT_PROJECT_ID` statt der autoritativen Bindung (`story_commands.py:488/526`).
- **N08** — persistierte Receipts nach `str()`-Koerzierung ohne Pflichtfeld-/Digest-Pruefung vertraut → malformtes Receipt kann Freshness vorschieben (`engine.py:193`).

## Neue P0 (N09–N13)
- **N09 `mcp_server.py:84`** — `story_search` verletzt Limit-/Ranking-Vertrag: jede Source mit vollem Limit abgefragt, dann konkateniert ohne globale Score-Ordnung/Truncation → `limit=10` kann 20 liefern, alle Story vor Research.
- **N10 `mcp_server.py:174`** — `_ranked_envelope` mapt Hits per `concept_id`; mehrere Section-Hits desselben Konzepts kollabieren → erster Treffer geht verloren.
- **N11 `weaviate_adapter.py:408`** — `search_objects` nutzt `setdefault` fuer fehlende Properties statt Ablehnung → malformter Hit ohne concept_id/title/source_type kommt als leer-erfolgreich zurueck (AC10-Verstoss, Reparatur-Default).
- **N12 `weaviate_adapter.py:564`** — bestehende Collection wird ohne Verifikation akzeptiert; drift/`self_provided` Collection passiert die Komposition, dann scheitern semantische Modi.
- **N13 `sync.py:304`** — `_sync_impl` prueft `source_type`, aber nicht `project_id`/`source_file` je Objekt → ein `acme`-Sync mit Objekt `project_id=other` schreibt ins Fremdprojekt bevor der Should-Set-Check greift (D2-Verstoss).

## Scope/Decisions
Scope PASS (kein Leakage). Decisions FAIL: D1 (N04), D3 (N03), D2 (N06/N13) verletzt; D4/D5/D6 intakt.
