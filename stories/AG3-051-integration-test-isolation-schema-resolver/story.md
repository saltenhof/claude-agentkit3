# AG3-051: Integration-Test-Isolation via zentralem Postgres-Schema-Resolver

<!-- AG3-051 (User-Entscheidung 2026-06-02): Folge-Arbeit aus AG3-048. Beim
Un-Gating der schweren Integration-Smoke-Tests (pipeline_runner, install_fresh)
trat ein pre-existing Test-Infra-Mangel zutage: alle Postgres-Suiten teilen EIN
versioniertes Schema und akkumulieren Zeilen -> UNIQUE-Kollisionen ueber Tests.
Diese Story behebt das an der Wurzel: EIN zentraler Schema-Resolver fuer ALLE
Postgres-Zugriffspfade + test-gescoptes Schema-Namespacing. Der Vorschlag wurde
vor Story-Anlage adversarisch von giftige-Codex reviewt (4 ERRORs / 4 WARNINGs);
alle Befunde sind unten eingearbeitet. -->

**Typ:** Implementation
**Groesse:** L
**Abhaengigkeiten:** AG3-048 (completed — hat die gegateten Smoke-Tests und den Mangel sichtbar gemacht)
**Quell-Konzepte (autoritativ, in dieser Reihenfolge):**
- `concept/methodology/software-blutgruppen.md` — `state_backend` ist T-Blutgruppe (Infrastruktur-Treiber); Aenderungen bleiben in T.
- `concept/technical-design/01_systemkontext_und_architekturprinzipien.md` — Determinismus, Fail-Closed, Trust Boundaries
- `FK-18 §18.9a` — versioniertes Side-by-Side-Schema (`ak3_v<slug>`), das hier NICHT angetastet, sondern nur test-uebersteuerbar gemacht wird
- `guardrails/testing-guardrails.md` — Negativpfad-/Isolationspflichten

> **Leitsatz (FIX THE MODEL):** Der heutige Defekt ist *sechsfach duplizierte*
> Schema-Aufloesung. Sechs Repositories rufen `versioned_postgres_schema_name()`
> direkt und machen ihr eigenes `CREATE SCHEMA` + `SET search_path`. Die Loesung
> ist EIN Resolver, den alle Pfade nutzen — nicht ein Test-Sonderpfad neben der
> bestehenden Duplikation. Test-Isolation ist die *Folge* der Konsolidierung,
> nicht ihr Zweck.

---

## 1. Kontext

`state_backend` selektiert das Backend prozessglobal ueber ein `@lru_cache(maxsize=1)`
(`store/facade.py:73`) und namespaced Postgres-State ueber ein **versioniertes Schema**
`ak3_v<slug>` (z. B. `ak3_v3_14_0`). Jede Verbindung macht `CREATE SCHEMA IF NOT EXISTS`
+ `SET search_path` (`postgres_store.py:249`).

Drei gekoppelte Prozess-Singletons erzeugen den Test-Isolationsmangel:

1. **Ambientes Env, session-weit:** `postgres_runtime_env` ist session-scoped
   (`tests/fixtures/postgres_backend.py:138`) und pinnt `AGENTKIT_STATE_BACKEND=postgres`
   + URL fuer die gesamte Session.
2. **Inject in alle Postgres-Suiten:** `tests/integration/conftest.py`,
   `tests/contract/conftest.py:37` **und** `tests/e2e/conftest.py` haengen dieses
   Fixture an jeden Test ihrer Suite.
3. **Schema-Name = reine Funktion von `SCHEMA_VERSION`** (`config.py:133`). Alle Tests
   landen im selben Namespace; niemand raeumt zwischen Tests auf -> Zeilen akkumulieren
   und kollidieren auf `UNIQUE(story_id)` / `UNIQUE(project_key, skill_name)`. Fix-IDs
   wie `TEST-001`, `demo-project`, `AG3-901` killen einander.

