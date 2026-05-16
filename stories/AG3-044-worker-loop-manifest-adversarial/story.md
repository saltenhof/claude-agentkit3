# AG3-044: WorkerSession + WorkerLoop + HandoverPackager + WorkerManifest + Adversarial-Spawn

**Typ:** Implementation
**Groesse:** L
**Abhaengigkeiten:** AG3-021, AG3-022, AG3-023 (ArtifactManager fuer Handover), AG3-026 (VerifySystem-Top), AG3-041 (QaCycleLifecycle fuer evidence_epoch in Adversarial-Spawn)
**Quell-Konzepte (autoritativ, in dieser Reihenfolge):**
- `FK-26 §26.2` (WorkerSession, Spawn-Protokoll, Worker-Kontext-Resolution)
- `FK-26 §26.3` (WorkerLoop, Vier-Schritt-Inkrement, Drift-Check Stufe 1)
- `FK-26 §26.7` (HandoverPackager + handover.json-Schema)
- `FK-26 §26.8` (WorkerManifest, drei Status, BLOCKED-Pflichtfelder)
- `FK-26 §26.11.2` (BLOCKED-Exit-Protokoll, ESCALATED-Pfad)
- `FK-27 §27.6` (Adversarial-Spawn via agents_to_spawn, Sandbox, Mandatory Targets)
- `FK-48` (Adversarial Testing Runtime)
- `formal.implementation.invariants §worker_blocked_escalates`

---

## 1. Kontext

THEME-009 aus `stories/_priorisierungsempfehlung.md`. Drei zusammenhaengende Befund-Gruppen:

**Worker-Seite** (`implementation-phase.A1-A4`):
- WorkerSession + Spawn-Protokoll fehlt
- WorkerLoop (4-Schritt-Inkrement) fehlt
- HandoverPackager + handover.json fehlt
- WorkerManifest + BlockingCategory fehlen (BlockingCategory ist als StrEnum in AG3-021 bereitgestellt)

**BLOCKED-Eskalation** (`implementation-phase.B1/C1`):
- ImplementationHandler liest `worker-manifest.json` nicht — verletzt Invariante `worker_blocked_escalates`
- ESCALATED-Triggerung falsch

**Adversarial-Spawn** (`verify-system.A8`):
- Adversarial-Agent-Spawn via `agents_to_spawn`-Feld im PhaseState fehlt
- Sandbox-Scoping (`_temp/adversarial/{story_id}/`)
- Mandatory Adversarial Targets aus Layer-2-Findings

Diese Story bringt Worker-Seite und Adversarial-Layer zusammen — beide arbeiten ueber `agents_to_spawn` als Engine-Steuerung. Sie ist gross, aber klar strukturiert: vier Sub-Komponenten + Adversarial-Spawn-Mechanik.

## 2. Scope

### 2.1 In Scope

#### 2.1.1 `WorkerSession` (FK-26 §26.2)

Neues Modul `src/agentkit/implementation/worker_session/`:

```python
class WorkerSession:
    def __init__(self, spawn_reason: SpawnReason, story_id: str, run_id: str) -> None: ...

    def resolve_worker_context(self) -> WorkerContext:
        # 1. Lese StoryContext aus story_context_manager
        # 2. Erzeuge WorkerContextItem-Set: story_brief, ac, repos, etc.
        # 3. Validiere via validate_worker_context
        ...

    def compose_worker_prompt(self, context: WorkerContext) -> str:
        # via PromptRuntime.materialize_prompt mit Template passend zu SpawnReason
        ...
```

`WorkerContextItemKey` StrEnum aus FK-26 §26.2.1.

#### 2.1.2 `WorkerLoop` (FK-26 §26.3)

`src/agentkit/implementation/worker_loop/`:

```python
class WorkerLoop:
    def __init__(self, drift_check_hook: DriftCheckHook, commit_hook: CommitHook) -> None: ...

    def run_increment(self, session: WorkerSession, increment_input: IncrementInput) -> IncrementResult:
        # 1. Implementieren (Code-Aenderung via Tool)
        # 2. Lokal verifizieren (Tests laufen)
        # 3. Drift pruefen (Hook-basiert)
        # 4. Committen (mit Hook-Validierung)
        ...

class IncrementStep(StrEnum):
    IMPLEMENT = "implement"
    VERIFY_LOCAL = "verify_local"
    DRIFT_CHECK = "drift_check"
    COMMIT = "commit"
```

