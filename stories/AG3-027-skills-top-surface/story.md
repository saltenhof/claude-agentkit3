# AG3-027: Skills BC — Top-Komponente Skills + Sub-Klassen

**Typ:** Implementation
**Groesse:** L
**Abhaengigkeiten:** AG3-021 (Enums fuer Status-Felder), AG3-022 (`ArtifactClass`-Bezug fuer Skill-Bundle-Records)
**Quell-Konzepte (autoritativ, in dieser Reihenfolge):**
- `concept/_meta/bc-cut-decisions.md §BC 11 agent-skills`
- `FK-43 §43.1` (Skills-Top-Komponente)
- `FK-43 §43.3.1/43.3.2` (Pflicht-/Optional-Skills)
- `FK-43 §43.4.1` (Symlink-basierte Projekt-Bindung)
- `FK-43 §43.4.2` (PlaceholderSubstitutor)
- `FK-43 §43.5.2` (Skill-Version-Pin)
- `FK-43 §43.6.2` (SkillQualityMetric)
- `formal.skills-and-bundles.entities`
- `formal.skills-and-bundles.state-machine`
- `formal.skills-and-bundles.invariants` (insbesondere `project_binding_is_symlink_only`)

---

## 1. Kontext

THEME-005 aus `stories/_priorisierungsempfehlung.md`. Befunde aus `agent-skills`-GAP-Analyse:

- `agent-skills.A1`: Modul `src/agentkit/skills/` mit Top-Komponente `Skills` und vier Top-Methoden fehlt — der BC ist der einzige der 16 ohne Produktionsmodul.
- `agent-skills.A2-A10`: Sub-Komponenten `SkillBundleStore`, `SkillBinding`, `PlaceholderSubstitutor`, `SkillQualityMetric`, Pflicht-Skills, Optional-Skills, Version-Pin, Invarianten, Governance-Hook, Events — alle nicht implementiert.
- `agent-skills.C1`: Installer erstellt `.claude/skills/` direkt, ohne `Skills.bind_skill` aufzurufen.
- `agent-skills.C2`: `__pycache__`-Artefakte in `src/agentkit/project_ops/install/` ohne Quellcode.

Diese Story liefert den **Kern**: Top-Komponente + zwei Subs (SkillBundleStore, SkillBinding) + PlaceholderSubstitutor + Skill-Lifecycle. `SkillQualityMetric` und Governance-Hook `skill_usage_check` (`agent-skills.A4/A9`) sind separate Folge-Stories (nicht in dieser Erst-Welle), siehe Out of Scope.

## 2. Scope

### 2.1 In Scope

#### 2.1.1 Paket `src/agentkit/skills/`

Neue Modul-Struktur:

- `__init__.py` — Re-Export `Skills`, `SkillBinding`, `SkillBundle`, `SkillBundleVersion`, `SkillBundleStore`, `PlaceholderSubstitutor`, `SkillLifecycleStatus`-StrEnum
- `top.py` — `Skills`-Klasse mit vier Top-Surface-Methoden
- `bundle_store.py` — `SkillBundleStore`, `SkillBundle`, `SkillBundleVersion`, `LogicalSkillId`
- `binding.py` — `SkillBinding`, `SkillLifecycleStatus`
- `placeholder.py` — `PlaceholderSubstitutor`
- `errors.py` — typisierte Exceptions

#### 2.1.2 `Skills`-Top-Klasse (bc-cut-decisions.md §BC 11)

```python
class Skills:
    def __init__(self, bundle_store: SkillBundleStore, binding_repo: SkillBindingRepository, substitutor: PlaceholderSubstitutor) -> None: ...

    def bind_skill(
        self,
        project_root: Path,
        skill_logical_id: LogicalSkillId,
        profile: SkillProfile,
        pipeline_config: PipelineConfig,
    ) -> SkillBinding: ...

    def resolve_binding(self, project_root: Path, skill_logical_id: LogicalSkillId) -> SkillBinding | None: ...

    def list_bound_skills(self, project_root: Path) -> list[SkillBinding]: ...

    def collect_quality_metrics(self, skill_logical_id: LogicalSkillId) -> SkillQualityMetric:
        # Stub: liefert leere SkillQualityMetric; voller Ausbau in Folge-Story
        ...
```

