# Proposal worker-a: Reviewvertrag als endlicher Widerlegungsvertrag

## Entscheidung

Eine Review bindet **nicht** an die Befundliste aus Runde 1. Runde 1 darf
deshalb nicht versprechen: „Behebe diese Liste, dann ist die Story fertig."
Sie bindet an einen vor der ersten Review festgehaltenen, endlichen
**Widerlegungsvertrag**. Dieser besteht aus:

1. den Abschlusszusagen der Story (`Z`): Akzeptanzkriterien, im Diff neu oder
   geaendert behauptete Invarianten sowie die auf den Kandidaten anwendbaren
   nicht aufschiebbaren Projektregeln;
2. einer fuer jede Zusage benannten Pruefmenge (`U`): geaenderte Artefakte,
   ihre deklarierten direkten Konsumenten und bei All-Aussagen ein
   maschinell inventarisierbares Universum;
3. dem je Zusage geschuldeten Abschlussbeleg: Test, Realitaetsnachweis,
   statische Vollstaendigkeitsinventur oder eine andere widerlegbare Evidenz;
4. einer Defektklassifikation, deren bereits akzeptierte Klassen innerhalb
   von `U` vollstaendig auszuraeumen sind.

Runde 1 bindet also den **Massstab**, nicht die Menge dessen, was ein Reviewer
zufaellig zuerst gesehen hat. Neue Befunde sind in der Abschlussreview
zulaessig. Eine weitere offene Erkundungsrunde ist nach erbrachtem
Abschlussbeleg dagegen unzulaessig: Sie waere eine neue Auditbeauftragung,
nicht mehr die Verifikation dieser Story.

## Das entscheidbare Blocker-Praedikat

Ein Befund `F` blockiert den aktuellen Kandidaten genau dann, wenn mindestens
eine der folgenden Bedingungen belegt ist:

- **B1 — Zusagenwiderlegung:** `F` enthaelt einen konkreten Gegenfall, durch
  den mindestens eine Zusage aus `Z` auf dem Kandidaten falsch ist.
- **B2 — Kandidatenverursachter ERROR:** Der Kandidat hat `F` erzeugt oder
  materiell verschaerft und `F` verletzt eine projektweite ERROR-Regel, auch
  wenn die Story diese Regel in ihren Akzeptanzkriterien vergessen hat.
- **B3 — offene Klasse:** `F` ist eine weitere Instanz einer bereits als
  blockierend akzeptierten Defektklasse innerhalb von `U`, und fuer diese
  Klasse fehlt noch die vollstaendige Inventur mit leerem Restbestand. Eine
  Klasse ist nicht dadurch geschlossen, dass die bisher bekannten Instanzen
  repariert sind.
- **B4 — fehlender Abschlussbeleg:** Eine Zusage aus `Z` ist eine
  All-Aussage, ihre Pruefmenge ist nicht endlich inventarisiert, oder der
  geschuldete Realitaets-/Vollstaendigkeitsnachweis fehlt oder ist
  nachweislich unvollstaendig.
- **B5 — Stop-the-line:** `F` belegt einen aktuell ausnutzbaren Fail-open-,
  Safety-, Security- oder Datenverlustpfad des landefertigen Repository-
  Kandidaten. Ein solcher Befund ist Release-Blocker, auch wenn er nicht durch
  die Story verursacht wurde. Der Storyscope darf bestimmen, wer ihn behebt;
  er darf nicht einen wissentlich unsicheren Kandidaten freigeben.

Ist keine dieser Bedingungen erfuellt, verlaengert `F` die Review dieser Story
nicht. Dann ist vor Abschluss zwingend ein Routing-Artefakt mit Locator,
Begruendung fuer `nicht B1..B5`, Owner, ausloesendem Trigger und Termin oder
PO-Entscheid vorhanden. „Out of scope" allein ist keine Begruendung. Ein
WARNING behaelt dabei seine Spiegelpflicht; ein anderer Owner ist kein
Vergessenserlaubnis.

Damit wird die in der Sitzung beobachtete Regel

> „blockiert genau dann, wenn der Befund die Zusage der Story falsch macht"

im Kern bestaetigt, aber sie ist allein zu eng. B2 verhindert, dass ein
schlecht geschnittenes Akzeptanzkriterium einen vom eigenen Diff erzeugten
ERROR legitimiert. B3 verhindert das fuenfrundige Flicken desselben
Shell-Parser-Fehlertyps. B4 macht aus „alles" eine beweispflichtige Aussage.
B5 bewahrt FAIL-CLOSED dort, wo Storyrouting sonst einen aktiven schweren
Schaden wissentlich landen liesse.

## Runden- und Terminierungsnorm

