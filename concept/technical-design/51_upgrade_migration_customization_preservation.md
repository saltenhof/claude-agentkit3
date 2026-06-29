---
concept_id: FK-51
title: Upgrade, Migration, Uninstall und Customization-Preservation
module: upgrade
domain: installation-and-bootstrap
status: active
doc_kind: core
parent_concept_id:
authority_over:
  - scope: upgrade
  - scope: uninstall
defers_to:
  - target: FK-50
    scope: checkpoint-engine
    reason: Upgrade reuses the installer checkpoint engine defined in FK-50
  - target: FK-10
    scope: deployment-levels
    reason: Das Drei-Ebenen-Modell (Dreifaltigkeit) sowie Update-Treiber- und Uninstall-Topologie sind in FK-10 §10.2 verankert; FK-51 fuehrt die operative Mechanik
supersedes: []
superseded_by:
tags: [upgrade, migration, customization, idempotency, uninstall]
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
glossary:
  exported_terms:
    - id: config-migration
      definition: >
        Schrittweiser Konvertierungsprozess einer project.yaml von
        einer aelteren config_version auf die aktuelle Zielversion. Laeuft
        innerhalb von CP 5 des Installers; erstellt vor jeder Aenderung ein
        .bak-Backup. Bei Scheitern: FAILED, keine Teilmigration.
      see_also:
        - term: installer-checkpoint
          domain: installation-and-bootstrap
    - id: customization-footprint
      definition: >
        Erfasstes Profil projektspezifischer Anpassungen an AgentKit-verwalteten
        Dateien, insbesondere geaenderte Schwellenwerte in der Pipeline-Config,
        projektspezifische CCAG-Regeln und bewusst gesetzte Bundle-Bindungen.
        Erkannte Anpassungen werden niemals stillschweigend ueberschrieben.
      see_also:
        - term: manifest-contract
          domain: installation-and-bootstrap
---

# 51 — Upgrade, Migration und Customization-Preservation

<!-- PROSE-FORMAL: formal.installer.entities, formal.installer.state-machine, formal.installer.commands, formal.installer.events, formal.installer.invariants, formal.installer.scenarios, formal.skills-and-bundles.entities, formal.skills-and-bundles.state-machine, formal.skills-and-bundles.commands, formal.skills-and-bundles.events, formal.skills-and-bundles.invariants, formal.skills-and-bundles.scenarios -->

## 51.1 Zweck

AgentKit-Upgrades müssen projektspezifische Anpassungen erkennen und
erhalten, statt sie zu überschreiben (FK-11-008). Laufzeit-Assets wie
Skills und Prompts werden systemweit versioniert bereitgestellt; im
Projekt werden nur Konfiguration und Symlink-Bindungen aktualisiert.

**F-51-023 — Erkennung und Erhalt nutzerseitiger Customizations (FK-11-023):** Upgrades müssen aktiv erkennen, welche projektseitigen Anpassungen vorgenommen wurden — dazu zählen geänderte Schwellenwerte in der Konfiguration, projektspezifische CCAG-Regeln und bewusst gesetzte Projektprofil-/Bundle-Bindungen. Erkannte Anpassungen werden niemals stillschweigend überschrieben.

## 51.2 Upgrade-Trigger und Treibermodell

Der Installer ist transport-agnostisch. CLI-Aufrufe sind Boundary-Controls
des aufrufenden BC. Aufruf erfolgt ueber das aufrufende BC (Boundary-Control).

Der Installer erkennt anhand der installierten Paketversion, der
registrierten Bundle-Version und des Konfigurations-Digests, ob ein
Upgrade oder eine Re-Bindung noetig ist.

**Treibermodell (hybrid; Topologie in FK-10 §10.2.8):** Der zentrale
Core **annonciert** über `/v1` die unterstützten Versionsfenster
(`min`/`recommended`/`blocked`; Wire-Detailvertrag in FK-91); die
**Entwicklermaschine zieht und aktiviert** das Update selbst
(`agentkit update` für Paket-/Bundle-Version, danach deliberater
Re-Bind/Re-Run auf Ebene 3). **Es gibt keinen Server-Push von
Executables** — das wäre Remote-Code-Ausführung über die Trust-Boundary,
gerade für Hook-Code.

