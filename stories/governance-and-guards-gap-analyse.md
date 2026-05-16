# governance-and-guards — GAP-Analyse

> Generiert von einem dedizierten Sonnet-Sub-Agent (Stand 2026-05-16).

## Header

| Feld | Wert |
|---|---|
| BC-ID | `governance-and-guards` |
| Display-Name | `Governance und Guards` |
| Analyse-Datum | `2026-05-16` |
| Konzept-Quellen (autoritativ) | `DK-03, DK-09, FK-22, FK-30, FK-31, FK-35, FK-42, FK-55, formal.guard-system.*, formal.governance-observation.*, formal.integrity-gate.*, formal.principal-capabilities.*, formal.setup-preflight.*` |
| Codebase-Hauptpfade | `src/agentkit/governance/`, `src/agentkit/guard_system/` |

## 1. Executive Summary

Der BC `governance-and-guards` zeigt eine erhebliche Spreizung zwischen Konzept und Implementierung. Die basale Hook-Infrastruktur (BranchGuard, ScopeGuard, ArtifactGuard, Harness-Adapter Claude Code / Codex) und die CCAG-Schicht sind gut ausgebaut und mit Unit-Tests versehen. Dagegen fehlen zentrale Konzeptbestandteile vollstaendig: die GovernanceObserver-Schicht (Anomalieerkennung, Rolling-Window, LLM-Adjudication), das vollstaendige Principal- und Capability-Modell nach FK-55 (neun Principals, Pfadklassen, harte Capability-Matrix, Freeze-Overlay), der SetupPreflightGate mit allen zehn Checks nach FK-22 sowie die normativen Top-Surfaces `Governance.register_hooks()` und `Governance.deactivate_locks()`. Zusaetzlich existiert ein Namensraum-Drift (doppeltes Paket `guard_system` neben dem konzeptionell normativen `governance.guard_system`), der in `bc-cut-decisions.md` als offener Refactor-Punkt verzeichnet ist. Das IntegrityGate ist partiell vorhanden, weicht jedoch in seinen Dimensionen und Pflicht-Artefakt-Checks erheblich vom Konzept ab.

| Kategorie | Anzahl |
|---|---|
| A — Nicht umgesetzt | 7 |
| B — Teilweise umgesetzt | 5 |
| C — Drift / Fehler | 5 |

## 2. Konzept-Soll (Kurzfassung)

- **9 Guard-Typen als PreToolUse-Hooks** (Branch-Guard, Orchestrator-Guard, QA-Artefakt-Schutz, QA-Agent-Guard, Adversarial-Guard, Self-Protection-Guard, Story-Creation-Guard, Budget-Guard, Worker-Health-Monitor) plus CCAG als letztem Hook — `FK-30 §30.5`, `FK-31`
- **Capability-Enforcement-Pipeline in fester Reihenfolge**: Principal aufloesen, Operation-Class, Path-Class, harte Matrix, Freeze-Overlay, offizielle Servicepfade, Modusregel, erst dann CCAG — `FK-30 §30.2.6`, `FK-55 §55.10.3`
- **9 kanonische Principals** mit typisierten Capability-Profilen; kein Principal darf aus Prompt-Inhalt entstehen — `FK-55 §55.3`, `FK-55 §55.3a`
- **8 Pfadklassen und 6 Operationsklassen** fuer deterministische Pfadklassifikation — `FK-55 §55.4`, `FK-55 §55.5`
- **Conflict-Freeze-Overlay** (doppelt materialisiert: State-Backend + lokaler Export) fuer HARD-STOP-Faelle — `FK-55 §55.8`, `FK-31 §31.2.7`
- **10 Preflight-Checks** fail-closed; vollstaendige PreflightResult-Struktur mit allen Checks — `FK-22 §22.3`
- **Guard-Aktivierung via Lock-Record + Project Edge Client** (Edge-Bundle-Publikation unter `_temp/governance/`) — `FK-22 §22.7`
- **Modus-Ermittlung (4 Trigger, REF-032)**: Concept-Paths, Architecture Impact, New Structures, Concept Quality — `FK-22 §22.8`
- **GovernanceObserver**: Sensorik (Hook + Phasen-Signale), Rolling-Window-Risikoscore, Incident-Kandidat, LLM-Adjudication (StructuredEvaluator), deterministische Massnahmen — `FK-35 §35.3`, `DK-03 §3.7`
- **IntegrityGate mit 3 Pflicht-Artefakten und 8 Dimensionen** vor Merge; als Python-Funktion, nicht als Hook — `FK-35 §35.2`, `DK-03 §3.6`
- **Eskalationsmechanismus**: einheitliches ESCALATED/PAUSED-Verhalten bei 13 definierten Triggern — `FK-35 §35.4`, `DK-03 §3.9`
- **Worker-Health-Monitor**: Scoring-Engine (PostToolUse), Interventions-Gate (PreToolUse), LLM-Assessment-Sidecar — `DK-03 §3.8`, `FK-30 §30.10`
- **CCAG als eigenstaendige Top-Level-Komponente** (nicht Teil des GuardSystem): YAML-Regeln, Permission-Request-/Lease-Modell, sessionuebergreifende Persistenz, modus-scharfe Entscheidung — `FK-42`, `DK-09 §9.1`
- **Top-Surfaces** `Governance.register_hooks(hook_definitions)` (fuer Installer) und `Governance.deactivate_locks(story_id)` (fuer Closure) — `FK-30 §30.3.1`, `FK-30 §30.6.0`
- **Betriebsmodus-Aufloesung** aus lokalem Edge-Bundle (fail-closed bei fehlendem Bundle) — `FK-30 §30.2.7`
- **Git Pre-Commit / Post-Commit Hooks** fuer Concept-Validierung und Concept-Build — `FK-30 §30.5.3`, `FK-30 §30.5.4a`
- **Permission-Request- und Lease-Modell** mit TTL, lazy Expiry und Fingerprint-Bindung — `FK-55 §55.9a`, `FK-42 §42.4`
- **Governance-Selbstschutz** (Self-Protection-Guard): immer aktiv, schuetzt Hook-Settings, CCAG-Symlinks, Lock-Records, Edge-Bundles — `FK-30 §30.5.4`

