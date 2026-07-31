# AG3-176 — Codex-Review der Konzeptinhalte, Runden 4 bis 11 (Abschluss)

Fortsetzung von `concept-review-round1-codex.md` und
`concept-review-round2-3-codex.md`. Jede Runde ist ein frischer read-only
Codex-Agent; die Nachbesserung dazwischen macht der Orchestrator, der nach jeder
Runde volle Suite, `ruff`, `mypy` und die sechs Konzept-Gates selbst faehrt.

**Runde 11: BESTANDEN. Landefaehig: ja. Keine Vor-Merge-Auflagen.**

## Verlauf

| Runde | Verdikt | Befunde |
|---|---|---|
| 1 | NICHT BESTANDEN | 2 BLOCKER, 5 MAJOR |
| 2 | NICHT BESTANDEN | 1 BLOCKER (R-02 offen), 3 MAJOR |
| 3 | NICHT BESTANDEN | 1 BLOCKER, 3 MAJOR |
| 4 | NICHT BESTANDEN | 2 BLOCKER, 3 MAJOR |
| 5 | NICHT BESTANDEN | 1 BLOCKER, 2 MAJOR |
| 6 | NICHT BESTANDEN | 1 BLOCKER, 2 MAJOR |
| 7 | NICHT BESTANDEN | 1 BLOCKER, 2 MAJOR |
| 8 | NICHT BESTANDEN | 1 BLOCKER, 1 MAJOR (R4-04 geschlossen) |
| 9 | NICHT BESTANDEN | 1 BLOCKER, 1 MAJOR — erstmals abschliessende Liste |
| 10 | NICHT BESTANDEN | 2 ERROR |
| 11 | **BESTANDEN** | keine |

Die Zahl der Befunde faellt nur langsam, ihre **Art** aendert sich stark: Runden
1-3 raeumten den nie nachgezogenen Restkorpus des Beschlusses 2026-07-21 ab;
ab Runde 4 sind es Defekte, die vorher niemand gesehen hatte; ab Runde 9 nur
noch Aussagen, die den Code falsch beschreiben.

## Was diese Runden gefunden haben

**Produktionsdefekte, die ohne diese Runden gelandet waeren:**

- `mcp>=1.0` im Packaging: `mcp.server.fastmcp` existiert erst ab 1.2.0 — jede
  Clean-Installation waere beim Import der Pflichtfaehigkeit gestorben.
- Danach `>=1.2.0` **ohne Obergrenze**: mcp 2.0.0 ist LATEST und liefert weder
  `mcp.server.fastmcp` noch `mcp.types`. Am Wheel selbst verifiziert, nicht per
  Zitat. Jetzt `mcp>=1.2.0,<2`, beidseitig begrenzt und per Contract-Test gegen
  konkrete Versionen abgesichert (1.1.9 abgelehnt, 1.2.0 und 1.27.2 akzeptiert,
  2.0.0 abgelehnt).
- Der CP-10a-Receipt-Vertrag war normiert, aber im Code **nirgends erzwungen**:
  leere Pflichtfelder, negative Counter, ein `story_sync`, das den Konzeptkorpus
  beansprucht — alles ging durch. Eine Norm, die nur beim Schreiben gilt, ist
  keine.
- **Reihenfolge Publikation/Commit war falsch herum**: Kandidaten-Receipts mit
  `status="success"` landeten unter den finalen Namen, bevor irgendetwas bewiesen
  war. Ein unbekannter oder gescheiterter Abschluss hinterliess damit eine
  Erfolgsbehauptung fuer einen Abschluss, der nie gelandet ist.
- Danach: die Aufloesung zu `NOT_COMMITTED` entfernte den Journal-Riegel,
  waehrend die falsche Evidenz liegen blieb.
- `atomic_write_text` ist nur **pro Datei** atomar: ein Absturz zwischen den
  beiden Receipt-Writes hinterliess ein gemischtes Paar aus zwei Laeufen, jede
  Datei fuer sich wohlgeformt.
- Ein Marker **nach** dem Commit kann das Fenster **ab** dem Commit prinzipiell
  nicht abdecken — der Intent-Fence steht jetzt davor.
