# AG3-046: ExplorationReview — dreistufiges Exit-Gate

**Typ:** Implementation
**Groesse:** L
**Abhaengigkeiten:** AG3-021 (Enums), AG3-026 (VerifySystem-Top), AG3-037 (Exploration-EventTypes), AG3-041 (Remediation-Loop), AG3-043 (Layer-2-StructuredEvaluator), AG3-045 (ExplorationPhaseHandler-Skelett)
**Quell-Konzepte (autoritativ, in dieser Reihenfolge):**
- `FK-23 §23.5` (Dreistufiges Exit-Gate)
- `FK-23 §23.5.1` (Stufe 1 Dokumententreue, binaer)
- `FK-23 §23.5.2` (Stufe 2a Design-Review, Remediation-Loop max 3 Runden)
- `FK-23 §23.5.3` (Stufe 2b Design-Challenge)
- `FK-25 §25.4.2` (ChangeFrame editierbar bis Gate-PASS)
- `formal.exploration.state-machine`

---

## 1. Kontext

THEME-010 aus `stories/_priorisierungsempfehlung.md`. Befund `exploration-and-design.A3`: ExplorationReview fehlt — kein Orchestrator fuer den Review-Zyklus; Aufruf von `verify-system.LlmEvaluator` und `verify-system.ConformanceService` fehlt. `exploration-and-design.B3`: Workflow-DSL hat Yield-Points fuer `design_review` und `design_challenge`, aber keine vollstaendige Gate-Stufenmodellierung.

AG3-045 hat den **Provisorium-Pfad** in `ExplorationPhaseHandler` mit direktem `APPROVED`-Set. Diese Story ersetzt das durch das echte dreistufige Gate.

## 2. Scope

### 2.1 In Scope

#### 2.1.1 `ExplorationReview` Sub-Komponente (FK-23 §23.5)

`src/agentkit/pipeline/phases/exploration/review/`:

```python
class ExplorationReview:
    def __init__(
        self,
        stage1_doc_fidelity: DocFidelityChecker,
        stage2a_design_review: DesignReviewRunner,
        stage2b_design_challenge: DesignChallengeRunner | None,
        artifact_manager: ArtifactManager,
    ) -> None: ...

    def run(self, change_frame: ChangeFrame, ctx: PhaseContext) -> ExplorationGateResult: ...

class ExplorationGateResult(BaseModel):
    stage1_result: DocFidelityResult
    stage2a_result: DesignReviewResult
    stage2b_result: DesignChallengeResult | None
    overall_status: ExplorationGateStatus  # APPROVED | REJECTED | PENDING
    review_rounds: int
    model_config = ConfigDict(frozen=True, extra="forbid")
```

#### 2.1.2 Stufe 1 — Dokumententreue (FK-23 §23.5.1)

`src/agentkit/pipeline/phases/exploration/review/doc_fidelity.py`:

```python
class DocFidelityChecker:
    def __init__(self, structured_evaluator: StructuredEvaluator) -> None: ...

    def check(self, change_frame: ChangeFrame) -> DocFidelityResult:
        # Aufruf StructuredEvaluator mit ReviewerRole.DOC_FIDELITY (aus AG3-043)
        # Binaeres Ergebnis: PASS | FAIL
        # Bei FAIL: ChangeFrame wird zurueck an Worker (oder neuer Drafting-Lauf)
        ...

class DocFidelityResult(BaseModel):
    status: Literal["pass", "fail"]
    findings: list[Finding]
    evaluator_result_ref: ArtifactReference
```

Aufruf von `StructuredEvaluator` (aus AG3-043) mit ReviewerRole.DOC_FIDELITY. Template `qa-doc-fidelity.md` ist in AG3-043 angelegt.

#### 2.1.3 Stufe 2a — Design-Review mit Remediation-Loop (FK-23 §23.5.2)

`src/agentkit/pipeline/phases/exploration/review/design_review.py`:

```python
class DesignReviewRunner:
    def __init__(self, structured_evaluator: StructuredEvaluator, max_rounds: int = 3) -> None: ...

    def run(self, change_frame: ChangeFrame, doc_fidelity_findings: list[Finding]) -> DesignReviewResult: ...

class DesignReviewResult(BaseModel):
    status: Literal["pass", "fail", "escalated"]
    review_rounds: int
    findings_per_round: list[list[Finding]]
    final_change_frame_ref: ArtifactReference
```

Remediation-Loop: nutzt `RemediationLoopController` aus AG3-041 mit max_rounds=3. Pro Runde: StructuredEvaluator-Aufruf mit ReviewerRole.SEMANTIC_REVIEW (Design-Review-Rolle); bei FAIL und round < 3: ChangeFrame wird angepasst (Worker oder LLM-gesteuert) und neue Runde gestartet; bei round >= 3 und FAIL: ESCALATED.

