# AG3-040 Sub-Block (a) - adversarial QA review zu 1916e12

Scope gelesen: `git show 1916e12`, `git show --stat 1916e12`, Story-Realignment,
formal.frontend-contracts und die genannten Code-/Testdateien. ToolSearch hatte
keinen `mcp__agentkit3-concepts__concept_*` Treffer; Konzepte wurden lokal aus
`concept/` gelesen.

## Blocker

**ERROR - Persistierte Dependencies werden im echten Counter-Pfad nicht gelesen.**
Die vermutete `queue`-Doppelzaehlung ist nicht der Fehler: Die Invariante definiert
ueberlappende Zaehler, denn `queue == Approved` und `ready/blocked` sind
Unterklassifikationen von `Approved` (`concept/formal-spec/frontend-contracts/invariants.md:361`,
`concept/formal-spec/frontend-contracts/invariants.md:372`,
`concept/formal-spec/frontend-contracts/invariants.md:373`,
`concept/formal-spec/frontend-contracts/invariants.md:377`). Der echte Fehler ist
schlimmer: `blocked` muss Approved-Stories mit offener Dependency zaehlen
(`concept/formal-spec/frontend-contracts/invariants.md:377`), aber der produktive
Readpfad liefert diese Dependencies nicht.

Belegkette:
- `compute_story_counters` entscheidet Readiness ueber `story.dependencies`
  (`src/agentkit/project_management/service.py:195`).
- `ProjectDetailService` bezieht Stories ueber `StoryService.list_stories`
  (`src/agentkit/project_management/service.py:101`), und `StoryService` reicht
  nur `StoryRepository.list_for_project` durch
  (`src/agentkit/story_context_manager/service.py:218`,
  `src/agentkit/story_context_manager/service.py:220`).
- Das `Story`-Modell sagt selbst, dass `dependencies` ein Read-Model-Join ist,
  nicht Teil der `stories`-Tabelle
  (`src/agentkit/story_context_manager/story_model.py:169`,
  `src/agentkit/story_context_manager/story_model.py:170`).
- Der StateBackend-Repository-Pfad macht aber keinen Join: SQLite und Postgres
  selektieren nur `stories` (`src/agentkit/state_backend/store/story_repository.py:519`,
  `src/agentkit/state_backend/store/story_repository.py:527`) und die Row-Mapper
  setzen `dependencies` nicht
  (`src/agentkit/state_backend/store/story_repository.py:134`,
  `src/agentkit/state_backend/store/story_repository.py:166`,
  `src/agentkit/state_backend/store/story_repository.py:235`,
  `src/agentkit/state_backend/store/story_repository.py:270`).
- Die echte Dependency-Quelle ist ein separater Repository-Pfad
  (`src/agentkit/state_backend/store/story_dependency_repository.py:28`,
  `src/agentkit/state_backend/store/story_dependency_repository.py:32`).

Impact: Eine persistierte Approved-Story mit offener Dependency wird im Endpoint
als `ready` statt `blocked` gemeldet. Das verletzt
`frontend-contracts.invariant.counters_classification` direkt. Das ist kein
Kosmetikthema fuer spaeter, sondern falscher Wire-Zustand.

Minimaler Fix: Der autoritative Story-Readpfad muss die Dependencies
materialisieren, bevor `project_management` aggregiert. Nicht im
`project_management`-Service heimlich gegen den StateBackend-Dependency-Store
greifen, sonst ist AK7 kaputt. Danach Integrationstest mit echter
`StateBackendStoryDependencyRepository`-Kante: Approved-Story haengt von
nicht-Done-Vorgaenger ab => `queue=...`, `ready` nicht erhoeht, `blocked`
erhoeht.

## Pruefpunkte 1-9

1. **ERROR - counters_classification.** Algebraisch ist `queue=alle Approved`
   korrekt und nicht disjunkt gemeint
   (`concept/formal-spec/frontend-contracts/invariants.md:361`,
   `concept/formal-spec/frontend-contracts/invariants.md:372`). Backlog wird
   korrekt in `blocked` aufgenommen (`src/agentkit/project_management/service.py:190`,
   `src/agentkit/project_management/service.py:191`), Cancelled zaehlt nur in
   `total`, weil die Invariante keinen weiteren Bucket fuer Cancelled definiert
   (`concept/formal-spec/frontend-contracts/invariants.md:358`,
   `concept/formal-spec/frontend-contracts/invariants.md:359`,
   `concept/formal-spec/frontend-contracts/invariants.md:365`). Trotzdem ERROR,
   weil die echte Service-Topologie Dependencies nicht liefert; siehe Blocker.

