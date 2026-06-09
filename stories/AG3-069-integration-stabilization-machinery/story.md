# AG3-069: Integration-Stabilization-Maschinerie (Manifest/Approval/Budget/Gate/Overlay)

**Typ:** Implementation
**Groesse:** L
**Bounded Context:** `integration-stabilization` / E2E-Vertrag (BC, Vertragsachse `implementation_contract`). Die Laufzeit-Maschinerie hinter dem zweiten Vertragstyp neben `story_type`: attestiertes Scope-Manifest, hartes Stabilisierungsbudget, Verify-Stage `stability_gate` und Guard-Overlay gegen die `seam_allowlist`.
**Quell-Konzepte (autoritativ):**
- `FK-05 §5.2` — zweite Vertragsachse `implementation_contract` (standard / integration_stabilization) als persistente Achse neben `story_type`.
- `FK-05 §5.5/§5.5.2/§5.5.4/§5.5.5` — `integration_scope_manifest` (vollstaendiger Pflicht-Feldsatz §5.5.2) + attestierter `manifest_approval_record` (§5.5.4: Hash, Version, `project_key+story_id+run_id`-Bindung); ohne Approval-Record fail-closed blockiert; Repo-Set-/Worktree-Grenze (§5.5.5).
- `FK-05 §5.6` — Exploration immer Pflicht fuer integration_stabilization; Setup darf nicht auf execution routen, bis das Manifest freigegeben ist.
- `FK-05 §5.7/§5.13` — Reklassifikationspfad mit Snapshot-Grenze und **keiner** Rueckwaerts-Legalisierung vorbestehender Cross-Scope-Deltas (frische `evidence_epoch`, Quarantaene).
- `FK-05 §5.9` — `stabilization_budget` als hartes Steuerungsobjekt (Schleifen, Surfaces, Contract-Changes, **Regressionen pro Verify-Zyklus**); live-blockierend im Hook-/Capability-Layer.
- `FK-05 §5.10/§5.12` — `stability_gate` als Verify-Profil-Gate; `seam_allowlist` + engeres Guard-Overlay; `declared_surfaces_only` als deterministischer Schicht-1-/Guard-Check.
- `FK-05 §5.11` — harte Closure-Precondition fuer integration_stabilization.
- `FK-05 §5.14` — technische Materialisierung: Schemas, Hook-Materialisierung, Guard-Overlay, Verify-Registry-Eintrag, **eigene Telemetrie** fuer Manifest-Freigabe, Undeclared-Surface und Budget-Erschoepfung.
- `FK-37 §37.1.3` — die vier integration_stabilization-Pflichtpruefungen im QA-Subflow-/Closure-Pfad: `integration_target_matrix_passed`, `declared_surfaces_only`, `stabilization_budget_not_exhausted`, `stability_gate`.
- Formal-Spec `concept/formal-spec/integration-stabilization/` (entities/commands/events/invariants/scenarios/state-machine) — normative Soll-Vorlage; Events `:27` und Invarianten `:26-66` sind der bindende Telemetrie-/Invarianten-Anker.

---

## 1. Kontext / Ist-Zustand (belegt)

Die Vertragsachse ist als Enum modelliert, die gesamte nachgelagerte Vertragsdurchsetzung fehlt:

