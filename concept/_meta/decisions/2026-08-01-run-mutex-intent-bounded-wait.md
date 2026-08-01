---
concept_id: META-DEC-2026-08-01-RUN-MUTEX-INTENT-BOUNDED-WAIT
title: Concept-Decision-Record — Coordination-Intent ist eine Klinke mit Wartefrist (FK-78 §78.4)
module: meta
cross_cutting: true
status: active
doc_kind: decision-record
authority_over: []
defers_to: []
supersedes: []
superseded_by:
tags: [meta, decision-record, concept-incubation, mutex, liveness, FK-78]
formal_scope: prose-only
---

# Concept-Decision-Record — Coordination-Intent ist eine Klinke mit Wartefrist (FK-78 §78.4)

Datum: 2026-08-01. **Korrektur zweier Liveness-Defekte** (Story AG3-179). Das
Coordination-Intent `RUN.mutex.intent` wird bei lebender fremder Klinke
beschraenkt ausgewartet statt sofort aufgegeben (Rand 2.1) — und seine Freigabe
darf nicht mehr still ausfallen (Rand 2.4).

## 1. Anlass

FK-78 §78.4 sagte bisher: „wer es nicht per O_CREAT|O_EXCL anlegen kann,
verliert." Das las sich wie die strengere Variante und war die kaputte.

Ein Schreiblauf haelt die Klinke nicht ueber seine ganze Laufzeit, sondern holt
sie **viermal** nacheinander: Erwerb/Uebernahme des Mutex, Revalidierung vor dem
Dispatch, Ziel-Write, Freigabe. Zwischen zwei dieser Abschnitte ist sie frei. Ein
Mitbewerber, der genau dann zugreift und anschliessend selbst am lebenden Mutex
scheitert, hat die Klinke in der Hand, waehrend der rechtmaessige Eigentuemer
seinen naechsten Abschnitt beginnen will — und der bricht dann ab. Im
symmetrischen Fall pingpongen beide und **kein** Schreiber kommt durch.

Belegt im echten Zwei-Prozess-Rennen: beide Teilnehmer meldeten Exit 2, einer
davon mit `another writer holds the RUN.mutex coordination intent` — das war der
Prozess, der den Mutex rechtmaessig besass. Quote auf `main` unter Last rund 10 %;
im CI-Lauf blockierte der Befund die gesamte Pipeline.

Es entstand dabei nie ein inkonsistenter Zustand — der Defekt ist reine Liveness.
Genau das machte ihn langlebig: fail-closed sieht aus wie Korrektheit.

## 2. Entscheidung

**Das Intent ist eine kurz gehaltene Klinke, kein Eigentumsrecht.** Eigentum
traegt der Mutex mit Nonce, TTL und Fencing-Token. Daraus folgt normativ:

**2.1 Beschraenktes Warten statt sofortigem Aufgeben.** Wer die Klinke nicht per
O_CREAT|O_EXCL anlegen kann, wartet in kurzen Polls bis zu einer Frist im
Sekundenbereich und bricht **erst danach** fail-closed ab. Die Klinke wird nur
ueber eine Handvoll Dateioperationen gehalten; Warten ist deshalb der Normalfall
und nicht die Ausnahme.

**2.2 Auch der noch leere Create wird ausgewartet.** Exklusiver Create und das
Schreiben der Payload sind zwei Schritte. Eine soeben angelegte, noch nicht
beschriebene Klinke ist ein Halten, keine Leiche — sie wird ausgewartet und
nicht als unlesbar eingesammelt. Der mtime-Fallback fuer verwaiste Klinken
(§78.4, benannte Grenze) bleibt davon unberuehrt, weil er erst nach TTL greift.

**2.3 Kein Freibrief fuer den Eigentuemer.** Ausdruecklich **nicht** entschieden
wurde die naheliegende Alternative, dem Mutex-Eigentuemer das Umgehen der Klinke
zu erlauben. Das haette die Atomizitaet zwischen Ownership-Pruefung und Wirkung
aufgegeben — also genau die Eigenschaft, fuer die die Klinke existiert. Eine
Uebernahme koennte dann wieder zwischen Pruefung und Heartbeat schluepfen.

**2.4 Wirkungen an der Klinke duerfen nicht still ausfallen.** Beim Nachweis der
Behebung trat ein zweiter, aelterer Defekt derselben Familie zutage: auf
Plattformen mit verbindlicher Dateisperrung blockiert schon ein **lesender**
Mitbewerber das `unlink` der Klinke (Windows, WinError 32). Der Code fing genau
diesen Fehler ab und verwarf ihn — die Freigabe tat dann nichts, und die Klinke
lag bis zum Ablauf ihrer TTL herum, waehrend sie niemand hielt. Jeder spaetere
Schreiber meldete daraufhin „ein anderer Schreiber haelt die Klinke", was
schlicht falsch war.

Das ist kein Windows-Detail, sondern eine Modellfrage: nach
compare-before-delete steht das Eigentum fest, die Loeschung ist damit eine
**geschuldete Wirkung** und kein Versuch. Loeschen und atomares Ersetzen werden
deshalb beschraenkt wiederholt; ein endgueltig gescheitertes Ersetzen ist harter
Abbruch, ein endgueltig gescheitertes Loeschen wird als WARNING mit Dateipfad
gemeldet statt als Erfolg ausgegeben. Ergaenzend liest ein Wartender die Payload
nur noch im Sekundentakt nach — der exklusive Create ist die billige Probe, und
haeufiges Lesen ist genau das, was dem Halter die Freigabe blockiert.

