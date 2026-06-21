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
        # AG3-030 Pass-1 Korrektur: is_enabled spiegelt nur features.are (FAIL-CLOSED:
        # fehlender AreClient bei features.are=True ist Konfigurationsfehler, kein
        # Disabled-Zustand). Siehe AK6.
        return self._pipeline_config.features.are is True

    def link_requirements(self, story_id: str, project_key: str) -> LinkResult:
        if not self.is_enabled:
            return LinkResult(status=AreDockpointStatus.SKIPPED, reason="feature_disabled")
        if self._are_client is None:
            raise AreConfigurationError("features.are=True but AreClient missing")
        # Andock-Punkt 1 — Full-Implementation in Folge-Story
        raise AreCapabilityNotImplementedError(
            "link_requirements full body in follow-up story"
        )

    def load_context(self, story_id: str, project_key: str, run_id: str) -> ContextLoadResult:
        if not self.is_enabled:
            return ContextLoadResult(status=AreDockpointStatus.SKIPPED, are_bundle_ref=None)
        if self._are_client is None:
            raise AreConfigurationError("features.are=True but AreClient missing")
        raise AreCapabilityNotImplementedError(
            "load_context full body in follow-up story"
        )

    def submit_evidence(self, story_id: str, evidence: AreEvidence) -> EvidenceSubmitResult:
        if not self.is_enabled:
            return EvidenceSubmitResult(status=AreDockpointStatus.SKIPPED)
        if self._are_client is None:
            raise AreConfigurationError("features.are=True but AreClient missing")
        raise AreCapabilityNotImplementedError(
            "submit_evidence full body in follow-up story"
        )

    def check_gate(self, story_id: str, project_key: str) -> CoverageVerdict:
        if not self.is_enabled:
            return CoverageVerdict(status=AreDockpointStatus.SKIPPED, verdict=None)
        if self._are_client is None:
            raise AreConfigurationError("features.are=True but AreClient missing")
        # In der Folge-Story wird hier fail-closed CoverageVerdict(status=FAIL,
        # reason="are_gate_unavailable") zurueckgegeben, sobald Layer-1 verdrahtet
        # ist (THEME-009 / AG3-042).
        raise AreCapabilityNotImplementedError(
            "check_gate full body in follow-up story"
        )
```

<!-- AG3-030 deep-review: NotImplementedError pro Enabled-Pfad zu fein typisiert (AreConfigurationError vs AreCapabilityNotImplementedError). check_gate wandert in der Folge-Story von Exception zu CoverageVerdict(status=FAIL, reason="are_gate_unavailable"), weil FK-40 ARE-Gate als Pflicht-Gate definiert (kein graceful-degradation). -->

**Wichtiger Kontext (Vertrags-Slot, nicht Produktionsverhalten)**: `AreCapabilityNotImplementedError` bei `features.are: true` ist nur ein Contract-Pinning fuer AG3-030 und darf NICHT in einen produktiven Pipelinepfad eingebunden werden. Solange die Andock-Punkte nicht implementiert sind, darf kein Installer-/Runtime-Pfad ein Projekt mit `features.are: true` als vollstaendig verifiziert registrieren. Folge-Stories (THEME-009) muessen enabled-ARE von `AreCapabilityNotImplementedError` auf echte `PASS/FAIL/FAILED`-Resultate umstellen.

`AreDockpointStatus` ist StrEnum: `SKIPPED`, `PASS`, `FAIL`, `ERROR`.

#### 2.1.2 `AreClient`-Skelett (FK-40 §40.4)

<!-- AG3-030 deep-review: AreClient gehoert per FK-40 §40.4 in agentkit.backend.requirements_coverage.are_client (BC-internes Sub), NICHT in agentkit.integration_clients.are.client. FK-40 §40.4: "AgentKit-Code kommuniziert ausschliesslich ueber AreClient-Sub agentkit.backend.requirements_coverage.are_client". Pfadkorrektur. -->

`src/agentkit/requirements_coverage/are_client.py` (NICHT `agentkit.integration_clients.are.client`):

```python
class AreClient:
    def __init__(self, base_url: str, auth_token: str | None = None) -> None: ...

    def list_requirements(self, story_id: str, scope: str) -> list[AreRequirement]:
        raise NotImplementedError("AreClient.list_requirements is follow-up")
    def get_recurring(self, scope: str, story_type: str) -> list[AreRequirement]:
        raise NotImplementedError("AreClient.get_recurring is follow-up")
    def load_context(self, story_id: str) -> AreContext:
        raise NotImplementedError("AreClient.load_context is follow-up")
    def submit_evidence(
        self,
        story_id: str,
        requirement_id: str,
        evidence_type: EvidenceType,
        evidence_ref: str,
    ) -> EvidenceSubmitResult:
        raise NotImplementedError("AreClient.submit_evidence is follow-up")
    def check_gate(self, story_id: str) -> CoverageVerdict:
        raise NotImplementedError("AreClient.check_gate is follow-up")
