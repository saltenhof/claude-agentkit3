# AG3-181 — Einbettungsmodell vollstaendig: Tokenizer, Chunk-Budgets, Fensterwahrheit

- **Typ:** implementation
- **Groesse:** M
- **Betroffen:** `resources/tokenizer/`, `concepts/chunking.py`, `concepts/tokenizer.py`, `backend/vectordb/`, FK-13
- **Herkunft:** Modellwechsel auf bge-m3 am 2026-08-02 (bewusst als Teilschnitt gelandet).

## Befund

Der Modellpin steht seit 2026-08-02 auf `BAAI/bge-m3`, die Pooling-Strategie
leitet sich daraus ab, und `cp_10` ist gruen. **Zwei Teile des Vertrags sind
dabei bewusst offen geblieben** und im Decision Record §2.3 benannt.

**Das Tokenizer-Asset passt nicht zum Modell.** Unter
`src/agentkit/resources/tokenizer/` liegt ein gebundenes Paket-Asset mit
gepinnten Digests: `tokenizer.json` (466 KB), `vocab.txt` (231 KB), zwei
`.sha256`, dazu `ASSET.md` mit Modell, Revision und Lizenz. Es ist
**WordPiece mit 30 522 Token** (all-MiniLM-L6-v2, BERT-Familie). bge-m3 ist
**SentencePiece mit rund 250 000 Token**. Das Asset dient der deterministischen,
modellrichtigen Chunk-Groessenrechnung — genau die stimmt damit nicht mehr.

Wirkung ausschliesslich auf die Groessenrechnung beim Ingest, **nie** auf die
serverseitige Einbettung; die macht der Sidecar mit dem echten Modell. Es ist
deshalb kein Datenfehler, aber eine falsche Bemessungsgrundlage.

**Es gibt keine Bindung zwischen Modell und Tokenizer.** `FK13_EMBEDDING_MODEL`
(`backend/vectordb/schema.py`) und `PINNED_MODEL` (`concepts/tokenizer.py`) sind
zwei unabhaengige Konstanten. Kein Digest-, kein Konsistenzcheck verbindet sie;
der vorhandene Digest prueft das Asset nur gegen sich selbst. Genau deshalb
konnte der Modellpin wandern, ohne dass irgendetwas anschlug.

**Vermutung, die zu klaeren ist:** `DEFAULT_MAX_TOKENS = 1000`
(`concepts/chunking.py`) wird mit dem MiniLM-Tokenizer gemessen. MiniLMs Fenster
ist 256 bis 512 Token. Wenn der Sidecar bei Fensterende abschneidet, ist der
Schwanz jedes Chunks zwischen 512 und 1000 Token **seit jeher still verloren
gegangen**. Das ist **nicht verifiziert**: weder das Abschneideverhalten des
Sidecars noch die Modellkonfiguration im laufenden Container wurden geprueft.
Mit bge-m3 und 8192 Token ist der Fall entschaerft — die Frage bleibt, ob
Bestandsdaten davon betroffen sind.

## Akzeptanzkriterien

1. **Das Tokenizer-Asset gehoert zum gepinnten Modell.** `tokenizer.json`,
   Digests, `ASSET.md` (Modell, Revision, Lizenz — bge-m3 ist MIT, nicht
   Apache-2.0) sind auf bge-m3 gezogen. Die `vocab.txt` in ihrer heutigen Rolle
   entfaellt oder wird durch das ersetzt, was das SentencePiece-Format
   tatsaechlich braucht — kein Karteileichen-Mitschleppen.
2. **Modell und Tokenizer koennen nicht mehr auseinanderdriften.** Es existiert
   genau eine Stelle, aus der beide folgen, oder eine fail-closed Pruefung, die
   den Lauf abbricht, wenn sie nicht zusammenpassen. Ein Test dreht den Pin
   zurueck und ist rot.
3. **Die Fenstervermutung ist beantwortet, nicht umgangen.** Gemessen am
   laufenden Sidecar: schneidet er bei Fensterende ab, ja oder nein? Das
   Ergebnis steht mit Kommando und Ausgabe im Story-Record. Bei „ja" ist
   zusaetzlich beantwortet, ob Bestandsdaten betroffen sind und was daraus folgt.
4. **`DEFAULT_MAX_TOKENS` folgt dem Modellfenster**, statt danebenzustehen.
   Steht dort weiterhin eine feste Zahl, ist im Code begruendet, warum sie
   unterhalb des Fensters bleibt und wer sie besitzt.
5. **FK-13 besitzt Tokenizer und Chunk-Budget**, so wie es seit 2026-08-02
   Modell und Pooling besitzt. Ein Wert, der die Bemessung jedes Chunks bestimmt,
   lebt nicht ohne Eigentuemer im Code.
6. **Ein Live-Lauf gegen das echte Weaviate** belegt die Umstellung: Ingest,
   Chunk-Groessen im erwarteten Bereich, Suche liefert Treffer. Gruene
   Unit-Tests reichen dafuer nicht (PO-Grundregel „Realitaetsnachweis an
   Fremdsystem-Grenzen").
7. Decision Record vorhanden; der Teilschnitt aus dem Record vom 2026-08-02 §2.3
   ist darin als geschlossen ausgewiesen.

## Abgrenzung

Kein weiterer Modellwechsel und keine Modellauswahl — bge-m3 ist gesetzt. Diese
Story schliesst den Vertrag um das bereits gewaehlte Modell.

Der Qualitaetsnachweis des Modellwechsels (Retrieval vorher/nachher auf dem
eigenen Korpus) gehoert zu AG3-183, nicht hierher.
