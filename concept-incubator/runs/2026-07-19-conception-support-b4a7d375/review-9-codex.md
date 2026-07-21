## Findings

1. **P0 – R8-1 weiterhin nicht vollständig geschlossen: TOCTOU zwischen Guard und Write/Release.**  
   `_MutexGuard.guard_write()` revalidiert und gibt anschließend nur ein Boolean zurück ([semantic_gate.py:172](/T:/codebase/claude-agentkit3/src/agentkit/bundles/target_project/tools/agentkit/concept_toolchain/semantic_gate.py:172)); der eigentliche Write erfolgt später. Ein Prozess kann nach erfolgreichem Guard länger als die TTL pausieren, ein anderer übernimmt, danach schreibt der alte Prozess trotzdem. Auch Heartbeat ([Zeile 330](/T:/codebase/claude-agentkit3/src/agentkit/bundles/target_project/tools/agentkit/concept_toolchain/semantic_gate.py:330)) und Release ([Zeile 346](/T:/codebase/claude-agentkit3/src/agentkit/bundles/target_project/tools/agentkit/concept_toolchain/semantic_gate.py:346)) sind Read-then-Replace/Unlink ohne dasselbe Intent über die gesamte Operation.  
   **Empfehlung:** Guard als Kontextmanager, der das exklusive Intent beziehungsweise einen OS-Lock über Revalidierung, Heartbeat und Ziel-Write/Release hält. Test: alten Writer direkt nach Guard pausieren, TTL verstreichen lassen, Takeover durchführen, alten Writer fortsetzen; weder Write noch Release dürfen landen.

2. **P0 – R8-2 nur teilweise geschlossen: ein beweglicher Intake-Head ist kein unveränderlicher Freeze.**  
   FK-78 erklärt `source_intake_head` nach seinem Gate für unveränderlich ([§78.4](/T:/codebase/claude-agentkit3/concept/technical-design/78_concept_incubation_process.md:308)); nach dem Input-Freeze werden aber regulär Derived-Quellen angehängt, wodurch derselbe Head geändert werden muss. Der Checker kennt dafür kein phasenbezogenes Gate ([incubator_check.py:67](/T:/codebase/claude-agentkit3/src/agentkit/bundles/target_project/tools/agentkit/concept_toolchain/incubator_check.py:67)) und vergleicht nur mit dem jeweils aktuellen RUN-Wert ([Zeile 459](/T:/codebase/claude-agentkit3/src/agentkit/bundles/target_project/tools/agentkit/concept_toolchain/incubator_check.py:459)). Gemeinsames Pruning plus Neuberechnung von Kette und RUN-Head bleibt damit prinzipiell möglich.  
   **Empfehlung:** zwei unveränderliche Pins: `source_intake_input_head` beim Input-Freeze und `source_intake_final_head` vor PROMOTING. Der Checker muss beweisen, dass die finale Kette den Input-Head als unveränderten Präfix enthält.

3. **P1 – R8-5 Remote-Lock-Vertrag noch inkonsistent/unvollständig.**  
   FK-78 beschreibt `remote` top-level, die Schema-/Codewelt je Ref; `ref` fehlt dagegen im FK-Feldkatalog ([FK-78 §78.11](/T:/codebase/claude-agentkit3/concept/technical-design/78_concept_incubation_process.md:611), [runmodel.py:1525](/T:/codebase/claude-agentkit3/src/agentkit/bundles/target_project/tools/agentkit/concept_toolchain/runmodel.py:1525)). Zudem soll der Digest laut FK nur Scope/Run/Token/Backend umfassen, der Code bindet zusätzlich TTL ([runmodel.py:414](/T:/codebase/claude-agentkit3/src/agentkit/bundles/target_project/tools/agentkit/concept_toolchain/runmodel.py:414)). Schließlich prüft `now - verified_at <= ttl`, aber nicht die Lebensdauer des tatsächlich beobachteten Lock-Blobs; `acquired_at`/`expires_at` fehlen.  
   **Empfehlung:** einen identischen Feldkatalog normieren; `acquired_at` oder `expires_at` digestbinden und sowohl Lock-Lebendigkeit als auch maximale Evidenzalterung prüfen.

4. **P1 – `consumer` muss normiert werden; die aktuelle Bedeutung ist nur objektbezogen.**  
   [promotion_check.py:548](/T:/codebase/claude-agentkit3/src/agentkit/bundles/target_project/tools/agentkit/concept_toolchain/promotion_check.py:548) beweist nicht, dass das Ziel das konkrete Event konsumiert, sondern nur, dass es das gesamte Event-Set über `formal_refs` bindet. Ohne Normierung definiert der Checker selbst die Semantik.

   Empfohlener Normtext:

   > Eine Kante `{from: <event_id>, to: <concept_id>, kind: consumer}` ist in v1 genau dann erfüllt, wenn `<event_id>` in einem formalen Event-Set `<object_id>` existiert, `<concept_id>` ein Konzeptdokument bezeichnet und dessen `formal_refs` `<object_id>` enthält. Die Kante belegt ausschließlich die vertragliche Bindung an das Event-Set, nicht die Verarbeitung des einzelnen Events. Ereignisspezifischer Konsum erfordert eine explizite `consumes_events`-Relation und darf aus `formal_refs` nicht abgeleitet werden.

5. **P2 – Nachlaufende Dokumentpflege.**  
   Skill/Template erläutern bei `git-remote` das nun zwingende `lock_remote` nicht. Außerdem enthält [STATE.md](/T:/codebase/claude-agentkit3/concept-incubator/runs/2026-07-19-conception-support-b4a7d375/STATE.md:88) weiterhin den alten Stand „12 equivalent / 8 disagrees“ und veraltete nächste Aktionen.

R8-3 und R8-4 sind materiell geschlossen. Die vier Target-Modi laufen jetzt durch dieselbe Receipt-Engine, und referenzierte Läufe werden vollständig promotionsgeprüft. Bei R8-5 sind `owns`, `defers_to`, `contract`, `member` und `producer` überzeugend geschlossen; offen bleiben `consumer` und Remote-Lebendigkeit.

Der `blocked_projection`-Endstand und Exit 2 von `check.py all` sind ehrlich und richtig. Ohne schema-konformen Projection-Audit gibt es keine weitergehende Closure ohne Scheinevidenz. So kann der Stand dem PO als transparent blockierte Lieferung berichtet werden, aber noch nicht als technisch final abgenommen.

## Finale Verdicts

| scope_id | target | verdict | Begründung |
|---|---|---|---|
| concept-incubation-technical | `concept_toolchain/` | `disagrees` | Vollständige Promotion-Revalidierung und TargetSpec sind repariert; Mutex-Fencing, phasenfester Intake-Head und Remote-Lock-Lebendigkeit erfüllen FK-78 noch nicht vollständig. |
| concept-incubation-technical | `formal.concept-incubation.commands` | `equivalent` | Der separate Release-Command ist auch aus FK-78 entfernt; Release ist konsistent untrennbarer Bestandteil von `complete-promotion` beziehungsweise `abort-run`. |

**Gesamturteil: Rework.** Die beiden verbleibenden P0 betreffen weiterhin die zentralen Garantien „Single Writer“ und „nichts geht verloren“.
