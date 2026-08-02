# AG3-191 — QA-/Policy-Fallbacks im `verify_system` entfernen

- **Typ:** implementation
- **Groesse:** M
- **Abhaengigkeiten:** `depends_on: []`; entblockt AG3-193
- **Quell-Konzept:** FK-27 (Verify/Closure-Orchestrierung), FK-33
  (deterministische Checks, Stage-Registry, Policy-Engine), FK-69 (QA-Zeilen)
- **Herkunft:** Neu am 2026-08-02 aus Auflage ERROR-9 des unabhaengigen
  Codex-Reviews des Schnitts aus Commit `77b4b034`.

## Kontext

### Befund — belegt, mit Locator

Das `verify_system` fuehrt an vier Stellen einen zweiten Weg zum selben Ziel.
Alle vier bezeichnen sich im Code **selbst** als Legacy- oder Fallback-Pfad —
das ist keine Interpretation, sondern der Wortlaut:

| Locator | Was | Wortlaut im Code |
|---|---|---|
| `backend/verify_system/check_outcome_emitter.py:109` | `origin_check_ref` als Einzelwert neben der Mapping-Aufloesung | „The legacy `origin_check_ref` single value is used as a fallback when …" |
| `backend/verify_system/check_outcome_emitter.py:170-171` | Aufloesung faellt auf den Einzelwert zurueck | „Falls back to the legacy single origin_check_ref when mapping not provided" |
| `backend/verify_system/policy_engine/engine.py:165-167` | `max_major_findings` als „legacy knob" neben dem per-Story-Type-Modell | „This is the legacy knob …" / „the fallback when the per-story-type model is not consulted" |
| `backend/verify_system/policy_engine/engine.py:414,444-445` | Ergebnisse werden auch unter `_legacy_result_name(stage)` gematcht | „Return the legacy result name for a registered stage." |
| `backend/verify_system/stage_coverage_mapping.py:60,65-66` | dieselbe Legacy-Namensabbildung ein zweites Mal | „Return the legacy LayerResult name for a stage ID." |
| `backend/state_backend/store/telemetry_projection_repository_qa.py:33` | Read delegiert „for backward compatibility" | „Read: delegates to the facade for backward compatibility." |

**Warum das hier besonders teuer ist.** Diese Pfade sitzen in der QA-Schicht —
also in dem Teil, der beurteilen soll, ob etwas in Ordnung ist. Ein
Fallback-Pfad in einem Urteilsmechanismus heisst: wenn die praezise Zuordnung
fehlt, urteilt die ungenaue weiter und meldet dasselbe Ergebnisformat. Genau
diese Bauart hat am 2026-08-02 an anderer Stelle einen falschen Wert
durchgesetzt, waehrend jeder Mechanismus einwandfrei arbeitete.

Die **doppelte** `_legacy_result_name`-Implementierung (Policy-Engine und
Stage-Coverage-Mapping) ist zusaetzlich eine zweite Wahrheit ueber dieselbe
Abbildung — bei Divergenz urteilen die beiden Stellen verschieden.

## Scope

### In Scope

- Entfernung aller sechs oben benannten Pfade **oder** — je Stelle einzeln —
  ihre Ausweisung als kanonische Form mit fachlicher Begruendung.
- Die Aufloesung der doppelten `_legacy_result_name`-Implementierung.
- Konzeptnachzug, wo ein entfernter Pfad normativ erwaehnt war.

### Out of Scope

- Das Flow-/Node-Vokabular — **AG3-182**.
- Die uebrigen produktiven Aliase ausserhalb des `verify_system` — **AG3-192**.
- Das Gate gegen den Rueckfall — **AG3-193**.
- Keine Aenderung an den QA-Schwellwerten selbst; diese Story entfernt den
  **zweiten Weg**, nicht die Politik.

## Betroffene Dateien

