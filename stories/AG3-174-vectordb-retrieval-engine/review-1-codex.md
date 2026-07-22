# Review 1 (Codex) — AG3-174 VektorDB-Retrieval-Engine

## Review-Basis

Geprüft wurden die Story samt Status, Implementierungsplan und Bericht, FK-13,
das Decision Record `2026-07-21-vectordb-edge-sharpening.md`,
`PROJECT_STRUCTURE.md`, die Architektur-/Test-Guardrails, der vollständige
gelieferte Working-Tree-Code sowie die einschlägigen Unit-, Integration- und
Contract-Tests. Die gemeldeten grünen Gates wurden nicht als
Korrektheitsnachweis übernommen.

Zusätzliche direkte Reproduktionen:

- `agentkit-concept --project-root . validate --corpus` liefert auf dem echten
  AK3-Corpus Exit 2 und unter anderem `E-SCHEMA-003` für jedes
  `doc_kind: decision-record` sowie `E-SCHEMA-002` für zahlreiche
  Formal-Spec-Dateien.
- Ein `story.md` mit doppeltem `story_id` und numerischem `title` wird als ein
  Chunk mit dem letzten `story_id` und zu String konvertiertem Titel ingestiert.
- Der vom MCP-Pfad verwendete `WeaviateStoryAdapter.search()` akzeptiert den
  vollständig unbrauchbaren Hit `{"score": 0.5}` unverändert.
- Ein Store, der für den neuen Concept-Bestand `written=0` zurückgibt, führt
  dennoch zum Löschen des Altbestands und zur Publikation eines Success-Receipts
  (`written=0, deleted=1, rows_left=0`).
- FastMCP 1.27.2/Pydantic wandelt an der echten Funktionsgrenze
  `full_reindex=1` in `True` und `limit=true` in `1` um und ignoriert unbekannte
  Argumente, bevor die handgeschriebenen Validatoren sie sehen.

## Findings

### AG3-174-R01 — BLOCKER — Der produktive Validator kann den echten AK3-Corpus nicht validieren

**Ort:** `src/agentkit/backend/vectordb/project_binding.py:108`,
`src/agentkit/backend/vectordb/project_binding.py:154`,
`src/agentkit/concepts/discovery.py:87`,
`src/agentkit/concepts/frontmatter.py:24`,
`concept/_meta/decisions/2026-07-21-vectordb-edge-sharpening.md:7`

**Fakten-Beleg:** Ohne expliziten Override wählt `_default_concepts_dir()` im
AK3-Repo das gesamte Verzeichnis `concept/`. Discovery nimmt darunter jedes
`*.md` per `rglob`, während `ALLOWED_DOC_KIND` ausschließlich `core` und
`appendix` akzeptiert. Der gleichzeitig als Primärquelle dieser Story
angegebene Decision Record trägt aber `doc_kind: decision-record`; weitere
autoritative Dokumente tragen `policy`, `methodology` oder Formal-Spec-Metadaten
ohne `concept_id`. Der reale CLI-Lauf endet deshalb mit Exit 2, bevor irgendein
Sync möglich ist.

**Normverletzung:** AC 5, 7 und 12 verlangen einen produktiven Validator,
Build und Sync für den konfigurierten Corpus. Die Story verbietet ausdrücklich,
einen Konzeptkonflikt selbst zu entscheiden. Hier passen FK-13s enge
Frontmatter-Spezifikation und der reale autoritative Corpus nicht zusammen; die
Implementierung hat weder gestoppt noch den Konflikt gemeldet, sondern nur mit
Toy-Corpora getestet.

**Fix:** Zuerst den Normkonflikt mit dem Auftraggeber klären. Danach den
autoritativen Corpus-Scope aus `ProjectConfig.concepts_dir` laden und entweder
die zulässigen Dokumentklassen normativ erweitern oder eine vollständige,
autoritative `.conceptignore`-/Quellenregel definieren. Anschließend muss
Validate/Build/Sync auf dem realen AK3-Corpus grün nachgewiesen werden.

### AG3-174-R02 — BLOCKER — Der geforderte Discovery-/Parser-SSOT existiert nicht

**Ort:** `tools/concept_ingester/discovery.py:349`,
`tools/concept_ingester/discovery.py:378`,
`tools/concept_ingester/discovery.py:406`,
`tools/concept_ingester/discovery.py:565`,
`tools/concept_ingester/ingester.py:130`,
`tools/concept_ingester/schema.py:20`,
`tests/unit/concepts/test_ssot_drift.py:42`

