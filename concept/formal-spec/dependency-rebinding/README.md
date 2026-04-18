---
title: Dependency Rebinding Formal Spec
status: active
doc_kind: context
---

# Dependency Rebinding

Dieser Kontext formalisiert das Umbiegen expliziter Story-Abhaengigkeiten
im offiziellen Story-Split-Pfad.

## Scope

Im Scope sind:

- explizite Story-Dependency-Kanten aus dem Split-Plan
- deterministische Auswahl der neuen Ziel-Storys
- Ablehnung mehrdeutiger oder unvollstaendiger Rebindings
- Schutz vor stillen Kantenverlusten, Duplikaten und Zyklusbildung
- deklarierte Rebinding-Szenarien

## Out of Scope

Nicht Teil dieses Kontexts sind:

- allgemeines Dependency-Management ausserhalb eines Story-Splits
- freie manuelle Dependency-Manipulation
- Story-Erstellung der Nachfolger selbst
- GitHub- oder Weaviate-Implementierungsdetails

## Dateien

| Datei | Inhalt |
|---|---|
| `entities.md` | Rebinding-nahe Kernentitaeten |
| `state-machine.md` | Prozesszustand des Rebinding-Subflows |
| `commands.md` | Offizielle Rebinding-Operationen |
| `events.md` | Rebinding-spezifische Events |
| `invariants.md` | Harte Regeln fuer Auswahl, Vollstaendigkeit und Graph-Integritaet |
| `scenarios.md` | Deklarierte Rebinding-Traces |

## Prosa-Quellen

- [FK-54](/T:/codebase/claude-agentkit3/concept/technical-design/54_story_split_service_scope_explosion.md)
- [FK-17](/T:/codebase/claude-agentkit3/concept/technical-design/17_fachliches_datenmodell_ownership.md)
- [FK-18](/T:/codebase/claude-agentkit3/concept/technical-design/18_relationales_abbildungsmodell_postgres.md)
- [FK-91](/T:/codebase/claude-agentkit3/concept/technical-design/91_api_event_katalog.md)