## 3. Code-Stand (Ist-Bild)

- `src/agentkit/governance/__init__.py` — Re-Export-Namespace; exponiert BranchGuard, ArtifactGuard, ScopeGuard, IntegrityGate, GuardRunner, Governance, GuardVerdict
- `src/agentkit/governance/guard_evaluation.py:HookEvent` — Harness-neutrales Event-Modell (Pydantic, frozen), Felder: operation, operation_args, freshness_class, cwd, session_id, principal_kind
- `src/agentkit/governance/guard_evaluation.py:evaluate_pre_tool_use` — Dispatcht an GuardRunner mit BranchGuard + optional ScopeGuard + ArtifactGuard; kein vollstaendiges Capability-Modell
- `src/agentkit/governance/guards/branch_guard.py:BranchGuard` — Immer-aktive Regeln (Force-Push, Hard-Reset, Force-Delete), Story-Execution-Branch-Regeln (Checkout/Push/Rebase auf Main), Git-Internal-Pfadschutz; offizieller Allow-Pfad fuer agentkit-CLI-Befehle
- `src/agentkit/governance/guards/scope_guard.py:ScopeGuard` — Blockiert file_write/file_edit ausserhalb allowed_paths; nur aktiv wenn Pfade konfiguriert
- `src/agentkit/governance/guards/artifact_guard.py:ArtifactGuard` — QA-Artefakt-Schreibschutz fuer Sub-Agents
- `src/agentkit/governance/runner.py:GuardRunner` — Fail-closed, alle Guards laufen durch; sammelt vollstaendige Violation-Info
- `src/agentkit/governance/runner.py:Governance` — Harness-neutrale Top-Surface mit `run_hook(hook_id, event, phase, project_root)`; dispatcht auf evaluate_pre_tool_use oder CCAG
- `src/agentkit/governance/guard_system/records.py:StoryExecutionLockRecord` — Dataclass fuer Lock-Record-Struktur
- `src/agentkit/governance/guard_system/__init__.py` — Leere Boundary-Datei (kein Inhalt)
- `src/agentkit/governance/harness_adapters/claude_code.py` — Claude Code Adapter: mappt ClaudeCodeHookEvent auf HookEvent; CLI-Entrypoint `agentkit-hook-claude`
- `src/agentkit/governance/harness_adapters/codex/` — Codex Adapter: event_mapping.py, decision_mapping.py, cli.py
- `src/agentkit/governance/hookruntime.py` — Backward-Compat-Pfad (Kommentar in bc-cut-decisions.md: bleibt unveraendert bis HookRuntime-BC geschnitten wird)
- `src/agentkit/governance/integrity_gate/__init__.py:IntegrityGate` — Partiell: prueft phase_snapshots, structural_artifact, verify_decision, context_record, phase_state_record; fehlt: 8-Dimensionen-Schema, Pflicht-Artefakt-Vorstufe, Multi-LLM-Compliance, Timestamp-Kausalitaet, Adversarial-Nachweis, Preflight-Compliance
- `src/agentkit/governance/ccag/runtime.py:CcagPermissionRuntime` — Vollstaendige CCAG-Evaluation: Block-Regeln vor Allow-Regeln, modus-scharfe Permission-Request-Erzeugung, fail-open bei Exception
- `src/agentkit/governance/ccag/rules.py` — YAML-Regel-Lader
- `src/agentkit/governance/ccag/leases.py` — PermissionLeaseStore
- `src/agentkit/governance/ccag/requests.py:PermissionRequestStore` — SQLite-basierter Request-Store
- `src/agentkit/governance/ccag/cli.py` — CCAG CLI-Kommandos
- `src/agentkit/governance/monitoring/__init__.py` — Leere Datei (kein Inhalt; kein GovernanceObserver)
- `src/agentkit/governance/doc_fidelity/__init__.py` — Leere Datei
- `src/agentkit/governance/policies/__init__.py` — Leere Datei
- `src/agentkit/guard_system/` — Dupliziertes Paket mit eigenem BranchGuard, ScopeGuard, ArtifactGuard, IntegrityGate, GuardRunner (Drift-Punkt aus bc-cut-decisions.md Refactor-Nr. 5)
- `src/agentkit/pipeline/phases/setup/preflight.py:run_preflight` — Partiell: prueft story_exists, status_approved, dependencies; fehlen: no_execution_artifacts, no_active_runtime_residue, no_story_branch, no_stale_worktree, no_scope_overlap, no_competing_story_mode_active, story_attributes_consistent

