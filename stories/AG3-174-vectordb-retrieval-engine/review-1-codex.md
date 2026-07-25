# AG3-174 — Codex Review r1

- **Datum:** 2026-07-23
- **Reviewer:** Codex (read-only, adversarial)
- **Branch:** `feat/ag3-174-vectordb-retrieval-engine` (5 Commits ueber `main`)
- **Orchestrator-Verifikation vorab:** ruff clean, mypy clean (997 Dateien), 198
  Tests gruen im AG3-174-Scope; drei Findings (R01/R03/R07) per Spot-Check
  bestaetigt.

## VERDICT: REJECT

Roter Faden: viel gruen getestetes Geruest, aber zahlreiche Falsch-Gruen-Pfade —
Tests pruefen Namen/Shapes statt echtes Verhalten, und mehrere Produktionspfade
(realer MCP-Server, reale Adapter-Verdrahtung, SSOT-Migration, Sync-Zaehler)
sind Stubs oder fehlen.

## Findings

### P0 (landeblockierend)

**R01 — `mcp_server.py:301` — Alle fuenf MCP-Input-Schemas unbrauchbar.**
Der generische `**kwargs`-Handler laesst FastMCP eine einzige Pflicht-Property
`kwargs` annoncieren statt der FK-13-Parameter (per Probe fuer jedes Tool
reproduziert). Ein normaler `{"query":"..."}`-Call erfuellt das annoncierte
Schema nicht; der Test `test_mcp_server.py:156` prueft nur Namen. → Explizit
typisierte Handler registrieren; vollstaendiges `inputSchema`, Pflichtparameter
und echte MCP-Calls fuer alle fuenf Tools asserten.

**R02 — `mcp_server.py:65` — Kein lauffaehiger Produktions-Engine.**
`McpToolService` braucht injizierte Retrieval-/Store-Services; nur Tests
instanziieren sie mit Fakes. Kein produktiver `RetrievalPort`/`CorpusStorePort`,
keine Runtime-Komposition, kein stdio-Entry-Point, keine idempotente
StoryContext-Collection-Erzeugung. → Realen duennen Transport-Adapter,
Schema-Owner, env-gebundene Komposition und ausfuehrbaren Server bauen; Nicht-
Default-Endpunkt per Subprozess-Test beweisen.

**R03 — `runtime_binding.py:31` — D2/AC11 machen den gRPC-Endpunkt still optional.**
`REQUIRED_ENV_KEYS` laesst `WEAVIATE_GRPC_ENDPOINT` aus; Zeile 132 liefert `""`
wenn fehlend, obwohl die Story beide Endpunkte fail-closed verlangt. → Beide
Endpunkte pflichtig und strikt validieren und exakt in die Produktionsverbindung
durchreichen.

**R04 — `story_md_export.py:159` — Exportierte Stories verletzen das StoryContext-Schema.**
Der unveraenderte Exporter sendet nur `story_id/title/problem/solution/
story_type/module/epic`; es fehlen `content`, `project_id`, `source_type`,
`source_file`, `content_hash`, Headings und deterministische UUIDs. Umgeht das
neue Schema; AC3 (vollstaendige Felder, projektbegrenzt, idempotent) nicht
erfuellbar. → Export-Indexierung durch die typisierte AG3-174-Story-Ingest-
Projektion routen und am echten Adapterrand verifizieren.

**R05 — `mcp_server.py:243` — Story/Research-Discovery und Delete-Closure nicht implementiert.**
`story_sync` scannt nur `**/story.md`, nutzt den Classifier nie, ingestiert kein
Research, speichert absolute Pfade; inkrementeller Sync besucht verschwundene
Quellen nie. `story_search` filtert nur `source_type="story"`. → Kanonischen
Classifier nutzen (Story + Research, projekt-relative Pfade), beide Owned-Types
suchen, Remote-vs-Discovered-Gleichheit inkrementell reconcilen.

**R06 — `tools/concept_ingester/discovery.py:349` — SSOT-Migration fand nicht statt.**
Das Tool behaelt eigenes `discover()`/`ConceptChunk`, lenienten
`yaml.safe_load`-Parser, zeichenbasiertes Chunking, `Ak3ConceptChunk`/Glossar-
Schemas und localhost-Default. Derselbe Korpus liefert je nach Entry-Point
verschiedene Discovery-Mengen — verletzt AC9 und SINGLE SOURCE OF TRUTH direkt.
→ Tool zum Adapter ueber `agentkit.concepts` umbauen; Glossar-/BC-Projektionen
als explizite Profile, nicht als Parallel-Parser/-Modell.

