---
title: Exploration Formal Spec
status: active
doc_kind: context
---

# Exploration

Dieser Kontext formalisiert den offiziellen Exploration-Pfad fuer
implementierende Stories im Exploration Mode.

## Scope

Im Scope sind:

- Exploration als eigener Phase- und Gate-Prozess
- H2-Nachklassifikation nach Klasse 1/2/3/4
- Feindesign-Subprozess fuer Klasse 2
- `PAUSED` bei Klasse 1/3/4
- Gate-Entscheidung `PENDING | APPROVED | REJECTED`

## Out of Scope

Nicht Teil dieses Kontexts sind:

- Setup-/Preflight-Regeln vor Exploration
- Implementation und Verify nach erfolgreicher Exploration
- Story-Split- und Story-Reset-Ausfuehrung selbst
- konkrete Prompt-Texte der Worker

## Dateien

| Datei | Inhalt |
|---|---|
| `entities.md` | Exploration-nahe Kernentitaeten |
| `state-machine.md` | Zustandsraum von Draft, Gate und Mandatsrouting |
| `commands.md` | Offizielle Exploration-Operationen |
| `events.md` | Exploration-spezifische Events |
| `invariants.md` | Harte Regeln fuer Gate, H2, Feindesign und Pause |
| `scenarios.md` | Deklarierte Exploration-Traces |

## Prosa-Quellen

- [FK-23](/T:/codebase/claude-agentkit3/concept/technical-design/23_modusermittlung_exploration_change_frame.md)
- [FK-25](/T:/codebase/claude-agentkit3/concept/technical-design/25_mandatsgrenzen_feindesign_autonomie.md)
- [FK-35](/T:/codebase/claude-agentkit3/concept/technical-design/35_integrity_gate_governance_beobachtung_eskalation.md)
- [DK-02](/T:/codebase/claude-agentkit3/concept/domain-design/02-pipeline-orchestrierung.md)
- [DK-03](/T:/codebase/claude-agentkit3/concept/domain-design/03-governance-und-guards.md)