**Verschaerfender Befund (Codex r1, verifiziert):** Sechs aktive Repositories umgehen
`postgres_store.current_schema_name()` und rufen `versioned_postgres_schema_name()`
direkt mit eigener Schema-Bootstrap-Logik:
`artifact_repository.py:382`, `story_repository.py:453`, `projection_repositories.py:306`,
`skill_binding_repository.py:124`, `governance_hook_repository.py:198`,
`lock_record_repository.py:139`. Ein Test-Override nur in `postgres_store.py` wuerde
also **partiell** isolieren (Facade-Pfade im Test-Schema, Repos weiter in `ak3_v3_14_0`).
Das ist die zentrale Begruendung fuer den Resolver-Refactor.

Die `tests/unit/conftest.py`-autouse-Fixture (`_force_sqlite_for_unit_tests`) dokumentiert
und entschaerft die Env/Cache-Leakage in Unit-Tests; sie **bleibt** und ist die tragende
Leitplanke fuer Unit-Tests. Die frueher beobachteten ~130 verify_system-Regressionen sind
**Backend-Selection-Leakage** (so dokumentiert in `tests/unit/conftest.py:3`), nicht primaer
Shared-Row-Coupling — diese Story behauptet keine andere Ursache.

## 2. Scope

### 2.1 In Scope

#### 2.1.1 EIN zentraler Schema-Resolver (Produktions-Refactor, T-Blutgruppe)

Ein einziger Resolver wird die Single Source of Truth fuer den Postgres-Schema-Namen
**und** das Schema-Bootstrap (`CREATE SCHEMA` + `SET search_path`). Verbindlich:

- Resolver-Funktion (z. B. `state_backend.config.resolve_schema_name()` bzw. ein
  gemeinsamer `_ensure_versioned_schema(conn)`-Helper an genau **einer** Stelle).
- **Alle sieben Pfade** nutzen ihn: `postgres_store` + die sechs oben genannten
  Repositories. Die sechs lokalen `from ... import versioned_postgres_schema_name`
  + inline `CREATE SCHEMA`/`SET search_path` werden durch den gemeinsamen Helper
  ersetzt. Danach existiert **kein** zweiter Schema-Bootstrap-Pfad mehr.
- Schema-Namen werden **ueberall** via `psycopg.sql.Identifier` (oder aequivalentes
  Quoting) emittiert. Die heutige Roh-`f"...{schema}..."`-Interpolation
  (`postgres_store.py:249` u. a.) entfaellt — sie ist schon jetzt ein latentes
  SQL-Identifier-Injection-Risiko (Codex ERROR 2).

#### 2.1.2 Fail-closed Test-Override

Der Resolver gibt das Test-Schema nur unter **harten** Bedingungen zurueck:

- Nur wirksam, wenn das Test-Mode-Gate aktiv ist (analog `AGENTKIT_ALLOW_SQLITE`;
  dedizierte Variable, z. B. `AGENTKIT_PG_SCHEMA_OVERRIDE`, NUR in Test-Fixtures gesetzt).
- Regex-validiert `^ak3test_[a-z0-9_]+$`. Verstoss -> `RuntimeError` (fail-closed).
- Override gesetzt, aber Gate inaktiv -> `RuntimeError`.
- Ohne Override liefert der Resolver unveraendert `versioned_postgres_schema_name()`
  (`ak3_v<slug>`). Produktion/Runtime/Build setzen den Override nie -> **null
  Verhaltensaenderung** in Produktion.

Damit ist der Override **keine** zweite operative Wahrheit: Produktion kennt nur den
versionierten Namen; Test-Schemas leben in einem disjunkten, regex-erzwungenen
`ak3test_`-Namespace (Codex ERROR 2 geschlossen).

#### 2.1.3 Test-Schema-Namespacing fuer ALLE Postgres-Suiten

Worker-gescoptes Schema + Per-Test-Hygiene, geteilt von integration/contract/e2e
(nicht nur integration — Codex ERROR 3):

- Schema-Name `ak3test_<runtoken>_<worker>`. `runtoken` = der von **pytest-xdist
  bereitgestellte `testrun_uid`** (identisch ueber alle Worker EINES Laufs, eindeutig
  zwischen Laeufen — loest WARNING 1 deterministisch, kein selbstgebauter
  Controller->Worker-Propagationsmechanismus); `<worker>` aus `PYTEST_XDIST_WORKER`
  (`_local` seriell ohne xdist). Eindeutigkeit ueber Worker und parallele CI-Laeufe.
