# AG3-028: FailureCorpus BC — Top-Komponente + IncidentTriage + record_incident-Empfaenger

> ## Codex-r2 Remediation 2026-06-01: incident_id GLOBAL eindeutig + IngressCriteria reines ODER (DK-07 §7.3.6)
>
> Die giftige Codex-Review r2 (Gesamturteil BLOCK) hat drei Fehler aufgedeckt;
> alle behoben (SCHEMA_VERSION 3.10.0 -> **3.11.0**, Side-by-Side FK-18 §18.9a):
>
> - **IngressCriteria ist ein reines ODER (DK-07 §7.3.6, autoritativ):** ADMIT
>   gdw. mindestens eines gilt — `severity >= MEDIUM` ODER `merge_blocked` ODER
>   `rework_minutes > 30` ODER Corpus-Neuheit. Severity ist **kein** harter
>   AND-Floor mehr (`LOW + merge_blocked` etc. werden jetzt korrekt aufgenommen).
>   REJECT bei keinem Kriterium = `NOT_SIGNIFICANT`; der tote/falsche
>   `BELOW_MIN_SEVERITY`-reason_code ist entfernt. Exakter Duplikat im Zeitfenster
>   wird separat mit `DUPLICATE_WINDOW` verworfen (Dedup; erreichbar, ZERO DEBT).
> - **incident_id ist GLOBAL eindeutig (User-Entscheidung):** PK von
>   `fc_incidents` = **`incident_id` allein** (kein composite `(project_key,
>   incident_id)` mehr). `fc_incident_counters` ist auf **`year` allein** gekeyt
>   (ein globaler Per-Jahr-Zaehler ueber alle Projekte). `project_key` bleibt
>   NOT-NULL-Spalte; read/purge_run filtern weiterhin zwingend nach `project_key`
>   (r1-Fix bleibt). Allokation race-sicher in EINEM atomaren Statement
>   (`INSERT ... ON CONFLICT(year) DO UPDATE SET next_seq = next_seq + 1
>   RETURNING next_seq - 1`; SQLite `BEGIN IMMEDIATE` + RETURNING). Der fruehere
>   `SELECT ... FOR UPDATE`-Bug (sperrt bei fehlender Zeile nichts -> zwei Txns
>   liefern `FC-YYYY-0001`) ist geschlossen; ein 16-Thread-Initial-Counter-Test
>   beweist es (Postgres-Concurrency als N1-WARNING, lokal nicht beweisbar).
> - **FC-YYYY-NNNN + evidence=list[str] FAIL-CLOSED erzwungen:** Pydantic-
>   Validator auf `Incident.incident_id` (Regex `^FC-\d{4}-\d{4,}$`) und auf
>   `evidence` (list[str], kein dict). DB-CHECK: Postgres `incident_id ~
>   '^FC-[0-9]{4}-[0-9]+$'` + `jsonb_typeof(evidence_json::jsonb)='array'`;
>   SQLite GLOB `FC-[0-9][0-9][0-9][0-9]-[0-9][0-9][0-9][0-9]*` +
>   `json_type(evidence_json)='array'`.
>
> Severity-Wertesprache bleibt englisch (`low|medium|high|critical`); Konzept
> (FK-41 §41.3.1/§41.4.1, bc-cut) ist bereits englisch + reindexed.

