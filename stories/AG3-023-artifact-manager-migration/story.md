# AG3-023: ArtifactManager + Migration der QA-Persistenz und Protected-Path-Liste

**Typ:** Implementation
**Groesse:** L
**Abhaengigkeiten:** AG3-022 (Envelope/Registry-Foundation)
**Quell-Konzepte (autoritativ, mit `rel_path` ab Repo-Root):**
- `FK-71 §71.2` — `concept/technical-design/71_artefakt_envelope_und_stage_registry.md` (Envelope-Pflichtfelder, ArtifactManager-Vertrag, Z. 109-181)
- `concept/_meta/bc-cut-decisions.md §BC 8 artifacts` — Z. 715-770 (ArtifactManager-Top-Surface `write/read/exists`)
- `FK-31 §31.3` — `concept/technical-design/31_branch_guard_orchestrator_guard_artefaktschutz.md` (QA-Artefakt-Schutz, Z. 420-487; **Protected-Path-Listen gehoeren in governance-and-guards**)
- `concept/_meta/bc-cut-decisions.md §BC 4 governance-and-guards` — Z. 285-338 (Modul-Pfad `agentkit.backend.governance.guard_system`; PROTECTED_ARTIFACTS-Liste pt. 24 der Refactor-Liste Z. 1900)
- `concept/_meta/bc-cut-decisions.md §BC 8 Konzept-Refactor-Liste Pkt. 24` — Z. 1900 (PROTECTED_ARTIFACTS gehoert zur Hook-Konfiguration in BC 4, nicht zu artifacts)
- `FK-18 §18.9a` — `concept/technical-design/18_relationales_abbildungsmodell_postgres.md` (Schema-Versionierung, Side-by-Side-DBs, Z. 428-507)

---

## 1. Kontext

THEME-003 Teil 2. AG3-022 hat das Datenmodell-Fundament gelegt (Envelope, Registry, Reference, Validator). Diese Story zieht den Vertrag in die Praxis:

- `ArtifactManager.write/read/exists` gegen den State-Backend-Driver
- Migration der existierenden QA-Artefakt-Persistenz (`verify_system/artifacts.py`) auf den Manager — verify-system konsumiert ArtifactManager statt eigener Persistenz-Facade (Drift `artifacts.C1`)
- Umzug der QA-Protected-Path-Liste aus `state_backend/paths.py` nach `governance-and-guards` (Drift `artifacts.C2`)
- Erweiterung der Artefaktklassen-Heuristik in `state_backend/postgres_store.py:_artifact_class_for` auf alle acht Klassen (Drift `artifacts.B1`)

Spezifische Befunde:
- `artifacts.A2`: ArtifactManager fehlt
- `artifacts.B2`: QA-Persistenz im falschen BC (verify_system)
- `artifacts.C1`: BC-Ownership-Verletzung — verify-system als de-facto Owner der Persistenz
- `artifacts.C2`: PROTECTED_QA_ARTIFACTS in state_backend statt governance
- `artifacts.B1`: nur 2 von 8 Artefaktklassen in postgres_store-Heuristik

## 2. Scope

### 2.1 In Scope

#### 2.1.1 `ArtifactManager` Top-Surface (bc-cut-decisions.md §BC 8)

Neues Modul `src/agentkit/artifacts/manager.py`:

```python
class ArtifactManager:
    def __init__(self, repository: ArtifactRepository, validator: EnvelopeValidator) -> None: ...
    def write(self, envelope: ArtifactEnvelope) -> ArtifactReference: ...
    def read(self, reference: ArtifactReference) -> ArtifactEnvelope: ...
    def exists(self, reference: ArtifactReference) -> bool: ...
```

- `write` validiert vor Persistenz (`EnvelopeValidator`), schreibt ueber `ArtifactRepository` (Protocol, siehe 2.1.2), gibt `ArtifactReference` zurueck.
- `read` laedt den Envelope; wirft `ArtifactNotFoundError` bei fehlendem Eintrag.
- `exists` ist Read-only-Check.
- Fail-closed: validation-Fehler werden propagiert; partial-writes sind nicht erlaubt (Transaktion oder atomic file write je nach Backend).

#### 2.1.2 `ArtifactRepository`-Protocol

`src/agentkit/artifacts/repository.py`:

```python
class ArtifactRepository(Protocol):
    def write_envelope(self, envelope: ArtifactEnvelope) -> ArtifactReference: ...
    def read_envelope(self, reference: ArtifactReference) -> ArtifactEnvelope | None: ...
    def exists_envelope(self, reference: ArtifactReference) -> bool: ...
```

