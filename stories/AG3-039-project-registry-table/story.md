# AG3-039: project_registry-Tabelle + ProjectRegistration-Entitaet + Installer-CP-7

**Typ:** Implementation
**Groesse:** M
**Abhaengigkeiten:** AG3-021 (Enums)
**Quell-Konzepte (autoritativ, in dieser Reihenfolge):**
- `FK-50 §50.3 CP 7` (State-Backend-Registrierung)
- `FK-50 §50.4` (CheckpointResult)
- `formal.installer.entities §installer.entity.project-registration`
- `formal.installer.invariants §installer.invariant.register_project_is_idempotent`
- `concept/_meta/bc-cut-decisions.md §BC 12 installation-and-bootstrap`

---

## 1. Kontext

THEME-008 aus `stories/_priorisierungsempfehlung.md`. Befund `installation-and-bootstrap.A2`: `project_registry`-Tabelle und `ProjectRegistration`-Entitaet fehlen.

Diese Story liefert die Persistenz fuer Checkpoint 7 (`FK-50 §50.3 CP 7`). Volle Checkpoint-Engine (`installation-and-bootstrap.A1`) und CLI-Refactor (`A5/A6/C1`) sind bewusst nicht in der Erst-Welle (Priorisierungsempfehlung §5).

## 2. Scope

### 2.1 In Scope

#### 2.1.1 Tabelle `project_registry` (FK-50 §50.3 CP 7)

`src/agentkit/state_backend/postgres_schema.sql` und SQLite-Analog:

```sql
CREATE TABLE IF NOT EXISTS project_registry (
    project_key VARCHAR PRIMARY KEY,
    project_root VARCHAR NOT NULL,
    github_owner VARCHAR NOT NULL,
    github_repo VARCHAR NOT NULL,
    runtime_profile VARCHAR NOT NULL,    -- core | are
    config_version VARCHAR NOT NULL,
    config_digest VARCHAR NOT NULL,
    registered_at TIMESTAMPTZ NOT NULL,
    last_verified_at TIMESTAMPTZ NULL,
    last_upgraded_at TIMESTAMPTZ NULL,
    UNIQUE (project_root)
);
```

CHECK-Constraint auf `runtime_profile IN ('core', 'are')`.

Schema-Versionierung Side-by-Side (AG3-005).

#### 2.1.2 `ProjectRegistration`-Pydantic-Modell

`src/agentkit/installer/registration.py`:

```python
class ProjectRegistration(BaseModel):
    project_key: str
    project_root: Path
    github_owner: str
    github_repo: str
    runtime_profile: RuntimeProfile        # StrEnum: CORE | ARE
    config_version: str
    config_digest: str
    registered_at: datetime
    last_verified_at: datetime | None
    last_upgraded_at: datetime | None
    model_config = ConfigDict(frozen=True, extra="forbid")
```

#### 2.1.3 `ProjectRegistrationRepository`

`src/agentkit/installer/repository.py`:

```python
class ProjectRegistrationRepository(Protocol):
    def get(self, project_key: str) -> ProjectRegistration | None: ...
    def save(self, registration: ProjectRegistration) -> None: ...
    def update_verified(self, project_key: str, verified_at: datetime) -> None: ...
    def update_upgraded(self, project_key: str, upgraded_at: datetime, new_digest: str) -> None: ...
    def list_all(self) -> list[ProjectRegistration]: ...
```

Konkrete Implementierung in `state_backend/store/project_registration_repository.py` (SQLite + Postgres).

#### 2.1.4 Installer-Anschluss

`src/agentkit/installer/runner.py:install_agentkit`:
- Nach dem Erstellen von `project.yaml` und vor dem Schreiben anderer Artefakte: Lookup gegen `ProjectRegistrationRepository.get(project_key)`.
- Idempotenz (`formal.installer.invariants §register_project_is_idempotent`): wenn `ProjectRegistration` existiert mit gleichem `config_digest` -> `CheckpointResult.SKIPPED` fuer CP 7
- Wenn `config_digest` abweicht -> `update_upgraded`
- Wenn nicht existiert -> `save`

Diese Story bringt **nicht** das volle Checkpoint-Schema (alle 12 Checkpoints) — siehe Out of Scope. Aber CP 7 ist als Aufruf-Pfad implementiert; das ist eigenstaendig pruefbar.

#### 2.1.5 `CheckpointResult`-Typisierung (FK-50 §50.4)

Diese Story liefert nicht die volle Checkpoint-Engine, aber das Type-Skelett:

```python
class CheckpointStatus(StrEnum):
    PASS = "pass"
    CREATED = "created"
    UPDATED = "updated"
    SKIPPED = "skipped"
    FAILED = "failed"

class CheckpointResult(BaseModel):
    checkpoint: str
    status: CheckpointStatus
    detail: str | None
    duration_ms: int
    model_config = ConfigDict(frozen=True, extra="forbid")
```

`InstallResult` (aus `installer/runner.py`) wird erweitert um `checkpoint_results: list[CheckpointResult] | None`. Wenn die volle Checkpoint-Engine in der Folge-Story kommt, wird das Feld typisiert befuellt; jetzt nur fuer CP 7.

#### 2.1.6 Tests

