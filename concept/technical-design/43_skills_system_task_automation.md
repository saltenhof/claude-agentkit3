---
concept_id: FK-43
title: Skills-System und Aufgabenautomatisierung
module: skills
domain: agent-skills
status: active
doc_kind: core
parent_concept_id:
authority_over:
  - scope: skills
defers_to:
  - target: FK-20
    scope: workflow-engine
    reason: Execute-userstory skill orchestrates pipeline phases managed by the workflow engine
  - target: FK-44
    scope: prompt-bundles
    reason: Skill-Templates werden ueber die Prompt-Bundle-Materialisierung gebunden (FK-44)
supersedes: []
superseded_by:
tags: [skills, automation, prompt-templates, symlink-binding, extensibility]
prose_anchor_policy: strict
formal_refs:
  - formal.skills-and-bundles.entities
  - formal.skills-and-bundles.state-machine
  - formal.skills-and-bundles.commands
  - formal.skills-and-bundles.events
  - formal.skills-and-bundles.invariants
  - formal.skills-and-bundles.scenarios
---

# 43 — Skills-System und Task-Automation

## 43.1 Zweck

<!-- PROSE-FORMAL: formal.skills-and-bundles.entities, formal.skills-and-bundles.invariants -->

Skills sind vordefinierte Prompt-Anleitungen, die Agents methodisch
durch komplexe Aufgaben führen. Sie standardisieren nicht nur den
Ablauf, sondern heben die Qualität des Ergebnisses, indem sie
bewährte Methodik einbetten, die ein Agent ohne Anleitung nicht
konsistent anwenden würde (FK-12-019 bis FK-12-021).

## 43.2 Skill-Format und Ablage

<!-- PROSE-FORMAL: formal.skills-and-bundles.state-machine, formal.skills-and-bundles.commands, formal.skills-and-bundles.events, formal.skills-and-bundles.scenarios -->

### 43.2.1 Dateistruktur

Ein Skill ist ein Verzeichnis mit einer `SKILL.md` (oder `skill.md`)
Datei. Claude Code erwartet Skills an normierten Orten; AgentKit
weicht davon nicht ab.

```
<skill-root>/
└── create-userstory/
    └── SKILL.md
```

Die `SKILL.md` ist ein Markdown-Dokument, das Claude Code als
Skill erkennt und bei Aufruf (z.B. `/create-userstory`) als
Prompt lädt.

**Normierte Skill-Orte:**

| Ort | Zweck |
|-----|------|
| `~/.claude/skills/` | User-/systemweite Skills |
| `{projekt-root}/.claude/skills/` | Projektspezifische Skill-Bindung |

**Architekturentscheidung für AgentKit 3/4:**
- Der kanonische Skill-Inhalt liegt systemweit in versionierten
  AgentKit-Bundles.
- Im Projekt liegen unter `.claude/skills/` nur Symlinks auf die
  ausgewählten Bundle-Verzeichnisse.
- Das Projekt enthält damit einen Claude-Code-kompatiblen Bindungspunkt,
  aber nicht die Skill-Quelle selbst.

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

Skills können Platzhalter enthalten, die beim Binden eines Projekts
aus der Projektkonfiguration substituiert oder zur Laufzeit aufgelöst
werden (Kap. 50):

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
| **User Story Creation (core)** | `create-userstory-core/` | Neue Stories erstellen | VektorDB-Abgleich, Anforderungsstruktur, ACs, Feldbelegung, Größenschätzung |
| **User Story Creation (ARE)** | `create-userstory-are/` | Neue Stories mit ARE erstellen | Wie oben plus ARE-spezifische Pflichtschritte |
| **Execute User Story (core)** | `execute-userstory-core/` | Story-Umsetzung orchestrieren | 5-Phasen-Pipeline ohne ARE-Annahmen |
| **Execute User Story (ARE)** | `execute-userstory-are/` | Story-Umsetzung mit ARE orchestrieren | 5-Phasen-Pipeline mit ARE-Pfaden |
| **Lookup User Story** | `lookup-userstory/` | Stories suchen und anzeigen | VektorDB-Suche, GitHub-Issue-Abfrage |
| **LLM Discussion** | `llm-discussion/` | Multi-LLM-Sparring | Rollenverteilung, Rundenstruktur, Konvergenzprüfung |

### 43.3.2 Optionale Skills

