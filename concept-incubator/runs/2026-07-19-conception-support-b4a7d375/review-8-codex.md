## Findings

1. **P0 – R7-6 nicht geschlossen: Mutex-Takeover ist nicht exklusiv.**  
   [semantic_gate.py](/T:/codebase/claude-agentkit3/src/agentkit/bundles/target_project/tools/agentkit/concept_toolchain/semantic_gate.py:219) liest einen abgelaufenen Mutex und ersetzt ihn anschließend ohne CAS auf dessen gelesene Identität. Zwei Übernehmer können beide erfolgreich zurückkehren; ein verlorener Heartbeat wird vor dem Dispatch zudem ignoriert ([Zeile 137](/T:/codebase/claude-agentkit3/src/agentkit/bundles/target_project/tools/agentkit/concept_toolchain/semantic_gate.py:137)).  
   **Empfehlung:** exklusives Takeover-Intent per `O_EXCL` oder OS-Lock; Nonce vor jedem Dispatch/Write zwingend revalidieren und Heartbeat-Verlust als Abbruch behandeln. Echten parallelen Zwei-Prozess-Test ergänzen.

2. **P0 – R7-1 nicht geschlossen: `source-intake.tsv` ist nicht nachweislich append-only.**  
   Der Katalog enthält weder Verkettung noch extern gepinnten Log-Head ([runmodel.py](/T:/codebase/claude-agentkit3/src/agentkit/bundles/target_project/tools/agentkit/concept_toolchain/runmodel.py:2134)); der Checker vergleicht nur zwei gleichzeitig veränderbare Mengen ([incubator_check.py](/T:/codebase/claude-agentkit3/src/agentkit/bundles/target_project/tools/agentkit/concept_toolchain/incubator_check.py:417)). Eine PO-Quelle kann aus Intake und Register gemeinsam verschwinden, ohne Befund. Die Derived-Pfad-Closure ist dagegen materiell verbessert.  
   **Empfehlung:** Intake als immutable/content-addressed Inbox oder verkettetes Append-Log mit außerhalb der beiden Register CAS-gepinntem Head führen. Zusätzlich kanonische Rollen je Derived-Pfad erzwingen.

3. **P0 – R7-3 nur teilweise geschlossen: Promotion kennt den Target-Modus nicht.**  
   Der Receipt-Vertrag enthält weder `target_mode` noch `selector` ([runmodel.py](/T:/codebase/claude-agentkit3/src/agentkit/bundles/target_project/tools/agentkit/concept_toolchain/runmodel.py:1274)). Der Promotion-Checker ruft deshalb die gemeinsame Prüfung ohne Modus auf ([promotion_check.py](/T:/codebase/claude-agentkit3/src/agentkit/bundles/target_project/tools/agentkit/concept_toolchain/promotion_check.py:242)); dadurch gilt stets der Default `markdown-section` ([receipts.py](/T:/codebase/claude-agentkit3/src/agentkit/bundles/target_project/tools/agentkit/concept_toolchain/receipts.py:215)). Whole-file-, Selector- und Directory-Receipts sind promotionsseitig nicht korrekt prüfbar.  
   **Empfehlung:** kanonischen `TargetSpec {path, anchor, target_mode, selector}` an Receipt/Atom oder Promotion-Manifest binden und in beiden Checkern explizit übergeben; Promotion-E2E-Test für alle vier Modi.

4. **P0 – R7-2 nur teilweise geschlossen: Projection revalidiert keine vollständige Promotion-Closure.**  
   [projection_check.py](/T:/codebase/claude-agentkit3/src/agentkit/bundles/target_project/tools/agentkit/concept_toolchain/projection_check.py:221) prüft Receipt, Atom-Pin und die deklarierte `promoted`-Disposition, nicht jedoch Required-Sets, Coverage, Findings, Semantik-Gates und Lock-Closure. Ein selbstkonsistentes, aber nie erfolgreich geprüftes Promotion-Manifest kann daher aktivieren. `check.py all` führt Promotion nur bei explizitem `--run` aus.  
   **Empfehlung:** für `last_run_id` den vollständigen Promotion-Check erneut ausführen oder ein unverwechselbar an Manifest und vollständiges Check-Set gebundenes Closure-Attestat verlangen.

5. **P1 – R7-5 nur teilweise geschlossen.**  
   Strukturierte Registry-Kanten prüfen weiterhin nur, ob beide Endpunkte existieren, nicht ob die konkrete `{from,to,kind}`-Beziehung im Authority-/Registry-Graph besteht ([promotion_check.py](/T:/codebase/claude-agentkit3/src/agentkit/bundles/target_project/tools/agentkit/concept_toolchain/promotion_check.py:419)). Bei git-remote werden `remote` und Attestierungsidentität nur syntaktisch geladen; die Frische verwendet mangels Remote-Lock-TTL regelmäßig den festen 3600-Sekunden-Fallback ([Zeile 550](/T:/codebase/claude-agentkit3/src/agentkit/bundles/target_project/tools/agentkit/concept_toolchain/promotion_check.py:550)).  
   **Empfehlung:** exakte Graphkante verifizieren; erwartetes Remote konfigurativ binden und TTL aus attestiertem, digestgebundenem Lock-Blob ableiten.