**Kompatibilitätsreaktion (fail-closed by default):**

- **ERROR / fail-closed:** Agent-Runtime unter `min` oder in `blocked`,
  nicht unterstützte Wire-Version, fehlender Handshake an
  Governance-/mutierenden Endpunkten, nicht lesbare
  `config_version`/`schema_version`, ungültiger Skill-Hash/-Signatur. Ein
  Hook, der seine Kompatibilität nicht belegen kann, liefert **kein
  PASS**.
- **WARNING:** Runtime unter `recommended` aber im Fenster, veraltetes
  aber erlaubtes Skill-Bundle, migrierbare `config_version`.
- **Skills brechen nie hart** (außer Integritätsbruch): ein zentral als
  veraltet markiertes Skill-Bundle blockiert ein Altprojekt nicht.

**Treiber je Ebene:** Ebene 1 ops-getrieben (DB-Migration explizit,
`min`-Client-Politik **vor** Rollout setzen); Ebene 2 Entwickler per
`agentkit update` auf Server-Hinweis; Ebene 3 deliberater
Re-Bind/Re-Run.

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

Wenn sich `config_version` in `project.yaml` ändert
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

Vor jeder Migration wird `project.yaml.bak` geschrieben.

## 51.5 Schema-Migration

Artefakt-Schemas (`schema_version`) werden im zentralen State-Backend
versioniert. Alte Artefakte abgeschlossener Stories bleiben
unverändert. Neue Runs schreiben die aktuelle Schema-Version.

## 51.6 Hook-Migration

Bei Upgrades koennen sich Hook-Registrierungen aendern (neue Hooks,
geaenderte Matcher, entfernte Hooks). Der Installer delegiert die
Hook-Verwaltung an die Top-Surface `Governance.register_hooks`
(BC `governance-and-guards`, FK-30). Die Manipulation der
harness-spezifischen Settings-Dateien (Beispiel Claude Code:
`.claude/settings.json`; Codex: harness-eigenes Aequivalent — siehe
FK-76 §76.5) liegt in `agentkit.backend.governance.guard_system` plus dem
zugehoerigen Harness-Adapter.

Der Installer:

1. Ermittelt die neuen/geaenderten Hook-Definitionen fuer die aktuelle Version
2. Ruft `Governance.register_hooks(hook_definitions)` auf
3. `governance.guard_system` erkennt AgentKit-Hooks anhand des Command-Patterns
   (`python -m agentkit.`), entfernt veraltete und fuegt neue hinzu
4. Nicht-AgentKit-Hooks bleiben unveraendert

### 51.6.1 Git-Hook-Migration (Pre-Commit Dispatching)

Der Pre-Commit-Hook (`tools/hooks/pre-commit`) verwendet seit
der ConceptContext-Einführung (Kap. 13.9) eine pfadbasierte
Dispatching-Logik:

- Secret-Detection: Global (immer aktiv, Kap. 15.5.2)
- Versionsbump: Nur bei Code-Änderungen (`agentkit/`, `pyproject.toml`)
- Concept-Validation: Nur bei Konzeptänderungen unter dem konfigurierten `concepts_dir`

Bei Upgrades von einer Version ohne Dispatching-Logik:

1. Prüft ob bestehender `pre-commit` Hook Secret-Detection enthält
2. Ergänzt Dispatching-Logik (Secret-Detection bleibt unverändert)
3. Fügt Concept-Validation-Aufruf hinzu
4. Sichert unerkannte Anpassungen als `.bak`

## 51.7 Cleanup alter Dateien

Der Installer unterstuetzt einen Cleanup-Modus fuer veraltete lokale
Bindungen oder obsolet gewordene Projektkonfiguration. Aufruf erfolgt
ueber das aufrufende BC (Boundary-Control).

Cleanup entfernt nur obsolete Symlink-Bindungen und lokale
AgentKit-Konfigurationsreste, nicht aber Projektcode oder zentrale
Laufzeitdaten.

