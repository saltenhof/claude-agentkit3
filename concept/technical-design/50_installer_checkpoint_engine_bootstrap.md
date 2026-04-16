---
concept_id: FK-50
title: Installer, Checkpoint-Engine und Bootstrap
module: installer
status: active
doc_kind: core
parent_concept_id:
authority_over:
  - scope: installer
defers_to:
  - target: FK-03
    scope: configuration-schema
    reason: Pipeline-Config schema and validation rules defined in FK-03
supersedes: []
superseded_by:
tags: [installer, checkpoint, bootstrap, idempotency]
---

# 50 — Installer, Checkpoint-Engine und Bootstrap

## 50.1 Zweck

AgentKit wird systemweit installiert und registriert anschließend ein
Zielprojekt über eine Folge idempotenter Checkpoints (FK 11). Das
Zielprojekt erhält lokale Konfiguration und Claude-Code-kompatible
Symlink-Bindungen für Skills, aber keine kopierten AgentKit-
Laufzeitartefakte.

**Architekturzuordnung:** Der Installer ist im Komponentenmodell eine
eigene Top-Level-Komponente. Er ist kein Teil der `PipelineEngine`,
sondern vorgelagerter Bootstrap- und Registrierungsmechanismus für
Projekte, Hooks, Skill-Bindungen und Backend-Registrierung.

## 50.2 Aufruf

```bash
# Erstregistrierung
agentkit register-project --gh-owner acme-corp --gh-repo trading-platform

# Erneut laufen (idempotent)
agentkit register-project --gh-owner acme-corp --gh-repo trading-platform

# Dry-Run (zeigt was passieren würde)
agentkit register-project --gh-owner acme-corp --gh-repo trading-platform --dry-run

# Verifikation (read-only Prüfung)
agentkit verify-project
```

## 50.3 Zwölf Checkpoints

```mermaid
flowchart TD
    CP1["CP 1: Python-Paket<br/>agentkit installiert?"] --> CP2
    CP2["CP 2: GitHub-Repo<br/>existiert?"] --> CP3
    CP3["CP 3: GitHub Project<br/>erstellen/finden"] --> CP4
    CP4["CP 4: Custom Fields<br/>(13 Felder)"] --> CP5
    CP5["CP 5: Pipeline-Config<br/>.story-pipeline.yaml"] --> CP6
    CP6["CP 6: Projektprofil<br/>ermitteln"] --> CP7
    CP7["CP 7: Projekt im<br/>State-Backend registrieren"] --> CP8
    CP8["CP 8: Skill-Symlinks<br/>binden"] --> CP9
    CP9["CP 9: Hooks<br/>registrieren"] --> CP10
    CP10["CP 10: MCP-Server<br/>(wenn VektorDB/ARE)"] --> CP11
    CP11["CP 11: Git-Hooks +<br/>CLAUDE.md"] --> CP12
    CP12["CP 12: Verifikation<br/>(read-only)"]
```

### 50.3.1 Checkpoint-Engine als Komponenten-Flow

Die Checkpoint-Engine des `Installer` wird ebenfalls ueber die
Einheits-DSL modelliert. Jeder Checkpoint ist ein expliziter
`step`-Knoten innerhalb eines
`FlowDefinition(level="component", owner="Installer")`.

**Wichtige Konsequenz:**

- Reihenfolge und optionale Aeste der Registrierung gehoeren in den
  Flow-Vertrag
- die Idempotenz einzelner Checkpoints bleibt Aufgabe ihrer Handler
- Profil- und Feature-Entscheidungen (`core` vs. `are`,
  `vectordb` an/aus) werden ueber `branch`-Knoten modelliert, nicht
  ueber verstreute Imperativlogik

Minimaler Installer-Flow:

```text
cp_01_package_check
  -> cp_02_repo_check
  -> cp_03_project_lookup
  -> cp_04_custom_fields
  -> cp_05_pipeline_config
  -> cp_06_profile_resolution
  -> cp_07_backend_registration
  -> cp_08_skill_bindings
  -> cp_09_hook_registration
  -> branch_vectordb_enabled
  -> cp_10_mcp_registration?
  -> branch_are_enabled
  -> cp_10c_are_scope_validation?
  -> cp_11_git_hooks_and_claude
  -> cp_12_verify_registration
```

Die Frage "Checkpoint laeuft erneut oder nicht?" wird damit sauber
geteilt:

- Kontrollfluss: durch die DSL
- Konvergenz/Idempotenz: durch den Checkpoint-Handler

Ein Checkpoint darf also im Flow erneut besucht werden, muss aber
handlerseitig denselben Zielzustand ohne Seiteneffekt-Explosion
herstellen.

### CP 1: Python-Paket

Prüft ob `agentkit` als Python-Paket verfügbar ist:

```python
import agentkit
assert agentkit.__version__
```

**Idempotenz:** Nur Prüfung, keine Aktion.

### CP 2: GitHub-Repo

Prüft ob das Repo existiert und `gh` CLI authentifiziert ist:

```bash
gh repo view {owner}/{repo} --json name
```

**Idempotenz:** Nur Prüfung.

### CP 3: GitHub Project

Sucht ein bestehendes GitHub Project V2 oder erstellt ein neues:

```bash
gh project list --owner {owner} --format json
# Wenn nicht gefunden:
gh project create --owner {owner} --title "AgentKit - {repo}"
```

**Idempotenz:** Erstellt nur wenn nicht vorhanden.

### CP 4: Custom Fields

Stellt sicher, dass alle 13 Custom Fields existieren (Kap. 12.2.1).
Prüft den bestehenden Zustand und erstellt nur fehlende Fields.
Vorhandene Fields werden nicht verändert.

**13 Felder:** Status, Story ID, Story Type, Size, Change Impact,
New Structures, Concept Quality (Pflicht, High/Medium/Low),
QA Rounds, Completed At, Module, Epic, Primary Repo,
Participating Repos.

REF-032 + Remediation: Maturity, External Integrations und
Requires Exploration entfernt; Concept Quality hinzugefügt.

**Idempotenz:** Nur fehlende Fields erstellen.

### CP 5: Pipeline-Config

Erzeugt `.story-pipeline.yaml` wenn nicht vorhanden. Bei
bestehender Datei: prüft `config_version`, migriert bei Bedarf
(Kap. 51).

**Idempotenz:** Überschreibt nie bestehende Config.

### CP 6: Projektprofil ermitteln

Ermittelt das Projektprofil, aus dem sich die zu bindenden Skills
und Prompt-Varianten ableiten. Zentrale Minimalunterscheidung:

- `core`
- `are`

Die Profilwahl erfolgt bei der Registrierung und nicht zur Laufzeit
innerhalb der Skills.

**Idempotenz:** Bereits ermitteltes Profil wird wiederverwendet,
sofern die Projektkonfiguration unverändert ist.

### CP 7: Projekt im State-Backend registrieren

Legt einen Projekt-Record im zentralen State-Backend an und
hinterlegt:

- Projektkennung
- GitHub-Owner/Repo/Project-ID
- Konfigurations-Digest
- Projektprofil
- zulässige Bundle-Version

**Idempotenz:** Upsert auf Projektkennung; nur Deltas werden geschrieben.

### CP 8: Skill-Symlinks binden

Erzeugt unter `.claude/skills/` die projektlokalen Symlinks auf die
systemweit installierten, versionierten Bundle-Verzeichnisse.

Beispiel:

```text
C:\ProgramData\AgentKit\bundles\4.0.0\are\skills\execute-userstory
T:\repo\.claude\skills\execute-userstory  ->  C:\ProgramData\AgentKit\bundles\4.0.0\are\skills\execute-userstory
```

