# Software-Blutgruppen — Klassifikation von Code nach Verantwortung und Testbarkeit

Methodisches Grundlagendokument. Die Klassifikation gilt projektuebergreifend
und ist nicht an AgentKit gebunden. AK3-spezifische Regeln, die auf dieser
Klassifikation aufsetzen, gehoeren in den Architektur-Guardrails (ARCH-22)
und in die Architecture-Conformance-Specs.

## 1. Zweck

Die Software-Blutgruppen klassifizieren Code-Anteile nach ihrer
Verantwortung im Gesamtsystem und an ihrer Eignung fuer
deterministische, infrastrukturarme Tests. Die Klassifikation hat
keinen aesthetischen Selbstzweck. Ihre Aufgaben sind:

1. **Testbarkeit sichern.** Fachlogik soll mit minimalem Setup
   deterministisch testbar sein. Technologie- und umgebungsabhaengiger
   Code soll auf dafuer vorgesehene Bereiche begrenzt werden, damit der
   fachliche Kern nicht in deren Test-Schwere mit hineingezogen wird.

2. **Substitutierbarkeit der Technik sichern.** Datenbanken, Transport-
   Schichten, externe Dienste muessen austauschbar bleiben, ohne dass
   die Fachlogik des Systems angefasst werden muss.

3. **Wiederverwendbarkeit ermoeglichen.** Domaenenfreie Hilfsfunktionen
   muessen projekt- und domaenenuebergreifend nutzbar bleiben. Der
   fachliche Kern muss unabhaengig von der konkreten Technik
   ausserrum (CLI, REST, GUI) wiederverwendbar sein.

4. **Verantwortung sichtbar machen.** Jeder Code-Anteil bekommt eine
   eindeutige Heimat. Code-Anteile ohne klare Heimat sind ein
   architektonisches Symptom, nicht eine Realitaet, mit der man leben
   muss.

Die Klassifikation ist *kontextabhaengig*. Was im einen System
Kernfachlichkeit ist, ist im anderen System reine Infrastruktur. Es
gibt keine universelle Liste von "A-Themen" oder "T-Technologien".
Entscheidend ist immer, was zur Kernfachlichkeit *des konkret
modellierten Systems* gehoert.

## 2. Die vier Beurteilungsdimensionen

Code-Anteile werden entlang von vier Dimensionen beurteilt:

| Dimension | Frage |
|---|---|
| **Domaenenbindung** | Ist dieser Code Teil der Kernfachlichkeit des Systems? |
| **Umgebungsbindung** | Haengt dieser Code an einer konkreten technischen Laufzeit-Umgebung (Datenbank, Netzwerk, Filesystem, OS, externer Cluster, UI-Toolkit)? |
| **Domaenen-Inhaerenz des Test-Aufwands** | Ist der fuer realistische Tests noetige Infrastruktur-Aufwand *inhaerenter* Bestandteil der Domaene, oder *Folge* einer Aussenwelt-Bindung, die mit der Domaene selbst nichts zu tun hat? |
| **Wiederverwendbarkeit** | Laesst sich dieser Code projekt- und domaenenuebergreifend einsetzen, oder ist er an die konkrete Anwendung bzw. Technologie gebunden? |

Kein einzelner Test entscheidet allein. Erst das Profil ueber alle
vier Dimensionen ergibt den Bluttyp.

## 3. Die vier Klassen

### 3.1 A — Fachlogik (Domaenenkern)

**Definition.** Code, der die Kernfachlichkeit des Systems traegt:
Geschaeftsregeln, Algorithmen, Lifecycle-Uebergaenge, Invarianten,
Validierungen. Sprache und Begriffe gehoeren zur Domaene, nicht zur
Technik.

