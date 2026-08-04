# AG3-212 — Die restlichen Urteils-Fallbacks im `verify_system`

- **Typ:** implementation
- **Groesse:** L
- **Abhaengigkeiten:** `depends_on: ["AG3-191"]`
- **Quell-Konzept:** FK-11 (Prompt-Execution/Evaluator), FK-27, FK-33, FK-69
- **Herkunft:** Unabhaengiges Codex-Review des AG3-191-Gesamtstands am
  2026-08-04. Es hat zehn ERRORs gefunden; sechs betrafen die Arbeit selbst und
  sind dort behoben. Die folgenden fuenf liegen **ausserhalb** der
  AG3-191-Locator-Tabelle und sind Bestand.

## Kontext

### Die Praemisse von AG3-191 war unvollstaendig

AG3-191 ging von **sechs** Fallback-Pfaden im `verify_system` aus — die, die
sich im Code selbst „legacy" oder „fallback" nannten und deshalb per Textsuche
auffindbar waren. Zwei weitere kamen waehrend der Umsetzung dazu
(`traversed_layers`, `resolve_default_options`), beide ebenfalls selbstbenannt.

Das unabhaengige Review hat **fuenf weitere** gefunden, die sich **nicht** so
nennen. Das ist die eigentliche Erkenntnis: die Textsuche nach „legacy" und
„fallback" findet die ehrlichen Faelle. Die teuren sind die, die wie ein Entwurf
aussehen — genau das, was `CLAUDE.md` unter ZERO DEBT beschreibt: „Schuld, die
wie ein Entwurf aussieht, kostet mehr als Schuld, die wie ein Fehler aussieht."

### Warum das im `verify_system` besonders teuer ist

Alle fuenf sitzen in der Schicht, die beurteilen soll, ob etwas in Ordnung ist.
Ein degradierter Eingang, der trotzdem dasselbe Ergebnisformat liefert, ist dort
kein Robustheitsgewinn, sondern ein stilles Falschurteil.

## Befunde — belegt, mit Locator

