# AG3-034: Preflight-Checks 2/5-10 + IntegrityGate-9-Dimensionen (inkl. Dim 9 SONARQUBE_GREEN) + Setup-green-main-Precondition + Concept/Research-Drift fix

**Typ:** Implementation
**Groesse:** L
**Abhaengigkeiten:** AG3-021 (Enums), AG3-022 (Envelope), AG3-023 (ArtifactManager fuer Envelope-Pflichtfeld-Pruefung), AG3-032 (PathClassifier fuer Preflight-Checks), **AG3-052 (`sonarqube_gate`-Capability — Dim 9 + Setup-green-main KONSUMIEREN diese API, kein Neubau)**
**Quell-Konzepte (autoritativ, in dieser Reihenfolge):**
- `FK-22 §22.3` (10 Preflight-Checks fail-closed)
- `FK-22 §22.3.1` (Check-Definitionen)
- `FK-22 §22.4c` (SonarQube-main-Green-Vorbedingung — Setup-Aufruf der `sonarqube_gate`-Capability, fail-closed)
- `FK-35 §35.2` (IntegrityGate mit Pflicht-Artefakt-Vorstufe + Dimensionspruefung)
- `FK-35 §35.2.3` (Pflicht-Artefakt-Vorstufe)
- `FK-35 §35.2.4` (**NEUN** Artefakt-Dimensionen — kanonische Liste inkl. Dim 9 SonarQube-Green)
- `FK-35 §35.2.4a` (Dim 9 SonarQube-Green — Attestations-Verifikation, Applicability-Geltung)
- `FK-35 §35.4` (Eskalationsmechanismus)
- `FK-33 §33.6.3` (Green-Definition, commit-gebundene Attestation, 3-Punkt-Verankerung)
- `FK-33 §33.6.5` (3-Zustands-Applicability-Modell — Owner; NOT_APPLICABLE bei `available:false` ODER `mode:fast`)
- `DK-03 §3.6` (IntegrityGate-Domaene)
- `formal.setup-preflight.*`
- `formal.integrity-gate.*`
- `formal.deterministic-checks.*` (Applicability-Invarianten/State-Machine der Capability)
- `FK-71 §71.2` (Envelope-Pflichtfelder)

---

## 1. Kontext

THEME-006 aus `stories/_priorisierungsempfehlung.md`. Befunde:

- `governance-and-guards.B1`: Nur 3 von 10 Preflight-Checks implementiert (`story_exists`, `status_approved`, `dependencies_done`). Fehlen: `story_attributes_consistent`, `no_execution_artifacts`, `no_active_runtime_residue`, `no_story_branch`, `no_stale_worktree`, `no_scope_overlap`, `no_competing_story_mode_active`.
- `governance-and-guards.B2`: IntegrityGate prueft nur 4 der **neun** Dimensionen (FK-35 §35.2.4). Fehlen Dim 5 (LLM-Reviews), Dim 6 (Adversarial), Dim 7 (QA-Subflow-flow_end), Dim 8 (Timestamp-Kausalitaet), **Dim 9 (SonarQube-Green, FK-35 §35.2.4a)**. Pflicht-Artefakt-Vorstufe fehlt. Preflight-Compliance-Guard und Multi-LLM-Compliance fehlen.
- `governance-and-guards.C4`: IntegrityGate behandelt CONCEPT/RESEARCH wie IMPLEMENTATION — Tests fuer Dim 5/6 (und Dim 9) sollen nur fuer Implementation/Bugfix gelten.
- `artifacts.B4`: IntegrityGate prueft nur Existenz, keine Envelope-Pflichtfelder.
- **Setup-green-main (FK-22 §22.4c)**: codeproduzierende Stories duerfen nur auf einem fuer-sich-gruenen `main` aufsetzen; die fail-closed Vorbedingung fehlt heute im Preflight.
- **Dim 9 / green-main konsumieren AG3-052**: die `sonarqube_gate`-Capability ist mit AG3-052 gebaut und konsumierbar (commit-gebundene Attestation, Green-Definition, 3-Zustands-Applicability, Accepted-Ledger, Single-Match-Reconciler). AG3-034 RUFT diese API auf — es baut KEINE Gate-Mechanik nach (FK-22 §22.4c.1: "Setup ist nur Aufrufer, kein Owner der Gate-Logik"; FK-35 §35.2.4a: "verifiziert nur — vermisst nicht neu").

Diese Story stellt die zwei Gates vollstaendig auf den vollen Konzept-Stand her (9 Dimensionen + Setup-green-main-Precondition). Sie ist eigenstaendig pruefbar, weil jeder Preflight-Check und jede Integrity-Dimension einen klaren Eingangs-/Ausgangskontrakt hat.

> **Scope-Korrektur (Story-Record, keine stille Konzept-Unterlieferung):** Diese Story und der bereits gebaute Code (`integrity_gate/dimensions.py`) trugen den Titel/Schnitt „8 Dimensionen". FK-35 §35.2.4 ist normativ **neun**. Die fehlende neunte Dimension (`SONARQUBE_GREEN`/`SONAR_NOT_GREEN`) und die Setup-green-main-Vorbedingung werden hier nachgezogen. Die Dim-1-8-IDs/FAIL-Codes wurden auf die KANONISCHEN FK-35-§35.2.4-Namen angeglichen (Stefan-Entscheidung 2026-06-03; vormals abweichende Ist-Namen `MISSING_*`/`*_NACHWEIS`/`*_KAUSALITY` sind entfernt, kein Alias).

## 2. Scope

