---
concept_id: META-DEC-2026-08-02-MODELLPIN-FOLGT-DER-LAUFENDEN-INFRASTRUKTUR
title: Concept-Decision-Record — Modellpin folgt der laufenden Infrastruktur (bge-m3)
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

# Concept-Decision-Record — Modellpin folgt der laufenden Infrastruktur (bge-m3)

Datum: 2026-08-02.

## 1. Anlass

Die betriebene Weaviate-Instanz fuehrt den Sidecar
`vectordb-text2vec-bge-m3:local` und damit das Einbettungsmodell `BAAI/bge-m3`.
FK-13 §13.2 pinnte weiterhin `sentence-transformers/all-MiniLM-L6-v2`. Das
Konzept wurde beim Infrastrukturwechsel nie nachgezogen.

Die Folge ist kein stiller Qualitaetsverlust, sondern ein harter Abbruch: der
Adapter erkennt die Drift fail-closed
(`weaviate_adapter._verify_existing_collection`), und der Installer bricht an
`cp_10` ab. Eine frische Installation ist damit gegen die real laufende
Infrastruktur nicht durchfuehrbar.

Es gibt **nichts zu migrieren**: die Datenbank steht bereits auf dem Zielmodell,
und ihr Inhalt ist ein abgeleiteter Suchindex ueber `concept/` und `stories/`.

## 2. Entscheidung

**2.1 Der Modellpin folgt der laufenden Infrastruktur.**
`FK13_EMBEDDING_MODEL` und FK-13 §13.2 stehen auf `BAAI/bge-m3`; das
Sidecar-Image in §13.2 ist `vectordb-text2vec-bge-m3:local`. Die
Pooling-Strategie wird unveraendert nach dem Beschluss vom 2026-08-02
(„Die Pooling-Strategie folgt dem Einbettungsmodell") abgeleitet und ergibt
damit automatisch `cls`. Es wurde keine Strategie von Hand gesetzt.

**2.2 Die `StoryContext`-Collection wird geloescht und neu angelegt.**
Die bestehende Collection weicht in `vectorizeClassName` ab (`true` statt des
geforderten `false`); das ist an einer bestehenden Collection nicht aenderbar.
Kein Backup, kein Re-Import, keine Datenrettung: der Inhalt ist ein abgeleiteter
Index und wird durch `concept_sync` / `story_sync` neu erzeugt. Waere ein Inhalt
darin nicht reproduzierbar, waere das ein eigener Defekt der Ingest-Kette, kein
Grund, den Index zu konservieren.

**2.3 Tokenizer-Asset und Chunk-Budgets bleiben in diesem Schnitt bewusst
zurueck — benannt, nicht stillschweigend.** Das ausgelieferte Tokenizer-Asset
(`resources/tokenizer/`) ist weiterhin MiniLM/WordPiece, und
`DEFAULT_MAX_TOKENS = 1000` ist gegen MiniLMs Kontextfenster gerechnet. Beide
wirken **ausschliesslich auf die Chunk-Groessenrechnung beim Ingest**, nie auf
die serverseitige Einbettung — die rechnet der Sidecar mit bge-m3. Es existiert
im Code **keine** Digest- oder Konsistenzpruefung, die den Modellpin an das
Tokenizer-Asset bindet; die beiden Konstanten sind unabhaengig
(`vectordb/schema.py` vs. `concepts/tokenizer.py`), weshalb der Teilschnitt
technisch traegt.

Die Nachfuehrung (Tokenizer-Asset + Digest + Chunk-Budgets + Re-Ingest) ist ein
eigenes Epic. Bis dahin ist der Zustand ein **benannter offener Punkt auf
WARNING-Ebene**, dem PO gemeldet: die Chunk-Grenzen sind zu konservativ und
gegen das falsche Vokabular gerechnet. Nebenbefund fuer dasselbe Epic: 1000
Tokens ueberschritten MiniLMs Fenster von 256–512 ohnehin; mit bge-m3 (8192) ist
das entschaerft.

## 3. Verhaeltnis zum Beschluss „Die Pooling-Strategie folgt dem Einbettungsmodell"

Jener Record (gleiches Datum) liess in §3 ausdruecklich offen, **ob** AK3 auf
bge-m3 wechselt, und hielt „bis dahin bleibt der Pin auf MiniLM" fest. Genau
diese offene Frage entscheidet der vorliegende Record — zugunsten des Wechsels.
Seine Entscheidungen 2.1–2.4 (Ableitungskante, Fail-closed bei unbekanntem
Modell, Eigentuemer im Konzept, Verbundcharakter eines Modellwechsels) bleiben
unveraendert gueltig; abweichend vom dortigen §3 wird der Verbund hier nicht in
einem Zug, sondern in zwei benannten Schnitten nachgezogen — begruendet in 2.3.

## 4. Impact-Sweep (P3)

Lexikalischer Sweep ueber `concept/`, `src/`, `pyproject.toml` und `ONBOARDING.md`
nach `all-MiniLM-L6-v2`, `MiniLM`, `transformers-inference` und
`vectordb-text2vec`:

- Normativer Owner des Modell-, Pooling- und Image-Werts ist genau ein Ort:
  FK-13 §13.2.
- Im Produktionscode existiert der Modellwert genau einmal
  (`FK13_EMBEDDING_MODEL`); alles Weitere ist daraus abgeleitet.
- Das Container-Image ist **nirgends** im Code hartkodiert, nur in FK-13 §13.2
  und beschreibend in `ONBOARDING.md`.
- `concepts/tokenizer.py` fuehrt mit `PINNED_MODEL` einen zweiten, unabhaengigen
  Modellwert fuer das Tokenizer-Asset. Er ist **nicht** mit
  `FK13_EMBEDDING_MODEL` verdrahtet — siehe 2.3.

## 5. Betroffenheitsmatrix

| Stelle | Klassifikation | Begruendung |
|---|---|---|
| `concept/technical-design/13_retrieval_vektordb_wissenszugriff.md` §13.2 | geaendert | Normativer Owner: Modell, Sidecar-Image und der benannte Teilschnitt beim Tokenizer. |
| `concept/_meta/decisions/2026-08-02-modellpin-folgt-der-laufenden-infrastruktur.md` | neu | Dieses Record. |
| `concept/_meta/decisions/2026-08-02-pooling-strategie-folgt-dem-einbettungsmodell.md` | referenziert-jetzt | Dessen offene Frage (§3) wird hier entschieden; seine Entscheidungen bleiben gueltig. |
| `src/agentkit/backend/vectordb/schema.py` | geaendert | `FK13_EMBEDDING_MODEL` auf `BAAI/bge-m3`; Pooling `cls` folgt abgeleitet. |
| `src/agentkit/resources/tokenizer/`, `concepts/tokenizer.py` | nicht-betroffen | Bewusst unveraendert (2.3); keine Bindung an den Modellpin. |
| Ingest-Chunk-Budgets (`DEFAULT_MAX_TOKENS`) | nicht-betroffen | Bewusst unveraendert (2.3), Epic. |
| `StoryContext`-Collection in Weaviate | neu angelegt | Loeschen und Neuanlage statt Migration (2.2). |
| Uebrige FK-Dokumente | nicht-betroffen | Keine weitere Stelle fuehrt Modell, Pooling oder Image. |
