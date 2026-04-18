---
title: Story Reset Formal Spec
status: active
doc_kind: context
---

# Story Reset

Dieser Kontext formalisiert den administrativen Reset-Pfad fuer
korrupt gewordene Story-Umsetzungen.

## Scope

Im Scope sind:

- der offizielle CLI-Pfad `agentkit reset-story`
- der Reset-Prozesszustand
- Reset-spezifische Kernentitaeten
- Reset-Events
- harte Purge- und Fence-Invarianten
- deklarierte Reset-Szenarien

## Out of Scope

Nicht Teil dieses Kontexts sind:

- die normale Story-Phasenorchestrierung
- der Story-Split-Pfad
- die Detailsemantik einzelner Datenbanktabellen
- Dashboard- oder KPI-Berechnung im Detail

## Dateien

| Datei | Inhalt |
|---|---|
| `entities.md` | Reset-nahe Kernentitaeten |
| `state-machine.md` | Prozesszustand des StoryResetService |
| `commands.md` | Offizielle Reset-Kommandos |
| `events.md` | Reset-spezifische Events |
| `invariants.md` | Harte Reset-Regeln |
| `scenarios.md` | Deklarierte Reset-Pfade |

## Prosa-Quellen

- [FK-53](/T:/codebase/claude-agentkit3/concept/technical-design/53_story_reset_service_recovery_flow.md)
- [FK-17](/T:/codebase/claude-agentkit3/concept/technical-design/17_fachliches_datenmodell_ownership.md)
- [FK-18](/T:/codebase/claude-agentkit3/concept/technical-design/18_relationales_abbildungsmodell_postgres.md)
- [FK-20](/T:/codebase/claude-agentkit3/concept/technical-design/20_workflow_engine_state_machine.md)
- [FK-52](/T:/codebase/claude-agentkit3/concept/technical-design/52_betrieb_monitoring_audit_runbooks.md)
