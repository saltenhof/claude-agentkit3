# AG3-027: Skills BC — Top-Komponente Skills + Sub-Klassen

<!-- AG3-027 deep-review (User-Entscheidung 2026-05-19): Split-Variante (A) gewaehlt. Diese Story bleibt schlanke Top-Surface (M). Persistenz (skill_bindings-Tabelle), Installer-Integration (BC12) und __pycache__-Cleanup wandern in die Folge-Story AG3-048-skills-persistence-installer-cleanup. -->

<!-- AG3-027 Nachbesserung (User-Entscheidung 2026-06-01): Binde-Mechanik plattformabhaengig. Die "nur-Symlink"-Invariante faellt; an ihre Stelle tritt `project_binding_is_link_only` (Symlink auf POSIX, Directory Junction auf Windows — Junction braucht KEINEN Developer Mode). `SkillBindingMode` ist `SYMLINK | JUNCTION`; `bind_skill` persistiert den tatsaechlich verwendeten Modus. Mechanik in `src/agentkit/skills/links.py` (`_winapi.CreateJunction` auf Windows, `os.rmdir` zum Loesen ohne Ziel-Loeschung, `os.path.isjunction`-Detektion). Bindung ist install-zeit-fest; Re-Install erfordert Harness-Neustart (zweistufiges Laden). Konzept: FK-43 §43.4.1.1 + §43.5.3, FK-50 CP8, FK-76 §76.7. -->

**Typ:** Implementation
**Groesse:** M
**Abhaengigkeiten:** AG3-021 (Enums fuer Status-Felder), AG3-022 (`ArtifactClass`-Bezug fuer Skill-Bundle-Records)
**Quell-Konzepte (autoritativ, in dieser Reihenfolge):**
- `concept/_meta/bc-cut-decisions.md §BC 11 agent-skills`
- `FK-43 §43.1` (Skills-Top-Komponente)
- `FK-43 §43.3.1/43.3.2` (Pflicht-/Optional-Skills)
- `FK-43 §43.4.1` + `§43.4.1.1` (plattformabhaengige Link-Bindung: Symlink/Junction)
- `FK-43 §43.5.3` (Bindungs-Stabilitaet, Re-Install-Vertrag)
- `FK-43 §43.4.2` (PlaceholderSubstitutor)
- `FK-43 §43.5.2` (Skill-Version-Pin)
- `FK-43 §43.6.2` (SkillQualityMetric)
- `formal.skills-and-bundles.entities`
- `formal.skills-and-bundles.state-machine`
- `formal.skills-and-bundles.invariants` (insbesondere `project_binding_is_link_only` + `binding_is_install_time_stable`)

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
- `binding_mode: SkillBindingMode` — StrEnum: `SYMLINK | JUNCTION` (plattformabhaengig, FK-43 §43.4.1.1)
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

**Wichtig**: `PlaceholderSubstitutor` ist ein interner Service fuer materialisierte/substituierte Harness-Varianten und kuenftige Read-Time-Aufloesung. Er ist NICHT Teil der `bind_skill`-Top-Surface — `bind_skill(skill_name, bundle_root, project_root)` ruft den Substitutor nicht (Symlink-Invariante `project_binding_is_link_only`).

#### 2.1.6 Persistenz — **vollstaendig ausgelagert nach AG3-048**

<!-- AG3-027 Pass-1 (Stefan-Klarstellung 2026-05-24): Persistenz ist in dieser Story ausschliesslich Protocol + InMemory-Implementierung. Der produktive Backend-Pfad wandert nach AG3-048 und ist dort als **Postgres-First** geschnitten (kanonische Persistenz gemaess DK-05 §5: "Die kanonische Speicherung von Telemetrie, Workflow-State und KPI-Rohdaten erfolgt in einer systemweiten PostgreSQL-Instanz"; FK-60 §60: "SQLite-Varianten verworfen zugunsten klarer Writer-/Reader-Trennung auf PostgreSQL"). SQLite zieht das gleiche Schema parallel mit, aber ausschliesslich als Test-Pfad (`AGENTKIT_ALLOW_SQLITE=1` nur fuer "narrow unit-test execution"; Runtime/Build/Contract/Integration/E2E werfen RuntimeError gemaess state_backend/config.py). -->

