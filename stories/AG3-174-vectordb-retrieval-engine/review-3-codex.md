# Review 3 (Codex) — AG3-174 zweite Verifikationsrunde

## Umfang und Ergebnis der Reproduktion

Geprüft wurden ausschließlich die in Review 2 offenen Findings R02, R04, R06,
R07, R09–R14, R16 und R19. R18 blieb wie angewiesen außerhalb des Auftrags.
Die kritischen Fälle wurden erneut über den produktiven Parser-, Ingest-,
`WeaviateStoryAdapter`- und MCP-stdio-Pfad ausgeführt; Fakes saßen dabei nur am
externen Weaviate-Port.

Die Remediation hat wesentliche Root Causes tatsächlich geschlossen: Der
permissive Parser-Rückfall ist entfernt, der Liar-Write wird vor Delete erkannt,
der echte stdio-Vertrag ist flach und strikt, fremde Search-Treffer werden
abgelehnt und der produktive Adapter bietet den projekt-/source-gebundenen
UUID-Delete an. Es verbleiben aber zwei Abschlussmarker-/Generationsfehler sowie
eine weiterhin fail-open arbeitende Schema-Prüfung. Außerdem ist das neue
Boundary-Testmodul weder ein echter stdio-Test noch im jetzigen Repo grün.

## Verifikation pro Runde-2-Finding

### R02: geschlossen im Produktcode; Boundary-Nachweis siehe R19

**Ort:** `src/agentkit/backend/concept_catalog/corpus/discovery.py:61-161`,
`src/agentkit/backend/concept_catalog/corpus/frontmatter.py:103-199`,
`src/agentkit/backend/concept_catalog/corpus/identity.py:8-21`,
`tools/concept_ingester/discovery.py:111-170`,
`tests/unit/concepts/test_ssot_drift.py:41-152`

**Verifiziert wie:** Duplicate Keys, syntaktisch malformes YAML, fehlender
Closing-Fence und ungültiges UTF-8 wurden jeweils gegen `frontmatter_mode="fk13"`,
`frontmatter_mode="inventory"` und den echten
`tools.concept_ingester.discovery.discover()`-Entry ausgeführt. Alle zwölf
Kombinationen warfen `ConceptParseError`; kein Profil erzeugte Ersatz-
Frontmatter oder indexierte den YAML-Block als Body. Der Tool-Konsument ruft
denselben Discovery-Owner, `chunk_markdown()` und
`deterministic_chunk_uuid()` auf. Für Chunk-Identitäten existiert nur noch die
Funktion in `corpus/identity.py`; `ingest/identity.py` ist ein Re-Export.

Der Drift-Test verwendet jetzt echte Mengengleichheit für Pfade, Chunks und
UUIDs; die frühere Tautologie ist entfernt. Seine FK-13-Seite rekonstruiert die
Menge allerdings direkt aus den gemeinsamen Kernfunktionen statt über
`build_concept_chunks()`/Sync. Das ist kein verbleibender Produkt-SSOT-Fehler,
aber Teil des R19-Testnachweisdefizits.

### R04: geschlossen für den geforderten Liar-/Partial-Write-Killer

**Ort:** `src/agentkit/backend/vectordb/ingest/engine.py:261-337`,
`tests/integration/vectordb/test_review2_boundary_regressions.py:80-155`

**Verifiziert wie:** Ein Store meldete `written == expected`, schrieb aber
nichts und lieferte den Altbestand zurück. `concept_sync_bounded_window()` brach
jetzt wegen der abweichenden `generation_id` vor jedem Delete ab; der
Altbestand und das bestehende Receipt blieben unverändert. `written == 0`
brach ebenfalls vor Delete/Receipt ab. Die Rücklese prüft pro UUID das volle
Tupel `project_id`, `source_type`, `source_file`, `content_hash` und
`generation_id` und liest projekt-/producer-source-gebunden zurück.

