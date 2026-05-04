# AG3-012: StoryAreLink Edge-Tabelle

**Typ:** Implementation
**Groesse:** S
**Abhaengigkeiten:** keine
**Quell-Konzept:** FK-02 §2.11.4, FK-40 §40.5b

---

## Kontext

FK-40 §40.5b verankert die Story↔ARE-Verknuepfung als Edge-Tabelle
`StoryAreLink` im BC `requirements-and-scope-coverage`. Schema:

| Feld | Typ | Rolle |
|------|-----|-------|
| `story_id` | FK | AK3-Story-ID |
| `are_item_id` | String | externe ARE-Item-Referenz (opak, kein FK) |
| `kind` | Enum | `addresses`, `partial`, `derives_from`, `recurring` |

Eindeutigkeit auf `(story_id, are_item_id, kind)`.

Im Code (`src/agentkit/`) ist die Tabelle nicht angelegt. Lifecycle:
INSERT in Andock-Punkt 1 (Story-Erstellung), UPDATE nur fuer `kind`,
DELETE nur via Story-Reset/Story-Split (FK-40 §40.5b.2).

## Scope

### In Scope

- Pydantic-Modell `StoryAreLink` (z. B. in
  `src/agentkit/requirements_coverage/models.py`)
- Repository-Pattern (analog `StoryDependencyRepository`):
  - `StoryAreLinkRepository` mit `add`, `update_kind`, `remove`,
    `list_by_story`
- SQLite/Postgres-Schema-Erweiterung mit Eindeutigkeits-Constraint
  auf `(story_id, are_item_id, kind)`
- Schema-Versionierung mitziehen (FK-18 §18.9a)
- Tests:
  - INSERT/UPDATE/DELETE
  - Eindeutigkeits-Constraint greift bei Duplikat
  - Mehrfach-Eintraege mit unterschiedlichem `kind` zulaessig
  - `list_by_story` liefert deterministische Reihenfolge

### Out of Scope

- ARE-Andock-Punkte (Story-Anlage triggert INSERT — separate Story
  oder Teil von Story-Service-Backend)
- Stale-`are_item_id`-Detection (FK-40 §40.5b.5 — Folge-Story bei
  ARE-Gate-Implementierung)
- Frontend-Lese-API-Endpoints (FK-40 §40.10 — Folge-Story)

## Betroffene Dateien

| Datei | Aenderungsart | Beschreibung |
|-------|---------------|--------------|
| `src/agentkit/requirements_coverage/models.py` | Neu | StoryAreLink + Kind-Enum |
| `src/agentkit/state_backend/store/story_are_link_repository.py` | Neu | Repository |
| `src/agentkit/state_backend/sqlite_store.py` | Modifiziert | Schema-Erweiterung |
| `src/agentkit/state_backend/postgres_schema.sql` | Modifiziert | Schema-Erweiterung |
| `src/agentkit/state_backend/config.py` | Modifiziert | SCHEMA_VERSION-Bump |
| `tests/unit/requirements_coverage/test_story_are_link_repository.py` | Neu | Repository-Tests |

## Akzeptanzkriterien

1. `StoryAreLink` Pydantic-Modell mit den drei Feldern + 4 Kind-Enum-Werten.
2. Repository unterstuetzt add/update_kind/remove/list_by_story.
3. Eindeutigkeits-Constraint `(story_id, are_item_id, kind)` greift.
4. Schema-Versionierung Side-by-Side; alte DB unangetastet.
5. Tests gruen, Lints clean.

## Definition of Done

- Build kompiliert
- Tests gruen
- mypy strict
- Sowohl SQLite als auch Postgres-Schema aktualisiert

## Konzept-Referenzen

- FK-02 §2.11.4 — StoryAreLink Schema
- FK-40 §40.5b — Persistenz-Verantwortung, Lifecycle, Schreibwege
- FK-18 §18.9a — Schema-Versionierung Side-by-Side

## Guardrail-Referenzen

- SINGLE SOURCE OF TRUTH: Schema in einem Pydantic-Modell, das
  Repository darauf
- FAIL CLOSED: Eindeutigkeits-Constraint, kein silent-overwrite