- Worker-scoped Fixture: legt Schema an, fuehrt DDL **einmal** pro Worker aus,
  traegt sich in eine Registry ein.
- **Keine pauschale Suite-autouse, und JEDER der drei Hooks MUSS pfad-gefiltert sein.**
  Achtung — heutiger Defekt: `tests/integration/conftest.py:7` und `tests/e2e/conftest.py:19`
  haengen `postgres_runtime_env` an **jedes** kollektierte Item an, **ohne** Pfad-Filter
  (`pytest_collection_modifyitems` sieht im Vollsuite-Lauf ALLE Items, nicht nur die der
  eigenen Suite — belegt durch den Kommentar in `tests/unit/telemetry/test_projection_roundtrip.py:7`
  "Integration-conftest forciert Postgres fuer alle Tests"). Nur `tests/contract/conftest.py:35`
  filtert heute. Die neue Mechanik MUSS daher in **allen drei** Hooks ein Pfad-Praedikat
  setzen, das die Isolationsfixture ausschliesslich an Items der eigenen Suite bindet:
  - integration-Hook -> nur `"/integration/"`-Items
  - e2e-Hook -> nur `"/e2e/"`-Items
  - contract-Hook -> nur `"/contract/"`-Items **abzueglich** `_POSTGRES_INDEPENDENT_CONTRACT_PATHS`
    (`tests/contract/conftest.py:12` — `core_types/`, `project_management/`, `failure_corpus/`).
  Pure-in-memory-Tests (`core_types/`, `project_management/`, `failure_corpus/` und alle
  Unit-Tests) duerfen **nie** Docker/Postgres via `postgres_container_url`
  (`postgres_backend.py:39`) anziehen (Codex v2 ERROR 1 + v3-Verschaerfung). Der Hook haengt
  statt `postgres_runtime_env` die neue function-scoped Isolationsfixture an die so
  gefilterte Item-Menge.
- Die Isolationsfixture: monkeypatch Env (backend=postgres, URL, Override);
  Reihenfolge *Env setzen -> Cache clearen -> TRUNCATE -> yield -> TRUNCATE ->
  Cache clearen*. `TEST-001` & Co. sind in jedem Test frisch.
- TRUNCATE-Discovery: nur **Base-Tables** des Test-Schemas via
  `information_schema.tables WHERE table_schema = <schema> AND table_type = 'BASE TABLE'`,
  Registry-Tabelle in `public` ausgeschlossen, Identifier gequotet, DDL vor Truncate,
  `RESTART IDENTITY CASCADE` (Codex WARNING 3).

#### 2.1.4 Ambient-Kopplung aufloesen

- Das session-scoped `postgres_runtime_env` entfaellt; die drei Collection-Hooks
  bleiben als **Selektoren** erhalten (gleiches Pfad-Filter inkl.
  `_POSTGRES_INDEPENDENT_CONTRACT_PATHS`), haengen aber statt der session-Fixture die
  neue function-scoped Isolationsfixture an. Kein session-globaler Pin ueberlebt mehr.
- `tests/unit/conftest.py`-sqlite-autouse **bleibt** (tragende Leitplanke). Der
  Contract-Hook-Kommentar (`tests/contract/conftest.py:6-11`) bestaetigt die Ursache der
  frueheren Unit-Regressionen: session-weites Umschalten von `AGENTKIT_STATE_BACKEND`
  kontaminierte interleavte SQLite-Unit-Tests. Per-Test-monkeypatch (auto-restore)
  beseitigt genau diese Kontamination.
- Order-/Shared-Row-gekoppelte Tests werden self-contained gemacht (eigene Daten je
  Test, nicht Verlass auf Fremdzeilen): mindestens `test_pipeline_runner.py:57`,
  `test_install_fresh.py:29`, `test_postgres_backend.py:87` (Codex WARNING 4).

