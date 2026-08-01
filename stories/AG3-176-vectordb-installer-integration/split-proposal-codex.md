# Zerlegungsvorschlag engine.py + runmodel.py — Codex

## engine.py

Aktueller Befund: Sonar meldet exakt **1.577 LOC**, die Datei hat physisch 2.087 Zeilen. Der Dateiname verdeckt derzeit mindestens sechs Verantwortungen.

### Ist-Analyse

- **Transportvertrag**: `CorpusClientPort` beschreibt in [engine.py](T:/codebase/claude-agentkit3/src/agentkit/backend/vectordb/engine.py:138), Z. 138–209, den benötigten dünnen Weaviate-Adapter.
- **Corpus-Objektbestand**: `WeaviateCorpusStore.list_objects_for_source`, `list_objects_for_source_types`, `upsert_objects`, `delete_objects_older_than` und `delete_objects_without_generation`, Z. 225–380, verwalten Chunk-Versionen und generationsgebundene Löschungen.
- **Completion-Ledger**: `get_receipt`, `set_receipt(s)`, `resolve_pending_commits`, `_publish_completion_run`, `_list_run_records` und weitere Methoden, Z. 382–949, implementieren atomare Run-Positionen, Idempotenz und Recovery nach unbekanntem Commit-Ausgang.
- **Source-Claim-Lifecycle**: `try_claim_source`, `reclaim_source`, `assert_claim_held`, `release_source`, `_generation_rows`, `_held_claim`, Z. 951–1224, verwalten den persistenten Generation-Ladder und das Fencing.
- **Persistierte Sync-Record-Verträge**: `_render_receipt_batch`, `_run_receipt_digest`, `_parse_run_record`, `_claim_from_props`, `receipt_from_props` und die strikten Hilfsvalidatoren, Z. 1241–1678, definieren Wire-Format, UUID-/Digest-Bindung und Fail-closed-Rekonstruktion.
- **Retrieval und Freshness-Sicht**: `WeaviateRetrievalPort`, `authoritative_generations`, `stale_chunk_count`, `_last_completed_revision`, Z. 1682–1864.
- **Runtime-Komposition und Entry-Point**: `ensure_corpus_collections`, `connect_real_client`, `compose_runtime`, `run_stdio_server`, `main`, Z. 1867–2067; `_split_endpoint` und `_split_grpc`, Z. 1938–1939, sind historische Re-Exports des bereits bestehenden `endpoints.py`.

Die entscheidende Red Flag ist `WeaviateCorpusStore`: Eine Klasse besitzt drei eigenständig benennbare Änderungsgründe — Corpus-Objekte, Completion-Publikation und Claim-Ownership. Der gemeinsame `CorpusStorePort` ist dagegen sinnvoll, weil `SyncService` diese Fähigkeiten als eine konsistente Persistenzgrenze benötigt.

### Schnittvorschlag

`~LOC` meint geschätzte Sonar-NCLOC einschließlich neuer Imports und Delegationscode.