**Fakten-Beleg:** `tools/concept_ingester` besitzt weiterhin einen vollständigen
zweiten Pfad: eigenes `rglob`, eigenes permissives YAML-Parsing, eigenes
zeichenbasiertes Chunking, eigene UUID-/Hashlogik, eigenen direkten
Weaviate-Ingest und sogar zwei andere Collections (`Ak3ConceptChunk`,
`Ak3GlossaryTerm`). Es importiert `agentkit.concepts` nicht. Der angebliche
Drift-Test prüft lediglich, dass der Parser-Reexport dasselbe Python-Objekt wie
die neue Discovery-Funktion ist; `tools/concept_ingester` kommt im Test nicht
vor.

**Normverletzung:** Story Scope 4, AC 9 und DoD fordern ausdrücklich, dass
`tools/concept_ingester` ein dünner Adapter auf denselben Kern wird und dass es
keinen zweiten Discovery-/Parser-Pfad gibt. Der Bericht versucht diese klare
Auflage nachträglich durch die neue Kategorie „AK3-internes Rich-Discovery“
umzudeuten. Das ist eine nicht autorisierte Architektur-/Konzeptentscheidung
und ein SSOT-Bruch.

**Fix:** Discovery, Frontmatter, Chunking und Identität aus
`tools/concept_ingester` entfernen. Erforderliche Glossar-/Projection-Funktionen
als explizite Konsumenten der einen Discovery-Menge modellieren. Der Drift-Test
muss beide realen Entry-Points auf demselben Corpus ausführen und identische
Dateimenge sowie profilkonformes Verhalten beweisen. Die zusätzliche
Transport-/Collection-Wahrheit ist zu entfernen oder separat normativ zu
beauftragen.

### AG3-174-R03 — BLOCKER — `memory_store.py` ist ein produktiv verdrahteter Fake und eine zweite Transportschicht

**Ort:** `src/agentkit/backend/vectordb/memory_store.py:1`,
`src/agentkit/backend/vectordb/memory_store.py:29`,
`src/agentkit/backend/vectordb/memory_store.py:206`,
`src/agentkit/concepts/cli.py:28`,
`src/agentkit/concepts/cli.py:191`

**Fakten-Beleg:** `MemoryVectorStore` implementiert Speicherung, Filterung,
Delete und sogar eigene Keyword-/Pseudo-Vector-Suche. Die produktive
`agentkit-concept sync`-CLI importiert ihn und setzt bei fehlendem `--memory`
Zeile 195–198 trotzdem `memory=True`; jeder manuelle Sync schreibt daher in
einen sofort verlorenen In-Process-Store, publiziert aber Receipt und Erfolg.

**Normverletzung:** Scope 10 verlangt Nutzung des bestehenden Adapters und
„keine zweite Transportschicht“. Die MOCKS-Regel und AC 10 erlauben Fakes nur am
externen Adapterport für Tests. Ein Test-Fake unter `src/` wäre bereits
fragwürdig; als stiller produktiver Default ist er eindeutig unzulässig und
erzeugt einen falschen Erfolgszustand.

**Fix:** Memory-Implementierung nach `tests/` verschieben. Die produktive CLI
muss den echten Weaviate-Adapter ausschließlich aus der autoritativen
Runtime-/Projektbindung aufbauen und bei fehlender Bindung oder Nichterreichbarkeit
hart scheitern. Kein produktiver `--memory`-Pfad und kein Success-Receipt ohne
persistenten Write.

### AG3-174-R04 — BLOCKER — Bounded-Window löscht nach unvollständigem Write und publiziert trotzdem Erfolg

**Ort:** `src/agentkit/backend/vectordb/ingest/engine.py:162`,
`src/agentkit/backend/vectordb/ingest/engine.py:174`,
`src/agentkit/backend/vectordb/concept_corpus/sync.py:85`,
`src/agentkit/backend/vectordb/concept_corpus/sync.py:94`

**Fakten-Beleg:** Nach `upsert()` wird weder geprüft, dass `written ==
len(objects)`, noch wird die neue Sollgeneration aus dem Store gelesen und auf
UUID-/Hash-/Projekt-/Source-Vollständigkeit validiert. Unabhängig vom
Write-Zähler folgt sofort `delete_by_filter()`, danach immer das Receipt. Die
direkte Reproduktion mit `upsert() -> 0` ergab `deleted=1`, einen leeren Index
und ein vorhandenes Receipt.

**Normverletzung:** AC 6 schreibt die Reihenfolge „neue Sollgeneration
vollständig schreiben **und Sollmenge validieren** → alt löschen → Receipt“
vor. AC 10 verbietet Success/Frischeänderung nach Partial Failure. Der aktuelle
Pfad kann den letzten guten Corpus vernichten und behauptet danach erfolgreichen
Abschluss.

