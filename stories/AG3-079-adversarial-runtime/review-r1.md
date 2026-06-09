OVERALL: CHANGES-REQUESTED

**1) Konzept-Vollstaendigkeit: FAIL**

- ERROR: FK-48 §48.2.2/§48.2.3 ist falsch geschnitten. FK verlangt mandatory targets nur aus Layer-2-Findings vom Typ `assertion_weakness` mit testbarem Negativfall und mit Feldern inkl. `addressed_part` ([48_adversarial_testing_runtime.md](T:/codebase/claude-agentkit3/concept/technical-design/48_adversarial_testing_runtime.md:279), :291-313, :363-376). Die Story erklärt die Ableitung aber als out-of-scope und “bereits in `spawn.py`” ([story.md](T:/codebase/claude-agentkit3/stories/AG3-079-adversarial-runtime/story.md:43)). Realer Code macht etwas anderes: `derive_targets()` nimmt jedes `Severity.BLOCKING` und hat kein `finding_type`/`addressed_part` ([spawn.py](T:/codebase/claude-agentkit3/src/agentkit/verify_system/adversarial_orchestrator/spawn.py:131), :147-158). Fix: Scope korrigieren: entweder Ableitungslogik nach FK-48 §48.2.2/§48.2.3 in AG3-079 aufnehmen oder eine harte Vorgänger-Story benennen, die exakt `assertion_weakness`, `addressed_part`, Prompt-Sektion und Ergebnisbindung liefert.

- ERROR: FK-11 §11.8 verlangt Telemetrie `llm_call` mit `role=adversarial_sparring` ([11_llm...md](T:/codebase/claude-agentkit3/concept/technical-design/11_llm_provider_browser_pools_prompt_execution.md:671), :675). Die Story zitiert das in den Quell-Konzepten ([story.md](T:/codebase/claude-agentkit3/stories/AG3-079-adversarial-runtime/story.md:11), deckt in Scope/AC aber nur das Domain-Event `adversarial_sparring` ab ([story.md](T:/codebase/claude-agentkit3/stories/AG3-079-adversarial-runtime/story.md:32), :52, :55-56). Fix: AC3/AC6/AC7 um `llm_call role=adversarial_sparring` ergänzen oder FK-konform erklären, welches Event der Integrity-Nachweis zählt.

**2) AC-Schaerfe: WEAK**

- ERROR: AC4 ist sprachlich und fachlich unscharf: “bestehende Tests landen in `tests/`” ([story.md](T:/codebase/claude-agentkit3/stories/AG3-079-adversarial-runtime/story.md:53)) vermischt bestehende Repo-Tests mit in der Sandbox erzeugten Tests. FK-48 §48.1.5 spricht von “Tests in Sandbox” und Promotion nach Validierung ([48_adversarial_testing_runtime.md](T:/codebase/claude-agentkit3/concept/technical-design/48_adversarial_testing_runtime.md:147), :151-166). Fix: AC in drei konkrete Pfade splitten: Sandbox-Test valid+pass -> `tests/`; Sandbox-Test valid+fail -> `tests/adversarial_quarantine/`; invalid/duplicate/dry-run-fail -> bleibt Sandbox. Dedup-Kriterium benennen.

- WARNING: AC8 ist nur halb testbar. “setzt das zugehoerige Layer-2-Finding auf mind. `partially_resolved`” ([story.md](T:/codebase/claude-agentkit3/stories/AG3-079-adversarial-runtime/story.md:57)) nennt weder Datenmodell noch Schreibort noch Mapping-Regel. Der bestehende Status ist `FindingResolutionStatus.PARTIALLY_RESOLVED` ([finding_resolution.py](T:/codebase/claude-agentkit3/src/agentkit/verify_system/remediation/finding_resolution.py:71)). Fix: AC muss Zielartefakt/Feedback-Modell, `target_id -> finding_id` Mapping und Statusfeld exakt nennen.

**3) Klarheit/Eindeutigkeit: FAIL**

