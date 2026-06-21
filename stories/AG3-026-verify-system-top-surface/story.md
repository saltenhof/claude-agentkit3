# AG3-026: VerifySystem Top-Surface — run_qa_subflow(...) -> PolicyVerdict

**Typ:** Implementation
**Groesse:** M
**Abhaengigkeiten:** AG3-021 (`QaContext`, `PolicyVerdict`, `Severity`), AG3-022 (`ArtifactEnvelope`), AG3-023 (`ArtifactManager`)
**Quell-Konzepte (autoritativ, in dieser Reihenfolge):**
- `concept/_meta/bc-cut-decisions.md §Verify als Capability (Variante Y)`
- `concept/_meta/bc-cut-decisions.md §QA-Subflow-Vertrag`
- `concept/_meta/bc-cut-decisions.md §BC 2 verify-system`
- `FK-27 §27.3` (QA-Subflow-Top)
- `formal.verify.state-machine`
- `formal.verify.invariants`

---

## 1. Kontext

THEME-005 aus `stories/_priorisierungsempfehlung.md`. Befund `verify-system.A1`: kein oeffentliches `VerifySystem`-Objekt mit der normierten Signatur `run_qa_subflow(ctx, story_id, qa_context, target) -> PolicyVerdict`. Solange diese Top-Surface fehlt, koennen weder pipeline-framework, implementation-phase noch exploration-and-design typsicher gegen verify-system integrieren.

Diese Story liefert die **Top-Surface als typisierten Vertrag mit verkabeltem Skelett**. Layer 1-4 bleiben dahinter im aktuellen (teilweise stub-) Zustand; ihre inhaltliche Vervollstaendigung ist THEME-009. Die Top-Surface ist eigenstaendig pruefbar: Tests verifizieren Vertragsform (Signaturen, Return-Type, Fehlertypen, fail-closed-Pfade), nicht die Layer-Logik.

<!-- AG3-026 deep-review: Hinweis zum oeffentlichen Vertrag. -->
**Normativer Vertrag (BC-Cut + FK-27 + formal.verify.commands):**
`VerifySystem.run_qa_subflow(ctx, story_id, qa_context, target: ArtifactReference) -> PolicyVerdict`.
Der Return-Type ist exakt `PolicyVerdict` (PASS | FAIL). Detaildaten werden ueber QA-Artefakte und Read-Models transportiert, nicht ueber den Return-Type. Interne Ergebnisobjekte (z.B. `QaSubflowExecutionResult`) sind erlaubt, aber NICHT Teil der oeffentlichen Surface.

## 2. Scope

### 2.1 In Scope

#### 2.1.1 `VerifySystem`-Top-Klasse

Neues Modul `src/agentkit/verify_system/system.py` (oder Erweiterung `__init__.py`):

```python
class VerifySystem:
    def __init__(
        self,
        layer_1: StructuralChecker,
        layer_2: LlmEvaluatorRunner,
        layer_3: AdversarialOrchestrator,
        policy_engine: PolicyEngine,
        artifact_manager: ArtifactManager,
    ) -> None: ...

    def run_qa_subflow(
        self,
        ctx: VerifyContextBundle,
        story_id: str,
        qa_context: QaContext,
        target: ArtifactReference,
    ) -> PolicyVerdict:
        ...
```

<!-- AG3-026 deep-review: target ist ArtifactReference (BC-Cut + FK-27 + formal.verify.commands); VerifyTarget bleibt internes Wrapper-Modell. -->

`VerifyContextBundle` ist ein neues typisiertes Pydantic-Modell in `src/agentkit/verify_system/contract.py`:

- `VerifyContextBundle`: `run_id`, `story_dir`, `phase_envelope` (Read-only), `attempt`

`VerifyTarget` ist ein **internes** Wrapper-Modell, das `VerifySystem` aus `ctx + target: ArtifactReference` ableitet. Es ist KEIN Methodenparameter und KEIN `__init__.py`-Export:

- `VerifyTarget` (intern): `artifact_ref: ArtifactReference`, `target_type: VerifyTargetType`, `branch_ref: str | None`, `commit_sha: str | None`, `paths_in_scope: tuple[str, ...]`
- `VerifyTargetType` StrEnum: `IMPLEMENTATION`, `EXPLORATION`, `BUGFIX`

#### 2.1.2 QA-Context-Routing (concept/_meta/bc-cut-decisions.md §QA-Subflow-Vertrag)

`run_qa_subflow` verzweigt anhand `qa_context: QaContext`:

- `IMPLEMENTATION_INITIAL`/`IMPLEMENTATION_REMEDIATION` -> volle 4-Schichten (Layer 1+2+3+Policy) gemaess FK-27 §27.3 + formal.verify.scenarios (POST_IMPLEMENTATION/POST_REMEDIATION)
- `EXPLORATION_INITIAL`/`EXPLORATION_REMEDIATION` -> reduzierte Layer-Auswahl (Design-Review-Schicht + Policy) gemaess QA-Subflow-Vertrag im BC-Cut

<!-- AG3-026 deep-review: Routing fuer Exploration ist im BC-Cut/Exploration-Vertrag normiert, nicht in FK-27 selbst. Die konkrete Layer-Reduktion fuer Exploration wird in dieser Story als Konfigurationstabelle gepinnt; FK-27 §27.3 begruendet primaer den Implementation-Pfad. -->

`select_layers(qa_context: QaContext) -> tuple[QALayer, ...]` ist Helper-Funktion und Teil der Top-Surface.

#### 2.1.3 PolicyVerdict-Antwort

<!-- AG3-026 deep-review: PolicyVerdictResult als oeffentlicher Return-Type war Konzept-Bruch (BC-Cut + FK-27 + formal.verify.commands). Korrektur: Return-Type ist exakt PolicyVerdict; Details ueber QA-Artefakte. -->

`run_qa_subflow(...)` gibt **exakt** `PolicyVerdict` zurueck (`PASS` oder `FAIL`). Das ist der oeffentliche Capability-Vertrag aus BC-Cut, FK-27 §27.7 und `formal.verify.commands`.

Detaildaten (Findings, Layer-Ergebnisse, Artefakt-Refs, QA-Zyklus-Identitaeten) werden NICHT ueber den Return-Type transportiert, sondern ueber:
- zyklusgebundene QA-Artefakte (`structural.json`, `qa_review.json`, `semantic_review.json`, `doc_fidelity.json`, `adversarial.json`, `decision.json`) gemaess FK-27 §27.7 mit ArtifactEnvelope + ProducerRegistry
- Read-Model-/Projection-Records (Folge-Stories)

Optional internes Modell (nicht exportiert, nicht Teil der Top-Surface):

```python
class QaSubflowExecutionResult(BaseModel):
    verdict: PolicyVerdict
    stage_results: tuple[StageResult, ...]
    artifact_refs: tuple[ArtifactReference, ...]
    blocking_failures: int
    major_failures: int
    minor_failures: int
    model_config = ConfigDict(frozen=True, extra="forbid")
```

`qa_cycle_id`, `qa_cycle_round`, `evidence_epoch`, `evidence_fingerprint` sind QA-Zyklus-Identitaeten aus PhaseState (AG3-025). Wenn `ctx.phase_envelope` bzw. PhaseState diese Werte traegt, schreibt `VerifySystem` sie in die erzeugten QA-Artefakte. Das **Befuellen/Invalidieren** dieser Zyklusfelder ist NICHT Scope dieser Story (siehe AG3-041, THEME-009).

#### 2.1.4 Fail-Closed-Wege

`VerifySystem` fail-closed bei:
- ungueltigem `QaContext`-Wert (kann nicht passieren, weil typisiert)
- unbekanntem `target_type`
- fehlendem `ArtifactManager` oder `policy_engine`
- Layer wirft unbekannte Exception -> wird in `LayerExecutionError` gewrappt und als BLOCKING-Finding aggregiert

Eigene Exceptions: `VerifySystemError` (Basis), `VerifyTargetUnknownError`, `LayerExecutionError`. In `src/agentkit/verify_system/errors.py`.

#### 2.1.5 Producer-Registry-Seeds

Beim Modul-Load (`verify_system/__init__.py` Init-Hook, etabliert in AG3-023): die vier QA-Producer registrieren. Diese Story stellt sicher, dass `VerifySystem` ueber den Manager nur registrierte Producer schreibt.

#### 2.1.6 Tests

- Unit-Tests fuer `VerifySystem.run_qa_subflow`:
  - happy path Implementation: alle vier Layer werden in der korrekten Reihenfolge aufgerufen (Layer 1 -> 2 -> 3 -> Policy)
  - happy path Exploration: nur Layer 2 + Policy
  - fail-closed: unbekanntes target_type
  - Layer-Exception wird zu BLOCKING-Finding und PolicyVerdict.FAIL
- Unit-Tests fuer `select_layers(qa_context)`
- Unit-Tests fuer `VerifyContextBundle`, `VerifyTarget`-Modelle (Pflichtfelder, Validators)
- Contract-Test `tests/contract/verify_system/test_top_surface.py`:
  - `VerifySystem.run_qa_subflow` ist als oeffentliche Methode im `__init__.py`-Export verfuegbar
  - Signatur exakt: `(ctx: VerifyContextBundle, story_id: str, qa_context: QaContext, target: ArtifactReference)` <!-- AG3-026 deep-review: target ist ArtifactReference -->
  - Return-Type exakt `PolicyVerdict` (PASS | FAIL)

