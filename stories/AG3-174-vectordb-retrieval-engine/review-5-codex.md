# AG3-174 — Codex Review r5

- **Datum:** 2026-07-25
- **Reviewer:** Codex (read-only, Fortsetzung r1–r4-Session)
- **Branch:** nach 7 r4-Remediation-Commits
- **Orchestrator-Verifikation vorab:** ruff clean, mypy clean (998), 715 Tests
  gruen, Tree clean.

## VERDICT: REJECT

Auf die explizite Frage „ist der Code fertig, abgesehen von den zwei
Ratifizierungen?" — **nein**. Es bleiben echte P0-Defekte in Persistence-
Fencing, Receipt-Ordnung/Replay, Schema-Verifikation, Projekt-Bindung und
kanonischer Pfadbehandlung.

**Aber: klare Konvergenz.** Offene Punkte 25 → 18. Der geschlossene Kern ist
gross und stabil.

## Geschlossen (bestaetigt, ueber mehrere Runden stabil)

R01, R02, R03, R05, R06, R07, R08, R09, R11, R12, R13, R14, N01, N02, N03, N05,
N07, N09, N10, N11, N13, N14, N18, N19, N22, N25.

Besonders bemerkenswert:
- **N14 CLOSED** — gegen die installierte `weaviate-client 4.22.0` verifiziert;
  Duplikat-Erkennung trifft die echte Exception-Form, ambivalente Faelle werden
  per Existenz-Probe entschieden.
- **R03 CLOSED** — die sechs `connect_to_custom`-Argumente passen zur echten
  4.22.0-Signatur.
- **N18 CLOSED** — Tokenisierung/Searchability liegen im Schema-SSOT.
- **R06 CLOSED** — keine Parser-Regression; `concept_ingester` bleibt Projektion
  ueber `discover_concept_files()`.

## Noch offen (11)

N04, N06, N08, N12, N15, N16, N17, N21, N24, R04, R10 — jeweils praeziser
diagnostiziert in den neuen Findings.

## Neue Findings (7 P0)

**N26 `composition_project.py:169`** — Story-Split umgeht die autoritative
Projekt-Identitaet: beide Export-Pfade geben `project_key` direkt als
`project_id` weiter. Bei `project_key=acme`, `project_prefix=AC` landen
Split-Chunks unter `acme` und sind fuer den AC-gebundenen MCP-Server unsichtbar
(D2-Verstoss).

**N27 `sync.py:493`** — Lease-Takeover fenct Stale-Writes nicht: der erste Fence
liegt *nach* dem Upsert, das Vanished-Delete wird erst *nach* dem Loeschen
gefenct. Writer A pausiert > 900 s → B uebernimmt mit epoch+1 und schliesst ab →
A schreibt danach noch stale Chunks. D3 kennt keine Zeitausnahme.

**N28 `engine.py:202`** — Receipts bleiben umordbar und replaybar: die Sequence
wird *vor* dem Receipt-Upsert reserviert und bindet nur project_id/sequence. A
reserviert 1 und stockt, B reserviert 2 und publiziert, A publiziert zuletzt —
B gewinnt Freshness. Ein altes gueltiges Receipt kann den stabilen Record
ueberschreiben und passiert die Digest-Pruefung (D1-Verstoss).

**N29 `sync.py:557`** — Leere Matrix-Eintraege umgehen das Pre-Mutation-Gate:
`objects_by_source={"concept/a.md": []}` validiert ueber null Objekte,
`source_type=""`, danach wird geclaimt, die persistierte Generation geloescht,
eine Sequence reserviert und ein malformtes Receipt geschrieben — erst dann
lehnt `sealed.verify()` ab.

**N30 `weaviate_adapter.py:955`** — Named-Vector-Drift-Check zielt auf das
falsche Client-Modell: in 4.22.0 liegen `vectorizeClassName`/`poolingStrategy`
in `_NamedVectorizerConfig.model`, der Code sucht `inner.vectorize_collection_name`
(existiert nicht). Der Test fabriziert ein `_Inner` mit genau diesem
nicht-existenten Attribut.

