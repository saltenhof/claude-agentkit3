---
title: Offene Entscheidungen fuer den Product Owner
status: draft
doc_kind: workspace-decision-input
date: 2026-08-02
authority_over: []
note: >
  Nach P-PO als offener Loesungsraum formuliert: Kontext, Konsequenzen,
  Empfehlung. Keine Multiple-Choice-Verengung. Wo unten Varianten
  auftauchen, sind sie Beispiele im Raum, keine Auswahlliste.
---

# Offene Entscheidungen

Acht Entscheidungen. Die ersten drei blockieren die Normierung des
Verfahrens; die uebrigen koennen danach fallen, sollten es aber nicht
unbegrenzt.

---

## E1 — Wo der Inkubator geschnitten wird: Thema oder Lauf

**Kontext.** FK-78 schneidet den Inkubator nach **Laeufen**
(`runs/<run_id>/`); der Lauf ist die Einheit von Nachvollziehbarkeit,
Locking und Closure. Die Beschreibung des Zielverfahrens und der
Blueprint schneiden nach **Themen** (`<space>/werkstatt|schnittstelle`).
Beide Schnitte existieren im Repo bereits nebeneinander — dieser
Arbeitsauftrag selbst hat in einem Themenordner geschrieben, den FK-78
nicht kennt.

**Woran es haengt.** Ein Thema ueberlebt viele Laeufe. Ein Lauf traegt
den Zustand. Wer nur Themen fuehrt, verliert die Lauf-Identitaet und
damit Lease, Fencing-Token und Promotion-Closure. Wer nur Laeufe fuehrt,
hat nach zwanzig Laeufen ein Verzeichnis, in dem niemand mehr findet,
was zu welchem Strang gehoert — und greift dann doch zum Themenordner.

**Konsequenzen, die daran haengen.** Der Ort entscheidet, wo
`concept-governance.json` seinen `incubator_root` hinzeigt, ob
bestehende Laeufe umziehen muessen, wie das Werkstatt-Manifest
(`INDEX.md`) gegliedert ist, und ob die Aufbewahrungsfrage
("wann darf Rohstoff weg?") pro Thema oder pro Lauf beantwortet wird.
Der Blueprint beantwortet sie pro Thema und bindet sie an das Ereignis
Promotion — AK3 hat dafuer heute gar keine Antwort.

**Empfehlung.** Thema aussen, Lauf innen:
`concept-incubator/<space>/workspace/runs/<run_id>/` und
`concept-incubator/<space>/interface/`. Das erhaelt die Lauf-Identitaet
vollstaendig, macht den Themenstrang auffindbar und bleibt eine
Layout-Ergaenzung in FK-78 §78.3 statt einer Schemaaenderung, weil
`incubator_root` bereits konfigurierbar ist. Die beiden bestehenden
Laeufe ziehen mit; ihr Inhalt bleibt unberuehrt.

---

## E2 — Wie frei ein Pruefagent sein darf, ohne die AK3-Doktrin zu brechen

**Kontext.** Drei Stellen im Bestand sagen sinngemaess dasselbe: LLMs
sind in AK3 Bewertungsfunktionen, keine frei handelnden Agenten
(`CLAUDE.md`, META-CONCEPT-CONSISTENCY §5, FK-78 §78.14). Das
Zielverfahren verlangt das Gegenteil: Agenten, die ihre Strategie selbst
waehlen. Das ist der einzige echte Doktrinkonflikt des Umbaus (C-1).

**Woran es haengt.** Die Regel hat einen Zweck, den niemand aufgeben
will: kein LLM entscheidet ueber Landen oder Blockieren. Sie hat aber
einen Wortlaut, der zusaetzlich das **Vorgehen** bindet — und genau das
war der Grund fuer die Sproedigkeit, die AG3-179 blockiert hat: ein
starrer Sweep mit fester Partitionierung, festem Prompt und einer
einzigen Auswertung je Partition, der an einem nicht-woertlichen Zitat
komplett endet.

