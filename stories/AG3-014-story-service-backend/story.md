# AG3-014: AK3 Story-Service Backend (Frontend-Contract-konform)

**Typ:** Implementation
**Groesse:** L
**Abhaengigkeiten:** keine harten (baut auf Vorarbeiten in `story_context_manager/` und `story/`)
**Quell-Konzepte (autoritativ, in dieser Reihenfolge):**
- **FK-91 §91.1a** (Service-API, Regeln 1-10 — Idempotenz, correlation_id, Fehler-Vertrag, Story-Wahrheit ausschliesslich ueber Control-Plane)
- **`formal.frontend-contracts.entities`** (Wire-Sicht der Story-Read-Models)
- **`formal.frontend-contracts.commands`** (Mutations + Fehler-Codes + forbidden_inputs)
- **`formal.frontend-contracts.invariants`** (Status-Transitions, op_id, Race)
- **`formal.frontend-contracts.events`** (`story_upserted`, `story_deleted`)
- **FK-02 §2.11.2** (Story-Identitaet: `story_uuid`, `(project_key, story_number)`, materialisierte Anzeige-ID)
- **FK-21** (Story-Creation-Pipeline) und **FK-22 §22.3.1** (Preflight-Checks gegen Service)
- **DK-10** (Story-Lifecycle, fuenf Status-Werte)
- **`formal.story-workflow.invariants`** (interne Pause/Escalation aendert Story-Status nicht)
- **FK-18 §18.9a** (Schema-Versionierung, AG3-005)

---

## 1. Kontext und Owner-BC

Owner-BC ist **`story_context_manager`** (FK-02 §2.11.2), **nicht** ein
neues generisches `story/`-Modul. Das `src/agentkit/story/`-Paket ist
ein Read-Model-Adapter (StorySummary/StoryDetail aus
AG3-002/003-Vorarbeiten); es bleibt als Wire-Projektion erhalten und
wird gegen den autoritativen Service hier zugeschnitten.

Aktueller Code-Stand (Vorarbeiten, nicht doppelt bauen):

| Pfad | Status | Was schon da ist |
|---|---|---|
| `src/agentkit/story_context_manager/lifecycle.py` | vorhanden | `create_story()`-Initialanlage (Story-Identitaet, project_key, Projekt-Praefix-Materialisierung) |
| `src/agentkit/story_context_manager/models.py` | vorhanden | `StoryContext`, `PhaseStatus`, `PhaseName`, `ClosurePayload` etc. — langlebige Story-Semantik |
| `src/agentkit/story_context_manager/repository.py` | vorhanden | `StoryContextRepository`-Protocol |
| `src/agentkit/story_context_manager/errors.py` | vorhanden | `StoryProjectNotFoundError`, `StoryProjectArchivedError`, `StoryIdentityConflictError` |
| `src/agentkit/story_context_manager/http/routes.py` | vorhanden | Routen-Hook im HTTP-Layer |
| `src/agentkit/story/{models,repository,service}.py` | vorhanden | Read-Model-Sicht fuer `GET /v1/stories[/{id}]` (Dashboard) |
| `src/agentkit/state_backend/store/story_context_repository.py` | vorhanden | Persistenz-Adapter fuer StoryContext |
| `src/agentkit/state_backend/store/story_dependency_repository.py` | vorhanden | Dependency-Edge-Tabelle (AG3-014 setzt nichts neu auf, sondern integriert) |
| `src/agentkit/state_backend/store/planning_story_repository.py` | vorhanden | Planning-Read-Model (joined `wave`, `critical_path`) |
| `src/agentkit/control_plane/http.py` | vorhanden | Routing-Skelett `^/v1/stories...`-Pattern |

Diese Story **erweitert** den existierenden `story_context_manager`-BC
um den vollstaendigen Service-Vertrag aus FK-91 §91.1a und den
`formal.frontend-contracts.*`-Specs.

---

## 2. Scope

### 2.1 In Scope

#### 2.1.1 Datenmodell — Story-Identitaet (FK-02 §2.11.2)

Story-Identitaet ist dreifach:

- `story_uuid: UUID` — technischer Primaerschluessel, global eindeutig
- `(project_key, story_number)` — fachlich eindeutig pro Projekt; `story_number` ist projektlokal monoton, **atomar** im `story_context_manager` allokiert
- `story_display_id: str` — z.B. `"AK3-042"`. Wird beim `create_story` aus `Project.story_id_prefix + story_number` einmalig materialisiert und im Story-Record persistiert. URL-Param `{story_id}` der API referenziert den `story_display_id`. **Pflicht-Lookup** ueber den `ProjectRepository`.

Eindeutigkeitsbedingungen: UNIQUE `(project_key, story_number)`, UNIQUE
`story_uuid`. `story_display_id` ist daraus deterministisch ableitbar
und in einem Spaltenfeld materialisiert.

