# AG3-184 — Referenz-Integritaets-Baseline von Zeilennummern loesen

- **Typ:** implementation
- **Groesse:** M
- **Abhaengigkeiten:** `depends_on: ["AG3-179"]`
- **Quell-Konzept:** `concept/_meta/konzept-konsistenz-governance.md` §5 (W1),
  FK-78 §78.14
- **Herkunft:** Drei unabhaengige Befunde am 2026-08-02; neu geschnitten am
  2026-08-02 nach unabhaengigem Codex-Review (Auflage ERROR-12) auf **einen**
  davon.

## Kontext

### Befund — belegt, mit Locator

Die Referenz-Integritaets-Baseline
(`concept/_meta/reference-integrity-baseline.yaml`, 345 Zeilen) haengt an
Zeilennummern. Jeder Eintrag nennt `path` **und** `line`:

```yaml
  - code: UNRESOLVED_REPO_PATH
    path: concept/technical-design/00_index.md
    line: 411
    reference: concept/technical-design/_meta/glossary-overview.md
```

Jede Textaenderung im referenzierten Konzeptdokument verschiebt sie, und der
Gate-Lauf bricht mit `STALE_BASELINE` ab. Am 2026-08-02 ist das **dreimal an
einem Tag** passiert:

- `stories/AG3-179-run-mutex-intent-liveness/status.yaml`, Nachweise Runde 2:
  „inkl. nachgezogener Zeilennummer 878 -> 939 in reference-integrity-baseline.yaml"
- ebenda, Nachweise Runde 3: „wandernde Zeile 965 -> 1006 nachgezogen; ohne das
  STALE_BASELINE + unaufgeloester Verweis"
- Commit `51498dae`: „Referenz-Baseline auf die verschobene FK-13-Zeile
  nachziehen"

Der Mechanismus erzeugt Arbeit, die nichts prueft, und erzieht dazu,
Baseline-Eintraege gedankenlos nachzuziehen — genau die Haltung, die eine
Baseline wertlos macht.

### Die Spannung, die aufzuloesen ist

Die Zeilennummer hat einen Zweck: sie haelt die Ausnahme **eng**. Ohne sie
deckt ein Eintrag potenziell jedes Vorkommen derselben Referenz im ganzen
Dokument ab — und eine Baseline, die zu viel abdeckt, ist genauso wertlos wie
eine, die staendig bricht, nur leiser. Die Story muss beides gleichzeitig
erreichen; das ist ihr eigentlicher Inhalt.

### Warum sie auf AG3-179 blockiert

AG3-179 ist zum Zeitpunkt dieses Schnitts `in_progress` mit offenen Findings
aus Runde 4 und veraendert **genau die Baseline-Zeilen fuer FK-78 und FK-13**,
die diese Story ersetzen soll. Zwei parallele Umbauten an derselben Datei sind
ein vermeidbarer Konflikt.

## Scope

### In Scope

- Ein Baseline-Format, dessen Eintraege eine Textaenderung ueberleben.
- Die Erhaltung der Enge: ein Eintrag deckt weiterhin genau das ab, was gemeint
  ist.
- Migration aller bestehenden Eintraege.

### Out of Scope

- `tools/` unter `ruff` und `mypy` — **AG3-197**.
- Die FK-93-Eigentumsfrage — **AG3-198** (Entscheidung) und **AG3-199**
  (Umsetzung).
- Gate-Outcome-Semantik — **AG3-195**.
- **Keine neuen Gates und keine Verschaerfung bestehender Schwellwerte.** Diese
  Story repariert das Werkzeug, das es gibt, damit seine Aussagen tragen.

## Betroffene Dateien

| Pfad | Aenderungsart | Warum |
|---|---|---|
| `concept/_meta/reference-integrity-baseline.yaml` | geaendert | Format ohne Zeilenbindung; alle 345 Zeilen migriert |
| `tools/concept_governance/reference_integrity.py` (bzw. der W1-Implementierungsort) | geaendert | Aufloesung der Eintraege ohne Zeilennummer, `STALE_BASELINE`-Semantik |
| `scripts/ci/check_concept_reference_integrity.py` | geaendert | Aufrufseite |
| `concept/_meta/konzept-konsistenz-governance.md` §5 | geaendert | W1-Beschreibung folgt dem neuen Format |
| `concept/_meta/decisions/2026-XX-XX-referenz-baseline-ohne-zeilenbindung.md` | neu | Decision Record mit Betroffenheitsmatrix |
| `tests/` | neu | Textaenderung vor dem Eintrag; zu weit gefasster Eintrag |

## Akzeptanzkriterien

1. **Ein Eintrag ueberlebt eine Textaenderung im referenzierten Dokument, ohne
   nachgezogen zu werden.** Nachgewiesen: eine Zeile **vor** dem Eintrag
   einfuegen, Gate bleibt gruen. Der Nachweis laeuft an einem echten Eintrag der
   Baseline, nicht an einem Testfixture.
2. **Die Ausnahme bleibt eng.** Ein Eintrag deckt **nicht** versehentlich mehr
   ab als gemeint. Nachgewiesen durch einen Test, in dem ein **zweites**,
   fachlich anderes Vorkommen derselben unaufgeloesten Referenz im selben
   Dokument **nicht** von der Ausnahme gedeckt ist und das Gate rot macht.
   Ohne diesen Nachweis ist AC 1 durch das blosse Streichen des `line`-Feldes
   erfuellbar — und genau das waere die falsche Loesung.
3. **Alle 345 Zeilen der bestehenden Baseline sind migriert**, keine verloren,
   keine stillschweigend erweitert. Nachgewiesen durch einen Vorher-/Nachher-
   Vergleich der abgedeckten Befundmenge: identisch, nicht groesser.
4. **`STALE_BASELINE` behaelt eine Aufgabe.** Ein Eintrag, dessen Referenz es
   gar nicht mehr gibt, faellt weiterhin auf. Ein Format, das nie mehr
   veraltet, hat auch keine Selbstreinigung — das ist zu vermeiden und
   nachzuweisen.
5. **Konzept nachgezogen** (`konzept-konsistenz-governance.md` §5) mit Decision
   Record und Betroffenheitsmatrix; alle deterministischen Konzept-Gates gruen.
6. **Volle Suite gruen**, `ruff` clean, `mypy --strict` fuer `win32`, `linux`,
   `darwin`.

## Definition of Done

- AC 1–6 erfuellt, jedes mit benanntem Beleg (Kommando, Ausgabe, Testname).
- AG3-179 ist `completed`, bevor diese Story startet (`depends_on`).
- Coverage haelt die 85-%-Schwelle.
- Decision Record im Diff oder gueltiger `Concept-Decision`-Trailer.
- Unabhaengiges Codex-Review bis zum Abbruchkriterium aus `CLAUDE.md`.

## Konzept-Referenzen

- `concept/_meta/konzept-konsistenz-governance.md` §5 — Werkzeug W1
  `concept-reference-integrity`
- `concept/technical-design/78_concept_incubation_process.md` §78.14 —
  Toolchain und Envelope
- `stories/AG3-157-*/` — die Story, die W1 gebaut hat (Historie)

## Guardrail-Referenzen

- `CLAUDE.md` „FIX THE MODEL, NOT THE SYMPTOM" — die Zeilenbindung ist das
  Modellproblem, nicht das wiederholte Nachziehen.
- `CLAUDE.md` „NO ERROR BYPASSING" — AC 2 und AC 4: die Baseline darf nicht
  durch die Reparatur zur Pauschalausnahme werden.
- `AGENTS.md` — W1 bleibt unveraendert blockierend.
