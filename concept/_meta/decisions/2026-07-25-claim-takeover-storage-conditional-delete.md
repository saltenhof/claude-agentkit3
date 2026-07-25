---
concept_id: META-DEC-2026-07-25-CLAIM-TAKEOVER-STORAGE-CONDITIONAL-DELETE
title: Concept-Decision-Record — Zerstoerender Sync-Schritt wird storage-seitig an den Besitz gebunden
module: meta
cross_cutting: true
status: active
doc_kind: decision-record
authority_over: []
defers_to: []
supersedes: []
superseded_by:
tags: [meta, decision-record, vectordb, retrieval, claim, concurrency, FK-13, AG3-174]
formal_scope: prose-only
---

# Concept-Decision-Record — Zerstoerender Sync-Schritt wird storage-seitig an den Besitz gebunden

Datum: 2026-07-25. Record gemaess META-CONCEPT-CONSISTENCY P3
(Blast-Radius-Pflicht bei normativen Aenderungen). Begrenzt auf FK-13 §13.3.1
(ein neues Feld) und §13.9.9 (Verhalten bei Besitzwechsel).

> **Nachtrag 2026-07-25 (Codex r7, Findings N37/N39) — Mechanismus korrigiert.**
> Die zuerst umgesetzte Mechanik (**Gleichheit gegen das beobachtete
> Besitz-Token**) erfuellte die ratifizierte Invariante **nicht** und ist
> **ersetzt**. Die Invariante selbst und die Entscheidung, nur den zerstoerenden
> Schritt storage-seitig zu sichern, bleiben unveraendert; ausgetauscht ist
> ausschliesslich das *Wie*, das diese Entscheidung ausdruecklich der Umsetzung
> ueberlassen hatte. Abschnitt 2a haelt fest, warum das erste Modell fiel und
> welches Modell gilt. Die frueheren Aussagen „neuere Daten koennen nicht
> geloescht werden" (bezogen auf das Token-Modell) und „ein Stale-Append der
> Completion ist harmlos" waren **falsch** und sind unten korrigiert.

## 1. Anlass

Codex-Review r6, Finding N33 (= N15/N27): jeder Fence im Corpus-Sync ist ein
**Read** (`assert_claim_held`), gefolgt von einer **separaten** Mutation. Ein
administrativer Reclaim (D3/N27: kein Zeitablauf, nur bewusster Eingriff) kann
genau dazwischen landen — dann mutiert der ueberholte Halter trotzdem. Eine
vorgelagerte Pruefung kann dieses Fenster prinzipiell nicht schliessen.

Am Weaviate-Rand wurde verifiziert: es gibt **keine** allgemeine
epoch-konditionale Mutation. `data.update`, `data.replace` und
`data.delete_by_id` kennen keine Vorbedingung; `data.insert` ist ausschliesslich
auf die Objekt-ID konditional (genau das nutzen Claim- und Completion-Record
bereits). **Eine** storage-seitige Bedingung existiert jedoch:
`data.delete_many(where=…)` ist filter-konditional.

Verifizierte Risiko-Asymmetrie der drei gefencten Schritte:

1. **Chunk-Write** — idempotent (deterministische UUID, identischer Inhalt).
2. **Completion** — insert-only und positionsgebunden; ein Nachzuegler kann nur
   eine neue Position anfuegen, nichts ueberschreiben.
3. **Loeschen alter/verschwundener Chunks** — der **einzige zerstoerende**
   Schritt und damit das einzige echte Datenverlustrisiko.

## 2. Entscheidung

**Nur der zerstoerende Schritt wird storage-seitig an den Besitz gebunden; die
beiden harmlosen Fenster werden ehrlich dokumentiert.**

Verbindliche Invariante: *Ein ueberholter Halter darf niemals Daten loeschen, die
der neuere Besitzer geschrieben hat — und dies muss storage-seitig erzwungen
sein, nicht durch eine vorgelagerte Pruefung.*

Umsetzung in der Norm:

- FK-13 §13.3.1 erhaelt das Feld `owning_claim`: das Besitz-Token der
  Claim-Generation, die eine Objektversion geschrieben hat. Es ist **kein**
  zweiter Besitz-Wahrheitstraeger — autoritativ bleibt der Claim-Datensatz —,
  geht nicht in die Einbettung ein und ist kein Rueckgabefeld der Werkzeuge.
- FK-13 §13.9.9 haelt fest, dass der zerstoerende Schritt an das **beobachtete**
  `owning_claim` gebunden und **ohne** vorgelagerte Ersatzpruefung ausgefuehrt
  wird, und benennt die zwei verbleibenden Fenster als bekannt und unschaedlich.
