# Proposal worker-b — Review als begrenzte Verifikationstransaktion

## Urteil

Eine Review ist weder ein einmaliger Maengelzettel noch eine unbegrenzte
Repo-Suche. Ihr Vertrag ist die Verifikation eines vor Runde 1 eingefrorenen
Satzes von Story-Zusagen gegen einen konkreten Kandidaten. Die Zusagen binden;
die Fundliste aus Runde 1 bindet nicht.

Der Reviewvertrag terminiert nach **hoechstens drei Runden** mit genau einem
von zwei Ergebnissen:

- `PASS`: alle geschuldeten Beweise liegen vor und kein blockierender Befund
  ist offen;
- `REPLAN_REQUIRED`: mindestens ein Blocker ist nach Runde 3 offen oder wird
  erst in Runde 3 gefunden. Die Story ist dann nicht fertig. Eine vierte Runde
  unter demselben Vertrag ist verboten; vor weiterer Implementierung muessen
  Vertrag, Schnitt oder Loesungsmodell neu beschlossen und erneut eingefroren
  werden.

Damit ist die Entscheidung fuer den Orchestrator mechanisch: **Nach Runde 3
ist eine weitere Reviewrunde Verschwendung.** Bei offenen Blockern ist der
naechste Pflichtschritt Re-Planung, nicht Review. Die Grenze folgt auch der
Anti-Loop-Regel aus `CLAUDE.md`: Nach zwei Remediationsversuchen wird nicht mit
derselben Methode weitergemacht.

Diese Norm nimmt einen echten Qualitaetsverlust in Kauf. Insbesondere waere
der in AG3-189 erst in Runde 13 gefundene Default
`command: str = "python"` unter ihr in dieser Reviewtransaktion nicht behoben
worden und haette ausgeliefert werden koennen. Eine Terminierungsnorm ohne
diesen Preis waere unehrlich.

## Der einzufrierende Vertrag

Vor Runde 1 muessen vier endliche Mengen feststehen:

1. **Claim-Register:** atomare, mit IDs versehene Story-Zusagen. Jeder Claim
   nennt Soll-Praedikat, Scope und Akzeptanzbeleg. „Die Interpreter-Isolation
   ist umgesetzt" ist zu unbestimmt; „kein Eintrag der Domain `D` publiziert
   oder verwendet einen nackten Interpreter-Aufruf" ist entscheidbar, wenn
   `D` definiert ist.
2. **Kandidaten-Baseline:** Digests aller unmittelbar geaenderten Artefakte.
3. **Beweisobliegenheiten:** je Claim die Tests, Gates, Realitaetsnachweise und
   Reviewachsen. Ein gruener Test ist dabei weiterhin nur der benannte Beleg,
   nicht selbst Normquelle (`META-ASSERTION-AUTHORITY` Regel 6).
4. **Globale Stop-Ship-Invarianten:** bereits normative, storyunabhaengige
   Verbote wie Datenverlust, Secret-Offenlegung, Error-Bypassing oder ein
   falsch-gruen behauptetes Pflichtgate. Der Reviewer darf diese anwenden,
   aber nicht waehrend der Review neue Stop-Ship-Klassen erfinden.

Eine universelle Zusage ist nur zulaessig, wenn ihr Quantifikationsbereich als
endliche, maschinell erzeugbare Domain eingefroren wird. Zur AG3-189-Zusage
„kein produktiver Weg ..." gehoeren daher nicht nur Treffer einer aktuellen
Suche, sondern die abschliessende Menge der produktiven Befehlsquellen,
Formate und Parserregeln. Fehlt eine solche Domain oder ein Totalitaetsbeleg,
ist der Reviewvertrag schon vor Runde 1 `REPLAN_REQUIRED`. Breite wird damit
nicht in Dateien oder Zeilen gemessen, sondern an Beweisbarkeit: **Kein
universeller Claim ohne endliche Domain und vollstaendigen Checker.**

## Die drei Runden

### Runde 1 — Discovery

