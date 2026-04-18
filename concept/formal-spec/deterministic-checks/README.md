---
title: Deterministic Checks Formal Spec
status: active
doc_kind: context
---

# Deterministic Checks

Dieser Kontext formalisiert die deterministischen Layer-1-Checks, die
Stage-Registry und die Policy-Engine als planenden und aggregierenden
Kern der Verify-Struktur.

## Scope

Im Scope sind:

- typisierte Stage-Definitionen
- Materialisierung eines StageExecutionPlans
- Layer-1-Checks und ihre Stage-Regeln
- Policy-Engine als Aggregator der Stage-Ergebnisse

## Out of Scope

Nicht Teil dieses Kontexts sind:

- konkrete LLM-Bewertungen in Schicht 2
- Adversarial-Testing-Details in Schicht 3
- Integrity-Gate in Closure
- Failure-Corpus-Promotion selbst

## Dateien

| Datei | Inhalt |
|---|---|
| `entities.md` | Stage- und Policy-nahe Kernentitaeten |
| `state-machine.md` | Plan- und Aggregationszustand |
| `commands.md` | Offizielle Registry-/Policy-Operationen |
| `events.md` | Stage-/Policy-Events |
| `invariants.md` | Harte Regeln fuer Registry, Applicability und Aggregation |
| `scenarios.md` | Deklarierte Deterministic-Check-Traces |

## Prosa-Quellen

- [FK-33](/T:/codebase/claude-agentkit3/concept/technical-design/33_deterministische_checks_stage_registry_policy_engine.md)
- [FK-27](/T:/codebase/claude-agentkit3/concept/technical-design/27_verify_pipeline_closure_orchestration.md)
- [FK-40](/T:/codebase/claude-agentkit3/concept/technical-design/40_are_integration_anforderungsvollstaendigkeit.md)
- [FK-41](/T:/codebase/claude-agentkit3/concept/technical-design/41_failure_corpus_pattern_promotion_check_factory.md)
- [FK-35](/T:/codebase/claude-agentkit3/concept/technical-design/35_integrity_gate_governance_beobachtung_eskalation.md)
