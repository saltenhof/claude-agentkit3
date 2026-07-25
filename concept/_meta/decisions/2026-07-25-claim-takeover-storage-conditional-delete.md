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

1. **Chunk-Write** — damals als „idempotent (deterministische UUID, identischer
   Inhalt)" eingeschaetzt. **Diese Praemisse war falsch** und ist im Nachtrag
   2026-07-25/2 korrigiert: bei geaendertem Inhalt entstehen andere UUIDs.
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

**Verbleibendes Fenster.** Nur noch der **Chunk-Write** ist unbewacht. Die
Begruendung „das ist idempotent, weil derselbe Inhalt unter derselben UUID landet"
gilt **nicht** bei geaendertem Inhalt; siehe den Nachtrag 2026-07-25/2. Es wird
weiterhin **keine** transaktionale Atomizitaet behauptet.

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

## 6. Nachtrag 2026-07-25/2 — Schreibfenster begrenzt, Praemisse korrigiert

Codex-Review r8 (Finding N41) hat die „selber Inhalt"-Praemisse widerlegt: Fence und
Upsert sind getrennte Operationen, also kann ein ueberholter Halter danach Objekte
**seiner** niedrigeren Generation anhaengen — und bei **geaendertem** Inhalt tragen
diese **andere** UUIDs, werden also von der neueren Generation nicht ueberschrieben.
Der Receipt-Fence weist den Nachzuegler ab, entfernt seine Zeilen aber nicht. Die
Aussage „unschaedlich, weil identischer Inhalt" war damit **falsch**.

**Analyse (Grundlage der Entscheidung):** Loeschbar waren diese Zeilen immer — der
naechste Sync derselben Quelle liest sie in seine `persisted`-Menge, sie fehlen in
seiner `should`-Menge, und seine Generation ist zwangslaeufig hoeher, also greift die
Ordnungsbedingung. Die Frische war ebenfalls nie korrumpiert (der Nachzuegler
publiziert keine autoritative Completion). Der eigentliche Defekt war also
**Rechtzeitigkeit und Fehlmeldung**: bis zum naechsten Sync konnte das Retrieval zwei
widersprechende Fassungen desselben Abschnitts liefern, waehrend `corpus_revision`
den neueren Stand meldete.