**Fix:** Rückgabetypen und Zähler strikt validieren, exakte Write-Anzahl
verlangen und die komplette neue Generation vor dem Delete projekt-/source-
gebunden zurücklesen und gegen die erwarteten IDs/Hashes prüfen. Jeder
Unterschied muss ohne Delete und ohne Receipt abbrechen. Auch Delete muss
`matches == successful` sowie `failed == 0` beweisen. Negativtests müssen
Partial Write, Partial Delete und unveränderten vorherigen Receipt/Bestand
nachweisen.

### AG3-174-R05 — MAJOR — Der „Single Writer“ serialisiert weder mehrere Engines noch Prozesse

**Ort:** `src/agentkit/backend/vectordb/ingest/engine.py:87`,
`src/agentkit/backend/vectordb/ingest/engine.py:92`,
`src/agentkit/backend/vectordb/ingest/engine.py:153`

**Fakten-Beleg:** Lock-Map und Guard sind Instanzfelder von `IngestEngine`.
Zwei Engine-Instanzen im selben Prozess und erst recht MCP-/CLI-Prozesse besitzen
unabhängige Locks und können dieselbe `(project_id, source)`-Umschaltung parallel
ausführen. Der Test verwendet immer genau eine Engine und testet keine
Konkurrenz.

**Normverletzung:** AC 6 fordert einen benannten Single-Writer-Mechanismus, der
parallele Syncs serialisiert oder fail-closed abweist. Ein objektlokaler Lock
erfüllt den Prozessvertrag nicht und ermöglicht gegenseitiges Löschen von
Generationen.

**Fix:** Prozessübergreifende, projekt-/source-gebundene Serialisierung mit
definiertem Ownership-/Timeout-Vertrag implementieren (z. B. projektlokaler
advisory/file lock innerhalb der Containment-Grenze oder ein autoritativer
Backend-Lock). Konkurrenztest mit zwei unabhängigen Engine-/Prozessinstanzen.

### AG3-174-R06 — BLOCKER — Die echte MCP-Grenze koerziert ungültige Argumente vor der strikten Prüfung

**Ort:** `src/agentkit/backend/vectordb/mcp_server.py:158`,
`src/agentkit/backend/vectordb/mcp_server.py:188`,
`src/agentkit/backend/vectordb/mcp_server.py:198`,
`src/agentkit/backend/vectordb/mcp/contracts.py:54`,
`tests/unit/vectordb/test_mcp_tools.py:112`

**Fakten-Beleg:** Die FastMCP-Funktionen verwenden normale `bool`-/`int`-/
`str`-Annotationen. FastMCP baut daraus ein Pydantic-Modell ohne `strict=True`
und `extra="forbid"`. Im installierten Runtime-Pfad werden `1 -> True`,
`true -> 1` koerziert und unbekannte Felder entfernt. Erst danach erreicht der
Wert `require_bool()` bzw. `require_limit()`. Die Tests rufen nur diese inneren
Helper direkt auf und umgehen genau die externe MCP-Grenze.

Zusätzlich sind `project_id` bei den beiden FastMCP-Sync-Funktionen
Pflichtparameter, obwohl AC 11 ausdrücklich verlangt, dass ein ausgelassener
Tool-Parameter auf die gebundene ID gesetzt wird.

**Normverletzung:** AC 10 verlangt strikte MCP-Enums/Booleans/Integer ohne
Pydantic-Koerzierung; AC 11 verlangt Omit-Binding. Beides ist am realen Wire-Pfad
nicht erfüllt.

**Fix:** Entweder einen Low-Level-MCP-Handler verwenden, der die rohe
Argument-Map einmalig durch eigene `ConfigDict(strict=True, extra="forbid")`-
Modelle parst, oder nachweislich strikte FastMCP-Argumentmodelle anbinden.
`project_id` muss am echten Tool optional sein. Contract-Tests müssen über
FastMCP/stdio mit rohem JSON `1`, `true`, Strings, `null`, Extras und
Fremdprojekt laufen.

### AG3-174-R07 — BLOCKER — Der MCP-Suchpfad umgeht die Hit-Härtung; Reparatur-Defaults und Partial-Delete bleiben aktiv

**Ort:** `src/agentkit/integration_clients/vectordb/weaviate_adapter.py:93`,
`src/agentkit/integration_clients/vectordb/weaviate_adapter.py:124`,
`src/agentkit/integration_clients/vectordb/weaviate_adapter.py:138`,
`src/agentkit/integration_clients/vectordb/weaviate_adapter.py:216`,
`src/agentkit/integration_clients/vectordb/weaviate_adapter.py:423`,
`src/agentkit/integration_clients/vectordb/weaviate_adapter.py:485`,
`src/agentkit/backend/vectordb/mcp/tools.py:105`