AG3-027 liefert **ausschliesslich**:
- `SkillBindingRepository`-Protocol in `src/agentkit/skills/repository.py`
- InMemory-Implementierung fuer Unit- und Contract-Tests

**Produktive Persistenz ist Inhalt von AG3-048**:
- Postgres-Tabelle `skill_bindings` (kanonische Wahrheit) — `binding_id` (PK), `project_key`, `skill_name`, `bundle_id`, `bundle_version`, `target_path`, `binding_mode`, `status`, `pinned_at`; UNIQUE `(project_key, skill_name)`
- SQLite-Parallel-Schema (gleiche DDL, nur fuer Unit-Tests) gemaess Pattern aus AG3-024/AG3-025
- Konkrete Repository in `state_backend/store/skill_binding_repository.py`
- Schema-Versionierung Side-by-Side (AG3-005)

#### 2.1.7 `bind_skill`-Mechanik (FK-43 §43.4.1/§43.4.1.1, FK-50 CP8, Invariante `project_binding_is_link_only`)

<!-- AG3-027 deep-review: Profilauflösung/Bundle-Resolution wandert raus (Installer CP6/CP7). bind_skill bekommt bereits konkreten bundle_root. Multi-Harness-Symlinks (Claude Code + Codex) sind FK-43-Pflicht. -->

Schritte (Aufruf `bind_skill(skill_name, bundle_root, project_root)`):
1. Validierung: `project_root` existiert; `bundle_root` existiert + ist gueltiges Bundle; Manifest-Digest validiert
2. Lifecycle: status -> `REQUESTED` -> `BUNDLE_SELECTED` (Profil-/Bundle-Resolution ist bereits durch Caller geleistet)
3. Link-Erzeugung pro aktiviertem Harness am harness-spezifischen Bindungspunkt — plattformabhaengig Symlink (POSIX) bzw. Directory Junction (Windows, via `_winapi.CreateJunction`; kein Developer Mode noetig):
   - Claude Code: `{project_root}/.claude/skills/{skill_name}` -> `bundle_root`
   - Codex: harness-spezifischer Pfad gemaess FK-30 §30.11 (Codex-Aequivalent)
   Beide Links werden gesetzt, wenn der jeweilige Harness im Projekt aktiviert ist (Mehrfach-Harness-Support gemaess FK-43). Der tatsaechlich verwendete `SkillBindingMode` wird im `SkillBinding` persistiert.
4. PlaceholderSubstitutor wird **nicht** auf den Bundle-Inhalt angewendet (Invariante `project_binding_is_link_only`: kein Kopieren, kein Mutieren); Platzhalter werden zur Read-Zeit durch Skill-Konsumenten substituiert.
5. Lifecycle: `BOUND`. Persistenz via Repository (Protocol).
6. Verifikation (Links existieren via `is_directory_link` = Symlink ODER Junction, Manifest-Digest stimmt): `VERIFIED`.

Fail-closed-Pfade:
- Link-Erzeugung schlaegt fehl -> `SkillBindingFailedError` (status bleibt `BUNDLE_SELECTED`, nicht persistiert); kein Datei-Copy-Fallback
- Bundle-Manifest-Digest mismatch -> `SkillBundleDigestMismatchError`
- Profile passt nicht zu Bundle-Variants -> `SkillProfileNotSupportedError`

#### 2.1.8 Installer-Anschluss (agent-skills.C1) — **AUSGELAGERT NACH AG3-048**

