OVERALL CHANGES-REQUESTED

**1) Konzept-Vollstaendigkeit: FAIL**

- ERROR: Analytics-Scope widerspricht AG3-094. AG3-093 verlangt Analytics funktional 1:1 inkl. Overview/Timeseries (`stories/AG3-093-frontend-app-shell-bc-views/story.md:39`, `:57`), erklaert Charts/SSE aber als AG3-094-Out-of-Scope (`:49`). AG3-094 beansprucht genau diese ECharts-/SSE-Arbeit (`stories/AG3-094-dashboards-live-updates-sse/story.md:28-45`, `:63-73`); der Prototyp hat reale ECharts-Chartmechanik (`frontend/prototype/src/components/AnalyticsView.tsx:7`, `:15`, `:218`).  
  Fix: AG3-093 auf Shell/Slice-Struktur und Analytics-Slot begrenzen; 1:1 Chart/Timeseries/SSE-ACs nur in AG3-094 lassen.

- ERROR: Hub-Sicht ist nicht entscheidungsreif. FK-72 fuehrt fuenf Top-Sichten inkl. Hub (`concept/technical-design/72_frontend_architektur.md:121-137`), Hub ist nur formal zurueckgestellt/prototypisch (`:432-434`). AG3-093 stellt den Hub aber als offene Frage statt als klares Akzeptanzziel (`stories/AG3-093-frontend-app-shell-bc-views/story.md:50`, `:84`).  
  Fix: explizit entscheiden: Hub-Nav/Placeholder im Shell-Scope ja/nein, mit konkretem AC.

**2) AC-Schaerfe: FAIL**

- ERROR: AG3-091 fehlt als harte Dependency, obwohl AC6 und Scope echte Read-Models verlangen (`story.md:5`, `:41`, `:47`, `:59`). `status.yaml` nennt nur AG3-090/AG3-092 (`status.yaml:8-10`), der Index ebenso (`var/concept-gap-analysis/_STORY_INDEX.md:118`), waehrend AG3-091 die Read-Models/Execution-Input-Surface besitzt (`_STORY_INDEX.md:116`).  
  Fix: `depends_on` um AG3-091 ergaenzen; AG3-091 `unblocks` und Index konsistent nachziehen.

- ERROR: Edge-Case-AC deckt FK-72 §72.14.6 nicht voll ab. Story AC7 testet nur Mutation-Fail, stale-selected und Empty-State (`story.md:60`), FK-72 fordert zusaetzlich u. a. last-request-wins, invalid-transition-Revert, Sheet-validation_failed-Draft, paused/escalated/failed Flow-State, Project-Switch, archived-project-disable, reconnect/offline (`concept/technical-design/72_frontend_architektur.md:510-590`).  
  Fix: AC7 in testbare Einzel-ACs aufsplitten oder bewusst per Owner/Story ausgrenzen.

- ERROR: Pflicht-Gates unvollstaendig. Story AC9 nennt lokale Tests/Lint/Concept-Gates (`story.md:62`), aber AGENTS verlangt Jenkins gruen, Sonar gruen und `scripts/ci/check_remote_gates.ps1` (`AGENTS.md:31-45`); das Script scheitert hart bei Sonar/Jenkins rot (`scripts/ci/check_remote_gates.ps1:75-82`).  
  Fix: Remote-Gate-Befehl und strikte Sonar-Metriken in AC/DoD aufnehmen.

**3) Klarheit: FAIL**

- ERROR: Falscher Ownership-Begriff. AG3-093 nennt `frontend` als “Bounded Context” (`story.md:5`), FK-72 sagt explizit: kein UI-BC, kein Cockpit-Aggregator, Cross-BC-Sichten sind Shell-Composer (`concept/technical-design/72_frontend_architektur.md:51-59`).  
  Fix: Header auf “Module/Layer frontend; Shell R-Klammer; BC-Owner in contexts/*” umstellen.

- ERROR: Offene Punkte widersprechen bereits gesetztem Scope. Scope fordert eigenen Layouter aus `graph.ts` (`story.md:32`, `:39`), offene Punkte fragen aber, ob er ersetzt werden soll (`story.md:85`). Hub ist ebenfalls offen (`:84`).  
  Fix: vor Autorisierung entscheiden oder Scope/AC entsprechend reduzieren.

**4) Kontext-Sinnhaftigkeit: FAIL**

- ERROR: Status-Metadaten sind inkonsistent. `status.yaml` hat `unblocks: []` (`status.yaml:11`), obwohl AG3-094 und AG3-105 laut Index auf AG3-093 aufbauen (`_STORY_INDEX.md:119-120`) und AG3-094 `depends_on: AG3-093` fuehrt (`stories/AG3-094-dashboards-live-updates-sse/status.yaml:8-10`).  
  Fix: `unblocks` mindestens mit AG3-094 und AG3-105 synchronisieren oder Feld bewusst entfernen/ignorieren.

- WARNING: Index-Quelle ist unterdeklariert. Index row nennt nur FK-72 §72.1-§72.10 (`_STORY_INDEX.md:118`), die Story selbst macht §72.13/§72.14 normativ (`story.md:17`, `:40-42`, `:77-79`).  
  Fix: Index auf §72.1-§72.14 erweitern oder Story-Quellen auf den Index-Scope zurueckschneiden.

**Must-Fix**

1. AG3-091 als harte Dependency in `status.yaml`, Index und Rueckverlinkung modellieren.
2. Analytics 1:1/Charts/SSE aus AG3-093 entfernen oder AG3-094-Scope neu schneiden; keine Doppel-Ownership.
3. Hub-Entscheidung vor Approval festlegen.
4. FK-72 §72.14.6 Edge-Cases vollstaendig und testbar in ACs aufnehmen.
5. Remote Jenkins/Sonar-Gates in AC/DoD aufnehmen.
6. “Bounded Context frontend” in korrekte Shell-/Frontend-Layer-Formulierung aendern.
7. `unblocks` und FK-Quellen im Story-Index/status konsistent machen.
