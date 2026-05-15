# AG3-020: ProjectConfiguration mit Multi-Repo-Liste (Vorab-Story fuer AG3-014 §2.1.7)

**Typ:** Implementation
**Groesse:** S
**Abhaengigkeiten:** keine
**Owner-BC:** `project-management`
**Quell-Konzepte:**
- FK-02 §2.11.1 (Project-Datenmodell-Anker — `configuration` ist offen formuliert "...")
- DK-10 §10.2 (Repo-Affinitaet; AK3 ist multi-repo-by-design)
- FK-22 (Multi-Repo-Worktrees; AG3-010 hat das implementiert)
- AG3-014 §2.1.7 + AC6 (Konsument der Validierung — wartet auf diese Vorab-Story)

---

## 1. Kontext

AK3 ist nach AG3-010/011 multi-repo-faehig: eine Story kann an mehreren
Repositories arbeiten (`participating_repos` als Liste). Das aktuelle
`ProjectConfiguration`-Schema kennt aber nur eine **einzelne**
`repo_url` und keine Liste der zum Projekt gehoerenden Repos. Das ist
ein Single-Repo-Legacy-Stand und passt nicht zur Multi-Repo-Realitaet.

Konsequenz fuer AG3-014 (Story-Service): die `participating_repos`-
Validierung gegen eine projektweite Allowlist (story.md §2.1.7, AC6)
laeuft heute ins Leere, weil das Feld nicht existiert. Ohne
Validierung kommt **jeder beliebige Repo-Name** in den State —
inklusive Tippfehler und Halluzinationen — und Folgephasen
(Worktree-Setup, Branch-Guard-Scope, ARE-Scope-Aufloesung) brechen
spaeter mit kryptischen Fehlern.

Diese Story schliesst die Schema-Luecke an der richtigen Stelle:
im `project-management`-BC, der Owner der Project-Entitaet ist.
**Sie ist BC-grenzentreu** und blockt AG3-014's Befund 3.

## 2. Scope

### 2.1 In Scope

#### 2.1.1 Schema-Erweiterung
- `ProjectConfiguration` bekommt ein neues Pflichtfeld:
  `repositories: list[str]`, **min 1 Eintrag**, eindeutige
  Eintraege, keine Leerstrings.
- Validator: bei `repo_url` mit Wert MUSS `repo_url` der Hauptzweig
  in `repositories` sein (oder: `repositories` enthaelt `repo_url`-
  Slug) — Entscheidung im Implementation-Schnitt; alternativ
  `repo_url` deprecated und nur noch als Anzeige-Backwards-Compat
  behalten. Empfohlene Variante: `repositories[0]` ist der
  konventionelle "primary" Repo (UI-Konvention analog zur
  `repos[0]`-Konvention aus formal.frontend-contracts.entity.story_summary).

#### 2.1.2 Persistenz
- `projects.configuration_json` ist bereits eine **JSON-Spalte**
  (TEXT in SQLite und Postgres). Keine SQL-Migration noetig.
- **JSON-Migrations-Loader**: bei alten Records ohne
  `repositories`-Feld wird beim Lesen ein Default abgeleitet
  (`[repo_url]` falls `repo_url` gesetzt ist, sonst leere Liste +
  Warning-Log). Das ist Forward-Compat fuer Test-DBs und lokale
  Sandboxes, nicht ein dauerhafter Fallback fuer Produktion.

#### 2.1.3 Project-Lifecycle und API
- `project_management.lifecycle.create_project(...)` akzeptiert
  `repositories: list[str]` als neuen Pflichtparameter.
- Project-HTTP-API (POST `/v1/projects`, PATCH `/v1/projects/{key}/configuration`):
  - `repositories` als Pflichtfeld im Body
  - Validierung: min 1 Eintrag, eindeutig, kein Leerstring →
    sonst `validation_failed` (400) mit `detail.invalid_repos`
- Patch-Pfad: bei Ersetzung der `repositories`-Liste MUSS die neue
  Liste mit den bereits in **aktiven Stories** referenzierten Repos
  konsistent sein. Wer einen Repo aus der Liste nimmt, der noch in
  laufenden Stories steht → `validation_failed` mit
  `detail.repos_still_in_use`. (Optional: zunaechst nur eine Warning
  loggen — Entscheidung im Schnitt, default ist hart fail-closed.)

