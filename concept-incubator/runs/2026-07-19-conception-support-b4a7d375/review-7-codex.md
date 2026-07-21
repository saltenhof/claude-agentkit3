## Teil A – Abnahme

**Abnahmeurteil: Rework.** Die 285 grünen Tests belegen viel Fortschritt, decken aber mehrere zentrale False-PASS-Pfade nicht ab. Der read-only Projektions-Selfcheck ist zwar grün, prüft im aktuellen `unreviewed`-Zustand jedoch keine Receipt-Bindung.

### Findings

1. **P0 – F1: Source-Closure bleibt ausdünnbar.**  
   [incubator_check.py](/T:/codebase/claude-agentkit3/src/agentkit/bundles/target_project/tools/agentkit/concept_toolchain/incubator_check.py:408) re-deriviert Briefing und versiegelte Proposals korrekt. „Alle PO-Inputs“ bedeutet aber nur „alle registrierten `PO_DECISION`-Zeilen“; ein externer kanonischer PO-Input-Satz fehlt. Ebenso validiert `_check_sources` vorhandene Derived-Zeilen, entdeckt aber eine komplett ausgelassene Synthese, Dissent-Map oder PO-Entscheidung nicht.  
   **Empfehlung:** append-only Intake-/Derived-Source-Manifest einführen und exakte Mengengleichheit gegen Briefing, Round-Seals, PO-Intake sowie kanonische Synthese-/Dissent-/Decision-Pfade prüfen.

2. **P0 – F2: Inhaltlich gefälschte Receipts können weiter aktivieren.**  
   [projection_check.py](/T:/codebase/claude-agentkit3/src/agentkit/bundles/target_project/tools/agentkit/concept_toolchain/projection_check.py:219) prüft weder `source_digest` noch `target_section_digest`, bindet das Atomregister nicht an `RUN.register_digests.atom_register` und verlangt für den Scope nicht `promotion_disposition=promoted`. Selbst `last_promotion_manifest` darf ohne Digest-Pointer fehlen.  
   **Empfehlung:** relevante Promotion-Closure vollständig erneut prüfen: zwingender Manifest-Pointer, gepinntes Atomregister, Receipt-Digests/Anker, `promoted`-Disposition und Zielbindung. Den Promotion-Checker möglichst als gemeinsame Engine verwenden.

3. **P0 – F2/F6: Zahlreiche Pflichtprojektionen sind konstruktiv nicht receiptable.**  
   [projection_check.py](/T:/codebase/claude-agentkit3/src/agentkit/bundles/target_project/tools/agentkit/concept_toolchain/projection_check.py:315) erzwingt für Verzeichnisse `target_digest=null`, während `active` ausnahmslos non-null verlangt. Der Promotion-Checker kann außerdem nur Markdown-Heading-Sektionen digestieren; YAML-/JSON-Ziele wie Registries, `concept-governance.json` und die Selbstprojektion besitzen keine auflösbaren Receipt-Anker.  
   **Empfehlung:** explizite Target-Modi normieren und implementieren: `markdown-section`, `whole-file`, `structured-selector` und `directory-tree`; jeweils mit kanonischer Digest-Regel. Alternativ Verzeichnisziele durch content-adressierte Manifestdateien ersetzen.

4. **P0 – F4: Klassifikations-Gate ist durch Weglassen des Registers umgehbar.**  
   [incubator_check.py](/T:/codebase/claude-agentkit3/src/agentkit/bundles/target_project/tools/agentkit/concept_toolchain/incubator_check.py:645) beendet die Prüfung ohne Befund, wenn Hauptregister und Overlay fehlen. Damit entfallen Vererbung, `sensitive→local` und Declassification vollständig. Auch `findings.tsv` ist promotionsseitig optional.  
   **Empfehlung:** `artifact-register.tsv` ab FRAMING und `findings.tsv` spätestens vor PROMOTING verpflichtend machen; nur das lokale Overlay darf optional sein.

