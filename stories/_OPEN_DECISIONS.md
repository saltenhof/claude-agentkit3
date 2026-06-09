# Offene Klärungs-/Entscheidungspunkte (Decision Register)

**Zweck.** Sammel- und Entscheidungsdokument für alle offenen Punkte, die während
der Wave-0-Umsetzung (AG3-057..105, Codex auf `main`) als No-Owner-Lücken,
Konzept-↔-Code-Widersprüche oder Scope-Fragen aufgetaucht sind. Hier werden die
**Entscheidungen dokumentiert**; die **Überführung in die Konzepte** (`concept/`)
erfolgt anschließend kontrolliert über den Konzept-Approval-Flow
(Codex absegnen → Edit → Codex re-review → GAC-1 grün), nie als stiller Edit.

**Status-Werte:** OFFEN · ENTSCHIEDEN · ÜBERFÜHRT (im Konzept nachgezogen) · ERLEDIGT (im Code umgesetzt).

**Quellen:** `var/concept-gap-analysis/_CROSS_STORY_PREREQS.md` + Befunde der laufenden Codex-Umsetzungen.

---

## A. Konzeptionelle Richtungsentscheidungen (PO/Konzept-Input nötig)

### D1 — `PhaseStatus`: 5 normierte vs. 7 reale Werte
- **Kontext:** FK-39 §39.2.1 normiert 5 Werte (`IN_PROGRESS`/`COMPLETED`/`FAILED`/`ESCALATED`/`PAUSED`); der Code trägt 7 (zusätzlich `PENDING`, `BLOCKED`), produktiv genutzt in 4 Engine-Modulen (composition_root, control_plane/dispatch, pipeline_engine/runner, engine). AG3-059 hat `status` typisiert, die Wertemenge bewusst nicht verändert.
- **Optionen:** **A** = Konzept an Realität anpassen (FK-39 nimmt `PENDING`/`BLOCKED` auf; doc-only, kein Code-Risiko). **B** = Code auf 5 Werte reduzieren (breite, riskante Zustandsmaschinen-Änderung, eigenes Code-Cut-Item).
- **Empfehlung:** **A** (Fix-the-Model: Konzept an validierte Laufzeit angleichen).
- **Entscheidung:** _TBD_
- **Ziel-Konzept:** FK-39 §39.2.1 (doc-only).
- **Status:** OFFEN

---

## B. No-Owner-Lücken — neues Cut-Item (AG3-106+) oder Owner-Zuweisung nötig

### D2 — `harness-integration`-BC + FK-76 PostToolOutcome-Adapter + §76.8 Port-Surface
- **Kontext:** Von AG3-080 (PostToolOutcome-Befüllung Claude/Codex → exit_code/stderr) und AG3-104 CP2 (`harness_integration`-Package + FK-76 §76.8). Ohne Adapter bleibt der Worker-Health-`hook_conflict`-Beitrag aus echten Commit-Failures 0. KEIN Owner.
- **Empfehlung:** neues Cut-Item AG3-106 „harness-integration BC + PostTool-Outcome-Adapter".
- **Entscheidung:** _TBD_ · **Ziel-Konzept:** FK-76 · **Status:** OFFEN

### D3 — Runtime-Execution-Purge-Port (FK-53 §53.7.5)
- **Kontext:** Von AG3-071. Kanonischer Purge für FlowExecution/NodeExecutionLedger/Attempt/Override/GuardDecision/PhaseState am `phase_state_store`-Owner. Existiert nicht; AG3-071 (Reset, Welle 4) konsumiert fail-closed. KEIN Owner.
- **Empfehlung:** neues Cut-Item vor Welle 4.
- **Entscheidung:** _TBD_ · **Ziel-Konzept:** FK-53 · **Status:** OFFEN

### D4 — FK-35 Eskalationsmechanik
- **Kontext:** Von AG3-097. Typisierter `escalation_class`/`infra_unavailable`-Phase-State-Carrier + PAUSED/Resume-Wiring. AG3-059-Fieldset deckt es nicht; FK-25 §25.5.4 delegiert an FK-35. KEIN Owner.
- **Empfehlung:** neues Cut-Item.
- **Entscheidung:** _TBD_ · **Ziel-Konzept:** FK-35 · **Status:** OFFEN

### D5 — FK-30 `*_send`-Send-Count-Hook
- **Kontext:** Von AG3-097. Real-Time-11th-send-Block über `HookEvent.operation` (kennt kein `llm_send`). AG3-086 deckt budget/skill_usage/prompt-integrity/CCAG, nicht `*_send`. KEIN Owner.
- **Empfehlung:** neues Cut-Item oder Scope-Zuweisung an AG3-086.
- **Entscheidung:** _TBD_ · **Ziel-Konzept:** FK-30 · **Status:** OFFEN