`SkillProfile` ist StrEnum mit den Konzept-Profilen (`CORE`, `ARE`). `LogicalSkillId` ist NewType.

#### 2.1.3 `SkillBundleStore`

Systemweiter, kanonischer Bundle-Store (analog `PromptBundleStore` aus AG3-015):

- `SkillBundle` (Pydantic-v2-Modell): `bundle_id`, `bundle_version`, `bundle_root: Path`, `manifest_digest: str`, `variants: dict[SkillProfile, LogicalSkillId]`
- `SkillBundleStore.get_bundle(bundle_id) -> SkillBundle`
- `SkillBundleStore.resolve_variant(skill_logical_id, profile) -> SkillBundle` — waehlt die passende Bundle-Variante fuer das angegebene Profil
- Default-Pfad: `~/.agentkit/skills/` (systemweit); pro Test kann ein temporaerer Pfad uebergeben werden.

Bundle-Versionierung: `SkillBundleVersion` als Pydantic-Modell mit `version: str`, `pinned_at: datetime`. Eigenstaendig zu PromptBundle (`FK-43 §43.5.2`).

#### 2.1.4 `SkillBinding` mit Skill-Lifecycle (formal.skills-and-bundles.state-machine)

`SkillBinding` ist Pydantic-v2-Modell (frozen, extra forbid):

- `project_key: str`
- `skill_logical_id: LogicalSkillId`
- `profile: SkillProfile`
- `bundle_id: str`
- `bundle_version: str`
- `status: SkillLifecycleStatus`
- `symlink_path: Path` — Pfad innerhalb des Projekts (`.claude/skills/{name}/`)
- `pinned_at: datetime`

`SkillLifecycleStatus` StrEnum mit den Werten aus `formal.skills-and-bundles.state-machine`: `REQUESTED`, `PROFILE_RESOLVED`, `BUNDLE_SELECTED`, `BOUND`, `VERIFIED`, `REJECTED`.

`SkillBindingRepository` Protocol fuer Persistenz. Storage: Tabelle `skill_bindings` in state_backend (siehe 2.1.6).

#### 2.1.5 `PlaceholderSubstitutor` (FK-43 §43.4.2)

```python
class PlaceholderSubstitutor:
    def substitute(self, content: str, pipeline_config: PipelineConfig) -> str:
        # Pflicht-Platzhalter:
        # {{gh_owner}} -> pipeline_config.github_owner
        # {{gh_repo}} -> pipeline_config.github_repo
        # {{project_prefix}} -> pipeline_config.story_id_prefix
        # {{project_key}} -> pipeline_config.project_key
        ...
```

Read-only-Zugriff auf `PipelineConfig`. Bei unbekanntem Platzhalter im Inhalt: fail-closed (`UnknownPlaceholderError`).

#### 2.1.6 Persistenz (SQLite + Postgres)

Neue Tabelle `skill_bindings`:
- `project_key`, `skill_logical_id`, `profile`, `bundle_id`, `bundle_version`, `status`, `symlink_path`, `pinned_at`
- UNIQUE `(project_key, skill_logical_id)`
- Konkrete Repository in `state_backend/store/skill_binding_repository.py`
- Schema-Versionierung Side-by-Side (AG3-005)

#### 2.1.7 `bind_skill`-Mechanik (FK-43 §43.4.1, Invariante `project_binding_is_symlink_only`)

