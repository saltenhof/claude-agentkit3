---
concept_id: FK-92
title: Verzeichnis- und Namenskonventionen
module: naming-conventions
cross_cutting: true
status: active
doc_kind: core
parent_concept_id:
authority_over:
  - scope: naming-conventions
defers_to: []
supersedes: []
superseded_by:
tags: [naming, conventions, directory-structure, reference]
prose_anchor_policy: strict
formal_refs:
  - formal.skills-and-bundles.invariants
---

# 92 — Verzeichnis- und Namenskonventionen

<!-- PROSE-FORMAL: formal.skills-and-bundles.invariants -->

## 92.1 Projekt-Verzeichnisstruktur

Vollständige Struktur in Kap. 10.3.1 (minimale Registrierung) und
Kap. 10.3.1a (optionales Default-Zielprojekt-Scaffold). Hier nur die
Konventionen.

### 92.1.0 Zielprojekt-Scaffold vs. AgentKit-Runtime-Temp

`temp/` und `_temp/` sind verschiedene Namensräume:

- `temp/` ist der optionale, projektlokale Arbeitsbereich des
  Default-Zielprojekt-Scaffolds. Er ist kein normativer Speicher und
  wird im Root-Repository ignoriert.
- `_temp/` ist ein AgentKit-Runtime-/Exportverzeichnis dieses
  AgentKit-Repositories, z. B. für QA-, Governance- oder
  Telemetrie-Exporte. Es ist kein Bestandteil des Zielprojekt-
  Scaffolds und darf nicht als fachliche Quelle verstanden werden.

Die Scaffold-Ordnernamen `concepts/`, `codebase/`, `temp/`,
`input/_meetings/`, `guardrails/` und `stories/` sind die
Standardnamen für leere Zielprojekte; alternative Projektstrukturen
werden über die typisierten Layout-Felder in `project.yaml` beschrieben.

### 92.1.1 Namespace-Konvention fuer Produktionscode

Produktionscode unter `src/agentkit/` folgt einer
komponentenorientierten Namespace-Regel:

| Regel | Bedeutung |
|-------|-----------|
| Komponentenname statt Technikname | Namespaces werden nach fachlicher Verantwortung benannt (`pipeline_engine`, `guard_system`, `conformance_service`) |
| Snake Case fuer Pakete | Paketnamen sind klein und `snake_case` |
| Subkomponenten als Unterpakete | Beispiel: `governance/setup_preflight_gate/` |
| Adapter bleiben unter `integrations/` | Externe Systemgrenzen bleiben technisch gebuendelt |
| Kein Sammelbecken `utils` fuer Fachlogik | Fachwissen gehoert in Komponenten, nicht in neutrale Hilfspakete |

**Sonderfall Prozesssprache:** Die querschnittliche Ablauf- und
Kontrollsprache liegt unter `agentkit/process/language/`. Sie gehoert
keiner einzelnen Fachkomponente wie `pipeline_engine`, sondern wird von
mehreren Komponenten konsumiert.

**Sonderfall Architektur-Tooling:** Der Compiler fuer die formale
Konzeptspezifikation ist kein Produktionscode und liegt deshalb nicht
unter `src/agentkit/`, sondern unter `tools/concept_compiler/`.

**Zielstruktur:**

```text
src/agentkit/{component_name}/
src/agentkit/{component_name}/{subcomponent_name}/
```

## 92.2 Naming-Schemata

| Entität | Format | Beispiel |
|---------|--------|---------|
| Story-ID | `{PREFIX}-{NNN}` | `ODIN-042` |
| Run-ID | UUID v4 | `a1b2c3d4-e5f6-7890-abcd-ef1234567890` |
| Branch | `story/{story_id}` | `story/ODIN-042` |
| Worktree-Pfad | `worktrees/{story_id}` | `worktrees/ODIN-042` |
| Story-Verzeichnis | `{story_id}_{slug}` | `ODIN-042_implement-broker-api` |
| QA-Verzeichnis | `_temp/qa/{story_id}/` | `_temp/qa/ODIN-042/` |
| QA-Artefakt | `{stage_id}.json` | `structural.json`, `qa_review.json` |
| Telemetrie-Tabelle | `execution_events` | Logische PostgreSQL-Tabelle fuer alle Stories |
| Telemetrie-Export | `_temp/story-telemetry/{story_id}.jsonl` | `ODIN-042.jsonl` |
| Lock-Export-Verzeichnis | `_temp/governance/locks/{story_id}/` | `_temp/governance/locks/ODIN-042/` |
| Lock-Export-Datei | `qa-lock.json` | `_temp/governance/locks/ODIN-042/qa-lock.json` |
| Worktree-Lock-Export | `.agent-guard/lock.json` | `worktrees/ODIN-042/.agent-guard/lock.json` |
| Adversarial-Sandbox | `_temp/adversarial/{story_id}/` | `_temp/adversarial/ODIN-042/` |
| Failure-Corpus-Incident | `FC-{YYYY}-{NNNN}` | `FC-2026-0017` |
| Failure-Corpus-Pattern | `FP-{NNNN}` | `FP-0003` |
| Failure-Corpus-Check | `CHK-{NNNN}` | `CHK-0012` |
| Installer-Checkpoint | `cp_{NN}_{name}` | `cp_04_github_fields` |

## 92.3 Dateierweiterungen

| Erweiterung | Inhalt | Verwendung |
|-------------|--------|-----------|
| `.json` | Strukturierte Daten | QA-Artefakte, Config, Manifest, Schemas |
| `.jsonl` | Export-/Audit-Stream (1 Zeile/Event) | Telemetrie-Export, Failure Corpus |
| `.yaml` | Konfiguration | Pipeline-Config, CCAG-Regeln |
| `.md` | Menschenlesbare Dokumente | Prompts, Skills, Protokolle, Konzepte |
| `.db` | Nicht projektlokal kanonisch | DB-Dateien sind fuer AgentKit nicht Source of Truth |
| `.bak` | Backup bei Upgrade | Gesicherte Nutzer-Anpassungen |

## 92.4 Slugifizierung

Story-Verzeichnisnamen verwenden einen Slug aus dem Issue-Titel:

```python
def slugify(title: str) -> str:
    slug = title.lower()
    slug = re.sub(r'[^a-z0-9]+', '-', slug)
    slug = slug.strip('-')
    return slug[:50]  # Max 50 Zeichen
```

Beispiel: "Implement Broker API Integration" → `implement-broker-api-integration`

> **Owner / Code-Realitaet (FEHLT heute):** Die `slugify`-Funktion fuer
> Story-**Verzeichnis**-Namen (`{story_id}_{slug}`, §92.2) existiert heute
> **nicht** als Code-Symbol (`grep "def slugify" src/agentkit/` → 0 Treffer).
> Die Story-Verzeichnis-Erzeugung gehoert fachlich zur **Story-Creation/
> Verzeichnis-Konventions-Verantwortung**; Code-Home ist der **Story-Creation-BC**
> (AG3-068 ownt das `story.md`-Export- und `story_creation`-Modul, FK-21 §21.11).
> AG3-068 enumeriert `slugify`/Story-Dir-Naming jedoch **nicht** explizit in
> seinem Scope. Der Bedarf wird daher als **Cross-Story-Voraussetzung (CP4)
> gegen AG3-068** gefuehrt (Remediation-Report AG3-104) — entweder AG3-068-Scope
> um `slugify` erweitern oder eine dedizierte Verzeichnis-Konventions-Story
> anlegen. **Kein** Implementierungs-Anspruch in dieser doc-only-Story.
