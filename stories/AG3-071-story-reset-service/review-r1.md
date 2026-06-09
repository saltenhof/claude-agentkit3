OVERALL CHANGES-REQUESTED

**1) Konzept-Vollstaendigkeit: WEAK**

- ERROR: AG3-071 beansprucht Schritt 5/6 ueber `purge_run(...)` zu loesen, aber FK-53 trennt operativen Runtime-Purge klar von Read-Models/Analytics: Runtime-State in §53.7.5, Read-Models/Analytics in §53.7.6. Evidence: [story.md](</mnt/t/codebase/claude-agentkit3/stories/AG3-071-story-reset-service/story.md:44>), [FK-53](</mnt/t/codebase/claude-agentkit3/concept/technical-design/53_story_reset_service_recovery_flow.md:223>), [FK-53](</mnt/t/codebase/claude-agentkit3/concept/technical-design/53_story_reset_service_recovery_flow.md:237>). Fix: Schritt 5 eigene Ports/Owner fuer FlowExecution/NodeExecution/Attempt/Override/GuardDecision/PhaseState/Locks/Leases benennen; `projection_repositories.purge_run` nur fuer FK-69/Projektionsanteile verwenden.
- WARNING: Reset-Purge-Kette ist laut Story-Index aufgeteilt: AG3-081 schliesst Read-Model/fc_*-Purge, AG3-082 `purge_story_analytics`; AG3-071 ist nur Ausloeser. `status.yaml` haengt aber nur an AG3-032/035. Evidence: [_STORY_INDEX.md](</mnt/t/codebase/claude-agentkit3/var/concept-gap-analysis/_STORY_INDEX.md:87>), [_STORY_INDEX.md](</mnt/t/codebase/claude-agentkit3/var/concept-gap-analysis/_STORY_INDEX.md:88>), [_STORY_INDEX.md](</mnt/t/codebase/claude-agentkit3/var/concept-gap-analysis/_STORY_INDEX.md:157>), [status.yaml](</mnt/t/codebase/claude-agentkit3/stories/AG3-071-story-reset-service/status.yaml:8>). Fix: entweder AG3-081/AG3-082 als harte Dependencies aufnehmen oder AC/Scope explizit auf typed outgoing ports + fail-closed “Owner-Schnittstelle fehlt” reduzieren.

**2) AC-Schaerfe: WEAK**

- ERROR: AC5 testet “Schritt 5/6 konsumieren die vorhandenen `purge_run(...)`-Owner (projection_repositories)”, obwohl diese Repositories nur FK-69-Projektions-/Read-Model-Familien abdecken. Evidence: [story.md](</mnt/t/codebase/claude-agentkit3/stories/AG3-071-story-reset-service/story.md:63>), [projection_repositories.py](</mnt/t/codebase/claude-agentkit3/src/agentkit/state_backend/store/projection_repositories.py:51>), [projection_repositories.py](</mnt/t/codebase/claude-agentkit3/src/agentkit/state_backend/store/projection_repositories.py:187>). Fix: AC5 in zwei ACs splitten: Runtime-Purge-Ports fuer kanonischen Runtime-State; FK-69/Analytics-Purge-Ports fuer abgeleitete Daten.
- WARNING: AC11 “vier Konzept-Gates” ist ungenau. CLAUDE.md nennt konkret `check_concept_frontmatter.py` und `compile_formal_specs.py`; Story nennt nicht, welche vier Gates gemeint sind. Fix: exakte Befehle/Scriptnamen auffuehren.

**3) Klarheit: WEAK**