- `ImplementationContract`-Enum existiert (`story_context_manager/types.py:24-26`: `STANDARD`, `INTEGRATION_STABILIZATION`) und wird in der `StoryTypeProfile`-Vertrags-Matrix referenziert (`allowed_implementation_contracts`, `types.py:37`/`:50-54`). Damit ist nur die **Typ-Spitze** da; alle Pflichten §5.5–§5.14 fehlen (Gap FK-05 §5.2 UNVOLLSTAENDIG).
- Grep `integration_scope_manifest`/`manifest_approval` ueber `src/agentkit/**/*.py` → **0 Treffer**; in `types.py` existiert ausschliesslich der Enum-Wert `integration_stabilization` (`types.py:26`), keine Manifest-/Approval-Record-Klasse, keine Freigabe-Logik (Gap FK-05 §5.5/§5.5.2/§5.5.4 FEHLT).
- Grep `stability_gate`/`stabilization_budget`/`seam_allowlist` ueber `src/agentkit/**/*.py` → 0 Treffer; kein Verify-Stage `stability_gate` in der `verify_system/stage_registry/data.py`-Stage-Tabelle (`data.py:61-157` enthaelt nur die Layer-1-Stages, kein `stability_gate`); kein Guard-Overlay fuer Worker-Writes (Gap FK-05 §5.9/§5.10/§5.12/§5.14 FEHLT).
- Kein Routing-Sonderpfad fuer `integration_stabilization` in `story_context_manager/routing_rules.py`; `get_phases_for_story`/`should_run_exploration` (`routing_rules.py:23-42`) werten nur `mode`/`execution_route` aus, kennen `implementation_contract` nicht (Gap FK-05 §5.6 FEHLT).
- Es existiert eine vollstaendige `concept/formal-spec/integration-stabilization/` (entities/commands/events/invariants/scenarios/state-machine) als normative Soll-Vorlage — die Python-Runtime ist nachzuziehen.
- Anknuepfung: Die Stage-Registry wird in **AG3-064** zum typisierten Vollausbau (`StageDefinition` mit `kind`/`trust_class`/`producer`/`override_policy`) gebracht; `stability_gate` wird als Stage-Eintrag genau dort eingehaengt (depends_on AG3-064). Der `declared_surfaces_only`-Check ist ein Layer-1-Structural-Check (`verify_system/structural/`). Der Context-Sufficiency-Builder ist **AG3-067**-Owner; der integration_stabilization-Kontextanteil (FK-37 §37.1.3) dockt an dessen Builder an (depends_on AG3-067).

## 2. Scope

