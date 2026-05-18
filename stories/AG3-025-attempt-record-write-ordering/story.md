# AG3-025: AttemptRecord typisieren + Write-Ordering Crash-Safety + QA-Zyklus-Identitaeten

**Typ:** Implementation
**Groesse:** M
**Abhaengigkeiten:** AG3-021 (`AttemptOutcome`, `FailureCause`-StrEnums), AG3-024 (PhaseEnvelope-Persistenzgrenze)
**Quell-Konzepte (autoritativ, mit `rel_path` ab Repo-Root):**
- `FK-39 §39.4.1` — `concept/technical-design/39_phase_state_persistenz.md` (Z. 376-389) — AttemptRecord-Schema
- `FK-39 §39.4.2/39.4.3` — `concept/technical-design/39_phase_state_persistenz.md` (Z. 391-422) — AttemptOutcome, FailureCause
- `FK-39 §39.4.4` — `concept/technical-design/39_phase_state_persistenz.md` (Z. 427-454) — Write-Ordering: AttemptRecord VOR PhaseState bei phasenabschliessenden Saves; Crash-Safety
- `FK-27 §27.2` — `concept/technical-design/27_verify_pipeline_closure_orchestration.md` — QA-Zyklus-Identitaeten (`qa_cycle_id`, `qa_cycle_round`, `evidence_epoch`, `evidence_fingerprint`)
- `formal.verify.state-machine` — `concept/formal-spec/verify/state-machine.md` — QA-Zyklus-State-Machine (Hintergrund)
- `FK-18 §18.9a` — `concept/technical-design/18_relationales_abbildungsmodell_postgres.md` (Z. 428-507) — Schema-Versionierung (Side-by-Side-DBs)
- `AG3-024 §2.1.5.1` — `stories/AG3-024-phase-envelope/story.md` — Yield-Klarstellung (PauseReason in PhaseEnvelope vs. AttemptOutcome.YIELDED am AttemptRecord)

---

## 1. Kontext

THEME-004 aus `stories/_priorisierungsempfehlung.md`, Teil 2. Drei Befunde haengen zusammen, weil sie alle die Persistenz-Schicht der Pipeline beruehren:

- `pipeline-framework.B4`: Write-Ordering-Bug. In `_handle_completed_result` wird `save_phase_state` VOR `save_attempt` aufgerufen — verletzt FK-39 §39.4.4 (phasenabschliessende Saves: AttemptRecord zuerst). Bei Crash zwischen den beiden Schreibvorgaengen fehlt der AttemptRecord in der History.
- `pipeline-framework.C4`: `AttemptRecord` ohne `failure_cause`, falsche Felder (`attempt_id` statt `attempt`, fehlendes `ended_at`, nicht-konzeptuelle Zusatzfelder).
- `pipeline-framework.B2`: `AttemptOutcome` und `FailureCause` als StrEnum fehlen — AG3-021 hat die Enums bereitgestellt, hier zieht sie ins Datenmodell.
- `verify-system.A2`: QA-Zyklus-Identitaeten (`qa_cycle_id`, `qa_cycle_round`, `evidence_epoch`, `evidence_fingerprint`) fehlen — gehoeren in die Phase-Persistenz, damit advance_qa_cycle() spaeter (THEME-009/AG3-041) deterministisch arbeiten kann.

Diese Story setzt das Datenmodell-Fundament; QA-Zyklus-Mechanik (advance_qa_cycle, Artefakt-Invalidierung) ist AG3-041.

## 2. Scope

### 2.1 In Scope

#### 2.1.1 `AttemptRecord` umbauen (FK-39 §39.4.1)

`src/agentkit/pipeline_engine/phase_executor/records.py:AttemptRecord` wird auf das Konzept-Schema gehoben:

Pflichtfelder (Pydantic-v2-Modell, `frozen=True`, `extra="forbid"`):
- `run_id: str`
- `phase: PhaseName`
- `attempt: int` (>=1)
- `outcome: AttemptOutcome` (aus `agentkit.core_types`)
- `failure_cause: FailureCause | None` (aus `agentkit.core_types`; gesetzt wenn `outcome in {FAILED, BLOCKED, ESCALATED}` — Wertegruppe konsistent mit FK-39 §39.4.3 Z. 425 "nur gesetzt wenn `outcome` in (`FAILED`, `BLOCKED`, `ESCALATED`)")
- `started_at: datetime`
- `ended_at: datetime` (>= started_at)
- `detail: dict[str, Any] | None`

