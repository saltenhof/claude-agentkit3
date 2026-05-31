# AG3-028: FailureCorpus BC — Top-Komponente + IncidentTriage + record_incident-Empfaenger

<!-- AG3-028 deep-review (User-Entscheidung 2026-05-19): Variante (a) Vorgezogene Vollumsetzung gewaehlt. FailureCorpus.record_incident schreibt produktiv ueber Telemetry.write_projection (FK-41 + FK-69-konform). Daraus ergeben sich harte Abhaengigkeiten zu AG3-035 (ProjectionAccessor) und AG3-040 (Postgres-Store-Completion); die Story wird auf L hochgestuft. Variante (b) "Top-Surface mit Protocol/Fake" ist verworfen. -->

**Typ:** Implementation
**Groesse:** L
**Abhaengigkeiten:** AG3-021 (`FailureCategory`, `PromotionStatus`, `Severity`), AG3-022 (`ArtifactClass`-Bezug), **AG3-035 (`ProjectionAccessor`)**, **AG3-040 (Postgres-Store-Completion)**
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

#### 2.1.5 Persistenz — fc_incidents-Tabelle via Telemetry.write_projection (FK-41 §41.3.1, FK-69)

<!-- AG3-028 deep-review (User-Entscheidung 2026-05-19): Variante (a) Vollumsetzung. Produktiver Schreibpfad ueber Telemetry.write_projection. Keine InMemory-Fake-Variante mehr; AG3-035 (ProjectionAccessor) und AG3-040 (Postgres-Store-Completion) sind Vorbedingung. -->

`FailureCorpus.record_incident` schreibt fachlich **ausschliesslich** ueber die in
AG3-035 etablierte `Telemetry.write_projection(table, row)`-API
(FK-41 §41.3 + FK-69: Schema-Owner `failure-corpus`, Writer
`failure_corpus.FailureCorpus`, DB-Owner
`telemetry-and-events.ProjectionAccessor`). Direkter `state_backend.store`-
Schreibpfad waere zweite operative Wahrheit und ist verboten.

`fc_incidents`-Tabelle wird in dieser Story produktiv angelegt (Schema-Owner
`failure-corpus` -> DDL liegt in `state_backend/postgres_schema.sql` + SQLite-
Bootstrap; Side-by-Side via SCHEMA_VERSION-Bump nach FK-18 §18.9a).

Tabellen-Schema fuer `fc_incidents`:
- `incident_id` (PK, UUID)
- `category` (CHECK: 12 erlaubte Werte aus `FailureCategory`)
- `severity` (CHECK: 4 erlaubte Werte aus `Severity`)
- `source_bc` (VARCHAR, NOT NULL)
- `story_id` (VARCHAR, NOT NULL)
- `run_id` (VARCHAR, NULL)
- `summary` (TEXT, NOT NULL)
- `evidence_json` (JSON/JSONB, NULL)
- `observed_at` (TIMESTAMPTZ, NOT NULL)
- `normalized_at` (TIMESTAMPTZ, NOT NULL)
- `promotion_status` (CHECK: exakt die Werte aus `PromotionStatus` gemaess
  FK-41-Glossar — NICHT auf 5 reduziert; Default fuer neue Incidents: `observed`).
  Wertebereich: `observed`, `triaged`, `clustered`, `promoted`, `closed_one_off`,
  `archived`, `candidate`, `accepted`, `check_proposed`, `check_active`,
  `monitoring`, `draft`, `approved`, `active`, `tuned`, `retired`, `rejected`.
- Index: `idx_fc_incidents_story_run ON fc_incidents(story_id, run_id)` (FK-41-konform).
- Index: `idx_fc_incidents_promotion_status ON fc_incidents(promotion_status)`.

**Telemetry.write_projection-Vertrag** (wird in AG3-035 etabliert; hier nur
konsumiert):
- `Telemetry.write_projection(table: str, row: dict[str, object]) -> None`
- Schreibpfad: ProjectionAccessor -> Postgres/SQLite-Bootstrap-getriebene Tabelle
- Idempotenz/Konflikt-Verhalten: UPSERT auf Primary-Key (FK-69-Default)
- Bei Fail: `ProjectionWriteError` (in `telemetry`-BC definiert)

