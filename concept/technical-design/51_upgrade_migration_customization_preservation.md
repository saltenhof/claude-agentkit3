---
concept_id: FK-51
title: Upgrade, Migration und Customization-Preservation
module: upgrade
status: active
doc_kind: core
parent_concept_id:
authority_over:
  - scope: upgrade
defers_to:
  - target: FK-50
    scope: checkpoint-engine
    reason: Upgrade reuses the installer checkpoint engine defined in FK-50
supersedes: []
superseded_by:
tags: [upgrade, migration, customization, idempotency]
---

# 51 — Upgrade, Migration und Customization-Preservation

## 51.1 Zweck

AgentKit-Upgrades müssen nutzerseitige Anpassungen erkennen und
erhalten, statt sie zu überschreiben (FK-11-008). Gleichzeitig
müssen neue Features, geänderte Schemas und aktualisierte Prompts
ins Zielprojekt übertragen werden.

**F-51-023 — Erkennung und Erhalt nutzerseitiger Customizations (FK-11-023):** Upgrades müssen aktiv erkennen, welche projektseitigen Anpassungen vorgenommen wurden — dazu zählen modifizierte Prompts und Skill-Dateien, hinzugefügte eigene Skills, geänderte Schwellenwerte in der Konfiguration sowie projektspezifische CCAG-Regeln. Erkannte Anpassungen werden niemals stillschweigend überschrieben; stattdessen erstellt der Installer eine Sicherheitskopie und informiert den Menschen über den Konflikt, damit er seine Änderungen in die neue Version überführen kann.

## 51.2 Upgrade-Trigger

```bash
# AgentKit-Paket aktualisieren
pip install --upgrade agentkit

# Installer erneut laufen (erkennt Upgrade automatisch)
agentkit install --gh-owner acme-corp --gh-repo trading-platform
```

Der Installer erkennt anhand des Manifests, ob ein Upgrade nötig
ist (Version im Manifest vs. `agentkit.__version__`).

## 51.3 Drei Upgrade-Szenarien

### 51.3.1 Datei unverändert (häufigster Fall)

```
Manifest-Hash == Datei-Hash auf Disk == neuer Source-Hash?
→ Ja: Datei nicht angefasst. Kein Update nötig.

Manifest-Hash == Datei-Hash, aber != neuer Source-Hash?
→ Nutzer hat nichts geändert, AgentKit hat Update.
→ Datei wird aktualisiert. Kein Backup nötig.
```

### 51.3.2 Datei vom Nutzer angepasst

```
Manifest-Hash != Datei-Hash auf Disk?
→ Nutzer hat Datei editiert.
→ .bak Backup erstellen, dann neue Version schreiben.
→ Mensch muss Anpassungen manuell nachziehen.
```

### 51.3.3 Neue Datei (in neuem AgentKit, nicht im Manifest)

```
Datei existiert nicht auf Disk und nicht im Manifest?
→ Neue Datei, einfach kopieren.
```

## 51.4 Config-Migration

### 51.4.1 Wann

Wenn sich `config_version` in `.story-pipeline.yaml` ändert
(Major-Sprung, z.B. 3.0 → 4.0).

### 51.4.2 Ablauf

```python
def migrate_config(existing: dict, target_version: str) -> dict:
    current = existing.get("config_version", "3.0")

    if current == target_version:
        return existing  # Keine Migration nötig

    # Schrittweise Migration
    if current == "3.0" and target_version == "4.0":
        existing = migrate_3_to_4(existing)

    existing["config_version"] = target_version
    return existing

def migrate_3_to_4(config: dict) -> dict:
    # Beispiel: Feld umbenannt
    if "old_field" in config:
        config["new_field"] = config.pop("old_field")

    # Neues Pflichtfeld mit Default
    config.setdefault("new_required_field", "default_value")

    return config
```

### 51.4.3 Backup

Vor jeder Migration wird `.story-pipeline.yaml.bak` geschrieben.

## 51.5 Schema-Migration

Artefakt-Schemas (`schema_version` in JSON Envelopes) werden
**nicht migriert**. Alte Artefakte gehören zu abgeschlossenen
Stories und bleiben unverändert. Neue Stories erzeugen Artefakte
mit der aktuellen Schema-Version (Kap. 03.3.4).

## 51.6 Hook-Migration

Bei Upgrades können sich Hook-Registrierungen ändern (neue Hooks,
geänderte Matcher, entfernte Hooks). Der Installer:

1. Liest bestehende `.claude/settings.json`
2. Erkennt AgentKit-Hooks anhand des Command-Patterns
   (`python -m agentkit.`)
3. Entfernt veraltete AgentKit-Hooks
4. Fügt neue/geänderte AgentKit-Hooks hinzu
5. Lässt nicht-AgentKit-Hooks unberührt

### 51.6.1 Git-Hook-Migration (Pre-Commit Dispatching)

Der Pre-Commit-Hook (`tools/hooks/pre-commit`) verwendet seit
der ConceptContext-Einführung (Kap. 13.9) eine pfadbasierte
Dispatching-Logik:

- Secret-Detection: Global (immer aktiv, Kap. 15.5.2)
- Versionsbump: Nur bei Code-Änderungen (`agentkit/`, `pyproject.toml`)
- Concept-Validation: Nur bei Konzeptänderungen (`_concept/`)

Bei Upgrades von einer Version ohne Dispatching-Logik:

1. Prüft ob bestehender `pre-commit` Hook Secret-Detection enthält
2. Ergänzt Dispatching-Logik (Secret-Detection bleibt unverändert)
3. Fügt Concept-Validation-Aufruf hinzu
4. Sichert unerkannte Anpassungen als `.bak`

## 51.7 Cleanup alter Dateien

Der Installer kann mit `--cleanup` veraltete Dateien entfernen
(z.B. Shell-Skripte aus einer früheren AgentKit-Generation):

```bash
agentkit install --gh-owner acme-corp --gh-repo trading-platform --cleanup
```

Cleanup entfernt nur Dateien, die im Manifest als "von AgentKit
installiert" markiert sind und in der aktuellen Version nicht
mehr existieren.

---

*FK-Referenzen: FK-11-006 (Idempotenz), FK-11-008
(Anpassungsschutz bei Upgrades)*
