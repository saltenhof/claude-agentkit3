# AG3-174 — VektorDB-Retrieval-Engine (harnessuebergreifend)

- **Typ:** implementation
- **Groesse:** L
- **depends_on:** [] — die tragende Infrastruktur (Weaviate-Adapter,
  Story-Indizierung, Preflight-Baustein) existiert; die Konzeptraender sind
  vorab verankert.
- **unblocks:** [AG3-175, AG3-176]
- **Quell-Konzept:** FK-13 (`13_retrieval_vektordb_wissenszugriff.md`,
  `status: active`) — §13.2 (Stack + Tokenizer-Asset), §13.3 (Datenmodell,
  Datenquellen, Chunking), §13.4 (MCP-Server, Tools, Suchmodi), §13.9
  (ConceptContext: Properties, Chunking, `concept_validate`, Build-Artefakte,
  `concept_sync`, Authority-Ranking, Archiv, `.conceptignore`) mit dem in
  §13.9.9 verankerten **Bounded-Window** statt Atomizitaet · FK-43
  (Bundle-Assets) · FK-21 §21.4.3
- **Herkunft:** PO-Neuschnitt 2026-07-21; Konzeptraender verankert in
  `concept/_meta/decisions/2026-07-21-vectordb-edge-sharpening.md`. Alter
  Schnitt und Reviewkette in `cut-history/`.

## Kontext / Problem

AK3 soll Zielprojekten semantische Suche ueber Stories UND Konzepte
mitliefern (FK-13, Pflichtinfrastruktur). Vorhanden und getestet sind der
Weaviate-Transport-Adapter, die Story-Indizierung als Transportprototyp und
der Preflight-Baustein. Es fehlt die eigentliche Engine: ein vollstaendiges
Schema, ein produktiver Ingest mit deterministischer Identitaet, der
Concept-Corpus-Lifecycle und der MCP-Server, der die Faehigkeit als Werkzeug
exponiert.

Die frueher offenen Konzeptraender sind **vorab entschieden und verankert**
(Decision Record 2026-07-21). Diese Story implementiert die verankerte Norm;
sie trifft keine Konzeptentscheidung. Bei Konflikt zwischen Story und Konzept:
**stoppen und melden.**

## Scope

### In Scope

1. **Packaging.** `mcp` und `weaviate-client` als echte
   `[project.dependencies]` (FK-13 §13.2); `weaviate-client>=4.9,<5.0` als
   FK-13-konformer Runtime-Pin statt des heutigen optionalen `>=4.0`-Extras
   (Review 174-P1-3). Tokenizer als **versioniertes Package-Asset** mit
   gebundenem SHA-256-Digest und gepinnter Revision — normativ
   festgeschrieben: Modell/Tokenizer `sentence-transformers/all-MiniLM-L6-v2`,
   gepinnte Revision `e4ce9877abf3edfe10b0d82785e83bdcb973e22e`,
   Runtime-Bibliothek `tokenizers==0.21.0`, Asset-Liste (`tokenizer.json` samt
   Vokabular), separate Digest-Datei, Lizenznachweis Apache-2.0 (FK-13 §13.2
   verankert; Werte aus dem alten Schnitt uebernommen, keine Neuentscheidung).
   Fail-closed bei fehlendem/abweichendem Asset, keine Laufzeit-Netzabholung,
   kein zeichenbasierter Ersatz. Clean-Venv-Test ausserhalb des
   Repo-Importpfads.
2. **Minimale Projektbindung.** Typisiertes Modell: autoritativer
   `project_root`, Containment-Pruefung fuer alle Schreibpfade, projektlokales
   `cwd`, `project_id` nach bestehendem FK-13-/Projektconfig-Vertrag,
   Endpunkt als Konfigurationswert. **Keine** globale Identitaetsordnung,
   keine Registry-CAS.