#### 2.1.2 Datenmodell — Story-Stammdaten

Pydantic-Modell `Story` mit den Pflichtfeldern aus
`formal.frontend-contracts.entity.story_summary`:

| Feld | Typ | Wire (Frontend) | Intern (Service) | Pflicht |
|---|---|---|---|---|
| `story_uuid` | UUID | – | `story_uuid` | ja |
| `project_key` | string | `project_key` | `project_key` | ja |
| `story_id` (Wire) | string | `story_id` | `story_display_id` | ja |
| `story_number` | int | – | `story_number` | ja (intern) |
| `title` | string | `title` | `title` | ja |
| `type` | StoryType | `type` | `story_type` | ja |
| `status` | StoryStatus | `status` (Wire: `"In Progress"` mit Leerzeichen) | `status` | ja |
| `size` | StorySize | `size` | `size` | ja |
| `mode` | StoryMode \| None | `mode` (default `standard` wenn None) | `mode` | nein |
| `epic` | string | `epic` | `epic` | ja |
| `module` | string | `module` | `module` | ja |
| `repos` (Wire-Name) | list[str], min 1 | `repos` | **`participating_repos`** (FK-21-Sprache) | ja |
| `change_impact` | ChangeImpact | `change_impact` | `change_impact` | ja |
| `concept_quality` | ConceptQuality | `concept_quality` | `concept_quality` | ja |
| `owner` | string | `owner` | `owner` | ja |
| `risk` | RiskLevel | `risk` | `risk` | ja |
| `blocker` | string \| None | `blocker` | `blocker` | nein |
| `dependencies` | list[str] | `dependencies` (Liste `story_display_id`) | — (via `StoryDependencyRepository`) | ja (leer erlaubt) |
| `labels` | list[str] | `labels` | `labels` | nein |
| `qa_rounds` | int | `qa_rounds` | – (Read-Model-Join von `telemetry`) | ja |
| `qa_rounds_exploration` / `_implementation` | int \| None | dito | dito | nein |
| `wave` | int | `wave` | – (Read-Model-Join von `planning_story_repository`) | ja |
| `critical_path` | bool | `critical_path` | – (Read-Model-Join) | ja |
| `processing_time` | string \| None | `processing_time` | – (Read-Model-Join `runtime.phase`) | nein |
| `created_at` | timestamp | `created_at` (system-managed) | `created_at` | nein (aber Wire-konform setzen) |
| `completed_at` | timestamp | `completed_at` (system-managed) | `completed_at` | nein |
| `runtime` | ref \| None | `runtime` (nur bei In Progress) | (lazy join) | nein |

**Enum-Werte exakt nach Wire-Vertrag:**

- `StoryStatus`: `"Backlog"`, `"Approved"`, `"In Progress"` (mit Leerzeichen!), `"Done"`, `"Cancelled"` — Python-Enum mit `value="In Progress"` aber Name `IN_PROGRESS`
- `StoryType`: `implementation`, `bugfix`, `concept`, `research`
- `StorySize`: `XS`, `S`, `M`, `L`, `XL`, `XXL`
- `StoryMode`: `standard`, `fast` (None wird wie `standard` interpretiert)
- `ChangeImpact`: `Local`, `Component`, `Cross-Component`, `Architecture Impact`
- `ConceptQuality`: `High`, `Medium`, `Low`
- `RiskLevel`: `low`, `medium`, `high`

**Wire-vs-Internal-Adapter** uebersetzt `participating_repos` ↔ `repos`
und `status="In Progress"` ↔ `StoryStatus.IN_PROGRESS`. Internes Modell
behaelt FK-21-Sprache, API-Layer projiziert auf Wire.

#### 2.1.3 Datenmodell — Story-Specification (Sub-Entity)

Eigene Pydantic-Klasse `StorySpecification` (1:1 zu Story, eigene
Tabelle `story_specifications`, FK auf `story_uuid`):

- `need: string | None` (Problemstellung)
- `solution: string | None` (Loesungsansatz)
- `acceptance: list[str]` (Pflicht; min 0 Eintraege, leere Liste erlaubt)
- `definition_of_done: list[str] | None`
- `concept_refs: list[str] | None`
- `guardrail_refs: list[str] | None`
- `external_sources: list[str] | None`

Gerendert in `story_detail.spec` (formal.frontend-contracts.entity.story_specification).

#### 2.1.4 StoryService — Top-Surface

Modul: `src/agentkit/story_context_manager/service.py` (neu, oder
Erweiterung der `lifecycle.py`). Die Operationen folgen dem Wire-
Vertrag aus `formal.frontend-contracts.commands`.