Ein anderer, bei normalem inkrementellem Erfolg entstehender
Generationsfehler ist unter R16 dokumentiert; er widerlegt nicht den hier
geforderten Liar-Killer, verletzt aber denselben Bounded-Window-Gesamtvertrag.

### R06: geschlossen im echten MCP-stdio-Pfad

**Ort:** `src/agentkit/backend/vectordb/mcp_server.py:23-76,141-175,213-223`,
`src/agentkit/backend/vectordb/mcp/wire_models.py:1-92`

**Verifiziert wie:** Ein echter `mcp.ClientSession` wurde über
`mcp.client.stdio.stdio_client` gegen einen Subprozess mit dem produktiven
`create_mcp_server()` ausgeführt. `tools/list` lieferte exakt die fünf Tools
mit flachen Schemas, ohne `arguments`-Wrapper und jeweils
`additionalProperties: false`. Ein flacher `story_sync` mit
`full_reindex=true` führte einen Full-Reindex aus und gab
`"full_reindex": true` mit fünf geschriebenen Records zurück. Am Wire wurden
`full_reindex=1`, `limit=true`, ein unbekanntes Extra und das fehlende Pflichtfeld
`query` als MCP-Validierungsfehler abgelehnt. `story_list_sources` ohne
`project_id` band P1; `project_id="OTHER"` lieferte das fail-closed
`ok:false`-Envelope.

Der gelieferte R06-Test erbringt diesen Beweis selbst nicht; siehe R19.

### AG3-174-R07 — BLOCKER — Fehlende Delete-Counter werden weiter zu Erfolg repariert

**Ort:** `src/agentkit/integration_clients/vectordb/weaviate_adapter.py:344-380,646-688`,
`src/agentkit/backend/vectordb/ingest/engine.py:400-470`

**Fakten-Beleg:** Search ist jetzt korrekt gebunden: Ein vollständig geformter
Treffer mit `project_id="OTHER"` bei P1 wurde am produktiven Adapter als
`VectorDbUnavailableError` abgelehnt. `_RealWeaviateClient.delete_by_ids()`
baut außerdem den Serverfilter aus `project_id AND source_type AND UUIDs`.

Die Counter-Grenze bleibt jedoch fail-open:

- `WeaviateStoryAdapter.delete_by_ids()` liest Mapping-Felder mit
  `result.get("matches", 0)`, `get("successful", 0)` und
  `get("failed", 0)` und akzeptiert sogar einen nackten Integer als Beweis für
  alle drei Counter (`weaviate_adapter.py:371-378`).
- `_RealWeaviateClient.delete_by_ids()` deutet ein fehlendes `failed` ebenfalls
  als `0` um (`weaviate_adapter.py:676-687`).
- Die Engine verlangt nur für `matches` und `successful` einen Integer; ein
  fehlendes oder falsch typisiertes `failed` wird nochmals auf `0` repariert
  (`engine.py:455-465`). Wegen `isinstance(True, int)` sind auch boolesche
  Counter nicht strikt ausgeschlossen.

Direkte Reproduktion über
`WeaviateStoryAdapter -> IngestEngine -> concept_sync_bounded_window`: Der
externe Port meldete wahrheitswidrig
`{"matches": expected, "successful": expected}` ohne `failed` und löschte
nichts. Ergebnis:

```text
R07_MISSING_FAILED SUCCESS
R07_RECEIPT_CHANGED True
R07_ROWS_BEFORE_AFTER 2 3
R07_GENERATIONS_AFTER [<old>, <new>]
```

**Warum noch offen:** Das ist exakt der verbotene stille Partial-Delete aus AC
6/10. Ein fehlender Beweis wird in Erfolg umgedeutet, ein Success-Receipt
publiziert und der Altbestand bleibt erhalten. Zero-Counter werden inzwischen
korrekt abgelehnt, aber die harte Counter-Invariante ist damit nicht an der
Wurzel geschlossen.

