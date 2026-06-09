OVERALL: CHANGES-REQUESTED

**1) Konzept-Vollstaendigkeit: FAIL**

- ERROR: FK-34 §34.8 verlangt `divergent` als Dataclass- und Event-Feld, die Story unterschlaegt es.  
  Evidence: `concept/technical-design/34_llm_bewertungen_adversarial_testing_runtime.md:538` `divergent: bool`; `:580` Event-Feld `divergent`. Story nennt bei `ReviewPairDivergence` nur `reviewer_a`/`reviewer_b`/`verdict_a`/`verdict_b`/`quorum_triggered`/`final_verdict` (`stories/.../story.md:28`) und beim Event nur `final_verdict`/`quorum_triggered` statt `score` (`:31`, `:44`).  
  Fix: `divergent` in Scope, AC und Payload-Schema aufnehmen.

- ERROR: Story widerspricht dem zitierten FK beim Nicht-Divergenz-Fall.  
  Evidence: FK-Mermaid schreibt bei `divergent=False` ein `review_divergence Event` mit `quorum_triggered=false` (`concept/.../34_llm...md:589`); Story verlangt dagegen "keine Divergenz, kein Tiebreaker, kein Event" (`stories/.../story.md:46`).  
  Fix: Entweder Story auf FK ausrichten und auch Nicht-Divergenz-Events spezifizieren, oder vorher FK-34 korrigieren. Nicht still abweichend implementieren.

- WARNING: Unbekannte Rohverdikte als `FAIL` sind nicht aus FK-34 §34.8 ableitbar.  
  Evidence: FK-Beispiel gibt `return VERDICT_NORMALIZATION.get(raw_verdict, raw_verdict)` vor (`concept/.../34_llm...md:512-514`); Story behauptet "unbekannter Wert → fail-closed/strengster Wert gem. FK" (`stories/.../story.md:26`).  
  Fix: Als bewusste Guardrail-Verschärfung mit Owner kennzeichnen oder FK vorher anpassen.

**2) AC-Schaerfe: FAIL**

- ERROR: AC4 ist nicht deterministisch testbar, weil bei drei Verdict-Werten kein 2-gegen-1 garantiert ist.  
  Evidence: Normalform ist `PASS`/`CONCERN`/`FAIL` (`stories/.../story.md:26`, FK `concept/.../34_llm...md:496-500`); AC4 sagt nur "final_verdict per Mehrheit 2-gegen-1" (`stories/.../story.md:43`). Für `PASS` vs `FAIL` und Tiebreaker `CONCERN` gibt es keine Mehrheit.  
  Fix: No-majority-Regel definieren: z.B. fail-closed strengstes Verdict, Retry, oder expliziter ERROR-Zustand.

- ERROR: AC1 testet nur Symbol-Existenz, nicht das normative Feldschema.  
  Evidence: AC1 "Modul/Symbole vorhanden" (`stories/.../story.md:40`), FK-Felder inkl. `divergent` stehen in `concept/.../34_llm...md:531-540`.  
  Fix: AC um exakte Dataclass-Felder, Frozen/Typisierung und Event-Payload-Felder ergänzen.

- WARNING: AC8 ist unscharf und unvollständig gegen lokale Pflicht-Gates.  
  Evidence: "vier Konzept-Gates" ohne Namen (`stories/.../story.md:47`); AGENTS/CLAUDE verlangen zusätzlich Jenkins/Sonar-Gates via `scripts/ci/check_remote_gates.ps1`.  
  Fix: Konkrete Befehle aufführen, inklusive `scripts/ci/check_concept_frontmatter.py`, `scripts/ci/compile_formal_specs.py`, Remote-Gates, pytest/ruff/mypy/Coverage.

**3) Klarheit/Eindeutigkeit: FAIL**

- ERROR: AG3-065 ist gleichzeitig konsumiert und optional/fallbackartig beschrieben.  
  Evidence: Story sagt "Tiebreaker-LLM-Call nutzt den Verify-LLM-Transport (AG3-065)" (`stories/.../story.md:29`, `:64`), aber auch "bei fehlendem Transport gegen den LlmClient-Port abstrahieren" (`:35`).  
  Fix: Entscheiden: entweder `AG3-065` harte Voraussetzung oder Scope nur gegen bestehenden `LlmClient`-Port ohne realen Transport.

- ERROR: Owner des Tiebreaker-LLM-Calls ist unklar.  
  Evidence: FK sagt "QA-Agent ... steuert das Quorum" und Pipeline delegiert (`concept/.../34_llm...md:566-568`); Story fokussiert zugleich auf `DivergenceHook`-Umverdrahtung (`stories/.../story.md:20`, `:30`).  
  Fix: Explizit festlegen: `telemetry/divergence.py` bleibt pure Logik; QA/Layer-2-Orchestrierung ruft Reviewer C; `DivergenceHook` emittiert nur Fakten und macht keinen LLM-Call.

**4) Kontext-Sinnhaftigkeit: FAIL**

- ERROR: Story-Dependency passt nicht zum eigenen Scope.  
  Evidence: `status.yaml` hängt nur von `AG3-037`, `AG3-043` ab (`stories/.../status.yaml:8-10`); Story konsumiert aber AG3-065 (`stories/.../story.md:20`, `:29`, `:64`). Index bestätigt AG3-066 nur mit `AG3-037, AG3-043` (`var/concept-gap-analysis/_STORY_INDEX.md:57`).  
  Fix: `AG3-065` als harte Dependency ergänzen oder alle AG3-065-Verpflichtungen aus Scope/AC entfernen.

- PASS-Teilbefund: Die behaupteten Ist-Zustand-Dateianker sind wahr.  
  `DivergenceHook` Docstring "third reviewer out of scope" steht in `src/agentkit/telemetry/hooks/divergence_hook.py:8-11`; `_SCORE_LOW`/`_SCORE_HIGH` und `_PASS_VERDICTS` in `:29-34`; Payload `score`/`routing` in `:93-94`; `_find_diverging_pair` binär Pass-vs-nicht-Pass in `:147-166`. `src/agentkit/telemetry/divergence.py` existiert nicht. FK-Anchor `34.8` und FK-34-130..132 existieren (`concept/.../34_llm...md:477`, `:490`, `:521`). Gap-Analyse-Anker existiert (`var/concept-gap-analysis/gap-fk-26-35.md:404`, `:412-429`).

**Must-Fix ERRORs**

1. `divergent` in Dataclass, Event-Payload und AC aufnehmen.  
2. Nicht-Divergenz-Event-Konflikt mit FK-34 §34.8 auflösen.  
3. No-majority-Regel für dreistufige Verdikte definieren.  
4. AC1 auf exaktes Feld-/Payload-Schema schärfen.  
5. AG3-065 als echte Dependency ergänzen oder aus Scope entfernen.  
6. Tiebreaker-Orchestrierungsowner klarziehen: QA/Layer-2 vs. TelemetryHook.