| Operation | HTTP-Endpoint (FK-91 §91.1a) | Wire-Command-ID | Initial-Status erlaubt | Resultierender Status |
|---|---|---|---|---|
| `create_story(...)` | `POST /v1/stories` | `create_story` | – | `Backlog` |
| `update_story_fields(...)` | `PATCH /v1/stories/{id}` | `update_story_fields` | beliebig | unveraendert |
| `approve_story(...)` | `POST /v1/stories/{id}/approve` | `approve_story` | `Backlog` | `Approved` |
| `reject_story(...)` | `POST /v1/stories/{id}/reject` | `reject_story` | `Approved` | `Backlog` |
| `cancel_story(...)` | `POST /v1/stories/{id}/cancel` | `cancel_story` | `{Backlog, Approved}` | `Cancelled` |
| `get_story(...)` | `GET /v1/stories/{id}` | – | – | – |
| `list_stories(...)` | `GET /v1/stories` | – | – | – |
| `search_stories(q)` | `GET /v1/projects/{project_key}/stories/search` | – | – | – |
| `get_story_fields(...)` | `GET /v1/stories/{id}/fields` | – | – | – |
| `set_story_field(field_key, value)` | `PUT /v1/stories/{id}/fields/{field_key}` | – | – | – |
| **Pipeline-only**: `begin_progress(story_id)` | impliziert durch `POST /v1/story-runs/{run_id}/phases/setup/start` | – | `Approved` | `In Progress` |
| **Pipeline-only**: `complete_story(story_id)` | impliziert durch `POST /v1/story-runs/{run_id}/closure/complete` | – | `In Progress` | `Done` |
| `get_dependencies(story_id)` | – (existing repo) | – | – | – |
| `add_dependency(story_id, depends_on)` | – | – | – | – |
| `remove_dependency(story_id, depends_on)` | – | – | – | – |

Beide Pipeline-only-Operationen werden **nicht** vom Frontend
aufgerufen. Sie sind interne Top-Surface des Service, von Setup-Phase
bzw. Closure-Sequence getriggert. Frontend hat keinen Pfad, um eine
Story manuell auf `In Progress` oder `Done` zu setzen
(Invariante `frontend-contracts.invariant.status_transitions_only_via_endpoints`
plus `formal.story-workflow.invariant.completion_only_after_closure`).

#### 2.1.5 Idempotenz (FK-91 §91.1a Regel 5)

Jeder mutierende Endpoint (`create_story`, `update_story_fields`,
`approve_story`, `reject_story`, `cancel_story`, `set_story_field`)
nimmt `op_id: string` als Pflichtparameter.

Mechanik:

- Tabelle `idempotency_keys` (oder analoge Persistenz) mit Spalten
  `op_id` (PK), `body_hash` (SHA-256 des kanonisierten Request-Bodys),
  `result_payload` (JSON), `created_at`, `correlation_id`.
- Eintreffender Request mit existierendem `op_id`:
  - selber `body_hash` → liefert `result_payload` zurueck, **keine
    zweite Mutation**
  - abweichender `body_hash` → `idempotency_mismatch` (409)

Lebensdauer: mindestens 24h (oder bis Story terminal beendet).

#### 2.1.6 Fehler-Vertrag (FK-91 §91.1a Regel 7+8, formal.frontend-contracts.commands)

Typisierte Service-Fehler:

| Service-Exception | `error_code` | HTTP | Wann |
|---|---|---|---|
| `StoryValidationError` | `validation_failed` | 400 | Pflichtfeld fehlt, Enum ungueltig, `repos` leer, unbekannter Repo (siehe 2.1.7) |
| `StoryNotFoundError` | `story_not_found` | 404 | `story_id` (Display-ID) ist unbekannt |
| `InvalidStatusTransitionError` | `invalid_transition` | 422 | approve/reject/cancel auf falschen Initial-Status getroffen |
| `IdempotencyMismatchError` | `idempotency_mismatch` | 409 | gleiche `op_id` mit abweichendem Body |
| `ForbiddenFieldError` | `forbidden_field` | 422 | PATCH enthaelt `status`, `created_at` oder `completed_at` |
| `StoryProjectArchivedError` / `ForbiddenError` | `forbidden` | 403 | Projekt archiviert oder Auth-Scope fehlt |
| `StoryConcurrencyConflictError` | `conflict` | 409 | optimistisches Locking auf Story-Record (nur falls noetig) |
| catch-all | `internal_error` | 500 | unerwartete Backend-Fehler; Retry mit derselben `op_id` erlaubt |

Antwort-Schema (Pflicht-Felder): `error_code`, `error` (Human-Readable),
`correlation_id`, optional strukturiertes `detail`. `correlation_id`
wird aus Request-Header `X-Correlation-Id` uebernommen oder vom
Service generiert und im Response-Header zurueckgegeben (Regel 7).