**N31 `story_md_export.py:336`** — Pfad-Ablehnung ist nicht zero-write und nicht
projekt-contained: `story.md` wird geschrieben, *bevor*
`canonical_story_source_file` laeuft; der Helper akzeptiert jeden absoluten Pfad
mit Elternverzeichnis `stories` und kennt keinen `project_root`; ein explizit
uebergebenes `source_file` umgeht ihn komplett. Der Test asserted nur „kein
Index-Call", nicht die Abwesenheit der Datei.

**N32 `ingest/adapter.py:217`** — Slug-Verzeichnisse ergeben die falsche
Story-Identitaet: `research_story_id` gibt `parts[1]` verbatim zurueck, also
`AG3-174-vectordb-retrieval-engine` statt `AG3-174` — und ein korrektes
Frontmatter `story_id: AG3-174` wird als Widerspruch abgelehnt. Tests nutzen nur
suffixfreie IDs.

## P2

- **P2-1** `test_weaviate_transport.py:760` — die N14-Library-Routing-Assertion
  prueft Docstring-Text statt Verhalten; die konstruierten Exception-Tests
  tragen die eigentliche Deckung.
- **P2-2** `report.md:194` — Rest-Korpus-Kategorien falsch beschrieben.

## Adjudikation der drei offenen Punkte

**Q1 (Authority-Scope, N23/R10):** Die Trennung von `module` und Authority-Scope
ist ehrlich und sicherer als die fruehere Konflation; Rule-3-Detail aus dem
Query-Text ist eine akzeptable, deterministische Interpretation. **Aber:**
`query_authority_scope` bleibt in Produktion leer → Regeln 1 und 2 fehlen im
Verhalten, **AC5 („alle fuenf Regeln") ist unerfuellt bis zur Ratifizierung.**
`report.md` darf nicht gleichzeitig „implemented" und „alle Findings
geschlossen" behaupten — die Story/AC ist als *pending* zu markieren.

**Q2 (Korpus, N20):** Die **Parser-Grenze ist korrekt** — modellierte Felder
bleiben strikt, Tippfehler in Pflichtfeldern scheitern, explizites YAML-null
wird nur fuer dokumentierte Optionals normalisiert, und CLI/MCP raten das
Korpus-Verzeichnis nicht mehr. Die Reste sind Korpus-/Profil-Fragen, **keine
Parser-Bugs**; ohne Konzept-Ratifizierung darf keine Parser-Lockerung dazukommen.
Korrigierte Taxonomie der 272 Restfehler (Erst-Fehler pro Datei!): 253×
`doc_kind`, 10× bare-string `defers_to`, **5×** fehlendes `concept_id`, 1×
falsch geformtes `supersedes`, 3× ohne Frontmatter (davon nur **eine** README).

**N15 (Lease):** Ein Operations-Lease ist konzeptionell etwas anderes als
Story-/Session-Ownership — **aber das macht diese Implementierung nicht sicher.**
D3 kennt keine Ablauf-Ausnahme, und Weaviate-Mutationen sind nicht atomar per
Epoch gefenct. **Erforderlich ist ein expliziter administrativer Reclaim**
(nachdem der alte Writer als tot festgestellt wurde), es sei denn das
Persistenzmodell erhaelt echtes Mutation-Time-Fencing.

## Scope / D-Decisions

Kein Leakage (keine Dateien von AG3-172/173/175/176, keine Konzeptdateien
geaendert). D1 nicht eingehalten (Receipt-Reorder/Replay, N28). D2 auf MCP- und
Export/Repair-Pfaden eingehalten, aber durch Story-Split-Composition verletzt
(N26). D3 verletzt durch automatischen Lease-Takeover und unvollstaendiges
Fencing (N27). D4/D6 gehoeren AG3-175/176. D5 eingehalten.
