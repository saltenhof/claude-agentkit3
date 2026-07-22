# Review 2 (Codex) — AG3-174 Verifikationsrunde

## Verifikationsumfang

Geprüft wurden ausschließlich die Remediations zu R01–R17 und R19. R18 blieb
wie angewiesen außerhalb dieser Runde. Maßstab waren der jetzige Working Tree,
Story und FK-13; die gemeldeten grünen Gates wurden nicht als
Korrektheitsnachweis übernommen.

Zusätzlich zur Codeprüfung wurden die kritischen Pfade direkt reproduziert:

- `written < expected` bricht jetzt tatsächlich vor Delete ab, lässt den
  Altbestand unverändert und verändert das vorhandene Receipt nicht.
- Ein Store, der dagegen `written == expected` meldet, aber nichts schreibt,
  wird von der Rückleseprüfung nicht erkannt: Der Altbestand wird gelöscht und
  ein neues Success-Receipt publiziert (`rows_left=0`).
- Ein UUID-Delete, der `0` statt der erwarteten Anzahl meldet, führt weiterhin
  zu einem Success-Receipt; alte und neue Generation bleiben gemischt stehen.
- An der echten FastMCP-stdio-Grenze lautet das Input-Schema nur
  `{arguments: object|null}`. Flache Aufrufe mit `full_reindex=true`,
  `full_reindex=1` oder unbekannten Feldern werden ohne Tool-Fehler als
  `arguments=null` ausgeführt.
- Der produktive MCP-Suchadapter akzeptiert einen vollständig geformten Treffer
  mit `project_id="OTHER"` bei einer Anfrage für `project_id="P1"`.
- Der `permissive`-Entry-Point akzeptiert eine Datei mit doppeltem YAML-Key,
  deutet den Parsefehler als fehlendes Frontmatter um und indexiert den
  YAML-Block als Body unter einer erfundenen Pfad-ID.
- Ein geändertes Konzept kann über den tatsächlichen
  `WeaviateStoryAdapter` nicht inkrementell ersetzt werden, weil dessen Port
  kein `delete_by_ids` anbietet.

Die gezielte bestehende Suite blieb dabei grün:
`89 passed` für `tests/unit/concepts`, `tests/unit/vectordb`,
`tests/integration/vectordb`, `tests/contract/vectordb` und die Adaptertests.
Das bestätigt zugleich die unten beschriebenen Testlücken.

## Geschlossene Findings

- **R01: geschlossen.** `bind_project()` übernimmt den Corpus-Scope aus
  `ProjectConfig.concepts_dir`; geprüft wurde ein FK-13-Zielprojekt-Corpus,
  nicht AK3s eigener gemischter `concept/`-Baum
  (`project_binding.py:89-130`).
- **R03: geschlossen.** Unter `src/agentkit` existiert kein Memory-/Fake-Store
  mehr. Die produktive Sync-CLI baut den echten Adapter und scheitert bei
  fehlender bzw. nicht erreichbarer Bindung ungleich null
  (`cli_sync.py:26-57,71-87`). Der Fake liegt nur unter `tests/support/`.
- **R05: geschlossen.** Der Lock ist jetzt ein projektlokaler, prozessübergreifender
  File-Lock (`single_writer.py:33-83`). Ein Zwei-Prozess-Contestion-Test ergab
  `FIRST LOCKED`, `SECOND REJECTED`.
- **R08: geschlossen.** Story-/Research-Frontmatter läuft über den
  Duplicate-Key- und UTF-8-strikten Parser; falsche Pflicht-/Optionaltypen und
  I/O-Fehler brechen den gesamten Build ab (`builders.py:48-61,232-288`).
- **R15: geschlossen.** Projekt-ID, `concepts_dir` und `wiki_stories_dir`
  stammen jetzt aus `ProjectConfig`; die früheren Namens-/Pfad-Fallbacks und
  die Export-ID `default` sind entfernt (`project_binding.py:89-130`,
  `story_md_export.py:174-185`).
- **R17: geschlossen.** Der SSOT liegt entsprechend der
  Orchestratorentscheidung unter
  `src/agentkit/backend/concept_catalog/corpus/`; ein Top-Package
  `src/agentkit/concepts/` existiert nicht mehr.