| Datei | Verantwortung (1 Satz) | Symbole | ~LOC |
|---|---|---|---:|
| `client_port.py` | Definiert den von allen VectorDB-Persistenzbausteinen benötigten dünnen Clientvertrag. | `CorpusClientPort` | 70 |
| `sync_record_codec.py` | Definiert Identität, kanonische Serialisierung und strikte Validierung aller persistierten Sync-Steuerrecords. | `RECEIPT_*`, `RUN_RECEIPT_*`, `CLAIM_*`, `_CompletionRunRecord`, `_positive_int`, `_required_strings`, `_render_receipt_batch`, `_render_producer_completions`, `_run_receipt_digest`, `_parse_receipt_batch`, `_parse_producer_completions`, `_parse_run_record`, `_claim_from_props`, `receipt_from_props`, UUID-Funktionen für Completion/Run/Claim/Release | 430 |
| `corpus_objects.py` | Persistiert Corpus-Objektversionen und erzwingt generations- sowie projektsichere Mutationen. | neue interne Klasse `WeaviateCorpusObjectStore` mit `list_objects_for_source`, `list_objects_for_source_types`, `upsert_objects`, `delete_objects_older_than`, `delete_objects_without_generation` | 130 |
| `completion_ledger.py` | Publiziert und liest autoritative Completion-Runs einschließlich dauerhafter Unknown-Outcome-Recovery. | neue interne Klasse `WeaviateCompletionLedger`; `get_receipt`, `set_receipt`, `set_receipts`, `resolve_pending_commits`, `list_receipts`, `list_producer_completions`, `_publish_completion_run`, `_build_run_record`, `_read_*`, `_find_run_by_id`, `_prune_superseded_completions`, `_finish_not_committed` | 570 |
| `source_claims.py` | Verwaltet den persistenten Source-Generation-Ladder und das explizite Claim-Fencing. | neue interne Klasse `WeaviateSourceClaimRegistry`; `try_claim_source`, `reclaim_source`, `assert_claim_held`, `release_source`, `_create_generation`, `_generation_rows`, `_highest_generation`, `_held_claim`, `_release_marker_exists`, `_prune_generations_below` | 230 |
| `corpus_store.py` | Stellt `CorpusStorePort` als stabile Fassade über Objektbestand, Completion-Ledger und Claim-Registry bereit. | öffentliche Klasse `WeaviateCorpusStore`; delegierende Portmethoden; kompatible `_claim_uuid`, `_release_uuid`, `_completion_uuid`, `_run_position_uuid` | 170 |
| `retrieval.py` | Liefert projektspezifische Suche und die aus Completions abgeleitete Freshness-/Stale-Sicht. | `WeaviateRetrievalPort`, `authoritative_generations`, `stale_chunk_count`, `_last_completed_revision` | 125 |
| `runtime.py` | Baut den produktiven VectorDB-Dienst aus Binding, Client, Schema, Store, Sync und Retrieval zusammen. | `ensure_corpus_collections`, `connect_real_client`, interner `build_runtime`, `_aux_property_specs`, `_receipt_property_specs` | 155 |
| `engine.py` | Bleibt ausführbarer Entry-Point und rückwärtskompatible Importfassade ohne eigene Persistenzfachlogik. | öffentliche Re-Exports; dünner `compose_runtime`-Wrapper; `_split_endpoint`, `_split_grpc`; `run_stdio_server`, `main`, `_resolve_dir` | 75 |

Der fachliche Baustein bleibt insgesamt der bestehende `VectorDbAdapter`. `CorpusSyncPersistence` ist darin ein Subsystem mit den drei Subkomponenten Objektbestand, Completion-Ledger und Claim-Registry; `engine.py` selbst ist danach keine Fachkomponente mehr, sondern Kompositions- und Kompatibilitätsrand.

### Abhängigkeitsrichtung

```text
engine
  → runtime
  → öffentliche Owner-Module für Re-Exports

runtime
  → corpus_store
  → retrieval
  → client_port
  → RuntimeBinding, SyncService, McpToolService

corpus_store
  → corpus_objects
  → completion_ledger
  → source_claims

corpus_objects
  → client_port, schema

completion_ledger
  → client_port
  → sync_record_codec
  → commit_recovery

source_claims
  → client_port
  → sync_record_codec

retrieval
  → client_port
  → CorpusStorePort
  → schema

sync_record_codec
  → sync-Domänenmodelle
```

Zyklusfreiheit folgt aus der topologischen Reihenfolge:

1. `client_port`, `sync_record_codec`
2. `corpus_objects`, `completion_ledger`, `source_claims`, `retrieval`
3. `corpus_store`
4. `runtime`
5. `engine`

Insbesondere darf `sync_record_codec._parse_run_record` nicht mehr auf `WeaviateCorpusStore._run_position_uuid` zurückgreifen. Die UUID-Bildung wird eine freie Codec-Funktion; dadurch entsteht kein Rückimport vom Codec zur Fassade. Ebenso typisiert `retrieval.py` seinen Store gegen `CorpusStorePort` beziehungsweise einen engeren Read-Port, nicht gegen die konkrete Fassade.

