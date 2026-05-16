# AG3-030: RequirementsCoverage BC — Top-Surface mit no-op-Aktivierungslogik + AreClient-Skelett

**Typ:** Implementation
**Groesse:** M
**Abhaengigkeiten:** AG3-021 (Enums), AG3-022 (`ArtifactClass`-Bezug fuer are_bundle)
**Quell-Konzepte (autoritativ, in dieser Reihenfolge):**
- `concept/_meta/bc-cut-decisions.md §BC 15 requirements-and-scope-coverage`
- `FK-40 §40.2` (Top-Surface no-op-Logik bei `features.are: false`)
- `FK-40 §40.4` (AreClient REST-Adapter)
- `FK-40 §40.5.1-40.5.4` (vier Andock-Punkte)
- `formal.deterministic-checks.invariants §are-gate-required-only-when-enabled`

---

## 1. Kontext

THEME-005 aus `stories/_priorisierungsempfehlung.md`. Befunde aus `requirements-and-scope-coverage`-GAP-Analyse:

- `requirements-and-scope-coverage.A6/C1`: BC-Surface exportiert keine `RequirementsCoverage`-Klasse. Aufrufer-BCs koennen die vorgesehene Top-Surface nicht importieren; kein Aktivierungs-Check (`features.are`).
- `requirements-and-scope-coverage.A1`: `AreClient` REST-Adapter fehlt — `src/agentkit/integrations/are/__init__.py` ist leer.
- `requirements-and-scope-coverage.A2-A5`: vier Andock-Punkte nicht implementiert. Diese Story liefert die **Surface mit no-op-Pfaden**; volle Andock-Implementierung in Folge-Stories nach AG3-022/AG3-023 (ARE-Bundle braucht ArtifactManager) und nach Layer-1-Vollausbau (AG3-042 fuer ARE-Gate).
- `requirements-and-scope-coverage.A6`: Aktivierungslogik `features.are: false` -> SKIPPED.

## 2. Scope

### 2.1 In Scope

#### 2.1.1 `RequirementsCoverage`-Top-Surface (FK-40 §40.2)

`src/agentkit/requirements_coverage/top.py`:

```python
class RequirementsCoverage:
    def __init__(self, are_client: AreClient | None, pipeline_config: PipelineConfig) -> None: ...

    @property
    def is_enabled(self) -> bool:
        return self._pipeline_config.features.are is True and self._are_client is not None

    def link_requirements(self, story_id: str, project_key: str) -> LinkResult:
        if not self.is_enabled:
            return LinkResult(status=AreDockpointStatus.SKIPPED, reason="feature_disabled")
        # Andock-Punkt 1 — Full-Implementation in Folge-Story
        raise NotImplementedError("link_requirements full body in follow-up story")

    def load_context(self, story_id: str, project_key: str, run_id: str) -> ContextLoadResult:
        if not self.is_enabled:
            return ContextLoadResult(status=AreDockpointStatus.SKIPPED, are_bundle_ref=None)
        raise NotImplementedError("load_context full body in follow-up story")

    def submit_evidence(self, story_id: str, evidence: AreEvidence) -> EvidenceSubmitResult:
        if not self.is_enabled:
            return EvidenceSubmitResult(status=AreDockpointStatus.SKIPPED)
        raise NotImplementedError("submit_evidence full body in follow-up story")

    def check_gate(self, story_id: str, project_key: str) -> CoverageVerdict:
        if not self.is_enabled:
            return CoverageVerdict(status=AreDockpointStatus.SKIPPED, verdict=None)
        raise NotImplementedError("check_gate full body in follow-up story")
```

`AreDockpointStatus` ist StrEnum: `SKIPPED`, `PASS`, `FAIL`, `ERROR`.

#### 2.1.2 `AreClient`-Skelett (FK-40 §40.4)

`src/agentkit/integrations/are/client.py`:

```python
class AreClient:
    def __init__(self, base_url: str, auth_token: str | None = None) -> None: ...

    def list_requirements(self, scope: str) -> list[AreRequirement]:
        raise NotImplementedError("AreClient.list_requirements is follow-up")
    def get_recurring(self) -> list[AreRequirement]:
        raise NotImplementedError("AreClient.get_recurring is follow-up")
    def load_context(self, requirement_ids: list[str]) -> AreContext:
        raise NotImplementedError("AreClient.load_context is follow-up")
    def submit_evidence(self, requirement_id: str, evidence: AreEvidence) -> None:
        raise NotImplementedError("AreClient.submit_evidence is follow-up")
    def check_gate(self, story_id: str, scope: str) -> CoverageVerdict:
        raise NotImplementedError("AreClient.check_gate is follow-up")
```

