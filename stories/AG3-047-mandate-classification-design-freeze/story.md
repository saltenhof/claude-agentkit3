# AG3-047: MandateClassification + DesignFreezeMarker + Exploration-Telemetrie-Events

**Typ:** Implementation
**Groesse:** M
**Abhaengigkeiten:** AG3-021 (Enums), AG3-022 (ArtifactClass), AG3-037 (Exploration-EventTypes in events.py), AG3-045 (ChangeFrame), AG3-046 (ExplorationReview)
**Quell-Konzepte (autoritativ, in dieser Reihenfolge):**
- `FK-25 §25.3` (Mandatsgrenzen, H1/H2)
- `FK-25 §25.4.1` (Vier Klassen, Prueffolge 1->3->4->2)
- `FK-25 §25.5` (Feindesign-Subprozess fuer Klasse 2)
- `FK-25 §25.6` (Scope-Explosion-Erkennung mit quantitativen Indikatoren)
- `FK-23 §23.4.3` (DesignFreezeMarker, `frozen: true`)
- `FK-25 §25.8` (Telemetrie-Events: mandate_classification, fine_design_decision, scope_explosion_check, impact_exceedance_check)

---

## 1. Kontext

THEME-010 aus `stories/_priorisierungsempfehlung.md`, abschliessende Story. Befunde:

- `exploration-and-design.A4`: MandateClassification fehlt — H1-Aggregation, H2-Nachklassifikation, Klasse 1/3/4-Eskalation, Feindesign-Subprozess (Klasse 2). Scope-Explosion-Detektor und Impact-Exceedance-Check fehlen.
- `exploration-and-design.A5`: DesignFreezeMarker fehlt — Entwurfsartefakt-Freeze nach Gate-PASS.
- `exploration-and-design.A7`: vier Telemetrie-EventTypes fehlen in `EventType` (sind in AG3-037 ergaenzt; hier wird emittiert).

Diese Story schliesst die Exploration-Welle ab.

## 2. Scope

### 2.1 In Scope

#### 2.1.1 `MandateClassification` (FK-25 §25.3-25.4)

`src/agentkit/pipeline/phases/exploration/mandate/`:

```python
class MandateClassification:
    def __init__(self, scope_detector: ScopeExplosionDetector, impact_checker: ImpactExceedanceChecker) -> None: ...

    def classify(self, change_frame: ChangeFrame, ctx: PhaseContext) -> MandateClassificationResult: ...

class MandateClass(StrEnum):
    KLASSE_1 = "klasse_1"   # Trivial — kein Mandate-Block
    KLASSE_2 = "klasse_2"   # Feindesign-Subprozess notwendig
    KLASSE_3 = "klasse_3"   # Scope-Explosion -> Story-Split
    KLASSE_4 = "klasse_4"   # Impact-Eskalation -> Architecture-Review

class MandateClassificationResult(BaseModel):
    mandate_class: MandateClass
    h1_signals: H1Signals
    h2_signals: H2Signals
    scope_explosion_check: ScopeExplosionResult
    impact_exceedance_check: ImpactExceedanceResult
    next_step: Literal["proceed_implementation", "feindesign_subprocess", "story_split", "architecture_review"]
    model_config = ConfigDict(frozen=True, extra="forbid")
```

Pruefreihenfolge (FK-25 §25.4.1): 1 -> 3 -> 4 -> 2 (semantisch: erst trivial pruefen, dann Scope-Explosion, dann Impact, dann Feindesign).

#### 2.1.2 `ScopeExplosionDetector` (FK-25 §25.6)

`src/agentkit/pipeline/phases/exploration/mandate/scope_detector.py`:

```python
class ScopeExplosionDetector:
    def detect(self, change_frame: ChangeFrame) -> ScopeExplosionResult: ...

class ScopeExplosionResult(BaseModel):
    triggered: bool
    indicators: list[ScopeIndicator]
    high_indicators_count: int   # >=2 -> Klasse 3
```

Quantitative Indikatoren (FK-25 §25.6):
- Anzahl betroffener Module > Schwelle
- Cross-Component-Aenderungen
- AC-Anzahl > Schwelle
- Geschaetzte Dateianzahl > Schwelle
- (weitere aus FK-25 §25.6)