**Fakten-Beleg:** Nur die Legacy-Methode `story_search()` ruft `_coerce_hit()`
auf. Der von `KnowledgeTools` verwendete Port `WeaviateStoryAdapter.search()`
reicht rohe Hits unverändert durch. Selbst `_coerce_hit()` ersetzt weiterhin
fehlende `title`, `snippet`, `source_type`, `section_heading` und `project_id`
durch Leerstrings; `_RealWeaviateClient.search()` erfindet bei fehlendem
Snippet ebenfalls `""`. Die MCP-Projektion ergänzt weitere `.get(...,
default)`-Werte. Beim Delete wird `successful` akzeptiert, ohne `matches` oder
einen Failure-Zähler abzugleichen; ein partielles Delete gilt damit als Erfolg.

Auch `fetch()` führt beim verfügbaren Iterator keinen Server-seitigen
Projektfilter mit, sondern filtert erst lokal; der Fallback ist hart auf 10.000
Objekte begrenzt und besitzt keine Pagination-Prüfung.

**Normverletzung:** Das sind exakt die in AC 10 verbotenen geerbten
Nachsichtigkeiten: fehlende/falsch typisierte Pflichtfelder, fehlerhafte
Pagination und unvollständige Write-/Delete-Zähler müssen hart scheitern und
dürfen nie als leeres/partielles Ergebnis oder Erfolg erscheinen. AC 4 verlangt
den Projektfilter auf jeder Leseoperation, nicht erst nach ungebundenem Abruf.

**Fix:** Eine einzige strikte Response-Normalisierung direkt im von MCP und
allen Consumern verwendeten `search()`-/`fetch()`-Port erzwingen; vollständige
source-spezifische Hit-Schemas ohne Ersatzwerte. Server-seitige Filter auf jede
Page, vollständige Pagination und exakte Counter-/Failure-Invarianten. Tests
müssen den tatsächlich von MCP verwendeten Adapter-Port prüfen, nicht nur die
Legacy-Methode.

### AG3-174-R08 — MAJOR — Story-/Research-Frontmatter ist last-wins, koerzierend und bei I/O-Fehlern fail-open

**Ort:** `src/agentkit/backend/vectordb/ingest/builders.py:46`,
`src/agentkit/backend/vectordb/ingest/builders.py:50`,
`src/agentkit/backend/vectordb/ingest/builders.py:52`,
`src/agentkit/backend/vectordb/ingest/builders.py:194`

**Fakten-Beleg:** Lesefehler werden mit `continue` still übersprungen.
`_parse_story_meta()` benutzt `yaml.safe_load`, gibt bei YAML-Fehler oder
falschem Root-Typ `{}` zurück und akzeptiert Duplicate-Keys nach PyYAML
last-wins. Danach reparieren `.get(... or fallback)` und `str(...)` fehlende
oder falsch typisierte Felder. Reproduziert wurde ein Duplicate-`story_id` plus
numerischer Titel: Es entstand erfolgreich ein Chunk mit dem letzten ID-Wert
und Titel `"123"`.

**Normverletzung:** Scope/AC 10 nennt YAML-Frontmatter ausdrücklich als
strikte externe Grenze; kein Partial Write, keine Bibliotheksnachsicht, keine
Typkoerzierung und kein YAML last-wins. Bei `full_reindex` kann ein bloß
unlesbares File durch das stille Skip zusätzlich als „verschwunden“ behandelt
und aus dem Index gelöscht werden.

**Fix:** Gemeinsamen Strict-YAML-Parser auch für Story-/Research-Metadaten
verwenden bzw. ein ebenso striktes Story-Schema bereitstellen. Lesefehler,
Duplikate und falsche Typen müssen den gesamten Sync vor dem ersten Write
abbrechen. Kein Fallback auf Pfad-/Stem-Metadaten für ein vorhandenes, aber
ungültiges Frontmatter.

### AG3-174-R09 — MAJOR — Authority-Ranking wirkt im produktiven `concept_search` nicht

**Ort:** `src/agentkit/backend/vectordb/mcp_server.py:153`,
`src/agentkit/backend/vectordb/mcp/tools.py:64`,
`src/agentkit/backend/vectordb/mcp/tools.py:199`,
`src/agentkit/backend/vectordb/concept_corpus/resolver.py:50`

**Fakten-Beleg:** Der produktive Server konstruiert `KnowledgeTools` ohne Graph;
der Resolver ist daher leer. `concept_search()` ruft `rank()` außerdem ohne
`query_scopes` auf. Damit können Regel 1 (direkte Authority) und Regel 2
(Scoped Deferral) nie feuern. Der Test ruft den Resolver künstlich mit einem
handgebauten Graph und `query_scopes=["s1"]` auf, beweist aber nicht den
MCP-Consumer. Appendix-Präferenz wird nur aus dem Filter `is_appendix=true`
abgeleitet, nicht aus Interface-/Test-Detail.

