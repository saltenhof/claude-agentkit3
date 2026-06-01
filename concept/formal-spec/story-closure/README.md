---
title: Story Closure Formal Spec
status: active
doc_kind: context
---

# Story Closure

Dieser Kontext formalisiert den offiziellen Closure-Pfad einer Story:
Integrity-Gate (inkl. Dimension 9 SonarQube-Green, FK-35 §35.2.4a), den
Pre-Merge-Scan-und-Merge-Block unter dem Merge-Serialisierungs-Lock
(FK-29 §29.1a, FK-33 §33.6.3), Push des Story-Branches und ff-Merge nach
`main` innerhalb des Locks, Schliessen des Issues und Abschluss der Story.

## Scope

Im Scope sind:

- der offizielle Service-API-Pfad `POST /phases/closure/start` (FK-91 §91.1a; normativ) sowie der Operator-Recovery-CLI-Pfad `agentkit run-phase closure` (FK-91 §91.1; Spezialfall)
- die Merge-Policies `ff_only` und `no_ff`
- der Pre-Merge-Scan-und-Merge-Block: Merge-Serialisierungs-Lock, integrierter-Kandidat-Scan/Attestation, ff-Merge unter dem Lock (Push innerhalb), Post-Merge-Reconcile (FK-29 §29.1a, FK-33 §33.6.3/§33.6.4)
- die Reihenfolge Integrity-Gate (inkl. Dimension 9) vor dem Merge-Block, gruener Scan vor Push, Push vor Merge
- Guard-Regeln fuer den offiziellen Closure-Pfad
- harte Abschluss- und Eskalationsregeln (inkl. main-Drift / roter integrierter Kandidat)
- deklarierte Closure-Szenarien

## Out of Scope

Nicht Teil dieses Kontexts sind:

- allgemeine Git-Governance ausserhalb des Closure-Pfads
- PR-Review- oder Freigabeprozesse
- manuelle Konfliktbehebung per Rebase oder Force-Push
- Build-/Testausfuehrung innerhalb des Implementation-QA-Subflows gegen die Capability `verify-system`
- vollstaendige Datenhaltung von Telemetrie und KPIs

## Dateien

| Datei | Inhalt |
|---|---|
| `entities.md` | Closure-nahe Kernentitaeten |
| `state-machine.md` | Prozesszustand des offiziellen Closure-Pfads |
| `commands.md` | Offizielle Closure-Kommandos und verbotene History-Rewrite-Pfade |
| `events.md` | Closure-spezifische Events |
| `invariants.md` | Harte Regeln fuer Push, Merge, Guard und Abschluss |
| `scenarios.md` | Deklarierte Closure-Traces |

## Prosa-Quellen

- [FK-12](/T:/codebase/claude-agentkit3/concept/technical-design/12_github_integration_repo_operationen.md)
- [FK-27](/T:/codebase/claude-agentkit3/concept/technical-design/27_verify_pipeline_closure_orchestration.md)
- [FK-29](/T:/codebase/claude-agentkit3/concept/technical-design/29_closure_sequence.md)
- [FK-33](/T:/codebase/claude-agentkit3/concept/technical-design/33_deterministische_checks_stage_registry_policy_engine.md)
- [FK-35](/T:/codebase/claude-agentkit3/concept/technical-design/35_integrity_gate_governance_beobachtung_eskalation.md)
- [FK-31](/T:/codebase/claude-agentkit3/concept/technical-design/31_branch_guard_orchestrator_guard_artefaktschutz.md)
- [FK-04](/T:/codebase/claude-agentkit3/concept/technical-design/04_betrieb_monitoring_audit_runbooks.md)
- [FK-91](/T:/codebase/claude-agentkit3/concept/technical-design/91_api_event_katalog.md)
- [FK-17](/T:/codebase/claude-agentkit3/concept/technical-design/17_fachliches_datenmodell_ownership.md)
- [FK-18](/T:/codebase/claude-agentkit3/concept/technical-design/18_relationales_abbildungsmodell_postgres.md)
