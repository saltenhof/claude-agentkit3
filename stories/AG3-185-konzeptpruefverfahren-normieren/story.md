# AG3-185 — PO-Entscheidungen und normative Verfahrensmigration

- **Typ:** concept
- **Groesse:** L
- **Abhaengigkeiten:** `depends_on: ["AG3-179", "AG3-200"]`; entblockt
  AG3-201, AG3-186
- **Quell-Konzept:** DK-16, FK-78, `concept/_meta/konzept-konsistenz-governance.md`
  (META-CONCEPT-CONSISTENCY), `concept/_meta/assertion-authority.md`
  (META-ASSERTION-AUTHORITY)
- **Herkunft:** PO-Entscheidungen vom 2026-08-02; Entwurf in
  `concept-incubator/konzeptpruefung-verfahren/workspace/` (Commit `fb38a9e7`),
  vier Liefergegenstaende, zwoelf Befunde. Neu geschnitten am 2026-08-02 nach
  unabhaengigem Codex-Review (Auflagen ERROR-13 bis ERROR-16).

## Kontext

### Befund

Die Konzeptpruefung wird umgestellt: weg von LLM-Hub-Gates, an die
Konzeptanteile geschickt werden in der Hoffnung auf saubere Modellantworten,
hin zu nativen KI-Agenten ueber die Harness-Bridge, denen von aussen nur
Leitplanken, Ziele und Nachweispflichten vorgegeben werden.