#### 2.1.7 Validierung — participating_repos / repos

Beim `create_story` und beim `update_story_fields` muss `repos` (Wire)
gegen `Project.configuration.repositories[]` validiert werden. Repos
ausserhalb der projekt-konfigurierten Liste → `validation_failed`
(400) mit strukturiertem `detail.unknown_repos`.

`update_story_fields` mit `repos=[]` (leere Liste) →
`validation_failed` (400, "min 1 repo required"; `formal.frontend-contracts.entity.story_summary.repos`).

#### 2.1.8 forbidden_inputs (PATCH)

`update_story_fields` lehnt jedes der folgenden Felder im Body mit
`forbidden_field` (422) ab:

- `status` (Pflicht-Pfad: dedizierte Endpoints `/approve`, `/reject`, `/cancel`)
- `created_at` (system-managed beim Anlegen)
- `completed_at` (system-managed beim Erreichen von `Done`)

Begruendung: `formal.frontend-contracts.invariant.status_transitions_only_via_endpoints`.

#### 2.1.9 Status-Lifecycle (kanonisch)

Erlaubte Transitionen (alle anderen → `invalid_transition` 422):

| Von | Nach | Auslöser | Pfad |
|---|---|---|---|
| (∅) | `Backlog` | `create_story` | Frontend / Skill |
| `Backlog` | `Approved` | `approve_story` | Frontend (menschlich) |
| `Approved` | `Backlog` | `reject_story` | Frontend |
| `Backlog` | `Cancelled` | `cancel_story` | Frontend |
| `Approved` | `Cancelled` | `cancel_story` | Frontend |
| `Approved` | `In Progress` | `begin_progress` | **Pipeline-only** (Setup-Phase, FK-22 §22.4.3) |
| `In Progress` | `Done` | `complete_story` | **Pipeline-only** (Closure, `formal.story-workflow.invariant.completion_only_after_closure`) |

**Explizit verbotene Direkt-Transitionen:**

- `In Progress` → `Cancelled` direkt → **nein**. Offizieller Pfad ist
  Story-Reset (FK-53) oder Story-Exit (FK-58). Frontend bietet hier
  keine direkte Cancel-Aktion (`formal.frontend-contracts.invariant.cancel_not_during_inflight`).
- `Done` → irgendetwas → **nein**, terminal.
- `Cancelled` → irgendetwas → **nein**, terminal.

**Interne Run-Zustaende aendern Story-Status NICHT** (formal.story-
workflow.invariant.internal_pause_or_escalation_does_not_close_story
und DK-10 §10.1):
- `PAUSED`, `ESCALATED`, `FAILED` im Story-Workflow lassen Story-Status
  auf `In Progress` stehen.
- Cancellation auf `In Progress` nur ueber FK-53/FK-58, nicht ueber
  diesen Service direkt.

#### 2.1.10 Repository (StateBackend)

- Neue Tabelle `stories` (oder Erweiterung existierender StoryContext-
  Tabelle, falls inhaltlich zusammenfaellt) mit allen Stammdaten-
  Spalten aus 2.1.2.
- Neue Tabelle `story_specifications` (FK auf `story_uuid`).
- Neue Tabelle `idempotency_keys` (PK `op_id`, plus body_hash,
  result_payload, ttl).
- SQLite **und** Postgres parallel; Schema-Versionierung
  Side-by-Side via `state_backend/config.py::SCHEMA_VERSION` (FK-18
  §18.9a, Mechanik aus AG3-005). Alte DB unangetastet.

Repository-Vertrag (Protocol) wird strikt komponentenspezifisch
geschnitten (Architecture-Conformance AC003/AC004 aus dem Workbook).
**Keine generische `state_backend.store`-Fassade** importieren.

#### 2.1.11 Event-Emission (formal.frontend-contracts.events)

Jede erfolgreiche Mutation emittiert ein
`frontend-contracts.event.story_upserted` ueber den Telemetrie-
Producer:

- Payload: `project_key`, `story_id`, `summary` (vollstaendige
  `story_summary`-Entity)
- Topic: `stories`
- Producer: `telemetry` (Single-Producer), `source_bc: story-lifecycle`

`story_deleted` wird nur in offiziellen Admin-Pfaden (FK-54 Split-
dissolved oder Admin-Purge) emittiert — **nicht** in dieser Story
implementiert; nur den Producer-Hook vorbereiten.

#### 2.1.12 Preflight-Adapter (FK-22 §22.3.1)

`src/agentkit/pipeline/phases/setup/preflight.py` aktualisieren:

- **Check 1 `story_exists`**: gegen Story-Service (`get_story`), nicht
  GitHub. Existiert die Story-Display-ID?
