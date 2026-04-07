---
concept_id: FK-92
title: Verzeichnis- und Namenskonventionen
module: naming-conventions
status: active
doc_kind: core
parent_concept_id:
authority_over:
  - scope: naming-conventions
defers_to: []
supersedes: []
superseded_by:
tags: [naming, conventions, directory-structure, reference]
---

# 92 — Verzeichnis- und Namenskonventionen

## 92.1 Projekt-Verzeichnisstruktur

Vollständige Struktur in Kap. 10.3.1. Hier nur die Konventionen.

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
| Telemetrie-DB | `_temp/agentkit.db` | (eine für alle Stories) |
| Telemetrie-Export | `_temp/story-telemetry/{story_id}.jsonl` | `ODIN-042.jsonl` |
| Lock-Verzeichnis | `_temp/governance/locks/{story_id}/` | `_temp/governance/locks/ODIN-042/` |
| Lock-Datei | `qa-lock.json` | `_temp/governance/locks/ODIN-042/qa-lock.json` |
| Active-Marker | `_temp/governance/active/{story_id}.active` | `ODIN-042.active` |
| Adversarial-Sandbox | `_temp/adversarial/{story_id}/` | `_temp/adversarial/ODIN-042/` |
| Failure-Corpus-Incident | `FC-{YYYY}-{NNNN}` | `FC-2026-0017` |
| Failure-Corpus-Pattern | `FP-{NNNN}` | `FP-0003` |
| Failure-Corpus-Check | `CHK-{NNNN}` | `CHK-0012` |
| Installer-Checkpoint | `cp_{NN}_{name}` | `cp_04_github_fields` |

## 92.3 Dateierweiterungen

| Erweiterung | Inhalt | Verwendung |
|-------------|--------|-----------|
| `.json` | Strukturierte Daten | QA-Artefakte, Config, Manifest, Schemas |
| `.jsonl` | Event-Stream (1 Zeile/Event) | Telemetrie-Export, Failure Corpus |
| `.yaml` | Konfiguration | Pipeline-Config, CCAG-Regeln |
| `.md` | Menschenlesbare Dokumente | Prompts, Skills, Protokolle, Konzepte |
| `.db` | SQLite-Datenbank | Telemetrie-Laufzeitspeicher |
| `.active` | Marker-Datei (JSON) | Story-Execution-Marker |
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
