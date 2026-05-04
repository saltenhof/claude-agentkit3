# AG3-014: AK3 Story-Service Backend

**Typ:** Implementation
**Groesse:** L
**Abhaengigkeiten:** keine
**Quell-Konzept:** FK-21 (Story-Erstellung), FK-22 §22.3 (Preflight-Checks gegen Story-Backend), DK-10 (Story-Lifecycle)

---

## Kontext

Nach den Konzept-Cleanups `8327852` (GitHub Projects) und `51bf521`
(GitHub Issues + GraphQL) ist Story- und Projektverwaltung komplett
ueber das **AK3-eigene Backend** zu fuehren. Die ehemals als GitHub-
Project-Custom-Fields gepflegten Felder sind jetzt **native Story-
Attribute** im AK3-Backend. Status-Werte
`Backlog/Approved/In Progress/Done/Cancelled` bleiben.

`StoryContext` und `StoryContextManager` sind teilweise da
(`src/agentkit/story_context_manager/`), aber nicht vollstaendig als
Service-Backend ausgepraegt. Diese Story baut den autoritativen
AK3-Story-Service auf.

## Scope

### In Scope

- Story-Modell (Pydantic, `src/agentkit/story/models.py`):
  - `story_id`, `title`, `description`, `story_type`, `size`,
    `status` (StatusEnum), `participating_repos`, `change_impact`,
    `new_structures`, `concept_quality`, `concept_paths`,
    `external_sources`, `guardrail_paths`, `acceptance_criteria`,
    `definition_of_done`, `solution_approach`, `dependencies`
    (Liste von Story-IDs), `created_at`, `updated_at`,
    `completed_at`, `vectordb_conflict`, `module`
  - Status-Enum: `Backlog`, `Approved`, `InProgress`, `Done`, `Cancelled`
  - Validierung: `participating_repos` Eintraege muessen in
    `project.repositories[]` existieren
- `StoryService` mit Operationen:
  - `create_story(...)` (Status: Backlog)
  - `update_attributes(...)`
  - `set_status(story_id, new_status)` (mit Lifecycle-Validierung,
    nur erlaubte Transitionen)
  - `get_story(story_id)`
  - `list_stories(filters)`
  - `get_dependencies(story_id)`
  - `add_dependency(story_id, depends_on_story_id, kind)`
  - `remove_dependency(...)`
- Repository (StateBackend):
  - SQLite + Postgres
  - Schema-Erweiterung; Schema-Versionierung mitziehen (FK-18 §18.9a)
- Preflight-Adapter:
  - Check `story_exists` (FK-22 §22.3.1 Check 1) gegen Story-Service
  - Check `status_approved` (FK-22 §22.3.1 Check 3) gegen Story-Service
  - Check `dependencies_closed` (FK-22 §22.3.1 Check 4) ueber
    `StoryDependencyRepository`
- Tests:
  - Story-Anlage/Status-Transitionen
  - Preflight-Checks gegen synthetisches Story-Backend
  - participating_repos-Validierung
  - dependency_closed-Logik

### Out of Scope

- Story-Erstellungs-Skill (FK-21; UI-/Skill-seitig)
- Story-Reset/Split-Service (FK-53/54 — separate Stories)
- Frontend-API (existiert als Konzept FK-72, separate Implementations)
- ARE-Bundle-Loader (FK-22 §22.4b — separate Story)

## Betroffene Dateien

| Datei | Aenderungsart | Beschreibung |
|-------|---------------|--------------|
| `src/agentkit/story/models.py` | Neu/Erweitert | Story-Pydantic + StatusEnum |
| `src/agentkit/story/service.py` | Neu/Erweitert | StoryService |
| `src/agentkit/story/repository.py` | Neu/Erweitert | Repository-Interface |
| `src/agentkit/state_backend/store/story_repository.py` | Neu | SQLite/Postgres |
| `src/agentkit/pipeline/phases/setup/preflight.py` | Modifiziert | Checks 1/3/4 gegen Service |
| `src/agentkit/state_backend/sqlite_store.py` | Modifiziert | Schema |
| `src/agentkit/state_backend/postgres_schema.sql` | Modifiziert | Schema |
| `src/agentkit/state_backend/config.py` | Modifiziert | SCHEMA_VERSION |
| `tests/unit/story/test_service.py` | Neu | umfangreich |
| `tests/unit/pipeline/phases/setup/test_preflight.py` | Erweitert | Checks 1/3/4 |

## Akzeptanzkriterien

1. Story kann angelegt werden, Status-Transitionen folgen einem
   definierten Lifecycle (kein freier Sprung von Cancelled zurueck zu
   Approved etc.).
2. Preflight-Checks 1, 3, 4 laufen gegen den Service, nicht gegen
   GitHub.
3. participating_repos-Validierung blockiert Story-Anlage mit
   unbekanntem Repo.
4. Dependency-Pruefung erkennt offene Vorgaenger-Stories.
5. Schema-Versionierung Side-by-Side; alte DB unangetastet.
6. Tests gruen, Lints clean.

## Definition of Done

- Build kompiliert
- Tests gruen (Service + Preflight + Repository)
- mypy strict
- Sowohl SQLite als auch Postgres-Schema migriert

## Konzept-Referenzen

- FK-21 — Story-Creation-Pipeline (Status-Transitionen)
- FK-22 §22.3.1 — Preflight-Checks 1, 3, 4
- DK-10 — Story-Lifecycle
- FK-18 §18.9a — Schema-Versionierung
- FK-02 §2.11 — Persistenz-Anker

## Guardrail-Referenzen

- FIX THE MODEL, NOT THE SYMPTOM: ein Story-Service als autoritative
  Quelle, kein zweites Schattenfeld
- ZERO DEBT: alle Pflicht-Attribute durch
- FAIL CLOSED: ungueltige Status-Transitionen werden hart abgelehnt