Konkrete Implementierungen werden in `state_backend/store/artifact_repository.py` neu angelegt (SQLite + Postgres), parallel zu existierenden Repos. Repository-Vertrag respektiert BC-Grenztreue (kein generischer `state_backend.store`-Fassaden-Import von Aufrufern; nur das Repository-Modul selbst nutzt die Fassade).

#### 2.1.3 Migration `verify_system/artifacts.py` -> ArtifactManager

`verify_system/artifacts.py` wandelt sich von "Persistenz-Facade" zu "Konsument von ArtifactManager":

- Funktionen `write_layer_artifacts`, `write_verify_decision_artifacts`, `load_verify_decision_artifact` rufen jetzt `ArtifactManager.write/read` mit einem korrekt gebauten `ArtifactEnvelope` auf (Pflichtfelder: `schema_version="3.0"`, `story_id`, `run_id`, `stage`, `attempt`, `producer`, `started_at`, `finished_at`, `status`, `artifact_class=QA`).
- Producer-Registrierung: vor dem ersten Aufruf wird `ProducerRegistry.register(ArtifactClass.QA, "verify-system.layer-1", ProducerType.DETERMINISTIC)` (analog fuer Layer-2/3/4) durchgefuehrt. Das passiert in einem Init-Hook von verify-system (`src/agentkit/verify_system/__init__.py` oder `register.py`).
- `serialize_layer_result` und `build_verify_decision_artifact` werden auf Envelope-Pflichtfelder gehoben (Drift `artifacts.B3`).

#### 2.1.4 Postgres- und SQLite-Schema fuer Artefakte (artifacts.B1)

`state_backend/postgres_schema.sql` und SQLite-Migration:

- `artifact_records`-Tabelle erweitert: Spalten `schema_version VARCHAR NOT NULL`, `attempt INT NOT NULL`, `producer_type VARCHAR NOT NULL`, `producer_id VARCHAR NOT NULL`, `producer_version VARCHAR NULL`, `started_at TIMESTAMPTZ NOT NULL`, `finished_at TIMESTAMPTZ NOT NULL`, `status VARCHAR NOT NULL`, `artifact_class VARCHAR NOT NULL` (8 erlaubte Wire-Werte als CHECK-Constraint — lower-case gemaess AG3-021 §2.1.1.1 Tabelle ArtifactClass), `payload_json JSON`
- Index auf `(story_id, run_id, stage, attempt)`
- Schema-Versionierung Side-by-Side via `SCHEMA_VERSION`-Bump nach FK-18 §18.9a (`agentkit_X_Y_Z.sqlite` bzw. Postgres-Schema `ak3_vX_Y_Z`)
- `_artifact_class_for`-Heuristik wird ersetzt: artifact_class wird aus Envelope direkt persistiert, keine Heuristik mehr noetig

##### 2.1.4.1 Backfill-Regeln fuer neue Envelope-Spalten (Codex-Befund 1)

FK-18 §18.9a (`concept/technical-design/18_relationales_abbildungsmodell_postgres.md` Z. 428-507) legt fest: **Schema-Wechsel ist destruktiver Reset** (Pre-Release, vor 1.0). Die alte DB unter alter Versions-Kennung bleibt unangetastet; die neue DB wird unter der neuen `SCHEMA_VERSION` leer angelegt. Es gibt **kein** automatisches Daten-Upgrade.

Damit ist die Backfill-Frage in der Pre-1.0-Phase nicht "wie projiziere ich Alt-Daten?", sondern: **Wie verhalten sich Tests und CI-Lauf, wenn eine alte DB-Datei oder ein altes Postgres-Schema unter dem Code mit neuer `SCHEMA_VERSION` herumliegt?**

Regeln pro neuer Envelope-Pflichtspalte:

| Spalte | Quelle (live-Schreibpfad) | Default bei leerem Feld | Fehlerfall | Migrations-Verhalten |
|---|---|---|---|---|
| `schema_version`  | `ENVELOPE_SCHEMA_VERSION` ("3.0") | n/a (Konstante) | n/a | nur in **neuer** DB; alte DB nicht beruehrt |
| `attempt`         | `envelope.attempt` (>=1) | n/a (Pflicht) | `EnvelopeFieldError` falls Worker es weglaesst | fail-closed bei `INSERT` ohne Wert |
| `producer_type`   | `envelope.producer.type` (StrEnum-Wert) | n/a (Pflicht) | `ProducerNotRegisteredError`/`EnvelopeFieldError` | fail-closed bei `INSERT` ohne Wert |
| `producer_id`     | `envelope.producer.id` | n/a (Pflicht) | `EnvelopeFieldError` | fail-closed |
| `producer_version`| `envelope.producer.version` (optional) | `NULL` | n/a | fail-closed nicht noetig |
| `started_at`      | `envelope.started_at` (UTC TIMESTAMPTZ) | n/a (Pflicht) | `EnvelopeFieldError` | fail-closed |
| `finished_at`     | `envelope.finished_at` (UTC TIMESTAMPTZ, >= `started_at`) | n/a (Pflicht) | `EnvelopeFieldError` | fail-closed |
| `status`          | `envelope.status` (`EnvelopeStatus`) | n/a (Pflicht) | `EnvelopeFieldError` falls Status nicht in `{PASS, FAIL, WARN, ERROR}` | fail-closed |
| `artifact_class`  | `envelope.artifact_class` (`ArtifactClass`) | n/a (Pflicht) | `EnvelopeFieldError` falls Wire-Wert nicht in CHECK-Constraint-Liste | fail-closed |
| `payload_json`    | `envelope.payload` (optional) | `NULL` | n/a | fail-closed nicht noetig |

**Greenfield-Lesart**: Da AK3 noch keine produktiven Bestandsdaten kennt, wird die Migration als **leere neue DB** unter neuer `SCHEMA_VERSION` realisiert. Alt-DB-Dateien werden weder gelesen noch projiziert. Existieren in einer Entwickler-Umgebung Alt-Daten unter alter `SCHEMA_VERSION`, bleiben sie unter dem alten Pfad/Schema liegen — der Worker dieser Story sorgt nicht fuer Daten-Uebernahme. Eine spaetere Transfer-Story (siehe FK-18 §18.9a.4) kann das nachholen.

**Alt-Daten unter alter `SCHEMA_VERSION` bleiben unbearbeitet** — kein Read-mit-Default, kein Best-Effort-Projection. Wer Alt-Daten lesen will, bootet AK3 explizit auf der alten Versions-Kennung (FK-18 §18.9a.3).

##### 2.1.4.2 Idempotenz und Re-Run-Safety (Codex-Befund 2)

Die Migrations-Logik (DB-Bootstrap unter neuer `SCHEMA_VERSION`) muss **idempotent re-runnable** sein. Konkret:

**SQLite** (`agentkit_X_Y_Z.sqlite`-Datei pro Version):
- Erste Ausfuehrung: legt Datei mit allen Tabellen und Constraints an.
- Erneute Ausfuehrung mit existierender Datei: `CREATE TABLE IF NOT EXISTS ...`-Pattern; existierende Schema-Definitionen werden nicht erneut erzwungen — wenn das `CREATE`-DDL mit dem existierenden Schema kollidiert (z.B. CHECK-Constraint geaendert), wird die Datei als **inkonsistent** angesehen und Bootstrap schlaegt mit `SchemaIntegrityError` fehl. Recovery: Datei manuell loeschen, Worker re-runnt -> neue Datei.
- Partial-Run (Bootstrap-Crash zwischen `CREATE TABLE` und `CREATE INDEX`): Re-Run findet die Tabelle, legt nur fehlenden Index an. Index-DDL nutzt `CREATE INDEX IF NOT EXISTS`.

**Postgres** (`ak3_vX_Y_Z`-Schema pro Version):
- Erste Ausfuehrung: `CREATE SCHEMA IF NOT EXISTS ak3_vX_Y_Z; SET search_path TO ak3_vX_Y_Z; CREATE TABLE artifact_records (...);`.
- Erneute Ausfuehrung: `CREATE TABLE IF NOT EXISTS` — bei Definitions-Drift schlaegt Bootstrap mit `SchemaIntegrityError` fehl (analog SQLite).
- Partial-Run mit teilweise erzeugten Tabellen/Indexen: `CREATE TABLE IF NOT EXISTS` und `CREATE INDEX IF NOT EXISTS` schliessen Luecken; bestehende Tabellen werden nicht angefasst.
- CHECK-Constraints werden nur bei initialer Tabellen-Anlage gesetzt; eine spaetere Aenderung erfordert Version-Bump (FK-18 §18.9a.1: "Innerhalb einer Major-Version sind Schema-Aenderungen tabu").

**Re-Run-Tests**:
- Bootstrap zweimal hintereinander auf gleicher leerer Working-Dir: zweite Ausfuehrung muss erfolgreich ohne Fehler durchlaufen, keine Duplikate.
- Bootstrap auf Working-Dir mit alter DB (alte Versions-Kennung): alte DB bleibt unangetastet, neue DB wird daneben angelegt.
- Tests laufen einmal pro Treiber (SQLite + Postgres).

