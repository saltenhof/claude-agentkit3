OVERALL: CHANGES-REQUESTED

**1) Konzept-Vollstaendigkeit: FAIL**

- ERROR: Reset-Scope verletzt FK-69. Story sagt: “loescht die fc_*-/Read-Model-Zeilen ... vollstaendig” ([story.md](/t:/codebase/claude-agentkit3/stories/AG3-081-event-buildout-bc14-bc15-integrity-dim8/story.md:35), AC6 Zeile 52). FK-69 sagt aber: `fc_incidents` löschen, `fc_patterns` korrigieren/recomputen, `fc_check_proposals` bleiben unberuehrt ([69_qa_telemetrie...](/t:/codebase/claude-agentkit3/concept/technical-design/69_qa_telemetrie_aggregation_dashboard.md:365)).  
  Fix: Scope/AC auf “fc_incidents purge; fc_patterns recompute/correct; fc_check_proposals untouched” umstellen.

- ERROR: FK-61 Flush-Strategie unvollstaendig in AC. Scope nennt Closure/Week-Rollover/Housekeeping/Reset ([story.md](/t:/codebase/claude-agentkit3/stories/AG3-081-event-buildout-bc14-bc15-integrity-dim8/story.md:34)), AC5 testet aber nur Closure/Reset ([story.md](/t:/codebase/claude-agentkit3/stories/AG3-081-event-buildout-bc14-bc15-integrity-dim8/story.md:51)). FK-61 verlangt alle vier Trigger ([61_kpi...](/t:/codebase/claude-agentkit3/concept/technical-design/61_kpi_erhebung_nach_domaenen.md:219)).  
  Fix: AC5 um Week-Rollover und Housekeeping inkl. Tests erweitern.

- WARNING: Mandatory Payloads aus FK-68 sind nicht hart in der Story aufgelistet. FK-68 nennt pro BC14/BC15 Event konkrete Zusatzfelder, z.B. `dependency_recorded`: `story_id`, `depends_on_id`; `are_gate_result`: `story_id`, `result` ([68_telemetrie...](/t:/codebase/claude-agentkit3/concept/technical-design/68_telemetrie_eventing_workflow_metriken.md:382), [68_telemetrie...](/t:/codebase/claude-agentkit3/concept/technical-design/68_telemetrie_eventing_workflow_metriken.md:397)). Story sagt nur “Mandatory-Payload-Contract” und bei ARE zusätzlich `covered/required/coverage_ratio` ([story.md](/t:/codebase/claude-agentkit3/stories/AG3-081-event-buildout-bc14-bc15-integrity-dim8/story.md:31)).  
  Fix: alle Pflichtfelder je Event tabellarisch in die Story aufnehmen und ARE-Konflikt FK-68 vs FK-61 explizit owner-basiert entscheiden.

**2) AC-Schaerfe: FAIL**

- ERROR: AC3 behauptet “Dim 8” als Telemetrie-Nachweis, aber nennt sechs Nachweise plus Negativtest nur fuer drei Klassen ([story.md](/t:/codebase/claude-agentkit3/stories/AG3-081-event-buildout-bc14-bc15-integrity-dim8/story.md:49)). Das ist weder vollstaendig noch eindeutig testbar.  
  Fix: pro Nachweis-Klasse einen konkreten Test verlangen oder explizit begruenden, warum Klassen nicht getestet werden.

- ERROR: AC5 “Jeder Guard-Hook” ist nicht operationalisiert ([story.md](/t:/codebase/claude-agentkit3/stories/AG3-081-event-buildout-bc14-bc15-integrity-dim8/story.md:51)). Die Story muss die betroffenen Hook-Dateien/Registrypfade nennen, sonst ist “jeder” nicht pruefbar.  
  Fix: konkrete Hook-Liste aus `governance/guards/` und/oder registrierten Hooks aufnehmen.

- WARNING: AC2 “eine einzige, dokumentierte Wahrheit” ist kein testbares Ergebnis ([story.md](/t:/codebase/claude-agentkit3/stories/AG3-081-event-buildout-bc14-bc15-integrity-dim8/story.md:48)).  
  Fix: Zielort benennen, z.B. `MANDATORY_PAYLOAD_FIELDS` plus Contract-Test, kein zweiter String-Map-Pfad.

**3) Klarheit/Eindeutigkeit: FAIL**