5. **P1 – F3/F6: Required-Edges und git-remote-Evidenz sind nur nominell geprüft.**  
   Strukturierte `{from,to,kind}`-Registry-Kanten werden in [promotion_check.py](/T:/codebase/claude-agentkit3/src/agentkit/bundles/target_project/tools/agentkit/concept_toolchain/promotion_check.py:433) gar nicht aufgelöst. Bei git-remote genügt eine selbstgeschriebene Evidenz mit passendem `scope_id`; Ref-Name, OID/Lock-Blob, Fencing-Token, Frische und Attestierungs-Principal werden nicht gebunden.  
   **Empfehlung:** Registry-Kanten gegen den tatsächlichen Authority-/Registry-Graph auflösen. Lock-Evidenz muss mindestens erwarteten Ref, Remote, beobachteten OID, kanonischen Lock-Blob-Digest, Fencing-Token, Zeitpunkt und attestierenden Principal/Session binden.

6. **P1 – F5: Mutex-Takeover ist nicht fencing-sicher.**  
   [semantic_gate.py](/T:/codebase/claude-agentkit3/src/agentkit/bundles/target_project/tools/agentkit/concept_toolchain/semantic_gate.py:171) löscht jeden Mutex nach zehn Minuten ohne Owner-Nonce oder Heartbeat. Eine legitime lange Operation kann dadurch parallelisiert werden; außerdem löscht `_release_mutex` fremden/neuen Mutex ohne Ownership-Prüfung. Der read-only Incubator akzeptiert zudem `LEASE.fencing_token > RUN.lease_fencing_token`.  
   **Empfehlung:** Mutex mit Nonce/Owner/Heartbeat und Compare-before-delete; Takeover ausschließlich mit Lease-/Fencing-Kopplung. Lease- und RUN-Token müssen im konsistenten Zustand gleich sein.

7. **P1 – F9 und Formal-Projektion widersprechen sich weiterhin.**  
   [commands.md](/T:/codebase/claude-agentkit3/concept/formal-spec/concept-incubation/commands.md:131) erlaubt isoliertes Lock-Release in `PROMOTING`/`PROMOTION_FAILED`; [invariants.md](/T:/codebase/claude-agentkit3/concept/formal-spec/concept-incubation/invariants.md:94) und die State-Machine erlauben Release ausschließlich beim atomaren Übergang nach `CLOSED`/`ABORTED`. Die drei „Negativszenarien“ in [scenarios.md](/T:/codebase/claude-agentkit3/concept/formal-spec/concept-incubation/scenarios.md:131) enthalten kein erwartetes Reject-/Failure-Ergebnis und beweisen ihre Namen daher nicht.  
   Zusätzlich fehlen in `entities` sicherheitsrelevante Felder wie die Lease-Owner-Session; `events.decisions.recorded` führt bereits in DECIDING normative `decision_record_ids`.  
   **Empfehlung:** `release-scope-locks` als nicht separat aufrufbaren Teil eines atomaren Complete-/Abort-Commands modellieren; Negativtraces brauchen `expected: rejected` samt unverändertem Zustand/Lock. Die Compiler-Folge-Story kann danach bestehen bleiben, nicht aber als Ersatz für korrekte Spezifikation.

8. **P1 – F7: Skill und CLI-Vertrag sind operativ nicht deckungsgleich.**  
   Der Skill ruft `semantic_gate.py units/prepare/import` ohne die tatsächlich zwingenden Parameter `--principal`, `--session`, `--fencing-token` auf; auch FK-78s CLI-Tabelle nennt sie nicht. Ein Agent, der der Anleitung folgt, erhält Exit 3.  
   **Empfehlung:** vollständige Signaturen in FK-78, `process-core.md` und Orchestrator-Schritten angeben; Receipt-IDs/-Pfade vor dem Manifest-Write explizit reservieren.