Ein unabhaengiger Reviewer prueft alle Claims, Beweisobliegenheiten und
Stop-Ship-Invarianten. Er darf dafuer das ganze Repo lesen und selbst waehlen,
welchen Spuren er folgt. Alle belegten Befunde werden in ein versiegeltes
Ledger geschrieben. Runde 1 verspricht keine Vollstaendigkeit der Fundliste;
sie schafft den ersten pruefbaren Kandidatenbefund.

### Runde 2 — erste Closure

Geprueft werden das ganze Befundledger, die behaupteten Root-Cause-Fixes, die
vollstaendige Remediation-Differenz und erneut alle Story-Claims. Runde 2 darf
neue Befunde aufnehmen. Ein kritischer Spaetfund wird also nicht deshalb
abgewiesen, weil Runde 1 ihn uebersehen hat.

### Runde 3 — Abschluss oder Re-Planung

Runde 3 prueft wieder das kumulierte Ledger, die seit Runde 2 geaenderten
Artefakte und alle Claims. Findet sie nichts Substanzielles und sind alle
Beweise vorhanden, ist `PASS` erreicht. Jeder offene oder neue Blocker ergibt
`REPLAN_REQUIRED`. Es gibt keinen `PASS_WITH_KNOWN_BLOCKER` und keine vierte
Runde desselben Vertrags.

Re-Planung ist keine Umbenennung von Runde 4. Sie muss mindestens eines
aendern: den Story-Schnitt, ein fehlerhaftes Loesungsmodell oder eine
PO-seitig zu breite Zusage. Der neue Vertrag bekommt neue Digests und eine
neue Drei-Runden-Transaktion. Ein unveraenderter Vertrag darf nicht durch
Zaehler-Reset fortgesetzt werden.

## Welche Befunde blockieren?

Jeder Befund traegt ein nachpruefbares Tupel aus `locator`, beobachtetem
Verhalten, betroffenem `claim_id` oder `global_invariant_id`, Gegenbeleg und
Klasse. Daraus folgt die Bindung:

| Klasse | Entscheidungsregel | Wirkung |
|---|---|---|
| Direkter Gegenbeleg | Das beobachtete Verhalten macht das Soll-Praedikat eines Story-Claims falsch. | Blockiert in Runde 1 bis 3. |
| Globale Stop-Ship-Verletzung | Der Befund widerlegt eine vorab benannte projektweite Invariante. | Blockiert in Runde 1 bis 3, unabhaengig vom Story-Scope. |
| Neue Instanz einer geschlossenen Klasse | Der Locator liegt in der fuer diese Klasse eingefrorenen endlichen Domain. | Blockiert; die behauptete Klassen-Closure ist widerlegt. Einzelstellenflicken ist nicht ausreichend. |
| Neue Klasse an einem seit der vorigen Runde geaenderten Artefakt | Der Befund betrifft die Remediation-Differenz. | Blockiert; der Autor hat den Reviewgegenstand veraendert. In Runde 3 fuehrt dies zu `REPLAN_REQUIRED`. |
| Fremder Bestandsbefund | Kein Story-Claim und keine globale Invariante wird widerlegt; der Locator liegt nicht im Remediation-Diff. | Blockiert diese Story nicht, muss aber vor `PASS` einen dauerhaften Owner, eine Story-ID und einen Entscheidungszeitpunkt erhalten. |

Die drei im Briefing genannten Befundarten sind damit tragfaehig, sofern sie
nicht nur sprachlich klassifiziert werden. Entscheidend sind Claim-Referenz,
Digest und Domain-Mitgliedschaft. Ein neuer handgeschriebener Parser in der
Domain einer angeblich geschlossenen Parserklasse ist ein maschinell
feststellbarer Gegenbeleg. Wird dagegen ein ganzes Modell geloescht, liegt ein
neuer Kandidatendigest vor und das Ersatzmodell gehoert zwingend in die
naechste Closure-Runde.

## Wer entscheidet?

