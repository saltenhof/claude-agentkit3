# AG3-040: Postgres-Store-Komplettierung: project_management + fc_*-Tabellen + Project-Wire-Adapter

**Typ:** Implementation
**Groesse:** M
**Abhaengigkeiten:** AG3-021 (Enums), AG3-028 (Incident-Modelle)
**Quell-Konzepte (autoritativ, in dieser Reihenfolge):**
- `FK-73 §73.4` (Postgres als single source of truth fuer project_management)
- `FK-41 §41.3.2/41.3.3` (fc_patterns, fc_check_proposals — Schema-Owner failure-corpus)
- `formal.frontend-contracts.entities §project_summary` (status-Enum)
- `formal.frontend-contracts.entities §project_detail/project_mode_lock/story_counters` (Wire-Adapter)

---

## Realignment-Notiz (2026-06-01, Feasibility vor Sub-Block (a))

- **Scope jetzt: NUR Sub-Block (a)** (project_management Postgres + Wire-Adapter
  + project_detail/mode_lock/story_counters Views). Die **fc_*-Tabellen (§2.1.2)
  bleiben ausgeklammert** und gehoeren zu AG3-028 (Schema-Owner failure-corpus,
  `_bearbeitungsreihenfolge.md` Anmerkung 1).
- **Story teilweise veraltet (Feasibility-Recon):** Die `projects`-Tabelle
  (Postgres `key`/`name`/`story_id_prefix`/`configuration`(JSONB)/`archived_at`,
  SQLite analog mit `configuration_json`) **existiert bereits** inkl.
  save/load/list-CRUD (`postgres_store.py`, `sqlite_store.py`) und
  `StateBackendProjectRepository`. §2.1.1 ist also faktisch ERLEDIGT (der
  Spaltenname-Mapping `configuration`↔`configuration_json` ist im Mapper schon
  geloest). Realer Restscope (a): `_project_payload`-Wire-Adapter (heute rohes
  `model_dump`), neue `views.py`, StoryCounters-Aggregation, Tests.
- **Wire-Vertrag = `formal.frontend-contracts.entities` ist autoritativ
  (Konzept > Story).** Daraus folgt gegenueber der Story-Skizze:
  - `project_summary` = exakt `project_key`, `display_name`, `status`
    (active|archived). **KEIN** `created_at`/`story_id_prefix`/`configuration`
    im Summary-Wire (Story §2.1.3 ist hier drift; `created_at` existiert nicht
    mal als Entity-Feld → wird NICHT erfunden).
  - `project_detail` = `project_key`/`display_name`/`status` **flach** +
    `mode_lock` + `story_counters` + `concept_anchors` (Story nestet
    `project_summary` — Wire ist flach; flach gewinnt).
  - `project_mode_lock` = `project_key` + `mode` (standard|fast|idle). **KEIN
    `holder_count`** im Wire (Story-Skizze/AG3-018 drift; falls je noetig →
    eigener formal-spec-/AG3-018-Schnitt mit Consent, NICHT hier erfinden).
  - `story_counters` = die 6 int-Zaehler; Klassifikation deterministisch nach
    `frontend-contracts.invariant.counters_classification`.
- **§2.2 Out-of-Scope Zeile „Failure-Corpus ueberlebt Reset" ist veraltet**
  (FK-69 §69.9: fc_incidents werden bei Reset entfernt, fc_patterns neu
  berechnet; gehoert ohnehin zum fc_-Block/AG3-028) — wird mit dem fc_-Block
  korrigiert, hier ohne Belang (fc_* ausgeklammert).

## Offene Folge (Codex-Review (a) r1, WARNING — owner-zugeordnet, NICHT Sub-Block (a))