### D6 — story_metrics `check_ref` + `ProjectionFilter` + Outcome-Population
- **Kontext:** Von AG3-078 (CP2/CP3/CP4). `story_metrics`-Schema `check_ref`+Outcome-Spalten (FK-69 §69.8, closure); `ProjectionFilter.check_ref`/`since_days` (telemetry); Outcome-Population aus echten verify/closure-Runs (nahe AG3-079). KEIN Owner.
- **Empfehlung:** ein gebündeltes Cut-Item (closure+telemetry).
- **Entscheidung:** _TBD_ · **Ziel-Konzept:** FK-69 / telemetry-and-events · **Status:** OFFEN

### D7 — Login-Pause
- **Kontext:** Von AG3-065. `PauseReason`-Enum-Erweiterung (FK-39 §39.2.2) + Phase-Runner-Pause-Wiring für FK-11 §11.2.3 Login-Fehler. KEIN Owner.
- **Empfehlung:** kleines Cut-Item.
- **Entscheidung:** _TBD_ · **Ziel-Konzept:** FK-39/FK-11 · **Status:** OFFEN

### D8 — Operator-Service-Gaps (für Operator-CLI, Welle 5)
- **Kontext:** Von AG3-076. reset-escalation-Service, integrity-override-Service, PID/TTL-stale-lock-Detection, lock-listing-Read-Repository. KEIN Owner.
- **Empfehlung:** Cut-Item vor Welle 5 (AG3-076 konsumiert).
- **Entscheidung:** _TBD_ · **Ziel-Konzept:** FK-45 · **Status:** OFFEN

### D9 — Dashboard Live-Read-Port + Catch-up-Materialization
- **Kontext:** Von AG3-084/082. `/api/live/stories` projekt-skopierter Runtime-Live-Read (execution_events/flow_executions); RefreshWorker-Catch-up-Fill braucht AG3-083-Spalten. KEIN Owner (nicht AG3-081).
- **Empfehlung:** Cut-Item vor Welle 5 (Dashboard).
- **Entscheidung:** _TBD_ · **Ziel-Konzept:** telemetry/runtime-schema · **Status:** OFFEN

### D10 — Task-Management-BFF-Adapter + Task-Read-Models
- **Kontext:** Von AG3-105. AG3-090s 8 BC-http-Module enthalten kein `task_management`; AG3-091 listet keine Task-Read-Models. AG3-096 baut den Task-BC, aber nicht die BFF-Anbindung. KEIN Owner für die BFF-Seite.
- **Empfehlung:** Scope-Zuweisung an AG3-091 (Read-Models) + ein BFF-http-Modul; vor AG3-105.
- **Entscheidung:** _TBD_ · **Ziel-Konzept:** FK-72/FK-91 · **Status:** OFFEN

### D11 — WorktreeManager-Konsolidierung
- **Kontext:** Von AG3-104 CP1. Soll-Owner `story_context_manager` (bc-cut-decisions.md:278). KEIN Backlog-Owner.
- **Empfehlung:** Cut-Item oder Scope an story_context_manager.
- **Entscheidung:** _TBD_ · **Ziel-Konzept:** bc-cut-decisions · **Status:** OFFEN

### D12 — concept/research-Subcheck-Bodies
- **Kontext:** Von AG3-064. Nur die aggregierenden Registry-Stages gebaut; die Subcheck-Bodies (`concept.structure/completeness/sparring/vectordb`, `research.structure/sources/assessment`, FK-33 §33.9) fehlen. Owner laut Story „AG3-078 bzw. dedizierte Check-Story" — uneindeutig.
- **Empfehlung:** Owner verbindlich festlegen (AG3-078 erweitern vs. neues Cut-Item).
- **Entscheidung:** _TBD_ · **Ziel-Konzept:** FK-33 §33.9 · **Status:** OFFEN

### D13 — SonarQube-Baseline-Hash-Feld (FK-73 §73.6)
- **Kontext:** Von AG3-104 CP3. Gehört zu `project-management` (NICHT AG3-070 = project-config). KEIN Backlog-Owner.
- **Empfehlung:** Scope an project-management-Story / Cut-Item.
- **Entscheidung:** _TBD_ · **Ziel-Konzept:** FK-73 · **Status:** OFFEN

### D14 — slugify-Konvention
- **Kontext:** Von AG3-104 CP4. AG3-068 enumeriert sie nicht. KEIN Owner.
- **Empfehlung:** AG3-068-Scope-Erweiterung oder kleine Convention-Story.
- **Entscheidung:** _TBD_ · **Ziel-Konzept:** FK-21/Convention · **Status:** OFFEN

### D15 — AG3-038-Folge-Gap (`schema_version`-Seed/Writer + `sync_state`-Cursor)
- **Kontext:** Von AG3-082. AG3-038 ist `completed` → Folge-Gap. KEIN aktiver Owner.
- **Empfehlung:** kleines Folge-Cut-Item.
- **Entscheidung:** _TBD_ · **Ziel-Konzept:** FK-62 · **Status:** OFFEN

---

## C. Owner-Scope-Erweiterungen (Owner existiert — nur AC/Scope erweitern; geringe Entscheidungslast)