2. **OK - Wire-Vertrag exakt.** `project_summary` ist exakt
   `project_key/display_name/status`
   (`src/agentkit/project_management/views.py:30`,
   `src/agentkit/project_management/views.py:41`;
   Spec: `concept/formal-spec/frontend-contracts/entities.md:33`,
   `concept/formal-spec/frontend-contracts/entities.md:48`). `project_detail`
   ist flach (`src/agentkit/project_management/views.py:78`,
   `src/agentkit/project_management/views.py:95`;
   Spec: `concept/formal-spec/frontend-contracts/entities.md:54`,
   `concept/formal-spec/frontend-contracts/entities.md:80`). `project_mode_lock`
   hat keinen `holder_count` (`src/agentkit/project_management/views.py:44`,
   `src/agentkit/project_management/views.py:56`;
   Spec: `concept/formal-spec/frontend-contracts/entities.md:93`,
   `concept/formal-spec/frontend-contracts/entities.md:105`). Contract-Tests
   pinnen Feldmengen explizit
   (`tests/contract/project_management/test_project_detail_wire.py:38`,
   `tests/contract/project_management/test_project_detail_wire.py:77`,
   `tests/contract/project_management/test_project_summary_wire.py:36`,
   `tests/contract/project_management/test_project_summary_wire.py:47`).

3. **ERROR - StoryService-Wahl.** Die Wahl von
   `story_context_manager.StoryService` statt `agentkit.backend.story` ist als Top-Surface
   richtig (`src/agentkit/story_context_manager/service.py:136`,
   `src/agentkit/story_context_manager/service.py:218`). Sie liefert Status,
   Blocker und Mode ueber das `Story`-Modell
   (`src/agentkit/story_context_manager/story_model.py:153`,
   `src/agentkit/story_context_manager/story_model.py:155`,
   `src/agentkit/story_context_manager/story_model.py:166`). Sie liefert aber im
   realen StateBackend-Pfad keine persistierten Dependencies; siehe Blocker.
   Damit ist die Quelle fuer Wire-Counters fachlich unvollstaendig.

4. **OK - AK7 Architecture-Conformance.** `project_management.service` nutzt
   `ProjectRepository` und eine schmale `StoryListPort`-API
   (`src/agentkit/project_management/service.py:39`,
   `src/agentkit/project_management/service.py:48`,
   `src/agentkit/project_management/service.py:63`,
   `src/agentkit/project_management/service.py:80`). Es gibt im geprueften
   Service keinen Direktzugriff auf `state_backend`/`story_contexts`. Der Fix fuer
   den Blocker muss diese Grenze erhalten.

5. **OK - mode_lock-Ableitung.** Die Invariante sagt: keine In-Progress-Story =>
   `idle`, mindestens eine In-Progress-Fast-Story => `fast`, sonst `standard`
   (`concept/formal-spec/frontend-contracts/invariants.md:113`,
   `concept/formal-spec/frontend-contracts/invariants.md:122`). Der Code macht
   genau das (`src/agentkit/project_management/service.py:137`,
   `src/agentkit/project_management/service.py:145`). `None`-Mode wird faktisch
   als Standard behandelt, weil nur explizites `FAST` fast setzt
   (`src/agentkit/project_management/service.py:141`,
   `src/agentkit/project_management/service.py:144`).

6. **OK - Fail-closed fuer unbekanntes Projekt und View-Striktheit.** Der Route
   precheckt `repository.get(key)` und antwortet 404
   (`src/agentkit/project_management/http/routes.py:166`,
   `src/agentkit/project_management/http/routes.py:169`,
   `src/agentkit/project_management/http/routes.py:731`,
   `src/agentkit/project_management/http/routes.py:737`). Der Service selbst
   wirft ebenfalls `ProjectNotFoundError`
   (`src/agentkit/project_management/service.py:97`,
   `src/agentkit/project_management/service.py:99`). Views sind `extra=forbid`
   und frozen (`src/agentkit/project_management/views.py:37`,
   `src/agentkit/project_management/views.py:53`,
   `src/agentkit/project_management/views.py:67`,
   `src/agentkit/project_management/views.py:88`).

7. **OK - conftest-Fix.** Die project_management-Contract-Tests sind reine
   Pydantic-/Adapter-Feldmengen-Tests und brauchen keinen Postgres-Fixture-Switch
   (`tests/contract/conftest.py:12`,
   `tests/contract/conftest.py:18`;
   `tests/contract/project_management/test_project_detail_wire.py:38`,
   `tests/contract/project_management/test_project_summary_wire.py:36`). Das
   SQLite-Pinning im Integrationstest ist als Hermetik legitim
   (`tests/integration/project_management/test_project_detail_endpoint.py:44`,
   `tests/integration/project_management/test_project_detail_endpoint.py:52`).
   Es verschleiert nicht den Blocker; der Blocker entsteht schon auf dem realen
   StoryService/StateBackend-Readpfad und waere unter Postgres genauso falsch.

