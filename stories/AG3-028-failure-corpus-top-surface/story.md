# AG3-028: FailureCorpus BC — Top-Komponente + IncidentTriage + record_incident-Empfaenger

<!-- AG3-028 deep-review (Schnitt-Vorbehalt): ChatGPT identifiziert die Persistenz als Hauptkonflikt. FK-41 + FK-69 normieren den Schreibpfad fuer fc_incidents ausdruecklich als FailureCorpus -> Telemetry.write_projection -> fc_incidents (Schema-Owner failure-corpus, DB-Owner telemetry-and-events.ProjectionAccessor). Der direkte Repository-Schreibpfad waere eine zweite operative Wahrheit. Entweder: (a) AG3-028 erhaelt Abhaengigkeit zu AG3-035/040 und nutzt Telemetry.write_projection, oder (b) AG3-028 bleibt Top-Surface mit Protocol/Fake und verschiebt produktive Persistenz in eine Folge-Story. Aktuelle Story-Variante: Option (b). Orchestrator entscheidet. -->

**Typ:** Implementation
**Groesse:** M
**Abhaengigkeiten:** AG3-021 (`FailureCategory`, `PromotionStatus`, `Severity`), AG3-022 (`ArtifactClass`-Bezug)
**Quell-Konzepte (autoritativ, in dieser Reihenfolge):**
- `concept/_meta/bc-cut-decisions.md §BC 13 failure-corpus`
- `FK-41 §41.1` (FailureCorpus-Top-Komponente, sechs Methoden)
- `FK-41 §41.3.1` (fc_incidents-Tabelle)
- `FK-41 §41.4` (IncidentTriage)
- `DK-07` (Failure-Corpus-Domaene)

---

## 1. Kontext

THEME-005 aus `stories/_priorisierungsempfehlung.md`. Befunde aus `failure-corpus`-GAP-Analyse:

- `failure-corpus.A1`: Top-Komponente `FailureCorpus` mit sechs Methoden (`record_incident`, `suggest_patterns`, `confirm_pattern`, `derive_check`, `approve_check`, `report_effectiveness`) — komplett nicht implementiert.
- `failure-corpus.A2`: Value-Types (`IncidentId`, `PatternId`, `CheckId`), `FailureCategory`-StrEnum (12 Werte — AG3-021 hat sie geliefert), `PromotionStatus`-StrEnum (AG3-021), `IncidentCandidate`-Pydantic-Modell.
- `failure-corpus.A3`: Sub-Komponente `IncidentTriage` mit `Incident`, `IncidentNormalizer`, `IngressCriteria`, `IncidentRepository`, `IncidentSeverity`.
- `failure-corpus.A6/A10`: `fc_incidents`-Tabelle und `record_incident`-Schnittstelle als Empfaenger fuer governance/verify/closure.

Diese Story liefert die **Top-Surface** und die **IncidentTriage-Sub** mit Persistenz — Promotion (PatternPromotion-Sub) und Check-Factory (CheckFactory-Sub) sind Folge-Stories nach dieser Welle (nicht erst-wellen-pflichtig, weil sie weiterfuehrende Logik mit LlmEvaluator/Story-Erzeugung sind, die fuer dieEmpfaenger-Funktion nicht benoetigt wird).

## 2. Scope

### 2.1 In Scope

#### 2.1.1 Paket `src/agentkit/failure_corpus/`

Bestehender leerer `__init__.py`-Stub wird aufgebaut. Neue Modul-Struktur:

- `__init__.py` — Re-Export
- `top.py` — `FailureCorpus`-Top-Komponente
- `types.py` — `IncidentId`, `PatternId`, `CheckId` (NewType), `IncidentSeverity` (StrEnum: `LOW`, `MEDIUM`, `HIGH`, `CRITICAL` — gemaess FK-41)
- `incident.py` — `IncidentCandidate`, `Incident` Pydantic-Modelle
- `incident_triage.py` — `IncidentTriage`, `IncidentNormalizer`, `IngressCriteria`
- `repository.py` — `IncidentRepository`-Protocol
- `errors.py` — typisierte Exceptions

