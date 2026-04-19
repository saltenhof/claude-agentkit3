---
title: Skills and Bundles Formal Spec
status: active
doc_kind: context
---

# Skills and Bundles

Dieser Kontext formalisiert die kanonische Bereitstellung von Skills und
Prompt-Bundles in AgentKit 3.

## Scope

Im Scope sind:

- systemweite, versionierte Bundle-Inhalte
- Profil- und Variantenwahl (`core` vs. `are`)
- projektlokale Claude-Code-kompatible Symlink-Bindungen
- Verbot von `latest`- oder Source-Checkout-Bindungen
- Upgrade-/Rebind-Semantik fuer bestehende Projekte

## Out of Scope

Nicht Teil dieses Kontexts sind:

- Story-Pipeline und Workflow-Orchestrierung
- konkrete Prompt-Inhalte einzelner Skills
- OS- oder Dateisystem-Implementierungsdetails jenseits der
  Bindungssemantik
- konkrete Installer-Checkpoint-Reihenfolge

## Dateien

| Datei | Inhalt |
|---|---|
| `entities.md` | Skill-/Bundle-nahe Kernentitaeten |
| `state-machine.md` | Zustandsraum von Variantenwahl und Bindung |
| `commands.md` | Offizielle Bundle- und Binding-Operationen |
| `events.md` | Bundle- und Binding-spezifische Events |
| `invariants.md` | Harte Regeln fuer Versionierung, Profilwahl und Symlink-Modell |
| `scenarios.md` | Deklarierte Bundle- und Binding-Traces |

## Prosa-Quellen

- [FK-43](/T:/codebase/claude-agentkit3/concept/technical-design/43_skills_system_task_automation.md)
- [FK-10](/T:/codebase/claude-agentkit3/concept/technical-design/10_runtime_deployment_speicher.md)
- [FK-50](/T:/codebase/claude-agentkit3/concept/technical-design/50_installer_checkpoint_engine_bootstrap.md)
- [FK-51](/T:/codebase/claude-agentkit3/concept/technical-design/51_upgrade_migration_customization_preservation.md)
- [FK-92](/T:/codebase/claude-agentkit3/concept/technical-design/92_verzeichnis_namenskonventionen.md)
