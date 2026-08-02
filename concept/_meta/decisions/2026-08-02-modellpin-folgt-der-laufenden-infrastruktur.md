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

**2.4 Collection-Namen folgen der Weaviate-Konvention und stehen im Konzept.**
Die drei Buchhaltungs-Collections heissen `Ak3SyncReceipts`, `Ak3SyncRuns` und
`Ak3SourceClaims`; die Konvention (Grossbuchstabe am Anfang, `Ak3`-Praefix) ist
in FK-13 §13.3.0 ausgeschrieben. Die bisherigen Namen
`__agentkit_sync_receipts`, `__agentkit_sync_runs` und `__agentkit_source_claims`
waren nie gueltig: Weaviate lehnt sie mit HTTP 422 ab
(`'__agentkit_sync_receipts' is not a valid class name`). Es wurde eine
Python-Konvention fuer „privat" auf ein Fremdsystem uebertragen, das
Klassennamen mit Grossbuchstaben verlangt. Der Fehler ist nie aufgefallen, weil
die Anlage nie gegen eine leere Instanz lief — die Collections existierten in
der Entwicklungs-Instanz schlicht nicht. Ein Rename ohne Migration ist
zulaessig, weil die Collections nie erfolgreich angelegt wurden.

**2.5 Was in den Vektor eingeht, wird an `source_properties` geprueft, nicht am
per-Property-`skip`.** Der Adapter legt Collections ueber die Named-Vectors-API
an (`Configure.Vectors...`). **Gemessen** an einer Wegwerf-Collection gegen die
laufende Instanz mit weaviate-client 4.21.2: ein
`Property(skip_vectorization=True)` wird von dieser API **nicht uebertragen** —
der Read-back meldet fuer *jede* Property `_PropertyVectorizerConfig(skip=False,
…)`, unabhaengig davon, was beim Anlegen mitgegeben wurde.

Der bisherige Drift-Check verglich genau dieses Feld. Er prueft damit nicht die
Wirklichkeit, sondern die Erinnerung an die Legacy-Schreibweise derselben
Tatsache — mit der Folge, dass **jede frisch angelegte Collection beim naechsten
Start von ihrem eigenen Schema abwich** und `cp_10` nie gruen werden konnte.

Der Check zieht deshalb auf die Stelle um, an der die benutzte API die Aussage
tatsaechlich fuehrt: `source_properties`. N35 wird dabei **staerker**, nicht
schwaecher — eine *fehlende* Selektion gilt jetzt ebenfalls als Drift, weil ohne
sie nichts mehr belegt, was die Collection einbettet. N12/N18 pruefen weiterhin
Namen, Datentypen, `vectorizePropertyName`, Tokenisierung, Searchability und
Filterability. Zusaetzlich liest der Adapter die per-Property-Konfiguration nun
aus `vectorizer_configs` (Named-Vectors-Oberflaeche) statt nur aus dem bei
Named Vectors immer leeren `vectorizer_config`.

Der Rueckweg auf die abgekuendigte Legacy-Vectorizer-API wurde **verworfen**: er
waere genau die Kompatibilitaetsschicht, die CLAUDE.md ausnahmslos verbietet,
und haette AK3 an eine abgekuendigte Schnittstelle gebunden, nur um einen
Pruefausdruck zu retten.

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
| `concept/technical-design/13_retrieval_vektordb_wissenszugriff.md` §13.3.0 | neu | Normativer Owner der Collection-Namen und der Namenskonvention (2.4). |
| `src/agentkit/backend/vectordb/completion_ledger.py`, `source_generation.py` | geaendert | `Ak3SyncReceipts`, `Ak3SyncRuns`, `Ak3SourceClaims` statt der von Weaviate abgelehnten `__`-Namen (2.4). |
| `src/agentkit/integration_clients/vectordb/weaviate_adapter.py` | geaendert | Drift-Check der eingebetteten Properties auf `source_properties` gezogen; `vectorizer_configs` als Leseort (2.5). |
| `tests/unit/integrations/vectordb/test_weaviate_transport.py` | geaendert | Nur die drei Collection-Namen nachgezogen. |
| Uebrige FK-Dokumente | nicht-betroffen | Keine weitere Stelle fuehrt Modell, Pooling, Image oder Collection-Namen. |
