# AG3-035: ProjectionAccessor zentralisieren + Reset-Purge fuer FK-69-Tabellen

**Typ:** Implementation
**Groesse:** M
**Abhaengigkeiten:** AG3-021 (Enums), AG3-022 (Envelope fuer Projection-Records)
**Quell-Konzepte (autoritativ, in dieser Reihenfolge):**
- `FK-69 §69.3` (ProjectionAccessor als DB-Owner)
- `FK-69 §69.4` (read_projection/write_projection)
- `FK-69 §69.10.1` (Reset-Purge)
- `FK-68 §68.3.4` (TelemetryService als Schreibgrenze)
- `formal.telemetry-analytics.invariants §reset-invalidates-read-models-and-facts`

---

## 1. Kontext

THEME-007 aus `stories/_priorisierungsempfehlung.md`. Befunde:

- `telemetry-and-events.A5`: ProjectionAccessor als eigenstaendiges Modul mit `write_projection`/`read_projection` fehlt — Projektionszugriff existiert verteilt in `verify_system/qa_read_models.py` und `closure/post_merge_finalization/records.py`. SoT-Drift.
- `telemetry-and-events.A6`: Reset-Purge fuer alle FK-69-Tabellen fehlt — bei Story-Reset bleiben veraltete Read-Models.
- `telemetry-and-events.B4`: FK-69-Read-Models sind verteilt (verify_system, closure); kein zentraler DB-Owner.
- `failure-corpus.A6`: fc_incidents-Persistenz soll laut FK-41 §41.3 via `Telemetry.write_projection` laufen — heute schreibt das fc-Repository direkt.

Diese Story fuehrt **ProjectionAccessor** ein als zentralen Schreib-Eintrag fuer FK-69-Read-Models und implementiert die Reset-Purge.

## 2. Scope

### 2.1 In Scope

#### 2.1.1 Neues Modul `src/agentkit/telemetry/projection_accessor.py`

```python
class ProjectionAccessor:
    """
    DB-Owner aller FK-69-Read-Models und fc_*-Tabellen.
    Zentrale Schreib- und Lese-Grenze fuer Projektionsdaten.
    """
    def __init__(self, repositories: ProjectionRepositories) -> None: ...

    def write_projection(
        self,
        projection_kind: ProjectionKind,
        record: ProjectionRecord,
    ) -> None:
        # validiert kind + record-Typ; persistiert via passendes Repository
        ...

    def read_projection(
        self,
        projection_kind: ProjectionKind,
        filter: ProjectionFilter,
    ) -> list[ProjectionRecord]:
        ...

    def purge_for_story(self, story_id: str) -> PurgeResult:
        """
        Reset-Purge: entfernt alle Projektionsdaten einer Story aus FK-69-Tabellen.
        Voraussetzung fuer formal.telemetry-analytics.invariants
        §reset-invalidates-read-models-and-facts.
        """
        ...
```

`ProjectionKind` ist StrEnum mit den existing + zukuenftigen FK-69-Tabellen:
- `QA_STAGE_RESULTS`
- `QA_FINDINGS`
- `STORY_METRICS`
- `PHASE_STATE_PROJECTION`
- `FC_INCIDENTS`
- `FC_PATTERNS` (falls existent)
- `FC_CHECK_PROPOSALS` (falls existent)
- `WORKFLOW_METRICS`

`ProjectionRecord` ist ein Union-Type bzw. Pydantic-Discriminated-Union ueber die konkreten Record-Klassen (`QAStageResultRecord`, `QAFindingRecord`, `StoryMetricsRecord`, `WorkflowMetricRecord`, `Incident`).

`ProjectionRepositories` ist Dataclass mit den konkreten Repos pro Tabelle.

#### 2.1.2 Migration der bestehenden Schreibstellen

Verteilte Schreiber werden auf den Accessor umgestellt:

- `src/agentkit/verify_system/qa_read_models.py:build_qa_stage_result` -> ruft `ProjectionAccessor.write_projection(QA_STAGE_RESULTS, record)`
- `src/agentkit/verify_system/qa_read_models.py:build_qa_findings` -> ruft `ProjectionAccessor.write_projection(QA_FINDINGS, record)`
- `src/agentkit/closure/...` Schreibstellen fuer `StoryMetricsRecord` -> Accessor
- AG3-028 (FailureCorpus): wenn dort fc_incident-Repository direkt schreibt, hier umstellen auf `ProjectionAccessor.write_projection(FC_INCIDENTS, incident)`. **Hinweis**: AG3-028 ist Voraussetzung fuer THEME-005; falls AG3-028 bei Erreichen dieser Story bereits gemerged ist, wird die Schreibstelle hier umgelenkt; sonst wartet die Umstellung auf der entsprechenden Folge-Story. Diese Story enthaelt die Accessor-Methoden; den fc_incidents-Schreib-Pfad nutzt die Folge-Story.

