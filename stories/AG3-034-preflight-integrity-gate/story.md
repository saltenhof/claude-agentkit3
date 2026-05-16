# AG3-034: Preflight-Checks 2/5-10 + IntegrityGate-8-Dimensionen + Concept/Research-Drift fix

**Typ:** Implementation
**Groesse:** L
**Abhaengigkeiten:** AG3-021 (Enums), AG3-022 (Envelope), AG3-023 (ArtifactManager fuer Envelope-Pflichtfeld-Pruefung), AG3-032 (PathClassifier fuer Preflight-Checks)
**Quell-Konzepte (autoritativ, in dieser Reihenfolge):**
- `FK-22 §22.3` (10 Preflight-Checks fail-closed)
- `FK-22 §22.3.1` (Check-Definitionen)
- `FK-35 §35.2` (IntegrityGate mit 3 Pflicht-Artefakten + 8 Dimensionen)
- `FK-35 §35.2.3/35.2.4` (Pflicht-Artefakt-Vorstufe + Dimensionen)
- `FK-35 §35.4` (Eskalationsmechanismus)
- `DK-03 §3.6` (IntegrityGate-Domaene)
- `formal.setup-preflight.*`
- `formal.integrity-gate.*`
- `FK-71 §71.2` (Envelope-Pflichtfelder)

---

## 1. Kontext

THEME-006 aus `stories/_priorisierungsempfehlung.md`. Befunde:

- `governance-and-guards.B1`: Nur 3 von 10 Preflight-Checks implementiert (`story_exists`, `status_approved`, `dependencies_done`). Fehlen: `story_attributes_consistent`, `no_execution_artifacts`, `no_active_runtime_residue`, `no_story_branch`, `no_stale_worktree`, `no_scope_overlap`, `no_competing_story_mode_active`.
- `governance-and-guards.B2`: IntegrityGate prueft nur 4 von 8 Dimensionen. Fehlen Dim 5 (LLM-Reviews), Dim 6 (Adversarial), Dim 7 (QA-Subflow-flow_end), Dim 8 (Timestamp-Kausalitaet). Pflicht-Artefakt-Vorstufe (MISSING_STRUCTURAL/MISSING_DECISION/MISSING_CONTEXT) fehlt. Preflight-Compliance-Guard und Multi-LLM-Compliance fehlen.
- `governance-and-guards.C4`: IntegrityGate behandelt CONCEPT/RESEARCH wie IMPLEMENTATION — Tests fuer Dim 5/6 sollen nur fuer Implementation/Bugfix gelten.
- `artifacts.B4`: IntegrityGate prueft nur Existenz, keine Envelope-Pflichtfelder.

Diese Story stellt die zwei Gates vollstaendig her. Sie ist eigenstaendig pruefbar, weil jeder Preflight-Check und jede Integrity-Dimension einen klaren Eingangs-/Ausgangskontrakt hat.

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
- `active_mode: StoryMode | None` (Werte `EXECUTION`, `EXPLORATION`, `FAST`, oder `None`/idle)
- `holder_count: int`
- `updated_at`

Check 10 logik: wenn Story-Mode != aktiver mode_lock-Mode und holder_count > 0 -> FAIL mit `cleanup_hint`. (Begruendung: aktive Standard-Stories blockieren Fast-Start; aktive Fast-Story blockiert Standard-Start. Siehe AG3-018-Story.)

Atomare Mode-Lock-Setzung beim Story-Start ist Aufgabe von AG3-018 bzw. Folge-Story; hier wird nur der Read-Pfad fuer Check 10 hergestellt.

#### 2.1.3 IntegrityGate-8-Dimensionen (FK-35 §35.2)

`src/agentkit/governance/integrity_gate/__init__.py` wird auf das 8-Dimensionen-Schema erweitert:

| Dim | Pruefung | Quelle |
|---|---|---|
| 1 | `MISSING_STRUCTURAL` Pflicht-Artefakt (structural artifact existiert) | ArtifactManager + Envelope-Validierung |
| 2 | `MISSING_DECISION` Pflicht-Artefakt (verify_decision existiert) | ArtifactManager |
| 3 | `MISSING_CONTEXT` Pflicht-Artefakt (story_context existiert) | StoryContextRepository |
| 4 | `PHASE_SNAPSHOTS_COMPLETE` (alle Phasen-Snapshots existieren) | PhaseEnvelopeStore |
| 5 | `LLM_REVIEW_COMPLIANT` (LLM-Bewertungen vorhanden und gemaess Stage-Registry-Pflicht) | nur bei `implementation`/`bugfix` (FK-35 §35.2.4 Dim 5) |
| 6 | `ADVERSARIAL_NACHWEIS` (Adversarial-Layer-Ergebnisse vorhanden falls Stage erforderlich) | nur bei `implementation`/`bugfix` |
| 7 | `QA_SUBFLOW_FLOW_END` (`PolicyVerdict.PASS` als letztes QA-Subflow-Ergebnis) | VerifyDecision-Envelope |
| 8 | `TIMESTAMP_KAUSALITY` (started_at <= finished_at fuer alle Envelopes; Phasenuebergaenge in zeitlicher Reihenfolge) | Envelope-Daten + Phase-States |

Pflicht-Artefakt-Vorstufe (FK-35 §35.2.3): Dim 1-3 sind harte Pre-Conditions. Wenn eines fehlt: gesamte Gate-Pruefung wird mit klarer `MISSING_*`-Meldung abgebrochen; Dim 4-8 werden nicht mehr ausgewertet (Performance + Klarheit).

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

Dim 5 (LLM_REVIEW_COMPLIANT) und Dim 6 (ADVERSARIAL_NACHWEIS) gelten nur fuer Implementation/Bugfix. Tests verifizieren das.

#### 2.1.5 Tests

- Unit-Tests pro Preflight-Check (10 Tests, je happy path + fail-Pfad)
- Unit-Test fuer `PreflightResult` (alle 10 Checks laufen, auch wenn frueher Fail)
- Unit-Tests fuer alle 8 IntegrityGate-Dimensionen
- Unit-Test fuer Pflicht-Artefakt-Vorstufe: fehlender structural artifact -> Dim 4-8 werden uebersprungen
- Unit-Tests fuer Concept/Research-Routing: Dim 5/6 werden bei concept/research nicht geprueft
- Integration-Test Preflight: vollstaendiger Lauf gegen eine simulierte Story; alle 10 Checks gruen oder ein definierter Fail
- Integration-Test IntegrityGate: vollstaendige Closure-Pruefung mit allen 8 Dimensionen
- Contract-Tests fuer Pflicht-Pruefungslisten

### 2.2 Out of Scope

- GovernanceObserver (`A1`) — bewusst nicht in der Erst-Welle
- WorkerHealthMonitor (`A2`) — bewusst nicht in der Erst-Welle
- IntegrityGate-Multi-LLM-Compliance-Check (Dim 5 Detail "Mindest-N-LLM-Reviews") — Folge-Story (braucht Stage-Registry mit Multi-LLM-Quorum-Definition)
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
| `src/agentkit/governance/integrity_gate/__init__.py` | Modifiziert | 8 Dimensionen, Pflicht-Artefakt-Vorstufe, Concept/Research-Routing |
| `src/agentkit/governance/integrity_gate/dimensions.py` | Neu | `IntegrityDimension` StrEnum + Dimension-Checker-Klassen |
| `src/agentkit/state_backend/store/mode_lock_repository.py` | Neu (falls noch nicht durch AG3-018) | Repository fuer project_mode_lock |
| `src/agentkit/state_backend/postgres_schema.sql` | Modifiziert | Tabelle `project_mode_lock` (falls noch nicht durch AG3-018) |
| `src/agentkit/state_backend/sqlite_store.py` | Modifiziert | analog SQLite |
| `src/agentkit/state_backend/config.py` | Modifiziert | SCHEMA_VERSION-Bump (falls noetig) |
| `tests/unit/pipeline/phases/setup/test_preflight_*` | Neu (10 Tests) | Pro Check |
| `tests/unit/governance/integrity_gate/test_dimensions.py` | Neu | 8 Dimensionen |
| `tests/unit/governance/integrity_gate/test_concept_research_routing.py` | Neu | Drift-Korrektur |
| `tests/integration/pipeline/test_preflight_full.py` | Neu | E2E Preflight |
| `tests/integration/governance/test_integrity_gate_full.py` | Neu | E2E IntegrityGate |
| `tests/contract/governance/test_integrity_dimensions.py` | Neu | Vertrags-Pinning |

## 4. Akzeptanzkriterien