9. **P1 – SSOT-Re-Skopierung ist derzeit ein ZERO-DEBT-/Decision-Konflikt.**  
   Der akzeptierte Decision Record entscheidet weiterhin, dass die CI-Gates dünne Wrapper werden ([§2 Nr. 4](/T:/codebase/claude-agentkit3/concept/_meta/decisions/2026-07-19-concept-incubation-support.md:54)); erst die Matrix verschiebt dies nach später. FK-78 nennt keinen Owner, Trigger oder Zieltermin, und der Selfcheck beweist keine Verhaltensäquivalenz der beiden Implementierungen.  
   **Empfehlung:** entweder jetzt migrieren oder die Scope-Änderung als ausdrücklich angenommene PO-Entscheidung mit Owner, Trigger und verfolgbarer Closure normieren. In der jetzigen Form akzeptiere ich die Re-Skopierung nicht.

10. **P1 – F8/Bootstrap: Der angeblich letzte Receipt-Schritt besitzt keinen bindbaren Promotion-Lauf.**  
    Der Gründungslauf enthält weder `RUN.json` noch Source-/Claim-/Atomregister oder Promotion-Manifest; zugleich verbietet die Bootstrap-Ausnahme die rückwirkende Behauptung schema-konformer Register. [STATE.md](/T:/codebase/claude-agentkit3/concept-incubator/runs/2026-07-19-conception-support-b4a7d375/STATE.md:3) steht weiterhin auf Review 5 und nennt den Härtungs-Agenten als laufend.  
    **Empfehlung:** einen neuen schema-konformen Projection-Audit-/Promotion-Lauf anlegen und `last_run_id` darauf umstellen. Bloße Receipt-Dateien im Bootstrap-Lauf wären kein Closure-Beleg.

### Auflösungsurteil F1–F10

| Finding | Urteil |
|---|---|
| F1 | **teilweise** – Baseline, Round-Seals, Pins und Ledger↔Atom geschlossen; PO-/Derived-Source-Universum nicht |
| F2 | **nicht geschlossen** – False Activation und nicht receiptable Zieltypen |
| F3 | **teilweise** – Semantik-Gates/Coverage verbessert; strukturierte Registry-Kanten ungelöst |
| F4 | **teilweise** – Regeln korrekt, Register aber optional |
| F5 | **teilweise** – Principal/Session/Lease-Prüfung gut; Mutex-Takeover/Release unsicher |
| F6 | **teilweise** – Schemas/JSON-Envelope gut; Target-Typen und Remote-Evidenz offen |
| F7 | **teilweise** – Prozessreihenfolge verbessert; CLI-Anleitung nicht ausführbar |
| F8 | **nicht geschlossen** |
| F9 | **nicht geschlossen** |
| F10 | **geschlossen** |

Akzeptiert sind insbesondere stdlib-only, materielle 9-Pin-Re-Derivation, Baseline-Re-Derivation, bidirektionale Ledger-/Atom-Kanten, Rollen-Default `sensitive` und die PowerShell-Ergänzung.

## Teil B – Semantische Reviewer-Verdicts

Diese Tabelle ist meine fachliche Entscheidung. Wegen der P0-Befunde – insbesondere fehlendem gültigem Promotion-Lauf und nicht unterstützten JSON/YAML-/Verzeichniszielen – sind selbst die `equivalent`-Zeilen aktuell noch **keine mechanisch bindbaren Closure-Receipts**.

Reviewer-Identität:

- `principal_id`: `openai.codex.review-agent`
- `session_ref`: `ak3-conception-review-chain-r1-r7-2026-07-20`

