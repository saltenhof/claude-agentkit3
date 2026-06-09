OVERALL CHANGES-REQUESTED

**1) Konzept-Vollstaendigkeit: FAIL**

ERROR: FK-37 §37.1.3 wird falsch abgebildet. Die Story nennt als “vier Vertrags-Pflichtpruefungen” `declared_surfaces_only`, Approval, Budget, Binding, aber FK-37 fordert `integration_target_matrix_passed`, `declared_surfaces_only`, `stabilization_budget_not_exhausted`, `stability_gate`; `integration_target_matrix_passed` fehlt als benannter Check/AC.
Evidence: [story.md](T:/codebase/claude-agentkit3/stories/AG3-069-integration-stabilization-machinery/story.md:36), [story.md](T:/codebase/claude-agentkit3/stories/AG3-069-integration-stabilization-machinery/story.md:53), [37_verify_context_und_qa_bundle.md](T:/codebase/claude-agentkit3/concept/technical-design/37_verify_context_und_qa_bundle.md:183).
Fix: Die vier FK-37-Checks exakt aufnehmen; Approval/Binding als zusaetzliche Manifest-Vorbedingungen modellieren, nicht als Ersatz fuer die FK-37-Liste.

ERROR: FK-05 §5.5-Mindestinhalt des Manifests ist unvollstaendig. Die Story fordert Surfaces/Seams, Version, Hash, Binding, aber nicht explizit `implementation_contract`, `target_seams`, `allowed_repos_paths`, `integration_targets`, `allowed_contract_changes`, `stabilization_budget`, `out_of_contract_examples`.
Evidence: [story.md](T:/codebase/claude-agentkit3/stories/AG3-069-integration-stabilization-machinery/story.md:29), [05_integration_stabilization_contract.md](T:/codebase/claude-agentkit3/concept/technical-design/05_integration_stabilization_contract.md:140).
Fix: Manifest-AC um alle FK-05 §5.5.2 Pflichtfelder erweitern.

ERROR: FK-05 §5.11 Closure-Regel fehlt als AC. Die Story registriert `stability_gate`, verlangt aber nicht, dass Closure fuer `integration_stabilization` nur nach `stability_gate=PASS`, erreichten Integrationszielen, ohne Manifest-Verletzung und ohne Replan/Split-Bedarf laufen darf.
Evidence: [story.md](T:/codebase/claude-agentkit3/stories/AG3-069-integration-stabilization-machinery/story.md:49), [05_integration_stabilization_contract.md](T:/codebase/claude-agentkit3/concept/technical-design/05_integration_stabilization_contract.md:323).
Fix: Closure-Precondition und Negativtest am Closure-Gate aufnehmen.

ERROR: FK-05 §5.14 Telemetrie fehlt komplett. Technische Materialisierung verlangt eigene Telemetrie fuer Manifest-Freigabe, Undeclared-Surface und Budget-Erschoepfung.
Evidence: [story.md](T:/codebase/claude-agentkit3/stories/AG3-069-integration-stabilization-machinery/story.md:28), [05_integration_stabilization_contract.md](T:/codebase/claude-agentkit3/concept/technical-design/05_integration_stabilization_contract.md:370), [events.md](T:/codebase/claude-agentkit3/concept/formal-spec/integration-stabilization/events.md:27).
Fix: Telemetrie-Events/Producer und Tests in Scope/AC aufnehmen.

**2) AC-Schaerfe: FAIL**

ERROR: Budget-AC ist zu eng. FK-05 §5.9 begrenzt auch “zulaessige Regressionen zwischen zwei Verify-Zyklen”; Story/AC nennen nur Schleifen, Surfaces, Contract-Changes.
Evidence: [story.md](T:/codebase/claude-agentkit3/stories/AG3-069-integration-stabilization-machinery/story.md:31), [story.md](T:/codebase/claude-agentkit3/stories/AG3-069-integration-stabilization-machinery/story.md:48), [05_integration_stabilization_contract.md](T:/codebase/claude-agentkit3/concept/technical-design/05_integration_stabilization_contract.md:274).
Fix: Regression-Cap und Test pro Cap ergaenzen.

ERROR: Repo-Set-/Worktree-Grenze fehlt als testbare AC. FK-05 §5.5.5 und Formal-Spec verbieten, dass das Manifest neue Repos/Worktrees autorisiert.
Evidence: [05_integration_stabilization_contract.md](T:/codebase/claude-agentkit3/concept/technical-design/05_integration_stabilization_contract.md:183), [invariants.md](T:/codebase/claude-agentkit3/concept/formal-spec/integration-stabilization/invariants.md:39).
Fix: Negativtest fuer Manifest mit Pfaden ausserhalb `worktree_roots`/participating repos aufnehmen.

