# Runde 2 worker-a: Die Kappung braucht ein Entscheidungsdossier

## Entscheidung

Das Erreichen der konfigurierten Rundengrenze erzeugt den Zustand
`ESCALATED_FOR_DECISION`, **kein Reviewurteil**. Der Zaehler beantwortet nur,
wer jetzt handeln darf: Der automatische Lauf darf keine weitere Runde
starten. Er sagt weder `PASS` noch `REPLAN_REQUIRED`.

Die Eskalation ist entscheidungsreif, wenn ein Mensch ohne erneute
Repo-Ermittlung drei Fragen beantworten kann:

1. Welche noch offene Zusage oder Invariante verhindert heute den Abschluss?
2. Warum hat die bisherige Methode sie nicht geschlossen?
3. Welche nachpruefbare Wirkung hat jede jetzt zulaessige Entscheidung?

Damit der Mensch nicht bloss eine Rundenzahl bestaetigt, braucht die
Eskalation ein **Entscheidungsdossier**. Die in Runde 1 gemeinsam ermittelten
Vertrags-, Klassen-, Routing- und Unabhaengigkeitsregeln gelten darunter
unveraendert; sie werden hier nicht erneut aufgelistet.

## 1. Pruefbarer Mindestgehalt der Eskalation

Das Dossier hat genau sechs Pflichtteile:

| ID | Pflichtinhalt | Mindestnachweis |
|---|---|---|
| E1 | **Eingefrorener Gegenstand** | `contract_id`, Vertragsversion, Kandidaten-Digest, wirksames Rundenlimit, verbrauchte Runden und unveraenderte Referenzen auf Claim-, Domain- und Beweisregister |
| E2 | **Offene Entscheidungseinheiten** | Fuer jeden offenen Punkt: Finding-ID, Locator, beobachteter Gegenfall, betroffener Claim bzw. globale Invariante, Defektklasse, Status des Fixes und fehlender Abschlussbeleg. Eine blosse Anzahl ist ungueltig. |
| E3 | **Verlauf** | Je Runde: erstmals gesehene Klassen, wiederkehrende Klassen, wiedereroeffnete Closure-Behauptungen, Aenderung des Kandidaten und Aenderung der Pruefdomain. Die Differenz zur vorigen Runde muss maschinell berechnet sein. |
| E4 | **Blockadediagnose** | Eine primaere Diagnose und gegebenenfalls Alternativen, jeweils mit den sie tragenden E2-/E3-Fakten, Gegenindizien und einem Satz dazu, was die Diagnose widerlegen wuerde. Maschinelle Beobachtung und bewertete Schlussfolgerung sind getrennt auszuweisen. |
| E5 | **Entscheidungsoptionen mit Preis** | Mindestens `final disponieren`, `weitere Runde(n) gewaehren` und `REPLAN_REQUIRED`; je Option: welche offenen Punkte danach wie disponiert sind, welche Zusage danach bewiesen oder unbewiesen bleibt und welches konkrete Risiko bzw. welcher Aufwand entsteht. |
| E6 | **Naechster Erkenntnisschritt** | Fuer eine Fortsetzung: Anzahl beantragter Runden, geaenderte Methode, zu pruefende Hypothese/Domain, erwarteter Beleg und Abbruchbedingung. „Noch einmal reviewen“ ist kein Plan. |

Ein Dossier ist **formal gueltig**, wenn alle Referenzen existieren, die
Rundendifferenzen aus dem unveraenderlichen Finding-Ledger nachgerechnet werden
koennen und jeder offene Blocker genau einmal disponiert wird. Das ist
maschinell pruefbar.

Es ist **inhaltlich entscheidungsreif**, wenn ein vom Implementierer
unabhaengiger Reviewer E4 gegen E1 bis E3 bestaetigt oder als bestritten
markiert hat und E5 die Folgen ohne versteckte Annahme benennt. Der
Orchestrator rendert und verrechnet; er erfindet die Diagnose nicht. Bei Streit
ueber Claim-, Domain- oder Klassenzuordnung greift die gemeinsame Regel:
Adjudikation durch einen dritten unabhaengigen Principal, bis dahin
fail-closed. Ist die Adjudikation selbst am Eskalationspunkt noch offen, ist
das eine zulaessige Diagnose (`ADJUDICATION_BLOCK`), aber nie ein stilles
`PASS`.

