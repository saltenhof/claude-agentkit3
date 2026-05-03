---
concept_id: FK-64
title: Control-Plane Design System
module: control-plane-design-system
domain: kpi-and-dashboard
status: active
doc_kind: core
parent_concept_id:
authority_over:
  - scope: control-plane-design-system
  - scope: visual-language
  - scope: ui-tokens
  - scope: typography
  - scope: component-guidelines
  - scope: story-cockpit-layout
defers_to:
  - target: FK-63
    scope: dashboard-views
    reason: FK-63 definiert die fachlichen Dashboard- und Story-Cockpit-Sichten; FK-64 normiert deren visuelle Sprache.
  - target: FK-70
    scope: planning-views
    reason: FK-70 definiert Dependency-Graph, Abhaengigkeiten, Execution Waves und Story-Detail als Pflichtsichten.
supersedes: []
superseded_by:
tags: [design-system, ui, control-plane, dashboard, typography, tokens, dark-theme]
formal_scope: prose-only
glossary:
  exported_terms:
    - id: control-plane-design-system
      definition: >
        Normatives visuelles Regelwerk fuer die AgentKit-Control-Plane.
        Es definiert Theme, Token-Skalen, Typografie, Komponentenregeln,
        Statusdarstellung und Layoutkonventionen fuer Story Cockpit,
        Dashboard, Planungsansichten und Story-Detail.
    - id: story-cockpit
      definition: >
        Interaktive Web-Oberflaeche der AgentKit-Control-Plane, die
        Story-Listen, Sheet-Ansicht, Kanban, Dependency-Graph,
        Story-Detail, Evidenz und Telemetrie in einer tenant-scoped
        Anwendung zusammenfuehrt.
    - id: semantic-accent
      definition: >
        Farbeinsatz mit fachlicher Bedeutung, beispielsweise fuer
        Status, Severity, Qualitaet oder Blocker. Ein semantic-accent
        ist kein dekorativer Farbwechsel.
  internal_terms:
    - id: prototype-token
      reason: >
        Implementierungsnaher CSS-Custom-Property-Name im UI-Prototyp.
        Er ist abgeleitet aus diesem Dokument, aber nicht selbst
        fachlicher Begriff.
---

# 64 — Control-Plane Design System

## 64.1 Zweck

Dieses Dokument definiert das normative Design System fuer die
AgentKit-Control-Plane. Es gilt fuer das Story Cockpit, die KPI- und
Dashboard-Sichten, Planungsansichten, Story-Details, Sheet-Ansichten,
Kanban, Dependency-Graph und alle fachlichen Flyouts oder Inspector-
Panels innerhalb dieser Web-Oberflaeche.

FK-64 ist kein Prototyp-Kommentar. Es ist die autoritative Quelle fuer
visuelle Sprache, Token-Skalen, Komponentenregeln und UI-Konsistenz.
Eine Implementierung darf davon nur abweichen, wenn das abweichende
Verhalten als neues Konzept oder als explizite Aenderung an FK-64
eingepflegt wird.

## 64.2 Einordnung im Bounded Context

Das Dokument gehoert zum Bounded Context `kpi-and-dashboard`, weil die
Control-Plane-Oberflaeche dort ihre Dashboard- und Auswertungsoberflaeche
hat und FK-63 bereits die fachliche Evolution zum Story Cockpit
beschreibt. FK-70 liefert planungsbezogene Pflichtsichten, besitzt aber
nicht die visuelle Sprache. FK-64 normiert daher die Darstellung
uebergreifend fuer alle Control-Plane-Sichten, ohne die fachliche
Semantik der anderen BCs zu uebernehmen.

**Abgrenzung:**

- FK-63 definiert, welche Dashboard- und Cockpit-Sichten fachlich
  vorhanden sein muessen.
- FK-70 definiert Planungsobjekte und Pflichtsichten wie Dependency-
  Graph, Abhaengigkeiten und Execution Waves.
- FK-64 definiert, wie diese Sichten visuell, typografisch und
  komponentenseitig konsistent dargestellt werden.