Es gibt genau zwei Arten offener Review; danach nur noch gezielte
Fixverifikation:

1. **Ermittlungsreview.** Ein unabhaengiger Reviewer darf mit Repo-Zugriff frei
   ermitteln und ueber die benannten Achsen hinausgehen. Alle Befunde werden
   gegen B1--B5 klassifiziert. Fuer jede akzeptierte Blockerklasse ersetzt
   eine systematische Klasseninventur das weitere Suchen nach Einzelstellen.
2. **Abschlussreview auf dem remedierten Kandidaten.** Ein unabhaengiger
   Reviewer prueft alle Zusagen, Inventuren, Abschlussbelege, geaenderten
   Modelle und gerouteten Nichtblocker. Er darf neue Befunde einbringen. Ein
   neuer B1--B5-Befund oeffnet nur die betroffene Zusage oder Klasse erneut.
3. **Fixverifikation.** Nach Befunden der Abschlussreview wird nur noch der
   Befundfix samt seinem tatsaechlichen Aenderungs- und Konsumentenumfang
   geprueft. Die Fixverifikation ist keine erneute freie Repo-Erkundung. Hat
   der Fix ein Modell geloescht, ersetzt oder eine neue Defektklasse
   geschaffen, ist genau dieses neue Modell erneut Abschlussgegenstand.

Eine weitere Reviewrunde ist **Pflicht**, wenn mindestens eines gilt:

- ein B1--B5-Blocker ist offen;
- ein Blockerfix ist noch nicht unabhaengig verifiziert;
- die vollstaendige Klasseninventur oder ein geschuldeter Abschlussbeleg
  fehlt;
- seit der letzten Abschlussreview wurde `U` durch einen Fix mechanisch
  erweitert oder ein Modell ersetzt und dieser neue Gegenstand wurde noch
  nicht geprueft;
- ein Nichtblocker ist noch nicht belastbar geroutet.

Die Review **terminiert**, sobald alle fuenf Aussagen falsch sind. Ab diesem
Punkt ist eine weitere offene Erkundungsrunde Verschwendung und sogar ein
Vertragswechsel. Erkennt jemand danach einen Defekt, ist das ein neuer
Incident bzw. ein neuer Storyeingang; es wird nicht rueckwirkend behauptet,
die abgeschlossene Review habe Fehlerfreiheit des gesamten Repositories
garantiert.

Diese Norm garantiert keine metaphysische Fehlerfreiheit. Sie garantiert
etwas Entscheidbares: Jede bekannte Widerlegung ist geschlossen oder
geroutet, jede All-Aussage hat ein endliches Universum und einen
Vollstaendigkeitsbeleg, und der letzte Kandidat wurde unabhaengig gegen genau
diesen Vertrag geprueft.

## Wer klassifiziert und entscheidet

Der Reviewer entscheidet nicht ueber die Landung. Er liefert Gegenfall,
Locator, vermutete Defektklasse und die betroffene Zusage bzw. Projektregel.
Repo-Zugriff ist damit Freiheit der **Ermittlung**, nicht Freiheit der
Entscheidung; das ist mit FK-78 §78.14 vereinbar.

Der Orchestrator wendet B1--B5 an und muss die Zuordnung schriftlich
herleiten. Er darf weder eine Zusage umformulieren noch eine Pruefmenge
verkleinern. Bestreiten Verfasser oder Reviewer die Klassifikation, entscheidet
ein dritter Principal in einer anderen Session, der weder Kandidat noch
Befund verfasst hat. Bis dahin gilt fail-closed `blockiert`.

Nur der PO darf:

- eine Storyzusage nach einem Gegenfall verkleinern oder gegen eine andere
  Zusage tauschen;
- bei fehlendem Konzeptanker eine neue Grundentscheidung setzen;
- zwischen zwei fachlich unterschiedlichen Endzustaenden waehlen.

Der PO darf einen bestaetigten B5-Befund nicht als Risikoakzeptanz
wegentscheiden; er kann bei bestrittener Einordnung entscheiden, welcher
fachliche Endzustand den Befund an der Wurzel schliesst.

Eine PO-Verkleinerung ist kein „Fix". Sie re-framed `Z` und startet die
Abschlussreview fuer den neuen Vertrag erneut.

## Befundklassen: tragfaehige Unterscheidung

Die drei im Briefing genannten Klassen sind tragfaehig, wenn sie nicht nur
benannt, sondern so verrechnet werden:

- Eine **neue Instanz einer geschlossenen Klasse** innerhalb von `U` ist B3.
  Sie beweist, dass der behauptete Vollstaendigkeitsbeleg falsch war. Es wird
  nicht noch einmal die Stelle geflickt; Inventur oder Modell wird korrigiert.