**Regeln:**
- Der Symlink zeigt auf eine konkrete Bundle-Version, nie auf `latest`.
- Pro Projekt wird nur die profilpassende Skill-Variante gebunden.
- Der Symlink ist Bindungspunkt, nicht Source of Truth.

**Idempotenz:** Bestehende korrekte Symlinks bleiben unverändert;
falsche oder veraltete Bindungen werden gezielt ersetzt.

### CP 9: Hooks registrieren

Schreibt Hook-Einträge in `.claude/settings.json` (Kap. 30.3.1).
Merge-Modus: bestehende Hooks bleiben erhalten, nur fehlende
AgentKit-Hooks werden hinzugefügt.

**Idempotenz:** Prüft ob jeder Hook bereits registriert ist.

### CP 10: MCP-Server

Nur wenn `features.vectordb: true`. Registriert den
Story-Knowledge-Base MCP-Server in `.mcp.json`:

```json
{
  "mcpServers": {
    "story-knowledge-base": {
      "type": "stdio",
      "command": "python",
      "args": ["{agentkit_path}/userstory/vectordb/mcp_server.py"],
      "env": { ... }
    }
  }
}
```

Auch ARE-MCP-Server wenn `features.are: true`.

**Idempotenz:** Prüft ob Server bereits registriert ist.

### CP 10a: ConceptContext-Properties und Erstindizierung

Nur wenn `features.vectordb: true`. Erweitert die `StoryContext`-
Collection um konzeptspezifische Properties (Kap. 13.9.3):

1. Prüft ob die neuen Properties (`concept_id`, `is_appendix`,
   `parent_concept_id`, `defers_to`, `authority_over`,
   `section_number`, `normative_rules`, `concept_status`)
   in der Collection existieren
2. Fügt fehlende Properties hinzu (Weaviate Schema-Update)
3. Registriert `concept_search` und `concept_sync` Tools im
   bestehenden Story-Knowledge-Base MCP-Server
4. Führt Erstindizierung aller Konzeptdokumente mit gültigem
   Frontmatter durch (`concept_sync(full_reindex=true)`)

**Abhängigkeiten:** CP 10 (MCP-Server muss registriert sein).

**Idempotenz:** Prüft ob Properties bereits existieren. Überspring
bereits indizierte Konzepte (Hash-basiert).

### CP 10b: Concept-Validation-Hook

Registriert den konzeptspezifischen Pre-Commit-Hook (Kap. 13.9.9)
in `tools/hooks/pre-commit`. Der Hook führt bei Änderungen unter
`_concept/` die Validierungs-Suite `concept_validate --staged` aus.

Die bestehende Secret-Detection (Kap. 15.5.2) bleibt global aktiv
und wird durch die pfadbasierte Dispatching-Logik nicht berührt.

**Abhängigkeiten:** CP 11 (Git-Hooks müssen konfiguriert sein).

**Idempotenz:** Prüft ob Dispatching-Logik bereits im Hook
enthalten ist.

### CP 10c: ARE-Scope-Validierung

Nur wenn `features.are: true`.

- Prüft: Alle Code-Repos in `repos[]` haben `are_scope` gesetzt. Alle Modul-Werte aus dem GitHub Project haben Eintrag in `are.module_scope_map`
- Erkennt Deltas automatisch: nur neue/unmapped Items lösen Abfrage aus
- Interaktiver Modus: nummerierte Auswahl aus ARE-Scopes (Quelle: ARE-API `/dimensions/scope` oder Fallback auf bereits konfigurierte Scopes)
- Agentischer Modus: gibt `PENDING_SELECTION` zurück mit Metadaten, orchestrierender Agent muss `resolve_pending_scope_mapping()` aufrufen
- Idempotenz: bereits zugeordnete Items werden nicht erneut abgefragt

**Abhängigkeiten:** CP 5 (Pipeline-Config), CP 4 (Custom Fields), CP 10 (ARE MCP-Server)

**Idempotenz:** Nur fehlende/unmapped Einträge werden abgefragt.