- Es wird **keine** transaktionale Atomizitaet behauptet (Linie aus
  DR 2026-07-21 Rand 5).

## 2a. Korrektur des Mechanismus (Nachtrag, Codex r7)

**Was fiel.** Das erste Modell stempelte ein Besitz-Token
(`<epoche>|<owner_id>`) auf die Objekte und loeschte konditional „alles, was
dieses **beobachtete** Token noch traegt". Das schliesst nur das Intervall
zwischen Lesen und Loeschen — es belegt **nicht**, zu welcher Generation das
gelesene Token gehoert. Gegenszenario: Writer A passiert seinen Fence, B
uebernimmt per Reclaim und schliesst ab, A setzt fort, liest **Bs** Chunks,
gruppiert sie unter Bs Token und loescht damit **Bs** Daten. Die
Invariante war in dieser Reihenfolge verletzt; die damaligen Tests deckten nur
die umgekehrte Reihenfolge ab.

Zusaetzlich war die Completion-Seite unzureichend: insert-only verhindert das
**Ueberschreiben**, nicht das **Anhaengen**. Ein ueberholter Schreiber konnte
nach dem neueren Besitzer eine spaetere Position belegen, damit — bei Ordnung
nach Position — massgeblich werden und die gueltige Completion des neueren
Besitzers als „veraltet" entfernen. Die frueher hier notierte Einschaetzung
„harmlos" war falsch.

**Gemeinsame Wurzel.** Es fehlte eine **persistente, monotone
Generationsidentitaet pro Quelle**. Epoche allein wiederholt sich ueber Laeufe,
und auch Epoche + Owner ist kein global geordneter Bezeichner (ein langlebiger
Sync-Dienst traegt denselben Owner ueber mehrere Akquisitionen).

**Was gilt.** Die Quelle traegt eine **persistente, streng monoton steigende
Generation**: **jede** Akquisition — normal **und** Reclaim — vergibt per
konditionalem Create die naechste Nummer, und eine normale Freigabe erhaelt die
Leiterposition (insert-only Freigabe-Markierung statt Loeschen des Records).
Darauf aufbauend:

- Objekte tragen `owning_generation` (FK-13 §13.3.1, numerisch).
- Der zerstoerende Delete ist storage-seitig an „Generation des Objekts **strikt
  kleiner** als die **eigene** Generation des loeschenden Claims" gebunden. Weil
  ein uebernehmender Besitzer zwangslaeufig hoeher liegt, haelt die Invariante in
  **beiden** Wettlauf-Reihenfolgen; und weil jede fruehere Generation strikt
  darunter liegt, geht kein legitimer Loeschvorgang verloren.
- Die **Completion** traegt dieselbe Generation und ist ueber sie geordnet:
  massgeblich ist die hoechste **Generation**, nicht die hoechste Position; das
  Pruning folgt derselben Ordnung. Ein Stale-Append kann damit weder die Frische
  zuruecknehmen noch eine gueltige neuere Completion verdraengen.
- Die Generation ist **kein zweiter Besitz-Wahrheitstraeger**: der Claim-Record
  entscheidet weiter, **wer** haelt; die Generation ordnet nur.

**Verbleibendes Fenster.** Nur noch der **Chunk-Write** ist unbewacht, und er ist
idempotent (deterministische UUID, gleicher Inhalt). Es wird weiterhin **keine**
transaktionale Atomizitaet behauptet.

## 3. Alternativen

- **Das Restfenster vollstaendig akzeptieren** wurde verworfen: der Loeschschritt
  bliebe ein echtes Datenverlustrisiko.
- **Vollabsicherung aller drei Schritte** wurde verworfen: sie braucht ein
  Takeover-Protokoll, das den alten Prozess nachweislich stilllegt — also
  Prozessaufsicht ausserhalb dieser Schicht. Eigene Story; AG3-174 wuerde darauf
  warten.
- **Bedingung „Epoche des Objekts aelter als meine" bei EPHEMERER Epoche**
  wurde verworfen und der Befund von Codex r7 ausdruecklich bestaetigt: die
  Claim-Epoche war nur *innerhalb* einer Uebernahmekette monoton, weil ein
  freigegebener Claim-Record geloescht wurde und die naechste Akquisition wieder
  bei 1 begann. Ein Ordnungspraedikat haette daher legitim loeschbare Alt-Chunks
  uebersprungen — verschwundene Quellen waeren **stillschweigend nie** entfernt
  worden (Bruch der Delete-Closure). Die Konsequenz ist **nicht**, die Ordnung
  aufzugeben, sondern die Leiter **persistent** zu machen (Abschnitt 2a).