#### 2.1.4 Stufe 2b — Design-Challenge (FK-23 §23.5.3)

`src/agentkit/pipeline/phases/exploration/review/design_challenge.py`:

```python
class DesignChallengeRunner:
    def __init__(self, structured_evaluator: StructuredEvaluator) -> None: ...

    def run(self, change_frame: ChangeFrame, prior_results: tuple[DocFidelityResult, DesignReviewResult]) -> DesignChallengeResult: ...

class DesignChallengeResult(BaseModel):
    status: Literal["pass", "fail"]
    challenge_summary: str
    addressed_issues: list[str]
    evaluator_result_ref: ArtifactReference
```

Aktiv nur in einer Variante (laut FK-23 §23.5.3 ist Design-Challenge eine optionale dritte Stufe, abhaengig vom Story-Mandat). Diese Story stellt die Klasse bereit; Aktivierungslogik wird in AG3-047 (MandateClassification) verkabelt.

#### 2.1.5 Workflow-DSL Gate-Stufenmodellierung (exploration-and-design.B3)

`src/agentkit/process/language/gates.py` (oder Modul-Erweiterung):

Typisierte Gate-Stufen als Pydantic-Modelle:

```python
class GateStage(BaseModel):
    stage_id: ExplorationGateStage  # StrEnum: DOC_FIDELITY | DESIGN_REVIEW | DESIGN_CHALLENGE
    yield_point: str
    required: bool
    rollback_on_fail: bool

class ExplorationGateStage(StrEnum):
    DOC_FIDELITY = "doc_fidelity"
    DESIGN_REVIEW = "design_review"
    DESIGN_CHALLENGE = "design_challenge"
```

Workflow-DSL `_build_implementation_workflow` wird angepasst, damit die zwei existing Yield-Points (`design_review`, `design_challenge`) mit typisierten GateStages annotiert sind.

#### 2.1.6 `ExplorationPhaseHandler` Provisorium ersetzen

`src/agentkit/pipeline/phases/exploration/phase.py:ExplorationPhaseHandler.on_enter`:

- Provisorium-Pfad aus AG3-045 (direktes `gate_status=APPROVED`) wird ersetzt durch `ExplorationReview.run(change_frame, ctx)`.
- Result wird in `ExplorationPayload.gate_status` geschrieben (APPROVED/REJECTED/PENDING entsprechend `overall_status`).
- Bei ESCALATED in Stage 2a: `HandlerResult.ESCALATED` mit Begruendung; Story bleibt in Exploration-Phase, Operator-Eingriff noetig.

#### 2.1.7 Tests

- Unit-Tests fuer `DocFidelityChecker` (PASS/FAIL-Pfade)
- Unit-Tests fuer `DesignReviewRunner` (Remediation-Loop, Eskalation bei round >= 3)
- Unit-Tests fuer `DesignChallengeRunner`
- Unit-Tests fuer `ExplorationReview.run` (Orchestrierung der drei Stages)
- Integration-Test fuer `ExplorationPhaseHandler.on_enter` mit gemockten StructuredEvaluators
- Integration-Test: Eskalation in Stage 2a fuehrt zu `HandlerResult.ESCALATED` und PhaseState bleibt `EXPLORATION` (kein Wechsel zu IMPLEMENTATION)
- Contract-Test `tests/contract/exploration/test_review_stages.py`: drei Gate-Stages typisiert
- Negativpfad-Test: Gate REJECTED -> Implementation-Guard greift (kombiniert mit AG3-045-Test)

### 2.2 Out of Scope

- MandateClassification (FK-25 §25.3-25.6, exploration-and-design.A4) — AG3-047
- DesignFreezeMarker (FK-23 §23.4.3, exploration-and-design.A5) — AG3-047
- Telemetrie-Events `mandate_classification`/`fine_design_decision`/`scope_explosion_check`/`impact_exceedance_check` — AG3-047 (EventTypes sind in AG3-037 vorhanden)
- Feindesign-Subprozess (FK-25 §25.5) — AG3-047 (Mandate-Klassifikation triggert ggf. den Subprozess)
- Scope-Explosion-Erkennung (FK-25 §25.6) — AG3-047
- Drift-Erkennung im Implementation — gehoert zu THEME-009/AG3-044
- Cleanup `pipeline_engine/verify_phase`-Artefakte — bereits THEME-001
- LLM-Worker-Drafting (volle LLM-Generierung des ChangeFrames) — Folge-Story

## 3. Betroffene Dateien