### 2.1 In Scope
1. **`integration_scope_manifest`** als typisiertes Pflichtartefakt (Pydantic, frozen) mit dem **vollstaendigen FK-05 §5.5.2-Mindestfeldsatz**: `project_key`, `story_id`, `implementation_contract`, `target_seams`, `allowed_repos_paths`, `integration_targets`, `allowed_contract_changes`, `stabilization_budget`, `out_of_contract_examples` — plus Version und Inhalts-Hash. Producer + Envelope nach Artefakt-Registry (FK-71). **Repo-Set-Grenze (§5.5.5):** das Manifest darf nur Pfade innerhalb der bereits gebundenen `worktree_roots` / participating Repos autorisieren; es darf keine neuen Repos/Worktrees einfuehren — Verstoss ist fail-closed.
2. **`manifest_approval_record`** als typisiertes Attestierungs-Artefakt (§5.5.4): verweist auf Manifest-Hash + Version, gebunden an `(project_key, story_id, run_id)`; ohne freigegebenen Approval-Record ist produktive Integrationsarbeit **fail-closed blockiert** an jedem der Blockierpunkte aus §2.3. Bindungs-Drift (Hash/Version/Run stimmt nicht) blockiert.
3. **`stabilization_budget`** als hartes Steuerungsobjekt (typisierte Caps, FK-05 §5.9): Stabilisierungsschleifen, neue Surfaces/Pfadgruppen, deklarierte Contract-Changes **und zulaessige Regressionen zwischen zwei Verify-Zyklen**. Budgetueberschreitung blockiert live im Hook-/Capability-Layer (nicht nur als Report), bevor der naechste produktive Stabilisierungsschritt ausserhalb des Restbudgets laeuft.
4. **`stability_gate`** als Verify-Stage-Eintrag (eingehaengt in die AG3-064-Registry): prueft erreichte `integration_targets`, `undeclared_surface` und Budget-Einhaltung; FAIL bei undeklarierter Surface oder Budgetbruch.
5. **`seam_allowlist` + Guard-Overlay**: deklarierte Seams werden materialisiert (`.agent-guard/seam_allowlist.json` o. konzept-konformer Pfad, FK-05 §5.14); ein PreToolUse-Guard-Overlay blockiert Worker-Writes ausserhalb der allowlist. Kein neues God-Guard-Modul — Overlay an die bestehende Guard-Kette (`governance/guards/`) andocken.
6. **`declared_surfaces_only` als deterministischer Schicht-1-Check** (`verify_system/structural/`): vergleicht tatsaechlich beruehrte Surfaces gegen Manifest-Deklaration, Seam-Allowlist und aktives Repo-Set (FK-05 §5.10); undeklarierte Beruehrung → FAIL. Kein LLM-Urteil.
7. **Exploration-Pflicht-Routing** (FK-05 §5.6): fuer `implementation_contract=integration_stabilization` erzwingt das Setup-Routing Exploration; ein Routen nach execution ohne freigegebenes Manifest ist verboten (`routing_rules`-Sonderpfad, typisiert, der `implementation_contract` mitliest).
8. **Closure-Precondition** (FK-05 §5.11): Closure fuer `integration_stabilization` darf nur laufen, wenn `stability_gate = PASS`, alle deklarierten `integration_targets` erreicht sind, keine ungeklaerte Manifest-Verletzung offen ist und kein Replan-/Split-Bedarf besteht. Verletzung blockiert fail-closed das Closure-Gate.
9. **Reklassifikations-/No-Retroactive-Legalization-Pfad** (FK-05 §5.7/§5.13): wird eine `standard`-Story offiziell nach `integration_stabilization` reklassifiziert, werden vorbestehende Cross-Scope-Deltas **nicht** rueckwirkend legalisiert; der regulaere Vertrag beginnt erst am genehmigten Manifest-Snapshot. Materialisiert sich in frischer `evidence_epoch` + manifestgebundenem Capability-Overlay; vor-Snapshot-Deltas werden quarantainiert (Invariante `reclassification_may_not_legalize_pre_manifest_cross_scope_delta`).
10. **Eigene Telemetrie** (FK-05 §5.14, formal-spec `events.md:27`): Events/Producer fuer Manifest-Freigabe (`integration_manifest_approved`), Undeclared-Surface (`undeclared_surface_detected`) und Budget-Erschoepfung (`stabilization_budget_exhausted`) — plus die uebrigen integration-stabilization-Events aus der Formal-Spec, soweit von dieser Story erzeugt (`stability_gate_passed`). Producer gem. Formal-Spec (`guard_system`/`pipeline_deterministic`).
11. **Die vier FK-37 §37.1.3-Vertrags-Pflichtpruefungen** als benannte, einzeln testbare, fail-closed Checks: `integration_target_matrix_passed`, `declared_surfaces_only`, `stabilization_budget_not_exhausted`, `stability_gate`. Schichtzuordnung gem. FK-37 §37.1.3: `declared_surfaces_only` → Schicht 1; `stabilization_budget_not_exhausted` → primaer Hook-/Capability-Enforcement, im QA-Subflow nur auditierend; `integration_target_matrix_passed`/`stability_gate` → QA-Subflow-/Closure-Preconditions. Zusaetzlich sind Manifest-Approval-Vorbedingung und Bindungs-Integritaet (`project_key+story_id+run_id`-Match) als eigene fail-closed Vorbedingungen modelliert — **zusaetzlich** zu den vier §37.1.3-Checks, nicht als deren Ersatz.
12. **Negativpfade an den Phasengrenzen**: kein Approval → blockiert; Bindungs-/Hash-Mismatch → blockiert; undeklarierte Surface → FAIL; Budgetbruch (inkl. Regression-Cap) → blockiert; Manifest mit Pfad ausserhalb `worktree_roots`/participating Repos → blockiert; execution-Routing ohne freigegebenes Manifest → blockiert; Closure ohne erfuellte §5.11-Precondition → blockiert; Reklassifikation, die vor-Snapshot-Deltas legalisieren will → blockiert/quarantainiert.

