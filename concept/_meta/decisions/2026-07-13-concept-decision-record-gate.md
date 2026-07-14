---
concept_id: META-DEC-2026-07-13-CONCEPT-DECISION-RECORD-GATE
title: Concept-Decision-Record — Concept-Decision-Record-Gate W4
module: meta
cross_cutting: true
status: active
doc_kind: decision-record
authority_over: []
defers_to: []
supersedes: []
superseded_by:
tags: [meta, decision-record, concept-consistency, ci, review-gate, AG3-158]
formal_scope: prose-only
---

# Concept-Decision-Record — Concept-Decision-Record-Gate W4

Datum: 2026-07-13. Record gemaess META-CONCEPT-CONSISTENCY P3
(Blast-Radius-Pflicht bei normativen Aenderungen).

## 1. Anlass

META-CONCEPT-CONSISTENCY P3 verlangt fuer jede normative
Konzeptaenderung einen Impact-Sweep mit Betroffenheitsmatrix. W4
beschrieb den dafuer vorgesehenen Review-Check bisher nur abstrakt:
Ein Record im selben Diff oder eine Commit-Referenz sollten die
Pflicht erfuellen, ohne dass Trailer-Syntax, Diff-Ermittlung und die
fail-closed Ausnahme fuer reine Formatkorrekturen konkretisiert
waren. Dadurch war die bereits manuell geltende ERROR-Regel nicht
deterministisch als CI-Gate durchsetzbar.

## 2. Entscheidung

W4 wird als LLM-freies, blockierendes CI-Gate umgesetzt. Der reine
Kern bewertet ein injiziertes Diff-Modell; ein duenner Git-Adapter
liefert Koerperzeilen und Commit-Nachrichten fuer eine feste
`base..head`-Range. In Scope liegen Dateien unter `concept/` mit
Ausnahme der Record-Ablage selbst.

Eine normative oder uneindeutige Koerperzeile erfordert ein Record.
Die Pflicht ist durch ein schema-konformes Record im selben Diff oder
durch den Trailer `Concept-Decision: YYYY-MM-DD-<slug>` auf ein
bestehendes Record erfuellt. `Concept-Format-Only: <Begruendung>`
darf nur uneindeutige Textaenderungen herabstufen; ein Modalmarker
bleibt auch mit diesem Trailer record-pflichtig. Leere Gruende, tote
Referenzen und falsch benannte Records sind blockierende ERRORs.

## 3. Alternativen

- Eine rein menschliche Review-Konvention wurde verworfen, weil sie
  P3 nicht reproduzierbar erzwingt und Fehler erst nachgelagert
  sichtbar macht.
- Ein semantischer LLM-Klassifikator wurde verworfen, weil W4 als
  billiges, deterministisches Prozess-Gate arbeiten soll und eine
  unsichere Bewertung fail-closed behandelt werden kann.
- Ein pauschaler Format-Only-Bypass wurde verworfen, weil er echte
  normative Aenderungen mit Modalmarkern verdecken koennte.
- Eine retroaktive Historienpruefung wurde verworfen; W4 gilt fuer
  die jeweils neu integrierte Commit-Range.

## 4. Impact-Sweep (P3)

Der lexikalische Sweep ueber `concept/`, `scripts/ci/`, `Jenkinsfile`,
`AGENTS.md`, `stories/` und die bestehenden Decision-Records ergab
genau einen normativen Owner fuer die W4-Regel:
`concept/_meta/konzept-konsistenz-governance.md`. Die beiden Records
vom 2026-07-02 liefern das Frontmatter- und Benennungsvorbild. Die
technische Durchsetzung liegt im neuen CI-Script und wird als eigener
Jenkins-Stage verdrahtet; bestehende Konzept-Gates bleiben technisch
entkoppelt. K5 ist nicht betroffen, weil das Gate weder Laufzeitdaten
noch ein Datenbankschema besitzt.

## 5. Betroffenheitsmatrix

| Stelle | Klassifikation | Begruendung |
|---|---|---|
| `concept/_meta/konzept-konsistenz-governance.md` W4 und Betriebsmodell | geaendert | Normativer Owner erhaelt Trailer-Syntax, Erfuellungswege, Non-Bypass und Review-Punkt. |
| `concept/_meta/decisions/2026-07-13-concept-decision-record-gate.md` | geaendert | Dieses Record persistiert Entscheidung, Alternativen und Impact-Sweep. |
| `scripts/ci/check_concept_decision_record.py` und `tools/concept_compiler/` | referenziert-jetzt | Deterministische technische Durchsetzung mit reinem Kern und Git-Adapter. |
| `Jenkinsfile` | geaendert | W4 wird als sechstes blockierendes Konzept-Gate fuer die Integrations-Range ausgefuehrt. |
| `AGENTS.md` | geaendert | Entwicklerhinweis und W4-Review-Checkliste werden am bestehenden Gate-Ort verankert. |
| Bestehende Konzeptdokumente ausserhalb des META-Owners | nicht-betroffen | Keine fachliche Aussage oder Authority wird geaendert. |
| Bestehende W1-/Formal-/Code-Contract-Gates | nicht-betroffen | W4 ist additiv und importiert keine bestehende Gate-Implementierung. |
