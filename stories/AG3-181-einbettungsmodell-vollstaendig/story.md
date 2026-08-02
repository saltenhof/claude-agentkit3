# AG3-181 — Einbettungsmodell vollstaendig: Tokenizer, Budgetformel, Re-Ingest

- **Typ:** implementation
- **Groesse:** L
- **Abhaengigkeiten:** `depends_on: []`; entblockt AG3-190
- **Quell-Konzept:** FK-13 §13.2 (Modellpin, Pooling), FK-13 §13.1
  (Pflicht-Dependencies)
- **Herkunft:** Modellwechsel auf bge-m3 am 2026-08-02 (Commit `8d80586a`),
  bewusst als Teilschnitt gelandet; Decision Record
  `concept/_meta/decisions/2026-08-02-modellpin-folgt-der-laufenden-infrastruktur.md`
  §2.3 benennt die offenen Teile. Neu geschnitten am 2026-08-02 nach
  unabhaengigem Codex-Review (Auflagen ERROR-7 und ERROR-8).

## Kontext

### Befund — belegt, mit Locator

Der Modellpin steht seit 2026-08-02 auf `BAAI/bge-m3`
(`src/agentkit/backend/vectordb/schema.py:381`), die Pooling-Strategie leitet
sich daraus ab (`:415`), und `cp_10` ist gruen. **Zwei Teile des Vertrags sind
dabei bewusst offen geblieben.**

**Das Tokenizer-Asset passt nicht zum Modell.** Unter
`src/agentkit/resources/tokenizer/` liegt ein gebundenes Paket-Asset mit
gepinnten Digests: `tokenizer.json`, `vocab.txt`, zwei `.sha256`, dazu
`ASSET.md` und `LICENSE.apache-2.0.txt`. Es ist **WordPiece mit 30 522 Token**
(all-MiniLM-L6-v2, BERT-Familie). bge-m3 ist **SentencePiece mit rund
250 000 Token**. Das Asset dient der deterministischen, modellrichtigen
Chunk-Groessenrechnung — genau die stimmt damit nicht mehr.

Wirkung ausschliesslich auf die Groessenrechnung beim Ingest, **nie** auf die
serverseitige Einbettung; die macht der Sidecar mit dem echten Modell. Es ist
deshalb kein Datenfehler, aber eine falsche Bemessungsgrundlage.

**Es gibt keine Bindung zwischen Modell und Tokenizer.**
`FK13_EMBEDDING_MODEL` (`backend/vectordb/schema.py:381`) und `PINNED_MODEL`
(`concepts/tokenizer.py:39`, heute
`"sentence-transformers/all-MiniLM-L6-v2"`) sind zwei unabhaengige Konstanten.
Kein Digest-, kein Konsistenzcheck verbindet sie; der vorhandene Digest prueft
das Asset nur gegen sich selbst. Genau deshalb konnte der Modellpin wandern,
ohne dass irgendetwas anschlug.

**Vermutung, die zu klaeren ist:** `DEFAULT_MAX_TOKENS = 1000`
(`concepts/chunking.py:20`) wird mit dem MiniLM-Tokenizer gemessen. MiniLMs
Fenster ist 256 bis 512 Token. Wenn der Sidecar bei Fensterende abschneidet,
ist der Schwanz jedes Chunks zwischen 512 und 1000 Token **seit jeher still
verloren gegangen**. Das ist **nicht verifiziert**: weder das
Abschneideverhalten des Sidecars noch die Modellkonfiguration im laufenden
Container wurden geprueft. Mit bge-m3 und 8192 Token ist der Fall entschaerft —
die Frage bleibt, ob Bestandsdaten davon betroffen sind.

### Was am ersten Schnitt falsch war

Vier Dinge. Drei davon sind billige Wege, die das Kriterium formal erfuellen und
das Problem bestehen lassen:

1. **`depends_on` stand falsch herum.** Die Story haengte an AG3-183, obwohl
   AG3-183 den Modellwechsel **bewerten** sollte, dessen Vertrag erst hier
   entsteht. Eine Qualitaetsmessung „nachher" waere gegen einen halb migrierten
   Zustand gelaufen. Die Kante ist umgedreht: der Nachweis ist nach **AG3-190**
   ausgezogen und haengt **an** dieser Story.
2. **Kein Re-Ingest.** Der Decision Record vom 2026-08-02 verlangt Tokenizer,
   Chunk-Budgets und Re-Ingest als **Verbund**. Der Schnitt verlangte nur
   „Ingest" und „Treffer". Wechselt die Bemessungsgrundlage, bleiben die alten
   Chunks aber stehen, ist die Collection danach eine Mischung aus zwei
   Chunkings — und die Suche liefert weiter Treffer.
