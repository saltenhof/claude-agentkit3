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
    reason: >
      agent-skills verwaltet Skill-Bundles eigenstaendig ueber Symlink-Bindungen
      (.claude/skills/). FK-44 (prompt-runtime) wird nur dann aufgerufen, wenn
      Skill-Inhalte zur Laufzeit eines Runs durch PromptRuntime.materialize_prompt
      aufgeloest werden muessen. Die Skill-Bundle-Mechanik (Versionierung,
      Symlink-Erzeugung, Projektbindung) bleibt vollstaendig in agent-skills.
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
glossary:
  exported_terms:
    - id: skill-binding
      definition: >
        Projektlokal erzeugte Verknuepfung (Symlink) von einem
        Claude-Code-Bindungspunkt im Projekt (.claude/skills/<name>)
        auf ein systemweites Bundle-Verzeichnis. Projektrepos duerfen
        ausschliesslich Symlinks enthalten, niemals die kanonische
        Skill-Quelle selbst.
      see_also:
        - term: skill-bundle
          domain: agent-skills
        - term: skill-id
          domain: agent-skills
    - id: skill-bundle
      definition: >
        Versioniertes, unveraenderliches Verzeichnis mit einer oder
        mehreren Skill-Varianten, das systemweit installiert wird.
        Jede Projektbindung zeigt auf genau eine konkrete
        Bundle-Version. Aliase wie latest sind als Produktionsziel
        verboten.
      see_also:
        - term: skill-variant
          domain: agent-skills
        - term: skill-binding
          domain: agent-skills
    - id: skill-id
      definition: >
        Eindeutiger Bezeichner eines Skills innerhalb eines Bundles,
        z.B. create-userstory-core. Bildet zusammen mit der
        Bundle-Version den stabilen Schluessel fuer Symlink-Bindungen
        und Upgrade-Tracking.
    - id: skill-lifecycle
      definition: >
        Zustandsfolge einer Skill-Bundlebindung vom initialen
        Requested-Zustand ueber Profile-Resolved, Bundle-Selected und
        Bound bis zu Verified oder Rejected. Jeder Zustandsuebergang
        prueft definierte Invarianten (vgl. formal.skills-and-bundles.state-machine).
      see_also:
        - term: skill-binding
          domain: agent-skills
    - id: skill-quality-metric
      definition: >
        Messbares Signal zur Bewertung der Effektivitaet eines Skills,
        z.B. Anzahl QA-Runden oder Failure-Corpus-Befunde nach einer
        Skill-Aenderung. Skill-Qualitaet ist nicht statisch, sondern
        wird ueber Experiment-Tags im Telemetriesystem beobachtet.
      see_also:
        - term: skill-id
          domain: agent-skills
  internal_terms:
    - id: placeholder-substitution
      reason: >
        Implementierungsdetail der Bundle-Materialisierung; kein
        exportierter Vertragsbegriff. Betrifft nur den Installer-Pfad
        und ist nicht Teil der oeffentlichen Skill-Schnittstelle.
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
Datei. Beide unterstuetzten Harnesses (Claude Code, Codex; FK-30
§30.11) erwarten Skills an harness-normierten Orten; AgentKit weicht
davon nicht ab und materialisiert pro Harness die jeweiligen
Symlink-Bindungspunkte.

```
<skill-root>/
└── create-userstory/
    └── SKILL.md
```

Die `SKILL.md` ist ein Markdown-Dokument, das der Harness
(Claude Code / Codex) als Skill erkennt und bei Aufruf (z.B.
`/create-userstory`) als Prompt lädt.

**Normierte Skill-Orte (Beispiel anhand Claude Code; FK-30 §30.11):**

| Ort | Zweck |
|-----|------|
| `~/.claude/skills/` | User-/systemweite Skills (Claude Code) |
| `{projekt-root}/.claude/skills/` | Projektspezifische Skill-Bindung (Claude Code) |

Codex hat ein harness-eigenes Aequivalent (Pfad-Konvention nach
Codex-Standard); der Codex-Adapter (FK-30 §30.11) materialisiert die
Symlinks am dortigen Bindungspunkt.

**Architekturentscheidung für AgentKit 3/4:**
- Der kanonische Skill-Inhalt liegt systemweit in versionierten
  AgentKit-Bundles.
- Im Projekt liegen unter dem harness-spezifischen Bindungspunkt
  (z. B. `.claude/skills/` fuer Claude Code) nur Symlinks auf die
  ausgewählten Bundle-Verzeichnisse.