**Normverletzung:** FK-13 §13.9.11 sowie AC 5/7 verlangen alle fünf Regeln im
App-Layer und ihre Anwendung durch `concept_search`. Ein isolierter Resolver,
dessen notwendige Inputs der produktive Call-Pfad nie liefert, erfüllt das
nicht.

**Fix:** Einen digest-/`corpus_revision`-gebundenen, strikt geladenen Graph in
den Server injizieren und einen normativ geklärten Weg für Query-Scopes sowie
Interface-/Test-Detail bereitstellen. Falls FK-13 hierfür nicht genügend Input
definiert, stoppen und die Konzeptlücke klären statt eine Heuristik zu
erfinden. MCP-Integrationstest muss die fünf Rankingfälle über den echten Tool-
Call nachweisen.

### AG3-174-R10 — MAJOR — `concept_path` ist nur im Descriptor vorhanden, aber weder am Tool noch im Handler implementiert

**Ort:** `src/agentkit/backend/vectordb/mcp_server.py:97`,
`src/agentkit/backend/vectordb/mcp_server.py:225`,
`src/agentkit/backend/vectordb/mcp/tools.py:233`

**Fakten-Beleg:** `list_tools()` bewirbt `concept_path`. Die echte FastMCP-
Funktion hat diesen Parameter nicht; der Handler validiert oder verwendet ihn
ebenfalls nicht und synchronisiert immer den ganzen Corpus. Es existiert kein
Test für den Parameter.

**Normverletzung:** FK-13 §13.9.5 und AC 8 binden den Toolvertrag inklusive
optionalem `concept_path`. Descriptor, Wire-Funktion und Ausführung sind
inkonsistent.

**Fix:** `concept_path` strikt projekt-contained validieren und den fachlich
definierten Single-Document-Sync inklusive Delete-/Receipt-Vertrag
implementieren, oder den Parameter erst nach einer normativen Konzeptänderung
überall entfernen. Contract-Test muss Descriptor, Wire-Schema und Verhalten
gemeinsam prüfen.

### AG3-174-R11 — MAJOR — `concept_validate` implementiert den vorgeschriebenen Finding-Katalog nicht vollständig

**Ort:** `src/agentkit/backend/vectordb/concept_corpus/validate.py:91`,
`src/agentkit/backend/vectordb/concept_corpus/validate.py:216`,
`src/agentkit/backend/vectordb/concept_corpus/validate.py:280`,
`tests/unit/vectordb/test_validate_and_authority.py:53`

**Fakten-Beleg:** Es gibt keine Implementierung für `E-AUTH-002`,
`W-CONTENT-002`, `W-CONTENT-003` und `W-SCOPE-001`. Die Tests sind nicht
tabellengetrieben und decken nur einzelne Codes ab; Exit 3 wird nicht als
Vertrag geprüft. Die Frontmatter-Negativmatrix testet nur vier der in AC 10
aufgezählten Fälle.

**Normverletzung:** AC 5 fordert ausdrücklich tabellengetriebene Tests für
**jeden** Error-/Warning-Code und Exit 0/1/2/3. Fehlende Checks bedeuten, dass
ungültige Corpuszustände als valid/sync-fähig durchgehen können.

**Fix:** Vollständigen Katalog implementieren, für zustandsvergleichende Regeln
wie `E-AUTH-002` einen expliziten Candidate-/Baseline-Vertrag verwenden und
jeden Code plus alle Exitcodes tabellengetrieben über die öffentliche
Validation-Operation testen.

### AG3-174-R12 — MAJOR — Der angeblich inkrementelle Sync reindiziert jeden Chunk bei jedem Lauf

**Ort:** `src/agentkit/backend/vectordb/ingest/engine.py:160`,
`src/agentkit/backend/vectordb/ingest/engine.py:162`,
`src/agentkit/backend/vectordb/ingest/engine.py:224`,
`tests/integration/vectordb/test_ingest_closure_and_gate.py:144`

**Fakten-Beleg:** `_sync()` erzeugt immer eine neue Generation, baut alle
Records und übergibt alle an `upsert()`. Ein Hashvergleich vor dem Write
existiert nicht; `skipped` ist fest `0`. Der „Idempotenz“-Test vergleicht nur
die Anzahl der Records nach zwei Läufen und bemerkt die erneuten Writes nicht.

**Normverletzung:** FK-13 §13.3.3/§13.9.9 und Scope 6 verlangen hashbasierte
Change-Detection; unveränderte Chunks werden ausdrücklich nicht neu indiziert.
Die Success-Zähler sind dadurch fachlich falsch.

**Fix:** Projekt-/source-gebunden vorhandene `content_hash`/Identitäten lesen,
nur neue/geänderte Chunks schreiben, unveränderte als `skipped` zählen und
verschwundene löschen. Tests müssen Adapteraufrufe und Zähler belegen, nicht
nur die Endanzahl.

