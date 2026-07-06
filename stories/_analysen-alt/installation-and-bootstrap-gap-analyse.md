# installation-and-bootstrap — GAP-Analyse

> Generiert von einem dedizierten Sonnet-Sub-Agent (Stand 2026-05-16).

## Header

| Feld | Wert |
|---|---|
| BC-ID | `installation-and-bootstrap` |
| Display-Name | `Installation und Bootstrap` |
| Analyse-Datum | `2026-05-16` |
| Konzept-Quellen (autoritativ) | `DK-08, FK-50, FK-51, formal.installer.entities, formal.installer.state-machine, formal.installer.commands, formal.installer.events, formal.installer.invariants, formal.installer.scenarios` |
| Codebase-Hauptpfade | `src/agentkit/installer/`, `src/agentkit/cli/` |

## 1. Executive Summary

Der BC `installation-and-bootstrap` ist implementiert als einfache Dateisystem-Deployment-Funktion (`install_agentkit`), die Projektscaffold, Codex-Settings, CCAG-Regeln und eine `project.yaml` in ein Zielprojekt schreibt. Das Konzept hingegen fordert eine vollstaendige Checkpoint-Engine mit 12 Checkpoints, typisiertem State-Backend-Eintrag, Symlink-Bindung ueber Nachbar-BC-Top-Surfaces, Dry-Run-Modus, Verifikations-Command und Customization-Preservation-Logik. Die Luecke zwischen Ist und Soll ist fundamental: die fachliche Kernmechanik (Checkpoint-Flow, State-Backend-Registrierung, Upgrade-Pfade) fehlt vollstaendig. Vorhandener Code deckt Teile der Dateianlieferung (CP 5, CP 9 ansatzweise, CP 11 ansatzweise), aber kein einziges Checkpoint mit echtem Status-Tracking.

| Kategorie | Anzahl |
|---|---|
| A — Nicht umgesetzt | 10 |
| B — Teilweise umgesetzt | 5 |
| C — Drift / Fehler | 3 |

## 2. Konzept-Soll (Kurzfassung)

- **Checkpoint-Engine mit 12 expliziten Checkpoints als FlowDefinition** — `FK-50.md §50.3`, `FK-50.md §50.3.1`
- **Typisiertes State-Backend als Schreib-Owner der `project_registry`-Tabelle** — `FK-50.md §50.3 CP 7`
- **`CheckpointResult`-Rueckgabe je Checkpoint (PASS/CREATED/UPDATED/SKIPPED/FAILED)** — `FK-50.md §50.4`
- **Ausfuehrungsmodi: Erstregistrierung, idempotenter Re-Lauf, Dry-Run, Verifikation** — `FK-50.md §50.2`
- **Symlink-Bindung ueber Top-Surface `Skills.bind_skill` (BC agent-skills)** — `FK-50.md §50.5`
- **Prompt-Bundle-Bindung ueber Top-Surface `PromptRuntime.update_binding` (BC prompt-runtime)** — `FK-50.md §50.5`
- **Hook-Registrierung ueber Top-Surface `Governance.register_hooks` (BC governance-and-guards)** — `FK-50.md §50.3 CP 9`
- **Idempotenz-Invariante: Re-Lauf konvergiert auf konsistenten Registrierungszustand** — `formal.installer.invariants §installer.invariant.register_project_is_idempotent`
- **Fail-closed: partielles Profil ist unzulaessig** — `FK-50.md §50.5`
- **CLI-Command `agentkit register-project --gh-owner --gh-repo`** — `formal.installer.commands §installer.command.register-project`
- **CLI-Command `agentkit verify-project` (read-only)** — `formal.installer.commands §installer.command.verify-project`
- **Upgrade mit Customization-Preservation (`CustomizationFootprint`)** — `FK-51.md §51.8`
- **Config-Migration bei `config_version`-Sprung mit `.bak`-Backup** — `FK-51.md §51.4`
- **Formale State-Machine: 7 Zustaende, Uebergangswachter** — `formal.installer.state-machine`
- **Event-Emission (registration.requested/.started/.completed/.failed/dry_run_completed/binding.rebound/customization.preserved)** — `formal.installer.events`

## 3. Code-Stand (Ist-Bild)