Symmetrisch dazu gilt das auch fuer den Erwerb: ein vom Betriebssystem
**verweigerter** Create — nicht „existiert bereits", sondern „darf gerade
nicht" — ist ein verlorener Anspruch mit regulaerem Fehlausgang. Bisher war nur
`FileExistsError` behandelt; jeder andere OS-Fehler an der Klinke beendete das
CLI mit einem Traceback und Exit 1, also ausgerechnet mit dem Code, den derselbe
Vertrag fuer Validierungsfunde reserviert. Ein Absturz ist keine Aussage.

Der Rest ist benannt: laesst ein Leser waehrend der ganzen Wiederholungsfrist
kein Fenster, ueberlebt die Klinke bis zu ihrer TTL. Er gehoert zur bereits
deklarierten Grenze „Aufraeumen verwaister Intents" und verschwindet erst mit
einem OS-Advisory-Lock.

**2.5 Nichts an der Strenge geaendert.** Schiedsrichter bleibt O_CREAT|O_EXCL;
compare-before-delete bleibt auf jedem Pfad; ein abgelaufenes Intent wird weiter
sofort uebernommen und nicht ausgewartet; nach Fristablauf wird abgebrochen, nicht
durchgewunken; ein lebender fremder **Mutex** bleibt fuer jeden Mitbewerber ein
harter Abbruch.

## 3. Abgrenzung

Die Frist ist ein Betriebswert und steht als Konstante im Code
(`semantic_gate.INTENT_WAIT_SECONDS`), wie schon die Mutex-TTL. FK-93 fuehrt
keinen der beiden Werte; diese Entscheidung aendert daran nichts und legt die
Zahl in der Norm bewusst nicht fest — normativ ist „beschraenkt warten, dann
fail-closed", nicht die Sekundenzahl.

Kein neuer Scope, keine neue Faehigkeit: die Nebenlaeufigkeitsgarantien sind
unveraendert, nur erreicht sie der Mechanismus jetzt auch tatsaechlich.

## 4. Betroffenheitsmatrix

| # | Gegenstand | Datei / Abschnitt | Klassifikation | Aenderung |
|---|-----------|-------------------|----------------|-----------|
| 2.1 | Klinke vs. Eigentum | FK-78 §78.4 | geaendert | Intent als kurz gehaltene Klinke benannt; Wartefrist statt sofortigem Verlieren |
| 2.1 | Takeover-Satz | FK-78 §78.4 | geaendert | „wer es nicht anlegen kann, verliert" → „wer es auch nach Ablauf der Wartefrist nicht anlegen kann, verliert" |
| 2.2 | Leerer Create | FK-78 §78.4 | geaendert | Spalt zwischen Create und Payload-Write ist ein Halten, kein verwaistes Intent |
| 2.3 | Eigentuemer-Bypass | FK-78 §78.4 | nicht-betroffen | ausdruecklich verworfen; Atomizitaet Pruefung↔Wirkung bleibt |
| 2.4 | Geschuldete Wirkungen | FK-78 §78.4 | geaendert | Loeschen/Ersetzen werden wiederholt; gescheitertes Ersetzen = Abbruch, gescheitertes Loeschen = WARNING, nie stiller Erfolg |
| 2.4 | Poll-Disziplin | FK-78 §78.4 | geaendert | Wartende lesen die Payload nur im Sekundentakt; der exklusive Create ist die Probe |
| 2.4 | Verweigerter Create | FK-78 §78.4 | geaendert | nicht-EEXIST-Fehler am Create = verlorener Anspruch mit Exit-Code, kein Traceback |
| 2.4 | Sharing-Rest | FK-78 §78.4, benannte Grenze | erweitert | nicht loeschbare Klinke ueberlebt bis TTL; als Teil derselben Grenze deklariert |
| 2.5 | Aufraeumen verwaister Intents | FK-78 §78.4, benannte Grenze | nicht-betroffen | Read-then-Unlink-Grenze und mtime-Fallback unveraendert |
| — | Mutex-Semantik | FK-78 §78.4 | nicht-betroffen | Nonce, TTL, Heartbeat, Fencing-Token-CAS unveraendert |

## 5. Herkunft der Ratifikation

PO-Auftrag 2026-08-01: „setz jetzt mal die 179 um gemaess der bisherigen
Richtlinien." Die Loesungsrichtung — beschraenktes Warten, Invarianten
unangetastet, kein Bypass fuer den Eigentuemer — war Bestandteil der Story
AG3-179, die der PO mit diesem Auftrag zur Umsetzung freigegeben hat.

Die Normkorrektur wurde nicht vorab einzeln vorgelegt: den Fix zu bauen und die
Norm weiter „sofort verlieren" sagen zu lassen, waere die schlechtere
Alternative gewesen. Das Delta ist dem PO im Abschlussbericht dieser Story im
Wortlaut vorgelegt.
