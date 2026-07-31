---
concept_id: META-DEC-2026-07-30-CP10A-RECEIPT-CONTRACT
title: Concept-Decision-Record — CP-10a-Receipt-Vertrag als Norm (FK-13 §13.9.9)
module: meta
cross_cutting: true
status: active
doc_kind: decision-record
authority_over: []
defers_to: []
supersedes: []
superseded_by:
tags: [meta, decision-record, vectordb, installer, receipt, evidence, FK-13, FK-50]
formal_scope: prose-only
---

# Concept-Decision-Record — CP-10a-Receipt-Vertrag als Norm (FK-13 §13.9.9)

Datum: 2026-07-30. **PO-Entscheidung.** Der lokale Beleg der CP-10a-
Erstindizierung bekommt einen verbindlichen Vertrag mit genau einem Owner.

## 1. Anlass

Der Beleg existierte als Implementierungsverhalten in
`installer/cp10a_initial_sync.py`, aber ohne Norm: FK-50 beschrieb ihn
prosaisch mit, FK-13 gar nicht. Jede Detailfrage — welcher Status zulaessig ist,
wo die Dateien liegen, was ein leerer Korpus bedeutet, was bei unbekanntem
Abschluss-Ausgang gilt — entschied der Code fuer sich allein. Zwei Beschreibungen
und keine Autoritaet ist genau das v2-Muster, das AK3 vermeidet.

Auslegungsspielraum an einer Evidenz-Grenze ist besonders teuer: ein Beleg, den
verschiedene Leser verschieden auslegen duerfen, belegt nichts.

## 2. Entscheidung

Der CP-10a-Receipt-Vertrag wird in **FK-13 §13.9.9** normativ verankert und ist
dort **Single Source of Truth**. FK-50 (CP 10a) beschreibt ihn nicht mehr,
sondern verweist.

Der Vertrag umfasst: Ablageorte, das vollstaendige Feldschema mit Typen und
Wertebereichen, die feste Zuordnung Producer → Korpus, den einzigen zulaessigen
Status, die Revisionsverkettung, die Paar-Publikation samt Restauration bei
Teilfehler sowie das Verhalten bei unbekanntem Abschluss-Ausgang.

Drei Festlegungen sind dabei eigenstaendige Entscheidungen und keine blosse
Detaillierung:

**2.1 Ein leerer Korpus ist Erfolg, kein Fehler.** „Null-Zaehler" betrifft die
Entdeckungsseite (`discovered`/`unchanged`/`upserted`). `deleted` darf positiv
sein: ein zuvor nichtleerer, jetzt leerer Korpus loescht seine Alt-Chunks, und
genau dieser Uebergang muss sich im Beleg abbilden. Die Alternative — alle
Zaehler null zu erzwingen — haette einen real unterstuetzten Uebergang
unbelegbar gemacht.

**2.2 Erst abschliessen, dann belegen — und kein halbes Paar.** Der Abschluss
der Generation wird **vor** dem Schreiben der Receipts committet. Ein Beleg darf
nur einen erreichten Zustand beschreiben; ein vorab geschriebener Beleg ist von
einem echten nicht unterscheidbar, sobald der Abschluss scheitert oder unklar
bleibt. Die beiden lokalen Receipts werden anschliessend als transaktionales
Paar geschrieben; scheitert der zweite Write, werden die exakten vorherigen
Bytes beider Dateien restauriert. Scheitert auch die Restauration, wird das
ehrlich gemeldet und nicht als Rollback ausgegeben.

Der Preis dieser Reihenfolge ist bewusst gewaehlt: der Korpus-Zustand ist beim
Publikationsfehler bereits fortgeschritten und wird nicht zurueckgerollt. Damit
dieser Rest nicht still getragen wird, wird der gesamte Abschnitt „Commit **und**
beide Receipts schreiben" durch eine **durable Markierung** eingezaeunt. Sie
entsteht **vor** dem Commit und verschwindet erst, wenn beide Dateien
geschrieben sind.

Dass sie vor dem Commit entsteht, ist keine Feinheit: eine Markierung nach dem
Commit koennte die Luecke nicht abdecken, fuer die sie existiert — ein Abbruch
dazwischen hinterliesse fortgeschrittenen Korpus, alte Receipts und keine Spur.

Deshalb behauptet die Markierung auch nicht, der Korpus sei fortgeschritten. Sie
behauptet, dass der eingezaeunte Abschnitt nicht zu Ende gefuehrt wurde und
niemand beweisen kann, ob Beleg und Korpus zusammenpassen. Solange sie liegt,
bricht jeder Leser fail-closed ab und der naechste Lauf publiziert nach.
Entfernt wird sie nur nach vollstaendiger Publikation oder wenn der Commit
definitiv **nicht** erfolgt ist und die exakten vorherigen Bytes restauriert
wurden; bei unbekanntem Ausgang bleibt sie stehen.

Erst diese Einzaeunung macht das Paar fuer Leser transaktional — der
Schreibvorgang selbst ist nur je Datei atomar, ein Prozessabbruch zwischen den
beiden Writes hinterliesse sonst ein gemischtes Paar aus zwei Laeufen, das sich
von einem bewiesenen nicht unterscheiden liesse. Die Einzaeunung ist bewusst
konservativ: ein Abbruch vor dem Commit hinterlaesst einen Zaun ueber einem
konsistenten Zustand, den der naechste Lauf abraeumt.

Die umgekehrte Reihenfolge konnte den Korpus zwar mit zurueckrollen, hinterliess
dafuer aber Erfolgsbelege fuer Abschluesse, die nie gelandet sind. Ein
detektierbarer, selbstheilender Rest ist einer stillen Falschaussage
vorzuziehen.

