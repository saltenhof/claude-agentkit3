---
title: Prompt Runtime Formal Spec
status: active
doc_kind: context
---

# Prompt Runtime

Dieser Kontext formalisiert die Trennung zwischen kanonischen
Prompt-Bundles, Projektbindung und run-scoped Prompt-Instanzen.

## Scope

Im Scope sind:

- systemweite, immutable Prompt-Bundles
- Projektbindung fuer kuenftige Runs
- Run-Pinning von Prompt-Bundle-Versionen
- Materialisierung konkreter Prompt-Instanzen
- Auditierbarkeit und Drift-Schutz

## Out of Scope

Nicht Teil dieses Kontexts sind:

- konkrete Template-Inhalte einzelner Prompts
- LLM-Pool-Protokolle selbst
- Skill-Inhalte und Skill-Methodik
- Datenbanktabellen- und SQL-Details

## Dateien

| Datei | Inhalt |
|---|---|
| `entities.md` | Prompt-nahe Kernentitaeten |
| `state-machine.md` | Bindung, Run-Pinning und Nutzungspfad |
| `commands.md` | Offizielle Prompt-Aufloesungs- und Materialisierungskommandos |
| `events.md` | Auditierbare Prompt-Ereignisse |
| `invariants.md` | Harte Regeln gegen Prompt-Drift und Cache-Autoritaet |
| `scenarios.md` | Deklarierte Prompt-Runtime-Traces |

## Prosa-Quellen

- [FK-44](/T:/codebase/claude-agentkit3/concept/technical-design/44_prompt_bundles_materialization_audit.md)
