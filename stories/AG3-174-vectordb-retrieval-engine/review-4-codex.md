# Review 4 (Codex) — AG3-174 finale Verifikation

## Umfang

Geprüft wurden ausschließlich die vier offenen Punkte aus Review 3 — R07,
R14, R16 und R19 — sowie der R11-Minor. Die Killer wurden erneut unabhängig
von den gelieferten Regressionstests über den produktiven Adapter-, Engine-,
Receipt-, Schema-, Sync- und MCP-stdio-Pfad ausgeführt.

## R07 — noch offen (MAJOR): Der UUID-Delete-Killer ist geschlossen, aber externe Write-/Filter-Delete-Counter werden weiterhin koerziert

**Ort:** `src/agentkit/integration_clients/vectordb/strict_counters.py:18-76`,
`src/agentkit/integration_clients/vectordb/weaviate_adapter.py:344-375,377-427,594-672`,
`src/agentkit/backend/vectordb/ingest/engine.py:293-309,399-563,565-594`

**Geschlossen und verifiziert:** Der konkrete Review-3-Killer sitzt jetzt:

- `{"matches": expected, "successful": expected}` ohne `failed` wird von
  `WeaviateStoryAdapter.delete_by_ids()` hart abgelehnt.
- Ein nackter Integer und boolesche Counter werden ebenfalls abgelehnt.
- `_RealWeaviateClient.delete_by_ids()` und `delete_by_filter()` verwenden
  denselben strikten Parser; es gibt dort keine Missing-`failed`-Reparatur mehr.
- Die Engine verlangt im UUID-Pfad nochmals die vollständige Shape mit exakt
  nicht-booleschen Integers.
- Meldet der Port eine vollständig geformte Erfolgs-Shape, löscht aber nichts,
  erkennt `_assert_stale_gone()` dies durch projekt-/source-gebundenes Re-read.
  Kein Receipt wird publiziert und die alten UUIDs bleiben nachweisbar.

Die direkte Reproduktion über
`WeaviateStoryAdapter -> IngestEngine -> concept_sync_bounded_window` ergab:

```text
missing_failed  REJECTED VectorDbWriteError  receipt_same=True old_preserved=True
bare_int        REJECTED VectorDbWriteError  receipt_same=True old_preserved=True
bool_fields     REJECTED VectorDbWriteError  receipt_same=True old_preserved=True
full_shape_lie  REJECTED IngestError         receipt_same=True old_preserved=True
```

**Verbleibender echter Rest:** Die ausdrücklich verlangte Prüfung auf *alle*
externen Delete-/Write-Counter-Shapes ist noch nicht sauber. Der Adapter
koerziert weiterhin mit `int(...)`:

- `WeaviateStoryAdapter.story_sync()` und `upsert()` in
  `weaviate_adapter.py:383-403`;
- `WeaviateStoryAdapter.delete_by_filter()` in
  `weaviate_adapter.py:418-427`;
- die Engine nochmals beim Upsert in `engine.py:297-304`.

Damit wird ein externer boolescher Write-/Filter-Delete-Counter weiterhin als
gültiger Integer angenommen:

```text
adapter_upsert_bool        ACCEPTED 1
adapter_filter_delete_bool ACCEPTED 1
```

Zusätzlich enthält der Engine-Fallback `_delete_checked()` noch die alte
Attribut-Nachsicht `getattr(result, "failed", 0)`, akzeptiert nackte Integers
und behandelt falsch typisiertes `failed` wieder als `0`
(`engine.py:581-588`). Der primäre produktive UUID-Delete-Pfad erreicht diesen
Fallback nicht mehr; die externe Adaptergrenze selbst akzeptiert die ungültigen
Shapes aber real. Das ist innerhalb der explizit angeforderten R07-Prüfachse
kein neuer Review-Gegenstand und kein bloßer Stilpunkt.

**Fix:** Für Upsert-/Write-Counts und den normalisierten Filter-Delete-Count
ebenfalls `type(value) is int` erzwingen; kein `int(...)`. `_delete_checked()`
auf genau den kanonischen internen Integer-Port reduzieren oder auch dort die
vollständige strukturierte Shape ohne Defaults verlangen. Regressionen müssen
bool, String/Float und bare-int jeweils direkt durch `WeaviateStoryAdapter`
führen, nicht nur `parse_delete_counters()` isoliert testen.

## R16 — geschlossen

**Ort:** `src/agentkit/backend/vectordb/completion_store.py:30-91,105-222`,
`src/agentkit/backend/vectordb/ingest/engine.py:596-677`,
`src/agentkit/backend/vectordb/concept_corpus/sync.py:116-133`,
`tests/integration/vectordb/test_review2_boundary_regressions.py:589-683`

**Verifiziert wie:** Completion enthält jetzt einen digestgebundenen Nachweis
der gewünschten Menge aus
`(chunk_uuid, content_hash, source_file, source_type)`. Generation-ID und die
alten per-Chunk-Revisionsfelder sind bewusst nicht mehr das Freshness-Kriterium.

Ein normal erfolgreicher inkrementeller Concept-Sync schrieb einen geänderten
Chunk, übersprang drei hashgleiche Chunks auf ihrer alten Generation und ließ
damit zwei beobachtete Generationen stehen. `story_list_sources` meldete jetzt
korrekt `freshness_status="ok"`:

```text
R16_SUCCESS {'discovered': 4, 'written': 1, 'deleted': 1, 'skipped': 3}
generations=2 freshness=ok
```

Danach wurde einmal ein gewünschter Chunk real entfernt und in einem separaten
Lauf ein zusätzlicher Rogue-Chunk eingefügt. Beide Zustände ergaben
`freshness_status="partial"`. Damit unterscheiden Completion und Diagnose
erfolgreiche Hash-Skips jetzt korrekt von echten Mengenabweichungen.

