# AG3-040 Sub-Block (a) - QA Recheck Runde 2 zu e7516e5

Pruefbasis:

- `git log --oneline 1916e12..HEAD`: `e7516e5 fix(project_management,story_context_manager): AG3-040(a) - Codex-r1 BLOCK behoben (Dependency-Materialisierung fuer Counters)`
- `git diff 1916e12..HEAD`: `project_management.service`, `story_context_manager.service`, Integrationstest, kleine Unit-Test-Port-Anpassungen, Story-WARNING-Tracking.
- Lokal nachgefahren: `.venv\Scripts\python -m pytest tests/integration/project_management/test_project_detail_endpoint.py tests/unit/project_management/test_service.py tests/unit/project_management/http/test_routes.py` -> 33 passed.
- Vorgelegte Evidenz nicht vollstaendig erneut gefahren: 2682 passed/25 skipped non-e2e, ruff clean, mypy 331 files, 4 Gates OK inkl. architecture-conformance, Coverage 88.17%.

## Verdikte

**R1-BLOCK: RESOLVED im engen Sinne.** Der produktive `project_detail`-Readpfad benutzt nicht mehr den nackten Story-Read, sondern den dependency-aware StoryService-Read:

- `ProjectDetailService.build_project_detail_view` ruft `list_stories_with_dependencies` (`src/agentkit/project_management/service.py:109`).
- Der Port ist genau auf diese dependency-aware API geschnitten (`src/agentkit/project_management/service.py:40`, `src/agentkit/project_management/service.py:55`).
- `StoryService.list_stories_with_dependencies` laedt erst Stories und dann alle Dependency-Edges fuer das Projekt (`src/agentkit/story_context_manager/service.py:264`, `src/agentkit/story_context_manager/service.py:266`).
- Die Kanten kommen aus `StoryDependencyRepository.list_for_project` (`src/agentkit/execution_planning/repository.py:15`, `src/agentkit/execution_planning/repository.py:18`) und im produktiven Default aus `StateBackendStoryDependencyRepository` (`src/agentkit/story_context_manager/service.py:180`, `src/agentkit/story_context_manager/service.py:184`; Implementierung: `src/agentkit/state_backend/store/story_dependency_repository.py:28`).
- Die Materialisierung joint tatsaechlich `edge.story_id -> story.story_display_id` und schreibt `depends_on_story_id` sortiert/dedupliziert in `Story.dependencies` (`src/agentkit/story_context_manager/service.py:266`, `src/agentkit/story_context_manager/service.py:273`).

**W-DISPLAYID: ERROR-JETZT, nicht nur WARNING-Folge.** Der neue Join ist fachlich richtig, aber er haengt produktiv an identischen Story-IDs ueber `stories`, `story_contexts` und `story_dependencies`. Genau diese Identitaet ist aktuell gebrochen:

- Das Konzept fordert `{PREFIX}-{NNN}` (`concept/technical-design/02_domaenenmodell_zustaende_artefakte.md:416`) und beschreibt die Anzeige-ID als einmal materialisierte Darstellung aus `Project.story_id_prefix + story_number` im Story-Record (`concept/technical-design/02_domaenenmodell_zustaende_artefakte.md:618`, `concept/technical-design/02_domaenenmodell_zustaende_artefakte.md:623`, `concept/technical-design/02_domaenenmodell_zustaende_artefakte.md:633`, `concept/technical-design/02_domaenenmodell_zustaende_artefakte.md:644`).
- Der `stories`-Store erzeugt aber unpadded IDs: SQLite `f"{story_id_prefix}-{story_number}"` (`src/agentkit/state_backend/store/story_repository.py:723`), Postgres ebenfalls (`src/agentkit/state_backend/store/story_repository.py:738`).
- Der alte StoryContext-Lifecycle erzeugt padded IDs: `f"{project.story_id_prefix}-{story_number:03d}"` (`src/agentkit/story_context_manager/lifecycle.py:55`).
- `story_dependencies` referenziert nicht `stories`, sondern `story_contexts(project_key, story_id)` (`src/agentkit/state_backend/postgres_schema.sql:50`, `src/agentkit/state_backend/postgres_schema.sql:53`; SQLite analog `src/agentkit/state_backend/sqlite_store.py:155`, `src/agentkit/state_backend/sqlite_store.py:158`).
- Der Remediation-Test muss deshalb manuell `story_contexts`-Rows mit den unpadded `StoryService`-IDs anlegen (`tests/integration/project_management/test_project_detail_endpoint.py:184`, `tests/integration/project_management/test_project_detail_endpoint.py:190`) bevor die echte Dependency-Kante gespeichert werden kann (`tests/integration/project_management/test_project_detail_endpoint.py:199`, `tests/integration/project_management/test_project_detail_endpoint.py:208`).