> ## Codex-r1 Remediation 2026-06-01: fc_incidents auf FK-41 §41.3.1/§41.4.1/§41.4.3 angeglichen
>
> Die giftige Codex-Review r1 (Gesamturteil BLOCK) hat ein **falsches
> fc_incidents-Schema** aufgedeckt (`source_bc`/`summary`/`evidence`-dict/
> `observed_at`/`normalized_at`/`FC-{uuid}`/kein `project_key`). Diese Story
> wurde auf den echten FK-41-Vertrag gezogen:
>
> - **fc_incidents (FK-41 §41.3.1):** `project_key` NOT NULL, `incident_id` im
>   Format **`FC-YYYY-NNNN`** (kein uuid), `run_id` NOT NULL, `category`,
>   `severity`, `phase`, `role` (CHECK `worker|qa|governance`), `model`,
>   `symptom`, `evidence_json` = **Liste von Strings**, `recorded_at`,
>   `incident_status`; optional `tags`/`impact`/`pattern_ref`. Alt-Felder
>   entfallen. SCHEMA_VERSION 3.9.0 -> **3.10.0** (Side-by-Side, FK-18 §18.9a).
> - **IncidentCandidate/Incident (FK-41 §41.4.1):** auf diese Felder umgestellt;
>   `IncidentCandidate` traegt zusaetzlich die Gate-Inputs `merge_blocked`/
>   `rework_minutes` (NICHT persistiert).
> - **IngressCriteria (DK-07 §7.3.6):** ~~Severity-Floor (AND) + ...~~ **durch
>   Codex-r2 ersetzt: reines ODER** (siehe r2-Banner oben). reason_codes:
>   `NOT_SIGNIFICANT`, `DUPLICATE_WINDOW` (das alte `BELOW_MIN_SEVERITY` ist
>   entfernt).
> - **project_key Pflicht:** read/purge_run filtern zwingend nach `project_key`
>   (FAIL-CLOSED). (Bleibt — auch nach r2.)
> - **incident_id-Allokation:** ~~gap-free pro `(project_key, Jahr)`~~ **durch
>   Codex-r2 ersetzt: global eindeutig, globaler Per-Jahr-Zaehler (PK = year),
>   PK von fc_incidents = incident_id allein** (siehe r2-Banner). Allokator
>   weiterhin in der DB-Schreibtransaktion; `ProjectionAccessor.record_fc_incident
>   (draft) -> IncidentId`.

<!-- AG3-028 deep-review (User-Entscheidung 2026-05-19): Variante (a) Vorgezogene Vollumsetzung gewaehlt. FailureCorpus.record_incident schreibt produktiv ueber Telemetry.write_projection (FK-41 + FK-69-konform). Daraus ergeben sich harte Abhaengigkeiten zu AG3-035 (ProjectionAccessor) und AG3-040 (Postgres-Store-Completion); die Story wird auf L hochgestuft. Variante (b) "Top-Surface mit Protocol/Fake" ist verworfen. -->

> ## KONFLIKT-1 — RESOLVED (User-Entscheidung 2026-06-01): drei entitäts-scoped Lifecycle-Enums, abgespeckt
>
> Der bisherige `PromotionStatus`-Sammel-Enum (ein Enum für drei Entitäten,
> FK-41-Glossar 17 Werte; AG3-021-Code nur 7) wird durch **drei
> entitäts-scoped Enums** ersetzt — und dabei auf die fachlich tragenden
> Zustände abgespeckt (Zwischen-/Spiegelzustände ohne Mehrwert gestrichen):
>
> | Enum | Werte | gestrichen ggü. altem Konzept |
> |---|---|---|
> | `IncidentStatus` | `observed`, `promoted`, `closed_one_off`, `archived` | `triaged` (= observed, Pflichtfelder erzwungen), `clustered` (aus `incident_refs`/`pattern_ref` ableitbar) |
> | `PatternStatus` | `candidate`, `accepted`, `rejected`, `retired` | `check_proposed`, `check_active` (Check-Spiegel, via `check_ref` ableitbar), `monitoring` (aktiv ⇒ wird erfasst) |
> | `CheckStatus` | `draft`, `approved`, `active`, `rejected`, `retired` | `tuned` (= neue Check-Revision, kein eigener Status) |
>
> **Konzept ist bereits nachgezogen** (FK-41 §41.3.1–3 + Glossar drei Terme
> `incident-status`/`pattern-status`/`check-status`; DK-07 §7.7; FK-61 §61.10.1
> KPI auf Join statt `check_active`; bc-cut-decisions §BC 13; bounded-contexts.yaml).
>
> **Code-Scope dieser Story (Weg 2, ZERO-DEBT): nur `IncidentStatus`
> materialisieren** — es ist der einzige Enum mit funktionalem Producer
> (`record_incident`/`fc_incidents.incident_status`). `PatternStatus`/
> `CheckStatus` landen mit ihren Producern (`PatternPromotion`/`CheckFactory`)
> in deren Folge-Stories; sie jetzt als toten Code anzulegen wäre ZERO-DEBT-Verstoß.
> Der alte 7-Werte-`PromotionStatus` (in `core_types/failure_corpus.py`) hat
> **keinen funktionalen Konsumenten** (nur Export + 2 Test-Dateien) und wird
> durch `IncidentStatus` ersetzt; die Tests (`test_failure_corpus.py`,
> `test_enum_wire_values.py`) ziehen mit.

