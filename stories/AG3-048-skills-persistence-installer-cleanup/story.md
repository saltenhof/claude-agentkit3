# AG3-048: Skills BC -- Persistenz + Installer-Andockung + Repo-Hygiene

<!-- AG3-048 (User-Entscheidung 2026-05-19): Folge-Story zu AG3-027. AG3-027 wurde
auf User-Entscheidung als schlanke Top-Surface (M) geschnitten; die drei BC-fremden
Bereiche (state_backend-Persistenz, installer/runner-Andockung, Repo-Hygiene) sind
hier gebuendelt und greifen erst nachdem AG3-027 die Top-Surface produktiv hat. -->

**Typ:** Implementation
**Groesse:** M
**Abhaengigkeiten:** AG3-027 (Skills-Top-Surface + `SkillBindingRepository`-Protocol + InMemory-Impl)
**Quell-Konzepte (autoritativ, in dieser Reihenfolge):**
- `concept/_meta/bc-cut-decisions.md §BC 11 agent-skills` (Persistenz-Andockung)
- `concept/_meta/bc-cut-decisions.md §BC 12 installation-and-bootstrap` (Installer-Anschluss)
- `concept/domain-design/05-telemetrie-und-metriken.md §5` (kanonische Persistenz **Postgres**, nicht SQLite)
- `FK-43 §43.3.1` (Pflicht-Skills, die der Installer binden muss)
- `FK-43 §43.4.1` (Symlink-Bindungsvertrag, der vom Installer konsumiert wird)
- `FK-18 §18.9a` (Side-by-Side-Schema-Versionierung fuer `skill_bindings`-Tabelle)
- `FK-60 §60` ("SQLite-Varianten verworfen zugunsten klarer Writer-/Reader-Trennung auf PostgreSQL")

> **Persistenz-Konvention (Stefan-Klarstellung 2026-05-24):**
> Postgres ist die kanonische Wahrheit fuer den `skill_bindings`-State. SQLite zieht
> das gleiche Schema parallel mit, aber ausschliesslich als **Test-Pfad** —
> `AGENTKIT_ALLOW_SQLITE=1` ist nur fuer "narrow unit-test execution" freigegeben;
> Runtime/Build/Contract/Integration/E2E werfen `RuntimeError` gemaess
> `state_backend/config.py:_sqlite_allowed`. Wenn im Folgenden "SQLite + Postgres"
> steht, ist immer **Postgres-kanonisch + SQLite-Test-Parallelpfad** gemeint, kein
> gleichberechtigter Dual-Backend-Betrieb.

---

## 1. Kontext

AG3-027 hat die Skills-Top-Surface (`Skills.bind_skill`, `SkillBundleStore`,
`SkillBinding`, `PlaceholderSubstitutor`, `SkillBindingRepository`-Protocol mit
InMemory-Impl) als schlanke M-Story geliefert. Drei Bereiche wurden bewusst
ausgegliedert, weil sie BC-fremde Aenderungen mitbringen und die Top-Surface-Story
auf L aufgeblaeht haetten:

- `skill_bindings`-Tabelle in Postgres (kanonisch) + SQLite (Test-Parallel-Schema) (state_backend-BC)
- `installer/runner.py:install_agentkit` ruft `Skills.bind_skill` (installer-BC,
  BC12)
- `__pycache__`-Artefakte unter `src/agentkit/project_ops/install/` (Repo-Hygiene)

Diese Story buendelt die drei Bereiche und macht die Skills-Persistenz produktiv.

## 2. Scope

### 2.1 In Scope

#### 2.1.1 `skill_bindings`-Tabelle (state_backend-Persistenz)

`src/agentkit/state_backend/store/skill_binding_repository.py` (neu) implementiert
das in AG3-027 definierte `SkillBindingRepository`-Protocol fuer Postgres (kanonisch)
und SQLite (Test-Parallel-Pfad mit identischem Schema, siehe Persistenz-Konvention
oben).

Schema (kanonisch Postgres, identisches DDL in SQLite parallel; FK-18 §18.9a
Side-by-Side -- neuer SCHEMA_VERSION-Bump 3.5.1 -> 3.6.0):

```sql
CREATE TABLE IF NOT EXISTS skill_bindings (
    binding_id      VARCHAR  NOT NULL,
    project_key     VARCHAR  NOT NULL,
    skill_name      VARCHAR  NOT NULL,
    bundle_id       VARCHAR  NOT NULL,
    bundle_version  VARCHAR  NOT NULL,
    target_path     TEXT     NOT NULL,
    binding_mode    VARCHAR  NOT NULL CHECK (binding_mode IN ('SYMLINK')),
    lifecycle_status VARCHAR NOT NULL CHECK (
        lifecycle_status IN ('REQUESTED','BUNDLE_SELECTED','BOUND','VERIFIED')
    ),
    manifest_digest VARCHAR  NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL,
    verified_at     TIMESTAMPTZ NULL,
    PRIMARY KEY (binding_id),
    UNIQUE (project_key, skill_name)
);
CREATE INDEX IF NOT EXISTS idx_skill_bindings_project_skill
    ON skill_bindings (project_key, skill_name);
```