### AG3-174-R13 — MAJOR — `validate --staged` validiert nicht zuverlässig den Git-Candidate-Corpus

**Ort:** `src/agentkit/concepts/cli.py:155`,
`src/agentkit/concepts/cli.py:244`,
`src/agentkit/concepts/cli.py:248`,
`src/agentkit/concepts/cli.py:254`,
`src/agentkit/concepts/cli.py:275`,
`tests/unit/vectordb/test_concept_cli.py:38`

**Fakten-Beleg:** Nur ACMR-Pfade werden als Index-Overlays gelesen; alle
anderen Dateien kommen aus dem Working Tree, sodass unstaged Änderungen den
Candidate verfälschen und eine staged gelöschte, danach lokal neu angelegte
Datei wieder erscheint. Git-Startfehler und auch ein fehlgeschlagener
`git show` werden als leere/fallback Overlays toleriert. Ein staged leerer Blob
wird wegen `and show.stdout` nicht verwendet. Die CLI-Tests erzeugen überhaupt
kein Git-Repo und keinen staged Cross-File-Fehler.

**Normverletzung:** AC 12/FK-13 Ring 2 verlangen exakt „staged plus
unverändert“ und einen Test mit neuem Cross-File-Fehler. Fail-open auf den
Working Tree kann einen Commit fälschlich freigeben.

**Fix:** Den vollständigen Candidate aus Git-Index plus HEAD-Basis aufbauen,
inklusive Deletes und leerer Blobs; Working-Tree-Zustand darf nicht einfließen.
Jeder Git-Fehler muss Exit 3 liefern. Echten temporären Git-Repo-Test mit
staged Änderung, unstaged Gegenänderung, Delete und Cross-File-Fehler ergänzen.

### AG3-174-R14 — MAJOR — Schema-Erzeugung ist im echten Server nicht fail-closed und prüft bestehende Schemata nicht

**Ort:** `src/agentkit/backend/vectordb/schema.py:65`,
`src/agentkit/backend/vectordb/schema.py:79`,
`src/agentkit/backend/vectordb/mcp_server.py:43`,
`src/agentkit/backend/vectordb/mcp_server.py:141`

**Fakten-Beleg:** `ensure_story_context_schema()` beendet sich allein aufgrund
von `collections.exists()` und verifiziert keine Properties, Typen oder
Vektorisierung eines vorhandenen Legacy-Schemas. `build_tools_from_env()`
unterdrückt jeden Ensure-Fehler mit `contextlib.suppress(Exception)`. Der echte
`main()`-Server ruft Ensure überhaupt nicht auf.

**Normverletzung:** AC 2 verlangt das vollständige Schema und idempotente
Erzeugung durch einen benannten Owner; FAIL-CLOSED verbietet das Verschlucken
inkompatibler Infrastruktur. Ein vorhandenes partielles Schema wird aktuell als
bereit behandelt und scheitert erst später oder speichert unvollständig.

**Fix:** Exaktes vorhandenes Schema gegen den Contract prüfen und bei Drift
hart abbrechen bzw. eine explizite Migration ausführen. Der produktive
Composition-Root muss Ensure vor Tool-Bereitstellung zwingend ausführen; keine
Exception-Unterdrückung. Contract-/Integrationstest mit vorhandenem
inkompatiblem Schema.

### AG3-174-R15 — MAJOR — Projektbindung ignoriert die autoritative Projektkonfiguration und erfindet Identität/Pfade

**Ort:** `src/agentkit/backend/vectordb/project_binding.py:127`,
`src/agentkit/backend/vectordb/project_binding.py:140`,
`src/agentkit/backend/vectordb/project_binding.py:154`,
`src/agentkit/backend/config/models.py:862`,
`src/agentkit/backend/config/models.py:871`,
`src/agentkit/backend/story_creation/story_md_export.py:174`

**Fakten-Beleg:** Das autoritative `ProjectConfig` besitzt `project_key`,
`wiki_stories_dir` und `concepts_dir`. `_load_project_id()` prüft aber nicht
`project_key`; bei fehlendem `project_prefix` oder Config-Fehler fällt es still
auf den Verzeichnisnamen zurück. Concepts/Stories werden ebenfalls nicht aus
der Config, sondern aus hartcodiert `concept|concepts` und `stories` genommen.
Der Story-Exporter ignoriert `Story.project_key`, sucht ein nicht existentes
`project_id`-Attribut und leitet ersatzweise aus der Display-ID oder sogar
`"default"` ab.

**Normverletzung:** Scope 2 und 7 verlangen `project_id` nach bestehendem
Projektconfig-Vertrag und das konfigurierte `concepts_dir` als maßgeblich.
Erfundene IDs/Pfade brechen Projektisolation und können verschiedene Projekte
unter demselben falschen Diskriminator zusammenführen.

