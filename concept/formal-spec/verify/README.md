---
title: Verify Formal Spec
status: active
doc_kind: context
---

# Verify

Dieser Kontext formalisiert die Capability `verify-system` als
vierstufigen Qualitaets- und Evidenzprozess.

`verify` ist **keine** eigenstaendige Top-Phase im Story-Workflow.
Verify ist eine Bounded-Context-Capability, die vom Exit-Gate der
Exploration und vom QA-Subflow der Implementation gleichberechtigt
gegen denselben Vertrag (`run_qa_subflow`, vgl. `_meta/bc-cut-decisions.md`
"Verify als Capability (Variante Y)") aufgerufen wird. Die hier
formalisierte State-Machine modelliert die internen Subflow-Stufen
(Layer 1 Structural -> Layer 2 LLM -> Layer 3 Adversarial -> Layer 4
Policy -> passed | failed | escalated) — kein Phasenstatus, sondern
interner Subflow-Zustand der aufrufenden Phase.

## Scope

Im Scope sind:

- `verify_context` und fail-closed Eintrittsregeln des QA-Subflows
- die vier QA-Schichten der Capability
- QA-Zyklus bis `passed`, `failed` oder `escalated`
- Policy-Evaluation als Abschluss eines Subflow-Laufs

## Out of Scope

Nicht Teil dieses Kontexts sind:

- Closure und Merge
- Story-Creation, Setup oder Exploration als Phasen
- eigentliche Code-Remediation in der aufrufenden Phase
- administrative Reset- oder Split-Pfade
- die Phase-Achse des Story-Workflows (siehe `formal.story-workflow`)

## Dateien

| Datei | Inhalt |
|---|---|
| `entities.md` | Capability-nahe Kernentitaeten |
| `state-machine.md` | Subflow-interner Prozesszustand von Layer 1 bis Policy |
| `commands.md` | Offizielle Capability-Aufrufe |
| `events.md` | Capability-spezifische Events |
| `invariants.md` | Harte Regeln fuer verify_context, Layer und Outcome |
| `scenarios.md` | Deklarierte Capability-Traces |

## Prosa-Quellen

- [FK-27](/T:/codebase/claude-agentkit3/concept/technical-design/27_verify_pipeline_closure_orchestration.md)
- [FK-20](/T:/codebase/claude-agentkit3/concept/technical-design/20_workflow_engine_state_machine.md)
- [DK-02](/T:/codebase/claude-agentkit3/concept/domain-design/02-pipeline-orchestrierung.md)
- [FK-91](/T:/codebase/claude-agentkit3/concept/technical-design/91_api_event_katalog.md)