> ## KONFLIKT-2 — RESOLVED (User-Entscheidung 2026-06-01): fc_incidents IN den Accessor verdrahten
>
> Geprüft an der Quelle (FK-41 §41.3, FK-69 §69.4/§69.9/§69.14 + AG3-035-Code):
> Der `ProjectionAccessor` ist die **einzige Schreibgrenze** für alle
> FK-69-Tabellen — FK-69 §69.9/§69.14 routen `fc_*` **explizit über
> `Telemetry.write_projection`**, und der Accessor-Docstring fordert „kein BC
> schreibt direkt in FK-69-Tabellen". Das in AG3-035 gesetzte fail-closed für
> `FC_INCIDENTS` (`ProjectionKindNotAccessorOwnedError`) war ein **Platzhalter**
> („fc-Repos gibt's noch nicht"; `_FC_OWNER = "AG3-028 …"`, `# DRIFT-AG3-028`).
>
> **Auflösung (die einzige konzepttreue):** AG3-028 verdrahtet `fc_incidents` IN
> den Accessor und hebt das fail-closed auf — NICHT „FailureCorpus schreibt über
> ein eigenes DB-Repo" (das verstieße gegen FK-69 §69.9 + den Accessor-Vertrag).
> Konkret:
> 1. `fc_incidents`-Repo-Adapter in `state_backend/store` (mit `write`, `read`,
>    `purge_run`), injiziert in `ProjectionRepositories`.
> 2. Im Accessor: `FC_INCIDENTS` von `_EXTERNALLY_OWNED_KINDS` →
>    `_ACCESSOR_OWNED_KINDS`; Record-Typ ins `_KIND_TO_RECORD_TYPE`-Mapping;
>    Branch in `write_projection`/`read_projection`/`purge_run`-Schleife;
>    `# DRIFT-AG3-028`-Marker entfernen.
> 3. `failure_corpus` persistiert **ausschließlich** über die injizierte
>    `Telemetry.write_projection`-API (AC#6: kein `state_backend.store`-Import in
>    `failure_corpus`). Das fc_incidents-DB-Repo lebt auf der **Accessor-Seite**,
>    nicht in `failure_corpus`.
> 4. `FC_PATTERNS`/`FC_CHECK_PROPOSALS` bleiben fail-closed bis zu ihren
>    Folge-Stories (FAIL-CLOSED für noch nicht gebaute Tabellen ist korrekt).
>
> **Import-Richtung beachten (Worker):** Der fc-Record-Typ für das
> `_KIND_TO_RECORD_TYPE`-Mapping muss ein **Blatt-Modul** sein (analog
> `verify_system.stage_registry.records`, das telemetry importiert, ohne
> telemetry zu importieren) — sonst Zirkularität `failure_corpus`↔`telemetry`.

**Typ:** Implementation
**Groesse:** L
**Abhaengigkeiten:** AG3-021 (`FailureCategory`, `Severity`; der dort gelieferte `PromotionStatus` wird in dieser Story durch `IncidentStatus` ersetzt — siehe KONFLIKT-1), AG3-022 (`ArtifactClass`-Bezug), **AG3-035 (`ProjectionAccessor`)**, **AG3-040 (Postgres-Store-Completion)**
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
- `failure-corpus.A2`: Value-Types (`IncidentId`, `PatternId`, `CheckId`), `FailureCategory`-StrEnum (12 Werte — AG3-021 hat sie geliefert), `IncidentStatus`-StrEnum (ersetzt den alten `PromotionStatus`; siehe KONFLIKT-1), `IncidentCandidate`-Pydantic-Modell.
- `failure-corpus.A3`: Sub-Komponente `IncidentTriage` mit `Incident`, `IncidentNormalizer`, `IngressCriteria`, `IncidentSeverity` und einem `ProjectionWriterPort` (statt eines failure_corpus-eigenen `IncidentRepository` — der fc_incidents-DB-Repo liegt accessor-seitig, KONFLIKT-2).
- `failure-corpus.A6/A10`: `fc_incidents`-Tabelle und `record_incident`-Schnittstelle als Empfaenger fuer governance/verify/closure.

Diese Story liefert die **Top-Surface** und die **IncidentTriage-Sub** mit Persistenz — Promotion (PatternPromotion-Sub) und Check-Factory (CheckFactory-Sub) sind Folge-Stories nach dieser Welle (nicht erst-wellen-pflichtig, weil sie weiterfuehrende Logik mit LlmEvaluator/Story-Erzeugung sind, die fuer dieEmpfaenger-Funktion nicht benoetigt wird).

## 2. Scope

### 2.1 In Scope

#### 2.1.1 Paket `src/agentkit/failure_corpus/`

Bestehender leerer `__init__.py`-Stub wird aufgebaut. Neue Modul-Struktur:

- `__init__.py` — Re-Export
- `top.py` — `FailureCorpus`-Top-Komponente
- `types.py` — `IncidentId`, `PatternId`, `CheckId` (NewType), `IncidentSeverity` (StrEnum: `LOW`, `MEDIUM`, `HIGH`, `CRITICAL` — gemaess FK-41)
- `incident.py` — `IncidentCandidate`, `IncidentDraft`, `Incident` Pydantic-Modelle
- `incident_triage.py` — `IncidentTriage`, `IncidentNormalizer`, `IngressCriteria`
- `ports.py` — `IncidentWriterPort` (`record_fc_incident -> IncidentId`) +
  `ProjectionReaderPort` (Corpus-Neuheit) — schmale Konsumenten-Sichten auf den
  `ProjectionAccessor`; **kein** DB-Repository in `failure_corpus`. Der
  fc_incidents-DB-Repo-Adapter lebt auf der Accessor-Seite in
  `state_backend/store`, siehe KONFLIKT-2 + §2.1.5/§3.)
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