#### 2.1.2 `FailureCorpus`-Top-Komponente (FK-41 §41.1)

```python
class FailureCorpus:
    def __init__(
        self,
        incident_triage: IncidentTriage,
        # die weiteren Subs sind in dieser Story Stubs:
        pattern_promotion: PatternPromotion | None = None,
        check_factory: CheckFactory | None = None,
    ) -> None: ...

    def record_incident(self, candidate: IncidentCandidate) -> IncidentId:
        # delegiert an IncidentTriage; persistiert via TelemetryProjectionWriter
        ...

    def suggest_patterns(self) -> list[PatternCandidate]:
        # Stub: leere Liste; Folge-Story
        raise NotImplementedError("PatternPromotion not in this story")

    def confirm_pattern(self, pattern_id: PatternId, decision: PatternDecision) -> FailurePattern:
        raise NotImplementedError("PatternPromotion not in this story")

    def derive_check(self, pattern_id: PatternId) -> CheckProposal:
        raise NotImplementedError("CheckFactory not in this story")

    def approve_check(self, check_id: CheckId, decision: CheckApprovalDecision) -> CheckProposal:
        raise NotImplementedError("CheckFactory not in this story")

    def report_effectiveness(self, window_days: int = 90) -> EffectivenessReport:
        raise NotImplementedError("Effectiveness tracking not in this story")
```

<!-- AG3-028 deep-review: Signaturen an BC-Cut + FK-41 angeglichen.
- confirm_pattern: braucht `decision: PatternDecision` (accepted/rejected)
- approve_check: braucht `decision: CheckApprovalDecision` (approved/rejected)
- report_effectiveness: `window_days=90` statt check_id (Aggregat-Report)
- suggest_patterns -> PatternCandidate (nicht FailurePattern), derive_check -> CheckProposal (Lifecycle-Trennung Kandidat/bestaetigt) -->

Zugehoerige Datenmodelle (Pydantic-v2, frozen, extra forbid):
- `PatternDecision`: StrEnum `ACCEPTED`, `REJECTED`
- `CheckApprovalDecision`: StrEnum `APPROVED`, `REJECTED`
- `PatternCandidate`: Vorschlag aus Clustering (FK-41 Pattern-Lifecycle)
- `FailurePattern`: bestaetigter Pattern (Lifecycle-Stufe `accepted`)
- `CheckProposal`: generierter Check-Vorschlag
- `EffectivenessReport`: Aggregat-Bericht ueber Window

Begruendung fuer NotImplementedError: Top-Surface ist vollstaendig vertraglich (alle sechs Methoden mit Signaturen vorhanden) — Aufrufer-BCs sehen den Vertrag und koennen ihre Code-Pfade vorbereiten; aber inhaltliche Logik fuer Promotion/CheckFactory braucht LlmEvaluator (THEME-009) und Story-Erzeugung (Cross-BC), beides spaeter.

`record_incident` ist **vollstaendig funktional**, weil das der Empfaenger-Vertrag ist, den andere BCs brauchen.

#### 2.1.3 `IncidentCandidate` und `Incident` (FK-41 §41.4)

`IncidentCandidate` ist Pydantic-v2-Modell (Input):
- `category: FailureCategory`
- `severity: IncidentSeverity`
- `source_bc: str` (governance-and-guards / verify-system / story-closure / implementation-phase)
- `story_id: str`
- `run_id: str`
- `summary: str`
- `evidence: dict[str, Any]` (frei strukturiert; spaetere Verfeinerung in Folge-Stories)
- `observed_at: datetime`

`Incident` ist Pydantic-v2-Modell (Persistenz, frozen, extra forbid):
- alle Felder von `IncidentCandidate`
- plus `incident_id: IncidentId`
- plus `normalized_at: datetime`
- plus `promotion_status: PromotionStatus` (Default: `OBSERVED`)

#### 2.1.4 `IncidentTriage`-Sub (FK-41 §41.4)