Bei >=2 HIGH-Indikatoren: `triggered=True` -> Klasse 3.

#### 2.1.3 `ImpactExceedanceChecker` (FK-25 §25.4.1)

`src/agentkit/pipeline/phases/exploration/mandate/impact_checker.py`:

```python
class ImpactExceedanceChecker:
    def check(self, change_frame: ChangeFrame, declared_impact: ChangeImpact) -> ImpactExceedanceResult: ...

class ImpactExceedanceResult(BaseModel):
    declared_impact: ChangeImpact     # aus story_context_manager
    actual_impact: ChangeImpact        # aus ChangeFrame.affected_modules
    exceeded: bool                      # actual > declared
```

`ChangeImpact` ist Wire-Enum aus story_context_manager (AG3-014: `Local`, `Component`, `Cross-Component`, `Architecture Impact`).

#### 2.1.4 Feindesign-Subprozess fuer Klasse 2 (FK-25 §25.5)

`src/agentkit/pipeline/phases/exploration/mandate/feindesign.py`:

```python
class FeindesignSubprocess:
    def run(self, change_frame: ChangeFrame, max_rounds: int = 10) -> FeindesignResult: ...

class FeindesignResult(BaseModel):
    status: Literal["converged", "max_rounds_exceeded"]
    rounds: int
    final_design_decisions: list[DesignDecision]
```

Vollausbau Multi-LLM-Diskussion (ChatGPT Pflicht, Qwen bevorzugt) ist out of scope — diese Story stellt das **Geruest** bereit:
- max_rounds=10 als Default
- Skelett-Implementation: ein einzelner StructuredEvaluator-Aufruf pro Runde (Multi-LLM ist Folge-Story)
- Result: `converged` oder `max_rounds_exceeded`

Wichtig: dieser Skelett-Pfad ist explizit dokumentiert (Docstring + TODO mit FK-25 §25.5-Verweis); volle Multi-LLM-Diskussion ist Folge-Story.

#### 2.1.5 `DesignFreezeMarker` (FK-23 §23.4.3)

`src/agentkit/pipeline/phases/exploration/freeze.py`:

```python
class DesignFreezeMarker:
    def __init__(self, artifact_manager: ArtifactManager) -> None: ...

    def freeze(self, change_frame: ChangeFrame) -> ChangeFrame:
        # Setze frozen=True, frozen_at=now()
        # Schreibe nach `_temp/qa/{story_id}/entwurfsartefakt.json` (read-only ab jetzt)
        # ArtifactManager-Update mit ArtifactClass.ENTWURF
        ...
```

Nach Freeze ist `_temp/qa/{story_id}/entwurfsartefakt.json` write-protected via `governance/protected_paths.py` (AG3-045 hat den Pfad vorbereitet; hier wird er bei Freeze tatsaechlich gelocked).

#### 2.1.6 Telemetrie-Events emittieren (FK-25 §25.8)

EventType-Werte sind in AG3-037 bereits ergaenzt. Diese Story emittiert sie:

- `mandate_classification` emittiert nach `MandateClassification.classify` mit Payload: `mandate_class`, `next_step`
- `fine_design_decision` emittiert pro Feindesign-Runde
- `scope_explosion_check` emittiert nach ScopeExplosionDetector
- `impact_exceedance_check` emittiert nach ImpactExceedanceChecker

Emission ueber existing `StateBackendEmitter`.

#### 2.1.7 Integration in ExplorationPhaseHandler

`src/agentkit/pipeline/phases/exploration/phase.py:ExplorationPhaseHandler.on_enter`:

Voller Flow:
1. ExplorationDrafting (AG3-045)
2. MandateClassification (diese Story)
3. ExplorationReview (AG3-046; nutzt MandateClassification-Result fuer Stage-2b-Aktivierung — DesignChallenge aktiv nur in bestimmten Klassen)
4. Wenn Gate APPROVED:
   - DesignFreezeMarker.freeze (diese Story)
   - `HandlerResult.COMPLETED`