- `src/agentkit/installer/runner.py:install_agentkit` — Monolithische Funktion; deployt Dateisystem-Scaffold, prompt-bundle-hardlinks, project.yaml, codex-config, CCAG-Regeln; kein Checkpoint-Schema, kein State-Backend-Aufruf
- `src/agentkit/installer/runner.py:uninstall_agentkit` — Entfernt Installer-Artefakte; kein Bezug zur formalen State-Machine
- `src/agentkit/installer/runner.py:InstallConfig` — Konfigurationsstruktur mit `project_key`, `project_root`, `github_owner/repo`, `prompt_bundle_root`; fehlt `runtime_profile`, `execution_mode`
- `src/agentkit/installer/runner.py:InstallResult` — Rueckgabe mit `success`, `project_root`, `created_files`, `errors`; kein `CheckpointResult`-Schema
- `src/agentkit/installer/paths.py` — Pfaddefinitionen fuer Projektlayout; vollstaendig und konsistent mit Konzept
- `src/agentkit/installer/ccag_settings.py:deploy_ccag_settings` — Schreibt CCAG-Regelfiles einmalig (write-once), korrekte Idempotenz
- `src/agentkit/installer/codex_settings.py:write_codex_settings` — Schreibt `.codex/config.toml` mit Hook-Eintrag; idempotent
- `src/agentkit/installer/file_ops.py` — Dateioperationen (hardlink/symlink/copy-Fallback, atomic write); kein Installer-Fachbezug
- `src/agentkit/cli/main.py` — Enthaelt `install`- und `uninstall`-Subcommands; kein `register-project`, kein `verify-project`
- `src/agentkit/config/models.py:ProjectConfig` — Pydantic-v2-Model fuer `project.yaml`; fehlt `config_version`, `runtime_profile`
- `tests/unit/installer/test_multi_harness_installer.py` — Idempotenz-Test fuer Dateisystem-Deployment; kein Checkpoint-State-Test
- `tests/contract/scaffold_snapshots/test_install_scaffold.py` — Contract-Tests fuer Scaffold-Struktur und project.yaml-Felder

## 4. GAP-Analyse

### 4.1 A — Nicht umgesetzt

| # | Thema | Konzept-Referenz | Anmerkung |
|---|---|---|---|
| A1 | Checkpoint-Engine als `FlowDefinition` mit 12 expliziten Checkpoints | `FK-50.md §50.3`, `FK-50.md §50.3.1` | Kein `FlowDefinition`, kein Checkpoint-Step-Schema; Logik liegt als imperative Funktion ohne Zustandstracking |
| A2 | State-Backend-Registrierung (CP 7): `project_registry`-Tabelle, `ProjectRegistration`-Entitaet | `FK-50.md §50.3 CP 7`, `formal.installer.entities §installer.entity.project-registration` | Keine `project_registry`-Tabelle; keine `ProjectRegistration`-Klasse im Installer |
| A3 | `CheckpointResult`-Typisierung (PASS/CREATED/UPDATED/SKIPPED/FAILED) | `FK-50.md §50.4` | `InstallResult` hat nur `success` (bool) und `created_files`; keine Checkpoint-granulare Statusrueckgabe |
| A4 | Ausfuehrungsmodus Dry-Run (`execution_mode=dry_run`) | `FK-50.md §50.2`, `formal.installer.commands §installer.command.register-project-dry-run`, `formal.installer.invariants §installer.invariant.dry_run_never_mutates_runtime_or_project_state` | Kein Dry-Run-Modus implementiert; kein `--dry-run`-Flag in CLI |
| A5 | CLI-Command `agentkit register-project` (ersetzt `install`) | `formal.installer.commands §installer.command.register-project` | CLI hat `install`-Subcommand ohne `--gh-owner`/`--gh-repo`; konzeptgemaessr Name und Signatur fehlen |
| A6 | CLI-Command `agentkit verify-project` (read-only Verifikation, CP 12) | `formal.installer.commands §installer.command.verify-project`, `FK-50.md §50.3 CP 12` | Kein `verify-project`-Subcommand; CP 12 nicht umgesetzt |
| A7 | Formale State-Machine mit 7 Zustaenden und Uebergangswachtern | `formal.installer.state-machine` | Kein Zustandsobjekt, keine Transitionen, kein Guard-Enforcement |
| A8 | Event-Emission (registration.requested/.started/.completed/.failed/dry_run_completed/binding.rebound/customization.preserved) | `formal.installer.events` | Keine Event-Emitter im Installer-Code vorhanden |
| A9 | GitHub-Repo-Pruefung (CP 2: `gh repo view`, gh-Auth-Pruefung) | `FK-50.md §50.3 CP 2` | Nicht implementiert; `github_owner`/`github_repo` werden nur in `project.yaml` geschrieben, nicht verifiziert |
| A10 | Projektprofil-Ermittlung (CP 6: `core` vs. `are`) und profilgesteuertes Skill-Binding | `FK-50.md §50.3 CP 6`, `FK-50.md §50.5` | Kein Profil-Resolver; Symlinks werden nicht erstellt; kein Aufruf von `Skills.bind_skill` |

### 4.2 B — Teilweise umgesetzt

