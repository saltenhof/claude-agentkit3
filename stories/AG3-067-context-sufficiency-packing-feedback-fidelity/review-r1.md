OVERALL CHANGES-REQUESTED

**Konzept-Vollstaendigkeit: WEAK**

- WARNING: FK-37 Loader-/Bezugsweg-Vollständigkeit ist nicht vollständig spezifiziert. Die Story fordert vier Loader (`story_spec`, `handover`, `concept_excerpt`, `arch_references`) in `stories/AG3-067-context-sufficiency-packing-feedback-fidelity/story.md:30` und AC1 `:45`; FK-37 verlangt aber für alle 6 Felder einen kanonischen Bezugsweg, inkl. caller-seitiger Einspeisung von `diff_summary` und `evidence_manifest` aus `context.json` (`concept/technical-design/37_verify_context_und_qa_bundle.md:369`, `:376-385`).  
  Fix: AC ergänzen: `diff_summary` und `evidence_manifest` müssen caller-seitig aus `context.json` übernommen, validiert und negativ getestet werden.

- ERROR: `ConformanceService.check_fidelity(feedback)` ist fachlich/technisch unscharf bzw. falsch. Die Story nennt diese Fassade in `story.md:33` und `:39`; FK-32 definiert `check_fidelity(level, evaluator, context)` mit `level="feedback"` und `expected_checks=[f"{level}_fidelity"]` (`concept/technical-design/32_dokumententreue_conformance_service.md:123-128`, `:160-169`). Im realen Source gibt es noch keinen `ConformanceService`/`check_fidelity`.  
  Fix: Story auf `check_fidelity(level="feedback", context=...)` korrigieren und klar sagen, ob AG3-063 harte Voraussetzung ist oder ob gegen einen Port/Adapter abstrahiert wird.

**AC-Schaerfe: FAIL**

- ERROR: Mandatory-Target-Rückkopplung ist gegen das reale Finding-Modell nicht implementierbar beschrieben. Die Story sagt, `Finding.source` kenne `adversarial_mandatory_target` (`story.md:23`) und fordert Findings aus `mandatory_target_results` (`story.md:34`, `:50`). Das reale `Finding` hat aber nur `layer`, `check`, `severity`, `message`, `trust_class`, `file_path`, `line_number`, `suggestion` (`src/agentkit/verify_system/protocols.py:206-213`). FK-38 zeigt nur Pseudocode mit `source/check_id/status` (`concept/technical-design/38_verify_feedback_und_doctreue_schleife.md:239-248`).  
  Fix: AC konkretisieren, wie `mandatory_target_results` in das reale `Finding`/`RemediationFeedback`-Modell gemappt wird, z. B. `layer="adversarial"`, `check=<target_id>`, `severity=BLOCKING`, plus Test auf `feedback.json`.

- WARNING: AC7 ist nicht prüfbar genug: “Assertion/Review” in `story.md:51` ist kein deterministisches Akzeptanzkriterium.  
  Fix: durch konkrete Tests/Checks ersetzen, z. B. kein neues produktives `*bundle*builder*` neben `build_review_bundle`, und Layer-2-Pfad nutzt genau den erweiterten Builder.

- WARNING: AC4 sagt “sechs Felder gesamt” (`story.md:48`), aber das reale `ReviewBundle` hat bereits operative Metadatenfelder (`story_id`, `acceptance_criteria`, `previous_findings`, `qa_cycle_round`) neben Kontextfeldern (`src/agentkit/verify_system/llm_evaluator/bundle.py:62-69`).  
  Fix: formulieren als “sechs semantische ContextBundle-Felder plus bestehende operative ReviewBundle-Metadaten”.

**Klarheit: WEAK**

- ERROR: Die Ist-Zustands-Evidenz “Grep → 0 Treffer” für `feedback_fidelity`/`doc-fidelity-feedback.md` ist falsch bzw. vermischt zwei Befunde (`story.md:22`). `evaluate_feedback_fidelity` existiert im Closure-Port (`src/agentkit/closure/post_merge_finalization/finalization.py:63-67`), wird vor Postflight aufgerufen (`:147-150`) und hat einen produktiven Stub-Port (`src/agentkit/closure/runtime_ports.py:208-218`). Der fehlende Teil ist der echte Evaluator/Prompt, nicht der Closure-Aufruf.  
  Fix: ersetzen durch: “Prompt `doc-fidelity-feedback.md` und produktiver Evaluator/expected_check `feedback_fidelity` fehlen; Closure-Port und non-blocking Stub existieren.”

- WARNING: “vierfeldrig” in `story.md:17` ist irreführend, weil `ReviewBundle` acht Felder hat (`bundle.py:62-69`). Gemeint ist offenbar das FK-27-vier-Textinput-Modell.  
  Fix: präzise trennen: “Layer2ReviewInput ist vierfeldrig; ReviewBundle enthält weitere operative Felder, aber nicht `arch_references`/`evidence_manifest`.”

**Kontext-Sinnhaftigkeit: FAIL**

- ERROR: Realer Layer-2-Integrationsanker fehlt in der Story. Der Code ruft `build_review_bundle` in `run_layer2_llm` auf (`src/agentkit/verify_system/llm_evaluator/layer2_integration.py:87-93`), und `VerifySystem` geht über `run_layer2_llm_failclosed` (`src/agentkit/verify_system/system.py:1653-1660`). Die Story fokussiert `bundle.py`, erwähnt aber den realen Pre-Step-Einbaupunkt nicht.  
  Fix: Scope/AC ergänzen: Sufficiency + Packing müssen vor `runner.run(...)` in `llm_evaluator/layer2_integration.py` bzw. dem realen Layer-2-Pfad verdrahtet werden.

- WARNING: `status.yaml` ist nicht konsistent mit dem Story-Index: AG3-101 hängt von AG3-067 ab (`var/concept-gap-analysis/_STORY_INDEX.md:142`), aber `unblocks: []` steht in `stories/AG3-067-context-sufficiency-packing-feedback-fidelity/status.yaml:12`.  
  Fix: `unblocks` um `AG3-101` ergänzen oder begründen, warum reverse dependencies in `status.yaml` bewusst nicht gepflegt werden.

**Must-Fix**

1. Falsche `feedback_fidelity`-Ist-Zustandsbehauptung korrigieren: Port/Aufruf/Stub existieren, echter Evaluator/Prompt fehlt.
2. Mandatory-Target-Rückkopplung gegen das reale `Finding`/`RemediationFeedback`-Modell spezifizieren.
3. FK-37 6-Feld-Bezugswege vollständig machen, inkl. caller-seitigem `diff_summary` und `evidence_manifest`.
4. Realen Layer-2-Einbaupunkt (`layer2_integration.py`/`run_layer2_llm`) als AC/Scope-Anker aufnehmen.
5. `ConformanceService`-Aufrufsignatur und AG3-063-Abhängigkeit klären; keine `check_fidelity(feedback)`-Pseudo-Fassade stehen lassen.