- **W-DISPLAYID (WARNING, aus Remediation aufgedeckt):** Zwei divergente
  Display-ID-Formate ueber die zwei Story-Projektionen: `StoryService.create_story`
  bildet `f"{prefix}-{number}"` (z.B. `AG3-1`), `story_context_manager.lifecycle.
  create_story` `f"{prefix}-{number:03d}"` (z.B. `AG3-001`); zudem separate
  story-number-Counter pro Projektion (`stories` vs `story_contexts`). FK-18
  §18.12.1 / FK-02 §2.11.2 behandeln die Display-ID als gemeinsamen Business-Key
  ueber beide Tabellen — die Divergenz kann produktiv den Dependency-Join
  brechen. Der counters-Fix joint korrekt auf `story_display_id`; der
  Regressionstest seedet ausgerichtete IDs. Echtes Modell-Inkonsistenz-Risiko,
  aber AUSSERHALB Sub-Block (a). Disposition: eigene Folgestory
  „Display-ID/story-number-Vereinheitlichung ueber beide Projektionen". Aktiv an
  Stefan zu spiegeln (Severity-Regel) — **offene User-Entscheidung**, bis dahin
  getrackt.

---

## 1. Kontext

THEME-008 aus `stories/_priorisierungsempfehlung.md`. Befunde:

- `project-management.B2`: Postgres-Storage fuer project_management ist Stub — `postgres_store.py` enthaelt keine vollstaendige projects-Tabellen-DDL. Produktionsbetrieb ist auf SQLite beschraenkt.
- `failure-corpus.A6`: fc_patterns, fc_check_proposals-Tabellen fehlen (fc_incidents bereits in AG3-028).
- `project-management.C1`: `_project_payload` serialisiert rohe Entity-Felder statt vertragsgemaessem Wire-Shape (`project_key`, `display_name`, `status`-Enum).
- `project-management.A1-A4`: Wire-Entitaeten `project_detail`, `project_mode_lock`, `story_counters`, `concept_anchors` fehlen — Cross-BC-Aggregation noetig.
- `pipeline-framework.A2` (Detail): `PhaseEnvelopeStore`-Sub — wurde durch AG3-024 schon angelegt; hier wird nur die Postgres-Persistenz vollstaendig.

Diese Story zieht die Postgres-Persistenz **ueber alle drei BC-Bereiche** auf Produktionsniveau und schliesst den Wire-Adapter-Drift.

## 2. Scope

### 2.1 In Scope

#### 2.1.1 Postgres-DDL fuer project_management (FK-73 §73.4)

`src/agentkit/state_backend/postgres_schema.sql`:

```sql
CREATE TABLE IF NOT EXISTS projects (
    project_key VARCHAR PRIMARY KEY,
    name VARCHAR NOT NULL,
    story_id_prefix VARCHAR NOT NULL UNIQUE,
    configuration_json JSONB NOT NULL,
    archived_at TIMESTAMPTZ NULL
);
```

Index auf `archived_at` (z.B. WHERE archived_at IS NULL fuer aktive Projekte).

SQLite-Schema bleibt mit TEXT-`configuration_json` (kein JSONB).

`src/agentkit/state_backend/postgres_store.py` wird erweitert:
- `project_row(...)`-Helper vollstaendig
- `save_project`, `load_project`, `list_projects`-Funktionen

`StateBackendProjectRepository` aus `project_management/state_backend/store/project_management_repository.py` faengt damit auch unter Postgres an, korrekt zu funktionieren — bisher hatte das nur SQLite. Parametrisierte Tests laufen jetzt erfolgreich auf Postgres.

#### 2.1.2 fc_patterns + fc_check_proposals (FK-41 §41.3.2/41.3.3)

Tabellen analog `fc_incidents` (AG3-028):