Nicht-konzeptuelle Zusatzfelder, die heute existieren (`attempt_id`, `guard_evaluations`, `artifacts_produced`, `yield_status`, `resume_trigger`), werden entweder entfernt oder in `detail` als untypisierte Diagnose-Payload gerollt. Entscheidung pro Feld:
- `attempt_id` -> entfaellt (Identitaet ergibt sich aus `(run_id, phase, attempt)`)
- `guard_evaluations` -> wandert nach `detail.guard_evaluations`
- `artifacts_produced` -> wandert nach `detail.artifacts_produced` (langfristig: Zuordnung ueber ArtifactReference; nicht hier)
- `yield_status` -> **entfaellt vollstaendig**; ersetzt durch `outcome=YIELDED` plus `paused_reason: PauseReason` in `PhaseEnvelope.state` (siehe AG3-024 §2.1.5.1 und 2.1.5 unten — keine Duplikatpflege).
- `resume_trigger` -> wandert nach `detail.resume_trigger`

##### 2.1.1.1 SQL-Schema fuer `attempts`-Tabelle (Codex-Befund 1)

Konzeptanker: `FK-39 §39.4.1` definiert das Datenmodell; `FK-18 §18.9a` regelt Schema-Versionierung. Verbindliches DDL fuer die `attempts`-Tabelle in der **neuen** DB unter neuer `SCHEMA_VERSION` (Side-by-Side; siehe AG3-023 §2.1.4.2).

**Postgres** (`state_backend/postgres_schema.sql`, Schema `ak3_vX_Y_Z`):

```sql
CREATE TABLE IF NOT EXISTS attempts (
    run_id          VARCHAR        NOT NULL,
    phase           VARCHAR        NOT NULL,
    attempt         INTEGER        NOT NULL CHECK (attempt >= 1),
    outcome         VARCHAR        NOT NULL CHECK (outcome IN ('COMPLETED','FAILED','ESCALATED','SKIPPED','YIELDED','BLOCKED')),
    failure_cause   VARCHAR        NULL CHECK (
        failure_cause IS NULL OR failure_cause IN (
            'GUARD_REJECTED','STRUCTURAL_CHECK_FAIL','SEMANTIC_REVIEW_FAIL','ADVERSARIAL_FINDING',
            'POLICY_FAIL','WORKER_BLOCKED','INTEGRITY_FAIL','MERGE_FAIL','PREFLIGHT_FAIL',
            'MAX_ROUNDS_EXCEEDED','TIMEOUT','GUARD_FAILED','HANDLER_EXCEPTION','PRECONDITION_FAILED',
            'HANDLER_REPORTED_FAILED','HANDLER_REPORTED_ESCALATED'
        )
    ),
    started_at      TIMESTAMPTZ    NOT NULL,
    ended_at        TIMESTAMPTZ    NOT NULL CHECK (ended_at >= started_at),
    detail_json     JSONB          NULL,
    PRIMARY KEY (run_id, phase, attempt),
    CONSTRAINT failure_cause_consistency CHECK (
        (outcome IN ('FAILED','BLOCKED','ESCALATED') AND failure_cause IS NOT NULL)
        OR (outcome NOT IN ('FAILED','BLOCKED','ESCALATED') AND failure_cause IS NULL)
    )
);
CREATE INDEX IF NOT EXISTS idx_attempts_run_phase ON attempts (run_id, phase);
CREATE INDEX IF NOT EXISTS idx_attempts_outcome ON attempts (outcome);
```

**SQLite** (`state_backend/sqlite_store.py`, Datei `agentkit_X_Y_Z.sqlite`):

