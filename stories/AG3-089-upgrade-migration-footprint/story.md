# AG3-089: Upgrade/Migration + CustomizationFootprint

**Typ:** Implementation
**Groesse:** L
**Bounded Context:** `installation-and-bootstrap` (`installer/upgrade/`) — Config-/Hook-Migration ueber Versionsspruenge und die Customization-Preservation als Lese-Aggregat ueber die Owner-BC-Top-Surfaces.
**Quell-Konzepte (autoritativ):**
- `FK-51 §51.3` — drei Upgrade-Szenarien: (1) Config+Bindung unveraendert, (2) Config vom Nutzer angepasst, (3) neue Skill-/Prompt-Variante
- `FK-51 §51.4` — Config-Migration `migrate_config(existing, target_version)` / `migrate_3_to_4`, schrittweise bei `config_version`-Major-Sprung, `.bak`-Backup vor jeder Migration
- `FK-51 §51.6` / `§51.6.1` — Hook-Migration via `Governance.register_hooks`, Git-Hook-Dispatching-Migration inkl. `.bak`-Sicherung unerkannter Anpassungen
- `FK-51 §51.7` — Cleanup obsoleter Bindungen/Config-Reste
- `FK-51 §51.8` — `CustomizationFootprint` (Lese-Aggregat ueber Owner-BC-Top-Surfaces) + Nie-still-ueberschreiben-Invariante (F-51-023)

---

## 1. Kontext / Ist-Zustand (belegt)

FK-51 ist **vollstaendig FEHLT** als Upgrade-/Migrations-/Preservation-Logik (Gap FK-46-56 §51.3-§51.8). Die *Lesesurfaces der Owner-BCs* existieren bereits — was fehlt, ist das aggregierende `CustomizationFootprint`-Modell, die Schutz-Invariante F-51-023 und der gesamte Upgrade-/Migrations-/Cleanup-Flow:

- **Config-Migration FEHLT:** Grep `migrate_config|migrate_3_to_4|\.bak|config_version` in `installer/` -> `config_version` nur als statische Konstante `PROJECT_CONFIG_VERSION = "1"` (`src/agentkit/installer/runner.py:75`); **keine** Versionsvergleichs-/Migrationslogik, **kein** `.bak`-Backup. `installer/upgrade/` existiert nicht (Glob -> keine Datei).
- **Hook-/Git-Hook-Migration FEHLT:** kein Cleanup-Modus (kein `cleanup`-CLI-Command), keine Hook-Migrationslogik, keine Git-Hook-Dispatching-Migration. Der idempotente Re-Run aktualisiert nur die Registrierungs-Row (`src/agentkit/installer/runner.py:1343` `update_upgraded`) — das ist **keine** Customization-Preservation.
- **`CustomizationFootprint` FEHLT:** Grep `CustomizationFootprint|customization` -> keine Implementierung. Das Aggregat + die Schutz-Invariante (F-51-023) sind ungebaut.

Anknuepfungspunkte (existieren bereits, werden **lesend** konsumiert):
- **Vier Lesequellen-Owner mit realen Top-/Lesesurfaces** (FK-51 §51.8-Tabelle):
  1. Pipeline-Config-Schwellenwerte (BC `pipeline-framework`, FK-03): `PipelineConfig`-Schema (`src/agentkit/config/models.py:335`) ueber Loader `load_project_config` (`src/agentkit/config/loader.py:52`); Erkennung via Datei-Hash/Digest-Vergleich.
  2. CCAG-Regeln (BC `governance-and-guards`): Runtime-Lesesurface `load_rules` (`src/agentkit/governance/ccag/rules.py:345`).
  3. Prompt-Bundle-Binding (BC `prompt-runtime`): `resolve_project_prompt_binding` -> `PromptBundleBinding` (`src/agentkit/prompt_runtime/resources.py:105`, `src/agentkit/prompt_runtime/resources.py:37`); Rebinding ueber `PromptRuntime.update_binding` (`src/agentkit/prompt_runtime/runtime.py:206`).
  4. Skill-Binding (BC `agent-skills`): `Skills.resolve_binding(project_root, skill_name)` (`src/agentkit/skills/top.py:625`, Top-Surface FK-43).