## Offene Findings

### AG3-174-R02 — BLOCKER — Der permissive Konsument führt wieder eine zweite Wahrheit in den gemeinsamen Kern ein

**Ort:** `src/agentkit/backend/concept_catalog/corpus/discovery.py:130-155`,
`src/agentkit/backend/concept_catalog/corpus/frontmatter.py:257-294`,
`tools/concept_ingester/discovery.py:114-167`,
`tests/unit/concepts/test_ssot_drift.py:38-56`

**Fakten-Beleg:** `tools.concept_ingester.discover()` ruft den gemeinsamen
Owner mit `strict=False, frontmatter_mode="permissive"` auf. Im gemeinsamen
Owner fängt der permissive Modus jeden `ConceptParseError` aus
Frontmatter-Split **und** YAML-Parse und ersetzt ihn durch `raw={}` plus den
gesamten Dateiinhalt als Body. `_validate_permissive()` erfindet anschließend
`concept_id`, `title`, `status="active"` und `doc_kind="core"`; ungültige
Status-/Doc-Kind-Werte werden ebenfalls auf diese Defaults repariert. Weitere
Validierungsfehler werden wegen `strict=False` still übersprungen.

Die direkte Reproduktion mit doppeltem `concept_id` ergab:

```text
FK13_REJECTED E-SCHEMA-001
AK3_TOOL_CHUNKS 2
AK3_TOOL_DEFAULT_ID domain-design/bad.md
AK3_TOOL_FRONTMATTER_IN_CONTENT True
```

Zusätzlich erzeugt der Tool-Konsument weiterhin eine eigene Chunk-Identität
über `_CHUNK_NAMESPACE` und `uuid5(rel_path#anchor)`
(`tools/concept_ingester/discovery.py:32-33,163-167`), während der
Produktivpfad `deterministic_chunk_uuid()` mit einer anderen Identität nutzt
(`backend/vectordb/ingest/identity.py:8-21`). Der Drift-Test beweist keine
Gleichheit beider Entry-Points: Seine Kernassertion
`tool_paths <= ssot_paths or tool_paths` ist für jede nichtleere Tool-Menge
wahr und damit tautologisch.

**Warum offen:** Das ist nicht bloß ein unterschiedliches Validierungsprofil
am Rand. Syntaktisch ungültiges YAML wird im gemeinsamen Discovery-/Parserkern
in gültige Ersatzdaten umgedeutet, Dateien werden still verloren, und die
Identität bleibt zweigleisig. Damit bleiben AC 9, AC 10/11 und der ausdrücklich
geforderte eine Discovery-/Parser-/Chunking-/Identity-Pfad verletzt.

**Fix:** YAML/UTF-8/Fence-Fehler müssen in allen Profilen hart bleiben. Ein
AK3-Inventarprofil darf nach erfolgreichem Parse andere zulässige
Dokumentklassen modellieren, aber keine Parsefehler, IDs oder Enums reparieren
und keine Dateien still überspringen. Identität als profilparametrisierte
Funktion in den SSOT ziehen. Den Drift-Test über beide realen Entry-Points mit
demselben Corpus ausführen und exakte Datei-, Chunk- und Identity-Mengen sowie
die gemeinsame Negativmatrix vergleichen.

### AG3-174-R04 — BLOCKER — Die Rückleseprüfung beweist nicht, dass die neue Sollgeneration geschrieben wurde

**Ort:** `src/agentkit/backend/vectordb/ingest/engine.py:245-307`,
`src/agentkit/backend/vectordb/ingest/engine.py:336-381`,
`src/agentkit/backend/vectordb/concept_corpus/sync.py:96-117`

**Fakten-Beleg:** Der neue `written != len(objects)`-Check ist korrekt und die
direkte Reproduktion bestätigte `delete_calls=0`, intakten Altbestand und ein
unverändertes Receipt. Danach prüft die Rücklesephase jedoch nur UUID,
Content-Hash, Projekt und irgendeinen vom Producer besessenen Source-Type. Sie
prüft weder `generation_id == generation_id` noch Source-Type und Source-Datei
gegen den jeweils erwarteten Record. Ein alter Record mit gleicher
deterministischer UUID und gleichem Hash genügt daher als angeblich neue
Sollgeneration.

