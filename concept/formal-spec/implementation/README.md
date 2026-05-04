---
title: Implementation Formal Spec
status: active
doc_kind: context
---

# Implementation

Dieser Kontext formalisiert die eigentliche Herstellung des
Story-Ergebnisses in der Implementation-Phase.

## Scope

Im Scope sind:

- Worker-Spawn und Worker-Lauf
- Arbeitsartefakte fuer die Phase
- `BLOCKED`- und Eskalationspfad
- Handover-/Manifest-Bereitstellung als QA-Eingabe
- Aufruf der Capability `verify-system` als phaseninterner QA-Subflow
  inkl. Subflow-internem Remediation-Loop

## Out of Scope

Nicht Teil dieses Kontexts sind:

- Setup-/Preflight-Startfaehigkeit
- Exploration und H2-Mandatsrouting
- die internen Schichten der Capability `verify-system` (siehe
  `formal.verify` — Capability-Vertrag)
- Closure-Entscheidungen
- Story-Split, Reset oder manuelle Recovery

## Dateien

| Datei | Inhalt |
|---|---|
| `entities.md` | Implementation-nahe Kernentitaeten |
| `state-machine.md` | Prozesszustand von Worker-Start bis Handover |
| `commands.md` | Offizielle Implementation-Kommandos |
| `events.md` | Implementation-spezifische Events |
| `invariants.md` | Harte Regeln fuer Start, BLOCKED und Handover |
| `scenarios.md` | Deklarierte Implementation-Traces |

## Prosa-Quellen

- [FK-20](/T:/codebase/claude-agentkit3/concept/technical-design/20_workflow_engine_state_machine.md)
- [DK-02](/T:/codebase/claude-agentkit3/concept/domain-design/02-pipeline-orchestrierung.md)
- [FK-27](/T:/codebase/claude-agentkit3/concept/technical-design/27_verify_pipeline_closure_orchestration.md)