#### 2.1.3 Reset-Purge (FK-69 §69.10.1)

`ProjectionAccessor.purge_for_story(story_id)`:

- Loescht alle Eintraege mit dem story_id-Filter aus:
  - `qa_stage_results`
  - `qa_findings`
  - `story_metrics`
  - `phase_state_projection`
  - `workflow_metrics`
- NICHT geloescht werden:
  - `fc_incidents`/`fc_patterns`/`fc_check_proposals` (Begruendung: Failure-Corpus-Faelle sollen ueber Story-Reset hinaus erhalten bleiben fuer Patterns). Klarstellung im Docstring.
- Liefert `PurgeResult` mit `purged_rows: dict[ProjectionKind, int]` und `errors: list[str]`.

Aufgerufen wird `purge_for_story` aus dem `StoryResetService` (out of scope dieser Story; in der Erst-Welle reicht der Accessor-Endpoint).

#### 2.1.4 ProjectionAccessor in Composition-Root

`ProjectionAccessor` wird im App-Bootstrap (`agentkit.bootstrap`-Modul oder Control-Plane-Init) instanziiert mit allen konkreten Repositories.

#### 2.1.5 Tests

- Unit-Tests fuer `write_projection`: jedes ProjectionKind landet im richtigen Repository
- Unit-Tests fuer `read_projection`: Filter werden korrekt durchgereicht
- Unit-Tests fuer `purge_for_story`: alle relevanten Tabellen werden geleert; fc_*-Tabellen bleiben
- Unit-Tests fuer ProjectionRecord-Discriminated-Union (validation: falscher Record-Typ fuer Kind -> Exception)
- Integration-Test: verify-system schreibt ueber Accessor; Read-Roundtrip via Accessor
- Contract-Test `tests/contract/telemetry/test_projection_accessor.py`: ProjectionKind-Werte enthalten alle FK-69-Tabellen

### 2.2 Out of Scope

- Harness-Hooks (`telemetry-and-events.A1`) — AG3-036
- DivergenceHook (`A2`) — AG3-036
- NormalizedEvent fuer Risk-Window (`A3`) — AG3-037
- JSONL-Audit-Bundle-Export (`A4`) — AG3-036
- TelemetryContract (`B1`) — AG3-037
- Preflight-Telemetrie-Stream (`B2`) — AG3-037
- Workflow-Metriken-Felder (`B3`) — AG3-036 oder Folge-Story
- SSE-Topic-Mapping (`B5`) — Folge-Story (kleinere Korrektur)
- TelemetryService-Schreibgrenze (`C1`) — Folge-Story; diese Story arbeitet stattdessen mit ProjectionAccessor als Schreibgrenze fuer Projektionen (TelemetryService bleibt fuer Events zustaendig)
- compute_pipeline_metrics-qa_rounds-Bug (`C2`) — Folge-Story
- StoryResetService selbst — bewusst nicht in der Erst-Welle (Priorisierungsempfehlung §5)

## 3. Betroffene Dateien

| Datei | Aenderungsart | Beschreibung |
|---|---|---|
| `src/agentkit/telemetry/projection_accessor.py` | Neu | `ProjectionAccessor`, `ProjectionKind`, `ProjectionRecord`-Union, `ProjectionFilter`, `PurgeResult` |
| `src/agentkit/telemetry/projection_records.py` | Neu (Sammeldatei) | Re-Export der Record-Klassen aus den BCs (QAStageResult, StoryMetrics etc.) als Discriminated-Union |
| `src/agentkit/verify_system/qa_read_models.py` | Modifiziert | Schreibstellen nutzen ProjectionAccessor |
| `src/agentkit/closure/post_merge_finalization/records.py` (oder Aufrufer) | Modifiziert | StoryMetrics ueber Accessor |
| `src/agentkit/state_backend/store/projection_repositories.py` | Neu | `ProjectionRepositories`-Dataclass mit allen Repos |
| `tests/unit/telemetry/test_projection_accessor.py` | Neu | Accessor-Tests |
| `tests/unit/telemetry/test_purge_for_story.py` | Neu | Purge-Tests |
| `tests/integration/telemetry/test_projection_roundtrip.py` | Neu | Integration |
| `tests/contract/telemetry/test_projection_accessor.py` | Neu | Vertrags-Pinning |

