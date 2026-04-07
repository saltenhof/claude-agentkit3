---
concept_id: FK-43
title: Skills-System und Aufgabenautomatisierung
module: skills
status: active
doc_kind: core
parent_concept_id:
authority_over:
  - scope: skills
defers_to:
  - target: FK-20
    scope: workflow-engine
    reason: Execute-userstory skill orchestrates pipeline phases managed by the workflow engine
supersedes: []
superseded_by:
tags: [skills, automation, prompt-templates, deployment, extensibility]
---

# 43 — Skills-System und Task-Automation

## 43.1 Zweck

Skills sind vordefinierte Prompt-Anleitungen, die Agents methodisch
durch komplexe Aufgaben führen. Sie standardisieren nicht nur den
Ablauf, sondern heben die Qualität des Ergebnisses, indem sie
bewährte Methodik einbetten, die ein Agent ohne Anleitung nicht
konsistent anwenden würde (FK-12-019 bis FK-12-021).

## 43.2 Skill-Format

### 43.2.1 Dateistruktur

Ein Skill ist ein Verzeichnis mit einer `SKILL.md` (oder `skill.md`)
Datei:

```
skills/
└── create-userstory/
    └── skill.md
```

Die `skill.md` ist ein Markdown-Dokument, das Claude Code als
Skill erkennt und bei Aufruf (z.B. `/create-userstory`) als
Prompt lädt.

### 43.2.2 Skill-Aufbau

```markdown
---
description: "Erstellt eine neue User Story mit VektorDB-Abgleich und Zieltreue-Prüfung"
---

# Create User Story

## Trigger
Wenn der Nutzer eine neue Story erstellen möchte.

## Vorgehen

### Schritt 1: Konzeption
...

### Schritt 2: VektorDB-Abgleich
...
```

### 43.2.3 Platzhalter

Skills können Platzhalter enthalten, die vom Installer bei der
Deployment substituiert werden (Kap. 50):

| Platzhalter | Ersetzt durch |
|-------------|--------------|
| `{{gh_owner}}` | GitHub-Owner aus Config |
| `{{gh_repo}}` | GitHub-Repo aus Config |
| `{{project_prefix}}` | Story-ID-Prefix |
| `{{project_number}}` | GitHub-Project-Nummer |

## 43.3 Mitgelieferte Skills

### 43.3.1 Pflicht-Skills (FK-12-022 bis FK-12-025)

| Skill | Verzeichnis | Aufgabe | Was er standardisiert |
|-------|-----------|---------|---------------------|
| **User Story Creation** | `create-userstory/` | Neue Stories erstellen | VektorDB-Abgleich, Anforderungsstruktur, ACs, Feldbelegung, Größenschätzung |
| **Execute User Story** | `execute-userstory/` | Story-Umsetzung orchestrieren | 5-Phasen-Pipeline, Agent-Spawn, Phase-State lesen/reagieren |
| **Lookup User Story** | `lookup-userstory/` | Stories suchen und anzeigen | VektorDB-Suche, GitHub-Issue-Abfrage |
| **LLM Discussion** | `llm-discussion/` | Multi-LLM-Sparring | Rollenverteilung, Rundenstruktur, Konvergenzprüfung |

### 43.3.2 Optionale Skills

| Skill | Verzeichnis | Aufgabe | Voraussetzung |
|-------|-----------|---------|--------------|
| **Manage Requirements** | `manage-requirements/` | ARE-Anforderungen verwalten | `features.are: true` |
| **Research** | Kein eigener Skill, Worker-Prompt | Strukturierte Recherche | — |
| **Semantic Review** | `semantic-review/` | Strukturierte Code-Qualitätsbewertung | — |

**F-43-029 — Semantic Review Skill (FK-12-029):** Ein dedizierter Semantic-Review-Skill muss mitgeliefert werden. Er bewertet Code-Beiträge anhand eines strukturierten Scoring-Schemas mit mindestens 12 definierten Prüfdimensionen, darunter Benennung, Fehlerbehandlung, zyklomatische Komplexität, Testabdeckung, Kopplung, Kohäsion, Dokumentation, Sicherheitsaspekte, Rückwärtskompatibilität, Performance-Implikationen, Konsistenz mit dem Projektstandard und Anforderungstreue. Für jede Dimension wird ein normierter Score und eine Begründung ausgegeben; das Gesamtergebnis fliesst als strukturiertes Artefakt in die Verify-Phase ein.

### 43.3.3 Execute User Story Skill

Der wichtigste Skill. Er orchestriert die gesamte Story-
Bearbeitungs-Pipeline:

1. Liest freigegebene Story aus GitHub Project
2. Ruft `agentkit run-phase setup` auf
3. Liest Phase-State → spawnt Worker (oder Exploration-Worker)
4. Wartet auf Worker-Ende
5. Ruft `agentkit run-phase verify` auf
6. Liest Phase-State → bei FAIL: spawnt Remediation-Worker
7. Bei PASS: ruft `agentkit run-phase closure` auf
8. Bei Eskalation: stoppt und informiert Mensch

**Der Skill ist der Orchestrator.** Er enthält die Logik, die
den Phase-State liest und die richtigen Aktionen ableitet. Der
Phase Runner ist das deterministische Backend, der Skill ist
die Agent-seitige Steuerungsschicht.

## 43.4 Skill-Deployment

### 43.4.1 Installation (FK-12-026)

Der Installer (Checkpoint 7) kopiert Skills ins Zielprojekt:

```python
def deploy_skills(agentkit_path: Path, project_root: Path,
                  config: PipelineConfig) -> list[str]:
    skills_src = agentkit_path / "userstory" / "skills"
    skills_dst = project_root / "skills"

    deployed = []
    for skill_dir in skills_src.iterdir():
        if skill_dir.is_dir():
            dst = skills_dst / skill_dir.name
            copy_with_placeholders(skill_dir, dst, config)
            deployed.append(skill_dir.name)

    return deployed
```

### 43.4.2 Platzhalter-Substitution

Nur in `.md`-Dateien. Einfaches String-Replace, keine
Template-Engine:

```python
def substitute_placeholders(content: str, config: PipelineConfig) -> str:
    replacements = {
        "{{gh_owner}}": config.github.owner,
        "{{gh_repo}}": config.github.repo_primary,
        "{{project_prefix}}": config.project_prefix,
        "{{project_number}}": str(config.github.project_number),
    }
    for placeholder, value in replacements.items():
        content = content.replace(placeholder, value)
    return content
```

## 43.5 Skill-Versionierung

### 43.5.1 Versionierung über Installer-Manifest

Das Manifest (`.installed-manifest.json`) trackt welche Skills
in welcher Version deployt wurden:

```json
{
  "installed_files": {
    "skills/create-userstory/skill.md": {
      "source_hash": "abc123...",
      "installed_at": "2026-03-17T10:00:00+01:00"
    }
  }
}
```

### 43.5.2 Upgrade-Verhalten

Bei AgentKit-Upgrade vergleicht der Installer die Source-Hashes:
- Gleicher Hash → Datei unverändert, kein Update nötig
- Verschiedener Hash + Nutzer hat Datei nicht geändert → Update
- Verschiedener Hash + Nutzer hat Datei geändert → `.bak` Backup,
  dann Update. Nutzer-Anpassungen müssen manuell nachgezogen werden.

## 43.6 Erweiterbarkeit (FK-12-027)

### 43.6.1 Eigene Skills hinzufügen

Neue Skills können hinzugefügt werden, ohne den AgentKit-Kern zu
ändern. Einfach ein neues Verzeichnis unter `skills/` mit
`SKILL.md` erstellen:

```
skills/
├── create-userstory/     # Mitgeliefert
├── execute-userstory/    # Mitgeliefert
└── my-custom-review/     # Projektspezifisch
    └── SKILL.md
```

Claude Code erkennt den Skill automatisch.

### 43.6.2 Skill-Qualität

Die Qualität der Story-Umsetzung hängt wesentlich davon ab, dass
Agents auf erprobte Abläufe zurückgreifen statt bei jeder Aufgabe
eigene Methodik zu erfinden. Deshalb:

- Mitgelieferte Skills werden mit AgentKit getestet
- Projektspezifische Skills liegen in der Verantwortung des
  Menschen
- Skill-Änderungen können über den Failure Corpus evaluiert
  werden: Wenn nach einer Skill-Änderung die QA-Runden steigen,
  ist das ein messbares Signal (Experiment-Tags, Kap. 14.7.2)

**F-43-030 — Normative Skill-Nutzung (FK-12-030):** Agents **müssen** mitgelieferte Skills für standardisierte Aufgaben verwenden, anstatt ad-hoc-Methodik einzusetzen. Für Aufgaben, zu denen ein passender Skill existiert, ist dessen Nutzung normativ vorgeschrieben — nicht optional. Ein Agent, der eine Story erstellt ohne den `create-userstory`-Skill zu verwenden, oder der ein semantisches Review ohne den `semantic-review`-Skill durchführt, verhält sich nicht regelkonform. Dieses Prinzip gilt gleichermassen für Pflicht- und optionale Skills, sofern deren Voraussetzung erfüllt ist.

---

*FK-Referenzen: FK-12-019 bis FK-12-027 (Skills komplett)*