Ein Store, der für alle Objekte die erwartete Anzahl meldet, aber keinen Write
ausführt, führte am echten `concept_sync_bounded_window()`-Pfad zu:

```text
LIAR_SUCCESS_RECEIPT True
LIAR_DELETE_CALLS 1
LIAR_ROWS_LEFT 0
```

Der Altbestand wurde als „validierte Sollmenge“ akzeptiert, anschließend wegen
seiner alten Generation gelöscht und das Receipt überschrieben.

**Warum offen:** AC 6 verlangt ausdrücklich „neue Sollgeneration vollständig
schreiben und Sollmenge validieren“ vor Delete und Receipt. Der jetzige Check
beweist nur, dass irgendeine ältere inhaltlich passende Menge vorhanden war.
Der zentrale Bounded-Window-Sicherheitsbeweis fehlt weiterhin.

**Fix:** Für jede erwartete UUID den vollständigen erwarteten Tupelwert
`(project_id, source_type, source_file, content_hash, generation_id)` prüfen;
die Rücklesequery muss projekt-, producer-/source- und generationsgebunden
sein. Erst bei exakter Mengengleichheit darf der alte Bestand gelöscht werden.
Ein Test muss einen lügenden `written==expected`-Port und falsche
Generation/Source-Werte injizieren und unveränderten Altbestand plus
unverändertes Receipt beweisen.

### AG3-174-R06 — BLOCKER — Die echte FastMCP-stdio-Grenze hat den falschen Wire-Vertrag und ignoriert flache Argumente

**Ort:** `src/agentkit/backend/vectordb/mcp_server.py:162-187`,
`src/agentkit/backend/vectordb/mcp/wire_models.py:14-69`,
`tests/unit/vectordb/test_mcp_tools.py:45-57`

**Fakten-Beleg:** Die fünf FastMCP-Tools werden jeweils als Funktion mit einem
einzigen Parameter `arguments: dict[...]` registriert. Deshalb exponiert die
echte stdio-Grenze nicht die dokumentierten Toolparameter, sondern:

```json
{"properties":{"arguments":{"anyOf":[{"additionalProperties":true,"type":"object"},{"type":"null"}],"default":null}},"type":"object"}
```

Direkte stdio-Calls ergaben:

```text
FLAT_BOOL  ERROR False  TEXT {"received": null}
FLAT_INT   ERROR False  TEXT {"received": null}
FLAT_EXTRA ERROR False  TEXT {"received": null}
NESTED_INT ERROR False  TEXT {"received": {"full_reindex": 1}}
```

Bei den Sync-Tools werden normale flache Parameter wegen des optionalen
Wrapperparameters still verworfen und der Default ausgeführt. Bei den
Suchtools fehlt stattdessen der erforderliche Wrapperparameter. Die strikten
Pydantic-Modelle greifen erst **nach** dieser falschen FastMCP-Grenze und sind
daher kein Wire-Beweis. `project_id` ist im internen Modell jetzt optional und
ein dort ankommendes Fremdprojekt wird abgelehnt; diese beiden Teilaspekte sind
geschlossen, der reale Vertrag aber nicht.

**Warum offen:** AC 7/8/10/11 verlangen genau die fünf FK-13-Tools mit ihren
flachen Parametern und Ablehnung statt stiller Reparatur. Der produktive
stdio-Server ignoriert aktuell sogar einen gültigen `full_reindex=true`-Aufruf
und unbekannte Extras ohne Fehler.

**Fix:** Den Low-Level-MCP-Call-Handler so registrieren, dass er das rohe
Argumentobjekt des Tool-Calls vor jeglicher FastMCP-Koerzierung erhält, dort
mit den strikten Modellen validieren und pro Tool das korrekte flache
`inputSchema` veröffentlichen. Ein echter stdio-Contract-Test muss
`tools/list` sowie gültige/ungültige flache Calls prüfen: `1→bool`,
`true→int`, Extras, fehlende Pflichtfelder, optionales `project_id` und
Fremdprojekt.

### AG3-174-R07 — BLOCKER — Search-/Delete-Grenzen sind weiterhin nicht vollständig projektgebunden und fail-closed