### Vertragsfläche

Heute produktiv konsumierte Namen:

- `closure/runtime_ports.py`, `installer/cp10a_initial_sync.py`, `installer/runner.py`: `CorpusClientPort`, `compose_runtime`
- `story_creation/weaviate_index.py`: `CorpusClientPort`, `WeaviateCorpusStore`, `ensure_corpus_collections`
- `vectordb/cli.py` und `installer/cp10a_initial_sync.py`: `compose_runtime`
- Installations- und MCP-Registrierung: `python -m agentkit.backend.vectordb.engine`
- Tests zusätzlich: `WeaviateRetrievalPort`, `connect_real_client`, Collection-Konstanten, `receipt_from_props`, `_run_receipt_digest`, `_render_producer_completions`, `_split_endpoint`, `_split_grpc`

Daraus folgt:

- Der Modulpfad `agentkit.backend.vectordb.engine` und seine `-m`-Ausführbarkeit bleiben unverändert.
- Alle heutigen öffentlichen bzw. produktiv direkt importierten Namen werden dort re-exportiert: mindestens `CorpusClientPort`, `WeaviateCorpusStore`, `WeaviateRetrievalPort`, `compose_runtime`, `connect_real_client`, `ensure_corpus_collections`, `receipt_from_props`, `run_stdio_server`, `main` und die Collection-Konstanten.
- Bestehende produktive Konsumenten benötigen im ersten Schritt **keine Importänderung**.
- Neue interne Implementierung sollte direkt aus den Owner-Modulen importieren; `engine.py` bleibt die stabile externe Fassade.
- `_split_endpoint` und `_split_grpc` bleiben trotz Unterstrich als historische Aliase erhalten, weil der Quellkommentar sie ausdrücklich als öffentlichen Seam bezeichnet.
- `compose_runtime` muss als Wrapper in `engine.py` verbleiben und den dort sichtbaren `connect_real_client` an `runtime.build_runtime` übergeben. Sonst bricht der bestehende Monkeypatch-Seam in `test_engine_realpath_r2.py`.
- Rein private Testseams dürfen gezielt umgestellt werden: `_COMPLETION_ATTEMPT_LIMIT` ist nach dem Schnitt in `completion_ledger.py` zu patchen. Ein bloßer Re-Export würde eine Zuweisung auf `engine._COMPLETION_ATTEMPT_LIMIT` nicht zur tatsächlich gelesenen Variable weiterleiten.
- Die strukturellen Tests, die `inspect.getsource(WeaviateCorpusStore)` auswerten, müssen künftig die fachlichen Owner `WeaviateCorpusObjectStore` beziehungsweise `WeaviateCompletionLedger` prüfen.

### Risiken

- **Höchstes Risiko: Completion-Ledger.** Digestmaterial, UUID-Bildung, Sequenzbereich, Insert-only-Verhalten und Journalzustand bilden zusammen einen atomaren Vertrag. Codec und Ledger dürfen nur gemeinsam migriert und mit den Recovery-/Collision-Tests verifiziert werden.
- **Facade-Komposition:** `client`, `collection`, `clock` und `recovery_journal` sind heute direkt sichtbare Dataclass-Felder. Die Fassade muss Signatur und Feldzugriff erhalten und exakt dieselbe Clock an Ledger und Claim-Registry weiterreichen.
- **Monkeypatch-Auflösung:** Ein importiertes Alias wird nicht automatisch von einem Patch am Ursprungsmodul beeinflusst. Besonders `connect_real_client` und `_COMPLETION_ATTEMPT_LIMIT` benötigen bewusst definierte Testseams.
- **Strukturelle Sicherheitsbeweise:** Die Tests für den einzigen Generation-Stamping-Pfad und für ausschließlich bedingte Corpus-Deletes dürfen nicht ersatzlos auf die Fassade zeigen.
- **Mögliche Überabstraktion:** Drei getrennte öffentliche Stores wären falsch; dadurch würde `SyncService` die gemeinsame Persistenzgrenze verlieren. Die Aufteilung bleibt intern hinter `WeaviateCorpusStore`.
- **LOC-Schätzung:** `completion_ledger.py` ist die größte Einheit, besitzt aber genau einen fachlichen Änderungsgrund und bleibt mit deutlichem Abstand unter 1.200 LOC.