- Der Skill-Pin-Guard im Upgrade war **toter Code**: `skills` wurde produktiv nie
  uebergeben, der Guard kehrte immer sofort zurueck.
- Die CLI meldete **Exit 0 und „upgraded"**, obwohl der Guard die Mutation
  blockiert hatte.
- Der Adapter **synthetisierte** einen gRPC-Endpunkt (HTTP-Host + 50051) und
  verwarf das TLS-Flag des HTTP-Endpunkts — entgegen PO-Entscheidung D-2.
- `ProjectBinding.weaviate_grpc_endpoint` hatte Default `""` ohne Validierung,
  waehrend der HTTP-Endpunkt fail-closed geprueft wurde.

**Eigene Nachbesserungen, die selbst Befunde wurden** (die Haelfte der Blocker
ab Runde 5 waren Folgefehler der jeweils vorigen Korrektur):

- Negativtests, die aus dem **falschen Grund** gruen waren: `source_types` als
  Liste scheiterte im Strict-Mode ohnehin, also deckte kein einziger
  parametrisierter Fall seine eigentliche Constraint ab.
- Eine Zusicherung in die Norm geschrieben („faellt beim naechsten Verify
  fail-closed auf") und nicht implementiert.
- Ein Riegel im Register-Pfad, der den Aufloesungsweg verklemmt haette.
- Vier Aussagen (Docstrings, Fehlertext, Decision Record, Testkommentar), die
  nach der Reihenfolge-Umkehr das Gegenteil des Codes behaupteten.
- Ein CLI-Riegel ohne reproduzierenden Test — Regelverstoss gegen „Bugfix
  braucht reproduzierenden Test". Nachgezogen und per **Mutationsprobe** belegt:
  Riegel getauscht -> Test rot, zurueckgesetzt -> Test gruen.

## Bewusst getroffene Design-Entscheidung (Runde 5, normativ verankert)

Der Abschluss wird **vor** der Publikation committet. Der Preis: bei einem
Publikationsfehler ist der Korpus fortgeschritten und wird nicht zurueckgerollt.
Der Gewinn: es kann keine Erfolgsbehauptung fuer einen nicht gelandeten
Abschluss mehr entstehen. Ein detektierbarer, selbstheilender Rest ist einer
stillen Falschaussage vorzuziehen. Der Rest wird nicht still getragen, sondern
durch den durablen Intent-Fence sichtbar gemacht (FK-13 §13.9.9 und
`concept/_meta/decisions/2026-07-30-cp10a-receipt-contract.md` §2.2).

## Abschluss-Feststellungen der Runde 11

- Beide ERRORs der Runde 10 geschlossen (Beleg je Pfad und Zeile).
- **Keine weiteren Stellen mit veralteter Reihenfolge-/Fence-Semantik.** Gezielt
  geprueft: CP10a-Adapter und -Checkpoint, `PreparedInitialSync`,
  `PreparedSyncRun`, `sync.py`, Completion-Publikation in `engine.py`,
  Fehlermeldungen, Testkommentare.
- Keine neuen Befunde; keine Regression durch die Nachbesserungen.
- Landefaehig: **ja**, ohne Vor-Merge-Auflagen und ohne nachgelagerte WARNINGs.

## Grenzen (aus allen Runden uebernommen)

- Read-only: kein Review-Agent hat Tests oder Gates selbst ausgefuehrt. Volle
  Suite, `ruff`, `mypy` und die sechs Konzept-Gates hat der Orchestrator nach
  jeder Runde selbst gefahren.
- W2/W3 (LLM-gestuetzte Konzept-Live-Gates) wurden nicht ausgefuehrt.
- **Jenkins: HTTP 401.** Der Dienst laeuft (`/login` -> 200, anonyme API -> 403),
  aber beide hinterlegten Credential-Varianten werden abgewiesen. Vom
  Orchestrator eigenstaendig reproduziert und an den PO gespiegelt; **kein**
  Befund dieses Reviews, aber ein offenes Closure-Gate.
- Der AG3-179-Mutex-Race-Flake ist ein Bestandsdefekt auf main und wurde
  auftragsgemaess nicht bewertet.