#### 2.1.5 Protected-Path-Liste verschieben (artifacts.C2, Codex-Befund 3)

Aktuelle Konstanten in `state_backend/paths.py`:
- `PROTECTED_QA_ARTIFACTS`
- `LAYER_ARTIFACT_FILES`
- `VERIFY_DECISION_FILE`

##### 2.1.5.1 Ziel-Modul (FK-31 + bc-cut-decisions §BC 4)

Konzept-Quelle:
- `FK-31 §31.3` (`concept/technical-design/31_branch_guard_orchestrator_guard_artefaktschutz.md`, Z. 420-487) — `qa-artifact-protection` Hook ist Teil des GuardSystem.
- `concept/_meta/bc-cut-decisions.md §BC 4 governance-and-guards` (Z. 285-338) — Modul-Pfad `agentkit.backend.governance.guard_system`; refactor-Liste Pkt. 24 (Z. 1900): "PROTECTED_ARTIFACTS-Liste gehoert zur Hook-Konfiguration in BC 4 (governance.guard_system), nicht zu artifacts".

**Verbindliches Zielmodul**: `src/agentkit/governance/guard_system/protected_paths.py`.

Begruendung: die Konstanten sind Hook-Konfiguration des QA-Artefakt-Schutzes (FK-31 §31.3); BC-Cut §BC 4 setzt das Sub `GuardSystem` unter `agentkit.backend.governance.guard_system`. Damit liegt `protected_paths.py` als Datei in genau diesem Sub. **Nicht** in `src/agentkit/governance/protected_paths.py` (BC-Top-Level — zu hoch) und **nicht** in `src/agentkit/governance/guards/artifact_guard.py` (das ist der Konsument, nicht der Owner der Liste).

Ueblicher Importpfad nach der Migration:
```python
from agentkit.backend.governance.guard_system.protected_paths import (
    PROTECTED_QA_ARTIFACTS,
    LAYER_ARTIFACT_FILES,
    VERIFY_DECISION_FILE,
)
```

##### 2.1.5.2 Re-Export-Verbot am Alt-Ort

- `state_backend/paths.py` exportiert die drei Konstanten **nicht** mehr (Zero Debt; kein Deprecation-Shim).
- Auch **kein** Re-Export aus `agentkit.backend.governance.__init__` oder `agentkit.backend.governance.protected_paths` (BC-Top-Level) — die einzige kanonische Importquelle ist `agentkit.backend.governance.guard_system.protected_paths`.
- Importer `governance/guards/artifact_guard.py` wird auf den neuen Pfad umgestellt.
- Ein neuer Test in `tests/unit/governance/test_protected_paths_no_legacy_reexport.py` verifiziert, dass:
  - `from agentkit.backend.state_backend.paths import PROTECTED_QA_ARTIFACTS` einen `ImportError` wirft;
  - `from agentkit.backend.governance.protected_paths import PROTECTED_QA_ARTIFACTS` einen `ImportError` wirft (kein BC-Top-Level Re-Export);
  - `from agentkit.backend.governance.guard_system.protected_paths import PROTECTED_QA_ARTIFACTS` erfolgreich ist.

##### 2.1.5.3 Alle Importer umstellen

- `governance/guards/artifact_guard.py` -> direkter Import aus dem neuen Pfad.
- Hook-Module (falls vorhanden, z.B. `agentkit.backend.governance.hooks.qa_artifact_lock_hook`) -> direkter Import.
- Tests, die heute Pfadlisten verwenden -> auf neuen Pfad.
- Suchpfad fuer den Worker: `grep -rn "state_backend.paths" src/` und `grep -rn "PROTECTED_QA_ARTIFACTS\|LAYER_ARTIFACT_FILES\|VERIFY_DECISION_FILE" src/ tests/`.

#### 2.1.6 ProducerRegistry-Seeds fuer Verify-System (Codex-Befund 4)

##### 2.1.6.1 Init-Hook-Variante (verbindlich)

Variantenwahl: **`register_verify_producers(registry: ProducerRegistry)`-Funktion in `src/agentkit/verify_system/register.py`** (neue Datei, nicht `__init__.py`). Begruendung: das verify_system-Paket bekommt eine eigene `register.py` als Init-Hook; `__init__.py` bleibt thin und enthaelt nur Re-Exports. Konsistent mit dem AK3-Schnitt "kein operativer Code in `__init__.py`".