- Eine **neue Klasse an einem veraenderten Artefakt** wird neu gegen B1--B5
  bewertet. Wurde ein Modell geloescht oder ersetzt, ist der neue Gegenstand
  noch nicht reviewed; die Abschlussreview ist fuer ihn Pflicht.
- Eine **Widerlegung der Storyzusage** ist ohne Abwaegung B1. Severity und
  Rundennummer sind dafuer irrelevant.

Die Klassifikation verschiebt Willkuer nur dann, wenn `Z`, `U` und der
Gegenfall nicht referenziert werden. Mit diesen drei Locatoren ist die
Entscheidung anfechtbar und von einem dritten Principal reproduzierbar.

## Zusagenbreite als eigentlicher Terminierungshebel

Es gibt keine sinnvolle Obergrenze in Dateien oder Zeilen. Die harte
Obergrenze lautet stattdessen:

> Eine universelle Storyzusage ist nur zulaessig, wenn ihr Universum vor der
> Review endlich und maschinell inventarisierbar ist und der Kandidat einen
> Vollstaendigkeitsbeleg dafuer liefert.

Ist das nicht moeglich, muss die Story vor der Review geschnitten oder die
Zusage durch den PO enger formuliert werden. „Kein produktiver Weg ..." ist
nur dann eine abschliessbare Zusage, wenn `produktiver Weg` in einem
vollstaendigen Register aufgeht: Entry Points, Hook-Handler, MCP-
Registrierungen, produktiv bindbare Skill-Versionen, Command-Fences und
prozessstartende Call-Sites. Die AG3-189-Sitzung zeigt den Preis einer erst
waehrend der Review erfundenen Menge: `text`-Fences, nicht existente
`-m`-Ziele, Bundle-Versionen und der Default in `vectordb/engine.py` wurden
nacheinander zu neuen Teilmengen. Nicht der Reviewer war zu neugierig; die
All-Aussage hatte anfangs keinen abgeschlossenen Zaehler.

## Anwendung auf das Belegmaterial

### AG3-189: der kritische VektorDB-Spaetfund

AG3-189 AC 3 verlangt genau einen Interpreter-Owner und AC 4, dass ein
PATH-`python` maschinell auffaellt. FK-10 §10.2.3 verbietet ebenfalls einen
nackten Interpreter an Paket-Einsprungpunkten. Der Default
`command: str = "python"` in `backend/vectordb/engine.py` ist daher ein
direkter Gegenfall: B1 und, als weitere Interpreterselektor-Instanz innerhalb
der produktiven Einsprungpunkte, B3. Der Test, der denselben Wert erwartete,
ist Gegenbeleg nach META-ASSERTION-AUTHORITY Regel 6, keine Entlastung.

Er blockiert unabhaengig davon, ob er in Runde 2 oder Runde 13 erscheint.
Seine spaete Entdeckung widerlegt einen Runde-1-Befundlistenvertrag, nicht den
Widerlegungsvertrag. Nach meiner Norm haette die Klasseninventur alle
produktiven Prozess-/Runtime-Command-Quellen enthalten muessen; ohne diese
Inventur waere B4 offen gewesen und die Story ohnehin nicht terminierbar.

Auch der in AG3-189 `status.yaml` beschriebene `text`-Fence-Befund ist B3/B4:
Ein Gate, das „alle Kommandos" behauptet und eine ausfuehrbare Fence wegen
ihres Sprach-Tags auslaesst, besitzt keinen gueltigen Abschlussbeleg. Die drei
produktiven Bundles mit nackten Aufrufen, davon zwei auf nicht vorhandene
Module, sind Instanzen derselben offenen Klasse, nicht drei Gruende fuer drei
weitere freie Reviews.

### AG3-219 und AG3-221: geaendertes Modell

AG3-219 belegt zuerst, dass wortgetreues Abschreiben durch das Modell am
harten Zeilenumbruch reproduzierbar scheitert. Das macht den Live-Gate-
Nachweis und damit die Storyzusage falsch: B1/B4. Der Wechsel auf
Quellspannen repariert das Modell statt den Vergleich aufzuweichen.

Der spaetere Cross-Partition-Befund aus AG3-219 R4 ist keine beliebige neue
Repo-Stelle. AG3-219 zog W3 ausdruecklich mit und senkte die Partitionsgrenze;
AG3-221 belegt, dass disjunkte Partitionen niemals jedes Chunk-Paar gemeinsam
pruefen, waehrend der Sweep Scope-Set-Konsistenz zusagte. Das ist B1, B2 und
B4. Deshalb ist AG3-221 zu Recht nicht als erledigte Kleinigkeit markiert,
sondern `blocked` auf die PO-Wahl: paar-deckend pruefen oder die Zusage ehrlich
auf Partitionskonsistenz verkleinern. Weg (B) behebt nicht den Algorithmus;
er ist eine PO-Re-Framierung und verlangt eine neue Abschlussreview gegen die
kleinere Zusage.