3. **Autoritative MCP-Runtime-Bindung als SSOT** (Review 174-P0-4). Ein
   einziger typisierter `McpServerSpec`/`RuntimeBinding` ist Quelle der
   Wahrheit fuer den gestarteten Prozess und wird von AG3-175 unveraendert
   konsumiert (dort referenziert): `PROJECT_ID` sowie HTTP-/gRPC-Endpunkt
   kommen fuer den MCP-Prozess **ausschliesslich** aus dem registrierten
   `env`; `cwd` ist Arbeits-/Containment-Grenze, **keine** zweite
   Konfigurationsquelle (kein localhost-/Default-Fallback). Fehlende, leere
   oder falsch typisierte Bindungswerte stoppen den Server fail-closed. Ein
   ausgelassener Tool-Parameter `project_id` wird auf die gebundene Projekt-ID
   gesetzt; ein abweichend uebergebenes `project_id` wird **abgelehnt**, nicht
   als Cross-Project-Abfrage ausgefuehrt — das gilt auch fuer
   `story_list_sources` (FK-13 §13.4.1/§13.9.5).
4. **Generischer Ingest-/Corpus-Kern als SSOT unter `src/agentkit/concepts/`**
   (Review 174-P1-4). Discovery, Frontmatter, Heading-Chunking, Hashing,
   Excludes liegen einmal in einem **transportfreien Domain-Paket**
   `src/agentkit/concepts/`; `discover_concept_files()` im Parser-Modul
   `agentkit/concepts/parser.py` ist der eine Owner fuer Validation, Build,
   Graph und Sync (FK-13 §13.9.13). Der Kern ist ohne Weaviate nutzbar (Lint/
   Validate). `backend/vectordb/ingest/` und `tools/concept_ingester` werden
   **Adapter/Konsumenten** darauf; **kein zweiter** Discovery-/Parser-Pfad.
   Parametrisierbar ueber Profile (`fk13_concept`/`fk13_story`/`ak3_tool`;
   Token-Einheit, an das Embedding-Modell gebundener Tokenizer, Overflow =
   deterministische Teilung unterhalb der Heading-Ebene).
5. **`StoryContext`-Schema vollstaendig** (Story- UND Concept-Properties in
   einem Wurf, eine Collection, `project_id` als Diskriminator; FK-13 §13.3.1,
   §13.9.3), durch einen benannten Owner idempotent erzeugt.
6. **Ingest produktiv mit erzwungener Source-/Producer-/Delete-Closure**
   (Review 174-P0-1). Alle Quellen nach der verankerten
   Source-Type/Producer-Zuordnung (FK-13 §13.3.2 korrigiert, §13.7.2, §13.9.5),
   als abnahmeverbindliche Closure:
   - `story.md` → `source_type=story` → ausschliesslich `story_sync`;
   - `stories/<story-ordner>/research/**/*.md` → `research` → ausschliesslich
     `story_sync` (positive Erkennung ueber kanonischen Pfad, kein
     Negativfilter);
   - konfigurierte Konzept-/Architekturquellen → `concept` → ausschliesslich
     `concept_sync`;
   - `review*.md`, Closure-/Audit-Artefakte und sonstiges unbekanntes Markdown
     sind **negative Research-Faelle** (nicht ingestiert);
   - `story_list_sources` weist nur diese zugelassenen Producer aus;
   - `full_reindex` loescht jeweils **nur** die vom aufgerufenen Tool
     besessenen Source-Types innerhalb des gebundenen `project_id` — ein
     `story_sync(full_reindex=true)` beruehrt keine Concept-Chunks und
     umgekehrt.
   Vollstaendige Felder inkl. `content`/`project_id`/`content_hash`,
   deterministische Chunk-Identitaet, projektbegrenztes Insert/Replace/Delete,
   idempotenter Re-Sync.
7. **Concept-Corpus-Lifecycle** (FK-13 §13.9): `concept_validate` als harte
   Sync-Vorbedingung mit vollstaendigem Finding-/Exit-Code-Katalog (§13.9.7);
   `INDEX.yaml`, `concept_graph.json`, gemeinsame `corpus_revision`
   (§13.9.8); `ConceptGraphResolver` fuers Authority-Ranking (§13.9.11);
   `.conceptignore` und Archiv-Handling; konfiguriertes `concepts_dir` ist
   massgeblich.