#### 2.1.3 `IncidentCandidate`, `IncidentDraft` und `Incident` (FK-41 §41.4.1)

`IncidentCandidate` ist Pydantic-v2-Modell (Input; frozen, extra forbid):
- `project_key: str` (Pflicht; Abfragen stets projektgebunden, FK-41 §41.3.1)
- `story_id: str`
- `run_id: str` (Pflicht)
- `category: FailureCategory`
- `severity: IncidentSeverity` (4 Stufen low/medium/high/critical = FK-41 niedrig/mittel/hoch/kritisch)
- `phase: str`
- `role: IncidentRole` (worker | qa | governance)
- `model: str`
- `symptom: str`
- `evidence: list[str]` (FK-41 §41.4.1: Liste von Evidenz-Strings)
- `tags: list[str] | None`, `impact: str | None` (optional)
- PLUS Gate-Inputs (FK-41 §41.4.3, NICHT persistiert): `merge_blocked: bool`, `rework_minutes: int`

`IncidentDraft` (normalisiert, vor id-Allokation; frozen): alle Persistenzfelder
ausser `incident_id`, plus `recorded_at` und `incident_status` (Default `OBSERVED`),
optional `pattern_ref`. Die `incident_id` wird DB-seitig vergeben.

`Incident` ist Pydantic-v2-Modell (Persistenz, frozen, extra forbid) — die
fc_incidents-Zeile (FK-41 §41.3.1):
- `project_key`, `incident_id` (`FC-YYYY-NNNN`), `run_id`, `story_id`, `category`,
  `severity`, `phase`, `role`, `model`, `symptom`, `evidence: list[str]`,
  `recorded_at`, `incident_status` (Default `OBSERVED`)
