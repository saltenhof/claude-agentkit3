---
title: Verify Formal Spec
status: active
doc_kind: context
---

# Verify

Dieser Kontext formalisiert die Verify-Phase als vierstufigen
Qualitaets- und Evidenzprozess vor Closure.

## Scope

Im Scope sind:

- `verify_context` und fail-closed Eintrittsregeln
- die vier Verify-Schichten
- QA-Zyklus bis `passed`, `failed` oder `escalated`
- Policy-Evaluation als Abschluss der Verify-Phase

## Out of Scope

Nicht Teil dieses Kontexts sind:

- Closure und Merge
- Story-Creation, Setup oder Exploration
- eigentliche Code-Remediation in der Implementation-Phase
- administrative Reset- oder Split-Pfade

## Dateien

| Datei | Inhalt |
|---|---|
| `entities.md` | Verify-nahe Kernentitaeten |
| `state-machine.md` | Prozesszustand von Layer 1 bis Policy |
| `commands.md` | Offizielle Verify-Kommandos |
| `events.md` | Verify-spezifische Events |
| `invariants.md` | Harte Regeln fuer verify_context, Layer und Outcome |
| `scenarios.md` | Deklarierte Verify-Traces |

## Prosa-Quellen

- [FK-27](/T:/codebase/claude-agentkit3/concept/technical-design/27_verify_pipeline_closure_orchestration.md)
- [FK-20](/T:/codebase/claude-agentkit3/concept/technical-design/20_workflow_engine_state_machine.md)
- [DK-02](/T:/codebase/claude-agentkit3/concept/domain-design/02-pipeline-orchestrierung.md)
- [FK-91](/T:/codebase/claude-agentkit3/concept/technical-design/91_api_event_katalog.md)