`SCHEMA_VERSION` (`state_backend/config.py`) wird auf `"3.6.0"` gebumpt
(Side-by-Side; alte DB unangetastet, neue DB hat zusaetzlich `skill_bindings`).

#### 2.1.2 `mappers.skill_binding_to_row` / `skill_binding_row_to_record`

`src/agentkit/state_backend/store/mappers.py`: Mapper zwischen `SkillBinding`
(Pydantic-v2-Modell aus AG3-027) und Row-Dict. Datetime-Handhabung analog
`attempt_row_to_record` (FK-18-konform).

#### 2.1.3 `Skills`-Composition-Root

`src/agentkit/bootstrap/composition_root.py:build_skills` (neu, analog
`build_artifact_manager` aus AG3-023):

```python
def build_skills(store_dir: Path) -> Skills:
    repository = StateBackendSkillBindingRepository(store_dir)
    return Skills(
        bundle_store=SkillBundleStore(...),
        binding_repo=repository,
    )
```

Aufrufer (Installer, Tests, runtime) erhalten `Skills` ueber DI.

#### 2.1.4 Installer-Integration (BC12)

`src/agentkit/installer/runner.py:install_agentkit`:

- Aufruf von `Skills.bind_skill` fuer jeden Pflicht-Skill (`FK-43 §43.3.1`:
  `create-userstory`, `execute-userstory`, `lookup-userstory`, `llm-discussion`)
- Profilermittlung (CP6/CP7) erfolgt im Installer **vor** dem `bind_skill`-Aufruf
- Direktes `mkdir(.claude/skills)` im Installer entfaellt
- Multi-Harness: Installer ermittelt aktivierte Harnesses
  (Claude Code, Codex) und ruft `bind_skill` pro Harness
- Fail-closed: Bundle nicht im System-Store -> `InstallationError` mit
  `cause: BundleNotFound`; `bind_skill` wirft -> Installation bricht ab
  (kein partial-install)

#### 2.1.5 Repo-Hygiene: `__pycache__`-Cleanup

`src/agentkit/project_ops/install/__pycache__/` (Verzeichnis ohne Quellcode mit
`skills.cpython-314.pyc`, `skill_variant.cpython-314.pyc`) wird geloescht. Plus
ein einmaliger Pre-Commit-Hook-Check, der solche orphaned `__pycache__`-
Verzeichnisse im src-Tree blockiert (kann als Folge-Story aufgemacht werden, wenn
zu invasiv -- in dieser Story nur einmaliges Loeschen + Doku).

#### 2.1.6 Tests

- `tests/unit/state_backend/store/test_skill_binding_repository.py` -- parametrisierter
  Roundtrip auf Postgres (kanonisch) + SQLite (Test-Parallelpfad), analog
  `test_attempt_repository.py`
- `tests/unit/state_backend/store/test_skill_binding_schema_bootstrap_idempotent.py`
  -- Bootstrap-Idempotenz analog `test_attempt_schema_bootstrap_idempotent.py`
- `tests/integration/installer/test_skills_binding.py` -- Installer ruft
  `Skills.bind_skill` fuer alle Pflicht-Skills; `.claude/skills/`-Symlinks
  existieren, keine Datei-Kopien
- Update der `tests/contract/skills/test_top_surface.py` (aus AG3-027) auf den
  produktiven Persistenz-Pfad (StateBackend-Repo statt InMemory)

### 2.2 Out of Scope

- Skills-Top-Surface selbst (`Skills.bind_skill`, `SkillBundleStore`,
  `PlaceholderSubstitutor`, `SkillBinding`-Modell) -- ist AG3-027.
- `SkillQualityMetric`-Vollausbau -- Folge-Story nach THEME-007.
- Optional-Skills `manage-requirements`, `semantic-review` -- Folge-Story.
- Hook `skill_usage_check` in `governance.guard_system` -- Folge-Story der
  Governance-Welle.

## 3. Betroffene Dateien

| Datei | Aenderungsart | Beschreibung |
|---|---|---|
| `src/agentkit/state_backend/store/skill_binding_repository.py` | Neu | Postgres-kanonische + SQLite-Test-parallele Impl von `SkillBindingRepository` |
| `src/agentkit/state_backend/postgres_schema.sql` | Modifiziert | `skill_bindings`-Tabelle (kanonisch) |
| `src/agentkit/state_backend/sqlite_store.py` | Modifiziert | identisches Parallel-Schema fuer Unit-Tests |
| `src/agentkit/state_backend/store/mappers.py` | Modifiziert | `skill_binding_to_row` / `skill_binding_row_to_record` |
| `src/agentkit/state_backend/config.py` | Modifiziert | `SCHEMA_VERSION` 3.5.1 -> 3.6.0 |
| `src/agentkit/bootstrap/composition_root.py` | Modifiziert | `build_skills(store_dir) -> Skills` |
| `src/agentkit/installer/runner.py` | Modifiziert | `Skills.bind_skill`-Aufruf pro Pflicht-Skill + Harness |
| `src/agentkit/project_ops/install/__pycache__/` | Geloescht | leerer Pyc-Stub entfernen |
| `tests/unit/state_backend/store/test_skill_binding_repository.py` | Neu | Roundtrip SQLite + Postgres |
| `tests/unit/state_backend/store/test_skill_binding_schema_bootstrap_idempotent.py` | Neu | Bootstrap-Idempotenz |
| `tests/integration/installer/test_skills_binding.py` | Neu | Installer-Andockung End-to-End |
| `tests/contract/skills/test_top_surface.py` | Modifiziert | Persistenz-Pfad auf StateBackend-Repo |

