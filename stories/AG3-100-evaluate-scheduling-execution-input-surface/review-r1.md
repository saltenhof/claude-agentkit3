OVERALL CHANGES-REQUESTED

**Konzept-Vollstaendigkeit: FAIL**
- **ERROR:** §70.11-Invariante #10 fehlt im Scope und in den AC, obwohl AG3-100 laut Index §70.11-Invarianten umsetzt. FK-70 listet #10 explizit: optionale Human-Review darf nicht still wie ein blockierendes Human-Gate behandelt werden (`concept/technical-design/70_story_planung_abhaengigkeiten_ausfuehrungsplanung.md:845`). Der Gap-Report nennt #10 ebenfalls als nicht durchsetzbar (`var/concept-gap-analysis/gap-fk-58-70.md:458`). AG3-100 nennt #10 nur im Ist-Zustand (`stories/AG3-100-evaluate-scheduling-execution-input-surface/story.md:18`), lässt es aber in Scope/AC weg (`story.md:32`, `story.md:49`).  
  **Fix:** #10 in Scope + AC + Negativtest aufnehmen oder explizit mit Owner ausgrenzen. Bei Titel/Index „§70.11-Invarianten“ ist aufnehmen der richtige Schnitt.

**AC-Schaerfe: FAIL**
- **ERROR:** Wire-Feldnamen sind falsch/konfliktär. AG3-100 fordert `eligibleReady`/`totalReady`/`globalSlotsLeft` (`story.md:8`, `story.md:29`, `story.md:46`, `story.md:60`). Die formale Contract-Quelle definiert aber `eligible_ready`, `total_ready`, `global_slots_left` (`concept/formal-spec/frontend-contracts/entities.md:685`, `:694`, `:699`). AG3-091 grenzt CamelCase ausdrücklich als UI-Prototyp-Form aus und verlangt backend-seitig snake_case (`stories/AG3-091-frontend-read-models-execution-input-surface/story.md:32`, `:77`).  
  **Fix:** AG3-100 auf snake_case Wire-Shape umstellen oder klar sagen, dass diese Namen nur FK-Prosa/Domain-Aliase sind und die HTTP-Contract-AC gegen `frontend-contracts.entity.execution_input_snapshot` laufen.

- **WARNING:** Pflicht-Gates unvollständig. AG3-100 AC8 nennt lokale Tests/ruff/mypy/Konzept-Gates (`story.md:50`), aber AGENTS verlangt vor „fertig“ Jenkins und Sonar über `scripts/ci/check_remote_gates.ps1` (`AGENTS.md:31`, `:43`) mit strikt grünem Sonar-Ziel (`AGENTS.md:33-37`).  
  **Fix:** AC8/DoD um Remote-Gate aufnehmen.

**Klarheit: WEAK**
- **WARNING:** Der bestehende Startpfad wird nicht sauber als Migrationskontext beschrieben. Real existiert bereits ein pre-start guard in `control_plane.dispatch`, der vor frischem Setup `assess_readiness` konsumiert (`src/agentkit/control_plane/dispatch.py:14`, `:77`, `:277`, `:282`, `:626`). `PipelineEngine` selbst ruft keine Planning-Surface auf (`src/agentkit/pipeline_engine/engine.py:927`, `:938`, `:1018`, `:1095`). AG3-100 sagt nur „PipelineEngine-Code nicht verdrahtet“ (`story.md:17`, `:19`) und riskiert damit eine zweite Admission-Schicht statt Migration von `assess_readiness` zu `evaluate_scheduling`.  
  **Fix:** explizit aufnehmen: bestehende `PreStartGuard`/`SchedulingAdmissionReader`-Wiring muss auf `evaluate_scheduling` migriert oder bewusst ersetzt werden; keine parallele Guard-Wahrheit.

**Kontext-Sinnhaftigkeit: FAIL**
- **ERROR:** Duplicate Owner mit AG3-091. AG3-100 scoped `GET .../execution-input/snapshot` und `/next` vollständig (`story.md:29`, `:30`, `:45-47`). AG3-091 scoped dieselben Endpunkte ebenfalls als In-Scope (`stories/AG3-091-frontend-read-models-execution-input-surface/story.md:32-35`, `:55-58`) und der Story-Index weist AG3-091 „Execution-Input-Surface (`/execution-input/snapshot|next|limits`)" zu (`var/concept-gap-analysis/_STORY_INDEX.md:116`), während AG3-100 ebenfalls die Doppel-Surface besitzt (`_STORY_INDEX.md:136`).  
  **Fix:** Owner-Schnitt bereinigen. Entweder AG3-100 besitzt Domain-Selector + `evaluate_scheduling` + formale `execution_input_next` Reason-Entity, AG3-091 nur Read-Layer/Contract-Exposure; oder AG3-100 besitzt die Endpunkte und AG3-091 entfernt sie. In beiden Stories dieselbe Grenze dokumentieren.

**Verifizierte Ist-Zustand-Claims**
- `evaluate_scheduling` fehlt in `src/agentkit` und ist nicht in der public surface exportiert; `__init__.py` exportiert nur `assess_readiness`/Dependency-Funktionen (`src/agentkit/execution_planning/__init__.py:14-30`).
- Aktuelle execution-planning Routes sind dependency-graph/dependencies/next-ready/config (`src/agentkit/execution_planning/http/routes.py:39-52`, `:125-157`).
- FK-20 §20.8.2 existiert an den behaupteten Linien und fordert `evaluate_scheduling` vor Story-Start (`concept/technical-design/20_workflow_engine_state_machine.md:760-773`).
- Zykluserkennung existiert und `add_dependency` lehnt Zyklen ab, aber ohne Quarantaene/Eskalation (`src/agentkit/execution_planning/dependency_graph.py:48-59`, `src/agentkit/execution_planning/lifecycle.py:72-78`).

**Must-Fix**
1. §70.11 #10 in Scope/AC/Tests aufnehmen.
2. Duplicate Owner mit AG3-091 auflösen.
3. Wire-Feldnamen auf formale snake_case Contracts korrigieren.
4. Bestehenden `control_plane.dispatch` PreStartGuard als Migrationspunkt benennen.
5. Remote-Gates in AC/DoD ergänzen.