| # | Thema | Code-Referenz | Konzept-Referenz | Was fehlt |
|---|---|---|---|---|
| B1 | Pipeline-Config-Anlage (CP 5: `project.yaml` erstellen wenn nicht vorhanden) | `src/agentkit/installer/runner.py:_build_project_yaml`, `_write_yaml_if_changed` | `FK-50.md §50.3 CP 5` | Kein `config_version`-Feld in `project.yaml`; keine Config-Migration bei `config_version`-Sprung (FK-51 §51.4); ARE-Scope-Mapping (`are.module_scope_map`) fehlt |
| B2 | Hook-Registrierung (CP 9) | `src/agentkit/installer/ccag_settings.py:deploy_ccag_settings`, `src/agentkit/installer/codex_settings.py:write_codex_settings` | `FK-50.md §50.3 CP 9`, `FK-51.md §51.6` | Kein Aufruf von `Governance.register_hooks` (Top-Surface-Delegation fehlt); Hooks werden direkt als Dateien geschrieben statt via BC `governance-and-guards` |
| B3 | Git-Hooks und CLAUDE.md (CP 11) | `src/agentkit/resources/target_project/` (statische Dateien via `_deploy_static_resource_files`) | `FK-50.md §50.3 CP 11` | Kein `git config core.hooksPath`-Aufruf; CLAUDE.md-Skelett-Erzeugung fehlt; Pre-Commit-Hook-Dispatching-Logik (51.6.1) nicht umgesetzt |
| B4 | Idempotenz bei Re-Lauf | `src/agentkit/installer/runner.py:_write_yaml_if_changed`, `_write_text_if_changed`, `ccag_settings._write_once` | `formal.installer.invariants §installer.invariant.register_project_is_idempotent` | Idempotenz nur auf Dateisystemebene; kein Idempotenz-Check gegen State-Backend-Registrierung; SKIPPED-Rueckgabe per Checkpoint fehlt |
| B5 | Prompt-Bundle-Bindung | `src/agentkit/installer/runner.py:_deploy_prompt_bindings`, `_ensure_prompt_bundle_store_entry` | `FK-50.md §50.5` | Bundle wird direkt als Hardlink/Kopie deployt, nicht ueber Top-Surface `PromptRuntime.update_binding`; kein Aufruf von BC `prompt-runtime`; `bundle_binding`-Entitaet fehlt |

### 4.3 C — Drift / Fehler

| # | Thema | Code-Referenz | Konzept-Referenz | Drift / Fehler |
|---|---|---|---|---|
| C1 | CLI-Verb ist `install` statt `register-project` | `src/agentkit/cli/main.py` (Zeile 37) | `formal.installer.commands §installer.command.register-project` | Das offizielle CLI-Kommando laut formaler Spec lautet `agentkit register-project --gh-owner --gh-repo`; die Implementierung verwendet `agentkit install --project-key --project-name --project-root` ohne `--gh-owner`/`--gh-repo`-Flags. Das verletzt den formalen Kommandovertrag und den State-Machine-Guard `system_installation_precedes_project_registration`. |
| C2 | Prompt-Bundle-Bindung direkt im Installer statt via `PromptRuntime.update_binding` | `src/agentkit/installer/runner.py:_deploy_prompt_bindings` | `FK-50.md §50.5`, `formal.installer.invariants §installer.invariant.project_local_scope_is_config_and_symlink_only` | Der Installer kopiert/hardlinkt Prompt-Templates eigenstaendig. Das verletzt die Invariante, wonach Symlink-Bindungen ueber die Top-Surface des Owner-BC (`prompt-runtime`, BC 10) erfolgen muessen. Der Installer schreibt damit in den Verantwortungsbereich eines anderen BC. |
| C3 | `InstallResult.success` als bool statt Checkpoint-granulare Rueckgabe | `src/agentkit/installer/runner.py:InstallResult` | `FK-50.md §50.4`, `formal.installer.entities §installer.entity.checkpoint-run` | Rueckgabe liefert binaeresErgebnis ohne Checkpoint-Identifikatoren. Konzept fordert je Checkpoint einen `CheckpointResult` mit `checkpoint`, `status`, `detail`, `duration_ms`. Die vereinfachte Rueckgabe macht Partial-Failures nicht auswertbar und verletzt die Fail-Closed-Semantik. |

## 5. Ableitungen / Empfehlungen

1. **Checkpoint-Engine als `FlowDefinition` implementieren (A1, A3):** Das Fundament des BC fehlt. Ohne Checkpoint-granulare Zustandstracking ist kein fairer Fortschritt messbar, Dry-Run und Verifikation sind nicht abgrenzbar, und die State-Machine-Invarianten koennen nicht enforced werden. Blocker fuer alle weiteren Punkte.

