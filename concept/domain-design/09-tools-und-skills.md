---
concept_id: DK-09
title: Tool-Governance (CCAG)
module: ccag-domain
domain: governance-and-guards
status: active
doc_kind: core
parent_concept_id:
authority_over:
  - scope: tool-governance
defers_to:
  - DK-12
  - FK-42
supersedes: []
superseded_by:
tags: [tools, ccag, hooks]
formal_scope: prose-only
glossary:
  exported_terms:
    - id: ccag
      definition: >
        Claude Code Agent Governance. Der registrierte Hook-Matcher erfasst die
        in FK-42 festgelegten Tool-Namen, trifft jedoch keine Autoritaets- oder
        Freigabeentscheidung. Harte Guards und Principal Capabilities bleiben
        die benannten Durchsetzungsstellen.
      see_also:
        - term: ccag-gatekeeper
          domain: governance-and-guards
        - term: guard-system
          domain: governance-and-guards
  internal_terms: []
---

# 09 — Tool-Governance (CCAG)

**Übersicht:** [00-uebersicht.md](00-uebersicht.md)

---

Neben Governance und Qualitätssicherung bringt AgentKit Infrastruktur
mit, die den Entwicklungsprozess selbst produktiver und zuverlässiger
macht. Zwei Komponenten sind dabei zentral: die parameterbasierte
Tool-Governance (CCAG, hier) und das spezialisierte Skill-System
([12-skills-und-skill-system.md](12-skills-und-skill-system.md)).

### 9.1 Tool-Matcher (CCAG)

AgentKit registriert `ccag_gatekeeper` fuer die in FK-42 festgelegten
Tool-Namen. Dieser Katalog stellt fuer alle Harness-Adapter dieselbe
Matcher-Identitaet bereit, trifft aber keine Entscheidung ueber einen Aufruf.

Zulaessigkeit und Blockade gehoeren ausschliesslich zu den benannten Guards
und zum Principal-Capability-Modell. CCAG speichert keine menschlichen
Entscheidungen, erzeugt keine Regeln und eroeffnet keine spaeter entscheidbare
Anfrage. Damit bleibt die Adapter-Schnittstelle stabil, ohne eine zweite
Autoritaet neben den Durchsetzungsstellen zu bilden.

### 9.2 Spezialisierte Skills

> Skills (User Story Creation, LLM Discussion, Semantic Review,
> Research) und das Skill-System (versionierte Bundles, Symlink-
> Bindung) sind in **DK-12 (Spezialisierte Skills und Skill-System)**
> normiert.