### Migrationsreihenfolge

1. Einen Contract-Test für die aus `engine` importierbaren Namen, die Konstruktor-Signatur von `WeaviateCorpusStore` und den `-m`-Entry-Point ergänzen.
2. `client_port.py` und `sync_record_codec.py` atomar extrahieren; `engine.py` importiert zunächst zurück und verhält sich unverändert. Danach Codec-, Receipt- und Recovery-Tests.
3. `corpus_objects.py` extrahieren und `WeaviateCorpusStore` nur für diese fünf Methoden delegieren lassen. Danach Sync-, Story-Index- und strukturelle Delete-/Stamping-Tests.
4. `source_claims.py` extrahieren; private UUID-Methoden auf der Fassade als statische Forwarder erhalten. Danach Claim-, Reclaim-, Release- und Race-Tests.
5. `completion_ledger.py` einschließlich Journal-Recovery in einem Schritt extrahieren. Danach die vollständigen Commit-Recovery-, Sync- und Transporttests.
6. `retrieval.py` extrahieren und gegen einen Port statt gegen die konkrete Fassade typisieren. Danach MCP-, CLI-, Retrieval- und Freshness-Tests.
7. Schemaaufbau, Verbindung und Komposition nach `runtime.py` verschieben; `engine.compose_runtime` als patchbaren Wrapper und `engine.main` als Entry-Point erhalten.
8. Erst danach interne Produktionsimporte schrittweise auf Owner-Module umstellen; externe und Contract-Tests verwenden weiterhin `engine`.
9. Volle Suite, Ruff, mypy, Sonar und Jenkins ausführen; keine Zwischenlandung mit doppelter aktiver Implementierung.

## runmodel.py

Aktueller Befund: Der Auftrag nennt 1.985 LOC; die aktuell abgefragte lokale Sonar-Instanz meldet **1.924 LOC**. Physisch besitzt [runmodel.py](T:/codebase/claude-agentkit3/src/agentkit/bundles/target_project/tools/agentkit/concept_toolchain/runmodel.py:1) 2.580 Zeilen. Der Unterschied ändert den notwendigen Schnitt nicht.

### Ist-Analyse

Bereits der Modul-Docstring, Z. 1–43, zählt neun Artefaktfamilien auf. Konkret stecken darin:

- **Gemeinsame Fail-closed-JSON-Validierung**, Z. 65–243: `Issue`, `_Ctx`, `_read_json_object`, `_keys`, `_str`, `_int`, `_enum`, `_matched`, `_sha`, `_time`, `_semver`, Objekt-/Listenvalidatoren.
- **Unzusammenhängende Digest- und Namensfunktionen**, Z. 251–457: semantische Request-Digests, Projektions-Digests, Scope-Lock-Namen, TTL, TSV-Digests und Register-Pins.
- **Run-Lifecycle**, Z. 466–723: `BaseRevision`, `RunActor`, `Participant`, `RunState`, `RUN_KEYS`, `load_run_state`.
- **Lease, Runden und Coverage-Plan**, Z. 727–990: `Lease`, `RoundState`, `CoveragePlan` samt Loadern.
- **Promotion und Receipts**, Z. 994–1425: `PromotionManifest`, `ProjectionReceipt`, `DeclassificationReceipt` und deren Untermodelle/Loader.
- **Writer-/Lock-Koordination**, Z. 1428–1668: `IntentState`, `MutexState`, `ScopeLock`, `LockEvidence` samt Loadern.
- **Korpusweites Projektionsmanifest**, Z. 1672–1865: `ProjectionEntry`, `RequiredProjection`, `ProjectionManifest`.
- **Semantische W2/W3-Artefakte**, Z. 1869–2018: `SemanticRequestPack`, `SemanticReceipt`, `SemanticFinding`.
- **TSV-Parser und Registergraph**, Z. 2027–2580: `TsvColumn`, `TsvRow`, `_load_tsv` und Loader für Corpus-Baseline, Source-Intake, Sources, Units, Coverage, Artefakte, Findings, Claims, Dispositionen und Atome.

