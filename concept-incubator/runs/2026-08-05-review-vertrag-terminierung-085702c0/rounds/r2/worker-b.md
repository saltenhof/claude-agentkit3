# Runde 2 worker-b — Die Eskalation als Entscheidungsvertrag

## Entscheidung

Die harte Rundengrenze beendet die autonome Review, nicht die Sache. Spaetestens
beim Erreichen des eingefrorenen Limits entsteht `HUMAN_DECISION_REQUIRED`.
Dieses Ergebnis ist nur dann zulaessig, wenn ein **Entscheidungsdossier** die
offenen Gegenbelege auf eine oder mehrere benannte Blockadeursachen
zurueckfuehrt und die Folgen jeder zulaessigen Entscheidung ausweist.

Die Eskalation ist entscheidungsreif, wenn der Mensch ohne weitere
Repo-Ermittlung beantworten kann:

1. Welche eingefrorene Zusage oder Beweisobliegenheit ist noch falsch oder
   unbelegt?
2. Warum kann der laufende Vertrag sie nicht durch blosses Fortsetzen
   verlaesslich schliessen?
3. Was bewirken Abschluss, ein endliches Zusatzkontingent und Re-Planung
   jeweils — einschliesslich des bekannten Restrisikos?

Kann das Dossier eine dieser Fragen nicht beantworten, ist das selbst sein
primaerer Blocker (`DIAGNOSIS_INCOMPLETE`). Es darf dann nicht "fuenf Runden
erreicht" als Ersatzdiagnose liefern und darf keinen Abschluss empfehlen.

## Pruefbarer Mindestgehalt

Das Dossier braucht genau sechs Pflichtteile. Mehr Prosa ist optional.

| ID | Pflichtinhalt | Mechanische Mindestpruefung |
|---|---|---|
| E1 | **Eingefrorener Gegenstand:** `contract_id`, Revision, Claim-/Invarianten-IDs, Kandidatendigest, geschuldete Belege, effektives Limit, verbrauchte Runden | Alle Referenzen existieren; Digest und Zaehler stimmen mit Run und Ledger ueberein. |
| E2 | **Offener Restbestand:** je offener Finding-ID Locator, Gegenbeleg, betroffener Claim/Beleg, Klasse, erste/letzte Runde, heutige Disposition | Kein freier Sammeltext; jeder offene Eintrag ist zu Vertrag oder vorab geltender Projektregel gebunden. |
| E3 | **Blockadediagnose:** mindestens ein Diagnosecode aus dem folgenden Katalog, die ihn tragenden Ledger-Eintraege und ein widerlegbares Kriterium dafuer, wann die Diagnose nicht mehr gilt | Code, Evidenzreferenzen und verantwortlicher Diagnose-Principal sind vorhanden. |
| E4 | **Nichtwissen:** ungepruefte Teile des eingefrorenen Universums, fehlende Realitaetsnachweise und durch Kandidatenaenderungen neu entstandene Pruefflaechen | Keine behauptete Vollstaendigkeit ohne endliche Domain und Beleg. |
| E5 | **Entscheidungsmatrix:** `FINALIZE`, `EXTEND(n)` und `REPLAN_REQUIRED`, bei Streit zusaetzlich `ADJUDICATE`; jeweils unmittelbare Wirkung, Erfolgsbedingung und verbleibendes Risiko; unzulaessige Optionen sind mit der sperrenden Policy benannt | Jede Option ist ausfuehrbar oder explizit gesperrt; `n` ist endlich. |
| E6 | **Autorisierungsfeld:** Entscheider, Entscheidung, Begruendung, Zeitpunkt, neue Obergrenze beziehungsweise neue Vertragsrevision | Keine Fortsetzung ohne signierte menschliche Entscheidung; kein Freitext wie "bis fertig". |

Damit ist Entscheidungsreife nicht mit Vollstaendigkeit verwechselt. Das
Dossier muss nicht alle noch unbekannten Defekte vorhersagen. Es muss aber die
Grenze des eigenen Wissens so genau ausweisen, dass `FINALIZE` als bewusste
Disposition und nicht als vermeintliches `PASS` erkennbar ist.

