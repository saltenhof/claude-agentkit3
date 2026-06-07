# AG3-037: TelemetryContract + neue Event-Typen + Risk-Window NormalizedEvent

**Typ:** Implementation
**Groesse:** M
**Abhaengigkeiten:** AG3-021 (Enums), AG3-022 (Envelope), AG3-035 (ProjectionAccessor)
**Quell-Konzepte (autoritativ, in dieser Reihenfolge):**
- `FK-68 §68.4` (agent_start/end-Paarung, llm_call-Pflicht-Rollen)
- `FK-68 §68.9` (preflight_compliant-Deckung, Preflight-Telemetrie-Stream)
- `FK-68 §68.10` (Integrity-Gate-Pruefung der Telemetrie)
- `FK-68 §68.8` (Governance-Risk-Window, NormalizedEvent)
- `FK-61 §61.12.1` (neue Event-Typen impact_violation_check, doc_fidelity_check, vectordb_search, compaction_event)
- `FK-61 §61.12.2` (angereicherte Payloads)
- `FK-25 §25.8` (mandate_classification, fine_design_decision events)

---

## 1. Kontext

THEME-007 aus `stories/_priorisierungsempfehlung.md`. Befunde:

- `telemetry-and-events.B1`: TelemetryContract als Modul fehlt — keine formalen Contract-Rules (agent_start/end-Paarung, review_compliant-Deckung, preflight_compliant-Gleichgewicht, llm_call-Pflicht-Rollen). Integrity-Gate kann ohne diesen Contract keine Telemetrie-Pruefung durchfuehren.
- `telemetry-and-events.B2`: Preflight-Telemetrie-Stream isoliert — Sentinel-Trennung nicht implementiert.
- `telemetry-and-events.A3`: NormalizedEvent fuer Risk-Window fehlt.
- `kpi-and-dashboard.A8`: neue Event-Typen `impact_violation_check`, `doc_fidelity_check`, `vectordb_search`, `compaction_event` fehlen (`IMPACT_VIOLATION_CHECK`, `DOC_FIDELITY_CHECK` sind in `events.py` aber nicht emittiert).
- `kpi-and-dashboard.A9`: angereicherte Payloads — `stage` in `integrity_violation`, `blocked_dimensions[]` in `integrity_gate_result`, `verdict` in `review_response`, Coverage-Felder in `are_gate_result`.
- `exploration-and-design.A7`: `mandate_classification`, `fine_design_decision`, `scope_explosion_check`, `impact_exceedance_check` fehlen in EventType.

Diese Story liefert den TelemetryContract als Pruef-Modul, ergaenzt die fehlenden EventTypes und implementiert NormalizedEvent fuer das Risk-Window.

**Scope-Charakter (autoritativ, vom holistischen Review entschieden):** AG3-037
ist eine **Library-/Surface-Story**. Sie liefert eine *konsumierbare* Oberflaeche:
das `TelemetryContract`-Modul (4 Regeln), den `PreflightSentinel`, den
Payload-Validator `validate_event_payload`, den `EventNormalizer` und die
Risk-Window-Persistenz (`record_risk_window_event`). Alle diese Deliverables sind
fachlich vollstaendig und getestet (kein Dead-Module-Claim). Die **Konsumption**
durch das Integrity-Gate (Dim 8 Telemetrie-Compliance, FK-68 §68.10) sowie die
**aktiven Domain-Emitter** (z.B. `mandate_classification`, `llm_call`-Pflicht in
den Produktionspfaden) sind bewusst auf **Folge-Stories** verschoben — sie haben
ihren eigenen Blast-Radius in `governance/integrity_gate` und die jeweiligen
BCs. Diese Story baut die Grundlage; sie verdrahtet sie nicht in das Gate (das
waere ein eigener Story-Scope). So bleibt der Library-Scope ehrlich und es
entsteht kein fail-open-Modul: die hier in Scope befindlichen Funktionen
(`validate_event_payload` raised; Preflight-Sentinel persistiert auch bei leerem
Stream; Normalizer; Risk-Window-Schreibstelle) sind alle echt funktional.

## 2. Scope

### 2.1 In Scope

#### 2.1.1 `TelemetryContract` (FK-68 §68.4/68.9/68.10)

Neues Modul `src/agentkit/telemetry/contract/telemetry_contract.py`:

```python
class TelemetryContract:
    """
    Formal-Rules-Repository: prueft, ob die Telemetrie eines Runs
    konzept-konform vollstaendig ist. Wird vom Integrity-Gate (Dim 8 Telemetrie-Compliance)
    konsumiert.
    """
    def __init__(self, projection_accessor: ProjectionAccessor) -> None: ...

    def check_agent_start_end_pairing(self, run_id: str) -> ContractRuleResult: ...
    def check_review_compliant_coverage(self, run_id: str, required_roles: set[str]) -> ContractRuleResult: ...
    def check_preflight_compliant_balance(self, run_id: str) -> ContractRuleResult: ...
    def check_llm_call_role_coverage(self, run_id: str, required_roles: set[str]) -> ContractRuleResult: ...

    def check_all(self, run_id: str, required_review_roles: set[str], required_llm_roles: set[str]) -> ContractCheckResult: ...
```

`ContractRuleResult` ist Pydantic-Modell:
- `rule_id: str` (z.B. `FK-68 §68.4.1`)
- `status: ContractStatus` (PASS | FAIL)
- `detail: str`

`ContractCheckResult` aggregiert alle Rule-Results.

#### 2.1.2 Preflight-Telemetrie-Stream-Sentinel (FK-68 §68.9)

`src/agentkit/telemetry/contract/preflight_sentinel.py`:

- Erkennung der Preflight-Events (`PREFLIGHT_REQUEST`, `PREFLIGHT_RESPONSE`, `PREFLIGHT_COMPLIANT`)
- Isolierte Zaehler-Regeln: pro Story muss Anzahl der `PREFLIGHT_REQUEST`-Events == Anzahl der `PREFLIGHT_COMPLIANT`-Events sein (Balance).
- Sentinel emittiert `preflight_compliance_violation` bei Ungleichgewicht.

#### 2.1.3 Neue Event-Typen (FK-61 §61.12.1, FK-25 §25.8)

`src/agentkit/telemetry/events.py:EventType` wird um die fehlenden Werte erweitert:

- `VECTORDB_SEARCH` (neu) — FK-61
- `COMPACTION_EVENT` (neu) — FK-61
- `MANDATE_CLASSIFICATION` (neu) — FK-25
- `FINE_DESIGN_DECISION` (neu) — FK-25
- `SCOPE_EXPLOSION_CHECK` (neu) — FK-25
- `IMPACT_EXCEEDANCE_CHECK` (neu) — FK-25 (bestaende: `IMPACT_VIOLATION_CHECK` ist davon zu unterscheiden — bleibt parallel)

`IMPACT_VIOLATION_CHECK` und `DOC_FIDELITY_CHECK` existieren bereits in `events.py` — die zugehoerigen Emitter werden in den jeweiligen BCs nachgeruestet (verify-system/exploration-and-design). Diese Story stellt die EventType-Werte und Pflicht-Payload-Felder bereit; aktive Emission ist Aufgabe der jeweiligen Domain-Stories (z.B. AG3-046 emittiert mandate_classification).

#### 2.1.4 Angereicherte Payloads (FK-61 §61.12.2)

Die Pflicht-Payload-Felder pro EventType werden via `EventType`-Sub-Klassen (Discriminated-Union) typisiert:

- `integrity_violation`: `stage` (Pflicht)
- `integrity_gate_result`: `blocked_dimensions: list[IntegrityDimension]` (Pflicht)
- `review_response`: `verdict: LlmEnvelopeStatus` (Pflicht)
- `are_gate_result`: Coverage-Felder (`covered: int`, `required: int`, `coverage_ratio: float`)

Implementation: `ExecutionEventRecord.payload` bleibt `dict[str, Any]`, aber pro EventType eine `validate_event_payload`-Funktion in `agentkit.telemetry.events`. Aufrufer-Validierung sichert, dass die richtigen Felder gesetzt sind.

#### 2.1.5 NormalizedEvent + Risk-Window (FK-68 §68.8)

`src/agentkit/telemetry/risk_window/normalized_event.py`:

```python
class NormalizedEvent(BaseModel):
    """
    Normalisierte Form eines ExecutionEventRecord fuer das Governance-Risk-Window.
    Reduziert die Vielfalt von EventType auf wenige Risikodimensionen.
    """
    event_id: str   # consistent with ExecutionEventRecord.event_id: str (canonical
                    # event ID, FK-68 §68.2.1). Not migrated to UUID: that would be a
                    # cross-codebase change to the canonical event-id type, out of scope.
    story_id: str
    run_id: str
    risk_category: RiskCategory   # StrEnum: SECURITY, INTEGRITY, OPERATIONAL, BUDGET
    severity: Severity            # aus core_types (BLOCKING/MAJOR/MINOR)
    observed_at: datetime
    source_event_type: EventType
    payload_excerpt: dict[str, Any]
```

