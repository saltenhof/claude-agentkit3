---
title: Story Closure Formal Spec
status: active
doc_kind: context
---

# Story Closure

Dieser Kontext formalisiert den offiziellen Closure-Pfad einer Story:
Push des Story-Branches, Merge nach `main`, Schliessen des Issues und
Abschluss der Story.

## Scope

Im Scope sind:

- der offizielle CLI-Pfad `agentkit run-phase closure`
- die Merge-Policies `ff_only` und `no_ff`
- die Reihenfolge Push vor Merge
- Guard-Regeln fuer den offiziellen Closure-Pfad
- harte Abschluss- und Eskalationsregeln
- deklarierte Closure-Szenarien

## Out of Scope

Nicht Teil dieses Kontexts sind:

- allgemeine Git-Governance ausserhalb des Closure-Pfads
- PR-Review- oder Freigabeprozesse
- manuelle Konfliktbehebung per Rebase oder Force-Push
- Build-/Testausfuehrung innerhalb von Verify
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
- [FK-31](/T:/codebase/claude-agentkit3/concept/technical-design/31_branch_guard_orchestrator_guard_artefaktschutz.md)
- [FK-52](/T:/codebase/claude-agentkit3/concept/technical-design/52_betrieb_monitoring_audit_runbooks.md)
- [FK-91](/T:/codebase/claude-agentkit3/concept/technical-design/91_api_event_katalog.md)
- [FK-17](/T:/codebase/claude-agentkit3/concept/technical-design/17_fachliches_datenmodell_ownership.md)
- [FK-18](/T:/codebase/claude-agentkit3/concept/technical-design/18_relationales_abbildungsmodell_postgres.md)
