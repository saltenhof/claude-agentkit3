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
prose_anchor_policy: strict
formal_refs:
  - formal.installer.entities
  - formal.installer.state-machine
  - formal.installer.commands
  - formal.installer.events
  - formal.installer.invariants
  - formal.installer.scenarios
  - formal.skills-and-bundles.entities
  - formal.skills-and-bundles.state-machine
  - formal.skills-and-bundles.commands
  - formal.skills-and-bundles.events
  - formal.skills-and-bundles.invariants
  - formal.skills-and-bundles.scenarios
---

# 51 — Upgrade, Migration und Customization-Preservation

<!-- PROSE-FORMAL: formal.installer.entities, formal.installer.state-machine, formal.installer.commands, formal.installer.events, formal.installer.invariants, formal.installer.scenarios, formal.skills-and-bundles.entities, formal.skills-and-bundles.state-machine, formal.skills-and-bundles.commands, formal.skills-and-bundles.events, formal.skills-and-bundles.invariants, formal.skills-and-bundles.scenarios -->

## 51.1 Zweck

AgentKit-Upgrades müssen projektspezifische Anpassungen erkennen und
erhalten, statt sie zu überschreiben (FK-11-008). Laufzeit-Assets wie
Skills und Prompts werden systemweit versioniert bereitgestellt; im
Projekt werden nur Konfiguration und Symlink-Bindungen aktualisiert.

**F-51-023 — Erkennung und Erhalt nutzerseitiger Customizations (FK-11-023):** Upgrades müssen aktiv erkennen, welche projektseitigen Anpassungen vorgenommen wurden — dazu zählen geänderte Schwellenwerte in der Konfiguration, projektspezifische CCAG-Regeln und bewusst gesetzte Projektprofil-/Bundle-Bindungen. Erkannte Anpassungen werden niemals stillschweigend überschrieben.

## 51.2 Upgrade-Trigger

```bash
# AgentKit-Paket aktualisieren
pip install --upgrade agentkit

# Installer erneut laufen (erkennt Upgrade automatisch)
agentkit register-project --gh-owner acme-corp --gh-repo trading-platform
```

Der Installer erkennt anhand der installierten Paketversion, der
registrierten Bundle-Version und des Konfigurations-Digests, ob ein
Upgrade oder eine Re-Bindung nötig ist.

## 51.3 Drei Upgrade-Szenarien

### 51.3.1 Konfiguration und Bindung unverändert (häufigster Fall)

```
Konfig-Digest == Datei-Hash auf Disk und Bundle-Version unverändert?
→ Ja: Kein Update nötig.

Konfig-Digest == Datei-Hash, aber Ziel-Bundle-Version hat sich geändert?
→ Konfiguration unverändert, AgentKit hat neue Version.
→ Symlink-Bindung kann bewusst auf neue Bundle-Version umgestellt werden.
```

### 51.3.2 Konfiguration vom Nutzer angepasst

```
Registrierter Digest != Datei-Hash auf Disk?
→ Nutzer hat Datei editiert.
→ .bak Backup erstellen, dann neue Version schreiben.
→ Mensch muss Anpassungen manuell nachziehen.
```

### 51.3.3 Neue Skill-/Prompt-Variante

Neue Varianten werden systemweit installiert. Ein Projekt erhält sie
erst, wenn seine Bindung explizit auf das neue Bundle bzw. Profil
umgestellt wird.

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

Artefakt-Schemas (`schema_version`) werden im zentralen State-Backend
versioniert. Alte Artefakte abgeschlossener Stories bleiben
unverändert. Neue Runs schreiben die aktuelle Schema-Version.

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

Der Installer kann mit `--cleanup` veraltete lokale Bindungen oder
obsolet gewordene Projektkonfiguration entfernen:

```bash
agentkit register-project --gh-owner acme-corp --gh-repo trading-platform --cleanup
```

Cleanup entfernt nur obsolete Symlink-Bindungen und lokale
AgentKit-Konfigurationsreste, nicht aber Projektcode oder zentrale
Laufzeitdaten.

---

*FK-Referenzen: FK-11-006 (Idempotenz), FK-11-008
(Anpassungsschutz bei Upgrades)*