ERROR: Reklassifikation/No-Retroactive-Legalization fehlt, obwohl FK-05 §5.7/§5.13 im Index-Scope liegt und AG3-072 diese enge Reklassifikation explizit AG3-069 zuordnet.
Evidence: [_STORY_INDEX.md](T:/codebase/claude-agentkit3/var/concept-gap-analysis/_STORY_INDEX.md:65), [05_integration_stabilization_contract.md](T:/codebase/claude-agentkit3/concept/technical-design/05_integration_stabilization_contract.md:247), [AG3-072 story.md](T:/codebase/claude-agentkit3/stories/AG3-072-story-split-service/story.md:49).
Fix: Reklassifikationspfad, frische `evidence_epoch`/Manifest-Snapshot-Grenze und Quarantaene vorbestehender Cross-Scope-Deltas aufnehmen oder einen echten Owner benennen.

**3) Klarheit: WEAK**

ERROR: Ist-Zustand-Zeile ist falsch. `integration_scope_manifest|manifest_approval` hat in `src/agentkit/**/*.py` null Treffer; `types.py` enthaelt nur `ImplementationContract`.
Evidence: [story.md](T:/codebase/claude-agentkit3/stories/AG3-069-integration-stabilization-machinery/story.md:20), [types.py](T:/codebase/claude-agentkit3/src/agentkit/story_context_manager/types.py:24).
Fix: Zeile korrigieren: “0 Treffer in `src/agentkit/**/*.py`; nur `integration_stabilization` existiert als Enum-Wert in `types.py`.”

WARNING: “produktive Integrationsarbeit blockiert” ist an mehreren Stellen nicht ausreichend operationalisiert.
Evidence: [story.md](T:/codebase/claude-agentkit3/stories/AG3-069-integration-stabilization-machinery/story.md:30), [story.md](T:/codebase/claude-agentkit3/stories/AG3-069-integration-stabilization-machinery/story.md:47).
Fix: Blockierpunkte konkret nennen: Worker-Spawn, Setup/Routing, PreToolUse-Write-Guard, Capability-Aufruf, Closure-Precondition.

**4) Kontext-Sinnhaftigkeit: WEAK**

ERROR: `status.yaml` fehlt `AG3-067` als Dependency, obwohl die Story den integration-stabilization-spezifischen Kontextanteil an den Context-Sufficiency-Builder andocken will und AG3-067 diesen Builder besitzt.
Evidence: [story.md](T:/codebase/claude-agentkit3/stories/AG3-069-integration-stabilization-machinery/story.md:43), [status.yaml](T:/codebase/claude-agentkit3/stories/AG3-069-integration-stabilization-machinery/status.yaml:8), [AG3-067 status.yaml](T:/codebase/claude-agentkit3/stories/AG3-067-context-sufficiency-packing-feedback-fidelity/status.yaml:1).
Fix: `AG3-067` in `depends_on` aufnehmen oder die Story so schneiden, dass sie nicht gegen den Builder implementiert.

PASS: FK-05/FK-37-Anker existieren; Code-Anker fuer Enum, Routing und Stage-Registry existieren; kein offensichtlicher Duplicate Owner fuer AG3-069. Code bestaetigt: `ImplementationContract` existiert, `routing_rules.py` hat keinen `integration_stabilization`-Sonderpfad, `stage_registry/data.py` enthaelt kein `stability_gate`.
Evidence: [types.py](T:/codebase/claude-agentkit3/src/agentkit/story_context_manager/types.py:24), [routing_rules.py](T:/codebase/claude-agentkit3/src/agentkit/story_context_manager/routing_rules.py:23), [data.py](T:/codebase/claude-agentkit3/src/agentkit/verify_system/stage_registry/data.py:61).

**Must-Fix**

1. FK-37-Pflichtchecks exakt korrigieren, inklusive `integration_target_matrix_passed`.
2. Manifest-Mindestfelder aus FK-05 §5.5.2 vollstaendig in Scope/AC aufnehmen.
3. Closure-Precondition aus FK-05 §5.11 als AC/Negativtest aufnehmen.
4. Telemetrie aus FK-05 §5.14 aufnehmen.
5. Budget um Regression-Cap erweitern.
6. Repo-Set-/Worktree-Grenze und Reklassifikations-/No-Retroactive-Legalization-Pfad abdecken.
7. Falsche Grep-/Ist-Zustand-Zeile korrigieren.
8. `AG3-067` Dependency klaeren bzw. ergaenzen.
