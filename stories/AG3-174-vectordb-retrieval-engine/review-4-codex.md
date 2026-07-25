# AG3-174 — Codex Review r4

- **Datum:** 2026-07-25
- **Reviewer:** Codex (read-only, Fortsetzung r1–r3-Session)
- **Branch:** `feat/ag3-174-vectordb-retrieval-engine` (nach 9 Commits eines neuen
  Coding-Agents — Opus 5 ersetzte den vorherigen Agent nach r3)
- **Orchestrator-Verifikation vorab:** ruff clean, mypy clean (998), 463 Tests
  gruen im Scope, Tree clean.

## VERDICT: REJECT

**Qualitativer Sprung, aber tiefere Befunde.** Die Review prueft erstmals gegen
die *installierte* `weaviate-client 4.22.0` und gegen AK3s *echten* Korpus —
dadurch treten Defekte hervor, die vorher unter Fakes verborgen blieben.

## Status der 18 r3-Findings

**CLOSED (7):** R01, R03, R12, R13, N05, N09, N10.

**STILL-OPEN (11):** R04, R06, R10, N02, N03, N04, N06, N08, N11, N12, N13 —
jeweils mit praeziserer Diagnose in den neuen Findings unten.

**REGRESSIONEN in vorher geschlossenen (2):**
- **R05 / N01** — die N11-Remediation liess `module`/`epic` aus den Story-/
  Research-Return-Profilen fallen, obwohl der MCP-Vertrag sie annonciert
  (`schema.py:78`); Research-Positivpfad gelingt nur, weil Tests
  Story-Frontmatter fabrizieren (`ingest/adapter.py:125`).

**Bleibt geschlossen:** R02, R07, R08, R09, R11, R14, N07.

## Neue Findings

**N14 P0 `weaviate_adapter.py:658`** — Der Claim-Test faked eine Exception, die
der installierte Client nicht wirft: `_DataCollection.insert` routet
Duplikat-UUIDs ueber `UnexpectedStatusCodeError`, Produktion faengt nur
`ObjectAlreadyExistsException`. Der Verlierer wird also `VectorDbWriteError`
statt sauberer D3-Rejection.

**N15 P0 `engine.py:241`** — Claims haben keinen Owner/Epoch/Expiry: ein Crash
nach dem Insert laesst die deterministische UUID **fuer immer** stehen (der
versprochene Retry-Reconcile existiert nicht). Zusaetzlich loescht
`_delete_vanished_sources` ohne jeden Claim (`sync.py:340`) → D3-Verstoss.

**N16 P0 `engine.py:162`** — `sequence=max+1` ist nicht atomar, und der Digest
bindet nur project/source/revision; `sequence`, `completed_at`, `state`,
`source_type` bleiben manipulierbar → Receipt-Replay kann Freshness vorschieben
(D1).

**N17 P0 `sync.py:259`** — N13-Validierung liegt weiter **nach** Mutationen:
`sync_source` schreibt den Claim vor der Objekt-Validierung, und
reconcile/full-reindex loeschen vanished Sources, bevor irgendein
eingehendes Objekt geprueft wurde → Teil-Mutation trotz AC10-Nullmutation.

**N18 P0 `weaviate_adapter.py:727`** — Alle Properties werden mit
`Tokenization.FIELD` erzeugt: „Vector retrieval engine" wird als **ein** Token
indiziert, die Keyword-Query „retrieval" matcht nicht. Die N12-Verifikation
vergleicht nur Namen/Typen und kann diesen Drift nicht erkennen.

**N19 P0 `schema.py:78`** — Per-Source-Profil widerspricht dem MCP-Vertrag:
`story_search` annonciert `module`/`epic` (`contracts.py:130`), das Profil
fordert sie nicht an → unvollstaendiges Envelope bleibt gruen, weil der Test nur
`story_id` asserted.

**N20 P0 `concepts/frontmatter.py:68`** — Der SSOT-Parser kann den echten
`concept`-Korpus nicht lesen: Probe ergab **0 Dokumente / 347 Parse-Fehler**
(nur `core|appendix` akzeptiert; null-Optionals, policy/decision/spec/detail
abgelehnt) — waehrend die CLI genau auf dieses Verzeichnis defaultet
(`vectordb/cli.py:269`). Zudem hardcodet der Adapter `contract_state`,
Policies, Formal-Refs, Glossar-Linkage und Exported-Terms leer
(`concept_ingester/discovery.py:266`) → Verhalten des ersetzten Ingesters
verloren. **Enthaelt eine Konzeptfrage (siehe unten).**