| Dimension | Profil |
|---|---|
| Domaenenbindung | hoch — projekt- und anwendungsspezifisch |
| Umgebungsbindung | keine — abstrakt, technologiefrei |
| Test-Aufwand | niedrig — Eingabe, Verarbeitung, Ausgabe; ohne Container, ohne Netzwerk, ohne Mocks |
| Wiederverwendbarkeit | innerhalb der Domaene wiederverwendbar; technologie-unabhaengig (derselbe Kern unter CLI, REST, GUI) |

**Erkennungssatz.** Dieser Code laesst sich in einem reinen Unit-Test
mit synthetischen Eingaben pruefen, ohne dass eine Infrastruktur
hochgefahren werden muss.

### 3.2 R — Repraesentation

**Definition.** Code, dessen Aufgabe die Ueberfuehrung einer
Repraesentation in eine andere ist. R kennt Domaenenbegriffe, weil er
domaenenspezifische Repraesentationen aufeinander abbildet. R
uebersetzt **Repraesentationen**, nicht **Mechanik**.

| Dimension | Profil |
|---|---|
| Domaenenbindung | mittel — kennt die Repraesentationen mehrerer Seiten |
| Umgebungsbindung | gering bis mittel — uebersetzt; haengt nicht direkt an Infrastruktur, kann sie aber kapseln |
| Test-Aufwand | niedrig bis mittel — testbar, sobald beide Repraesentationen synthetisch erzeugbar sind |
| Wiederverwendbarkeit | bezogen auf das Repraesentationspaar |

**Typische Aufgaben.** API-DTO ↔ Domain-Modell, View-Modell ↔ Template,
Wire-Format ↔ interne Repraesentation, JSON-Schema ↔ getypter
Domain-Record. Anti-Korruptions-Schicht ist eine *Rolle*, die R
einnehmen kann, aber nicht der Kern. Der Kern ist Transformation.

**Funktion im Klassifikations-System.** R fuellt die Luecke zwischen A,
T und 0. Code-Anteile, die sich nicht eindeutig als A, T oder 0 lesen
lassen, sind meist R.

**Wichtige Grenze.** Wo nicht nur Entitaeten, sondern auch *Mechanik*
uebersetzt werden muss (Lade-Strategien, Transaktionsgrenzen,
Konsistenzregeln), reicht reines R nicht — dort entsteht zwingend
AT-Code (siehe 4.2).

### 3.3 T — Technik / Infrastruktur

**Definition.** Code mit direkter Bindung an eine konkrete technische
Laufzeit-Umgebung, deren Beherrschung *nicht* zur Kernfachlichkeit
des Systems gehoert. T enthaelt nicht nur die unmittelbaren
Treiber-Calls, sondern auch das Mechanik-Wissen ueber die Technologie
(z.B. wie modelliert man Vererbung in einer relationalen vs.
dokumentenbasierten Datenbank, welche Lade-Strategien sind sinnvoll,
welche Indizes wirken).

| Dimension | Profil |
|---|---|
| Domaenenbindung | keine — ausserhalb der Kernfachlichkeit |
| Umgebungsbindung | hoch — an eine konkrete Technologie gekoppelt (Postgres ≠ MySQL ≠ MSSQL ≠ Solr-SQL; HTTP ≠ gRPC; lokales FS ≠ S3) |
| Test-Aufwand | hoch — realistisches Test-Setup verlangt Infrastruktur-Bring-up |
| Wiederverwendbarkeit | niedrig — technologie-spezifisch |

**Drei Erkennungstests, die zusammen wirken:**

1. **Kontext-Test.** Liegt dieser Code ausserhalb der Kernfachlichkeit?
2. **Substitutierungs-Test.** Wuerde ein Wechsel der Technologie die
   Fachlogik *nicht* beruehren?
3. **Inhaerenz-Test.** Ist der Infrastruktur-Aufwand fuer realistische
   Tests *Folge externer Bindung*, statt inhaerenter Bestandteil der
   Domaene?

Erst wenn alle drei zutreffen, ist es eindeutig T. Ein einzelner
Test reicht nicht.

