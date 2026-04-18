---
title: Conformance Formal Spec
status: active
doc_kind: context
---

# Conformance

Dieser Kontext formalisiert die vier Ebenen der Dokumententreue als
normativen Bewertungsprozess.

## Scope

Im Scope sind:

- Referenzdokument-Identifikation
- die vier Dokumententreue-Ebenen
- Payload-Grenzen und fail-closed Verhalten
- Conformance-Verdikte `PASS`, `PASS_WITH_CONCERNS`, `FAIL`

## Out of Scope

Nicht Teil dieses Kontexts sind:

- die technische Laufzeit der Verify-Schicht-2-/3-Aufrufe
- die Gate-Entscheidung vor Closure
- die StageRegistry-Planung

## Dateien

| Datei | Inhalt |
|---|---|
| `entities.md` | Conformance-nahe Kernentitaeten |
| `state-machine.md` | Bewertungszustand ueber die vier Ebenen |
| `commands.md` | Offizielle Bewertungs-Kommandos |
| `events.md` | Conformance-spezifische Events |
| `invariants.md` | Harte Regeln fuer Referenzen, Payload und Verdikte |
| `scenarios.md` | Deklarierte Conformance-Pfade |

## Prosa-Quellen

- [FK-32](/T:/codebase/claude-agentkit3/concept/technical-design/32_dokumententreue_conformance_service.md)
- [FK-91](/T:/codebase/claude-agentkit3/concept/technical-design/91_api_event_katalog.md)