Die Sprachwechsel sind deutlich: Run/Lease/Round, Promotion/Locks, Projection, Semantic und TSV-Register verwenden jeweils eigenes Vokabular und haben getrennte Konsumenten. `runmodel.py` ist damit eine Kategorieablage für „alle Modelle“, keine einzelne Komponente.

### Schnittvorschlag

| Datei | Verantwortung (1 Satz) | Symbole | ~LOC |
|---|---|---|---:|
| `runmodel_validation.py` | Stellt die einheitliche Fail-closed-Validierung und den gemeinsamen Issue-Typ für alle JSON-Artefakte bereit. | `Issue`, `_Ctx`, `_read_json_object`, `_keys`, `_str`, `_opt_str`, `_int`, `_bool`, `_enum`, `_matched`, `_sha`, `_sha_or_null`, `_time`, `_semver`, `_str_list`, `_obj_items`, `_sub_obj`, `_nullable_obj` | 165 |
| `run_lifecycle.py` | Validiert Zustand, Beteiligte, Runden und exklusiven Writer-Lifecycle eines Council-Runs. | `BaseRevision`, `RunActor`, `DataRelease`, `Participant`, `BlockedInfo`, `RecheckInfo`, `RunState`, `RUN_KEYS`, `load_run_state`; `LeaseOwner`, `Lease`, `LEASE_KEYS`, `load_lease`; `RoundDispatch`, `RoundReceipt`, `RoundParticipant`, `RoundSeal`, `RoundState`, `ROUND_KEYS`, `load_round_state`; `CoveragePackage`, `CoveragePlan`, `COVERAGE_PLAN_KEYS`, `load_coverage_plan`; `IntentState`, `MutexState`, `INTENT_KEYS`, `MUTEX_KEYS`, `load_intent_state`, `load_mutex_state`, `parse_timestamp`, `now_utc`, `timestamp_expired` | 500 |
| `promotion_contracts.py` | Validiert die Beweise, Ziele und Scope-Locks, die eine Promotion autorisieren oder blockieren. | `ScopeBlocker`, `PromotionScope`, `RegistryEdge`, `TestOracle`, `PromotionTarget`, `ScopeLockEntry`, `SemanticGateEntry`, `PromotionManifest`, `MANIFEST_KEYS`, `load_promotion_manifest`; `DeclassificationReceipt`, `DECLASSIFICATION_KEYS`, `load_declassification_receipt`; `ScopeLock`, `SCOPE_LOCK_KEYS`, `load_scope_lock`; `LockEvidenceRef`, `LockEvidence`, `LOCK_EVIDENCE_*`, `load_lock_evidence`; `normalize_scope_id`, `scope_hash`, `scope_lock_filename`, `scope_lock_ref`, `canonical_lock_blob_digest`, `REGISTRY_EDGE_KINDS` | 430 |
| `projection_contracts.py` | Validiert deklarierte Korpusprojektionen und die Receipts ihrer materialisierten Zielpassagen. | `ReceiptTarget`, `ProjectionReceipt`, `RECEIPT_KEYS`, `load_projection_receipt`; `LifecycleSource`, `AssertionSource`, `RequiredProjection`, `ProjectionBlocker`, `ManifestRef`, `ProjectionEntry`, `ProjectionManifest`, `PROJECTION_*`, `TARGET_MODES`, `load_projection_manifest`, `canonical_projection_entry_digest` | 270 |
| `semantic_contracts.py` | Validiert deterministische semantische Request-Packs und die daraus zurückgelieferten W2/W3-Receipts. | `SemanticChunk`, `SemanticRequestPack`, `REQUEST_PACK_KEYS`, `load_semantic_request_pack`; `SemanticFinding`, `SemanticReceipt`, `SEMANTIC_RECEIPT_KEYS`, `load_semantic_receipt`, `canonical_request_digest` | 150 |
| `tsv_validation.py` | Stellt Parser, Zeilenmodell und wiederverwendbare Syntaxprüfungen für den typisierten TSV-Registergraph bereit. | `TsvColumn`, `TsvRow`, `_load_tsv`, `_parse_tsv_row`, `_check_row_order`, `_check_pattern`, `_check_int_value`, `_check_rel_path`, `_check_enum_value`, `check_semicolon_list`, `split_refs`, `decode_tsv_field`, `file_sha256`, `canonical_tsv_subset_digest` | 175 |
| `run_registers.py` | Validiert den auditierten Registergraph eines Runs und berechnet dessen Freeze-/Chain-Digests. | `SOURCE_REGISTER_HEADER`, `SOURCE_UNITS_HEADER`, `CLAIMS_INVENTORY_HEADER`, `SOURCE_INTAKE_HEADER`, `INTAKE_*`; `derive_register_digests`, `intake_entry_digest`, `intake_chain_problems`, `intake_head_digest`, `intake_prefix_head_index`; `load_corpus_baseline`, `load_source_intake`, `load_source_register`, `load_source_units`, `load_source_coverage`, `load_normative_coverage`, `load_artifact_register`, `load_findings_register`, `load_claims_inventory`, `load_disposition_ledger`, `load_atom_register` sowie deren registerfachliche `_check_*`-/Regelfunktionen | 390 |
| `runmodel.py` | Bleibt eine kleine statische Kompatibilitätsfassade für ausgelieferte Zielprojekte. | Re-Exports der expliziten `__all__`-Flächen aller Owner-Module; keine Modelle, Validatoren oder Fachlogik | 30 |