**Durchfallendes Gegenbeispiel:**

> Runde 5 von 5 erreicht. Drei Findings sind offen. Das Team kommt nicht
> weiter. Empfehlung: zwei weitere Runden.

Das ist ein Statusbericht. Es fehlen Gegenfaelle und Zusagenbezug, der Verlauf,
die Ursache der ausbleibenden Closure, die Aenderung der Methode und der Preis
des Abschlusses. Ein Mensch kann hier nur glauben oder ablehnen.

## 2. Diagnose der eigenen Blockade

Die Diagnose ist keine freie Selbsterzaehlung des ausfuehrenden Agents. Sie
entsteht in zwei Schichten.

### 2.1 Maschinell ableitbare Beobachtungen

Das verpflichtende Finding-Ledger muss pro Finding mindestens fuehren:
`finding_id`, `first_seen_round`, `last_seen_round`, `class_id`, Locator,
`claim_id`/`invariant_id`, Kandidaten-Digest, betroffene Domain-Mitglieder,
Disposition, Fix-Digest, Closure-Receipt, Streitstatus und benoetigte
Autoritaet. Klassen- und Claim-IDs duerfen nicht nachtraeglich umgeschrieben
werden; Korrekturen sind neue, verknuepfte Ledger-Eintraege.

Daraus kann die Maschine vier fuer diese Runde verlangte Signale berechnen:

| Signal | Maschineller Tatbestand | Bewertete Diagnose |
|---|---|---|
| `RECURRENT_CLASS` | Dieselbe `class_id` erscheint nach behaupteter Closure erneut oder ueberlebt zwei Remediationsversuche; Locator und Instanz duerfen wechseln. | **Modell falsch**, wenn der gemeinsame Erzeugungsmechanismus unveraendert blieb. Die Anti-Loop-Regel verlangt dann Methodenwechsel statt eines weiteren Instanzfixes. |
| `NOVELTY_DRIFT` | In mehreren aufeinanderfolgenden Runden entstehen neue Klassen oder neue Domain-Familien, waehrend Claim bzw. Pruefdomain erweitert werden. | **Schnitt/Pruefdomain nicht geschlossen**; „Story zu breit“ ist eine Bewertung, nicht die rohe Zaehlung. Ein echter Modellwechsel kann ebenfalls berechtigt neue Klassen erzeugen. |
| `DISPUTED_BINDING` | Ein Finding ist als bestritten markiert und besitzt keinen gueltigen Adjudikationsentscheid. | **Adjudikation faellig**. Das Signal selbst ist mechanisch; die Sachentscheidung trifft der dritte Principal. |
| `AUTHORITY_GAP` | Eine offene Obligation verweist auf fehlenden Konzeptanker, zwei fachlich verschiedene Endzustaende oder eine Zusagenaenderung, fuer die nur PO-Autoritaet gilt. | **Ohne PO-Entscheid nicht erfuellbar**. Ob wirklich eine Grundentscheidung fehlt, bestaetigt der unabhaengige Reviewer; entscheiden darf nur der PO. |

Ein fuenftes Signal ist fuer das Belegmaterial notwendig:
`EXECUTION_SUBSTRATE_BLOCKED`. Es liegt vor, wenn die geschuldete Pruefung gar
keine Antwort erhalten hat. AG3-219s vier unterschiedlichen
`EVALUATION_TRANSPORT_FAILURE` sind keine vier Korpusbefunde. Die Maschine kann
Transportstatus, Backend und Versuchszahl zaehlen; die Bewertung muss trennen,
ob ein begrenzter Retry einer unbeantworteten Frage Erkenntnis verspricht oder
ob ein fremder Owner handeln muss. E2 des PO-Entscheids laesst die
Hub-Stabilisierung beim Hub-Projekt, nicht bei AK3.