### 2.1 In Scope

#### 2.1.1 Preflight-Checks 2, 5-10 (FK-22 §22.3.1)

`src/agentkit/pipeline/phases/setup/preflight.py` wird auf 10 Checks erweitert:

| # | Check-ID | Bedeutung | Fail-Datenquelle |
|---|---|---|---|
| 1 | `story_exists` | bereits da | StoryService |
| 2 | `story_attributes_consistent` | NEU | StoryService (story_type/size/mode-Kombination) + PROFILES-Validierung |
| 3 | `status_approved` | bereits da | StoryService |
| 4 | `dependencies_done` | bereits da | StoryDependencyRepository |
| 5 | `no_execution_artifacts` | NEU | filesystem check: `_temp/stories/{story_id}/` ist leer |
| 6 | `no_active_runtime_residue` | NEU | State-Backend: keine offenen PhaseStates fuer story_id |
| 7 | `no_story_branch` | NEU | git ls-remote: kein `story/{story_id}` auf origin |
| 8 | `no_stale_worktree` | NEU | filesystem: kein `_worktrees/{story_id}` Verzeichnis (oder ist git-aufgeraeumt) |
| 9 | `no_scope_overlap` | NEU | StoryDependencyRepository: keine andere `IN_PROGRESS`-Story mit ueberlappenden `participating_repos` |
| 10 | `no_competing_story_mode_active` | NEU | `mode_lock`-Tabelle aus AG3-018 (falls implementiert) bzw. dieser Story (siehe 2.1.2) |

Jeder Check liefert `PreflightCheckResult`:

```python
class PreflightCheckResult(BaseModel):
    check_id: PreflightCheckId  # StrEnum
    status: PreflightStatus       # PASS | FAIL
    detail: str | None
    cleanup_hint: str | None    # FK-22 §22.3 fordert Cleanup-Hinweise bei FAIL
```

Aggregat `PreflightResult`:

```python
class PreflightResult(BaseModel):
    overall: PreflightStatus
    checks: list[PreflightCheckResult]
    failed_check_ids: list[PreflightCheckId]
```

Alle 10 Checks laufen IMMER (fail-closed, nicht abgebrochen beim ersten Fehler — Diagnose-Vollstaendigkeit, FK-22 §22.3).

#### 2.1.2 `mode_lock`-Tabelle und Check 10

`no_competing_story_mode_active` braucht den projektweiten `mode_lock` (FK-24 §24.3.3, story-lifecycle.A8). Dieser Mode-Lock wurde fuer AG3-018 (Fast-Modus) konzipiert; falls AG3-018 bereits die `mode_lock`-Tabelle gebaut hat, wird sie hier nur konsumiert. Falls noch nicht: diese Story legt die Tabelle minimal an.

Tabelle `project_mode_lock`:
- `project_key` (PK)
- `active_mode: StoryMode | None` (normativer Wertebereich `standard`, `fast`, oder `None`/idle — FK-24 §24.3.3; `execution`/`exploration` falten auf Projekt-Lock-Ebene in `standard`. Fruehere Schreibweise `{EXECUTION, EXPLORATION, FAST}` war Drift, hier korrigiert; reine Story-Record-Korrektur, keine AC-Aenderung.)
- `holder_count: int`
- `updated_at`

**Mode-Achse (Konzept-Nachschaerfung, konsistent mit AG3-052):** Die fast/standard-`mode`-Achse ist **entkoppelt** von `execution_route` (FK-24 §24.3.3). Die Story-`mode`-Achse liegt auf `StoryContext.mode` (`WireStoryMode.FAST` / standard), nicht auf der `execution_route`-Achse. Dieselbe Achse steuert die Sonar-Applicability (§2.1.2b, §2.1.3 Dim 9): `mode == fast` -> NOT_APPLICABLE_FAST. AG3-034 liest `mode` aus dem Story-/Mode-Lock-Pfad und gibt es an `resolve_for_context(..., fast=...)` der AG3-052-Capability weiter.

Check 10 logik: wenn Story-Mode != aktiver mode_lock-Mode und holder_count > 0 -> FAIL mit `cleanup_hint`. (Begruendung: aktive Standard-Stories blockieren Fast-Start; aktive Fast-Story blockiert Standard-Start. Siehe AG3-018-Story.)

Atomare Mode-Lock-Setzung beim Story-Start ist Aufgabe von AG3-018 bzw. Folge-Story; hier wird nur der Read-Pfad fuer Check 10 hergestellt.

#### 2.1.2b Setup-green-main-Precondition (FK-22 §22.4c) — konsumiert AG3-052

Vor der Worktree-Erstellung (§22.6, nach der Story-Typ-Weiche §22.5) prueft das Setup-Skript deterministisch und ohne LLM, ob der aktuelle `main` **fuer sich gruen** ist. Das ist der **erste der drei Lifecycle-Gate-Punkte** der `sonarqube_gate`-Capability (FK-33 §33.6.3, Punkt 1). AG3-034 ist hier **Aufrufer, nicht Owner** der Gate-Logik (FK-22 §22.4c.1).

**Applicability zuerst (FK-33 §33.6.5):** Die Vorbedingung wird nur ausgewertet, wenn der Gate-Punkt **APPLICABLE** ist:

| Applicability | Vorbedingung | Setup-Verhalten |
|---|---|---|
| `APPLICABLE` | `sonarqube.available == true` UND `mode != fast` UND `story_type ∈ {implementation, bugfix}` | main-Attestation lesen (QG per `analysisId`) + Revision-Match (`last_analyzed_revision == git main HEAD`). GREEN -> Setup laeuft weiter. RED/STALE/unerreichbar -> **Setup fail-closed verweigert** mit aktivem, schuldfreiem Cleanup-Vorschlag (§22.4c.3) |
| `NOT_APPLICABLE_UNAVAILABLE` | `sonarqube.available == false` (auch fuer codeproduzierende Projekte zulaessig) | **SKIP** (kein fail-closed) — Skip-Edge zu `worktrees_ready` |
| `NOT_APPLICABLE_FAST` | `mode == fast` | **Gate-Punkt entfaellt** — Skip-Edge zu `worktrees_ready` (Fast-Schuld) |
| (concept/research) | `story_type ∉ {implementation, bugfix}` | kein Worktree, kein Fachcode -> Vorbedingung entfaellt (§22.4c.1) |

**Fail-closed-Abgrenzung (zentrale Regel, FK-33 §33.6.5):** *bewusst-abwesend* (`available == false`) ≠ *kaputt* (`available == true`, aber Server/Branch-Plugin unerreichbar, QG rot, Attestation stale). Nur der KONFIGURIERT-aber-rot/stale/unerreichbar-Fall failt fail-closed.

**Konsumierte AG3-052-API:** `resolve_for_context(available=..., fast=..., story_type=...)` -> `SonarApplicability`; `build_sonar_gate_port_for_run(...)` (liefert bei APPLICABLE-aber-Koordinaten-fehlend einen fail-closed APPLICABLE-Port, niemals einen stillen Skip — FK-33 §33.6.5); `evaluate_sonarqube_gate(...)` -> `SonarGateOutcome`; `is_green` / `is_green_status`. AG3-034 baut **keine** Attestation/Reconciler/Green-Definition nach.

**Re-Entry (FK-33 §33.6.5 Re-Entry-Vorbedingung / §22.4c.3):** Nach `available:false->true` bzw. nach akkumulierter Fast-Schuld stellt der bestehende **Cleanup-Remediation-Worker** (ausserhalb des Story-Scopes, FK-22 §22.4c.3) `main` gruen her, bevor die strict-Story fortschreitet. AG3-034 fuehrt **keinen** neuen Mechanismus ein — es schreibt nur den aktiven, schuldfreien Vorschlag in das Phase-State-Ergebnis.

#### 2.1.3 IntegrityGate-9-Dimensionen (FK-35 §35.2 / §35.2.4 / §35.2.4a)

`src/agentkit/governance/integrity_gate/__init__.py` wird auf das **9**-Dimensionen-Schema (FK-35 §35.2.4) erweitert:

Die `IntegrityDimension`-IDs sind die KANONISCHEN FK-35-§35.2.4-Namen. Die §35.2.3-Pflicht-Artefakt-Vorstufe behaelt ihre eigenen FAIL-Codes (`MISSING_STRUCTURAL`/`MISSING_CONTEXT`/`MISSING_DECISION`), die fachlich von den §35.2.4-Dimensions-IDs getrennt bleiben (Vorstufe meldet Artefakt-Abwesenheit, die Dimensionen tiefere Invarianten).

| Dim | ID (FK-35 §35.2.4 kanonisch) | Pruefung | Quelle |
|---|---|---|---|
| 1 | `NO_QA_ARTIFACTS` | QA-Artefaktbestand / structural artifact existiert | ArtifactManager + Envelope-Validierung |
| 2 | `CONTEXT_INVALID` | Context-Integritaet / story_context existiert + valide | StoryContextRepository |
| 3 | `STRUCTURAL_SHALLOW` | Structural-Check-Tiefe / Phasen-Snapshots vollstaendig | PhaseEnvelopeStore |
| 4 | `DECISION_INVALID` | Policy-Decision / verify_decision existiert | ArtifactManager |
| 5 | `NO_LLM_REVIEW` | LLM-Bewertungen vorhanden (Stage-Registry-Pflicht) | nur bei `implementation`/`bugfix` |
| 6 | `NO_ADVERSARIAL` | Adversarial-Layer-Ergebnisse vorhanden falls Stage erforderlich | nur bei `implementation`/`bugfix` |
| 7 | `NO_VERIFY` | QA-Subflow flow_end (`PolicyVerdict.PASS`) | VerifyDecision-Envelope |
| 8 | `TIMESTAMP_INVERSION` | Timestamp-Kausalitaet (started_at <= finished_at; Phasenreihenfolge) | Envelope-Daten + Phase-States |
| 9 | `SONARQUBE_GREEN` (FAIL `SONAR_NOT_GREEN`) | commit-gebundene Sonar-Attestation des integrierten Pre-Merge-Stands ist gruen | **nur bei `implementation`/`bugfix` UND APPLICABLE** (FK-35 §35.2.4a / FK-33 §33.6.5); verifiziert ueber AG3-052-Capability — vermisst NICHT neu |

> **Benennung (FK-35 §35.2.4 kanonisch):** Die `IntegrityDimension`-Member tragen die kanonischen FK-35-§35.2.4-Pruefgegenstands-/FAIL-Code-Namen. **Dim 9** wird dimensionsseitig als `SONARQUBE_GREEN` gefuehrt, FAIL-seitig kanonisch als `SONAR_NOT_GREEN` (FK-35 §35.2.4a).

##### Dim 9 `SONARQUBE_GREEN` — Attestations-Verifikation (FK-35 §35.2.4a, konsumiert AG3-052)