### 2.2 Out of Scope

- `advance_qa_cycle()`-Mechanik mit Artefakt-Invalidierung (`verify-system.A2`) — THEME-009 (AG3-041)
- Layer-2 echte LLM-Aufrufe + ParallelEvalRunner (`verify-system.B2`) — THEME-009 (AG3-043)
- Adversarial-Spawn (`verify-system.A8`) — THEME-009 (AG3-044)
- Stage-Registry-Bindung (`verify-system.B3`) — THEME-009
- Finding-Resolution-Status (`verify-system.B5`) — THEME-009
- Remediation-Loop-Zaehler / ESCALATED-Pfad (`verify-system.B6`) — THEME-009
- `EvidenceAssembler`, `ImportResolver`, `Request-DSL`, `ConformanceService`, `ContextSufficiencyBuilder` (`verify-system.A3-A7`) — bewusst nicht in der Erst-Welle (Priorisierungsempfehlung §5)
- Divergenz-Quorum (`verify-system.A9`) — Detail-Ausbau
- Layer-1 Erweiterung (Artefakt-/Branch-/Build-/Hygiene-Checks) (`verify-system.B1`) — THEME-009 (AG3-042)
- guard.llm_reviews/guard.multi_llm als BLOCKING-Gates (`verify-system.C3`) — THEME-009 (AG3-042)
- Frontend-Lese-API fuer QA-Read-Models — separate Folge-Story

## 3. Betroffene Dateien

| Datei | Aenderungsart | Beschreibung |
|---|---|---|
| `src/agentkit/verify_system/__init__.py` | Modifiziert | Re-Export `VerifySystem`, `VerifyContextBundle` <!-- AG3-026 deep-review: PolicyVerdictResult/VerifyTarget nicht oeffentlich --> |
| `src/agentkit/verify_system/system.py` | Neu | `VerifySystem`-Top-Klasse |
| `src/agentkit/verify_system/contract.py` | Neu | `VerifyContextBundle`; intern `VerifyTarget`, `VerifyTargetType`-StrEnum; optional internes `QaSubflowExecutionResult` (nicht exportiert) |
| `src/agentkit/verify_system/errors.py` | Neu (oder Modifiziert) | `VerifySystemError`, `VerifyTargetUnknownError`, `LayerExecutionError` |
| `src/agentkit/verify_system/routing.py` | Neu | `select_layers(qa_context)` |
| `tests/unit/verify_system/test_top_surface.py` | Neu | Methoden-Tests |
| `tests/unit/verify_system/test_routing.py` | Neu | select_layers |
| `tests/unit/verify_system/test_contract_models.py` | Neu | VerifyContextBundle/VerifyTarget |
| `tests/contract/verify_system/test_top_surface.py` | Neu | Vertrags-Pinning |

## 4. Akzeptanzkriterien