```python
class IncidentTriage:
    def __init__(self, normalizer: IncidentNormalizer, criteria: IngressCriteria, repository: IncidentRepository) -> None: ...

    def ingest(self, candidate: IncidentCandidate) -> IncidentId:
        # 1. Pruefe IngressCriteria — verwerfe wenn nicht relevant
        # 2. Normalisiere via IncidentNormalizer
        # 3. Erzeuge Incident mit normalized_at und promotion_status=OBSERVED
        # 4. Persistiere via Repository
        # 5. Gib IncidentId zurueck
        ...
```

`IncidentNormalizer` (Default-Implementierung):
- ergaenzt fehlende `category` (aber `category` ist Pflicht in `IncidentCandidate` — der Normalizer schaerft also nicht die Kategorie, sondern macht Whitespace-/Encoding-/Length-Normalisierung von `summary`)
- setzt `normalized_at = now()`

`IngressCriteria` (Default-Implementierung):
- Mindest-Severity-Filter (z.B. `MEDIUM` aufwaerts; konfigurierbar)
- Doppelung-Filter (gleiche `source_bc + story_id + summary` innerhalb 60s -> verworfen)

#### 2.1.5 Persistenz — fc_incidents-Tabelle (FK-41 §41.3.1, FK-69)

<!-- AG3-028 deep-review: Persistenz auf Telemetry-Projection-Vertrag umgestellt. FK-41 + FK-69 normieren den Schreibpfad eindeutig: FailureCorpus -> Telemetry.write_projection -> fc_incidents. Direkter state_backend.store-Schreibpfad waere zweite operative Wahrheit (Konzept-Bruch). -->

`FailureCorpus.record_incident` schreibt fachlich **ausschliesslich** ueber eine injizierte `IncidentProjectionWriter`-/`TelemetryProjectionWriter`-Schnittstelle, deren produktive Implementierung `Telemetry.write_projection(table="fc_incidents", row=...)` ist (FK-41 §41.3 + FK-69: Schema-Owner `failure-corpus`, Writer `failure_corpus.FailureCorpus`, DB-Owner `telemetry-and-events.ProjectionAccessor`).

**Story-Scope-Variante (Default, Top-Surface)**:
- Diese Story liefert das `IncidentProjectionWriter`-Protocol + eine InMemory-/Fake-Implementierung fuer Unit/Integration-Tests.
- KEINE direkte state_backend-Tabellenerzeugung in dieser Story.
- KEINE Postgres/SQLite-Schema-Aenderung.
- KEIN SCHEMA_VERSION-Bump.

**Alternative Variante (wenn vorgezogen)**:
- AG3-028 erhaelt harte Abhaengigkeit zu AG3-035 (`ProjectionAccessor`) und schreibt produktiv ueber `Telemetry.write_projection`.
- `fc_incidents`-DDL gehoert in die ProjectionAccessor-Story, nicht hierher.

Tabellen-Schema fuer `fc_incidents` (zur Doku — Erzeugung in der ProjectionAccessor-Folge-Story):
- `incident_id` (PK, UUID)
- `category` (CHECK: 12 erlaubte Werte aus `FailureCategory`)
- `severity` (CHECK: 4 erlaubte Werte)
- `source_bc`
- `story_id`
- `run_id`
- `summary`
- `evidence_json` (JSON)
- `observed_at`, `normalized_at`
- `promotion_status` (CHECK: exakt die Werte aus `PromotionStatus` gemaess FK-41-Glossar — NICHT auf 5 reduziert; Default fuer neue Incidents: `observed`). <!-- AG3-028 deep-review: PromotionStatus hat deutlich mehr als 5 Werte (observed/triaged/clustered/promoted/closed_one_off/archived/candidate/accepted/check_proposed/check_active/monitoring/draft/approved/active/tuned/retired/rejected). -->

#### 2.1.6 `record_incident`-Empfaenger fuer andere BCs

Die Top-Surface ist transport-agnostisch (kein eigener CLI/HTTP-Endpunkt in dieser Story). Aufrufer-BCs (`governance-and-guards`, `verify-system`, `story-closure`) erhalten `FailureCorpus` ueber Dependency-Injection und rufen `record_incident(candidate)` auf.