```sql
CREATE TABLE IF NOT EXISTS attempts (
    run_id          TEXT     NOT NULL,
    phase           TEXT     NOT NULL,
    attempt         INTEGER  NOT NULL CHECK (attempt >= 1),
    outcome         TEXT     NOT NULL CHECK (outcome IN ('COMPLETED','FAILED','ESCALATED','SKIPPED','YIELDED','BLOCKED')),
    failure_cause   TEXT     NULL CHECK (
        failure_cause IS NULL OR failure_cause IN (
            'GUARD_REJECTED','STRUCTURAL_CHECK_FAIL','SEMANTIC_REVIEW_FAIL','ADVERSARIAL_FINDING',
            'POLICY_FAIL','WORKER_BLOCKED','INTEGRITY_FAIL','MERGE_FAIL','PREFLIGHT_FAIL',
            'MAX_ROUNDS_EXCEEDED','TIMEOUT','GUARD_FAILED','HANDLER_EXCEPTION','PRECONDITION_FAILED',
            'HANDLER_REPORTED_FAILED','HANDLER_REPORTED_ESCALATED'
        )
    ),
    started_at      TEXT     NOT NULL,       -- ISO-8601 mit TZ
    ended_at        TEXT     NOT NULL,       -- ISO-8601 mit TZ
    detail_json     TEXT     NULL,           -- JSON-Text
    PRIMARY KEY (run_id, phase, attempt),
    CHECK (ended_at >= started_at),
    CHECK (
        (outcome IN ('FAILED','BLOCKED','ESCALATED') AND failure_cause IS NOT NULL)
        OR (outcome NOT IN ('FAILED','BLOCKED','ESCALATED') AND failure_cause IS NULL)
    )
);
CREATE INDEX IF NOT EXISTS idx_attempts_run_phase ON attempts (run_id, phase);
CREATE INDEX IF NOT EXISTS idx_attempts_outcome ON attempts (outcome);
```

Hinweise:
- Wire-Werte der Enums sind **upper-case** Strings (siehe AG3-021 §2.1.1.1 Tabelle `AttemptOutcome` und `FailureCause`).
- `detail_json` ist NULL-fahig; Worker/Handler-Diagnose-Payload aus `detail.guard_evaluations`, `detail.artifacts_produced`, `detail.resume_trigger`.
- Primary-Key `(run_id, phase, attempt)` ist konsistent mit der konzeptionellen Identitaet aus FK-39 §39.4.1.
- `failure_cause_consistency` als named CHECK-Constraint enforced das `outcome -> failure_cause`-Verhaeltnis aus FK-39 §39.4.3 Z. 425 — keine Pruefung im Code als zweite Wahrheit; einzige operative Wahrheit liegt im DB-Constraint plus dem Pydantic-Model-Validator (Belt-and-Suspenders).

##### 2.1.1.2 Backfill-Regeln fuer bestehende AttemptRecords (Codex-Befund 2)

FK-18 §18.9a-Regelung gilt analog AG3-023 §2.1.4.1: Pre-Release-Phase, Schema-Bump erzeugt **neue DB unter neuer Versions-Kennung**; alte DB unter alter Kennung bleibt unangetastet. Es gibt **keine** automatische Daten-Migration der alten `attempts`-Tabelle.

Regeln pro neuer/geaenderter Spalte (relevant fuer Worker, die ein Migrations-Tooling spaeter bauen — nicht Teil dieser Story):

| Spalte | Quelle aus Alt-Daten | Default bei nicht-mappbarem Alt-Wert | Fehlerfall |
|---|---|---|---|
| `failure_cause` | aus `outcome`-Wert plus alter Freitext-Diagnose ableitbar: `outcome=FAILED` ohne Cause-Hinweis -> `HANDLER_REPORTED_FAILED` (Fallback); `outcome=ESCALATED` ohne Cause -> `HANDLER_REPORTED_ESCALATED`; bei `BLOCKED` ohne erkennbare Quelle -> `WORKER_BLOCKED` | n/a — wenn ein Alt-Wert tatsaechlich nicht mappbar ist (kein Outcome, kein Hinweis): **fail-closed**, Migrations-Tooling listet den Datensatz und bricht ab | Worker melden den Eintrag dem Auftraggeber zur manuellen Korrektur |
| `detail` | aus alten Feldern `guard_evaluations`, `artifacts_produced`, `resume_trigger` zusammengefuehrt | `None`, falls keines der Felder gesetzt war | n/a |
| `ended_at` | aus altem `finished_at` (falls vorhanden) oder altem `completed_at`; falls fehlend, **fail-closed** | n/a — fehlendes `ended_at` ist nicht akzeptabel | Migrations-Tooling bricht ab; Worker melden |
| `started_at` | aus altem `started_at` (Pflichtfeld auch vorher) | n/a | fail-closed |
| `attempt` | aus altem `attempt` (Pflichtfeld) oder, falls Alt-Modell `attempt_id` trug, **fail-closed** (kein automatischer Cast aus `attempt_id` zu `attempt:int`) | n/a | fail-closed; Worker melden |