Der Orchestrator ist Registerfuehrer, nicht Schiedsrichter. Der Reviewer legt
das Befundtupel vor. Unbestrittene Tupel werden durch die obige Policy
verrechnet. Bestreitet der Implementierer die Zuordnung zu Claim, Invariante
oder Domain, entscheidet ein **zweiter unabhaengiger Principal**: weder Autor
noch erster Reviewer noch Council-Orchestrator, jeweils andere Session. Bis
zum Entscheid bleibt der Befund blockierend. Nur der PO darf eine Zusage
aendern, einen Stop-Ship-Vertrag neu setzen oder ein belegtes Restrisiko
akzeptieren. Das entspricht der vorhandenen Unabhaengigkeitsregel fuer
Projection-Receipts in FK-78 §78.10 und verhindert, dass der Orchestrator
Partei und Schiedsrichter zugleich ist.

Die beobachtete Regel „blockiert genau dann, wenn die Zusage der Story falsch
wird" ist daher im Kern richtig, aber unvollstaendig. Sie braucht erstens die
vorab benannten globalen Invarianten, zweitens einen unabhaengigen
Streitentscheid und drittens die Drei-Runden-Grenze. Ohne diese drei
Ergaenzungen bleibt sie entweder zu eng oder nicht terminierend.

## Anwendung auf die Sitzung vom 2026-08-05

Die Belege stuetzen die Klassifikation:

- **AG3-189:** AC 3 bis 5 versprechen einen einzigen Interpreterbegriff, ein
  maschinelles Gate und den Gegenbeweis zu PATH-`python`. Der Befund aus Runde
  13 (`backend/vectordb/engine.py`, Default `"python"`, durch einen Test als
  Erwartung festgeschrieben) ist ein direkter Gegenbeleg und zugleich ein
  Beleg, dass die behauptete Domain/Checker-Closure falsch war. Haette er
  Runde 2 erreicht, haette er zwingend blockiert. Seine Schwere darf aber die
  Rundengrenze nicht nachtraeglich aufheben.
- **AG3-189 Runde 15 / AG3-220:** Installationsform, Python-Untergrenze und
  Bundle-Floors haben doppelte Autoritaet; der zusaetzlich gefundene
  Widerspruch ueber direkte Agent-CLI-Aufrufe braucht eine PO-Entscheidung.
  Diese Befunde widerlegen nicht die Interpreter-Zusage. Ihre Auslagerung nach
  AG3-220 beziehungsweise zum PO ist unter der Norm richtig. Sie waeren keine
  Pflicht zur Fortsetzung von AG3-189.
- **AG3-214:** Die Ausgangszusage „genau ein Writer" macht die Befunde 1 und 2
  aus `story.md` unmittelbar blockierend. Das spaeter dokumentierte Schreiben
  produktiver Installer-Repositories ohne Writer-Lease (Decision Record
  `2026-08-04-ein-writer-ein-vertrag.md`, Runde 4) ist ebenfalls ein direkter
  Gegenbeleg. Dass Runde 7 die Serve-Grenze, die Readiness vor lokalen
  Credential-Wirkungen und die transaktionale Bindung von Domainwirkung und
  Claim-Finalisierung nachziehen musste, zeigt: Nach Runde 3 war nicht PASS,
  sondern Re-Planung des Writer-Modells faellig.
- **AG3-219 / AG3-221:** Die disjunkte Partitionierung sieht Widersprueche
  ueber Partitionsgrenzen nie, meldete aber Vollstaendigkeit. Das ist ein
  falsch-gruenes Gate und damit Stop-Ship. Da der Fund erst in AG3-219 Runde 4
  kam, haette die Reviewtransaktion nach dieser Norm vorher geendet. Nach
  Bekanntwerden waere er jedoch nicht als weitere AG3-219-Runde behandelt
  worden, sondern als neuer Vertrag mit der noch offenen PO-Wahl zwischen
  Paarabdeckung und kleinerer Zusage. Genau dieser Zustand ist in AG3-221
  ehrlich als `blocked` dokumentiert.
- Der mandatsfremde `scripts/`-Befund aus AG3-214 Runde 3 wurde korrekt als
  eigene Story AG3-218 persistiert. Das ist das Muster fuer einen
  nichtblockierenden Fremdbefund: nicht nebenbei reparieren, aber auch nicht
  verlieren.

