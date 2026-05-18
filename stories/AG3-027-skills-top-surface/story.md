# AG3-027: Skills BC — Top-Komponente Skills + Sub-Klassen

<!-- AG3-027 deep-review (Schnitt-Vorbehalt): ChatGPT empfiehlt, Persistenz (SQLite/Postgres skill_bindings-Tabelle), Installer-Integration (BC12) und __pycache__-Cleanup aus dieser Story auszulagern, weil sie die Top-Surface-Story von "M" auf "L" aufblaehen und BC-fremde Aenderungen (state_backend, installer/runner) mit hineintragen. Die Story behaelt aktuell den Vollscope, markiert aber Out-of-Scope-Kandidaten explizit. Orchestrator entscheidet, ob ein Split notwendig ist. -->

**Typ:** Implementation
**Groesse:** L (Schnitt-Vorbehalt — siehe Header-Kommentar)
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

#### 2.1.2 `Skills`-Top-Klasse (bc-cut-decisions.md §BC 11, FK-43, FK-50 CP8)

<!-- AG3-027 deep-review: bind_skill-Signatur korrigiert. FK-43 + FK-50 CP8 normieren bind_skill(skill_name, bundle_root, project_root) -> None. Profil-/Bundle-Resolution ist Installer-Vorarbeit (CP6/CP7), nicht bind_skill-Parameter. -->

```python
class Skills:
    def __init__(self, bundle_store: SkillBundleStore, binding_repo: SkillBindingRepository) -> None: ...

    def bind_skill(
        self,
        skill_name: str,
        bundle_root: Path,
        project_root: Path,
    ) -> None: ...

    def resolve_binding(self, project_root: Path, skill_name: str) -> SkillBinding | None: ...

    def list_bound_skills(self, project_root: Path) -> list[SkillBinding]: ...

    def collect_quality_metrics(self, skill_name: str) -> SkillQualityMetric:
        # Convention: ohne Telemetrie-Datenquelle (Folge-Story) MUSS NotImplementedError
        # geworfen werden. Eine leere SkillQualityMetric ist nicht akzeptabel, weil sie
        # ein "alles okay" suggeriert (FK-43: Skill-Quality ist echte Messung aus
        # Telemetrie + Failure-Corpus).
        raise NotImplementedError("SkillQualityMetric requires telemetry/failure-corpus data — follow-up story")
```

`SkillProfile` ist StrEnum mit den Konzept-Profilen (`CORE`, `ARE`). `LogicalSkillId` ist NewType — wird in dieser Story durch `skill_name: str` ersetzt (entspricht FK-43-Vokabular); `LogicalSkillId` bleibt als interner Alias erlaubt.

Eine optionale Convenience-Methode `bind_profile_skills(project_root: Path, profile: SkillProfile, config: PipelineConfig) -> list[SkillBinding]` ist **erlaubt**, aber NICHT Teil der FK-43/FK-50-Top-Surface — interne Helper, nicht im `__init__.py`-Export.

#### 2.1.3 `SkillBundleStore`

<!-- AG3-027 deep-review: resolve_variant ist Installer-Vorarbeit (CP6/CP7), nicht Teil der Top-Surface dieser Story. -->

Systemweiter, kanonischer Bundle-Store (analog `PromptBundleStore` aus AG3-015):

- `SkillBundle` (Pydantic-v2-Modell): `bundle_id`, `bundle_version`, `bundle_root: Path`, `manifest_digest: str`, `variants: dict[SkillProfile, str]` (skill_name pro Profil)
- `SkillBundleStore.get_bundle(bundle_id) -> SkillBundle`
- Default-Pfad: `~/.agentkit/skills/` (systemweit); pro Test kann ein temporaerer Pfad uebergeben werden.

`SkillBundleStore.resolve_variant(skill_name, profile) -> SkillBundle` ist **NICHT Scope dieser Story** — `bind_skill` bekommt bereits einen konkreten `bundle_root` uebergeben. Profilermittlung + Bundle-Auswahl gehoeren in eine Folge-Story (Installer-Andockung CP6/CP7).

Bundle-Versionierung: `SkillBundleVersion` als Pydantic-Modell mit `version: str`, `pinned_at: datetime`. Eigenstaendig zu PromptBundle (`FK-43 §43.5.2`).

#### 2.1.4 `SkillBinding` mit Skill-Lifecycle (formal.skills-and-bundles.entities + state-machine)

<!-- AG3-027 deep-review: Feldnamen an formal.skills-and-bundles.entities angeglichen (binding_id, project_key, skill_name, bundle_id, target_path, binding_mode). -->

`SkillBinding` ist Pydantic-v2-Modell (frozen, extra forbid) und folgt der formalen Entity `skill-binding`:

- `binding_id: str` — kanonische Identitaet aus formal.skills-and-bundles.entities
- `project_key: str`
- `skill_name: str`
- `bundle_id: str`
- `bundle_version: str`
- `target_path: Path` — Bindungspunkt im Projekt (z.B. `.claude/skills/{skill_name}`)
- `binding_mode: SkillBindingMode` — StrEnum: `SYMLINK` (Pflicht), Zukunfts-Slots
- `status: SkillLifecycleStatus`
- `pinned_at: datetime`

`SkillLifecycleStatus` StrEnum mit den Werten aus `formal.skills-and-bundles.state-machine`: `REQUESTED`, `PROFILE_RESOLVED`, `BUNDLE_SELECTED`, `BOUND`, `VERIFIED`, `REJECTED`.

`SkillBindingRepository` Protocol fuer Persistenz. **Top-Surface-Story-Scope**: Repository-Protocol + InMemory-/Fake-Implementierung fuer Unit-Tests. Echte SQLite/Postgres-Tabelle siehe Vorbehalt in 2.1.6.

#### 2.1.5 `PlaceholderSubstitutor` (FK-43 §43.4.2)

<!-- AG3-027 deep-review: PlaceholderSubstitutor ist Implementierungsdetail fuer materialisierte/substituierte Harness-Varianten (FK-43 §43.4.2). bind_skill ist Symlink-only und ruft den Substitutor NICHT. -->

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

**Wichtig**: `PlaceholderSubstitutor` ist ein interner Service fuer materialisierte/substituierte Harness-Varianten und kuenftige Read-Time-Aufloesung. Er ist NICHT Teil der `bind_skill`-Top-Surface — `bind_skill(skill_name, bundle_root, project_root)` ruft den Substitutor nicht (Symlink-Invariante `project_binding_is_symlink_only`).

#### 2.1.6 Persistenz (SQLite + Postgres)

<!-- AG3-027 deep-review (Schnitt-Vorbehalt): ChatGPT empfiehlt, Persistenz aus dieser Top-Surface-Story herauszuziehen und in eine Folge-Story "AG3-027b SkillBinding persistence + pin record" zu schneiden. Begruendung: Top-Surface braucht nur Protocol + InMemory-Fake; produktive State-Backend-Migration ist BC-fremde Arbeit (state_backend). Aktuell bleibt der Vollscope drin, mit dem Hinweis, dass Orchestrator entscheidet, ob Split vorgezogen wird. -->

Neue Tabelle `skill_bindings`:
- `binding_id` (PK), `project_key`, `skill_name`, `bundle_id`, `bundle_version`, `target_path`, `binding_mode`, `status`, `pinned_at`
- UNIQUE `(project_key, skill_name)`
- Konkrete Repository in `state_backend/store/skill_binding_repository.py`
- Schema-Versionierung Side-by-Side (AG3-005)

**Wenn Split**: Diese Story behaelt nur `SkillBindingRepository`-Protocol + InMemory-Implementierung; alle `state_backend/`-Aenderungen wandern in die Folge-Story.

#### 2.1.7 `bind_skill`-Mechanik (FK-43 §43.4.1, FK-50 CP8, Invariante `project_binding_is_symlink_only`)

<!-- AG3-027 deep-review: Profilauflösung/Bundle-Resolution wandert raus (Installer CP6/CP7). bind_skill bekommt bereits konkreten bundle_root. Multi-Harness-Symlinks (Claude Code + Codex) sind FK-43-Pflicht. -->

Schritte (Aufruf `bind_skill(skill_name, bundle_root, project_root)`):
1. Validierung: `project_root` existiert; `bundle_root` existiert + ist gueltiges Bundle; Manifest-Digest validiert
2. Lifecycle: status -> `REQUESTED` -> `BUNDLE_SELECTED` (Profil-/Bundle-Resolution ist bereits durch Caller geleistet)
3. Symlink-Erzeugung pro aktiviertem Harness am harness-spezifischen Bindungspunkt:
   - Claude Code: `{project_root}/.claude/skills/{skill_name}` -> `bundle_root`
   - Codex: harness-spezifischer Pfad gemaess FK-30 §30.11 (Codex-Aequivalent)
   Beide Symlinks werden gesetzt, wenn der jeweilige Harness im Projekt aktiviert ist (Mehrfach-Harness-Support gemaess FK-43).
4. PlaceholderSubstitutor wird **nicht** auf den Bundle-Inhalt angewendet (Invariante `project_binding_is_symlink_only`: kein Kopieren, kein Mutieren); Platzhalter werden zur Read-Zeit durch Skill-Konsumenten substituiert.
5. Lifecycle: `BOUND`. Persistenz via Repository (Protocol).
6. Verifikation (Symlinks existieren, zeigen auf Bundle, Manifest-Digest stimmt): `VERIFIED`.