**2.3 Unbekannter Abschluss-Ausgang ist weder Erfolg noch Rollback.** Endet der
Abschluss mit `commit_outcome_unknown` (Bounded-Window, Entscheidung 2026-07-21
Rand 5), wird **kein** Receipt publiziert und **nichts** zurueckgerollt: die
vorhandenen Receipts bleiben unveraendert der letzte bewiesene Stand, das
durable Recovery-Journal bleibt erhalten, und der Ausgang ist vor der naechsten
Korpus-Mutation aufzuloesen. Beide Behauptungen — „hat geklappt" wie „wurde
zurueckgenommen" — waeren Aussagen ueber einen Zustand, den niemand beobachtet
hat.

Daraus folgt unmittelbar: **der Vertrag gilt beim Lesen wie beim Schreiben.**
Ein Verify, das die Receipt-Dateien liest, waehrend fuer dasselbe Projekt ein
unaufgeloester Ausgang im Recovery-Journal steht, darf nicht bestaetigen. Die
Dateien sind dabei **nicht** Kandidaten — sie sind der letzte bewiesene Stand;
unbewiesen ist nur, ob der Korpus inzwischen darueber hinausgegangen ist. Eine
Norm, die nur beim Schreiben durchgesetzt wird, ist keine Norm.

## 3. Abgrenzung

Diese Entscheidung folgt **nicht** aus dem Beschluss 2026-07-21 Rand 1; der
autorisiert nur Pflichtinfrastruktur, den deprecateten Migrationsschluessel und
die Entfernung des Optionalitaetszweigs. Sie wird deshalb hier eigenstaendig
ratifiziert und nicht als dessen Ableitung ausgegeben.

Kein neuer Scope: der Vertrag beschreibt die Faehigkeit, die AG3-176 ohnehin
liefert. Was hinzukommt, ist Verbindlichkeit und ein benannter Owner.

## 4. Betroffenheitsmatrix

| # | Gegenstand | Datei / Abschnitt | Klassifikation | Aenderung |
|---|-----------|-------------------|----------------|-----------|
| 1 | Receipt-Vertrag | FK-13 §13.9.9 | geaendert | Vertrag als SSOT verankert: Pfade, Feldschema mit Typen/Wertebereichen, Producer→Korpus, Status, Revisionssemantik |
| 1 | Receipt-Vertrag | FK-50 CP 10a | geaendert | Duplikat entfernt; verweist auf FK-13 §13.9.9 |
| 2.1 | Empty Corpus | FK-13 §13.9.9 | geaendert | leerer Korpus = Erfolg; `deleted > 0` ausdruecklich zulaessig |
| 2.2 | Reihenfolge | FK-13 §13.9.9 | geaendert | Commit vor Publikation; die Receipt-Datei traegt vor geklaertem Commit den letzten bewiesenen Stand |
| 2.2 | Teilfehler | FK-13 §13.9.9 | geaendert | exakte Byte-Restauration; ehrliche Meldung bei gescheiterter Restauration; Korpus-Zustand wird dabei nicht zurueckgerollt |
| 2.2 | Publikationsfenster | FK-13 §13.9.9 | geaendert | durable Markierung **vor** dem Commit bis zur vollstaendigen Publikation (Intent-Fence); sie — nicht der Schreibvorgang — macht das Paar fuer Leser transaktional |
| 2.2 | Aussage der Markierung | FK-13 §13.9.9 | geaendert | ihre Anwesenheit behauptet nicht, dass der Korpus fortschritt, sondern dass der Abschnitt unvollendet blieb; Entfernung nur nach vollstaendiger Publikation oder nach definitivem Nicht-Commit mit exakter Byte-Restauration |
| 2.3 | Unbekannter Ausgang | FK-13 §13.9.9 | geaendert | weder Erfolg noch Rollback; Aufloesung vor naechster Mutation |
| 2.3 | Lesen an Ausgang gebunden | FK-13 §13.9.9 | geaendert | Verify bricht fail-closed ab, solange ein Publikationsfenster offen ist ODER ein Abschluss-Ausgang aussteht; danach sind die Dateien wieder gueltige Evidenz |
| 2.3 | Bounded-Window | Decision 2026-07-21 Rand 5 | referenziert | Herkunft des `commit_outcome_unknown`-Zustands |
| — | Story-Korpus-Zuordnung | Decision 2026-07-21 Rand 2 | referenziert | feste Producer→Korpus-Zuordnung stammt von dort |
| — | Installer-Optionalitaet | Decision 2026-07-21 Rand 1 | nicht-betroffen | dieser Vertrag sagt nichts ueber Aktivierung |

## 5. Herkunft der Ratifikation

PO-Vorlage 2026-07-30: der Vertrag wurde als einziger Punkt mit **neuer Norm**
gesondert vorgelegt und um Freigabe gebeten. PO-Antwort:

> „Wenn du die Konzeptinhalte mit Codex Review abgesichert hast, dann habe ich
> da keinen Einspruch."

Die Absicherung erfolgte durch mehrere getrennte read-only Codex-Review-Runden
im Rahmen von AG3-176; die Berichte liegen im Story-Record dieser Story. Der
Vertrag hat sich in diesen Runden substanziell geschaerft — die erste Runde
stellte fest, dass er nur Feldnamen aufzaehlte, die vierte, dass er ohne diesen
Record gar nicht ratifiziert war.

Die Berichte sind bewusst **nicht** als Pfad referenziert: ein Normdokument
haengt nicht an transienten Story-Arbeitsdateien.