| ID | Punkt | Owner-Story | Quelle | Status |
|---|---|---|---|---|
| E1 | `sonarqube.accept_frequency_fc_threshold` (Validierung+Default) | AG3-070 | AG3-078 CP1 | OFFEN |
| E2 | Design-Token-Modell **+** `get_design_tokens`-HTTP-Endpoint | AG3-092 | AG3-084 | OFFEN |
| E3 | FK-68 §68.2.2 `review_divergence`-Payload-Zeile (`score/routing` → FK-34-Feldset) | AG3-103 | AG3-066 | OFFEN |
| E4 | Deutsche Failure-Corpus-Enum/CHECK-Werte → ARCH-55 (englisch) | AG3-078 | AG3-104 CP5 | OFFEN |

---

## D. Doc-only Konzept-Drifts (→ doc-only-Stories 101/102/103/104, via Konzept-Approval-Flow)

| ID | Drift | Ziel-Story | Quelle | Status |
|---|---|---|---|---|
| X1 | FK-39 §39.2.1/§39.2.2 `pause_reason` Case-Drift (UPPERCASE im Code) | 101/103 | AG3-059 | OFFEN |
| X2 | FK-45 §45.2 Prosa „→ ESCALATED" vs. realem Pre-Dispatch-`rejected` | 102/104 | AG3-060 | OFFEN |
| X3 | FK-36: `agentkit.prompting.compose`→`prompt_runtime` | 104 | AG3-075 | OFFEN |
| X4 | FK-36: DD-09 vs. §36.10/§36.11 (alter Deny-Stand) | 104 | AG3-075 | OFFEN |
| X5 | FK-36: `project_key` fehlt in §36.5.2 (Spawn-Spec) + §36.9.4 (Marker) | 104 | AG3-075 | OFFEN |
| X6 | FK-22 §22.4b raw-write-Pseudocode vs. ArtifactManager-Pfad | 102 | AG3-077 | OFFEN |
| X7 | FK-15 §15.5.2 Hook-Pfad `tools/hooks/pre-commit` vs. real `.githooks/pre-commit` | 102 | AG3-087 | OFFEN |
| X8 | FK-18 Tabellen-Namensdrift (`node_execution_ledgers`/`attempts`/`artifact_envelopes`) | 102 | AG3-087 | OFFEN |
| X9 | FK-15 §15.4.3 Branch-Guard-als-Secret-Owner-Drift | 102 | AG3-087 | OFFEN |
| X10 | FK-93 worker_health-Defaults (Konzept-Abgleich; FK-49 ist Schema-Owner) | 103 | AG3-080 | OFFEN |
| X11 | AG3-099-Wording: `EventTypeId`→`EventType`, „integrity-dim8"-Token raus, Emitter-Split | 099-Body | AG3-081 | OFFEN |

---

## E. Index-Korrekturen (`_STORY_INDEX.md` / Metadaten — Orchestrator-intern, mechanisch)

| ID | Korrektur | Quelle | Status |
|---|---|---|---|
| I1 | AG3-084-Zeile: FK-64 + `get_design_tokens` entfernen (→ AG3-092); `/api/live/stories` umhängen | CP-C | OFFEN |
| I2 | AG3-082↔083 Dependency-Richtung (082 depends_on 083; self-dep-Tippfehler) | 083-r3 | OFFEN |
| I3 | AG3-099 „acht" → „neun fehlende + migrierte dependency_edge = zehn" Planning-Schema-Families | 099-r1 | OFFEN |
| I4 | AG3-081 Directory/Index „integrity-dim8" → Telemetry-Evidence-Block (FK-68 §68.4) angleichen | 076/081 | OFFEN |

---

## Bereits entschieden (Historie)

- **KPI-Routen-Root = Singular `/kpi/{dimension}`** (PO 2026-06-08). ÜBERFÜHRT: AG3-090 umgesetzt; FK-72-§72.8.2-Prosa-Nachzug in AG3-103-Scope. Kein offener Prerequisite mehr.
- **Globale Akzeptanzkriterien** GAC-1 (Arch-Checker 0 Errors) + GAC-2 (`guardrails/architecture-guardrails.md`) — `stories/_GLOBAL_ACCEPTANCE.md`.
- **Branch-Integration / Arbeitsmodus:** ausschließlich Codex, ausschließlich `main` (keine Branches/Worktrees), 10-Min-Poll. (PO-Vorgabe; ersetzt die frühere Branch+PR-Politik.)

---

## Vorgehen bei Überführung in die Konzepte
1. Entscheidung hier eintragen (`Entscheidung:` füllen, Status → ENTSCHIEDEN).
2. Konzept-Edit über den Approval-Flow: Codex absegnen (write=false) → Edit `concept/...` → Codex re-review → GAC-1/Concept-Gates grün → push. Status → ÜBERFÜHRT.
3. Code-Umsetzung (falls nötig) als reguläre Story/Cut-Item (AG3-106+) im üblichen Codex-auf-main-Loop. Status → ERLEDIGT.