- optional `tags`, `impact`, `pattern_ref`

#### 2.1.4 `IncidentTriage`-Sub (FK-41 §41.4)

```python
class IncidentTriage:
    def __init__(self, normalizer: IncidentNormalizer, criteria: IngressCriteria,
                 writer: IncidentWriterPort, reader: ProjectionReaderPort) -> None: ...

    def ingest(self, candidate: IncidentCandidate) -> IncidentId:
        # 1. Corpus-Neuheit ermitteln (reader.read_projection(FC_INCIDENTS, project_key))
        # 2. Pruefe IngressCriteria — verwerfe wenn nicht relevant (IncidentRejectedError)
        # 3. Normalisiere via IncidentNormalizer -> IncidentDraft (recorded_at, OBSERVED)
        # 4. Persistiere via writer.record_fc_incident(draft) -> IncidentId
        #    (id-Allokation FC-YYYY-NNNN in der DB-Transaktion)
        # 5. Gib IncidentId zurueck
        ...
```

`IncidentNormalizer` (Default-Implementierung):
- `category` ist Pflicht im Kandidaten — der Normalizer schaerft nicht die
  Kategorie, sondern macht Whitespace-/Length-Normalisierung von `symptom`
- setzt `recorded_at = now()`

`IngressCriteria` (Default-Implementierung, DK-07 §7.3.6 — Aufnahmekriterien):
Kombinator-Semantik (Codex-r2: DK-07 §7.3.6 ist autoritativ ein **reines ODER**):

    ADMIT  <=>  severity >= min_severity
                OR merge_blocked
                OR rework_minutes > 30
                OR is_novel

- Severity ist **kein** harter Floor (kein AND): ein einziges erfuelltes
  Kriterium genuegt zur Aufnahme (z.B. `LOW + merge_blocked`).
- Corpus-Neuheit (`is_novel`): gleiche `(project_key, category)` noch nicht in
  `fc_incidents` -> neu (geprueft via `read_projection(FC_INCIDENTS, ...)`).
- Reject = `IncidentRejectedError` mit erreichbaren reason_codes:
  `NOT_SIGNIFICANT` (kein Kriterium greift) und `DUPLICATE_WINDOW` (exakter
  Duplikat im Zeitfenster) — FAIL-CLOSED, kein toter reason_code.

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

Tabellen-Schema fuer `fc_incidents` (FK-41 §41.3.1, Codex-r1):
- `project_key` (TEXT, NOT NULL — Pflicht; projektgebunden)
- `incident_id` (TEXT, Format `FC-YYYY-NNNN` — kein uuid)
- `run_id` (TEXT, NOT NULL)
- `story_id` (TEXT, NOT NULL)
- `category` (CHECK: 12 erlaubte Werte aus `FailureCategory`)
- `severity` (CHECK: 4 Werte `low|medium|high|critical` aus `IncidentSeverity`)
- `phase` (TEXT, NOT NULL)
- `role` (TEXT, NOT NULL, CHECK `worker|qa|governance`)
- `model` (TEXT, NOT NULL)
- `symptom` (TEXT, NOT NULL)
- `evidence_json` (JSON/TEXT, NOT NULL — Liste von Strings, FK-41 §41.4.1)
- `recorded_at` (TIMESTAMPTZ, NOT NULL)
- `incident_status` (CHECK: vier Werte `observed|promoted|closed_one_off|archived`;
  Default `observed`)