#### 2.1.4 AG3-014-Integration (downstream hookup)
- `StoryService._get_project_repos(project_key)` liest jetzt aus
  `project.configuration.repositories` statt leerer Liste.
- Die Validierungslogik im Story-Service (story.md §2.1.7) ist
  bereits angelegt; sie greift automatisch, sobald
  `_get_project_repos` echte Werte zurueckgibt.
- AG3-014 AC6 wird damit erfuellbar; das gehoert zur Abschluss-
  Verifikation, ist aber technisch trivial (einzeiliges Lookup).

#### 2.1.5 Bootstrap und Default-Projekt
- `_ensure_default_projects_for_story_contexts` in
  `state_backend/sqlite_store.py` (alle Stellen) baut Default-Project-
  Configurations mit der neuen `repositories`-Liste. Bei Backfill von
  bestehenden Story-Contexts ohne explizite Project-Anlage: wenn
  Story-Context `participating_repos` traegt, werden die ins
  Default-Project-`repositories` injiziert; sonst leere Liste mit
  WARN-Log.

#### 2.1.6 Tests
- Pydantic-Validator (`repositories` min 1, unique, no empty)
- Create-Project happy path + Validierung-Fehlerpfade
- PATCH `/v1/projects/{key}/configuration` mit/ohne Repo-Aenderung
- Repo-aus-Liste-entfernen-mit-aktiver-Story → fail-closed
- JSON-Migrations-Loader (alter Record ohne `repositories` →
  Default-Ableitung + Warning)
- Integration: AG3-014 `StoryService._get_project_repos` liefert
  die echten Repos; Story-Anlage mit unbekanntem Repo wird hart
  abgelehnt (Validierung der vollstaendigen AG3-014 §2.1.7-Kette)

### 2.2 Out of Scope

- Multi-Repo-`repo_url`-Migration mit URL pro Eintrag (heutiges
  `repo_url`-Feld bleibt einfacher String — Entscheidung kann in
  Folge-Story strukturiertem `RepoSpec(name, url, default_branch)`
  ausgebaut werden, falls noetig).
- Frontend-UI-Aenderungen (FK-72) — Wire-Felder bleiben analog zu
  AG3-014 `story_summary.repos`; das ist bereits eine Liste.
- AG3-014-Abschluss (`status: completed`) — gehoert NICHT zu dieser
  Story; AG3-014 schliesst sich nach Integration separat.

## 3. Betroffene Dateien

| Datei | Aenderung |
|---|---|
| `src/agentkit/project_management/entities.py` | `ProjectConfiguration.repositories: list[str]` plus Validatoren |
| `src/agentkit/project_management/lifecycle.py` | `create_project(...)` Signatur und Validierung |
| `src/agentkit/project_management/http/routes.py` | POST `/v1/projects` + PATCH config: `repositories` Pflichtfeld |
| `src/agentkit/project_management/repository.py` | JSON-Migration-Loader (alter Record → Default-Ableitung) |
| `src/agentkit/project_management/errors.py` | ggf. neue Fehlerklasse `ProjectRepositoriesInvalidError` / `ProjectRepoStillInUseError` |
| `src/agentkit/state_backend/sqlite_store.py` | `_ensure_default_projects_for_story_contexts`: Default-Repositories einsetzen |
| `src/agentkit/state_backend/store/project_management_repository.py` (oder analog) | falls Project-Repo dort liegt: JSON-Roundtrip mit neuem Feld |
| `src/agentkit/story_context_manager/service.py` | `_get_project_repos` liest `project.configuration.repositories` |
| `tests/unit/project_management/test_entities.py` | Validator-Tests |
| `tests/unit/project_management/test_lifecycle.py` | create_project + invalid-repos Pfade |
| `tests/unit/project_management/http/test_routes.py` | HTTP-Level-Tests neuer Validierungen |
| `tests/unit/state_backend/test_project_management_repository.py` | JSON-Migrations-Loader-Tests |
| `tests/unit/story_context_manager/test_service.py` | erweitert: unknown_repos wird jetzt blockiert (AG3-014 AC6 wird mit dieser Story erfuellbar) |