Begruendung NotImplementedError: HTTP-Adapter mit echtem REST-Code ist viel Arbeit fuer eine eigene Folge-Story. Diese Story stellt sicher, dass die Klasse mit korrekten Signaturen existiert; spaeter wird der Body befuellt.

#### 2.1.3 Datenmodelle

`src/agentkit/requirements_coverage/contract.py`:

- `AreRequirement` (Pydantic-Modell): `requirement_id`, `summary`, `acceptance_criteria`, `recurring: bool`
- `AreContext`: `requirements: list[AreRequirement]`, `loaded_at`
- `AreEvidence`: `requirement_id`, `evidence_text`, `produced_by` (worker/qa)
- `LinkResult`, `ContextLoadResult`, `EvidenceSubmitResult`, `CoverageVerdict` als Result-Modelle

Alle frozen, extra forbid.

#### 2.1.4 `__init__.py`-Export erweitern

Aktuell exportiert `src/agentkit/requirements_coverage/__init__.py` nur `StoryAreLink`-Symbole. Erweitert um `RequirementsCoverage`, `AreClient`, alle Datenmodelle, `AreDockpointStatus`.

#### 2.1.5 Stale-`are_item_id`-Behandlung (B1 Detail, FK-40 §40.5b.5)

`src/agentkit/state_backend/store/story_are_link_repository.py:StateBackendStoryAreLinkRepository.update_kind` und `remove` werden um Stale-Erkennung ergaenzt:

- Wenn ein `are_item_id` an einer Story haengt, die nicht mehr im ARE-System existiert: `STALE`-Status (neue StrEnum `StoryAreLinkStatus`) wird markiert.
- Story-Reset-Verhalten: Eintraege ueberleben Reset (FK-40 §40.5b.4) — Test bestaetigt das.

Diese Detail-Erweiterung ist klein und passt natuerlich in die BC-Top-Surface-Story.

#### 2.1.6 Tests

- Unit-Tests fuer `RequirementsCoverage.is_enabled` (Pipeline-Config mit/ohne `features.are`)
- Unit-Tests fuer alle vier Methoden: no-op SKIPPED wenn disabled, NotImplementedError wenn enabled (mit Verweis auf Folge-Story)
- Unit-Tests fuer Datenmodelle (Pflichtfelder, frozen)
- Test fuer Stale-`are_item_id`-Behandlung im Repository
- Contract-Test `tests/contract/requirements_coverage/test_top_surface.py`: alle vier Methoden mit Signaturen + `is_enabled`-Property

### 2.2 Out of Scope

- Volle AreClient-Implementierung (REST-Endpunkte) — Folge-Story
- Andock-Punkt 1 — Anforderungen verlinken (`requirements-and-scope-coverage.A2`) — Folge-Story
- Andock-Punkt 2 — Anforderungskontext laden (`A3`) inkl. ArtifactManager-Integration — Folge-Story
- Andock-Punkt 3 — Evidence einreichen (`A4`) — Folge-Story
- Andock-Punkt 4 — ARE-Gate pruefen (`A5`) — gehoert zu THEME-009 (Layer-1-Vollausbau, AG3-042)
- `ScopeMapping`-Sub (`A7`) — Folge-Story (Schreib-Owner ist installation-and-bootstrap)
- Telemetrie-Events fuer ARE (`A8`) — THEME-007 (AG3-037)
- Frontend Lese-API (`B2`) — Folge-Story

## 3. Betroffene Dateien