`Normalizer`:

```python
class EventNormalizer:
    def normalize(self, record: ExecutionEventRecord) -> NormalizedEvent | None:
        # Mapping von EventType auf RiskCategory
        # None wenn das Event nicht risikorelevant ist
        ...
```

Risk-Window-Persistenz via dedizierter `ProjectionAccessor.record_risk_window_event(normalized_event)`-Methode, die in eine eigene `risk_window`-Tabelle schreibt. **Keine** neue `ProjectionKind RISK_WINDOW`: das Risk-Window ist ein FK-68-Telemetrie-Sensor-Read-Model und kein FK-69-Read-Model. FK-69 §69.3 bleibt unveraendert bei **exakt 7** Read-Model-Tabellen; ein 8tes `ProjectionKind` wuerde diese Invariante verletzen. Die dedizierte Methode + Tabelle haelt das Risk-Window sauber von den FK-69-Read-Models getrennt (FIX THE MODEL: klarer Owner, keine Vermischung der zwei Read-Model-Familien).

GovernanceObserver-Scoring (`governance-and-guards.A1`) bleibt **out of scope** (nicht in der Erst-Welle). Diese Story stellt nur die Schreibstelle bereit.

#### 2.1.6 Tests

- Unit-Tests fuer alle vier TelemetryContract-Rules
- Unit-Tests fuer Preflight-Sentinel (Balance check)
- Unit-Test fuer neue EventType-Werte (Pflicht-Payload-Felder pro Type)
- Unit-Tests fuer `EventNormalizer.normalize` (jede RiskCategory)
- Integration-Test: ein Worker-Lauf erzeugt agent_start/end, review_request/response/compliant; `TelemetryContract.check_all` liefert PASS
- Contract-Test `tests/contract/telemetry/test_event_catalog.py`: vollstaendige Liste der EventType-Werte mit zugehoerigen Pflicht-Payload-Feldern

### 2.2 Out of Scope

- **Integrity-Gate Dim 8 Telemetrie-Compliance-Verdrahtung (FK-68 §68.10)** —
  die *Konsumption* von `TelemetryContract.check_all` durch das Integrity-Gate
  ist eine eigene Folge-Story mit Blast-Radius in `governance/integrity_gate`.
  AG3-037 liefert nur die konsumierbare Oberflaeche, nicht die Gate-Anbindung.
- **Aktive Produktions-Emitter** der vom Contract geprueften Events
  (`agent_start/end`-Paarung im echten Pfad, `llm_call`-Pflichtrollen,
  `mandate_classification` etc.) — Aufgabe der jeweiligen Domain-Stories
  (z.B. AG3-046). AG3-037 stellt EventType-Werte + Pflicht-Payload-Vertraege bereit.
- GovernanceObserver (`governance-and-guards.A1`) — bewusst nicht in der Erst-Welle
- Workflow-Metriken-Felder Vollausbau (`B3`) — Folge-Story (adversarial_findings, adversarial_tests_created, files_changed, agentkit_commit als Pflicht-Felder)
- SSE-Topic-Mapping-Korrektur (`B5`) — Folge-Story
- TelemetryService-Schreibgrenze (`C1`) — Folge-Story
- compute_pipeline_metrics-qa_rounds-Bug (`C2`) — Folge-Story
- Aktive Emitter fuer `mandate_classification` etc. in Exploration-BC — AG3-046
- WorkerHealth-Events — bewusst nicht in der Erst-Welle
- Planning-Events — bewusst nicht in der Erst-Welle
- ARE-Events — kommt mit ARE-Vollausbau

## 3. Betroffene Dateien