**Ort:** `src/agentkit/integration_clients/vectordb/weaviate_adapter.py:112-183`,
`src/agentkit/integration_clients/vectordb/weaviate_adapter.py:267-302`,
`src/agentkit/backend/vectordb/mcp/tools.py:121-140,212-237`,
`src/agentkit/backend/vectordb/ingest/engine.py:336-381`

**Fakten-Beleg:** `WeaviateStoryAdapter.search()` verwendet jetzt dieselbe
Normalisierung wie `story_search()`, und `_RealWeaviateClient.fetch()` trägt
den Serverfilter auf jeder Seite; diese Teile sind verbessert. Die
Normalisierung prüft den zurückgegebenen `project_id` aber nicht gegen den
angefragten Wert. Die direkte Reproduktion akzeptierte bei einer P1-Anfrage
den Treffer `project_id="OTHER"`. Die MCP-Projektionen reparieren weiterhin
fehlende Ergebnisfelder mit `hit.get(..., "")`, `[]` oder `False`, statt eine
malforme Weaviate-Antwort abzulehnen.

Beim bevorzugten Stale-Delete ruft die Engine außerdem `delete_by_ids()` nur
mit Collection und UUIDs auf — ohne Projektfilter — und übernimmt dessen
Integer ungeprüft. Ein Port, der `0` zurückgab, erzeugte:

```text
ZERO_DELETE_SUCCESS_RECEIPT True
DELETED_COUNTER 0
ROWS_BEFORE_AFTER 2 3
```

**Warum offen:** Damit sind die Weaviate-Antwortgrenze, die Zwei-Projekt-
Isolation aus AC 4 und die harte Partial-Delete-Invariante aus AC 6/10 noch
nicht erfüllt. Ein fremder Treffer kann bis zum Success-Envelope gelangen und
ein fehlgeschlagener Delete wird als erfolgreicher Abschluss markiert.

**Fix:** Die Normalisierung muss den erwarteten Projekt-/Source-Kontext kennen
und jede Abweichung ablehnen; Story- und Concept-Hits brauchen jeweils eine
vollständige strikte Ergebnis-Shape ohne Reparaturdefaults. UUID-Delete muss
serverseitig zusätzlich auf `project_id` und den Producer-/Source-Scope
filtern und strukturierte Counter liefern; `matches == successful == expected`
und `failed == 0` sind vor Receipt hart zu prüfen.

### AG3-174-R09 — MAJOR — Authority-Ranking degradiert bei fehlendem/kaputtem Graphen still

**Ort:** `src/agentkit/backend/vectordb/mcp/tools.py:64-75`,
`src/agentkit/backend/vectordb/mcp/tools.py:185-211`,
`tests/unit/vectordb/test_validate_and_authority.py:113-172`

**Fakten-Beleg:** Der Live-Handler instanziiert den Resolver jetzt und ruft
`rank()` auf; der frühere Totpfad ist damit teilweise geschlossen. `_load_graph()`
liefert bei fehlender Datei, I/O-, UTF-8- oder JSON-Fehler jedoch still `{}`.
Der MCP-Server startet und liefert erfolgreiche `concept_search`-Antworten,
obwohl graphbasierte Deferrals und Scope-Ableitung fehlen. Der Test injiziert
einen synthetischen Graph direkt und läuft nicht über diesen produktiven
Load-Pfad.

**Warum offen:** AC 5/7 verlangt angewandtes Authority-Ranking, nicht ein
stilles Best-Effort-Ranking. Ein obligatorisches Build-Artefakt darf bei
fehlender oder malformer externer Datei nicht unbemerkt zu semantisch anderen
Ergebnissen führen.

**Fix:** `concept_graph.json` strikt laden und Shape sowie
`corpus_revision` gegen den gebundenen Corpus/Completion-Stand prüfen. Fehlend,
malform oder stale muss Start bzw. Tool-Call fail-closed beenden. Den Test über
`KnowledgeTools` mit echter Datei und negativer Datei-Matrix führen.

### AG3-174-R10 — MAJOR — `concept_path` kann Erfolg melden, ohne das gewählte Dokument zu synchronisieren

**Ort:** `src/agentkit/backend/vectordb/mcp/tools.py:249-288`,
`src/agentkit/backend/vectordb/ingest/engine.py:144-153`

