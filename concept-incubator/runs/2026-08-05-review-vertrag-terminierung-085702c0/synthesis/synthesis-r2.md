# Synthese Runde 2 — Operationalisierung des PO-Entscheids E1

Lauf: `2026-08-05-review-vertrag-terminierung-085702c0`
Grundlage: `rounds/r2/worker-a.md`, `rounds/r2/worker-b.md` (unabhaengig
erstellt, gegenseitig ungelesen), aufbauend auf den 13 Konsenspunkten aus
`synthesis/dissent-map.md`.

## Ergebnis

**Die Runde ist konvergiert.** Beide Teilnehmer kommen unabhaengig auf
dieselbe Struktur, teilweise auf dieselben Zahlen und auf dasselbe
durchfallende Gegenbeispiel. Der Dissens aus Runde 1 ist geschlossen; die
Reste sind ergaenzend, nicht widersprechend.

## K2 — Konsens der zweiten Runde

| ID | Aussage |
|---|---|
| K2-1 | Das Erreichen der Grenze erzeugt einen **wartenden Kontrollzustand**, kein Reviewurteil: `ESCALATED_FOR_DECISION` (a) / `HUMAN_DECISION_REQUIRED` (b). Der Zaehler sagt weder `PASS` noch `REPLAN_REQUIRED`. |
| K2-2 | Die Eskalation ist nur zulaessig als **Entscheidungsdossier mit genau sechs Pflichtteilen**. Beide leiten dieselben sechs Rubriken her: eingefrorener Gegenstand, offener Restbestand je Finding, Verlauf/Nichtwissen, Blockadediagnose, Entscheidungsmatrix mit Preis, Autorisierung bzw. naechster Erkenntnisschritt. |
| K2-3 | **Eine blosse Anzahl ist ungueltig.** Jeder offene Punkt braucht Finding-ID, Locator, Gegenfall, Claim-/Invariantenbindung, Klasse und fehlenden Abschlussbeleg. |
| K2-4 | Entscheidungsreif heisst: Der Mensch beantwortet **ohne erneute Repo-Ermittlung** — welche Zusage ist offen, warum hat die bisherige Methode sie nicht geschlossen, was bewirkt jede zulaessige Entscheidung. |
| K2-5 | Beide liefern **dasselbe durchfallende Gegenbeispiel** („Limit 5/5, drei Findings offen, Empfehlung zwei weitere Runden") und dieselbe Begruendung: ein Statusbericht, bei dem der Mensch nur glauben oder ablehnen kann. |
| K2-6 | Die Diagnose entsteht **zweistufig**: deterministische Signale aus dem Finding-Ledger, davon getrennt die bewertete Kausalaussage durch einen unabhaengigen Diagnose-Principal. Ein LLM darf seine eigene `class_id` nicht zur Wahrheit machen. |
| K2-7 | Vier Diagnoseklassen, deckungsgleich benannt: **Modell nicht geschlossen** (`RECURRENT_CLASS` / `MODEL_NOT_CLOSED`), **Universum nicht endlich** (`NOVELTY_DRIFT` / `SCOPE_NOT_FINITE`), **Einordnung bestritten** (`DISPUTED_BINDING` / `CLASSIFICATION_DISPUTED`), **Produktentscheid fehlt** (`AUTHORITY_GAP` / `PRODUCT_DECISION_MISSING`). Mehrere duerfen gleichzeitig gelten. |
| K2-8 | Der Rundenzaehler wird **niemals zurueckgesetzt**. Monoton ueber die gesamte Story. |
| K2-9 | Ein Modellwechsel, ein Fix oder eine vergroesserte Domain setzt den Zaehler **nicht** zurueck. Das waere die einfachste Umgehung: vor dem Limit umbenennen und bei null beginnen. |
| K2-10 | `EXTEND(n)` verlangt ein **endliches, benanntes `n`**; Default ist **eine** Runde. „Bis fertig" oder „so viele wie noetig" ist ungueltig. Am neuen Ceiling wird erneut eskaliert. |
| K2-11 | Eine **Zusagenaenderung erzeugt einen neuen Vertrag** mit neuen Digests und eigener Revision. Alle bisherigen Findings werden uebertragen oder begruendet geroutet — kein Finding verschwindet durch Re-Framing. Der bisherige Vertrag endet nie als `PASS`. |
| K2-12 | Das Limit lebt in einer **versionierten, projektweiten Policy mit benanntem Governance-Owner**. Nicht in `story.md`, nicht in `status.yaml`, nicht in Umgebungsvariable, CLI-Flag oder Prompt. Schreibrecht nur PO bzw. mandatierte Governance; Implementierer, Reviewer, Orchestrator und laufender Agent haben Leserecht. |
| K2-13 | Beide nennen unabhaengig den **Startwert 5**. |
| K2-14 | Der Vertrag kopiert Wert **und Policy-Revision** beim Einfrieren; eine spaetere Policy-Aenderung wirkt nicht auf laufende Vertraege. |
| K2-15 | `FINALIZE` darf einen fehlgeschlagenen Beleg **nicht in `PASS` umetikettieren**. Es ist ein eigener, auditierbarer menschlicher Abschluss mit benanntem Restbestand. |
| K2-16 | Ob der PO einen bestaetigten Stop-Ship-Befund als Restrisiko akzeptieren darf, wird hier **ausdruecklich nicht entschieden** (offener Dissens D2/P3 aus Runde 1). Beide weigern sich, die Frage vorwegzunehmen. |
| K2-17 | Fuer AG3-189 bei Runde 5 kommen beide auf **dieselbe Diagnose**: primaer das nicht geschlossene Parser-/Suchmodell, sekundaer der All-Claim ohne inventarisiertes Universum. Beide halten `PASS` fuer unzulaessig und empfehlen eine gewaehrte Runde **fuer den Modellwechsel**, nicht fuer weiteres Flicken. |
| K2-18 | Beide stellen erneut fest: **es gibt kein atomares Rundenledger**, deshalb ist die exakte R5-Rekonstruktion unmoeglich — und genau das belegt, warum das Ledger verpflichtend werden muss. |

## E — Ergaenzungen, jeweils nur von einem benannt

| ID | Von | Aussage | Bewertung des Orchestrators |
|---|---|---|---|
| E-1 | `worker-a` | Fuenftes Signal **`EXECUTION_SUBSTRATE_BLOCKED`**: die geschuldete Pruefung hat gar keine Antwort erhalten. AG3-219s vier `EVALUATION_TRANSPORT_FAILURE` sind keine vier Korpusbefunde. | Deckt einen an diesem Tag real aufgetretenen Fall ab, den die vier Klassen aus K2-7 nicht erfassen. Ergaenzend, nicht strittig. |
| E-2 | `worker-b` | **`DIAGNOSIS_INCOMPLETE`** als eigener Blocker: Kann das Dossier seine eigenen drei Fragen nicht beantworten, ist das sein primaerer Blocker; es darf dann keinen Abschluss empfehlen. | `worker-a` hat dieselbe Wirkung ueber „formal gueltig / inhaltlich entscheidungsreif", benennt sie aber nicht als Code. Ergaenzend. |
| E-3 | `worker-b` | Die Grenze ist das **spaeteste, nicht das frueheste** Eskalationsereignis. Ein technisch ungueltiger Vertrag kann frueher eskalieren. | Ergaenzend, kein Widerspruch. |
| E-4 | `worker-a` | Ohne ausdrueckliche Zahl gilt genau **eine** weitere Runde; ein Kontingent ist hoechstens so gross wie das Grundlimit. | Praezisiert K2-10. |

## D2 — Verbliebene Unterschiede (klein)

| ID | Frage | `worker-a` | `worker-b` |
|---|---|---|---|
| D2-1 | Status von `REPLAN_REQUIRED` | **Eigenstaendiges Ergebnis**, das das System am Limit empfehlen, aber nicht allein setzen darf. | Am Limit lautet das Systemergebnis immer `HUMAN_DECISION_REQUIRED`; `REPLAN_REQUIRED` ist **eine der menschlichen Dispositionen**. |
| D2-2 | Limits je Storytyp | Zunaechst **nicht** — „schafft vor allem Umgehungsflaeche". Unterschiedlicher Bedarf wird ueber Grants behandelt. | **Optional zulaessig** als projektweit benannte Profile, falls empirisch belegt; der Storytyp waehlt ein Profil, setzt keinen Wert. |

Beide Unterschiede sind Ausgestaltung, nicht Richtung. In D2-1 stimmen sie in
der Sache ueberein (das System setzt es nicht allein); strittig ist nur, ob es
als eigener Zustand oder als Disposition gefuehrt wird.

## Bemerkenswerte Einzelfeststellung

`worker-b` stellt fest, dass der historische PO-Entscheid zu AG3-189 —
sinngemaess „so viele Runden wie noetig" — unter dieser Norm **als unbeschraenkt
zurueckgewiesen** und zur Angabe von `n` und Erfolgsbedingung zurueckgegeben
worden waere.

Das ist keine Kritik am Entscheid, sondern der Beleg, dass die Norm auch gegen
den bindet, der sie erlassen hat. Der Orchestrator haelt es fest, weil es die
Ernsthaftigkeit der Regel bestimmt: Eine Grenze, die fuer den PO nicht gilt,
ist keine.

## Offen fuer den PO

| ID | Frage | Herkunft |
|---|---|---|
| P2-1 | D2-1: `REPLAN_REQUIRED` als eigener Zustand oder als Disposition? | Runde 2 |
| P2-2 | D2-2: Storytyp-Profile zulassen oder zunaechst nur einen projektweiten Wert? | Runde 2 |
| P2-3 | Bestaetigung des Startwerts **5** (beide Teilnehmer unabhaengig). | Runde 2 |
| P2-4 | Wer ist der **Governance-Owner** der Review-Policy, wenn nicht der PO selbst? | Runde 2 |
| P3 (offen aus Runde 1) | Darf der PO einen bestaetigten Stop-Ship-Befund als Restrisiko akzeptieren? | Runde 1, von beiden Runden bewusst nicht entschieden |