```python
# src/agentkit/verify_system/register.py
from agentkit.backend.artifacts import ProducerRegistry, ProducerType
from agentkit.backend.core_types import ArtifactClass


def register_verify_producers(registry: ProducerRegistry) -> None:
    """Registriert die vier QA-Layer-Producer des verify-systems.

    Wird im Composition-Root (App-Bootstrap) **einmalig** aufgerufen,
    bevor irgendein Pipeline-Run startet. Re-Run ist idempotent
    (Registry.register ueberschreibt Same-Key-Eintrag oder ignoriert
    Re-Registrierung — siehe AG3-022 §2.1.5.1 Init-Strategie).
    """
    registry.register(ArtifactClass.QA, "verify-system.layer-1-structural", ProducerType.DETERMINISTIC)
    registry.register(ArtifactClass.QA, "verify-system.layer-2-llm", ProducerType.LLM_REVIEWER)
    registry.register(ArtifactClass.QA, "verify-system.layer-3-adversarial", ProducerType.LLM_REVIEWER)
    registry.register(ArtifactClass.QA, "verify-system.layer-4-policy", ProducerType.DETERMINISTIC)
```

Konzept-Begruendung der vier Producer:
- `layer-1-structural` -> deterministische Strukturchecks (FK-27 §27.4 — Schicht 1).
- `layer-2-llm` -> LLM-Reviews (FK-27 §27.5 — Schicht 2: QA-Review/Semantic Review/Doc-Fidelity).
- `layer-3-adversarial` -> Adversarial-Agent-Tests (FK-27 §27.6 — Schicht 3).
- `layer-4-policy` -> Policy-Engine (FK-27 §27.7 — Schicht 4, deterministische Aggregation).

##### 2.1.6.2 Composition-Root-Aufruf

Registry-Instanz wird **Singleton im Composition-Root** (App-Bootstrap) angelegt; verify-system konsumiert sie via Dependency-Injection (Konstruktor-Parameter, kein Modul-Globale).

- Falls `src/agentkit/bootstrap/` bereits existiert: `bootstrap/composition_root.py` ruft `register_verify_producers(registry)` direkt nach der Registry-Instanziierung auf.
- Falls `bootstrap/` noch nicht existiert: neue Datei `src/agentkit/bootstrap/composition_root.py` mit Funktion `build_producer_registry() -> ProducerRegistry`, die `ProducerRegistry()` erzeugt und alle bekannten BC-Init-Hooks (in dieser Story: nur `register_verify_producers`) ruft.
- **Kein** Modul-Import-Side-Effect-Hook (`__init__.py`-Magic) — der Aufruf ist explizit im Bootstrap.

##### 2.1.6.3 Test-Fixture-Strategie

Tests, die einen ArtifactManager mit registrierten Verify-Producern brauchen, verwenden eine **lokale Test-Fixture** unter `tests/conftest.py` oder `tests/integration/conftest.py`:

```python
@pytest.fixture
def verify_registry() -> ProducerRegistry:
    registry = ProducerRegistry()
    register_verify_producers(registry)
    return registry
```

Keine globalen Test-Singletons; jede Test-Funktion baut die Registry frisch (oder per Pytest-Fixture-Scope `function`/`module`). Damit ist die Test-Isolation gewaehrleistet.

#### 2.1.7 Tests

- Unit-Tests fuer `ArtifactManager.write/read/exists` (happy + Validation-Fehler)
- Unit-Tests fuer `ArtifactRepository`-Implementierungen (SQLite + Postgres parametrisiert, analog AG3-014/AG3-020)
- Migration-Tests: `write_layer_artifacts` ueber Manager — Roundtrip mit Envelope-Pflichtfeldern verifiziert; alte Aufrufer-API (Signaturen) bleibt rueckwaertskompatibel
- Schema-Migration-Test: alter DB-Schema-Stand wird sauber migriert (idempotent re-runnable, FK-18 §18.9a)
- Test fuer Verschieben der Protected-Path-Listen: `governance/protected_paths.py` exportiert die drei Konstanten; ein neuer Import in `state_backend/paths.py` existiert nicht mehr
- Integration-Test (Pipeline-Slice): ein verify-system-Lauf schreibt vier Layer-Artefakte ueber den ArtifactManager; alle vier sind via `read` wieder lesbar

### 2.2 Out of Scope