3. **„Chunk-Groessen im erwarteten Bereich" hat keinen Zahlenbereich.** Ein
   Kriterium ohne Zahl ist durch jede Beobachtung erfuellbar.
4. **Das Budget deckte nur den Body ab.** Eingebettet werden nicht nur
   `content`, sondern alle Felder aus `FK13_VECTOR_SOURCE_PROPERTIES`
   (`backend/vectordb/schema.py:428`, abgeleitet aus den als `vectorized`
   deklarierten Schema-Properties — heute `content`, `title`,
   `section_heading`). Dazu kommen die Special Tokens des Modells. Ein Budget,
   das nur den Body bemisst, unterschaetzt die tatsaechliche Sequenzlaenge
   systematisch.

## Scope

### In Scope

- Tokenizer-Asset auf bge-m3 ziehen, inklusive Revision, Lizenz und Digests.
- Eine fail-closed Bindung zwischen Modellpin und Tokenizerpin.
- Eine ausgeschriebene Budgetformel ueber **alle** eingebetteten Felder
  inklusive Special Tokens und Sicherheitsmarge.
- Beantwortung der Fenster-/Abschneidefrage am laufenden Sidecar.
- Vollstaendiger Re-Ingest ohne Altchunks, mit Read-back.
- FK-13 als Eigentuemer von Tokenizer-Revision und Chunk-Budget; Decision Record.

### Out of Scope

- **Kein weiterer Modellwechsel und keine Modellauswahl** — bge-m3 ist gesetzt.
  Diese Story schliesst den Vertrag um das bereits gewaehlte Modell.
- Der **Retrieval-Qualitaetsnachweis** des Modellwechsels (vorher/nachher auf
  dem eigenen Korpus) — **AG3-190**, und zwar *danach*, nicht davor.
- Die Fremdsystem-Vertragsmatrix und die CI-Verankerung des Live-Laufs —
  **AG3-183** / **AG3-194**.

## Betroffene Dateien

| Pfad | Aenderungsart | Warum |
|---|---|---|
| `src/agentkit/resources/tokenizer/tokenizer.json` (+ `.sha256`) | ersetzt | SentencePiece-Tokenizer von bge-m3 statt WordPiece |
| `src/agentkit/resources/tokenizer/vocab.txt` (+ `.sha256`) | entfernt oder ersetzt | WordPiece-Vokabular; kein Karteileichen-Mitschleppen |
| `src/agentkit/resources/tokenizer/ASSET.md` | geaendert | Modell, exakte Revision, Lizenz (bge-m3 ist MIT, nicht Apache-2.0) |
| `src/agentkit/resources/tokenizer/LICENSE.apache-2.0.txt` | ersetzt | Lizenztext folgt dem Modell |
| `src/agentkit/concepts/tokenizer.py` | geaendert | `PINNED_MODEL` folgt dem Modellpin; fail-closed Konsistenzpruefung |
| `src/agentkit/concepts/chunking.py` | geaendert | Budgetformel statt freistehender Konstante |
| `src/agentkit/backend/vectordb/schema.py` | geaendert | Modellpin als einzige Quelle, aus der der Tokenizerpin folgt |
| `concept/technical-design/13_retrieval_vektordb_wissenszugriff.md` | geaendert | FK-13 besitzt Tokenizer-Revision und Chunk-Budget |
| `concept/_meta/decisions/2026-XX-XX-tokenizer-und-chunkbudget.md` | neu | Decision Record; schliesst §2.3 des Records vom 2026-08-02 |
| `tests/unit/concepts/` | geaendert | Budgetformel, Grenzkorpus, Pin-Bindung |
| `tests/e2e/vectordb/` | neu | Re-Ingest und Read-back gegen echtes Weaviate |

## Akzeptanzkriterien

1. **Das Tokenizer-Asset gehoert zum gepinnten Modell.** `tokenizer.json`,
   Digests und `ASSET.md` (Modell, **exakte Revision**, Lizenz) sind auf bge-m3
   gezogen. Die `vocab.txt` in ihrer heutigen Rolle entfaellt oder wird durch
   das ersetzt, was das SentencePiece-Format tatsaechlich braucht — kein
   Karteileichen-Mitschleppen. Der Lizenztext im Verzeichnis passt zum Modell.
2. **Modell und Tokenizer koennen nicht mehr auseinanderdriften.** Es existiert
   genau eine Stelle, aus der beide folgen, oder eine fail-closed Pruefung, die
   den Lauf abbricht, wenn sie nicht zusammenpassen. Die Pruefung bindet
   ausdruecklich auch die **Revision**, nicht nur den Modellnamen — ein
   Revisionswechsel bei gleichem Namen aendert das Vokabular. Ein Test dreht
   den Pin zurueck und ist rot.