### 2.2 Wer bewertet

Der letzte unabhaengige Reviewer der ausgeschöpften Runde schlaegt die
Diagnose mit Ledger-Referenzen vor. Der Implementierer darf zustimmen oder sie
begruendet bestreiten. Der Orchestrator darf nur deterministische Signale und
Policyfolgen erzeugen. Bei Streit entscheidet der bereits vereinbarte dritte
Principal. Der eskalierte Mensch entscheidet anschliessend ueber Disposition
und Budget, nicht rueckwirkend darueber, welche Fakten im Ledger standen.

Diese Trennung ist wesentlich: „fuenf neue Klassen“ ist messbar; „der
Storyschnitt ist zu breit“ ist eine kausale Aussage. Ohne die Trennung wuerde
ein plausibel formulierter Agent seine eigene Fortsetzung autorisieren.

Die Storyakten bestaetigen alle Diagnoseformen:

- AG3-214 belegt den Preis eines nicht persistierten Befunds und spaeter
  wiederkehrende Modellprobleme. Ein Finding „im Kopf“ kann weder Trend noch
  Adjudikation tragen.
- AG3-219 trennt ein falsches Evidenzmodell (abschreiben statt zeigen) von
  Transporttransienz und von dem spaeter gefundenen Cross-Partition-Modell.
- AG3-221 ist ein reiner `AUTHORITY_GAP`: Paarabdeckung und die kleinere
  Zusage „Partitionskonsistenz“ sind zwei fachlich verschiedene Endzustaende.
- AG3-220 enthaelt denselben Typ beim Widerspruch ueber direkte Agent-CLI-
  Aufrufe. Ein weiterer Reviewer kann ihn finden, aber nicht entscheiden.
- AG3-222 und AG3-223 zeigen erfuellungsunfaehige Vertraege an zwei
  unterschiedlichen Grenzen: dem LIGHT-Pruefer fehlt ein Baseline-Vertrag,
  dem Inkubator der mutierende Executor. Eine gute Eskalation nennt das
  fehlende Bauteil und seinen Owner, nicht nur `INCOMPLETE`.

## 3. Gewaehrte Runden und der Reviewvertrag

### 3.1 Kein Reset unter demselben Vertrag

`rounds_consumed` ist monoton. Die beim Start eingefrorene Grenze bleibt im
Vertrag sichtbar. Am Limit wird keine weitere Runde zugelassen, bis ein
menschlich signiertes **Grant-Record** vorliegt mit:

- Dossier-ID und Vertragsversion,
- Entscheider und Zeitpunkt,
- einer endlichen Zahl `additional_rounds`,
- Begruendung und gewaehlter E6-Hypothese/Methode,
- dem danach geltenden `authorized_through_round`.

Ohne ausdrueckliche Zahl gilt genau **eine** weitere Runde. Ein ausdrueckliches
Kontingent ist zulaessig, aber pro Grant hoechstens so gross wie das
projektweite Grundlimit. Danach wird erneut eskaliert. Der Zaehler wird nie
zurueckgesetzt und ein Agent darf weder Limit noch Grant schreiben. Damit ist
„weitermachen“ eine endliche menschliche Autorisierung und kein Bypass der
harten Grenze.

Ein Fix, eine vergroesserte Domain oder sogar der Ersatz eines
Loesungsmodells setzt den Zaehler ebenfalls **nicht** zurueck. Das waere die
einfachste Umgehung: vor dem Limit das Modell umbenennen und wieder bei null
beginnen. Das neue Modell muss gemaess gemeinsamer Grundlage erneut geprueft
werden, verbraucht aber das bestehende Budget bzw. einen menschlichen Grant.

### 3.2 Zusagenaenderung erzeugt einen neuen Vertrag

