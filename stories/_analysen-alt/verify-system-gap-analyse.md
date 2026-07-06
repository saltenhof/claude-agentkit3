# verify-system — GAP-Analyse

> Generiert von einem dedizierten Sonnet-Sub-Agent (Stand 2026-05-16).

## Header

| Feld | Wert |
|---|---|
| BC-ID | `verify-system` |
| Display-Name | `Verify-System (Multi-Layer-QA-Capability)` |
| Analyse-Datum | `2026-05-16` |
| Konzept-Quellen (autoritativ) | `DK-04, DK-11, FK-27, FK-28, FK-32, FK-33, FK-34, FK-37, FK-38, FK-46, FK-47, FK-48, formal.verify.*, formal.deterministic-checks.*, formal.llm-evaluations.*, formal.conformance.*` |
| Codebase-Hauptpfade | `src/agentkit/verify_system/, src/agentkit/llm_evaluator/` |

## 1. Executive Summary

Das verify-system ist als Capability-BC konzipiert und strukturell bereits angelegt: das Paket `src/agentkit/verify_system/` existiert mit Subpaketen fuer structural, llm_evaluator, adversarial_orchestrator, policy_engine und remediation. Die Grundkonzepte (4-Schichten-QA, TrustClass, Finding, PolicyEngine) sind implementiert. Allerdings sind die drei LLM-gesteuerten Schichten (Layer 2 — StructuredEvaluator/ParallelEvalRunner, Layer 3 — Adversarial Agent mit Sandbox und Mandatory Targets) explizit als Passthrough-Stub markiert und liefern immer PASS ohne echten LLM-Aufruf. Die gesamte Evidence-Assembly-Infrastruktur (FK-28, FK-46, FK-47) sowie der ConformanceService (FK-32), der ContextSufficiencyBuilder (FK-37) und die QA-Zyklus-Mechanik (advance_qa_cycle, Artefakt-Invalidierung) fehlen vollstaendig im Code. Das Konzept ist deutlich weiter ausgearbeitet als der Implementierungsstand.

| Kategorie | Anzahl |
|---|---|
| A — Nicht umgesetzt | 10 |
| B — Teilweise umgesetzt | 7 |
| C — Drift / Fehler | 4 |

## 2. Konzept-Soll (Kurzfassung)