#### 2.1.5 Schema-Cleanup (dreifach, ehrlich abgestuft)

- **Primaer — Worker-Finalizer:** `DROP SCHEMA <ak3test_...> CASCADE` (Identifier-gequotet)
  + Registry-Zeile loeschen, bei sauberem Exit.
- **Crash-Backstop — Session-Start-Sweep:** Registry-Tabelle
  `public.ak3_test_schema_registry(schema_name TEXT PRIMARY KEY, run_token TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now())`. Sweep droppt nur Schemas mit
  `created_at < now() - interval '24 hours'` (DB-seitige Zeit, kein Client-Clock-Skew).
- **Strukturell — Docker `--rm`:** der Default-Pfad (`postgres_backend.py:33`) entsorgt
  den ganzen Container ohnehin; Registry + Sweep sind dort Belt-and-Suspenders.

> **WARNING (deferrable, explizit dokumentiert — Codex WARNING 1):** Der TTL-Sweep ist
> **kein** Race-Freiheits-Garant. Ein Lauf >24h, ein angehaltener Debugger oder ein
> haengender Worker auf einer geteilt-persistenten CI-Postgres koennte theoretisch
> ein noch lebendes Schema droppen. Restrisiko bleibt bestehen; primaerer Raeumer ist
> der Worker-Finalizer + wegwerfbare DB pro Lauf. Wenn die CI auf eine geteilt-persistente
> Instanz festgelegt wird, ist ein Heartbeat-/last_seen-Ownership-Modell als Folge-Story
> noetig. Dieser Punkt ist beim Abschluss aktiv an den Auftraggeber zu spiegeln.

#### 2.1.6 Dev-Abhaengigkeiten reproduzierbar machen

`pyproject.toml` `[project.optional-dependencies].dev` (`pyproject.toml:23`) listet heute
nur `pytest`, `pytest-cov`, `pytest-asyncio` — **nicht** `pytest-randomly` / `pytest-xdist`
(Codex v2 ERROR 2). Da die Pflichtbefehle ueber `.venv\Scripts\python -m pip install -e ".[dev]"`
laufen, ist die in AK9/DoD geforderte Verifikation sonst nicht aus der deklarierten Umgebung
reproduzierbar. Beide Pakete werden zu `[dev]` ergaenzt (`pytest-randomly`, `pytest-xdist`);
`testrun_uid` (xdist) ist damit auch produktiv als Fixture verfuegbar.

#### 2.1.7 Verifikation

- Die zwei gegateten Smoke-Tests un-gaten: `tests/integration/pipeline_engine/test_pipeline_runner.py`,
  `tests/integration/project_ops/install_fresh/test_install_fresh.py`.
- Contract-Test: ohne Override liefert der Resolver `ak3_v<slug>`; Override aendert
  **nur** den Schema-Namen; Override ohne Gate / Pattern-Verstoss -> `RuntimeError`.
- Regressionstest: zwei Tests schreiben beide `TEST-001` und gehen beide gruen
  (beweist Per-Test-Reset).
- Volle Suite gruen unter `pytest-randomly` **und** `pytest -n auto`.

### 2.2 Out of Scope

- Heartbeat-/last_seen-Ownership-Modell fuer den Sweep (nur falls geteilt-persistente
  CI-DB verbindlich wird -> Folge-Story).
- Aenderung des produktiven `ak3_v<slug>`-Namensschemas oder der `SCHEMA_VERSION`-Mechanik.
- Umstellung der CI-Postgres-Topologie (Jenkinsfile) — separat zu entscheiden.
- Neue fachliche Tabellen oder Migrationen.

## 3. Betroffene Dateien

