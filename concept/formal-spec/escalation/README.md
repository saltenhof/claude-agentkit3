---
title: Escalation Formal Spec
status: active
doc_kind: context
---

# Escalation

Dieser Kontext formalisiert den offiziellen menschlichen
Interventionspfad nach `PAUSED` oder `ESCALATED`.

## Scope

Im Scope sind:

- einheitliches Verhalten nach Eskalationsausloesern
- Unterschied `PAUSED` vs. `ESCALATED`
- offizieller Resume-/Reset-Eskalation-Pfad
- Weiterleitung in Story-Split als regulaere Aufloesung von Scope-Explosion

## Out of Scope

Nicht Teil dieses Kontexts sind:

- die eigentlichen Ursachen der Eskalation
- Story-Reset und Story-Split als interne Service-Flows
- Closure-Gate- oder Governance-Logik selbst

## Dateien

| Datei | Inhalt |
|---|---|
| `entities.md` | Eskalationsnahe Kernentitaeten |
| `state-machine.md` | Aufloesungszustand von PAUSED/ESCALATED |
| `commands.md` | Offizielle CLI-Kommandos fuer die Aufloesung |
| `events.md` | Eskalations-spezifische Events |
| `invariants.md` | Harte Regeln fuer Resume, neuer Run und Redirect |
| `scenarios.md` | Deklarierte Eskalationstraces |

## Prosa-Quellen

- [FK-35](/T:/codebase/claude-agentkit3/concept/technical-design/35_integrity_gate_governance_beobachtung_eskalation.md)
- [FK-91](/T:/codebase/claude-agentkit3/concept/technical-design/91_api_event_katalog.md)