3. **Die Budgetformel ist ausgeschrieben und deckt alles ab, was eingebettet
   wird.** Sie rechnet ueber **alle** Felder aus
   `FK13_VECTOR_SOURCE_PROPERTIES` (heute `content`, `title`,
   `section_heading`), ueber die Special Tokens des Modells und ueber eine
   benannte Sicherheitsmarge. Die Formel steht im Konzept mit ihren Groessen,
   nicht nur als Zahl im Code. Ein Test rechnet sie fuer ein konstruiertes
   Dokument nach.
4. **Ein Grenzkorpus belegt beide Seiten der Schwelle.** Es existieren
   Testdokumente knapp **unterhalb** und knapp **oberhalb** des Limits; das
   Verhalten ist fuer beide festgelegt und gemessen. Ein Korpus, der nur weit
   unter dem Limit liegt, erfuellt dieses Kriterium nicht.
5. **`DEFAULT_MAX_TOKENS` folgt dem Modellfenster**, statt danebenzustehen.
   Steht dort weiterhin eine feste Zahl, ist im Code **und im Konzept**
   begruendet, warum sie unterhalb des Fensters bleibt und wer sie besitzt.
6. **Die Fenstervermutung ist beantwortet, nicht umgangen.** Gemessen am
   laufenden Sidecar: schneidet er bei Fensterende ab, ja oder nein? Das
   Ergebnis steht mit Kommando und Ausgabe im Story-Record. Bei „ja" ist
   zusaetzlich beantwortet, ob Bestandsdaten betroffen sind und was daraus folgt.
7. **Vollstaendiger Re-Ingest ohne Altchunks.** Nach der Umstellung enthaelt die
   Collection **keinen** Chunk mehr, der nach der alten Bemessung erzeugt wurde.
   Nachgewiesen durch Read-back gegen das laufende Weaviate: die
   **tatsaechliche Chunkmenge** wird ausgelesen und gegen die aus dem Korpus
   berechnete Erwartung verglichen — Anzahl **und** Groessenverteilung. „Die
   Suche liefert Treffer" erfuellt dieses Kriterium nicht.
8. **Der Live-Lauf gegen das echte Weaviate ist Abnahmekriterium**, nicht
   Opt-in (PO-Grundregel „Realitaetsnachweis an Fremdsystem-Grenzen"). Faellt er
   aus, ist das eine **benannte Luecke** mit Grund — nie „gruen".
9. **FK-13 besitzt Tokenizer-Revision und Chunk-Budget**, so wie es seit
   2026-08-02 Modell und Pooling besitzt. Ein Wert, der die Bemessung jedes
   Chunks bestimmt, lebt nicht ohne Eigentuemer im Code.
10. **Decision Record vorhanden**; der Teilschnitt aus dem Record vom
    2026-08-02 §2.3 ist darin als geschlossen ausgewiesen. Alle
    deterministischen Konzept-Gates gruen.

## Definition of Done

- AC 1–10 erfuellt, jedes mit benanntem Beleg (Kommando, Ausgabe, Testname).
- Live-Lauf gegen ein laufendes Weaviate gefahren; Kommando, Ausgabe und
  Read-back-Zahlen liegen im Story-Record.
- `.venv\Scripts\python -m pytest` gruen; `ruff check src tests` clean;
  `mypy src --strict` gruen fuer `win32`, `linux` und `darwin`.
- Coverage haelt die 85-%-Schwelle.
- Alle deterministischen Konzept-Gates gruen; Decision Record im Diff oder
  gueltiger `Concept-Decision`-Trailer.
- Unabhaengiges Codex-Review bis zum Abbruchkriterium aus `CLAUDE.md`.

## Konzept-Referenzen

- `concept/technical-design/13_retrieval_vektordb_wissenszugriff.md` §13.1
  (Pflicht-Dependencies), §13.2 (Modellpin, Pooling, Tokenizer-Asset)
- `concept/_meta/decisions/2026-08-02-modellpin-folgt-der-laufenden-infrastruktur.md`
  §2.3 — die hier zu schliessenden Teilschnitte
- `concept/_meta/decisions/2026-08-02-pooling-strategie-folgt-dem-einbettungsmodell.md`

## Guardrail-Referenzen

- `CLAUDE.md` „REALITAETSNACHWEIS AN FREMDSYSTEM-GRENZEN" — AC 6, AC 7, AC 8.
  Der belegte Anlassfall ist genau dieser Pfad.
- `CLAUDE.md` „FIX THE MODEL, NOT THE SYMPTOM" — AC 2 und AC 5: keine zweite
  Wahrheit ueber das Modell.
- `CLAUDE.md` „ZERO DEBT RULE" — kein Karteileichen-Mitschleppen (AC 1).
- `CLAUDE.md` „FAIL-CLOSED" — AC 2.