## Bezifferte Kosten

Bei Anwendung ab Beginn der beobachteten Sitzung waere dieselbe
Reviewtransaktion nach Runde 3 beendet worden. Aus den vorhandenen Artefakten
sind **mindestens zehn spaeter erstmals benannte Befundcluster** erkennbar, die
in der jeweiligen Ursprungsstory nicht mehr behoben worden waeren:

1. AG3-189 R13: nackter `"python"`-Default in der VektorDB-Engine;
2. AG3-189 R15: doppelte Autoritaet zur Installationsform;
3. AG3-189 R15: doppelte Autoritaet zur Python-Untergrenze;
4. AG3-189 R15: doppelte beziehungsweise bereits gedriftete Bundle-Floors;
5. AG3-189 R15: unentschiedener Widerspruch ueber direkte Agent-CLI-Aufrufe;
6. AG3-214 R4: produktive Installer-Writes ausserhalb des aktiven Writers;
7. AG3-214 R7: Lease-Durchsetzung erst hinter statt an der Serve-Grenze;
8. AG3-214 R7: Writer-Readiness erst nach lokalen Credential-Wirkungen;
9. AG3-214 R7: Domainwirkung und Claim-Finalisierung nicht hinreichend
   transaktional beziehungsweise konvergent gebunden;
10. AG3-219 R4: Cross-Partition-Widersprueche fuer W3 unsichtbar trotz
    Vollstaendigkeitszusage.

Davon waeren Nr. 2 bis 5 und 10 mit Owner beziehungsweise PO-Blockade in neue
Vertraege gelangt. Nr. 6 bis 9 haetten AG3-214 in `REPLAN_REQUIRED` gehalten,
sobald sie spaeter bekannt wurden. **Nr. 1 ist der harte Preis:** Da er vor
dem Ende der drei Runden nicht gefunden wurde, haette die Regel seine
Auslieferung nicht verhindert.

Eine exakte Zuordnung aller im Briefing genannten „rund vierzig" Einzelfunde
ist aus den benannten `story.md`/`status.yaml` nicht entscheidbar: Sie
aggregieren spaete Runden teilweise zu einem Modellbefund und enthalten kein
vollstaendiges, atomisches Rundensledger. Eine exakte Zahl ueber zehn hinaus
waere erfunden. Gerade diese Belegluecke spricht dafuer, das Finding-Ledger im
Reviewvertrag verpflichtend zu machen.

## Zugriff und Entscheidungsfreiheit

„Frei ermitteln" endet erst an den Leserechten: Der Reviewer darf selbst
bestimmen, welche Dateien, Abhaengigkeiten und Gegenbeispiele er untersucht.
Das ist die Staerke des Harness-Zugriffs. „Frei entscheiden" begaenne dort, wo
er Claims, Rundenzahl, Stop-Ship-Klassen, Binding oder Risikodisposition selbst
aendert. Das darf er nicht. Er liefert Evidenz; die eingefrorene Policy
verrechnet sie; ein unabhaengiger Principal adjudiziert Streit; der PO aendert
den Vertrag. Damit bleibt das LLM Bewertungsfunktion, obwohl es seine
Ermittlungsstrategie frei waehlt.

## Was beim PO bleibt

Nicht aus dem Bestand ableitbar und deshalb vor Normierung vom PO zu
entscheiden sind:

- ob drei Runden als projektweite harte Grenze akzeptiert werden, samt dem
  belegten Risiko des ausgelieferten R13-Defekts;
- welche vorhandenen Invarianten in den abschliessenden globalen
  Stop-Ship-Katalog gehoeren;
- ob `REPLAN_REQUIRED` zwingend Story-Split, neuen Loesungsentwurf oder beides
  verlangt;
- im konkreten AG3-221-Fall: vollstaendige Paarabdeckung oder die kleinere,
  ehrliche Zusage „Partitionskonsistenz".

Nicht beim PO liegt die Einzelfallfrage, ob man „doch noch eine Runde"
versucht. Unter dieser Norm lautet die Antwort nach Runde 3 immer nein.
