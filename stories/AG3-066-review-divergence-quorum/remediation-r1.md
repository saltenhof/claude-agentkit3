# AG3-066 — Remediation r1 (Antwort auf review-r1.md)

**Datum:** 2026-06-07
**Scope der Remediation:** ausschliesslich `story.md` (+ Pruefung `status.yaml`). Kein Produktionscode, keine Tests, keine `concept/`-Dateien angefasst.
**Autoritative Quellen geprueft:** `concept/technical-design/34_llm_bewertungen_adversarial_testing_runtime.md` §34.8 (`:477-593`); `src/agentkit/telemetry/hooks/divergence_hook.py`; `src/agentkit/telemetry/events.py:64`; `var/concept-gap-analysis/_STORY_INDEX.md:57,144`; `var/concept-gap-analysis/gap-fk-26-35.md:404-429`.

---

## Must-Fix ERRORs

### ERROR 1 — `divergent` fehlt in Dataclass, Event-Payload und AC
**Beleg:** FK `:538` `divergent: bool` (Dataclass); FK `:580` Event-Feld `divergent`.
**Behebung:** `divergent: bool` in die Dataclass-Feldliste aufgenommen (Quell-Konzept-Block + Scope §2.1.1: exakte FK-Felder `reviewer_a/reviewer_b/verdict_a/verdict_b/divergent/quorum_triggered/final_verdict`). In das Event-Payload aufgenommen (Scope §2.1.4 + AC5: Payload traegt `story_id/reviewer_a/reviewer_b/divergent/quorum_triggered/final_verdict`). AC1 und AC5 assertieren den Feldsatz inkl. `divergent` jetzt explizit.

### ERROR 2 — Widerspruch zum FK beim Nicht-Divergenz-Fall
**Beleg:** FK-Mermaid `:589` schreibt bei `divergent=False` ein `review_divergence`-Event mit `quorum_triggered=false`; alte Story verlangte „kein Event".
**Behebung:** Story an das zitierte FK ausgerichtet. Neuer Scope §2.1.5 und neues AC6: bei `divergent=False` emittiert der Hook **dennoch** ein `review_divergence`-Event mit `divergent=False`, `quorum_triggered=False`, `final_verdict=null`. Das alte „kein Event" wurde entfernt. Begruendung als Konzepttreue-Guardrail in §5 dokumentiert. (Kein FK geaendert — die Story folgt dem FK.)

### ERROR 3 — No-majority-Regel fuer dreistufige Verdikte fehlte
**Beleg:** Normalform `PASS`/`CONCERN`/`FAIL` (FK `:496-500`); altes AC4 garantierte keine 2-gegen-1-Mehrheit (z. B. `PASS`/`CONCERN`/`FAIL`).
**Behebung:** No-majority-Regel definiert: bei drei paarweise verschiedenen Verdikten → deterministisch **fail-closed strengstes Verdikt** nach Ordnung `PASS < CONCERN < FAIL` (Scope §2.1.1 `apply_quorum`, §2.1.2, AC4). AC4 fordert Tests fuer alle Mehrheits-Konstellationen **und** den No-majority-Fall (deterministisch testbar). FK-34 §34.8 kennt diese Regel nicht; die Code-Entscheidung ist als bewusste, dokumentierte Wahl gekennzeichnet und die FK-Prosa-Ergaenzung an **AG3-103** (doc-only, interne FK-Widersprueche/Defaults) geroutet (Scope §2.2, §5). Kein stilles Abweichen.