5. Wenn Klasse 3 (Scope-Explosion):
   - Empfehlung: Story-Split via Operator (kein automatischer Split — StorySplitService ist nicht in der Erst-Welle)
   - `HandlerResult.ESCALATED` mit `suggested_reaction="scope_explosion_detected: recommend story split"`
6. Wenn Klasse 4 (Impact-Eskalation):
   - `HandlerResult.ESCALATED` mit `suggested_reaction="impact_exceedance: architecture review needed"`
7. Wenn Klasse 2 (Feindesign):
   - FeindesignSubprocess.run; bei converged -> weiter zum Review; bei max_rounds -> ESCALATED

#### 2.1.8 Tests

- Unit-Tests fuer `ScopeExplosionDetector` (mit/ohne 2 HIGH-Indikatoren)
- Unit-Tests fuer `ImpactExceedanceChecker` (Local declared, Architecture Impact actual)
- Unit-Tests fuer `MandateClassification.classify` (Klasse 1/2/3/4-Pfade)
- Unit-Tests fuer `FeindesignSubprocess.run` (converged + max_rounds)
- Unit-Tests fuer `DesignFreezeMarker.freeze` (frozen=True, ArtifactManager-Update)
- Integration-Test fuer `ExplorationPhaseHandler.on_enter` vollstaendig (alle vier Klassen-Pfade)
- Telemetrie-Event-Test: alle vier Event-Typen werden korrekt emittiert mit Pflicht-Payloads
- Contract-Test `tests/contract/exploration/test_mandate_classification.py`: vier Klassen + Pruefreihenfolge

### 2.2 Out of Scope

- Multi-LLM-Diskussion Vollausbau im Feindesign-Subprozess (`FK-25 §25.5` Detail "ChatGPT Pflicht, Qwen bevorzugt", Hub-Session-Summary, Hook-Monitoring) — Folge-Story
- StorySplitService (`story-lifecycle.A6`) — bewusst nicht in der Erst-Welle. Klasse-3-Pfad eskaliert nur mit Empfehlung; tatsaechlicher Split ist Operator-Aktion.
- StoryResetService — bewusst nicht in der Erst-Welle
- Drift-Erkennung in Implementation (`exploration-and-design.B4`) — gehoert zu THEME-009
- Frontend-UI fuer Mandate-Klassen — separate Folge-Story
- Cleanup Tests-Stub-Verzeichnis `tests/integration/pipeline/exploration_mode/` — hier befuellt, soweit fuer die Story-Tests noetig; Rest gehoert zu Folge-Stories

## 3. Betroffene Dateien

| Datei | Aenderungsart | Beschreibung |
|---|---|---|
| `src/agentkit/pipeline/phases/exploration/mandate/__init__.py` | Neu | |
| `src/agentkit/pipeline/phases/exploration/mandate/classification.py` | Neu | `MandateClassification`, `MandateClass`, `MandateClassificationResult` |
| `src/agentkit/pipeline/phases/exploration/mandate/scope_detector.py` | Neu | `ScopeExplosionDetector` |
| `src/agentkit/pipeline/phases/exploration/mandate/impact_checker.py` | Neu | `ImpactExceedanceChecker` |
| `src/agentkit/pipeline/phases/exploration/mandate/feindesign.py` | Neu | `FeindesignSubprocess` (Skelett) |
| `src/agentkit/pipeline/phases/exploration/freeze.py` | Neu | `DesignFreezeMarker` |
| `src/agentkit/pipeline/phases/exploration/phase.py` | Modifiziert | Voller Flow mit Klassifikation + Freeze + Telemetrie |
| `src/agentkit/governance/protected_paths.py` | Modifiziert | Entwurfsartefakt-Pfad-Lookup beruecksichtigt `frozen`-Flag |
| `tests/unit/pipeline/phases/exploration/mandate/...` | Neu | |
| `tests/unit/pipeline/phases/exploration/test_freeze.py` | Neu | |
| `tests/integration/pipeline/exploration/test_phase_full.py` | Neu | E2E aller Klassen |
| `tests/integration/pipeline/exploration_mode/test_klasse_routing.py` | Neu | Tests-Stub-Verzeichnis (befuellt) |
| `tests/contract/exploration/test_mandate_classification.py` | Neu | Klassen + Pruefreihenfolge |
| `tests/contract/exploration/test_telemetry_events.py` | Neu | vier Event-Typen Payload-Pinning |

