# AG3-042: Layer 1 — Artefakt-/Branch-/Build-/Test-/Hygiene-Checks + Recurring Guards

**Typ:** Implementation
**Groesse:** L
**Abhaengigkeiten:** AG3-021, AG3-022, AG3-023 (ArtifactManager), AG3-026 (VerifySystem-Top)
**Quell-Konzepte (autoritativ, in dieser Reihenfolge):**
- `FK-27 §27.4.1/27.4.2/27.4.3` (Layer 1 — Artefakt, Branch, Build/Test, Hygiene, Recurring Guards)
- `FK-33` (Stage-Registry + Policy-Engine)
- `FK-27 §27.4.3` (guard.llm_reviews/guard.multi_llm als BLOCKING-Gates, REF-036)
- `verify-system.B1/C3` aus GAP-Analyse

---

## 1. Kontext

THEME-009 aus `stories/_priorisierungsempfehlung.md`. Befund `verify-system.B1`: Layer-1 prueft nur Meta-Checks. Fehlen:
- Artefakt-Pruefung (`artifact.protocol`, `artifact.worker_manifest`, `artifact.manifest_claims`, `artifact.handover`)
- Branch-Checks (`branch.story`, `branch.commit_trailers`)
- Build/Test-Checks (`build.compile`, `build.test_execution`, `test.count`, `test.coverage`)
- Hygiene-Checks (`hygiene.todo_fixme`, `hygiene.disabled_tests`, `hygiene.commented_code`)
- Recurring Guards (`guard.llm_reviews`, `guard.review_compliance`, `guard.no_violations`, `guard.multi_llm`)
- ARE-Gate (optional)
- Impact-Violation-Check mit ESCALATED-Pfad

Befund `verify-system.C3`: `guard.llm_reviews` und `guard.multi_llm` fehlen als separate BLOCKING-Gates (REF-036, BB2-057). Befund `verify-system.B3`: Stage-Registry-Bindung mit BLOCKING/MAJOR/MINOR.

Diese Story implementiert die kompletten Layer-1-Checks **plus** Stage-Registry-Bindung als typisierte Klassifikation.

## 2. Scope

### 2.1 In Scope

#### 2.1.1 Stage-Registry (FK-33)

Neues Modul `src/agentkit/verify_system/stage_registry/`:

- `stages.py` — `StageDefinition`-Pydantic-Modell:
  - `stage_id: str` (z.B. `artifact.protocol`, `branch.story`)
  - `layer: int` (1-4)
  - `severity: Severity` (BLOCKING/MAJOR/MINOR aus core_types)
  - `applies_to: set[StoryType]` (welche Story-Typen brauchen diese Stage)
  - `execution_policy: ExecutionPolicy` (StrEnum: `ALWAYS`, `IF_LAYER_PASSES`, `IF_PREVIOUS_PASS`)
- `registry.py` — `StageRegistry.stages_for(story_type) -> list[StageDefinition]`
- `data.py` — vollstaendige Stage-Definitionen aus FK-27 §27.4 als Konstanten

Stages (mindestens, mit Severity-Klassifikation aus FK-27 §27.4.2/§27.4.3 —
FK-27 ist die autoritative Quelle und gewinnt bei jeder Abweichung dieser
Zusammenfassung; die Code-/Registry-Severities in `data.py` folgen FK-27):
- `artifact.protocol` — BLOCKING (Pflicht-Artefakt > 50 bytes)
- `artifact.worker_manifest` — BLOCKING
- `artifact.manifest_claims` — BLOCKING (FK-27 §27.4.1 / FK-33 §33.3.2; die
  frühere Zusammenfassung sagte MAJOR — FK-27 gewinnt -> BLOCKING)
- `artifact.handover` — BLOCKING
- `branch.story` — BLOCKING
- `branch.commit_trailers` — BLOCKING (FK-27 §27.4.2 / FK-33 §33.3.2; die
  frühere Zusammenfassung sagte MINOR — FK-27 gewinnt -> BLOCKING)
- `build.compile` — BLOCKING
- `build.test_execution` — BLOCKING
- `test.count` — MAJOR
- `test.coverage` — MAJOR
- `hygiene.todo_fixme` — MINOR
- `hygiene.disabled_tests` — MINOR (FK-27 §27.4.2 / FK-33 §33.3.2; die frühere
  Zusammenfassung sagte MAJOR — FK-27 gewinnt -> MINOR)
- `hygiene.commented_code` — MINOR
- `guard.llm_reviews` — BLOCKING (REF-036)
- `guard.review_compliance` — MAJOR (FK-27 §27.4.3 Quelle `review_compliant`;
  die frühere Zusammenfassung sagte BLOCKING — FK-27 gewinnt -> MAJOR)