### 2.2 Out of Scope (mit Owner)
- **Stage-Registry-Grundgeruest** (`StageDefinition` mit `kind`/`trust_class`/`producer`/`override_policy`, Layer 2/3/4) — **AG3-064**; `stability_gate` haengt sich nur ein.
- **`config_version`/Feature-Matrix/`policy`-Stanza** des Config-Modells — **AG3-070** (depends_on); diese Story konsumiert Config, baut sie nicht neu.
- **Context-Sufficiency-Builder** (FK-37 Kern, `ContextSufficiencyBuilder`/`SufficiencyLevel`/Section-aware Packing) — **AG3-067** (depends_on); hier wird nur der integration_stabilization-spezifische Kontextanteil (§37.1.3) an dessen Builder angedockt, kein zweiter Builder gebaut.
- **Story-Exit bei erschoepftem Stabilisierungsbudget** (`exit_class`, `integration_budget_exhausted`, kontrollierter Rueckfall) — **AG3-073** (Story-Exit); hier nur das Budget-Blockieren und der Replan-/Decomposition-Auslauf, nicht der offizielle Exit-Pfad.
- **`terminal_state`-Achse + `exit_class`-Constraints** — **AG3-074** (FK-59); diese Story setzt nur die fail-closed Blockierung, nicht die konsolidierte Ergebnisachse.
- **Standard-Story-Split** (`StorySplitService`, Split-Plan, Dependency-Rebinding) — **AG3-072**; AG3-072 §2.2 ordnet die **enge Reklassifikation** auf `integration_stabilization` ausdruecklich dieser Story (AG3-069) zu. Der Reklassifikationspfad (AC §2.1.9) ist damit **in-story**; der allgemeine Split bleibt AG3-072.

### 2.3 Blockierpunkte (Operationalisierung "produktive Integrationsarbeit blockiert")
"Blockiert" ist an jedem dieser konkreten Punkte fail-closed (FK-05 §5.5.1/§5.9/§5.11/§5.12):
- **Worker-Spawn** (§5.5.1): kein Worker-Spawn fuer `integration_stabilization` ohne freigegebenen Approval-Record.
- **Setup/Routing** (§5.6): keine execution-Route ohne freigegebenes Manifest.
- **PreToolUse-Write-Guard** (§5.12): Worker-Writes ausserhalb `seam_allowlist`/`allowed_repos_paths` blockiert.
- **Capability-/Hook-Layer** (§5.9): naechster produktiver Stabilisierungsschritt ausserhalb des Restbudgets blockiert live.
- **Closure-Precondition** (§5.11): Closure ohne `stability_gate=PASS` + erreichte Ziele + keine offene Manifest-Verletzung blockiert.