#### 2.1.7 Tests

- Unit-Tests fuer `FailureCorpus.record_incident` (happy path + IngressCriteria verwirft)
- Unit-Tests fuer `IncidentTriage.ingest`
- Unit-Tests fuer `IncidentNormalizer` und `IngressCriteria`
- Unit-Tests fuer `IncidentRepository` (parametrisiert SQLite + Postgres)
- Tests fuer NotImplementedError der vier verbleibenden Top-Methoden (Vertrag-Pinning, dass sie existieren und korrekt fehlen)
- Contract-Test `tests/contract/failure_corpus/test_top_surface.py`: alle sechs Methoden mit Signaturen
- Integration-Test: ein BC ruft `record_incident`; Incident ist in fc_incidents lesbar

### 2.2 Out of Scope

- `PatternPromotion`-Sub (`failure-corpus.A4`) — Folge-Story nach THEME-009 (LlmEvaluator notwendig fuer Cluster-Schaerfung)
- `CheckFactory`-Sub (`failure-corpus.A5`) — Folge-Story (10 Klassen, Story-Erzeugung, Effectiveness-Tracking)
- Auto-Deaktivierung (`failure-corpus.A7`) — Folge-Story
- LlmEvaluator-Integration (`failure-corpus.A8`) — Folge-Story
- GitHub-Adapter fuer Story-Erzeugung (`failure-corpus.A9`) — Folge-Story
- Reset-Purge fuer fc_*-Tabellen — gehoert zu THEME-007 (AG3-035)
- ProjectionAccessor-Umlenkung — gehoert zu THEME-007 (AG3-035)
- fc_patterns, fc_check_proposals Tabellen — Folge-Stories (kommen mit PatternPromotion/CheckFactory)
- Telemetrie-Events fuer Incident-Erzeugung — separate Folge nach THEME-007

## 3. Betroffene Dateien

| Datei | Aenderungsart | Beschreibung |
|---|---|---|
| `src/agentkit/failure_corpus/__init__.py` | Modifiziert (leer -> exportiert Top-Surface) | Re-Export |
| `src/agentkit/failure_corpus/top.py` | Neu | `FailureCorpus`-Top-Klasse |
| `src/agentkit/failure_corpus/types.py` | Neu | NewTypes, `IncidentSeverity` |
| `src/agentkit/failure_corpus/incident.py` | Neu | `IncidentCandidate`, `Incident` Pydantic-Modelle |
| `src/agentkit/failure_corpus/incident_triage.py` | Neu | `IncidentTriage`, `IncidentNormalizer`, `IngressCriteria` |
| `src/agentkit/failure_corpus/repository.py` | Neu | `IncidentRepository`-Protocol |
| `src/agentkit/failure_corpus/errors.py` | Neu | typisierte Exceptions |
| `src/agentkit/state_backend/store/fc_incident_repository.py` | Neu | SQLite/Postgres-Implementierung |
| `src/agentkit/state_backend/postgres_schema.sql` | Modifiziert | `fc_incidents`-Tabelle |
| `src/agentkit/state_backend/sqlite_store.py` | Modifiziert | analog SQLite |
| `src/agentkit/state_backend/config.py` | Modifiziert | SCHEMA_VERSION-Bump |
| `tests/unit/failure_corpus/test_top.py` | Neu | Top-Tests |
| `tests/unit/failure_corpus/test_incident.py` | Neu | Modell-Tests |
| `tests/unit/failure_corpus/test_incident_triage.py` | Neu | Triage-Tests |
| `tests/unit/state_backend/store/test_fc_incident_repository.py` | Neu | parametrisiert SQLite + Postgres |
| `tests/contract/failure_corpus/test_top_surface.py` | Neu | Vertrags-Pinning |
| `tests/integration/failure_corpus/test_record_incident_roundtrip.py` | Neu | End-to-End Empfaenger-Pfad |

## 4. Akzeptanzkriterien