| scope_id | target | verdict | Begründung |
|---|---|---|---|
| concept-incubation-technical | formal.concept-incubation.entities | disagrees | Lease-Owner-Session und mehrere für Verlustfreiheit/Klassifikation maßgebliche Entitäten bzw. Felder fehlen. |
| concept-incubation-technical | formal.concept-incubation.state-machine | equivalent | Hauptpfad, Blocked-/Recheck-/Failure-Rückwege, Terminalität und Lock-Halteprinzip entsprechen FK-78. |
| concept-incubation-technical | formal.concept-incubation.commands | disagrees | Das isoliert erlaubte `release-scope-locks` widerspricht der atomaren CLOSED-/ABORTED-Release-Regel. |
| concept-incubation-technical | formal.concept-incubation.events | disagrees | `decisions.recorded` führt in DECIDING bereits `decision_record_ids`; FK-78 erlaubt dort nur die Derived-PO-Quelle. |
| concept-incubation-technical | formal.concept-incubation.invariants | disagrees | Die Projektionsaktivierung lässt die notwendige Bindung an eine tatsächlich promovierte Disposition aus; die RUN-CAS-Regel ist zudem als „every mutation“ überbreit formuliert. |
| concept-incubation-technical | formal.concept-incubation.scenarios | disagrees | Die angeblichen Negativszenarien modellieren weder Reject-Ergebnis noch unveränderten Lock-/Zustandsstand. |
| concept-incubation-technical | domain-registry.yaml#concept-incubation | equivalent | Domäne, Bezeichnung und Vertragsdokumente DK-16/FK-78 stimmen. |
| concept-incubation-technical | bounded-contexts.yaml#concept-incubation | equivalent | Verantwortung, Ownership und Abgrenzung entsprechen dem BC-Schnitt aus FK-78. |
| concept-incubation-technical | module-registry.yaml | equivalent | Das Modul `concept-incubation` ist korrekt registriert. |
| concept-incubation-technical | policy-registry.yaml | equivalent | Konsistenz- und Assertion-Authority-Policies sind passend registriert und auf ihre Quellen gebunden. |
| concept-incubation-technical | concept/_meta/concept-governance.json | equivalent | Roots, Lock-Backend, Grammatiken, Frontmatter- und Datenklassenvertrag entsprechen §78.2. |
| concept-incubation-technical | PROJECT_STRUCTURE.md | equivalent | Top-Level-Inkubator und deploybare Toolchain sind mit korrekter Norm-/Werkstatt-Trennung verankert. |
| concept-incubation-technical | concept_toolchain/ | disagrees | Source-/Klassifikations-Closure ist ausdünnbar und Projection-/Remote-Lock-Prüfung kann falsches PASS erzeugen. |
| concept-incubation-technical | concept-incubation-core/4.0.0 | disagrees | Prozessführung ist weitgehend korrekt, aber die dokumentierten mutierenden CLI-Aufrufe fehlen zwingende Writer-/Fencing-Parameter. |
| conception-process | FK-78 | equivalent | FK-78 operationalisiert Blueprint, Rollen, Gremienprozess und Promotion des DK-16 ohne fachliche Richtungsabweichung. |
| conception-process | CLAUDE.md – Work Modes | equivalent | Council-Orchestrator, Nicht-Parteinahme und Integrationsrolle entsprechen DK-16. |
| conception-process | DK-00 – Säule 4.10 | equivalent | Die Übersicht projiziert Zweck, Inkubatorprozess und Skill-/Toolchain-Operationalisierung korrekt. |
| assertion-authority | meta-contract.md §2 | equivalent | „Disagreement blocks“ und die Trennung von Prosa- und Formal-Autorität sind korrekt übernommen. |
| assertion-authority | formal.concept-incubation.invariants | disagrees | `projection_status_derivation` lässt die in Assertion-Authority verlangte `promotion_disposition=promoted`-Voraussetzung aus. |
| assertion-authority | projection-manifest.json | equivalent | Der aktuelle `blocked_projection`-/`unreviewed`-Stand mit akzeptiertem Lifecycle und sichtbarem Blocker ist fachlich ehrlich materialisiert. |