**Kontextrelativitaet.** Dasselbe Code-Stueck kann in einem System A
und in einem anderen System T sein. Beispiel: HTTP-Client. Im
Webcrawler ist die HTTP-Beherrschung Teil der Kernfachlichkeit
(HTTP-Codes, robots.txt, Retry-Mechanismen, Content-Negotiation) —
also A. In einer Geschaeftsanwendung, die nur "eine Information aus
einer Quelle" braucht, und diese Quelle zufaellig eine Webseite ist,
ist HTTP genau das umgebungsspezifische Detail, das die Fachlogik
nicht interessiert — also T.

### 3.4 0 — Null-Software (Utilities)

**Definition.** Code, der projekt- und domaenenunabhaengig
wiederverwendbar ist. 0-Code darf technische Anteile enthalten (ein
Logging-Framework mit File- und DB-Appendern ist Null-Software),
solange er generisch bleibt und keine Domaenenbindung traegt.

| Dimension | Profil |
|---|---|
| Domaenenbindung | keine — vollstaendig domaenenfrei |
| Umgebungsbindung | keine bis generisch-technisch — kann technische Anteile haben (Logger schreibt in eine Datei), aber generisch genug, dass das Zielsystem nicht festgelegt ist |
| Test-Aufwand | niedrig |
| Wiederverwendbarkeit | maximal — projekt- und domaenenuebergreifend einsetzbar |

**Typische Beispiele.** String-, Datums-, Math-Utilities, generische
Datenstrukturen, Logging-Frameworks, generische Type-Bridges,
Exception-Basisklassen ohne Domaenenbezug, atomic-write-Mechaniken,
JSON-load-/dump-Wrapper.

**Erkennungssatz.** Dieser Code laesst sich in jedes andere Projekt
kopieren, ohne dass mit ihm Domaenenwissen mitgenommen wird.

## 4. Mischformen

### 4.1 Warum Mischformen ueberhaupt vorkommen

Die saubere Trennung in vier reine Klassen ist ein analytisches Werkzeug,
nicht ein Versprechen, dass jeder Code-Anteil *zwingend* genau in eine
Klasse passt. In der Praxis gibt es Stellen, an denen mehrere Klassen
zwingend gemeinsam vorkommen muessen, weil ihre Verantwortungen
*konstitutiv aufeinander angewiesen* sind. Solche Stellen heissen
Mischformen. Sie sind nicht per se Antipattern; sie sind erwartbar an
Schnittstellen zwischen fachlicher und technischer Welt.

### 4.2 AT-Code — die haeufigste Mischform

**Definition.** AT-Code ist Code, der *Fachlogik und
Technologie-Mechanik gleichzeitig traegt*, weil seine Aufgabe die
Mediation zwischen beiden Welten ist. R-Repraesentations-Uebersetzung
allein reicht hier nicht, weil nicht nur Entitaeten, sondern auch
Mechanik (Lade-Strategie, Transaktionsgrenzen, Konsistenzregeln)
uebersetzt werden muss.

**Beispiel 1 — Datenbank-Zugriffsschicht.** Eine Datenbank-Zugriffsschicht
muss von aussen fachliche Entitaeten entgegennehmen und auf
datenbankspezifische Strukturen abbilden. Zugleich muss sie
entscheiden, wie Vererbung in der DB modelliert wird, was normalisiert
oder denormalisiert ist, wann lazy oder eager geladen wird, wo
Transaktionsgrenzen liegen. Das ist konstitutiv AT — es laesst sich
nicht in reines R + reines T aufspalten, weil die Mechanik selbst Teil
der Mediation ist.

