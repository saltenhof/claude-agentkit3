---
concept_id: META-DEC-2026-08-02-POOLING-STRATEGIE-FOLGT-DEM-EINBETTUNGSMODELL
title: Concept-Decision-Record — Die Pooling-Strategie folgt dem Einbettungsmodell und hat einen Eigentuemer
module: meta
cross_cutting: true
status: active
doc_kind: decision-record
authority_over: []
defers_to: []
supersedes: []
superseded_by:
tags: [meta, decision-record, vectordb, retrieval, embedding, FK-13, FK-93]
formal_scope: prose-only
---

# Concept-Decision-Record — Die Pooling-Strategie folgt dem Einbettungsmodell und hat einen Eigentuemer

Datum: 2026-08-02.

## 1. Anlass

`backend/vectordb/schema.py` pinnte `"poolingStrategy": "masked_mean"` als frei
stehende Konstante. FK-13 sagte zu Pooling **nichts** — der Wert hatte keinen
normativen Eigentuemer und existierte nur im Code.

Damit ist er genau das, was an diesem Tag schon zweimal aufgefallen ist: eine
Zahl ohne Eigentuemer, die beim naechsten Wechsel unbemerkt veraltet. Beim Port
`9080` war es eine Portmigration, die den Installer nie erreichte. Hier ist es
ein Modellwechsel der Infrastruktur, den der Code nie nachvollzogen hat.

Die Besonderheit macht ihn schlimmer als den Port: **eine falsche
Pooling-Strategie wirft keinen Fehler.** Sie aggregiert jede Einbettung falsch
und aeussert sich ausschliesslich in schlechteren Treffern. Ein kaputter Port
faellt beim ersten Aufruf auf; eine falsche Pooling-Strategie faellt nie auf.

## 2. Entscheidung

**2.1 Die Pooling-Strategie ist kein Parameter, sondern eine Modelleigenschaft.**
Sie wird aus dem gepinnten Einbettungsmodell **abgeleitet**
(`schema.pooling_strategy_for`), nicht daneben gesetzt. Es gibt keine Stelle
mehr, an der man sie unabhaengig vom Modell aendern koennte — die einzige
Eingabe ist `FK13_EMBEDDING_MODEL`.

**2.2 Ein unbekanntes Modell faellt fail-closed.** Die Ableitungstabelle kennt
`sentence-transformers/all-MiniLM-L6-v2` -> `masked_mean` und `BAAI/bge-m3` ->
`cls`. Fuer ein nicht eingetragenes Modell wird **nicht geraten**; der Aufruf
bricht ab. Eine geratene Strategie waere ein stiller Qualitaetsverlust, und
still ist hier der teure Teil.

**2.3 Modell und Strategie haben einen Eigentuemer im Konzept.** FK-13 §13.2
fuehrt beide, samt Ableitungstabelle und der Aussage, dass `vectorizeClassName`
immer `false` bleibt. Der Wert ist extern wahrnehmbar — ein Betreiber merkt ihn
an schlechteren Treffern — und faellt damit unter das FK-93-Aufnahmekriterium:
Katalogeintrag mit Eigentuemer-Kante statt Code-Konstante.

**2.4 Ein Modellwechsel ist kein Einzeiler.** Modell, Tokenizer-Asset samt
gepinntem Digest und die Ingest-Chunk-Budgets sind ein Verbund: die Budgets
werden mit dem Tokenizer *dieses* Modells und gegen *dessen* Kontextfenster
gerechnet. Wer das Modell wechselt, zieht alle drei im selben Zug nach und
ingestet den Korpus neu.

## 3. Was NICHT entschieden wurde — und warum

**Ob AK3 auf `BAAI/bge-m3` wechselt.** Die laufende Infrastruktur fuehrt
inzwischen den Sidecar `vectordb-text2vec-bge-m3:local`, waehrend FK-13 §13.2
`sentence-transformers/all-MiniLM-L6-v2` pinnt. Der Konflikt ist real und
belegt; er wird hier **benannt, nicht implizit entschieden**.

Nur die Pooling-Strategie auf `cls` zu stellen waere der falsche Schnitt: das
mitgelieferte Tokenizer-Asset ist WordPiece mit 30 522 Tokens (BERT/MiniLM),
bge-m3 nutzt SentencePiece mit rund 250 000 Tokens und ein Kontextfenster von
8192 statt 512. Die Chunk-Budgets des Ingests rechnen gegen das kleine Fenster.
Ein Umstellen der Strategie allein ergaebe einen halb migrierten Zustand —
`cls`-Pooling auf einem Korpus, der fuer MiniLM gechunkt wurde. Das ist der
Zustand, den ZERO DEBT ausschliesst.

Der Wechsel gehoert deshalb in eine eigene, geschnittene Story (Tokenizer-Asset
+ Digest + Chunk-Budgets + Re-Ingest). Bis dahin bleibt der Pin auf MiniLM, und
die Abweichung zur Infrastruktur wird vom Adapter **fail-closed erkannt**
(`weaviate_adapter._verify_existing_collection` meldet die Modelldrift und
bricht ab) — sie ist sichtbar, nicht stillschweigend geduldet.

**Nachtrag (2026-08-02, noch am selben Tag):** Die hier offen gelassene Frage ist
entschieden — der Pin steht auf `BAAI/bge-m3`. Massgeblich ist ab sofort
`2026-08-02-modellpin-folgt-der-laufenden-infrastruktur.md`; die dortige 2.3
begruendet, warum Tokenizer-Asset und Chunk-Budgets in einem zweiten, benannten
Schnitt folgen. Die Entscheidungen 2.1–2.4 dieses Records bleiben unveraendert
gueltig.

## 4. Konsequenzen

- `FK13_VECTORIZER_MODEL["poolingStrategy"]` ist ein abgeleiteter Wert; ein
  Direktschreiben ist entfallen.
- Ein kuenftiger Modellwechsel aendert genau eine Konstante — und schlaegt
  fehl, solange die Strategie fuer das neue Modell nicht erklaert ist.
- Die Modelldrift gegen die laufende Weaviate-Instanz bleibt offen und ist dem
  Product Owner gemeldet.