**Entscheidung (im Rahmen der von D9 delegierten Mechanik):** Der abschliessende
Besitzer fuehrt **nach** dem Publizieren seiner Completion **einen weiteren
storage-konditionalen Durchgang** ueber seine eigene Quelle aus, mit derselben
Bedingung („Generation strikt kleiner als meine") und ohne jede vorgelagerte
Applikationspruefung. Damit endet das Schreibfenster an der Completion statt am
naechsten Sync. Kein neuer Zustand, keine Aenderung der Objektidentitaet, keine
Kopplung des Retrievals, keine Aenderung der Werkzeug-Vertraege.

**Verworfen** wurden die beiden anderen Formen: Stale-Writes storage-seitig
unmoeglich zu machen ist an diesem Rand nicht verfuegbar (der Client kennt keine
Vorbedingung fuer Schreibvorgaenge) und waere nur ueber generationsgebundene UUIDs
emulierbar — was die deterministische Chunk-Identitaet zerstoert, auf der
idempotenter Re-Sync, Delete-Closure und Identitaetspruefung beruhen. Ein
**Retrieval-Filter auf die Generation** wurde verworfen, weil eine Abfrage viele
Quellen umfasst und keine quellenweise Schranke kennt, und weil damit ein internes
Nebenlaeufigkeits-Ordinal auf die Abfrageoberflaeche geriete, die FK-13 bewusst
davon freihaelt; ein Filter auf `corpus_revision` waere die einzige kohaerente
Variante dieser Form und ist fuer den erreichten Schutz nicht erforderlich.

**Zusaetzlich (Finding N43):** Vorbestehende Zeilen ohne `owning_generation` sind
gegen keine Generation ordenbar und haetten jeden Reindex dauerhaft blockiert. Der
haltende Besitzer raeumt sie deshalb explizit auf: Zeilen der neuen Generation
werden durch den Upsert ersetzt und dadurch gestempelt, die uebrigen unter einer
**IS-NULL-Bedingung** entfernt, die strukturell keine gestempelte Zeile treffen
kann. Eine **vorhandene, aber unbrauchbare** Generation ist ein benannter Fehler,
keine Vermutung. Es werden keine fremden Inhalte in eine Generation uebernommen. Die
Aufraeumung ist claim-gebunden, fail-closed und wird im Sync-Ergebnis mitgefuehrt.
Verankert in FK-13 §13.9.9.

## 7. Nachtrag 2026-07-25/3 - Shape 3 verengt, schliesst aber nicht

Codex-Review r9 stellt strukturell fest: *One finite sweep cannot close a write that
may land afterwards.* Der in Nachtrag /2 beschriebene Durchgang ist ein **endlicher**
Vorgang; ein Schreiben, das **danach** eintrifft, kann er nicht abdecken. Er
verkleinert das Fenster auf den Regelfall - die Aussage aus /2, das Fenster sei *auf
das Intervall bis zur Completion begrenzt*, war **zu stark** und ist in FK-13 §13.9.9
korrigiert. Zusaetzlich stand der erforderliche zerstoerende Schritt dort **nach** dem
Receipt, entgegen AC6; die Reihenfolge ist korrigiert: der Abschluss-Delete liest
frisch und laeuft **vor** der Completion.

**Was unveraendert gilt:** die ratifizierte D9-Invariante - ein ueberholter Halter
kann Daten einer neueren Generation nicht loeschen - ist eingehalten und in beiden
Wettlauf-Reihenfolgen belegt; die gemeldete Frische kann nicht zurueckgedreht werden
(N39).

**Was offen bleibt:** die **Sichtbarkeit** zusaetzlicher Zeilen einer niedrigeren
Generation zwischen dem Abschluss-Delete und dem naechsten Sync derselben Quelle.
Dieser Zeitpunkt ist nicht zeitlich begrenzt. Der Restbefund ist **offen und nicht
ratifiziert** und ausdruecklich **kein** akzeptierter Vertrag.

**Aufloesungsraum - genau drei Formen, keine davon hier entschieden:**

1. Den Stale-Write eliminieren oder storage-seitig fencen - an diesem Rand **nicht
   verfuegbar** (ueber drei Runden gegen den gepinnten Client verifiziert: es gibt
   keine Vorbedingung fuer Schreibvorgaenge; eine Emulation ueber generationsgebundene
   UUIDs zerstoert die deterministische Chunk-Identitaet, auf der idempotenter
   Re-Sync, Delete-Closure und Identitaetspruefung beruhen).
2. Das Retrieval nicht-autoritative Generationen ausschliessen lassen - kohaerent
   **nur** ueber `corpus_revision` (nicht ueber die Generation, die FK-13 bewusst von
   der Abfrageoberflaeche fernhaelt); Kosten: Kopplung der Abfrage an die
   Completion-Menge, Filterwachstum mit der Zahl der Quellen im Suchraum, und die
   Zeilen existieren weiterhin fuer ungefilterte Leser und Zaehlungen.
3. Ein **ratifizierter Vertrag**, der eine potenziell unbegrenzte
   Post-Completion-Inkonsistenz ehrlich modelliert. **Erfordert eine PO-Entscheidung.**

Gemaess PO-Mandat vom 2026-07-25 (eine Runde weiter, dann Schnitt) wird die
Aufloesung **nicht** in AG3-174 versucht. Der Vorschlag fuer die Folgestory samt
Kosten je Form liegt im Story-Report; eine neue Story wird ohne PO-Zustimmung nicht
angelegt.

Grundlage: PO-Ratifizierung D9 in
`stories/AG3-174-vectordb-retrieval-engine/po-decisions.md`. Zusammen mit D7 und
D8 sind das die Konzeptaenderungen, die AG3-174 gestattet sind. Die Mechanik war in
D9 ausdruecklich der Umsetzung ueberlassen; dieser Nachtrag bleibt innerhalb der
autorisierten Abschnitte §13.3.1/§13.9.9, §13.9.6 bleibt unberuehrt.
