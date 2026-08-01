# Zerlegung `engine.py` + `runmodel.py` — Abgleich zweier unabhaengiger Vorschlaege

PO-Auftrag 2026-07-31: zwei Analysten (Codex, Opus) schlagen unabhaengig eine
**fachliche** Zerlegung vor; beide mit wortgleichem Briefing und beide mit dem
Component-Architecture-Skill als Handwerkszeug. Bei starker Korrelation wird die
Umsetzung beauftragt, bei starker Divergenz ist zu klaeren, warum.

Vollstaendiger Codex-Vorschlag: `split-proposal-codex.md`.

## Ergebnis: starke Korrelation in der Sache, zwei klar benennbare Divergenzen

### `engine.py` — Schnittkanten praktisch deckungsgleich

| Verantwortung | Codex | Opus |
|---|---|---|
| Clientvertrag | `client_port.py` (70) | `client_port.py` (63) |
| Completion-Ledger | `completion_ledger.py` (570) | `completion_ledger.py` (553) |
| Record-Serialisierung/Parsing | `sync_record_codec.py` (430) | `completion_records.py` (336) |
| Source-Generationsleiter | `source_claims.py` (230) | `source_generation.py` (206) |
| Objektlebenszyklus | `corpus_objects.py` (130) | *in* `corpus_store.py` |
| Store-Fassade | `corpus_store.py` (170) | `corpus_store.py` (145) |
| Retrieval + Frische | `retrieval.py` (125) | `retrieval.py` (96) |
| Collection-Provisionierung | *in* `runtime.py` | `provisioning.py` (44) |
| Komposition + Entry | `runtime.py` (155) + Fassade (75) | `engine.py` (85) |
| Geteilte Feldleser | — | `record_fields.py` (26) |

Beide schneiden an denselben Stellen: der Wechsel von *object/chunk* zu
*receipt/run/sequence* und weiter zu *claim/generation/owner*. Opus belegt das
zusaetzlich am Vokabularwechsel (Zeilen 382 und 951) und misst, dass
`WeaviateCorpusStore` mit **790 LOC** ohnehin an der ebenfalls geltenden
800-LOC-Klassengrenze steht — die Klasse ist das eigentliche Problem, nicht die
Datei.

### `runmodel.py` — dieselben Cluster, Opus feiner

| Verantwortung | Codex | Opus |
|---|---|---|
| Feldvalidierung | `runmodel_validation.py` (165) | `runmodel_validation.py` (135) |
| TSV-Grammatik | `tsv_validation.py` (175) | `runmodel_tsv.py` (135) |
| Konkrete Register | `run_registers.py` (390) | `runmodel_registers.py` (281) |
| Register-Pins | *in* `run_registers.py` | `runmodel_pins.py` (83) |
| Lauf in Flight | `run_lifecycle.py` (500) | `runmodel_run.py` (422) |
| Exklusivzugriff (Mutex/Lock) | *in* `run_lifecycle.py` | `runmodel_locks.py` (174) |
| Promotion | `promotion_contracts.py` (430) | `runmodel_promotion.py` (353) |
| Projektion | `projection_contracts.py` (270) | `runmodel_projection.py` (149) |
| Semantik-Gate | `semantic_contracts.py` (150) | `runmodel_semantic.py` (124) |
| Digests/Scope-Namen | *nicht separiert* | `runmodel_digests.py` (56) |

Opus stuetzt den Schnitt zusaetzlich empirisch: die JSON-Sektion und die
TSV-Sektion referenzieren einander **null Mal**, und die 27 Modellklassen der
JSON-Sektion haben **null Querbezuege** — vollstaendige Symbolinventur, keine
Stichprobe. Unabhaengige Bestaetigung: die 13 ausgelieferten JSON-Schemas unter
`concept_toolchain/schemas/` mappen 1:1 auf dieselben Cluster.

## Divergenz 1 — Kompatibilitaetsfassade: ja oder nein

- **Codex**: Fassade behalten (`engine.py` 75 LOC, `runmodel.py` 30 LOC). Nimmt
  Migrationsdruck von den Konsumenten.
- **Opus**: keine Fassade, Konsumenten migrieren. Drei Argumente: Praezedenz
  (`runmodel_constants.py` wurde ohne Durchreichung extrahiert), das
  Modul-Level-Limit, und der bereits verworfene dynamische `__getattr__`.

**Empirisch geprueft** (Orchestrator): eine Re-Export-Fassade ueber 80 Namen
ergibt nach `ruff format` **92 Modul-Level-Zeilen** — sie passt unter das
100er-Limit. Opus' zweites Argument traegt also **nicht**; Opus hatte es selbst
als unverifiziert markiert.

Aber: 8 Zeilen Luft. Jeder weitere exportierte Name bringt die Fassade an die
Grenze, und dann steht dieselbe Diskussion erneut an. Das spricht gegen die
Fassade als Dauerloesung — nicht weil sie heute bricht, sondern weil sie auf
Kante gebaut waere.