1. **Paket `src/agentkit/failure_corpus/` ist nicht mehr leer** und exportiert `FailureCorpus`, `IncidentCandidate`, `Incident`, `IncidentId`, `PatternId`, `CheckId`, `IncidentSeverity`, `IncidentTriage`, `IngressCriteria`, `IncidentNormalizer`.
2. **Top-Klasse `FailureCorpus` hat sechs Methoden**: `record_incident`, `suggest_patterns`, `confirm_pattern`, `derive_check`, `approve_check`, `report_effectiveness`. Nur `record_incident` ist voll funktional; die anderen werfen `NotImplementedError` mit aussagekraeftiger Begruendung.
3. **`record_incident(candidate)` ist fail-closed**: validiert IngressCriteria, normalisiert, persistiert (via `IncidentProjectionWriter`-Protocol, FK-41/FK-69-konform); gibt `IncidentId` zurueck oder wirft `IncidentRejectedError` (in `errors.py`) bei IngressCriteria-Reject. `IncidentRejectedError` traegt strukturierte `reason_codes` (StrEnum: `BELOW_MIN_SEVERITY`, `DUPLICATE_WINDOW`, `NOT_BLOCKING`). <!-- AG3-028 deep-review: reason_codes strukturiert statt freier String. -->
4. **`Incident`-Modell ist persistiert** in `fc_incidents` mit allen Spalten aus 2.1.5. UNIQUE auf `incident_id`. CHECK-Constraints auf `category`, `severity`, `promotion_status`.
5. **`IncidentTriage` durchlaeuft drei Schritte**: IngressCriteria -> Normalizer -> Repository.write. Per Test verifizierbar.
6. **Architecture-Conformance**: `agentkit.failure_corpus` importiert nur `agentkit.core_types` und `agentkit.artifacts` (optional fuer Future-ArtifactRefs); nicht aus `state_backend.store`-Fassaden ausserhalb des Repository-Moduls.
7. **Persistenz parametrisiert**: Repository-Tests laufen auf SQLite und Postgres.
8. **Pflichtbefehle gruen**: pytest unit + integration + contract; mypy --strict; ruff clean; Coverage haelt 85%.

## 5. Definition of Done

- AK 1-8 erfuellt.
- `.venv\Scripts\python -m pytest tests/unit/failure_corpus tests/integration/failure_corpus tests/contract/failure_corpus -q` gruen.
- `mypy --strict` gruen, `ruff check src tests` gruen.
- SQLite + Postgres migriert.
- Aenderungen committed auf `main`.

## 6. Konzept-Referenzen (autoritativ)

- **`concept/_meta/bc-cut-decisions.md §BC 13`** — Top-Surface, Subs
- **FK-41 §41.1** — sechs Top-Methoden
- **FK-41 §41.3.1** — fc_incidents
- **FK-41 §41.4** — IncidentTriage, IncidentNormalizer, IngressCriteria
- **FK-41 §41.4.1** — FailureCategory-Werte (AG3-021)
- **DK-07** — Failure-Corpus-Domaene

## 7. Guardrail-Referenzen

- **FIX THE MODEL, NOT THE SYMPTOM**: BC mit echtem Empfaenger-Vertrag, nicht nur Stub-Verzeichnis.
- **ZERO DEBT**: nicht-implementierte Methoden werfen explizit NotImplementedError mit Verweis auf Folge-Stories; nichts schweigt.
- **FAIL CLOSED**: IngressCriteria reject ist Exception, nicht silently ignored.
- **SINGLE SOURCE OF TRUTH**: fc_incidents lebt einmal pro Storage-Backend; spaeter wird die Schreibstelle auf ProjectionAccessor migriert (THEME-007).

## 8. Hinweise fuer den Sub-Agent

- `NotImplementedError` ist hier explizit erwuenscht — nicht zu verwechseln mit "halbfertig". Die Methoden sind Vertrags-Slots fuer kuenftige Stories. Begruendung in Docstring + Verweis auf Folge-Story.
- AK2 NICHT veraendern.