- **Check 3 `status_approved`**: gegen Service. Story-Status muss
  `Approved` sein, bevor die Pipeline aufgreifen darf
  (DK-10 §10.1 — kein Agent kann eigenstaendig entscheiden).
- **Check 4 `dependencies_closed`**: gegen `StoryDependencyRepository`.
  Alle in `dependencies` genannten Stories muessen `Done` sein
  (FK-21 §21.10.1 Tabelle).

Bei Fehlschlag: Phase faellt mit Service-Fehler, Telemetrie-Event,
keine Story-Status-Mutation.

#### 2.1.13 Search-API

`GET /v1/projects/{project_key}/stories/search?q=<query>`:

- Filtert auf `story_id` (Display-ID), `title`, `repos`, `module`, `epic`
- Liefert `story_summary`-Liste (gleiche Wire-Form wie `GET /v1/stories`)
- Query-Parameter `q` ist Pflicht
- Keine semantische VektorDB-Suche in dieser Story (das ist Story-
  Knowledge-Base, FK-13, eigene Folge-Story)

#### 2.1.14 Field-Level-API

`GET /v1/stories/{id}/fields` — alle Story-Attribut-Werte als Map
`{field_key: value}`.

`PUT /v1/stories/{id}/fields/{field_key}` — einzelnes Feld setzen.
Pflicht: `op_id`. Validierung wie `update_story_fields` (gleiche
`forbidden_inputs` plus same Wire-Vertrag-Regeln). Setzt `status`,
`created_at`, `completed_at` mit `forbidden_field` (422) ab.

#### 2.1.15 Story-Display-ID-Allokation (atomar)

`create_story(...)`:

1. Lookup `Project` ueber `project_key` (ProjectRepository).
2. Projekt archiviert? → `forbidden` (403).
3. Allokiere `story_number` atomar (Postgres: SEQUENCE `(project_key)`-
   scoped oder `SELECT FOR UPDATE` + UPDATE; SQLite: Transaktion mit
   `BEGIN IMMEDIATE`).
4. Materialisiere `story_display_id = Project.story_id_prefix + "-" + story_number`.
5. Validierung der Stammdaten + `repos`.
6. Persistiere Story-Record + Specification-Record.
7. Persistiere Idempotency-Eintrag.
8. Emit `story_upserted`.
9. Antwort: vollstaendige `story_summary`.

Wenn Schritt 5 fehlschlaegt: Schritte 1-4 werden zurueckgerollt
(keine Story-Number-Luecke; Sequence-Allokation ist transactional).

### 2.2 Out of Scope

- **Story-Erstellungs-Guard** (FK-21 §21.13) — Hook-Implementierung gehoert
  in `governance-and-guards` (separate Story). Der Service stellt sich
  aber so dar, dass der Hook ihn vorgelagert blockieren kann (kein
  Eingriff in den Service-Code).
- **VektorDB-Indizierung beim `create_story`** — FK-21 §21.11.4: der
  CLI-Befehl `agentkit export-story-md` triggert Weaviate-Sync.
  Diese Story implementiert den Service, **nicht** den story.md-Export
  und nicht den VektorDB-Sync — beides gehoert in den Skill-Pfad
  bzw. eine separate Folge-Story.
- **Multi-LLM-Konflikt-Bewertung** beim Story-Anlegen (FK-21 §21.5)
  — Skill-seitig, nicht Service-seitig.
- **Story-Reset / Story-Split / Story-Exit** (FK-53/54/58) — eigene
  Services / Folge-Stories.
- **Frontend-Implementierung** (FK-72) — diese Story liefert nur die
  Backend-Seite.
- **SSE-Streaming der `story_upserted`-Events** — Topic-Producer
  (telemetry) und SSE-Endpoint existieren bereits (AG3-003).
  Diese Story emittiert nur, der bestehende SSE-Pfad propagiert.
- **`/v1/projects/...`-Endpoints** ausserhalb der Story-Bezug-Endpoints
  (Project-Selector, mode-lock, Counter, KpiBar) — die werden vom
  `project_management`- bzw. Telemetry-BC gefuehrt.
- **`/v1/projects/{key}/stories/{id}/flow`-Endpoint** — gehoert zum
  Pipeline-Engine-Read-Model (FK-39, `phase-state-projection`).
- **GitHub-Spiegelung** — FK-91 §91.1a Regel 9: Stories ausschliesslich
  ueber Control-Plane. GitHub ist optionale read-only Anzeige, nicht
  Wahrheitsquelle. Diese Story implementiert keinen GitHub-Sync.
- **ARE-Verknuepfung** (StoryAreLink) — FK-40 §40.5b; eigene Story
  (AG3-012 ist bereits abgeschlossen, integriert sich aber separat).

---

## 3. Betroffene Dateien