Beachtenswert: die Konsumentenlage ist in den beiden Modulen **verschieden**.
Bei `engine.py` importieren alle 12 Stellen **namentlich** — die Migration ist
ein reiner Pfadwechsel. Bei `runmodel.py` binden alle 16 Konsumenten das
**Modul** (`from . import runmodel`) mit ~250 Aufrufstellen ueber 80 Namen. Die
Fassadenfrage ist damit nicht einmal dieselbe Frage.

## Divergenz 2 — Granularitaet

Opus schneidet feiner: Pins, Locks und Digests je eigenstaendig; dazu zwei
Kleinstmodule (`record_fields.py` 26, `provisioning.py` 44). Opus benennt das
selbst als Regelverstoss gegen den Size-Check des Skills und begruendet, warum
die Alternative (Duplikation oder eine Rueckkante) schlechter waere.

Codex haelt Locks beim Lauf-Lifecycle und Pins bei den Registern — mit dem
Argument gemeinsamer Freeze-Digests und des heutigen Call-Graphen.

## Was beide unabhaengig als eigentliche Frage benennen

**Beide** markieren dieselbe Stelle als das, was sie bewusst NICHT angefasst
haben:

> Codex: „Ein radikalerer Schnitt koennte auch `CorpusStorePort` zerlegen; das
> halte ich derzeit fuer schlechter, weil `SyncService` Claim, Corpus-Mutation
> und Completion als einen zusammengehoerigen Sync-Persistenzvertrag benoetigt."

> Opus: „Nicht vorgeschlagen, obwohl es der sauberere Zug waere: die Zerlegung
> von `CorpusStorePort` … Der Port buendelt heute drei Verantwortungen und
> zwingt mir die Delegationsschicht in `WeaviateCorpusStore` auf. … Wenn der PO
> den Schnitt ‚richtig' will statt nur Sonar-konform, ist das die Frage, die
> zuerst zu klaeren ist."

Zwei unabhaengige Analysten kommen auf dieselbe verdeckte Kopplung und auf
dieselbe Begruendung, sie in diesem Auftrag nicht zu loesen. Das ist der
belastbarste Befund des ganzen Abgleichs: `CorpusStorePort` (FK-13, `sync.py`)
buendelt drei Verantwortungen, und deshalb braucht der `engine.py`-Schnitt eine
Fassadenklasse statt dreier gleichrangiger Komponenten.

Ebenso benennen **beide** denselben schwaechsten Punkt ihres eigenen
Vorschlags: den Lauf-Lifecycle-Cluster (Codex 500 LOC, Opus 422 LOC) mit der
Frage, ob die Lease dorthin oder zu den Locks gehoert.

## Bewertung

Die Vorschlaege korrelieren in der Sache stark: identische Schnittkanten,
identische Zyklusanalyse, identische Selbstkritik. Die Divergenzen sind zwei
saubere Entscheidungen, keine widerspruechlichen Weltbilder.

Empfehlung fuer die Umsetzung:

1. **Schnittkanten nach Opus** — feiner, empirisch belegt (Symbolinventur,
   Vokabularwechsel, Schema-Mapping), und er haelt zusaetzlich die
   800-LOC-Klassengrenze ein, die Codex gar nicht adressiert.
2. **Keine Fassade — auch keine temporaere.** (PO-Entscheidung 2026-08-01.)
3. **`CorpusStorePort`-Zerlegung NICHT** in dieser Arbeit. Sie ist eine
   Konzeptaenderung an FK-13 und gehoert vor den PO, nicht in einen LOC-Split.
   Als Folgethema erfassen.

## Nachtrag 2026-08-01 — die Fassadenfrage ist gegenstandslos

Der PO hat die Praemisse hinterfragt: AK3 wird from scratch gebaut und ist
nirgendwo im Einsatz. Nachgeprueft:

- `engine.py`: 26 Importstellen, **alle in diesem Repo**.
- `runmodel.py`: 20 Importstellen, **alle in diesem Repo**.
- Das Zielprojekt ruft ausschliesslich **Skripte** ueber Pfad auf
  (`python tools/agentkit/concept_toolchain/check.py`, `semantic_gate.py`) —
  **kein** Modulimport von aussen. Diese Pfade aendern sich durch den Schnitt
  nicht. Beim Upgrade wird das Verzeichnis per `rglob` vollstaendig ersetzt;
  es gibt kein Manifest, das Dateinamen festnagelt.

Eine Kompatibilitaetsfassade wuerde damit **niemanden** schuetzen. Sie wuerde
nur verhindern, dass wir Aufrufstellen im eigenen Repo umbenennen — Arbeit
sparen jetzt gegen eine dauerhafte Indirektionsschicht spaeter. Das ist Schuld
ohne Gegenwert.

Auch die *temporaere* Fassade faellt weg: jede Extraktion laeuft als EIN Commit,
der Verschiebung und betroffene Aufrufstellen zusammen enthaelt. Dann ist jeder
Zwischenstand gruen, ohne dass je eine Fassade existiert. Der Unterschied ist
allein, wie oft dieselben Dateien angefasst werden — ein Komfortargument, kein
Qualitaetsargument.

Damit entfaellt auch die empirische Messung oben (92/100 Modul-Level-Zeilen) als
Entscheidungsgrundlage: die Frage ist nicht, ob eine Fassade ins Limit passt,
sondern ob sie ueberhaupt einen Zweck hat. Sie hat keinen.
