---
title: Formal Spec ID and Reference Scheme
status: active
doc_kind: core
authority_over:
  - scope: formal-spec-ids
  - scope: formal-spec-references
---

# Formal Spec ID and Reference Scheme

## 1. Ziel

Alle formalen Objekte und alle driftkritischen Verweise muessen stabil,
eindeutig und umbenennungsfest adressierbar sein.

Darum sind Dateinamen und relative Pfade nie die kanonische
Referenzbasis. Kanonisch sind nur IDs.

## 2. Dokument-ID

Jede Datei unter `concept/formal-spec/` hat eine globale Dokument-ID im
Frontmatter-Feld `id`.

Namensschema:

`formal.<context>.<artifact>`

Beispiele:

- `formal.workflow-engine.state-machine`
- `formal.story-split.commands`
- `formal.github-integration.events`

## 3. Objekt-IDs innerhalb der Spezifikationszone

Jedes fachliche Objekt innerhalb des YAML-Blocks besitzt eine stabile
`id`.

Namensschema:

`<context>.<kind>.<name>`

Beispiele:

- `workflow-engine.state.running`
- `workflow-engine.transition.pause`
- `story-split.command.execute`
- `story-split.event.completed`
- `story-split.invariant.successors_created`

## 4. Referenzregel

Referenzen zwischen Formal-Objekten erfolgen ausschliesslich ueber
diese IDs.

Nicht zulaessig:

- Referenz ueber Dateiname
- Referenz ueber Ueberschrift
- Referenz nur ueber Ordnername

Zulaessig:

- `from: workflow-engine.state.paused`
- `emits: [story-split.event.completed]`
- `requires: [story-split.invariant.successors_created]`

## 5. Prosa-Referenzen

Normative Aussagen in `domain-design/` oder `technical-design/`
muessen Formal-IDs referenzieren.

Der konkrete Inline-Mechanismus wird spaeter technisch festgezogen.
Semantisch ist jetzt schon verbindlich:

- Prosa referenziert Formal-IDs
- nicht Formal-Dateinamen
- nicht nur Kapitelnummern

## 6. Formale Rueckverweise auf Prosa

Formal-Spec-Dateien duerfen im Frontmatter `prose_refs` fuehren.

Diese verweisen auf:

- konkrete Konzeptdateien
- spaeter optional auf stabile Abschnittsanker

Zweck:

- Traceability
- Drift-Audit
- Change-Impact-Analyse

## 7. ID-Stabilitaet

Eine einmal vergebene Formal-ID wird nicht stillschweigend recycelt.

Bei Umbenennung oder fachlicher Aufspaltung gilt:

- neue Objekte erhalten neue IDs
- stillgelegte IDs werden explizit als deprecated/superseded behandelt,
  sobald dieser Lebenszyklus modelliert wird

## 8. Kontextnamen

Kontextnamen im ID-Schema muessen:

- lowercase sein
- Bindestriche statt Unterstriche verwenden
- fachlich stabil sein
- nicht an momentane Dateistruktur oder Klassennamen gekoppelt sein

## 9. Konfliktregel

Wenn dieselbe fachliche Aussage sowohl als freie Prosa als auch als
Formal-ID existiert, gewinnt fuer maschinenpruefbare Semantik immer die
Formal-ID.