| Datei | Aenderungsart | Beschreibung |
|---|---|---|
| `src/agentkit/story_context_manager/models.py` | Erweitert | `Story` (Stammdaten), `StorySpecification`, `StoryStatus`, `StoryType`, `StorySize`, `StoryMode`, `ChangeImpact`, `ConceptQuality`, `RiskLevel` |
| `src/agentkit/story_context_manager/service.py` | Neu | `StoryService` mit allen Operationen aus 2.1.4 |
| `src/agentkit/story_context_manager/lifecycle.py` | Erweitert | `create_story()`-Erweiterung (atomare Number-Allokation, Specification-Persistenz), `begin_progress()`, `complete_story()` |
| `src/agentkit/story_context_manager/errors.py` | Erweitert | `StoryValidationError`, `StoryNotFoundError`, `InvalidStatusTransitionError`, `IdempotencyMismatchError`, `ForbiddenFieldError` (plus bestehende) |
| `src/agentkit/story_context_manager/idempotency.py` | Neu | `IdempotencyKeyStore`, Body-Hash-Logik |
| `src/agentkit/story_context_manager/wire_adapter.py` | Neu | Wire ↔ Internal-Adapter (`repos` ↔ `participating_repos`, `"In Progress"` ↔ `IN_PROGRESS`) |
| `src/agentkit/story_context_manager/http/routes.py` | Erweitert | Alle Endpoints aus 2.1.4 plus Field-Level + Search |
| `src/agentkit/state_backend/store/story_repository.py` | Neu | SQLite/Postgres-Implementierung des Story-Persistenz-Vertrags |
| `src/agentkit/state_backend/store/story_specification_repository.py` | Neu | Specification-Persistenz |
| `src/agentkit/state_backend/store/idempotency_key_repository.py` | Neu | Idempotency-Persistenz |
| `src/agentkit/state_backend/sqlite_store.py` | Modifiziert | Schema-Erweiterung |
| `src/agentkit/state_backend/postgres_schema.sql` | Modifiziert | Schema-Erweiterung |
| `src/agentkit/state_backend/config.py` | Modifiziert | `SCHEMA_VERSION`-Bump (Side-by-Side, AG3-005) |
| `src/agentkit/control_plane/http.py` | Modifiziert | Routing-Pattern fuer alle neuen Endpoints + Mapping Exception → HTTP-Status + correlation_id-Propagation |
| `src/agentkit/control_plane/runtime.py` | Modifiziert | Wire-Vertrag-Antwort-Composition (story_summary, story_detail, story_specification) |
| `src/agentkit/story/models.py` / `service.py` | Modifiziert | Read-Model-Sicht zieht jetzt aus dem Service (statt aus Execution-Events allein); Wire-Vertrag-Konformitaet pruefen |
| `src/agentkit/pipeline/phases/setup/preflight.py` | Modifiziert | Checks 1, 3, 4 gegen Service (siehe 2.1.12) |
| `src/agentkit/pipeline/phases/setup/phase.py` | Modifiziert | Nach erfolgreichem Setup: `service.begin_progress(story_id)` aufrufen (FK-22 §22.4.3) |
| `src/agentkit/closure/...` (passender Punkt) | Modifiziert | Nach erfolgreichem Closure: `service.complete_story(story_id)` aufrufen |
| `tests/unit/story_context_manager/test_service.py` | Neu | umfangreich (siehe Akzeptanzkriterien) |
| `tests/unit/story_context_manager/test_lifecycle_transitions.py` | Neu | alle Status-Pfade durchspielen |
| `tests/unit/story_context_manager/test_idempotency.py` | Neu | op_id-Mechanik |
| `tests/unit/story_context_manager/test_wire_adapter.py` | Neu | Wire↔Internal-Konversion |
| `tests/unit/state_backend/store/test_story_repository.py` | Neu | SQLite + Postgres (parametrisiert) |
| `tests/unit/control_plane/test_story_endpoints.py` | Neu | HTTP-Level-Tests inkl. Fehler-Codes |
| `tests/unit/pipeline/phases/setup/test_preflight.py` | Erweitert | Checks 1/3/4 gegen Service |
| `tests/contract/test_frontend_contracts_story_summary.py` | Neu | Wire-Schema gegen `formal.frontend-contracts.entities` ankern |

---

## 4. Akzeptanzkriterien

1. **Story-Anlage**: `POST /v1/stories` mit `op_id` legt eine Story
   im Status `Backlog` an. Story-Display-ID wird aus
   `Project.story_id_prefix + story_number` materialisiert.
   `story_number` ist projekt-lokal monoton; konkurrierende
   `create_story`-Aufrufe ergeben aufeinanderfolgende, luecken-freie
   Nummern (atomare Allokation).