**Komponenten-Ownership:**

Die Sub-Komponente `kpi-and-dashboard.DesignSystem` (siehe
`entities.md`) haelt ausschliesslich Token-Definitionen und
Komponentenrichtlinien (Token-Skalen, Typografie, Spacing, Farben,
Komponentenregeln). Sie ist UI-Layer ohne eigene Laufzeit-Logik.
Die Token-Konsumenten — das Frontend des `control_plane`-BC sowie
alle Control-Plane-Sichten — importieren die Tokens und wenden sie
an. `DesignSystem` gibt keine Tokens dynamisch aus und betreibt
keinen eigenen HTTP-Endpunkt; die Boundary-Control liegt bei
`control_plane`.

## 64.3 Design-Prinzipien

1. **Arbeitsoberflaeche statt Marketing-UI.** Die Control-Plane ist ein
   operatives Werkzeug. Dichte, Scanbarkeit, klare Hierarchie und
   wiederholbare Bedienung haben Vorrang vor dekorativer Wirkung.
2. **Dunkles Lightroom-nahes Theme.** Die Oberflaeche nutzt Schwarz-
   und Grautoene mit klar unterscheidbaren Flaechenebenen. Reines
   Schwarz-in-Schwarz ist verboten; Panels muessen auch ohne Hover
   unterscheidbar sein.
3. **Gezielte Akzente.** Tuerkis und Gelb-Orange sind bewusst
   eingesetzte Akzentfarben. Weitere Farben duerfen nur semantisch
   begruendet erscheinen, etwa fuer Status, Severity oder Gruppierung.
4. **Gleiche Ebene, gleiche Darstellung.** Semantisch gleiche Texte,
   Buttons, Badges, Tabs und Tabellenzellen verwenden dieselben Tokens.
5. **Keine lokalen Sondergroessen.** Schriftgroessen, Buttonhoehen,
   Spacing, Radii und Schatten werden ueber Tokens gesetzt. Lokale
   Literale sind nur fuer dynamische, datengetriebene Werte erlaubt.
6. **Inspector bleibt Arbeitskontext.** Story-Details sind nicht modal.
   Der Nutzer muss mehrere Stories per Klick oder Tastatur durchgehen
   koennen, waehrend der Inspector aktualisiert bleibt.

## 64.4 Theme und Flaechenhierarchie

Die Control-Plane verwendet ein dunkles Theme mit drei Ebenen:

| Ebene | Zweck | Charakter |
|-------|-------|-----------|
| Canvas | Hauptarbeitsflaeche, Graph, Sheet-Hintergrund | sehr dunkel, ruhig, wenig Kontrast |
| Surface | Karten, Tabellen, Panels | sichtbar heller als Canvas |
| Raised Surface | Toolbars, Header, aktive Bereiche | nochmals abgesetzt, mit subtilem Verlauf |

Flaechen duerfen leichte vertikale Gradients nutzen, wenn diese die
Ebenenhierarchie verbessern. Gradients duerfen nicht ornamental wirken
und duerfen keine Lesbarkeit verschlechtern.

**Regeln:**

- Der App-Hintergrund ist dunkler als Panels.
- Panels haben sichtbare Abhebung durch Surface-Farbe, Border oder
  Schatten.
- Toolbars und Header duerfen einen leichten Verlauf tragen.
- Doppelte Borderlinien sind zu vermeiden. Wenn Wrapper und Kind-Element
  an derselben Kante Linien zeichnen wuerden, muss die Wrapper-Linie als
  Hintergrund-Layer oder Spacer geloest werden.

## 64.5 Farbsystem

### 64.5.1 Neutrale Farben

| Token-Familie | Einsatz |
|---------------|---------|
| `bg-*` | Canvas, App-Hintergrund, tiefe Flaechen |
| `surface-*` | Panels, Karten, Tabellen, Toolbars |
| `border-*` | Hairlines, Panelgrenzen, Gridlinien |
| `text-*` | Primaertext, Sekundaertext, Muted Text, Faint Text |