**Beispiel 2 — UI-Anwendungsrahmen.** Ein generischer
Anwendungsrahmen (Window-Manager, Routing, Dialog-Verwaltung,
Lifecycle, Eventbus) hat einen klaren A-Anteil — die *Konzepte* eines
Dialogs (er hat einen Zustand, er kann sich schliessen, er ist
hierarchisch geschachtelt) sind fachliche Modelle dieses
Anwendungsrahmens. Zugleich projiziert der Rahmen diese Konzepte auf
eine konkrete Technologie (Qt, React, Terminal, native Mobile-Bridge),
und dort liegt der T-Anteil. Der Rahmen ist konstitutiv AT.

Das *einzelne Dialog* eines solchen Rahmens kann demgegenueber rein
A bleiben — weil es nur die fachlichen Modelle des Rahmens nutzt und
die Technologie-Projektion vom Rahmen erledigt wird.

### 4.3 Was "AT minimieren" wirklich heisst

Die haeufige Norm-Aussage "AT-Code minimieren" wird leicht
missverstanden als "AT-Code auf null reduzieren". Das waere falsch
und in der Praxis auch unmoeglich. Der echte Kern der Norm ist:

> **AT-Code lokalisieren, damit der A-Kern AT-frei bleibt.**

AT ist an bestimmten Stellen konstitutiv und unausweichlich (Datenbank-
Zugriffsschichten, UI-Anwendungsrahmen, Sync-Adapter, Importer,
Mediation-Mapper). Das Ziel der Norm ist nicht Eliminierung, sondern
**Lokalisierung**:

1. Identifiziere die Stellen, an denen AT konstitutiv ist (Mediation).
2. Begrenze AT *exakt auf diese Stellen*. Nicht weniger, aber auch nicht
   mehr.
3. Ausserhalb dieser Stellen bleibt der Code rein A, R, T oder 0.

Lokalisierung ist nicht identisch mit Minimierung — aber sie hat
Minimierung als kausale Folge. Wer AT-Code auf wenige fachlich
benannte Schichten begrenzt, hat in Summe weniger AT-Code als wer ihn
diffus durch das System verteilt.

## 5. Kontextrelativitaet von A und T

A und T sind keine Eigenschaften einer Technologie, sondern
Eigenschaften *des konkreten Systems im konkreten Kontext*.

| System | HTTP-Beherrschung | DB-Beherrschung | UI-Toolkit-Beherrschung |
|---|---|---|---|
| Webcrawler | A — inhaerent | T — extern | nicht relevant |
| OLTP-Backoffice | T — extern | A — inhaerent | T — extern |
| Datenbank-Engine selbst | T — extern | A — inhaerent | T — extern |
| UI-Framework-Hersteller | T — extern | T — extern | A — inhaerent |
| Generischer Business-Service | T — extern | T — extern | T — extern |

Daraus folgt: Vor jeder Klassifikation muss klar sein, was die
**Kernfachlichkeit des konkreten Systems** ist. Ohne diesen Schritt
fuehrt die Klassifikation in die Irre.

## 6. Methodische Reihenfolge

Beim Anwenden der Klassifikation:

1. **Kernfachlichkeit benennen.** Was ist die Domaene dieses Systems?
   Was gehoert zwingend zu seiner fachlichen Identitaet, was nicht?
2. **Code-Cluster identifizieren** und die vier Dimensionen pro
   Cluster pruefen.
3. **Bluttyp zuordnen** — A, R, T oder 0 — auf Basis des Profils.
4. **Mischformen erkennen** — wo sind AT-Stellen konstitutiv? Sind
   sie auf Mediation-Schichten lokalisiert, oder diffus verteilt?
5. **Norm zur Haerte der Trennung** zwischen den Bluttypen aus den
   *Zielen des konkreten Systems* ableiten (Substitutierbarkeit?
   Testbarkeit? Wartbarkeit? Wiederverwendung?). Nicht aus einer
   Lehrbuchschablone uebernehmen.
6. **Erst danach Tooling** (Linter, Architektur-Konformanzregeln) als
   Werkzeug, das die so definierte Norm umsetzt — niemals als Quelle
   der Norm.