| # | Locator | Was |
|---|---|---|
| 1 | `verify_system/story_contract_resolution.py:18`, `verify_system/system.py:102`, Test `tests/unit/verify_system/test_top_surface.py:926` | Ein **fehlender `StoryContext`** wird als `IMPLEMENTATION` mit Standardvertrag behandelt. Der Implementation-Pfad blockiert vorgelagert, **Exploration erreicht diesen erfundenen Typ aber**. Ein Test schuetzt den Null-Port ausdruecklich. |
| 2 | `verify_system/qa_execution.py:112`, `verify_system/layer2_conformance.py:58`, `verify_system/llm_evaluator/reviewer.py:113`, Test `tests/unit/implementation/test_implementation_phase.py:945` | Fehlender praeziser **Layer-2-Input** wird in ein leeres Objekt umgewandelt, ohne LLM auf historische Dateisystem-Reviewer umgeleitet und als genau drei MAJORs beim Schwellenwert 3 toleriert. Der produktnahe Test dokumentiert diesen PASS ausdruecklich. |
| 3 | `verify_system/llm_evaluator/structured_evaluator.py:507`, **normativ vorgeschrieben** in FK-11 §320 („Stufe 3: Regex-Fallback (letztes Mittel)") | Nach gescheiterter JSON-Validierung urteilt der QA-Evaluator aus **regex-extrahiertem Freitext** weiter. |
| 4 | `verify_system/defaults.py` — falls nach AG3-191 noch Reste bestehen | Zweiter Konfigurationsweg neben dem typisierten Optionsvertrag. **In AG3-191 als E6 bereits behoben**; hier nur als Pruefpunkt gefuehrt. |
| 5 | `verify_system/sonarqube_gate/adapter.py:480`, `sonarqube_gate/stage.py:52`, `qa_cycle/fingerprint.py:71` | Aktuelles **plus altes Sonar-Response-Format**, eine testgeschuetzte Sonar-„Compatibility view", und **synthetische Fingerprint-Evidenz** fuer alte oder unverdrahtete Aufrufer. |

## PO-ENTSCHEID 2026-08-04 — Variante (a), Befund 3 ist entschieden

> „Wenn der Evaluator ein JSON, also eine formal definierte Struktur, nicht
> parsen kann, dann soll er auch nicht auf Regex zurueckfallen. Dann ist die
> Struktur kaputt und dann muss man das Problem an der Wurzel packen."

**FK-11 Stufe 3 faellt.** Bei gescheiterter Schemavalidierung gilt
ausschliesslich der begrenzte Retry, danach FAIL. Der QA-Evaluator urteilt nie
aus Freitext.

Der Zusatz „an der Wurzel packen" ist Teil des Auftrags, nicht Rhetorik: ein
FAIL, das nur „Schema verletzt" sagt, verschiebt das Problem lediglich vom
Fallback in ein Protokoll, das niemand liest. Der Fehlerpfad muss die Ursache
**auffindbar** machen — welcher Evaluator, welches Modell, welcher
Prompt-/Response-Ausschnitt, welche Schemaverletzung. Kaputte Struktur ist ein
Defekt am Prompt- oder Modellvertrag und wird dort behoben.

Damit entfaellt der Blocker; die Story ist umsetzungsreif. Die verworfenen
Varianten bleiben unten stehen, damit spaeter nachvollziehbar ist, was
entschieden wurde und was nicht.

## Verworfene Varianten zu Befund 3

Befund 3 ist der einzige, bei dem **das Konzept selbst den Fallback anordnet**.
FK-11 §320 beschreibt eine dreistufige Auswertung und nennt Stufe 3
ausdruecklich einen „Robustheits-Fallback". Das steht gegen die hoeherrangigen
Regeln aus `CLAUDE.md`:

- „NO ERROR BYPASSING — keine heimlichen Fallbacks auf schlechtere
  Datenqualitaet oder weichere Regeln"
- „FAIL-CLOSED — unklare oder unvollstaendige Zustaende werden nicht
  grosszuegig toleriert"

Nach der Prioritaetsordnung (`CLAUDE.md` §Mindset) gewinnt die Projektregel
gegen das Fachkonzept — aber eine normative Konzeptaussage streicht man nicht
nebenbei in einer Implementierungsstory. Zur Wahl standen:

- **(a) — GEWAEHLT.** FK-11 Stufe 3 faellt. Bei Schemafehler nur der begrenzte
  Retry, danach FAIL. Der QA-Evaluator urteilt nie aus Freitext. FK-11 wird
  nachgezogen.
- **(b) — verworfen.** Stufe 3 bleibt, ihr Ergebnis wird aber nicht
  urteilsfaehig. Haette den Regex-Pfad als toten Code konserviert und die Frage
  „warum steht das da" der naechsten Story vererbt.
- **(c) — verworfen.** Stufe 3 bleibt unveraendert als dokumentierte Ausnahme.
  Waere die Ausnahme fuer genau die Bauart gewesen, gegen die AG3-191 und diese
  Story antreten.

## Akzeptanzkriterien

1. **Kein QA-Kontext ohne `StoryContext`.** Der Null-Port und
   `_effective_story_type(None)` sind entfernt; jeder Pfad — auch Exploration —
   traegt einen echten typisierten Kontext. Ein fehlender Kontext ist
   fail-closed ein Fehler mit benanntem Grund. Der Test, der den Null-Port
   schuetzt, ist **korrigiert oder entfernt**, nicht ergaenzt.
2. **Layer 2 urteilt nur auf kanonischem Input.** Der Handover-/Evidence-Input
   ist Pflicht; fehlende Pflichtfelder sind BLOCKING. Der historische
   deterministische Ersatzpfad und die Tests, die ihn festschreiben, sind
   entfernt. Nachgewiesen an einem Negativpfad-Test **am produktiven Aufrufer**.
3. **Der Sonar-Gate-Pfad hat genau eine Wahrheit.** Gegen die real gepinnte
   Sonar-Version genau eine Response-Form; die zweite Stage-Oberflaeche
   entfaellt; fehlende Fingerprint-Evidenz laeuft ausschliesslich ueber
   `MissingFingerprintEvidenceSource` fail-closed. **Realitaetsnachweis gegen
   die laufende Sonar-Instanz** (`http://localhost:9901`, Zugang in `.env`) —
   gruene Unit-Tests sind Voraussetzung, nie Nachweis.
4. **Der Regex-Freitext-Pfad ist entfernt, und FK-11 ist korrigiert.** Beides
   im selben Diff — das eine ohne das andere ist keine Erledigung.
   - Code: nach gescheiterter Schemavalidierung ausschliesslich der begrenzte
     Retry, danach FAIL. Kein Urteil aus Freitext, kein toter Regex-Rest.
   - **Konzept: FK-11 §320 wird korrigiert, nicht kommentiert.** Die dreistufige
     Auswertung verliert Stufe 3; die Beschreibung sagt danach, was gilt, nicht
     was einmal galt. Ein Konzept, das etwas anderes schreibt als der Code, ist
     an der Stelle nachzuziehen — ein „Hinweis, dass Stufe 3 nicht mehr
     verwendet wird" erfuellt das nicht (PO-Praezisierung 2026-08-04).
   - Der Fehlerpfad macht die **Ursache auffindbar**: welcher Evaluator,
     welches Modell, welche Schemaverletzung, welcher Response-Ausschnitt. Ein
     FAIL, das nur „Schema verletzt" sagt, verschiebt das Problem vom Fallback
     in ein Protokoll, das niemand liest.
   - Pruefe im selben Zug, ob weitere Konzeptstellen die dreistufige Auswertung
     oder den Regex-Fallback beschreiben (FK-27, FK-33, FK-69 und die
     formal-Specs), und zieh sie mit. Halb nachgezogen ist ZERO-DEBT-Verstoss.
5. **Der Pruefpunkt aus AG3-191 haelt:** `resolve_default_options` und
   `**overrides` existieren nicht mehr.
6. **Es gibt keinen weiteren unbenannten Urteils-Fallback.** Nachgewiesen durch
   eine **systematische** Inventur, die nicht auf Textsuche nach „legacy"/
   „fallback" beruht: jeder `.get()` ohne Mitgliedschaftspruefung, jeder
   `or`-Default, jeder optionale Parameter mit stillem Ersatzverhalten und
   jeder `except`, der ein Urteil weiterreicht, im `verify_system` ist bewertet
   und im Ergebnis benannt. Genau diese Klasse hat AG3-191 uebersehen.
7. **Volle Suite gruen** (Jenkins), `ruff` clean, `mypy --strict`, alle
   deterministischen Konzept-Gates; Decision Record mit Betroffenheitsmatrix.

## Definition of Done

- AC 1-7 erfuellt, jedes mit benanntem Beleg (Kommando, Ausgabe, Testname).
- Coverage haelt die 85-%-Schwelle.
- Unabhaengiges Codex-Review bis zum Abbruchkriterium aus `CLAUDE.md`.

## Guardrail-Referenzen

- `CLAUDE.md` „KEINE KOMPATIBILITAETSSCHICHTEN — AUSNAHMSLOS"
- `CLAUDE.md` „NO ERROR BYPASSING", „FAIL-CLOSED"
- `CLAUDE.md` „REALITAETSNACHWEIS AN FREMDSYSTEM-GRENZEN" — AC 3
- `CLAUDE.md` ZERO DEBT — „Schuld, die wie ein Entwurf aussieht, kostet mehr
  als Schuld, die wie ein Fehler aussieht."