```sql
CREATE TABLE IF NOT EXISTS fc_patterns (
    pattern_id UUID PRIMARY KEY,
    canonical_summary VARCHAR NOT NULL,
    failure_category VARCHAR NOT NULL,
    incident_ids JSONB NOT NULL,        -- list of incident_id
    cluster_score NUMERIC NULL,
    promotion_status VARCHAR NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    confirmed_at TIMESTAMPTZ NULL
);

CREATE TABLE IF NOT EXISTS fc_check_proposals (
    check_id UUID PRIMARY KEY,
    pattern_id UUID NOT NULL REFERENCES fc_patterns(pattern_id),
    check_type VARCHAR NOT NULL,
    check_invariant VARCHAR NOT NULL,
    proposal_content VARCHAR NOT NULL,
    promotion_status VARCHAR NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    approved_at TIMESTAMPTZ NULL,
    effectiveness_stats JSONB NULL
);
```

CHECK-Constraints auf `failure_category` (12 Werte), `promotion_status` (5 Werte), `check_type`.

**Wichtig**: Diese Tabellen liegen in `fc_*`-Namespace. Schema-Owner laut FK-41 ist `failure-corpus`-BC; aber die SQL-Definition lebt in `state_backend/postgres_schema.sql` (technischer Adapter).

Repository-Klassen `FcPatternRepository`, `FcCheckProposalRepository` als Protocols in `agentkit.failure_corpus.repository` (Erweiterung), Implementierungen in `state_backend/store/`.

Achtung: PatternPromotion- und CheckFactory-Subs (Full-Logik) sind weiter Out of Scope der Erst-Welle (vgl. AG3-028 Out of Scope). Diese Story stellt nur die Tabellen + Repository-Skelette bereit, damit das Schema vorhanden ist; aktive Beschreibung passiert in spaeteren Stories.

#### 2.1.3 Project-Wire-Adapter (project-management.B1/C1)

`src/agentkit/project_management/http/routes.py:_project_payload` wird umgebaut:

```python
def _project_payload(project: Project) -> dict[str, Any]:
    return {
        "project_key": project.key,
        "display_name": project.name,
        "status": "active" if project.archived_at is None else "archived",
        "story_id_prefix": project.story_id_prefix,
        "configuration": project.configuration.model_dump(mode="json"),
        "created_at": ...,
        "archived_at": project.archived_at.isoformat() if project.archived_at else None,
    }
```

Wire-Vertrag aus `formal.frontend-contracts.entities §project_summary` ist exakt erfuellt.

#### 2.1.4 project_detail / project_mode_lock / story_counters (project-management.A1-A3)

`src/agentkit/project_management/views.py` (neu):

```python
class ProjectDetailView(BaseModel):
    project_summary: ProjectSummaryWire
    mode_lock: ProjectModeLock
    story_counters: StoryCounters
    concept_anchors: list[str]
    model_config = ConfigDict(frozen=True, extra="forbid")

class ProjectModeLock(BaseModel):
    mode: Literal["idle", "standard", "fast"]
    holder_count: int

class StoryCounters(BaseModel):
    total: int
    finished: int
    running: int
    ready: int
    queue: int
    blocked: int
```

`build_project_detail_view(project_key: str, ...)` aggregiert ueber:
- `ProjectRepository.get(project_key)` (project_summary)
- `mode_lock_repository.get(project_key)` (aus AG3-034 oder AG3-018 — falls noch nicht da, leerer Default `idle`)
- StoryService: list_stories pro project_key, gruppiert nach Status (Counters)
- `concept_anchors`: zunaechst leere Liste (Feld-Skelett — Inhalt-Schreibstelle in Folge-Story)

GET-Endpoint `/v1/projects/{key}` antwortet jetzt `ProjectDetailView` statt rohe Entity.

#### 2.1.5 Tests

