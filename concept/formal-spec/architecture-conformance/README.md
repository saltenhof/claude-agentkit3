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
- Enabling-Constraint-Pruefungen, die weiterreichende Invarianten hart
  pruefbar machen (FK-07 §7.7.4): Verbot von Roh-SQL/Direkt-Cursor
  ausserhalb der Repository-Module (Single-Writer-Gating), Verbot
  direkter Transport-/Client-Importe ausserhalb der Adapter
  (op_id/correlation_id-Gating), Ablauf-Pruefung strukturierter
  deletability-Metadaten
- Auffaelligkeits-Pruefungen (severity warning) fuer Konstellationen,
  die eine Abwaegung erfordern, aber kein hartes Verbot sind (z. B.
  AC012: A-Modul importiert direkt T-Modul → AT-Mediation pruefen)

## Out of Scope

- vollstaendige *semantische* Single-Writer-Pruefung von beliebigem
  dynamischem SQL-/ORM-/Reflection-Code (das import- und literalbasierte
  Single-Writer-Gating ueber das Roh-SQL-Verbot ist dagegen in Scope;
  FK-07 §7.7.4)
- semantische Repository-Konformanz und Bewertung fachlicher
  Verantwortung aus Freitext (bleibt test-/review-gestuetzt)
- nicht-Python-Code

## Prosa-Quellen

- [FK-01](/T:/codebase/claude-agentkit3/concept/technical-design/01_systemkontext_und_architekturprinzipien.md)
- [FK-17](/T:/codebase/claude-agentkit3/concept/technical-design/17_fachliches_datenmodell_ownership.md)
- [FK-18](/T:/codebase/claude-agentkit3/concept/technical-design/18_relationales_abbildungsmodell_postgres.md)
- [FK-07](/T:/codebase/claude-agentkit3/concept/technical-design/07_komponentenarchitektur_und_architekturkonformanz.md)