- IntegrityGate-Erweiterung fuer Envelope-Pflichtfeld-Pruefung (`artifacts.B4`) — gehoert zu THEME-006 (AG3-034). Diese Story stellt sicher, dass Envelopes korrekt geschrieben werden; das Gate liest sie spaeter.
- ARE-Bundle-Persistenz via ArtifactManager — Folge-Story der RequirementsCoverage-Welle
- AuditRecord-Persistenz fuer PromptRuntime — Folge-Story zu AG3-015 (Prompt-Runtime hat das Audit-Datenmodell)
- Handover-Artefakt-Persistenz vom Worker — gehoert zu THEME-009 (AG3-044 Worker-Loop+Manifest)
- Telemetrie-Envelope-Integration (Telemetry-Artefakte als eigene Class) — gehoert zu THEME-007
- Migration aller anderen Artefaktklassen (ENTWURF, GOVERNANCE, ADVERSARIAL_TEST_SANDBOX) — sobald ihre BCs Schreibzugriff bekommen
- Producer-Registry-Seeds fuer andere BCs als verify-system — wandern in die jeweiligen BC-Top-Surface-Stories der THEME-005

## 3. Betroffene Dateien

| Datei | Aenderungsart | Beschreibung |
|---|---|---|
| `src/agentkit/artifacts/manager.py` | Neu | `ArtifactManager` mit write/read/exists |
| `src/agentkit/artifacts/repository.py` | Neu | `ArtifactRepository`-Protocol |
| `src/agentkit/artifacts/__init__.py` | Modifiziert | Re-Export `ArtifactManager`, `ArtifactRepository`, `ArtifactNotFoundError` |
| `src/agentkit/artifacts/errors.py` | Modifiziert | `ArtifactNotFoundError` ergaenzen |
| `src/agentkit/state_backend/store/artifact_repository.py` | Neu | SQLite/Postgres-Implementierung |
| `src/agentkit/state_backend/postgres_schema.sql` | Modifiziert | Erweiterte Envelope-Spalten |
| `src/agentkit/state_backend/sqlite_store.py` | Modifiziert | Schema-Erweiterung |
| `src/agentkit/state_backend/config.py` | Modifiziert | `SCHEMA_VERSION`-Bump (AG3-005-Mechanik); Modul-Docstring klaert Unterscheidung zu `ENVELOPE_SCHEMA_VERSION` |
| `src/agentkit/state_backend/postgres_store.py` | Modifiziert | `_artifact_class_for`-Heuristik entfernen; artifact_class kommt aus Envelope |
| `src/agentkit/state_backend/paths.py` | Modifiziert | Konstanten `PROTECTED_QA_ARTIFACTS`, `LAYER_ARTIFACT_FILES`, `VERIFY_DECISION_FILE` entfernen (kein Re-Export-Shim) |
| `src/agentkit/governance/guard_system/protected_paths.py` | Neu | Konstanten verschoben hierhin (FK-31 §31.3 + bc-cut §BC 4); kanonischer Ort |
| `src/agentkit/governance/guards/artifact_guard.py` | Modifiziert | Import aus `governance.guard_system.protected_paths` |
| `src/agentkit/verify_system/artifacts.py` | Modifiziert | Wird zu Manager-Konsument; baut Envelope mit allen Pflichtfeldern |
| `src/agentkit/verify_system/policy_engine/projections.py` | Modifiziert | `serialize_layer_result`/`build_verify_decision_artifact` setzen Envelope-Pflichtfelder |
| `src/agentkit/verify_system/register.py` | Neu | `register_verify_producers(registry)` — vier QA-Layer-Producer (Init-Hook-Variante) |
| `src/agentkit/verify_system/__init__.py` | Modifiziert | thin: nur Re-Exports; **kein** Import-Side-Effect-Aufruf von `register_verify_producers` |
| `src/agentkit/bootstrap/composition_root.py` | Neu oder Modifiziert | `build_producer_registry()` ruft `register_verify_producers(registry)` explizit; falls Datei noch nicht existiert -> Neu, sonst Modifiziert |
| `tests/unit/artifacts/test_manager.py` | Neu | write/read/exists + Validation-Fehler |
| `tests/unit/state_backend/store/test_artifact_repository.py` | Neu | parametrisiert SQLite + Postgres |
| `tests/unit/verify_system/test_artifacts.py` | Modifiziert | Manager-Roundtrip statt direkter File-IO |
| `tests/unit/governance/test_protected_paths.py` | Neu | Konstanten korrekt verschoben — Import nur aus `governance.guard_system.protected_paths` erfolgreich |
| `tests/unit/governance/test_protected_paths_no_legacy_reexport.py` | Neu | Alt-Importe `state_backend.paths`, `governance.protected_paths` werfen `ImportError` |
| `tests/unit/state_backend/store/test_artifact_schema_bootstrap_idempotent.py` | Neu | Re-Run-Safety SQLite + Postgres (siehe 2.1.4.2) |
| `tests/unit/verify_system/test_register_verify_producers.py` | Neu | `register_verify_producers` registriert vier Producer; Re-Run ist idempotent |
| `tests/integration/pipeline/test_qa_artifact_roundtrip.py` | Neu | end-to-end: verify-system schreibt vier Layer; alle lesbar |