Drift-Check Stufe 1: deterministischer Hook-basierter Diff-gegen-Entwurfsartefakt (Entwurfsartefakt aus Exploration; falls keine Exploration: skip mit `drift_check.skipped=true`).

#### 2.1.3 `HandoverPackager` (FK-26 §26.7)

`src/agentkit/implementation/handover/`:

```python
class HandoverPackager:
    def __init__(self, artifact_manager: ArtifactManager) -> None: ...

    def package(self, session: WorkerSession, increments: list[IncrementResult]) -> ArtifactReference:
        # Erzeugt handover.json mit Pflichtfeldern
        # Schreibt via ArtifactManager (ArtifactClass.HANDOVER)
        ...
```

`handover.json` Pydantic-Schema (FK-26 §26.7.2 — sieben Pflichtfelder):
- `story_id`, `run_id`, `commit_sha`, `branch_ref`
- `increments: list[IncrementSummary]`
- `risks_for_qa: list[str]`
- `drift_log: list[DriftEvent]`
- `acceptance_criteria_status: dict[ACId, ACStatus]`

`ACStatus` StrEnum: `MET`, `PARTIALLY_MET`, `NOT_MET`.

#### 2.1.4 `WorkerManifest` (FK-26 §26.8)

`src/agentkit/implementation/manifest/`:

```python
class WorkerManifest(BaseModel):
    story_id: str
    run_id: str
    status: WorkerManifestStatus
    blocking_category: BlockingCategory | None    # aus core_types (AG3-021)
    blocking_issue: str | None
    recommended_next_action: str | None
    completed_at: datetime
    model_config = ConfigDict(frozen=True, extra="forbid")

class WorkerManifestStatus(StrEnum):
    COMPLETED = "completed"
    COMPLETED_WITH_ISSUES = "completed_with_issues"
    BLOCKED = "blocked"
```

Validator: bei `status=BLOCKED` MUESSEN `blocking_category`, `blocking_issue`, `recommended_next_action` gesetzt sein.

Persistenz ueber ArtifactManager (ArtifactClass.HANDOVER analog).

#### 2.1.5 BLOCKED-Exit-Protokoll (FK-26 §26.11.2, implementation-phase.B1/C1)

`src/agentkit/pipeline/phases/implementation/phase.py:ImplementationPhaseHandler`:

- `on_enter` liest IMMER ZUERST `worker-manifest.json` (via ArtifactManager mit `ArtifactClass.HANDOVER`)
- Bei `status=BLOCKED`: Sofortiger Return `HandlerResult.ESCALATED` mit `suggested_reaction` aus `manifest.recommended_next_action`, Blocker-Details aus Manifest
- KEIN QA-Subflow-Start mehr in diesem Fall

Invariante `formal.implementation.invariants §worker_blocked_escalates` ist damit pruefbar.

#### 2.1.6 Adversarial-Spawn (FK-27 §27.6, FK-48)

`src/agentkit/verify_system/adversarial_orchestrator/spawn.py`:

```python
class AdversarialSpawner:
    def __init__(self, artifact_manager: ArtifactManager) -> None: ...

    def derive_targets(self, layer2_findings: list[Finding]) -> list[AdversarialTarget]:
        # Mandatory Targets aus Layer-2-Findings ableiten
        ...

    def request_spawn(self, ctx: VerifyContextBundle, targets: list[AdversarialTarget]) -> AdversarialSpawnRequest:
        # Schreibt agents_to_spawn-Feld in PhaseState
        # Engine wertet das aus und spawnt Worker
        ...
```

Sandbox-Scoping: alle Adversarial-Spawns schreiben nach `_temp/adversarial/{story_id}/{epoch}/`. Pfad in Protected-Paths (AG3-023).

Adversarial-Result-Processing (Test-Promotion, Quarantine) ist begrenzt — diese Story stellt nur den Spawn-Mechanismus bereit; volle Adversarial-Logik (Test-Promotion-Workflow) ist Folge-Story.

#### 2.1.7 Orchestrator-Trennlinie fuer Remediation-Worker (pipeline-framework.C3)

