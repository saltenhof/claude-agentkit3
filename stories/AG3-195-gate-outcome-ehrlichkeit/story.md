# AG3-195 — Gate-Outcome-Ehrlichkeit

- **Typ:** implementation
- **Groesse:** M
- **Abhaengigkeiten:** `depends_on: []`
- **Quell-Konzept:** `AGENTS.md` (Pflicht-Gates), `CLAUDE.md`
  „SEVERITY-SEMANTIK" und „FAIL-CLOSED", FK-78 §78.14 (Envelope, Exit-Codes)
- **Herkunft:** Neu am 2026-08-02 aus Auflage ERROR-11 des unabhaengigen
  Codex-Reviews des Schnitts aus Commit `77b4b034`. Zuvor trugen AG3-183 AC2
  und AG3-184 AC5 dieselbe Aussage — zwei Eigentuemer fuer eine Regel.

## Kontext

### Befund — belegt, mit Locator

Ein nicht gefahrener Lauf sieht in AK3 heute an mehreren Stellen aus wie ein
bestandener. Belegt, nicht vermutet:

- **AG3-179 Runde 1** meldete „alle Konzept-Gates gruen", obwohl **nur die
  statischen liefen**. `AGENTS.md` fuehrt den Fall inzwischen ausdruecklich:
  „Ein nicht durchgelaufener Sweep wird niemals als 'gruen' berichtet.
  'Konzept-Gates gruen' bezeichnet ausschliesslich die statischen Gates. Wer
  beides zusammenzieht, wiederholt die Ueberbehauptung aus AG3-179 Runde 1."
- **Der Abschlusslauf ohne Container-Laufzeit** in derselben Story: „10410
  passed, 40 skipped, 356 errors, 0 FAILED" — ein Ergebnis, das ohne die
  ausdrueckliche Nacharbeit des Orchestrators als „0 failed" lesbar gewesen
  waere.
- **Der Freigabepfad des Mutex** (AG3-179 F1): eine endgueltig gescheiterte
  geschuldete Loeschung meldete weiter Erfolg — stderr-WARNING bei **Exit 0**
  und „[units] OK". Der Wurzelfix dort war ein reservierter Exit-Code `4` mit
  festgelegter Rangfolge (`2` > `1` > `4` > `0`, Decision Record
  `2026-08-01-run-mutex-intent-bounded-wait.md` Rand 2.4a).

Der Mutex-Fall ist der Beleg dafuer, dass die Regel loesbar ist — er hat sie
fuer **ein** Werkzeug geloest. Die uebrigen Gates haben sie nicht.

### Warum das eine eigene Story ist

Die Aussage „uebersprungen ist nicht bestanden" ist eine **Quer**-Eigenschaft
aller Gates: Tests, Lint, Typen, Konzept-Gates, Fremdsystem-Nachweise,
Jenkins-Stages. Wird sie in zwei Fach-Storys je zur Haelfte mitgefordert,
entsteht genau die Lage, die AK3 vermeiden will: eine Wahrheit ohne
Eigentuemer.

## Scope

### In Scope

- Eine einheitliche, ausgeschriebene Semantik der Gate-Ergebnisse:
  bestanden / befundet / **nicht gefahren** / abgebrochen — und ihre
  Rangfolge.
- Die Durchsetzung dieser Semantik in den Pflichtlaeufen (`Jenkinsfile`,
  `scripts/ci/`, Konzept-Gates, `.githooks/pre-commit`).
- Eine Zusammenfassung am Ende eines Laufs, die nicht gefahrene Gates
  **benennt**.

### Out of Scope

- Die Fremdsystem-Vertragsmatrix und die E2E-Spitzen — **AG3-183**.
- Die CI-Stufe der Realitaetsnachweise — **AG3-194**.
- Die Referenz-Baseline — **AG3-184**.
- `tools/` unter Lint/Typen — **AG3-197**.
- **Keine Aenderung an Schwellwerten oder an dem, was ein Gate inhaltlich
  prueft.** Diese Story aendert, was ein Gate ueber sich selbst **berichtet**.

## Betroffene Dateien