## 4. Akzeptanzkriterien

1. **`ArtifactManager` existiert** in `src/agentkit/artifacts/manager.py` mit Methoden `write`, `read`, `exists`. Konstruktor nimmt `ArtifactRepository` und `EnvelopeValidator` als Dependencies.
2. **`ArtifactRepository` ist Protocol** und hat zwei Implementierungen (SQLite, Postgres) unter `state_backend/store/artifact_repository.py`. Parametrisierte Tests laufen auf beiden Backends.
3. **`ArtifactManager.write` validiert** vor Persistenz; ungueltige Envelopes (falscher Producer, falsches Status-Mapping, fehlende Pflichtfelder) werden mit den Exceptions aus AG3-022 abgewiesen. Keine partiellen Writes.
4. **`ArtifactManager.read` liefert `ArtifactEnvelope`**; bei Nicht-Existenz wird `ArtifactNotFoundError` geworfen.
5. **`verify_system/artifacts.py` baut Envelopes mit allen Pflichtfeldern** (`schema_version="3.0"`, `story_id`, `run_id`, `stage`, `attempt`, `producer`, `started_at`, `finished_at`, `status`, `artifact_class=QA`). Aufrufer-API der drei Funktionen bleibt rueckwaertskompatibel.
6. **`Producer`-Registrierung fuer verify-system** ist vorhanden: vier Producer (`layer-1-structural`, `layer-2-llm`, `layer-3-adversarial`, `layer-4-policy`) sind in der Registry bekannt; jede QA-Artefakt-Persistenz waehlt einen davon.
7. **Schema-Migration**: `state_backend/postgres_schema.sql` und SQLite-Schema enthalten die erweiterten Envelope-Spalten gemaess 2.1.4 (Backfill-Regeln 2.1.4.1, Idempotenz 2.1.4.2). Bootstrap ist idempotent re-runnable nach FK-18 §18.9a-Mechanik (Side-by-Side-DB pro `SCHEMA_VERSION`). Alte DB-Stand unter alter Versions-Kennung bleibt unangetastet. Postgres `CHECK`-Constraint auf `artifact_class IN ('worker', 'qa', 'pipeline', 'telemetry', 'governance', 'entwurf', 'handover', 'adversarial_test_sandbox')`.
8. **`_artifact_class_for`-Heuristik entfernt**: artifact_class wird aus Envelope direkt persistiert. Tests bestaetigen, dass alle acht Klassen schreib- und lesbar sind.
9. **Konstanten verschoben**: `PROTECTED_QA_ARTIFACTS`, `LAYER_ARTIFACT_FILES`, `VERIFY_DECISION_FILE` leben **ausschliesslich** in `agentkit.backend.governance.guard_system.protected_paths` (siehe 2.1.5.1). `state_backend/paths.py` und `agentkit.backend.governance.protected_paths` (BC-Top-Level) exportieren sie nicht; alle Importer wurden umgestellt; Re-Export-Verbot durch Test 2.1.5.2 abgesichert.
10. **`governance/guards/artifact_guard.py`** importiert aus `governance.guard_system.protected_paths`. Tests des ArtifactGuards laufen unveraendert.
11. **Integration-Test** beweist, dass ein verify-system-Lauf vier Layer-Artefakte schreibt und liest, alle mit korrekten Envelope-Pflichtfeldern.
12. **Architecture-Conformance**: `agentkit.backend.artifacts` darf nicht von `agentkit.backend.state_backend` importieren (nur das umgekehrte ist erlaubt via Protocol-Dependency-Injection). `verify_system` darf nicht direkt `state_backend.store` als Persistenz-Facade verwenden — nur ueber `ArtifactManager`.
13. **Producer-Registrierung explizit im Composition-Root** (kein `__init__.py`-Side-Effect): `bootstrap/composition_root.build_producer_registry()` ruft `register_verify_producers(registry)`. Re-Run der Registry-Bootstrap-Funktion ist idempotent (zweiter Aufruf wirft keinen Fehler).
14. **Pflichtbefehle gruen**: pytest unit + integration + contract; mypy --strict; ruff clean; Coverage haelt 85%.