### ERROR 4 — AC1 testete nur Symbol-Existenz, nicht das Feldschema
**Beleg:** altes AC1 „Modul/Symbole vorhanden"; FK-Felder inkl. `divergent` `:531-540`.
**Behebung:** AC1 verschaerft auf exakte Dataclass-Felder, Typen und `frozen=True`; AC5 verschaerft auf den exakten Event-Payload-Feldsatz (inkl. „kein `score`/`routing`"). Beide AC fordern Schema-Assertionen, nicht nur Existenz.

### ERROR 5 — AG3-065 gleichzeitig konsumiert und optional (Dependency-Konflikt)
**Beleg:** alte Story konsumierte AG3-065 (`story.md:20,29,64`), beschrieb ihn aber zugleich als fallbackbar (`:35`); `status.yaml` und Index (`_STORY_INDEX.md:57`) listen nur `AG3-037, AG3-043`.
**Behebung — gewaehlter Zweig: „aus Scope entfernen" (scope-treu).** Der eigentliche Tiebreaker-LLM-Call gehoert laut FK-34 §34.8.3 (`:566-568`) dem **QA-Agenten/Layer-2-Pfad**, nicht diesem Modul; der Index-Cut von AG3-066 ist reine Logik + Scoring-Abloesung mit `depends_on: AG3-037, AG3-043`. Alle AG3-065-Verpflichtungen wurden aus Scope/AC/Hinweisen entfernt. `divergence.py` nimmt drei Verdikte als Funktionsargumente entgegen und macht **keinen** LLM-Call; die Reviewer-C-Beschaffung ist in §2.2 explizit an AG3-037/AG3-043 (Transport AG3-065) geroutet. Dadurch passt `status.yaml` (`AG3-037, AG3-043`) wieder zum Scope und zum Index — **keine** Dependency-Aenderung noetig, Scope nicht ausgeweitet.

### ERROR 6 — Tiebreaker-Orchestrierungsowner unklar (QA/Layer-2 vs. TelemetryHook)
**Beleg:** FK `:566-568` „QA-Agent steuert das Quorum"; alte Story fokussierte zugleich `DivergenceHook`-Umverdrahtung.
**Behebung:** Explizit festgelegt (neuer Owner-Abgrenzungs-Absatz in §1, plus §2.1.3, §2.2, §6): `telemetry/divergence.py` bleibt **pure Logik**; die QA-/Layer-2-Orchestrierung ruft Reviewer C; der `DivergenceHook` emittiert **nur Fakten** und macht **keinen** LLM-Call. AC5 fordert „kein LLM-Call im Hook" implizit ueber die reine Payload-/Logik-Umstellung; §2.1.3 sagt es direkt aus.

---

## WARNINGs

### WARNING (1.3) — Unbekannte Rohverdikte als `FAIL` nicht aus FK ableitbar
**Beleg:** FK `:512-514` `return VERDICT_NORMALIZATION.get(raw_verdict, raw_verdict)` (Passthrough); alte Story behauptete „unbekannt → fail-closed/strengster Wert gem. FK".
**Behebung:** Story FK-treu korrigiert auf **Passthrough** (`get(raw, raw)`) in Scope §2.1.1 und AC2 (Test: unbekannter Wert → unveraendert zurueck). Die fruehere falsche „gem. FK"-Begruendung entfernt. Die Frage, ob eine fail-closed-Haertung gewuenscht ist, ist als FK-Praezisierung an **AG3-103** geroutet (§2.2) — nicht still in der Code-Story abgewichen.

### WARNING (2/AC8) — AC8 unscharf gegen lokale Pflicht-Gates
**Beleg:** altes AC8 „vier Konzept-Gates" ohne Namen; CLAUDE/AGENTS verlangen zusaetzlich Jenkins/Sonar via `scripts/ci/check_remote_gates.ps1`.
**Behebung:** AC zu AC9 ausgebaut mit konkreten Befehlen (alle ueber `.venv\Scripts\python`): pytest unit/integration/contract (`-n0`, Chunks); mypy default **und** `--platform linux`; ruff; die vier real existierenden Konzept-Gates `scripts/ci/check_concept_frontmatter.py`, `scripts/ci/compile_formal_specs.py`, `scripts/ci/check_concept_code_contracts.py`, `scripts/ci/check_architecture_conformance.py`; Remote-Gates via `scripts/ci/check_remote_gates.ps1` (nach Commit/CI); Coverage ≥ 85 %.

---

## Code-Anker-Korrekturen (gegen den realen `divergence_hook.py`)

Alle Ist-Zustand-Anker auf die echten Zeilen praezisiert (vorher teils Sammelbereiche):
- `_SCORE_LOW`/`_SCORE_HIGH` → `divergence_hook.py:30-31` (vorher pauschal `:29-34`).
- `_PASS_VERDICTS` → `divergence_hook.py:34`.
- Payload `score`/`routing` → `divergence_hook.py:93-94`.
- Docstring „third reviewer out of scope" → `divergence_hook.py:8-11` (FK-Wortlaut „THEME-009 (verify-system.A9)" uebernommen).
- binaere Divergenz/`_find_diverging_pair` → `divergence_hook.py:147-166`; `_is_pass`/`_PASS_VERDICTS` `:143-144`.
- `EventType.REVIEW_DIVERGENCE` → `events.py:64`.
- FK-Anker durchgehend mit exakten Zeilen ergaenzt: §34.8.2 `:496-514`, Dataclass `:531-540`, `check_divergence` `:543-552`, Quorum-Ablauf/Owner `:555-568`, Event-Felder `:575-582`, Nicht-Divergenz-Event `:589`.
- Gap-Analyse-Anker → `var/concept-gap-analysis/gap-fk-26-35.md:404-429`. Index-Cut → `_STORY_INDEX.md:57`; AG3-103-Routing → `_STORY_INDEX.md:144`.

## Bestaetigter PASS-Teilbefund (kein Handlungsbedarf)
Der Reviewer bestaetigte die Ist-Zustand-Anker als wahr; nach Re-Read von `divergence_hook.py`/`events.py`/FK-34 bestaetigt diese Remediation das ebenfalls.

---

## status.yaml — Pruefung
`status.yaml` wurde geprueft: `depends_on: [AG3-037, AG3-043]` stimmt mit dem Index-Cut (`_STORY_INDEX.md:57`) und dem korrigierten Scope (ERROR-5 via „aus Scope entfernen") ueberein. Titel/Typ/Size korrekt. **Kein Feld falsch — keine Aenderung noetig.**

## Geaenderte Dateien
- `stories/AG3-066-review-divergence-quorum/story.md` (neu geschrieben, Template-Struktur AG3-057 beibehalten).
- `stories/AG3-066-review-divergence-quorum/remediation-r1.md` (dieser Report).
- `status.yaml`: nicht geaendert (geprueft, korrekt).