- **Hook-Migrationsziel:** Callable `Governance.register_hooks(hook_definitions)` (`src/agentkit/governance/runner.py:193`); die `HookDefinition`/`RegistrationResult`-Typen liefert `src/agentkit/governance/hook_registration.py` (`HookDefinition` ab Z. 70).
- Die Checkpoint-Engine + Execution-Modi aus **AG3-088** (Upgrade ist ein Modus/Flow der Engine, kein zweiter Installer).
- `config_version`-Pflichtfeld + fail-closed Loader aus **AG3-070** (FK-03) als Versions-Quelle der Migration.

## 2. Scope

### 2.1 In Scope
1. **`migrate_config(existing, target_version)` + `migrate_3_to_4`** unter `installer/upgrade/` (§51.4):
   - schrittweise Migration bei `config_version`-Major-Sprung (kein Sprung-Ueberspringen),
   - `.bak`-Backup der bestehenden Config **vor** jeder Migration (atomar, wiederherstellbar),
   - typisierte Migrations-Schritte (Owner = installer-upgrade); fail-closed bei unbekannter Quell-/Zielversion.
2. **Drei Upgrade-Szenarien (§51.3)** in der Upgrade-Flow-Logik (auf der AG3-088-Engine) als typisierte Entscheidung ueber Digest-/Bundle-/Binding-Kriterien:
   - **§51.3.1 unveraendert:** Config-Digest == Datei-Hash auf Disk **und** Bundle-Version unveraendert -> **kein Update** (skip). Hat sich nur die Ziel-Bundle-Version geaendert (Config-Digest == Datei-Hash), darf die Symlink-Bindung **explizit** auf die neue Bundle-Version umgestellt werden.
   - **§51.3.2 vom Nutzer angepasste Config:** registrierter Digest != Datei-Hash -> `.bak`-Backup erstellen, **dann** neue Version schreiben; die manuelle Nachzieh-Pflicht des Menschen wird explizit gemeldet (kein stilles Verwerfen der Nutzer-Aenderung, aber auch kein Block der Config-Migration — Backup + Write ist hier der vorgeschriebene Pfad).
   - **§51.3.3 neue Skill-/Prompt-Variante:** systemweite Varianten werden nur uebernommen, wenn die Projekt-Bindung **explizit** auf das neue Bundle/Profil umgestellt wird (kein automatischer Pull).
3. **Hook-/Git-Hook-Migration (§51.6/§51.6.1):**
   - geaenderte/neue/entfernte Hook-Definitionen ermitteln und ueber `Governance.register_hooks` neu materialisieren;
   - Pre-Commit-Git-Hook-Dispatching-Migration: bestehenden `pre-commit` pruefen, Dispatching-Logik (Secret-Detection global, Versionsbump bei Code-, Concept-Validation bei Konzeptaenderungen) ergaenzen; **unerkannte Pre-Commit-Anpassungen werden vor dem Schreiben als `.bak` gesichert** (§51.6.1 Schritt 4) — keine stille Zerstoerung.
4. **Cleanup-Modus (§51.7):** obsolete Symlink-Bindungen/lokale Config-Reste entfernen; als typisierter `cleanup`-Modus/CLI-Subkommando; **fail-closed**, wo Cleanup eine vom Footprint erkannte Anpassung treffen wuerde (siehe Invariante). Cleanup fasst weder Projektcode noch zentrale Laufzeitdaten an.
5. **`CustomizationFootprint` (§51.8):** Lese-Aggregat im BC `installation-and-bootstrap`, das die vier Quellen ueber deren Owner-BC-Top-/Lesesurfaces kombiniert (Pipeline-Config-Digest via `load_project_config`/`PipelineConfig`, CCAG-Regeln via `load_rules`, Prompt-Binding via `resolve_project_prompt_binding`, Skill-Binding via `Skills.resolve_binding`) — kein Direktzugriff in fremde BC-interne Strukturen. **Invariante F-51-023:** erkannte Anpassungen werden **nie still ueberschrieben**.
6. **Tests:** siehe Akzeptanzkriterien — drei §51.3-Szenarien, schrittweise 3->4-Migration mit `.bak`, fail-closed bei unbekannter Version, Hook-Migration ruft `register_hooks`, Git-Hook-`.bak` bei unerkannter Anpassung, Cleanup-Schutz, Footprint-Vier-Quellen, F-51-023.