1. **Klasse `VerifySystem`** ist in `src/agentkit/verify_system/system.py` definiert und ueber `from agentkit.backend.verify_system import VerifySystem` importierbar.
2. **Methode `run_qa_subflow(ctx, story_id, qa_context, target)`** existiert mit den genannten Parametern. Return-Type ist exakt `PolicyVerdict` (PASS | FAIL). Contract-Test prueft die Annotation und dass ausschliesslich `PolicyVerdict.PASS` oder `PolicyVerdict.FAIL` zurueckgegeben werden. <!-- AG3-026 deep-review: Return-Type aus FK-27 §27.7 + formal.verify.commands -->
3. **`VerifyContextBundle`** ist Pydantic-v2-Modell, frozen, extra forbid, mit Pflichtfeldern wie in 2.1.1 beschrieben. `VerifyTarget` ist ein internes Wrapper-Modell und NICHT Teil der oeffentlichen Surface (kein Methodenparameter, kein `__init__.py`-Export).
4. **Routing-Regel**: `select_layers(QaContext.IMPLEMENTATION_INITIAL)` und `IMPLEMENTATION_REMEDIATION` liefern alle vier Layer (Structural, LLM-Evaluator, Adversarial, Policy); `EXPLORATION_INITIAL`/`EXPLORATION_REMEDIATION` liefern die reduzierte Exploration-Layer-Auswahl (Layer 2 + Policy) gemaess QA-Subflow-Vertrag (BC-Cut).
5. **Layer-Reihenfolge**: bei Implementation-Context ruft `run_qa_subflow` die Layer in genau dieser Reihenfolge: Structural -> LlmEvaluator -> Adversarial -> Policy. (Layer-Implementierungen koennen Stubs sein.)
6. **Fail-closed-Verhalten**: unbekannter `target_type` (intern) -> `VerifyTargetUnknownError`. Layer wirft Exception -> wird zu `LayerExecutionError`, das als BLOCKING-Finding im optional internen `QaSubflowExecutionResult` einfliesst und `verdict = PolicyVerdict.FAIL` setzt (Return-Type bleibt `PolicyVerdict`).
7. **ArtifactManager-Integration**: `run_qa_subflow` schreibt fuer jeden tatsaechlich ausgefuehrten Layer das **zugehoerige** QA-Artefakt gemaess FK-27 §27.7 (Layer 1: `structural.json`; Layer 2: `qa_review.json`, `semantic_review.json`, `doc_fidelity.json`; Layer 3: `adversarial.json`; Policy: `decision.json`) ueber `ArtifactManager`. Producer aus ProducerRegistry, ArtifactClass.QA, Pflichtfelder aus AG3-022. Stub-Layer duerfen ein synthetisches, aber schema-valides Layer-Artefakt liefern. Tests bestaetigen Producer + Schema-Vertrag. <!-- AG3-026 deep-review: "mindestens ein Envelope pro Layer" war zu unscharf. -->
8. **QA-Zyklus-Felder werden nicht vom Return-Type erzwungen.** Wenn `ctx.phase_envelope` bzw. PhaseState bereits `qa_cycle_id`, `qa_cycle_round`, `evidence_epoch`, `evidence_fingerprint` enthaelt, schreibt `VerifySystem` diese Werte in die erzeugten QA-Artefakte. Das Befuellen/Invalidieren der Zyklusfelder ist NICHT Scope dieser Story (siehe AG3-041, THEME-009). <!-- AG3-026 deep-review: PolicyVerdictResult-Pflichtfelder waren oeffentlicher Vertrag — fehlerhaft. -->
8a. **Optional interne Detail-Modelle** (z.B. `QaSubflowExecutionResult`) duerfen mit Feldern wie `stage_results`, `blocking_failures`, `major_failures`, `minor_failures`, `artifact_refs` existieren, sind aber kein `__init__.py`-Export und kein Return-Type.
9. **Architecture-Conformance**: `VerifySystem` haelt sich an die BC-Grenzen; importiert `ArtifactManager` via Protocol (Dependency-Injection), nicht aus `state_backend.store` direkt.
10. **Pflichtbefehle gruen**: pytest unit + contract; mypy --strict; ruff clean; Coverage haelt 85%.
11. **`PolicyVerdictResult` ist NICHT in `__init__.py` exportiert** und NICHT Return-Type. <!-- AG3-026 deep-review: explizites Verbot, um Konzeptbruch zu verhindern. -->

## 5. Definition of Done

- AK 1-10 erfuellt.
- `.venv\Scripts\python -m pytest tests/unit/verify_system tests/contract/verify_system -q` gruen.
- `mypy --strict` gruen, `ruff check src tests` gruen.
- Aenderungen committed auf `main`.

## 6. Konzept-Referenzen (autoritativ)

- **`concept/_meta/bc-cut-decisions.md §Verify als Capability (Variante Y)`** — Top-Surface
- **`concept/_meta/bc-cut-decisions.md §QA-Subflow-Vertrag`** — `run_qa_subflow`-Signatur, QaContext-Werte
- **`concept/_meta/bc-cut-decisions.md §BC 2 verify-system`** — Sub-Komponenten und Beziehungen
- **FK-27 §27.3** — QA-Subflow-Top
- **`formal.verify.state-machine`** — Sub-Zustaende
- **`formal.verify.invariants`** — fail-closed

## 7. Guardrail-Referenzen

- **FIX THE MODEL, NOT THE SYMPTOM**: Top-Surface als Vertragsachse — Aufrufer integrieren typsicher; keine String-Routing-Logik mehr.
- **ZERO DEBT**: Vertrag vollstaendig (alle Antwortfelder), nicht "spaeter erweitern".
- **FAIL CLOSED**: alle bekannten Fehlerklassen typisiert; Layer-Exceptions werden nicht verschluckt.
- **SINGLE SOURCE OF TRUTH**: ein Eintrittspunkt fuer QA, eine Routing-Regel.

## 8. Hinweise fuer den Sub-Agent

- Diese Story stabilisiert nur den Vertrag. Layer-Inhalte bleiben (Stubs). Aufrufer-BCs (pipeline-framework) koennen ab jetzt korrekt gegen `VerifySystem` programmieren — die Layer-Vervollstaendigung kommt mit THEME-009.
- Composition-Root: `VerifySystem` wird dort instanziiert, wo die ProducerRegistry singleton lebt (siehe AG3-023). Tests bauen ihre eigene `VerifySystem`-Instanz mit Stub-Layern.
- AK2 NICHT veraendern.