**Fix:** An allen drei Schichten ausschließlich eine vollständige strukturierte
Shape mit exakt vorhandenen, nicht-booleschen Integers für `matches`,
`successful` und `failed` akzeptieren. Keine Mapping-Defaults und keinen
Integer-Legacy-Pfad. Vor Receipt die stale UUIDs projekt-/source-gebunden
zurücklesen und ihr tatsächliches Verschwinden verifizieren. Den oben
reproduzierten Missing-`failed`-Liar als Adapter-Regressionstest ergänzen.

### R09: geschlossen

**Ort:** `src/agentkit/backend/vectordb/mcp/tools.py:96-169,256-303`,
`tests/integration/vectordb/test_review2_boundary_regressions.py:321-354`

**Verifiziert wie:** `KnowledgeTools` lädt `concept_graph.json` produktiv
fail-closed, validiert Objekt-/Nodes-/Edges-/Revision-Shape und vergleicht die
Revision gegen den live entdeckten Corpus. Fehlende, malforme und stale
Graphen wurden über den echten Konstruktorpfad abgelehnt; Authority-Ranking
wird anschließend auf die Search-Hits angewandt.

### R10: geschlossen

**Ort:** `src/agentkit/backend/vectordb/mcp/tools.py:357-456`

**Verifiziert wie:** Corpus-relativer, projekt-relativer und absoluter Pfad
innerhalb des Corpus funktionieren; outside/missing werden abgelehnt. Zusätzlich
wurde `fk_test.md` inhaltlich geändert und über den realen Tool-Handler
inkrementell synchronisiert. Ergebnis war `written=1`, `deleted=1`,
`skipped=1`; ausschließlich `concepts/fk_test.md` blieb als Source-Datei und
der geänderte Inhalt war im Store vorhanden. Der frühere leere No-op-Success
ist beseitigt.

### R11: MAJOR-Root-Cause geschlossen; ein neuer MINOR-Rest bei der optionalen Scope-Meta-Datei

**Ort:** `src/agentkit/backend/vectordb/concept_corpus/validate.py:97-125,399-429,479-535,538-586`

**Verifiziert wie:** Im echten staged-Candidate-Pfad wurde die einzige
`authority_over`-Belegung gegenüber Git HEAD entfernt. Die produktiv aus HEAD
gebaute Baseline erzeugte `E-AUTH-002` und Exit 2. Dieser frühere Totpfad ist
geschlossen.

Die W-SCOPE-Lösung ist in ihrem normativen Kern sauber: Ohne autoritative
Ziel-Corpus-Datei ist der Check inert; es wird keine lokale fundamentale
Scope-Liste erfunden und kein `W-SCOPE-001` als ausgeführt/erfolgreich
ausgewiesen. Eine vorhandene gültige `_meta/fundamental_scopes.yaml` löste für
einen unbelegten Scope real `W-SCOPE-001` aus. Die Designation der Scopes bleibt
damit zu Recht beim PO/Orchestrator.

**MINOR-Rest:** Eine vorhandene, aber malforme Meta-Datei wird durch
`yaml.safe_load` plus `except ...: return None` beziehungsweise Shape-
`return None` still wie „nicht vorhanden“ behandelt (`validate.py:494-504`).
Die Reproduktion ergab Exit 0 ohne Warning oder Error. Sobald der PO diese
Datei tatsächlich autoritativ macht, wäre das eine falsche Erfolgsaussage.

**Fix:** Nur Abwesenheit darf inert sein. Ist die Datei vorhanden, müssen
UTF-8/YAML-, Duplicate-Key- und Shape-Fehler als benannter Validation-/Internal-
Fehler sichtbar werden. Das ist begrenzter Feinschliff und keine erneute lokale
Scope-Konzeptentscheidung.

### R12: geschlossen, soweit nicht durch R07s Counter-Reparatur unterlaufen

