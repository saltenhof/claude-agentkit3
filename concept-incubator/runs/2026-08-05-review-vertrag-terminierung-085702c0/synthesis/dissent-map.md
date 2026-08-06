# Dissent-Map — Runde 1

Lauf: `2026-08-05-review-vertrag-terminierung-085702c0`
Teilnehmer: `worker-a`, `worker-b` (unabhaengig, kein gegenseitiger Einblick)
Erstellt vom Council-Orchestrator nach Claim-Inventur.

## K — Konsens (beide Proposals, unabhaengig)

| ID | Aussage |
|---|---|
| K1 | Die **Befundliste** aus Runde 1 bindet **nicht**. Beide lehnen den Vertrag „behebe diese Liste, dann ist die Story fertig" ab. |
| K2 | Was bindet, ist der **vor Runde 1 eingefrorene Satz der Story-Zusagen** samt Beweisobliegenheiten. |
| K3 | Die beobachtete Orchestrator-Regel („blockiert genau dann, wenn der Befund die Zusage der Story falsch macht") ist **im Kern richtig, aber allein zu eng**. |
| K4 | Ergaenzung zu K3: Ein Befund blockiert auch, wenn er eine **vorab benannte projektweite Invariante** verletzt — auch wenn die Story sie in ihren Akzeptanzkriterien vergessen hat. |
| K5 | Eine **universelle Zusage** („kein produktiver Weg …") ist nur zulaessig, wenn ihr Universum **vor** der Review endlich und maschinell inventarisierbar ist und ein Vollstaendigkeitsbeleg existiert. |
| K6 | Zusagenbreite misst sich **nicht** in Dateien oder Zeilen, sondern in **Beweisbarkeit**. |
| K7 | Eine **neue Instanz einer angeblich geschlossenen Klasse** blockiert: sie widerlegt den behaupteten Vollstaendigkeitsbeleg. Nicht die Stelle flicken — Inventur oder Modell korrigieren. |
| K8 | Wird ein **Modell geloescht oder ersetzt**, ist der Gegenstand ein neuer und muss erneut geprueft werden. |
| K9 | Der Orchestrator darf **nicht Partei und Schiedsrichter** sein. Bei bestrittener Klassifikation entscheidet ein **dritter, unabhaengiger Principal** in anderer Session — weder Autor noch Reviewer. Bis dahin gilt fail-closed `blockiert`. |
| K10 | Nur der **PO** darf eine Zusage verkleinern oder tauschen. Eine PO-Verkleinerung ist **kein Fix**: sie re-framed den Vertrag und startet die Abschlussreview neu. |
| K11 | Ein **Nichtblocker** darf nur mit persistiertem Owner, Locator und Trigger/Termin aus dem Vertrag fallen. „Out of scope" allein ist keine Begruendung. |
| K12 | **Zugriff ist Freiheit der Ermittlung, nicht der Entscheidung** — damit vereinbar mit FK-78 §78.14. Der Reviewer liefert Evidenz; die eingefrorene Policy verrechnet sie. |
| K13 | Die Storyakten sind **kein atomares Rundenledger**. Eine exakte Gegenrechnung ueber alle Sitzungsbefunde ist daraus **nicht** ableitbar. Beide verweigern erfundene Zahlen und fordern ein verpflichtendes Finding-Ledger. |

## D — Dissens

### D1 — Terminierung. Der eigentliche Streitpunkt.

| | `worker-a` | `worker-b` |
|---|---|---|
| Mechanismus | **Keine feste Rundengrenze.** Terminiert, sobald fuenf Bedingungen alle falsch sind (kein offener Blocker; jeder Blockerfix unabhaengig verifiziert; Klasseninventuren und Abschlussbelege vollstaendig; kein ungeprueftes neues Modell / erweitertes Universum; alle Nichtblocker geroutet). | **Harte Grenze von drei Runden.** Ergebnis `PASS` oder `REPLAN_REQUIRED`. Eine vierte Runde unter demselben Vertrag ist **verboten**. |
| Umgang mit dem Spaetfund | Der VektorDB-Default blockiert, **gleich in welcher Runde**. | Der VektorDB-Default **waere ausgeliefert worden**. Ausdruecklich als Preis benannt. |
| Anti-Loop-Schutz | Ueber B3/B4: Klasseninventur ersetzt weiteres Einzelstellensuchen. | Ueber den Zaehler: nach Runde 3 ist Re-Planung Pflicht, nicht Review. |
| Selbstdiagnose fuer AG3-189 | Die Story war **nie terminierbar**, weil der Vollstaendigkeitsbeleg fuer die All-Aussage fehlte (B4 dauerhaft offen). | Nach Runde 3 waere `REPLAN_REQUIRED` gefallen — also dieselbe Diagnose, nur mit erzwungenem Halt. |

**Beobachtung des Orchestrators (Integrationsarbeit, keine Entscheidung):**
Die Positionen liegen naeher beieinander, als die Form vermuten laesst. **Beide
diagnostizieren denselben Ursprungsfehler** — AG3-189 startete die Review ohne
abgeschlossenes Universum. Sie unterscheiden sich darin, was operativ passiert,
wenn man das **mitten im Lauf** merkt: `a` haelt die Review offen, bis der Beleg
existiert; `b` erzwingt den Abbruch und einen neuen Vertrag.

Daraus ergibt sich eine **dritte, nicht vorgeschlagene Moeglichkeit**, die der
PO pruefen mag: keine Rundenzahl als Grenze, aber ein **erzwungener
Re-Plan-Trigger** — ein Blocker in einer *neuen Klasse* (nicht: neue Instanz)
belegt, dass Schnitt oder Loesungsmodell falsch sind, und loest Re-Planung statt
einer weiteren Runde aus. Das erhaelt `a`s „keine bekannte Widerlegung geht
raus" und `b`s Schutz gegen die Endlosschleife. **Diese Variante ist vom Council
nicht geprueft worden** und traegt daher keinen Konsens.

### D2 — Wo die globalen Invarianten herkommen

- `worker-a`: **B5 Stop-the-line** — ein aktuell ausnutzbarer Fail-open-,
  Safety-, Security- oder Datenverlustpfad blockiert den Kandidaten, **auch
  wenn die Story ihn nicht verursacht hat**. Der PO darf einen bestaetigten
  B5-Befund **nicht** als Risiko wegentscheiden.
- `worker-b`: Der Katalog der Stop-Ship-Invarianten wird **vorab** eingefroren;
  der Reviewer darf ihn anwenden, aber **waehrend der Review keine neuen
  Stop-Ship-Klassen erfinden**. Der PO darf ein belegtes Restrisiko akzeptieren.

Der Unterschied ist nicht redaktionell: `a` entzieht dem PO eine Befugnis, die
`b` ihm laesst.

### D3 — Bezifferte Kosten

| | `worker-a` | `worker-b` |
|---|---|---|
| Zaehlweise | 4 Befundgruppen / ≥7 lokalisierte Stellen bleiben ausserhalb der Story | ≥10 Befundcluster, spaeter erstmals benannt |
| Harter Preis | *keiner* — alle Zusagenwiderlegungen bleiben blockierend | **Nr. 1: der VektorDB-Default waere ausgeliefert worden** |
| Bedingte Kosten | AG3-221 je nach PO-Wahl | Nr. 6–9 haetten AG3-214 in `REPLAN_REQUIRED` gehalten |

Beide betonen: Eine Terminierungsnorm ohne benannten Preis waere unehrlich.

## P — Was beim PO liegt

| ID | Frage | Quelle |
|---|---|---|
| P1 | **Feste Rundengrenze ja/nein** — und falls ja, wird der Preis (ausgelieferter Spaetfund vom Typ VektorDB-Default) akzeptiert? | D1, beide |
| P2 | Welche vorhandenen Invarianten gehoeren in den **Stop-Ship-Katalog**? | D2, beide |
| P3 | Darf der PO einen bestaetigten Stop-Ship-Befund als **Restrisiko akzeptieren**? | D2, Dissens |
| P4 | Verlangt `REPLAN_REQUIRED` zwingend Story-Split, neuen Loesungsentwurf oder beides? | `worker-b` |
| P5 | **AG3-221**: vollstaendige Paarabdeckung oder die kleinere Zusage „Partitionskonsistenz"? | beide, unabhaengig |
| P6 | **Agentischer CLI-Widerspruch** (FK-45 gegen FK-43/Decision Record/FK-21) — Grundentscheidung. | beide, unabhaengig |

## PO-Entscheide (2026-08-05, nach Runde 1)

### E1 — zu P1: Rundenkappung ja, aber als Eskalation statt als Terminierung

> „Die Rundenanzahl muss hart gekappt sein. Das muss ein konfigurierbarer Wert
> sein, der wird wahrscheinlich irgendwo bei vier oder fuenf liegen. Danach muss
> das System an den Menschen eskalieren. Also nicht: es ist nach vier bis fuenf
> Runden automatisch geloest, sondern dann muss es dem Menschen vorgestellt
> werden mit der Aussage, warum es nicht geloest werden kann, was dem gerade im
> Wege steht, sodass der Mensch entscheiden kann, richtet er das an der Stelle
> dann final ab oder schickt er das in die naechste Runde."

**Der Entscheid waehlt keine der beiden Positionen, er loest den Dissens auf.**

- Gegen `worker-a`: Es gibt eine **harte, konfigurierbare Obergrenze** (Richtwert
  4-5). Eine unbegrenzte Rundenfolge ist ausgeschlossen.
- Gegen `worker-b`: Das Erreichen der Grenze ist **kein automatisches Ergebnis**
  — weder `PASS` noch `REPLAN_REQUIRED`. Es ist ein **Eskalationspunkt**, an dem
  ein Mensch entscheidet: abschliessen, oder weitere Runde(n) gewaehren.
- Damit entfaellt der von `worker-b` benannte harte Preis: Ein Spaetfund vom Typ
  des VektorDB-Defaults wird nicht durch einen Zaehler ausgeliefert, sondern
  einem Menschen vorgelegt.

**Neue Pflicht, die aus dem Entscheid folgt:** Die Eskalation traegt Inhalt, nicht
nur den Zaehlerstand. Sie muss sagen, **warum** nicht geloest werden konnte und
**was im Wege steht** — sonst kann der Mensch nicht entscheiden, sondern nur
abnicken.

Offen und Gegenstand von Runde 2 (siehe unten).

### E2 — zu Frage 2 (Hub-Stabilitaet, ausserhalb des Council-Scopes)

> „Es ist nicht Aufgabe eines Clients, dafuer zu sorgen, dass der Hub immer
> online ist, sondern es ist Aufgabe des Hubs, dafuer zu sorgen, dass er immer
> online ist."

AK3 ist **Nutzer** des Hubs. In AK3 wird nichts vorgesehen, um den Hub am Leben
zu halten. Stabilisierung — bis hin zu ueberwachenden Zusatzdiensten — gehoert
in das Hub-Projekt. Hier nur als Kontext festgehalten, weil er die
Transportfrage des Bewertungsvertrags beruehrt.

## Offener Beleg-Mangel

Beide Proposals benennen unabhaengig dieselbe Luecke: Es existiert **kein
atomares Rundenledger** der Sitzung vom 2026-08-05. Die Storyakten aggregieren
spaete Runden teilweise zu einem Modellbefund. Eine exakte Zuordnung der „rund
vierzig" Einzelfunde ist daraus nicht moeglich — beide lehnen es ab, eine Zahl
zu erfinden.

Das ist selbst ein Befund: **Die Norm, die hier entsteht, braucht ein
verpflichtendes Finding-Ledger, sonst ist sie im Nachhinein nicht pruefbar.**
Beide fordern es unabhaengig voneinander.