Schritte:
1. Validierung: project_root existiert, profile ist erlaubt fuer skill_logical_id (aus Bundle-Variants-Map)
2. Bundle-Resolution via `SkillBundleStore.resolve_variant`
3. Lifecycle: status -> `REQUESTED` -> `PROFILE_RESOLVED` -> `BUNDLE_SELECTED`
4. Symlink-Erzeugung im Projekt unter `{project_root}/.claude/skills/{skill_logical_id}` zeigt auf Bundle-Root
5. PlaceholderSubstitutor wird **nicht** auf den Bundle-Inhalt angewendet (Invariante `project_binding_is_symlink_only`: kein Kopieren, kein Mutieren); Platzhalter werden **zur Read-Zeit** durch Skill-Konsumenten substituiert. Diese Story bietet aber `PlaceholderSubstitutor` als Service bereit.
6. Lifecycle: `BOUND`. Persistenz via Repository.
7. Verifikation (Symlink existiert, zeigt auf Bundle, Manifest-Digest stimmt): `VERIFIED`.

Fail-closed-Pfade:
- Symlink-Erzeugung schlaegt fehl -> `SkillBindingFailedError` (status bleibt `BUNDLE_SELECTED`, nicht persistiert)
- Bundle-Manifest-Digest mismatch -> `SkillBundleDigestMismatchError`
- Profile passt nicht zu Bundle-Variants -> `SkillProfileNotSupportedError`

#### 2.1.8 Installer-Anschluss (agent-skills.C1)

`src/agentkit/installer/runner.py:install_agentkit`:
- Aufruf von `Skills.bind_skill` fuer jeden Pflicht-Skill (FK-43 §43.3.1 nennt: `create-userstory`, `execute-userstory`, `lookup-userstory`, `llm-discussion` — Profile core/are je nach Projekt-Profil)
- Direktes Anlegen von `.claude/skills/` als leerer Platzhalter entfaellt
- Falls Bundle nicht im System-Store: fail-closed mit Installation-Fehler

#### 2.1.9 Tests

- Unit-Tests fuer `Skills.bind_skill` (happy path, fail-closed-Pfade, Lifecycle-Transitions)
- Unit-Tests fuer `Skills.resolve_binding`, `list_bound_skills`
- Unit-Tests fuer `SkillBundleStore.resolve_variant` (Profil-Variant-Mapping)
- Unit-Tests fuer `PlaceholderSubstitutor` (alle vier Pflicht-Platzhalter + unknown-placeholder fail-closed)
- Unit-Tests fuer `SkillBindingRepository` (parametrisiert SQLite + Postgres)
- Integration-Test: Installer ruft `Skills.bind_skill` fuer alle Pflicht-Skills; `.claude/skills/` enthaelt Symlinks, keine Datei-Kopien
- Contract-Test `tests/contract/skills/test_top_surface.py`: alle vier Methoden mit exakter Signatur, Invariante `project_binding_is_symlink_only`

#### 2.1.10 Cleanup `__pycache__`-Artefakte (agent-skills.C2)

`src/agentkit/project_ops/install/__pycache__/` mit `skills.cpython-314.pyc`, `skill_variant.cpython-314.pyc` (Verzeichnis ohne Quellcode) wird geloescht.

### 2.2 Out of Scope

- `SkillQualityMetric`-Vollausbau (`agent-skills.A4`) — die Top-Methode `collect_quality_metrics` liefert hier nur einen leeren Stub. Voller Ausbau ist Folge-Story nach THEME-007 (Telemetrie-Projektionen).
- Pflicht-Skill-SKILL.md-Inhalte (`agent-skills.A5`) — die `.md`-Inhalte der Skills selbst (Anleitungen) sind nicht Teil dieser Backend-Story. Folge-Story Skills-Content.
- Optional-Skills `manage-requirements`, `semantic-review` (`agent-skills.A6`) — Folge-Story.
- Hook `skill_usage_check` in `governance.guard_system` (`agent-skills.A9`) — Folge-Story der Governance-Welle.
- Skill-Lifecycle-Events fuer Telemetrie (`agent-skills.A10`) — Folge-Story nach THEME-007.
- Eigenstaendiger Skill-Version-Pin (`agent-skills.A7`) — Datenmodell `SkillBundleVersion` ist hier vorhanden, aber kein Pin-Lifecycle-Service (`update_binding`-aequivalent). Folge-Story.
- Formale Invarianten-Codierung als Laufzeitpruefungen darueber hinaus (`agent-skills.A8`) — die zentrale Invariante `project_binding_is_symlink_only` ist in dieser Story enforced; weitere sechs Invarianten in Folge.
- F-43-029 (Semantic-Review-Skill, 12 Pruefdimensionen) — Folge-Story.