### 2.2 Out of Scope (mit Owner)
- **Checkpoint-Engine / Execution-Modi / `register-project`/`verify-project`** — **AG3-088** (diese Story baut darauf auf, ergaenzt sie nicht).
- **Config-Modell / `config_version`-Pflichtfeld / Feature-Matrix / fail-closed Loader** — **AG3-070** (FK-03/FK-90). Upgrade konsumiert das Modell.
- **Owner-Lesesurfaces selbst** (`PipelineConfig`/`load_project_config`, `load_rules`, `resolve_project_prompt_binding`/`PromptRuntime.update_binding`, `Skills.resolve_binding`) — bestehende BCs; hier nur **lesend** ueber deren Surface aggregiert, nicht veraendert.
- **Telemetrie-Events fuer Upgrade** — falls noetig ueber bestehenden Contract; kein neuer Event-Katalog hier.

## 3. Akzeptanzkriterien
1. `migrate_config`/`migrate_3_to_4` existieren unter `installer/upgrade/` und migrieren schrittweise bei `config_version`-Major-Sprung (Test 3->4); ein `.bak`-Backup wird vor jeder Migration erzeugt (Test: Backup vorhanden + Inhalt = alte Config).
2. Migration ist fail-closed bei unbekannter Quell-/Zielversion (Negativtest).
3. **Drei §51.3-Szenarien (typisierte Pfadentscheidung):**
   - **3a (§51.3.1 skip):** Config-Digest == Datei-Hash **und** Bundle-Version unveraendert -> Ergebnis „kein Update", keine Schreiboperation (Test).
   - **3b (§51.3.2 digest mismatch):** registrierter Digest != Datei-Hash -> `.bak` erzeugt, neue Version geschrieben, Nachzieh-Pflicht gemeldet (Test: `.bak`-Inhalt = alte Config, neue Config auf Disk).
   - **3c (§51.3.3 explicit binding):** neue Bundle-/Profil-Variante wird **nur** bei expliziter Bindungsumstellung uebernommen; ohne explizite Umstellung bleibt die alte Bindung (Test: kein automatischer Pull).
4. Hook-Migration ermittelt geaenderte Hook-Definitionen und ruft `Governance.register_hooks` (Test: Aufruf belegt); Git-Hook-Dispatching-Migration ueberfuehrt den alten Dispatch (Test).
5. **Git-Hook-`.bak`-Schutz (§51.6.1):** eine **unerkannte** Anpassung im bestehenden `pre-commit` wird vor dem Schreiben als `.bak` gesichert; keine stille Zerstoerung (Test: alter Hook-Inhalt liegt als `.bak` vor).
6. Cleanup-Modus entfernt obsolete Bindungen/Config-Reste, laesst aber erkannte Anpassungen unangetastet (Test: obsolet -> entfernt, angepasst -> bleibt).
7. `CustomizationFootprint` aggregiert die vier Quellen ueber deren Owner-Top-/Lesesurfaces (`PipelineConfig`-Digest, `load_rules`, `resolve_project_prompt_binding`, `Skills.resolve_binding`) (Test mit je einer gesetzten Anpassung pro Quelle).
8. Nie-still-ueberschreiben (F-51-023): ein Schreibpfad in **Cleanup oder Binding-Umstellung**, der eine vom Footprint erkannte Anpassung treffen wuerde, blockiert/meldet (WARNING/ESCALATE) und mutiert **nicht** (Test). Abgrenzung: die Config-Migration nach §51.3.2 ist hiervon ausgenommen — dort ist `.bak`+Write der vorgeschriebene Pfad (AC 3b), die Invariante schuetzt die nicht-migrierbaren Schreibpfade (Cleanup/Binding/Git-Hook).
9. **Pflichtbefehle gruen:** pytest unit/integration/contract (in Chunks, `-n0`); mypy default + `--platform linux`; ruff; vier Konzept-Gates; Coverage >= 85 %.

