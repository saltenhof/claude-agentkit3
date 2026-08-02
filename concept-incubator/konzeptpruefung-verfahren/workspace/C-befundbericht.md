---
title: Befundbericht — Abgleich Blueprint (Intima) gegen AK3
status: draft
doc_kind: workspace-finding-report
date: 2026-08-02
authority_over: []
quelle_blueprint: >
  Gesichert gelesen aus
  scratchpad/intima-blueprint/ (Kopie vom 2026-08-02 des zuvor unter
  P:\_private-img2img\concept\_meta liegenden Bestands). Das P-Laufwerk
  wurde waehrend der Arbeit migriert; ab der Meldung wurde ausschliesslich
  aus der Kopie gelesen.
---

# Befundbericht — Blueprint gegen AK3

Gelesen: `atomare-konzeptpruefung-und-migrationsvalidierung.md` (ATOM-01),
`arbeitsweise-konzeption.md`, `konzept-konsistenz-governance.md`,
`ablage-und-zielorte.md` (Auszuege §1a, §3, §3c),
`konzeptwelt-schichtung-und-eigentum.md` (Vorbemerkung, §1–§5, §7.3, §8).
Gegenstand auf AK3-Seite: DK-16, FK-78, FK-07,
`concept/_meta/konzept-konsistenz-governance.md`,
`concept/_meta/assertion-authority.md`, `AGENTS.md`, `CLAUDE.md`,
`concept/technical-design/_meta/*.yaml`, die gebundelte Concept-Toolchain
und `stories/AG3-179-.../report.md`.

Der Blueprint ist als Goldstandard behandelt: uebernommen wird der
projektunabhaengige Verfahrensanteil, Domaenenspezifisches bleibt
draussen. Wo AK3 etwas anders loest, steht die Begruendung dabei (C-12).

---

## C-1 — Der einzige echte Doktrinkonflikt: freier Agent gegen Bewertungsfunktion

**Befund.** Der PO-Auftrag verlangt Agenten, "denen von aussen nur
Leitplanken, Ziele und Nachweispflichten vorgegeben werden und die ihre
Strategie selbst waehlen". Der AK3-Bestand sagt an drei Stellen etwas
anderes:

- `CLAUDE.md`: AK3 "setzt nur dort LLMs ein, wo kreative oder bewertende
  Arbeit wirklich noetig ist"; QA-Layer 2 sind "Bewertungsfunktionen,
  nicht frei handelnde Agents".
- `META-CONCEPT-CONSISTENCY` §5: "Alle Werkzeuge folgen dem AK3-eigenen
  Muster: LLM nur als Bewertungsfunktion, Entscheidung deterministisch.
  Kein Werkzeug entscheidet frei."
- FK-78 §78.14: Semantik-Gates sind "LLM-Bewertungen mit
  deterministischer Verrechnung — niemals als deterministisch
  etikettiert".

Ein Agent, der seine Strategie selbst waehlt, **ist** keine
Bewertungsfunktion. Das laesst sich nicht wegformulieren.

**Warum es trotzdem aufloesbar ist.** Die AK3-Regel adressiert die
**Entscheidung**, nicht die **Untersuchung**. Was sie verhindern will,
ist ein LLM, das ueber Landen oder Blockieren befindet. Ein Agent, der
frei ermittelt und typisierte Belege abliefert, ueber die anschliessend
eine Policy entscheidet, verletzt den Zweck der Regel nicht — er
verletzt nur ihren heutigen Wortlaut.

**Vorschlag zur Praezisierung** (nicht: zur Aufweichung): Die Regel
trennt kuenftig zwei Dinge, die sie heute in einem Satz vermengt:
*Ermittlung ist frei, Verrechnung ist deterministisch.* Damit bleibt der
harte Kern erhalten — kein LLM entscheidet ueber Blockade — und der
Umbau ist konform statt geduldet.

**Warum das nicht nebenbei geht.** Diese Praezisierung ruehrt an einen
Kernsatz von `CLAUDE.md` und an eine `authority_over`-Aussage von
META-CONCEPT-CONSISTENCY. Sie gehoert in ein Decision Record und in
`D-offene-entscheidungen.md` (Entscheidung 2), nicht in einen
Uebergangsvermerk.

---

## C-2 — Die Migrationstreue-Pruefung fehlt in AK3 nicht

**Befund.** Der Auftrag sagt, sie fehle "vollstaendig". Das ist
widerlegbar, und die Korrektur veraendert den Zuschnitt der Arbeit
erheblich:

| Ebene | Fundstelle |
|---|---|
| fachlicher Anspruch | DK-16 §6, vier Ansprueche: nichts verloren, nichts verfaelscht, nichts eingeschmuggelt, Bestand nicht unbemerkt bewegt |
| technische Norm | FK-78 §78.10 (Projection-Receipts, Diff-Hunk-Reverse-Trace), §78.11 (Promotion-Closure Regeln 1–3) |
| Implementierung | `…/concept_toolchain/promotion_check.py`: `_check_atom_closure`, `_check_receipt_independence`, `_check_reverse_trace`, `_check_targets` |