`ImplementationPhaseHandler` macht keinen inline-Remediation-Loop mehr. Stattdessen:
- Bei QA-Subflow-FAIL und `RemediationDecision.CONTINUE_REMEDIATION`: setze `agents_to_spawn=[remediation_worker]` im PhaseState, gib `HandlerResult.YIELDED` zurueck
- Engine spawnt einen neuen Worker (durch Phase-Re-Entry mit `SpawnReason.REMEDIATION`)
- Bei ESCALATE: `HandlerResult.ESCALATED`

#### 2.1.8 Tests

- Unit-Tests pro Sub-Komponente (WorkerSession, WorkerLoop, HandoverPackager, WorkerManifest)
- Validator-Test `WorkerManifest` BLOCKED Pflichtfelder
- Integration-Test BLOCKED-Exit: Manifest mit status=BLOCKED triggert ESCALATED ohne QA-Subflow
- Integration-Test Adversarial-Spawn: Layer-2-Findings -> AdversarialTargets -> agents_to_spawn-Feld gesetzt
- Integration-Test Orchestrator-Trennlinie: QA-FAIL -> YIELDED + agents_to_spawn statt while True
- Contract-Test `tests/contract/implementation/test_handover_schema.py`: sieben Pflichtfelder
- Contract-Test `tests/contract/implementation/test_worker_manifest.py`: drei Status + BLOCKED-Pflichtfelder

### 2.2 Out of Scope

- WorkerHealthMonitor (`implementation-phase.A5-A8`) — bewusst nicht in der Erst-Welle
- LLM-Pool-Reviews-Vollausbau (`implementation-phase.B4`) — Folge-Story (Sparring-Templates fehlen)
- Bugfix Red-Green-Suite (`FK-26 §26.9`) — Folge-Story
- Adversarial-Test-Promotion und Quarantine-Workflow (`FK-48` Detail) — Folge-Story
- LLM-Assessment-Sidecar (`implementation-phase.A7`) — bewusst nicht in der Erst-Welle
- Worker-Health-Score/Intervention-Events — bewusst nicht in der Erst-Welle
- Hook-Commit-Failure-Klassifikation (`implementation-phase.A8`) — Folge-Story
- tool-call-log.jsonl (Sliding-Window) — Folge-Story
- worker_health-Konfiguration in project.yaml — Folge-Story

## 3. Betroffene Dateien

| Datei | Aenderungsart | Beschreibung |
|---|---|---|
| `src/agentkit/implementation/__init__.py` | Neu | |
| `src/agentkit/implementation/worker_session/__init__.py` | Neu | |
| `src/agentkit/implementation/worker_session/session.py` | Neu | `WorkerSession`, `WorkerContext`, `WorkerContextItemKey` |
| `src/agentkit/implementation/worker_loop/__init__.py` | Neu | |
| `src/agentkit/implementation/worker_loop/loop.py` | Neu | `WorkerLoop`, `IncrementStep`, `IncrementInput`, `IncrementResult`, `IncrementSummary`, `DriftEvent` |
| `src/agentkit/implementation/handover/__init__.py` | Neu | |
| `src/agentkit/implementation/handover/packager.py` | Neu | `HandoverPackager`, `HandoverData`, `ACStatus` |
| `src/agentkit/implementation/manifest/__init__.py` | Neu | |
| `src/agentkit/implementation/manifest/manifest.py` | Neu | `WorkerManifest`, `WorkerManifestStatus` |
| `src/agentkit/pipeline/phases/implementation/phase.py` | Modifiziert | BLOCKED-Exit liest worker-manifest; Orchestrator-Trennlinie statt while True |
| `src/agentkit/verify_system/adversarial_orchestrator/spawn.py` | Neu | `AdversarialSpawner`, `AdversarialTarget`, `AdversarialSpawnRequest` |
| `src/agentkit/verify_system/adversarial_orchestrator/challenger.py` | Modifiziert | Layer-3-Aufruf nutzt AdversarialSpawner |
| `src/agentkit/governance/protected_paths.py` | Modifiziert | `_temp/adversarial/` als Protected-Path ergaenzt |
| `tests/unit/implementation/...` | Neu | Pro Sub-Komponente |
| `tests/integration/pipeline/test_blocked_exit.py` | Neu | E2E BLOCKED |
| `tests/integration/verify_system/test_adversarial_spawn.py` | Neu | E2E Adversarial |
| `tests/integration/pipeline/test_orchestrator_trennlinie.py` | Neu | E2E Remediation-Worker-Spawn |
| `tests/contract/implementation/test_handover_schema.py` | Neu | Pflichtfeld-Pinning |
| `tests/contract/implementation/test_worker_manifest.py` | Neu | Status + BLOCKED-Pflichtfelder |