**Konsequenzen.** Wird die Regel unveraendert gelassen, laeuft das neue
Verfahren dauerhaft als geduldete Ausnahme — und geduldete Ausnahmen
erodieren die Regel, die sie duldet. Wird sie zu weit geoeffnet,
verliert AK3 sein Unterscheidungsmerkmal gegenueber "wir fragen halt ein
Modell".

**Empfehlung.** Die Regel entlang der Linie praezisieren, die sie
ohnehin meint: **Ermittlung frei, Verrechnung deterministisch.** Der
Agent waehlt Werkzeuge, Reihenfolge und Tiefe; er liefert typisierte
Belege mit Locator und woertlichem Zitat; ueber Freigabe oder Blockade
entscheidet eine Policy ueber diesen Belegen, nie der Agent. Damit
bleibt "kein Werkzeug entscheidet frei" wahr und wird sogar schaerfer
pruefbar als heute.

---

## E3 — Wogegen "genau das Freigegebene" gemessen wird

**Kontext.** Die Migrationstreue-Pruefung braucht eine Referenz. In
FK-78 ist das heute das **Atom-Register**, das nur ein
`FULL_ATOM`-Lauf erzeugt. Der Wunsch, dass ein Opus-Agent schreibt und
direkt danach ein Codex prueft, existiert unterhalb dieser Schwelle und
hat dort keine Referenz.

**Woran es haengt.** Je genauer die Referenz, desto belastbarer der
Nachweis und desto teurer die Vorbereitung. Die Spanne reicht von
"Digest des freigegebenen Dokuments" (billig, beweist nur, dass
dasselbe Dokument gemeint war) ueber eine Zuordnungstabelle Aussage ->
Zielort (mittel, macht Mengenvergleiche moeglich) bis zum vollen
Atom-Register mit Qualifikatoren und Autoritaetszielen (teuer, macht
Verlustfreiheit beweisbar). Dazwischen liegt beliebig viel Raum.

**Konsequenzen.** Die Wahl bestimmt, was der Verfasser vor der Freigabe
schreiben muss, was die Maschine automatisch pruefen kann und was der
Agent semantisch beurteilen muss. Sie bestimmt ausserdem, ob
"verlustfrei uebernommen" kuenftig eine belegte Aussage oder eine
Behauptung ist.

**Empfehlung.** Ein **Einfuegeplan** je Freigabe: eine Zeile je
materieller Aussage mit `statement` (qualifikatorentreu), Zielpfad,
Zielanker, Aenderungsart und beanspruchtem Scope, beim Uebergang nach
`interface` digest-gepinnt. Das ist die kleinste Referenz, gegen die
beide Richtungen — "nicht weniger" und "nicht mehr" — maschinell
messbar sind, und es ist Arbeit, die der Verfasser beim Einfuegen
ohnehin leistet, nur bisher unaufgeschrieben. Der Vollausbau bleibt
`FULL_ATOM` vorbehalten.

---

## E4 — Ob der ruhende Bestand weiter geprueft wird

**Kontext.** Das neue Verfahren ist **aenderungsgetrieben**: es prueft,
was jemand anfasst. W2 und W3 waren **korpusgetrieben**: sie liefen
nightly ueber den gesamten Bestand und fanden Widersprueche in
Passagen, an denen gerade niemand arbeitete. Diese Faehigkeit geht
ersatzlos verloren, wenn die Nightly-Laeufe eingestellt werden.

**Woran es haengt.** Widersprueche entstehen fast nie im Moment der
Aenderung, sondern **danach** — die eine Seite wird gepflegt, die
andere altert. Genau das war der Anlassfall von
META-CONCEPT-CONSISTENCY: vier Dokumente hatten denselben Mechanismus
nebenbei mitnormiert, und als die Entscheidung sich aenderte, wurde nur
das Heimat-Dokument aktualisiert. Ein rein aenderungsgetriebenes
Verfahren haette diesen Fall nie gefunden.

**Konsequenzen.** Ohne Bestandsdetektor waechst die Drift unbemerkt
weiter, und sie wird erst sichtbar, wenn jemand zufaellig beide Seiten
liest. Mit Bestandsdetektor bleibt eine laufende Kostenstelle bestehen
— und im Fall von W3 eine, die heute nicht zuverlaessig durchlaeuft.

