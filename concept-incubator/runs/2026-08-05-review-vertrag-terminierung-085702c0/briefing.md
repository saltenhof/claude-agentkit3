# Briefing — Vertrag und Terminierung der Review

## Warum dieser Lauf

AK3 setzt unabhaengige Codex-Reviews als Definition of Done ein
(`CLAUDE.md` §DEFINITION OF DONE). Das funktioniert: In einer einzigen Sitzung
am 2026-08-05 fanden Reviewrunden rund vierzig echte Defekte, die weder Tests
noch Gates gefunden hatten.

Es terminiert aber nicht von selbst. Dieselbe Sitzung brauchte fuer eine
Story **siebzehn Runden**, und der **schwerste Einzelbefund kam nach
dreizehn**: ein `command: str = "python"` als Default-Argument in
`backend/vectordb/engine.py`, abgesichert durch einen Test, der genau diesen
falschen Wert als Erwartung festschrieb.

Ein Reviewer mit Repo-Zugriff findet ueber zehn, zwanzig Runden immer weiter
etwas. Das ist keine Schwaeche des Verfahrens, sondern seine Eigenschaft.
Ungeklaert ist, **wann eine Story trotzdem fertig ist**.

## Die Frage

**Was ist der Vertrag einer Review, und wodurch terminiert sie?**

Nicht gefragt ist, ob Reviews sinnvoll sind, und auch nicht, wie man Reviewer
schaerfer macht. Gefragt ist die Norm, an der ein Orchestrator ablesen kann,
ob eine weitere Runde Pflicht oder Verschwendung ist.

### Teilfrage 1 — Bindungswirkung

Legt Runde 1 den Vertrag fest („das ist, was ich gefunden habe; erfuelle es,
dann geht die Story durch"), oder darf jede Runde Neues auf den Tisch legen?

Die empirische Lage: Die Schwere der Befunde nahm in der beobachteten Sitzung
**nicht monoton ab**. Ein Vertrag aus Runde 1 haette den schwersten Befund
ausgeliefert. Eine unbegrenzte Runden-Reihe terminiert dagegen nie.

### Teilfrage 2 — Der kritische Spaetfund

Runde 2 findet etwas nachweislich Kritisches, das im Vertrag von Runde 1 nicht
steht. Was gilt?

Der Orchestrator hat in der beobachteten Sitzung faktisch nach dieser Regel
gehandelt, ohne sie je aufgeschrieben zu haben:

> Ein Befund blockiert die Story genau dann, wenn er **die Zusage dieser
> Story falsch macht**. Andernfalls bekommt er einen Owner und ein Datum,
> aber nicht diese Runde.

Nach dieser Regel entstanden waehrend der Sitzung drei Folge-Storys
(AG3-220, AG3-221) und eine Zuordnung an eine bestehende (AG3-173). Ob die
Regel richtig ist, ist offen — sie ist Beobachtung, nicht Norm.

### Teilfrage 3 — Wer entscheidet das?

Nach welchem Massstab, und **durch wen**, wird festgestellt, ob ein Befund die
Zusage der Story falsch macht? In der beobachteten Sitzung war das der
Orchestrator — also Partei und Schiedsrichter in einer Person. Das ist der
wunde Punkt.

### Teilfrage 4 — Befundklassen

In der Sitzung liessen sich drei Dinge unterscheiden, die alle „Befund"
hiessen:

1. **Neue Instanz einer bereits geschlossenen Klasse.** Ein handgeschriebener
   Shell-Parser lieferte fuenf Runden lang denselben Fehlertyp an neuer
   Stelle. Behoben wurde es erst, als das Modell geloescht statt der Fall
   geflickt wurde.
2. **Neue Klasse an einem veraenderten Artefakt.** Zweimal wurden ganze
   Modelle geloescht; danach ist der Gegenstand ein anderer.
3. **Etwas, das die Zusage der Story widerlegt.**

Ist diese Unterscheidung tragfaehig? Fuehrt sie zu einem entscheidbaren
Kriterium — oder verschiebt sie die Willkuer nur in die Klassifikation?

### Teilfrage 5 — Zusagenbreite als Terminierungshebel

Die Story mit siebzehn Runden hatte eine sehr breite Zusage („kein produktiver
Weg publiziert oder verwendet einen nackten Aufruf"). Bei dieser Breite
widerlegt fast jeder Fund die Zusage, also wird fast jeder Fund zur
Pflichtrunde.

Folgt daraus, dass die **Vertragsweite** der eigentliche Terminierungshebel
ist und nicht die Reviewer-Disziplin? Und wenn ja: Was heisst das fuer den
Story-Schnitt — gibt es eine Obergrenze fuer die Breite einer Zusage?

### Teilfrage 6 — Zugriff (untergeordnet)

`FK-78 §78.14` verlangt „LLM nur als Bewertungsfunktion, kein Werkzeug
entscheidet frei". Ein Reviewer mit Repo-Zugriff waehlt selbst, was er liest —
das **ist** ein Freiheitsgrad, und genau der macht ihn stark.

Kontext: Der bisherige Bewertungsweg ueber den Multi-LLM-Hub kennt diesen
Freiheitsgrad nicht — dort sieht der Bewerter nur, was hochgeladen wurde. Der
PO hat entschieden, die Bewertung auf die Harness Bridge umzustellen; der Hub
ist nicht mehr Zielarchitektur. Begruendung: „Man kann nur das Qualitaet
sichern lassen, was man explizit hochlaedt, waehrend Agenten sich selber
durchlesen koennen, was sie fuer sinnvoll halten."

Die Sitzung stuetzt das: Die hub-basierten Konzept-Gates fanden an dem Tag
nahezu nichts, die Reviews mit Repo-Zugriff rund vierzig Defekte — fast alle
**ausserhalb** dessen, wo die Story hinsah.

Wo also endet „frei ermitteln" und wo beginnt „frei entscheiden"? Diese Frage
ist dieser Runde **untergeordnet**: Sie ist erst beantwortbar, wenn der
Vertrag steht.

## Was ein Proposal leisten muss

- **Eine entscheidbare Norm**, kein Prinzipienkatalog. Ein Orchestrator muss
  daran ablesen koennen, ob eine weitere Runde Pflicht ist.
- **Am Beleg gepruefte Aussagen.** Die Sitzung vom 2026-08-05 ist im Repo
  nachvollziehbar (Story-Verzeichnisse `AG3-189`, `AG3-214`, `AG3-219`,
  `AG3-220`, `AG3-221`, deren `status.yaml` und `story.md`). Wer eine These
  aufstellt, prueft sie gegen diesen Bestand — belegt oder widerlegt.
- **Die Kosten der eigenen Norm.** Jede Terminierungsregel laesst etwas durch.
  Welche der vierzig Befunde jener Sitzung waeren unter der vorgeschlagenen
  Norm **nicht** behoben worden? Diese Frage ist zu beantworten, nicht zu
  umgehen.
- **Die Gegenposition ernst nehmen.** Wer fuer harte Bindung an Runde 1
  argumentiert, muss den VektorDB-Fall erklaeren. Wer fuer offene Runden
  argumentiert, muss sagen, wann Schluss ist.
- Explizit benennen, was **nicht** entscheidbar ist und beim PO liegt.

## Was nicht Gegenstand ist

- Die Migration vom Hub auf die Harness Bridge als solche. Sie ist entschieden;
  hier geht es um den Vertrag, nicht um den Transport.
- Konkrete Story-Inhalte aus der Sitzung. Sie sind **Belegmaterial**, nicht
  Gegenstand.
- Werkzeugauswahl, Prompt-Formulierungen, Modellwahl.