| Pfad | Aenderungsart | Warum |
|---|---|---|
| `scripts/ci/` (alle Gate-Skripte) | geaendert | einheitliche Ergebnisklassen und Exit-Codes |
| `Jenkinsfile` | geaendert | Stage-Ergebnis unterscheidet nicht gefahren von bestanden; Gesamtbewertung |
| `.githooks/pre-commit` | geaendert | dieselbe Semantik lokal |
| `tools/concept_governance/`, `tools/concept_compiler/` | geaendert | Envelope-/Exit-Code-Konsumenten |
| `concept/technical-design/78_concept_incubation_process.md` §78.14 | geaendert | Exit-Code-/Envelope-Vertrag erweitert |
| `concept/_meta/decisions/2026-XX-XX-gate-outcome-semantik.md` | neu | Decision Record mit Betroffenheitsmatrix |
| `tests/` | neu | je Ergebnisklasse ein Test |

## Akzeptanzkriterien

1. **Die Ergebnisklassen sind ausgeschrieben und haben eine Rangfolge.**
   Mindestens: bestanden, befundet, **nicht gefahren**, abgebrochen. Die
   Rangfolge ist begruendet und getestet — nach dem Muster, das der Decision
   Record `2026-08-01-run-mutex-intent-bounded-wait.md` Rand 2.4a fuer
   `semantic_gate.py` bereits festgelegt hat (`2` > `1` > `4` > `0`).
2. **Kein Gate meldet mehr „gruen" fuer etwas, das es nicht geprueft hat.**
   Nachgewiesen fuer **jedes** Pflicht-Gate einzeln: ein Lauf, in dem die
   Voraussetzung fehlt (Dienst unten, Datei fehlt, Umgebung unvollstaendig),
   endet unterscheidbar von einem bestandenen Lauf. Ein Gate, fuer das dieser
   Nachweis nicht gefuehrt wird, gilt als nicht abgedeckt.
3. **Ein Konsument kann die Faelle unterscheiden, ohne die Meldung zu
   parsen.** Exit-Code oder maschinenlesbares Ergebnisfeld — nicht Text.
4. **Die Lauf-Zusammenfassung benennt nicht gefahrene Gates.** Ein Lauf, in dem
   drei von zehn Gates nicht liefen, sagt das im Ergebnis — er meldet nicht
   „sieben bestanden".
5. **Ein Testlauf mit `skipped`/`errors` ist nicht als Erfolg lesbar.**
   Insbesondere der Fall aus AG3-179 („356 errors, 0 FAILED") ist als
   **nicht gefahren** klassifiziert, nicht als bestanden. Nachgewiesen an einem
   konstruierten Lauf ohne Container-Laufzeit.
6. **Die Aussage gilt auch fuer den Jenkins-Gesamtstatus.** Ein Build, in dem
   eine Pflicht-Stage uebersprungen wurde, ist nicht gruen.
7. **Konzept nachgezogen** (FK-78 §78.14 Exit-Code-/Envelope-Vertrag; `AGENTS.md`
   Pflicht-Gates) mit Decision Record und Betroffenheitsmatrix; alle
   deterministischen Konzept-Gates gruen.

## Definition of Done

- AC 1–7 erfuellt, jedes mit benanntem Beleg (Kommando, Ausgabe, Testname).
- Die Liste der abgedeckten Gates liegt vollstaendig im Story-Record; jedes mit
  dem Nachweis aus AC 2.
- `.venv\Scripts\python -m pytest` gruen; `ruff check src tests` clean;
  `mypy src --strict` gruen fuer `win32`, `linux` und `darwin`.
- Decision Record im Diff oder gueltiger `Concept-Decision`-Trailer.
- Unabhaengiges Codex-Review bis zum Abbruchkriterium aus `CLAUDE.md`.

## Konzept-Referenzen

- `concept/technical-design/78_concept_incubation_process.md` §78.14 —
  Exit-Code-Vertrag, Findings-Envelope
- `concept/_meta/decisions/2026-08-01-run-mutex-intent-bounded-wait.md`
  Rand 2.4 / 2.4a — das bereits geloeste Muster
- `concept/_meta/konzept-konsistenz-governance.md` §4 — Severity-Zuordnung

## Guardrail-Referenzen

- `CLAUDE.md` „SEVERITY-SEMANTIK" — WARNING ist ein Handlungsauftrag, kein
  Erfolgsersatz.
- `CLAUDE.md` „FAIL-CLOSED" — unklare Zustaende werden nicht grosszuegig
  toleriert.
- `CLAUDE.md` „NO ERROR BYPASSING".
- `AGENTS.md` — „Ein nicht durchgelaufener Sweep wird niemals als 'gruen'
  berichtet."