8. **Drei-Ringe-CLI-/Service-Oberflaeche auf demselben Discovery-SSOT**
   (Review 174-P0-2). AG3-174 liefert die produktiven CLI-/Service-Operationen
   auf dem Parser/Discovery-Kern aus Punkt 4:
   - Ring 1: `concept lint --changed`/`concept lint <file>`,
     `concept doctor --summary`;
   - Ring 2: `concept validate --staged` gegen den Candidate-Corpus (staged
     plus unveraenderte Dateien), `concept validate --corpus --strict`
     (Warnings eskalieren);
   - `concept build` (Build-Artefakte) und die manuelle CLI `concept sync`.
   Alle auf demselben Parser/Discovery-SSOT; keine zweite Discovery-Menge. Die
   **tatsaechlich feuernde CP10b-/Pre-Commit-Installation** und der Post-Commit-
   Pfad (`concept build` VOR `concept sync`) gehoeren zu **AG3-176**; hier nur
   die produktiven Operationen, die dort verdrahtet werden.
9. **`concept_sync` mit generationskonsistentem Replace** nach dem
   **verankerten Bounded-Window** (FK-13 §13.9.9): neue Generation schreiben,
   dann alte entfernen; kurzes Umschaltfenster, in dem Leser einen
   Uebergangsstand sehen koennen; Abschluss ueber `corpus_revision`.
   **Kein CAS, kein Generations-Zeiger** — die frueher geforderte Mechanik
   entfaellt normativ.
10. **MCP-Server mit den fuenf FK-13-Tools** (`story_search`,
    `story_list_sources`, `story_sync`, `concept_search`, `concept_sync`),
    drei wirksamen Suchmodi (§13.4.2, `search_mode` nicht ignorieren),
    vollstaendige Ergebnis-/Fehler-Envelopes (Sync-Zaehler, `corpus_revision`,
    kein stiller Partial-Failure), `concept_search` filtert per Default auf
    `active` (§13.9.10) und wendet das Authority-Ranking an. Nutzt den
    bestehenden Adapter, keine zweite Transportschicht. VektorDB-Ausfall
    fail-closed nach §13.8.
11. **Strikte externe Eingabegrenzen, fail-closed** (Review 174-P0-3;
    Nachsicht-Pruefachse). Jede externe Eingabe wird strikt validiert;
    ungueltiges wird **fail-closed abgelehnt statt repariert** — keine geerbte
    Bibliotheks-Nachsicht (`errors="replace"`, Pydantic-Koerzierung,
    `.get(..., default)`, YAML-Last-wins). Betroffen: YAML-Frontmatter,
    MCP-Toolargumente, Tokenizer-Asset und Weaviate-Antworten. Die heutigen
    Reparatur-Defaults (`weaviate_adapter.py:98-123` Leerstring-Ersatz,
    `:313` ignoriertes `search_mode`, `:329` Score-`0.0`) werden entfernt.
    Details und Negativmatrizen als eigenes AC (siehe AC 10).

### Out of Scope (mit Owner)

- Projektlokale Harness-Registrierung (`.mcp.json` / `.codex/config.toml`) —
  **AG3-175**.
- Installer-Integration: Endpunkt-Preflight-Verdrahtung, CP10a-Erstindex,
  laufende Producer, Pflichtaktivierung, Skill-Auslieferung — **AG3-176**.
- E2E-Retrieval-Qualitaetsnachweis gegen echte Weaviate — **nachgelagert
  mit dem PO**, nicht Story-Inhalt.
- ARE-Server (AG3-173), Postgres-Race (AG3-172).

## Betroffene Dateien