- Das Projekt enthält damit pro Harness einen kompatiblen
  Bindungspunkt, aber nicht die Skill-Quelle selbst.

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
| `{{gh_owner}}` | GitHub-Owner aus Config (Code-Backend) |
| `{{gh_repo}}` | GitHub-Repo aus Config (Code-Backend; bei Multi-Repo: erstes Repo aus `participating_repos` falls Skill-Kontext eine Story hat, sonst `repositories[0].name`) |
| `{{project_key}}` | AK3-Project-Schluessel aus `project.yaml` (Story-Backend-Identifier) |
| `{{project_prefix}}` | Story-ID-Prefix aus `project.yaml` |

## 43.3 Mitgelieferte Skills

### 43.3.1 Pflicht-Skills (FK-12-022 bis FK-12-025)

| Skill | Verzeichnis | Aufgabe | Was er standardisiert |
|-------|-----------|---------|---------------------|
| **User Story Creation (core)** | `create-userstory-core/` | Neue Stories erstellen | VektorDB-Abgleich, Anforderungsstruktur, ACs, Feldbelegung, Größenschätzung |
| **User Story Creation (ARE)** | `create-userstory-are/` | Neue Stories mit ARE erstellen | Wie oben plus ARE-spezifische Pflichtschritte |
| **Execute User Story (core)** | `execute-userstory-core/` | Story-Umsetzung orchestrieren | 4-Phasen-Pipeline (Setup, Exploration, Implementation inkl. QA-Subflow, Closure) ohne ARE-Annahmen |
| **Execute User Story (ARE)** | `execute-userstory-are/` | Story-Umsetzung mit ARE orchestrieren | 4-Phasen-Pipeline (Setup, Exploration, Implementation inkl. QA-Subflow, Closure) mit ARE-Pfaden |
| **Lookup User Story** | `lookup-userstory/` | Stories suchen und anzeigen | VektorDB-Suche, AK3-Story-Backend-Abfrage |
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

**F-43-029 — Semantic Review Skill (FK-12-029):** Ein dedizierter Semantic-Review-Skill muss mitgeliefert werden. Er bewertet Code-Beitraege anhand eines strukturierten Scoring-Schemas mit mindestens 12 definierten Pruefdimensionen, darunter Benennung, Fehlerbehandlung, zyklomatische Komplexitaet, Testabdeckung, Kopplung, Kohaesion, Dokumentation, Sicherheitsaspekte, Rueckwaertskompatibilitaet, Performance-Implikationen, Konsistenz mit dem Projektstandard und Anforderungstreue. Fuer jede Dimension wird ein normierter Score und eine Begruendung ausgegeben; das Gesamtergebnis fliesst als strukturiertes Artefakt in den QA-Subflow innerhalb der Implementation-Phase ein.

### 43.3.3 Execute User Story Skill

Der wichtigste Skill. Er orchestriert die gesamte Story-
Bearbeitungs-Pipeline:

1. Liest freigegebene Story aus dem AK3-Story-Backend
2. Ruft `agentkit run-phase setup` auf
3. Liest Phase-State -> spawnt Worker (oder Exploration-Worker)
4. Wartet auf Worker-Ende
5. Ruft `agentkit run-phase implementation` auf — der QA-Subflow
   laeuft Subflow-intern in der Implementation-Phase und ruft die
   Capability `VerifySystem` (FK-27)
6. Liest Phase-State -> bei `qa_cycle_status: awaiting_remediation`:
   spawnt Remediation-Worker und ruft `agentkit run-phase implementation`
   erneut auf (Subflow-Loop, kein Phasenwechsel)
7. Bei `qa_cycle_status: pass` (Implementation COMPLETED): ruft
   `agentkit run-phase closure` auf
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
2. waehlt projektweise das passende Profil (`core`, `are`, ...)
3. erzeugt **pro unterstuetzem Harness** Symlinks auf genau diese
   systemweiten Bundle-Verzeichnisse — fuer Claude Code unter
   `.claude/skills/`, fuer Codex unter dem Codex-Skill-Verzeichnis
   (Pfad-Konvention nach Codex-Standard)

Beispiel (Multi-Harness):

```text
C:\ProgramData\AgentKit\bundles\4.0.0\core\skills\execute-userstory\

T:\repo\.claude\skills\execute-userstory   ->  C:\ProgramData\AgentKit\bundles\4.0.0\core\skills\execute-userstory
T:\repo\.codex\skills\execute-userstory    ->  C:\ProgramData\AgentKit\bundles\4.0.0\core\skills\execute-userstory
```