| Skill | Verzeichnis | Aufgabe | Voraussetzung |
|-------|-----------|---------|--------------|
| **Manage Requirements** | `manage-requirements/` | ARE-Anforderungen verwalten | `features.are: true` |
| **Research** | Kein eigener Skill, Worker-Prompt | Strukturierte Recherche | — |
| **Semantic Review** | `semantic-review/` | Strukturierte Code-Qualitätsbewertung | — |

**Profilregel:** Skills und Prompts müssen so spezifisch wie möglich
sein. Profilunterschiede wie `ARE` vs. `non-ARE` werden deshalb nicht
als große Fallunterscheidung innerhalb eines Skills modelliert, sondern
über getrennte Varianten. Die Projektauswahl der passenden Variante
erfolgt bei der Registrierung/Bundlung, nicht während der Skill-Laufzeit.

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

## 43.4 Skill-Bereitstellung und Projektbindung

### 43.4.1 Systemweite Installation (FK-12-026)

Der Installer kopiert Skills nicht inhaltlich ins Zielprojekt.
Stattdessen:

1. installiert er versionierte AgentKit-Skill-Bundles systemweit
2. wählt projektweise das passende Profil (`core`, `are`, ...)
3. erzeugt unter `.claude/skills/` Symlinks auf genau diese
   systemweiten Bundle-Verzeichnisse

Beispiel:

```text
C:\ProgramData\AgentKit\bundles\4.0.0\core\skills\execute-userstory\
T:\repo\.claude\skills\execute-userstory  ->  C:\ProgramData\AgentKit\bundles\4.0.0\core\skills\execute-userstory
```

```python
def bind_skill(skill_name: str, bundle_root: Path, project_root: Path) -> None:
    source = bundle_root / "skills" / skill_name
    target = project_root / ".claude" / "skills" / skill_name
    create_symlink(source, target)
```

### 43.4.2 Platzhalter-Substitution und Bundle-Parameter

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

### 43.5.1 Versionierung über Bundle-Version und Projektbindung

Die Projektbindung trackt, auf welche Bundle-Version ein Projekt zeigt:

```json
{
  "agentkit_bundle_version": "4.0.0",
  "project_profile": "core",
  "bound_skills": ["create-userstory-core", "execute-userstory-core"]
}
```

### 43.5.2 Upgrade-Verhalten

Bei AgentKit-Upgrade werden bestehende Projekte nicht automatisch auf
`latest` umgehängt. Der Installer zeigt auf eine konkrete Bundle-Version.
Ein Projekt erhält eine neue Skill-Version erst, wenn seine
Symlink-Bindungen bewusst auf die neue Bundle-Version umgestellt werden.

## 43.6 Erweiterbarkeit (FK-12-027)

### 43.6.1 Eigene Skills hinzufügen

Neue Skills können hinzugefügt werden, ohne den AgentKit-Kern zu
ändern. Dazu wird ein neues systemweites Bundle oder Teilbundle
bereitgestellt; das Projekt bindet es anschließend über Symlink ein:

```
C:\ProgramData\AgentKit\bundles\4.0.0\custom\
├── create-userstory-core/
├── execute-userstory-core/
└── my-custom-review/
    └── SKILL.md
```

Claude Code erkennt den Skill automatisch über den projektlokalen
Symlink unter `.claude/skills/`.

### 43.6.2 Skill-Qualität

Die Qualität der Story-Umsetzung hängt wesentlich davon ab, dass
Agents auf erprobte Abläufe zurückgreifen statt bei jeder Aufgabe
eigene Methodik zu erfinden. Deshalb:

- Mitgelieferte Skills werden mit AgentKit getestet
- Projektspezifische Skills liegen in der Verantwortung des
  Menschen
- Skill-Änderungen können über den Failure Corpus evaluiert
  werden: Wenn nach einer Skill-Änderung die QA-Runden steigen,
  ist das ein messbares Signal (Experiment-Tags, Kap. 68.7.2)

**F-43-030 — Normative Skill-Nutzung (FK-12-030):** Agents **müssen** mitgelieferte Skills für standardisierte Aufgaben verwenden, anstatt ad-hoc-Methodik einzusetzen. Für Aufgaben, zu denen ein passender Skill existiert, ist dessen Nutzung normativ vorgeschrieben — nicht optional. Ein Agent, der eine Story erstellt ohne den `create-userstory`-Skill zu verwenden, oder der ein semantisches Review ohne den `semantic-review`-Skill durchführt, verhält sich nicht regelkonform. Dieses Prinzip gilt gleichermassen für Pflicht- und optionale Skills, sofern deren Voraussetzung erfüllt ist.

---

*FK-Referenzen: FK-12-019 bis FK-12-027 (Skills komplett)*