### CP 11: Git-Hooks + CLAUDE.md

Installiert `pre-commit` Hook (Secret-Detection, Kap. 15.5.2)
und `pre-push` Hook:

```bash
# Setzt core.hooksPath auf tools/hooks/
git config core.hooksPath tools/hooks/
```

**Idempotenz:** Prüft ob hooksPath bereits gesetzt ist.

Erzeugt ein Skelett für die `CLAUDE.md`-Datei des Projekts.
**Nur bei Erstinstallation** — wird nie überschrieben, weil
CLAUDE.md ein vom Menschen gepflegtes Dokument ist.

**Idempotenz:** Nur erstellen wenn nicht vorhanden.

### CP 12: Verifikation

Read-only Validierung aller vorherigen Checkpoints:

- Config lesbar und Schema-valide?
- Projektprofil bestimmt?
- Projekt im State-Backend registriert?
- Alle erwarteten Skill-Symlinks vorhanden und korrekt?
- Alle Hooks registriert?
- GitHub-Fields vorhanden?
- ARE-Scope-Zuordnung vollständig? (alle Code-Repos haben `are_scope`, alle Modul-Werte gemappt — nur wenn `features.are: true`)

**Ergebnis:** PASS oder Liste von Problemen.

## 50.4 Checkpoint-Ergebnis

```python
@dataclass
class CheckpointResult:
    checkpoint: str     # z.B. "cp_04_github_fields"
    status: str         # PASS, CREATED, UPDATED, SKIPPED, FAILED
    detail: str         # Menschenlesbare Beschreibung
    duration_ms: int    # Ausführungsdauer
```

| Status | Bedeutung |
|--------|----------|
| PASS | Checkpoint war bereits erfüllt, keine Aktion nötig |
| CREATED | Neues Artefakt erstellt |
| UPDATED | Bestehendes Artefakt aktualisiert |
| SKIPPED | Nicht relevant (z.B. VektorDB bei `vectordb: false`) |
| FAILED | Checkpoint gescheitert — Installation abbrechen |

## 50.5 Symlink-Bindung

Der Installer erzeugt projektlokale Symlinks auf systemweite
Bundle-Verzeichnisse:

```python
def bind_project_skills(project_root: Path, bundle_root: Path, skills: list[str]) -> None:
    skills_dir = project_root / ".claude" / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)
    for skill_name in skills:
        source = bundle_root / "skills" / skill_name
        target = skills_dir / skill_name
        create_or_update_symlink(source, target)
```

**Fail-closed:** Kann ein erwarteter Symlink nicht angelegt werden,
scheitert die Projektregistrierung. Ein partiell gebundenes Profil ist
nicht zulässig.

## 50.6 Fehlerbehandlung

| Fehler | Checkpoint | Reaktion |
|--------|-----------|---------|
| `gh` nicht installiert | CP 2 | FAILED, Installation abbrechen |
| `gh` nicht authentifiziert | CP 2 | FAILED, Hinweis auf `gh auth login` |
| Repo nicht gefunden | CP 2 | FAILED |
| GitHub API Rate Limit | CP 3/4 | Retry mit Backoff, dann FAILED |
| Keine Schreibrechte im Projekt | CP 8/9/11 | FAILED |
| State-Backend nicht erreichbar | CP 7 | FAILED |
| Symlink kann nicht angelegt oder aktualisiert werden | CP 8 | FAILED |
| Bestehende Config mit inkompatiblem Schema | CP 5 | Migration versuchen (Kap. 51), bei Scheitern FAILED |

**Bei FAILED:** Alle vorherigen Checkpoints waren erfolgreich und
bleiben erhalten. Der Installer kann nach Problembehebung erneut
gestartet werden — Idempotenz garantiert, dass bereits erledigte
Checkpoints nicht wiederholt werden.

---

*FK-Referenzen: FK-11-001 bis FK-11-009 (Installation komplett)*
