---
title: Truth Boundary Checker Formal Spec
status: active
doc_kind: context
---

# Truth Boundary Checker

Dieser Kontext formalisiert die harte Wahrheitsgrenze zwischen
kanonischem State-Backend und nicht-kanonischen Story-Exportdateien
sowie den deterministischen Concept-to-Code-Contract-Checker.

## Scope

- geschützte Runtime-/Governance-Module
- verbotene Exportdateinamen und Loader
- erlaubte Ausnahmepfade
- deterministische Vertragsverletzungen im Code

## Out of Scope

- konkrete PostgreSQL-Queries
- Runtime-Refactor aller bestehenden Legacy-Pfade
- nicht-Python-Code

## Prosa-Quellen

- [FK-01](/T:/codebase/claude-agentkit3/concept/technical-design/01_systemkontext_und_architekturprinzipien.md)
- [FK-17](/T:/codebase/claude-agentkit3/concept/technical-design/17_fachliches_datenmodell_ownership.md)
- [FK-18](/T:/codebase/claude-agentkit3/concept/technical-design/18_relationales_abbildungsmodell_postgres.md)
- [FK-33](/T:/codebase/claude-agentkit3/concept/technical-design/33_deterministische_checks_stage_registry_policy_engine.md)
- [FK-35](/T:/codebase/claude-agentkit3/concept/technical-design/35_integrity_gate_governance_beobachtung_eskalation.md)
- [FK-06](/T:/codebase/claude-agentkit3/concept/technical-design/06_truth_boundary_and_concept_code_contract_checker.md)
