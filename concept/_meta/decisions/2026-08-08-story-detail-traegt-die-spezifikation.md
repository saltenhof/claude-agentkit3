---
concept_id: META-DEC-2026-08-08-STORY-DETAIL-CARRIES-SPECIFICATION
title: Concept-Decision-Record — der projekt-skopierte Story-GET traegt die Spezifikation
module: meta
cross_cutting: true
status: active
authority_over: []
doc_kind: decision-record
defers_to:
  - target: FK-91
    scope: api-catalog
    reason: FK-91 owns the /v1 operation catalog this record adds a response field to
  - target: FK-10
    scope: distribution-boundary
    reason: FK-10 owns the edge/core cut that makes the operation necessary
supersedes: []
superseded_by:
tags: [meta, decision-record, api-catalog, distribution, story-lifecycle, AG3-240]
formal_scope: prose-only
---

# Concept-Decision-Record — der projekt-skopierte Story-GET traegt die Spezifikation

Datum: 2026-08-08. Record fuer AG3-240.

## 1. Anlass

AK3 soll auf zwei Maschinen laufen: **Project Edge** auf dem Entwicklerrechner,
**Kern** auf einem zentralen Server. `/v1` ist die einzige vorgesehene Bruecke
(FK-01 §1.2.3). Was der Edge heute als Python-Funktion ruft, muss dort eine
Operation haben — sonst bricht der Distributionsschnitt an dieser Stelle.

`export-story-md` braucht `Story` **und** `StorySpecification`
(`story_creation/story_md_export.py:68`). Die CLI konstruiert dafuer bis heute
den kern-lokalen `StoryService` (`cli/story_commands.py:467`).

## 2. Der Befund, der diesen Record ausgeloest hat

AG3-240 hatte zunaechst behauptet, die Operation existiere bereits als
`GET /v1/stories/{story_id}`. **Das ist falsch.** Diese Route lebt
ausschliesslich innerhalb von `StoryContextRoutes`; die produktive Anwendung
delegiert **ausschliesslich projekt-skopierte** Story-Routen und die baren
`/v1/stories`-Routen ausdruecklich **nicht** (`control_plane_http/app.py:908`).

Der tatsaechlich exponierte Projekt-GET antwortete mit `StoryDetail`
(`app.py:210`) — einem Modell **ohne** Spezifikationsfeld (`story/models.py:79`).

**`Story + StorySpecification` war von ausserhalb des Kerns nicht erreichbar.**

Das unabhaengige Review hat den Fehler gefunden; er stand vorher als „null neue
Endpunkte noetig" im Story-Record und im Bericht an den PO.

## 3. Entscheidung

**Der projekt-skopierte GET wird erweitert. Es entsteht kein neuer Pfad.**

- `StoryDetail` traegt das neue Feld `specification: StorySpecification | None`.
- `None` bedeutet **keine Spezifikation erfasst** — niemals „nicht geladen".
  Ein Feld, das zwei Zustaende in einem `null` vermischt, waere an der
  Netzgrenze nicht mehr unterscheidbar.
- `StoryReadPort.load_story_specification(project_key, story_id)` ist die neue
  Portmethode; die Implementierung **verifiziert den `project_key`**, damit ein
  auf ein Projekt beschraenkter Aufrufer nie die Spezifikation eines anderen
  erhaelt.

## 4. Was ausdruecklich NICHT entschieden wird

**Die bare Route `/v1/stories/...` bleibt undelegiert.** Die Spezifikation auf
der Projektroute mitzufuehren darf keinen zweiten Weg hinein oeffnen. Ein Test
haelt das fest; ohne ihn waere die Erweiterung eine stille Vergroesserung der
Angriffsflaeche.

## 5. Warum eine Erweiterung und kein neuer Endpunkt

`CLAUDE.md` §FIX THE MODEL, NOT THE SYMPTOM und AC 3 der BC-Storys: Mehrere
Aufrufe desselben fachlichen Vorgangs werden **eine** Operation. „Story-Detail
lesen" ist ein Vorgang. Ein zweiter Pfad daneben waere ein zweiter Weg zu
derselben Sache — genau das, was `CLAUDE.md` §SINGLE SOURCE OF TRUTH
ausschliesst.

## 6. Betroffenheitsmatrix

| Dokument | Aenderung |
|---|---|
| **FK-91 §91.1** | Antwortfeld `specification`, seine `null`-Semantik und die Begruendung; additive Tabellenzeile am bestehenden Anker |
| FK-10 | unveraendert — der Schnitt selbst aendert sich nicht |
| FK-01 | unveraendert — die Operation ist kern-seitig, kein Hook-Pfad beruehrt |
| Formal Spec | unveraendert — keine Distributionszuordnung geaendert |

## 7. Was offen bleibt

Die Serverhaelfte ist damit vollstaendig. **Edge-Modell und Client gehoeren
AG3-209**, das den edge-seitigen Story-Typ praegt. Bis dahin bewegt sich die
Grenzverletzungszahl dieser Ueberquerung nicht — das ist der ehrliche Stand und
nicht als Fortschritt zu berichten.
