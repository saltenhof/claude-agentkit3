# project-management — GAP-Analyse

> Generiert von einem dedizierten Sonnet-Sub-Agent (Stand 2026-05-16).

## Header

| Feld | Wert |
|---|---|
| BC-ID | `project-management` |
| Display-Name | `Project-Management (Project-Entitaet, ID-Praefix-Schema, Konfiguration)` |
| Analyse-Datum | `2026-05-16` |
| Konzept-Quellen (autoritativ) | `DK-14, FK-73, formal.frontend-contracts.entities, formal.frontend-contracts.commands` |
| Codebase-Hauptpfade | `src/agentkit/project_management/, src/agentkit/state_backend/store/project_management_repository.py` |

## 1. Executive Summary

Der BC project-management ist fachlich gut ausgereift: Domain-Entitaet `Project`, Lifecycle-Operationen (create/update/archive), HTTP-Routing und das SQLite-Storage-Backend sind vollstaendig umgesetzt. Die Stories AG3-014 (Story-Service Backend) und AG3-020 (Multi-Repo-Liste) wurden zuletzt abgeschlossen und haben die `repositories`-Pflichtliste sowie den Repo-in-Use-Guard integriert. Drei Luecken praegen das Restbild: (1) Das Wire-Format des GET-Endpunkts liefert nicht die in `formal.frontend-contracts.entities` geforderte `status`-Enum-Projektion (active/archived), sondern rohe Pydantic-Felder; (2) die Frontend-Entitaeten `project_detail`, `project_mode_lock`, `story_counters` und `concept_anchors` existieren weder als serverseitige Aggregation noch als Endpunkt; (3) Postgres-Storage ist ein Stub ohne vollstaendige Projekt-Tabellen-Unterstuetzung.

| Kategorie | Anzahl |
|---|---|
| A — Nicht umgesetzt | 4 |
| B — Teilweise umgesetzt | 3 |
| C — Drift / Fehler | 1 |

## 2. Konzept-Soll (Kurzfassung)

- **Project-Entitaet mit key, name, story_id_prefix (immutable), configuration** — `FK-73.md §73.1`
- **Lifecycle-Uebergaenge create / update / archive (kein Re-Aktivieren in v1)** — `FK-73.md §73.2`
- **API-Endpunkte GET /v1/projects, GET /v1/projects/{key}, POST /v1/projects, PATCH /v1/projects/{key}, POST /v1/projects/{key}/archive** — `FK-73.md §73.3`
- **Postgres als single source of truth (Tabelle projects, JSONB configuration, Unique Index auf story_id_prefix, archived_at Timestamp)** — `FK-73.md §73.4`
- **Wire-Entitaet project_summary mit Feldern project_key, display_name, status (active|archived)** — `formal.frontend-contracts.entities §entities.project_summary`
- **Wire-Entitaet project_detail mit mode_lock, story_counters, concept_anchors** — `formal.frontend-contracts.entities §entities.project_detail`
- **Wire-Entitaet project_mode_lock (mode: idle|standard|fast) abgeleitet aus laufenden Stories (FK-24)** — `formal.frontend-contracts.entities §entities.project_mode_lock`
- **Wire-Entitaet story_counters (total, finished, running, ready, queue, blocked)** — `formal.frontend-contracts.entities §entities.story_counters`
- **repositories-Liste als Pflichtfeld (min 1, keine Duplikate, repo_url muss darin enthalten sein)** — `FK-73.md §73.1`, `DK-14.md §2`
- **project_key als Cross-Cutting-Filter-Ursprung fuer alle BC-Tabellen** — `FK-73.md §73.5`
- **Abgrenzung: Bootstrap liefert lauffaehiges System, Project-Management legt erstes Projekt an** — `FK-73.md §73.6`, `DK-14.md §6`

## 3. Code-Stand (Ist-Bild)