**Fakten-Beleg:** Die Dokumentauswahl akzeptiert neben exakter Gleichheit auch
`source_file_filter.endswith(d.rel_path)`. Ein corpus-relativer Pfad wie
`fk_test.md` wird dadurch als gültig erkannt, aber zu `source_file_filter=
"fk_test.md"` normalisiert. Die gebauten Records tragen dagegen
`source_file="concepts/fk_test.md"` und werden in der Engine vollständig
herausgefiltert. Das Tool publiziert danach ein Success-Receipt für eine leere
Sollmenge. Die direkte Reproduktion meldete `ok=True`, ließ aber ausschließlich
die alte Generation stehen.

**Warum offen:** R10 sollte die fehlende Funktion real implementieren. Ein
akzeptierter Einzelpfad darf weder ein No-op-Success noch einen falschen
Delete-Scope erzeugen.

**Fix:** Eine einzige kanonische Pfadsemantik festlegen und den Parameter
zuerst strikt relativ zu `binding.concepts_dir` bzw. zum dokumentierten
Projektpfad auflösen. Ausschließlich exakte kanonische Gleichheit zulassen,
`source_file_filter` aus dem ausgewählten `ConceptDocument`/Record ableiten und
eine leere Recordmenge vor Ingest ablehnen. Echte Tooltests für relativ,
projekt-relativ, absolut, außerhalb, nicht vorhanden und mehrdeutig ergänzen.

### AG3-174-R11 — MAJOR — Der Finding-Katalog ist formal vorhanden, aber nicht vollständig produktiv erreichbar

**Ort:** `src/agentkit/backend/vectordb/concept_corpus/validate.py:67-115`,
`src/agentkit/backend/vectordb/concept_corpus/validate.py:386-416`,
`src/agentkit/backend/vectordb/concept_corpus/validate.py:466-496`

**Fakten-Beleg:** `E-AUTH-002` wird nur berechnet, wenn
`baseline_documents` übergeben wird. Kein produktiver Aufrufer — weder Corpus-
Validate noch `validate --staged` — liefert diese Baseline; der vorgeschriebene
Finding ist somit Totcode. Für `W-SCOPE-001` erfindet die Implementierung lokal
die vier „fundamentalen“ Scopes `state-schema`, `pipeline`, `error-routing` und
`vectordb`. Weder FK-13 noch das Decision Record bestimmen diese Liste.

**Warum offen:** AC 5 fordert den vollständigen Finding-Katalog. Ein nie
erreichbarer Code erfüllt ihn nicht. Die lokale Scope-Liste ist zugleich eine
Konzeptentscheidung, obwohl die Story nur aus dem Konzept ableiten darf.

**Fix:** Beim Candidate-/Restructuring-Pfad den Baseline-Corpus aus Git HEAD
aufbauen und an die Authority-Diff-Prüfung übergeben. Die fundamentalen Scopes
müssen aus einer bestehenden autoritativen Quelle kommen; fehlt diese, ist die
Entscheidung vor Implementierung normativ zu klären. Jeden Finding-Code mit
einem echten auslösenden Corpus tabellengetrieben testen.

### AG3-174-R12 — MAJOR — Geänderte oder entfernte Chunks können über den produktiven Adapter nicht inkrementell bereinigt werden

**Ort:** `src/agentkit/backend/vectordb/ingest/engine.py:213-243,336-385`,
`src/agentkit/integration_clients/vectordb/weaviate_adapter.py:322-378`

**Fakten-Beleg:** Unveränderte Hashes werden jetzt tatsächlich übersprungen.
Für geänderte/entfernte Chunks benötigt die Engine anschließend
`delete_by_ids`. Der produktive `WeaviateStoryAdapter` implementiert diese
Methode nicht. Die direkte Reproduktion nach einer Concept-Änderung endete mit:

```text
store cannot delete individual stale UUIDs (need delete_by_ids); fail-closed (R12).
ADAPTER_HAS_DELETE_BY_IDS False
```

Zu diesem Zeitpunkt ist die neue Generation bereits geschrieben; jeder Retry
endet wieder am fehlenden Delete-Port.