**Empfehlung.** Die Faehigkeit erhalten, den Mechanismus wechseln: der
Bestandsdetektor wird periodisch (nicht nightly) als agentischer
Auftrag ueber **jeweils einen Scope** gefahren, mit demselben
Receipt-Vertrag wie die Vorlagepruefung. Das umgeht die
Partitionierungssproedigkeit, weil ein Agent selbst entscheidet, wie er
ein grosses Set liest, und es macht die Kosten steuerbar, weil die
Reihenfolge waehlbar ist. **Nicht empfohlen:** die Faehigkeit
stillschweigend fallen lassen — das waere der teuerste Teil des Umbaus,
weil niemand ihn bemerken wuerde.

---

## E5 — Wo die importierte Blueprint-Methodik wohnt

**Kontext.** Vier projektunabhaengige Bausteine des Blueprints haben in
AK3 kein Zuhause: die Lueckenklassifikation `gap_class` (C-5), der kalte
Implementierbarkeitstest (C-6), die Provider-Claim-Kante (C-7) und die
Freigabekriterien fuer `active` samt kaltem Gegenleser (C-8).

**Woran es haengt.** Sie koennten in bestehende Autoritaeten eingefuegt
werden (META-CONCEPT-CONSISTENCY fuer die Prinzipien,
META-ASSERTION-AUTHORITY fuer die Statusfragen, FK-78 fuer die
Registerfelder) — dann bleibt der Korpus schmal, aber die Methodik
liegt verstreut. Oder sie bekommen ein eigenes Methodikdokument nach dem
Muster von ATOM-01 — dann ist sie zusammenhaengend lesbar und
exportfaehig, aber AK3 bekommt ein weiteres Meta-Dokument mit eigenem
`authority_over`, und die Abgrenzung zu den beiden bestehenden
Meta-Vertraegen muss sauber gezogen werden.

**Konsequenzen.** AK3 exportiert seine Meta-Governance in Zielprojekte
(FK-78 Blueprint-Export). Was hier entsteht, wandert mit. Ein
zusammenhaengendes Methodikdokument ist fuer den Export deutlich
wertvoller als vier Einschuebe; ein viertes Meta-Dokument ist fuer den
AK3-Alltag ein weiterer Ort, an dem jemand nachsehen muss.

**Empfehlung.** Geteilt, entlang der Frage "Norm oder Verfahren": Die
**Felder** gehen dorthin, wo ihre Register wohnen (`gap_class` in FK-78
§78.9; Freigabekriterien in META-ASSERTION-AUTHORITY, weil dort die
Statussemantik liegt). Die **Pruefverfahren** — kalter
Implementierbarkeitstest, Provider-Claim-Kante, kalter Gegenleser —
bekommen ein eigenes, exportfaehiges Methodikdokument, weil sie
Arbeitsanweisungen fuer Agenten sind und nicht Felder in einem Register.
Damit bleibt das Prinzip erhalten, dass die Aussage dort wohnt, wo sie
geprueft wird.

---

## E6 — Wie weit die Unabhaengigkeit des Pruefers reicht

**Kontext.** FK-78 §78.10 verlangt heute: anderer `principal_id` **und**
andere `session_ref` als der Verfasser. Nicht verlangt: anderes Modell,
anderer Anbieter, andere Harness. Der Blueprint verlangt einen "kalten
Gegenleser ohne Vorkenntnis und ohne Beteiligung an der Entstehung" —
das ist eine Aussage ueber Wissen, nicht ueber Identitaet.

**Woran es haengt.** Zwei Sessions desselben Modells teilen keine
Konversation, aber dieselben Trainingsprioren und dieselben blinden
Flecken. Ein Verfasser und ein Pruefer aus demselben Haus finden
denselben Fehler nicht. Umgekehrt kostet Anbieterwechsel Zugang,
Konfiguration und Latenz — und im Extremfall Datenfreigabe, weil
`sensitive` die Maschine nicht ohne PO-Freigabe je Backend verlaesst
(FK-78 §78.13).

