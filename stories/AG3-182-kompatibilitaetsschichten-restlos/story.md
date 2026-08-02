# AG3-182 — Kompatibilitaetsschichten restlos entfernen

- **Typ:** implementation
- **Groesse:** L
- **Betroffen:** `backend/process/language/`, `backend/governance/`, `integration_clients/`, diverse
- **Herkunft:** PO-Grundregel vom 2026-08-02 (`CLAUDE.md`, „KEINE KOMPATIBILITAETSSCHICHTEN — AUSNAHMSLOS").

## Befund

Es gibt kein produktives Projekt mit AK3. Jede Kompatibilitaetsschicht schuetzt
damit niemanden und erzeugt einen zweiten Pfad, den ab sofort jeder mitliest,
mitpflegt und mitprueft. Am 2026-08-02 wurde ein grosser Teil des Bestands
entfernt (Commit `01a27de1`): drei CLI-Verben, mehrere Compat-Module,
`GuardResult.PASS/.FAIL` samt zwei `NOSONAR`, fuenf `read_*_record`-Wrapper,
tote Nahtstellen, zwei Doppel-Reads.

**Der teuerste Beleg dafuer, warum die Regel richtig ist:** der Compat-Alias
`serve-control-plane` hielt den Legacy-Port `9080` am Leben. Die Portmigration
auf `9702` erreichte den Installer nie — **jede frische Installation schrieb
eine `control-plane.json`, die auf einen Port zeigte, auf dem nichts lauscht.**
Die Schicht hat nichts geschuetzt und genau den Fehler erzeugt, gegen den sie
angeblich half.

**Was bewusst stehen geblieben ist**, weil es nicht mechanisch entfernbar war:

| Ort | Was | Warum aufgeschoben |
|---|---|---|
| `backend/process/language/model.py` | `PhaseDefinition`/`TransitionRule`/`WorkflowDefinition`, `.phases`, `.transitions`, `get_phase()`, `phase_names` | ~330 Stellen in ~30 Modulen; `FlowDefinition.name` kollidiert mit dem kanonischen `NodeDefinition.name`, `.phases`/`get_phase(` existieren gleichlautend auf anderen Objekten |
| `backend/governance/runner.py:461` | Legacy-Tombstone-Dualwrite | haengt am `DeactivationResult`-Kontrakt |
| `backend/governance/runner.py:369` | `_purge_edge_bundles` Compat-Pfad | dito |
| `llm_client.set_eval_deadline` | deprecated, nur von Tests benutzt | Konsumenten sind Tests |
| `telemetry_projection_repository_qa.py:33` | Compat-Kandidat | benannt, nicht bewertet |
| `reasons.py:43`, `runner.py:393` | deprecated VectorDB-Migrations-Key | benannt, nicht bewertet |

## Akzeptanzkriterien

1. **Jeder Eintrag der Tabelle oben ist erledigt** — entfernt, oder mit einer
   fachlichen Begruendung als *kein* Kompatibilitaetskonstrukt ausgewiesen.
   „Zu aufwaendig" ist keine Begruendung; „das ist die kanonische Form, der
   andere Name war nie ein Alias" waere eine.
2. **Der `model.py`-Umbau laeuft als EIN Zug**: kanonischer Name bleibt, alter
   verschwindet, alle Aufrufstellen wandern mit. Kein Zwischenstand, in dem
   beide existieren. Die Namenskollisionen (`FlowDefinition.name` vs.
   `NodeDefinition.name`, gleichlautende `.phases`/`get_phase(` auf anderen
   Objekten) sind vor der Umbenennung aufgeloest und die Aufloesung ist im
   Code begruendet.
3. **Eine repo-weite Suche** nach `deprecated`, `compat alias`, `backward-compat`,
   `legacy` in `src/` weist am Ende **jeden verbleibenden Treffer** namentlich
   aus, mit Begruendung warum er kein Kompatibilitaetskonstrukt ist. Die
   Wortsuche allein trennt Konstrukt und Prosa nicht — die Bewertung ist Teil
   des Ergebnisses, nicht die Zahl.
4. **Ein Gate verhindert den Rueckfall.** Ein neuer Deprecated-Alias, ein
   Re-Export-Shim oder ein „legacy"-Default faellt maschinell auf, bevor er
   landet — oder es ist begruendet, warum das maschinell nicht entscheidbar ist
   und was stattdessen traegt.
5. **Kein `NOSONAR`, kein Rule-Exclude, kein unerklaertes `noqa`/`type: ignore`
   bleibt zurueck, das eine Kompatibilitaetsschicht verdeckt.** Am 2026-08-02
   fanden sich zwei `NOSONAR`, die genau das taten.
6. Volle Suite gruen, `ruff`, `mypy --strict` fuer win32/linux/darwin, alle
   deterministischen Konzept-Gates gruen. Konzept nachgezogen, wo ein entfernter
   Name normativ erwaehnt war.

## Abgrenzung

Keine Umbenennung aus Geschmacksgruenden. Diese Story entfernt
Kompatibilitaets**schichten** — Konstrukte, die einen zweiten Weg zum selben
Ziel offenhalten. Ein schlecht gewaehlter, aber einziger Name ist kein Fall
fuer diese Story.