## 4. Akzeptanzkriterien

1. **`MandateClassification.classify` durchlaeuft Pruefreihenfolge 1 -> 3 -> 4 -> 2** (FK-25 §25.4.1). Erster Treffer gewinnt.
2. **`MandateClass`-StrEnum** mit vier Werten (`klasse_1`, `klasse_2`, `klasse_3`, `klasse_4`).
3. **`ScopeExplosionDetector` triggert bei >=2 HIGH-Indikatoren** -> Klasse 3.
4. **`ImpactExceedanceChecker` erkennt declared < actual** -> Klasse 4.
5. **`FeindesignSubprocess`** liefert nach max 10 Runden Result `converged` oder `max_rounds_exceeded`. Tests bestaetigen beide Pfade.
6. **`DesignFreezeMarker.freeze`** setzt `frozen=True`, `frozen_at=now()`; nach Freeze ist Entwurfsartefakt-Pfad write-protected.
7. **Telemetrie-Events**: `mandate_classification`, `fine_design_decision`, `scope_explosion_check`, `impact_exceedance_check` werden mit korrekten Payloads emittiert. Tests bestaetigen das.
8. **`ExplorationPhaseHandler.on_enter` integriert vollstaendigen Flow** (Drafting -> Klassifikation -> Review -> Freeze). Klassen 3 und 4 -> ESCALATED mit aussagekraeftiger `suggested_reaction`.
9. **Klasse 2 -> FeindesignSubprocess**: wird aufgerufen; bei `converged` weiter zu Review; bei `max_rounds_exceeded` -> ESCALATED.
10. **Klasse 1 -> direkt zu Review** ohne Zusatz-Schritt.
11. **Pflichtbefehle gruen**: pytest unit + integration + contract; mypy --strict; ruff clean; Coverage haelt 85%.

## 5. Definition of Done

- AK 1-11 erfuellt.
- `.venv\Scripts\python -m pytest tests/unit/pipeline/phases/exploration tests/integration/pipeline/exploration tests/integration/pipeline/exploration_mode tests/contract/exploration -q` gruen.
- `mypy --strict` gruen, `ruff check src tests` gruen.
- Aenderungen committed auf `main`.

## 6. Konzept-Referenzen (autoritativ)

- **FK-25 §25.3** — Mandatsgrenzen
- **FK-25 §25.4.1** — Vier Klassen, Pruefreihenfolge
- **FK-25 §25.5** — Feindesign-Subprozess (Skelett)
- **FK-25 §25.6** — Scope-Explosion
- **FK-23 §23.4.3** — DesignFreezeMarker
- **FK-25 §25.8** — Telemetrie-Events

## 7. Guardrail-Referenzen

- **FIX THE MODEL, NOT THE SYMPTOM**: Mandatsgrenzen werden typsicher klassifiziert.
- **ZERO DEBT**: Pruefreihenfolge exakt nach Konzept; keine "spaeter Feindesign-Logik ergaenzen" — Skelett mit Verweis ist klar dokumentiert.
- **FAIL CLOSED**: Scope-Explosion und Impact-Eskalation eskalieren, kein silent Pass.
- **NO ERROR BYPASSING**: DesignFreeze macht das Entwurfsartefakt schreibgeschuetzt.

## 8. Hinweise fuer den Sub-Agent

- `MandateClassification.classify` durchlaeuft die Pruefungen in 1->3->4->2-Reihenfolge — nicht alphabetisch! Pruefe FK-25 §25.4.1.
- FeindesignSubprocess ist ein Skelett mit klarer Doku — kein heimliches Multi-LLM-Aufrufen erfinden. Folge-Story bringt das.
- `frozen`-Flag im ChangeFrame: nach DesignFreezeMarker.freeze nicht mehr editierbar. ProtectedPaths-Modul checkt das beim Schreibversuch.
- AK2 NICHT veraendern.
