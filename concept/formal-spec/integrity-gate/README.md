---
title: Integrity Gate Formal Spec
status: active
doc_kind: context
---

# Integrity Gate

Dieser Kontext formalisiert das letzte Closure-Gate vor dem Merge.

## Scope

Im Scope sind:

- Pflicht-Artefakt-Pruefung
- acht Gate-Dimensionen und Telemetrie-Nachweise
- offizieller Override-Pfad
- Gate-Audit-Log

## Out of Scope

Nicht Teil dieses Kontexts sind:

- die inhaltliche Bewertung der Implementierung
- Hook-Sensorik der Governance-Beobachtung
- Story-Split oder Story-Reset als Folgeentscheidungen

## Dateien

| Datei | Inhalt |
|---|---|
| `entities.md` | Gate-nahe Kernentitaeten |
| `state-machine.md` | Gate-Lauf von Start bis PASS/FAIL/Override |
| `commands.md` | Offizielle Integrity-Gate-Kommandos |
| `events.md` | Gate-spezifische Events |
| `invariants.md` | Harte Regeln fuer Pflichtartefakte, Run-Grenzen und Override |
| `scenarios.md` | Deklarierte Gate-Traces |

## Prosa-Quellen

- [FK-35](/T:/codebase/claude-agentkit3/concept/technical-design/35_integrity_gate_governance_beobachtung_eskalation.md)
- [FK-91](/T:/codebase/claude-agentkit3/concept/technical-design/91_api_event_katalog.md)