8. **ERROR - Tests zu schwach.** Die Unit-Tests beweisen die pure Funktion nur
   mit handgebauten `Story.dependencies`
   (`tests/unit/project_management/test_service.py:37`,
   `tests/unit/project_management/test_service.py:57`,
   `tests/unit/project_management/test_service.py:153`,
   `tests/unit/project_management/test_service.py:182`). Der Integrationstest
   seedet echte Stories, aber keine echte Dependency-Kante
   (`tests/integration/project_management/test_project_detail_endpoint.py:95`,
   `tests/integration/project_management/test_project_detail_endpoint.py:105`) und
   kann deshalb nicht entdecken, dass persistierte Dependencies im realen
   Readpfad verschwinden. Keine `xfail`/`skip` gefunden, aber die Assertions sind
   an der kritischsten Stelle blind.

9. **OK - Story-Skizze vs. formal-spec.** Die Abweichung von der alten Story-Skizze
   ist konzepttreu: Die Realignment-Notiz setzt formal-spec als autoritativ
   (`stories/AG3-040-postgres-store-completion/story.md:28`,
   `stories/AG3-040-postgres-store-completion/story.md:41`). Die formale Spec
   fordert flat `project_detail` und kein `holder_count`
   (`concept/formal-spec/frontend-contracts/entities.md:61`,
   `concept/formal-spec/frontend-contracts/entities.md:80`,
   `concept/formal-spec/frontend-contracts/entities.md:93`,
   `concept/formal-spec/frontend-contracts/entities.md:105`). Der Code folgt dem,
   nicht der driftenden Skizze (`src/agentkit/project_management/views.py:78`,
   `src/agentkit/project_management/views.py:95`).

## AK-Matrix

| AK | Status | Bewertung |
|---|---:|---|
| AK1 projects-Postgres-Tabelle/CRUD | OK | Im Sub-Block laut Realignment faktisch vorbestehend (`stories/AG3-040-postgres-store-completion/story.md:20`, `stories/AG3-040-postgres-store-completion/story.md:27`). Schema/CRUD sind vorhanden (`src/agentkit/state_backend/postgres_schema.sql:25`, `src/agentkit/state_backend/postgres_schema.sql:34`; `src/agentkit/state_backend/postgres_store.py:997`, `src/agentkit/state_backend/postgres_store.py:1096`). |
| AK2 fc_* | Nicht Scope | Ausdruecklich AG3-028/out-of-scope (`stories/AG3-040-postgres-store-completion/story.md:16`, `stories/AG3-040-postgres-store-completion/story.md:19`). |
| AK3 `_project_payload` | OK | Liefert nur `project_key/display_name/status` (`src/agentkit/project_management/http/routes.py:589`, `src/agentkit/project_management/http/routes.py:604`). |
| AK4 `ProjectDetailView` | OK | Pydantic, frozen, extra-forbid, flach (`src/agentkit/project_management/views.py:78`, `src/agentkit/project_management/views.py:95`). |
| AK5 GET `/v1/projects/{key}` | ERROR | Route liefert DetailView (`src/agentkit/project_management/http/routes.py:169`, `src/agentkit/project_management/http/routes.py:172`), aber `story_counters` sind bei persistierten Dependencies falsch; siehe Blocker. |
| AK6 ModeLock/StoryCounters Felder | OK | Normative Felder vorhanden (`src/agentkit/project_management/views.py:44`, `src/agentkit/project_management/views.py:75`). |
| AK7 Architecture-Conformance | OK | Zugriff via Service-/Repository-Ports, kein direkter story_contexts-DB-Zugriff (`src/agentkit/project_management/service.py:39`, `src/agentkit/project_management/service.py:80`). |
| AK8 Pflichtbefehle/Gates | WARNING | Vorgelegte Evidenz nennt 2681 passed/25 skipped, ruff, mypy, Gates, Coverage. In diesem Review nicht full-suite erneut gefahren. Sonar API aktuell OK (`projectStatus.status=OK`), Jenkins-URL war lokal 403 und deshalb nicht unabhaengig verifizierbar. |

## Gesamturteil

BLOCK. Der Wire-Shape ist sauberer als die Story-Skizze, aber der wichtigste
fachliche Zaehler ist im echten Readpfad falsch, sobald echte Dependency-Kanten
existieren. Das verletzt die formale Counter-Invariante und muss vor Merge/Done
behoben werden.

Gesamturteil: BLOCK
