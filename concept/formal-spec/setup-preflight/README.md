---
title: Setup Preflight Formal Spec
status: active
doc_kind: context
---

# Setup Preflight

Dieser Kontext formalisiert den offiziellen Setup- und
Preflight-Pfad bis zur Startfaehigkeit einer Story-Bearbeitung.

## Scope

Im Scope sind:

- die neun Preflight-Checks
- Story-Context-Berechnung
- Worktree- und Branch-Setup
- Guard-Aktivierung
- Modus-Ermittlung als Setup-Ausgang

## Out of Scope

Nicht Teil dieses Kontexts sind:

- Story-Creation vor `Approved`
- Exploration, Implementation oder Verify selbst
- administrative Recovery-Pfade wie Reset oder Split
- freie manuelle Cleanup- oder Git-Operationen

## Dateien

| Datei | Inhalt |
|---|---|
| `entities.md` | Setup-nahe Kernentitaeten |
| `state-machine.md` | Prozesszustand von Preflight bis Mode-Routing |
| `commands.md` | Offizielle Setup-/Preflight-Kommandos |
| `events.md` | Setup-spezifische Events |
| `invariants.md` | Harte Regeln fuer Startfaehigkeit und Fail-Closed |
| `scenarios.md` | Deklarierte Setup-Traces |

## Prosa-Quellen

- [FK-22](/T:/codebase/claude-agentkit3/concept/technical-design/22_setup_preflight_worktree_guard_activation.md)
- [FK-20](/T:/codebase/claude-agentkit3/concept/technical-design/20_workflow_engine_state_machine.md)
- [DK-02](/T:/codebase/claude-agentkit3/concept/domain-design/02-pipeline-orchestrierung.md)
- [FK-91](/T:/codebase/claude-agentkit3/concept/technical-design/91_api_event_katalog.md)
