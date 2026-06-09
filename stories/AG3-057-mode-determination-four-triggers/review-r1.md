OVERALL CHANGES-REQUESTED

**1) Konzept-Vollstaendigkeit: WEAK**

ERROR: `Pflichtfeld fehlt -> Exploration` aus FK-23 ist nicht vollständig in ACs operationalisiert.  
Evidence: `concept/technical-design/23_modusermittlung_exploration_change_frame.md:144-147`; `stories/AG3-057-mode-determination-four-triggers/story.md:57-58`.  
Fix: Explizit definieren/testen, was bei fehlendem `new_structures`, fehlendem `concept_paths`-Attribut und fehlenden StoryService-Feldern passiert. Keine impliziten Bool-Defaults, wenn das Feld Pflicht ist.

ERROR: Nicht-code Storys werden in der Story als `EXECUTION` modelliert, kollidieren aber mit dem konsolidierten v3-Modell `execution_route=None`.  
Evidence: `stories/AG3-057-mode-determination-four-triggers/story.md:34-35`, `:44`, `:59`; `concept/technical-design/24_story_type_mode_terminalitaet.md:177-181`; `src/agentkit/story_context_manager/types.py:75-82`; `src/agentkit/story_context_manager/models.py:395-400`.  
Fix: `determine_mode` entweder nur für impl/bugfix aufrufen oder Rückgabe `StoryMode | None`; AC6 auf `None`/“keine Trigger-Auswertung” ändern.

**2) AC-Schaerfe: FAIL**

ERROR: AC7 behauptet, `routing_rules` route unverändert korrekt; für Bugfix-Exploration stimmt das real nicht.  
Evidence: `stories/AG3-057-mode-determination-four-triggers/story.md:20`, `:60`; `src/agentkit/story_context_manager/routing_rules.py:36-41`; `src/agentkit/story_context_manager/types.py:57-73`; `src/agentkit/process/language/definitions.py:107-117`; `tests/integration/pipeline_engine/test_pipeline_runner.py:447-449`.  
Fix: AC erweitern: Bugfix mit `execution_route=EXPLORATION` muss tatsächlich `setup -> exploration -> implementation -> closure` laufen, inkl. Workflow/Profile/Registry-Anpassung und Test-Update.

WARNING: `project_root` ist widersprüchlich spezifiziert: Signatur verlangt `Path`, AC fordert “fehlendes `project_root`”.  
Evidence: `stories/AG3-057-mode-determination-four-triggers/story.md:34`, `:43`, `:58`; `concept/technical-design/22_setup_preflight_worktree_guard_activation.md:824-828`.  
Fix: Signatur zu `project_root: Path | None = None` ändern oder Fallback-AC entfernen.

**3) Klarheit/Eindeutigkeit: WEAK**

ERROR: Autoritative Feld-Owner sind nicht eindeutig. `change_impact`/`concept_quality` existieren bereits in `Story`, `concept_refs` existiert in `StorySpecification`, aber die Story fordert zusätzlich `concept_paths`. Das riskiert eine zweite Wahrheit.  
Evidence: `stories/AG3-057-mode-determination-four-triggers/story.md:27-32`, `:45`; `src/agentkit/story_context_manager/story_model.py:143`, `:194-195`; `src/agentkit/state_backend/store/story_repository.py:418-426`; `concept/technical-design/37_verify_context_und_qa_bundle.md:447-451`.  
Fix: Präzise festlegen: vorhandene `Story.change_impact`/`Story.concept_quality` verwenden; `concept_refs` zu `concept_paths` mappen/umbenennen oder als Legacy ablösen; `new_structures`/`vectordb_conflict` mit eindeutigem Persistenz-Owner ergänzen.

**4) Kontext-Sinnhaftigkeit: FAIL**

ERROR: Ist-Zustand-Anker sind nur teilweise korrekt. `context_builder.py:155/168/227/250` und `models.py:316/395` stimmen; die Aussage “routing_rules routet unverändert korrekt” ist aber für Bugfix falsch.  
Evidence: `src/agentkit/governance/setup_preflight_gate/context_builder.py:155`, `:168`, `:227`, `:250`; `src/agentkit/story_context_manager/models.py:316`, `:395`; Gegenbeleg `src/agentkit/process/language/definitions.py:107-117` und `tests/unit/bootstrap/test_pipeline_handler_registry.py:89-98`.  
Fix: Story muss Workflow/Profile/Handler-Registry als In-Scope aufnehmen oder Bugfix aus dem 4-Trigger-Modell herausnehmen. Letzteres widerspricht FK-22/FK-23.

**Must-Fix**

1. Non-code Rückgabe/Wiring auf `execution_route=None` korrigieren.
2. Bugfix-Exploration real in Workflow/Profile/Registry aufnehmen und ACs dafür ergänzen.
3. Autoritative Feld-Owner und `concept_refs`/`concept_paths`-Mapping eindeutig spezifizieren.
4. Fehlende Pflichtfelder vollständig fail-closed testen, besonders `new_structures`.
5. `project_root`-Signatur/Fallback widerspruchsfrei machen.