## 4. Akzeptanzkriterien

1. **Klasse `ProjectionAccessor` existiert** in `src/agentkit/telemetry/projection_accessor.py` mit drei Methoden `write_projection`, `read_projection`, `purge_for_story`.
2. **`ProjectionKind`-StrEnum** enthaelt die acht Werte aus 2.1.1.
3. **`write_projection` validiert Record-Typ vs. Kind**: falscher Record-Typ fuer ein Kind -> `ProjectionRecordTypeMismatchError` (in `telemetry/errors.py`).
4. **Migration**: `verify_system/qa_read_models.py` und Closure-Schreibstellen rufen jetzt `ProjectionAccessor.write_projection`, nicht direkt das Repository.
5. **`purge_for_story`** loescht qa_stage_results, qa_findings, story_metrics, phase_state_projection, workflow_metrics fuer die angegebene story_id. fc_*-Tabellen werden NICHT geloescht. `PurgeResult.purged_rows` enthaelt Zaehlung pro Tabelle.
6. **Read-Roundtrip funktioniert**: write -> read liefert den geschriebenen Record (Integration-Test mit echtem SQLite).
7. **Architecture-Conformance**: `ProjectionAccessor` ist im `agentkit.telemetry`-Paket; importiert konkrete Repositories nur ueber `ProjectionRepositories`-Dataclass (Dependency-Injection); kein direkter `state_backend.store`-Fassaden-Import.
8. **Pflichtbefehle gruen**: pytest unit + integration + contract; mypy --strict; ruff clean; Coverage haelt 85%.

## 5. Definition of Done

- AK 1-8 erfuellt.
- `.venv\Scripts\python -m pytest tests/unit/telemetry tests/integration/telemetry tests/contract/telemetry -q` gruen.
- `mypy --strict` gruen, `ruff check src tests` gruen.

## 6. Offene Drifts die diese Story schliesst

- **AG3-026 DRIFT-AG3-035**: `verify_system/system.py` liest `StoryContext` direkt via
  `state_backend.store.load_story_context` statt ueber ArtifactManager + Top-Surfaces (BC-Topologie-Bruch).
  Diese Story muss den `_execute_layer`-Aufruf in `system.py` auf
  `ProjectionAccessor.read_projection` umstellen, sobald der Accessor
  `STORY_CONTEXT` als ProjectionKind unterstuetzt — oder via uebergebener
  StoryContext-Injection-Loesung. Bis dahin bleibt der DRIFT-Kommentar im Code
  (markiert mit `# DRIFT-AG3-035`).
- Aenderungen committed auf `main`.

## 6. Konzept-Referenzen (autoritativ)

- **FK-69 §69.3** — ProjectionAccessor als DB-Owner
- **FK-69 §69.4** — read/write_projection
- **FK-69 §69.10.1** — Reset-Purge
- **FK-68 §68.3.4** — TelemetryService als Schreibgrenze (orthogonal: TelemetryService fuer Events, ProjectionAccessor fuer Projektionen)
- **`formal.telemetry-analytics.invariants §reset-invalidates-read-models-and-facts`**

## 7. Guardrail-Referenzen

- **FIX THE MODEL, NOT THE SYMPTOM**: ein DB-Owner pro Read-Model-Familie statt verteilter Schreibstellen.
- **ZERO DEBT**: Migration der bestehenden Schreiber komplett; keine Reststellen, die direkt am Accessor vorbei schreiben.
- **FAIL CLOSED**: falscher Record-Typ -> Exception.
- **SINGLE SOURCE OF TRUTH**: ProjectionAccessor ist die einzige Schreib-API fuer FK-69-Read-Models.

## 8. Hinweise fuer den Sub-Agent

- `ProjectionRecord` als Discriminated-Union: pruefe Pydantic-v2-Pattern `Annotated[Union[...], Field(discriminator="kind")]`.
- `purge_for_story` ist transactional pro Tabelle (best-effort), Fehler werden in `errors[]` propagiert. Wenn alle leer: result.errors leer.
- AK2 NICHT veraendern.