- ERROR: “Integrity-Gate-Dim-8” ist falsch/mehrdeutig. Im echten Gate ist Dimension 8 `TIMESTAMP_INVERSION` ([dimensions.py](/t:/codebase/claude-agentkit3/src/agentkit/governance/integrity_gate/dimensions.py:17), [_dimension_specs.py](/t:/codebase/claude-agentkit3/src/agentkit/governance/integrity_gate/_dimension_specs.py:39)); FK-35 bestaetigt Dim 8 als Timestamp-Kausalitaet ([35_integrity...](/t:/codebase/claude-agentkit3/concept/technical-design/35_integrity_gate_governance_beobachtung_eskalation.md:274)).  
  Fix: nicht “Dim 8” nennen. Als “TelemetryContract-Gate/Telemetrie-Nachweisblock” modellieren oder zuerst Konzeptentscheidung zur Dimensionierung schreiben.

- ERROR: “Emitter” widerspricht Out-of-Scope. Scope 2.1.1 verlangt “Enum-Member + Emitter” ([story.md](/t:/codebase/claude-agentkit3/stories/AG3-081-event-buildout-bc14-bc15-integrity-dim8/story.md:30)); Out-of-Scope sagt fachliche Planning-Emitter sind AG3-099 ([story.md](/t:/codebase/claude-agentkit3/stories/AG3-081-event-buildout-bc14-bc15-integrity-dim8/story.md:43)).  
  Fix: “Emitter” auf generische Telemetry-Service Helper/Contract-Write-Boundary begrenzen oder aus Scope entfernen.

**4) Kontext-Sinnhaftigkeit: FAIL**

- ERROR: Ist-Zustand Reset-Purge ist falsch. Story behauptet “nicht als zentraler Job auffindbar” ([story.md](/t:/codebase/claude-agentkit3/stories/AG3-081-event-buildout-bc14-bc15-integrity-dim8/story.md:24)); real existiert `ProjectionAccessor.purge_run()` zentral mit QA, story_metrics, fc_incidents, risk_window und phase_state_projection ([projection_accessor.py](/t:/codebase/claude-agentkit3/src/agentkit/telemetry/projection_accessor.py:405)).  
  Fix: Story auf Delta reduzieren: bestehendes `purge_run` erweitern/korrigieren statt “zentralen Purge-Pfad” neu fordern.

- ERROR: `phase_state_projection` Ownership-Konflikt. Story fordert “Schreib-/Lese-Ownership ueber ProjectionAccessor” ([story.md](/t:/codebase/claude-agentkit3/stories/AG3-081-event-buildout-bc14-bc15-integrity-dim8/story.md:33)); Code markiert `PHASE_STATE_PROJECTION` als extern besessen durch `pipeline_engine.PhaseExecutor` und weist Accessor-Ownership fail-closed ab ([projection_accessor.py](/t:/codebase/claude-agentkit3/src/agentkit/telemetry/projection_accessor.py:105), [projection_accessor.py](/t:/codebase/claude-agentkit3/src/agentkit/telemetry/projection_accessor.py:195)).  
  Fix: Story muss explizit Migration der Ownership verlangen oder den Record beim Pipeline-Owner lassen.

- PASS mit Hinweis: genannte Anker existieren: FK-68 §68.2/§68.10, FK-69 §69.3/§69.9/§69.14, FK-61 §61.4.3. Ist-Zustand-Claims zu EventType/BC15/TelemetryContract/ProjectionRecord/GuardCounter sind im Kern belegt ([events.py](/t:/codebase/claude-agentkit3/src/agentkit/telemetry/events.py:18), [events.py](/t:/codebase/claude-agentkit3/src/agentkit/telemetry/events.py:223), [telemetry_contract.py](/t:/codebase/claude-agentkit3/src/agentkit/telemetry/contract/telemetry_contract.py:11), [projection_records.py](/t:/codebase/claude-agentkit3/src/agentkit/telemetry/projection_records.py:35), [postgres_schema.sql](/t:/codebase/claude-agentkit3/src/agentkit/state_backend/postgres_schema.sql:902)).

**Must-Fix ERROR List**

1. “Dim 8” aus der Story entfernen oder gegen FK-35/Code sauber neu entscheiden.
2. Reset-Purge-Scope an FK-69 anpassen: `fc_incidents` löschen, `fc_patterns` korrigieren/recomputen, `fc_check_proposals` nicht löschen.
3. Falschen Ist-Zustand zu Reset-Purge korrigieren; bestehendes `ProjectionAccessor.purge_run()` ist der Ausgangspunkt.
4. `phase_state_projection` Ownership klären: ProjectionAccessor-Migration explizit oder Pipeline-Owner beibehalten.
5. AC5 um Week-Rollover und Housekeeping erweitern.
6. “Emitter” vs AG3-099-Out-of-Scope entflechten.
7. AC3/AC5 so konkretisieren, dass alle geforderten Nachweise und alle betroffenen Hooks testbar sind.
