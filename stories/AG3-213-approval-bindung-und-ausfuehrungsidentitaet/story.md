# AG3-213 — Approval-Bindung, Ausfuehrungsidentitaet und der Budget-Fallback

- **Typ:** implementation
- **Groesse:** M
- **Abhaengigkeiten:** `depends_on: ["AG3-191"]`
- **Quell-Konzept:** FK-69 (QA-Telemetrie, Outcome-Schluessel), FK-20/FK-27
  (Implementation-Phase, Approval), Integration-Stabilization
- **Herkunft:** Unabhaengiges Codex-Review des AG3-191-Stands am 2026-08-04
  (Runde 6). Von acht ERRORs lagen fuenf innerhalb der AG3-191-ACs und sind
  dort behoben; diese drei liegen ausserhalb und haben je einen eigenen
  fachlichen Kern.

## Befund 1 (Sicherheit) — die Approval-Bindung prueft sich gegen sich selbst

**Locator:** `src/agentkit/backend/implementation/phase.py:1231,1242`

Ist keine gebundene `FlowExecution.run_id` aufloesbar, nimmt
`_resolve_is_run_id` die `approval.run_id` als Ersatz. Die Run-Bindung wird
danach **gegen denselben Approval-Wert** geprueft, den sie absichern soll. Ein
Approval kann damit Implementation freigeben, obwohl keine autoritative
Run-Identitaet existiert.

Das ist die Bauart aus AG3-191 in ihrer teuersten Form: nicht ein Urteil, das
ungenauer weiterarbeitet, sondern eine **Bindungspruefung, die ihren eigenen
Prueflings-Wert als Referenz nimmt**. Sie kann strukturell nie fehlschlagen.

**Behebung:** Fuer Integration-Stabilization eine vorhandene, nicht-leere
kanonische Flow-Run-ID verlangen; fehlt der Run-Scope, wird blockiert. Der
Approval-Wert ist niemals Ersatzinput derselben Bindungspruefung.

## Befund 2 (Datenmodell) — mehrfach ausgefuehrte Checks werden verschluckt

**Locator:** `verify_system/structural/checker.py:369`,
`verify_system/check_outcome_emitter.py:59`, `verify_system/qa_read_models.py:39`;
festgeschrieben durch `tests/integration/verify_system/test_check_outcome_emitter_wiring.py:262`

`phase_snapshots` wird produktiv **einmal je Phase** ausgefuehrt und
entsprechend mehrfach in `total_checks` gezaehlt, waehrend der
Outcome-Primaerschluessel alle Ausfuehrungen desselben `check_id` auf **genau
eine Zeile** kollabieren laesst. Zaehlung und Persistenz widersprechen sich; die
Auditspur verliert Ausfuehrungen.

Der Befund ist Bestand, wurde aber erst durch AG3-191 sichtbar: seit
`executed_check_ids` das verbindliche Protokoll ist, gibt es eine Wahrheit, an
der sich die Persistenz messen laesst.

**Zwei Loesungswege, die Wahl ist eine Fachentscheidung und gehoert in die
Umsetzung, nicht in diese Story:**

- jede Phasenpruefung mit eigener registry-registrierter Check-ID protokollieren
  (`phase_snapshots.<phase>`), Findings angleichen — oder
- den normativen **und** physischen Outcome-Schluessel um eine
  Ausfuehrungsidentitaet erweitern.

Der zweite Weg ist eine Schemaaenderung an FK-69 mit Migrationsbedarf in beiden
Stores; der erste bleibt im Registry-Vokabular. Wer umsetzt, legt die Wahl
begruendet vor, bevor er baut.

Der Test, der die Kollision heute als erwartetes Verhalten festschreibt, ist zu
korrigieren — nicht zu ergaenzen.

## Befund 3 (fail-closed) — korrupter Budgetzustand wird zu unverbrauchtem Budget

**Locator:** `src/agentkit/backend/integration_stabilization/stability_gate_producer.py:85`

Lesefehler, ungueltiges JSON und missgebildete Feldwerte einer **vorhandenen**
`integration_budget.json` werden zu `{}` bzw. `0` heruntergestuft. Ein
erschoepftes oder unbekanntes Budget kann damit als PASS durch das
Stability-Gate laufen.

**Behebung:** Nur die fachlich erlaubte **Abwesenheit** der Datei ist ein
initialer Nullstand. Eine vorhandene, aber unlesbare oder schemawidrige Datei
beendet den Gate-Lauf mit benanntem BLOCK. Produktiver Negativtest.

## Akzeptanzkriterien

1. **Keine Bindungspruefung nimmt ihren Prueflingswert als Referenz.** Fehlt der
   Run-Scope, wird blockiert. Nachgewiesen durch einen Negativtest, der ohne
   aufloesbare `FlowExecution.run_id` die Freigabe verweigert — am produktiven
   Aufrufer, nicht an der Hilfsfunktion.
2. **Zaehlung und Persistenz der Check-Outcomes stimmen ueberein.** Mehrfach
   ausgefuehrte Checks sind in der Auditspur vollstaendig sichtbar. Der gewaehlte
   Weg ist begruendet; bei Schemaaenderung ist FK-69 nachgezogen und beide
   Stores tragen sie.
3. **Ein vorhandenes, unlesbares Budget blockiert.** Nur Abwesenheit ist
   Nullstand. Negativtest am produktiven Gate-Lauf.
4. **Volle Suite gruen** (Jenkins), `ruff`, `mypy --strict`, alle
   deterministischen Konzept-Gates; Decision Record mit Betroffenheitsmatrix,
   falls FK-69 beruehrt wird.

## Definition of Done

- AC 1-4 erfuellt, jedes mit benanntem Beleg (Kommando, Ausgabe, Testname).
- Coverage haelt die 85-%-Schwelle.
- Unabhaengiges Codex-Review bis zum Abbruchkriterium aus `CLAUDE.md`.

## Guardrail-Referenzen

- `CLAUDE.md` „FAIL-CLOSED" — Befunde 1 und 3
- `CLAUDE.md` „NO ERROR BYPASSING"
- `CLAUDE.md` „FIX THE MODEL, NOT THE SYMPTOM" — Befund 2 ist ein
  Modellwiderspruch, kein Zaehlfehler