## 4. GAP-Analyse

### 4.1 A — Nicht umgesetzt

| # | Thema | Konzept-Referenz | Anmerkung |
|---|---|---|---|
| A1 | GovernanceObserver (Anomalieerkennung, Rolling-Window, Incident-Kandidat, LLM-Adjudication, deterministische Massnahmen) | `FK-35 §35.3`, `DK-03 §3.7`, `formal.governance-observation.*` | `src/agentkit/governance/monitoring/__init__.py` ist leer; kein GovernanceObserver, kein Risikoscore, kein Cooldown-Mechanismus. Blocker fuer kontinuierliche Laufzeit-Governance. |
| A2 | Worker-Health-Monitor (Scoring-Engine, Interventions-Gate, LLM-Assessment-Sidecar, Hook-Commit-Failure-Klassifikation) | `DK-03 §3.8`, `FK-30 §30.10`, `FK-30 §30.5.1 health_monitor` | Kein `worker_health`-Modul vorhanden; Hook-Registrierung in runner.py setzt `health_monitor` als gueltigen Hook-ID, aber es existiert keine Implementierung dahinter. |
| A3 | Vollstaendiges Principal- und Capability-Modell (9 Principals, Pfadklassen, Operationsklassen, harte Capability-Matrix, Orchestrator-Capability-Grenzen) | `FK-55 §55.3`, `FK-55 §55.4`, `FK-55 §55.5`, `FK-55 §55.6`, `formal.principal-capabilities.*` | Die Capability-Enforcement-Pipeline nach FK-55 §55.10.3 (10-Schritt-Reihenfolge) ist nicht implementiert. `evaluate_pre_tool_use` kennt nur `principal_kind` (main/subagent), keine vollstaendige Principal-Typisierung (orchestrator, worker, qa_reader usw.). |
| A4 | Conflict-Freeze-Overlay (doppelte Materialisierung: State-Backend + lokaler Export; Wirkung auf Orchestrator-Mutationen) | `FK-55 §55.8`, `FK-31 §31.2.7` | Kein Freeze-Modell implementiert; kein `conflict_freeze`-Record, kein `freeze_version`-Export. |
| A5 | Top-Surfaces `Governance.register_hooks(hook_definitions)` und `Governance.deactivate_locks(story_id)` | `FK-30 §30.3.1`, `FK-30 §30.6.0` | `Governance.run_hook()` ist vorhanden, aber weder `register_hooks` noch `deactivate_locks` sind als Methoden der `Governance`-Klasse implementiert. |
| A6 | Self-Protection-Guard (Governance-Selbstschutz: schuetzt Hook-Settings, CCAG-Symlinks, Lock-Records, governance-Verzeichnis — immer aktiv) | `FK-30 §30.5.4`, `DK-03 §3.3 Nachweis` | Kein `self_protection`-Guard-Modul vorhanden. Hook-ID `self_protection_guard` ist in PRE_HOOK_IDS registriert, wird aber an `evaluate_pre_tool_use` weitergeleitet ohne eigene Guard-Logik. |
| A7 | Story-Erstellungs-Guard (blockiert direkte AK3-Story-Service-Mutationen am Skill vorbei — immer aktiv) | `FK-31 §31.5` | Kein `story_creation_guard`-Modul. Hook-ID `story_creation_guard` in PRE_HOOK_IDS, aber keine Implementierung hinter dem Dispatcher. |