## 3. Betroffene Dateien

| Datei | Aenderungsart | Beschreibung |
|---|---|---|
| `src/agentkit/skills/__init__.py` | Neu | Re-Export |
| `src/agentkit/skills/top.py` | Neu | `Skills`-Klasse |
| `src/agentkit/skills/bundle_store.py` | Neu | `SkillBundleStore`, `SkillBundle`, `SkillBundleVersion`, `LogicalSkillId` |
| `src/agentkit/skills/binding.py` | Neu | `SkillBinding`, `SkillLifecycleStatus`, `SkillProfile` |
| `src/agentkit/skills/placeholder.py` | Neu | `PlaceholderSubstitutor` |
| `src/agentkit/skills/errors.py` | Neu | Exceptions |
| `src/agentkit/skills/repository.py` | Neu | `SkillBindingRepository`-Protocol |
| `src/agentkit/state_backend/store/skill_binding_repository.py` | Neu | SQLite/Postgres-Implementierung |
| `src/agentkit/state_backend/postgres_schema.sql` | Modifiziert | `skill_bindings`-Tabelle |
| `src/agentkit/state_backend/sqlite_store.py` | Modifiziert | analog SQLite |
| `src/agentkit/state_backend/config.py` | Modifiziert | SCHEMA_VERSION-Bump |
| `src/agentkit/installer/runner.py` | Modifiziert | `Skills.bind_skill`-Aufruf statt direktem `.claude/skills/`-Mkdir |
| `src/agentkit/project_ops/install/__pycache__/` | Geloescht | leerer Pyc-Stub entfernen |
| `tests/unit/skills/test_top.py` | Neu | Skills-Top-Tests |
| `tests/unit/skills/test_bundle_store.py` | Neu | Bundle-Store-Tests |
| `tests/unit/skills/test_binding.py` | Neu | Binding-Lifecycle-Tests |
| `tests/unit/skills/test_placeholder.py` | Neu | Substitution-Tests |
| `tests/unit/state_backend/store/test_skill_binding_repository.py` | Neu | parametrisiert SQLite + Postgres |
| `tests/integration/installer/test_skills_binding.py` | Neu | Installer ruft Skills.bind_skill; Symlink-Check |
| `tests/contract/skills/test_top_surface.py` | Neu | Vertrags-Pinning |

## 4. Akzeptanzkriterien

