---
title: Guard System Formal Spec
status: active
doc_kind: context
---

# Guard System

Dieser Kontext formalisiert das GuardSystem als hook-basierten
Enforcement-Mechanismus fuer verbotene oder eingeschraenkte Aktionen.

## Scope

Im Scope sind:

- Hook-gebundene Enforcement-Pfade
- Branch-, Orchestrator-, Artefakt- und Story-Creation-Guards
- erlaubte offizielle Ausnahmen fuer Systempfade
- Blockieren vs. Erlauben als formale Guard-Entscheidung

## Out of Scope

Nicht Teil dieses Kontexts sind:

- CCAG als separate Permission-Runtime
- Integrity-Gate in Closure
- Telemetrie-Aggregation
- freie Agentenlogik ausserhalb des Hook-Enforcements

## Dateien

| Datei | Inhalt |
|---|---|
| `entities.md` | Guard-nahe Kernentitaeten |
| `state-machine.md` | Zustand eines Guard-Checks |
| `commands.md` | Offizielle bzw. verbotene Operationsfamilien |
| `events.md` | Guard-spezifische Events |
| `invariants.md` | Harte Allow-/Deny-Regeln |
| `scenarios.md` | Deklarierte Guard-Traces |

## Prosa-Quellen

- [FK-30](/T:/codebase/claude-agentkit3/concept/technical-design/30_hook_adapter_guard_enforcement.md)
- [FK-31](/T:/codebase/claude-agentkit3/concept/technical-design/31_branch_guard_orchestrator_guard_artefaktschutz.md)
- [FK-35](/T:/codebase/claude-agentkit3/concept/technical-design/35_integrity_gate_governance_beobachtung_eskalation.md)