Insbesondere ist "nicht mehr als freigegeben" **deterministisch geloest**:
jeder nicht-formale Diff-Hunk unter den Konzept-Wurzeln muss durch ein
Receipt-/Atom-Zielanker gedeckt sein, sonst ERROR. Und "nichts
verfaelscht" ist ueber die Unabhaengigkeitsregel
`reviewer_principal_id != writer_principal_id` **und** verschiedene
Sessions abgesichert.

**Was wirklich fehlt** — enger und dadurch loesbar:

1. Die Mechanik haengt am **Atom-Register**, das nur ein
   `FULL_ATOM`-Lauf erzeugt. Fuer den vom PO geforderten sofort
   anwendbaren Pfad ("ein Opus-Agent schreibt, ein Codex prueft direkt
   danach") existiert sie nicht.
2. Es gibt **keine leichte Freigabebasis** — nichts, wogegen "genau das
   Freigegebene" ausserhalb eines Vollverfahrens gemessen werden koennte.
3. Es gibt **keinen Auftragsvertrag fuer den pruefenden Agenten**,
   sondern nur fuer den Reviewer eines einzelnen Projektions-Receipts.

**Folge fuer die Arbeit.** Nicht "Verfahren erfinden", sondern
"vorhandene Mechanik auf eine leichte Basis stellen". Der Vorschlag dazu
steht in `A-verfahrensentwurf.md` §3.2 (Einfuegeplan als
Freigabebasis).

**Und ein ehrlicher Zusatzbefund:** Die Mechanik ist normiert und
implementiert, aber im AK3-eigenen Korpus **noch nie durchlaufen**. Der
Gruendungslauf `2026-07-19-conception-support-b4a7d375` traegt einen
"Bootstrap-Sonderstatus" mit sichtbaren Blockern; das Werkstatt-Manifest
weist keinen abgeschlossenen Promotionslauf nach den eigenen Regeln aus.
Eine normierte, implementierte und nie gefahrene Mechanik ist kein
Beweis fuer Praxistauglichkeit.

---

## C-3 — `interface` ist ein falscher Freund, und das Layout kollidiert

**Zwei Befunde an derselben Stelle.**

**(a) Der Name traegt im Blueprint eine andere Funktion.** Dort ist
`schnittstelle/` **keine Reviewstufe**, sondern eine
**Sichtbarkeits- und Tracking-Grenze**: genau zwei Kategorien je Space,
`werkstatt/` traegt den Rohstoff und ist **nie** versioniert,
`schnittstelle/` traegt das abgeleitete Ergebnis und ist versioniert
(`ablage-und-zielorte` §3, "Substruktur der Inkubator-Spaces"). Der
Whitelist-Default sitzt in `concept-inkubator/.gitignore`; jeder Space
schaltet seine `schnittstelle/` einzeln frei. Eine leere
`schnittstelle/` ist dort ausdruecklich "ein Befund, kein Verstoss".

Wer den Namen fuer ein Reviewgate uebernimmt, importiert die Vokabel
ohne ihre Semantik. Das ist genau die Klasse Fehler, die
META-CONCEPT-CONSISTENCY P1 verhindern soll — dieselbe Bezeichnung,
zwei Bedeutungen, keine Pruefung dazwischen.

**Empfehlung:** Den Namen behalten (der PO hat ihn gesetzt, und er ist
sprechend), aber **beide Funktionen explizit zusammenlegen**: `interface`
ist der versionierte Vorlagestand **und** die Reviewstation. Dann ist es
eine bewusste Erweiterung, kein unbemerkter Bedeutungswechsel. Was nicht
geht, ist die Funktion stillschweigend zu tauschen.

**(b) Das Layout kollidiert mit FK-78 §78.3.** FK-78 schneidet
**lauf-orientiert** (`concept-incubator/runs/<run_id>/…`); Blueprint und
PO-Beschreibung schneiden **themen-orientiert**
(`<space>/werkstatt|schnittstelle`). Beides nebeneinander waere eine
zweite Wahrheit ueber den Ort der Inkubation.

Bemerkenswert: der Schreibpfad dieses Auftrags
(`concept-incubator/konzeptpruefung-verfahren/workspace/`) **ist bereits
das themen-orientierte Layout** und damit heute nicht FK-78-konform.
Das ist kein Vorwurf, sondern ein Beleg dafuer, dass das
run-orientierte Layout in der taeglichen Arbeit nicht greift: der
naheliegende Griff ist der Themenordner.

**Empfehlung:** Themenraum aussen, Lauf innen —
`concept-incubator/<space>/workspace/runs/<run_id>/`. `incubator_root`
ist in `concept-governance.json` bereits konfigurierbar (FK-78 §78.2),
die Aenderung bleibt damit eine Layout-Ergaenzung in §78.3 statt einer
Schemaaenderung. Details in `A-verfahrensentwurf.md` §1.3.

---

## C-4 — Die Komponenten- und Schnittstellenschicht: was der Blueprint hat, was der PO will, und was beides unterscheidet

Aufgenommen auf PO-Nachreichung. **Nicht durchkonzipiert, nur praezise
benannt.**

### C-4.1 Was im Blueprint steht

`konzeptwelt-schichtung-und-eigentum.md` (`META-CONCEPT-WORLD-LAYERING`,
Stand `draft`) fuehrt eine **geschlossene Ebenenmenge** ueber fuenf
Pflichten:

| Ebene | Pflicht |
|---|---|
| `System` | Bestand und Schnitt — welche Kontexte es gibt |
| `BoundedContext` | Sprach- und Konsistenzgrenze |
| `Component` | Vertrag/Ersetzbarkeit **und** Eigentum am veraenderlichen Fakt |
| `DomainFact` | Identitaet, Attribute, Invarianten |

Der Massstab fuer jede Ebene ist scharf gestellt: *"Welche Aussage wird
unmoeglich, wenn ich die Ebene streiche?"* — eine Ebene rechtfertigt
sich nur durch eine Pflicht, die keine Nachbarebene tragen kann.

Der Anlassfall ist mechanisch und uebertragbar: In einem Korpus mit
sauberen Bounded Contexts existierte eine zweistellige Zahl von
Komponentenbezeichnern, **deren saemtliche Nennungen in genau einer
syntaktischen Rolle standen — im Eigentuemerfeld — und keine einzige in
einer definierenden**. Der Korpus sprang vom Kontext direkt auf den
Fakt. Drei unabhaengige Gruende hielten das offen: das Feld sah aus wie
Freitext; wo eine Regel existierte, las sie kein Werkzeug; wo ein Befund
notiert war, erzwang nichts seine Bearbeitung.

Die tragenden Festlegungen, alle projektunabhaengig:

- **`KW-L0`** — jedes Feld, dessen Wert ein Bezeichner ist, deklariert
  seinen Zielnamensraum und ist damit eine **gepruefte Referenzkante**.
  Kein Bezeichnerfeld traegt eine freie Zeichenkette.
- **`KW-L1`/`KW-L2`/`KW-L3`** — keine Ebene wird uebersprungen; ein
  Bezeichner kommt nur als Definition oder als Referenz vor; ein
  unbekannter Eigentuemer erzeugt **nie** implizit einen Eintrag.
  Operativ: *der Aenderungssatz, der einen Eigentuemerwert einfuehrt,
  enthaelt die Definition.*
- **Das Portobjekt als eigenes Schema** — `id`, `visibility`,
  `consumers[]`, `operations[]` mit typisierten Parametern und
  Rueckgabetyp, `contract_ref` als **Anker auf die Prosa-Semantik**.
- **`KW-C2` Praezisionsboden `S0`–`S6`** — ein *wirksamer* Port
  (jemand nennt ihn im Bedarf, oder der Anbieter ist bindbar) verlangt
  **`S5` ohne Ausnahme**: Operationen + Parameternamen + Parametertypen
  + Rueckgabetyp. Hergeleitet aus dem Divergenztest, nicht aus Geschmack.
- **`KW-C4` Konsumart an der Kante** — `sync|async` gehoert an den
  `requires`-Eintrag des Konsumenten, nicht an den Port. Herleitung:
  ein realer Lauf meldete zweistellig viele Zyklen, **von denen kein
  einziger einer war**, weil das Modell nur eine Kantenart kannte.
- **§5.1 Zwei Teile, zwei Wohnorte:** Signatur und Kante
  maschinenlesbar in der Registry, **Semantik ausschliesslich in der
  Prosa des Anbieters**. Single-Assertion wird damit *konstruktiv*
  erfuellt statt durch Disziplin — keine Schicht kann den Inhalt der
  anderen wiederholen, weil es verschiedene Aussagen sind. Ein
  Registryeintrag mit prosaischem Vertragssatz im Freitextfeld ist
  bereits der Fehler.

### C-4.2 Wo die PO-Beschreibung vom Blueprint abweicht

Der PO beschreibt eine Schicht, die **von den Bounded Contexts abweichen
darf**, **orthogonal** zu ihnen liegt und die **Projektion darauf ist,
wie tatsaechlich in Repositories und Software-Artefakte geschnitten
wird**. Das ist **nicht** die Component des Blueprints:

1. Die Blueprint-Component ist **strikt kontextgebunden** — "das Praefix
   des Bezeichners ist der umschliessende Kontext. Kein Freiheitsgrad"
   (§4.3.1), `parent_component` nur im eigenen Kontext.
2. Der Blueprint **verwirft** einen Auslieferungs- oder
   Verzeichnisbegriff ausdruecklich als Ebene: er "traegt keine
   fachliche Pflicht" (§2.2).
3. Die Abbildung auf die Quelltextstruktur ist **ausdruecklich ausserhalb**
   der Policy und "wird in der Bauphase entschieden" (Vorbemerkung,
   §7.3): "Eine benannte Grenze ist das Gegenteil einer Luecke."

**Der PO will also etwas, das der Blueprint bewusst nicht regelt.** Das
ist kein Widerspruch zum Goldstandard — es ist die Flaeche, die der
Goldstandard offen laesst. Zwei Anschlussstellen gibt es dennoch, und
sie sind praezise:

- **§4.6 ist ein offener Punkt des Blueprints und liegt dort dem
  Operator vor:** ob eine Komponentenspezifikation eine **zusaetzliche
  Objektart der formalen Schicht** wird. Genannt sind zwei Vorfragen —
  die Autoritaetsfrage (wer gewinnt bei Widerspruch zwischen
  Komponentenspec und Prosavertrag; fuer Ports ist das **nicht**
  geklaert) und der Ort (formale Familien sind thematisch geschnitten
  und entsprechen den Kontexten nur teilweise, waehrend die
  Komponentenebene strikt kontextgebunden ist).
- **`KW-H1`:** die Registry lebt in derjenigen Schicht, der die
  Autoritaetsordnung Komponenten zuweist — "nicht in derjenigen Schicht,
  die zufaellig schon maschinenlesbar ist". Mit dem Zusatzargument, dass
  eine formale Schicht bewusst **partiell** sein darf, die
  Komponentenebene aber **nicht partiell sein kann**.

Die zweite Vorfrage aus §4.6 ist genau der Punkt, an dem der PO
weitergeht: er will eine Schicht, die den Kontexten *nicht* entsprechen
muss. Der Blueprint sieht die Spannung und laesst sie offen; der PO
loest sie in die andere Richtung auf.

### C-4.3 Was AK3 heute hat — und was dadurch fehlt

**AK3 hat auf dieser Achse mehr als der Blueprint und weniger zugleich.**

*Vorhanden:*

- **FK-07** (`component-architecture`, `architecture-conformance`,
  `architecture-checker`) mit normativem Top-Level-Schnitt (§7.4),
  verbindlichen Importgrenzen (§7.8), messbaren Invarianten (§7.9) und
  einem **deterministischen Checker gegen den Python-Code** (§7.7) —
  also genau die Bauphasen-Bindung, die der Blueprint ausklammert.
- **`bounded-contexts.yaml`** mit `responsibility`, `owns`, `excluded`
  je BC — der Blueprint-Pflicht 1 entsprechend, semantisch reich.
- **`domain-registry.yaml`** mit `contract_docs`/`member_docs` je BC —
  die dokumentbezogene Vertragssicht.

*Nicht vorhanden — und das ist die Luecke:*

1. **Keine maschinenlesbare Component als Objekt.** `module-registry.yaml`
   ist eine **flache Namensliste** ohne `responsibility`, ohne `owns`,
   ohne `provides`, ohne `requires`. Es gibt kein Objekt, gegen das
   `KW-L1` pruefen koennte.
2. **Kein Portobjekt.** AK3 spricht in FK-07 §7.2 Nr. 6 von
   "veroeffentlichten Ports der owning Components" — als **Prosa**.
   Es existiert keine Portidentitaet, keine `operations[]`, kein
   `contract_ref`, keine `visibility`, keine `consumers[]`. Der
   Praezisionsboden `S5` ist damit nicht einmal formulierbar.
3. **Keine Konsumart an der Kante.** AK3s Architekturpruefung arbeitet
   auf dem **Importgraphen**. Ein Importgraph kennt nur eine Kantenart —
   exakt die Konstellation, aus der im Blueprint zweistellig viele
   Falschzyklen entstanden.
4. **Kein `KW-L0`-Aequivalent.** AK3 erzwingt Referenzintegritaet ueber
   Dokument-IDs, Anker und `formal.*`-IDs (W1). Ob ein *Feld* eine
   Referenzkante traegt, ist nirgends deklariert — genau die Luecke, aus
   der der Blueprint-Anlassfall entstand.
5. **Kein Ort fuer die Repository-Projektion.** FK-07 §7.6 fuehrt eine
   "Repository-Regel", `PROJECT_STRUCTURE.md` die Verzeichnisstruktur —
   beides Prosa, beides nicht als Ebene mit Eigentum und Vertrag
   modelliert.

**Was daraus praktisch folgt.** AK3 kann heute die Frage *"welche
Komponente besitzt diesen Fakt, welchen Port bietet sie an, und mit
welcher Signatur"* nicht maschinell beantworten. Es kann nur pruefen,
dass die **Imports** die in Prosa gezogenen Grenzen einhalten. Das ist
eine Konformanzpruefung ohne Vertragsobjekt: sie faengt Verstoesse gegen
den Schnitt, aber nicht die Klasse "Vertrag existiert nur als Name"
— und genau diese Klasse hat im Blueprint den Bruch verursacht.

**Empfehlung: eigene Konzeptarbeit, nicht Teil dieses Umbaus.** Die
Flaeche beruehrt FK-07 (Komponentenschnitt), FK-17/FK-18 (Ownership),
den Formal-Layer-Vertrag und die Registry-Landschaft gleichzeitig. Sie
traegt mindestens zwei echte Weichen (Objektart in der formalen Schicht;
Kontextbindung ja/nein) und ist damit nach den Kriterien aus
`A-verfahrensentwurf.md` §4 ein **Council-Fall mit
Vollstaendigkeitsanspruch**. Sie in die Konzeptpruefungs-Umstellung
hineinzuziehen waere die God-Task, die CLAUDE.md verbietet.

---

## C-5 — `gap_class` fehlt: AK3 kann "benannte Luecke" nicht entscheiden

**Befund.** ATOM-01 §8.2a fuehrt eine Pflichtklassifikation jeder Luecke:

| Klasse | Folge |
|---|---|
| `extension` | darf benannt offen bleiben |
| `calibration` | darf offen bleiben, **wenn** der Interimvertrag vollstaendig ist (Startstatus, Nichtverfuegbarkeitsverhalten je Consumer, Promotionskriterium, und die Bedingung, unter der ein Startwert produktives Verhalten *nicht* freischaltet) |
| `contract` | **blockiert** — ein aktiver Vertrag/Consumer/Gate setzt die fehlende Semantik bereits voraus; ein Owner- oder Zukunftsverweis heilt sie nicht |
| `decision` | **blockiert** — echte Weiche ohne Entscheidungsinstanz |

Die Klassifikation ist ausdruecklich **kein Ermessen**: sie folgt aus
zwei Fragen in fester Reihenfolge, und die zweite ist der Divergenztest
(Invariante 13): *Koennen zwei gewissenhafte Implementierer hier
wesentlich verschiedenes Verhalten bauen?*

**AK3 kennt diese Achse nicht.** FK-78 §78.9 fuehrt Dispositionen
(`COVERED_EXACT`, `OPEN_MISSING`, `DEFERRED_BACKLOG`, …), aber keine
Klassifikation der Luecke selbst. `DEFERRED_BACKLOG` verlangt
`owner`, `trigger` und `anchor` — das ist die **Sichtbarkeit** einer
Luecke, nicht ihre **Zulaessigkeit**. Ein `deferral` mit Owner und Anker
ist heute in AK3 formal in Ordnung, auch wenn ein aktiver Consumer die
fehlende Semantik bereits voraussetzt.

**Warum das teuer ist.** Ohne `gap_class` ist "wir haben die Luecke
benannt" ein universeller Freifahrtschein. Der Blueprint zieht daraus
sogar eine Freigabekonsequenz (P7): eine `contract`-Luecke verletzt das
Freigabekriterium "keine fremde Erwartung ins Leere" **auch dann, wenn
sie sauber benannt ist**.

**Empfehlung:** `gap_class` als Pflichtfeld an `OPEN_MISSING` und
`DEFERRED_BACKLOG` in FK-78 §78.9 nachziehen, mit der
Severity-Untergrenze aus ATOM-01 §12.2 (`contract`/`decision`
mindestens P1; widerlegte Closure-Behauptung in Kernmechanik P0). Das
ist projektunabhaengige Methodik und passt ohne Reibung in den
bestehenden Feldkatalog.

---

## C-6 — Der kalte Implementierbarkeitstest fehlt: AK3 hat kein Werkzeug, das Abwesenheit findet

**Befund.** ATOM-01 §9.5 formuliert den Test und begruendet ihn mit
einem Satz, der die ganze Pruefarchitektur einordnet:

> Dieser Test ist das einzige Werkzeug des Verfahrens, das
> **Abwesenheit** findet. Alle uebrigen Kanten pruefen Behauptungen;
> eine fehlende Sache behauptet nichts und erzeugt daher von sich aus
> keine Pruefung.

Das gilt fuer AK3 unveraendert und trifft dort **jedes einzelne** Gate:
Frontmatter-Lint, Referenzintegritaet, Formal-Compile,
Decision-Record-Gate, Projektionsmanifest, Promotion-Closure — alle
pruefen vorhandene Aussagen gegen vorhandene Ziele. Auch W2 und W3
taten das: W2 prueft **vorhandene** normative Aussagen gegen die
Registry, W3 **vorhandene** Aussagensets gegeneinander. Keines von
ihnen kann melden, dass etwas gar nicht dasteht.

**Die operative Form ist billig:** Ein unbeteiligter Agent bekommt
ausschliesslich die Primaerquellen und den Auftrag, das Verhalten zu
spezifizieren. Jede Stelle, an der er eine eigene Annahme einfuegen
muesste, wird als Luecke registriert — **als Befund, nicht als
Rueckfrage an den Auftraggeber**. Zwei unabhaengige Laeufe auf
identischer Eingabe muessen dieselben Schluessel, Werte oder dieselbe
Missingness erzeugen; weichen sie ab, liegt eine Vertragsluecke vor.

**Das ist der Test, fuer den die Harness-Bridge gebaut ist.** Er
verlangt genau, was das neue Verfahren liefert: einen unabhaengigen
Agenten mit eigener Strategie, dem man ein Ziel gibt statt eines
Vorgehens. Er ist in `A-verfahrensentwurf.md` als **R3** aufgenommen.

---

## C-7 — Die Provider-Claim-Kante fehlt

**Befund.** ATOM-01 §9.4: Jede Aussage der Form "Dokument X besitzt,
definiert, liefert, enthaelt, pinnt oder fuehrt Y" ist eine positive
Closure-Behauptung ueber **fremden** Bestand. Sie wird dreistufig
geprueft: der Claim muss konkrete Zielsymbole nennen (ein blosser
Dokumentverweis besteht die Kante nicht), jedes Symbol muss im
Zieldokument namentlich existieren, und es muss dort dieselbe Bedeutung
tragen.

Entscheidend ist die Bauform: **die Pruefung ist paarweise und an
keinem der beiden Dokumente allein feststellbar.** Wer nur das
Zieldokument liest, sieht keine offene Erwartung — die steht beim
Claimenden. Wer nur den Claimenden liest, sieht einen Verweis, der
plausibel aussieht.

**AK3-Stand.** W1 (`check_concept_reference_integrity.py`) prueft
Aufloesbarkeit von Dokument-IDs, §-Ankern, `formal.*`-IDs und Pfaden.
Das deckt Stufe 2 fuer *aufloesbare Referenzen* ab, aber nicht Stufe 1
(nennt der Claim ueberhaupt Zielsymbole?) und nicht Stufe 3
(Bedeutungsgleichheit). Und der haeufigste Fall entzieht sich W1
ganz: eine Prosaaussage "die konkreten Werte liefert FK-93" ohne
benannte Symbole ist referenzintegritaets-**gruen** und trotzdem eine
unbelegte Closure-Behauptung.

**Belegter Anlassfall in AK3:** genau diese Klasse ist in AG3-179 als
E3 aufgetreten — FK-93 beansprucht Autoritaet ueber fremde Werte, ohne
die Kanten zu erklaeren. Der PO hat dazu ausdruecklich festgehalten,
dass der Wurzelfix "nicht deshalb zu machen ist, damit W2 gruen wird",
sondern weil das fehlende Deferral-Modell eine eigene Modellierungsschuld
ist, die "jeden Umbau der Pruefmechanik ueberlebt".

**Empfehlung:** Als Nachweispflicht in R1 fuehren (dort ist sie in
`A-verfahrensentwurf.md` enthalten) und den deterministischen Anteil —
"ein Provider-Claim ohne benannte Zielsymbole ist ein Befund" — als
W1-Erweiterung pruefen, sobald jemand eine belastbare Musterliste der
Claimverben hat. Solange die nicht existiert, bleibt es agentisch.

---

## C-8 — Freigabekriterien fuer `status: active` fehlen in AK3

**Befund.** Der Blueprint (P7) beantwortet mit `status` genau eine
Frage: *Darf sich ein Beschluss auf dieses Dokument stuetzen?* Es ist
damit **keine Reifeaussage, sondern eine Verbindlichkeitsaussage**, und
es gibt vier abschliessende Freigabekriterien: abgegrenzte
Verantwortung, belegte Aussagen, keine offenen Marker, **keine fremde
Erwartung ins Leere**. Vollstaendigkeit ist ausdruecklich **kein**
Kriterium — benannte Luecken sind zulaessig, aber nur `extension` und
vollstaendig interimsgedeckte `calibration` (Bindung an C-5).

Dazu ein Verfahren: Pruefung durch einen **kalten Gegenleser** ohne
Vorkenntnis und ohne Beteiligung an der Entstehung, der je Kriterium ein
Urteil mit Fundstelle liefert und **nicht ueber die Freigabe
entscheidet**. Kriterium 4 wird **paarweise** geprueft: der Gegenleser
erhaelt neben dem Pruefling alle aktiven Dokumente, die auf ihn
verweisen. Ohne diesen Gegenbestand ist das Urteil "nicht erteilbar" —
ausdruecklich nicht "gruen".

Und eine Regel gegen den bequemsten Ausweg: **widersprechen sich zwei
Pruefer, ist das kein Ergebnis.** Die Stelle bekommt sofort eine
`CONFLICT`-Disposition, und es gibt kein zusammenfassendes
Freigabeurteil, solange sie besteht.

**AK3-Stand.** `status: draft|active` existiert im Frontmatter jedes
Konzeptdokuments und wird vom Frontmatter-Lint auf Wertebereich
geprueft. **Kriterien, wann `active` gesetzt werden darf, existieren
nicht.** META-ASSERTION-AUTHORITY normiert `assertion_status` je
**Scope** sehr genau (§3/§4) — aber das ist eine andere Achse als der
`status` des **Dokuments**, und die Beziehung zwischen beiden ist
nirgends ausgesprochen.

**Das ist eine Luecke mit direkter Wirkung auf das neue Verfahren:**
"Freigabe im `interface`" braucht ein Kriterium, gegen das freigegeben
wird. Ohne Freigabekriterien ist die Freigabe eine Meinung.

**Empfehlung:** Die vier Kriterien und die Rolle des kalten Gegenlesers
sind projektunabhaengig und passen als Ergaenzung in
META-ASSERTION-AUTHORITY (dort liegt die Statussemantik) oder in
META-CONCEPT-CONSISTENCY. Der Zielort ist eine Entscheidung, kein
Detail — siehe `D-offene-entscheidungen.md` Entscheidung 5.

---

## C-9 — Gute Nachricht: der Receipt-Vertrag ist ausfuehrerneutral

**Befund.** FK-78 §78.14 zerlegt ein Semantik-Gate bereits in drei
Teile: `prepare` erzeugt ein **Request-Pack**
(`{gate, scope_id, base_revision, template_id, template_digest,
chunks[], request_digest}`), irgendjemand fuehrt aus, `import`
validiert ein **Semantik-Receipt** mit vollstaendiger
Chunk-Digest-Rueckbindung, und `check.py semantic-status` verrechnet.

**In diesem Vertrag steht nirgends, wer ausfuehrt.** "Die
LLM-Ausfuehrung uebernimmt der Agent/Hub" — das ist bereits offen
formuliert. `participants[].spawn_mode` kennt `harness-bridge` als
gleichberechtigten Wert neben `llm-hub`.

**Folge:** Der Wechsel Hub -> Bridge ist ein **Adaptertausch**, kein
Verfahrenswechsel. Was faellt, ist der Hub-spezifische Betrieb der
AK3-Skripte `check_concept_authority_prose.py` /
`check_concept_scope_consistency.py` und die dort verbaute
Partitionierung — nicht das Modell aus Request-Pack, Receipt und
deterministischer Verrechnung.

**Das ist der wichtigste konstruktive Befund dieses Berichts:** die
Umstellung ist erheblich kleiner, als der Auftrag vermuten laesst, wenn
man auf dem vorhandenen Receipt-Vertrag aufsetzt statt neben ihm.

**Kleiner Folgebefund:** FK-78 §78.17 Nr. 3 fuehrt "Hub-Batch-Komfort
fuer W2/W3 in Zielprojekten" als deklarierte Folge-Story. Dieser
Folge-Story faellt mit der Umstellung die Grundlage weg; sie gehoert in
die Betroffenheitsmatrix des Decision Records.

---

## C-10 — Werkstatt-Tracking: AK3 versioniert, der Blueprint nie

**Befund.** Der Blueprint haelt `werkstatt/` **grundsaetzlich
ausserhalb der Versionsverwaltung** — Whitelist-Default in
`concept-inkubator/.gitignore`, jeder Space schaltet nur seine
`schnittstelle/` frei, "ein neuer Space ist damit von Haus aus dicht".
Begruendung ist dort der Datenschutz (intime Quellen).

AK3 macht es anders und **besser begruendet**: `concept-incubator/` ist
versioniert; ignoriert werden nur `locks/`, `secrets/`, die
Mutex-Dateien und das lokale Artefakt-Register-Overlay. An die Stelle
der Pauschalregel tritt FK-78 §78.13: **Datenklassen je Artefakt**
(`open|internal|sensitive`, unklassifiziert zaehlt fail-closed als
`sensitive`), `effective_class` als Maximum ueber den Provenienzgraphen,
`vcs_disposition` daraus abgeleitet und ein Commit-Gate, das Verstoesse
blockiert.

**Kein Handlungsbedarf — aber eine Warnung.** Wer den Blueprint-Space
mitsamt seinem `.gitignore`-Muster uebernimmt, wuerde AK3s feinere
Loesung durch eine groebere ersetzen und dabei die Nachvollziehbarkeit
der Werkstatt verlieren. Der Themenraum wird uebernommen, das
Ignore-Muster nicht.

---

## C-11 — Was AK3 heute behauptet, das das neue Verfahren nicht mehr traegt

| Fundstelle | Aussage | Status nach dem Umbau |
|---|---|---|
| `AGENTS.md` Z. 73–87 | W2/W3 vor jeder Landung normativer Konzeptaenderungen | **abgeloest** — Wortlaut in `B-uebergangsvermerk.md` |
| META-CONCEPT-CONSISTENCY §6 | "W2/W3 laufen nightly und zusaetzlich vor der Landung" | **Betriebspflicht ausgesetzt**; Werkzeugbeschreibung §5 bleibt gueltig |
| META-CONCEPT-CONSISTENCY §5 | "LLM nur als Bewertungsfunktion … Kein Werkzeug entscheidet frei" | **praezisierungsbeduerftig** — siehe C-1 |
| META-CONCEPT-CONSISTENCY §7 | Umsetzungsfahrplan W1→W4→W2→W3 | historisch; W2/W3 sind umgesetzt und werden abgeloest |
| FK-78 §78.17 Nr. 3 | Folge-Story "Hub-Batch-Komfort fuer W2/W3" | **gegenstandslos** |
| FK-78 §78.14 | "Hub-Batch-Betrieb fuer W2/W3" als AK3-Spezifikum | wird Bridge-Betrieb; Receipt-Vertrag bleibt (C-9) |
| DK-16 §4 Nr. 1–7 | siebenstufiger Lauf ohne Vorlagestation | **ergaenzungsbeduerftig** um `interface` zwischen Nr. 6 und Nr. 7 |
| FK-78 §78.3 | `concept-incubator/runs/<run_id>/` als Layout | **ergaenzungsbeduerftig** um den Themenraum (C-3b) |

Zusaetzlich ein **Faktenbefund ohne Verfahrensbezug**, der in der
Baseline haengt: `concept/_meta/authority-prose-baseline.yaml` fuehrt
begruendete W2-Baseline-Eintraege. Wird W2 abgeloest, braucht die Datei
eine Entscheidung — weiterfuehren, einfrieren oder in das neue
Befundregister ueberfuehren. Stilles Liegenlassen waere ZERO-DEBT-Bruch.

---

## C-12 — Was AK3 besser loest, mit Begruendung

Der Auftrag verlangt ausdruecklich eine Begruendung, wo AK3 abweicht.
Vier Stellen:

1. **Mechanisierte Closure statt Register in `var/`.** ATOM-01 ist ein
   **Reviewverfahren** mit dreizehn Arbeitsartefaktrollen unter `var/`
   und einer Liste empfohlener Assertions (§11.2), die "als Code
   ausgedrueckt werden SOLL". AK3 hat diese Assertions **gebaut**:
   Digest-Pins in `RUN.json`, verkettetes `source-intake.tsv` mit
   Praefix-Beweis, deterministische Unit-Re-Derivation, Scope-Locks mit
   Fencing-Token, Diff-Hunk-Reverse-Trace. *Begruendung:* Ein Verfahren,
   dessen Closure von der Disziplin des Ausfuehrenden abhaengt, ist in
   einem agentischen Setting genau das Falsche — der Ausfuehrende
   wechselt staendig und hat keine Erinnerung.

2. **Die Werkstatt ist versioniert und datenklassifiziert.** Siehe C-10.
   *Begruendung:* Eine Pauschalregel "nie tracken" loest ein
   Datenschutzproblem durch Verlust von Nachvollziehbarkeit; die
   Klassenregel loest es gezielt.

3. **`assertion_status` und `equivalence_status` als korpusweite
   Achsen.** Der Blueprint fuehrt ein `projection-manifest.yaml`, aber
   seine Statusableitung lebt in `assertion-authority.md` als Prosa. AK3
   hat sie zusaetzlich in formalen Invarianten
   (`projection_lifecycle_first`, `projection_status_derivation`) und im
   `check.py projection`. *Begruendung:* Statusableitung ist
   widerspruchsanfaellige Lifecycle-Semantik — genau der Fall, den P4
   in die formale Schicht verweist.

4. **`blocked_projection` als ehrlicher Stopp.** AK3 kennt einen
   Zustand, in dem ein Scope entschieden, aber nicht ausfuehrbar ist,
   und verbietet ausdruecklich, ihn als schwaechere Form von `active` zu
   lesen. *Begruendung:* Das ist die einzige Antwort auf die zwei
   symmetrischen Fehler — "gilt schon" bei fehlender Projektion und
   "gilt noch" bei veralteter.

**Und eine Stelle, an der der Blueprint AK3 methodisch voraus ist,
ueber die Einzelbefunde hinaus:** er schreibt seine
**Herleitungen** auf — welcher reale Lauf welchen Befund erzeugt hat,
welche fruehere Fassung woran gescheitert ist, und was die Ruecknahme
gekostet hat. `konzeptwelt-schichtung-und-eigentum.md` traegt seine
eigene Rueckstufung auf `draft` im Kopf, mit Zaehlung der Befunde und
der Lehre in einem Satz. AK3-Konzepte begruenden ihre Regeln, aber
protokollieren ihre **Irrwege** kaum. Das ist kein kosmetischer
Unterschied: ein Agent mit Zwanzig-Minuten-Horizont leitet eine
zurueckgenommene Regel korrekt neu ab, wenn ihre Herleitung
unveraendert stehenbleibt — genau das, was der Blueprint als
zweiseitigen Blast-Radius-Sweep normiert (P3, rueckwaerts).