- optional: `tags` (JSON/TEXT, NULL), `impact` (TEXT, NULL), `pattern_ref` (TEXT, NULL)
- **PK `(incident_id)`** (Codex-r2: incident_id GLOBAL eindeutig; das fruehere
  composite `(project_key, incident_id)` ist zurueckgebaut, siehe r2-Banner).
  Zusaetzliche DB-CHECKs: `incident_id`-Format `FC-YYYY-NNNN` und
  `evidence_json` = JSON-Array (FAIL-CLOSED).
- Append-only: genau ein Datensatz pro `incident_id`.
- Index: `idx_fc_incidents_project_story_run ON fc_incidents(project_key, story_id, run_id)`.
- Index: `idx_fc_incidents_incident_status ON fc_incidents(incident_status)`.
- Begleit-Tabelle `fc_incident_counters(year, next_seq)` (PK `year` allein,
  GLOBAL ueber alle Projekte) fuer die race-sichere `FC-YYYY-NNNN`-Allokation
  via atomarem `ON CONFLICT(year) DO UPDATE ... RETURNING` (Codex-r2).

**Accessor-Schreibvertrag** (Codex-r1 — am Code verifiziert):
- fc_incidents wird ueber die dedizierte
  `ProjectionAccessor.record_fc_incident(draft: IncidentDraft) -> IncidentId`
  geschrieben — NICHT ueber die generische `write_projection` (die `-> None`
  gibt und die in der Transaktion vergebene `FC-YYYY-NNNN`-id nicht liefern
  koennte). `write_projection(FC_INCIDENTS, ...)` ist fail-closed
  (`FCIncidentWriteViaDedicatedMethodError`).
- Schreibpfad: `record_fc_incident` delegiert an den injizierten
  `fc_incidents`-Repo-Adapter, der die id GLOBAL eindeutig ueber den Per-Jahr-
  Zaehler vergibt — race-sicher in EINEM atomaren Statement (`INSERT ... ON
  CONFLICT(year) DO UPDATE SET next_seq = next_seq + 1 RETURNING next_seq - 1`;
  SQLite zusaetzlich unter `BEGIN IMMEDIATE`). Codex-r2.
- `fc_incidents` ist **append-only** (genau ein Datensatz pro `incident_id`,
  FK-41 §41.3.1) — INSERT, kein UPSERT.
- `FC_INCIDENTS` ist accessor-owned (`is_accessor_owned(FC_INCIDENTS) is True`);
  `read_projection(FC_INCIDENTS, ...)` verlangt `project_key` fail-closed.

`FailureCorpus`-Komposition (Composition-Root in `bootstrap/composition_root.py`):
```python
def build_failure_corpus(accessor: ProjectionAccessor) -> FailureCorpus:
    triage = IncidentTriage(
        normalizer=IncidentNormalizer(),
        criteria=IngressCriteria(),
        writer=accessor,  # IncidentWriterPort: record_fc_incident -> IncidentId
        reader=accessor,  # ProjectionReaderPort: Corpus-Neuheit (FK-41 §41.4.3)
    )
    return FailureCorpus(incident_triage=triage)
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
- Tests fuer den `fc_incidents`-Repo-Adapter (state_backend/store, parametrisiert SQLite + Postgres) + Accessor-Roundtrip write→read ueber `write_projection`/`read_projection`
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
| `src/agentkit/telemetry/projection_accessor.py` | Modifiziert | `FC_INCIDENTS` von `_EXTERNALLY_OWNED_KINDS` → `_ACCESSOR_OWNED_KINDS`; Record-Typ ins `_KIND_TO_RECORD_TYPE`; Branch in `write_projection`/`read_projection`/`purge_run`; `# DRIFT-AG3-028`-Marker entfernt (KONFLIKT-2) |
| `src/agentkit/failure_corpus/ports.py` | Neu | `IncidentWriterPort` (`record_fc_incident -> IncidentId`) + `ProjectionReaderPort` (Corpus-Neuheit) |
| `src/agentkit/state_backend/config.py` | Modifiziert | SCHEMA_VERSION 3.9.0 -> 3.10.0 |
| `src/agentkit/telemetry/errors.py` | Modifiziert | `FCIncidentWriteViaDedicatedMethodError` |
| `src/agentkit/core_types/failure_corpus.py` | Modifiziert | `PromotionStatus` (7) entfernt → `IncidentStatus` (4: observed/promoted/closed_one_off/archived) ergänzt (KONFLIKT-1) |
| `src/agentkit/core_types/__init__.py` | Modifiziert | Export `PromotionStatus` → `IncidentStatus` |
| `tests/unit/core_types/test_failure_corpus.py` | Modifiziert | `IncidentStatus` (4 Werte) statt `PromotionStatus` |
| `tests/contract/core_types/test_enum_wire_values.py` | Modifiziert | `IncidentStatus` (4) statt `PromotionStatus` (7) |