| Pfad | Aenderungsart | Warum |
|---|---|---|
| `src/agentkit/backend/verify_system/check_outcome_emitter.py` | geaendert | `origin_check_ref`-Fallback; Signatur ohne zweiten Weg |
| `src/agentkit/backend/verify_system/policy_engine/engine.py` | geaendert | `max_major_findings`-Legacy-Knopf; `_legacy_result_name` |
| `src/agentkit/backend/verify_system/stage_coverage_mapping.py` | geaendert | zweite `_legacy_result_name`-Implementierung |
| `src/agentkit/backend/state_backend/store/telemetry_projection_repository_qa.py` | geaendert | Read-Delegation „for backward compatibility" |
| `src/agentkit/backend/**` (Aufrufstellen) | geaendert | Aufrufer wandern mit |
| `tests/unit/verify_system/**` | geaendert | Tests, die den Fallback-Vertrag festschreiben, werden korrigiert oder entfernt |
| `concept/technical-design/33_deterministische_checks_stage_registry_policy_engine.md` | geaendert | falls ein entfernter Pfad normativ erwaehnt ist |
| `concept/_meta/decisions/2026-XX-XX-qa-policy-fallbacks.md` | neu | Decision Record mit Betroffenheitsmatrix |

## Akzeptanzkriterien

1. **Jede der sechs benannten Stellen ist erledigt** — entfernt, oder mit einer
   **fachlichen** Begruendung als *kein* Kompatibilitaetskonstrukt ausgewiesen.
   „Zu aufwaendig" ist keine Begruendung; „das ist die kanonische Form, der
   andere Name war nie ein Alias" waere eine. Eine Stelle, deren eigener
   Docstring sie „legacy" oder „fallback" nennt, kann nur durch **Entfernung
   oder Umformulierung samt Verhaltensaenderung** erledigt werden — nicht durch
   eine Notiz, die den Docstring stehen laesst.
2. **Es gibt genau eine Abbildung von Stage auf Result-Namen.** Die doppelte
   `_legacy_result_name`-Implementierung ist auf einen Ort reduziert oder
   entfallen. Nachgewiesen durch einen Test, der beide Aufrufwege gegen
   dieselbe Quelle fuehrt.
3. **Kein QA-Pfad urteilt weiter, wenn die praezise Zuordnung fehlt.** Fehlt
   `check_origin_refs` oder die Story-Type-Schwelle, ist das fail-closed ein
   Fehler mit benanntem Grund — nicht ein Rueckfall auf die ungenaue Variante.
   Nachgewiesen durch einen Negativpfad-Test.
4. **Kein `NOSONAR`, kein Rule-Exclude, kein unerklaertes `noqa`/`type: ignore`
   bleibt zurueck**, das einen dieser Pfade verdeckt.
5. **Tests, die den Fallback-Vertrag festschreiben, sind korrigiert oder
   entfernt** — nicht ergaenzt. Ein Test, der verlangt, dass der Legacy-Pfad
   funktioniert, ist Teil der Schicht.
6. **Volle Suite gruen**, `ruff` clean, `mypy --strict` fuer `win32`, `linux`,
   `darwin`, alle deterministischen Konzept-Gates gruen. Konzept nachgezogen,
   wo ein entfernter Name normativ erwaehnt war.

## Definition of Done

- AC 1–6 erfuellt, jedes mit benanntem Beleg (Kommando, Ausgabe, Testname).
- Coverage haelt die 85-%-Schwelle.
- Decision Record im Diff oder gueltiger `Concept-Decision`-Trailer.
- Unabhaengiges Codex-Review bis zum Abbruchkriterium aus `CLAUDE.md`.

## Konzept-Referenzen

- `concept/technical-design/33_deterministische_checks_stage_registry_policy_engine.md`
- `concept/technical-design/27_verify_pipeline_closure_orchestration.md`
- FK-69 §69.15.6 — die im Code zitierten QA-Zeilen-Invarianten

## Guardrail-Referenzen

- `CLAUDE.md` „KEINE KOMPATIBILITAETSSCHICHTEN — AUSNAHMSLOS".
- `CLAUDE.md` „FAIL-CLOSED" — AC 3.
- `CLAUDE.md` „WORKFLOW- UND STATE-DISZIPLIN" — QA-Artefakte sind geschuetzt;
  ein zweiter Urteilspfad untergraebt das.
- `CLAUDE.md` „FIX THE MODEL, NOT THE SYMPTOM" — AC 2: keine zweite Wahrheit.