### 4.2 B — Teilweise umgesetzt

| # | Thema | Code-Referenz | Konzept-Referenz | Was fehlt |
|---|---|---|---|---|
| B1 | Preflight-Checks (10 Checks, fail-closed, alle ausführen) | `src/agentkit/pipeline/phases/setup/preflight.py:run_preflight` | `FK-22 §22.3.1` | Nur story_exists, status_approved, dependencies_done implementiert. Fehlend: story_attributes_consistent, no_execution_artifacts, no_active_runtime_residue, no_story_branch, no_stale_worktree, no_scope_overlap, no_competing_story_mode_active (Checks 2, 5, 6, 7, 8, 9, 10). Cleanup-Hinweise bei Failure fehlen. |
| B2 | IntegrityGate (8 Dimensionen + 3 Pflicht-Artefakte als Vorstufe) | `src/agentkit/governance/integrity_gate/__init__.py:IntegrityGate` | `FK-35 §35.2.3`, `FK-35 §35.2.4` | Pflicht-Artefakt-Vorstufe (MISSING_STRUCTURAL, MISSING_DECISION, MISSING_CONTEXT als harter Blocker vor Dimensionspruefung) fehlt. Dimensionen 5 (LLM-Bewertungen), 6 (Adversarial), 7 (QA-Subflow-flow_end), 8 (Timestamp-Kausalitaet) fehlen. Preflight-Compliance-Guard (PREFLIGHT_MISSING, PREFLIGHT_NOT_COMPLIANT) fehlt. Multi-LLM-Compliance fehlt. Opake Fehlermeldung `GOVERNANCE VIOLATION DETECTED` nicht implementiert. |
| B3 | Modus-Ermittlung (4 Trigger REF-032) | `src/agentkit/pipeline/phases/setup/preflight.py` | `FK-22 §22.8` | Preflight ist partiell implementiert; Modus-Ermittlung (determine_mode mit 4 Triggern und VektorDB-Konflikt-Sonderfall) ist nicht in der Codebase auffindbar; FK-22 §22.8.1 zeigt Python-Pseudocode der noch nicht implementiert ist. |
| B4 | Orchestrator-Guard (Schutzzone 1 Codebase + Schutzzone 2 Content-Plane) | `src/agentkit/governance/guard_evaluation.py:_guards_for_state` | `FK-31 §31.2` | Kein dediziertes `orchestrator_guard`-Modul. Die vorhandene ScopeGuard-Logik schuetzt den Worker-Scope, nicht gezielt den Orchestrator. Orchestrator-Guard-Regelsatz (blocked_paths aus project.yaml, CONTENT_PLANE_FILES fest kodiert), Principal-Erkennung via is_subagent-Fallback, Schutzzone-2-Sperre fehlen vollstaendig. |
| B5 | CCAG-Capability-Integration: CCAG muss erst nach hartem Capability-Deny aufgerufen werden | `src/agentkit/governance/runner.py:run_hook`, `src/agentkit/governance/ccag/runtime.py:CcagPermissionRuntime` | `FK-30 §30.2.6`, `FK-42 §42.2.4`, `FK-55 §55.10.3` | CCAG evaluiert `evaluate_ccag` ohne vorgelagerte harte Capability-Matrix. Die normative Auswertungsreihenfolge (Principal -> Path-Class -> Matrix -> Freeze -> Servicepfade -> CCAG) ist nicht implementiert; CCAG kann damit noch harte Denies abmildern. |