| Datei | Aenderungsart |
|---|---|
| `pyproject.toml` | Dependencies (`weaviate-client>=4.9,<5.0`) + Tokenizer-Asset/Digest/Lizenz |
| `src/agentkit/concepts/parser.py` (+ `discovery`, `frontmatter`, `chunking`, `hashing`) | neu — **transportfreier** SSOT-Kern; `discover_concept_files()` als einziger Owner (FK-13 §13.9.13) |
| `src/agentkit/concepts/cli.py` (o. Aequivalent) | neu — `concept lint/doctor/validate/build/sync` auf demselben Discovery-SSOT |
| `src/agentkit/backend/vectordb/project_binding.py` | neu |
| `src/agentkit/backend/vectordb/runtime_binding.py` (`McpServerSpec`/`RuntimeBinding`) | neu — autoritative Runtime-Bindung, von AG3-175 konsumiert |
| `src/agentkit/backend/vectordb/schema.py` | neu — vollstaendiges Schema, idempotent |
| `src/agentkit/backend/vectordb/ingest/` | neu — **Adapter** auf den `concepts/`-Kern (kein zweiter Discovery-Pfad) |
| `src/agentkit/backend/vectordb/concept_corpus/` | neu — validate, build, graph, resolver, freshness, generationskonsistenter Replace |
| `src/agentkit/backend/vectordb/mcp_server.py` + `tools/`, `contracts.py` | neu — Server, fuenf Tools, Envelopes, strikte Argument-Validierung |
| `src/agentkit/integration_clients/vectordb/weaviate_adapter.py` | erweitern — Concept-Properties, deterministische UUID, Projektfilter, **Entfall der Reparatur-Defaults** (Zeilen 98-123/313/329); bleibt duenn |
| `src/agentkit/backend/story_creation/story_md_export.py`, `weaviate_index.py` | aendern — vollstaendige Felder, deterministische IDs |
| `tools/concept_ingester/` | zu duennem Adapter auf den `concepts/`-SSOT-Kern |
| `tests/unit/`, `tests/integration/`, `tests/contract/` | neu/erweitern |

## Akzeptanzkriterien

1. Clean-Venv-Test (ausserhalb Repo-Importpfad) belegt Installierbarkeit;
   Tokenizer laedt fail-closed aus dem Asset (Digestpruefung vor dem Parsen),
   ohne Netz; gepinnte Revision/Bibliothek/Asset-Liste/Lizenz sind belegt.
2. `StoryContext`-Schema traegt alle FK-13-§13.3.1/§13.9.3-Properties;
   Contract-Test bindet die Felddefinition ans Konzept; idempotente Erzeugung.
3. Eine exportierte Story ist ueber den echten Adapter mit vollstaendigen
   Feldern (inkl. `content`, `project_id`) auffindbar; zweiter Sync erzeugt
   genau einen Datensatz. **Source-/Producer-/Delete-Closure** (Review
   174-P0-1): ein Sequenztest fuehrt `story_sync(full_reindex=true)` und
   `concept_sync(full_reindex=true)` in **beiden Reihenfolgen** aus und findet
   danach beide Quellklassen unveraendert vor; Delete, verschwundene
   Quelldatei, inkrementeller und idempotenter Re-Sync sind je Source-Type
   geprueft; `story_list_sources` weist nur die zugelassenen Producer aus; ein
   `review*.md`/Closure-Artefakt landet als negativer Research-Fall nicht im
   Index.
4. Jede Lese-/Schreib-/Loeschoperation traegt den Projektfilter; Zwei-Projekt-
   Test beweist, dass keine Operation projektfremde Daten beruehrt.
5. `concept_validate` blockiert einen Sync bei ungueltigem Korpus hart (kein
   Teil-Sync); `INDEX.yaml`/`concept_graph.json`/`corpus_revision` sind
   konsistent. **Tabellengetriebene Contract-Tests** (Review 174-P1-2) decken
   jeden Error-/Warning-Code und Exit 0/1/2/3, alle fuenf Authority-Ranking-
   Regeln mit deterministischem Tie-Break, Core/Appendix/Archiv-Metadaten,
   alle vier `.conceptignore`-Glob-Grenzfaelle (`research/**`, `research/**/*`,
   `*.md`, `drafts/*.md` — nicht ueber ein blosses `Path.match`) sowie
   Gleichheit der Discovery-Menge in Validate, Build und Sync ab; zyklische/
   gebrochene Authority-Kanten schlagen fehl; `E-CHUNK-001` bleibt blockierend,
   auch wenn der generische Chunker den Inhalt deterministisch teilen koennte.
