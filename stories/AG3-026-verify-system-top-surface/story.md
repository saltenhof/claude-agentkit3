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
        target: VerifyTarget,
    ) -> PolicyVerdict:
        ...
```

`VerifyContextBundle` und `VerifyTarget` sind neue typisierte Pydantic-Modelle in `src/agentkit/verify_system/contract.py`:

- `VerifyContextBundle`: `run_id`, `story_dir`, `phase_envelope` (Read-only), `attempt`
- `VerifyTarget`: `target_type` (StrEnum: `IMPLEMENTATION`, `EXPLORATION`, `BUGFIX`), `branch_ref`, `commit_sha`, `paths_in_scope: list[str]`

#### 2.1.2 QA-Context-Routing (concept/_meta/bc-cut-decisions.md §QA-Subflow-Vertrag)

`run_qa_subflow` verzweigt anhand `qa_context: QaContext`:

- `IMPLEMENTATION_INITIAL`/`IMPLEMENTATION_REMEDIATION` -> volle 4-Schichten (Layer 1+2+3+Policy)
- `EXPLORATION_INITIAL`/`EXPLORATION_REMEDIATION` -> nur Layer 2 (Design-Review-Schicht) + Policy

Routing-Regel ist im Konzept normiert; eine Helper-Funktion `select_layers(qa_context: QaContext) -> tuple[QALayer, ...]` ist Teil der Top-Surface.

#### 2.1.3 PolicyVerdict-Antwort

`run_qa_subflow` gibt `PolicyVerdict` (aus `agentkit.core_types`, AG3-021) zurueck. Antwort-Modell wird angereichert:

```python
class PolicyVerdictResult(BaseModel):
    verdict: PolicyVerdict          # PASS | FAIL
    findings: list[Finding]
    blocking_findings: list[Finding]
    layer_results: dict[str, LayerResult]
    qa_cycle_id: str
    qa_cycle_round: int
    evidence_epoch: int
    artifact_refs: list[ArtifactReference]
    model_config = ConfigDict(frozen=True, extra="forbid")
```

Begruendung: `PolicyVerdict` allein als Return-Type ist zu eng; Aufrufer braucht Finding-Details und Persistenzreferenzen. Konzept (FK-27 §27.7) erlaubt erweitertes Antwortmodell, solange `PolicyVerdict` enthalten ist. Der Methoden-Return-Type bleibt `PolicyVerdict` als Top-Level-Signature; das `PolicyVerdictResult` ist Bestandteil der oeffentlichen API als Detail-Wrapper, in der Praxis liefert `run_qa_subflow` `PolicyVerdictResult` (das `verdict: PolicyVerdict` propagiert). 

Pragmatische Loesung: Methode liefert `PolicyVerdictResult` (das hat ein `.verdict`-Feld). Wenn Konzept-Wortlaut "-> PolicyVerdict" verlangt: Sub-Klassen-Vertrag explizit dokumentieren; Architecture-Conformance-Test pinnt das.

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
  - Signatur exakt: `(ctx: VerifyContextBundle, story_id: str, qa_context: QaContext, target: VerifyTarget)`
  - Return-Type `PolicyVerdictResult` mit `.verdict: PolicyVerdict`

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
| `src/agentkit/verify_system/__init__.py` | Modifiziert | Re-Export `VerifySystem`, `VerifyContextBundle`, `VerifyTarget`, `PolicyVerdictResult` |
| `src/agentkit/verify_system/system.py` | Neu | `VerifySystem`-Top-Klasse |
| `src/agentkit/verify_system/contract.py` | Neu | `VerifyContextBundle`, `VerifyTarget`, `VerifyTargetType`-StrEnum, `PolicyVerdictResult` |
| `src/agentkit/verify_system/errors.py` | Neu (oder Modifiziert) | `VerifySystemError`, `VerifyTargetUnknownError`, `LayerExecutionError` |
| `src/agentkit/verify_system/routing.py` | Neu | `select_layers(qa_context)` |
| `tests/unit/verify_system/test_top_surface.py` | Neu | Methoden-Tests |
| `tests/unit/verify_system/test_routing.py` | Neu | select_layers |
| `tests/unit/verify_system/test_contract_models.py` | Neu | VerifyContextBundle/VerifyTarget |
| `tests/contract/verify_system/test_top_surface.py` | Neu | Vertrags-Pinning |

## 4. Akzeptanzkriterien

1. **Klasse `VerifySystem`** ist in `src/agentkit/verify_system/system.py` definiert und ueber `from agentkit.verify_system import VerifySystem` importierbar.
2. **Methode `run_qa_subflow(ctx, story_id, qa_context, target)`** existiert mit den genannten Parametern. Return-Type ist `PolicyVerdictResult`, das ein Feld `.verdict: PolicyVerdict` traegt.
3. **`VerifyContextBundle` und `VerifyTarget`** sind Pydantic-v2-Modelle, frozen, extra forbid, mit Pflichtfeldern wie in 2.1.1 beschrieben.
4. **Routing-Regel**: `select_layers(QaContext.IMPLEMENTATION_INITIAL)` und `IMPLEMENTATION_REMEDIATION` liefern alle vier Layer (Structural, LLM-Evaluator, Adversarial, Policy); `EXPLORATION_INITIAL`/`EXPLORATION_REMEDIATION` liefern nur Layer 2 + Policy.
5. **Layer-Reihenfolge**: bei Implementation-Context ruft `run_qa_subflow` die Layer in genau dieser Reihenfolge: Structural -> LlmEvaluator -> Adversarial -> Policy. (Layer-Implementierungen koennen Stubs sein.)
6. **Fail-closed-Verhalten**: unbekannter `target_type` -> `VerifyTargetUnknownError`. Layer wirft Exception -> wird zu `LayerExecutionError`, das als BLOCKING-Finding ins `PolicyVerdictResult` einfliesst und `verdict = FAIL` setzt.
7. **ArtifactManager-Integration**: `run_qa_subflow` schreibt mindestens ein Envelope pro Layer-Ergebnis ueber `ArtifactManager` (Producer aus Registry, ArtifactClass.QA, Pflichtfelder aus AG3-022). Tests bestaetigen das.
8. **`PolicyVerdictResult` Pflichtfelder**: `verdict`, `findings`, `blocking_findings`, `layer_results`, `qa_cycle_id`, `qa_cycle_round`, `evidence_epoch`, `artifact_refs`. (QA-Zyklus-Identitaeten werden ggf. aus PhaseState gelesen — Mechanik in AG3-041.)
9. **Architecture-Conformance**: `VerifySystem` haelt sich an die BC-Grenzen; importiert `ArtifactManager` via Protocol (Dependency-Injection), nicht aus `state_backend.store` direkt.
10. **Pflichtbefehle gruen**: pytest unit + contract; mypy --strict; ruff clean; Coverage haelt 85%.

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
