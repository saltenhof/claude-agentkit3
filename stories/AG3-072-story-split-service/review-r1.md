OVERALL CHANGES-REQUESTED

**1) Konzept-Vollstaendigkeit: FAIL**

- **ERROR**: FK-54-Einstiegsvoraussetzungen fehlen als harter Service-/AC-Vertrag. `FK-54 §54.4` verlangt `scope_explosion`, menschliche Freigabe, Split-Plan und keine konkurrierende Admin-Operation (`concept/technical-design/54_story_split_service_scope_explosion.md:133`). Die Story erwähnt bestätigte `scope_explosion` nur im Kontext/Out-of-Scope (`stories/AG3-072-story-split-service/story.md:5`, `:48`), fordert aber keinen fail-closed Check/Negativtest.  
  **Fix:** In Scope und AC aufnehmen: reject ohne `scope_explosion`/PAUSED-Exploration/human approval/kein konkurrierender Admin-Op.

- **WARNING**: Der formale Split-Plan enthält `story_lineage` (`concept/formal-spec/story-split/entities.md:36-42`), die Story-Planstruktur nicht (`stories/AG3-072-story-split-service/story.md:39`).  
  **Fix:** Entweder `story_lineage` ins Planmodell aufnehmen oder explizit normieren, dass Lineage deterministisch aus `source_story_id` + `successors[]` abgeleitet wird.

**2) AC-Schaerfe: FAIL**

- **ERROR**: AC decken den formalen Negativpfad nicht ab. `formal.story-split.scenario.reject-without-scope-explosion-preconditions` fordert Failure ohne Preconditions (`concept/formal-spec/story-split/scenarios.md:36-44`); AC 1-11 testen nur Planvalidierung, Endzustand, Rebinding, Closure-Nichtnutzung usw. (`stories/AG3-072-story-split-service/story.md:55-66`).  
  **Fix:** AC fuer Precondition-Reject mit “keine Teilmutation” ergänzen.

- **ERROR**: Dependency-Rebinding ist zu schmal. Formale Rebinding-Invarianten verlangen no stale cancelled target, no silent drop, deterministic target selection, no unjustified fanout und graph integrity/cycle prevention (`concept/formal-spec/dependency-rebinding/invariants.md:30-44`). AC5 prüft nur stale pointer (`stories/AG3-072-story-split-service/story.md:60`).  
  **Fix:** ACs fuer silent drop, Fanout nur bei Planangabe, deterministische Wiederholung, keine Duplikate/Zyklen ergänzen.

- **WARNING**: Idempotenz ist nicht testbar spezifiziert. CLI hat laut FK nur `--story --plan --reason` (`concept/technical-design/54_story_split_service_scope_explosion.md:158-174`), AC10 spricht aber von “derselben `split_id`” (`stories/AG3-072-story-split-service/story.md:65`) ohne zu definieren, wie diese beim zweiten Lauf wiedergefunden/übergeben wird.  
  **Fix:** Resume-Key definieren, z. B. deterministisch aus `(project_key, source_story_id, plan_ref/hash)` oder Service-API mit explizitem `split_id`.

**3) Klarheit: WEAK**

- **ERROR**: Falsche Ist-Zustand-Behauptung zur Cancel-Transition. Story behauptet `In Progress → Cancelled` sei erlaubt (`stories/AG3-072-story-split-service/story.md:27`, wiederholt `:80`). Real ist es explizit verboten: `_ALLOWED_TRANSITIONS` enthält nur `Backlog/Approved -> Cancelled` (`src/agentkit/story_context_manager/service.py:80-89`), `_check_transition` wirft fuer `In Progress -> Cancelled` (`src/agentkit/story_context_manager/service.py:112-116`), `cancel_story` dokumentiert `In Progress or Done -> invalid_transition` (`src/agentkit/story_context_manager/service.py:602-604`).  
  **Fix:** Story muss einen offiziellen administrativen Cancel-Pfad fuer Split fordern oder klar sagen, dass der bestehende `cancel_story()`-Pfad nicht reicht.

**4) Kontext-Sinnhaftigkeit: FAIL**

- **ERROR**: Der Guard-AC vermischt Branch-Guard mit Backend-Servicepfad. Story sagt freie Git-/Backend-Mutation werde ueber vorhandene Branch-Guard-Allowlist getestet (`stories/AG3-072-story-split-service/story.md:64`), aber der reale Branch-Guard erlaubt nur Kommando-Prefixe fuer Git-/Branch-Kontext (`src/agentkit/governance/guards/branch_guard.py:23-26`). Offizielles Servicepfad-Verdict ist zugleich Out-of-Scope AG3-087 (`stories/AG3-072-story-split-service/story.md:52`).  
  **Fix:** AC9 trennen: Branch-Guard-Prefix hier testen; Backend-Servicepfad/`ALLOW_VIA_OFFICIAL_SERVICE_PATH` entweder als harte Dependency auf AG3-087 modellieren oder aus diesem AC entfernen.

**Verifizierte Anker**

- `StorySplitService` ist im Code nicht vorhanden; Suche nach `StorySplitService`/`split_from`/`split_successors`/`superseded_by` findet keinen Produktivpfad.
- Scope-Explosion-Detektion existiert: `src/agentkit/exploration/phase.py:119-121`, `src/agentkit/exploration/mandate/classification.py:80`, `src/agentkit/exploration/mandate/telemetry.py:85`.
- `split-story` ist reserviert/allowlisted: `src/agentkit/governance/principal_capabilities/operations.py:166-168`, `src/agentkit/governance/guards/branch_guard.py:23-26`.
- CLI hat keinen `split-story`-Subparser: `src/agentkit/cli/main.py:38-160`.
- Backlog-Erzeugung ist real: `src/agentkit/story_context_manager/service.py:378-384`.
- `phase_state_projection.purge_run`-Anker ist real: `src/agentkit/state_backend/store/projection_repositories.py:186-202`.

**Must-Fix**

1. Falsche `In Progress -> Cancelled`-Behauptung korrigieren und administrativen Split-Cancel-Pfad spezifizieren.
2. FK-54.4/formal preconditions als Scope + Negativtest aufnehmen.
3. Rebinding-ACs um no-silent-drop, Fanout, Determinismus und Zyklus-/Duplikatprüfung erweitern.
4. `split_id`/Resume-Key eindeutig definieren.
5. Guard-AC sauber zwischen Branch-Guard und AG3-087-Servicepfad trennen.