- `guard.no_violations` — BLOCKING
- `guard.multi_llm` — BLOCKING (REF-036; zählt `llm_call_complete`-Events,
  emittiert erst nach erfolgreichem Schreiben des Review-Artefakts, FK-27
  §27.4.3 / §27.5.5)
- `are.gate` — BLOCKING (nur wenn features.are=true)
- `impact.violation` — BLOCKING -> ESCALATED (FK-27 §27.4.2/§27.4.5: führt
  immer direkt zu ESCALATED, kein Worker-Feedback-Loop)

#### 2.1.2 Layer-1-Checker-Module

`src/agentkit/verify_system/structural/checks/` (Sub-Verzeichnis, eine Datei pro Check-Gruppe):

- `artifact_checks.py` — `check_artifact_protocol`, `check_artifact_worker_manifest`, `check_artifact_manifest_claims`, `check_artifact_handover`
- `branch_checks.py` — `check_branch_story`, `check_branch_commit_trailers`
- `build_test_checks.py` — `check_build_compile`, `check_build_test_execution`, `check_test_count`, `check_test_coverage`
- `hygiene_checks.py` — `check_hygiene_todo_fixme`, `check_hygiene_disabled_tests`, `check_hygiene_commented_code`
- `recurring_guards.py` — `check_guard_llm_reviews`, `check_guard_review_compliance`, `check_guard_no_violations`, `check_guard_multi_llm`
- `are_gate.py` — `check_are_gate` (nutzt `RequirementsCoverage` aus AG3-030)
- `impact_violation.py` — `check_impact_violation`

Signatur pro Check:
```python
def check_<name>(ctx: VerifyContextBundle, target: VerifyTarget) -> Finding | None:
    # None = PASS, sonst Finding mit Severity aus StageDefinition
```

#### 2.1.3 `StructuralChecker` umbauen

`src/agentkit/verify_system/structural/checker.py:StructuralChecker.evaluate` wird umgebaut:

- Iteriert ueber `StageRegistry.stages_for(story_type)` gefiltert auf `layer == 1`
- Ruft jeden Check; sammelt Findings
- Liefert `LayerResult` mit allen Findings

Existing Meta-Checks (`check_context_exists`, `check_context_valid`, `check_no_corrupt_state`) bleiben als Pre-Checks erhalten — sie sind Pflicht-Voraussetzung fuer alle Stages.

#### 2.1.4 PolicyEngine an Stage-Registry binden (verify-system.B3)

`src/agentkit/verify_system/policy_engine/engine.py:PolicyEngine`:

- Konstruktor nimmt `StageRegistry` als Dependency
- `decide(findings)` aggregiert nach Stage-Registry-Kategorien:
  - irgendein BLOCKING-Finding (in einer Stage, die `applies_to`-passend ist) -> FAIL
  - kein BLOCKING + MAJOR-Findings <= threshold -> PASS
  - sonst FAIL
- fail-closed bei fehlendem Artefakt einer durchlaufenen Schicht (`verify-system.B3`)

`PolicyEngine.max_high_findings` (alter Threshold) wird durch ein konzept-konformes Schwellenmodell ersetzt:
- `max_major_findings_per_story_type: dict[StoryType, int]` (Default-Werte aus FK-33)

#### 2.1.5 Tests

- Unit-Tests pro Check (je 1-2 Pfade: PASS + spezifisches Finding)
- Unit-Tests fuer `StageRegistry.stages_for` (jedes StoryType liefert die richtige Stage-Liste)
- Unit-Tests fuer `StructuralChecker.evaluate` mit verschiedenen Findings-Kombinationen
- Unit-Tests fuer PolicyEngine-Aggregation nach Stage-Registry
- Integration-Test: Layer-1-Lauf gegen eine simulierte Story-Verzeichnis-Struktur
- Contract-Test `tests/contract/verify_system/test_stage_registry.py`: alle Stage-Definitionen mit Severity aus FK-27 §27.4

### 2.2 Out of Scope

- Layer 2 LLM-Aufrufe — AG3-043
- Adversarial-Layer (Layer 3) — AG3-044
- Worker-Loop + Manifest — AG3-044
- ConformanceService (Layer 2 Ebene 3 Umsetzungstreue) — bewusst nicht in der Erst-Welle
- EvidenceAssembler — bewusst nicht in der Erst-Welle
- Divergenz-Quorum — bewusst nicht in der Erst-Welle

## 3. Betroffene Dateien

