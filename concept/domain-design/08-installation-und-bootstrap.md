---
concept_id: DK-08
title: Projektregistrierung und Bootstrap
module: installation
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
---

# 08 — Projektregistrierung und Bootstrap

<!-- PROSE-FORMAL: formal.installer.entities, formal.installer.state-machine, formal.installer.commands, formal.installer.invariants, formal.installer.scenarios -->

**Quelle:** Konsolidiert aus agentkit-domain-concept.md, Kapitel 11
**Datum:** 2026-04-02
**Übersicht:** [00-uebersicht.md](00-uebersicht.md)

---

AgentKit wird systemweit installiert und registriert anschließend ein
Zielprojekt über eine Folge idempotenter Checkpoints: GitHub-Projekt-
Setup mit Custom Fields, projektlokale Pipeline-Konfiguration,
Hook-Registration und projektlokale Symlink-Bindung auf systemweite,
versionierte Skill-Bundles. Laufzeitdaten und kanonische Zustände
liegen nicht im Projekt, sondern zentral. Eine nachgelagerte
Verifikation prüft den Registrierungszustand auf Konsistenz.