[Entscheidung 2026-05-04 — Multi-Harness] AK3 unterstuetzt ab Tag 1
zwei Harnesses parallel (Claude Code, Codex; siehe FK-30 §30.11).
Beide haben kompatible `SKILL.md`-Skill-Formate. Der Installer
pflanzt deshalb pro Skill **zwei Symlinks** — einen pro Harness.
Der **Skill-Inhalt ist Single-Source** im systemweiten Bundle; die
Symlinks zeigen beide auf dieselbe Datei.

Falls einzelne Harnesses harness-spezifische Frontmatter- oder
Format-Konventionen erzwingen, die das gemeinsame Bundle nicht
erfuellt, erzeugt der Installer **substituierte Varianten** im
AK3-Installationsverzeichnis und linkt diese in den jeweiligen
Harness-Skill-Pfad. Substitution arbeitet auf einer **neutralen
Skill-Repraesentation** im Bundle und produziert harness-spezifische
Auslieferungen — ohne dass der inhaltliche Skill (Trigger, Vorgehen,
Schritte) doppelt gepflegt werden muss.

**Top-Surface `Skills.bind_skill`:**

`Skills.bind_skill` ist die kanonische Schnittstelle der Komponente
`Skills` (BC agent-skills) fuer die Installer-Interaktion. Der Installer
(BC installation-and-bootstrap, FK-50) ruft diese Methode auf — er
erzeugt Symlinks nicht direkt. Analogie zu `PromptRuntime.update_binding`
(BC prompt-runtime, FK-44).

```python
# Top-Surface: aufgerufen vom Installer (FK-50)
Skills.bind_skill(skill_name: str, bundle_root: Path, project_root: Path) -> None
```

**Hinweis fuer FK-50:** Die vollstaendige Dokumentation dieser
Installer-Schnittstelle erfolgt in FK-50 (installation-and-bootstrap).

### 43.4.2 Platzhalter-Substitution und Bundle-Parameter

Nur in `.md`-Dateien. Einfaches String-Replace, keine
Template-Engine.

**Klasse `PlaceholderSubstitutor` (in `SkillBinding`):**

`PlaceholderSubstitutor` substituiert Werte aus `PipelineConfig`
(BC foundation, FK-03). Die Schnittstelle zu `PipelineConfig` ist
**read-only**: keine Schreibzugriffe, keine Zustandsmutation.
Die substituierten Felder stammen ausschliesslich aus FK-03:

| Platzhalter | Quelle in `project.yaml` (FK-03) |
|---|---|
| `{{gh_owner}}` | `config.github_owner` |
| `{{gh_repo}}` | `config.repositories[0].name` (bei Single-Repo: das einzige Repo; bei Multi-Repo: deterministisches erstes Repo der Liste) |
| `{{project_prefix}}` | `config.project_prefix` |
| `{{project_key}}` | `config.project_key` |