Dim 9 **fuehrt keinen Sonar-Scan aus** (FK-35 §35.2.4a, zentrale Regel). Der Scan des integrierten Pre-Merge-Kandidaten lebt im Pre-Merge-Scan-und-Merge-Block der Closure-Sequenz (FK-29 §29.1a, OOS dieser Story) und nutzt die `sonarqube_gate`-Capability. Dim 9 **verifiziert** ausschliesslich die dort erzeugte, commit-gebundene **Attestation** — konsistent mit dem Gate-Prinzip „prueft Prozess-Integritaet, nicht fachliche Qualitaet" (§35.2.2). Prueftiefe (alle Bedingungen, FK-35 §35.2.4a): (1) Attestation existiert fuer den gueltigen `run_id`; (2) Commit-Bindung `commit_sha`/`tree_hash` == Merge-Zustand; (3) QG OK auf der Overall-Code-Invariante per `analysisId`; (4) Exception-Ledger-Hash stimmt (FK-33 §33.6.4); (5) Tool-/Config-Versionen stimmen.

**Applicability-Geltung (FK-33 §33.6.5):** Dim 9 wird nur ausgewertet, wenn der Gate-Punkt **APPLICABLE** ist (`sonarqube.available == true` UND `mode != fast` UND `story_type ∈ {implementation, bugfix}`).
- `sonarqube.available == false` -> Dim 9 **NOT_APPLICABLE** (Skip; kein `SONAR_NOT_GREEN`-FAIL) — es existiert bewusst keine Attestation („abwesend ≠ kaputt").
- `mode == fast` -> das **gesamte 9-Dimensionen-IntegrityGate wird in der Closure durch das Sanity-Gate ersetzt** (Tests gruen, Worktree clean, Pre-Merge-Rebase OK, FK-24 / FK-29); Dim 9 wird nicht ausgewertet.
- `available == true`, aber Attestation fehlt/stale/rot/unerreichbar -> bleibt **APPLICABLE** und failt **fail-closed** mit `SONAR_NOT_GREEN`, Phase-State `ESCALATED` (§35.2.9). Kein Bypass, keine Substitution durch CI-Sonar.

**Konsumierte AG3-052-API (Dim 9):** `resolve_for_context(...)` -> `SonarApplicability`; `SonarAttestation` + `.is_bound_to(main_head_revision)` (Commit-Bindung/Stale-Check); `is_green` / `is_green_status` (Green-Definition); `evaluate_sonarqube_gate(...)` -> `SonarGateOutcome` (`gate_status` `sonarqube_gate_passed` | `failed` | `sonarqube_gate_not_applicable`). Die Attestations-Quelle ist die kanonische Capability-Attestation, kein Worker-Artefakt/Dateiexport.

Pflicht-Artefakt-Vorstufe (FK-35 §35.2.3): Dim 1-3 sind harte Pre-Conditions. Wenn eines fehlt: gesamte Gate-Pruefung wird mit klarer `MISSING_*`-Meldung abgebrochen; Dim 4-9 werden nicht mehr ausgewertet (Performance + Klarheit).

Envelope-Pflichtfeld-Pruefung (Dim 1-3, artifacts.B4): IntegrityGate ruft `EnvelopeValidator.validate` (aus AG3-022) fuer jedes Pflicht-Artefakt. Fehler -> Gate FAIL mit `ENVELOPE_VIOLATION`.

`IntegrityGateResult`:

```python
class IntegrityGateResult(BaseModel):
    overall: IntegrityGateStatus  # PASS | FAIL | ESCALATED
    dimension_results: dict[IntegrityDimension, DimensionResult]
    missing_artifacts: list[str]
    blocked_dimensions: list[IntegrityDimension]
    failure_reason: str | None
```

#### 2.1.4 Concept/Research-Drift behebt (governance-and-guards.C4)

`_REQUIRED_PHASES` in `integrity_gate/__init__.py` wird typ-abhaengig:

```python
def required_phases_for(story_type: StoryType) -> tuple[PhaseName, ...]:
    if story_type in {StoryType.IMPLEMENTATION, StoryType.BUGFIX}:
        return (PhaseName.SETUP, PhaseName.IMPLEMENTATION, PhaseName.CLOSURE)
    if story_type == StoryType.CONCEPT:
        return (PhaseName.SETUP, PhaseName.CLOSURE)
    if story_type == StoryType.RESEARCH:
        return (PhaseName.SETUP, PhaseName.CLOSURE)
    raise ValueError(...)
```

Dim 5 (LLM_REVIEW_COMPLIANT), Dim 6 (ADVERSARIAL_NACHWEIS) **und Dim 9 (SONARQUBE_GREEN)** gelten nur fuer Implementation/Bugfix; Dim 9 zusaetzlich nur im APPLICABLE-Fall (FK-33 §33.6.5). Tests verifizieren das.

#### 2.1.5 Tests

- Unit-Tests pro Preflight-Check (10 Tests, je happy path + fail-Pfad)
- Unit-Test fuer `PreflightResult` (alle 10 Checks laufen, auch wenn frueher Fail)
- **Unit-Tests Setup-green-main-Precondition (§2.1.2b)**: APPLICABLE-green -> Setup laeuft weiter; APPLICABLE-rot/stale/unerreichbar -> fail-closed mit Cleanup-Vorschlag; `available:false` -> SKIP (Skip-Edge, kein FAIL); `mode:fast` -> SKIP; concept/research -> entfaellt. Gegen eine **gestubbte AG3-052-Capability-Grenze** (keine Live-Sonar-Abhaengigkeit; echte Applicability-Aufloesung via `resolve_for_context`).
- Unit-Tests fuer alle **9** IntegrityGate-Dimensionen
- **Unit-Tests Dim 9 (`SONARQUBE_GREEN`)**: APPLICABLE-green-Attestation -> PASS; APPLICABLE rot/stale/Commit-Drift/Ledger-Hash-Mismatch/unerreichbar -> FAIL `SONAR_NOT_GREEN` (`ESCALATED`); `available:false` -> NOT_APPLICABLE (Dim 9 fehlt im Ergebnis, kein FAIL); `mode:fast` -> Dim 9 nicht ausgewertet; concept/research -> Dim 9 nicht ausgewertet.
- Unit-Test fuer Pflicht-Artefakt-Vorstufe: fehlender structural artifact -> Dim 4-9 werden uebersprungen
- Unit-Tests fuer Concept/Research-Routing: Dim 5/6/9 werden bei concept/research nicht geprueft
- **Unit-Test Applicability-3-Zustaende (absent ≠ unreachable)** an Setup-green-main UND Dim 9: `available:false`=SKIP vs `available:true`+unreachable=fail-closed.
- Integration-Test Preflight: vollstaendiger Lauf gegen eine simulierte Story; alle 10 Checks gruen oder ein definierter Fail; green-main-Edge mit gestubbter Capability.
- Integration-Test IntegrityGate: vollstaendige Closure-Pruefung mit allen **9** Dimensionen (gestubbte Capability-Grenze fuer Dim 9).
- Contract-Tests fuer Pflicht-Pruefungslisten (inkl. der **9**-Dimensionen-Liste und der Applicability-Geltung von Dim 9 / green-main).

### 2.2 Out of Scope

- **AG3-052-interne Gate-Mechanik** (commit-gebundene Attestation, Green-Definition/Overall-Code-Invariante, 3-Zustands-Applicability-Aufloesung, Accepted-Ledger, Single-Match-Reconciler, SonarQube-Adapter, `sonarqube_gate`-Stage) — bereits gebaut in AG3-052; AG3-034 **konsumiert** nur die Capability-API (FK-22 §22.4c.1 „Aufrufer, kein Owner"; FK-35 §35.2.4a „verifiziert nur — vermisst nicht neu"). **Nicht erneut bauen.**
- **Closure-Pre-Merge-Scan + Merge-Serialisierungs-Lock + Post-Merge-Reconcile gegen `main`** (FK-29 §29.1a) — Closure-Story. Dieser Scan ERZEUGT die Attestation, die Dim 9 nur verifiziert.
- **QA-Subflow-Sonar-Stage (Punkt 2, FK-27 §27.6a)** — bereits AG3-052 (QA-Subflow-Andockpunkt). Hier nicht.
- **Cleanup-Remediation-Worker** (rot `main` -> scope-fremder Aufraeum-Worker) — bestehender/eigener Owner (FK-22 §22.4c.3); AG3-034 schreibt nur den aktiven, schuldfreien Vorschlag.
- **Sechs-Augen-Quorum-PROZESS** fuer Accepted-Issues (FK-33 §33.6.4) — Governance-Forward-Ref; nicht hier.
- GovernanceObserver (`A1`) — bewusst nicht in der Erst-Welle
- WorkerHealthMonitor (`A2`) — bewusst nicht in der Erst-Welle
- IntegrityGate-Multi-LLM-Compliance-Check (Dim 5 Detail "Mindest-N-LLM-Reviews") — Folge-Story (braucht Stage-Registry mit Multi-LLM-Quorum-Definition). **Das ist NICHT Dim 9.**
- Modus-Ermittlung (`B3`) — bleibt bei AG3-018-Folge
- Orchestrator-Guard-Vollausbau (`B4`) — Folge-Story
- Atomare mode_lock-Setzung beim Story-Start — AG3-018 / nachgelagerte Story
- Phase-Transition-Enforcement nach FK-45-Semantik (`pipeline-framework.B3`) — Folge-Story
- Recovery-Mechanik fuer fehlerhafte Worktrees — separate Story
- Branch-Cleanup-Logik im no_story_branch-Fail (CLI agentkit cleanup-branch) — Folge-Story

## 3. Betroffene Dateien

| Datei | Aenderungsart | Beschreibung |
|---|---|---|
| `src/agentkit/pipeline/phases/setup/preflight.py` | Erweitert | 10 Checks, PreflightCheckResult/PreflightResult |
| `src/agentkit/pipeline/phases/setup/preflight_checks/` | Neu (Unterverzeichnis) | Eine Datei pro Check fuer Klarheit |
| `src/agentkit/governance/integrity_gate/__init__.py` | Modifiziert | **9-Dimensionen-Aggregation**, Pflicht-Artefakt-Vorstufe, Concept/Research-Routing; Dim-9-Verdrahtung der Capability-Grenze (DI, kein Live-Sonar im Gate-Kern) |
| `src/agentkit/governance/integrity_gate/dimensions.py` | Modifiziert | **Dim 9 `SONARQUBE_GREEN`** ergaenzt; `dimensions_for` zieht Dim 9 code-only + applicability-konditional; `evaluate_dimension` verifiziert die Attestation via AG3-052 (kein Neubau) |
| `src/agentkit/pipeline/phases/setup/preflight_checks/` bzw. `preflight.py` | Erweitert | **Setup-green-main-Precondition (§2.1.2b)** — ruft AG3-052-Capability (`resolve_for_context`/`build_sonar_gate_port_for_run`/`evaluate_sonarqube_gate`), fail-closed; Skip-Edge bei NOT_APPLICABLE |
| `src/agentkit/state_backend/store/mode_lock_repository.py` | Neu (falls noch nicht durch AG3-018) | Repository fuer project_mode_lock |
| `src/agentkit/state_backend/postgres_schema.sql` | Modifiziert | Tabelle `project_mode_lock` (falls noch nicht durch AG3-018) |
| `src/agentkit/state_backend/sqlite_store.py` | Modifiziert | analog SQLite |
| `src/agentkit/state_backend/config.py` | Modifiziert | SCHEMA_VERSION-Bump (falls noetig) |
| `tests/unit/pipeline/phases/setup/test_preflight_*` | Neu (10 Tests) + green-main | Pro Check + green-main-Precondition (alle 3 Applicability-Zustaende) |
| `tests/unit/governance/integrity_gate/test_dimensions.py` | Neu/Erweitert | **9** Dimensionen (inkl. Dim 9 + Applicability) |
| `tests/unit/governance/integrity_gate/test_concept_research_routing.py` | Neu | Drift-Korrektur (Dim 5/6/9 bei concept/research absent) |
| `tests/integration/pipeline/test_preflight_full.py` | Neu | E2E Preflight (gestubbte Capability-Grenze fuer green-main) |
| `tests/integration/governance/test_integrity_gate_full.py` | Neu | E2E IntegrityGate (9 Dim, gestubbte Capability-Grenze fuer Dim 9) |
| `tests/contract/governance/test_integrity_dimensions.py` | Neu | Vertrags-Pinning (9-Dim-Liste + Dim-9/green-main-Applicability-Geltung) |

## 4. Akzeptanzkriterien

1. **10 Preflight-Checks**: `PreflightResult.checks` enthaelt nach einem Lauf genau 10 Eintraege (auch wenn frueher Fail).
2. **Jeder Check ist in einem eigenen Submodul** unter `preflight_checks/` (1 Datei pro Check). Funktion-Signatur: `def check(ctx: PreflightContext) -> PreflightCheckResult`.
3. **Cleanup-Hint Pflicht**: jeder FAIL liefert einen menschenlesbaren `cleanup_hint` (z.B. "Run `agentkit cleanup-worktree --story=AK3-042`"). Tests bestaetigen das.
4. **Preflight ist fail-closed pro Check**: Exception in einem Check wird zu FAIL mit `detail="exception: <type>: <msg>"`, kein Check wird stillschweigend uebersprungen.
5. **`IntegrityGate` prueft 9 Dimensionen** (FK-35 §35.2.4) mit den genannten IDs. Fuer eine APPLICABLE impl/bugfix-Story enthaelt `IntegrityGateResult.dimension_results` 9 Eintraege (oder weniger, wenn Pflicht-Artefakt-Vorstufe abbricht — dann sind Dim 4-9 in `blocked_dimensions`); fuer NOT_APPLICABLE/concept/research entsprechend weniger (Dim 9 bzw. Dim 5/6/9 fehlen).
6. **Pflicht-Artefakt-Vorstufe**: fehlender structural artifact -> Gate liefert FAIL mit `failure_reason="MISSING_STRUCTURAL"` und `blocked_dimensions` umfasst Dim 4-9.
7. **Envelope-Pflichtfeld-Pruefung** in Dim 1-3: `EnvelopeValidator.validate` wird fuer jedes Pflicht-Artefakt aufgerufen; Validation-Fehler -> Gate FAIL mit `ENVELOPE_VIOLATION`-Reason.
8. **Concept/Research-Routing**: bei `story_type in {CONCEPT, RESEARCH}` werden Dim 5 (LLM_REVIEW_COMPLIANT), Dim 6 (ADVERSARIAL_NACHWEIS) **und Dim 9 (SONARQUBE_GREEN)** **nicht** ausgewertet (`dimension_results.get(...)` None bzw. Eintrag fehlt). Tests bestaetigen das.
9. **Timestamp-Kausalitaet (Dim 8)**: `started_at <= finished_at` pro Envelope; Phase-Reihenfolge `setup_started_at <= implementation_started_at <= closure_started_at`. Verstoss -> FAIL mit `TIMESTAMP_VIOLATION`.
10. **Dim 9 `SONARQUBE_GREEN` (FK-35 §35.2.4a, konsumiert AG3-052)**: bei `implementation`/`bugfix` UND APPLICABLE verifiziert das Gate die commit-gebundene Attestation ueber die AG3-052-Capability (`resolve_for_context`, `SonarAttestation.is_bound_to`, `is_green_status`, `evaluate_sonarqube_gate`) — **kein eigener Scan**. APPLICABLE-green -> PASS; APPLICABLE rot/stale/Commit-Drift/Ledger-Mismatch/unerreichbar -> FAIL `SONAR_NOT_GREEN` (`ESCALATED`). `available:false` -> NOT_APPLICABLE (Dim 9 absent, kein FAIL); `mode:fast` -> Dim 9 nicht ausgewertet. Tests je Zustand inkl. absent ≠ unreachable.
11. **Setup-green-main-Precondition (FK-22 §22.4c, konsumiert AG3-052)**: vor der Worktree-Erstellung; APPLICABLE-green -> Setup weiter; APPLICABLE rot/stale/unerreichbar -> Setup **fail-closed** mit aktivem, schuldfreiem Cleanup-Vorschlag (§22.4c.3); `available:false`/`mode:fast` -> SKIP (Skip-Edge zu `worktrees_ready`, kein FAIL); concept/research -> entfaellt. Keine Gate-Mechanik nachgebaut.
12. **Architecture-Conformance**: `preflight_checks/` und `integrity_gate/dimensions.py` halten BC-Grenzen; lesen Artefakte nur ueber ArtifactManager bzw. existing-Repositories; die Sonar-Verifikation laeuft ausschliesslich ueber die `verify_system.sonarqube_gate`-Capability-API (keine zweite Sonar-Wahrheit, kein direkter SonarQube-Adapter in `governance`/`setup`).
13. **Pflichtbefehle gruen**: pytest unit + integration + contract; mypy default **und** `--platform linux`; ruff clean; Coverage ≥ 85%; LOC-Linter (`scripts/python/py_loc_to_sonar.py`) 0 Issues; vier CI-Konzept-Gates gruen.

## 5. Definition of Done

- AK 1-13 erfuellt.
- `.venv\Scripts\python -m pytest` gruen.
- `mypy src` (default) **und** `mypy --platform linux src` gruen; `ruff check src tests` gruen.
- LOC-Linter + vier CI-Konzept-Gates gruen.
- giftige Codex-Review (+ ggf. Grok) -> PASS; Jenkins SUCCESS; Sonar Quality Gate OK.
- Aenderungen committed auf `main`.

## 6. Konzept-Referenzen (autoritativ)

- **FK-22 §22.3/22.3.1** — 10 Preflight-Checks
- **FK-22 §22.4c** — SonarQube-main-Green-Vorbedingung (Setup als Aufrufer der Capability, fail-closed; §22.4c.3 Cleanup-Vorschlag)
- **FK-35 §35.2** — IntegrityGate-Aufbau
- **FK-35 §35.2.3** — Pflicht-Artefakt-Vorstufe
- **FK-35 §35.2.4** — **NEUN** Artefakt-Dimensionen (kanonische Liste + FAIL-Codes); Dim 5/6/9 nur fuer Implementation/Bugfix
- **FK-35 §35.2.4a** — Dim 9 SonarQube-Green (Attestations-Verifikation, Applicability-Geltung, „verifiziert nur — vermisst nicht neu")
- **FK-35 §35.4** — Eskalationsmechanismus
- **FK-33 §33.6.3** — Green-Definition, commit-gebundene Attestation, 3-Punkt-Verankerung
- **FK-33 §33.6.5** — 3-Zustands-Applicability (Owner): APPLICABLE / NOT_APPLICABLE_UNAVAILABLE / NOT_APPLICABLE_FAST; absent ≠ kaputt
- **FK-24 §24.3.3/§24.3.4** — fast/standard-`mode`-Achse (entkoppelt von `execution_route`)
- **DK-03 §3.6** — IntegrityGate
- **`formal.setup-preflight.*`** — formale Spec (inkl. green-main-Invariante)
- **`formal.integrity-gate.*`** — formale Spec (inkl. 9-Dim-Invariante)
- **`formal.deterministic-checks.*`** — Applicability-Invarianten/State-Machine der `sonarqube_gate`-Capability
- **AG3-052 §2.2 / AC8** — Consumer-Vertrag der `sonarqube_gate`-Capability-API
- **FK-71 §71.2** — Envelope-Pflichtfelder

## 7. Guardrail-Referenzen

- **FIX THE MODEL, NOT THE SYMPTOM**: alle Preflight-Checks vollstaendig — keine "spaeter erweitern"-TODOs.
- **ZERO DEBT**: IntegrityGate prueft Pflichtfelder, nicht nur Existenz.
- **FAIL CLOSED**: jedes Pflicht-Artefakt fehlt -> harter Abbruch mit klarer Meldung.
- **SINGLE SOURCE OF TRUTH**: Pflicht-Phasen pro StoryType ueber `required_phases_for(...)`-Funktion, nicht in mehreren Stellen kopiert.
- **NO ERROR BYPASSING**: keine Story darf Closure passieren ohne PASS in allen relevanten Dimensionen.

## 8. Hinweise fuer den Sub-Agent

- Mode-Lock-Tabelle: falls AG3-018 die Tabelle schon gebaut hat, NICHT neu anlegen. Lookup auf `state_backend/postgres_schema.sql`.
- **Dim 9 + green-main KONSUMIEREN AG3-052, NICHT neu bauen.** Aufrufbare API: `agentkit.backend.verify_system.sonarqube_gate` (`resolve_for_context`, `build_sonar_gate_port_for_run`, `evaluate_sonarqube_gate`, `SonarApplicability`, `SonarAttestation`, `is_green`/`is_green_status`, `SonarGateOutcome`). Keine eigene Attestation/Reconciler/Green-Definition; kein direkter `integrations.sonar`-Zugriff aus `governance`/`setup` (Capability ist die Grenze).
- **Mode-Achse:** `fast` aus `StoryContext.mode` (`WireStoryMode.FAST`) lesen — NICHT aus `execution_route` (FK-24 §24.3.3 entkoppelt die Achsen; das war der alte Achsen-Bug).
- **Applicability vor Bewertung:** an beiden Andockpunkten zuerst `resolve_for_context(...)` aufloesen; `available:false`/`mode:fast` = Skip; `available:true`+unerreichbar = APPLICABLE + fail-closed (absent ≠ kaputt).
- Sonar im Test: KEINE Live-Sonar-Abhaengigkeit; nur die Capability-/HTTP-Grenze stubben (MOCKS-Ausnahme: externes System), Applicability-/Verifikationslogik echt testen.
- Preflight-Tests: kein Mock-Filesystem, nutze `tmp_path`-Fixtures.
- IntegrityGate-Tests: bauen ArtifactManager mit Stub-Repository.
- AK2 NICHT veraendern.
- Dim-1-8-Benennung ist ENTSCHIEDEN (an FK-35 §35.2.4 angeglichen, §10).

## 9. Scope-Amendment 2026-06-03 (Stefan-Entscheidung, Konzept-Treue)

giftige-Codex + Worker haben unabhaengig festgestellt: FK-35 §35.2.4 fordert
**NEUN** Artefakt-Dimensionen (Dim 9 = `SonarQube-Green` / `SONAR_NOT_GREEN`,
normativ in `formal-spec/integrity-gate/invariants.md`), und die Setup-Phase
fordert eine **fail-closed GREEN-main-Precondition** (`formal-spec/
setup-preflight/invariants.md` + FK-22 §22). Die urspruengliche Story (§2.1.3
"8 Dimensionen") war damit eine stille Konzept-Unterlieferung. Stefan-
Entscheidung: AG3-034 wird auf den vollen Konzept-Stand gezogen. Erweiterter
Scope (zusaetzlich zu §2.1):

**Applicability-Vorbehalt (FK-33 §33.6.5 — Konzept-Nachschärfung 2026-06-03):**
Dim 9 und die GREEN-main-Precondition gelten NUR, wenn der `sonarqube_gate`
APPLICABLE ist, d. h. `sonarqube.available == true` (FK-03) **UND** `mode != fast`
(FK-24 §24.3.4) **UND** `story_type ∈ {implementation, bugfix}`. Bei
`sonarqube.available == false` (Projekt ohne Sonar) sind Dim 9 / green-main
NOT_APPLICABLE (Skip, kein fail-closed); bei `mode == fast` ersetzt das
Sanity-Gate das 9-Dim-Gate (Dim 9 / green-main nicht geprueft). Nur ein
KONFIGURIERT-aber-rot/stale/unerreichbares Sonar (`available == true`) failt
fail-closed — bewusst-abwesend ≠ kaputt.

- **Dim 9 `SONARQUBE_GREEN`** (FK-35 §35.2.4 / formal.integrity-gate.invariants):
  liest die commit-gebundene Sonar-Attestierung, bindet an Merge-State
  (commit_sha/tree_hash), Quality-Gate OK, Ledger-/Versions-Match; nur fuer
  `implementation`/`bugfix` **und nur im APPLICABLE-Fall**. Im APPLICABLE-Fall:
  fehlende/rot/stale/unerreichbare Attestierung -> fail-closed FAIL. Bei
  `available == false` -> NOT_APPLICABLE (Skip); bei `mode == fast` -> Sanity-Gate.
- **GREEN-main-Precondition im Preflight** (formal.setup-preflight.invariants /
  FK-22 §22.4c): im APPLICABLE-Fall verweigert stale/rote/unerreichbare main den
  Setup fail-closed; bei `available == false` oder `mode == fast` ->
  NOT_APPLICABLE (Skip-Edge zu `worktrees_ready`).
- Die commit-gebundene Attestierungs-/Ledger-Quelle ist mit **AG3-052** gebaut
  und konsumierbar (`verify_system.sonarqube_gate`): `SonarAttestation`,
  `AcceptedExceptionLedger`, `evaluate_sonarqube_gate`, `resolve_for_context`,
  `build_sonar_gate_port_for_run`. AG3-034 fuehrt daher `AG3-052` als
  Abhaengigkeit (siehe Header + status.yaml). Das Gate failt fail-closed, bis die
  Attestierung vorliegt (kein Bypass, keine Substitution durch CI-Sonar).
  Re-Entry nach `available:false->true` bzw. nach Fast-Schulden:
  Cleanup-Remediation-Worker (FK-22 §22.4c.3 / FK-33 §33.6.5 Re-Entry) stellt
  green-main her, bevor die strict-Story laeuft (kein neuer Mechanismus).

Die §2.2-Ausklammerung von "Multi-LLM-Compliance (Dim 5 Detail Mindest-N)" bleibt
bestehen (das ist NICHT Dim 9).

## 10. Dimensions-Benennung Dim 1-8 — ENTSCHIEDEN (angeglichen)

Stefan-Entscheidung 2026-06-03: Die `IntegrityDimension`-IDs/FAIL-Codes Dim 1-8
wurden auf die KANONISCHEN FK-35-§35.2.4-Namen angeglichen (siehe §2.1.3):
`NO_QA_ARTIFACTS`, `CONTEXT_INVALID`, `STRUCTURAL_SHALLOW`, `DECISION_INVALID`,
`NO_LLM_REVIEW`, `NO_ADVERSARIAL`, `NO_VERIFY`, `TIMESTAMP_INVERSION` — plus Dim 9
`SONARQUBE_GREEN` (FAIL `SONAR_NOT_GREEN`). Die vormaligen Ist-Namen
(`MISSING_*`/`*_NACHWEIS`/`*_KAUSALITY`) sind entfernt, kein Alias. Die
§35.2.3-Pflicht-Artefakt-Vorstufe behaelt ihre eigenen, davon getrennten
FAIL-Codes (`MISSING_STRUCTURAL`/`MISSING_CONTEXT`/`MISSING_DECISION`), da sie
Artefakt-Abwesenheit meldet und nicht die §35.2.4-Dimensions-Invarianten. Alle
Konsumenten/Tests/Contracts wurden mitgezogen. Die vormalige offene
Konformitaetsfrage (WARNING) ist damit aufgeloest.