1. **Paket `src/agentkit/skills/` existiert** und exportiert `Skills`, `SkillBinding`, `SkillBundle`, `SkillBundleVersion`, `SkillBundleStore`, `PlaceholderSubstitutor`, `SkillLifecycleStatus`, `SkillProfile`.
2. **`Skills`-Klasse hat vier Top-Methoden** mit den genannten Signaturen: `bind_skill`, `resolve_binding`, `list_bound_skills`, `collect_quality_metrics` (letzteres als Stub mit leerer Metric).
3. **`bind_skill` durchlaeuft die Lifecycle-Transitions** `REQUESTED -> PROFILE_RESOLVED -> BUNDLE_SELECTED -> BOUND -> VERIFIED`. Tests verifizieren die Transitionen.
4. **Symlink-Invariante**: nach erfolgreichem `bind_skill` existiert unter `{project_root}/.claude/skills/{skill}/` ein Symlink (kein File-Copy), der auf den Bundle-Root zeigt. Tests pruefen `Path.is_symlink()`.
5. **Fail-closed-Pfade typisiert**: `SkillBindingFailedError`, `SkillBundleDigestMismatchError`, `SkillProfileNotSupportedError`, `UnknownPlaceholderError`, `SkillBundleNotFoundError`. Jede Exception ist in `errors.py` definiert und wird in Tests provoziert.
6. **`PlaceholderSubstitutor` ersetzt die vier Pflicht-Platzhalter** korrekt. Unbekannte Platzhalter -> `UnknownPlaceholderError`.
7. **Persistenz**: `skill_bindings`-Tabelle in SQLite + Postgres. Parametrisierte Repository-Tests laufen auf beiden Backends. UNIQUE `(project_key, skill_logical_id)` ist enforced.
8. **Installer-Integration**: `install_agentkit` ruft `Skills.bind_skill` fuer die vier Pflicht-Skills (`create-userstory`, `execute-userstory`, `lookup-userstory`, `llm-discussion` — Profile passend zum Projekt). Direktes `mkdir(.claude/skills)` entfaellt.
9. **`__pycache__`-Artefakte entfernt**: `src/agentkit/project_ops/install/__pycache__/skills.cpython-314.pyc` und `skill_variant.cpython-314.pyc` existieren nicht mehr.
10. **Architecture-Conformance**: `agentkit.skills` importiert nur aus `agentkit.core_types`, `agentkit.artifacts` (ggf. fuer Bundle-Records spaeter — heute optional), `agentkit.config` (PipelineConfig); nicht direkt aus `agentkit.state_backend.store`-Fassaden ausserhalb des Repository-Moduls.
11. **Pflichtbefehle gruen**: pytest unit + integration + contract; mypy --strict; ruff clean; Coverage haelt 85%.

## 5. Definition of Done

- AK 1-11 erfuellt.
- `.venv\Scripts\python -m pytest tests/unit/skills tests/integration/installer tests/contract/skills -q` gruen.
- `mypy --strict` gruen, `ruff check src tests` gruen.
- SQLite + Postgres migriert.
- Aenderungen committed auf `main`.

## 6. Konzept-Referenzen (autoritativ)

- **`concept/_meta/bc-cut-decisions.md §BC 11`** — Top-Surface, Sub-Komponenten, Klassen-Skizze
- **FK-43 §43.1** — Skills-Top
- **FK-43 §43.3.1/43.3.2** — Pflicht-/Optional-Skills
- **FK-43 §43.4.1** — Symlink-Bindung
- **FK-43 §43.4.2** — PlaceholderSubstitutor
- **FK-43 §43.5.2** — Skill-Version-Pin
- **`formal.skills-and-bundles.state-machine`** — Lifecycle
- **`formal.skills-and-bundles.invariants`** — insbesondere `project_binding_is_symlink_only`

## 7. Guardrail-Referenzen

- **FIX THE MODEL, NOT THE SYMPTOM**: Skills-BC bekommt Produktionsmodul; Installer wird BC-grenztreu.
- **ZERO DEBT**: Lifecycle-Status sind vollstaendig typisiert; keine Status-Strings.
- **FAIL CLOSED**: jeder Bindungspfad mit eigener Exception; keine stillen Fallbacks.
- **SINGLE SOURCE OF TRUTH**: Symlinks statt Datei-Kopien; Bundle lebt einmal im System-Store.

## 8. Hinweise fuer den Sub-Agent

- Symlinks unter Windows: das Repo lebt auf Windows; `Path.symlink_to` benoetigt entweder Developer-Mode oder Admin-Rechte. Falls Symlinks fehlschlagen, **darf nicht** in Datei-Copy gefallen werden — Invariante! Stattdessen: hartfehlern mit Aufforderung, Developer-Mode zu aktivieren. Tests koennen `tmp_path` nutzen; CI muss Symlinks koennen.
- Installer-Integration: pruefe alle Aufrufpfade in `install_agentkit`. Es gibt vermutlich Tests, die direktes mkdir erwarten — die werden angepasst.
- AK2 NICHT veraendern. Aber: AK2 hat einen `.claude/skills/`-Pfad mit Inhalten — die sind nicht Vorlage, aber zur Orientierung lesbar.