- **Gleichheit gegen den beobachteten Wert** (Compare-and-Delete) wurde zuerst
  umgesetzt und dann **verworfen**: sie autorisiert nichts (Abschnitt 2a).
- **Nur die Epoche als Token / Epoche + Owner als Token** wurde verworfen:
  Epochenwerte wiederholen sich ueber Laeufe, und ein langlebiger Sync-Dienst
  traegt denselben Owner ueber mehrere Akquisitionen — das Paar ist damit weder
  global eindeutig noch geordnet.
- **Eine Ersatzpruefung im Applikationscode „zur Sicherheit" behalten** wurde
  verworfen: sie stellt genau die Scheinsicherheit wieder her, die diese
  Entscheidung beseitigt.

## 4. Impact-Sweep (P3)

Lexikalischer Sweep ueber `concept/`, `guardrails/`, `scripts/ci/`, `tools/`,
`src/` und `stories/` nach `StoryContext`, `claim`, `Shadow-Replace`,
`corpus_revision` und `delete`:

- Normativer Owner des Datenmodells und des Sync-Lifecycles ist ausschliesslich
  FK-13 (§13.3.1, §13.9.9). Kein weiteres Konzeptdokument fuehrt die
  `StoryContext`-Properties.
- `concept/_meta/decisions/2026-07-21-vectordb-edge-sharpening.md` (Rand 5) hat
  den Shadow-Replace auf „generationskonsistent mit kurzem Umschaltfenster"
  abgeschwaecht. Diese Entscheidung ergaenzt sie, ohne sie zu ueberschreiben: das
  Fenster bleibt, nur die **Nicht-Loeschbarkeit fremder, neuerer Daten** wird
  garantiert.
- §13.9.5/§13.4.1 (Werkzeug-Vertraege) sind **nicht betroffen**: `owning_claim`
  ist kein Parameter und kein Rueckgabefeld.
- §13.9.6 (Frontmatter) ist **nicht betroffen** — das Feld ist Laufzeit-Besitz,
  keine Korpus-Metadatenaussage. Auch das offene `doc_kind`-Vokabular (Frage Q2)
  bleibt unberuehrt.
- §13.2/§13.9.3 (Vektorisierung): das Feld ist ausdruecklich **nicht**
  vektorisiert und nicht Teil der Einbettungsquellen.
- K5/Datenhaltung: die Aenderung betrifft die Weaviate-Collection `StoryContext`
  (ein zusaetzliches, nicht vektorisiertes, filterbares Textfeld); kein
  relationales Schema, keine Telemetrie.

## 5. Betroffenheitsmatrix

| Stelle | Klassifikation | Begruendung |
|---|---|---|
| FK-13 §13.3.1 (`StoryContext`-Properties) | geaendert | Neues Feld `owning_generation` (INT) samt Abgrenzung „kein zweiter Besitz-Wahrheitstraeger". |
| FK-13 §13.9.9 (Corpus-Build-Lifecycle) | geaendert | Persistente Quell-Generation; storage-seitig **geordneter** zerstoerender Schritt; generationsgebundene Completion; ein benanntes Restfenster; keine Atomizitaetsbehauptung. |
| `concept/_meta/decisions/2026-07-21-vectordb-edge-sharpening.md` (Rand 5) | referenziert | Bounded-Window-Linie, die hier fortgeschrieben und nicht aufgehoben wird. |
| FK-13 §13.9.5 / §13.4.1 (Werkzeug-Vertraege) | nicht-betroffen | Kein Parameter, kein Rueckgabefeld. |
| FK-13 §13.9.6 (Frontmatter) | nicht-betroffen | Laufzeit-Besitz statt Korpus-Metadatum. |
| FK-13 §13.2 / §13.9.3 (Vektorisierung) | nicht-betroffen | Feld ist nicht vektorisiert. |
| `concept/_meta/decisions/2026-07-25-claim-takeover-storage-conditional-delete.md` | geaendert | Dieses Record persistiert Entscheidung, Alternativen und Impact-Sweep. |
| Sync/Store im Code (`backend/vectordb/sync.py`, `engine.py`) | referenziert-jetzt | Stempelt beim Schreiben und loescht ausschliesslich storage-konditional. |
| Transport-Adapter (`integration_clients/vectordb/weaviate_adapter.py`) | referenziert-jetzt | Setzt die Bedingung ueber `delete_many(where=…)`. |

Grundlage: PO-Ratifizierung D9 in
`stories/AG3-174-vectordb-retrieval-engine/po-decisions.md`. Zusammen mit D7 und
D8 sind das die Konzeptaenderungen, die AG3-174 gestattet sind.