Aendert der PO Claim, Scope oder geschuldeten Abschlussbeleg materiell, endet
der bisherige Vertrag als `SUPERSEDED` oder `REPLAN_REQUIRED`, niemals als
`PASS`. Der Nachfolger erhaelt eine neue Vertragsversion, neue Kandidaten- und
Domain-Digests und einen eigenen Rundenzähler ab null. Er muss den Vorgaenger,
die exakte Vertragsdifferenz und **alle** bisherigen Findings referenzieren;
kein Finding verschwindet durch Re-Framing. Eine blosse Aenderung der
Remediationsmethode oder des Implementierungsmodells ist keine
Zusagenaenderung und berechtigt nicht zum Reset.

So ist der Neustart nicht aushebelbar: Nur die Instanz, die die Zusage aendern
darf, kann einen neuen Vertrag schaffen, und die alte offene Wahrheit bleibt
im Ledger sichtbar.

### 3.3 `REPLAN_REQUIRED` bleibt eigenstaendig

`ESCALATED_FOR_DECISION` ist ein wartender Kontrollzustand.
`REPLAN_REQUIRED` ist dagegen ein eigenstaendiges, menschlich bestaetigtes
Ergebnis: Der aktuelle Vertrag endet ohne `PASS`, weil Schnitt,
Loesungsmodell oder Zusage neu eingefroren werden muss. Das System darf es am
Rundenlimit empfehlen, aber nicht allein wegen des Zaehlers setzen.

Der Mensch hat am Eskalationspunkt damit mindestens diese Dispositionen:

- **final als `PASS` schliessen**, aber nur wenn kein bestaetigter Blocker und
  keine offene Beweisobliegenheit mehr existiert und eine weitere Vorlage
  nach dem bestehenden Abbruchkriterium keinen Erkenntnisgewinn braechte;
- **`REPLAN_REQUIRED`**, wenn der aktuelle Vertrag strukturell nicht
  schliessbar ist;
- **endliche weitere Runde(n) gewaehren**, wenn E6 einen konkreten
  Erkenntnisgewinn verspricht;
- **die Zusage aendern**, was den alten Vertrag ohne `PASS` beendet und einen
  neuen erzeugt.

Ein bestaetigter offener Blocker wird durch den Satz „final abschliessen“
nicht syntaktisch zu `PASS`. Ob der PO bestimmte Stop-Ship-Risiken ueberhaupt
akzeptieren darf, ist der in Runde 1 offengebliebene Dissens P3 und durch E1
nicht entschieden. Das Dossier muss einen solchen Fall offen ausweisen; es
darf diese Grundentscheidung nicht vorwegnehmen.

## 4. Ort und Aenderungsvorbehalt des Limits

Es gibt zunaechst **einen projektweiten Wert** mit dem Startwert **5** in der autoritativen
Pipeline-/Review-Policy, beispielsweise
`policy.max_independent_review_rounds`. Er wird beim Einfrieren als Wert plus
Policy-Digest in den Reviewvertrag kopiert. Eine spaetere Projektkonfigurations-
aenderung veraendert keinen laufenden Vertrag.

Der Wert lebt nicht in `story.md`, nicht in `status.yaml`, nicht in einer
Worker-Umgebungsvariable und nicht in einem Prompt. Schreibberechtigt ist nur
der menschliche Owner der Projektpolicy (im heutigen Verantwortungsmodell der
PO bzw. eine von ihm autorisierte Governance-Administration). Implementierer,
Reviewer und Orchestrator haben Leserecht.

Storytyp- oder storyspezifische Limits sind fuer den ersten Vertrag nicht
noetig und schaffen vor allem Umgehungsflaeche. Unterschiedlicher Bedarf wird
am echten Dossier durch Grants behandelt. Soll spaeter empirisch ein
Storytyp-Profil entstehen, bleibt es eine zentral gepflegte Policy-Map mit
demselben Owner; eine Story darf sich nie selbst hochstufen. Ein vor Runde 1
genehmigter Story-Sonderwert waere ein signierter Policy-Override und Teil des
eingefrorenen Vertrags, kein editierbares Storyfeld.

## 5. AG3-189: Was bei Runde 5 konkret vorgelegen haette

### 5.1 Beleggrenze