`FailureCorpus`-Komposition (Composition-Root in `bootstrap/composition_root.py`):
```python
def build_failure_corpus(telemetry: Telemetry) -> FailureCorpus:
    return FailureCorpus(
        triage=IncidentTriage(...),
        projection_writer=telemetry,  # injects write_projection-Vertrag
    )
```

#### 2.1.5b fc_incidents Reset-Purge (FK-69 §69.9 / FK-41 §41.3)

AG3-035 hat `ProjectionAccessor.purge_run(project_key, story_id, run_id)` mit den
damals existierenden FK-69-Tabellen umgesetzt und den fc_*-Purge ausdruecklich auf
**diese Story** vertagt (`# DRIFT-AG3-028`-Marker), weil hier `fc_incidents`
entsteht. Diese Story loest den Marker auf:

- `ProjectionAccessor.purge_run` wird um `ProjectionKind.FC_INCIDENTS` erweitert:
  beim vollstaendigen Reset eines `run_id` werden **alle `fc_incidents`-Zeilen
  dieses `run_id` aktiv entfernt** (FK-41 §41.3: „Vollstaendiger Story-Reset
  loescht alle `fc_incidents`-Zeilen des betroffenen `run_id`"; FK-69 §69.9).
- Dafuer bekommt das `fc_incidents`-Repository (Adapter in `state_backend/store`)
  eine `purge_run(project_key, story_id, run_id) -> int`-Methode analog den
  uebrigen FK-69-Repos; sie wird via `ProjectionRepositories` injiziert.
- **KEINE** „Failure-Corpus ueberlebt Reset"-Regel: die Incidents des
  zurueckgesetzten Runs verschwinden. Der `# DRIFT-AG3-028`-Marker in
  `telemetry/projection_accessor.py:purge_run` wird entfernt.
- `fc_patterns.incident_count`-Recompute und die Unberuehrtheit von
  `fc_check_proposals` (FK-41 §41.3) gehoeren zu den Folge-Stories, die diese
  Tabellen anlegen (PatternPromotion/CheckFactory) — solange es keine
  `fc_patterns`/`fc_check_proposals`-Tabellen gibt, gibt es dort nichts zu tun.

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
- fc_patterns, fc_check_proposals Tabellen — Folge-Stories (kommen mit PatternPromotion/CheckFactory); deren Reset-Recompute (`fc_patterns.incident_count`) / Unberuehrtheit (`fc_check_proposals`) wird mit diesen Tabellen in den jeweiligen Folge-Stories umgesetzt (FK-41 §41.3, FK-69 §69.9)
- Telemetrie-Events fuer Incident-Erzeugung — separate Folge nach THEME-007

## 3. Betroffene Dateien

| Datei | Aenderungsart | Beschreibung |
|---|---|---|
| `src/agentkit/failure_corpus/__init__.py` | Modifiziert (leer -> exportiert Top-Surface) | Re-Export |
| `src/agentkit/failure_corpus/top.py` | Neu | `FailureCorpus`-Top-Klasse |
| `src/agentkit/failure_corpus/types.py` | Neu | NewTypes, `IncidentSeverity` |
| `src/agentkit/failure_corpus/incident.py` | Neu | `IncidentCandidate`, `Incident` Pydantic-Modelle |
| `src/agentkit/failure_corpus/incident_triage.py` | Neu | `IncidentTriage`, `IncidentNormalizer`, `IngressCriteria` |
| `src/agentkit/failure_corpus/errors.py` | Neu | typisierte Exceptions |
| `src/agentkit/state_backend/postgres_schema.sql` | Modifiziert | `fc_incidents`-Tabelle (DDL + Indizes) |
| `src/agentkit/state_backend/sqlite_store.py` | Modifiziert | analog SQLite |
| `src/agentkit/state_backend/config.py` | Modifiziert | SCHEMA_VERSION-Bump |
| `src/agentkit/bootstrap/composition_root.py` | Modifiziert | `build_failure_corpus(telemetry)` |
| `src/agentkit/state_backend/store/fc_incident_repository.py` | Neu | fc_incidents-Repo inkl. `purge_run` (FK-69 §69.9) |
| `src/agentkit/state_backend/store/projection_repositories.py` | Modifiziert | `fc_incidents`-Repo in `ProjectionRepositories` + Wiring |
| `src/agentkit/telemetry/projection_accessor.py` | Modifiziert | `purge_run` um `FC_INCIDENTS` erweitert; `# DRIFT-AG3-028`-Marker entfernt |

<!-- AG3-028 deep-review (Vollumsetzung 2026-05-19): keine
  failure_corpus/repository.py und keine fc_incident_repository.py mehr.
  Persistenz-Pfad geht ueber Telemetry.write_projection (AG3-035 liefert
  die API). Tests konsumieren die produktive Telemetry-Instanz. -->

| `tests/unit/failure_corpus/test_top.py` | Neu | Top-Tests |
| `tests/unit/failure_corpus/test_incident.py` | Neu | Modell-Tests |
| `tests/unit/failure_corpus/test_incident_triage.py` | Neu | Triage-Tests |
| `tests/unit/state_backend/store/test_fc_incidents_schema_bootstrap.py` | Neu | Bootstrap-Idempotenz fuer `fc_incidents` (analog `attempts`) |
| `tests/contract/failure_corpus/test_top_surface.py` | Neu | Vertrags-Pinning |
| `tests/integration/failure_corpus/test_record_incident_roundtrip.py` | Neu | End-to-End Empfaenger-Pfad |

## 4. Akzeptanzkriterien

1. **Paket `src/agentkit/failure_corpus/` ist nicht mehr leer** und exportiert `FailureCorpus`, `IncidentCandidate`, `Incident`, `IncidentId`, `PatternId`, `CheckId`, `IncidentSeverity`, `IncidentTriage`, `IngressCriteria`, `IncidentNormalizer`.
2. **Top-Klasse `FailureCorpus` hat sechs Methoden**: `record_incident`, `suggest_patterns`, `confirm_pattern`, `derive_check`, `approve_check`, `report_effectiveness`. Nur `record_incident` ist voll funktional; die anderen werfen `NotImplementedError` mit aussagekraeftiger Begruendung.
3. **`record_incident(candidate)` ist fail-closed**: validiert IngressCriteria, normalisiert, schreibt produktiv ueber `Telemetry.write_projection(table="fc_incidents", row=...)` (FK-41/FK-69-konform); gibt `IncidentId` zurueck oder wirft `IncidentRejectedError` (in `errors.py`) bei IngressCriteria-Reject. `IncidentRejectedError` traegt strukturierte `reason_codes` (StrEnum: `BELOW_MIN_SEVERITY`, `DUPLICATE_WINDOW`, `NOT_BLOCKING`).
4. **`fc_incidents`-Tabelle existiert** in SQLite + Postgres mit allen Spalten + Indizes aus §2.1.5. UNIQUE auf `incident_id`. CHECK-Constraints auf `category`, `severity`, `promotion_status`. SCHEMA_VERSION-Bump ist verbindlich (FK-18 §18.9a, alte DB unangetastet).
5. **`IncidentTriage` durchlaeuft drei Schritte**: IngressCriteria -> Normalizer -> `Telemetry.write_projection`. Per Test verifizierbar.
6. **Architecture-Conformance**: `agentkit.failure_corpus` importiert nur `agentkit.core_types`, `agentkit.artifacts` (optional) und `agentkit.telemetry` (fuer den `Telemetry.write_projection`-Vertrag); **nicht** aus `agentkit.state_backend.store` direkt.
7. **End-to-End-Persistenz**: ein Integration-Test ruft `record_incident` und liest den persistierten Row aus `fc_incidents` auf beiden Backends (SQLite + Postgres).
8. **Pflichtbefehle gruen**: pytest unit + integration + contract; mypy --strict; ruff clean; Coverage haelt 85%.
9. **fc_incidents Reset-Purge (FK-69 §69.9 / FK-41 §41.3)**: `ProjectionAccessor.purge_run` entfernt beim Reset eines `run_id` auch alle `fc_incidents`-Zeilen dieses Runs; das `fc_incidents`-Repository hat `purge_run`; der `# DRIFT-AG3-028`-Marker in `telemetry/projection_accessor.py` ist entfernt. Ein Test legt echte `fc_incidents`-Zeilen an und beweist, dass nach `purge_run` keine Zeile des Runs verbleibt (und andere Runs unberuehrt bleiben).

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