- Unit-Tests fuer `ProjectRegistration`-Modell (Pflicht-Felder, Validators)
- Unit-Tests fuer `ProjectRegistrationRepository` (CRUD, parametrisiert SQLite + Postgres)
- Idempotenz-Test: Installer doppelt aufgerufen mit gleichem config_digest -> Repository wird nicht gemutiert; Aufruf liefert `CheckpointResult.SKIPPED` fuer CP 7
- Upgrade-Test: anderer config_digest -> Repository wird mit `last_upgraded_at` aktualisiert
- Integration-Test: Installer-Lauf -> `ProjectRegistration` ist in Repository persistiert mit korrekten Feldern

### 2.2 Out of Scope

- Vollstaendige Checkpoint-Engine mit 12 Checkpoints (`installation-and-bootstrap.A1`) — bewusst nicht in der Erst-Welle (Priorisierungsempfehlung §5)
- Dry-Run-Modus (`A4`) — Folge-Story
- CLI `agentkit register-project`/`verify-project` (`A5/A6`) — explizit "spaetere Iteration"
- Formale State-Machine (`A7`) — Folge-Story
- Event-Emission (`A8`) — Folge-Story (Installer-Events)
- GitHub-Repo-Pruefung (`A9`) — Folge-Story
- Projektprofil-Ermittlung CP 6 (`A10`) — Folge-Story
- Customization-Preservation FK-51 — explizit "spaetere Iteration"
- Config-Migration FK-51 §51.4 — Folge-Story

## 3. Betroffene Dateien

| Datei | Aenderungsart | Beschreibung |
|---|---|---|
| `src/agentkit/installer/registration.py` | Neu | `ProjectRegistration`, `RuntimeProfile`-StrEnum, `CheckpointStatus`, `CheckpointResult` |
| `src/agentkit/installer/repository.py` | Neu | `ProjectRegistrationRepository`-Protocol |
| `src/agentkit/installer/runner.py` | Modifiziert | CP 7 Anschluss; `InstallResult.checkpoint_results` |
| `src/agentkit/state_backend/store/project_registration_repository.py` | Neu | SQLite/Postgres-Impl |
| `src/agentkit/state_backend/postgres_schema.sql` | Modifiziert | Tabelle `project_registry` |
| `src/agentkit/state_backend/sqlite_store.py` | Modifiziert | analog SQLite |
| `src/agentkit/state_backend/config.py` | Modifiziert | SCHEMA_VERSION-Bump |
| `tests/unit/installer/test_registration.py` | Neu | Modell + Idempotenz |
| `tests/unit/state_backend/store/test_project_registration_repository.py` | Neu | CRUD parametrisiert |
| `tests/integration/installer/test_register_project.py` | Neu | E2E Installer-Lauf |

## 4. Akzeptanzkriterien

1. **Tabelle `project_registry`** existiert in SQLite + Postgres mit den Spalten aus 2.1.1.
2. **`ProjectRegistration`-Pydantic-Modell** existiert mit allen Pflicht-Feldern (frozen, extra forbid).
3. **`ProjectRegistrationRepository`** mit den fuenf Methoden ist implementiert (Protocol + SQLite/Postgres-Impl).
4. **Idempotenz**: Installer doppelt mit gleichem `config_digest` liefert `CheckpointResult.SKIPPED` fuer CP 7; Repository wird nicht erneut geschrieben.
5. **Upgrade-Pfad**: anderer `config_digest` -> `last_upgraded_at` aktualisiert.
6. **`CheckpointResult` und `CheckpointStatus`** sind typisiert verfuegbar.
7. **`InstallResult.checkpoint_results`** enthaelt mindestens einen Eintrag (fuer CP 7) nach einem Installer-Lauf.
8. **`RuntimeProfile`-StrEnum** mit `CORE`, `ARE`.
9. **Architecture-Conformance**: `agentkit.installer.registration` und `agentkit.installer.repository` halten BC-Grenze; Repository-Implementierung im state_backend.
10. **Pflichtbefehle gruen**: pytest unit + integration; mypy --strict; ruff clean; Coverage haelt 85%.

## 5. Definition of Done

- AK 1-10 erfuellt.
- `.venv\Scripts\python -m pytest tests/unit/installer tests/integration/installer -q` gruen.
- `mypy --strict` gruen, `ruff check src tests` gruen.
- SQLite + Postgres migriert.
- Aenderungen committed auf `main`.

## 6. Konzept-Referenzen (autoritativ)

- **FK-50 §50.3 CP 7** — State-Backend-Registrierung
- **FK-50 §50.4** — CheckpointResult
- **`formal.installer.entities §project-registration`** — Entitaet
- **`formal.installer.invariants §register_project_is_idempotent`** — Idempotenz

## 7. Guardrail-Referenzen

- **FIX THE MODEL, NOT THE SYMPTOM**: kanonische Registrierung statt `project.yaml`-only Wahrheit.
- **ZERO DEBT**: nicht "spaeter Tabelle ergaenzen".
- **FAIL CLOSED**: Idempotenz-Check ist hart; abweichender Digest -> Upgrade-Pfad explizit.

## 8. Hinweise fuer den Sub-Agent

- `config_digest`: SHA-256 ueber kanonisierten `project.yaml`-Inhalt.
- Die volle Checkpoint-Engine ist bewusst nicht in der Erst-Welle; sei vorsichtig, nicht alle 12 Checkpoints einzubauen — Aufgabenfokus ist CP 7.
- AK2 NICHT veraendern.