**R07 — `cli.py:149` — `concept sync` ist ein Erfolg-zurueckgebender Stub.**
Validiert/discovered nur, druckt `sync-ready`, gibt 0 zurueck ohne Storage-
Kontakt; `lint --changed` geparst aber ungenutzt; doctor liefert Zaehler statt
Corpus-Diff-Diagnostik. Automatisierung meldet erfolgreichen Sync bei null
geschriebenen Chunks. → Produktiven SyncService/Adapter in die CLI komponieren;
jede Ring-1/Ring-3-Operation echt implementieren.

**R08 — `cli.py:39` — `validate --staged` faellt bei Git-Fehlern offen.**
Alle `CalledProcessError` liefern leeres Overlay oder ueberspringen still eine
Datei (auch fehlgeschlagenes `git show`); staged Deletions nicht repraesentiert.
Ein Git-/Pfad-/Index-Lesefehler validiert den Working-Corpus und exitet gruen
statt den Candidate-Commit zu pruefen. → Pfade aus Repo-Root aufloesen,
name-status inkl. Deletions konsumieren, jeden unerwarteten Git-/Lesefehler auf
Exit 3 mappen.

**R09 — `validator.py:181` — Finding-Katalog und Tabellentests falsch-gruen.**
Nur drei von sechs Warning-Checks aufgerufen; `W-CONTENT-002`, `W-CONTENT-003`,
`W-SCOPE-001` ohne Implementierung. `E-ID-002` prueft ID-Syntax statt
Dateinamen-Uebereinstimmung; Exit 3 nie erzeugt. Der Exit-1-Test akzeptiert
Errors ODER Warnings (`test_concept_validate.py:113`); fehlende Codes nur als
Konstantennamen getestet (Zeile 357). → Jede Katalogbedingung und echte
Tabellenfaelle je Finding + alle vier Exit-Codes implementieren.

**R10 — `resolver.py:67` — Authority-Ranking implementiert die fuenf Regeln nicht.**
Jedes Konzept mit irgendeinem Scope bekommt Regel-1-Gutschrift ohne
abgefragten Scope; Regel 2 boostet den deferring Node statt das gescopte Ziel;
jeder Appendix bekommt Regel-3-Gutschrift unabhaengig von Interface-/Test-
Relevanz. Unverwandte Autoritaeten/Appendizes koennen deterministisch falsch
oben ranken. → Expliziten Query-Scope/Detail in den Resolver geben, gescopte
Graph-Kanten traversieren, unabhaengige Gegenbeispieltests fuer alle fuenf
Regeln.

**R11 — `parser.py:274` — Concept-Sync hat keine echte Shadow-Generation.**
Concept-Chunk-Identitaet schliesst Content/corpus_revision aus — eine reine
Content-Aenderung behaelt dieselbe UUID; `upsert_objects` ueberschreibt den
alten Chunk, bevor die neue Soll-Generation vollstaendig ist. Leser sehen eine
beliebige Mischung statt des ratifizierten write-new → validate → delete-old
Bounded-Window. → Generation-/Content-Identitaet in Shadow-UUIDs aufnehmen, mit
stabiler logischer Identitaet fuer Reconcile.

**R12 — `sync.py:229` — Teil-Writes/-Deletes publizieren ein Erfolgs-Receipt.**
Der Service ignoriert den Upsert-Count, macht kein Should-Set-Re-Read,
verifiziert den Delete-Count nicht, publiziert dann `COMPLETED`; der reale
Adapter zaehlt gequeuete Objekte ohne Batch-Fehler zu inspizieren. Ein 1-of-2-
Write oder 0-of-1-Delete advanced Freshness und liefert `written=len(objects)`
trotz unvollstaendiger Generation. → Exakte Transport-Zaehler und persistierte
Mengengleichheit vor Delete/Receipt validieren; malformte Pagination/Partial-
Batches ablehnen.

**R13 — `contracts.py:173` — Falsch typisierte MCP-Inputs als weggelassen behandelt.**
Ein Nicht-String-`project_id` wird zu `None` und auf das gebundene Projekt
aufgeloest; falsche `status`/`story_type`/`concept_id`/`module`-Typen still
ignoriert; unbekannte Argumente nicht abgelehnt. `project_id=1` oder
`status=false` gelingen statt eines benannten Validierungsfehlers. → Exakte
Allowed-Key-Sets und jeden optionalen Wert strikt validieren, bevor Defaults
gebunden oder Ports aufgerufen werden.

### P1

**R14 — `impl-plan.md:156` — Geforderter P6-Folge-Owner/-Bericht fehlt.**
Der Plan verspricht die FK-13-§13.6-Folge-Notierung, aber der Branch enthaelt
keinen Story-Bericht und nennt keinen konkreten Downstream-Owner. Landung liesse
die BC-uebergreifende P6-Pflicht still offen (gegen Folge-Auflage + DoD). →
Story-Bericht mit konkret benanntem Folge-Owner ergaenzen; SSOT-Adapter-
Entscheidung dokumentieren.
