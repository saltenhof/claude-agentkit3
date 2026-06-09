# AG3-088: Checkpoint-Engine-Installer (FlowDefinition statt God-File)

**Typ:** Implementation
**Groesse:** L
**Bounded Context:** `installation-and-bootstrap` (`installer/`) — der Installer als deterministische Checkpoint-Engine im Flow-Modell statt als imperatives God-File.
**Quell-Konzepte (autoritativ):**
- `FK-50 §50.2` — Ausfuehrungsmodi (Erstregistrierung, idempotenter Re-Lauf, Dry-Run `execution_mode=dry_run`, Verifikation `execution_mode=verify` read-only) + CLI-Boundary-Controls `register-project`/`verify-project`
- `FK-50 §50.3` / `§50.3.1` — Checkpoint-Engine als `FlowDefinition(level=COMPONENT, owner="Installer")` mit `step`/`branch`-Knoten; Checkpoint-Inventar CP1..CP12 inkl. reservierter CP3/CP4 und Sub-Checkpoints CP10a/10b/10c/10d
- `FK-50 §50.4` — `CheckpointResult` (status-Vokabular `PASS/CREATED/UPDATED/SKIPPED/FAILED` + maschinenlesbarer `reason`); NOT_APPLICABLE wird als `SKIPPED` mit `reason="not_applicable"` gefuehrt (kein eigener Status)

---

## 1. Kontext / Ist-Zustand (belegt)

- **God-File statt FlowDefinition (ABWEICHEND):** `installer/runner.py:1014` `install_agentkit(config)` ist eine monolithische imperative Funktion mit fest verdrahteter Reihenfolge; Grep `FlowDefinition` in `installer/` -> **0 Treffer**. Die in PROJECT_STRUCTURE vorgesehenen Substrukturen `installer/checkpoint_engine/` und `installer/bootstrap_checkpoints/` existieren nicht (nur `installer/integration_checkpoints/`). Das ist genau das God-File-Muster, das §50.3.1 und CLAUDE.md vermeiden (Gap FK-46-56 §50.3.1).
- **Ausfuehrungsmodi UNVOLLSTAENDIG:** kein `dry_run`-Modus, kein read-only `verify`-Modus (Grep `dry_run|execution_mode|verify_project` -> nur Prosa-Kommentare). Idempotenter Re-Lauf existiert nur fuer CP7 (`runner.py:1335` Digest-Vergleich, `existing.config_digest == digest` -> SKIPPED, divergent -> UPDATED) (Gap §50.2).
- **Checkpoints unvollstaendig:** real vorhanden sind CP5 (project.yaml, `runner.py:1076-1079`), CP7 (State-Backend-Registration, `runner.py:1092` ueber `_run_cp7_state_backend_registration`), CP8 (Skill-Links via `Skills.bind_skill`, `runner.py:882`), CP10d (Sonar-Preflight, `installer/integration_checkpoints/`), CI-Preflight (AG3-056). **Fehlen** als eigenstaendige Checkpoints: CP1 (Python-Paketcheck), CP2 (`gh repo view`-Check), CP3/CP4 (reservierte No-op-Knoten fuer Nummernstabilitaet, §50.3.1), CP6 (Profilermittlung als Checkpoint mit Result — heute nur interner `_resolve_skill_profile`, `runner.py:674`), CP8-Halbteil (`PromptRuntime.update_binding`, `prompt_runtime/runtime.py:206`), CP9 (Hook-Registrierung via `Governance.register_hooks` statt statischem Settings-Deploy), CP10/10a/10b/10c (MCP-Server, ConceptContext-Properties, Concept-Validation-Hook, ARE-Scope-Validierung), CP11 (`core.hooksPath` + CLAUDE.md-Skelett), CP12 (read-only Gesamtverifikation) (Gap §50.2/§50.3).
- **CLI-Boundary FEHLT:** `cli/main.py:38-160` kennt `install`/`uninstall`/`run-story`/`doctor`/`serve-control-plane` — **kein** `register-project`, **kein** `verify-project`.