Die vier wechselnden Hub-Transportfehler in AG3-219 sind dagegen keine vier
inhaltlichen Befunde. Sie verhindern den geschuldeten Realitaetsnachweis und
sind deshalb B4. Ein begrenzter Retry unbeantworteter Requests ist mit der Norm
vereinbar; ein Retry eines inhaltlichen Urteils waere es nicht.

### AG3-214: Routing muss persistieren

AG3-214 dokumentiert fuenf ERRORs und ein WARNING, nachdem ein frueherer
FK-10/FK-91-Befund aus einer AG3-180-Review nur im Kopf blieb und verloren
ging. Das stuetzt nicht unbegrenzte Runden, sondern die Routingpflicht:
Nichtblocker ohne persistierten Owner, Locator und Trigger sind nicht
terminiert. Innerhalb AG3-214 selbst sind die sechs Befunde Teil der expliziten
Zusage „ein Writer, ein Vertrag" und blockieren dort nach B1; in AG3-180
durften sie nur mit einem solchen Routing aus dem Storyvertrag herausfallen.

## Kosten der Norm, am 2026-08-05 beziffert

Die Norm laesst bewusst vorbestehende, nicht sicherheitskritische Befunde
ausserhalb von `Z` und ausserhalb des vom Kandidaten verursachten Umfangs
unbehoben durch **diese** Story. Das ist nicht kostenlos:

- Aus AG3-189 R15 waeren die drei AG3-220-Gruppen nicht in AG3-189 behoben
  worden: zwei veraltete Aussagen zur Installationsform (FK-01, FK-50), zwei
  Kopien der Python-Untergrenze in FK-01 sowie der fremde/stale Bundle-Floor
  in FK-50 und die fehlende Begruendung des `lookup-userstory-core`-Floors.
- Ebenfalls nicht in AG3-189 behoben worden waere der normative Widerspruch,
  ob Agents die CLI direkt aufrufen duerfen (FK-45 gegen FK-43/Decision Record
  und FK-21). Er braucht eine Grundentscheidung des PO.

Das sind **vier Befundgruppen bzw. mindestens sieben im Storybeleg einzeln
lokalisierte Problemstellen/Entscheidungsluecken**, die beim Abschluss von
AG3-189 weiter existieren duerften. Ihr Preis ist real: AG3-220 bleibt eine
eigene Story mit Abhaengigkeiten; die CLI-Frage bleibt bis zum PO-Entscheid
offen. Die Regel behauptet nicht, sie seien harmlos, sondern nur, dass eine
weitere AG3-189-Review der falsche Owner ist.

Hinzu kommt eine bedingte achte Kostenstelle: Waehlt der PO fuer AG3-221
Partitionskonsistenz, bleibt die fehlende paarweise Scope-Set-Abdeckung
technisch ungebaut. Bezahlt wird mit einer engeren Produktzusage. Waehlt er
Scope-Set-Konsistenz, ist sie B1/B4 und muss vor Abschluss behoben werden.

Der VektorDB-Default, der `text`-Fence-Fehlpass, die nicht existenten
Bundle-Module, der AG3-219-Zitatvertrag und der Cross-Partition-PASS waeren
unter dieser Norm **nicht** vertagt worden: Sie widerlegen jeweils die eigene
Zusage oder deren Abschlussbeleg. Eine Norm, die sie nur wegen ihrer spaeten
Runde ausliefert, lehne ich ab.

## Nicht entscheidbar aus dem vorhandenen Beleg

Die Storydateien sind kein rundenweises Befundregister der rund vierzig
Sitzungsbefunde. Sicher belegt sind AG3-221 aus AG3-219 R4, AG3-220 aus
AG3-189 R15 und der laut Briefing nach Runde 13 gefundene VektorDB-Default.
Fuer die uebrigen Befunde fehlen je Fund Rundennummer, damalige Storyzusage,
Disposition und Fix. Deshalb ist eine ehrliche 40-zeilige Gegenrechnung
„behoben/nicht behoben" aus diesem Paket nicht moeglich. Auch der im Briefing
genannte an AG3-173 geroutete Befund ist in den fuenf benannten Storyakten
nicht mit Locator enthalten.

Nicht durch den Orchestrator entscheidbar ist ferner die PO-Wahl in AG3-221
sowie der agentische CLI-Widerspruch aus AG3-220. Beides veraendert die
Produktzusage und ist keine Klassifikationsfrage. Der Rest ist mit B1--B5
entscheidbar, ohne „angemessen abwaegen" als versteckte sechste Regel.