`runmodel_constants.py` bleibt als bestehende Einheit unverändert. Alle neuen Module importieren weiterhin `RunModelConstants as Vocab`; es entsteht weder ein zweites Vokabular noch ein neuer `constants`-/`common`-Topf.

Die Fassade sollte nicht wieder dynamisches `__getattr__` verwenden — genau dieses Muster wurde laut Kommentar in `runmodel_constants.py` bereits wegen `Any`-Typisierung verworfen. Geeignet sind wenige bewusst dokumentierte Re-Exports aus Modulen mit jeweils explizitem `__all__`.

### Abhängigkeitsrichtung

```text
runmodel
  → runmodel_validation
  → run_lifecycle
  → promotion_contracts
  → projection_contracts
  → semantic_contracts
  → tsv_validation
  → run_registers

runmodel_validation
  → runmodel_constants

tsv_validation
  → runmodel_validation
  → runmodel_constants

run_lifecycle
  → runmodel_validation
  → runmodel_constants

promotion_contracts
  → runmodel_validation
  → runmodel_constants
  → run_lifecycle          # BaseRevision und gemeinsame Zeitsemantik

projection_contracts
  → runmodel_validation
  → runmodel_constants

semantic_contracts
  → runmodel_validation
  → runmodel_constants
  → run_lifecycle          # BaseRevision

run_registers
  → tsv_validation
  → runmodel_validation
  → runmodel_constants
```

Kein Owner-Modul importiert `runmodel.py`. Damit ist `runmodel.py` strikt oberhalb der Fachmodule und kann keinen Zyklus verursachen.

Zwei wichtige Cycle-Vermeidungen:

- `derive_register_digests`, `load_source_intake` und `intake_head_digest` bleiben gemeinsam in `run_registers.py`; andernfalls entstünde leicht ein Register-Digest-Kreis.
- `BaseRevision` besitzt `run_lifecycle.py`; Promotion und Semantik dürfen davon abhängen, der Lifecycle importiert diese Artefakte aber nicht zurück.

### Vertragsfläche

Aktuelle Konsumenten:

- `incubator_check.py`: unter anderem `RunState`, `RoundState`, `CoveragePlan`, deren Loader, Promotion-/Receipt-Loader sowie nahezu alle Registerloader und Intake-Digestfunktionen.
- `promotion_check.py`: `PromotionManifest`, `PromotionScope`, `ScopeLockEntry`, `LockEvidenceRef`, `RegistryEdge`, `RunState`, Scope-Namens-/Digestfunktionen und Registerloader.
- `projection_check.py`: `ProjectionManifest`, `ProjectionEntry`, `RequiredProjection`, `ProjectionReceipt`, `PromotionManifest`, deren Loader und `canonical_projection_entry_digest`.
- `semantic_gate.py`: `RunState`, `Lease`, `IntentState`, `PromotionManifest`, `SemanticRequestPack`, `canonical_request_digest` und Source-Registerloader.
- `semantic_status.py`: `SemanticGateEntry`, `SemanticRequestPack`, `SemanticReceipt` und deren Loader.
- `check.py`: direkter Import von `load_projection_manifest`.
- `receipts.py`: direkter Import von `ProjectionReceipt` und `TsvRow`.
- Tests importieren überwiegend `from concept_toolchain import runmodel`; einzelne Tests importieren `Issue` direkt.

Vertrag nach dem Schnitt:

- `from concept_toolchain import runmodel` bleibt gültig.
- Zugriffe wie `runmodel.RunState`, `runmodel.load_run_state`, `runmodel.ProjectionReceipt`, `runmodel.TsvRow`, `runmodel.SOURCE_INTAKE_HEADER` bleiben gültig.
- Direkte Imports wie `from .runmodel import Issue, TsvRow` bleiben gültig.
- `Issue` existiert exakt einmal in `runmodel_validation.py`; sämtliche Loader liefern Instanzen derselben Klasse.
- Die Fassade re-exportiert die bisher fachlich öffentlichen Klassen, Loader, Digests, Header und Key-Konstanten. Zufällig sichtbare stdlib-Imports wie `datetime`, `hashlib` oder `re` sind keine fachliche Vertragsfläche.
- Während der Extraktion brauchen Konsumenten keine Importänderung. Danach sollten die ausgelieferten internen Checker ihre Owner direkt importieren:
  - `semantic_gate/status` → Lifecycle-, Semantic-, Promotion- und Registermodule
  - `projection_check` → Projection-, Promotion- und Registermodule
  - `promotion_check` → Lifecycle-, Promotion- und Registermodule
  - `incubator_check` → Lifecycle-, Promotion- und Registermodule
  - `receipts.py` → `projection_contracts`
  - `check.py` → `projection_contracts`
- Public-Contract-Tests bleiben bewusst auf `runmodel` gerichtet, damit die ausgelieferte Kompatibilitätsfläche nicht unbemerkt schrumpft.

### Risiken

- **Fehlervertrag:** Nicht nur Rückgabemodelle, sondern auch Issue-Reihenfolge, `locator`, Meldungstext und „model is None bei Issues“ werden von Checkern und Tests ausgewertet.
- **Dataclass-Identität:** Ein Re-Export bewahrt Klassenidentität, verändert aber `Class.__module__`. JSON-Artefakte sind der dokumentierte Persistenzvertrag; falls Zielprojekte Modelle pickeln, wäre das ein bisher unsichtbarer Vertrag.
- **Exportmenge:** Ohne heutiges `__all__` muss vor dem Schnitt festgelegt werden, welche Domänensymbole öffentlich sind. Ein AST-basierter Snapshot der tatsächlich konsumierten Namen sollte diese Entscheidung absichern.
- **Konstantendrift:** `RunModelConstants` bleibt SSOT. Keine lokalen Kopien von Regexen oder Enums in den neuen Modulen.
- **Registergrenze:** `run_registers.py` ist fachlich breit, aber kohäsiv: alle Funktionen validieren denselben auditierten Registergraph und seine Freeze-Digests. Eine Trennung nach Dateiformat versus Fachregister erfolgt bereits durch `tsv_validation.py`.
- **Promotion-Grenze:** `DeclassificationReceipt` könnte formal eine eigene Datenklassifikationskomponente begründen. Aktuell wird es jedoch nur als Promotions-/Commit-Beweis konsumiert; eine eigene, sehr kleine Datei wäre nach dem Subkomponentenprinzip eher Überzerlegung.
- **Bundle-Vertrag:** Die Dateien werden ins Zielprojekt ausgeliefert. Installer-, Bundle-Template-, Golden- und stdlib-only-Tests sind daher genauso wichtig wie normale Unit-Tests.
- **Modulebene:** Jede Owner-Datei benötigt ein eigenes explizites `__all__`; insbesondere `runmodel.py` darf nicht zu einer 100+ Zeilen langen manuellen Aliasliste werden.