- Unit-Tests fuer Postgres-`projects`-Tabellen-Roundtrip
- Unit-Tests fuer `fc_patterns`/`fc_check_proposals`-CRUD (parametrisiert SQLite + Postgres) — minimaler Roundtrip; volle Logik in Folge-Stories
- Unit-Tests fuer `_project_payload` (Wire-Felder exakt nach Vertrag)
- Unit-Tests fuer `ProjectDetailView`, `ProjectModeLock`, `StoryCounters` (frozen, extra forbid)
- Integration-Test: GET `/v1/projects/{key}` liefert ProjectDetailView mit korrektem Wire-Format
- Contract-Test `tests/contract/project_management/test_project_summary_wire.py` und `test_project_detail_wire.py`: exakte Felder nach `formal.frontend-contracts.entities`

### 2.2 Out of Scope

- PatternPromotion-Sub Vollausbau — Folge-Story
- CheckFactory-Sub Vollausbau — Folge-Story
- `concept_anchors`-Inhalt (Befuellung) — Folge-Story (braucht Konzept-Indexierungs-Logik)
- PATCH `/v1/projects/{key}/configuration` Doppelroute-Klaerung (`project-management.B3`) — Folge-Story (FK-91-Aktualisierung)
- Real-Postgres-Container in CI falls noch nicht vorhanden — bestehende Postgres-Test-Konfiguration (AG3-005) nutzen
- `mode_lock_repository`-Tabelle/Logik (gehoert zu AG3-034 oder AG3-018)
- Reset-Purge fuer fc_*-Tabellen — bewusst NICHT (Failure-Corpus ueberlebt Reset, siehe AG3-035)

## 3. Betroffene Dateien

| Datei | Aenderungsart | Beschreibung |
|---|---|---|
| `src/agentkit/state_backend/postgres_schema.sql` | Modifiziert | Tabelle `projects`, `fc_patterns`, `fc_check_proposals` |
| `src/agentkit/state_backend/postgres_store.py` | Modifiziert | Project-CRUD + fc-CRUD |
| `src/agentkit/state_backend/sqlite_store.py` | Modifiziert | analog SQLite |
| `src/agentkit/state_backend/config.py` | Modifiziert | SCHEMA_VERSION-Bump |
| `src/agentkit/failure_corpus/repository.py` | Modifiziert | + `FcPatternRepository`, `FcCheckProposalRepository` Protocols |
| `src/agentkit/state_backend/store/fc_pattern_repository.py` | Neu | |
| `src/agentkit/state_backend/store/fc_check_proposal_repository.py` | Neu | |
| `src/agentkit/project_management/http/routes.py` | Modifiziert | `_project_payload` Wire-Felder; GET /v1/projects/{key} liefert ProjectDetailView |
| `src/agentkit/project_management/views.py` | Neu | `ProjectDetailView`, `ProjectModeLock`, `StoryCounters`, `ProjectSummaryWire` |
| `src/agentkit/project_management/service.py` (oder lifecycle) | Modifiziert | `build_project_detail_view` |
| `tests/unit/state_backend/store/test_postgres_projects.py` | Neu/Erweitert | Postgres-Tests |
| `tests/unit/state_backend/store/test_fc_pattern_repository.py` | Neu | |
| `tests/unit/state_backend/store/test_fc_check_proposal_repository.py` | Neu | |
| `tests/unit/project_management/http/test_routes.py` | Modifiziert | Wire-Felder |
| `tests/unit/project_management/test_views.py` | Neu | View-Modelle |
| `tests/integration/project_management/test_project_detail_endpoint.py` | Neu | E2E |
| `tests/contract/project_management/test_project_summary_wire.py` | Neu | Wire-Pinning |
| `tests/contract/project_management/test_project_detail_wire.py` | Neu | Wire-Pinning |

## 4. Akzeptanzkriterien