## 3. Akzeptanzkriterien
1. `integration_scope_manifest` ist ein typisiertes, frozen Pydantic-Artefakt mit dem **vollstaendigen FK-05 §5.5.2-Feldsatz** (`project_key`, `story_id`, `implementation_contract`, `target_seams`, `allowed_repos_paths`, `integration_targets`, `allowed_contract_changes`, `stabilization_budget`, `out_of_contract_examples`) plus Version und Hash; `manifest_approval_record` ist frozen mit Hash/Version/`(project_key, story_id, run_id)`-Bindung. Beide mit Producer/Envelope (Test je Pflichtfeld).
2. Ohne freigegebenen `manifest_approval_record` ist produktive Integrationsarbeit an allen §2.3-Blockierpunkten blockiert (Negativtest); ein Bindungs-/Hash-/Run-Mismatch blockiert ebenfalls (Negativtest).
3. Ein Manifest, das Pfade ausserhalb der gebundenen `worktree_roots`/participating Repos autorisiert (oder neue Repos/Worktrees einfuehrt), wird fail-closed abgelehnt (Negativtest, FK-05 §5.5.5 / Invariante `manifest_may_not_expand_repo_set`).
4. `stabilization_budget` blockiert live bei Ueberschreitung **jeder** Cap (Stabilisierungsschleifen, Surfaces/Pfadgruppen, Contract-Changes, **Regressionen pro Verify-Zyklus**) im Hook-/Capability-Layer (ein Test pro Cap, inkl. Regression-Cap).
5. `stability_gate` ist als Verify-Stage in der AG3-064-Registry registriert und FAILt bei `undeclared_surface`, nicht erreichten `integration_targets` oder Budgetbruch (Test).
6. `declared_surfaces_only` ist ein deterministischer Schicht-1-/Guard-Check gegen Diff, Manifest, Seam-Allowlist und aktives Repo-Set; beruehrte vs. deklarierte Surfaces werden verglichen, undeklarierte Beruehrung → FAIL; kein LLM-Pfad (Test).
7. Das `seam_allowlist`-Guard-Overlay blockiert Worker-Writes ausserhalb der deklarierten Seams (Negativtest), ohne die bestehenden Guards zu duplizieren.
8. Setup-Routing fuer `integration_stabilization` erzwingt Exploration und verbietet execution-Routing ohne freigegebenes Manifest (Negativtest am Phasengrenz-Routing; der Routing-Pfad liest `implementation_contract`).
9. **Closure-Precondition (FK-05 §5.11):** Closure fuer `integration_stabilization` laeuft nur bei `stability_gate=PASS` + allen erreichten `integration_targets` + keiner offenen Manifest-Verletzung + keinem Replan-/Split-Bedarf; jede Verletzung blockiert das Closure-Gate (Negativtest pro Bedingung).
10. **Reklassifikation (FK-05 §5.7/§5.13):** ein Reklassifikationspfad standard→integration_stabilization legalisiert vorbestehende Cross-Scope-Deltas **nicht** rueckwirkend; er erzeugt eine frische `evidence_epoch` + manifestgebundenes Overlay und quarantainiert vor-Snapshot-Deltas (Test: vor-Snapshot-Delta bleibt quarantainiert/nicht legalisiert).
11. **Telemetrie (FK-05 §5.14):** dedizierte Events/Producer fuer Manifest-Freigabe (`integration_manifest_approved`), Undeclared-Surface (`undeclared_surface_detected`), Budget-Erschoepfung (`stabilization_budget_exhausted`) und `stability_gate_passed` werden emittiert; Producer entsprechen der Formal-Spec (`events.md`) (Test pro Event).
12. **Die vier FK-37 §37.1.3-Pflichtpruefungen** (`integration_target_matrix_passed`, `declared_surfaces_only`, `stabilization_budget_not_exhausted`, `stability_gate`) sind benannt, einzeln testbar und fail-closed; ein PASS der normalen QA-Subflow-Schichten allein reicht nicht fuer Closure (Test). Manifest-Approval-Vorbedingung und Bindungs-Integritaet sind **zusaetzliche** benannte fail-closed Vorbedingungen.
13. Alle neuen Bezeichner/Enum-Werte/Wire-Keys/DB-Spalten/Dateinamen englisch (ARCH-55).
14. **Pflichtbefehle gruen:** pytest unit/integration/contract (in Chunks, `-n0`); mypy default + `--platform linux`; ruff; vier Konzept-Gates; Coverage ≥ 85 %.

## 4. Definition of Done
- AK 1–14 erfuellt; giftige Codex-Review PASS; Implementierung/Commit erst nach Execution-Plan-Freigabe — diese Story wird zunaechst nur autorisiert/reviewt.

