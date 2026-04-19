---
title: Installer Formal Spec
status: active
doc_kind: context
---

# Installer

Dieser Kontext formalisiert die projektbezogene Registrierung,
Verifikation und Re-Bindung von AgentKit 3.

## Scope

Im Scope sind:

- der offizielle `register-project`-Pfad
- der read-only Verifikationspfad
- idempotente Checkpoint-Ausfuehrung
- versionierte Bundle-Bindungen und projektlokale Symlinks
- Upgrade-/Rebind-Faelle mit Customization-Preservation

## Out of Scope

Nicht Teil dieses Kontexts sind:

- die normale Story-Pipeline
- fachliche Story-Erzeugung und Story-Ausfuehrung
- konkrete Paketmanager- oder OS-Installationsdetails
- SQL- oder State-Backend-Implementierungsdetails

## Dateien

| Datei | Inhalt |
|---|---|
| `entities.md` | Installer-nahe Kernentitaeten |
| `state-machine.md` | Prozesszustand von Registrierung, Dry-Run und Verifikation |
| `commands.md` | Offizielle Installer-Kommandos |
| `events.md` | Installer-spezifische Events |
| `invariants.md` | Harte Regeln fuer Idempotenz, Bundles und Customization-Preservation |
| `scenarios.md` | Deklarierte Installer-Traces |

## Prosa-Quellen

- [FK-50](/T:/codebase/claude-agentkit3/concept/technical-design/50_installer_checkpoint_engine_bootstrap.md)
- [FK-51](/T:/codebase/claude-agentkit3/concept/technical-design/51_upgrade_migration_customization_preservation.md)
- [DK-08](/T:/codebase/claude-agentkit3/concept/domain-design/08-installation-und-bootstrap.md)
- [FK-10](/T:/codebase/claude-agentkit3/concept/technical-design/10_runtime_deployment_speicher.md)
- [FK-43](/T:/codebase/claude-agentkit3/concept/technical-design/43_skills_system_task_automation.md)
- [FK-91](/T:/codebase/claude-agentkit3/concept/technical-design/91_api_event_katalog.md)