## R14 — geschlossen

**Ort:** `src/agentkit/backend/vectordb/schema.py:151-224,279-336`,
`tests/contract/vectordb/test_story_context_schema_contract.py:55-200`,
`tests/integration/vectordb/test_review2_boundary_regressions.py:540-585`

**Verifiziert wie:** Eine introspektierbare Config mit sämtlichen Property-
Namen und Datentypen, aber ohne `skip_vectorization`, `tokenization` und
Vectorizer-/`vector_config`-Metadaten, erzeugte jetzt sofort
`SchemaDriftError` statt Erfolg. Fehlende Skip-Werte müssen echte Booleans
sein; erwartete Tokenization ist zwingend; `vector_config` wird einschließlich
verschachtelter Weaviate-v4-Form ausgewertet und fehlender Vectorizer wird
abgelehnt.

Der frühere `except TypeError`-Create-Fallback ist entfernt. Ein künstlich vom
Collection-Create geworfener `TypeError("create mismatch")` wurde unverändert
propagiert; es entstand keine vereinfachte Collection ohne Vectorizer.

## R19 — geschlossen

**Ort:** `tests/integration/vectordb/test_review2_boundary_regressions.py:189-286,340-407,559-683`,
`tests/support/vectordb/mcp_stdio_runner.py:1-55`,
`tests/unit/concepts/test_ssot_drift.py:1-108`,
`tests/contract/vectordb/test_story_context_schema_contract.py:126-200`

**Verifiziert wie:** `test_r06_real_stdio_client_wire_matrix` startet jetzt
tatsächlich einen Subprozess über `StdioServerParameters`, verbindet
`stdio_client` und `ClientSession` und prüft `tools/list` sowie reale Wire-
Calls. Die falsche `pytest.mark.asyncio`-Markierung existiert nicht mehr; der
Test führt seine Coroutine kontrolliert mit `asyncio.run()` aus.

Die FK-13-Seite des Drift-Tests läuft über den produktiven
`build_concept_chunks()`-Builder. R07 Missing-`failed`/bare-int/bool,
R14 fehlende Vektormetadaten sowie R16 erfolgreicher Mixed-Generation- und
zusätzlicher Rogue-Chunk sind als Regressionen vorhanden. Der fehlende-Chunk-
Fall wurde in dieser Runde zusätzlich manuell am echten `list_sources()`-Pfad
verifiziert.

Serieller Lauf ohne xdist:

```text
python -m pytest -q -n 0 \
  tests/integration/vectordb/test_review2_boundary_regressions.py \
  tests/unit/concepts/test_ssot_drift.py \
  tests/contract/vectordb/test_story_context_schema_contract.py

30 passed
```

Das Integrationsmodul selbst sammelt aktuell 19 Tests; zusammen mit SSOT-Drift
und Schema-Contract sind es die bestätigten 30. Das ist nur eine Präzisierung
der Zählung, kein Finding.

## R11-Minor — noch offen (MINOR): Der benannte Fehler landet im Warning-Kanal und blockiert Sync nicht

**Ort:** `src/agentkit/backend/vectordb/concept_corpus/validate.py:123-140,479-582`,
`src/agentkit/backend/vectordb/concept_corpus/sync.py:61-78`

**Fakten-Beleg:** Die YAML-Grenze selbst ist verbessert: Eine vorhandene
malforme `fundamental_scopes.yaml` wird strikt geparst, Duplicate Keys werden
abgelehnt und `_check_scope_owners()` erzeugt einen benannten
`E-INTERNAL-001`-Finding mit `severity="error"`.

Dieser Finding wird jedoch über
`warnings.extend(_check_scope_owners(...))` in die Warning-Liste einsortiert.
Der normale `validate_corpus()`-Lauf ergab deshalb:

```text
exit=1
ok_for_sync=True
errors=[]
warnings=[('E-INTERNAL-001', 'error')]
```

`concept_sync_bounded_window()` ruft Validation nicht mit `strict=True` auf und
prüft nur `ok_for_sync`; die direkte Reproduktion mit malformer vorhandener
Meta-Datei endete daher mit `R11_SYNC ACCEPTED`. Der Fehler ist nicht mehr
unsichtbar, wird funktional aber weiterhin wie ein nicht blockierendes Warning
behandelt.

**Fix:** `_check_scope_owners()` muss Error- und Warning-Findings getrennt
liefern oder `FundamentalScopesError` vor der Warning-Sammlung direkt in
`errors` eintragen. Regression: malforme vorhandene Datei muss Exit 2/3,
`ok_for_sync=False` und `ConceptSyncBlockedError` bewirken; eine abwesende Datei
bleibt inert.

## Gesamturteil

**NICHT FREIGEBEN.** R14, R16 und R19 sind geschlossen; auch der gefährliche
R07-Partial-Delete-/False-Receipt-Killer ist tatsächlich beseitigt. R07 ist
aber auf der ausdrücklich verlangten vollständigen externen Counter-Achse noch
nicht an der Wurzel zu: boolesche Write- und Filter-Delete-Counts werden im
produktiven Adapter weiterhin per `int(...)` akzeptiert, und der Engine-
Fallback enthält noch Missing-`failed`-Nachsicht. Das ist verbleibende
fail-closed-Substanz (**MAJOR**), nicht Nachkarten.

Der R11-Rest ist weiterhin **MINOR**, aber ebenfalls real: Ein sichtbarer
`E-INTERNAL-001` blockiert den Sync nicht. Beide Fixes sind eng und lokal; nach
diesen zwei Korrekturen genügt eine weitere gezielte Verifikation derselben
Fälle. Neue Review-Themen sind nicht erforderlich.