**Praktische Konsequenz fuer diese Story**: Da AK3 noch keine produktiven Bestandsdaten kennt, ist Backfill in dieser Story nicht zu implementieren. Die obigen Regeln sind verbindlicher Leitfaden fuer eine spaetere Migrations-Story (FK-18 §18.9a.4 sieht das als separat gestartete Aktion vor). Migration-Tests in dieser Story beschraenken sich auf:
- "neue DB bootet sauber" (siehe AG3-023 §2.1.4.2)
- "alte DB unter alter Versions-Kennung bleibt unangetastet"
- "Re-Run der `attempts`-Bootstrap-Sequenz auf der neuen DB ist idempotent"

Es gibt keinen Read-mit-Default-Pfad in dieser Story.

#### 2.1.2 Write-Ordering-Bug beheben (FK-39 §39.4.4, Codex-Befund 3)

`src/agentkit/pipeline/engine.py`:

Phasenabschliessende Saves: ZUERST `save_attempt` (AttemptRecord), DANN `save_phase_state` (PhaseEnvelope.state). Begruendung: ein Crash zwischen den beiden Saves muss `state` als noch-nicht-abgeschlossen zeigen, aber den AttemptRecord der gerade beendeten Attempt-Phase erhalten — Recovery kann darauf aufsetzen (FK-39 §39.4.4 Z. 431-437).

##### 2.1.2.1 Die drei Handler, in denen die Write-Ordering-Invariante gilt

| Handler-Methode (in `pipeline/engine.py`) | Phase-Outcome | Status heute (vor AG3-025) | Fix in dieser Story |
|---|---|---|---|
| `_handle_completed_result` | `COMPLETED` | **falsch**: heute `save_phase_state` vor `save_attempt` (`pipeline-framework.B4`) | Reihenfolge umstellen: `save_attempt` zuerst |
| `_handle_terminal_result`  | `FAILED` / `ESCALATED` | **bereits korrekt** laut GAP-Analyse — kein Code-Change noetig, nur Test als Invariant-Sicherung | Test sichert |
| `_handle_guard_failure_result` | `BLOCKED` / Guard-Reject (`failure_cause=GUARD_REJECTED` oder `GUARD_FAILED`) | **bereits korrekt** laut GAP-Analyse | Test sichert |

Zusaetzlich: PAUSED-Saves (`_handle_paused_result`, AG3-024) sind ebenfalls phasenabschliessend gemaess FK-39 §39.4.4 Z. 429 ("COMPLETED, FAILED, ESCALATED, PAUSED"). Sie sind kein Bestandteil dieser Story, weil AG3-024 schon die PauseReason-Typisierung mitbringt; die Write-Ordering fuer PAUSED wird **als bestehende Invariante** durch einen separaten Test gepruft (analog zu den anderen Handlern). Falls die Reihenfolge dort heute schon korrekt ist, bleibt sie; falls nicht, wird sie in dieser Story korrigiert (Reihenfolge-Korrektur ist trivial). Wenn Bestands-Code beim Lesen der Engine zeigt, dass Pause-Path nicht abgedeckt ist, ist das Teil dieser Story.

Refactor-Empfehlung (siehe §8 unten): die Reihenfolge an allen Stellen in eine Hilfsfunktion `save_phase_completion(envelope: PhaseEnvelope, attempt_record: AttemptRecord) -> None` zusammenfassen, die intern `save_attempt(record)` -> `save_phase_state(envelope.state)` ruft. Damit ist die Invariante an genau einem Ort verankert.

##### 2.1.2.2 Test-Doubles und Beweis-Strategie

Tests fuer Write-Ordering in `tests/unit/pipeline/test_engine_write_ordering.py` (neu) und `tests/unit/pipeline_engine/phase_executor/test_write_ordering_helper.py` (neu, falls Hilfsfunktion eingefuehrt):

- **Recording-Mock-Repository**: ein Test-Doppel fuer die Persistenz-Schicht (Repository-Protocol) zeichnet die Aufrufreihenfolge auf:

```python
class RecordingAttemptRepository:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []

    def save(self, record: AttemptRecord) -> None:
        self.calls.append(("save_attempt", record))


class RecordingPhaseRepository:
    def __init__(self, log: list[tuple[str, Any]]) -> None:
        self.log = log

    def save(self, envelope_state: PhaseState) -> None:
        self.log.append(("save_phase_state", envelope_state))
```