Die heutige Akte enthaelt kein atomares Rundenledger. Deshalb kann niemand
ehrlich behaupten, welche einzelnen Finding-IDs am exakten Ende von Runde 5
offen waren. Das ist nicht nur eine Fussnote: Nach der hier vorgeschlagenen
Norm waere das historische Dossier schon formal **nicht entscheidungsreif**
gewesen. Die folgende Rekonstruktion trennt daher damalige belegbare Signale
von spaeterer Bestaetigung.

### 5.2 Das entscheidungsreife R5-Dossier

**Gegenstand:** AG3-189 AC 3 und AC 4 behaupten einen einzigen
Interpreter-Owner fuer *alle* Einsprungpunkte und ein Gate, das jeden
PATH-`python`-Einsprung vor Landung findet. Das sind universelle Claims.

**Verlauf bis zur Kappung:** Der erste gelandete Checker in Commit
`b2d8e762` bestand aus 377 Zeilen und sechs Funktionen. Er auditierte im Kern
Python-AST-Aufrufe plus eine gebundelte Hook-Settings-Datei. Bereits die
unmittelbaren Folge-Builds belegten zweimal dieselbe Blindstelle der
Pruefmenge:

- Build 1233 fand Hook-Tests ausserhalb des lokal gewaehlten
  Unterverzeichnisses; der Commit `7415fddb` nennt selbst die Ursache:
  „meine Pruefmenge war enger als die der CI“.
- Build 1234 fand den ausgelassenen Contract-Test unter
  `tests/contract/governance`; `a0c81673` nennt es erneut „denselben blinden
  Fleck“.
- Das Sitzungsbriefing belegt fuer die ersten fuenf Runden denselben
  Fehlertyp an neuen Stellen eines handgeschriebenen Shell-Parsers. Damit ist
  spaetestens am R5-Punkt `RECURRENT_CLASS` erfuellt; ein sechster
  Einzelstellenfix waere nach der Anti-Loop-Regel unzulaessig.

**Primaere Diagnose — `MODEL_FAILURE`:** Der Checker suchte Instanzen in
jeweils bekannten Syntaxformen, besass aber kein abgeschlossenes Modell aller
produktiven Befehlsquellen und ihrer Konsumenten. Wiederkehrende Funde waren
nicht fuenf unabhaengige Fehler, sondern Widerlegungen derselben Closure-
Behauptung.

**Sekundaere Diagnose — `NOVELTY_DRIFT`:** Die Storyzusage war breiter als die
eingefrorene Domain. Ohne Inventar fuer Prozess-APIs, Default-Selektoren,
produktive Bundle-Versionen, Markdown-Fences unabhaengig vom Sprach-Tag,
Hook-/MCP-/CLI-Registrierungen und `-m`-Ziele konnte das Gate AC 3/4 nicht
vollstaendig beweisen. Welche dieser Flaechen bereits einen konkreten Defekt
enthielt, musste Runde 5 noch nicht wissen; dass sie nicht abschliessend
gezaehlt und belegt waren, genuegte als Blocker.

**Autoritaetsblock:** Es gab zwei fachlich verschiedene Wege: die breite
Zusage und ihre gesamte Domain durchziehen oder die Story schneiden bzw. die
Zusage verkleinern. Das durfte der Ausfuehrende nicht entscheiden. Genau diese
Wahl wurde spaeter dem PO vorgelegt; `status.yaml` dokumentiert den Entscheid
„vollstaendig aufraeumen“.

**Optionen und Preis am R5-Punkt:**

1. `PASS` waere unzulaessig gewesen: AC 3/4 hatten keinen
   Vollstaendigkeitsbeleg. Ein finaler Abschluss haette wissentlich das Risiko
   weiterer nackter Interpreterselektoren getragen.
2. `REPLAN_REQUIRED` haette die breite Zusage beendet und einen neuen,
   endlich inventarisierten Vertrag bzw. Storyschnitt verlangt. Preis:
   zusaetzlicher Planungs- und Reviewlauf; bis dahin kein Abschluss von
   AG3-189.