**Fix:** Projektconfig genau einmal strikt laden; `project_key`,
`wiki_stories_dir` und `concepts_dir` ohne Reparaturfallback binden und
contained auflösen. Configfehler sind Startfehler. Der Exportpfad muss die
autoritative Projektbindung bzw. mindestens `story.project_key` verwenden;
`"default"` ist zu entfernen.

### AG3-174-R16 — MAJOR — Pflichtdaten und Freshness werden nur als leere Platzhalter ausgeliefert

**Ort:** `src/agentkit/backend/vectordb/ingest/models.py:42`,
`src/agentkit/backend/vectordb/ingest/builders.py:123`,
`src/agentkit/backend/vectordb/ingest/engine.py:235`,
`src/agentkit/backend/vectordb/ingest/engine.py:256`,
`src/agentkit/backend/vectordb/mcp/tools.py:218`

**Fakten-Beleg:** `normative_rules` ist im Schema und Ergebnis vorhanden, wird
beim Concept-Build aber an keiner Stelle extrahiert oder gesetzt und bleibt
immer `""`. `story_list_sources` initialisiert `last_corpus_revision` mit
`""`; Story-/Research-Sync erhält grundsätzlich keine erfolgreiche Revision
oder sonstige Freshness und liefert daher keine belastbare „letzte erfolgreiche
Revision/Freshness“. Der Test prüft nur, dass einige Keys existieren.

**Normverletzung:** FK-13 §13.9.4 fordert extrahierte normative Regeln pro
Chunk. AC 8 verlangt für `story_list_sources` letzte erfolgreiche Revision/
Freshness, nicht einen leeren Shape-Platzhalter. Leere Defaults täuschen
Vertragserfüllung vor.

**Fix:** Normative-Regel-Sektion deterministisch extrahieren und testen.
Erfolgreiche producer-/source-gebundene Sync-Freshness als echten,
digestgebundenen Abschlusszustand modellieren und in `story_list_sources`
ausgeben; fehlende oder inkonsistente Freshness muss benannt/fail-closed sein.

### AG3-174-R17 — BLOCKER — Neues Top-Package `agentkit.concepts` verletzt die verbindliche Deployment-Unit-Struktur

**Ort:** `src/agentkit/concepts/__init__.py:1`,
`src/agentkit/concepts/profiles.py:14`,
`src/agentkit/concepts/chunking.py:14`,
`PROJECT_STRUCTURE.md` Abschnitt „src/agentkit/ — Deployment Units“ und Regel 1

**Fakten-Beleg:** `src/agentkit/concepts/` ist ein neues direktes Kind von
`agentkit` und importiert seinerseits zurück in
`agentkit.backend.vectordb.tokenizer`. `PROJECT_STRUCTURE.md` erlaubt direkt
unter `src/agentkit/` ausschließlich `backend`, `frontend`, `harness_client`,
`integration_clients`, `bundles` plus Paketmarker und bezeichnet
Strukturverstöße explizit als Deliverable-Blocker. Neue Boundary-/Fachmodule
dürfen gerade nicht als weitere direkte Kinder entstehen.

**Normverletzung:** Die Story nennt zwar selbst `src/agentkit/concepts/`, sagt
aber ebenso ausdrücklich: Bei Konflikt zwischen Story und Konzept/Struktur
stoppen und melden; sie trifft keine Konzeptentscheidung. Das stillschweigende
Übersteuern der verbindlichen Deployment-Unit-Regel ist daher eine verbotene
Architekturentscheidung. Zusätzlich ist die behauptete Transportfreiheit durch
die Rückabhängigkeit auf `backend` strukturell nicht sauber.

**Fix:** Nicht eigenmächtig nur verschieben. Zuerst den Widerspruch zwischen
Story und `PROJECT_STRUCTURE.md` autoritativ entscheiden lassen. Ohne
Strukturänderung gehört der Kern in einen passenden Backend-BC (naheliegend
`backend/concept_catalog` oder klar begründet unter `backend/vectordb`) und die
CLI in `backend/cli`; Abhängigkeitsrichtung anschließend ohne Top-Level-
Rückimport herstellen.

### AG3-174-R18 — BLOCKER — Die ausdrücklich verlangte AG3-172-Landesperre ist nur ein Kommentar

**Ort:** `stories/AG3-174-vectordb-retrieval-engine/status.yaml:19`,
`stories/AG3-174-vectordb-retrieval-engine/status.yaml:21`,
`stories/AG3-174-vectordb-retrieval-engine/report.md:71`,
`stories/AG3-172-postgres-schema-xdist-race/status.yaml:4`

