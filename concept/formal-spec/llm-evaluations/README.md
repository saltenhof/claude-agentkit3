---
title: LLM Evaluations Formal Spec
status: active
doc_kind: context
---

# LLM Evaluations

Dieser Kontext formalisiert Verify-Schicht 2 und Schicht 3 als
gemeinsamen Evidenzprozess.

## Scope

Im Scope sind:

- die drei parallelen Layer-2-Bewertungen
- Layer-2-Aggregation und Divergenz
- der Adversarial-Agent als Layer 3
- Remediation-spezifische Finding-Resolution und Mandatory Targets

## Out of Scope

Nicht Teil dieses Kontexts sind:

- die normative Dokumententreue-Bewertung selbst
- deterministic checks und Policy-Engine
- das Closure-Gate

## Dateien

| Datei | Inhalt |
|---|---|
| `entities.md` | Bewertungs- und Adversarial-Entitaeten |
| `state-machine.md` | Laufzeit von Layer 2 bis Layer 3 |
| `commands.md` | Offizielle Evaluate-/Adversarial-Kommandos |
| `events.md` | LLM-Evaluation-spezifische Events |
| `invariants.md` | Harte Regeln fuer Parallelitaet, Sparring und Remediation |
| `scenarios.md` | Deklarierte Layer-2-/Layer-3-Traces |

## Prosa-Quellen

- [FK-34](/T:/codebase/claude-agentkit3/concept/technical-design/34_llm_bewertungen_adversarial_testing_runtime.md)
- [FK-91](/T:/codebase/claude-agentkit3/concept/technical-design/91_api_event_katalog.md)