- Beide Test-Doubles teilen sich eine `call_log: list[tuple[str, Any]]` (Composition ueber gemeinsame Liste oder Adapter-Pattern). Pro Handler-Test: Engine mit Doubles ausfuehren -> assert `call_log == [("save_attempt", ...), ("save_phase_state", ...)]` in **dieser Reihenfolge**.
- Pro Handler **ein** Test:
  - `test_completed_result_save_ordering` -> `_handle_completed_result`
  - `test_terminal_result_save_ordering` -> `_handle_terminal_result` mit `outcome=FAILED` und `outcome=ESCALATED` (parametrisiert)
  - `test_guard_failure_result_save_ordering` -> `_handle_guard_failure_result`
- Crash-Simulation-Test `test_crash_between_saves_keeps_attempt_record` (Recording-Repository wirft nach `save_attempt` eine Exception, bevor `save_phase_state` aufgerufen wird; verify dass: AttemptRecord-Repository-Call erfolgte, PhaseState-Repository-Call nicht).
- **Keine MagicMock**, sondern echte Test-Doubles mit kontrolliertem Verhalten (CLAUDE.md "MOCKS/STUBS NUR IM ENGEN AUSNAHMEFALL").

#### 2.1.3 QA-Zyklus-Identitaeten in PhaseState (FK-27 §27.2)

`src/agentkit/story_context_manager/models.py:PhaseState` (oder die ImplementationPayload-Sub):

- Neue Felder im `ImplementationPayload` (bzw. korrespondierendem Sub-Payload fuer die Phase, in der QA laeuft) — **wortgleich FK-27 §27.2.1**:
  - `qa_cycle_id: str | None` (12-Zeichen lowercase hex UUID-Fragment; wird bei jedem `advance_qa_cycle()` neu generiert; bleibt fuer alle Remediation-Runden eines Zyklus)
  - `qa_cycle_round: int` (>=0, monoton ab 1 wenn `qa_cycle_id` gesetzt; inkrementiert bei neuem Zyklus)
  - `evidence_epoch: datetime | None` (UTC-aware ISO-8601 Timestamp; Zeitpunkt der letzten Code-/Artefakt-Mutation — **kein Counter**, ein Datum)
  - `evidence_fingerprint: str | None` (SHA-256-Hash als 64-char lowercase hex ueber die relevanten Artefakte; Entscheidung 2026-04-08 Element 19)
- Validatoren: wenn `qa_cycle_id` gesetzt ist, muss `qa_cycle_round >= 1` sein; `evidence_epoch` ist tz-aware (fail-closed bei naive datetimes); `qa_cycle_id` matched `^[0-9a-f]{12}$`; `evidence_fingerprint` matched `^[0-9a-f]{64}$`.

<!-- AG3-025 Re-Review (User-Entscheidung 2026-05-18): Variante B — Konzepte (FK-27 §27.2.1) bleiben autoritativ, Implementierung wurde nachgezogen. Aelterer Story-Wortlaut "UUID4" + "evidence_epoch: int" war konzeptwidrig und ist ersetzt. -->

- Schema-Versionierung: Side-by-Side via `state_backend.config.SCHEMA_VERSION`-Bump (AG3-005). Alte DB unangetastet.

WICHTIG: Diese Story stellt nur das **Datenmodell** und die **Persistenz** bereit. Die Logik, die diese Felder befuellt und invalidiert (`advance_qa_cycle`, 11 Artefaktdateien nach `stale/`), ist Inhalt von AG3-041 (THEME-009).

#### 2.1.4 YIELDED ↔ PauseReason-Trennung (Codex-Befund 4, §"Konzept-Spannungen" Pkt. 3)

Yield-Information **eindeutig getrennt** zwischen `AttemptRecord` und `PhaseEnvelope.state`:

- **`AttemptOutcome.YIELDED` am `AttemptRecord`** — eine reine **Outcome-Markierung**. Sie sagt: "dieser Phase-Versuch endete mit YIELD". Das Feld `failure_cause` ist bei `YIELDED` `None` (Yield ist kein Failure; nur `outcome in {FAILED, BLOCKED, ESCALATED}` setzt `failure_cause`).
- **`paused_reason: PauseReason` in `PhaseEnvelope.state`** (AG3-024) — der **fachliche Pause-Grund** (z.B. `AWAITING_DESIGN_REVIEW`). Konzept-Soll: lebt im durable PhaseStateCore.

**Doppelpflege ist verboten.** Es gibt **eine** Quelle fuer den Pause-Grund (PhaseEnvelope.state.paused_reason). Der `AttemptRecord` markiert nur das Outcome.