**Fakten-Beleg:** AG3-174 steht auf `done`, `depends_on` bleibt leer, und die
AG3-172-Bedingung existiert nur in Kommentaren/Prosa. Eine Suche in Workflow,
CI und Tests findet keinen maschinengeprüften AG3-174→AG3-172-Merge-Guard.
AG3-172 selbst steht weiterhin auf `ready`, Phase `setup`, ist also weder
abgeschlossen noch gelandet. Der Bericht behauptet dennoch „Workflow-Gate;
nicht nur Kommentar“.

**Normverletzung:** Die DoD nennt diese Vorbedingung explizit eine
Landevoraussetzung, die vom Workflow tatsächlich geprüft werden muss. Der
aktuelle Zustand erlaubt genau die verbotene Landung vor AG3-172.

**Fix:** Einen echten, fail-closed Completion-/Merge-Guard implementieren und
testen oder die autoritative Dependency-Kante so modellieren, dass parallele
Entwicklung weiterhin möglich, die Landung aber technisch gesperrt ist.
AG3-174 darf vor erfüllter Sperre nicht `done`/landbar sein.

### AG3-174-R19 — MAJOR — Die Abnahmetests behaupten Verträge, prüfen sie aber nicht

**Ort:** `tests/unit/vectordb/test_mcp_tools.py:82`,
`tests/integration/vectordb/test_ingest_closure_and_gate.py:168`,
`tests/unit/concepts/test_ssot_drift.py:42`,
`tests/unit/concepts/test_frontmatter_strict.py:11`,
`tests/unit/vectordb/test_validate_and_authority.py:53`

**Fakten-Beleg:** `test_search_modes_differ` prüft nur den zurückgespiegelten
Modus-String, nicht unterschiedliche Suchausführung oder Ergebnisse.
`test_bounded_window_receipt_after_delete` instrumentiert keine Reihenfolge und
keinen Crash/Retry/Partial-Write/Parallelfall. Der SSOT-Test lädt den zweiten
Ingester nicht. Die Frontmatter-Matrix enthält nur vier Fälle statt der
geforderten vollständigen Matrix. Der Validator-Test ist nicht
tabellengetrieben und deckt nicht alle Codes/Exitcodes. Die MCP-Tests rufen
Python-Handler direkt auf statt die FastMCP-Grenze.

**Normverletzung:** AC 5, 6, 7, 9, 10, 11 und 12 verlangen diese Beweise
explizit. Die grüne Testsuite ist deshalb kein Nachweis der zentralen
Invarianten; mehrere der oben reproduzierten Fehler liegen genau in den
umgangenen Grenzen.

**Fix:** Tests an den echten produktiven Grenzen ergänzen: instrumentierter
Store-Port für Write/Validate/Delete/Receipt-Reihenfolge und Fehlerzustände,
zwei unabhängige Writer, tatsächlicher FastMCP/stdio-Aufruf, MCP-genutzter
Weaviate-Port, echter Git-Index-Candidate, realer `tools/concept_ingester`-
Vergleich und tabellengetriebene vollständige Negativmatrizen.

## Nicht als Finding gewertet

- Die vier verlangten `.conceptignore`-Glob-Grenzen sind in der isolierten
  Matcher-Implementierung plausibel und durch passende Grenztests belegt.
- `E-CHUNK-001` bleibt im Validator trotz deterministischer Teilsplittung
  blockierend.
- In den neu gelieferten Python-Bezeichnern, Wire-/JSON-Keys und Kommentaren
  wurde kein belastbarer ARCH-55-Sprachverstoß gefunden. Deutsche Story-
  Markdown-Überschriften sind fachlicher Inhalt, kein maschineller Contract.
- Das Bounded-Window-Modell selbst verwendet keinen CAS und keinen
  Generations-Zeiger; der Fehler liegt in der fehlenden Sollmengen-/
  Partial-Failure-Absicherung, nicht in unerlaubter Atomizitätsmechanik.

## Gesamturteil

**Nachbessern — nicht freigeben.**

Die MAJOR+-Findings sind echte Substanz. Es gibt mehrere unabhängige
Landungsblocker: Der reale Corpus ist nicht validier-/syncbar, der SSOT ist
nachweislich doppelt, die produktive CLI meldet Erfolg auf einem flüchtigen
Fake, der Replace-Pfad kann bei partiellem Write den letzten guten Bestand
löschen und trotzdem ein Receipt publizieren, die echten MCP-/Weaviate-Grenzen
sind nicht strikt, die verbindliche Projektstruktur wurde ohne Klärung
überstimmt und die AG3-172-Landesperre existiert nicht. Das ist deutlich mehr
als Feinschliff; MINOR-/NIT-Themen sind für die Freigabeentscheidung derzeit
irrelevant und wurden bewusst nicht aufgelistet.
