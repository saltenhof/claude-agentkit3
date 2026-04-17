"""Prompt templates for worker agents."""

from __future__ import annotations


def _worker_implementation() -> str:
    return """\
# Worker-Prompt: Implementation Story {story_id}

## Auftrag
Implementiere die User Story **{story_id}: {title}**.

## Story-Details
- **Issue:** #{issue_nr}
- **Typ:** Implementation
- **Modus:** {mode}
- **Groesse:** {size}

## Akzeptanzkriterien
{body}

## Arbeitsverzeichnis
{project_root}

## Regeln
- Lies CLAUDE.md im Projektroot zuerst
- Implementiere vollstaendig - keine TODOs, keine Stubs
- Tests schreiben fuer neue Logik
- Am Ende: commit + push

[SENTINEL:worker-implementation-v1:{story_id}]
"""


def _worker_bugfix() -> str:
    return """\
# Worker-Prompt: Bugfix Story {story_id}

## Auftrag
Behebe den Bug beschrieben in **{story_id}: {title}**.

## Bug-Details
- **Issue:** #{issue_nr}
- **Typ:** Bugfix

## Fehlerbeschreibung
{body}

## Arbeitsverzeichnis
{project_root}

## Regeln
- Reproduzierenden Test ZUERST schreiben (muss vor dem Fix fehlschlagen)
- Dann den Bug fixen
- Test muss nach dem Fix gruen sein
- Am Ende: commit + push

[SENTINEL:worker-bugfix-v1:{story_id}]
"""


def _worker_concept() -> str:
    return """\
# Worker-Prompt: Concept Story {story_id}

## Auftrag
Erstelle das Konzeptdokument fuer **{story_id}: {title}**.

## Anforderungen
- **Issue:** #{issue_nr}
- **Typ:** Concept

## Beschreibung
{body}

## Regeln
- Konzept als Markdown unter concept/ anlegen
- Fachliche Vollstaendigkeit vor Prosa
- Keine Code-Implementierung - nur Design
- Am Ende: commit + push

[SENTINEL:worker-concept-v1:{story_id}]
"""


def _worker_research() -> str:
    return """\
# Worker-Prompt: Research Story {story_id}

## Auftrag
Recherchiere das Thema beschrieben in **{story_id}: {title}**.

## Forschungsfrage
- **Issue:** #{issue_nr}
- **Typ:** Research

## Beschreibung
{body}

## Regeln
- Ergebnisse als Markdown dokumentieren
- Quellen angeben
- Empfehlungen formulieren
- Am Ende: commit + push

[SENTINEL:worker-research-v1:{story_id}]
"""


def _worker_exploration() -> str:
    return """\
# Worker-Prompt: Exploration fuer {story_id}

## Auftrag
Erstelle ein Design-Artefakt fuer \
**{story_id}: {title}** BEVOR die Implementierung beginnt.

## Story-Details
- **Issue:** #{issue_nr}
- **Modus:** Exploration

## Anforderungen
{body}

## Deliverables
1. Design-Dokument mit Architekturentscheidungen
2. Betroffene Dateien identifizieren
3. Risiken und Abhaengigkeiten benennen
4. KEINE Implementierung - nur Design

[SENTINEL:worker-exploration-v1:{story_id}]
"""


def _worker_remediation() -> str:
    return """\
# Worker-Prompt: Remediation fuer {story_id} (Runde {round_nr})

## Auftrag
Behebe die QA-Findings aus der Verify-Phase \
fuer **{story_id}: {title}**.

## Findings
{feedback}

## Regeln
- NUR die genannten Findings adressieren
- Keine Scope-Erweiterung
- Tests aktualisieren wenn noetig
- Am Ende: commit + push

[SENTINEL:worker-remediation-v1:{story_id}]
"""


def _build_templates() -> dict[str, str]:
    return {
        "worker-implementation": _worker_implementation(),
        "worker-bugfix": _worker_bugfix(),
        "worker-concept": _worker_concept(),
        "worker-research": _worker_research(),
        "worker-exploration": _worker_exploration(),
        "worker-remediation": _worker_remediation(),
    }


TEMPLATES = _build_templates()

__all__ = ["TEMPLATES"]
