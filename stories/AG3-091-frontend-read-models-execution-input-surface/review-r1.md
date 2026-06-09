OVERALL CHANGES-REQUESTED

**1) Konzept-Vollstaendigkeit: FAIL**

ERROR: `execution-input/limits` fehlt im Scope und in den ACs, obwohl AG3-091 es laut Index besitzt.  
Evidence: `var/concept-gap-analysis/_STORY_INDEX.md:116` nennt `/execution-input/snapshot|next|limits`; FK-91 listet `GET /v1/projects/{project_key}/execution-input/limits` in `concept/technical-design/91_api_event_katalog.md:134`; formale Entity existiert in `concept/formal-spec/frontend-contracts/entities.md:728`. Die Story scoped nur `snapshot|next` in `stories/AG3-091-frontend-read-models-execution-input-surface/story.md:27-30`, ACs decken Limits nicht ab.  
Fix: `GET .../execution-input/limits` als Read-Model inklusive Contract-Test aufnehmen oder Index/FK explizit auf anderen Owner korrigieren. Da der Index AG3-091 nennt, ist Aufnahme der saubere Fix.

ERROR: Mode-Lock-Zielbild kollidiert mit formaler Spec und bestehendem Read-Model.  
Evidence: Story verlangt Control-Plane-`mode_lock` mit `null/standard/fast + holder_count` in `story.md:32` und `story.md:52`. Formal Spec sagt aber `mode: [standard, fast, idle]`, kein `holder_count`, story-derived in `concept/formal-spec/frontend-contracts/entities.md:93-110` und `concept/formal-spec/frontend-contracts/invariants.md:108-122`. Existierender Code spiegelt das: `src/agentkit/project_management/views.py:44-56`, `src/agentkit/project_management/service.py:124-153`. Canonical persistence existiert bereits: `src/agentkit/state_backend/store/mode_lock_repository.py:1-3`, `:61-70`, `:199-203`.  
Fix: Story muss explizit die Formal-Spec- und Code-Migration auf canonical `project_mode_lock` mit finaler Wire-Shape aufnehmen.

ERROR: Feldnamen sind nicht vertragsklar.  
Evidence: Story verwendet Prototype-CamelCase `eligibleReady`, `totalReady`, `globalSlotsLeft` in `story.md:28` und `story.md:48`; Formal Spec verwendet `eligible_ready`, `total_ready`, `global_slots_left` in `concept/formal-spec/frontend-contracts/entities.md:685`, `:694`, `:699`.  
Fix: Einen Wire-Contract festlegen und Story/Formal-Spec/Tests darauf angleichen. Ohne diese Entscheidung ist AC9 nicht umsetzbar.

**2) AC-Schaerfe: FAIL**

ERROR: Scope-Punkte 3 und 4 haben keine AC-Abdeckung.  
Evidence: Planning-Endpunkt-Angleichung und Project-Config-Read sind Scope in `story.md:36-37`; AC1-10 in `story.md:48-57` testen weder `/v1/projects/{key}/planning/ready-set|execution-plan` noch `/v1/projects/{key}/configuration`.  
Fix: Eigene ACs fuer Planning-Pfadform, Altpfad-/Kompatibilitaetsverhalten, Project-Config-GET, 404/405/contract tests ergaenzen.

ERROR: `execution-input/next` hat keine formale Entity.  
Evidence: Story fordert Contract-Bindung fuer jeden Endpunkt in `story.md:38` und `story.md:56`; `next` liefert Story plus Triage-Begruendung in `story.md:29`, aber Formal Entities enthalten nur `execution_input_snapshot` und `execution_input_stack` in `concept/formal-spec/frontend-contracts/entities.md:669-727`. FK-72 verlangt Entity/Command je neuem Endpoint in `concept/technical-design/72_frontend_architektur.md:445-451`.  
Fix: `execution_input_next`/`execution_input_pick` Entity mit Reason-Feldern definieren oder formal belegen, dass `next` exakt eine bestehende Entity nutzt.

**3) Klarheit: WEAK**

ERROR: Mode-Lock-Anweisung widerspricht sich selbst.  
Evidence: Story sagt “nicht aus Story-Heuristik” in `story.md:18`, `:32`, `:52`, fordert aber in den Sub-Agent-Hinweisen “Mode-Lock-Semantik 1:1” aus `selectActiveProjectMode` in `story.md:71`. Der Prototype-Selector ist eindeutig story-derived: `frontend/prototype/src/store/storySelectors.ts:280-285`.  
Fix: Prototype fuer Mode-Lock nur als UI-Zustandsbild referenzieren; fachliche Quelle klar auf canonical `project_mode_lock` setzen.

WARNING: `key`/`project_key` ist inkonsistent benannt.  
Evidence: Story verwendet `/v1/projects/{project_key}` in `story.md:28-29`, aber `/v1/projects/{key}` in `story.md:36-37`.  
Fix: Durchgehend `{project_key}` verwenden, passend zu FK-91.

**4) Kontext-Sinnhaftigkeit: FAIL**

ERROR: Ist-Zustand “Backend-Read-Model fehlt” ist fuer Counters/Mode-Lock falsch bzw. unvollstaendig.  
Evidence: Story behauptet fehlendes Backend-Read-Model in `story.md:19`; bestehender `GET /v1/projects/{key}` liefert bereits `mode_lock` und `story_counters`: route in `src/agentkit/project_management/http/routes.py:162-173`, Aggregation in `src/agentkit/project_management/service.py:109-115`, Models in `src/agentkit/project_management/views.py:44-75`.  
Fix: Kontext als “standalone Endpoints fehlen; vorhandenes Aggregate ist story-derived und muss migriert/reused werden” formulieren, damit keine zweite Logik entsteht.

ERROR: Planning-Baseline passt nicht zum realen Code.  
Evidence: Story spricht von bestehenden `/v1/planning/ready-set` und `/v1/planning/execution-plan` in `story.md:22` und deren Hebung in `story.md:36`. Der reale Router matcht project-scoped `/planning/dependency-graph`, `/planning/dependencies`, `/planning/next-ready`, `/planning/config`: `src/agentkit/execution_planning/http/routes.py:39-52`, `:125-157`.  
Fix: Story auf den echten Ist-Zustand korrigieren und klar sagen, ob `ready-set`/`execution-plan` neu entstehen, alte FK-Pfade migriert werden oder `next-ready` ersetzt wird.

**Must-Fix**

1. `GET /execution-input/limits` samt AC/Contract-Test aufnehmen.  
2. Mode-Lock-Contract gegen canonical `project_mode_lock` samt Formal-Spec-Migration eindeutig machen.  
3. Wire-Feldnamen zwischen Story und `formal.frontend-contracts.entities` vereinheitlichen.  
4. ACs fuer Planning-Angleichung und Project-Config-GET ergaenzen.  
5. Ist-Zustand fuer bestehende ProjectDetail/Counters/Mode-Lock und Planning-Routes korrigieren.