```

<!-- AG3-030 deep-review: Signaturen an FK-40 §40.4.1 REST-Endpunkte angeglichen. list_requirements braucht story_id; get_recurring braucht scope+story_type; load_context nimmt story_id (nicht requirement_ids); submit_evidence ist strukturiert (evidence_type + evidence_ref); check_gate braucht nur story_id. -->

Begruendung NotImplementedError: HTTP-Adapter mit echtem REST-Code ist viel Arbeit fuer eine eigene Folge-Story. Diese Story stellt sicher, dass die Klasse mit korrekten Signaturen existiert; spaeter wird der Body befuellt.

`src/agentkit/integrations/are/` bleibt unveraendert (keine Re-Exports), weil AreClient BC-internes Sub ist.

#### 2.1.3 Datenmodelle

<!-- AG3-030 deep-review: AreRequirement um requirement_type, description, must_cover ergaenzt; AreEvidence von freiem Text auf evidence_type+evidence_ref umgestellt (FK-40 Evidence-Reference-Vertrag). -->

`src/agentkit/requirements_coverage/contract.py`:

- `AreRequirement` (Pydantic-Modell):
  - `requirement_id: str`
  - `requirement_type: AreRequirementType` (StrEnum gemaess FK-40)
  - `summary: str`
  - `description: str | None`
  - `must_cover: bool`
  - `acceptance_criteria: list[str]`
  - `recurring: bool`
- `AreContext`: `requirements: list[AreRequirement]`, `loaded_at`
- `AreEvidence`:
  - `requirement_id: str`
  - `evidence_type: EvidenceType` (StrEnum: `TEST_REPORT`, `COMMIT_REF`, `ARTIFACT_REF`, `MANUAL_NOTE`)
  - `evidence_ref: str`
  - `produced_by: EvidenceProducer` (StrEnum: `WORKER`, `QA`)
- `LinkResult`, `ContextLoadResult`, `EvidenceSubmitResult`, `CoverageVerdict` als Result-Modelle

Alle frozen, extra forbid.

#### 2.1.4 `__init__.py`-Export erweitern

Aktuell exportiert `src/agentkit/requirements_coverage/__init__.py` nur `StoryAreLink`-Symbole. Erweitert um `RequirementsCoverage`, `AreClient`, alle Datenmodelle, `AreDockpointStatus`.

#### 2.1.5 Stale-`are_item_id`-Behandlung — verschoben

<!-- AG3-030 deep-review: Stale-Erkennung gehoert nicht ins Repository. FK-40 normiert: stale ARE-Items werden beim Andock-Punkt 4 (check_gate) sichtbar, AreClient.check_gate meldet das Item als unbekannt, das Gate setzt FAIL mit Stale-Hinweis. Das aktuelle StoryAreLink-Istmodell hat ausserdem kein Statusfeld. -->

Stale-Erkennung ist **nicht Scope von AG3-030**. AG3-030 stellt nur sicher, dass bestehende `StoryAreLink`-Modelle und Repository-Protokolle unveraendert importierbar bleiben.

Stale-Behandlung wird in der ARE-Gate-Folge-Story (THEME-009, AG3-042) implementiert:
- `RequirementsCoverage.check_gate(story_id)` ruft `AreClient.check_gate(story_id)` auf
- Unbekannte/stale ARE-Items fuehren zu `CoverageVerdict(status=FAIL, stale_items=[...])`

**Story-Reset-Verhalten** (FK-40 §40.5b.4): `StoryAreLink`-Eintraege ueberleben Reset. Wenn dazu noch kein Regressionstest existiert, darf in dieser Story ein einfacher Repository-Regressionstest hinzukommen, **ohne** Schema- oder Statusfeld-Aenderung.

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
- StageRegistry-Registrierung der ARE-Stage — NICHT Scope. `requirements_coverage` liefert nur `check_gate`-Logik; Registrierung und Auswertung als Layer-1-Stage gehoeren zu `verify-system` (FK-40 §40.7). <!-- AG3-030 deep-review -->
- Stale-`are_item_id`-Behandlung im Repository — verschoben in ARE-Gate-Folge-Story (siehe 2.1.5).

## 3. Betroffene Dateien

| Datei | Aenderungsart | Beschreibung |
|---|---|---|
| `src/agentkit/requirements_coverage/__init__.py` | Modifiziert | Exportiert `RequirementsCoverage`, `AreClient`, Datenmodelle, `AreDockpointStatus` |
| `src/agentkit/requirements_coverage/top.py` | Neu | `RequirementsCoverage`-Klasse |
| `src/agentkit/requirements_coverage/are_client.py` | Neu | `AreClient`-Klasse mit NotImplementedError-Stubs (BC-internes Sub, FK-40 §40.4) <!-- AG3-030 deep-review: Pfadkorrektur. --> |
| `src/agentkit/requirements_coverage/contract.py` | Neu | Datenmodelle inkl. `EvidenceType`, `EvidenceProducer`, `AreRequirementType` |
| `src/agentkit/requirements_coverage/errors.py` | Neu | typisierte Exceptions inkl. `AreConfigurationError`, `AreCapabilityNotImplementedError` |
| `tests/unit/requirements_coverage/test_top.py` | Neu | Top-Surface-Tests |
| `tests/unit/requirements_coverage/test_contract.py` | Neu | Datenmodelle |
| `tests/unit/requirements_coverage/test_are_client.py` | Neu | AreClient-Skelett-Asserts |
| `tests/contract/requirements_coverage/test_top_surface.py` | Neu | Vertrags-Pinning |

## 4. Akzeptanzkriterien

1. **`RequirementsCoverage`-Klasse existiert** und ist via `from agentkit.backend.requirements_coverage import RequirementsCoverage` importierbar.
2. **`is_enabled`-Property** liefert `True` wenn Pipeline-Config `features.are == True` und `AreClient` gesetzt ist; sonst `False`.
3. **Vier Top-Methoden**: `link_requirements`, `load_context`, `submit_evidence`, `check_gate`. Jede prueft `is_enabled` zuerst. Wenn `False`: gibt Result-Modell mit `status=SKIPPED` zurueck (kein Fehler, keine Exception). Wenn `True`: `NotImplementedError` mit Verweis auf Folge-Story.
4. **`AreClient`-Klasse existiert** unter `src/agentkit/requirements_coverage/are_client.py` mit fuenf Methoden gemaess FK-40 §40.4.1: `list_requirements(story_id, scope)`, `get_recurring(scope, story_type)`, `load_context(story_id)`, `submit_evidence(story_id, requirement_id, evidence_type, evidence_ref)`, `check_gate(story_id)`. Alle werfen `NotImplementedError` mit "follow-up"-Verweis. <!-- AG3-030 deep-review: Pfad + Signaturen korrigiert. -->
5. **Result-Modelle** sind frozen, extra forbid: `LinkResult`, `ContextLoadResult`, `EvidenceSubmitResult`, `CoverageVerdict`.
6. **`features.are: true`-Pfad**: bei aktivierter ARE und fehlendem `AreClient` wirft jede Methode `AreConfigurationError`; bei aktivierter ARE und vorhandenem `AreClient` wirft jede Methode `AreCapabilityNotImplementedError` mit Verweis auf die Folge-Story (Vertrags-Slot, kein produktives Verhalten). <!-- AG3-030 deep-review: ehemals AK 6 (Stale-Erkennung) ersetzt — Stale wandert in Folge-Story. -->
7. **Architecture-Conformance**: `agentkit.backend.requirements_coverage` importiert nur `agentkit.backend.core_types`, `agentkit.backend.config`; nicht aus `agentkit.integration_clients.are` (AreClient ist BC-internes Sub) und nicht direkt aus state_backend.store-Fassaden ausserhalb Repository-Module.
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

- Pipeline-Config `features.are`: existiert vermutlich bereits in `agentkit.backend.config`. Falls noch nicht: schmaler Pydantic-Sub-Block `Features(are: bool = False)`. Prueft Source vor Aenderung.
- AK2 NICHT veraendern.