**Ort:** `src/agentkit/integration_clients/vectordb/weaviate_adapter.py:344-381,646-688`,
`tests/integration/vectordb/test_review2_boundary_regressions.py:389-421`

**Verifiziert wie:** `WeaviateStoryAdapter` bietet jetzt produktiv
`delete_by_ids(collection, uuids, project_id, source_types)`. Der Änderungs-
und Dateilöschtest läuft über diesen Adapter, nicht direkt über den Memory-
Store: geänderter Inhalt ersetzt die alte UUID und eine gelöschte Quelldatei
verschwindet. Der Memory-Client sitzt dabei zulässig nur hinter dem externen
Weaviate-Port. Die serverseitige Filterkonstruktion ist im realen Client
implementiert. Die unstrikte Auswertung seiner Antwort ist der separate
R07-Blocker.

### R13: geschlossen

**Ort:** `src/agentkit/backend/concept_catalog/cli.py:202-311`,
`src/agentkit/backend/concept_catalog/corpus/discovery.py:80-107`

**Verifiziert wie:** Eine `.conceptignore` wurde mit `ignored.md` gestaged und
danach im Working Tree wieder geleert. `_staged_candidate_overlays()` lieferte
weiter den Index-Blob `b"ignored.md\n"`; der echte Candidate-Corpus enthielt
nur `fk_test.md`. Staged Deletes/Renames werden als Delete-Overlays geführt.
Die Working-Tree-Wahrheit beeinflusst diesen Pfad nicht mehr.

### AG3-174-R14 — MAJOR — Vorhandene Schemaform bleibt bei fehlenden Vektor-Metadaten fail-open

**Ort:** `src/agentkit/backend/vectordb/schema.py:93-106,151-198,242-294`,
`tests/contract/vectordb/test_story_context_schema_contract.py:55-119`

**Fakten-Beleg:** Fehlende Introspection, fehlende Properties, falsche
Datentypen/Arraytypen und ein explizit falscher `vectorizer` werden jetzt
abgelehnt. Die angeblich vollständige Prüfung akzeptiert aber weiterhin einen
nicht beweisbaren Zustand:

- Fehlt `skip_vectorization`, wird die Prüfung übersprungen
  (`schema.py:162-171`).
- Fehlt die erwartete `tokenization`, wird die Prüfung übersprungen
  (`schema.py:172-180`).
- Fehlt der Vectorizer beziehungsweise liegt er im von der Create-Seite
  verwendeten `vector_config`-Feld, kehrt `_assert_vectorizer()` erfolgreich
  zurück (`schema.py:183-190`); `vector_config` wird gar nicht gelesen.
- Ein `TypeError` beim produktiven Create fällt auf eine vereinfachte
  Collection ohne den kanonischen Vectorizer zurück (`schema.py:282-294`).

Eine introspektierbare Config mit allen Property-Namen und Datentypen, aber
ohne `skip_vectorization`, `tokenization` und Vectorizer-Metadaten wurde direkt
von `ensure_story_context_schema()` akzeptiert:

```text
R14_MISSING_VECTOR_METADATA ACCEPTED
```

Die neuen Tests setzen diese Attribute ausnahmslos selbst und prüfen den
fehlenden Beweis daher nicht.

**Warum noch offen:** AC 2 und die R14-Remediation verlangen die vollständige
kanonische Schemaform. „Metadatum nicht introspektierbar“ darf nicht mit
„passt“ gleichgesetzt werden.

**Fix:** Für jede erwartete Eigenschaft Vectorize-/Tokenization-Nachweise
zwingend verlangen, das tatsächliche Weaviate-v4-`vector_config` strikt gegen
die Create-Konfiguration prüfen und fehlende/uneindeutige Werte ablehnen. Den
produktiven `TypeError`-Fallback entfernen oder ausschließlich über einen
expliziten Testadapter ermöglichen. Negative Tests für jeweils fehlende
Vektor-, Skip- und Tokenization-Metadaten ergänzen.