| Datei | Aenderungsart | Beschreibung |
|---|---|---|
| `src/agentkit/requirements_coverage/__init__.py` | Modifiziert | Exportiert `RequirementsCoverage`, Datenmodelle, `AreDockpointStatus` |
| `src/agentkit/requirements_coverage/top.py` | Neu | `RequirementsCoverage`-Klasse |
| `src/agentkit/requirements_coverage/contract.py` | Neu | Datenmodelle |
| `src/agentkit/requirements_coverage/errors.py` | Neu | typisierte Exceptions |
| `src/agentkit/integrations/are/__init__.py` | Modifiziert | Re-Export `AreClient` |
| `src/agentkit/integrations/are/client.py` | Neu | `AreClient`-Klasse mit NotImplementedError-Stubs |
| `src/agentkit/state_backend/store/story_are_link_repository.py` | Modifiziert | Stale-Erkennung in update_kind/remove |
| `tests/unit/requirements_coverage/test_top.py` | Neu | Top-Surface-Tests |
| `tests/unit/requirements_coverage/test_contract.py` | Neu | Datenmodelle |
| `tests/unit/integrations/are/test_client.py` | Neu | Skelett-Asserts |
| `tests/unit/state_backend/store/test_story_are_link_stale.py` | Neu | Stale-Tests |
| `tests/contract/requirements_coverage/test_top_surface.py` | Neu | Vertrags-Pinning |

## 4. Akzeptanzkriterien

1. **`RequirementsCoverage`-Klasse existiert** und ist via `from agentkit.requirements_coverage import RequirementsCoverage` importierbar.
2. **`is_enabled`-Property** liefert `True` wenn Pipeline-Config `features.are == True` und `AreClient` gesetzt ist; sonst `False`.
3. **Vier Top-Methoden**: `link_requirements`, `load_context`, `submit_evidence`, `check_gate`. Jede prueft `is_enabled` zuerst. Wenn `False`: gibt Result-Modell mit `status=SKIPPED` zurueck (kein Fehler, keine Exception). Wenn `True`: `NotImplementedError` mit Verweis auf Folge-Story.
4. **`AreClient`-Klasse existiert** mit fuenf Methoden (`list_requirements`, `get_recurring`, `load_context`, `submit_evidence`, `check_gate`); alle werfen `NotImplementedError` mit "follow-up"-Verweis.
5. **Result-Modelle** sind frozen, extra forbid: `LinkResult`, `ContextLoadResult`, `EvidenceSubmitResult`, `CoverageVerdict`.
6. **Stale-`are_item_id`-Behandlung**: `StoryAreLinkStatus`-StrEnum mit `ACTIVE`, `STALE` ist im Repository nutzbar; `update_kind`/`remove` koennen Eintraege als STALE markieren statt zu loeschen.
7. **Architecture-Conformance**: `agentkit.requirements_coverage` importiert nur `agentkit.core_types`, `agentkit.config`, `agentkit.integrations.are`; nicht direkt aus state_backend.store-Fassaden ausserhalb Repository-Module.
8. **Pflichtbefehle gruen**: pytest unit + contract; mypy --strict; ruff clean; Coverage haelt 85%.

## 5. Definition of Done

- AK 1-8 erfuellt.
- `.venv\Scripts\python -m pytest tests/unit/requirements_coverage tests/unit/integrations/are tests/contract/requirements_coverage -q` gruen.
- `mypy --strict` gruen, `ruff check src tests` gruen.
- Aenderungen committed auf `main`.

## 6. Konzept-Referenzen (autoritativ)

- **`concept/_meta/bc-cut-decisions.md §BC 15`** — Top-Surface
- **FK-40 §40.2** — no-op-Aktivierungslogik
- **FK-40 §40.4** — AreClient
- **FK-40 §40.5.1-40.5.4** — vier Andock-Punkte
- **`formal.deterministic-checks.invariants §are-gate-required-only-when-enabled`** — Aktivierungsregel

## 7. Guardrail-Referenzen

- **FIX THE MODEL, NOT THE SYMPTOM**: Top-Surface mit klarer Aktivierungslogik; keine impliziten Aufrufer-Fallbacks.
- **ZERO DEBT**: NotImplementedError mit explizitem Verweis auf Folge-Story; nicht "stille leere Liste".
- **FAIL CLOSED**: bei aktivierter ARE laeuft kein Andockpunkt durch ohne Implementation.

## 8. Hinweise fuer den Sub-Agent

- Pipeline-Config `features.are`: existiert vermutlich bereits in `agentkit.config`. Falls noch nicht: schmaler Pydantic-Sub-Block `Features(are: bool = False)`. Prueft Source vor Aenderung.
- AK2 NICHT veraendern.