**Durchfallendes Gegenbeispiel:**

> Limit 5/5 erreicht. Drei ERRORs sind offen. Das Review findet weiterhin neue
> Probleme. Empfehlung: zwei weitere Runden.

Es fehlen Claim-Bindung, Gegenbelege, Ursache, ungepruefte Domain,
Erfolgsbedingung und die Konsequenz eines Abschlusses. Der Mensch kann nur der
Empfehlung folgen oder sie ablehnen; er kann nicht entscheiden.

## Blockadediagnose

### Vier Codes statt einer erfundenen Ein-Ursachen-Erklaerung

Mehrere Codes duerfen gleichzeitig gelten. Das ist bei AG3-189 wichtig: Ein
falsches Suchmodell und eine zu breite, nicht inventarisierte Zusage koennen
sich gegenseitig verursachen.

| Code | Feststellbares Signal | Diagnose und Konsequenz |
|---|---|---|
| `MODEL_NOT_CLOSED` | Dieselbe akzeptierte Defektklasse erscheint nach behaupteter Klassen-Closure erneut; insbesondere nach zwei Remediationsversuchen mit demselben Modell. | Einzelstellenfix oder Checker-Modell ist falsch. Weitere Runde nur nach Modellwechsel beziehungsweise vollstaendiger Klasseninventur. |
| `SCOPE_NOT_FINITE` | Neue Defektklassen erscheinen wiederholt in zuvor nicht inventarisierten Teilmengen; das Universum eines All-Claims waechst waehrend der Review oder sein Vollstaendigkeitsbeleg fehlt. | Der Schnitt ist nicht beweisbar eingefroren. Re-Planung, Story-Split oder PO-seitige Zusagenpraezisierung ist vorrangig. |
| `CLASSIFICATION_DISPUTED` | Reviewer und Verfasser/Orchestrator haben fuer denselben Finding-Digest widersprechende, signierte Zuordnungen zu Claim, Invariante, Klasse oder Blocking-Wirkung. | Keine weitere Reparaturrunde vor Adjudikation. Der dritte unabhaengige Principal entscheidet; bis dahin blockiert der Befund. |
| `PRODUCT_DECISION_MISSING` | Eine Zusage ist nur durch die Wahl zwischen fachlich verschiedenen Endzustaenden oder durch einen fehlenden Konzeptanker erfuellbar. | Nur der PO setzt den Pfosten beziehungsweise aendert die Zusage. Implementierer und Reviewer duerfen keine Variante heimlich waehlen. |

AG3-219 zeigt, warum ein Dossier mehrere Codes braucht. Der Zitatvertrag war
ein falsches Modell; nach dessen Ersatz wurden Transportfehler sichtbar; die
R4-Review fand mit der disjunkten Partitionierung nochmals eine neue Klasse.
AG3-221 macht daraus ehrlich `PRODUCT_DECISION_MISSING`: paar-deckende
Scope-Set-Konsistenz bezahlen oder die Zusage auf Partitionskonsistenz
verkleinern. AG3-220 enthaelt denselben Code fuer den Widerspruch, ob Agents
die CLI direkt aufrufen duerfen. AG3-222 und AG3-223 belegen dagegen
`MODEL_NOT_CLOSED` auf Verfahrensebene: Ein LIGHT-Vertrag ist nicht pruefbar,
beziehungsweise ein normierter Lifecycle besitzt keinen Executor. Mehr
Reviewrunden stellen das fehlende Werkzeug nicht her.

Fuer `CLASSIFICATION_DISPUTED` enthalten die benannten Storyakten keinen
atomaren, beidseitig signierten Streitfall. Der Code folgt daher aus dem
Konsens K9, nicht aus einer nachtraeglich erfundenen Zuordnung zu einer dieser
Storys.

### Was die Maschine kann — und was bewertet werden muss

Mit dem von beiden Runde-1-Proposals geforderten Finding-Ledger kann die
Maschine folgende Tatsachen ableiten:

- Wiederkehr derselben `class_id`, Neuheit einer `class_id` und Verteilung
  ueber Runden;
- Claim-/Invariantenreferenz, offene Beweise, Locator und Zugehoerigkeit zum
  Remediation-Diff;