Das ist kein kosmetisches Format-WARNING. Bei realen padded `story_contexts`-Kanten (`AG3-001`) und unpadded `stories`-Rows (`AG3-1`) findet `predecessors.get(story.story_display_id)` (`src/agentkit/story_context_manager/service.py:271`) nichts. Dann ist die R1-Symptomatik produktiv wieder da: Approved mit offener Dependency wird `ready`. Das blockiert Sub-Block (a), weil der Endpoint genau diesen Join braucht.

## Counter-Klassifikation

Die reine Klassifikation passt zur Invariante `frontend-contracts.invariant.counters_classification`:

- Formal: `queue = Approved`, `ready = Approved + no blocker + all deps Done`, `blocked = Backlog + Approved mit blocker/offener dep` (`concept/formal-spec/frontend-contracts/invariants.md:353`, `concept/formal-spec/frontend-contracts/invariants.md:379`).
- Code: `queue` zaehlt alle Approved (`src/agentkit/project_management/service.py:193`).
- `Backlog` geht direkt in `blocked` (`src/agentkit/project_management/service.py:198`, `src/agentkit/project_management/service.py:199`).
- Approved + alle Dependencies in `done_ids` + kein blocker geht in `ready` (`src/agentkit/project_management/service.py:203`, `src/agentkit/project_management/service.py:205`).
- Approved + blocker oder offene/unbekannte Dependency geht in `blocked` (`src/agentkit/project_management/service.py:203`, `src/agentkit/project_management/service.py:207`).
- Cancelled zaehlt nur in `total`: `total = len(stories)` (`src/agentkit/project_management/service.py:190`), danach wird nur `In Progress`, `Done`, `Approved`, `Backlog` klassifiziert (`src/agentkit/project_management/service.py:191`, `src/agentkit/project_management/service.py:207`).

Die Dependency-Materialisierung behandelt alle Kinds als Vorgaenger, weil sie nicht nach `kind` filtert (`src/agentkit/story_context_manager/service.py:266`, `src/agentkit/story_context_manager/service.py:269`). Das ist zur hier massgeblichen kind-agnostischen Counter-Invariante passend. Der separate FK-70-Hinweis, dass `soft_story_dependency` kein harter Topologie-Blocker sein soll (`src/agentkit/core_types/dependency.py:18`, `src/agentkit/core_types/dependency.py:20`), bleibt ein Konzeptkonflikt zwischen Planungsvokabular und Frontend-Counter-Invariante, ist aber nicht neu durch e7516e5.

## Reproduktionstest

Der neue Integrationstest ist fuer den R1-BLOCK echt:

- Er nutzt eine echte `StateBackendStoryDependencyRepository`-Kante, kein manuelles `Story.dependencies`-Setzen (`tests/integration/project_management/test_project_detail_endpoint.py:199`, `tests/integration/project_management/test_project_detail_endpoint.py:208`).
- Er geht ueber den echten HTTP-Dispatcher und `ProjectDetailService` (`tests/integration/project_management/test_project_detail_endpoint.py:210`, `tests/integration/project_management/test_project_detail_endpoint.py:219`).
- Er beweist blocked-vor-ready-nach-Done: vorher `queue=2`, `ready=1`, `blocked=1` (`tests/integration/project_management/test_project_detail_endpoint.py:221`, `tests/integration/project_management/test_project_detail_endpoint.py:225`); nach Done `finished=1`, `queue=1`, `ready=1`, `blocked=0` (`tests/integration/project_management/test_project_detail_endpoint.py:227`, `tests/integration/project_management/test_project_detail_endpoint.py:235`).
- Der Test ist nicht `xfail`/`skip` und haette gegen den alten Code gefailt, weil `ProjectDetailService` damals `list_stories` statt `list_stories_with_dependencies` nutzte.

Aber: er ist blind fuer W-DISPLAYID, weil er die `story_contexts`-Rows absichtlich mit den unpadded StoryService-IDs seedet (`tests/integration/project_management/test_project_detail_endpoint.py:184`, `tests/integration/project_management/test_project_detail_endpoint.py:196`). Als R1-Reproducer gut. Als produktiver End-to-End-Beweis ueber die zwei echten Story-Projektionen zu schwach.

## Architektur / AK7

AK7 bleibt fuer `project_management` sauber:

- `project_management` haengt an `StoryListPort`, nicht am Dependency-Store (`src/agentkit/project_management/service.py:40`, `src/agentkit/project_management/service.py:55`).
- Der produktive Call geht ueber `StoryService` (`src/agentkit/project_management/service.py:83`, `src/agentkit/project_management/service.py:109`).
- Kein neuer Direktimport `project_management -> execution_planning` oder `project_management -> story_dependency_repository`; die einzigen Treffer in `project_management.service` sind Doku/Port und der erlaubte Default auf `StateBackendProjectRepository`.

Die neue Kante `story_context_manager -> StoryDependencyRepository` ist als DI-Kante akzeptabel: der SCM-Service materialisiert sein eigenes `Story.dependencies`-Readmodell ueber ein Repository-Protokoll (`src/agentkit/story_context_manager/service.py:67`, `src/agentkit/story_context_manager/service.py:162`, `src/agentkit/story_context_manager/service.py:188`). Die vorgelegte architecture-conformance-Evidenz steht damit nicht im Widerspruch. Der harte Fehler liegt nicht in der Kante, sondern in der nicht einheitlichen Story-ID.

## Regressionen

Keine neue N+1-Regression: `list_stories_with_dependencies` macht einen Story-Batch-Read und einen Dependency-Batch-Read (`src/agentkit/story_context_manager/service.py:264`, `src/agentkit/story_context_manager/service.py:266`). Deduplizierung und deterministische Sortierung passieren per `sorted(set(deps))` (`src/agentkit/story_context_manager/service.py:273`).

`list_stories` bleibt unveraendert und damit fuer bestehende Consumer ohne Dependency-Join stabil (`src/agentkit/story_context_manager/service.py:231`, `src/agentkit/story_context_manager/service.py:233`). Das ist gut, weil der neue Join nicht heimlich alle Story-Listen verteuert.

Die R1-OK-Punkte bleiben OK: Wire-Vertrag flach/exakt, `mode_lock`-Ableitung, fail-closed 404/View-Striktheit und der conftest-/SQLite-Fix wurden durch e7516e5 nicht erkennbar verschlechtert. Die lokale Teilverifikation mit 33 Tests ist gruen.

## Neue Befunde

**ERROR - W-DISPLAYID bricht den produktiven Dependency-Join jetzt.** Die Remediation ist nur fuer aligned IDs korrekt. Das echte Modell hat aktuell zwei ID-Erzeuger (`AG3-1` vs `AG3-001`) und der Dependency-Store haengt an `story_contexts`, waehrend der Counter-Corpus aus `stories` kommt. Damit kann der neue Join echte Kanten verfehlen. Sofort beheben: ein einziger Story-ID-/Story-Number-Owner, einheitliches Format, und ein Integrationstest, der nicht manuell aligned `story_contexts` seedet, sondern die reale Erzeugung beider Projektionen oder den konsolidierten Zielpfad benutzt.

## AK-Matrix

| AK | Status | Bewertung |
|---|---:|---|
| AK1 | OK | Projects-Postgres/CRUD nicht neu tangiert; Sub-Block-Basis bleibt vorbestehend. |
| AK3 | OK | `_project_payload`/Summary-Wire nicht veraendert; R1-OK bleibt stehen. |
| AK4 | OK | `ProjectDetailView`-Shape unveraendert flach/strikt. |
| AK5 | ERROR | GET `/v1/projects/{key}` nutzt jetzt den echten Dependency-Readpfad, aber der Join ist produktiv durch Display-ID-Divergenz brechbar. |
| AK6 | OK mit Risiko aus AK5 | Felder und reine Counter-Logik korrekt; falsche ID-Korrelation kann die Werte trotzdem falsch machen. |
| AK7 | OK | `project_management` bleibt hinter StoryService/Port; keine neue Direktkante zum Dependency-Store. |
| AK8 | WARNING | Vorgelegte Gesamtgate-Evidenz gruen; lokal nur die relevanten 33 Tests nachgefahren. W-DISPLAYID bleibt als ERROR vor "fertig" zu beheben, nicht als Gate-Warning wegzuheften. |

## Gesamturteil

BLOCK. Der R1-Codepfadfehler ist behoben, aber die Remediation legt die naechste harte Wahrheit frei: solange `stories.story_display_id` und `story_contexts.story_id` auseinanderlaufen, ist der Dependency-Join im produktiven Scope nicht verlaesslich. Das ist fuer AG3-040(a) kein spaeteres Schoenheitsproblem, sondern falscher `story_counters`-Output.

Gesamturteil: BLOCK