Konsequenzen fuer diese Story:
- `AttemptRecord.detail` traegt **kein** Feld `paused_reason` und kein `pause_reason` und keinen `yield_status`. Das alte `yield_status` ist entfernt (siehe 2.1.1).
- Tests verifizieren: ein PAUSED-Phase-Abschluss schreibt einen `AttemptRecord(outcome=YIELDED, failure_cause=None, ...)` und ein `PhaseEnvelope.state` mit `paused_reason: PauseReason` — und genau **nur** an diesen beiden Orten.
- Recovery-Logik (FK-39 §39.4.4) liest `paused_reason` aus dem PhaseState, nicht aus dem AttemptRecord.

Verwortlich wortgleich abgestimmt mit AG3-024 §2.1.5.1 (Codex-Befund §"Konzept-Spannungen" Pkt. 3: "Yield-Information ueber zwei Stories").

#### 2.1.5 Tests

- Unit-Tests fuer `AttemptRecord` (alle Pflichtfelder, validators, frozen, extra forbid) in `tests/unit/pipeline_engine/phase_executor/test_attempt_record.py`.
- Unit-Tests fuer Write-Ordering: Recording-Test-Doubles (siehe 2.1.2.2) zeichnen die Aufruf-Reihenfolge auf; AttemptRecord wird vor PhaseState gespeichert in allen drei Handlern aus 2.1.2.1 — `tests/unit/pipeline/test_engine_write_ordering.py`.
- Crash-Safety-Test (`test_crash_between_saves_keeps_attempt_record`): simulierter Crash zwischen `save_attempt` und `save_phase_state` laesst den AttemptRecord lesbar, PhaseState noch im vorherigen Zustand.
- Yield-Trennung-Test in `tests/unit/pipeline/test_engine_yielded_split.py`: ein PAUSED-Abschluss schreibt `AttemptRecord(outcome=YIELDED, failure_cause=None)` und `PhaseEnvelope.state.paused_reason=<PauseReason>`. AttemptRecord-`detail` enthaelt **kein** `paused_reason`, **kein** `pause_reason`, **kein** `yield_status` — Felder explizit asserted (siehe 2.1.4).
- Unit-Tests fuer QA-Zyklus-Identitaeten im PhaseState (Pflichtfelder, Validators, Defaults) in `tests/unit/story_context_manager/test_qa_cycle_fields.py`.
- Bootstrap-Idempotenz-Test in `tests/unit/state_backend/store/test_attempt_schema_bootstrap_idempotent.py`: zweimaliger Bootstrap der `attempts`-Tabelle in SQLite und Postgres ist ohne Fehler erfolgreich; keine Duplikate.
- **Keine** Migrations-Tests aus alter Persistenz in dieser Story (Greenfield; Migrations-Tests sind separate Story siehe 2.1.1.2). Test-Setup baut frische DB pro Test.

### 2.2 Out of Scope

- QA-Zyklus-Mechanik selbst (`advance_qa_cycle`, Artefakt-Invalidierung, `evidence_fingerprint`-Berechnung) — THEME-009 (AG3-041)
- Stage-Registry-Bindung — THEME-009
- Recovery-CLI — separate Story
- Orchestrator-Spawn fuer Remediation — THEME-009 (AG3-044)
- Severity-Reporting-Schema-Erweiterung — gehoert zu Policy-Engine-Story (Folge von AG3-021)

## 3. Betroffene Dateien

