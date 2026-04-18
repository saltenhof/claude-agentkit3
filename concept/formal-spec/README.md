---
title: AgentKit 3 Formal Spec
status: active
doc_kind: meta
---

# AgentKit 3 - Formal Spec

`concept/formal-spec/` ist die autoritative, deterministisch pruefbare
Spezifikationsschicht von AgentKit 3.

Sie existiert **zusaetzlich** zu den Prosa-Konzepten unter
`concept/domain-design/` und `concept/technical-design/`.

## Zweck

Die Formalspezifikation beschreibt genau die Teile von AK3, die ich
maschinell pruefen, linten, referenzaufloesen, auf Konsistenz
kontrollieren und ueber deklarierte Traces bis zu terminalen Zustaenden
validieren will.

Sie ersetzt die Prosa nicht.

- Prosa erklaert, begruendet und grenzt ab.
- Formal-Spec normiert diskrete, pruefbare Systemsemantik.

## Zielstruktur

Die Ablage folgt primaer fachlichen Kontexten bzw. Komponenten, nicht
globalen Artefakt-Silos.

```text
concept/formal-spec/
  00_meta/
    README.md
    meta-contract.md
  <context-a>/
    README.md
    state-machine.md
    commands.md
    events.md
    invariants.md
    scenarios.md
  <context-b>/
    ...
```

## Strukturregeln

1. Top-Level unter `formal-spec/` sind fachliche Kontexte oder
   Meta-Regelwerke.
2. Ein Kontext darf mehrere formale Teilaspekte enthalten
   (`state-machine`, `events`, `commands`, `invariants`, `scenarios`),
   aber diese bleiben lokal am selben fachlichen Ort.
3. Globale Artefakt-Silos wie `states/`, `constraints/` oder
   `scenarios/` auf Top-Level sind nicht zulaessig.
4. Traceability- und Compile-Artefakte sind keine Source of Truth und
   gehoeren nach `var/`.

## Autoritaetsregel

Die verbindlichen Meta-Regeln fuer diese Schicht stehen in
`concept/formal-spec/00_meta/meta-contract.md`.
