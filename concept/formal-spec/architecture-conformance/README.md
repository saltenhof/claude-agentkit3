---
title: Architecture Conformance Formal Spec
status: active
doc_kind: context
---

# Architecture Conformance

Dieser Kontext formalisiert den maschinell pruefbaren Teil der
AK3-Komponentenarchitektur.

## Scope

- Komponentenklassifikation ueber Namespace-Prefixe
- Blutgruppen A/R/T fuer die initial stabilen Komponenten
- deterministische Importgrenzen zwischen Fachkomponenten, Adaptern und
  Treibern
- ausgewaehlte Azyklizitaetsregeln fuer stabile Komponenten

## Out of Scope

- vollstaendige Single-Writer-Pruefung auf SQL-/Repository-Ebene
- semantische Bewertung fachlicher Verantwortung aus Freitext
- nicht-Python-Code

## Prosa-Quellen

- [FK-01](/T:/codebase/claude-agentkit3/concept/technical-design/01_systemkontext_und_architekturprinzipien.md)
- [FK-17](/T:/codebase/claude-agentkit3/concept/technical-design/17_fachliches_datenmodell_ownership.md)
- [FK-18](/T:/codebase/claude-agentkit3/concept/technical-design/18_relationales_abbildungsmodell_postgres.md)
- [FK-65](/T:/codebase/claude-agentkit3/concept/technical-design/65_komponentenarchitektur_und_architekturkonformanz.md)
