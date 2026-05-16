# AG3-043: Layer 2 — StructuredEvaluator + ParallelEvalRunner + drei Rollen

**Typ:** Implementation
**Groesse:** L
**Abhaengigkeiten:** AG3-015 (PromptRuntime.materialize_prompt), AG3-021, AG3-022, AG3-026, AG3-041 (Finding-Resolution)
**Quell-Konzepte (autoritativ, in dieser Reihenfolge):**
- `FK-27 §27.5` (Layer 2 — ParallelEvalRunner, drei parallele StructuredEvaluator-Aufrufe)
- `FK-34` (LLM-Bewertungen, drei Rollen, fail-closed)
- `FK-38 §38.2` (qa_review 12 Checks, semantic_review 1 Check, doc_fidelity/Umsetzungstreue 1 Check)
- `FK-44` (PromptRuntime fuer Template-Lookup)
- `verify-system.B2/B7/A8` aus GAP-Analyse

---

## 1. Kontext

THEME-009 aus `stories/_priorisierungsempfehlung.md`. Befund `verify-system.B2`: SemanticReviewer ist Passthrough-Stub (immer PASS, kein LLM-Aufruf). Es fehlen:
- StructuredEvaluator (JSON-Schema-Validierung, fail-closed)
- ParallelEvalRunner (ThreadPoolExecutor)
- drei parallele Rollen (qa_review/12 Checks, semantic_review/1 Check, doc_fidelity/1 Check)
- Prompt-Template-Lookup via PromptRuntime.materialize_prompt

Befund `verify-system.B7`: Prompt-Templates `qa-semantic`, `qa-semantic-review`, `qa-adversarial-review` sind Stubs.

Diese Story implementiert Layer 2 vollstaendig. Sie ist sehr LLM-Aufrufs-lastig; Tests muessen mit deterministischen LLM-Mocks arbeiten (Ausnahme zur Mock-Regel — siehe Hinweise).

## 2. Scope

### 2.1 In Scope

#### 2.1.1 `StructuredEvaluator` (FK-34)

`src/agentkit/verify_system/llm_evaluator/structured_evaluator.py`:

```python
class StructuredEvaluator:
    def __init__(self, llm_client: LlmClient, prompt_runtime: PromptRuntime) -> None: ...

    def evaluate(
        self,
        role: ReviewerRole,
        bundle: ReviewBundle,
        previous_findings: list[Finding] | None,
        qa_cycle_round: int,
    ) -> StructuredEvaluatorResult: ...

class StructuredEvaluatorResult(BaseModel):
    role: ReviewerRole
    verdict: LlmVerdict  # PASS | FAIL | PASS_WITH_CONCERNS
    findings: list[Finding]
    finding_resolutions: dict[FindingId, FindingResolutionStatus]  # nur im Remediation-Modus
    raw_response_hash: str  # SHA-256 ueber LLM-Output fuer Audit
    template_sha256: str
    model_config = ConfigDict(frozen=True, extra="forbid")
```

`LlmVerdict` StrEnum mit `PASS`, `FAIL`, `PASS_WITH_CONCERNS` (LLM-Domain-Wert; wird durch `ProducerRegistry.map_llm_status_to_envelope_status` auf `EnvelopeStatus` gemappt).

`ReviewerRole` StrEnum: `QA_REVIEW`, `SEMANTIC_REVIEW`, `DOC_FIDELITY`.

`StructuredEvaluator` macht:
1. `PromptRuntime.materialize_prompt` mit Template-Name passend zur Rolle (`qa-review.md`, `qa-semantic-review.md`, `qa-doc-fidelity.md`)
2. LLM-Aufruf mit dem materialisierten Prompt + Bundle als JSON
3. JSON-Schema-Validierung der LLM-Antwort (fail-closed: ungueltige Struktur -> StructuredEvaluatorError)
4. Mapping der Antwort auf Findings + finding_resolutions

#### 2.1.2 `ParallelEvalRunner` (FK-27 §27.5)

`src/agentkit/verify_system/llm_evaluator/parallel_runner.py`:

```python
class ParallelEvalRunner:
    def __init__(self, evaluator: StructuredEvaluator, max_workers: int = 3) -> None: ...

    def run(
        self,
        bundle: ReviewBundle,
        previous_findings: list[Finding] | None,
        qa_cycle_round: int,
    ) -> dict[ReviewerRole, StructuredEvaluatorResult]:
        # ThreadPoolExecutor mit max_workers=3
        # ruft StructuredEvaluator parallel fuer alle drei Rollen
        # fail-closed: wenn eine Rolle scheitert, gibt LayerResult passed=False zurueck
        ...
```

#### 2.1.3 `qa-review.md`-Prompt (FK-38 §38.2 — 12 Checks)

Neues Template `src/agentkit/resources/internal/prompts/qa-review.md`:

12 Pflicht-Checks (FK-38 §38.2 Liste — exakt uebernehmen):
- Anforderungserfuellung
- Testabdeckung
- Architekturkonsistenz
- Codequalitaet
- Security-Risiken
- Performance-Risiken
- Dokumentations-Drift
- Konzept-Fidelitaet
- Inkrement-Disziplin
- Review-Compliance
- Story-Scope-Treue
- BC-Grenzen

Jeder Check liefert PASS/FAIL/PASS_WITH_CONCERNS + Begruendung. Schema in Prompt enforced.

#### 2.1.4 `qa-semantic-review.md` und `qa-doc-fidelity.md`

Templates fuer die jeweils 1-Check-Rollen:
- `qa-semantic-review.md` — bewertet semantische Konsistenz Story-Brief vs. Implementation
- `qa-doc-fidelity.md` — bewertet Doctreue Ebene 2 (Konzept-Fidelitaet)

#### 2.1.5 `ReviewBundle` als Input fuer LLM-Aufrufe

`src/agentkit/verify_system/llm_evaluator/bundle.py`:

```python
class ReviewBundle(BaseModel):
    story_id: str
    story_brief_excerpt: str
    acceptance_criteria: list[str]
    diff_summary: str        # git diff origin/main..HEAD --stat
    diff_content: str        # max 100KB
    concept_refs: list[str]  # FK-/DK-Anker
    previous_findings: list[Finding] | None
    qa_cycle_round: int
    model_config = ConfigDict(frozen=True, extra="forbid")
```

Builder-Funktion `build_review_bundle(ctx, target)`.

Bundle-Groessenbeschraenkung: max 200KB total (Hinweis: vollstaendiger Bundle-Packing-Mechanismus aus FK-37 ist Out of Scope der Erst-Welle; einfache Truncation-Logik reicht).

#### 2.1.6 Finding-Resolution-Integration

Im Remediation-Modus (qa_cycle_round > 1):
- `previous_findings` werden im Bundle uebergeben
- LLM bewertet, ob Vorrunden-Findings resolved sind -> `finding_resolutions`
- Liefert FindingResolutionStatus aus AG3-041 ein

#### 2.1.7 VerifySystem-Integration

`VerifySystem.run_qa_subflow` aus AG3-026:
- Layer-2-Slot wird mit `ParallelEvalRunner.run(...)` befuellt
- Drei `StructuredEvaluatorResult` werden zu drei Layer-Result-Eintraegen aggregiert (oder als ein konsolidiertes LayerResult mit Rolle-Annotation)

#### 2.1.8 Legacy-Migration

`src/agentkit/llm_evaluator/`-Top-Level-Shim (`verify-system.C4`) wird ENTFERNT — dieser Paket-Drift wird hier endlich abgeschlossen. Alle Importer wandern auf `agentkit.verify_system.llm_evaluator`.

#### 2.1.9 Tests

- Unit-Tests fuer `StructuredEvaluator` mit deterministischem LLM-Mock (Ausnahme zur Mock-Regel, siehe Hinweise)
- Unit-Tests fuer `ParallelEvalRunner` (Parallelitaet, fail-closed)
- Unit-Tests fuer JSON-Schema-Validierung (ungueltige LLM-Antworten)
- Unit-Tests fuer Bundle-Builder
- Unit-Test fuer Finding-Resolution-Integration (Remediation-Modus)
- Integration-Test: VerifySystem-Lauf mit allen drei Rollen, Mock-LLM, Result-Aggregation
- Contract-Test: 12 Pflicht-Checks in `qa-review.md`-Template (parse Template-File und assert Check-Namen)

### 2.2 Out of Scope

- Layer 3 Adversarial — AG3-044
- ConformanceService (vollwertige Umsetzungstreue-Bewertung) — bewusst nicht in der Erst-Welle
- EvidenceAssembler (3-Stufen-Bundle, ImportResolver, Request-DSL) — bewusst nicht in der Erst-Welle
- Section-aware Bundle-Packing (FK-37 §37.3) — bewusst nicht in der Erst-Welle
- ContextSufficiencyBuilder — bewusst nicht in der Erst-Welle
- Divergenz-Quorum (`verify-system.A9`) — bewusst nicht in der Erst-Welle
- LLM-Pool-Auswahl (welcher konkrete LLM-Provider) — Sub-Story; diese Story arbeitet mit `LlmClient`-Abstraktion
- Cost-Tracking pro Aufruf — Folge-Story

## 3. Betroffene Dateien