**Warum offen:** FK-13 §13.3.3/§13.9.9 und AC 3 verlangen inkrementellen
Hash-Upsert samt Delete verschwundener/geänderter Chunks. Nur der
Unchanged-Fall funktioniert produktiv; die Tests bestehen, weil der
Test-Memory-Port eine zusätzliche Methode anbietet, die der echte Adapter nicht
hat.

**Fix:** Einen projekt-/source-gebundenen Stale-Delete im produktiven Adapter
implementieren, einschließlich harter Counter-Invarianten. Integrationstest
über `WeaviateStoryAdapter` für Änderung und Dateilöschung ausführen, nicht
direkt über den reicheren Memory-Port.

### AG3-174-R13 — MAJOR — `validate --staged` verwendet für `.conceptignore` weiterhin Working-Tree-Wahrheit

**Ort:** `src/agentkit/backend/concept_catalog/cli.py:202-280`,
`src/agentkit/backend/concept_catalog/corpus/discovery.py:81-106`,
`src/agentkit/backend/concept_catalog/corpus/conceptignore.py:32-48`

**Fakten-Beleg:** Staged Markdown-Blobs und unveränderte HEAD-Dateien werden
jetzt korrekt kombiniert; ein neu erzeugter Cross-File-Authority-Konflikt
ergab reproduzierbar Exit 2. `.conceptignore` wird jedoch nie aus dem Git-Index
geladen: `_staged_candidate_overlays()` berücksichtigt nur `.md`, während
Discovery die Ignore-Datei direkt aus dem Working Tree liest.

Bei staged `fk_other.md`-Exclude plus nachträglich leerer, unstaged
Working-Tree-Ignore-Datei meldete der Candidate-Lauf fälschlich
`E-AUTH-001` und Exit 2. Der echte staged Candidate hätte `fk_other.md`
ausgeschlossen.

**Warum offen:** Der Candidate-Corpus besteht damit nicht ausschließlich aus
staged plus unverändertem HEAD. Eine unstaged Ignore-Änderung kann den
Commit-Gate-Ausgang ändern; R13 und AC 12 sind noch nicht vollständig
geschlossen.

**Fix:** `.conceptignore` als Teil der Candidate-Overlay-Wahrheit aus Index bzw.
HEAD laden und im staged Modus niemals aus dem Working Tree lesen. Den
geforderten Cross-File-Test um staged/unstaged divergierende Ignore-Dateien,
Deletes und Renames ergänzen.

### AG3-174-R14 — MAJOR — Bestehende Weaviate-Schemata werden weiterhin nur oberflächlich bzw. gar nicht verifiziert

**Ort:** `src/agentkit/backend/vectordb/schema.py:90-123`,
`tests/contract/vectordb/test_story_context_schema_contract.py:52-71`

**Fakten-Beleg:** Wenn `collections.get` oder `config.get` nicht verfügbar ist,
kehrt `_verify_existing_schema()` trotz des Kommentars „fail-closed“ einfach
erfolgreich zurück. Wenn Introspection vorhanden ist, vergleicht sie nur
Property-Namen. Datentyp, Array-Typ, Vektorisierung/Skip-Vectorization,
Tokenization und Vectorizer-Konfiguration bleiben ungeprüft. Der Contract-Test
nutzt gerade einen Client ohne `get` und bestätigt deshalb den fail-open-
Idempotenzpfad.

**Warum offen:** Ein bestehendes `StoryContext` mit falschen Typen oder falscher
Vektorisierung gilt als passend. Das verletzt AC 2 und die fail-closed-
Schema-Grenze aus R14; `ensure` in CLI/MCP repariert diesen unzureichenden
Vergleich nicht.

**Fix:** Produktionsclients ohne beweisbare Introspection hart ablehnen. Die
vollständige kanonische Schemaform einschließlich Datentypen und
Vektorisierungsregeln vergleichen und jede Abweichung als `SchemaDriftError`
melden. Contract-Tests mit falschem Typ, falschem Array-Typ, fehlender Property,
falschem Vectorizer und fehlender Introspection ergänzen.

### AG3-174-R16 — MAJOR — `story_list_sources` meldet nicht die letzte erfolgreiche Revision/Freshness

**Ort:** `src/agentkit/backend/vectordb/ingest/engine.py:418-470`,
`src/agentkit/backend/vectordb/concept_corpus/sync.py:105-117`