**Konsequenzen.** Die Antwort bestimmt, wie teuer eine Freigabe ist und
wie belastbar sie ist. Sie bestimmt ausserdem, ob die
Kernauftrags-Aussage von DK-16 — "KI-Agenten unterschiedlicher
Hersteller" — im leichten Pfad ueberhaupt wirksam wird oder nur im
Council.

**Empfehlung.** Die harte Regel bleibt Principal + Session (sie ist
maschinell pruefbar). Ergaenzt wird eine **abgestufte Erwartung**: bei
Aenderungen, die eine Weiche im Systemverhalten stellen oder mehrere
Autoritaeten beruehren, ist ein Pruefer aus einem anderen Modellhaus
Pflicht; darunter ist er empfohlen. Das ist dieselbe
Proportionalitaetslogik wie bei den drei Profilen und braucht keine
neue Achse.

---

## E7 — Ob die Komponenten- und Schnittstellenschicht eigene Konzeptarbeit wird

**Kontext.** Der PO hat eine Schicht zwischen Prosa und Formal-Layer
benannt, die Komponenten- und Schnittstellenbeschreibung traegt, von den
Bounded Contexts abweichen darf und die Projektion darauf ist, wie
tatsaechlich in Repositories und Software-Artefakte geschnitten wird.
Der Befund dazu steht in C-4 und ist der umfangreichste dieses
Berichts. Kurzfassung: Der Blueprint hat eine **kontextgebundene**
Component-Ebene mit Portobjekten, Praezisionsboden `S0`–`S6` und
Konsumart an der Kante — und er klammert die Codeprojektion
**ausdruecklich aus**. AK3 hat umgekehrt die Codeprojektion (FK-07,
Architektur-Checker gegen den Importgraphen) und **kein
Komponentenobjekt**: `module-registry.yaml` ist eine flache Namensliste,
Ports existieren nur in Prosa.

**Woran es haengt.** Die Frage beruehrt FK-07, FK-17/FK-18, den
Formal-Layer-Vertrag und die Registry-Landschaft gleichzeitig. Sie
traegt mindestens zwei echte Weichen: ob eine Komponentenspezifikation
eine zusaetzliche Objektart der formalen Schicht wird (im Blueprint
ausdruecklich offen, §4.6), und ob die Schicht kontextgebunden bleibt
oder — wie vom PO beschrieben — orthogonal liegen darf.

**Konsequenzen.** Solange kein Komponentenobjekt existiert, kann AK3
nicht maschinell beantworten, welche Komponente einen Fakt besitzt,
welchen Port sie anbietet und mit welcher Signatur. Der
Architektur-Checker faengt Verstoesse gegen den in Prosa gezogenen
Schnitt, aber nicht die Klasse "Vertrag existiert nur als Name" — genau
die Klasse, die im Blueprint den Bruch verursacht hat. Andererseits ist
diese Flaeche gross genug, um die Konzeptpruefungs-Umstellung zu
verschlucken, wenn sie mit hineingezogen wird.

**Empfehlung.** Eigene Konzeptarbeit, eigener Lauf, **nach** der
Normierung des Pruefverfahrens — und dann als Council-Fall mit
Vollstaendigkeitsanspruch. Zwei Gruende fuer diese Reihenfolge: erstens
ist die Komponentenschicht genau die Art von Vorhaben, fuer die das
neue Verfahren gebaut wird (mehrere Autoritaeten, echte Weichen,
Migration von Bestand) — sie ist damit sein erster echter Anwendungsfall
statt seine Vorbedingung. Zweitens ist die Objektartenfrage im Blueprint
selbst offen; sie jetzt zu entscheiden hiesse, sie ohne den Stand zu
entscheiden, der dort gerade erarbeitet wird.

---

## E8 — Ab wann das neue Verfahren Pflicht ist

**Kontext.** Der PO hat betont, dass die vereinfachte Variante **sofort
anwendbar** ist und das formale, mit Guardrails und Hooks abgesicherte
Verfahren Ausbaustufe ist, nicht Voraussetzung. Gleichzeitig ist die
alte Pflicht ab sofort ausgesetzt — und zwischen "alte Pflicht weg" und
"neue Pflicht normiert" liegt ein Fenster ohne verbindliche semantische
Pruefung.