```python
# Schnittstelle: read-only auf PipelineConfig (FK-03)
class PlaceholderSubstitutor:
    def substitute(self, content: str, config: PipelineConfig) -> str:
        replacements = {
            "{{gh_owner}}": config.github_owner,
            "{{gh_repo}}": config.repositories[0].name,
            "{{project_prefix}}": config.project_prefix,
            "{{project_key}}": config.project_key,
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

### 43.5.2 Upgrade-Verhalten und Skill-Pin-Mechanik

Bei AgentKit-Upgrade werden bestehende Projekte nicht automatisch auf
`latest` umgehaengt. Der Installer zeigt auf eine konkrete Bundle-Version.
Ein Projekt erhaelt eine neue Skill-Version erst, wenn seine
Symlink-Bindungen bewusst auf die neue Bundle-Version umgestellt werden.

**Eigenstaendiger Skill-Pin:**

agent-skills verwaltet seinen Bundle-Version-Pin eigenstaendig — er ist
**nicht** mit `prompt-runtime.BundlePinning` (FK-44) geteilt. Begruendung:

- Skill-Bundles sind Verzeichnis-Symlinks (harness-spezifisch — z. B.
  `.claude/skills/<name>/` fuer Claude Code, harness-eigenes
  Aequivalent fuer Codex; FK-30 §30.11)
  mit einem separaten Lifecycle (Requested → ProfileResolved →
  BundleSelected → Bound → Verified/Rejected).
- Prompt-Bundles sind Datei-Materialisierungen
  (`.agentkit/manifests/prompt-pins/{run_id}.json`) mit
  Run-Scope-Pinning.
- Strukturell aehnlich, mechanisch verschieden: kein gemeinsamer
  Pin-Mechanismus, keine gemeinsame Lock-Datei.

Der Skill-Versionierungs-Record wird in `SkillBundleStore` gefuehrt
(BC agent-skills); `prompt-runtime.BundlePinning` bleibt fuer
Prompt-Bundle-Pins zustaendig.

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

Der Harness (Claude Code / Codex; FK-30 §30.11) erkennt den Skill
automatisch über den projektlokalen Symlink am harness-spezifischen
Bindungspunkt (z. B. `.claude/skills/` fuer Claude Code).

### 43.6.2 Skill-Qualitaet

Die Qualitaet der Story-Umsetzung haengt wesentlich davon ab, dass
Agents auf erprobte Ablaeufe zurueckgreifen statt bei jeder Aufgabe
eigene Methodik zu erfinden. Deshalb:

- Mitgelieferte Skills werden mit AgentKit getestet
- Projektspezifische Skills liegen in der Verantwortung des
  Menschen

**Lese-Schnittstellen fuer SkillQualityMetric:**

`SkillQualityMetric` (BC agent-skills, Sub `agentkit.skills.quality_metric`)
aggregiert Qualitaets-Signale aus zwei Quellen:

1. **Telemetrie-Projektionen** — Lese-Zugriff via
   `Telemetry.ProjectionAccessor` (BC telemetry-and-events,
   Sub `agentkit.telemetry.projection_accessor`, exposure: sub_exposed).
   Gelesen werden WorkflowMetric-Daten, deren Owner
   `story-closure.PostMergeFinalization` (BC story-closure,
   `agentkit.closure.post_merge_finalization`) ist.
   Typische Signale: QA-Rundenanzahl, Remediation-Counts pro Skill-ID.

2. **Failure-Corpus-Befunde** — Lese-Zugriff auf `failure_corpus`
   Top-Komponente (BC failure-corpus, `agentkit.failure_corpus`).
   Skill-Experiment-Tags (`experiment_tag`) verknuepfen
   Failure-Corpus-Eintraege mit konkreten Skill-Versionen.

Skill-Aenderungen koennen so quantitativ evaluiert werden: Steigen
QA-Runden oder Failure-Corpus-Treffer nach einer Skill-Aenderung,
ist das ein messbares Signal (Experiment-Tags, Kap. 68.7.2).

**F-43-030 — Normative Skill-Nutzung (FK-12-030):** Agents **muessen** mitgelieferte Skills fuer standardisierte Aufgaben verwenden, anstatt ad-hoc-Methodik einzusetzen. Fuer Aufgaben, zu denen ein passender Skill existiert, ist dessen Nutzung normativ vorgeschrieben — nicht optional. Ein Agent, der eine Story erstellt ohne den `create-userstory`-Skill zu verwenden, oder der ein semantisches Review ohne den `semantic-review`-Skill durchfuehrt, verhaelt sich nicht regelkonform. Dieses Prinzip gilt gleichermassen fuer Pflicht- und optionale Skills, sofern deren Voraussetzung erfuellt ist.

**Enforcement-Owner: governance.guard_system (BC governance-and-guards)**

F-43-030 definiert die Norm. Der Enforcement-Mechanismus liegt bei
`governance.guard_system` (BC governance-and-guards), nicht bei
`verify-system.PolicyEngine`. Begruendung: Erkennung und Blockade
erfolgen zur Laufzeit vor dem Tool-Call (fail-fast), nicht erst nach
Abschluss einer Phase im Verify-Block.

Der Hook `skill_usage_check` (Sub `agentkit.governance.guard_system`)
erkennt an Tool-Aufruf-Patterns zur Laufzeit, ob ein Agent
ad-hoc-Methodik einsetzt, obwohl ein passender Skill existiert und
dessen Voraussetzung erfuellt ist. Bei Erkennung blockiert er den
Tool-Call und fordert den Skill-Aufruf.

Cross-BC-Beziehung: Norm-Owner ist BC agent-skills (FK-43, dieses
Kapitel); Enforcement-Owner ist BC governance-and-guards (FK-30 §30.5.1).
`verify-system.PolicyEngine` ist kein Enforcement-Owner fuer F-43-030.

Details zum Hook und Registrierung: FK-30 §30.5.1.

---

*FK-Referenzen: FK-12-019 bis FK-12-027 (Skills komplett)*