### 4.3 C — Drift / Fehler

| # | Thema | Code-Referenz | Konzept-Referenz | Drift / Fehler |
|---|---|---|---|---|
| C1 | Namensraum-Duplikat: `guard_system` vs. `governance.guard_system` | `src/agentkit/guard_system/`, `src/agentkit/governance/guard_system/` | `concept/_meta/bc-cut-decisions.md §Refactor-Nr-5` | Zwei Pakete mit identischen Guard-Klassen (BranchGuard, ScopeGuard, ArtifactGuard, IntegrityGate, GuardRunner) — eines unter `agentkit.guard_system`, das andere unter `agentkit.governance.guard_system`. Konzept-Ziel ist `agentkit.governance.guard_system`. Refactor als offen verzeichnet, aber nicht vollzogen. Verletzt Single-Source-of-Truth. |
| C2 | `governance.monitoring` ist leere Huelse statt `governance.governance_observer` | `src/agentkit/governance/monitoring/__init__.py` | `concept/_meta/bc-cut-decisions.md §Refactor-Nr-6` | Konzept-Norm lautet `agentkit.governance.governance_observer`. Vorhandener Pfad ist `agentkit.governance.monitoring` und enthaelt keinen Inhalt. Weder Namensraum noch Implementierung stimmen. |
| C3 | `doc_fidelity` und `policies` als leere Pakete in `governance/` | `src/agentkit/governance/doc_fidelity/__init__.py`, `src/agentkit/governance/policies/__init__.py` | `concept/_meta/bc-cut-decisions.md §Refactor-Nr-2,3` | `agentkit.governance.doc_fidelity` und `agentkit.governance.policies` gehoeren laut bc-cut-decisions.md zu `verify-system` (ConformanceService, StageRegistry). Verzeichnisse sind unter `governance/` angelegt, was falsche BC-Zugehoerigkeit suggeriert. |
| C4 | IntegrityGate wertet Konzept- und Research-Stories identisch wie Implementation aus | `src/agentkit/governance/integrity_gate/__init__.py:_REQUIRED_PHASES` | `FK-35 §35.2.4 Dim-5`, `DK-03 §3.6` | `_REQUIRED_PHASES` schreibt fuer CONCEPT und RESEARCH dieselben Pflichtphasen ("setup", "implementation") wie fuer IMPLEMENTATION. Konzept: LLM-Review und Adversarial-Checks (Dim 5, 6) gelten nur fuer implementation/bugfix-Stories, nicht fuer Concept/Research. |
| C5 | `Governance.run_hook` dispatcht alle Pre-Hooks ausser CCAG pauschal auf `evaluate_pre_tool_use` | `src/agentkit/governance/runner.py:run_hook` | `FK-30 §30.3.3`, `FK-30 §30.5` | Alle Hook-IDs (branch_guard, orchestrator_guard, story_creation_guard, integrity_guard, qa_agent_guard, adversarial_guard, self_protection_guard, health_monitor) landen in demselben `evaluate_pre_tool_use`-Aufruf. Konzept schreibt dedizierte, sequentielle Guard-Module in normierter Reihenfolge vor. Derzeit keine differentielle Guard-Logik pro Hook-ID. |

## 5. Ableitungen / Empfehlungen

1. **Namensraum-Konsolidierung (`guard_system` -> `governance.guard_system`)**: Blocker fuer konzeptkonformen Zustand. `src/agentkit/guard_system/` entfernen und dessen Inhalte in `src/agentkit/governance/guard_system/` ueberführen. Alle Importe anpassen. Risiko: hohe Seiteneffekte; erfordert vollstaendige Test-Suite als Sicherheitsnetz.

2. **Principal-Capability-Modell (FK-55) implementieren**: Voraussetzung fuer Trust-Boundary-Enforcement. Ohne typisierte Principals und Pfadklassen-Klassifikation sind harte Guards umgehbar. Zuerst `operation_class`-Normalisierung und `path_class`-Klassifikation, dann Capability-Matrix, dann Freeze-Overlay. Blockiert: korrekte Orchestrator-Guard-Implementierung.

