---
title: Story Workflow Formal Spec
status: active
doc_kind: context
---

# Story Workflow

Dieser Kontext formalisiert den deterministischen Ablauf einer
Story-Bearbeitung in AK3.

## Scope

Im Scope sind:

- Phasenfolge `setup -> exploration|implementation -> verify -> closure`
- Run-Kontrollstatus `IN_PROGRESS`, `PAUSED`, `ESCALATED`,
  `COMPLETED`, `FAILED`
- offizielle Workflow-Kommandos fuer diesen Ablauf
- phasenrelevante Events
- zentrale Invarianten und deklarierte End-to-End-Traces

## Out of Scope

Nicht Teil dieses ersten Kontexts sind:

- `StoryResetService`
- `StorySplitService`
- generische Engine-Interna wie Scheduling, Parallelitaet,
  Timeout-Management oder dynamische DAGs
- Telemetrie-Storage, Analytics und Read Models

## Dateien

| Datei | Inhalt |
|---|---|
| `state-machine.md` | Phase-, Status- und Transition-Modell |
| `commands.md` | Offizielle Workflow-Kommandos |
| `events.md` | Workflow-relevante Lifecycle-Events |
| `invariants.md` | Harte Konsistenzregeln |
| `scenarios.md` | Deklarierte Ablauftraces |

## Prosa-Quellen

- [FK-20](/T:/codebase/claude-agentkit3/concept/technical-design/20_workflow_engine_state_machine.md)
- [DK-02](/T:/codebase/claude-agentkit3/concept/domain-design/02-pipeline-orchestrierung.md)
- [FK-24](/T:/codebase/claude-agentkit3/concept/technical-design/24_story_type_mode_terminalitaet.md)
- [FK-27](/T:/codebase/claude-agentkit3/concept/technical-design/27_verify_pipeline_closure_orchestration.md)
- [FK-35](/T:/codebase/claude-agentkit3/concept/technical-design/35_integrity_gate_governance_beobachtung_eskalation.md)
