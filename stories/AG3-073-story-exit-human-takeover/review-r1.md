OVERALL: CHANGES-REQUESTED

**Konzept-Vollstaendigkeit: FAIL**
- ERROR: §58.7 ist nicht umgesetzt: FK-58 fordert „Exit erst nach ausdruecklicher Pruefung der Alternativen: Standardvertrag, Reklassifikation, Story-Split“ ([FK-58](T:/codebase/claude-agentkit3/concept/technical-design/58_story_exit_human_takeover_handoff.md:191)). Die Story zitiert das zwar ([story.md](T:/codebase/claude-agentkit3/stories/AG3-073-story-exit-human-takeover/story.md:12)), aber kein AC erzwingt diese Pruefung ([story.md](T:/codebase/claude-agentkit3/stories/AG3-073-story-exit-human-takeover/story.md:62)).
  Fix: `story_exit_record.json`/Dossier brauchen ein typisiertes `alternative_review` mit `standard_contract_checked`, `reclassification_checked`, `split_checked`, jeweiliger Ablehnung und Exit-Gate-Negativtests bei fehlender/leer begruendeter Alternative.
- ERROR: §58.3 wird zu eng auf Enum-Validierung reduziert. FK-58 verbietet Exit fuer „normale Schwierigkeit“, „Agent-Unsicherheit“, „uebliche Remediation“ und split/replan-loesbare Faelle ([FK-58](T:/codebase/claude-agentkit3/concept/technical-design/58_story_exit_human_takeover_handoff.md:132)); die Story sagt aber „Die Enum ist der Owner der Zulaessigkeitspruefung“ ([story.md](T:/codebase/claude-agentkit3/stories/AG3-073-story-exit-human-takeover/story.md:41)).
  Fix: Enum nur als Reason-Code-Owner definieren; Zulaessigkeit separat als Kontext-/Alternativenpruefung modellieren und testen.

**AC-Schaerfe: WEAK**
- ERROR: AC8 „Orchestrator-/Agent-Selbstentscheidung kann den Exit nicht ausloesen“ ist nicht testbar genug ([story.md](T:/codebase/claude-agentkit3/stories/AG3-073-story-exit-human-takeover/story.md:70)). Es fehlt, welche API/Service-Methode welchen `principal_type`/`source_component` ablehnen muss.
  Fix: konkrete Contract-Grenze nennen: z. B. Service akzeptiert nur `source_component=human_cli` plus offiziellen Capability/Admin-Verdict; Tests fuer direkte Service-Aufrufe mit Orchestrator/Worker-Principal.
- WARNING: AC4 verlangt „korrektes Schema/Producer“ ([story.md](T:/codebase/claude-agentkit3/stories/AG3-073-story-exit-human-takeover/story.md:66)), aber nennt keine Schema-/Envelope-/Producer-Owner.
  Fix: konkrete Pydantic-/JSON-Schema-Owner und Producer-ID je Artefakt festlegen.

**Klarheit/Eindeutigkeit: FAIL**
- ERROR: Branch-Guard/Admin-Pfad ist widerspruechlich. Die Story verlangt `exit-story` als „einziger Exit-Pfad“ ([story.md](T:/codebase/claude-agentkit3/stories/AG3-073-story-exit-human-takeover/story.md:40)), macht die Allowlist-Aufnahme aber optional „falls trivial“/Folgepunkt ([story.md](T:/codebase/claude-agentkit3/stories/AG3-073-story-exit-human-takeover/story.md:33), [story.md](T:/codebase/claude-agentkit3/stories/AG3-073-story-exit-human-takeover/story.md:59)). Real fehlen `exit-story` in `ADMIN_SUBCOMMANDS` ([operations.py](T:/codebase/claude-agentkit3/src/agentkit/governance/principal_capabilities/operations.py:168)) und BranchGuard-Allowlist ([branch_guard.py](T:/codebase/claude-agentkit3/src/agentkit/governance/guards/branch_guard.py:23)).
  Fix: Entweder hart in Scope und AC aufnehmen, oder Story als blockiert durch AG3-087 markieren. Kein „falls trivial“ bei offiziellem einzigem Pfad.
- NIT: `operations.py:168`/`branch_guard.py` sind basename-only-Anker. Sie existieren, aber bitte volle Pfade nennen.

**Kontext-Sinnhaftigkeit: FAIL**
- ERROR: `BindingDeleteScope` wird als Teardown-Pfad fuer Lock/Session/Guard-Regime verkauft ([story.md](T:/codebase/claude-agentkit3/stories/AG3-073-story-exit-human-takeover/story.md:50), [story.md](T:/codebase/claude-agentkit3/stories/AG3-073-story-exit-human-takeover/story.md:69)). Real ist `BindingDeleteScope` nur der run-scoped Binding-Schluessel ([records.py](T:/codebase/claude-agentkit3/src/agentkit/control_plane/records.py:18)); Lock-/Event-Teardown passiert ueber `commit_operation_with_side_effects` ([runtime.py](T:/codebase/claude-agentkit3/src/agentkit/control_plane/runtime.py:1229)), Export-/Guard-Deaktivierung ueber `Governance.deactivate_locks` ([runner.py](T:/codebase/claude-agentkit3/src/agentkit/governance/runner.py:265)).
  Fix: Exit-Service muss die echten Owner nennen: neue exit-spezifische Control-Plane-Operation fuer Binding/Lock/Event-Atomik plus Governance-Lockexport-Cleanup, ohne normale Closure aufzurufen.
- PASS-Ankercheck: `FK-58 §58.2-§58.10` und `FK-59 §59.6.2` existieren. Die Ist-Zustand-Claims „keine Exit-Begriffe unter src/agentkit“, CLI ohne `exit-story`, `engine.py:751`, Runtime/ProjectEdge/StoryStatus/ControlPlaneRecord-Anker sind verifiziert.

**Must-Fix ERRORs**
1. Alternativenpruefung aus FK-58 §58.7 als Record-/Dossier-/Gate-/Testpflicht ergaenzen.
2. Zulassigkeit nicht der Reason-Enum zuschieben; Kontextverbote aus §58.3 fail-closed modellieren.
3. Human-only/Admin-Pfad testbar gegen Orchestrator-/Agent-Selbstentscheidung absichern.
4. BranchGuard/`ADMIN_SUBCOMMANDS`-Ownerentscheidung hart machen, nicht optional.
5. Teardown-Owner korrigieren: `BindingDeleteScope` ist nicht der Lock-/Guard-Regime-Teardown.