## 4. Definition of Done
- AC 1–9 erfuellt; giftige Codex-Review PASS; (Implementierung/Commit erst nach Execution-Plan-Freigabe — diese Story wird zunaechst nur autorisiert/reviewt).

## 5. Guardrail-Referenzen
- **FAIL-CLOSED:** unbekannte Version, Cleanup/Binding gegen erkannte Anpassung, fehlendes Backup-Ziel, unerkannter Pre-Commit -> blockieren bzw. `.bak` sichern, nicht weglassen.
- **FIX-THE-MODEL / SINGLE SOURCE OF TRUTH:** `CustomizationFootprint` liest ausschliesslich ueber Owner-BC-Top-/Lesesurfaces — kein Direktzugriff/zweite Wahrheit; Hooks ueber `register_hooks`.
- **ZERO DEBT / Nie-still-ueberschreiben:** F-51-023 ist die zentrale Invariante fuer Cleanup-/Binding-/Git-Hook-Schreibpfade — keine stille Datenvernichtung. Die §51.3.2-Config-Migration nutzt `.bak`+Write (vom FK vorgeschrieben), keine stille Mutation.
- **TYPISIERT STATT STRINGS:** Migrations-Schritte, Szenario-Entscheidung, Footprint-Eintraege, Cleanup-Modus typisiert.
- **ARCH-55:** Migrations-/Modus-/Aggregat-Namen, `.bak`-Konvention englisch.

## 6. Hinweise fuer den Sub-Agent
- Read T:/codebase/claude-agentkit3/CLAUDE.md first — all project rules apply to you.
- Diese Story setzt **AG3-088** (Checkpoint-Engine + Modi) und **AG3-070** (`config_version`-Loader) voraus — Upgrade ist ein Flow/Modus der Engine, **kein** zweiter Installer.
- `CustomizationFootprint` darf **nicht** in fremde BC-interne Strukturen greifen — nur ueber die vier Owner-Surfaces (`load_rules`, `resolve_project_prompt_binding`, `Skills.resolve_binding`, `PipelineConfig`-Digest via `load_project_config`).
- F-51-023 (nie still ueberschreiben) gilt fuer Cleanup-/Binding-/Git-Hook-Schreibpfade: jeder dieser Schreibpfade muss vorher den Footprint konsultieren. Die §51.3.2-Config-Migration ist davon ausgenommen (FK-vorgeschriebenes `.bak`+Write).
- `.bak`-Backup atomar und vor jeder Migration bzw. vor dem Ueberschreiben unerkannter Pre-Commit-Anpassungen; bei Migrationsfehler wiederherstellbar.
- Code-Anker sind als `file:line` im Ist-Zustand belegt; bei Implementierung gegen die realen Surfaces arbeiten, nicht gegen erfundene Symbole.
- AK2 NICHT veraendern. `.mcp.json` NICHT anfassen. **Kein Commit** ohne expliziten Auftrag.
- „done" nur mit Beleg: Diff-Zusammenfassung, gruene Pflichtbefehle, Test-Namen (3->4-Migration, `.bak`, fail-closed-Version, drei §51.3-Szenarien, Git-Hook-`.bak`, Footprint-4-Quellen, Nie-still-ueberschreiben).

---

## Globale Akzeptanzkriterien (verbindlich)

Zusaetzlich zu den obigen Akzeptanzkriterien gelten die **globalen Akzeptanzkriterien**
aus `stories/_GLOBAL_ACCEPTANCE.md` (Single Source of Truth):

- **GAC-1:** `scripts/ci/check_architecture_conformance.py` laeuft mit **0 Errors**
  (Exit 0, fail-closed) — `PYTHONPATH=src .venv\Scripts\python scripts/ci/check_architecture_conformance.py`.
- **GAC-2:** Die Architektur-Guardrails `guardrails/architecture-guardrails.md`
  (ARCH-NN) werden eingehalten; Konflikt = hart stoppen und melden.