| Datei | Aenderungsart | Beschreibung |
|---|---|---|
| `src/agentkit/verify_system/stage_registry/stages.py` | Neu | `StageDefinition`, `ExecutionPolicy` |
| `src/agentkit/verify_system/stage_registry/registry.py` | Neu | `StageRegistry` |
| `src/agentkit/verify_system/stage_registry/data.py` | Neu | Stage-Definitionen aus FK-27/FK-33 |
| `src/agentkit/verify_system/stage_registry/__init__.py` | Modifiziert | Re-Export |
| `src/agentkit/verify_system/structural/checks/__init__.py` | Neu | Re-Export |
| `src/agentkit/verify_system/structural/checks/artifact_checks.py` | Neu | |
| `src/agentkit/verify_system/structural/checks/branch_checks.py` | Neu | |
| `src/agentkit/verify_system/structural/checks/build_test_checks.py` | Neu | |
| `src/agentkit/verify_system/structural/checks/hygiene_checks.py` | Neu | |
| `src/agentkit/verify_system/structural/checks/recurring_guards.py` | Neu | |
| `src/agentkit/verify_system/structural/checks/are_gate.py` | Neu | |
| `src/agentkit/verify_system/structural/checks/impact_violation.py` | Neu | |
| `src/agentkit/verify_system/structural/checker.py` | Modifiziert | iteriert StageRegistry |
| `src/agentkit/verify_system/policy_engine/engine.py` | Modifiziert | StageRegistry-Bindung, fail-closed bei fehlendem Artefakt |
| `tests/unit/verify_system/structural/...` | Neu/Erweitert | |
| `tests/unit/verify_system/stage_registry/...` | Neu | |
| `tests/contract/verify_system/test_stage_registry.py` | Neu | Stage-Pinning |
| `tests/integration/verify_system/test_layer1_full.py` | Neu | E2E |

## 4. Akzeptanzkriterien

1. **`StageRegistry`** existiert und liefert pro StoryType die konzept-normierte Stage-Liste.
2. **Mindestens 19 Stage-Definitionen** existieren mit korrekter Severity-Klassifikation gemaess FK-27 §27.4.2.
3. **`StructuralChecker` iteriert ueber alle Layer-1-Stages** der StageRegistry; jedes BLOCKING-Finding fuehrt zu `LayerResult.passed=False`.
4. **`guard.llm_reviews` und `guard.multi_llm`** sind als separate BLOCKING-Gates implementiert (REF-036).
5. **PolicyEngine ist fail-closed bei fehlendem Artefakt** einer durchlaufenen Schicht.
6. **PolicyEngine-Schwellenmodell**: `max_major_findings_per_story_type` ersetzt `max_high_findings`. Tests verifizieren die Aggregation.
7. **ARE-Gate** wird nur aktiviert, wenn `features.are=true` (Konsum von `RequirementsCoverage.is_enabled` aus AG3-030).
8. **Impact-Violation-Check**: erkennt unzulaessigen `change_impact` (z.B. Story als `Local` deklariert, tatsaechliche Aenderungen `Architecture Impact`). Bei Violation: ESCALATED-Pfad (PolicyVerdict-Result hat `escalated=true`).
9. **Pflichtbefehle gruen**: pytest unit + integration + contract; mypy --strict; ruff clean; Coverage haelt 85%.

## 5. Definition of Done

- AK 1-9 erfuellt.
- `.venv\Scripts\python -m pytest tests/unit/verify_system tests/integration/verify_system tests/contract/verify_system -q` gruen.
- `mypy --strict` gruen, `ruff check src tests` gruen.
- Aenderungen committed auf `main`.

## 6. Konzept-Referenzen (autoritativ)

- **FK-27 §27.4.1/27.4.2/27.4.3** — Layer 1, Severity-Klassifikation, REF-036
- **FK-33** — Stage-Registry + PolicyEngine
- **FK-71 §71.2** — Envelope-Pflichtfelder fuer Artefakt-Checks
- **`formal.verify.invariants`** — Layer-1-Pflichten

## 7. Guardrail-Referenzen

- **FIX THE MODEL, NOT THE SYMPTOM**: Layer 1 hat endlich Substanz — kein leeres Meta-Check.
- **ZERO DEBT**: alle Stages typisiert, keine "spaeter Pruefung erweitern"-TODOs.
- **FAIL CLOSED**: fehlendes Artefakt einer durchlaufenen Schicht -> hart FAIL.
- **NO ERROR BYPASSING**: guard.llm_reviews und guard.multi_llm muessen passieren.

## 8. Hinweise fuer den Sub-Agent

- Stage-Definitionen aus FK-27 §27.4 abschreiben — keine Eigeninterpretation.
- Build/Test-Check: nutze pytest-subprocess; aufgerufenes Test-Skript-Targeting via `pyproject.toml`-konformer Args.
- AK2 NICHT veraendern.