### Migrationsreihenfolge

1. Einen Export-Snapshot für alle aktuell konsumierten Domänensymbole sowie Contract-Tests für Klassenidentität, Loader-Rückgabeformen, Key-Konstanten und `Issue` anlegen.
2. `runmodel_validation.py` extrahieren; `Issue` und alle JSON-Primitiven sofort aus `runmodel.py` re-exportieren. Gesamte `test_runmodel.py`-/Schema-Suite ausführen.
3. `run_lifecycle.py` einschließlich Intent/Mutex und gemeinsamer Zeitsemantik extrahieren. Lifecycle-, Mutex-Race-, Bundle-Template- und Incubator-Tests ausführen.
4. `projection_contracts.py` und `semantic_contracts.py` nacheinander extrahieren. Nach jedem Schritt Projection- beziehungsweise Semantic-Gate-/Status-Tests ausführen.
5. `promotion_contracts.py` einschließlich Scope-Lock und Lock-Evidence extrahieren. Promotion-, Remote-Lock-, Projection- und Incubator-Tests ausführen.
6. `tsv_validation.py` extrahieren, während die konkreten Registerloader zunächst noch gemeinsam bleiben; danach TSV-Negativpfade und Issue-Reihenfolge prüfen.
7. `run_registers.py` samt `derive_register_digests` und Intake-Chain geschlossen extrahieren. Intake-Freeze-, Runmodel-, Incubator- und Promotion-Tests ausführen.
8. `runmodel.py` auf die statische Kompatibilitätsfassade reduzieren und anschließend die internen Checker auf ihre Owner-Module umstellen.
9. Vollständige Bundle-/Installer-/Contract-Suite, Ruff, mypy, Sonar und Jenkins ausführen; erst dann landen.

## Selbsteinschätzung

Am ehesten angreifbar sind zwei Entscheidungen:

- Bei `engine.py` bleibt `WeaviateCorpusStore` als zusammengesetzte Fassade erhalten. Ein radikalerer Schnitt könnte auch `CorpusStorePort` zerlegen; das halte ich derzeit für schlechter, weil `SyncService` Claim, Corpus-Mutation und Completion als einen zusammengehörigen Sync-Persistenzvertrag benötigt.
- Bei `runmodel.py` verbleiben alle konkreten TSV-Register in `run_registers.py`. Sollte sich zeigen, dass Source-Freeze und Synthesis-/Atom-Register unabhängig weiterentwickelt werden, wäre eine spätere Teilung in `source_registers.py` und `decision_registers.py` gerechtfertigt. Der jetzige Call-Graph und die gemeinsamen Freeze-Digests sprechen zunächst für Zusammenhalt.

Read-only-Gatebefund: Der Worktree ist unverändert. Sonar steht erwartungsgemäß auf **ERROR** mit genau den beiden kritischen LOC-Verstößen (`engine.py` 1.577, `runmodel.py` aktuell 1.924) und sonst `security_hotspots=0`. Der Jenkins-Status ließ sich nicht verifizieren: Die lokale Instanz verlangt entgegen der dokumentierten Unsecured-Konfiguration Authentifizierung, während die geladenen Platzhalter-Credentials mit 401 abgewiesen werden. Es wurden keine Dateien verändert.