- Erweiterung der eingefrorenen Domain oder Kandidaten-Baseline;
- vorhandene Gegenklassifikationen und eine fehlende Adjudikation;
- eine bereits registrierte PO-Abhaengigkeit.

Nicht rein maschinell ableitbar ist, ob zwei Symptome wirklich dieselbe
Ursache haben, ob eine Klasseninventur fachlich vollstaendig ist, ob die
Zusagenbreite statt nur ein schlechter Fix das Problem erzeugt und ob zwei
Loesungswege verschiedene Produktzustaende darstellen. Insbesondere darf ein
LLM nicht seine eigene `class_id` zur Wahrheit machen.

Deshalb gibt es zwei Stufen:

1. Der deterministische Aggregator erzeugt aus Ledger und Vertragsdiff die
   Signale und einen vorlaeufigen Diagnosecode.
2. Ein unabhaengiger **Diagnose-Principal** — nicht Implementierer und nicht
   der beanstandete Reviewer — bestaetigt oder widerlegt die Kausalzuordnung
   mit Evidenz. Bei Widerspruch greift K9: ein dritter Principal adjudiziert.
   Der PO diagnostiziert nicht den Code; er entscheidet nur dort, wo Ziel,
   Zusage oder Restrisiko in seine Autoritaet fallen.

Der Orchestrator kompiliert das Dossier. Er darf weder die Diagnose erfinden
noch durch Weglassen einer Gegenposition entscheiden.

## Vertrag nach einer menschlich gewaehrten Fortsetzung

Der Zaehler wird **nie zurueckgesetzt**. Das Dossier und der Run fuehren
mindestens:

- `rounds_consumed_total` fuer die gesamte Story;
- `contract_revision` fuer den eingefrorenen Zusagensatz;
- `authorization_epoch` und `authorized_through_round` fuer jede menschliche
  Gewaehrung.

`EXTEND(n)` gewaehrt ein **exaktes endliches Kontingent**, standardmaessig eine
Runde. Der Mensch darf mehrere Runden gewaehren, muss `n` aber nennen und
die erwartete Closure-Wirkung beschreiben. "Weiter bis PASS" oder "so viele
wie noetig" ist ungueltig. Am neuen Ceiling entsteht erneut
`HUMAN_DECISION_REQUIRED`, sofern vorher kein `PASS` erreicht wurde. So kann
der Ausfuehrende die Grenze nicht aushebeln; ein Mensch kann weitere Chancen
bewusst und wiederholt autorisieren, wie es der PO-Entscheid verlangt.

Bleibt die Zusage gleich, bleiben auch Contract-ID, Domain und Ledger erhalten;
die neue Kandidaten-Baseline wird als weitere Revision verkettet. Aendert der
Mensch die Zusage, entsteht gemaess K10 ein **neuer Vertragsstand** mit neu
eingefrorenen Claims, Domain, Beweisen und Kandidatendigest. Alte Findings
werden auf die neue Revision abgebildet oder begruendet geroutet, nie geloescht.
Auch dann gibt es keinen stillen Zaehlerreset und kein automatisch neues
Projektkontingent: Der menschliche Re-Plan-Entscheid nennt zugleich das erste
endliche Reviewkontingent des neuen Vertrags. `rounds_consumed_total` bleibt
sichtbar.

`REPLAN_REQUIRED` ist damit **kein autonomes Schwestergebnis** der
Rundengrenze. An der Grenze lautet das Systemergebnis
`HUMAN_DECISION_REQUIRED`; `REPLAN_REQUIRED` ist eine diagnostisch begruendete
Disposition, die der Mensch waehlen kann. Danach ist die alte Revision
geschlossen, aber die Story nicht fertig. Ein technisch ungueltiger Vertrag
kann schon vor Erreichen des Limits eskalieren — die Grenze ist das spaeteste,
nicht das frueheste Eskalationsereignis.