- **VerifySystem als Top-Komponente mit `run_qa_subflow(ctx, story_id, qa_context, target) -> PolicyVerdict`** — `concept/_meta/bc-cut-decisions.md §Verify als Capability (Variante Y)`
- **QaContext-Typisierung: IMPLEMENTATION_INITIAL / IMPLEMENTATION_REMEDIATION / EXPLORATION_INITIAL / EXPLORATION_REMEDIATION** — `concept/_meta/bc-cut-decisions.md §QA-Subflow-Vertrag`
- **Atomarer QA-Zyklus mit qa_cycle_id, qa_cycle_round, evidence_epoch, evidence_fingerprint; advance_qa_cycle() invalidiert 11 Artefaktdateien** — `FK-27 §27.2`
- **QA-Zyklus-State-Machine: idle → awaiting_qa → awaiting_policy → pass | awaiting_remediation → escalated** — `FK-27 §27.2.2, formal.verify.state-machine`
- **Layer 1 deterministisch: Artefakt-Prüfung (artifact.protocol, artifact.worker_manifest, artifact.manifest_claims, artifact.handover), Structural Checks (branch, build, test, security, hygiene, impact), Recurring Guards (guard.llm_reviews, guard.review_compliance, guard.no_violations, guard.multi_llm als eigene BLOCKING-Gates), ARE-Gate (optional)** — `FK-27 §27.4, FK-33`
- **Layer 2: ParallelEvalRunner mit drei parallelen StructuredEvaluator-Aufrufen (qa_review 12 Checks, semantic_review 1 Check, doc_fidelity/Umsetzungstreue 1 Check); kein Dateisystem-Zugriff; fail-closed bei unbekannten Check-IDs** — `FK-27 §27.5, FK-34, FK-38 §38.2`
- **ContextSufficiencyBuilder als Pflicht-Vorstufe zu Layer 2: prueft 6 Bundle-Felder, Sufficiency-Klassifikation, Packing** — `FK-37 §37.2, DK-11 §4.5.4`
- **Layer 3 Adversarial Agent: separater Spawn via agents_to_spawn, Sandbox-Schreiben, Mandatory Adversarial Targets aus Layer-2-Findings, Test-Promotion, Quarantine-Verzeichnis** — `FK-27 §27.6, FK-48`
- **Layer 4 Policy-Engine: Stage-Registry-typisiert, Blocking/Major/Minor-Threshold, fail-closed bei fehlendem Artefakt** — `FK-27 §27.7, FK-33`
- **Finding-Resolution im Remediation-Modus: Layer-2-Evaluator bewertet Vorrunden-Findings direkt (fully_resolved / partially_resolved / not_resolved), Closure blockiert bei offenem Finding** — `DK-04 §4.6, FK-34`
- **ConformanceService (4 Ebenen: Zieltreue, Entwurfstreue, Umsetzungstreue, Rückkopplungstreue) als Subkomponente** — `FK-32`
- **EvidenceAssembler (3-Stufen: deterministischer Kern, Import-Extraktion, Worker-Hints), BundleEntry, AuthorityClass, BundleManifest, 350-KB-Limit** — `FK-28, DK-11 §4.5.3`
- **ImportResolver: Python/TS/Java-Patterns, Confidence-Labels (RESOLVED_IMPORT, RESOLVED_ALIAS, BARREL_CONTEXT, SAME_PACKAGE_HEURISTIC, SPRING_SCAN_HEURISTIC, UNRESOLVED_DYNAMIC)** — `FK-46`
- **Request-DSL und Preflight-Turn: 7 Request-Typen, max 8 Requests pro Reviewer, deterministischer RequestResolver, multi-repo-faehig** — `FK-47, DK-11 §4.5.3.3`
- **Section-aware Bundle-Packing statt stumpfer Mittelschnitt-Trunkierung** — `DK-11 §4.5.4.3, FK-37 §37.3`
- **Divergenz-Quorum: dritter Reviewer bei Verdikt-Divergenz, 2-gegen-1** — `DK-11 §4.5.3.4`
- **Telemetrie-Schema-Ownership: QaStageResult und QaFinding liegen bei verify-system** — `concept/_meta/bc-cut-decisions.md §33`
- **Formal-Spec-Anpassungen (formal.story-workflow, formal.verify) nach Variante-Y-Entscheidung stehen noch aus** — `concept/_meta/bc-cut-decisions.md §Verify als Capability (Variante Y)`

## 3. Code-Stand (Ist-Bild)

- `src/agentkit/verify_system/protocols.py:Severity` — StrEnum mit CRITICAL/HIGH/MEDIUM/LOW/INFO (abweichend von Konzept-Kategorien BLOCKING/MAJOR/MINOR)
- `src/agentkit/verify_system/protocols.py:TrustClass` — StrEnum A/B/C, korrekte Grundklassifikation
- `src/agentkit/verify_system/protocols.py:Finding` — frozen dataclass mit layer, check, severity, message, trust_class, file_path, line_number, suggestion
- `src/agentkit/verify_system/protocols.py:LayerResult` — frozen dataclass mit layer, passed, findings, metadata; blocking_findings-Property
- `src/agentkit/verify_system/protocols.py:QALayer` — Protocol fuer alle Layer-Implementierungen
- `src/agentkit/verify_system/structural/checker.py:StructuralChecker` — Layer-1-Aggregator; prueft context_exists, context_valid, phase_snapshots, no_corrupt_state
- `src/agentkit/verify_system/structural/checks.py` — 5 individuelle Check-Funktionen (check_context_exists, check_context_valid, check_phase_snapshots, check_artifacts_present, check_no_corrupt_state), canonical-state-read-basiert
- `src/agentkit/verify_system/llm_evaluator/reviewer.py:SemanticReviewer` — Layer-2-Passthrough, gibt immer LayerResult(passed=True) zurueck, kein LLM-Aufruf
- `src/agentkit/verify_system/adversarial_orchestrator/challenger.py:AdversarialChallenger` — Layer-3-Passthrough, gibt immer LayerResult(passed=True) zurueck, kein Agent-Spawn
- `src/agentkit/verify_system/policy_engine/engine.py:PolicyEngine` — Layer-4-Aggregation mit max_high_findings-Threshold; CRITICAL/HIGH aus SYSTEM oder zu viele HIGH -> FAIL
- `src/agentkit/verify_system/policy_engine/engine.py:VerifyDecision` — frozen dataclass mit passed, status, layer_results, all_findings, blocking_findings, summary
- `src/agentkit/verify_system/policy_engine/trust.py` — TRUST_WEIGHT und effective_severity-Berechnung
- `src/agentkit/verify_system/remediation/feedback.py:RemediationFeedback` — frozen dataclass; build_feedback() erzeugt Feedback aus VerifyDecision
- `src/agentkit/verify_system/artifacts.py` — Persistenz-Facade: write_layer_artifacts, write_verify_decision_artifacts, load_verify_decision_artifact
- `src/agentkit/verify_system/qa_read_models.py` — FK-69-Read-Model-Materialisierung: QAStageResultRecord, QAFindingRecord, build_qa_stage_result, build_qa_findings
- `src/agentkit/verify_system/stage_registry/records.py:QAStageResultRecord` — Telemetrie-Projektionstyp
- `src/agentkit/verify_system/stage_registry/records.py:QAFindingRecord` — Telemetrie-Projektionstyp
- `src/agentkit/verify_system/evidence/__init__.py` — leeres Modul, kein Code
- `src/agentkit/verify_system/reports/__init__.py` — leeres Modul, kein Code
- `src/agentkit/llm_evaluator/reviewer.py` — Re-Export-Shim von verify_system.llm_evaluator.reviewer