1. **Postgres-Tabelle `projects`** existiert mit allen Spalten aus 2.1.1. Repository-Tests laufen jetzt erfolgreich auf Postgres (parametrisiert).
2. **fc_patterns, fc_check_proposals** existieren in SQLite + Postgres. Roundtrip-Tests bestaetigen Lesen/Schreiben.
3. **`_project_payload`** liefert: `project_key`, `display_name`, `status` (`active`/`archived`), `story_id_prefix`, `configuration`, `archived_at`. Wire-Vertrag aus `formal.frontend-contracts.entities §project_summary` erfuellt.
4. **`ProjectDetailView` ist Pydantic-Modell** mit `project_summary`, `mode_lock`, `story_counters`, `concept_anchors` (frozen, extra forbid).
5. **GET `/v1/projects/{key}`** liefert ProjectDetailView mit befuellten `mode_lock` (idle als Default falls keine mode_lock-Tabelle), `story_counters` aus StoryService-Aggregation, leerer `concept_anchors[]`.
6. **`ProjectModeLock`** und `StoryCounters` haben die normativen Felder.
7. **Architecture-Conformance**: `project_management.views` liest StoryService-Daten ueber existing Service-API (kein direkter DB-Zugriff aus project_management auf story_contexts).
8. **Pflichtbefehle gruen**: pytest unit + integration + contract; mypy --strict; ruff clean; Coverage haelt 85%.

## 5. Definition of Done

- AK 1-8 erfuellt.
- `.venv\Scripts\python -m pytest -q` gruen.
- `mypy --strict` gruen, `ruff check src tests` gruen.
- SQLite + Postgres migriert; Postgres-Tests fuer projects, fc_patterns, fc_check_proposals gruen.
- Aenderungen committed auf `main`.

## 6. Konzept-Referenzen (autoritativ)

- **FK-73 §73.4** — Postgres als SoT
- **FK-41 §41.3.2/41.3.3** — fc_patterns, fc_check_proposals
- **`formal.frontend-contracts.entities §project_summary`** — Wire-Vertrag
- **`formal.frontend-contracts.entities §project_detail`** — Aggregat-Sicht
- **`formal.frontend-contracts.entities §project_mode_lock`** — mode_lock-Wire
- **`formal.frontend-contracts.entities §story_counters`** — Counters

## 7. Guardrail-Referenzen

- **FIX THE MODEL, NOT THE SYMPTOM**: Postgres endlich produktionsreif fuer project_management.
- **ZERO DEBT**: Wire-Vertrag exakt erfuellt; keine `key`/`name`-Drift mehr.
- **FAIL CLOSED**: Endpoint liefert ProjectDetailView strikt nach Pflicht-Schema; missing Field -> Pydantic-Validation-Error.

## 8. Hinweise fuer den Sub-Agent

- `concept_anchors`: leere Liste als Default. Inhalt-Befuellung ist Folge-Story (braucht Konzept-Inventar).
- `mode_lock`: falls noch nicht persistent verfuegbar (AG3-018/AG3-034), liefere `mode="idle", holder_count=0`. Nicht erfinden.
- AK2 NICHT veraendern.

## 9. Abnahme-Status (2026-06-01)

- **Sub-Block (a) — done + abgenommen.** project_management Postgres/Wire +
  project_detail/mode_lock/story_counters-Views + dependency-aware Counters.
  Giftige Codex-Review (a): r1 BLOCK (Dependency-Materialisierung) -> r2 BLOCK
  (W-DISPLAYID) -> beide behoben. **W-DISPLAYID ist durch AG3-050 aufgeloest**
  (vereinheitlichte Story-Identitaet; Dependency-FK/Read-Pfad auf statische
  `stories`). Kumulativ gruen @01421c7: Jenkins #24 SUCCESS, Sonar Quality Gate
  OK (new_coverage 84.4%, 0 new/critical violations). Counter-Klassifikation
  laeuft jetzt produktiv ueber den statischen Pfad (kein story_contexts-Seeding).
- **Sub-Block (b) — fc_*-Tabellen (§2.1.2): offen, owned by AG3-028**
  (Anmerkung 1 in `_bearbeitungsreihenfolge.md`). Deshalb bleibt
  `AG3-040.status.yaml` auf `in_progress`, bis (b) ueber AG3-028 abgeschlossen ist.