<!-- AG3-028 (KONFLIKT-2 RESOLVED 2026-06-01): Persistenz geht ueber
  Telemetry.write_projection(FC_INCIDENTS, record) IN den Accessor. Der
  fc_incidents-DB-Repo-Adapter (fc_incident_repository.py) lebt auf der
  Accessor-Seite in state_backend/store und wird via ProjectionRepositories
  injiziert — NICHT in failure_corpus. failure_corpus haelt nur den schmalen
  ProjectionWriterPort (ports.py) und importiert kein state_backend.store (AC#6).
  Tests konsumieren die produktive Telemetry/Accessor-Instanz. -->

| `tests/unit/failure_corpus/test_top.py` | Neu | Top-Tests |
| `tests/unit/failure_corpus/test_incident.py` | Neu | Modell-Tests |
| `tests/unit/failure_corpus/test_incident_triage.py` | Neu | Triage-Tests |
| `tests/unit/state_backend/store/test_fc_incidents_schema_bootstrap.py` | Neu | Bootstrap-Idempotenz fuer `fc_incidents` (analog `attempts`) |
| `tests/contract/failure_corpus/test_top_surface.py` | Neu | Vertrags-Pinning |
| `tests/integration/failure_corpus/test_record_incident_roundtrip.py` | Neu | End-to-End Empfaenger-Pfad |

## 4. Akzeptanzkriterien

1. **Paket `src/agentkit/failure_corpus/` ist nicht mehr leer** und exportiert `FailureCorpus`, `IncidentCandidate`, `Incident`, `IncidentStatus`, `IncidentId`, `PatternId`, `CheckId`, `IncidentSeverity`, `IncidentTriage`, `IngressCriteria`, `IncidentNormalizer`. (`IncidentStatus` ersetzt `PromotionStatus` in `core_types`; siehe KONFLIKT-1.)
2. **Top-Klasse `FailureCorpus` hat sechs Methoden**: `record_incident`, `suggest_patterns`, `confirm_pattern`, `derive_check`, `approve_check`, `report_effectiveness`. Nur `record_incident` ist voll funktional; die anderen werfen `NotImplementedError` mit aussagekraeftiger Begruendung.
3. **`record_incident(candidate)` ist fail-closed**: ermittelt Corpus-Neuheit, validiert IngressCriteria (DK-07 §7.3.6 reines ODER), normalisiert, schreibt produktiv ueber `ProjectionAccessor.record_fc_incident(draft)` (global eindeutige id-Allokation `FC-YYYY-NNNN` in der DB-Transaktion); gibt `IncidentId` zurueck oder wirft `IncidentRejectedError` (in `errors.py`) bei Reject. `IncidentRejectedError` traegt strukturierte, **erreichbare** `reason_codes` (StrEnum: `NOT_SIGNIFICANT`, `DUPLICATE_WINDOW` — kein toter reason_code; `BELOW_MIN_SEVERITY` entfernt, Codex-r2). Die generische `write_projection(FC_INCIDENTS, ...)` ist fail-closed (`FCIncidentWriteViaDedicatedMethodError`), weil die id zurueckkommen muss.
4. **`fc_incidents`-Tabelle existiert** in SQLite + Postgres mit allen Spalten + Indizes aus §2.1.5 (FK-41 §41.3.1). `project_key`/`run_id`/`role`/`phase`/`model`/`symptom` NOT NULL; `evidence_json` = JSON-Array von Strings (DB-CHECK); `incident_id` Format `FC-YYYY-NNNN` (DB-CHECK). **PK `(incident_id)`** (global eindeutig, Codex-r2). CHECK-Constraints auf `category` (12), `severity` (4), `role` (3), `incident_status` (4). `fc_incident_counters(year, next_seq)` (PK year, global) fuer die race-sichere id-Allokation. SCHEMA_VERSION-Bump 3.10.0 -> 3.11.0 (FK-18 §18.9a, alte DB unangetastet).
5. **`IncidentTriage` durchlaeuft drei Schritte**: IngressCriteria -> Normalizer -> `Telemetry.write_projection`. Per Test verifizierbar.
6. **Architecture-Conformance**: `agentkit.backend.failure_corpus` importiert nur `agentkit.backend.core_types`, `agentkit.backend.artifacts` (optional) und `agentkit.backend.telemetry` (fuer den `Telemetry.write_projection`-Vertrag); **nicht** aus `agentkit.backend.state_backend.store` direkt.
7. **End-to-End-Persistenz**: ein Integration-Test ruft `record_incident` und liest den persistierten Row aus `fc_incidents` auf beiden Backends (SQLite + Postgres).
8. **Pflichtbefehle gruen**: pytest unit + integration + contract; mypy --strict; ruff clean; Coverage haelt 85%.
9. **fc_incidents Reset-Purge (FK-69 §69.9 / FK-41 §41.3)**: `ProjectionAccessor.purge_run` entfernt beim Reset eines `run_id` auch alle `fc_incidents`-Zeilen dieses Runs; das `fc_incidents`-Repository hat `purge_run`; der `# DRIFT-AG3-028`-Marker in `telemetry/projection_accessor.py` ist entfernt. Ein Test legt echte `fc_incidents`-Zeilen an und beweist, dass nach `purge_run` keine Zeile des Runs verbleibt (und andere Runs unberuehrt bleiben).
10. **Accessor-Ownership fuer FC_INCIDENTS (KONFLIKT-2)**: `FC_INCIDENTS` ist von
    `_EXTERNALLY_OWNED_KINDS` nach `_ACCESSOR_OWNED_KINDS` verschoben; `write_projection`/
    `read_projection` bedienen `FC_INCIDENTS` ueber den injizierten `fc_incidents`-Repo
    (kein `ProjectionKindNotAccessorOwnedError` mehr fuer `FC_INCIDENTS`); Record-Typ im
    `_KIND_TO_RECORD_TYPE`-Mapping; `is_accessor_owned(FC_INCIDENTS) is True`. Ein Test
    beweist Roundtrip write→read ueber den Accessor. `FC_PATTERNS`/`FC_CHECK_PROPOSALS`
    bleiben fail-closed (Test pinnt das). `failure_corpus` importiert **kein**
    `state_backend.store` (AC#6).
11. **IncidentStatus ersetzt PromotionStatus (KONFLIKT-1)**: `core_types/failure_corpus.py`
    exportiert `IncidentStatus` (genau `observed`, `promoted`, `closed_one_off`, `archived`);
    `PromotionStatus` ist entfernt; `core_types/__init__.py`, `test_failure_corpus.py` und
    `test_enum_wire_values.py` ziehen mit. Kein verbleibender Import von `PromotionStatus`
    im Repo (Audit/Grep im Test oder PR-Beleg).

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