- WARNING: `ESCALATED-Vorzustand -> RESETTING` vermischt Achsen. Im echten `StoryStatus` gibt es kein `ESCALATED`; Eskalation ist Run-/Phase-/Befund-Kontext, nicht Story-Stammdatenstatus. Evidence: [story.md](</mnt/t/codebase/claude-agentkit3/stories/AG3-071-story-reset-service/story.md:41>), [story_model.py](</mnt/t/codebase/claude-agentkit3/src/agentkit/story_context_manager/story_model.py:34>), [phase_state_store/models.py](</mnt/t/codebase/claude-agentkit3/src/agentkit/phase_state_store/models.py:22>). Fix: formulieren als `StoryStatus.IN_PROGRESS -> RESETTING` plus separater Nachweis eines Eskalations-/Ausnahmebefunds aus Runtime-/Audit-Artefakten; kein `StoryStatus.ESCALATED` einfuehren.
- NIT: AC1 “exakt vier Vertragsoperationen” ist enger als FK-53 “mindestens diese Operationen”. Evidence: [story.md](</mnt/t/codebase/claude-agentkit3/stories/AG3-071-story-reset-service/story.md:59>), [FK-53](</mnt/t/codebase/claude-agentkit3/concept/technical-design/53_story_reset_service_recovery_flow.md:332>). Fix: “oeffentliche Mindestoperationen” oder “public API umfasst mindestens/exakt diese vier, interne Ports erlaubt” praezisieren.

**4) Kontext-Sinnhaftigkeit: FAIL**

- ERROR: Der Ist-Zustand-Anker `projection_repositories.py:75/113/149/176/196` existiert, aber die daraus gezogene Aussage “autoritativer Runtime-/Read-Model-Purge-Owner” ist falsch. Die Datei beschreibt FK-69-Projektionen; echte Locks haben z. B. `LockRecordRepository.deactivate_locks_for_story`, nicht `purge_run`. Evidence: [story.md](</mnt/t/codebase/claude-agentkit3/stories/AG3-071-story-reset-service/story.md:29>), [projection_repositories.py](</mnt/t/codebase/claude-agentkit3/src/agentkit/state_backend/store/projection_repositories.py:1>), [lock_record_repository.py](</mnt/t/codebase/claude-agentkit3/src/agentkit/state_backend/store/lock_record_repository.py:184>), [governance/runner.py](</mnt/t/codebase/claude-agentkit3/src/agentkit/governance/runner.py:265>). Fix: Ist-Zustand korrigieren und vorhandene Owner getrennt auffuehren.
- WARNING: Die Story entscheidet “Reset ist kein Cancelled”, was FK-53 stuetzt, aber FK-91 enthaelt noch ein widersprechendes Event `story_cancelled_administratively` “ueber Split, Exit oder Reset ... Cancelled”. Evidence: [story.md](</mnt/t/codebase/claude-agentkit3/stories/AG3-071-story-reset-service/story.md:33>), [FK-53](</mnt/t/codebase/claude-agentkit3/concept/technical-design/53_story_reset_service_recovery_flow.md:291>), [FK-91](</mnt/t/codebase/claude-agentkit3/concept/technical-design/91_api_event_katalog.md:311>). Fix: Konflikt explizit als Konzeptdrift benennen und klären: AG3-071 darf Reset nicht als `Cancelled` emittieren/setzen; FK-91-Nachzug routen.

Anchor-Check: Die Ist-Zustand-Claims zu `operations.py:168`, `branch_guard.py:25`, `cli/main.py:38-141`, `story_model.py:34-46`, `service.py:80-93` sind real und inhaltlich belastbar. Der Purge-Claim in `story.md:29` ist der blockierende falsche Anker.

**Must-Fix**

1. Purge-Owner-Modell korrigieren: Runtime-Purge nicht ueber FK-69-`projection_repositories` verkaufen.
2. AC5 und Scope 2.1.5/2.1.7 entsprechend splitten und testbar machen.
3. AG3-081/AG3-082 Dependency-/Port-Strategie eindeutig festlegen.
4. `ESCALATED` als Vorbedingungsnachweis statt StoryStatus-Quelle formulieren.
5. FK-91-`Cancelled`-Konflikt sichtbar routen oder in der Story explizit ausschliessen.