`FINALIZE` darf einen fehlgeschlagenen Beleg nicht in `PASS` umetikettieren.
Es ist ein eigener, auditierbarer menschlicher Abschluss mit dem im Dossier
benannten Restbestand. Ob ein bestimmter Stop-Ship-Befund ueberhaupt menschlich
akzeptierbar ist, entscheiden der noch zu normierende Stop-Ship-Katalog und
die dafuer gesetzte Autoritaet; der offene Dissens D2 wird hier nicht
stillschweigend entschieden. Fehlt dem Entscheider die Autoritaet, weist das
System `FINALIZE` zurueck.

## Ort und Aenderungsvorbehalt des Limits

Das Basislimit lebt in einer **versionierten projektweiten Review-Policy** mit
einem benannten Governance-Owner. Der eingefrorene Reviewvertrag kopiert
Policy-Revision und effektiven Wert; eine spaetere Policy-Aenderung wirkt nur
auf neu eingefrorene Vertraege. Umgebungsvariable, CLI-Flag, `story.md`,
`status.yaml` oder ein vom Ausfuehrenden beschreibbares Run-Feld sind keine
zulaessigen Owner.

Es gibt einen projektweiten Default — nach PO-Richtwert zunaechst 5 — und
optional projektweit benannte Profile je Storytyp, falls deren Unterschiede
empirisch belegt sind. Der Storytyp waehlt nur ein bereits autorisiertes
Profil; er setzt keinen freien Wert. Eine storyspezifische Abweichung ist
keine Konfiguration, sondern eine menschliche Ausnahmeentscheidung im
Eskalationsrecord. Aendern duerfen Policy-Werte nur PO oder ein von ihm
ausdruecklich mandatierter Governance-Owner, niemals Implementierer,
Reviewer, Orchestrator oder laufender Agent der betroffenen Story.

## AG3-189 — konkretes Dossier bei Runde 5

Die Akten besitzen kein atomares Rundenledger. Deshalb ist nicht belegbar,
welcher Einzelfund exakt vor oder nach Runde 5 erstmals vorlag. Der frueheste
persistierte Eskalationsstand (`status.yaml`, Commit `3098217c`) nennt jedoch
den damaligen Entscheidungsanlass konkret. Eine ehrliche Runde-5-Eskalation
haette auf dieser belegbaren Basis so ausgesehen:

### E1/E2 — Gegenstand und Restbestand

- Betroffene Zusagen: AC 3 bis 5 — genau ein Interpreter-Owner, maschinelles
  Auffallen jedes PATH-`python`-Einsprungpunkts und ein Nachweis mit
  vergiftetem PATH.
- Bekannte Gegenbelege: drei produktiv gebundene Bundles
  (`create-userstory-core`, `execute-userstory-core`,
  `concept-incubation-core`) publizierten nackte `python`-Aufrufe; zwei davon
  zielten zudem auf nicht existente Module.
- Beweisdefekt: Ausfuehrbare Befehle in einem `text`-Fence entgingen dem Gate,
  obwohl dieses behauptete, alle Kommandos zu auditieren. Damit war nicht nur
  ein Treffer offen, sondern der Vollstaendigkeitsbeleg falsch-gruen.
- Nichtwissen: Es existierte keine eingefrorene, vollstaendige Domain aller
  produktiven Befehlsquellen, Formate, Parserregeln und Runtime-Defaults.
  Die Akte berichtet: Jede Gate-Erweiterung fand die naechste Fundstelle.

### E3 — Diagnose

Primaer `MODEL_NOT_CLOSED`: Wiederholtes Erweitern eines handgeschriebenen
Such-/Parsermodells fand neue Instanzen derselben Interpreterklasse; der
`text`-Fence widerlegte seine behauptete Closure. Sekundaer
`SCOPE_NOT_FINITE`: "kein produktiver Weg" war ein All-Claim, dessen Universum
erst waehrend der Review entdeckt wurde. Der laufende Vertrag konnte daher
weder sagen, wie viele Quellen noch fehlten, noch wann eine weitere
Einzelstellenrunde genuegte.

### E5 — echte Wahl fuer den Menschen