6. **`concept_sync` — Bounded-Window-Vertrag** (Review 174-P1-1). Ein Test
   belegt die Reihenfolge: (1) neue Sollgeneration vollstaendig schreiben und
   Sollmenge validieren; (2) alte/fremde Chunks derselben Source erst danach
   loeschen; (3) erst nach erfolgreichem Delete ein **digestgebundenes
   Sync-Receipt mit `corpus_revision`** publizieren; (4) Crash davor laesst den
   letzten Abschlussmarker unveraendert, ein Retry erkennt und bereinigt
   vollstaendige/partielle Reste deterministisch; (5) parallele Syncs desselben
   `(project_id, source_file)` werden durch einen benannten Single-Writer-
   Mechanismus serialisiert oder fail-closed abgewiesen. **Explizit**: ein
   sofortiger Single-Generation-Zustand nach Prozessabsturz ist **nicht**
   garantiert; Leser duerfen im normierten Fenster beide Generationen sehen.
   Kein CAS, kein Generations-Zeiger.
7. Der MCP-Server liefert per `tools/list` genau die fuenf Tools; die drei
   Suchmodi wirken unterschiedlich; `concept_search` liefert nur
   Konzept-Chunks, Default `active`, Authority-Ranking; Ergebnis-/Fehler-
   Envelopes sind vollstaendig; Weaviate-Ausfall ist fail-closed.
8. Ein Contract-Test bindet Toolnamen, Pflichtparameter und Rueckgabefelder an
   FK-13 §13.4.1/§13.9.5. Fuer `story_list_sources` ist die **minimale Shape**
   abnahmeverbindlich (Review 174-P1-3): mindestens gebundenes `project_id`,
   `source_type`, Producer/Tool, Source-/Chunk-Zaehler und letzte erfolgreiche
   Revision/Freshness; **keine** fremden Projekte.
9. Der SSOT-Discovery-Kern liegt in `src/agentkit/concepts/` und ist die
   einzige Implementierung (Review 174-P1-4); `backend/vectordb/ingest` und
   `tools/concept_ingester` sind Adapter darauf; ein Drift-Test sichert die
   Profil-Verhaltensgleichheit gegen `tools/concept_ingester`; ein Test belegt,
   dass Lint/Validate ohne Weaviate lauffaehig sind.
10. **Strikte externe Grenzen** (Review 174-P0-3; Nachsicht-Pruefachse) — je
    Grenze eine echte Negativmatrix, jeweils mit Beweis, dass **kein**
    Teil-Write, **keine** Freshness-Aenderung und **kein** Success-Envelope
    entsteht (Fakes nur am externen Adapterport erlaubt):
    - Frontmatter: ungueltiges UTF-8, doppelte Namen auf jeder Ebene,
      unbekannte YAML-Tags, nicht endliche Zahlen, Lone Surrogates, falsche
      Container-/Skalartypen, unzulaessige Enums und uebermaessige Tiefe →
      benannter Validierungsfehler; keine Typkoerzierung;
    - MCP-Eingaben: strikte Enums/Booleans/Integer, positive begrenzte
      `limit`-Werte, keine bool-as-int-Koerzierung, kein fremdes `project_id`;
    - Weaviate-Antworten: fehlende/falsch typisierte Pflichtfelder,
      NaN/Infinity-Score, fehlerhafte Pagination, unvollstaendige Write-/
      Delete-Zaehler sind harte, benannte Fehler und **niemals** leeres
      Ergebnis oder Erfolg;
    - Tokenizer: Digestpruefung vor dem Parsen; beschaedigtes, tief
      verschachteltes oder semantisch inkompatibles Asset ist harter Fehler
      ohne Netz-/Cache-Fallback.
11. **Autoritative MCP-Runtime-Bindung** (Review 174-P0-4). Der gestartete
    Subprozess wird mit einem **Nicht-Default-Endpunkt** aus dem registrierten
    `env` geprobt und arbeitet dagegen (kein localhost-/Default-Fallback);
    fehlende/leere/falsch typisierte Bindungswerte stoppen fail-closed; ein
    ausgelassenes `project_id` wird auf die gebundene ID gesetzt; ein
    **Fremdprojekt-Override** wird abgelehnt statt cross-project ausgefuehrt —
    auch fuer `story_list_sources`.
