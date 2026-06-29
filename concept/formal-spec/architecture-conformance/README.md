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
- Blutgruppen A/R/T/0 (siehe `concept/methodology/software-blutgruppen.md`
  fuer die Volldefinition)
- deterministische Importgrenzen zwischen Fachkomponenten, Adaptern und
  Treibern
- ausgewaehlte Azyklizitaetsregeln fuer stabile Komponenten
- Ownership der kanonischen Datenfamilien ueber gebundene Write-/
  Read-Surfaces (welche Komponente eine Familie schreiben bzw. lesen
  darf; Import-Ebene)
- Auffaelligkeits-Pruefungen (severity warning) fuer Konstellationen,
  die eine Abwaegung erfordern, aber kein hartes Verbot sind (z. B.
  AC012: A-Modul importiert direkt T-Modul → AT-Mediation pruefen)

## Out of Scope

- Code-Qualitaet (Roh-SQL vs. Repository-Funktion, Typ-Hygiene,
  Komplexitaet, Naming) — Sache von Linting/Code-Review
- Observability-Konventionen (`op_id`/`correlation_id` auf Aufrufen) —
  Sache der Telemetrie-/Operations-Vertraege
- Lifecycle-/Tech-Debt-Steuerung (deletability-Deadlines)
- semantische Komponenten-/Repository-Konformanz und Bewertung
  fachlicher Verantwortung (bleibt test-/review-gestuetzt)
- nicht-Python-Code

## Prosa-Quellen

- [FK-01](/T:/codebase/claude-agentkit3/concept/technical-design/01_systemkontext_und_architekturprinzipien.md)
- [FK-17](/T:/codebase/claude-agentkit3/concept/technical-design/17_fachliches_datenmodell_ownership.md)
- [FK-18](/T:/codebase/claude-agentkit3/concept/technical-design/18_relationales_abbildungsmodell_postgres.md)
- [FK-07](/T:/codebase/claude-agentkit3/concept/technical-design/07_komponentenarchitektur_und_architekturkonformanz.md)