## 4. Akzeptanzkriterien

1. **`skill_bindings`-Tabelle existiert** kanonisch in Postgres-Schema `ak3_v3_6_0`
   (mit identischem Parallel-Schema in SQLite fuer Unit-Tests), mit `binding_id`-PK,
   `UNIQUE(project_key, skill_name)`, CHECK-Constraints fuer `binding_mode` und
   `lifecycle_status`, plus Index `idx_skill_bindings_project_skill`.
2. **`SCHEMA_VERSION` ist 3.6.0** (Side-by-Side, FK-18 §18.9a; alte 3.5.1-DB
   unangetastet).
3. **`StateBackendSkillBindingRepository`** implementiert das aus AG3-027 bekannte
   Protocol; Roundtrip-Test laeuft auf Postgres (kanonisch) + SQLite (Test-Parallel)
   parametrisiert (`AGENTKIT_ALLOW_SQLITE=1` nur in Unit-Tests).
4. **`build_skills` Composition-Root** existiert und buendelt
   `SkillBundleStore` + `StateBackendSkillBindingRepository` zu einer
   `Skills`-Instanz.
5. **Installer (`install_agentkit`)** ruft `Skills.bind_skill` fuer alle vier
   Pflicht-Skills aus `FK-43 §43.3.1`. Direktes `mkdir(.claude/skills)` entfaellt.
6. **Multi-Harness-Symlinks**: nach `install_agentkit` existieren Symlinks pro
   aktiviertem Harness (Claude Code + Codex) -- gepruefte via Integration-Test.
7. **Fail-closed-Pfade**: Bundle nicht gefunden -> `InstallationError` mit
   strukturiertem `cause`; partial-install ist verboten (Installer bricht ab
   bevor irgendein Symlink angelegt wird).
8. **`__pycache__`-Cleanup**: `src/agentkit/project_ops/install/__pycache__/`
   existiert nach diesem Commit nicht mehr.
9. **Architecture-Conformance**: `agentkit.installer` darf `agentkit.skills`
   importieren; `agentkit.skills` importiert NICHT aus `installer/`; AC-checks
   gruen.
10. **Pflichtbefehle gruen**: pytest unit + integration + contract; mypy --strict;
    ruff clean; Coverage haelt 85%.

## 5. Definition of Done

- AK 1-10 erfuellt.
- `.venv\Scripts\python -m pytest tests/unit/state_backend/store tests/integration/installer tests/contract/skills -q` gruen.
- `mypy --strict src tests` gruen, `ruff check src tests` gruen.
- Postgres (kanonisch) + SQLite (Test-Parallel-Schema) migriert (Side-by-Side, alte DB unangetastet).
- AG3-027 muss vorher abgenommen sein (Top-Surface produktiv).
- Aenderungen committed auf `main`.

## 6. Konzept-Referenzen (autoritativ)

- **`concept/_meta/bc-cut-decisions.md §BC 11`** -- Skills-BC Persistenz-Andockung
- **`concept/_meta/bc-cut-decisions.md §BC 12`** -- Installer-Andockung
- **FK-43 §43.3.1** -- Pflicht-Skill-Liste
- **FK-43 §43.4.1** -- Symlink-Bindung
- **FK-18 §18.9a** -- Side-by-Side-Schema-Versionierung

## 7. Guardrail-Referenzen

- **FIX THE MODEL, NOT THE SYMPTOM**: Persistenz liegt im state_backend-BC,
  nicht im skills-BC. Installer-Andockung liegt im installer-BC.
- **ZERO DEBT**: keine doppelte Persistenz (InMemory aus AG3-027 wird nur in
  Tests verwendet).
- **FAIL CLOSED**: Installer bricht ab, wenn ein Pflicht-Skill nicht gebunden
  werden kann.
- **SINGLE SOURCE OF TRUTH**: Symlinks statt Datei-Kopien; SkillBundle lebt
  einmal im System-Store.

## 8. Hinweise fuer den Sub-Agent

- Diese Story baut **auf** AG3-027 auf. Wenn AG3-027 noch nicht gemerged ist:
  abbrechen und Auftraggeber melden.
- `mapper.skill_binding_to_row` muss tz-aware `datetime` korrekt persistieren
  (FK-18-Pattern, analog `attempt_record_to_row`).
- Installer-Integration darf nicht silent failen -- ein nicht bindbarer
  Pflicht-Skill ist ein Installationsfehler.
- AK2 NICHT veraendern.