2. **Idempotenz**: Wiederholung von `create_story` mit derselben `op_id`
   und gleichem Body liefert dasselbe Ergebnis, ohne eine zweite
   Story zu erzeugen. Mit abweichendem Body → `idempotency_mismatch`
   (409). Gilt analog fuer alle anderen mutierenden Endpoints.
3. **Status-Lifecycle**: Status-Transitionen folgen exakt der Tabelle
   aus 2.1.9. Jede unerlaubte Transition → `invalid_transition` (422).
   Direkter Cancel auf `In Progress` oder `Done` ist blockiert mit
   `invalid_transition` und Klartext-Hinweis auf Story-Reset/Story-Exit.
4. **PATCH-forbidden_inputs**: `PATCH /v1/stories/{id}` mit `status`,
   `created_at` oder `completed_at` im Body → `forbidden_field` (422).
5. **Wire-Vertrag-Konformitaet**: Alle Read-Model-Antworten
   (`GET /v1/stories`, `GET /v1/stories/{id}`, `GET /.../search`)
   entsprechen `formal.frontend-contracts.entity.story_summary` bzw.
   `story_detail` — alle Pflichtfelder gesetzt, alle Enum-Werte
   exakt (insb. `"In Progress"` mit Leerzeichen, Size-Werte
   inkl. `XXL`).
6. **Repo-Validierung**: `participating_repos` werden gegen
   `Project.configuration.repositories[]` validiert. Unbekannter
   Repo → `validation_failed` (400) mit `detail.unknown_repos`.
   Leere Repos-Liste → `validation_failed`.
7. **Dependency-Pruefung im Preflight**: Setup-Phase blockiert
   `dependencies_closed`-Check, wenn mindestens eine Vorgaenger-
   Story noch nicht `Done` ist.
8. **Pipeline-Statusuebergaenge**: Setup-Phase ruft
   `service.begin_progress(story_id)`, sobald Setup erfolgreich;
   Story-Status geht `Approved` → `In Progress`. Closure-Sequence
   ruft `service.complete_story(story_id)` nach erfolgreichem
   Abschluss; Story-Status geht `In Progress` → `Done`.
9. **Interne Failures aendern Story-Status nicht**: Eine `PAUSED`,
   `ESCALATED` oder `FAILED` im Run-Zustand laesst Story-Status auf
   `In Progress` stehen (formal.story-workflow.invariant.internal_pause_or_escalation_does_not_close_story).
10. **Event-Emission**: Jede erfolgreiche Mutation emittiert
    `frontend-contracts.event.story_upserted` mit korrekt befuellter
    `summary` ueber den Telemetrie-Producer; SSE-Topic `stories`
    propagiert (bestehender Pfad).
11. **Fehler-Antwort-Schema**: Alle Fehler-Antworten enthalten
    `error_code`, `error`, `correlation_id`; optional `detail`.
    `correlation_id` wird aus Request-Header `X-Correlation-Id`
    uebernommen oder generiert und im Response-Header gesetzt.
12. **Schema-Versionierung**: Neue Schema-Version Side-by-Side
    (AG3-005-Mechanik); alte DB unangetastet, neue Migration
    idempotent re-runnable.
13. **Search**: `GET /v1/projects/{key}/stories/search?q=...` filtert
    auf `story_id`, `title`, `repos`, `module`, `epic` und liefert
    `story_summary`-Liste.
14. **Field-Level-API**: `GET /v1/stories/{id}/fields` und
    `PUT /v1/stories/{id}/fields/{field_key}` funktionieren analog
    zu PATCH (forbidden_inputs gleich, op_id Pflicht).
15. **Auth-Scope / Projekt-Archivierung**: Mutationen auf archivierte
    Projekte → `forbidden` (403). `GET`s auf archivierte Projekte
    sind weiter erlaubt (Stories bleiben sichtbar).
16. **Tests gruen**: pytest unit + contract; mypy `--strict`; ruff;
    Coverage >= 85% (CLAUDE.md).
17. **Architecture-Conformance**: AC001-AC004 (Validatoren in
    `scripts/ci/`) passen; keine direkte `state_backend.store`-
    Fassaden-Importe ausserhalb der zugelassenen Reader.

---

## 5. Definition of Done

- Alle Akzeptanzkriterien 1-17 erfuellt.
- `T:/codebase/claude-agentkit3/.venv/Scripts/python.exe -m pytest tests/unit tests/contract -q` gruen.
- `mypy --strict` gruen, `ruff check src tests` gruen.
- Coverage haelt 85%-Schwelle.
- SQLite **und** Postgres-Schema migriert (parametrisierte Repository-
  Tests laufen auf beiden Backends).
- `scripts/ci/check_concept_code_contracts.py` und
  `check_architecture_conformance.py` gruen.