| Datei | Aenderungsart | Beschreibung |
|---|---|---|
| `src/agentkit/pipeline/phases/exploration/review/__init__.py` | Neu | |
| `src/agentkit/pipeline/phases/exploration/review/review.py` | Neu | `ExplorationReview`, `ExplorationGateResult` |
| `src/agentkit/pipeline/phases/exploration/review/doc_fidelity.py` | Neu | `DocFidelityChecker`, `DocFidelityResult` |
| `src/agentkit/pipeline/phases/exploration/review/design_review.py` | Neu | `DesignReviewRunner`, `DesignReviewResult` |
| `src/agentkit/pipeline/phases/exploration/review/design_challenge.py` | Neu | `DesignChallengeRunner`, `DesignChallengeResult` |
| `src/agentkit/process/language/gates.py` | Modifiziert | `GateStage`, `ExplorationGateStage` |
| `src/agentkit/process/language/definitions.py` | Modifiziert | Workflow-DSL annotiert Yield-Points typisiert |
| `src/agentkit/pipeline/phases/exploration/phase.py` | Modifiziert | Provisorium ersetzt durch ExplorationReview-Aufruf |
| `tests/unit/pipeline/phases/exploration/review/...` | Neu | Pro Sub |
| `tests/integration/pipeline/exploration/test_review_e2e.py` | Neu | E2E |
| `tests/contract/exploration/test_review_stages.py` | Neu | Gate-Pinning |

## 4. Akzeptanzkriterien

1. **`ExplorationReview`-Klasse existiert** und ruft Stage 1 -> Stage 2a -> ggf. Stage 2b in der konzept-normierten Reihenfolge.
2. **`DocFidelityChecker`** ruft `StructuredEvaluator` mit `ReviewerRole.DOC_FIDELITY`; liefert binaer `pass`/`fail`.
3. **`DesignReviewRunner`** ruft `StructuredEvaluator` mit `ReviewerRole.SEMANTIC_REVIEW` in Remediation-Loop (max 3 Runden, nutzt `RemediationLoopController` aus AG3-041).
4. **Stage 2a Eskalation**: bei FAIL nach Runde 3 -> `status=escalated`.
5. **`DesignChallengeRunner`** existiert mit `run(change_frame, prior_results)`; Aktivierungslogik bleibt offen (kommt in AG3-047).
6. **`ExplorationGateStage`-StrEnum** mit drei Werten (`DOC_FIDELITY`, `DESIGN_REVIEW`, `DESIGN_CHALLENGE`).
7. **`ExplorationPhaseHandler.on_enter` ruft `ExplorationReview.run`** und ersetzt damit den Provisorium-Pfad aus AG3-045. Der `# TODO AG3-046`-Kommentar ist entfernt.
8. **Result-Mapping**: `ExplorationReview.overall_status == APPROVED` -> `ExplorationPayload.gate_status = APPROVED`; analog REJECTED/PENDING.
9. **ESCALATED-Pfad**: bei Stage 2a Eskalation -> `HandlerResult.ESCALATED` mit `suggested_reaction` aus DesignReviewResult.
10. **Negativpfad-Test**: Gate REJECTED -> Implementation-Phase wird **nicht** freigegeben (Guard `exploration_gate_approved` liefert False, bestaetigt durch Test).
11. **Pflichtbefehle gruen**: pytest unit + integration + contract; mypy --strict; ruff clean; Coverage haelt 85%.

## 5. Definition of Done

- AK 1-11 erfuellt.
- `.venv\Scripts\python -m pytest tests/unit/pipeline/phases/exploration tests/integration/pipeline/exploration tests/contract/exploration -q` gruen.
- `mypy --strict` gruen, `ruff check src tests` gruen.
- Aenderungen committed auf `main`.

## 6. Konzept-Referenzen (autoritativ)

- **FK-23 §23.5** — Exit-Gate
- **FK-23 §23.5.1** — Stufe 1
- **FK-23 §23.5.2** — Stufe 2a
- **FK-23 §23.5.3** — Stufe 2b
- **FK-25 §25.4.2** — ChangeFrame
- **`formal.exploration.state-machine`** — Stufen-Lifecycle

## 7. Guardrail-Referenzen

- **FIX THE MODEL, NOT THE SYMPTOM**: Provisorium aus AG3-045 ersetzt; echtes Gate aktiv.
- **ZERO DEBT**: alle drei Stufen typisiert.
- **FAIL CLOSED**: Stage 2a Eskalation -> Story bleibt in Exploration.
- **NO ERROR BYPASSING**: kein Pfad direkt zu APPROVED ohne Stage 1 PASS.

## 8. Hinweise fuer den Sub-Agent

- Stage 2b-Aktivierung: prueft `ChangeFrame`-Mandat-Hinweise; falls leer, ueberspringen. Die volle Mandate-Klassifikation kommt in AG3-047.
- AK2 NICHT veraendern.