Anknuepfungspunkte (existieren, konsumieren):
- **Flow-DSL ist bereits vorhanden:** `src/agentkit/process/language/` mit `FlowDefinition` (`model.py:175`, Felder `flow_id`/`level`/`owner`/`nodes`/`edges`/`hooks`), `FlowLevel.COMPONENT` (`model.py:40`), `NodeKind.STEP`/`.BRANCH` (`model.py:46`/`:49`), `builder.py`, `gates.py`, `recovery.py`. Die Checkpoint-Engine wird **damit** modelliert (kein neuer DSL-Bau).
- `CheckpointResult` + `CheckpointStatus`: `installer/registration.py:123-173` (`CheckpointResult` mit `checkpoint`/`status`/`detail`/`reason`/`duration_ms`, Pflicht-`reason` bei SKIPPED/FAILED via Validator `:150`) und `installer/registration.py:43-50` (`CheckpointStatus` = `PASS/CREATED/UPDATED/SKIPPED/FAILED`); `RuntimeProfile` `installer/registration.py:33`. NOT_APPLICABLE-als-`SKIPPED`/`reason="not_applicable"` ist konform — wird wiederverwendet, **kein** neues Status-Wort.
- Bestehende Checkpoint-Logik in `runner.py` (CP5/7/8/10d) wird in Step-Handler **ueberfuehrt**, nicht neu erfunden.
- `Governance.register_hooks` (`governance/runner.py:193`) als CP9-Ziel (Datenmodelle `HookDefinition` etc. liegen in `governance/hook_registration.py`; die Methode liegt in `governance/runner.py`). `Skills.bind_skill` (`skills/top.py:361`) und `PromptRuntime.update_binding` (`prompt_runtime/runtime.py:206`) als CP8.

## 2. Scope

### 2.1 In Scope
1. **Installer als `FlowDefinition(level=COMPONENT, owner="Installer")`** (§50.3.1): jeder Checkpoint ein `step`-Knoten; Profil-/Feature-Entscheidungen als `branch`-Knoten (`branch_vectordb_enabled`, `branch_are_enabled`, `branch_sonarqube_enabled`). Kontrollfluss durch die bestehende Flow-DSL; Idempotenz in den Step-Handlern. Substruktur `installer/checkpoint_engine/` (+ `bootstrap_checkpoints/`). **Exakte Knoten-ID-Liste** (§50.3.1 Minimal-Flow, normativ):
   - `cp_01_package_check`
   - `cp_02_repo_check`
   - `cp_03_reserved` (No-op, deterministischer `CheckpointResult` status `SKIPPED` mit `reason="reserved"`)
   - `cp_04_reserved` (No-op, deterministischer `CheckpointResult` status `SKIPPED` mit `reason="reserved"`)
   - `cp_05_pipeline_config`
   - `cp_06_profile_resolution`
   - `cp_07_backend_registration`
   - `cp_08_skill_bindings`
   - `cp_09_hook_registration`
   - `cp_10_mcp_registration` (MCP-Server-Registrierung; laeuft bei `features.vectordb: true` ODER `features.are: true` — siehe Branch-Modellierung unten)
   - `branch_vectordb_enabled` -> `cp_10a_concept_context_properties`
   - `branch_sonarqube_enabled` -> `cp_10d_sonarqube_availability_and_conformance`
   - `cp_11_git_hooks_and_claude`
   - `branch_vectordb_enabled` (zweiter Branch nach CP11) -> `cp_10b_concept_validation_hook`
   - `branch_are_enabled` (nach CP10) -> `cp_10c_are_scope_validation`
   - `cp_12_verify_registration`

   **Abhaengigkeits-/Reihenfolge-Modellierung (FK-50 §50.3, normativ — die Knoten-Reihenfolge bildet die deklarierten CP-Abhaengigkeiten ab):**
   - **CP10 vor CP10a/CP10b/CP10c:** CP10a haengt von CP10 ab (`...50...md:402`), CP10c haengt von CP5 **und** CP10/ARE-MCP ab (`...50...md:431`). CP10 ist deshalb **ein gemeinsamer Knoten** und registriert den Story-Knowledge-Base-MCP-Server bei `features.vectordb: true` **und** — fail-closed-unabhaengig von VectorDB — den **ARE-MCP-Server bei `features.are: true`** (`...50...md:383`; FK-03 verlangt `are.mcp_server` ausschliesslich an `features.are`, nicht an `features.vectordb`, `03_konfig...md:343`). CP10 ist damit selbst kein reiner VectorDB-Branch-Kind mehr, sondern laeuft, sobald *eines* der beiden Features aktiv ist; bei `vectordb: false UND are: false` -> `SKIPPED`/`reason="vectordb_disabled"` (kein MCP-Server zu registrieren). So ist CP10c (`features.are: true`) garantiert ein registrierter ARE-MCP-Server vorgelagert.
   - **CP10b nach CP11:** CP10b (Concept-Validation-Hook-Dispatching) haengt von CP11 ab, weil die Git-Hooks erst konfiguriert sein muessen (`...50...md:416`). CP10b ist deshalb **nach** `cp_11_git_hooks_and_claude` modelliert: CP11 erstellt/konfiguriert das Hook-Substrat (`core.hooksPath`, `tools/hooks/`-Skelett), CP10b registriert anschliessend die pfadbasierte Concept-Dispatching-Logik in den bereits existierenden Hook. Der `branch_vectordb_enabled`-Branch wird dafuer zweistufig modelliert (CP10a vor CP11, CP10b nach CP11) — beide nur bei `features.vectordb: true`.