## 51.8 Customization-Erkennung

Der `CustomizationFootprint` kombiniert Informationen aus drei
Quellen — jeweils ueber die kanonischen Lese-Schnittstellen der
Owner-BCs:

| Quelle | Owner-BC | Lese-Schnittstelle |
|--------|----------|-------------------|
| Pipeline-Config-Schwellenwerte | `pipeline-framework` (FK-03) | `PipelineConfig`-Schema lesen (lokale Datei; Digest-Vergleich) |
| CCAG-Regeln (projektspezifisch) | `governance-and-guards` | Top-Surface lesen; CCAG-Regeln sind Teil des Governance-Vertrags |
| Bundle-Bindings (Prompt) | `prompt-runtime` | `PromptRuntime.update_binding`-Pendant; aktuellen Bundle-Pin lesen |
| Bundle-Bindings (Skills) | `agent-skills` | `Skills.resolve_binding(skill_id, project_root)` (Top-Surface FK-43) |

Der `CustomizationFootprint` ist ein Lese-Aggregat in BC
`installation-and-bootstrap`. Er schreibt keine Daten in andere BCs.
Alle Lese-Pfade gehen ueber die jeweiligen Top-Surfaces, nie direkt
ueber Filesystem-Zugriff auf fremde BC-interne Strukturen.

**Invariante:** Erkannte Anpassungen werden niemals stillschweigend
ueberschrieben (F-51-023).

## 51.9 Uninstall und Decommission

Das **Drei-Ebenen-Modell** und die Verb-Topologie sind in FK-10 §10.2.9
verankert; dieser Abschnitt führt die **operative Mechanik**. §51.7
(Cleanup) bleibt der nicht-destruktive Teilausschnitt davon.

**Grundregel:** Eine niedrigere Ebene löscht **niemals** kanonischen
Zustand einer höheren Ebene.

| Verb | Ebene | Mechanik | Schutz |
|------|-------|----------|--------|
| **Projekt-Detach** | 3 | Skill-Junctions lösen (über die Owner-Top-Surfaces, z. B. `Skills.unbind`), AK3-Hook-Registrierung über `Governance.register_hooks` (nur AK3-Blöcke, Command-Pattern `python -m agentkit.`) entfernen, `tools/agentkit/`-Launcher und `.agentkit/`-Bindungen löschen | Junction nur via `unlink`/`rmdir` nach `isjunction`-Check, **nie** `rmtree` durch den Link (FK-43); Projektcode und fremde Hooks bleiben; **zentraler State des Projekts bleibt** |
| **Maschinen-Uninstall** | 2 | `agentkit`-Paket deinstallieren, Bundle-Store und Shims entfernen | Vor dem Entfernen einer Bundle-Version: gebundene Projekte über das Registrierungs-Aggregat ermitteln und als **orphaned** warnen; laufende Harness-/Hook-Prozesse vorher beenden |
| **Core-Decommission** | 1 | Backend-/Frontend-Dienste stoppen, ggf. DB abbauen | **Destruktiv**: nur nach expliziter Bestätigung **und Pflicht-Export** des State-Backends (Audit-Trail, Closure-Records, QA-Ergebnisse); DB-Volume-Löschung **nie** an Dienst-Uninstall koppeln |
| **Projekt-Löschung** | 1 | kanonischen State eines Projekts zentral löschen | **Destruktiv**; explizite Bestätigung; nicht-destruktive Alternative bleibt **Archivierung** (DK-14) |

**Abgrenzung:** Ephemeres Runtime-Cleanup (Worktrees, Locks,
Read-Projektionen; FK-10 §10.4.2) ist **kein** Uninstall. Der
Cleanup-Modus aus §51.7 deckt genau **Projekt-Detach** (Ebene 3) ab;
Maschinen-Uninstall und Core-Decommission sind getrennte Abläufe, die
destruktiven beiden hinter expliziter Bestätigung.

---

*FK-Referenzen: FK-11-006 (Idempotenz), FK-11-008
(Anpassungsschutz bei Upgrades)*
