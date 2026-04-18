---
title: Formal Spec Meta Contract
status: active
doc_kind: core
authority_over:
  - scope: formal-spec-structure
  - scope: formal-spec-authority
  - scope: formal-spec-compile
  - scope: formal-spec-drift-control
---

# Formal Spec Meta Contract

## 1. Zweck

Die formale Spezifikationsschicht ist die autoritative Quelle fuer alle
AK3-Aussagen, die sich als diskrete, deterministisch pruefbare
Systemsemantik ausdruecken lassen.

Sie dient dazu, dass ich nicht nur Konzepte schreibe, sondern sie auch
maschinell gegen Konsistenz, Vollstaendigkeit und deklarierte
Ablaufpfade pruefen kann.

## 2. Autoritaetsgrenze

Es gelten zwei unterschiedliche Wahrheitsbereiche:

1. `concept/domain-design/` und `concept/technical-design/`
   erklaeren, begruenden und grenzen ab.
2. `concept/formal-spec/` normiert alle diskreten, maschinenpruefbaren
   Aussagen.

Bei Konflikten gilt:

- Fuer maschinenpruefbare Aussagen gewinnt `formal-spec/`.
- Fuer Rationale, Trade-offs, Heuristiken, UX, offene Risiken und
  ausserhalb des Modells liegende Aspekte bleibt die Prosa autoritativ.

## 3. Was zwingend formal werden muss

Die formale Schicht muss mindestens diese Objektarten abdecken:

- Zustaende
- Uebergaenge
- Terminalitaet
- Commands bzw. CLI-Wirkungen
- Events
- Invarianten
- deklarierte Szenario-Traces
- die minimal noetigen Entitaeten/Aggregate mit Identitaet oder
  Lifecycle-Bedeutung

Diese Dinge werden formal, weil ich sie deterministisch pruefen kann.

## 4. Was bewusst in Prosa bleibt

Nicht Teil des formalen Kerns sind:

- Architektur-Rationale
- Trade-offs
- UX-Entscheidungen
- organisatorische Ownership
- qualitative Heuristiken
- fachliche Motivation
- nichtdeterministische oder externe Betriebsrealitaet, soweit sie
  nicht als diskrete Annahme modelliert wird

Diese Inhalte bleiben in `domain-design/` oder `technical-design/`.

## 5. Strukturprinzip

Die Ablage unter `concept/formal-spec/` erfolgt primaer nach
fachlichem Kontext oder Komponente.

Zulaessig:

```text
concept/formal-spec/
  workflow-engine/
    state-machine.md
    events.md
    commands.md
    invariants.md
    scenarios.md
```

Nicht zulaessig:

```text
concept/formal-spec/
  states/
  constraints/
  scenarios/
```

Begruendung:

- Ein fachlicher Change muss lokal zusammenbleiben.
- Zustandslogik, Events, Commands, Invarianten und Szenarien eines
  Kontexts duerfen nicht auf globale Artefakt-Silos verstreut werden.

## 6. Form der Dateien

`formal-spec/` bleibt Markdown-only, um mit den Repo-Guardrails
kompatibel zu bleiben.

Gleichzeitig gilt:

- Formal-Spec-Dateien sind **structured markdown**, nicht freie
  Fliesstextdokumente.
- Die normative Semantik liegt nur in explizit definierten,
  maschinenlesbaren Strukturzonen.
- Freie Erlaeuterung ausserhalb dieser Zonen ist erlaubt, aber nicht
  normative Quelle.

Die konkrete Syntax der Strukturzonen wird spaeter separat
festgezogen. Dieses Dokument legt nur den Vertrag fest, dass die
normative Semantik nicht aus freiem Text gelesen werden darf.

## 7. Was `compile` bedeutet

`compile` bedeutet in AK3 nicht Sourcecode-Erzeugung, sondern eine
deterministische Validierungspipeline fuer die Formalspezifikation.

Mindestens enthalten sind:

1. Parse- und Schema-Pruefung
2. Referenzaufloesung
3. Modellkonsistenzpruefung
4. Vollstaendigkeitspruefung nach expliziten Coverage-Regeln
5. Validierung deklarierter Szenario-Traces bis zu einem erlaubten
   terminalen Zustand
6. Drift-Audit gegen die Prosa-Konzepte

Nicht Teil von `compile` ist ein vollstaendiges allgemeines
Model-Checking ueber alle moeglichen Pfade.

## 8. Grenzen der formalen Schicht

Die Formalspezifikation beweist nicht:

- fachliche Angemessenheit
- Produkt- oder UX-Qualitaet
- Vollverhalten externer Systeme
- organisatorische Prozesse
- nichtdeterministische Realwelteffekte

Diese Restmenge muss weiterhin in der Prosa dokumentiert werden.

Prosa-Konzepte mit formal relevanten Themen sollen deshalb explizit
kennzeichnen:

- was ausserhalb des formalen Scopes liegt
- welche Annahmen nicht maschinell geprueft werden
- welche betrieblichen Risiken bestehen bleiben

## 9. Drift-Schutz

Drift zwischen `formal-spec/` und den Prosa-Konzepten darf nicht nur
ueber menschliche Disziplin behandelt werden.

Deshalb gelten diese Regeln:

1. Formale Objekte erhalten stabile IDs.
2. Prosa-Konzepte referenzieren diese IDs dort, wo sie normatives
   Verhalten beschreiben.
3. Vollstaendige Listen von Zustaenden, Events, Commands oder
   Transitionen duerfen nicht parallel als frei gepflegte Prosa-Kopie
   existieren.
4. CI bzw. der Concept-Compiler prueft:
   - dangling references
   - fehlende Pflicht-Referenzen
   - normatives Verhalten in Prosa ohne Formal-Bezug, soweit dies
     regelbasiert erkennbar ist

## 10. Generate-vs-Source-of-Truth

Generierte oder abgeleitete Artefakte sind nie autoritativ.

Dazu gehoeren insbesondere:

- Traceability-Matrizen
- Compile-Reports
- Coverage-Reports
- normalisierte AST- oder IR-Ausgaben
- generierte Tabellen oder Sichten

Diese Artefakte gehoeren nach `var/`, nicht nach `concept/`.

## 11. Minimaler naechster Schritt

Bevor inhaltliche Formalspezifikationen entstehen, muessen festgezogen
werden:

1. Dateisyntax fuer structured markdown
2. ID- und Referenzschema
3. kleinster gemeinsamer Satz an Objektarten
4. Compiler-/Lint-Pipeline als repo-integrierte Toolchain
