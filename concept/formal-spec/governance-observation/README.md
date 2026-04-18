---
title: Governance Observation Formal Spec
status: active
doc_kind: context
---

# Governance Observation

Dieser Kontext formalisiert die kontinuierliche Governance-
Beobachtung zwischen Sensorik, Rolling Window und Adjudication.

## Scope

Im Scope sind:

- Hook- und Phasen-Signale
- Rolling-Window-Risikoscore
- Incident-Kandidaten
- LLM-Adjudication und deterministische Massnahmen

## Out of Scope

Nicht Teil dieses Kontexts sind:

- das Integrity-Gate vor Closure
- manuelle Story-Split- oder Story-Reset-Entscheidungen
- reguläre Guard-Blockentscheidungen pro Tool-Aufruf

## Dateien

| Datei | Inhalt |
|---|---|
| `entities.md` | Beobachtungsnahe Kernentitaeten |
| `state-machine.md` | Incident-Lebenszyklus von Signal bis Massnahme |
| `commands.md` | Offizielle Beobachtungs-Kommandos |
| `events.md` | Beobachtungs-spezifische Events |
| `invariants.md` | Harte Regeln fuer Schwellenwerte und Sofortstopps |
| `scenarios.md` | Deklarierte Beobachtungstraces |

## Prosa-Quellen

- [FK-35](/T:/codebase/claude-agentkit3/concept/technical-design/35_integrity_gate_governance_beobachtung_eskalation.md)
- [FK-91](/T:/codebase/claude-agentkit3/concept/technical-design/91_api_event_katalog.md)