## 4. GAP-Analyse

> **Wichtig:** Jede Zeile in einer der drei Tabellen muss mindestens
> eine konkrete Doc-Referenz tragen. Code-Referenzen sind in den
> Tabellen B und C Pflicht, in Tabelle A optional (weil dort gerade
> kein Code existiert).

### 4.1 A — Nicht umgesetzt

| # | Thema | Konzept-Referenz | Anmerkung |
|---|---|---|---|
| A1 | VerifySystem-Top-Komponente mit `run_qa_subflow(ctx, story_id, qa_context, target) -> PolicyVerdict` | `concept/_meta/bc-cut-decisions.md §QA-Subflow-Vertrag` | Kein oeffentliches `VerifySystem`-Objekt mit der normierten Signatur existiert; der BC hat keine aufrufbare Top-Surface |
| A2 | QA-Zyklus-Mechanik: advance_qa_cycle(), qa_cycle_id, qa_cycle_round, evidence_epoch, evidence_fingerprint, Artefakt-Invalidierung (11 Dateien nach stale/) | `FK-27 §27.2` | Keinerlei Zyklus-Identitaetsfelder oder Invalidierungslogik implementiert |
| A3 | EvidenceAssembler (3-Stufen, BundleEntry, AuthorityClass, BundleManifest, 350-KB-Limit) und CLI-Command `agentkit evidence assemble` | `FK-28, DK-11 §4.5.3.1` | `src/agentkit/verify_system/evidence/__init__.py` ist leer; kein Evidence-Package unter `src/agentkit/evidence/` |
| A4 | ImportResolver (Python/TS/Java Regex-Patterns, Confidence-Labels: RESOLVED_IMPORT, RESOLVED_ALIAS, BARREL_CONTEXT, SAME_PACKAGE_HEURISTIC, SPRING_SCAN_HEURISTIC, UNRESOLVED_DYNAMIC) | `FK-46` | Nicht implementiert |
| A5 | Request-DSL und Preflight-Turn: 7 Request-Typen, RequestResolver (multi-repo), Preflight-Prompt-Template, max-8-Requests-Limit, 30-Sekunden-Timeout | `FK-47, DK-11 §4.5.3.3` | Nicht implementiert |
| A6 | ConformanceService (4 Ebenen: Zieltreue, Entwurfstreue, Umsetzungstreue, Rückkopplungstreue) mit ManifestIndexer, 3-Tier-Prompt-Groessenkontrolle (50 KB / 500 KB Schwellen) | `FK-32` | Nicht implementiert; Paket hat keinen conformance_service-Sub |
| A7 | ContextSufficiencyBuilder: prueft 6 Bundle-Felder, schreibt context_sufficiency.json, Sufficiency-Klassifikation (sufficient / reviewable_with_gaps / partially_reviewable), Section-aware Packing | `FK-37 §37.2, DK-11 §4.5.4` | Nicht implementiert; keine ContextBundle-Klasse vorhanden |
| A8 | Adversarial-Agent-Spawn via agents_to_spawn-Feld im Phase-State, Sandbox-Scoping (`_temp/adversarial/{story_id}/`), Test-Promotion, Quarantaene-Verzeichnis, Mandatory Adversarial Targets mit Gate-Rueckkopplung | `FK-27 §27.6, FK-48` | `AdversarialChallenger` ist explizit als Passthrough markiert; kein Agent-Spawn, kein Sandbox-Write |
| A9 | Divergenz-Quorum: Verdikt-Normalisierung, dritter Reviewer bei Divergenz, 2-gegen-1-Mehrheitsentscheidung | `DK-11 §4.5.3.4` | Nicht implementiert |
| A10 | Formal-Spec-Anpassungen (formal.story-workflow, formal.verify) nach Variante-Y-Entscheidung | `concept/_meta/bc-cut-decisions.md §Verify als Capability (Variante Y)` | Im bc-cut-decisions explizit als "offen" markiert |