Fail-closed-Pfade:
- Symlink-Erzeugung schlaegt fehl -> `SkillBindingFailedError` (status bleibt `BUNDLE_SELECTED`, nicht persistiert)
- Bundle-Manifest-Digest mismatch -> `SkillBundleDigestMismatchError`
- Profile passt nicht zu Bundle-Variants -> `SkillProfileNotSupportedError`

#### 2.1.8 Installer-Anschluss (agent-skills.C1)

<!-- AG3-027 deep-review (Schnitt-Vorbehalt): Installer-Aenderungen (installer/runner.py:install_agentkit) gehoeren zum BC `installation-and-bootstrap` (BC12), nicht zur Skills-Top-Surface. ChatGPT empfiehlt, diesen Abschnitt in eine eigene BC12-Andock-Story zu verschieben. Aktuell bleibt der Vollscope inklusive Installer-Umbau drin; Orchestrator entscheidet, ob Split. -->

`src/agentkit/installer/runner.py:install_agentkit`:
- Aufruf von `Skills.bind_skill` fuer jeden Pflicht-Skill (FK-43 §43.3.1 nennt: `create-userstory`, `execute-userstory`, `lookup-userstory`, `llm-discussion` — Profile core/are je nach Projekt-Profil; Profilermittlung in CP6/CP7 vor dem Aufruf)
- Direktes Anlegen von `.claude/skills/` als leerer Platzhalter entfaellt
- Falls Bundle nicht im System-Store: fail-closed mit Installation-Fehler

**Wenn Split**: Diese Story liefert nur `Skills.bind_skill` als konsumierbare Top-Surface plus einen Contract-Test/Integration-Fixture, der zeigt, dass `Skills.bind_skill` vom Installer konsumierbar ist. Der tatsaechliche Umbau von `installer/runner.py` wandert in die BC12-Andock-Story.

#### 2.1.9 Tests

- Unit-Tests fuer `Skills.bind_skill` (happy path, fail-closed-Pfade, Lifecycle-Transitions)
- Unit-Tests fuer `Skills.resolve_binding`, `list_bound_skills`
- Unit-Tests fuer `SkillBundleStore.resolve_variant` (Profil-Variant-Mapping)
- Unit-Tests fuer `PlaceholderSubstitutor` (alle vier Pflicht-Platzhalter + unknown-placeholder fail-closed)
- Unit-Tests fuer `SkillBindingRepository` (parametrisiert SQLite + Postgres)
- Integration-Test: Installer ruft `Skills.bind_skill` fuer alle Pflicht-Skills; `.claude/skills/` enthaelt Symlinks, keine Datei-Kopien
- Contract-Test `tests/contract/skills/test_top_surface.py`: alle vier Methoden mit exakter Signatur, Invariante `project_binding_is_symlink_only`

#### 2.1.10 Cleanup `__pycache__`-Artefakte (agent-skills.C2)

<!-- AG3-027 deep-review (Schnitt-Vorbehalt): __pycache__-Cleanup ist Repo-Hygiene, kein Skills-Top-Surface-Vertrag. ChatGPT empfiehlt, das als separate Cleanup-Task auszulagern. Aktuell bleibt es drin; Orchestrator entscheidet. -->

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

1. **Paket `src/agentkit/skills/` existiert** und exportiert `Skills`, `SkillBinding`, `SkillBundle`, `SkillBundleVersion`, `SkillBundleStore`, `PlaceholderSubstitutor`, `SkillLifecycleStatus`, `SkillProfile`, `SkillBindingMode`.
2. **`Skills`-Klasse hat vier Top-Methoden** mit den genannten Signaturen: `bind_skill(skill_name: str, bundle_root: Path, project_root: Path) -> None`, `resolve_binding(project_root, skill_name)`, `list_bound_skills(project_root)`, `collect_quality_metrics(skill_name)` (letzteres wirft `NotImplementedError` mit Verweis auf Folge-Story; **keine leere Metric**). <!-- AG3-027 deep-review: Signatur an FK-43/FK-50 CP8 angeglichen; collect_quality_metrics darf nicht still ein "alles okay" suggerieren. -->
3. **`bind_skill` durchlaeuft die Lifecycle-Transitions** `REQUESTED -> BUNDLE_SELECTED -> BOUND -> VERIFIED` (Profilauflösung ist Caller-Vorarbeit). Tests verifizieren die Transitionen.
4. **Symlink-Invariante (Multi-Harness)**: nach erfolgreichem `bind_skill` existiert pro aktiviertem Harness ein Symlink am harness-spezifischen Bindungspunkt — fuer Claude Code `{project_root}/.claude/skills/{skill_name}`, fuer Codex der FK-30 §30.11-Aequivalentpfad. Kein File-Copy, kein Canonical Skill Source im Projekt. Tests pruefen `Path.is_symlink()` fuer alle aktivierten Harnesses. <!-- AG3-027 deep-review: FK-43 fordert AK3 ab Tag 1 Claude Code + Codex parallel; Story darf nicht nur .claude/skills pruefen. -->
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