| Datei | Aenderungsart | Beschreibung |
|---|---|---|
| `src/agentkit/pipeline_engine/phase_executor/records.py` | Modifiziert | `AttemptRecord` mit FK-39-§39.4.1-Schema |
| `src/agentkit/pipeline_engine/phase_executor/save_phase_completion.py` | Neu (optional) | Hilfsfunktion `save_phase_completion(envelope, attempt_record)` mit fester Reihenfolge `save_attempt` -> `save_phase_state` |
| `src/agentkit/pipeline/engine.py` | Modifiziert | Write-Ordering Fix in `_handle_completed_result` (siehe 2.1.2.1); Aufrufe an `save_attempt` mit neuem AttemptRecord-Schema; alle drei Handler benutzen `save_phase_completion` (falls Hilfsfunktion eingefuehrt) |
| `src/agentkit/state_backend/store/attempt_repository.py` | Modifiziert | Schema-Mapping: `failure_cause`, `ended_at`, `detail_json` |
| `src/agentkit/state_backend/postgres_schema.sql` | Modifiziert | `attempts`-Tabelle gemaess DDL in 2.1.1.1 (Postgres) |
| `src/agentkit/state_backend/sqlite_store.py` | Modifiziert | `attempts`-Tabelle gemaess DDL in 2.1.1.1 (SQLite) |
| `src/agentkit/state_backend/config.py` | Modifiziert | `SCHEMA_VERSION`-Bump (Side-by-Side, FK-18 §18.9a) |
| `src/agentkit/story_context_manager/models.py` | Modifiziert | `ImplementationPayload` (oder analoges Phase-Sub) mit QA-Zyklus-Feldern |
| `tests/unit/pipeline_engine/phase_executor/test_attempt_record.py` | Neu/Modifiziert | AttemptRecord-Schema-Tests |
| `tests/unit/pipeline/test_engine_write_ordering.py` | Neu | Write-Ordering-Tests pro Handler (siehe 2.1.2.2) |
| `tests/unit/pipeline/test_engine_yielded_split.py` | Neu | Yield-Trennung: outcome=YIELDED + paused_reason in PhaseEnvelope (siehe 2.1.4) |
| `tests/unit/story_context_manager/test_qa_cycle_fields.py` | Neu | QA-Zyklus-Identitaets-Felder |
| `tests/unit/state_backend/store/test_attempt_repository.py` | Modifiziert | Roundtrip mit failure_cause; DB-CHECK-Constraints werden verprobt |
| `tests/unit/state_backend/store/test_attempt_schema_bootstrap_idempotent.py` | Neu | Idempotenz des `attempts`-Bootstrap-Pfads (analog AG3-023) |

## 4. Akzeptanzkriterien

1. **`AttemptRecord` traegt die FK-39-Pflichtfelder**: `run_id`, `phase`, `attempt`, `outcome: AttemptOutcome`, `failure_cause: FailureCause | None`, `started_at`, `ended_at`, `detail`. Nicht-konzeptuelle Felder sind entfernt oder in `detail` verlagert (Mapping siehe 2.1.1). Modell ist Pydantic-v2, frozen, extra forbid.
2. **`failure_cause` ist gesetzt** wenn `outcome in {FAILED, BLOCKED, ESCALATED}`, sonst `None` (konzeptkonform mit FK-39 §39.4.3 Z. 425). Pydantic-Validator enforced das; DB-CHECK-Constraint `failure_cause_consistency` enforced es doppelt (siehe 2.1.1.1).
3. **SQL-Schema fuer `attempts`-Tabelle** ist in beiden Stores wie in 2.1.1.1 spezifiziert: Postgres-DDL und SQLite-DDL inklusive `CHECK`-Constraints fuer `outcome`, `failure_cause`, `failure_cause_consistency`, `attempt >= 1`, `ended_at >= started_at`, Primary-Key `(run_id, phase, attempt)`, Index `idx_attempts_run_phase` und `idx_attempts_outcome`.
4. **Write-Ordering korrekt** in den drei in 2.1.2.1 aufgelisteten Handlern (`_handle_completed_result`, `_handle_terminal_result`, `_handle_guard_failure_result`) — `save_attempt` VOR `save_phase_state`. Die Recording-Test-Doubles aus 2.1.2.2 verifizieren die Reihenfolge per `call_log`-Assertion in **dieser** Reihenfolge.
5. **Crash-Safety-Invariante** demonstriert (Test `test_crash_between_saves_keeps_attempt_record`): nach simuliertem Crash zwischen den beiden Saves ist der AttemptRecord lesbar, PhaseState noch im vorherigen Stand.
6. **QA-Zyklus-Identitaeten in PhaseState**: `qa_cycle_id`, `qa_cycle_round`, `evidence_epoch`, `evidence_fingerprint` sind im ImplementationPayload (oder korrespondierendem Sub) typisiert vorhanden. Pflicht-Defaults: alle `None`/0 bei Erstanlage. Validator: bei gesetztem `qa_cycle_id` ist `qa_cycle_round >= 1`.
7. **Schema-Migration**: AttemptRecord-Tabelle und PhaseState-Spalten in beiden Stores (SQLite + Postgres) mit Side-by-Side-Versionierung (FK-18 §18.9a). Bootstrap idempotent re-runnable (analog AG3-023 §2.1.4.2). Backfill-Regeln aus 2.1.1.2 sind dokumentiert, aber nicht implementiert (Greenfield).
8. **`outcome=YIELDED` korrekt belegt**: Yield-Status laeuft nicht mehr als rohes String-Feld, sondern als `AttemptOutcome.YIELDED` (am AttemptRecord, `failure_cause=None`) plus `PhaseEnvelope.state.paused_reason: PauseReason` (das hat AG3-024 gesetzt). Doppelpflege ist verboten — Tests verifizieren das (siehe 2.1.4).
9. **Pflichtbefehle gruen**: pytest unit + integration; mypy --strict; ruff clean; Coverage haelt 85%.