**Der Anlass war Erfuellbarkeit, nicht Bequemlichkeit.** Die
W2/W3-Pre-Merge-Pflicht war nicht erfuellbar: ein reproduzierbarer
`HUB_UNREACHABLE` oberhalb einer Partitionsgroesse von 35 666 Zeichen im
qwen-Adapter (groesste erfolgreiche: 35 202) und ein fehlender Retry in
`collect_scope_findings`, der einen kompletten Sweep an einem einzigen
nicht-woertlichen Modellzitat beendet. Eine Regel, die dasteht und nicht
erfuellbar ist, erzieht zur stillen Umgehung — in AG3-179 Runde 1 ist genau das
passiert („alle Konzept-Gates gruen", obwohl nur die statischen liefen).

**Was am 2026-08-02 schon verankert ist** (`AGENTS.md`, Commits `273c8bac`,
`19747fea`): die Aussetzung der Pflicht, die drei Pruefachsen der unabhaengigen
Agentenvorlage, und das Agentenmandat — frei in Strategie und Handeln, nicht in
Ziel und Leitplanken; neue normative Inhalte nur als Ausdetaillierung eines
groeber definierten Inhalts mit benennbarer Ankerstelle, ohne Widerspruch, ohne
neue Konzeptdomaene; fehlt der Anker, holt der Agent den PO.

**Was fehlt: die normative Nachfuehrung.** `AGENTS.md` ist lokale
Agenteninstruktion, kein Konzeptdokument. FK-78 §78.14 sagt weiterhin „LLM nur
als Bewertungsfunktion, kein Werkzeug entscheidet frei" ohne die ratifizierte
Praezisierung, und `konzept-konsistenz-governance.md` §6 fuehrt die
Betriebspflicht unveraendert.

### Was am ersten Schnitt falsch war

1. **Die Story war zirkulaer.** Ihr AC1 verlangte, den Entwurf „durch das
   Verfahren zu fuehren, das er beschreibt" — ein Verfahren, das zu diesem
   Zeitpunkt weder normiert noch vollstaendig implementiert ist, waehrend die
   Abgrenzung derselben Story dessen Bau ausschliesst. Das ist keine Auflage,
   sondern eine Blockade.
   **Aufloesung:** Es gilt die **Interimspflicht**, die `AGENTS.md` seit dem
   2026-08-02 bereits fuehrt — Vorlage an einen unabhaengigen Agenten (anderer
   Principal, andere Session) mit den drei benannten Pruefachsen. Sie „braucht
   keine neue Mechanik" (`AGENTS.md`) und existiert heute. Der Durchlauf durch
   das **neue** Verfahren ist der Gegenstand von AG3-202, nicht dieser Story.
2. **Sie war eine getarnte Epic.** Entscheidungen, Normierung, Mechanikbau und
   erster Pilot in einem Schnitt. Aufgeteilt in AG3-185 / AG3-201 / AG3-202.
3. **Ein importfaehiger Baustein fehlte vollstaendig.** Der Werkstattbericht
   nennt **vier** (`D-offene-entscheidungen.md` E5), die Story drei. Es fehlte
   **C-7, die Provider-Claim-Kante**.
4. **Die normative Betroffenheit war unvollstaendig** — die Story forderte nur
   FK-78 §78.14 und Governance §6.

### C-7 — der fehlende Baustein, und warum er der wichtigste ist

`C-befundbericht.md` C-7: Jede Aussage der Form „Dokument X besitzt, definiert,
liefert, enthaelt, pinnt oder fuehrt Y" ist eine positive Closure-Behauptung
ueber **fremden** Bestand. Sie wird dreistufig geprueft:

1. der Claim muss **konkrete Zielsymbole** nennen — ein blosser Dokumentverweis
   besteht die Kante nicht;
2. jedes Symbol muss im Zieldokument **namentlich existieren**;
3. es muss dort **dieselbe Bedeutung** tragen.

Entscheidend ist die Bauform: **die Pruefung ist paarweise und an keinem der
beiden Dokumente allein feststellbar.** Wer nur das Zieldokument liest, sieht
keine offene Erwartung — die steht beim Claimenden. Wer nur den Claimenden
liest, sieht einen Verweis, der plausibel aussieht.

W1 (`check_concept_reference_integrity.py`) deckt Stufe 2 fuer **aufloesbare**
Referenzen ab, aber nicht Stufe 1 und nicht Stufe 3. Der haeufigste Fall
entzieht sich W1 ganz: eine Prosaaussage „die konkreten Werte liefert FK-93"
ohne benannte Symbole ist referenzintegritaets-**gruen** und trotzdem eine
unbelegte Closure-Behauptung.

**Belegter Anlassfall in AK3:** genau diese Klasse ist in AG3-179 als E3
aufgetreten — FK-93 beansprucht Autoritaet ueber fremde Werte, ohne die Kanten
zu erklaeren. Der PO hat dazu festgehalten, dass der Wurzelfix „nicht deshalb zu
machen ist, damit W2 gruen wird", sondern weil das fehlende Deferral-Modell eine
eigene Modellierungsschuld ist, die „jeden Umbau der Pruefmechanik ueberlebt".

### Der konstruktive Gegenbefund, der den Umfang klein haelt

C-9: Der Request-Pack-/Receipt-Vertrag aus FK-78 §78.14 ist
**ausfuehrerneutral** — `participants[].spawn_mode` kennt `harness-bridge`
bereits als gleichberechtigten Wert neben `llm-hub`. Der Wechsel Hub → Bridge
ist ein **Adaptertausch, kein Verfahrenswechsel**. Was faellt, ist der
Hub-spezifische Betrieb der beiden Skripte und die dort verbaute
Partitionierung — nicht das Modell aus Request-Pack, Receipt und
deterministischer Verrechnung.

## Scope

### In Scope

- Beantwortung der **acht offenen Entscheidungen** aus
  `D-offene-entscheidungen.md` (E1–E8) — vom PO, wo sie ihm gehoeren; vom
  Umsetzer mit Begruendung, wo sie technisch sind.
- Die normative Nachfuehrung entlang der **vollstaendigen**
  Betroffenheitsmatrix (siehe AC 3).
- Entscheidung ueber **alle vier** importfaehigen Bausteine.
- Der Auftragsvertrag des pruefenden Agenten.
- Die Layout- und Begriffsfrage (`workspace`/`interface`, Thema vs. Lauf).

### Out of Scope

- **Der Bau der Mechanik** (Leichtpfad, Harness-Bridge-Adapter,
  Receipt-Mechanik) — **AG3-201**.
- **Der erste vollstaendige Durchlauf samt Migrationstreue-Pruefung** —
  **AG3-202**.
- **Kein Retry-Vertrag fuer W2/W3** — das Verfahren wird ersetzt, nicht
  repariert (PO-Entscheidung 2026-08-02; der Retry war fertig implementiert und
  ist in AG3-179 vollstaendig zurueckgebaut worden).
- Die Komponenten-/Schnittstellenschicht — **AG3-203** / **AG3-186**.

## Betroffene Dateien

| Pfad | Aenderungsart | Warum |
|---|---|---|
| `concept/technical-design/78_concept_incubation_process.md` §78.14 | geaendert | ratifizierte Praezisierung des Agentenmandats |
| ebenda §78.3 | geaendert | Layout-Ergaenzung Themenraum (E1) |
| ebenda §78.9 | geaendert | `gap_class` als Pflichtfeld an `OPEN_MISSING`/`DEFERRED_BACKLOG` (C-5), falls uebernommen |
| ebenda §78.10/§78.11 | geaendert | leichte Freigabebasis (E3), Unabhaengigkeitsgrad (E6) |
| ebenda §78.16 | geaendert | Proportionalitaet, falls die Profile beruehrt sind |
| ebenda §78.17 Nr. 3 | geaendert | Folge-Story „Hub-Batch-Komfort fuer W2/W3" wird gegenstandslos (C-9) |
| `concept/_meta/konzept-konsistenz-governance.md` §5 | geaendert | „LLM nur als Bewertungsfunktion" praezisieren (C-1/E2) |
| ebenda §6 | geaendert | Betriebspflicht W2/W3 (Wortlaut liegt in `B-uebergangsvermerk.md`) |
| ebenda §7 | geaendert | Umsetzungsfahrplan W1→W4→W2→W3 ist historisch |
| `concept/domain-design/16-konzeption-und-konzeptinkubation.md` §4 | geaendert | siebenstufiger Lauf ohne Vorlagestation (C-11) |
| `concept/_meta/assertion-authority.md` | geaendert | Freigabekriterien fuer `status: active` (C-8), falls dort verortet |
| `concept/_meta/authority-prose-baseline.yaml` | geaendert/entfernt | W2-Baseline: weiterfuehren, einfrieren oder ueberfuehren (C-11) |
| `AGENTS.md` | geaendert | Abgleich mit der jetzt normierten Fassung |
| Ein neues Methodikdokument (Zielort ist Entscheidung E5) | ggf. neu | kalter Implementierbarkeitstest, Provider-Claim-Kante, kalter Gegenleser |
| `concept/_meta/decisions/2026-XX-XX-konzeptpruefverfahren-migration.md` | neu | Decision Record mit vollstaendiger Betroffenheitsmatrix |

## Akzeptanzkriterien

1. **Die acht Entscheidungen aus `D-offene-entscheidungen.md` sind
   beantwortet** — E1 bis E8, jede einzeln, mit Urheber. PO-Entscheidungen sind
   **vom PO** eingeholt; technische Entscheidungen sind begruendet. Eine
   unbeantwortete Entscheidung ist kein Abschluss. E2 ist bereits ratifiziert
   (2026-08-02) und wird uebernommen, nicht neu entschieden.
   Insbesondere **E4**: wird ruhender Bestand weiter geprueft? Das neue
   Verfahren ist aenderungsgetrieben und sieht ihn sonst nie wieder an —
   „stillschweigend fallen lassen" ist nach C-11/E4 der teuerste Ausgang, weil
   ihn niemand bemerken wuerde.
2. **FK-78 §78.14 traegt die ratifizierte Praezisierung des Agentenmandats im
   Wortlaut, den `AGENTS.md` seit 2026-08-02 fuehrt.** Kein Widerspruch mehr
   zwischen Konzept und Agenteninstruktion. Nachgewiesen durch einen
   Wortlautvergleich beider Stellen, nicht durch „sinngemaess uebernommen".
3. **Die Betroffenheitsmatrix ist vollstaendig** und enthaelt **mindestens**
   die folgenden Elemente, jedes mit einer **Zielentscheidung**
   (geaendert / neu / nicht-betroffen / gegenstandslos):
   META-CONCEPT-CONSISTENCY **§5**, **§6**, **§7**; DK-16 **§4**;
   FK-78 **§78.3**, **§78.14**, **§78.16**, **§78.17 Nr. 3**;
   `concept/_meta/authority-prose-baseline.yaml`; `AGENTS.md`; der Decision
   Record selbst. Ein Element ohne Zielentscheidung ist eine Luecke, keine
   Auslassung.
4. **Alle vier importfaehigen Bausteine sind entschieden** — jeweils
   uebernommen und normiert, **oder** mit Begruendung verworfen:
   - **C-5 `gap_class`** (`extension` / `calibration` / `contract` /
     `decision`, mit der Severity-Untergrenze aus ATOM-01 §12.2). Ohne sie ist
     „wir haben die Luecke benannt" ein universeller Freifahrtschein.
   - **C-6 kalter Implementierbarkeitstest** — das einzige Werkzeug des
     Verfahrens, das **Abwesenheit** findet; jedes AK3-Gate prueft nur
     vorhandene Aussagen.
   - **C-7 Provider-Claim-Kante** — mit **allen drei Stufen**: Zielsymbole
     benannt, Symbole existieren namentlich, Bedeutungsgleichheit. Ein
     Kriterium, das nur die Aufloesbarkeit des Dokumentverweises fordert,
     erfuellt dieses AC **nicht** — das kann W1 heute schon, und genau daran
     ist der FK-93-Fall vorbeigelaufen.
   - **C-8 Freigabekriterien fuer `status: active`** samt kaltem Gegenleser und
     der `CONFLICT`-Regel bei widersprechenden Pruefern. Ohne sie ist eine
     Freigabe eine Meinung.
5. **Der Auftragsvertrag des pruefenden Agenten ist ausgeschrieben:** Ziel,
   Leitplanken, Nachweispflichten, Abbruchkriterien. Er waehlt seine Strategie
   selbst; was er schuldet, steht fest. „Konnte nicht geprueft werden" ist ein
   zulaessiges Ergebnis und niemals PASS.
6. **Die Layout- und Begriffsfrage ist geklaert** (E1/C-3): Themenraum vs.
   Lauf, und `interface` als Name, der im Blueprint eine **Tracking-Grenze**
   bezeichnet und hier zusaetzlich eine Reviewstation werden soll. Beide
   Funktionen sind explizit zusammengelegt oder explizit getrennt — ein
   stillschweigender Bedeutungswechsel ist ausdruecklich ausgeschlossen. **Eine
   dritte Benennung fuer dieselbe Sache entsteht nicht.**
7. **`konzept-konsistenz-governance.md` §6 ist nachgezogen** (der Wortlaut
   liegt in `B-uebergangsvermerk.md`), §5 ist entlang E2 praezisiert, §7 ist als
   historisch ausgewiesen.
8. **`authority-prose-baseline.yaml` hat eine Entscheidung** — weiterfuehren,
   einfrieren oder in das neue Befundregister ueberfuehren. Stilles
   Liegenlassen waere ZERO-DEBT-Bruch (C-11).
9. **Diese Story laeuft unter der Interimspflicht, nicht unter dem noch nicht
   normierten Verfahren.** Der Diff wird vor der Landung einem unabhaengigen
   Agenten vorgelegt — anderer Principal, andere Session als der Verfasser —
   mit den drei Pruefachsen aus `AGENTS.md`. Befunde werden an der Wurzel
   behoben.
10. **Alle deterministischen Konzept-Gates gruen**; W4-Decision-Record mit
    Betroffenheitsmatrix vorhanden. Ein nicht gefahrener W2/W3-Sweep wird
    **nicht** als gruen berichtet.

## Definition of Done

- AC 1–10 erfuellt, jedes mit benanntem Beleg.
- Die Antworten auf E1–E8 liegen im Decision Record, je mit Urheber und Datum.
- Die Betroffenheitsmatrix aus AC 3 ist vollstaendig und maschinell durch
  `check_concept_decision_record.py` bestaetigt.
- Unabhaengiges Codex-Review bis zum Abbruchkriterium aus `CLAUDE.md`.

## Konzept-Referenzen

- `concept/domain-design/16-konzeption-und-konzeptinkubation.md` §4, §6
- `concept/technical-design/78_concept_incubation_process.md` §78.3, §78.9,
  §78.10, §78.11, §78.13, §78.14, §78.16, §78.17
- `concept/_meta/konzept-konsistenz-governance.md` §5, §6, §7
- `concept/_meta/assertion-authority.md`
- `concept-incubator/konzeptpruefung-verfahren/workspace/`
  (`A-verfahrensentwurf.md`, `B-uebergangsvermerk.md`, `C-befundbericht.md`,
  `D-offene-entscheidungen.md`) — Werkstattstand, **nicht normativ**

## Guardrail-Referenzen

- `AGENTS.md` (Agentenmandat, PO-Ratifikation 2026-08-02) — Grundlage von AC 1
  und AC 9.
- `CLAUDE.md` „Council-Orchestrator" — Rollentrennung bei Konzeptarbeit im
  Incubator.
- `CLAUDE.md` „ZERO DEBT RULE" — AC 3 und AC 8.
- `CLAUDE.md` „Definition of Done: Codex-Review bis zum Abbruchkriterium".