3. **Eine weitere Runde gewaehren**, aber nur fuer den Modellwechsel: vor
   erneutem Review die Domain als endliches Register einfrieren, die
   handgeschriebene Folge von Einzelfallparsern ersetzen, Checker-Coverage je
   Domain-Familie ausgeben und einen Negativtest pro Familie liefern. Die
   Abbruchbedingung dieser Runde waere ein nachrechenbarer Totalitaetsbeleg,
   nicht „kein neuer Treffer“.

**Empfehlung:** genau eine weitere Runde fuer diesen Modellwechsel; danach
erneute Eskalation, falls Domain oder Klassen weiter wachsen. Das Dossier
haette einem Menschen damit zur Entscheidung gereicht: nicht um den damals
noch unbekannten VektorDB-Default vorauszusagen, sondern um zu erkennen, dass
ein Abschluss den universellen Claim unbewiesen freigeben wuerde und dass
blosses Weiterflicken keinen Erkenntnisgewinn mehr versprach.

Die spaetere Entwicklung bestaetigt diese Diagnose hart: Der heutige Checker
ist auf 2.952 Zeilen und 46 Funktionen angewachsen, prueft unter anderem
produktive Skill-Bundle-Versionen und sprach-tag-unabhaengige Fences;
AG3-189s `status.yaml` nennt drei produktiv gebundene Bundles, zwei Aufrufe auf
nicht vorhandene Module und den falsch-gruenen `text`-Fence. Runde 13 fand
zusaetzlich den Default `command: str = "python"` in der VektorDB-Engine. Diese
spaeteren Befunde gehoeren **nicht** als vorgetaeuschtes Wissen in das
R5-Dossier. Sie zeigen aber, dass dessen R5-Diagnose „Domain nicht geschlossen,
Parsermodell falsch“ richtig und entscheidungsrelevant gewesen waere.

## 6. Was diese Norm durchlaesst und kostet

Der PO-Entscheid beseitigt den **automatischen** R13-Preis einer starren
Terminierung, nicht jedes Spaetfundrisiko. Entscheidet der Mensch bei R5 trotz
unvollstaendiger Domain auf Abschluss, kann ein damals unbekannter Defekt wie
der VektorDB-Default weiterhin ausgeliefert werden. Die Norm garantiert, dass
dieser Preis sichtbar und zurechenbar entschieden wird; sie garantiert nicht,
dass der Mensch immer weitere Runden gewaehren wird.

Weitere Kosten:

- Ein falsch klassifiziertes Ledger kann eine praezise, aber falsche Diagnose
  erzeugen. Unabhaengige Bewertung und Adjudikation reduzieren dieses Risiko,
  beseitigen es aber nicht.
- Der Mensch wird zum knappen Qualitaetsfaktor. Zu lange Dossiers oder
  routinemaessige Grants erzeugen genau das Abnicken, das die Norm verhindern
  soll. Deshalb der kleine Mindestgehalt und standardmaessig nur eine Runde.
- Ein einheitliches Projektlimit passt nicht fuer jede Story gleich gut. Die
  Alternative, frei editierbare Storylimits, waere jedoch keine Grenze.
- Wiederholte menschliche Grants koennen die Gesamtdauer weiterhin
  unbeschraenkt verlaengern. Das ist der bewusste Preis von E1: keine
  automatische Endlosschleife, aber menschliche Autoritaet, nach sichtbarer
  Diagnose weiter in Qualitaet zu investieren.
- Finding-Ledger, Domain-Receipts und unabhaengige Diagnose erzeugen
  Verfahrensaufwand. AG3-214s verlorener Befund und die fuer AG3-189 heute
  unmoegliche exakte R5-Rekonstruktion belegen, warum dieser Aufwand nicht
  dekorativ ist.

Die harte Grenze bleibt damit hart: Ohne neuen menschlichen Grant laeuft keine
Runde. Sie ist dennoch kein verkappter Terminierungsautomat: Ein bekannter
Blocker wird weder durch den Zaehler geheilt noch durch `REPLAN_REQUIRED`
umbenannt.
