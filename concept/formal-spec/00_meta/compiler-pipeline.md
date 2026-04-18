---
title: Formal Spec Compiler Pipeline
status: active
doc_kind: core
authority_over:
  - scope: formal-spec-compiler
  - scope: formal-spec-lint
---

# Formal Spec Compiler Pipeline

## 1. Ziel

Der AK3-Concept-Compiler prueft die Formalspezifikation deterministisch.

Er erzeugt keine Produktionsartefakte, sondern:

- Fehler bei inkonsistenter Spezifikation
- Warnungen bei unvollstaendiger oder driftgefaehrdeter Spezifikation
- abgeleitete Reports unter `var/`

## 2. Mindestphasen des Compilers

### Phase 1 - Parse und Schema

Der Compiler liest:

- Frontmatter
- die kanonische Spezifikationszone

Er prueft:

- formale Dateistruktur
- Pflichtfelder
- erlaubte `spec_kind`
- erlaubte Objektarten

### Phase 2 - Referenzaufloesung

Der Compiler prueft:

- existieren alle referenzierten IDs
- sind Referenzen typkompatibel
- gibt es Namenskollisionen
- gibt es tote oder unaufloesbare Referenzen

### Phase 3 - Modellkonsistenz

Der Compiler prueft mindestens:

- terminale Zustaende werden nicht illegal weiterverwendet
- Uebergaenge verweisen auf existierende Zustaende
- Commands haben definierte Wirkungen
- Events und Invarianten besitzen gueltige Bezuege

### Phase 4 - Vollstaendigkeitsregeln

Der Compiler prueft regelbasiert, ob die Spezifikation den geforderten
Mindestdeckungsgrad erreicht.

Beispiele:

- nicht-terminale Zustaende haben mindestens einen legalen Ausweg oder
  sind explizit blockierend markiert
- Commands sind mindestens einmal in Szenarien referenziert
- terminale Zustaende sind ueber deklarierte Traces erreichbar oder
  bewusst als administrativ markiert

### Phase 5 - Trace-Validierung

Der Compiler fuehrt keine allgemeine exhaustive Pfadsuche durch.

Er validiert nur deklarierte Traces aus `scenario-set`:

- Startbedingung ist legal
- jeder Schritt ist entlang des Modells legal
- Guards und Invarianten werden eingehalten oder gezielt verletzt, wenn
  das Szenario genau dies behauptet
- der Endzustand entspricht dem deklarierten terminalen oder
  erwarteten Fehlerausgang

### Phase 6 - Drift-Audit gegen Prosa

Der Compiler prueft:

- referenzierte Formal-IDs aus Prosa existieren
- Pflicht-Referenzen sind vorhanden
- driftkritische Frei-Listen in Prosa sind nicht als parallele zweite
  Wahrheit gepflegt

## 3. Intermediate Representation

Der Compiler normalisiert alle Formal-Spec-Dateien in eine interne
Zwischendarstellung.

Diese IR ist die Grundlage fuer:

- Konsistenzpruefungen
- Trace-Validierung
- Coverage-Auswertungen
- Change-Impact-Analyse
- Reports

## 4. Ausgaben

Generierte Ausgaben gehoeren ausschliesslich nach `var/`, zum Beispiel:

- normalisierte IR
- Traceability-Matrix
- Coverage-Report
- Compile-Report

Diese Ausgaben sind Hilfsartefakte und nie die kanonische Wahrheit.

## 5. Zielbild der Toolchain

Die erste Toolchain ist repo-integriert und pragmatisch.

Zielbild:

- Python-basierter Compiler/Linter
- CI-faehig
- ohne Spezialformalismus als Primärsystem

Spezialwerkzeuge wie TLA+, Alloy oder Statecharts koennen spaeter fuer
Teilprobleme ergaenzt werden, sind aber nicht der Basispfad von AK3.

## 6. Erfolgsbegriff

Eine Formal-Spec gilt genau dann als "buildbar", wenn:

1. alle Compiler-Phasen erfolgreich durchlaufen
2. deklarierte Traces legal validiert sind
3. keine Drift-Fehler gegen die Prosa offen sind
4. keine verbotene zweite Wahrheitsquelle entstanden ist