**Woran es haengt.** Ein Fenster ohne Pflicht ist genau die Situation,
in der Gewohnheiten entstehen. Wird es zu lang, ist die neue Pflicht
spaeter eine Verschaerfung gegen den eingespielten Zustand. Wird es zu
kurz, wird eine unfertige Norm eingefuehrt — derselbe Fehler wie beim
letzten Mal, nur mit anderem Werkzeug.

**Konsequenzen.** Die Antwort bestimmt, was in `AGENTS.md` als
Interimspflicht steht (heute vorgeschlagen: unabhaengige Vorlage mit
drei Pruefachsen, ohne Werkzeugzwang), und ob laufende Arbeit
nachtraeglich unter die neue Pflicht faellt.

**Empfehlung.** Die Interimspflicht sofort setzen — sie kostet nichts,
weil sie nur die bereits geltende Codex-Review-Grundregel auf
Konzeptaenderungen anwendet — und die volle Normierung an ein
**Ereignis** binden statt an ein Datum: sie tritt in Kraft, sobald der
erste Lauf des neuen Verfahrens vollstaendig durchgelaufen ist,
einschliesslich Migrationstreue-Pruefung. Damit ist die Norm an einem
echten Lauf gemessen, bevor sie andere bindet. Laufende Arbeit faellt
nicht rueckwirkend darunter.

---

## Was ich bewusst nicht entschieden habe

- **Die Frontmatter-Gestalt** eines kuenftigen Methodikdokuments (E5) —
  sie haengt am Zielort und der ist offen.
- **Die konkreten Spaltennamen** des Einfuegeplans ueber den
  Mindestbestand hinaus (E3) — das ist Feindesign und gehoert in den
  ersten echten Lauf, nicht in einen Entwurf ohne Erprobung.
- **Ob der Themenraum bestehende Laeufe umzieht oder nur neue aufnimmt**
  (E1) — das ist eine Migrationsentscheidung mit Kosten, die ich nicht
  beziffern kann.
- **Alles an der Komponentenschicht ausser ihrer Benennung** (E7) —
  ausdruecklich nach Auftrag.
- **Ob `authority-prose-baseline.yaml` weitergefuehrt, eingefroren oder
  ueberfuehrt wird** (C-11) — sie haengt an E4 und faellt mit ihr.

---

## Ratifiziert am 2026-08-02 (PO)

**E2 — Doktrinkonflikt "Agent waehlt Strategie selbst" vs. "kein Werkzeug
entscheidet frei": aufgeloest.** Der PO traegt die Praezisierung und hat sie in
zwei Schritten selbst geschaerft. Der verbindliche Wortlaut steht in `AGENTS.md`
und ist von dort zu uebernehmen, nicht aus diesem Werkstattdokument zu zitieren.

Der Kern in drei Saetzen:

1. Frei ist die **Strategie und das Handeln**; nicht frei sind **Ziel und
   Leitplanken**.
2. Der Agent hat **ausdruecklich das Mandat, neue normative Inhalte zu
   schaffen** — gebunden an drei gemeinsam geltende Bedingungen:
   Ausdetaillierung eines groeber definierten Konzeptinhalts mit benennbarer
   Ankerstelle, kein Widerspruch zum Bestand, keine neue Konzeptdomaene.
3. Fehlt der Anker, waere die Domaene neu, oder entstuende ein Widerspruch,
   **holt der Agent den PO** und laesst sich die groben Pfosten auf
   Meta-Konzeptebene setzen. Erst danach schreibt er weiter.

Verboten ist damit **Erfindung, nicht Ableitung**. Die Regel aus FK-78 §78.14
bleibt unangetastet; praezisiert ist, dass sie die *Entscheidung* meint und
nicht die *Ermittlung*.

Offen bleibt die normative Nachfuehrung in FK-78 §78.14 und
`konzept-konsistenz-governance.md` — sie laeuft ueber das Verfahren, das dieser
Entwurf beschreibt, samt Decision Record.
