---
concept_id: DK-08
title: Checkpoint-basierte Selbstinstallation
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
---

# 08 — Checkpoint-basierte Selbstinstallation

**Quelle:** Konsolidiert aus agentkit-domain-concept.md, Kapitel 11
**Datum:** 2026-04-02
**Übersicht:** [00-uebersicht.md](00-uebersicht.md)

---

AgentKit installiert sich über eine Folge idempotenter Checkpoints selbst
in ein Zielprojekt: GitHub-Projekt-Setup mit Custom Fields, Pipeline-
Konfiguration, Hook-Registration, Skill- und Prompt-Deployment. Jeder
Checkpoint ist einzeln wiederholbar, der Gesamtzustand wird in einem
Manifest festgehalten. Upgrades erkennen nutzerseitige Anpassungen und
erhalten sie, statt sie zu überschreiben. Eine nachgelagerte Verifikation
prüft den Installationszustand auf Konsistenz.