- `src/agentkit/project_management/entities.py:ProjectConfiguration` — Pydantic-Modell mit repo_url, default_branch, are_url, default_worker_count, repositories (min_length=1, Duplikat-Pruefung, repo_url-Konsistenz-Validator)
- `src/agentkit/project_management/entities.py:Project` — kanonische Domain-Entitaet mit key-Pattern-Validator und story_id_prefix-Pattern-Validator, frozen/immutable
- `src/agentkit/project_management/lifecycle.py:create_project` — erstellt Project, erzwingt repositories-Pflicht via _validate_repositories_for_write, Override-Semantik fuer repositories-Kwarg
- `src/agentkit/project_management/lifecycle.py:update_configuration` — mutiert name/configuration, sperrt key/story_id_prefix, enforced repositories-Min-1 bei explizitem Update
- `src/agentkit/project_management/lifecycle.py:archive_project` — setzt archived_at, verwirft Doppel-Archivierung
- `src/agentkit/project_management/repository.py:ProjectRepository` — Protocol (get, list, save)
- `src/agentkit/project_management/errors.py` — vollstaendiges Fehlermodell (ProjectImmutableFieldError, ProjectAlreadyArchivedError, ProjectNotFoundError, ProjectStoryIdPrefixConflictError, ProjectRepositoriesInvalidError, ProjectRepoStillInUseError)
- `src/agentkit/project_management/http/routes.py:ProjectManagementRoutes` — HTTP-Handler fuer GET/POST/PATCH-Routen, Korrelations-Header, repos_in_use_checker-Guard, PATCH /v1/projects/{key}/configuration (extra Route, nicht in FK-73 §73.3 aufgefuehrt)
- `src/agentkit/state_backend/store/project_management_repository.py:StateBackendProjectRepository` — SQLite-backed Implementierung via state-backend-Fassade, story_id_prefix-Eindeutigkeitsschutz
- `src/agentkit/state_backend/sqlite_store.py` — SQLite-Tabelle `projects` mit key, name, story_id_prefix, configuration_json (TEXT, kein JSONB), archived_at
- `tests/unit/project_management/test_entities.py` — Entity-Invarianten-Tests
- `tests/unit/project_management/test_lifecycle.py` — Lifecycle-Unit-Tests inkl. AG3-020-Repos-Faelle
- `tests/unit/project_management/http/test_routes.py` — HTTP-Routen-Unit-Tests
- `tests/unit/project_management/test_repository.py` — Repository-Unit-Tests

## 4. GAP-Analyse

> **Wichtig:** Jede Zeile in einer der drei Tabellen muss mindestens
> eine konkrete Doc-Referenz tragen. Code-Referenzen sind in den
> Tabellen B und C Pflicht, in Tabelle A optional (weil dort gerade
> kein Code existiert).

### 4.1 A — Nicht umgesetzt

| # | Thema | Konzept-Referenz | Anmerkung |
|---|---|---|---|
| A1 | Wire-Entitaet `project_detail` (mode_lock, story_counters, concept_anchors) fehlt vollstaendig als Server-Aggregation | `formal.frontend-contracts.entities §entities.project_detail` | GET /v1/projects/{key} liefert heute rohe Project-Entity-Felder; keine Aggregation aus Story-Countern oder mode_lock |
| A2 | Wire-Entitaet `project_mode_lock` (idle/standard/fast aus laufenden Stories) nicht implementiert | `formal.frontend-contracts.entities §entities.project_mode_lock` | Erfordert Cross-BC-Abfrage gegen story-lifecycle; kein Endpunkt, keine Projektionslogik vorhanden |
| A3 | Wire-Entitaet `story_counters` (total, finished, running, ready, queue, blocked) nicht implementiert | `formal.frontend-contracts.entities §entities.story_counters` | Muss aus story_contexts aggregiert werden; fehlt im project_management-HTTP-Handler vollstaendig |
| A4 | `concept_anchors` (projektweite normative Verweise fuer Inspector-Tab) fehlt als Datenfeld und API | `formal.frontend-contracts.entities §entities.project_detail` | Kein Feld in ProjectConfiguration, kein API-Feld; noch kein Schema-Entwurf |

### 4.2 B — Teilweise umgesetzt

| # | Thema | Code-Referenz | Konzept-Referenz | Was fehlt |
|---|---|---|---|---|
| B1 | Wire-Format GET /v1/projects: `status`-Enum-Feld fehlt | `src/agentkit/project_management/http/routes.py:_project_payload` | `formal.frontend-contracts.entities §entities.project_summary` | `_project_payload` nutzt `project.model_dump(mode="json")`, das `archived_at` als Timestamp ausgibt, aber nicht das geforderte `status`-Enum (`active`/`archived`) als eigenstaendiges Feld projiziert; `project_key` und `display_name` sind ebenfalls nicht explizit nach Vertrag umbenannt |
| B2 | Postgres-Storage: Tabellen-Definition und JSONB-Constraint fehlen | `src/agentkit/state_backend/postgres_store.py` | `FK-73.md §73.4` | FK-73 §73.4 fordert Postgres als primary storage mit JSONB-Spalte fuer configuration, Unique Index auf story_id_prefix und archived_at-Timestamp; die postgres_store.py enthaelt keine vollstaendige projects-Tabellen-DDL (nur SQLite hat sie); Postgres-Path ist fuer project_management nicht produktionsreif |
| B3 | PATCH /v1/projects/{key}/configuration — ausservertragliche Zusatz-Route | `src/agentkit/project_management/http/routes.py:_PROJECT_CONFIG_PATH` | `FK-73.md §73.3` | FK-73 §73.3 katalogisiert `PATCH /v1/projects/{key}` als einzigen Update-Endpunkt; die Implementierung hat zusaetzlich `PATCH /v1/projects/{key}/configuration`. Funktional ist das kein Bug, aber FK-91 (API-Katalog) muss diesen Endpunkt noch enthalten |