6. **P1 – Normativer Restwiderspruch beim Lock-Release.**  
   Formal sind separater Command und isolierter Release korrekt entfernt. FK-78 verweist jedoch weiterhin ausdrücklich auf den nicht mehr existierenden Command `release-scope-locks` ([FK-78 §78.11](/T:/codebase/claude-agentkit3/concept/technical-design/78_concept_incubation_process.md:598)).  
   **Empfehlung:** durch „untrennbarer Bestandteil von `complete-promotion` bzw. `abort-run`“ ersetzen.

7. **P2 – Status-/Terminologiepflege.**  
   [STATE.md](/T:/codebase/claude-agentkit3/concept-incubator/runs/2026-07-19-conception-support-b4a7d375/STATE.md:45) meldet die abgeschlossene Härterunde noch als `LAEUFT`. Außerdem ist der SSOT-Übergang triggergebunden, aber nicht zeitlich „terminiert“ ([FK-78](/T:/codebase/claude-agentkit3/concept/technical-design/78_concept_incubation_process.md:738)). Entsprechend präzisieren.

## Auflösungsurteil

| Punkt | Urteil |
|---|---|
| R7-1 Intake/Derived-Closure | **nicht geschlossen** |
| R7-2 Projection-Bindung | **teilweise** |
| R7-3 Target-Modi | **teilweise** |
| R7-4 Pflichtregister | **geschlossen** |
| R7-5 Registry-/Remote-Evidenz | **teilweise** |
| R7-6 Mutex | **nicht geschlossen** |
| Entities/Events/Invarianten/Szenarien | **normativ geschlossen** |
| Skill-CLI und Prozessführung | **geschlossen** |
| Compound Lock-Release | **formal geschlossen, FK-78-Restfehler** |

Die SSOT-Entscheidung akzeptiere ich: Owner, Trigger, Closure-Nachweis und Interimsrisiko machen daraus eine offen angenommene Übergangsschuld und keinen ZERO-DEBT-Verstoß. „Terminiert“ sollte lediglich durch „triggergebunden“ ersetzt werden.

Der `blocked_projection`-Endstand ist richtig. Ohne schema-konformen Audit-Lauf gibt es keinen ehrlichen zusätzlichen Closure-Schritt; meine semantischen Neubewertungen dürfen nicht ersatzweise als Receipts eingetragen werden. Der Audit sollte allerdings erst nach Schließung der P0-Lücken mit der gehärteten Toolchain erfolgen.

## Aktualisierte Verdicts der acht bisherigen `disagrees`

| scope_id | target | verdict | Begründung |
|---|---|---|---|
| concept-incubation-technical | `formal.concept-incubation.entities` | `equivalent` | Lease-Session, Mutex, ArtifactRecord und DeclassificationReceipt sind nun angemessen projiziert. |
| concept-incubation-technical | `formal.concept-incubation.commands` | `disagrees` | Der formale Compound-Command ist richtig, FK-78 behauptet aber weiterhin den separaten Command `release-scope-locks`. |
| concept-incubation-technical | `formal.concept-incubation.events` | `equivalent` | `po_decision_source_ids` und die compound erzeugten Release-/Terminalevents entsprechen dem Verfahren. |
| concept-incubation-technical | `formal.concept-incubation.invariants` | `equivalent` | Promotion-Bindung, Target-Modi und präzisierte Mutex-/RUN-Regeln sind normativ enthalten; die Implementierungsverletzung ist ein separater Befund. |
| concept-incubation-technical | `formal.concept-incubation.scenarios` | `equivalent` | Die Szenarien behaupten keine nicht ausdrückbaren Reject-Traces mehr und benennen die Compiler-Grenze ehrlich. |
| concept-incubation-technical | `concept_toolchain/` | `disagrees` | Intake, Target-Modus, Projection-Closure und Mutex können weiterhin falsche Closure beziehungsweise Parallelmutationen zulassen. |
| concept-incubation-technical | `concept-incubation-core/4.0.0` | `equivalent` | CLI-Signaturen, Intake, Pflichtregister und Promotion-Reihenfolge entsprechen jetzt FK-78. |
| assertion-authority | `formal.concept-incubation.invariants` | `equivalent` | `projection_status_derivation` bindet nun an Receipt, promotierten Scope und unabhängige Principals/Sessions. |

**Gesamturteil: Rework.** Vier P0-Lücken verhindern die Schlussfreigabe trotz der deutlich verbesserten normativen Konsistenz.
