---
concept_id: DK-08
title: Projektregistrierung und Bootstrap
module: installation
domain: installation-and-bootstrap
status: active
doc_kind: core
parent_concept_id:
authority_over:
  - scope: installation
defers_to: []
supersedes: []
superseded_by:
tags: [installation, bootstrap, checkpoints, idempotent, upgrades]
prose_anchor_policy: strict
formal_refs:
  - formal.installer.entities
  - formal.installer.state-machine
  - formal.installer.commands
  - formal.installer.invariants
  - formal.installer.scenarios
glossary:
  exported_terms:
    - id: bootstrap-status
      definition: >
        Aktueller Registrierungszustand eines Projekts gegenueber AgentKit.
        Gibt an, ob alle Installer-Checkpoints erfolgreich abgeschlossen wurden
        und das Projekt vollstaendig im zentralen State-Backend registriert ist.
    - id: installer-checkpoint
      definition: >
        Atomare, idempotente Einheit des Bootstrap-Ablaufs. Jeder Checkpoint
        hat einen eindeutigen Bezeichner, prueft seinen Zielzustand und
        erzeugt genau einen CheckpointResult. Die Reihenfolge ist durch den
        Installer-Flow vorgegeben; bereits erfuelLte Checkpoints werden bei
        erneutem Lauf uebersprungen.
    - id: manifest-contract
      definition: >
        Maschinenlesbarer Vertrag zwischen dem Installer und dem Zielprojekt,
        der die gebundenen Bundle-Versionen, das Projektprofil und die
        registrierten Hooks deklariert. Kanonische Quelle fuer
        Upgrade-Entscheide und Verifikationslaeufe.
---

# 08 — Projektregistrierung und Bootstrap

<!-- PROSE-FORMAL: formal.installer.entities, formal.installer.state-machine, formal.installer.commands, formal.installer.invariants, formal.installer.scenarios -->

**Quelle:** Konsolidiert aus agentkit-domain-concept.md, Kapitel 11
**Datum:** 2026-04-02
**Übersicht:** [00-uebersicht.md](00-uebersicht.md)

---

AgentKit wird systemweit installiert und registriert anschließend ein
Zielprojekt über eine Folge idempotenter Checkpoints: GitHub-Repo-Bindung
für Code-Operationen, optionale Default-Projektstruktur für leere
Neuprojekte, projektlokale Pipeline-Konfiguration, Hook-Registration
projektlokale Symlink-Bindung auf systemweite, versionierte
Skill-Bundles und den offiziellen Project-Edge-Launcher fuer
Agent-Kommandos. Die Default-Projektstruktur ist ein explizites Opt-in;
Bestandsprojekte und Projekte mit eigener Soll-Struktur erhalten sie
nicht automatisch. Laufzeitdaten und kanonische Zustände liegen nicht
im Projekt, sondern zentral. Eine nachgelagerte Verifikation prüft den
Registrierungszustand auf Konsistenz.
