---
title: State Storage Formal Spec
status: active
doc_kind: context
---

# State Storage

Dieser Kontext formalisiert den PostgreSQL-basierten kanonischen
Speicherschnitt von AgentKit 3.

## Scope

Im Scope sind:

- fachliche Record-Families statt konkreter SQL-Tabellendetails
- Kanonizitaet, Single-Writer und `project_key`-Scope
- Reset-/Invalidierungsfolgen fuer Runtime-, Telemetrie- und
  Projektionsdaten
- nicht-blockierende Telemetrie
- deklarierte Storage-Szenarien fuer Persistenz, Rebuild und Purge

## Out of Scope

Nicht Teil dieses Kontexts sind:

- konkretes SQL-DDL, Indizes und Migrationsdetails
- ORM-Mappings und Query-Implementierungen
- Backup-, Replikations- oder HA-Topologien
- fachliche Story- oder Verify-Entscheidungslogik ausserhalb des
  Speicherschnitts

## Dateien

| Datei | Inhalt |
|---|---|
| `entities.md` | Fachliche Record-Families und ihre Kernattribute |
| `state-machine.md` | Storage-Kohärenz- und Purge-Zustände |
| `commands.md` | Offizielle Storage-Operationen |
| `events.md` | Storage-spezifische Ereignisse |
| `invariants.md` | Harte Regeln fuer Kanonizitaet, Scope und Reset-Closure |
| `scenarios.md` | Deklarierte Storage-Traces |

## Prosa-Quellen

- [FK-17](/T:/codebase/claude-agentkit3/concept/technical-design/17_fachliches_datenmodell_ownership.md)
- [FK-18](/T:/codebase/claude-agentkit3/concept/technical-design/18_relationales_abbildungsmodell_postgres.md)
- [FK-14](/T:/codebase/claude-agentkit3/concept/technical-design/14_telemetrie_eventing_workflow_metriken.md)
- [FK-15](/T:/codebase/claude-agentkit3/concept/technical-design/15_security_secrets_identity_zugriffsmodell.md)
- [FK-16](/T:/codebase/claude-agentkit3/concept/technical-design/16_qa_telemetrie_aggregation_dashboard.md)
- [FK-53](/T:/codebase/claude-agentkit3/concept/technical-design/53_story_reset_service_recovery_flow.md)
- [FK-91](/T:/codebase/claude-agentkit3/concept/technical-design/91_api_event_katalog.md)
