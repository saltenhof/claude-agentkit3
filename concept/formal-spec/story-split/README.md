---
title: Story Split Formal Spec
status: active
doc_kind: context
---

# Story Split

Dieser Kontext formalisiert den administrativen Split-Pfad fuer
`Scope-Explosion`.

## Scope

Im Scope sind:

- der offizielle CLI-Pfad `agentkit split-story`
- der Split-Prozesszustand
- Split-spezifische Entitaeten
- Split-Events
- harte Invarianten fuer Cancelled-/Nachfolger-/Rebinding-Semantik
- deklarierte Split-Szenarien

## Out of Scope

Nicht Teil dieses Kontexts sind:

- die normale Story-Phasenorchestrierung
- die vollstaendige Story-Creation-Semantik der Nachfolger
- der Story-Reset-Pfad
- Telemetrie-Storage und KPI-Aggregation im Detail

## Dateien

| Datei | Inhalt |
|---|---|
| `entities.md` | Split-nahe Kernentitaeten |
| `state-machine.md` | Prozesszustand des StorySplitService |
| `commands.md` | Offizielle Split-Kommandos |
| `events.md` | Split-spezifische Events |
| `invariants.md` | Harte Split-Regeln |
| `scenarios.md` | Deklarierte Split-Pfade |

## Prosa-Quellen

- [FK-54](/T:/codebase/claude-agentkit3/concept/technical-design/54_story_split_service_scope_explosion.md)
- [FK-12](/T:/codebase/claude-agentkit3/concept/technical-design/12_github_integration_repo_operationen.md)
- [FK-17](/T:/codebase/claude-agentkit3/concept/technical-design/17_fachliches_datenmodell_ownership.md)
- [FK-18](/T:/codebase/claude-agentkit3/concept/technical-design/18_relationales_abbildungsmodell_postgres.md)
- [FK-35](/T:/codebase/claude-agentkit3/concept/technical-design/35_integrity_gate_governance_beobachtung_eskalation.md)