3. **Orchestrator-Guard und Self-Protection-Guard als eigenstaendige Module**: Beide sind immer aktiv oder story-gebunden und existieren nicht als Implementierung. Ohne Orchestrator-Guard ist Schutzzone 2 (Content-Plane) nicht durchgesetzt; Orchestrator kann `context.json` lesen.

4. **IntegrityGate auf 8 Dimensionen + Pflicht-Artefakt-Vorstufe erweitern**: Aktuell fehlen Dimensionen 5 (LLM-Review), 6 (Adversarial), 7 (QA-Subflow-flow_end), 8 (Timestamp-Kausalitaet) sowie der BB2-012-Defektschutz (Pflicht-Artefakt-Vorstufe). Das Gate laesst Closure-Faelle durch, die das Konzept als harte Blocker behandelt.

5. **Preflight-Checks 2, 5-10 implementieren**: Sieben der zehn Preflight-Checks fehlen. Besonders kritisch: no_scope_overlap (Parallele Stories) und no_competing_story_mode_active (Fast/Standard-Mode-Konflikt). Ohne diese kann Setup in einem konkurrierenden Zustand starten.

6. **GovernanceObserver implementieren**: Benoetigt Rolling-Window-Query auf execution_events, Incident-Kandidat-Erzeugung und LLM-Adjudication via StructuredEvaluator. Niedrigere Dringlichkeit als die obigen strukturellen Luecken, da GovernanceObserver auf vorhandene Telemetrie-Events aufbaut, die noch nicht vollstaendig emittiert werden.

7. **Top-Surfaces `Governance.register_hooks` und `Governance.deactivate_locks` hinzufuegen**: Ohne diese fehlt dem Installer und der Closure-Phase ein stabiler Vertragsendpunkt gemaess bc-cut-decisions.md. Mittlere Prioritaet, blockiert aber Installer-Refactor.

## 6. Suchstrategie & Quellen

- **Vollstaendig gelesen:**
  - `concept/domain-design/03-governance-und-guards.md`
  - `concept/domain-design/09-tools-und-skills.md`
  - `concept/technical-design/22_setup_preflight_worktree_guard_activation.md`
  - `concept/technical-design/30_hook_adapter_guard_enforcement.md`
  - `concept/technical-design/31_branch_guard_orchestrator_guard_artefaktschutz.md`
  - `concept/technical-design/35_integrity_gate_governance_beobachtung_eskalation.md`
  - `concept/technical-design/42_ccag_tool_governance_permission_runtime.md`
  - `concept/technical-design/55_principal_capability_model_story_scope_enforcement.md`
  - `concept/technical-design/_meta/domain-registry.yaml`
  - `stories/_gap-analyse-schema.md`
  - `CLAUDE.md`
- **Punktuell via Grep/Read:**
  - `concept/_meta/bc-cut-decisions.md` — Abschnitte zu governance-and-guards (Refactor-Nummern 5-8, IntegrityGate-BC-Entscheidung, SetupPreflightGate, Budget-Hook-Hybrid, GovernanceObserver-Sensor, Skill-Usage-Enforcement)
- **Code-Scan (Glob/Grep):**
  - Pattern `src/agentkit/governance/**/*.py`: vollstaendige Modulliste des governance-Pakets
  - Pattern `src/agentkit/guard_system/**/*.py`: Duplikat-Paket
  - Pattern `src/agentkit/**/*observer*.py`, `*principal*.py`, `*preflight*.py`: Pruefung auf fehlende Module
  - Grep `register_hooks|deactivate_locks|GovernanceObserver`: Bestätigung Abwesenheit
  - Glob `concept/formal-spec/{guard-system,governance-observation,integrity-gate,principal-capabilities,setup-preflight}/**`: Bestätigung Existenz aller formalen Specs
  - Read `src/agentkit/governance/guard_evaluation.py`, `runner.py`, `guards/branch_guard.py`, `guards/scope_guard.py`, `integrity_gate/__init__.py`, `ccag/runtime.py`, `guard_system/records.py`, `monitoring/__init__.py`, `doc_fidelity/__init__.py`, `policies/__init__.py`
  - Read `src/agentkit/pipeline/phases/setup/preflight.py`