- Aenderungen committed auf `main` (Story-Status-Commit als
  Folgecommit).

---

## 6. Konzept-Referenzen (autoritativ)

- **FK-91 §91.1a** — Service-API-Endpunkte (Regeln 1-10)
- **FK-91 §91.8** — SSE-Event-Topics (`stories`)
- **`formal.frontend-contracts.entities`** — story_summary, story_specification, story_detail, story_runtime_state
- **`formal.frontend-contracts.commands`** — create_story, update_story_fields, approve_story, reject_story, cancel_story (alle Fehler-Codes)
- **`formal.frontend-contracts.invariants`** — `status_transitions_only_via_endpoints`, `op_id_required_on_mutations`, `cancel_not_during_inflight`, `kanban_drag_drop_constrained_transitions`, `optimistic_update_revert`, `no_global_event_ordering`
- **`formal.frontend-contracts.events`** — story_upserted, story_deleted
- **`formal.story-workflow.invariants`** — `internal_pause_or_escalation_does_not_close_story`, `completion_only_after_closure`
- **FK-02 §2.11.2** — Story-Identitaet (uuid, number, prefix, display_id)
- **FK-21 §21.10** — Story-Felder und Anlage
- **FK-21 §21.13** — Story-Erstellungs-Guard (extern, Hook-Side)
- **FK-22 §22.3.1** — Preflight-Checks 1, 3, 4
- **FK-22 §22.4.3** — Status `Approved` → `In Progress` nach Setup
- **DK-10 §10.1** — Story-Lifecycle, interne vs. fachliche Status
- **FK-18 §18.9a** — Schema-Versionierung
- **FK-29** — Closure setzt `Done`
- **FK-53 / FK-58** — Reset/Exit-Pfade (out of scope, aber als
  offizieller Pfad fuer In-Progress-Cancel referenziert)

---

## 7. Guardrail-Referenzen

- **FIX THE MODEL, NOT THE SYMPTOM**: ein autoritativer Story-Service
  in `story_context_manager`, kein zweites Service-Skelett in `story/`.
- **ZERO DEBT**: alle Pflicht-Wire-Felder, alle Fehler-Codes, alle
  Status-Transitionen vollstaendig. Keine TODOs fuer
  `forbidden_field`-Validierung oder Idempotenz-Mechanik.
- **FAIL CLOSED**: ungueltige Transitionen, unbekannte Repos,
  fehlende `op_id`, archivierte Projekte → hart ablehnen mit
  exaktem error_code. Keine grosszuegige Toleranz.
- **SINGLE SOURCE OF TRUTH**: Wire-Vertrag-Schema lebt in
  `formal.frontend-contracts.*`; Implementation referenziert,
  dupliziert nicht. Internes Story-Modell ist die SSoT; Read-Models
  (`story/`, `dashboard/`) projizieren.
- **NO ERROR BYPASSING**: keine generischen `set_status`-Backdoors;
  Status-Transitionen ausschliesslich ueber dedizierte Methoden.
- **TRUTH-BOUNDARY**: kein `json.load` auf Story-Export-Dateien aus
  geschuetzten Modulen (TB001-TB005, AC-Lints aus `scripts/ci/`).

---

## 8. Hinweise fuer den Sub-Agent

- Vorarbeiten in `story_context_manager/` und `story/` **nicht**
  blind ueberschreiben — Erweitern, Sub-Entities ergaenzen, Wire-
  Adapter dazubauen. Bei Konflikt mit existierender Vorarbeit:
  stoppen und melden.
- AK2-Vorlage (`T:/codebase/claude-agentkit/agentkit/story_context_manager/`)
  kann zur Orientierung gelesen werden, aber nicht copy-paste —
  AK2 ist im Wire-Vertrag NICHT konform mit den heutigen FK-91/
  formal.frontend-contracts.
- Status-Werte exakt nach Wire: `"In Progress"` mit Leerzeichen,
  `"Architecture Impact"` mit Leerzeichen. Python-Enum-Namen
  `IN_PROGRESS`, `ARCHITECTURE_IMPACT`.
- `participating_repos` ist der **interne** Name (FK-21-Sprache);
  Wire-Name ist **`repos`**. Wire-Adapter konvertiert in beide
  Richtungen.
- `op_id` ist **Pflicht** auf jeder Mutation. Wer das vergisst,
  produziert Backend, das den Frontend-Vertrag bricht.
- Tests muessen sowohl SQLite als auch Postgres-Backends abdecken
  (parametrisierte Fixtures, vergleichbar mit AG3-005-Pattern).
- Architecture-Conformance: keine generische
  `agentkit.backend.state_backend.store`-Fassade importieren —
  komponentenspezifische Repository-Vertraege halten (AC003/AC004
  aus dem Workbook).