| Datei | Aenderungsart | Beschreibung |
|---|---|---|
| `pyproject.toml` | Modifiziert | `pytest-randomly` + `pytest-xdist` zu `[dev]` (reproduzierbare Verifikation) |
| `src/agentkit/state_backend/config.py` | Modifiziert | Zentraler `resolve_schema_name()` mit fail-closed Override + Regex-Gate |
| `src/agentkit/state_backend/postgres_store.py` | Modifiziert | `_ensure_versioned_schema` nutzt Resolver + `sql.Identifier`-Quoting |
| `src/agentkit/state_backend/store/artifact_repository.py` | Modifiziert | Inline-Schema-Bootstrap -> gemeinsamer Helper |
| `src/agentkit/state_backend/store/story_repository.py` | Modifiziert | dito |
| `src/agentkit/state_backend/store/projection_repositories.py` | Modifiziert | dito |
| `src/agentkit/state_backend/store/skill_binding_repository.py` | Modifiziert | dito |
| `src/agentkit/state_backend/store/governance_hook_repository.py` | Modifiziert | dito |
| `src/agentkit/state_backend/store/lock_record_repository.py` | Modifiziert | dito |
| `tests/fixtures/postgres_backend.py` | Modifiziert | Worker-Schema-Fixture (`testrun_uid`-basiert), function-scoped Isolations-Fixture, Registry + Sweep + Finalizer; session-`postgres_runtime_env` entfernt |
| `tests/integration/conftest.py` | Modifiziert | Hook **neu pfad-gefiltert** (`/integration/`), haengt Isolationsfixture statt session-Inject an — heutiger ungefilterter Inject (`:7`) wird ersetzt |
| `tests/contract/conftest.py` | Modifiziert | Hook bindet Isolationsfixture, Pfad-Filter `/contract/` minus `_POSTGRES_INDEPENDENT_CONTRACT_PATHS` bleibt erhalten |
| `tests/e2e/conftest.py` | Modifiziert | Hook **neu pfad-gefiltert** (`/e2e/`), haengt Isolationsfixture statt session-Inject an — heutiger ungefilterter Inject (`:19`) wird ersetzt |
| `tests/unit/conftest.py` | Unveraendert | sqlite-autouse bleibt tragend |
| `tests/integration/pipeline_engine/test_pipeline_runner.py` | Modifiziert | un-gaten + self-contained |
| `tests/integration/project_ops/install_fresh/test_install_fresh.py` | Modifiziert | un-gaten + self-contained |
| `tests/contract/state_backend/test_postgres_backend.py` | Modifiziert | self-contained (kein Verlass auf `load_*_global(...)[0]`) |
| `tests/contract/state_backend/test_schema_resolver.py` | Neu | Resolver-Vertrag: Default == `ak3_v<slug>`, Override fail-closed |
| `tests/integration/state_backend/test_schema_isolation.py` | Neu | zwei Tests schreiben `TEST-001`, beide gruen |

## 4. Akzeptanzkriterien

1. **Ein einziger Schema-Resolver** ist die SSoT fuer Schema-Name + Bootstrap; die
   sechs Repositories und `postgres_store` nutzen ihn. Kein zweiter
   `CREATE SCHEMA`/`SET search_path`-Pfad existiert mehr (grep-pruefbar).
2. **Identifier-Quoting ueberall**: keine Roh-`f"...{schema}..."`-Interpolation eines
   Schema-Namens in SQL mehr.
3. **Fail-closed Override**: ohne Override == `versioned_postgres_schema_name()`;
   Override nur bei aktivem Gate + Pattern `^ak3test_[a-z0-9_]+$`; sonst `RuntimeError`.
   Belegt durch `test_schema_resolver.py`.
4. **Alle drei Postgres-Suiten** (integration, contract, e2e) sind per Test isoliert;
   das session-scoped `postgres_runtime_env` ist entfernt. **Alle drei Collection-Hooks
   sind pfad-gefiltert** und binden die function-scoped Isolationsfixture nur an Items der
   eigenen Suite: integration -> `/integration/`, e2e -> `/e2e/`, contract -> `/contract/`
   abzueglich `_POSTGRES_INDEPENDENT_CONTRACT_PATHS`. Pure-in-memory-Tests (`core_types/`,
   `project_management/`, `failure_corpus/`, alle Unit-Tests) ziehen **kein** Docker/Postgres
   — der Vollsuite-Lauf ist ohne Docker fuer die Nicht-Postgres-Teilmenge lauffaehig (belegt).