### 4.3 C — Drift / Fehler

| # | Thema | Code-Referenz | Konzept-Referenz | Drift / Fehler |
|---|---|---|---|---|
| C1 | `_project_payload` serialisiert rohe Entity-Felder statt vertragsgemaessem Wire-Shape | `src/agentkit/project_management/http/routes.py:_project_payload` | `formal.frontend-contracts.entities §entities.project_summary`, `formal.frontend-contracts.entities §entities.project_detail` | Das Frontend-Contract verlangt `project_key` (nicht `key`), `display_name` (nicht `name`) und ein explizites `status: active|archived` Enum-Feld. Der aktuelle Code liefert die Python-Modell-Felder (`key`, `name`, `archived_at`) unveraendert — ein stiller Wire-Vertragbruch, der Frontend-Code brechen wuerde, der den Contract als Quelle der Wahrheit nutzt |

## 5. Ableitungen / Empfehlungen

1. **Wire-Payload-Konformitaet herstellen (Blocker fuer Frontend-Integration):** `_project_payload` muss `key` -> `project_key`, `name` -> `display_name` umbenennen und ein `status`-Feld (`"active"` wenn `archived_at is None`, sonst `"archived"`) hinzufuegen. Das ist ein sehr kleiner Code-Change mit hohem Konformitaetsgewinn; Contract-Test in `tests/contract/` beifuegen (formal.frontend-contracts.entities).

2. **Postgres-Storage fuer project-management vervollstaendigen:** FK-73 §73.4 setzt Postgres als single source of truth voraus. Solange postgres_store.py keine vollstaendige projects-Tabellen-DDL hat, ist Produktionsbetrieb auf SQLite beschraenkt. Die postgres_store.py-Luecke schliesst die Migration zu Produktions-Postgres. Prioritaet mittel, aber Blocker vor Go-Live.

3. **Frontend-Entitaeten project_detail / project_mode_lock / story_counters aggregieren:** Diese drei Entitaeten sind fuer die Topbar und KpiBar des Frontends (FK-72, formal.frontend-contracts.entities) unverzichtbar. Sie erfordern Cross-BC-Queries gegen story-lifecycle. Empfehlung: als BFF-Aggregationslayer im control_plane_http oder als dedizierte Projektion in project_management definieren. Design-Entscheidung vor Implementierungsstart klaeren.

4. **PATCH /v1/projects/{key}/configuration in FK-91 nachfuehren:** Die Zusatzroute ist funktional sinnvoll, aber im API-Katalog (FK-91) nicht vermerkt. Entweder als offiziellen Endpunkt in FK-91 aufnehmen oder in den Standard-PATCH /v1/projects/{key} zusammenfuehren. Kein Blocking-Issue, aber ZERO DEBT erfordert Konsistenz zwischen Impl und Katalog.

## 6. Suchstrategie & Quellen

- **Vollstaendig gelesen:**
  - `concept/domain-design/14-project-management.md`
  - `concept/technical-design/73_project_management.md`
  - `concept/formal-spec/frontend-contracts/entities.md`
  - `concept/formal-spec/frontend-contracts/commands.md`
  - `concept/technical-design/_meta/domain-registry.yaml`
  - `src/agentkit/project_management/entities.py`
  - `src/agentkit/project_management/lifecycle.py`
  - `src/agentkit/project_management/repository.py`
  - `src/agentkit/project_management/errors.py`
  - `src/agentkit/project_management/http/routes.py`
  - `src/agentkit/project_management/__init__.py`
  - `src/agentkit/state_backend/store/project_management_repository.py`
  - `tests/unit/project_management/test_lifecycle.py`
  - `tests/unit/project_management/test_entities.py`
- **Punktuell gelesen:**
  - `concept/_meta/bc-cut-decisions.md` (project-management-relevante Abschnitte)
  - `src/agentkit/state_backend/sqlite_store.py` (projects-Tabellen-DDL, Zeilen 110-170)
  - `src/agentkit/state_backend/postgres_store.py` (project_row-Funktionen, Zeilen 1-30)
  - `src/agentkit/state_backend/store/facade.py` (load_project/save_project-Aufrufe)
- **Code-Scan (Glob/Grep):**
  - Pattern `src/agentkit/project*/**/*.py`: alle Python-Module im BC ermitteln
  - Pattern `tests/**/test_project*.py` und `tests/**/project_management/**`: Test-Abdeckung sichten
  - Pattern `project_summary|project_detail|project_mode_lock|concept_anchors` in `src/`: Wire-Entitaeten-Implementierung pruefen (Ergebnis: kein Treffer ausser route-interne Path-Regex)
  - Pattern `_project_payload` in routes.py: Wire-Format-Serialisierung verstehen
  - Pattern `status.*active|archived_at` in project_management/: Status-Enum-Feld pruefen