## 4. Akzeptanzkriterien

1. **Paket `src/agentkit/implementation/` existiert** mit Subs `worker_session/`, `worker_loop/`, `handover/`, `manifest/`.
2. **`WorkerSession.resolve_worker_context`** liest StoryContext und liefert typisierten `WorkerContext`.
3. **`WorkerLoop.run_increment`** durchlaeuft die vier Schritte mit `IncrementStep`-StrEnum.
4. **`HandoverPackager.package`** erzeugt handover.json mit allen sieben Pflichtfeldern; persistiert via ArtifactManager (ArtifactClass.HANDOVER).
5. **`WorkerManifest`** ist Pydantic-Modell mit drei Status. Validator: bei BLOCKED sind drei Pflichtfelder gesetzt.
6. **BLOCKED-Exit**: `ImplementationPhaseHandler.on_enter` liest worker-manifest.json **vor** dem QA-Subflow; bei `status=BLOCKED` liefert es sofort `HandlerResult.ESCALATED` mit Manifest-Details in `suggested_reaction`.
7. **Invariante `worker_blocked_escalates`** ist erfuellt: Integration-Test bestaetigt das.
8. **Adversarial-Spawner**: `AdversarialSpawner.derive_targets(layer2_findings)` liefert mindestens einen `AdversarialTarget` pro BLOCKING-Finding mit Test-Anker. `request_spawn` schreibt `agents_to_spawn`-Feld in PhaseState.
9. **Sandbox-Pfad**: alle Adversarial-Spawns nutzen `_temp/adversarial/{story_id}/{epoch}/`; Pfad ist Protected (Test).
10. **Orchestrator-Trennlinie**: bei QA-FAIL + CONTINUE_REMEDIATION setzt der ImplementationPhaseHandler `agents_to_spawn` und gibt `YIELDED` zurueck; kein inline-Remediation-Loop mehr.
11. **Pflichtbefehle gruen**: pytest unit + integration + contract; mypy --strict; ruff clean; Coverage haelt 85%.

## 5. Definition of Done

- AK 1-11 erfuellt.
- `.venv\Scripts\python -m pytest tests/unit/implementation tests/integration/pipeline tests/integration/verify_system tests/contract/implementation -q` gruen.
- `mypy --strict` gruen, `ruff check src tests` gruen.
- Aenderungen committed auf `main`.

## 6. Konzept-Referenzen (autoritativ)

- **FK-26 §26.2/26.3/26.7/26.8/26.11.2** — Worker-Komponenten
- **FK-27 §27.6** — Adversarial-Spawn
- **FK-48** — Adversarial Testing Runtime
- **`formal.implementation.invariants §worker_blocked_escalates`**

## 7. Guardrail-Referenzen

- **FIX THE MODEL, NOT THE SYMPTOM**: ImplementationHandler liest endlich das Worker-Manifest; Invariante kann pruefen.
- **ZERO DEBT**: Worker-Module vollstaendig; kein "spaeter HandoverPackager bauen"-TODO.
- **FAIL CLOSED**: BLOCKED-Status -> ESCALATED ohne Umweg.
- **NO ERROR BYPASSING**: ImplementationPhaseHandler kann nicht den Manifest-Check ueberspringen.

## 8. Hinweise fuer den Sub-Agent

- WorkerSession + WorkerLoop + HandoverPackager + WorkerManifest sind vier eigenstaendige Submodule — eine pro Verzeichnis. Tests pro Sub.
- Adversarial-Spawn: die `agents_to_spawn`-Feld-Mechanik in PhaseState muss ergaenzt werden, falls noch nicht vorhanden. Engine konsumiert es bei Phase-Re-Entry.
- AK2 NICHT veraendern.
