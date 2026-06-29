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
        Maschinenlesbarer Vertrag ueber die gebundenen Bundle-Versionen,
        das Projektprofil und die registrierten Hooks. Die kanonische
        Quelle liegt zentral (Projektregistrierung: registered_bundle_version
        + config_digest); eine projektlokale Materialisierung ist nur eine
        Config-/Pinning-Projektion (Lockfile), kein Laufzeit-Anker
        (FK-10 §10.2.7). Grundlage fuer Upgrade-Entscheide und
        Verifikationslaeufe.
---

# 08 — Projektregistrierung und Bootstrap

<!-- PROSE-FORMAL: formal.installer.entities, formal.installer.state-machine, formal.installer.commands, formal.installer.invariants, formal.installer.scenarios -->

**Übersicht:** [00-uebersicht.md](00-uebersicht.md)

---

AgentKit besteht aus zwei Installationsanteilen unterschiedlicher Lokalität:
dem **State- und Orchestrierungs-Core**, der wahlweise auf dem
Entwicklerrechner oder — für Team-Betrieb — zentral auf einem dedizierten
Server läuft, und der **agentenseitigen Installation** (versionierte Prompt-/
Skill-Bundles sowie der AK3-Client mit Hooks und Project-Edge-Launcher), die
auf jedem Entwicklerrechner lokal vorliegen muss, weil der Agent-Harness sie
transparent als Dateien liest. Anschließend registriert AgentKit ein
Zielprojekt über eine Folge idempotenter Checkpoints: GitHub-Repo-Bindung
für Code-Operationen, optionale Default-Projektstruktur für leere
Neuprojekte, projektlokale Pipeline-Konfiguration, Hook-Registration,
projektlokale Symlink-Bindung auf die rechnerweite (nicht server-zentrale),
versionierte Skill-Bundle-Installation und den offiziellen
Project-Edge-Launcher fuer Agent-Kommandos. Die Default-Projektstruktur ist ein explizites Opt-in;
Bestandsprojekte und Projekte mit eigener Soll-Struktur erhalten sie
nicht automatisch. Laufzeitdaten und kanonische Zustände liegen nicht
im Projekt, sondern zentral. Eine nachgelagerte Verifikation prüft den
Registrierungszustand auf Konsistenz.

**Drei Installationsebenen (Dreifaltigkeit).** Fachlich sind es **drei**
getrennte Ebenen mit je eigenem Installationsweg, Update und Uninstall
(technische Ausführung in FK-10 §10.2):

1. **Zentral (Core)** — Backend, Frontend und der kanonische
   State-Speicher. Eigene Bootstrap-Routine mit manuellen Anteilen, **kein**
   Checkpoint-Installer.
2. **Entwicklermaschine** — einmal pro Rechner: der AK3-Client (Hooks +
   Project-Edge) und der versionierte, rechnerweite Skill-/Prompt-Bundle-
   Store.
3. **Projektraum** — pro Projekt nur dünne Bindungen (Konfiguration,
   Hook-Registrierung, Skill-Links auf die rechnerweite Installation,
   Project-Edge-Launcher), installiert durch die idempotente
   Checkpoint-Folge.

Höhere Ebenen sind Voraussetzung der niedrigeren; **kanonischer Zustand
lebt nur zentral**. Daraus folgt fachlich: Deployment ist **nicht
einmalig** — Updates werden vom Core annonciert und von der Maschine
gezogen (kein Server-Push), und beim Entfernen darf eine niedrigere Ebene
niemals zentralen Zustand einer höheren löschen (**Detach ≠
Decommission**).