**Fakten-Beleg:** Die Shape enthält jetzt Producer, Counts und Revision. Als
„last“ wird aber schlicht der zuletzt iterierte aktuelle Chunkwert verwendet;
es gibt weder Sortierung noch Abgleich mit einem Completion-Receipt. Jeder
nichtleere Revisionstext wird als `freshness_status="ok"` ausgegeben. Chunks
einer vor Receipt gescheiterten Teilgeneration können deshalb als letzte
erfolgreiche Revision erscheinen. Story-Syncs erhalten standardmäßig sogar
`corpus_revision=""` und landen dauerhaft bei `missing_revision`.

**Warum offen:** AC 8 verlangt die **letzte erfolgreiche** Revision/Freshness.
Chunk-Metadaten sind während des normierten Bounded-Window ausdrücklich kein
Abschlussmarker. Die jetzige Ausgabe verwechselt beobachteten Bestand mit
erfolgreichem Abschluss.

**Fix:** Pro Projekt/Producer bzw. Source einen digestgebundenen
Completion-Stand führen und `story_list_sources` dagegen auswerten. Gemischte,
unbestätigte oder vom Receipt abweichende Generationen müssen `stale`/`partial`
statt `ok` liefern. Tests müssen einen Write-/Delete-Abbruch vor Receipt und
den unveränderten letzten Erfolgsstand prüfen.

### AG3-174-R19 — MAJOR — Die Remediationstests beweisen die kritischen realen Grenzen weiterhin nicht

**Ort:** `tests/unit/concepts/test_ssot_drift.py:38-56`,
`tests/integration/vectordb/test_ingest_closure_and_gate.py:83-115`,
`tests/unit/vectordb/test_mcp_tools.py:45-57,109-143`,
`tests/contract/vectordb/test_story_context_schema_contract.py:52-71`

**Fakten-Beleg:** Der SSOT-Test enthält die tautologische `... or tool_paths`-
Assertion. Der Partial-Write-Test prüft nur `upsert -> 0`; er prüft weder ein
unverändertes vorhandenes Receipt noch die fehlende Generation-Prüfung noch
Partial-Delete-Counter. Die MCP-Tests rufen `parse_tool_args()` bzw.
`KnowledgeTools` direkt auf und umgehen FastMCP/stdio vollständig. Der
Schema-Idempotenztest besitzt keine Introspection und maskiert R14. Änderung
und Delete laufen über einen Memory-Port mit `delete_by_ids`, obwohl der echte
Adapter diese Fähigkeit nicht anbietet.

Dass dieselben 89 Tests grün sind, während die oben genannten realen
Reproduktionen fehlschlagen, ist der direkte Gegenbeweis zur behaupteten
Abnahmesubstanz.

**Warum offen:** AC 3–11 verlangen echte Boundary-/Sequenzbeweise. Die Tests
bestätigen überwiegend interne Hilfsfunktionen oder einen mächtigeren Fake und
lassen genau die produktiven Bruchstellen aus.

**Fix:** Die reproduzierten Fälle als Regressionstests übernehmen: echter
FastMCP-stdio-Client, `WeaviateStoryAdapter` als tatsächlich verwendeter Port,
lügender Full-Count plus Generation-Reread, Partial-Delete-Counter, fremder
Search-Treffer, staged Ignore-Divergenz sowie beide realen SSOT-Entry-Points mit
exakter Gleichheit.

## Gesamturteil

**Nicht freigeben — nachbessern.** R02, R04, R06 und R07 sind weiterhin
Blocker; R09–R14, R16 und R19 enthalten zusätzliche echte MAJOR-Substanz.
Besonders schwer wiegen das erfolgreiche Receipt nach unbewiesener bzw.
unvollständig gelöschter Generation, der faktisch falsche MCP-Wire-Vertrag,
die projektfremde Search-Antwort und der permissive Parser-Rückfall.

Das Verbleibende ist **kein Feinschliff**, den der Orchestrator selbst
abräumen sollte. Die Root-Causes betreffen Sicherheits-/Korrektheitsinvarianten
und produktive Ports; der Umsetzer muss sie samt echten Boundary-Regressionen
schließen. Stoppen ist in diesem Zustand nicht vertretbar.