Neutrale Farben bilden mindestens fuenf unterscheidbare Stufen:

1. App-Hintergrund
2. Canvas
3. Surface
4. Raised Surface
5. Hover/Selected Surface

### 64.5.2 Akzentfarben

| Farbe | Einsatz |
|-------|---------|
| Tuerkis dunkel | Primaere Buttons, aktive CTA-Pfade |
| Tuerkis hell | Textlinks, IDs, aktive Labels auf dunklem Grund |
| Gelb-Orange | Warnungen, warme Akzentleisten, Attention States |

Tuerkis hat zwei Varianten. Die hellere Variante ist fuer Text und
Labels auf dunklem Hintergrund reserviert. Die dunklere, kraeftigere
Variante ist fuer Flaechen wie primaere Buttons vorgesehen und traegt
weissen Text.

### 64.5.3 Semantische Farben

| Semantik | Einsatz |
|----------|---------|
| Success | Done, PASS, erfolgreiche Gates |
| Warning | WARNING, Review-Hinweise, weiche Blocker |
| Danger | ERROR, Blocked, harte Blocker, fehlgeschlagene Gates |
| Info | Approved, neutrale Systeminformation |
| Done | erfolgreich abgeschlossene Story-Zustaende |
| Cancelled | terminal verworfene Story-Zustaende |

Semantische Farben erscheinen punktuell. Die Anwendung darf nicht
flaechig bunt werden. Statusfarben muessen als Bedeutung erkennbar
bleiben und duerfen nicht fuer dekorative Varianz zweckentfremdet
werden.

## 64.6 Typografie

### 64.6.1 Schriftfamilien

| Rolle | Font |
|-------|------|
| Body/UI | Open Sans mit System-Fallback |
| Display | League Spartan mit Open-Sans-Fallback |

Open Sans ist die Standardschrift fuer Fliesstext, Tabellen,
Navigation, Buttons und Controls. League Spartan ist nur fuer
uebergeordnete Titel wie App-Titel, Story-Inspector-ID oder sehr
praegnante Paneltitel vorgesehen.

### 64.6.2 Groessenskala

Alle Schriftgroessen werden relativ definiert. `px` fuer
Schriftgroessen ist verboten.

| Token | Wert | Einsatz |
|-------|------|---------|
| `text-xs` | `0.75em` | Badges, Meta, Tabellen-Gruppen, Statusbar |
| `text-sm` | `0.875em` | Buttons, Tabellenzellen, Kartenbody |
| `text-md` | `0.9375em` | Storytitel, kompakte Paneltitel |
| `text-lg` | `1.125em` | Detail- und Analyse-Paneltitel |
| `text-2xl` | `1.625em` | Seiten- und Inspector-Titel, KPI-Werte |
| `text-3xl` | `2em` | grosse Analytics-Zahl, selten |

### 64.6.3 Semantische Textrollen

| Rolle | Groesse | Gewicht | Einsatz |
|-------|---------|---------|---------|
| Label | `text-xs` | semibold | Eyebrows, Meta, Statusbar, Group Header |
| Body | `text-sm` | regular | Tabellenzellen, Listen, Beschreibungen |
| UI | `text-sm` | medium | Buttons, Selects, Segment Controls |
| Title | `text-md` | semibold | Story Cards, Kanban-Spalten, kompakte Panels |
| Panel Title | `text-lg` | semibold | Inspector-Abschnitte, Analytics Cards |
| Page Title | `text-2xl` | semibold | Haupttitel, Inspector-ID |
| KPI | `text-2xl` oder `text-3xl` | black | Zahlen mit Auswertungscharakter |

**Einheitlichkeitsgebot:** Eine semantische Rolle darf innerhalb der
Control-Plane nicht je View unterschiedlich gross sein. Wenn ein Titel
in Kanban und Sheet dieselbe Informationshierarchie besitzt, nutzt er
denselben Typo-Token.

## 64.7 Spacing, Dimensionen und Border