## 5. Guardrail-Referenzen
- **FAIL CLOSED:** fehlendes/abweichendes Manifest-Approval, Bindungs-Mismatch, undeklarierte Surface, Budgetbruch (inkl. Regression-Cap), Repo-Set-Verletzung, execution ohne Manifest, verletzte Closure-Precondition und rueckwirkende Reklassifikations-Legalisierung blockieren — keine weichere Regel, kein Bypass.
- **FIX THE MODEL / SINGLE SOURCE OF TRUTH:** `implementation_contract` bleibt die eine persistente Vertragsachse; Manifest/Budget/Allowlist sind ihre typisierten Owner, keine Parallel-Steuerwahrheit.
- **TYPISIERT STATT STRINGS:** Manifest/Approval/Budget/Gate als Pydantic-Modelle und Stage-Eintrag, kein String-/Flag-Geflecht; `integration_stabilization`-Routing typisiert.
- **NO ERROR BYPASSING:** das Guard-Overlay haengt an der bestehenden Kette, kein Umgehungspfad.
- **ARCH-55:** alle neuen Identifier englisch.

## 6. Hinweise fuer den Sub-Agent
- Read T:/codebase/claude-agentkit3/CLAUDE.md first — all project rules apply to you.
- `concept/formal-spec/integration-stabilization/` ist die normative Soll-Vorlage (entities/commands/events/invariants/scenarios/state-machine) — Modelle/Invarianten/Telemetrie-Events daran ausrichten. Die Telemetrie-Events stehen in `events.md`, die zu erzwingenden Invarianten in `invariants.md` (u. a. `manifest_may_not_expand_repo_set`, `reclassification_may_not_legalize_pre_manifest_cross_scope_delta`, `closure_requires_stability_gate_pass`, `budget_exhaustion_blocks_live_capability`, `declared_surfaces_only_is_deterministic`).
- `stability_gate` NICHT als eigenes Registry-Konstrukt bauen: in die `StageDefinition`-Registry aus **AG3-064** einhaengen (depends_on). Wenn AG3-064 noch nicht verfuegbar ist: Schnittstelle skizzieren und Reihenfolgekonflikt melden, nicht doppelt modellieren.
- Den integration_stabilization-Kontextanteil (FK-37 §37.1.3) an den `ContextSufficiencyBuilder` aus **AG3-067** andocken (depends_on), keinen zweiten Builder bauen. Wenn AG3-067 noch nicht verfuegbar ist: gegen dessen Builder-Schnittstelle programmieren und Reihenfolgekonflikt melden.
- `seam_allowlist`-Overlay an `governance/guards/` andocken, kein neuer God-Guard. Materialisierungspfad konzept-konform (kein `_temp/`-Source-of-Truth, FK-10).
- Der Reklassifikationspfad gehoert AG3-069 (AG3-072 §2.2 ordnet die enge Reklassifikation ausdruecklich hierher) — den Standard-Split NICHT mitbauen (AG3-072).
- AK2 NICHT veraendern. `.mcp.json` NICHT anfassen. **Kein Commit** ohne expliziten Auftrag.
- „done" nur mit Beleg: Diff-Zusammenfassung, gruene Pflichtbefehle, Test-Namen der vier FK-37-Pflichtpruefungen + Approval-/Bindungs-/Repo-Set-/Budget-/Closure-/Reklassifikations-/Telemetrie-Negativpfade.

---

## Globale Akzeptanzkriterien (verbindlich)

Zusaetzlich zu den obigen Akzeptanzkriterien gelten die **globalen Akzeptanzkriterien**
aus `stories/_GLOBAL_ACCEPTANCE.md` (Single Source of Truth):

- **GAC-1:** `scripts/ci/check_architecture_conformance.py` laeuft mit **0 Errors**
  (Exit 0, fail-closed) — `PYTHONPATH=src .venv\Scripts\python scripts/ci/check_architecture_conformance.py`.
- **GAC-2:** Die Architektur-Guardrails `guardrails/architecture-guardrails.md`
  (ARCH-NN) werden eingehalten; Konflikt = hart stoppen und melden.