## 5. Definition of Done

- AK 1-14 erfuellt.
- `.venv\Scripts\python -m pytest tests/unit/artifacts tests/unit/verify_system tests/unit/governance tests/integration -q` gruen.
- `mypy --strict` gruen, `ruff check src tests` gruen.
- SQLite **und** Postgres-Schema migriert (parametrisierte Repository-Tests laufen auf beiden).
- `scripts/ci/check_architecture_conformance.py` und `check_concept_code_contracts.py` gruen.
- Aenderungen committed auf `main` (Story-Status-Commit als Folgecommit).

## 6. Konzept-Referenzen (autoritativ, mit `rel_path`)

- **FK-71 §71.2** — `concept/technical-design/71_artefakt_envelope_und_stage_registry.md` (Z. 109-181) — Envelope-Pflichtfelder, ArtifactManager-Vertrag
- **`concept/_meta/bc-cut-decisions.md §BC 8 artifacts`** — Z. 715-770 — ArtifactManager als Top-Surface
- **`concept/_meta/bc-cut-decisions.md §BC 4 governance-and-guards`** — Z. 285-338 — `agentkit.backend.governance.guard_system`-Modul-Pfad fuer Protected-Path-Listen; refactor-Liste Pkt. 24 (Z. 1900)
- **FK-18 §18.9a** — `concept/technical-design/18_relationales_abbildungsmodell_postgres.md` (Z. 428-507) — Schema-Versionierung (Side-by-Side-DBs)
- **FK-31 §31.3** — `concept/technical-design/31_branch_guard_orchestrator_guard_artefaktschutz.md` (Z. 420-487) — QA-Artefakt-Schutz; Protected-Path-Listen als Hook-Konfiguration im GuardSystem
- **FK-27 §27.4-§27.7** — `concept/technical-design/27_verify_pipeline_closure_orchestration.md` — Layer-1/2/3/4 Begruendung der vier verify-system-Producer (siehe 2.1.6.1)
- **AG3-022 §2.1.5.1** — `stories/AG3-022-artifact-envelope-registry/story.md` — Producer-Registry-Init-Strategie (leere Registry, Klassen-Seed, LLM-Mapping)

## 7. Guardrail-Referenzen

- **FIX THE MODEL, NOT THE SYMPTOM**: BC-Grenze zwischen verify-system und artifacts klar gezogen; QA-Persistenz wandert in den richtigen BC.
- **ZERO DEBT**: keine Deprecation-Re-Exports der Protected-Path-Listen aus `state_backend/paths.py`.
- **FAIL CLOSED**: ArtifactManager schreibt nur valide Envelopes; Repository-Implementierung lehnt Half-State ab.
- **SINGLE SOURCE OF TRUTH**: artifact_class kommt aus dem Envelope, nicht aus einer Heuristik.
- **NO ERROR BYPASSING**: kein direkter Fassaden-Import von `state_backend.store` aus `verify_system` — Pflicht ueber ArtifactManager.

## 8. Hinweise fuer den Sub-Agent

- Pydantic v2: bestehende `frozen=True`-Modelle aus AG3-022 muessen unveraendert bleiben.
- Schema-Bootstrap nach FK-18 §18.9a-Mechanik: neue `SCHEMA_VERSION` -> neue DB unter neuer Versions-Kennung (`agentkit_X_Y_Z.sqlite` bzw. Postgres-Schema `ak3_vX_Y_Z`). Nicht `ALTER TABLE` auf der alten DB — alte DB bleibt unangetastet. Re-Run-Safety durch `CREATE TABLE IF NOT EXISTS` und `CREATE INDEX IF NOT EXISTS`; bei Definitions-Drift hartes Fail mit `SchemaIntegrityError`. Details siehe 2.1.4.2.
- Composition-Root: ProducerRegistry als Singleton. Wenn das App-Bootstrap-Layer noch nicht existiert, lege ein neues `agentkit.backend.bootstrap`-Modul (separat von `installer/`) an. Test-Fixtures bauen Registry pro Test frisch (siehe 2.1.6.3); Produktivcode nutzt den Composition-Root-Singleton (siehe 2.1.6.2).
- Performance: write ist Pfad-kritisch (jede QA-Runde schreibt mehrere Envelopes). Pruefe, dass kein zusaetzliches Roundtrip-Read auf `write` passiert.
- AK2 (`T:/codebase/claude-agentkit/`) NICHT veraendern.