## 5. Definition of Done

- AK 1-9 erfuellt.
- `.venv\Scripts\python -m pytest -q` gruen.
- `mypy --strict` gruen, `ruff check src tests` gruen.
- SQLite + Postgres migriert (Bootstrap idempotent re-runnable; alte DB bleibt unangetastet).
- Aenderungen committed auf `main`.

## 6. Konzept-Referenzen (autoritativ, mit `rel_path`)

- **FK-39 §39.4.1** — `concept/technical-design/39_phase_state_persistenz.md` (Z. 376-389) — AttemptRecord-Schema
- **FK-39 §39.4.2/39.4.3** — `concept/technical-design/39_phase_state_persistenz.md` (Z. 391-422) — AttemptOutcome, FailureCause inkl. Wertelisten
- **FK-39 §39.4.4** — `concept/technical-design/39_phase_state_persistenz.md` (Z. 427-454) — Write-Ordering bei phasenabschliessenden Saves; Crash-Safety
- **FK-27 §27.2** — `concept/technical-design/27_verify_pipeline_closure_orchestration.md` — QA-Zyklus-Identitaeten
- **`formal.verify.state-machine`** — `concept/formal-spec/verify/state-machine.md` — QA-Zyklus-State-Machine (Hintergrund, hier nur Datenmodell)
- **FK-18 §18.9a** — `concept/technical-design/18_relationales_abbildungsmodell_postgres.md` (Z. 428-507) — Schema-Versionierung (Side-by-Side-DBs, idempotenter Bootstrap)
- **AG3-024 §2.1.5.1** — `stories/AG3-024-phase-envelope/story.md` — Yield-Klarstellung (PauseReason in PhaseEnvelope vs. AttemptOutcome.YIELDED am AttemptRecord)
- **AG3-021 §2.1.1.1** — `stories/AG3-021-kern-enums/story.md` — Wire-Werte fuer `AttemptOutcome` und `FailureCause` (upper-case Strings, fuer `CHECK`-Constraint-Liste in 2.1.1.1)

## 7. Guardrail-Referenzen

- **FIX THE MODEL, NOT THE SYMPTOM**: AttemptRecord-Schema endlich konzeptkonform; keine String-Outcomes.
- **ZERO DEBT**: alte Zusatzfelder entweder klar entfernt oder in `detail` rolled — kein Doppelgesicht.
- **FAIL CLOSED**: outcome ohne korrespondierende failure_cause -> Validator-Fehler.
- **SINGLE SOURCE OF TRUTH**: ein AttemptRecord-Modell, ein Persistenzpfad.

## 8. Hinweise fuer den Sub-Agent

- Write-Ordering: pruefe alle Aufruf-Pfade von `save_attempt` und `save_phase_state`. Es gibt drei Handler (2.1.2.1) — fasse die Reihenfolge in einer Hilfsfunktion `save_phase_completion(envelope, attempt_record)` zusammen, die intern `save_attempt(record)` -> `save_phase_state(envelope.state)` ruft. Damit ist die Invariante an genau einem Ort verankert (siehe 2.1.2.1 letzter Absatz).
- Schema-Bootstrap nach FK-18 §18.9a-Mechanik: Side-by-Side-DB pro `SCHEMA_VERSION`, **kein** `ALTER TABLE` auf alter DB; Re-Run-Safety durch `CREATE TABLE IF NOT EXISTS` analog AG3-023 §2.1.4.2. Die SQL-DDLs in 2.1.1.1 sind verbindlich.
- Yield-Trennung: PauseReason (fachlicher Grund) lebt in `PhaseEnvelope.state.paused_reason` (AG3-024 Owner); `AttemptOutcome.YIELDED` ist reine Outcome-Markierung am AttemptRecord ohne `failure_cause`. Keine Duplikatpflege im AttemptRecord.detail; Tests asserten das (siehe 2.1.4 und 2.1.5).
- QA-Zyklus-Identitaeten sind nur Datenmodell. Wer sie befuellt: AG3-041 (siehe Out-of-Scope).
- AK2 NICHT veraendern.