### 64.7.1 Spacing-Skala

Abstaende, Padding und Gaps nutzen eine 4pt-orientierte `rem`-Skala:

| Token | Wert |
|-------|------|
| `space-1` | `0.25rem` |
| `space-2` | `0.5rem` |
| `space-3` | `0.75rem` |
| `space-4` | `1rem` |
| `space-5` | `1.25rem` |
| `space-6` | `1.5rem` |
| `space-8` | `2rem` |

### 64.7.2 Border und Hairlines

Standard-Borders sind Hairlines. In CSS duerfen sie als `0.0625rem`
oder als zentraler Border-Token ausgedrueckt werden. Staerkere Linien
duerfen nur fuer Akzentleisten, Resize-Handles oder Statusindikatoren
verwendet werden.

Tab-Leisten, Header und Gridlinien muessen so gebaut sein, dass keine
doppelten Linien an Kontaktkanten entstehen. Wrapper-Linien duerfen
ueber Hintergrund-Layer simuliert werden, wenn Kind-Elemente eigene
Borders zeichnen.

### 64.7.3 Radii

| Token | Einsatz |
|-------|---------|
| small | kompakte Chips, Tabellenbuttons |
| medium | Standardkarten, Buttons, Inputs |
| large | groessere Panels und Flyouts |
| pill | Badges, Statuspills |

Cards bleiben kantig genug fuer ein Arbeitswerkzeug. Uebermaessig
runde Marketing-Optik ist zu vermeiden.

## 64.8 Buttons und Controls

### 64.8.1 Button-Groessen

| Variante | Einsatz |
|----------|---------|
| Standard | Header-Aktionen, Dialogaktionen, Inspector-Close |
| Compact | dichte Sheet-Toolbars, Tabellenaktionen |
| Icon | Navigation, reine Symbolaktionen |

Primaere und sekundere Buttons in derselben Aktionsleiste muessen
dieselbe Hoehe haben. Ein Close-Button in einem Inspector darf nicht
deutlich kleiner wirken als der primaere Add-Story-Button, wenn beide
als vollwertige Aktionsbuttons dargestellt werden.

### 64.8.2 Varianten

| Variante | Darstellung | Einsatz |
|----------|-------------|---------|
| Primary | dunkles Tuerkis, weisser Text | wichtigste Aktion einer View |
| Secondary | graue Surface, heller Text | normale Nebenaktion |
| Compact | graue Surface, reduzierte Hoehe | dichte Toolbar |
| Ghost | transparent, sichtbarer Hover | subtile Inline-Aktion |
| Danger | rote Semantik | destruktive Aktion |

Je View darf es in der Regel nur eine sichtbare Primary Action geben.

## 64.9 Tabs und Aktenreiter

Story-Inspector-Tabs verwenden eine abgeschraegte Aktenreiter-Optik.
Beide Seiten eines Tabs muessen visuell schraeg wirken; einseitig
rechteckige Tabs sind nicht zulässig.

**Regeln:**

- Aktiver Tab verwendet hellen Tuerkis-Text.
- Nur die Unterkante des aktiven Tabs darf tuerkis hervorgehoben sein.
- Ober-, Links- und Rechtskante des aktiven Tabs bleiben grau wie bei
  inaktiven Tabs.
- Benachbarte Tabs duerfen an der Kontaktkante nur eine Haarlinie
  zeigen.
- Der Tab-Wrapper darf keine echte Borderlinie erzeugen, die mit
  Tab-Borders doppelt sichtbar wird.

## 64.10 Sheet-Ansicht

Die Sheet-Ansicht ist eine Web-Excel-Sicht fuer Stories. Sie muss fuer
Massenbearbeitung, Vergleich und Scanbarkeit optimiert sein.

Pflichtfunktionen der Darstellungslogik:

- sortierbare Spaltenkoepfe
- sichtbare Gruppierung, mindestens nach Epic
- kopierbare Epic-Gruppen oder Story-ID-Gruppen
- Inline-Editing fuer fachlich editierbare Zellen
- frozen columns fuer Story-ID und Titel
- selektierbare Zeilen
- Status- und Qualitaetsdarstellung ueber Badges
- Statusbar mit sichtbaren Kontextzahlen

Tabellenheader nutzen Label-Typografie. Tabellenzellen nutzen Body-
Typografie. Fortschritts- oder Readiness-Balken fuer Stories sind
verboten, solange sie nicht aus einer belastbaren fachlichen
Zustandsquelle berechnet werden koennen.

## 64.11 Kanban

Kanban ist fuer Statusueberblick und Arbeitsfluss gedacht, nicht fuer
Detailanalyse. Es verwendet genau die fachlichen Story-Statusspalten
`Backlog`, `Approved`, `In Progress`, `Done` und `Cancelled`.
`Cancelled` ist terminal, zaehlt aber nicht als erledigt. Karten muessen
kompakt bleiben und duerfen nur die wichtigsten Informationen zeigen:

- Story-ID
- Titel
- Modul oder Scope
- Wave oder Planungsbezug
- Typ und Groesse als Badges

Kanban-Spalten nutzen einheitliche Header-Typografie. Karten nutzen
dieselbe Storytitel-Typografie wie Graph Nodes, sofern beide dieselbe
Informationshierarchie tragen.

## 64.12 Dependency-Graph

Der Dependency-Graph ist eine Pflichtsicht der Planungsdomaene. Er muss
interaktiv sein und eine XY-Graph/Flow-Bibliothek verwenden.

Graph Nodes repraesentieren Stories. Edges repraesentieren
Abhaengigkeiten oder planungsrelevante Beziehungen. Visuell gilt:

- Story Nodes sind kompakte Arbeitskarten, keine Illustrationen.
- Story-ID und Status sind oben scanbar.
- Titel ist die primaere Node-Information.
- Blocker muessen farblich semantisch erkennbar sein.
- Ausgewaehlte Nodes erhalten einen klaren, aber nicht grellen Fokus.

Der Graph-Hintergrund bleibt dunkel und ruhig. Grid- oder Background-
Pattern duerfen Orientierung geben, aber keine visuelle Konkurrenz zu
Nodes und Edges erzeugen.

## 64.13 Story Inspector

Der Story Inspector ist ein nicht-modales Detailpanel. Er liegt ueber
der Arbeitsflaeche, blockiert sie aber nicht durch Blur oder Overlay.

Pflichtverhalten:

- Klick auf eine Story oeffnet oder aktualisiert den Inspector.
- Klick auf eine andere Story aktualisiert den Inspector ohne vorheriges
  Schliessen.
- Arrow Up und Arrow Down duerfen die Story-Auswahl fortschalten.
- Klick ausserhalb von Story und Inspector schliesst den Inspector.
- Der Inspector ist in der Breite resizebar.
- Die zuletzt gewaehlte Breite wird clientseitig persistiert.

Der Inspector hat drei fachliche Tabs:

| Tab | Inhalt |
|-----|--------|
| Spezifikation | Story-Inhalt, Akzeptanzkriterien, Abhaengigkeiten, Quellen, Guardrails, Definition of Done |
| Ergebnis | QA-Zyklen, Review-Runden, Evidence Bundle, Manifest, Verdicts, Logs |
| KPIs | Laufzeit, Tokens, LLM-Calls, Agent-Starts, Review-Metriken, Pool-Telemetrie |

Zwischen Ergebnis und KPIs darf es inhaltliche Ueberschneidung geben.
Der Ergebnis-Tab ist evidenz- und verdict-orientiert; der KPI-Tab ist
messwert- und telemetry-orientiert.

## 64.14 Status, Badges und Severity

Statusdarstellung muss semantisch stabil sein. Farben duerfen nicht je
View neu interpretiert werden.