| Wahl | Wirkung bei Runde 5 | Bekannter Preis / Erfolgsbedingung |
|---|---|---|
| `FINALIZE` | Kein `PASS`, sondern menschlicher Abschluss mit Restrisiko. | Die drei Bundle-Gegenbelege und ein falsch-gruenes Pflichtgate widersprachen AC 3/4. Ohne zulaessige Aenderung der Zusage beziehungsweise hinreichende Risikoautoritaet war diese Wahl gesperrt. Zudem blieb der spaetere VektorDB-Default als unbekannter Gegenfall moeglich. |
| `EXTEND(1)` oder anderes endliches `n` | Weitere Review nur mit dem Auftrag, zuerst Domain und Checker-Modell zu schliessen, nicht weitere Stellen zu flicken. | Erfolg erst bei endlicher Inventur aller Befehlsquellen plus Negativbelegen fuer `text`-Fences, tote Modulziele und Runtime-Defaults; danach Abschlussreview auf neuem Kandidatendigest. |
| `REPLAN_REQUIRED` | Alten Vertrag schliessen; All-Claim in eine endliche Domain ueberfuehren oder Story entlang beweisbarer Teilmengen schneiden. | Neue Vertragsrevision und explizites Kontingent noetig; kein bekannter Befund darf beim Schnitt verlorengehen. |

Das haette zur Entscheidung gereicht: Nicht die Zahl der offenen Stellen,
sondern die fehlende Klassen-Closure war im Weg. Der Mensch haette gezielt
Re-Planung oder ein endliches Kontingent zum Bau der Inventur gewaehren
koennen. Der tatsaechliche damalige PO-Entscheid "so viele Runden wie noetig"
waere unter dieser Norm als unbeschraenkt zurueckgewiesen und zur Angabe von
`n` und Erfolgsbedingung zurueckgegeben worden.

Das Dossier haette den erst in R13 gefundenen
`backend/vectordb/engine.py`-Default nicht hellsehen koennen. Es haette aber
gerade **nicht** behauptet, die Domain sei geschlossen. Waere der Mensch bei
R5 trotz dieses benannten Nichtwissens ausgestiegen, waere der Default wie
unter meiner Runde-1-Norm ausgeliefert worden — nun jedoch als menschlich
disponiertes Restrisiko, nicht als automatische Wirkung des Zaehlers. Bei
einem gewaehrten Kontingent haette R13 nach erneuter Eskalation weiterhin
erreicht werden koennen.

## Kosten und verbleibende Luecke

Diese Norm garantiert Terminierung der **autonomen** Schleife, nicht das Ende
menschlicher Entscheidungen und nicht Fehlerfreiheit.

- Ein Mensch kann trotz eines entscheidungsreifen Dossiers `FINALIZE` waehlen;
  dann koennen unbekannte Spaetfunde wie der VektorDB-Default ausgeliefert
  werden. Die Norm macht diesen Preis sichtbar, sie verbietet ihn nicht
  pauschal.
- Ein falscher Diagnose-Principal kann eine breite Domain fuer geschlossen
  halten oder zwei Symptome derselben Klasse falsch trennen. Unabhaengigkeit
  reduziert dieses Risiko, beseitigt es nicht.
- Wiederholte endliche Gewaehrungen koennen in Summe sehr viele Runden
  ergeben. Das ist keine automatische Endlosschleife mehr, aber weiterhin
  teuer; jede Verlaengerung verbraucht menschliche Aufmerksamkeit.
- Der Ledger-, Klassifikations- und Dossierzwang kostet Arbeit. Ohne ihn waere
  die Selbstdiagnose jedoch nicht reproduzierbar; AG3-189 zeigt genau diese
  heutige Belegluecke.
- Ein projektweiter Default von 5 passt nicht notwendig zu jedem Storytyp.
  Profile und Ausnahmen schaffen Passung, zugleich aber Governance-Aufwand
  und das Risiko einer schleichenden Aufweichung. Deshalb sind sie versioniert,
  benannt und dem Ausfuehrenden entzogen.

Der nicht eliminierbare Rest ist damit klar: Ein Reviewvertrag kann bekannte
Widerlegungen, fehlende Beweise und die Form seines Nichtwissens vorlegen. Er
kann nicht beweisen, dass ausserhalb seiner endlichen Pruefmenge kein weiterer
Defekt existiert, und er kann dem Menschen die Produktentscheidung nicht
abnehmen.