<!-- AG3-027 deep-review (User-Entscheidung 2026-05-19): Split umgesetzt. Installer-Umbau (installer/runner.py:install_agentkit -> Skills.bind_skill) ist Inhalt der Folge-Story AG3-048. Diese Story liefert ausschliesslich die Top-Surface ``Skills.bind_skill`` plus einen Contract-Test, der zeigt, dass die Top-Surface vom Installer konsumierbar ist. -->

Diese Story liefert nur `Skills.bind_skill` als konsumierbare Top-Surface plus einen Contract-Test, der zeigt, dass die Top-Surface vom Installer **konsumierbar** ist (keine Aenderung am Installer hier). Der tatsaechliche Umbau von `installer/runner.py` ist Inhalt von AG3-048.

#### 2.1.9 Tests

- Unit-Tests fuer `Skills.bind_skill` (happy path, fail-closed-Pfade, Lifecycle-Transitions)
- Unit-Tests fuer `Skills.resolve_binding`, `list_bound_skills`
- Unit-Tests fuer `SkillBundleStore.resolve_variant` (Profil-Variant-Mapping)
- Unit-Tests fuer `PlaceholderSubstitutor` (alle vier Pflicht-Platzhalter + unknown-placeholder fail-closed)
- Unit-Tests fuer `SkillBindingRepository` (parametrisiert SQLite + Postgres)
- Integration-Test: Installer ruft `Skills.bind_skill` fuer alle Pflicht-Skills; `.claude/skills/` enthaelt Links (Symlink/Junction), keine Datei-Kopien
- Contract-Test `tests/contract/skills/test_top_surface.py`: alle vier Methoden mit exakter Signatur, Invariante `project_binding_is_link_only`

#### 2.1.10 Cleanup `__pycache__`-Artefakte (agent-skills.C2) — **AUSGELAGERT NACH AG3-048**

<!-- AG3-027 deep-review (User-Entscheidung 2026-05-19): Cleanup wandert in AG3-048 (Repo-Hygiene wird dort gebuendelt). -->

### 2.2 Out of Scope

- **Persistenz der `SkillBinding`-Records** (`skill_bindings`-Tabelle in SQLite/Postgres, SCHEMA_VERSION-Bump, parametrisierte Repository-Tests) — wandert nach **AG3-048**. Diese Story liefert nur das `SkillBindingRepository`-Protocol plus eine InMemory-Implementierung, damit die Top-Surface testbar ist; produktive Persistenz folgt in AG3-048.
- **Installer-Integration BC12** (`installer/runner.py:install_agentkit` ruft `Skills.bind_skill`) — wandert nach **AG3-048**.
- **`__pycache__`-Cleanup** unter `src/agentkit/project_ops/install/` — wandert nach **AG3-048** (Repo-Hygiene-Block).
- `SkillQualityMetric`-Vollausbau (`agent-skills.A4`) — die Top-Methode `collect_quality_metrics` wirft hier `NotImplementedError`. Voller Ausbau ist Folge-Story nach THEME-007 (Telemetrie-Projektionen).
- Pflicht-Skill-SKILL.md-Inhalte (`agent-skills.A5`) — die `.md`-Inhalte der Skills selbst (Anleitungen) sind nicht Teil dieser Backend-Story. Folge-Story Skills-Content.
- Optional-Skills `manage-requirements`, `semantic-review` (`agent-skills.A6`) — Folge-Story.
- Hook `skill_usage_check` in `governance.guard_system` (`agent-skills.A9`) — Folge-Story der Governance-Welle.
- Skill-Lifecycle-Events fuer Telemetrie (`agent-skills.A10`) — Folge-Story nach THEME-007.
- Eigenstaendiger Skill-Version-Pin (`agent-skills.A7`) — Datenmodell `SkillBundleVersion` ist hier vorhanden, aber kein Pin-Lifecycle-Service (`update_binding`-aequivalent). Folge-Story.
- Formale Invarianten-Codierung als Laufzeitpruefungen darueber hinaus (`agent-skills.A8`) — die zentrale Invariante `project_binding_is_link_only` ist in dieser Story enforced; weitere sechs Invarianten in Folge.
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
| `src/agentkit/skills/repository.py` | Neu | `SkillBindingRepository`-Protocol + InMemory-Implementierung fuer Tests |
| `tests/unit/skills/test_top.py` | Neu | Skills-Top-Tests |
| `tests/unit/skills/test_bundle_store.py` | Neu | Bundle-Store-Tests |
| `tests/unit/skills/test_binding.py` | Neu | Binding-Lifecycle-Tests |
| `tests/unit/skills/test_placeholder.py` | Neu | Substitution-Tests |
| `tests/contract/skills/test_top_surface.py` | Neu | Vertrags-Pinning fuer alle vier Methoden + Installer-Konsumierbarkeits-Probe |