### AG3-174-R16 — BLOCKER — Erfolgreicher inkrementeller Sync publiziert einen Receipt über einen permanent gemischten Generationsstand

**Ort:** `src/agentkit/backend/vectordb/ingest/engine.py:244-259,279-324,339-350`,
`src/agentkit/backend/vectordb/completion_store.py:117-146`,
`tests/integration/vectordb/test_review2_boundary_regressions.py:560-604`

**Fakten-Beleg:** Bei `full_reindex=false` behalten hashgleiche, übersprungene
Chunks ausdrücklich ihre alte `generation_id`; nur geänderte Chunks erhalten
die neue Generation. Der Delete-Pfad entfernt im inkrementellen Fall nur nicht
mehr gewünschte UUIDs und lässt gewünschte Alt-Generationen stehen. Danach
wird trotzdem ein Completion-Stand mit ausschließlich der neuen
`generation_id` publiziert. `evaluate_freshness()` verlangt dagegen genau eine
beobachtete Generation passend zum Completion-Stand und meldet den vom Sync
selbst erzeugten Zustand als `partial`.

Reproduktion mit zwei Konzeptdokumenten, davon eines geändert:

```text
R16_INCREMENTAL_REPORT {'discovered': 4, 'written': 1, 'deleted': 1, 'skipped': 3}
R16_INCREMENTAL_FRESHNESS partial
R16_OBSERVED_GENS [<old>, <receipt-generation>]
```

Der Sync selbst war erfolgreich und publizierte Receipt/Completion. Der
gemischte Stand ist kein kurzes Crashfenster, sondern bleibt dauerhaft. Die
neuen R16-Tests prüfen nur einen Abbruch vor Receipt und eine manuell injizierte
Rogue-Generation; den normalen erfolgreichen inkrementellen Pfad prüfen sie
nicht.

**Warum noch offen:** Das verletzt nicht nur die Ausgabeform von
`story_list_sources`, sondern AC 6: Nach Abschluss muss die vollständig
validierte Sollgeneration stehen und erst dann darf das Receipt publiziert
werden. Das Receipt behauptet aktuell eine Generation, die drei von vier
gewünschten Chunks nicht tragen.

**Fix:** Vor Delete/Receipt alle gewünschten Chunks auf die neue Generation
bringen und danach die exakte projekt-/source-gebundene Sollmenge einschließlich
`generation_id` beweisen. Hashgleichheit kann weiterhin die erneute
Inhalts-/Vektorarbeit vermeiden, darf aber nicht zu einem alten
Abschlussmarker führen; gegebenenfalls ist dafür ein strikt gezähltes
Metadaten-Update am Adapter nötig. Danach muss ein erfolgreicher inkrementeller
Sync `freshness_status="ok"` liefern. Kein CAS und kein Generations-Zeiger sind
dazu erforderlich.

### AG3-174-R19 — MAJOR — Die neue Regression behauptet reale Boundaries, führt den stdio-Pfad aber nicht aus und ist aktuell rot

**Ort:** `tests/integration/vectordb/test_review2_boundary_regressions.py:1-5,163-224,278-313,389-421,430-604`,
`tests/unit/concepts/test_ssot_drift.py:41-94`

**Fakten-Beleg:** Das Modul sammelt zwar die gemeldeten 17 Fälle, aber
`test_r06_low_level_server_list_and_call` erzeugt nur ein Serverobjekt und ruft
danach `list_tools()` sowie `dispatch_tool()` direkt auf. Es importiert weder
`mcp.client.stdio` noch `ClientSession`; der Kommentar „stdio path uses the same
function“ ist kein Boundary-Beweis. Zusätzlich ist die synchrone Testfunktion
mit `@pytest.mark.asyncio` markiert, obwohl das Projekt kein passendes Plugin
lädt. Der aktuelle gezielte Lauf ergab:

```text
1 failed, 25 passed
FAILED test_r06_low_level_server_list_and_call
async def functions are not natively supported
PytestUnknownMarkWarning: Unknown pytest.mark.asyncio
```

Damit ist die Meldung `pytest 10087 passed` am jetzigen Working Tree nicht
reproduzierbar. Die übrigen fokussierten Tests ergaben `14 passed` sowie
`48 passed`; sie decken den oben reproduzierten Missing-`failed`-Delete, den
fehlenden Schema-Metadatenbeweis und den normalen erfolgreichen Mixed-
Generation-Sync nicht ab. Der SSOT-Test hat exakte Assertions, führt seine
FK-13-Seite aber direkt aus gemeinsamen Kernfunktionen statt durch den realen
FK-13-Builder/Sync-Entry.

**Warum noch offen:** Die Produktimplementierung von R06 besteht die von mir
separat ausgeführte echte stdio-Probe, doch der verlangte dauerhafte
Boundary-Regressionsbeweis fehlt und die angeblich grüne Suite ist lokal rot.
Bei R07/R14/R16 liefern die fehlenden Killerfälle erneut falsche Sicherheit.

**Fix:** Den R06-Test als echten stdio-Subprozess mit
`StdioServerParameters`, `stdio_client` und `ClientSession` implementieren und
die Wire-Matrix dort ausführen; die falsche Async-Markierung entfernen oder die
benötigte Test-Infrastruktur explizit bereitstellen. R07 Missing-`failed`, R14
fehlende Vektor-Metadaten und R16 erfolgreichen inkrementellen Mixed-Stand als
Regressionen übernehmen. Für Drift den FK-13-Satz über
`build_concept_chunks()` beziehungsweise den produktiven Sync-Adapter bilden.

## Gates

- Gezielte neue Module: **rot**, `1 failed, 25 passed` (R19 oben).
- Weitere fokussierte Adapter-/MCP-/Validate-/CLI-/SSOT-/Schema-Tests:
  **48 passed**.
- Kritische R04/R07/R09/R10/R12/R14/R16-Auswahl: **14 passed**; die neuen
  Killer-Reproduktionen R07/R14/R16 schlagen außerhalb der vorhandenen Tests
  wie oben beschrieben fehl.
- Der lokale Jenkins-/Sonar-Check konnte nicht als grün bestätigt werden:
  `check_remote_gates.ps1` erhielt von Jenkins `401 Unauthorized`. Das ist kein
  Ersatz für ein fachliches Finding, aber die gemeldeten Remote-Gates sind in
  dieser Runde nicht verifiziert.

## Gesamturteil

**NICHT FREIGEBEN.** Konkret verbleiben:

1. **R07 BLOCKER:** Ein fehlender `failed`-Counter wird zu `0` repariert;
   Partial-Delete erzeugt Success-Receipt und lässt Altbestand stehen.
2. **R16 BLOCKER:** Ein normal erfolgreicher inkrementeller Sync publiziert
   Completion über einen permanent gemischten, nicht vom Receipt belegten
   Generationsstand.
3. **R14 MAJOR:** Bestehende Schemata ohne beweisbare Vektor-/Tokenization-
   Metadaten werden weiterhin akzeptiert.
4. **R19 MAJOR:** Der behauptete stdio-Regressionstest umgeht stdio, deckt die
   verbliebenen Killer nicht ab und macht das neue Modul aktuell rot.

Der W-SCOPE-Meta-Fehler ist **MINOR** und könnte als begrenzter Feinschliff vom
Orchestrator selbst abgeräumt werden. Die vier Punkte darüber sind dagegen
echte Korrektheits-/Fail-closed-Substanz; insbesondere die beiden falschen
Success-/Completion-Marker sind keine Perfektionismusfragen. Stoppen ist in
diesem Zustand nicht vertretbar.