### 4.2 B — Teilweise umgesetzt

| # | Thema | Code-Referenz | Konzept-Referenz | Was fehlt |
|---|---|---|---|---|
| B1 | Layer-1 Structural Checks: nur Meta-Checks (context_exists, context_valid, no_corrupt_state, phase_snapshots) | `src/agentkit/verify_system/structural/checks.py, src/agentkit/verify_system/structural/checker.py:StructuralChecker` | `FK-27 §27.4.1, FK-27 §27.4.2, FK-27 §27.4.3` | Fehlen: Artefakt-Pruefung (artifact.protocol, artifact.worker_manifest, artifact.manifest_claims, artifact.handover), Branch-Checks (branch.story, branch.commit_trailers), Build/Test-Checks (build.compile, build.test_execution, test.count, test.coverage), Hygiene-Checks (hygiene.todo_fixme, hygiene.disabled_tests, hygiene.commented_code), Recurring Guards (guard.llm_reviews, guard.review_compliance, guard.no_violations, guard.multi_llm), ARE-Gate, Impact-Violation-Check mit ESCALATED-Pfad |
| B2 | Layer-2 LLM-Bewertungen: Paketstruktur und Protokoll vorhanden, aber Implementierung fehlt | `src/agentkit/verify_system/llm_evaluator/reviewer.py:SemanticReviewer` | `FK-27 §27.5, FK-34` | SemanticReviewer ist Passthrough; kein StructuredEvaluator (JSON-Schema-Validierung, fail-closed), kein ParallelEvalRunner (ThreadPoolExecutor), keine drei parallelen Rollen (qa_review/12 Checks, semantic_review/1 Check, doc_fidelity/1 Check), kein Prompt-Template-Lookup via PromptRuntime.materialize_prompt |
| B3 | Policy-Engine: Grundlogik vorhanden, aber Severity-Schema und Stage-Registry-Bindung weichen ab | `src/agentkit/verify_system/policy_engine/engine.py:PolicyEngine` | `FK-27 §27.7, FK-33` | PolicyEngine nutzt eigene CRITICAL/HIGH-Kategorien statt der Stage-Registry-Kategorien BLOCKING/MAJOR/MINOR; kein Stage-Registry-Lookup (stages_for(story_type)); kein fail-closed bei fehlendem Artefakt einer durchlaufenen Schicht; PASS_WITH_WARNINGS-Status existiert nicht im Konzept (dort nur PASS/FAIL) |
| B4 | Telemetrie-Schema-Ownership: QAStageResultRecord und QAFindingRecord als verify-system-eigene Typen | `src/agentkit/verify_system/stage_registry/records.py:QAStageResultRecord, QAFindingRecord` | `concept/_meta/bc-cut-decisions.md §33` | Typen existieren, aber Stage-Registry-Subpaket hat keinen StageDefinition-Typ; keine stage-_registry-typisierte Auswertung (stages_for(story_type), execution_policy, applies_to-Filter) |
| B5 | Finding-Resolution im Remediation-Modus | `src/agentkit/verify_system/remediation/feedback.py:build_feedback` | `DK-04 §4.6, FK-34` | build_feedback() erzeugt Feedback, aber ohne Finding-Resolution-Status (fully_resolved / partially_resolved / not_resolved); kein Vorrunden-Finding-Kontext wird an Layer-2-Evaluator uebergeben; Closure-Gate bei offenem Finding fehlt |
| B6 | Remediation-Loop-Zaehler und Eskalation bei max_feedback_rounds | `src/agentkit/verify_system/remediation/feedback.py:RemediationFeedback.round_nr` | `FK-38, FK-34 §remediation-round` | round_nr-Feld ist vorhanden, aber keine Engine-seitige Inkrementierung, keine max_feedback_rounds-Pruefung, kein ESCALATED-Pfad bei Erschoepfung |
| B7 | Prompt-Audit fuer Layer 2 und Layer 3 | `src/agentkit/verify_system/prompt_audit.py` — aufgerufen aus SemanticReviewer und AdversarialChallenger | `FK-44 (Prompt-Bundles)` | prompt_audit wird materialisiert, aber die zugrunde liegenden echten Prompt-Templates fuer qa-semantic.md, qa-semantic-review.md, qa-adversarial-review.md sind nicht implementiert; der Pfad fuehrt zu leeren Stubs |