2. **Step-Handler je Checkpoint** mit `CheckpointResult`-Rueckgabe (bestehender Typ). Bestehende CP5/CP7/CP8/CP10d werden in Handler ueberfuehrt; die **fehlenden** CP werden ergaenzt:
   - **CP1** Python-Paketcheck (`import agentkit; assert agentkit.__version__`).
   - **CP2** GitHub-Repo via `gh repo view {owner}/{repo} --json name`.
   - **CP3 / CP4** reservierte No-op-`step`-Knoten (§50.3.1, §50.3 CP3/CP4 „entfaellt"): keine Aktion, deterministischer `CheckpointResult` (`SKIPPED`, `reason="reserved"`), nur zur Nummernstabilitaet.
   - **CP6** Profilermittlung als echter Checkpoint mit `CheckpointResult` (statt nur interner `_resolve_skill_profile`, `runner.py:674`).
   - **CP8 (vollstaendig, §50.3 CP8 + §50.5)** Skill-Links ueber `Skills.bind_skill(...)` **und** Erhalt/Transfer der Prompt-Bundle-Bindung ueber `PromptRuntime.update_binding(bundle_id, version)` (`prompt_runtime/runtime.py:206`). Beide Bindungswege sind Teil von CP8 (FK-50 §50.3 CP8 / §50.5).
   - **CP9** Hook-Registrierung ueber `Governance.register_hooks(hook_definitions)` (`governance/runner.py:193`) statt statischem Settings-Deploy.
   - **CP10** MCP-Server-Registrierung als **gemeinsame Vorbedingung** fuer CP10a/CP10b (VectorDB) und CP10c (ARE): registriert den Story-Knowledge-Base-MCP-Server bei `features.vectordb: true` und den **ARE-MCP-Server bei `features.are: true`** — letzteres unabhaengig von VectorDB, weil FK-03 `are.mcp_server` ausschliesslich an `features.are` bindet (`03_konfig...md:343`) und CP10c die CP10-ARE-MCP-Registrierung als Abhaengigkeit voraussetzt (`...50...md:431`). Result-Mapping: registriert/aktualisiert -> `CREATED`/`UPDATED`; beide Features aus -> `SKIPPED`/`reason="vectordb_disabled"` (kein Server zu registrieren). **CP10a** ConceptContext-Properties + Erstindizierung (nur `features.vectordb: true`, haengt von CP10 ab, `...50...md:402`); **CP10b** Concept-Validation-Hook (nur `features.vectordb: true`, **nach CP11 modelliert**, weil CP10b die konfigurierten Git-Hooks aus CP11 voraussetzt, `...50...md:416`).
   - **CP10c (§50.3 CP10c, nur bei `features.are: true`; Abhaengigkeit: CP5 + CP10/ARE-MCP, `...50...md:431`)** ARE-Scope-Validierung. CP10c laeuft erst, nachdem CP10 den ARE-MCP-Server bei `features.are: true` registriert hat (Knoten-Reihenfolge bildet diese Abhaengigkeit ab); fehlt der ARE-MCP-Server als harte Vorbedingung, ist das fail-closed ein `FAILED`. Prueft `are_scope` an allen Code-Repos in `repositories[]` und vollstaendige `are.module_scope_map`-Eintraege; erkennt Deltas (nur neue/unmapped Items); interaktiver Modus (nummerierte Auswahl aus ARE-Scopes) bzw. agentischer Modus (Rueckgabe `PENDING_SELECTION` mit Metadaten, der orchestrierende Agent ruft `resolve_pending_scope_mapping()` auf). Result-Mapping: fehlende Mappings im agentischen Modus -> `CheckpointResult` status `SKIPPED` mit `reason="pending_selection"` (kein FAILED, kein Status-Neologismus — die fachliche `PENDING_SELECTION`-Metainfo reist in `detail`/Handler-Payload mit); aufgeloeste/bereits gemappte Items -> `UPDATED`/`PASS`; idempotenter Re-Lauf bei vollstaendigem Mapping -> `SKIPPED`/`PASS`.
   - **CP11** `core.hooksPath`-Setzung (`git config core.hooksPath tools/hooks/`) + CLAUDE.md-Skelett (nur bei Erstinstallation, nie ueberschrieben).
   - **CP12** read-only Gesamtverifikation aller vorherigen Checkpoints.
3. **Vier Ausfuehrungsmodi (§50.2)** ueber ein typisiertes `execution_mode`-Enum:
   - **Erstregistrierung:** Checkpoint-Folge vollstaendig durchlaufen.
   - **Idempotenter Re-Lauf:** bereits erfuellte Checkpoints -> `SKIPPED`/`PASS`, Digest-Delta -> `UPDATED`; ueber **alle** CP, nicht nur CP7.
   - **Dry-Run (`execution_mode=dry_run`):** mutiert garantiert nichts (keine Dateien, kein Backend-State, keine Bindungen). **Dry-Run-Result-Contract pro CP:** der Handler meldet den *geplanten* Statuswert, den der echte Register-Lauf erzeugen wuerde (`CREATED` fuer „wuerde anlegen", `UPDATED` fuer „wuerde aktualisieren", `PASS` fuer „bereits erfuellt", `SKIPPED` fuer nicht-anwendbar mit dem gleichen `reason` wie im Register-Lauf, z. B. `vectordb_disabled`/`not_applicable`/`reserved`); zusaetzlich traegt jeder Dry-Run-`CheckpointResult` in `detail` die Plan-Markierung und im `reason` (bei `CREATED`/`UPDATED`) den stabilen Plan-Token `planned_no_mutation`, damit ein Konsument „geplant, nicht ausgefuehrt" hart von einem realen Mutationsergebnis unterscheiden kann.
   - **Verify (`execution_mode=verify`):** read-only, keine Mutation, liefert `CheckpointResults` (CP12-aequivalent ueber den Gesamtflow).
4. **CLI-Boundary-Controls** `agentkit register-project` und `agentkit verify-project` (`cli/main.py`-Subkommandos), die die Engine im jeweiligen Modus anstossen.
5. **Tests:** Flow-Knoten-Struktur (alle Knoten-IDs aus 2.1 als Knoten vorhanden, branch-Knoten je Feature), Dry-Run mutiert nichts (Dateisystem/State-Snapshot vor/nach identisch) und liefert den Dry-Run-Result-Contract aus 2.1.3, Verify ist read-only, idempotenter Re-Lauf -> `SKIPPED`/`UPDATED`, jeder Checkpoint liefert das korrekte `CheckpointResult` (PASS/CREATED/UPDATED/SKIPPED/FAILED inkl. Pflicht-`reason` bei SKIP/FAIL), CP2 fail-closed bei fehlendem Repo, CP3/CP4 liefern deterministisch `SKIPPED`/`reason="reserved"`, CP8 ruft `PromptRuntime.update_binding`, CP9 ruft `register_hooks`, CP10c (fehlendes Mapping -> `pending_selection`; aufgeloestes Mapping -> `UPDATED`/`PASS`; idempotenter Skip), **CP-Reihenfolge-Invarianten:** CP10 vor CP10a/CP10c, CP10b nach CP11 (Kanten-Assertion auf der Flow-Struktur); CP10 registriert den ARE-MCP-Server in einem ARE-only-Profil (`features.are: true`, `vectordb: false`) und liefert `SKIPPED`/`reason="vectordb_disabled"`, wenn beide Features aus sind.

### 2.2 Out of Scope (mit Owner)
- **Upgrade/Migration + CustomizationFootprint** (FK-51) — **AG3-089** (baut auf dieser Checkpoint-Engine auf).
- **Config-Modell-Vollausbau / `config_version` / Feature-Matrix** (FK-03/FK-90) — **AG3-070**. Diese Story **konsumiert** das Config-Modell (inkl. `features.are`/`features.vectordb`/`sonarqube`-Stanza); sie definiert es nicht.
- **Sonar/CI-Preflight-Checkpoints** (CP10d / AG3-056) — bestehend; nur in die Flow-Engine eingehaengt, nicht neu gebaut.
- **Concept-Validation-Git-Hook-Skripte** unter `tools/hooks/` — ausserhalb `src/agentkit/`; CP10b verdrahtet nur die Registrierung, nicht das Skript selbst.
- **ARE-Scope-Quelle (ARE-API `/dimensions/scope`) und `resolve_pending_scope_mapping()`-Produzent im ARE-BC** — CP10c **konsumiert** die ARE-Scope-Liste und gibt im agentischen Modus `PENDING_SELECTION` zurueck; der ARE-Vollausbau (vier Dock-Points, `load_are_bundle`) ist **AG3-077** (FK-40). CP10c baut nicht den ARE-BC.

## 3. Akzeptanzkriterien
1. Der Installer ist als `FlowDefinition(level=COMPONENT, owner="Installer")` modelliert; jeder Checkpoint ist ein `step`-Knoten. **Strukturell pruefbar (nicht Grep-Wortlaut):** `install_agentkit` ist entweder entfernt oder eine **duenne Fassade**, die ausschliesslich an `CheckpointEngine.run(...)` delegiert und keine Checkpoint-Reihenfolge mehr selbst imperativ verdrahtet; Test: der Flow wird ueber die Engine ausgefuehrt und die Fassade enthaelt keine CP-Orchestrierungslogik (Delegation belegt).
2. `branch`-Knoten existieren fuer vectordb/are/sonarqube-Feature-Entscheidungen und routen korrekt (Test pro Branch beide Zweige); der `branch_vectordb_enabled`-Branch ist zweistufig (CP10a vor CP11, CP10b nach CP11) und beide Stufen routen nur bei `features.vectordb: true`.
3. Alle in §2.1.1 gelisteten Knoten-IDs (`cp_01_package_check` .. `cp_12_verify_registration` inkl. `cp_03_reserved`, `cp_04_reserved`, `cp_10a_concept_context_properties`, `cp_10b_concept_validation_hook`, `cp_10c_are_scope_validation`, `cp_10d_sonarqube_availability_and_conformance`) existieren als Knoten und liefern ein `CheckpointResult` (Test je CP, inkl. Pflicht-`reason` bei SKIP/FAIL).
4. CP2 ist fail-closed bei nicht erreichbarem/nicht existentem GitHub-Repo (`gh repo view`) -> `FAILED` (Negativtest).
5. CP3/CP4 sind reservierte No-op-Knoten und liefern deterministisch `SKIPPED` mit `reason="reserved"` (Test).
6. CP8 bindet Skill-Links (`Skills.bind_skill`) **und** erhaelt/transferiert die Prompt-Bundle-Bindung ueber `PromptRuntime.update_binding` (Test: beide Aufrufe belegt).
7. CP9 registriert Hooks ueber `Governance.register_hooks` (`governance/runner.py:193`) (Test: Aufruf belegt).
8. CP10c (`features.are: true`) validiert ARE-Scope: fehlendes Mapping -> `CheckpointResult` `SKIPPED`/`reason="pending_selection"` im agentischen Modus mit `PENDING_SELECTION`-Metadaten; aufgeloestes/vollstaendiges Mapping -> `UPDATED`/`PASS`; idempotenter Re-Lauf bei vollstaendigem Mapping -> `SKIPPED`/`PASS` (drei Tests). Bei `features.are: false` ist CP10c `SKIPPED`/`reason="are_disabled"`.
9. **CP-Abhaengigkeits-Reihenfolge (FK-50 §50.3) ist in der Flow-Struktur durchgesetzt (Test je Kante):** (a) `cp_10_mcp_registration` liegt **vor** `cp_10a_concept_context_properties` und `cp_10c_are_scope_validation`; bei `features.are: true` ist der ARE-MCP-Server aus CP10 registriert, bevor CP10c laeuft (`...50...md:431`). (b) `cp_10b_concept_validation_hook` liegt **nach** `cp_11_git_hooks_and_claude` (`...50...md:416`). (c) CP10 laeuft bei `features.vectordb: true` ODER `features.are: true`, und liefert `SKIPPED`/`reason="vectordb_disabled"`, wenn beide Features aus sind (Test: ARE-only-Profil registriert den ARE-MCP-Server in CP10 ohne VectorDB).
10. CP10 mutiert in `register`-Mode die **Ziel-Projekt-`.mcp.json`** (MCP-Server-Eintrag — Story-Knowledge-Base bei vectordb, ARE-MCP bei are), in `dry_run`/`verify` jedoch garantiert nicht (Test: Ziel-`.mcp.json` unveraendert in dry_run/verify). Die AK3-Repo-eigene `.mcp.json` wird nie angefasst (siehe §6).
11. `execution_mode=dry_run` fuehrt keinerlei Mutation aus (Dateisystem/State unveraendert), liefert aber den Dry-Run-Result-Contract aus §2.1.3 (geplanter Statuswert + `reason`-Token `planned_no_mutation` bei `CREATED`/`UPDATED`, Plan-Markierung in `detail`) (Test).
12. `execution_mode=verify` ist read-only und liefert `CheckpointResults`; idempotenter Re-Lauf liefert `SKIPPED`/`UPDATED` statt erneutem `CREATE` (Tests).
13. `agentkit register-project` und `agentkit verify-project` sind als CLI-Subkommandos registriert und stossen die Engine im korrekten Modus an (Test).
14. **Pflichtbefehle gruen:** pytest unit/integration/contract (in Chunks, `-n0`); mypy default + `--platform linux`; ruff; vier Konzept-Gates; Coverage >= 85 %.

## 4. Definition of Done
- AK 1–14 erfuellt; giftige Codex-Review PASS; (Implementierung/Commit erst nach Execution-Plan-Freigabe — diese Story wird zunaechst nur autorisiert/reviewt).

## 5. Guardrail-Referenzen
- **KEINE MONOLITHISCHE WORKFLOW-DATEI:** der imperative `install_agentkit`-Block wird durch die fachlich geschnittene Flow-Engine ersetzt; eine verbleibende `install_agentkit`-Fassade delegiert nur — Kern-Zielbild von v3 gegen v2-God-Files.
- **FAIL-CLOSED:** CP2/CP-Preconditions blockieren (`FAILED`) bei verletzten Vorbedingungen; Verify und Dry-Run mutieren nie.
- **FIX-THE-MODEL / SINGLE SOURCE OF TRUTH:** bestehende Flow-DSL und `CheckpointResult`/`CheckpointStatus` wiederverwenden; keine zweite Checkpoint-Mechanik, kein neues Status-Wort (NOT_APPLICABLE = `SKIPPED`/`not_applicable`; PENDING_SELECTION = `SKIPPED`/`pending_selection` + Metadaten). Hooks ueber `register_hooks`, nicht ueber zweiten Settings-Schreibweg.
- **TYPISIERT STATT STRINGS:** `execution_mode`-Enum, Checkpoint-Knoten typisiert, kein String-Flag-Schaltwerk.
- **ARCH-55:** Knoten-/Modus-/CLI-/`reason`-Token englisch.
- **ZERO DEBT:** alle CP (CP1..CP12 inkl. reservierter CP3/CP4 und Sub-CP 10a/10b/10c/10d) real als Knoten; kein „CP spaeter".

## 6. Hinweise fuer den Sub-Agent
- Read T:/codebase/claude-agentkit3/CLAUDE.md first — all project rules apply to you.
- **Nicht** eine neue Flow-Engine bauen — `src/agentkit/process/language/` (FlowDefinition/NodeKind/builder/recovery) ist die DSL; Installer = `level=COMPONENT`-Instanz davon.
- Bestehende CP5/CP7/CP8/CP10d-Logik aus `runner.py` in Step-Handler **ueberfuehren** (Verhalten erhalten), nicht parallel neu schreiben; `CheckpointResult`/`CheckpointStatus` aus `installer/registration.py` weiterverwenden.
- CP9: der Wechsel von statischem Settings-Deploy zu `Governance.register_hooks` (`governance/runner.py:193`) ist eine bewusste Korrektur (§50.3) — sicherstellen, dass das deployte Verhalten aequivalent bleibt.
- **CP-Reihenfolge ist normativ (FK-50 §50.3):** CP10 (gemeinsame MCP-Registrierung) muss **vor** CP10a/CP10b/CP10c liegen, und CP10b **nach** CP11 (`...50...md:402/416/431`). CP10 laeuft, sobald `features.vectordb: true` **oder** `features.are: true` (ARE-MCP-Server nur an `features.are`, FK-03 `03_konfig...md:343`); der `branch_vectordb_enabled`-Branch ist zweistufig (CP10a vor CP11, CP10b nach CP11). Nicht CP10 unter einen reinen VectorDB-Branch klemmen — sonst fehlt CP10c im ARE-only-Profil der ARE-MCP-Server.
- Dry-Run/Verify duerfen **garantiert** nichts mutieren — das ist testbar (Dateisystem/State-Snapshot vor/nach).
- **`.mcp.json`-Klarstellung:** CP10 schreibt die **Ziel-Projekt-`.mcp.json`** im `register`-Mode (FK-50 §50.3 CP10) — das ist In-Scope. Die **AK3-Repo-eigene `.mcp.json`** im Repo-Root (Dev-MCP-Konfiguration dieses Repos) wird **nie** angefasst. Kein Widerspruch: zwei verschiedene Dateien (deployte Ziel-Datei vs. AK3-eigene Dev-Datei). In `dry_run`/`verify` bleibt auch die Ziel-`.mcp.json` unveraendert.
- AK2 NICHT veraendern. **Kein Commit** ohne expliziten Auftrag.
- „done" nur mit Beleg: Diff-Zusammenfassung, gruene Pflichtbefehle, Test-Namen (Flow-Struktur inkl. CP3/CP4/CP10c, Dry-Run-No-Mutation + Dry-Run-Result-Contract, Verify-read-only, CP2-fail-closed, CP8-update_binding, CP9-register_hooks, CP10c-pending_selection).

---

## Globale Akzeptanzkriterien (verbindlich)

Zusaetzlich zu den obigen Akzeptanzkriterien gelten die **globalen Akzeptanzkriterien**
aus `stories/_GLOBAL_ACCEPTANCE.md` (Single Source of Truth):

- **GAC-1:** `scripts/ci/check_architecture_conformance.py` laeuft mit **0 Errors**
  (Exit 0, fail-closed) — `PYTHONPATH=src .venv\Scripts\python scripts/ci/check_architecture_conformance.py`.
- **GAC-2:** Die Architektur-Guardrails `guardrails/architecture-guardrails.md`
  (ARCH-NN) werden eingehalten; Konflikt = hart stoppen und melden.