## 4. Akzeptanzkriterien

1. `ProjectConfiguration.repositories: list[str]` ist Pflicht, min 1
   Eintrag, unique, kein Leerstring.
2. `create_project` ohne `repositories` → Pydantic-Validation-Fehler.
3. POST `/v1/projects` ohne `repositories` oder mit leerer Liste →
   `validation_failed` (400) mit `detail.invalid_repos`.
4. PATCH `/v1/projects/{key}/configuration` mit `repositories`, die
   einen aktiv genutzten Repo entfernt → `validation_failed` mit
   `detail.repos_still_in_use`.
5. Alter DB-Record ohne `repositories` wird beim Lesen sauber auf
   `[repo_url]` (oder leere Liste mit Warning) projiziert; kein
   Pydantic-Crash.
6. `StoryService._get_project_repos(project_key)` liefert die
   konfigurierten Repos. AG3-014-Test fuer unknown_repos blockt
   eine Story-Anlage mit `repos=["nicht-existent"]` mit
   `validation_failed` und `detail.unknown_repos`.
7. Alle Pflichtbefehle gruen (ruff, mypy --strict src tests,
   pytest tests/unit tests/contract zusammenhaengend,
   check_concept_code_contracts, check_architecture_conformance).

## 5. Definition of Done

- AC1-AC7 erfuellt.
- Sub-Agent verwendet ausschliesslich `.venv` (kein globaler Install).
- AG3-014 ist mit dieser Story integrierbar (story_context_manager
  liest project.configuration.repositories).
- Aenderungen committed und auf `main` gepusht.

## 6. Konzept-Referenzen

- FK-02 §2.11.1 — `Project.configuration` ist offen formuliert
  ("Repo-URL, Default-Branch, ARE-URL, externe Tools,
  Default-Worker-Anzahl, …"); die Erweiterung passt in das `…`.
  Keine Konzeptaenderung noetig.
- DK-10 §10.2 — Repo-Affinitaet ist mehrteilig (PARTICIPATING_REPOS).
- AG3-010/011 — Multi-Repo-Worktrees und Worker-Spawn als
  Geschwister-Stories.
- AG3-014 §2.1.7 — Konsument; AC6 wird durch diese Vorab-Story
  erfuellbar.

## 7. Guardrail-Referenzen

- **FAIL CLOSED**: unbekannte Repos und leere Listen werden hart
  abgelehnt; kein silent-Passthrough.
- **FIX THE MODEL, NOT THE SYMPTOM**: Befund 3 aus dem AG3-014-Review
  wird an der Wurzel geheilt (Schema), nicht durch einen Workaround.
- **BC-GRENZTREUE**: Project-Datenmodell-Erweiterung gehoert in
  `project-management`-BC, nicht in `story_context_manager`.
- **ZERO DEBT**: AG3-014's deferrte Validierung wird damit komplett.

## 8. Hinweise fuer den Sub-Agent

- JSON-Migration ist forward-compat: alte Records ohne
  `repositories` muessen sauber lesbar bleiben (Default-Ableitung).
  Idee: ein `model_validator(mode="before")` in Pydantic, der bei
  fehlendem Feld einen Default setzt + WARN loggt. NICHT
  fail-closed beim Lesen — sonst kaputtes Bootstrap.
- Pruefe `_ensure_default_projects_for_story_contexts` an allen
  Aufrufstellen in `sqlite_store.py` — der bestehende Backfill-Pfad
  muss `repositories` mitschreiben.
- Nicht das `repo_url`-Feld entfernen, nur ergaenzen. Backwards-
  Compat fuer existierende Skripte ist nicht in Scope dieser Story
  und wird in einer Folge-Story aufgeraeumt, falls noetig.
- AK2 (`T:/codebase/claude-agentkit/`) NICHT veraendern. Lesen
  erlaubt zur Orientierung, schreiben verboten. Aber Achtung: AK2
  hat dieses Schema-Feld vermutlich auch nicht — keine Vorlage zum
  Abgucken.