### 4.3 C — Drift / Fehler

> Hier landen Implementierungen, die etwas tun, aber nicht das, was im
> Konzept steht, **oder** offensichtlich fehlerhaft sind (Bug,
> Verletzung einer Invariante, falsche Trust-Boundary, etc.).

| # | Thema | Code-Referenz | Konzept-Referenz | Drift / Fehler |
|---|---|---|---|---|
| C1 | Severity-Schema: CRITICAL/HIGH/MEDIUM/LOW/INFO statt BLOCKING/MAJOR/MINOR | `src/agentkit/verify_system/protocols.py:Severity` | `FK-27 §27.4.2, FK-33` | Das Konzept definiert Severity-Kategorien BLOCKING / MAJOR / MINOR fuer Stage-Definitions; der Code verwendet ein fuenfstufiges CRITICAL/HIGH/MEDIUM/LOW/INFO-Schema. Beides ist nicht aequivalent: z.B. fehlt die MINOR-Semantik des Konzepts (sammeln, in Policy einfliessen, aber nicht einzeln blockieren). Die Abweichung ist systematisch und betrifft die gesamte Policy-Engine-Logik. |
| C2 | PASS_WITH_WARNINGS-Status in PolicyEngine existiert nicht im Konzept | `src/agentkit/verify_system/policy_engine/engine.py:PolicyEngine.decide` | `FK-27 §27.7.2` | Das Konzept kennt nur PASS und FAIL als Entscheidungsausgabe der Policy-Engine. PASS_WITH_WARNINGS ist ein dritter Status, der im Konzept keine Grundlage hat und zu Drift in Closures, Telemetrie und Integration-Tests fuehren kann. |
| C3 | guard.llm_reviews und guard.multi_llm fehlen als separate BLOCKING-Gates (Zwei-Stufen-Pruefung REF-036) | `src/agentkit/verify_system/structural/checker.py:StructuralChecker.evaluate` | `FK-27 §27.4.3` | Das Konzept normiert explizit zwei separate BLOCKING-Guards (Guard 1: Reviews angefordert? Guard 2: alle Reviewer abgeschlossen?) als eigenstaendige Gates. Beide fehlen. Laut Konzept ist dies ein Governance-Leck (empirisch belegt BB2-057): ein Review kann fehlen, ohne dass der Subflow blockiert. |
| C4 | `src/agentkit/llm_evaluator/` ist ein veraltetes Legacy-Paket mit Re-Export-Shim statt korrekter Pfad-Ownership | `src/agentkit/llm_evaluator/reviewer.py` | `concept/_meta/bc-cut-decisions.md §1878-1880` | bc-cut-decisions listet explizit: Migration `agentkit.llm_evaluator` -> `agentkit.backend.verify_system.llm_evaluator` als offenen Refactor-Punkt. Das Top-Level-Paket `src/agentkit/llm_evaluator/` ist ein Shim, der in das verify_system-Subpaket zeigt — ein Zwischenzustand, der alte und neue Strukturen parallel haelt. Verstaerkt durch fehlende fachliche Abgrenzung. |

## 5. Ableitungen / Empfehlungen

1. **VerifySystem Top-Komponente und QA-Zyklus-Mechanik implementieren (A1, A2)** — Dies ist der schwerste Blocker. Ohne `run_qa_subflow(...) -> PolicyVerdict` mit typisiertem QaContext kann kein anderer BC (pipeline-framework, implementation-phase) korrekt gegen verify-system integrieren. advance_qa_cycle() und die Artefakt-Invalidierung sind Voraussetzung fuer korrekte Remediation-Loops. Risiko: Alle Integration-Tests die den QA-Subflow aufrufen arbeiten gegen eine nicht-normierte interne Schnittstelle.