2. **State-Backend-Registrierung (CP 7) und `ProjectRegistration`-Entitaet anlegen (A2):** Die `project_registry`-Tabelle ist der kanonische Registrierungseintrag laut Konzept. Ohne sie hat der Installer keine auswertbare Wahrheit ueber den Projektstatus. Blocker fuer idempotente Re-Laeufe und Upgrade-Logik (FK-51).

3. **CLI-Signatur auf `register-project`/`verify-project` umstellen (A5, A6, C1):** Die formale Spec definiert die CLI-Surface verbindlich. Der aktuelle `install`-Subcommand ist ein Drift, der Aufrufer (Agents, CI, Wrapper-Skripte) auf falsche Kommandos eintrainiert. Sollte parallel zur Checkpoint-Engine-Implementierung korrigiert werden.

4. **Top-Surface-Delegation fuer Prompt-Bundle-Bindung und Hook-Registrierung umstellen (B2, B5, C2):** Der Installer schreibt aktuell direkt in Verantwortungsbereiche der BCs `prompt-runtime` und `governance-and-guards`. Das verletzt die BC-Grenzlinien und die formale Invariante `project_local_scope_is_config_and_symlink_only`. Korrekte Delegation muss hergestellt werden, sobald die Nachbar-BCs ihre Top-Surfaces exponieren.

5. **Upgrade-Pfade und Customization-Preservation implementieren (alle FK-51-Anforderungen):** Config-Migration, Upgrade-Erkennung via `config_digest` und `CustomizationFootprint` sind vollstaendig absent. Ohne diese Mechanismen kann ein Upgrade bestehende Projektkonfiguration stillschweigend ueberschreiben — direkter Verstoss gegen `installer.invariant.customizations_are_never_silently_overwritten`.

6. **Event-Emission integrieren (A8):** Installer-Events sind Voraussetzung fuer Telemetrie und Auditierbarkeit. Kein Event bedeutet, dass Registrierungs- und Upgrade-Laeufe unsichtbar sind. Mittelfristig adressieren, sobald Checkpoint-Engine steht.

## 6. Suchstrategie & Quellen

- **Vollstaendig gelesen:**
  - `concept/domain-design/08-installation-und-bootstrap.md`
  - `concept/technical-design/50_installer_checkpoint_engine_bootstrap.md`
  - `concept/technical-design/51_upgrade_migration_customization_preservation.md`
  - `concept/formal-spec/installer/README.md`
  - `concept/formal-spec/installer/entities.md`
  - `concept/formal-spec/installer/state-machine.md`
  - `concept/formal-spec/installer/commands.md`
  - `concept/formal-spec/installer/events.md`
  - `concept/formal-spec/installer/invariants.md`
  - `concept/formal-spec/installer/scenarios.md`
  - `concept/technical-design/_meta/domain-registry.yaml`
  - `src/agentkit/installer/runner.py`
  - `src/agentkit/installer/__init__.py`
  - `src/agentkit/installer/paths.py`
  - `src/agentkit/installer/ccag_settings.py`
  - `src/agentkit/installer/codex_settings.py`
  - `src/agentkit/installer/file_ops.py`
  - `src/agentkit/cli/main.py`
  - `src/agentkit/config/models.py`
  - `tests/unit/installer/test_installer_namespace.py`
  - `tests/unit/installer/test_multi_harness_installer.py`
  - `tests/contract/scaffold_snapshots/test_install_scaffold.py`

- **Punktuell via Grep:**
  - Pattern `register.project|CheckpointResult|checkpoint_run|ProjectRegistration`: Bestaetigung, dass State-Backend-Registrierungstypen nicht existieren
  - Pattern `FlowDefinition.*Installer|checkpoint_engine`: Bestaetigung, kein Checkpoint-Engine-Einsatz im Installer
  - Pattern `Skills\.bind_skill|PromptRuntime\.update_binding|Governance\.register_hooks`: Bestaetigung, keine Top-Surface-Delegation
  - Pattern `dry.run|execution_mode|verify_project`: Bestaetigung, kein Dry-Run und kein verify-project
  - Pattern `config_digest|CustomizationFootprint|migrate_config` in `src/agentkit/installer/`: Bestaetigung, keine Upgrade-Logik im Installer

- **Code-Scan (Glob):**
  - Pattern `src/agentkit/installer/**`: Moduluebersicht
  - Pattern `src/agentkit/cli/**`: CLI-Struktur
  - Pattern `tests/unit/installer/**` und `tests/contract/**`: Testabdeckung
  - Pattern `src/agentkit/boundary/**` und `src/agentkit/config/**`: Pruefen ob relevante Installer-Typen dort liegen