| Datei | Aenderungsart | Beschreibung |
|---|---|---|
| `src/agentkit/verify_system/llm_evaluator/__init__.py` | Modifiziert | Re-Export aller neuen Klassen |
| `src/agentkit/verify_system/llm_evaluator/structured_evaluator.py` | Neu | `StructuredEvaluator`, `StructuredEvaluatorResult`, `LlmVerdict`, `ReviewerRole` |
| `src/agentkit/verify_system/llm_evaluator/parallel_runner.py` | Neu | `ParallelEvalRunner` |
| `src/agentkit/verify_system/llm_evaluator/bundle.py` | Neu | `ReviewBundle`, `build_review_bundle` |
| `src/agentkit/verify_system/llm_evaluator/llm_client.py` | Neu | `LlmClient`-Protocol (Adapter wird in Folge-Story konkret) |
| `src/agentkit/verify_system/llm_evaluator/reviewer.py` | Modifiziert | bestehender Reviewer ruft jetzt ParallelEvalRunner |
| `src/agentkit/llm_evaluator/` | Geloescht | Legacy-Shim entfernt (verify-system.C4) |
| `src/agentkit/resources/internal/prompts/qa-review.md` | Neu | 12 Checks |
| `src/agentkit/resources/internal/prompts/qa-semantic-review.md` | Neu | 1 Check |
| `src/agentkit/resources/internal/prompts/qa-doc-fidelity.md` | Neu | 1 Check |
| `tests/unit/verify_system/llm_evaluator/...` | Neu/Erweitert | |
| `tests/integration/verify_system/test_layer2_e2e.py` | Neu | E2E mit Mock-LLM |
| `tests/contract/verify_system/test_qa_review_template.py` | Neu | 12-Check-Pinning |

## 4. Akzeptanzkriterien

1. **`StructuredEvaluator`** existiert mit `evaluate(role, bundle, previous_findings, qa_cycle_round) -> StructuredEvaluatorResult`. JSON-Schema-Validierung fail-closed.
2. **`ParallelEvalRunner.run`** ruft alle drei Rollen parallel auf; Mock-Test bestaetigt Parallelitaet.
3. **Drei Pflicht-Templates** existieren in `src/agentkit/resources/internal/prompts/` mit den konzept-normierten Check-Listen (12/1/1).
4. **Prompt-Lookup** erfolgt via `PromptRuntime.materialize_prompt` (AG3-015); Tests verifizieren, dass der materialisierte Pfad genutzt wird (kein direkter Resource-Read).
5. **JSON-Schema-Validierung**: Ungueltige LLM-Antwort -> `StructuredEvaluatorError`, kein silent skip.
6. **Finding-Resolution im Remediation-Modus** wird im LLM-Aufruf mitgegeben; LLM-Antwort liefert `finding_resolutions`-Map; gemappt auf `FindingResolutionStatus` aus AG3-041.
7. **Legacy `agentkit.llm_evaluator`-Top-Level-Shim entfernt**; alle Importer auf `agentkit.verify_system.llm_evaluator` umgestellt.
8. **`VerifySystem.run_qa_subflow`** ruft `ParallelEvalRunner` als Layer 2; Result wird in `PolicyVerdictResult.layer_results` aggregiert.
9. **Pflichtbefehle gruen**: pytest unit + integration + contract; mypy --strict; ruff clean; Coverage haelt 85%.

## 5. Definition of Done

- AK 1-9 erfuellt.
- `.venv\Scripts\python -m pytest tests/unit/verify_system/llm_evaluator tests/integration/verify_system tests/contract/verify_system -q` gruen.
- `mypy --strict` gruen, `ruff check src tests` gruen.
- Aenderungen committed auf `main`.

## 6. Konzept-Referenzen (autoritativ)

- **FK-27 §27.5** — Layer 2 / ParallelEvalRunner
- **FK-34** — drei Rollen
- **FK-38 §38.2** — Check-Listen pro Rolle
- **FK-44** — PromptRuntime fuer Template-Lookup
- **DK-04 §4.6** — Remediation-Modus

## 7. Guardrail-Referenzen

- **FIX THE MODEL, NOT THE SYMPTOM**: Layer 2 macht endlich echte LLM-Calls; kein Passthrough mehr.
- **ZERO DEBT**: Drei Templates vollstaendig; Legacy-Shim entfernt.
- **FAIL CLOSED**: ungueltige LLM-Antwort -> Exception.
- **NO ERROR BYPASSING**: Layer 2 darf nicht uebersprungen werden.

## 8. Hinweise fuer den Sub-Agent

- **Mock-LLM**: Diese Story braucht zwingend Mocks fuer Tests (echte LLM-Aufrufe in CI sind kosten- und zeitaufwendig). Das ist die explizite Ausnahme zur Mock-Regel — begruendet im Story-Briefing.
- LlmClient-Protocol: pruefe existing MultiLlmHub im Repo. Falls vorhanden, ist `LlmClient` ein Adapter darauf; sonst neuer Protocol fuer Folge-Story.
- JSON-Schema fuer LLM-Antwort: definiere in `structured_evaluator.py` als Pydantic-Modell (`LlmEvaluatorResponse`), das jedes der drei Templates parsen koennen muss. Bei Parse-Fehler -> StructuredEvaluatorError.
- AK2 NICHT veraendern.
