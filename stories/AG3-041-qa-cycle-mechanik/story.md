# AG3-041: QA-Zyklus-Mechanik — advance_qa_cycle + evidence_epoch + Artefakt-Invalidierung + Remediation-Loop

**Typ:** Implementation
**Groesse:** L
**Abhaengigkeiten:** AG3-021, AG3-022, AG3-023 (ArtifactManager), AG3-024 (PhaseEnvelope), AG3-025 (QA-Zyklus-Felder im PhaseState), AG3-026 (VerifySystem-Top)
**Quell-Konzepte (autoritativ, in dieser Reihenfolge):**
- `FK-27 §27.2` (QA-Zyklus-Identitaeten, advance_qa_cycle, 11 Artefaktdateien)
- `FK-27 §27.2.2` (QA-Zyklus-State-Machine: idle -> awaiting_qa -> awaiting_policy -> pass | awaiting_remediation -> escalated)
- `FK-38` (Remediation-Loop, max_feedback_rounds)
- `FK-34` (Finding-Resolution, partial/fully/not_resolved)
- `DK-04 §4.6` (Remediation-Modus mit Vorrunden-Findings)
- `formal.verify.state-machine`

---

## 1. Kontext

THEME-009 aus `stories/_priorisierungsempfehlung.md`. Befund `verify-system.A2`: QA-Zyklus-Mechanik fehlt — `advance_qa_cycle`, `qa_cycle_id`, `qa_cycle_round`, `evidence_epoch`, `evidence_fingerprint` und die Invalidierungslogik fuer 11 Artefaktdateien.

`AG3-025` hat die Datenfelder geliefert; diese Story bringt die **Mechanik**. Sie umfasst:
- `advance_qa_cycle()` als Aufruf-Pfad
- evidence_fingerprint-Berechnung
- Artefakt-Invalidierung (11 Dateien nach `stale/`)
- Remediation-Loop-Zaehler + ESCALATED-Pfad
- Finding-Resolution im Remediation-Modus

## 2. Scope

### 2.1 In Scope

#### 2.1.1 `advance_qa_cycle()` (FK-27 §27.2)

Neues Modul `src/agentkit/verify_system/qa_cycle/lifecycle.py`:

```python
class QaCycleLifecycle:
    """
    Verwaltet QA-Zyklus-Identitaeten und Uebergaenge.
    """
    def __init__(
        self,
        phase_envelope_store: PhaseEnvelopeStore,
        artifact_manager: ArtifactManager,
        projection_accessor: ProjectionAccessor,
    ) -> None: ...

    def start_cycle(self, ctx: VerifyContextBundle, qa_context: QaContext) -> str:
        # Erzeugt qa_cycle_id (UUID4), setzt qa_cycle_round=1, evidence_epoch=1
        # in PhaseState. Berechnet evidence_fingerprint.
        ...

    def advance_qa_cycle(self, ctx: VerifyContextBundle) -> None:
        # Inkrementiert qa_cycle_round +1, evidence_epoch +1
        # Invalidiert 11 Artefaktdateien (move to stale/)
        # Persistiert via PhaseEnvelopeStore.save
        ...

    def get_current_state(self, ctx: VerifyContextBundle) -> QaCycleState:
        # Liefert qa_cycle_id, round, epoch, fingerprint aus PhaseState
        ...
```

#### 2.1.2 `evidence_fingerprint` (FK-27 §27.2.1)

Berechnung: SHA-256 ueber den **kanonisierten** Inhalt von:
- `git diff origin/main..HEAD --stat` (Story-Branch)
- Modifizierte Dateien (Inhaltshash pro Datei)
- handover.json (falls existent)

Bei wiederholtem Aufruf mit unveraendertem Code: gleicher Fingerprint. Verwendet `hashlib.sha256` deterministisch.

#### 2.1.3 Artefakt-Invalidierung (FK-27 §27.2)

11 Artefaktdateien werden bei `advance_qa_cycle` von `_temp/qa/{story_id}/` nach `_temp/qa/{story_id}/stale/{old_epoch}/` verschoben:

1. `structural_result.json`
2. `semantic_review.json`
3. `qa_review.json`
4. `doc_fidelity.json`
5. `adversarial_result.json`
6. `verify_decision.json`
7. `context_sufficiency.json` (falls existent)
8. `import_resolution.json` (falls existent)
9. `bundle_manifest.json` (falls existent)
10. `feedback.json`
11. `policy_verdict.json`

Pfade exakt aus FK-27 §27.2 spezifiziert. Wenn eine Datei nicht existiert: skip ohne Fehler.

Invalidierungs-Aufruf laeuft ueber ArtifactManager (jeder Stale-Move emittiert ein `artifact_invalidated`-Telemetrie-Event). Aktive Implementation: Datei-Move (atomic_rename).

#### 2.1.4 Remediation-Loop-Zaehler + ESCALATED (FK-38, verify-system.B6)

`src/agentkit/verify_system/remediation/loop_counter.py`:

```python
class RemediationLoopController:
    def __init__(self, max_feedback_rounds: int = 3) -> None: ...

    def check_and_advance(self, qa_cycle_state: QaCycleState, verify_decision: PolicyVerdictResult) -> RemediationDecision:
        # Bei verdict=PASS -> CONTINUE_TO_CLOSURE
        # Bei verdict=FAIL und round < max_feedback_rounds -> CONTINUE_REMEDIATION
        # Bei verdict=FAIL und round >= max_feedback_rounds -> ESCALATE
        ...

class RemediationDecision(StrEnum):
    CONTINUE_TO_CLOSURE = "continue_to_closure"
    CONTINUE_REMEDIATION = "continue_remediation"
    ESCALATE = "escalate"
```

`max_feedback_rounds` ist konfigurierbar (Pipeline-Config); Default 3.

#### 2.1.5 Finding-Resolution im Remediation-Modus (DK-04 §4.6, verify-system.B5)

`src/agentkit/verify_system/remediation/finding_resolution.py`:

```python
class FindingResolutionStatus(StrEnum):
    FULLY_RESOLVED = "fully_resolved"
    PARTIALLY_RESOLVED = "partially_resolved"
    NOT_RESOLVED = "not_resolved"

class FindingResolutionAssessor:
    def assess(self, previous_findings: list[Finding], current_findings: list[Finding]) -> dict[FindingId, FindingResolutionStatus]:
        # Matched alte gegen neue Findings via Finding-ID/Check-ID
        # Wenn altes Finding nicht mehr in current -> FULLY_RESOLVED
        # Wenn altes Finding in current mit reduzierter Severity -> PARTIALLY_RESOLVED
        # Wenn altes Finding mit gleicher/hoeherer Severity -> NOT_RESOLVED
        ...
```

Diese Assessor-Logik laeuft im Remediation-Modus VOR dem Layer-2-Aufruf — Vorrunden-Findings werden als Kontext gereicht. Voll-Integration mit Layer-2-LLM-Aufruf ist Aufgabe von AG3-043.

#### 2.1.6 Closure-Block bei offenen Findings

`VerifyDecision.has_open_findings()` Helper:
- Wenn `qa_context in {IMPLEMENTATION_REMEDIATION, EXPLORATION_REMEDIATION}` und mind. eine `FindingResolutionStatus = NOT_RESOLVED`: Decision-Flag `closure_blocked=True`
- Wird vom Closure-Phase-Handler konsumiert (Closure-Phase nicht hier; Voll-Integration in Folge-Story)

#### 2.1.7 VerifySystem-Integration

`VerifySystem.run_qa_subflow` aus AG3-026 wird erweitert:
- Aufruf `qa_cycle_lifecycle.start_cycle` (wenn `qa_cycle_id == None`) oder `advance_qa_cycle` (wenn Remediation)
- evidence_fingerprint wird im Result ausgewiesen
- Aufruf `remediation_loop_controller.check_and_advance` nach Policy-Engine
- Falls ESCALATE: setze `PolicyVerdictResult.verdict = FAIL` und `escalated=True`

#### 2.1.8 Tests

- Unit-Tests fuer `QaCycleLifecycle.start_cycle` / `advance_qa_cycle` (Felder im PhaseState korrekt; 11 Dateien verschoben)
- Unit-Tests fuer `evidence_fingerprint` (Determinismus: gleicher Code -> gleicher Hash)
- Unit-Tests fuer Artefakt-Invalidierung (Mock-Filesystem, alle 11 Pfade)
- Unit-Tests fuer `RemediationLoopController` (PASS, FAIL+continue, FAIL+escalate)
- Unit-Tests fuer `FindingResolutionAssessor` (alle drei Status)
- Integration-Test: VerifySystem-Lauf mit Remediation-Loop; advance_qa_cycle wird zwischen Runden aufgerufen; bei max-Round-Erschoepfung ESCALATED
- Contract-Test `tests/contract/verify_system/test_qa_cycle.py`: 11 Pflicht-Artefaktpfade exakt nach FK-27 §27.2

### 2.2 Out of Scope

- Layer 1 strukturelle Vollausbau (`verify-system.B1`) — AG3-042
- Layer 2 echte LLM-Aufrufe (`verify-system.B2`) — AG3-043
- Adversarial-Spawn (`verify-system.A8`) — AG3-044
- Stage-Registry-Bindung (`verify-system.B3`) — AG3-043 (im Rahmen Layer 2)
- Orchestrator-Trennlinie fuer Remediation-Worker-Spawn (`pipeline-framework.C3`) — AG3-044
- ConformanceService, EvidenceAssembler, ImportResolver, Request-DSL (`verify-system.A3-A7`) — bewusst nicht in der Erst-Welle
- guard.llm_reviews/guard.multi_llm als BLOCKING-Gates (`verify-system.C3`) — AG3-042 (Layer 1)
- Prompt-Templates qa-semantic/qa-adversarial (`verify-system.B7`) — kommt mit AG3-043

## 3. Betroffene Dateien