- ERROR: Sandbox-Pfad widerspricht sich. Quell-Konzept-Zusammenfassung und FK-11 nennen `_temp/adversarial/{story_id}/` ([story.md](T:/codebase/claude-agentkit3/stories/AG3-079-adversarial-runtime/story.md:7); [11_llm...md](T:/codebase/claude-agentkit3/concept/technical-design/11_llm_provider_browser_pools_prompt_execution.md:654)), die Ist-Zustand-Story und Code-SSOT nutzen `_temp/adversarial/{story_id}/{epoch}/` ([story.md](T:/codebase/claude-agentkit3/stories/AG3-079-adversarial-runtime/story.md:20); [qa_artifact_names.py](T:/codebase/claude-agentkit3/src/agentkit/core_types/qa_artifact_names.py:115), :117). AC5 liest aber wieder `_temp/adversarial/{story_id}/result.json` ([story.md](T:/codebase/claude-agentkit3/stories/AG3-079-adversarial-runtime/story.md:34)). Fix: Einen kanonischen Pfad festlegen, vermutlich codekonform mit `{epoch}`, und alle result/test/promotion-Pfade angleichen.

- WARNING: “Ist der Transport noch nicht real, an der Pool-Grenze testbar halten” ([story.md](T:/codebase/claude-agentkit3/stories/AG3-079-adversarial-runtime/story.md:77)) kollidiert mit `depends_on: AG3-065` ([status.yaml](T:/codebase/claude-agentkit3/stories/AG3-079-adversarial-runtime/status.yaml:8)). Fix: Entweder AG3-065 als harte Voraussetzung behandeln und den Fallback streichen, oder die Story in Transport-Adapter-Abstraktion plus Runtime splitten.

**4) Kontext-Sinnhaftigkeit: FAIL**

- ERROR: Producer-Vorgabe kollidiert mit dem bestehenden Code-SSOT. Story verlangt Producer `qa-adversarial` ([story.md](T:/codebase/claude-agentkit3/stories/AG3-079-adversarial-runtime/story.md:34), :54, :67). Der Code erklärt aber `ADVERSARIAL_PRODUCER = "verify-system.layer-3-adversarial"` als kanonisch und `qa-adversarial` ausdrücklich nur als illustrative FK-Bezeichnung ([qa_artifact_names.py](T:/codebase/claude-agentkit3/src/agentkit/core_types/qa_artifact_names.py:79), :83-90). Integrity-Gate prüft genau diesen kanonischen Producer ([dimensions.py](T:/codebase/claude-agentkit3/src/agentkit/governance/integrity_gate/dimensions.py:557)). Fix: Story muss den kanonischen Producer verwenden oder explizit eine Konzept-/Code-SSOT-Änderung beauftragen.

- ERROR: Ist-Zustand-Behauptungen sind falsch. `extract_mandatory_targets` existiert nicht in `spawn.py`; Suche im Repo liefert keinen Treffer, `spawn.py` hat nur `derive_targets()` ([spawn.py](T:/codebase/claude-agentkit3/src/agentkit/verify_system/adversarial_orchestrator/spawn.py:127)). Außerdem behauptet die Story `_dimension_specs.py` sei “ohne `adversarial`-Treffer” ([story.md](T:/codebase/claude-agentkit3/stories/AG3-079-adversarial-runtime/story.md:21)); tatsächlich enthält die Datei `NO_ADVERSARIAL`, `ADVERSARIAL_STAGE`, `ADVERSARIAL_PRODUCER` ([ _dimension_specs.py](T:/codebase/claude-agentkit3/src/agentkit/governance/integrity_gate/_dimension_specs.py:16), :37, :83-86). Fix: Ist-Zustand präzisieren: vorhanden ist Adversarial-Envelope-Gate, fehlend ist der Telemetrie-/Sparring-Nachweis.

Must-fix ERROR list:

1. Producer `qa-adversarial` durch kanonischen `verify-system.layer-3-adversarial` ersetzen oder SSOT-Änderung explizit machen.
2. Mandatory-target-Ableitung nicht fälschlich als erledigt/out-of-scope behaupten; FK-48 §48.2.2/§48.2.3 vollständig schneiden.
3. `llm_call role=adversarial_sparring` in Scope/AC/Gate-Nachweis aufnehmen.
4. Sandbox/result-Pfad auf eine kanonische Form bringen, inklusive `{epoch}`-Entscheidung.
5. Falsche Ist-Zustand-Anker korrigieren: kein `extract_mandatory_targets`; `_dimension_specs.py` hat bereits Adversarial-Bezüge.