<!-- AG3-027 deep-review (Split 2026-05-19): folgende Files NICHT mehr in dieser Story -- wandern nach AG3-048:
  - state_backend/store/skill_binding_repository.py (SQLite/Postgres-Persistenz)
  - state_backend/postgres_schema.sql + sqlite_store.py (skill_bindings-Tabelle)
  - state_backend/config.py (SCHEMA_VERSION-Bump)
  - installer/runner.py (Installer-Andockung)
  - project_ops/install/__pycache__/ (Repo-Hygiene)
  - tests/unit/state_backend/store/test_skill_binding_repository.py
  - tests/integration/installer/test_skills_binding.py
-->


## 4. Akzeptanzkriterien

1. **Paket `src/agentkit/skills/` existiert** und exportiert `Skills`, `SkillBinding`, `SkillBundle`, `SkillBundleVersion`, `SkillBundleStore`, `PlaceholderSubstitutor`, `SkillLifecycleStatus`, `SkillProfile`, `SkillBindingMode`.
2. **`Skills`-Klasse hat vier Top-Methoden** mit den genannten Signaturen: `bind_skill(skill_name: str, bundle_root: Path, project_root: Path) -> None`, `resolve_binding(project_root, skill_name)`, `list_bound_skills(project_root)`, `collect_quality_metrics(skill_name)` (letzteres wirft `NotImplementedError` mit Verweis auf Folge-Story; **keine leere Metric**). <!-- AG3-027 deep-review: Signatur an FK-43/FK-50 CP8 angeglichen; collect_quality_metrics darf nicht still ein "alles okay" suggerieren. -->
3. **`bind_skill` durchlaeuft die Lifecycle-Transitions** `REQUESTED -> BUNDLE_SELECTED -> BOUND -> VERIFIED` (Profilauflösung ist Caller-Vorarbeit). Tests verifizieren die Transitionen.
4. **Link-Invariante (Multi-Harness, plattformabhaengig)**: nach erfolgreichem `bind_skill` existiert pro aktiviertem Harness ein Link (Symlink auf POSIX, Directory Junction auf Windows) am harness-spezifischen Bindungspunkt — fuer Claude Code `{project_root}/.claude/skills/{skill_name}`, fuer Codex der FK-30 §30.11-Aequivalentpfad. Kein File-Copy, kein Canonical Skill Source im Projekt. Tests pruefen `is_directory_link()` (Symlink ODER Junction) fuer alle aktivierten Harnesses. <!-- AG3-027 Nachbesserung 2026-06-01: project_binding_is_link_only; Junction auf Windows braucht keinen Developer Mode, daher laufen die Bind-Tests auf jeder Plattform ohne Skip. -->
5. **Fail-closed-Pfade typisiert**: `SkillBindingFailedError`, `SkillBundleDigestMismatchError`, `SkillProfileNotSupportedError`, `UnknownPlaceholderError`, `SkillBundleNotFoundError`. Jede Exception ist in `errors.py` definiert und wird in Tests provoziert.
6. **`PlaceholderSubstitutor` ersetzt die vier Pflicht-Platzhalter** korrekt. Unbekannte Platzhalter -> `UnknownPlaceholderError`.
7. **Persistenz-Protocol**: `SkillBindingRepository`-Protocol ist definiert; InMemory-Implementierung liegt im Skills-BC und ist Unit-/Contract-test-fest. **Produktive SQLite/Postgres-Persistenz ist explizit AG3-048**.
8. **Installer-Konsumierbarkeits-Probe**: Contract-Test beweist, dass `Skills.bind_skill` mit der vom Installer erwarteten Signatur aufrufbar ist (keine tatsaechliche Aenderung am Installer in dieser Story — siehe AG3-048).
9. **Architecture-Conformance**: `agentkit.backend.skills` importiert nur aus `agentkit.backend.core_types`, `agentkit.backend.artifacts` (ggf. fuer Bundle-Records spaeter — heute optional), `agentkit.backend.config` (PipelineConfig); nicht direkt aus `agentkit.backend.state_backend.store`-Fassaden.
10. **Pflichtbefehle gruen**: pytest unit + contract; mypy --strict; ruff clean; Coverage haelt 85%.