| Datei | Aenderungsart | Beschreibung |
|---|---|---|
| `src/agentkit/verify_system/qa_cycle/__init__.py` | Neu | Re-Export |
| `src/agentkit/verify_system/qa_cycle/lifecycle.py` | Neu | `QaCycleLifecycle` |
| `src/agentkit/verify_system/qa_cycle/fingerprint.py` | Neu | `compute_evidence_fingerprint` |
| `src/agentkit/verify_system/qa_cycle/invalidation.py` | Neu | Artefakt-Move-Logik |
| `src/agentkit/verify_system/remediation/loop_counter.py` | Neu | `RemediationLoopController`, `RemediationDecision` |
| `src/agentkit/verify_system/remediation/finding_resolution.py` | Neu | `FindingResolutionAssessor`, `FindingResolutionStatus` |
| `src/agentkit/verify_system/remediation/feedback.py` | Modifiziert | `RemediationFeedback` traegt FindingResolutionStatus pro Vorrunden-Finding |
| `src/agentkit/verify_system/system.py` | Modifiziert | VerifySystem.run_qa_subflow ruft QaCycleLifecycle + LoopController |
| `src/agentkit/verify_system/contract.py` | Modifiziert | `PolicyVerdictResult` traegt `escalated: bool`, `closure_blocked: bool` |
| `tests/unit/verify_system/qa_cycle/...` | Neu | |
| `tests/unit/verify_system/remediation/...` | Neu/Erweitert | |
| `tests/integration/verify_system/test_remediation_loop.py` | Neu | E2E |
| `tests/contract/verify_system/test_qa_cycle.py` | Neu | Vertrags-Pinning |

## 4. Akzeptanzkriterien

1. **`QaCycleLifecycle.start_cycle`** erzeugt `qa_cycle_id` (UUID4), setzt `qa_cycle_round=1`, `evidence_epoch=1`, berechnet `evidence_fingerprint`, persistiert in PhaseState.
2. **`QaCycleLifecycle.advance_qa_cycle`** inkrementiert `qa_cycle_round` und `evidence_epoch`, recompute fingerprint, verschiebt die 11 Artefaktdateien nach `stale/{old_epoch}/`.
3. **`compute_evidence_fingerprint`** ist deterministisch: gleicher Code-Stand -> gleicher Hash.
4. **`RemediationLoopController.check_and_advance`** liefert die korrekte Decision je nach Verdict + Round (PASS -> CONTINUE_TO_CLOSURE; FAIL+round<max -> CONTINUE_REMEDIATION; FAIL+round>=max -> ESCALATE).
5. **`FindingResolutionAssessor.assess`** klassifiziert alte Findings korrekt in `FULLY_RESOLVED`/`PARTIALLY_RESOLVED`/`NOT_RESOLVED`.
6. **`VerifySystem.run_qa_subflow` integriert QaCycleLifecycle + LoopController**: bei Erstaufruf start_cycle; bei Remediation-Context advance_qa_cycle. Bei ESCALATE wird `PolicyVerdictResult.escalated=True` gesetzt.
7. **Closure-Block-Flag**: `PolicyVerdictResult.closure_blocked=True`, wenn im Remediation-Modus mind. ein offenes (NOT_RESOLVED) Vorrunden-Finding existiert.
8. **Pflicht-Artefakt-Pfade** in `invalidation.py` als Konstante; Contract-Test pinnt die 11 Pfade nach FK-27 §27.2.
9. **Pflichtbefehle gruen**: pytest unit + integration + contract; mypy --strict; ruff clean; Coverage haelt 85%.

## 5. Definition of Done

- AK 1-9 erfuellt.
- `.venv\Scripts\python -m pytest tests/unit/verify_system tests/integration/verify_system tests/contract/verify_system -q` gruen.
- `mypy --strict` gruen, `ruff check src tests` gruen.
- Aenderungen committed auf `main`.

## 6. Konzept-Referenzen (autoritativ)

- **FK-27 §27.2** — QA-Zyklus-Identitaeten + 11 Pflicht-Artefakte
- **FK-27 §27.2.2** — State-Machine
- **FK-38** — Remediation-Loop
- **FK-34** — Finding-Resolution
- **DK-04 §4.6** — Remediation-Modus
- **`formal.verify.state-machine`** — formale Spec

## 7. Guardrail-Referenzen

- **FIX THE MODEL, NOT THE SYMPTOM**: QA-Zyklus-Identitaeten endlich operativ; nicht nur Datenmodell.
- **ZERO DEBT**: Remediation-Loop schliesst sich; kein impliziter `while True`-Inline-Loop.
- **FAIL CLOSED**: ESCALATED ist hart; keine stille Wiederholung.
- **NO ERROR BYPASSING**: max_feedback_rounds darf nicht uebersprungen werden.

## 8. Hinweise fuer den Sub-Agent

- 11 Pflicht-Artefakte sind aus FK-27 §27.2 abzuschreiben (lies dort die Datei-Liste).
- evidence_fingerprint: nutze `git diff`-Output deterministisch (gleicher Subprozess-Aufruf, gleiche Sortierung).
- AK2 NICHT veraendern.
