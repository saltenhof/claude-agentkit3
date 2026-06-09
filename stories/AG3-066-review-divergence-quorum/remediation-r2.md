# AG3-066 — Remediation r2 (Antwort auf review-r2.md)

**Datum:** 2026-06-07
**Scope der Remediation:** ausschliesslich `story.md` (+ Pruefung `status.yaml`). Kein Produktionscode, keine Tests, keine `concept/`-Dateien angefasst.
**Autoritative Quellen (re-read und verifiziert):**
- `concept/technical-design/34_llm_bewertungen_adversarial_testing_runtime.md` §34.8 (`:477-593`; „Kap. 68"-Verweis `:572-573`; Event-Felder `:575-582`).
- `concept/technical-design/68_telemetrie_eventing_workflow_metriken.md` Frontmatter `authority_over: eventing/telemetry-hooks` (`:9-13`); `review_divergence`-Tabelle mit `score`/`routing` (`:362`).
- `src/agentkit/telemetry/events.py` (`MANDATORY_PAYLOAD_FIELDS` `:173-221`; `validate_event_payload` `:257-289`; `EventType.REVIEW_DIVERGENCE` `:64`).
- `tests/contract/telemetry/test_event_catalog.py` (`_EXPECTED_MANDATORY_FIELDS` `:112-141`; `test_mandatory_payload_fields_match_contract` `:149-150`).
- `src/agentkit/telemetry/risk_window/normalizer.py` (`REVIEW_DIVERGENCE → INTEGRITY` `:40`; `_EXCERPT_KEYS` mit `"score"` `:56-67`).
- `src/agentkit/telemetry/hooks/divergence_hook.py` (Payload `score`/`routing` `:93-94`).
- `var/concept-gap-analysis/_STORY_INDEX.md` (AG3-066-Cut `:57`; AG3-103 fuehrt FK-68 §68.2 als Owner `:144`).

---

## Round-2 Befund: NEW must-fix ERROR

### ERROR (r2) — FK-34/FK-68-Konflikt: Story stellt Payload auf FK-34-Felder um, waehrend FK-68 noch Eventing-Owner mit `score`/`routing`-Schema ist; reale Consumer tragen noch das alte Format

**Beleg (Reviewer, verifiziert):**
- FK-68 besitzt Telemetrie-/Eventing-/Telemetry-Hooks-Hoheit (`68_telemetrie...md:9-13`) und deklariert `review_divergence` noch mit `reviewer_a`/`reviewer_b`/`score (LOW/MEDIUM/HIGH)`/`routing` (`68_telemetrie...md:362`).
- FK-34 §34.8.4 schreibt den neuen Feldsatz `story_id`/`reviewer_a`/`reviewer_b`/`divergent`/`quorum_triggered`/`final_verdict` vor (`34_llm...md:575-582`) und verweist dafuer auf „Kap. 68" (`:572-573`) → echter FK-uebergreifender Widerspruch.
- Realer Consumer `EventNormalizer` haelt noch `"score"` und **kein** `divergent`/`quorum_triggered`/`final_verdict` im Audit-Excerpt (`normalizer.py:56-67`).
- Zusatzbefund beim Re-Read: `REVIEW_DIVERGENCE` ist **gar nicht** in `MANDATORY_PAYLOAD_FIELDS` (`events.py:173-221`) und im Contract-Pin (`test_event_catalog.py:112-141`) gelistet — das Feldschema war nie fail-closed erzwungen.

**Behebung — scope-treue Zwei-Teil-Aufloesung (keine `concept/`-Aenderung in dieser Code-Story):**

1. **Code-Schema-Migration end-to-end IN Scope (AG3-066 besitzt laut Index-Cut `:57` die Scoring-Abloesung):** §1-Konfliktcheck und Scope §2.1.4 benennen jetzt **alle** realen Schema-Owner/Consumer und ziehen sie auf den einen kanonischen FK-34-Feldsatz:
   - Hook-Payload (`divergence_hook.py:93-94`, `score`/`routing` → FK-34-Felder).
   - Neuer fail-closed-Pin `EventType.REVIEW_DIVERGENCE: ("story_id","reviewer_a","reviewer_b","divergent","quorum_triggered","final_verdict")` in `MANDATORY_PAYLOAD_FIELDS` (`events.py:173-221`).
   - Contract-Pin `_EXPECTED_MANDATORY_FIELDS` (`test_event_catalog.py:112-141`) mitgezogen, sonst kippt `test_mandatory_payload_fields_match_contract`.
   - `_EXCERPT_KEYS` des `EventNormalizer` (`normalizer.py:56-67`): toten `"score"`-Key durch `divergent`/`quorum_triggered`/`final_verdict` ersetzen; Normalizer-Unit-Test (`tests/unit/telemetry/risk_window/test_normalizer.py`) mitgezogen.
   - Neue Akzeptanzkriterien: **AC5a** (Pin + Contract-Pin + Excerpt-Mitzug, je mit Test) und AC8 konkretisiert auf `test_event_catalog.py` + Hook-/Normalizer-Tests.
2. **FK-68-Prosa-Angleichung OUT of Scope, an Owner geroutet:** Die FK-68 §68.2.2-Tabelle (`:362`, noch `score`/`routing`) ist eine `concept/`-Aenderung und darf hier nicht angefasst werden. Sie ist an **AG3-103** geroutet, das FK-68 §68.2 bereits explizit als doc-only-Owner-Scope fuehrt (`_STORY_INDEX.md:144`). Neuer §2.2-Out-of-Scope-Eintrag + §5-Konzepttreue-Absatz + §6-Hinweis. Bis AG3-103 nachzieht, ist der FK-68-Tabellenwert ein bekannter, hier gespiegelter Stale-Eintrag (WARNING-Charakter via Routing) — kein stiller Bruch.

Damit bleibt FK-68 alleiniger Eventing-Schema-Owner; AG3-066 zieht das **Code**-Schema FK-34-konform nach (innerhalb seines Cuts), AG3-103 zieht die **FK-68-Prosa** nach. Kein paralleles Divergenz-Format (SINGLE SOURCE OF TRUTH / FIX THE MODEL). Der Index-Cut und damit `status.yaml` (`depends_on: AG3-037, AG3-043`) bleiben unveraendert — der gewaehlte Branch fuegt **keine** neue Schema-Story-Abhaengigkeit hinzu, sondern haelt die Migration im eigenen Cut + Routing der Prosa.

---

## Per-Dimension-Verdikte aus review-r2 — Abdeckung

- **Konzept-Vollstaendigkeit (FAIL: unhandled FK-34/FK-68-Konflikt):** behoben durch expliziten Konflikt-Absatz (§1), Code-Migration in Scope (§2.1.4) und FK-68-Prosa-Routing an AG3-103 (§2.2).
- **AC-Schaerfe (FAIL: ACs deckten nicht alle Schema-Owner/Consumer):** behoben durch AC5a (`MANDATORY_PAYLOAD_FIELDS`, Contract-Pin, `_EXCERPT_KEYS`) und konkretisiertes AC8.
- **Kontext-Sinnhaftigkeit (FAIL: reale Telemetrie-Consumer kodieren noch `score`):** behoben — `EventNormalizer._EXCERPT_KEYS` und der Contract-Pin sind jetzt namentlich als mitzuziehende Consumer im Scope/AC.
- **Klarheit/Eindeutigkeit (WEAK: Orchestrierungs-Follow-up nur geroutet):** unveraendert korrekt geroutet (Reviewer-C-LLM-Call out-of-scope an QA/Layer-2 AG3-037/AG3-043, Transport AG3-065) — das war ein WEAK-Hinweis, kein must-fix; der Cut bleibt scope-treu.

---

## Code-Anker-Pruefung (gegen den realen Code, r2)

Alle in der Story zitierten Ist-Zustand-Anker erneut gegen den realen Code verifiziert; sie stimmen:
- `divergence_hook.py`: `_SCORE_LOW`/`_SCORE_HIGH` `:30-31`, `_PASS_VERDICTS` `:34`, Payload `score`/`routing` `:93-94`, Docstring „out of scope" `:8-11`, `_find_diverging_pair` `:147-166`, `_is_pass`/`_PASS_VERDICTS` `:143-144` — korrekt.
- `events.py`: `EventType.REVIEW_DIVERGENCE` `:64`, `MANDATORY_PAYLOAD_FIELDS` `:173-221` — korrekt; `REVIEW_DIVERGENCE` dort nicht vorhanden (jetzt in Scope ergaenzt).
- `normalizer.py`: `REVIEW_DIVERGENCE → INTEGRITY` `:40`, `_EXCERPT_KEYS` `:56-67` (mit `score`) — korrekt.
- `test_event_catalog.py`: `_EXPECTED_MANDATORY_FIELDS` `:112-141`, `test_mandatory_payload_fields_match_contract` `:149-150` — korrekt.
- FK-Anker: FK-68 `authority_over` `:9-13`, FK-68-Tabelle `:362`; FK-34 „Kap. 68" `:572-573`, Event-Felder `:575-582` — korrekt.
- Routing-Anker: AG3-066-Cut `_STORY_INDEX.md:57`; AG3-103 (FK-68 §68.2) `_STORY_INDEX.md:144` — korrekt.

---

## status.yaml — Pruefung
`depends_on: [AG3-037, AG3-043]` stimmt mit dem Index-Cut (`_STORY_INDEX.md:57`) und dem gewaehlten Aufloesungs-Branch (Code-Migration im eigenen Cut, FK-68-Prosa an AG3-103, **keine** neue Schema-Story-Dependency) ueberein. Titel/Typ/Size unveraendert korrekt. **Kein Feld falsch — keine Aenderung noetig.**

## Geaenderte Dateien
- `stories/AG3-066-review-divergence-quorum/story.md` (Quell-Konzepte um FK-68 ergaenzt; §1-Konfliktcheck + Consumer-Liste; Scope §2.1.4 end-to-end-Mitzug; §2.2 FK-68-Prosa-Routing an AG3-103; AC5a + AC8-Konkretisierung; §5/§6 ergaenzt; Template-Struktur AG3-057 beibehalten).
- `stories/AG3-066-review-divergence-quorum/remediation-r2.md` (dieser Report).
- `status.yaml`: nicht geaendert (geprueft, korrekt).