**N21 P0 `story_md_export.py:192`** — `canonical_story_source_file` nutzt nur
`story_dir.name`, prueft weder Containment unter `<project>/stories/` noch
Uebereinstimmung mit der `story_id`: Export von `AK3-042` nach `C:\tmp\foo`
landet als `stories/foo/story.md`; `story_sync` findet/loescht es nie und ein
zweites `foo` kollidiert. Der Test billigt den Temp-Ordnernamen ausdruecklich.

**N22 P0 `project_binding.py:160`** — `_project_id_from_config` faengt
`AgentKitError`/`OSError`/`ValueError` und meldet „not found": malformte oder
unlesbare Config wird mit *Abwesenheit* verwechselt und faellt auf `PROJECT_ID`
zurueck (D2-Verstoss).

**N23 P0 `resolver.py:120`** — Authority-Ranking konflatiert `module` und
`authority_over`-Scope: Produktion uebergibt den Module-Filter als beides.
Zudem lassen additive Konstanten einen hohen BM25-Score eine Autoritaet
schlagen, die normativ „beats". **Enthaelt eine Konzeptfrage (siehe unten).**

**N24 P0 `ingest/adapter.py:125`** — Research-Ingest verlangt Story-Frontmatter
(`story_id`), obwohl der kanonische Producer-Vertrag Research ueber den Pfad
`stories/<story>/research/**/*.md` identifiziert. Eine normale Research-Notiz
laesst den ganzen `story_sync` scheitern; Tests verdecken das, indem sie
`_STORY_FM` in Research-Dateien kopieren.

**N25 P1 `weaviate_adapter.py:638`** — Paginierung lehnt genau die konfigurierte
Obergrenze ab (`offset == MAX_FETCH_OBJECTS` → „exceeds", ohne zu pruefen ob
ueberhaupt ein weiteres Objekt existiert); Duplikat-/inkonsistente Seiten werden
nicht erkannt.

## Adjudikation von `0fdbead8` (Autoritaets-Metadata)

**Bestaetigt und als legitim befunden.** Die Root-Cause-Behauptung ist **wahr**:
die frueheren R06-Migration entfernte `authority_over_full`/`defers_to_full`/
`supersedes_full`. Die Wiederherstellung rekonstruiert die qualifizierten
Eintraege korrekt, und die Regression erreicht den echten
`authorization_scopes()`-Consumer. Die drei Fixture-Edits sind **echte
FK-13-§13.9.6-Konformitaetskorrekturen mit unveraenderten Assertions — keine
aufgeweichten Tests.** Einschraenkung: der Commit reparierte nur die
Autoritaets-Teilmenge; N20 zeigt, dass die breitere SSOT-Migration unvollstaendig
bleibt.

## Scope / PO-Decisions

Scope **PASS** — kein Leakage in AG3-175/176/172/173.

- **D4, D5, D6** — eingehalten/unberuehrt.
- **D1** verletzt durch replaybare/nicht-atomare Freshness-Ordnung (N16).
- **D2** verletzt durch Invalid-Config-Fallback (N22).
- **D3** verletzt durch unrecoverable Claims und ungeclaimtes Vanished-Delete (N15).

Bewertung der drei protokollierten Interpretationen:
- server-seitiger `text2vec-transformers`: **korrekt**.
- Rule-3-Detail deterministisch aus dem Query-Text: **akzeptabel**.
- Authority-Scope an `module` gebunden: **nicht akzeptabel ohne Ratifizierung**.
- kanonisches `stories/<story>/story.md`: konzeptionell richtig, aber die
  Implementierung *fabriziert* die Identitaet statt den echten Pfad zu
  verifizieren → **nicht akzeptabel** (N21).

## Zwei Punkte mit Konzept-/PO-Bedarf

1. **N23** — FK-13 modelliert `module` und `authority_over`-Scopes getrennt,
   §13.9.5 definiert aber keinen Scope-Parameter fuer `concept_search`. Ein
   explizites, ratifiziertes Scope-Konzept ist erforderlich; die Konflation ist
   abzuloesen.
2. **N20** — AK3s eigener `concept`-Korpus folgt einer anderen
   Frontmatter-Konvention als FK-13 §13.9.6. Entweder ist der CLI-Default auf
   `concept/` falsch (Code-Fix, im Scope) oder §13.9.6 muss erweitert / ein
   zweites Korpus-Profil deklariert werden (Konzeptaenderung, **ausserhalb**
   dieser Story).
