---
concept_id: DK-12
title: Spezialisierte Skills und Skill-System
module: skills
domain: agent-skills
status: active
doc_kind: core
parent_concept_id:
authority_over:
  - scope: skills-domain
defers_to:
  - DK-09
  - DK-08
  - FK-43
supersedes: []
superseded_by:
tags: [skills, automation]
formal_scope: prose-only
---

# 12 — Spezialisierte Skills und Skill-System

**Quelle:** Konsolidiert aus DK-09 §9.2 (Stand 2026-04-02)
**Datum:** 2026-04-29
**Übersicht:** [00-uebersicht.md](00-uebersicht.md)

---

AgentKit bringt für verschiedene Aufgabenstellungen spezialisierte
Skills mit. Ein Skill ist eine vordefinierte Prompt-Anleitung, die
einen Agenten methodisch durch eine komplexe Aufgabe führt. Skills
standardisieren nicht nur den Ablauf, sondern heben die Qualität des
Ergebnisses, indem sie bewährte Methodik einbetten, die ein Agent ohne
Anleitung nicht konsistent anwenden würde.

**Beispiele für mitgelieferte Skills:**

| Skill | Aufgabe | Was er standardisiert |
|-------|---------|---------------------|
| User Story Creation | Neue Stories erstellen | VektorDB-Abgleich, Anforderungsstruktur, Akzeptanzkriterien, Größenschätzung |
| LLM Discussion | Multi-LLM-Sparring zu einer Fragestellung | Rollenverteilung, Rundenstruktur, unabhängige Positionsbildung, Konvergenzprüfung |
| Semantic Review | LLM-basierte Code-Bewertung | Strukturiertes Scoring-Schema, Fokus auf die 12 definierten Checks |
| Research | Strukturierte Internetrecherche | Systematische Suche, Quellenvielfalt, Bewertungskriterien, Ergebnisablage |

Skills werden bei der Projektregistrierung
([08-installation-und-bootstrap.md](08-installation-und-bootstrap.md))
nicht inhaltlich ins Zielprojekt kopiert. Stattdessen liegen sie
systemweit in versionierten Bundles und werden projektlokal über
`.claude/skills/` per Symlink gebunden. Neue Skills können hinzugefügt
werden, ohne den Kern von AgentKit zu ändern. Die Qualität der
Story-Umsetzung hängt wesentlich davon ab, dass Agents nicht bei jeder
Aufgabe ihre eigene Methodik erfinden, sondern auf erprobte Abläufe
zurückgreifen.

## 12.1 Abgrenzung zu DK-09 (Tools/CCAG)

Skills sind **inhaltliche Methodik** (Was tut der Agent? Welche
Schritte? Welche Prüfungen?). Tool-Governance via CCAG (DK-09) ist
**Berechtigung** (Welche Tools darf der Agent ausführen? Mit welchen
Parametern?). Beide ergänzen sich:

- Ein Skill kann Tools voraussetzen (z.B. `git`, `gh`, `pytest`),
  ohne sie selbst freizugeben.
- CCAG kann Tools freigeben, ohne dem Agent eine Methodik
  vorzuschreiben.
- Erst beide zusammen ergeben einen Agenten, der eine Aufgabe
  konsistent und sicher ausführen kann.