## 7. Was die Klassifikation nicht leistet

- **Keine deterministische Ableitung.** Die Bluttypen sind ein Werkzeug
  fuer architektonische Abwaegung, kein Algorithmus, der Code automatisch
  klassifiziert. Architekturentscheidungen bleiben menschliche
  Abwaegungsentscheidungen entlang konkurrierender Ziele.
- **Keine 100% Lupenreinheit.** Der Versuch, jeden Code-Schnipsel
  zwingend in einen reinen Bluttyp zu zwingen, eskaliert in
  Over-Engineering: 100 Zeilen Businesslogik werden von 2000 Zeilen
  Wrapper- und Fassaden-Code begleitet, die selbst getestet, gepflegt
  und verstanden werden muessen. Reinheit ist nicht das Ziel —
  Testbarkeit, Substitutierbarkeit und Wiederverwendbarkeit sind es.
- **Keine universelle Liste.** Es gibt keine globale Aussage wie "HTTP
  ist immer T" oder "Datenbank ist immer T". Erst der Kontext der
  Kernfachlichkeit eines Systems entscheidet.
- **Kein Selbstzweck.** Die Klassifikation dient den Zielen aus
  Abschnitt 1. Wo sie diese Ziele nicht foerdert, sondern nur Buerokratie
  erzeugt, ist sie falsch angewendet.

## 8. Beispiel-Galerie

| Code-Anteil | Klassifikation | Begruendung |
|---|---|---|
| Berechnungs-Algorithmus fuer eine Versicherungs-Praemie | A | Kernfachlichkeit; ohne Infrastruktur testbar |
| Mapping `OrderDTO` → `OrderEntity` (rein strukturell) | R | Repraesentations-Ueberfuehrung; keine Mechanik |
| Datenbank-Zugriffsschicht (Repository inkl. Lade-Strategien, Transaktionen) | AT | konstitutive Mediation; R allein reicht nicht |
| UI-Anwendungsrahmen (Window-Manager, Routing, Dialog-Lifecycle) | AT | A-Konzepte (Dialog, Eventbus) + T-Projektion (Qt, React, Terminal) |
| Einzelner fachlicher Dialog innerhalb eines Anwendungsrahmens | A | nutzt nur die A-Konzepte des Rahmens |
| Postgres-Treiber-Modul (rohe SQL-Queries, Connection-Pool) | T | ausserhalb der Kernfachlichkeit, technologie-spezifisch, Infra-Setup-Pflicht |
| HTTP-Client in einer Geschaeftsanwendung, die eine Webseite scrapt | T | Inhaerenz-Test negativ — die Domaene koennte die Information auch aus DB oder Datei beziehen |
| HTTP-Client in einem Webcrawler | A | Inhaerenz-Test positiv — HTTP-Mechanik ist Teil der Kernfachlichkeit |
| String-Utility-Sammlung | 0 | domaenenfrei, projektuebergreifend, niedrige Test-Schwere |
| Logging-Framework mit File- und DB-Appendern | 0 | domaenenfrei trotz technischer Anteile; in jedem Projekt einsetzbar |
| Datums-/Zeitfunktionen (`now_iso`, `parse_iso`) | 0 | domaenenfrei, generisch |
| Modul, das Geschaeftsregeln *und* SQL-Statements direkt mischt | AT-diffus — Antipattern | nicht lokalisiert; gehoert aufgespalten in A-Kern + AT-Mediation |

## 9. Zusammenfassung in einem Satz

A traegt die Fachlogik, T traegt die konkrete Technik, R uebersetzt
zwischen Repraesentationen, 0 ist domaenenfreie Wiederverwendbarkeit;
AT-Mischungen sind an dafuer vorgesehenen Mediation-Schichten legitim,
und ihre Lokalisierung haelt den fachlichen Kern frei und testbar.