| Story-Status | Darstellung | Bedeutung |
|--------------|-------------|-----------|
| Backlog | Neutral | angelegt, aber nicht zur Umsetzung freigegeben |
| Approved | Info | fachlich freigegeben; kann dennoch durch Abhaengigkeiten blockiert sein |
| In Progress | Tuerkis-Akzent oder aktiver Indikator | aktive Bearbeitung laeuft |
| Done | Done/Success | terminal erfolgreich abgeschlossen |
| Cancelled | Neutral gedimmt | terminal verworfen oder abgebrochen; zaehlt nicht als Done |

Severity-Badges fuer `PASS`, `WARNING` und `ERROR` sind davon getrennt.
Sie beschreiben Gates, Reviews oder Evidenzbefunde, aber keinen
Story-Status. `Blocked` ist ebenfalls kein eigener Story-Status. Eine
Story kann fachlich blockiert sein, wenn sie im Status `Backlog` noch
nicht freigegeben wurde oder wenn sie im Status `Approved` wegen
Abhaengigkeiten oder Blocker-Kontext aktuell nicht umgesetzt werden
kann.

Badges sind kompakt, pillenfoermig und verwenden Label-Typografie.
Status darf zusaetzlich durch Icons oder Text geklaert werden, aber
nicht allein durch Farbe.

## 64.15 Analytics und KPIs

KPI-Zahlen duerfen groesser sein als normale UI-Texte. Diese Ausnahme
ist auf tatsaechliche Kennzahlen begrenzt. Grosse Zahlen ohne KPI-
Bedeutung sind verboten.

Charts muessen die gleiche semantische Farbskala verwenden wie der
Rest der Anwendung. Warnfarben sind Warnungen vorbehalten. Trendlinien,
Balken und Sparklines duerfen Tuerkis als neutrale Leistungsfarbe
verwenden, solange keine Statussemantik verletzt wird.

## 64.16 Accessibility und Bedienbarkeit

- Textkontrast muss fuer Normaltext mindestens WCAG AA erreichen.
- Fokuszustaende muessen sichtbar sein.
- Interaktive Elemente brauchen eine stabile Zielgroesse.
- Icon-only Buttons brauchen einen zugänglichen Namen.
- Farbe allein darf keinen fachlichen Zustand transportieren.
- Tabellen, Tabs und Inspector muessen per Tastatur nutzbar bleiben.
- Text darf auf kleinen Viewports nicht in Buttons oder Karten
  ueberlaufen.

## 64.17 CSS-Architektur

Die Implementierung bildet dieses Konzept ueber CSS Custom Properties
und Komponentenklassen ab.

**Regeln:**

- Globale Designwerte leben in Design-System-Tokens.
- View-CSS referenziert Tokens und definiert keine neuen
  Schriftgroessen-Skalen.
- `font-size`-Literale ausserhalb der Token-Definition sind verboten.
- Buttonhoehen und Button-Paddings werden ueber Control-Tokens gesetzt.
- Farben werden ueber Token-Familien gesetzt; Ad-hoc-Hexwerte sind nur
  bei Token-Definitionen erlaubt.
- Dynamische Inline-Styles sind nur fuer datengetriebene Werte erlaubt,
  beispielsweise Diagrammhoehen, Tabellenbreiten oder persistierte
  Inspector-Breite.

## 64.18 Konformitaetsregel

Eine UI-Aenderung ist konform zu FK-64, wenn:

1. sie die hier definierten semantischen Textrollen verwendet,
2. Buttongroessen und Control-Groessen aus den Control-Tokens bezieht,
3. Statusfarben nicht umdeutet,
4. keine neuen lokalen Schriftgroessen einfuehrt,
5. Sheet, Kanban, Graph und Inspector die genannten Pflichtrollen
   erhalten,
6. Interaktion und Tastaturbedienung des Story Inspectors nicht
   verschlechtert,
7. visuelle Akzente fachlich oder interaktionsbezogen begruendet sind.

Verstoesse gegen diese Regeln sind Konzept-Drift. Bei bewusstem Drift
muss FK-64 zuerst angepasst werden; die Implementierung folgt dem
Konzept, nicht umgekehrt.
