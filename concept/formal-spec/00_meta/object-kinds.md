---
title: Formal Spec Object Kinds
status: active
doc_kind: core
authority_over:
  - scope: formal-spec-object-kinds
---

# Formal Spec Object Kinds

## 1. Ziel

Dieses Dokument legt fest, welche formalen Objektarten in AK3
zulaessig sind und welchen Mindestumfang sie haben.

## 2. Zulaessige Kernobjektarten fuer v1

Die erste formale Schicht von AK3 kennt genau diese Kernobjektarten:

- `state-machine`
- `command-set`
- `event-set`
- `invariant-set`
- `scenario-set`
- `entity-set`

Begruendung:

- Diese Objektarten decken den operativen, diskreten Kern von AK3 ab.
- Sie reichen aus, um Zustaende, Commands, Events, Invarianten,
  minimale Entitaeten und deklarierte Ablaufpfade formell zu fassen.
- Zusetzliche Spezialobjektarten werden erst eingefuehrt, wenn der
  Kern nicht mehr traegt.

## 3. Mindestinhalt pro Objektart

### `state-machine`

Muss mindestens enthalten:

- initiale Zustaende
- nicht-initiale Zustaende
- terminale Zustaende
- Uebergaenge
- Guards oder Vorbedingungen pro Uebergang, soweit vorhanden

### `command-set`

Muss mindestens enthalten:

- Commands mit stabilen IDs
- erlaubte Ausgangszustaende
- beabsichtigte Effekte
- resultierende Events und/oder Transitionen

### `event-set`

Muss mindestens enthalten:

- Events mit stabilen IDs
- Produzent oder ausloesender Kontext
- Payload-Grundstruktur
- semantische Rolle des Events

### `invariant-set`

Muss mindestens enthalten:

- Invarianten mit stabilen IDs
- Geltungsbereich
- pruefbare Regel in deterministischer Form

### `scenario-set`

Muss mindestens enthalten:

- deklarierte Traces
- Startbedingung
- Schrittfolge ueber Commands, Events oder Transitionen
- erwarteter terminaler Ausgang oder erwartete Regelverletzung

### `entity-set`

Muss nur dann angelegt werden, wenn der Kontext mindestens eine
Entitaet mit Identitaet, Lifecycle oder referenzierter Ownership fuer
die formale Semantik benoetigt.

Mindestumfang:

- Entitaets-ID
- Identitaetsschluessel
- fachliche Kernattribute
- Lifecycle-Relevanz, falls vorhanden

## 4. Nicht als eigene Kernobjektart in v1

Bewusst **keine** eigene Top-Level-Objektart in v1 sind:

- `edge-case`
- `ownership`
- `traceability`
- `policy`

Begruendung:

- Edge Cases werden in v1 als Szenarien oder Regelverletzungen
  modelliert.
- Ownership bleibt zunaechst Meta- oder Prosa-Information.
- Traceability ist eine Querschnittsfunktion, kein fachlicher
  Primaerinhalt.
- Policies werden erst als eigene Objektart eingefuehrt, wenn sie nicht
  mehr sauber in Commands, Invarianten oder States aufgehen.

## 5. Einfuehrung neuer Objektarten

Neue formale Objektarten duerfen nur eingefuehrt werden, wenn:

1. der bestehende Satz nachweislich nicht ausreicht
2. die neue Objektart einen eigenstaendigen pruefbaren Mehrwert bringt
3. Syntax, Compiler-Regeln und Drift-Auswirkungen mit angepasst werden