12. **Drei-Ringe-CLI-/Service-Operationen ausgefuehrt** (Review 174-P0-2). Die
    Operationen `lint`, `doctor`, `validate --staged`, `validate --corpus
    --strict`, `build` und `sync` existieren produktiv auf demselben Parser/
    Discovery-SSOT; ein Test belegt: `validate --staged` blockiert ueber den
    Candidate-Corpus (staged plus unveraenderte Dateien) einen **neu
    erzeugten Cross-File-Fehler**, und `--strict` eskaliert Warnings. (Die
    tatsaechlich feuernde Pre-Commit-/Post-Commit-Installation ist AG3-176.)

## Definition of Done

- Alle Akzeptanzkriterien erfuellt; `pytest` gruen, Coverage haelt 85 %;
  `mypy src`, `ruff check src tests` sauber; Konzept-Gates gruen, falls
  Konzeptdateien beruehrt.
- Produktionscode nur unter `src/agentkit/`; `integration_clients/` bleibt
  duenner Adapter; kein God-File; keine Zirkel.
- Keine Mocks fuer Ingest-/Adapterpfade (echte Dateien, echter Adapter).
- Story-Bericht dokumentiert die SSOT-Adapter-Entscheidung.
- **Verbindlicher interner Implementierungsplan vor `in_progress`** (Review
  174-P2-1). Groesse **L** bleibt, ist aber nur als Backlog-Klammer
  vertretbar: Vor dem Start liegt ein Plan mit den Teilvertikalen (Packaging/
  Tokenizer, Projekt-/Runtime-Bindung, Ingest-Kern `concepts/`, StoryContext-
  Schema, drei Ingest-Profile, Corpus-Lifecycle/Validator/Build/Graph,
  Drei-Ringe-CLI, Bounded-Window-Sync, Authority-Resolver, MCP-Oberflaeche)
  vor, je Teilvertikale mit eigenem Modul- und Testbudget und einem
  **Integrationsgate vor der MCP-Schicht**. Kein God-File, keine bis zum Ende
  aufgeschobene Integration; `L` ist keine Planungsannahme fuer einen kurzen
  Lauf.
- **Landevoraussetzung AG3-172 als geprueftes Gate** (uebergreifende
  Kanten-Auflage): Der Merge dieser Story ist an das vorherige Landen von
  AG3-172 gebunden; die Vorbedingung ist als vom Workflow tatsaechlich
  geprueftes Completion-/Merge-Gate zu fuehren, nicht nur als Kommentar.
  (`depends_on` bleibt unveraendert; Entwicklung darf parallel beginnen,
  landen erst nach AG3-172.)

## Uebergreifende Folge-Auflage

- **FK-13 §13.6 — semantische Ergaenzung der P6-Kontextselektion** (Review,
  uebergreifender Teil, P1-Nachweisauflage): Fuer die semantische P6-
  Kontextselektion ist weder im Bestand noch in AG3-174..176 ein produktiver
  Consumer erkennbar. Das blockiert den MCP-Kern **nicht**, darf aber **nicht
  still als „durch MCP vorhanden" abgehakt** werden. Auflage: entweder einen
  bestehenden Owner samt Contract-Test referenzieren **oder** einen expliziten
  Folge-Owner festhalten. Fuer diese Story gilt der zweite Weg — der
  Consumer-Nachweis wird als **benannter Folge-Owner** (nachgelagerte Story,
  P6-Kontextselektion) getragen und im Story-Bericht namentlich als offene
  Folge-Auflage vermerkt.

## Konzept-Referenzen

FK-13 §13.2/§13.3/§13.4/§13.6/§13.7/§13.8/§13.9 (inkl. §13.9.7/§13.9.9-13,
§13.9.13 Parser-Owner) · FK-43 · FK-21 §21.4.3 · FK-50 CP 10b (feuernde
Installation in AG3-176) · Decision Record `2026-07-21-vectordb-edge-sharpening.md`

## Guardrail-Referenzen

FAIL-CLOSED · SINGLE SOURCE OF TRUTH (Ingest-Kern) · FIX THE MODEL ·
MOCKS NUR IM AUSNAHMEFALL · ZERO DEBT · ARCH-55