## 5. Definition of Done

- AK 1-10 erfuellt.
- `.venv\Scripts\python -m pytest tests/unit/skills tests/contract/skills -q` gruen.
- `mypy --strict` gruen, `ruff check src tests` gruen.
- Aenderungen committed auf `main`.
- AG3-048 (Folge-Story fuer Persistenz + Installer-Andockung + Cache-Cleanup) ist angelegt und referenziert AG3-027 als Vorgaenger.

## 6. Konzept-Referenzen (autoritativ)

- **`concept/_meta/bc-cut-decisions.md §BC 11`** — Top-Surface, Sub-Komponenten, Klassen-Skizze
- **FK-43 §43.1** — Skills-Top
- **FK-43 §43.3.1/43.3.2** — Pflicht-/Optional-Skills
- **FK-43 §43.4.1/§43.4.1.1** — Link-Bindung (Symlink/Junction)
- **FK-43 §43.4.2** — PlaceholderSubstitutor
- **FK-43 §43.5.2** — Skill-Version-Pin
- **`formal.skills-and-bundles.state-machine`** — Lifecycle
- **`formal.skills-and-bundles.invariants`** — insbesondere `project_binding_is_link_only`

## 7. Guardrail-Referenzen

- **FIX THE MODEL, NOT THE SYMPTOM**: Skills-BC bekommt Produktionsmodul; Installer wird BC-grenztreu.
- **ZERO DEBT**: Lifecycle-Status sind vollstaendig typisiert; keine Status-Strings.
- **FAIL CLOSED**: jeder Bindungspfad mit eigener Exception; keine stillen Fallbacks.
- **SINGLE SOURCE OF TRUTH**: Links (Symlink/Junction) statt Datei-Kopien; Bundle lebt einmal im System-Store.

## 8. Hinweise fuer den Sub-Agent

- Links unter Windows: das Repo lebt auf Windows. Die Bindung nutzt auf Windows eine **Directory Junction** (`_winapi.CreateJunction`), die KEINEN Developer Mode und kein `SeCreateSymbolicLinkPrivilege` braucht — der fruehere Symlink-only-Ansatz scheiterte ohne Developer Mode (WinError 1314) und ist verworfen. Falls die Link-Erzeugung fehlschlaegt, **darf nicht** in Datei-Copy gefallen werden (Invariante `project_binding_is_link_only`) — stattdessen hartfehlern. Junction-Sicherheit: Detektion via `os.path.isjunction`, Loesen via `os.rmdir` (nie `shutil.rmtree` durch den Link — das loescht das zentrale Ziel). Tests laufen mit `tmp_path` auf jeder Plattform.
- Installer-Integration: pruefe alle Aufrufpfade in `install_agentkit`. Es gibt vermutlich Tests, die direktes mkdir erwarten — die werden angepasst.
- AK2 NICHT veraendern. Aber: AK2 hat einen `.claude/skills/`-Pfad mit Inhalten — die sind nicht Vorlage, aber zur Orientierung lesbar.
