---
title: Story Creation Formal Spec
status: active
doc_kind: context
---

# Story Creation

Dieser Kontext formalisiert die offizielle Erzeugung neuer Stories vor
der Bearbeitungs-Pipeline.

## Scope

Im Scope sind:

- der offizielle Story-Creation-Pfad
- Konzeption, Pflichtpruefungen und Feldbelegung
- GitHub-Issue- und Project-Anlage
- deterministischer `story.md`-Export
- Freigabelogik `Backlog -> Approved`

## Out of Scope

Nicht Teil dieses Kontexts sind:

- die Bearbeitungs-Pipeline ab `Approved`
- Story-Split als administrativer Spezialpfad
- Reset-, Closure- oder Rebinding-Logik
- konkrete VektorDB- und LLM-Implementierungsdetails

## Dateien

| Datei | Inhalt |
|---|---|
| `entities.md` | Story-Creation-nahe Kernentitaeten |
| `state-machine.md` | Prozesszustand des Story-Creation-Pfads |
| `commands.md` | Offizielle Story-Creation-Kommandos |
| `events.md` | Story-Creation-spezifische Events |
| `invariants.md` | Harte Regeln fuer Pflichtpruefungen, Status und Export |
| `scenarios.md` | Deklarierte Story-Creation-Traces |

## Prosa-Quellen

- [FK-21](/T:/codebase/claude-agentkit3/concept/technical-design/21_story_creation_pipeline.md)
- [FK-12](/T:/codebase/claude-agentkit3/concept/technical-design/12_github_integration_repo_operationen.md)
- [FK-17](/T:/codebase/claude-agentkit3/concept/technical-design/17_fachliches_datenmodell_ownership.md)
- [FK-18](/T:/codebase/claude-agentkit3/concept/technical-design/18_relationales_abbildungsmodell_postgres.md)
- [FK-91](/T:/codebase/claude-agentkit3/concept/technical-design/91_api_event_katalog.md)
- [FK-54](/T:/codebase/claude-agentkit3/concept/technical-design/54_story_split_service_scope_explosion.md)