2. **Severity-Schema normieren (C1, C2)** — Die Abweichung CRITICAL/HIGH/MEDIUM vs. BLOCKING/MAJOR/MINOR ist kein kosmetisches Problem: sie bestimmt das Policy-Engine-Verhalten, die Stage-Registry-Logik und die Telemetrie-Kategorisierung. Solange der Drift besteht, ist jede nachtraeglich implementierte Stage-Registry inkompatibel mit der bestehenden PolicyEngine. PASS_WITH_WARNINGS (C2) muss vor der Stage-Registry-Anbindung eliminiert werden.

3. **guard.llm_reviews und guard.multi_llm als BLOCKING-Guards implementieren (C3)** — Konzeptuell als REF-036 und BB2-057 empirisch belegter Governance-Fehler. Solange diese Guards fehlen, kann eine Story QA-Subflow-PASS erreichen ohne dass ein einziges LLM-Review gelaufen ist. Das widerspricht dem Kernauftrag des BC direkt.

4. **Layer-2 StructuredEvaluator mit echtem LLM-Aufruf, ParallelEvalRunner und den drei Rollen (qa_review, semantic_review, doc_fidelity) implementieren (B2)** — Voraussetzung fuer Finding-Resolution (B5), Mandatory Adversarial Targets (A8) und den Divergenz-Quorum (A9). Aktuell liefert Layer 2 immer PASS; der gesamte QA-Subflow ist ohne LLM-Bewertung sinnlos.

5. **EvidenceAssembler und ContextSufficiencyBuilder implementieren (A3, A7)** — Voraussetzung fuer korrekte Layer-2-Bundle-Qualitaet. Ohne Evidence-Assembly ist der Worker weiterhin alleiniger Kurator des Review-Bundles (DK-11 Governance-Problem). Beides sind deterministisch implementierbare Blocker ohne LLM-Abhaengigkeit.

6. **ConformanceService (FK-32) implementieren (A6)** — Ebene 3 (Umsetzungstreue) ist als dritter paralleler Layer-2-Aufruf normiert; ohne ConformanceService fehlt diese Ebene vollstaendig aus dem QA-Subflow. Ebene 4 (Rückkopplungstreue) blockiert Closure.

7. **Legacy-Paket `src/agentkit/llm_evaluator/` migrieren (C4)** — Halbfertiger Architekturuebergang. Der Shim verlaengert den Drift. Sobald Layer 2 implementiert wird, sollte der alte Namespace vollstaendig durch `agentkit.backend.verify_system.llm_evaluator` ersetzt werden.

## 6. Suchstrategie & Quellen

- **Vollstaendig gelesen:**
  - `concept/domain-design/04-qualitaetssicherung.md`
  - `concept/domain-design/11-review-qualitaetsverbesserung.md`
  - `concept/technical-design/27_verify_pipeline_closure_orchestration.md`
  - `concept/technical-design/28_evidence_assembly_review_vorbereitung.md`
  - `concept/technical-design/32_dokumententreue_conformance_service.md`
  - `concept/technical-design/33_deterministische_checks_stage_registry_policy_engine.md` (Header + §33.1)
  - `concept/technical-design/34_llm_bewertungen_adversarial_testing_runtime.md` (Header)
  - `concept/technical-design/37_verify_context_und_qa_bundle.md` (Header)
  - `concept/technical-design/38_verify_feedback_und_doctreue_schleife.md` (Header)
  - `concept/technical-design/46_import_resolver.md` (Header)
  - `concept/technical-design/47_request_dsl_und_preflight_turn.md` (Header)
  - `concept/technical-design/48_adversarial_testing_runtime.md` (Header)
  - `concept/formal-spec/verify/entities.md`
  - `concept/formal-spec/verify/state-machine.md`
  - `concept/formal-spec/verify/invariants.md`
  - `concept/_meta/bc-cut-decisions.md §Verify als Capability (Variante Y)` und `§BC 2: verify-system`
  - `concept/technical-design/_meta/domain-registry.yaml` (Eintrag verify-system)
- **Code-Scan (Glob/Grep):**
  - Pattern `src/agentkit/verify_system/**/*.py`: alle 22 Python-Dateien im BC-Hauptpfad
  - Pattern `src/agentkit/llm_evaluator/**/*.py`: Legacy-Shim-Paket
  - Pattern `src/agentkit/evidence/**/*.py`: nicht vorhanden
  - Pattern `src/agentkit/qa/**/*.py`: nicht vorhanden
  - Grep `verify_system|StructuralChecker|PolicyEngine` in tests/: Nachweis vorhandener Unit-Tests fuer structural, policy_engine, remediation, artifacts, protocols