5. **Unit-sqlite-autouse** unveraendert vorhanden und wirksam.
   **`pytest-randomly` + `pytest-xdist`** sind in `[dev]` deklariert (Verifikation aus
   `.[dev]` reproduzierbar); `runtoken` stammt aus xdist `testrun_uid`.
6. **Per-Test-Reset** belegt: `test_schema_isolation.py` schreibt in zwei Tests dieselbe
   Fix-ID und beide laufen gruen.
7. **Cleanup**: Worker-Finalizer droppt das Test-Schema; Registry + 24h-Sweep existieren;
   keine `ak3test_`-Schema-Leiche nach sauberem Lauf.
8. **Gegatete Smoke-Tests un-gated** und gruen (`test_pipeline_runner`, `test_install_fresh`).
9. **Volle Suite gruen unter `pytest-randomly` und `pytest -n auto`** (beides belegt).
10. **Produktion unveraendert**: `current_schema_name()`/Resolver liefern in Produktion
    weiterhin `ak3_v<slug>`; golden/contract-Schnappschuesse unveraendert.
11. **Pflichtbefehle gruen**: pytest (unit+integration+contract); `mypy --strict src`
    **und** `mypy --platform linux src`; `ruff check src tests`; Coverage haelt 85%;
    Sonar Quality Gate OK (0 new violations).

## 5. Definition of Done

- AK 1-11 erfuellt.
- `.venv\Scripts\python -m pytest` gruen (default), zusaetzlich ein Lauf mit `-n auto`.
- `mypy --strict src` und `mypy --platform linux src` gruen; `ruff check src tests` gruen.
- giftige-Codex-Review-Loop bis VERDICT PASS.
- Jenkins gruen + Sonar Quality Gate OK auf dem Ziel-Commit.
- WARNING aus §2.1.5 aktiv an den Auftraggeber gespiegelt.
- Aenderungen committed auf `main`, gepusht.

## 6. Konzept-Referenzen (autoritativ)

- **`concept/methodology/software-blutgruppen.md`** — `state_backend` = T; Refactor bleibt in T.
- **FK-18 §18.9a** — versioniertes Side-by-Side-Schema (unangetastet, nur test-uebersteuerbar).
- **`concept/technical-design/01_...`** — Determinismus, Fail-Closed.

## 7. Guardrail-Referenzen

- **FIX THE MODEL**: Sechsfach-Duplikation der Schema-Aufloesung wird zu einem Resolver
  konsolidiert; kein Test-Sonderpfad neben der Duplikation.
- **SINGLE SOURCE OF TRUTH**: ein Schema-Resolver; Override regex-/gate-erzwungen, in
  Produktion inaktiv.
- **FAIL CLOSED**: Override ohne Gate / falsches Muster -> `RuntimeError`.
- **NO ERROR BYPASSING**: Test-Isolation wird real hergestellt, nicht durch Skip/Gate kaschiert.
- **SEVERITY-SEMANTIK**: das Sweep-Restrisiko (§2.1.5) ist ein WARNING und wird gespiegelt,
  nicht still liegengelassen.

## 8. Hinweise fuer den Sub-Agent

- `Read T:/codebase/claude-agentkit3/CLAUDE.md first — all project rules apply to you.`
- Reihenfolge: zuerst der Resolver-Refactor (§2.1.1/§2.1.2), dann die Fixtures (§2.1.3/§2.1.4),
  zuletzt Un-Gating + Verifikation. Nach dem Resolver-Refactor MUSS die Suite (sqlite-Pfad)
  schon gruen sein, bevor die Fixtures angefasst werden.
- Verifiziere die "sechs Repos umgehen den Resolver"-Annahme zu Beginn selbst per grep
  (`versioned_postgres_schema_name` in `store/`), falls sich die Codebasis verschoben hat.
- mypy IMMER auch mit `--platform linux` pruefen (Jenkins ist Linux; lokaler Windows-Lauf
  verdeckt plattformspezifische Fehler).
- AK2 NICHT veraendern; keine globalen pip-Installs (gemeinsamer Package-Name `agentkit`).
- Bei Konflikt zwischen diesem Briefing und einem Konzept: stoppen und melden.