1. **10 Preflight-Checks**: `PreflightResult.checks` enthaelt nach einem Lauf genau 10 Eintraege (auch wenn frueher Fail).
2. **Jeder Check ist in einem eigenen Submodul** unter `preflight_checks/` (1 Datei pro Check). Funktion-Signatur: `def check(ctx: PreflightContext) -> PreflightCheckResult`.
3. **Cleanup-Hint Pflicht**: jeder FAIL liefert einen menschenlesbaren `cleanup_hint` (z.B. "Run `agentkit cleanup-worktree --story=AK3-042`"). Tests bestaetigen das.
4. **Preflight ist fail-closed pro Check**: Exception in einem Check wird zu FAIL mit `detail="exception: <type>: <msg>"`, kein Check wird stillschweigend uebersprungen.
5. **`IntegrityGate` prueft 8 Dimensionen** mit den genannten IDs. `IntegrityGateResult.dimension_results` enthaelt 8 Eintraege (oder weniger, wenn Pflicht-Artefakt-Vorstufe abbricht — dann sind Dim 4-8 in `blocked_dimensions`).
6. **Pflicht-Artefakt-Vorstufe**: fehlender structural artifact -> Gate liefert FAIL mit `failure_reason="MISSING_STRUCTURAL"` und `blocked_dimensions=[4,5,6,7,8]`.
7. **Envelope-Pflichtfeld-Pruefung** in Dim 1-3: `EnvelopeValidator.validate` wird fuer jedes Pflicht-Artefakt aufgerufen; Validation-Fehler -> Gate FAIL mit `ENVELOPE_VIOLATION`-Reason.
8. **Concept/Research-Routing**: bei `story_type in {CONCEPT, RESEARCH}` werden Dim 5 (LLM_REVIEW_COMPLIANT) und Dim 6 (ADVERSARIAL_NACHWEIS) **nicht** ausgewertet (Dimensionen sind `dimension_results.get(...)` None oder fehlend). Tests bestaetigen das.
9. **Timestamp-Kausalitaet (Dim 8)**: `started_at <= finished_at` pro Envelope; Phase-Reihenfolge `setup_started_at <= implementation_started_at <= closure_started_at`. Verstoss -> FAIL mit `TIMESTAMP_VIOLATION`.
10. **Architecture-Conformance**: `preflight_checks/` und `integrity_gate/dimensions.py` halten BC-Grenzen; lesen Artefakte nur ueber ArtifactManager bzw. existing-Repositories.
11. **Pflichtbefehle gruen**: pytest unit + integration + contract; mypy --strict; ruff clean; Coverage haelt 85%.

## 5. Definition of Done

- AK 1-11 erfuellt.
- `.venv\Scripts\python -m pytest -q` gruen.
- `mypy --strict` gruen, `ruff check src tests` gruen.
- Aenderungen committed auf `main`.

## 6. Konzept-Referenzen (autoritativ)

- **FK-22 §22.3/22.3.1** — 10 Preflight-Checks
- **FK-35 §35.2** — IntegrityGate-Aufbau
- **FK-35 §35.2.3** — Pflicht-Artefakt-Vorstufe
- **FK-35 §35.2.4** — Dim 5/6 nur fuer Implementation/Bugfix
- **FK-35 §35.4** — Eskalationsmechanismus
- **DK-03 §3.6** — IntegrityGate
- **`formal.setup-preflight.*`** — formale Spec
- **`formal.integrity-gate.*`** — formale Spec
- **FK-71 §71.2** — Envelope-Pflichtfelder

## 7. Guardrail-Referenzen

- **FIX THE MODEL, NOT THE SYMPTOM**: alle Preflight-Checks vollstaendig — keine "spaeter erweitern"-TODOs.
- **ZERO DEBT**: IntegrityGate prueft Pflichtfelder, nicht nur Existenz.
- **FAIL CLOSED**: jedes Pflicht-Artefakt fehlt -> harter Abbruch mit klarer Meldung.
- **SINGLE SOURCE OF TRUTH**: Pflicht-Phasen pro StoryType ueber `required_phases_for(...)`-Funktion, nicht in mehreren Stellen kopiert.
- **NO ERROR BYPASSING**: keine Story darf Closure passieren ohne PASS in allen relevanten Dimensionen.

## 8. Hinweise fuer den Sub-Agent

- Mode-Lock-Tabelle: falls AG3-018 die Tabelle schon gebaut hat, NICHT neu anlegen. Lookup auf `state_backend/postgres_schema.sql`.
- Preflight-Tests: kein Mock-Filesystem, nutze `tmp_path`-Fixtures.
- IntegrityGate-Tests: bauen ArtifactManager mit Stub-Repository.
- AK2 NICHT veraendern.