| Datei | Aenderungsart | Beschreibung |
|---|---|---|
| `src/agentkit/telemetry/contract/__init__.py` | Modifiziert | Re-Export TelemetryContract |
| `src/agentkit/telemetry/contract/telemetry_contract.py` | Neu | TelemetryContract-Klasse |
| `src/agentkit/telemetry/contract/preflight_sentinel.py` | Neu | Preflight-Balance-Check |
| `src/agentkit/telemetry/events.py` | Modifiziert | Neue EventType-Werte + `validate_event_payload`-Funktion |
| `src/agentkit/telemetry/risk_window/__init__.py` | Neu | |
| `src/agentkit/telemetry/risk_window/normalized_event.py` | Neu | NormalizedEvent + RiskCategory |
| `src/agentkit/telemetry/risk_window/normalizer.py` | Neu | EventNormalizer |
| `src/agentkit/telemetry/projection_accessor.py` | Modifiziert | ProjectionKind ggf. um RISK_WINDOW erweitert |
| `tests/unit/telemetry/contract/...` | Neu | |
| `tests/unit/telemetry/risk_window/...` | Neu | |
| `tests/contract/telemetry/test_event_catalog.py` | Neu | Pflicht-Liste der EventType-Werte + Payload-Felder |

## 4. Akzeptanzkriterien

1. **`TelemetryContract` existiert** mit vier Rule-Methoden plus `check_all`. Jede Rule liefert `ContractRuleResult`.
2. **Preflight-Sentinel** prueft `len(PREFLIGHT_REQUEST) == len(PREFLIGHT_COMPLIANT)` pro Story. Verstoss -> FAIL mit `rule_id="FK-68 §68.9.2"`.
3. **Neue EventType-Werte ergaenzt**: `VECTORDB_SEARCH`, `COMPACTION_EVENT`, `MANDATE_CLASSIFICATION`, `FINE_DESIGN_DECISION`, `SCOPE_EXPLOSION_CHECK`, `IMPACT_EXCEEDANCE_CHECK`.
4. **`validate_event_payload(event_type, payload)`** prueft Pflicht-Felder pro EventType; missing -> Exception.
5. **`NormalizedEvent` und `EventNormalizer.normalize` existieren** und liefern `NormalizedEvent | None`. Mapping: `agent_start`/`agent_end` -> OPERATIONAL; `integrity_violation` -> INTEGRITY; `review_divergence` -> INTEGRITY; `web_call_attempted` -> BUDGET (in research-Stories).
6. **`RiskCategory`-StrEnum** mit Werten `SECURITY`, `INTEGRITY`, `OPERATIONAL`, `BUDGET`.
7. **Dedizierte `ProjectionAccessor.record_risk_window_event(...)`-Schreibstelle + eigene `risk_window`-Tabelle**; der `EventNormalizer` schreibt NormalizedEvents ueber diese Methode dorthin. **Kein** neues `ProjectionKind RISK_WINDOW`: FK-69 §69.3 bleibt bei exakt 7 Read-Model-Tabellen (das Risk-Window ist ein FK-68-Telemetrie-Sensor-Read-Model, kein 8tes FK-69-Read-Model). Rationale: getrennter Owner haelt die FK-68- und FK-69-Read-Model-Familien sauber entkoppelt und schuetzt die FK-69-7er-Invariante.
8. **Architecture-Conformance**: `telemetry.contract` und `telemetry.risk_window` importieren nur aus `agentkit.core_types`, `agentkit.telemetry`, `agentkit.artifacts`; keine Cross-BC-Aufrufe.
9. **Pflichtbefehle gruen**: pytest unit + integration + contract; mypy --strict; ruff clean; Coverage haelt 85%.

## 5. Definition of Done

- AK 1-9 erfuellt.
- `.venv\Scripts\python -m pytest tests/unit/telemetry tests/integration/telemetry tests/contract/telemetry -q` gruen.
- `mypy --strict` gruen, `ruff check src tests` gruen.
- Aenderungen committed auf `main`.

## 6. Konzept-Referenzen (autoritativ)

- **FK-68 §68.4** — Pairing-Regeln
- **FK-68 §68.9** — Preflight-Stream
- **FK-68 §68.10** — Integrity-Gate-Pruefung
- **FK-68 §68.8** — Risk-Window
- **FK-61 §61.12.1/61.12.2** — Event-Typen + Payloads
- **FK-25 §25.8** — Exploration-Events

## 7. Guardrail-Referenzen

- **FIX THE MODEL, NOT THE SYMPTOM**: TelemetryContract als Pruefmodul — Integrity-Gate hat endlich eine Grundlage.
- **ZERO DEBT**: alle EventTypes + Payloads vollstaendig.
- **FAIL CLOSED**: missing Pflicht-Payload-Feld -> Exception.

## 8. Hinweise fuer den Sub-Agent

- EventType erweitern: pruefe bestehende Liste in `events.py`. Werte alphabetisch oder nach Domaene gruppiert.
- AK2 NICHT veraendern.
