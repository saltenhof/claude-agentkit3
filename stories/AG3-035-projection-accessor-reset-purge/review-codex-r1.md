# Codex-Review AG3-035 (giftig, unabhaengig)

Stand: 2026-05-31

Gepruefte Grundlagen:

- Commit `db5396c` (`git show`, `git show --stat`)
- `stories/AG3-035-projection-accessor-reset-purge/story.md`
- `concept/technical-design/69_qa_telemetrie_aggregation_dashboard.md` (FK-69)
- `concept/technical-design/68_telemetrie_eventing_workflow_metriken.md` (FK-68)
- `concept/formal-spec/telemetry-analytics/invariants.md`
- `CLAUDE.md` / lokale `AGENTS.md`-Regeln: ZERO DEBT, SINGLE SOURCE OF TRUTH, FAIL-CLOSED, NO ERROR BYPASSING, Severity-Semantik

## Gesamturteil

BLOCK.

Die Implementierung ist kein sauberer Abschluss von AG3-035, sondern eine Mischform aus teilweisem Accessor, weiterlaufenden Direktpfaden und im Code umdefinierten Akzeptanzkriterien. Mehrere Tests pinnen explizit Abweichungen von der Story statt sie sichtbar zu machen. Besonders kritisch: der produktive QA-Schreibpfad geht weiter am `ProjectionAccessor` vorbei, fc_*-Reset wird trotz FK-69-Pflicht vertagt, und der angeblich geloeste DRIFT-AG3-035 importiert weiterhin `state_backend.store.load_story_context`.

## Befunde

### 1. ERROR: `ProjectionKind` verletzt AK2 und ueberschreibt die Story im Code

Beleg:

- Story fordert acht Werte inklusive `WORKFLOW_METRICS`: `stories/AG3-035-projection-accessor-reset-purge/story.md:64` bis `story.md:72`, AK2 nochmals `story.md:147`.
- Code definiert nur sieben Werte: `src/agentkit/telemetry/projection_accessor.py:46` bis `projection_accessor.py:60`.
- Contract-Test pinnt die Abweichung aktiv: `tests/contract/telemetry/test_projection_accessor.py:32` bis `test_projection_accessor.py:62`.
- FK-69 selbst nennt sieben Tabellen: `concept/technical-design/69_qa_telemetrie_aggregation_dashboard.md:150` bis `69_qa_telemetrie_aggregation_dashboard.md:168`.

Was falsch ist:

Die Implementierung kann sich fachlich auf FK-69 stuetzen, aber sie darf nicht still die Story-AK umschreiben. Die Story ist laut Review-Auftrag die erste Pruefgrundlage. Ein Code-Kommentar `Story-Skizze ... faelschlich` in `projection_accessor.py:49` bis `projection_accessor.py:51` ist keine autoritative Scope-Aenderung. Das ist ZERO-DEBT-widrig, weil der Konflikt nicht in Story/Konzept aufgeloest wurde, sondern in Tests zugunsten der Implementierung festgeschrieben wird.

Konkreter Fix:

Entweder Story/AK2 formal korrigieren und `workflow_metrics` in AG3-035 explizit als Nicht-FK-69-Abgrenzung dokumentieren, oder `ProjectionKind.WORKFLOW_METRICS` samt Repository-/Purge-Vertrag implementieren. Ohne diese Entscheidung darf AK2 nicht als erfuellt gelten.

### 2. ERROR: AK1/AK5 verlangen `purge_for_story`, Code entfernt die Methode aktiv

Beleg:

- AK1 verlangt `write_projection`, `read_projection`, `purge_for_story`: `stories/AG3-035-projection-accessor-reset-purge/story.md:146`.
- AK5 beschreibt `purge_for_story`: `stories/AG3-035-projection-accessor-reset-purge/story.md:150`.
- Code implementiert nur `purge_run(project_key, story_id, run_id)`: `src/agentkit/telemetry/projection_accessor.py:282` bis `projection_accessor.py:287`.
- Test erwartet explizit, dass `purge_for_story` nicht existiert: `tests/unit/telemetry/test_purge_for_story.py:197` bis `test_purge_for_story.py:208`.
- FK-69 fordert run_id-scoped aktives Entfernen: `concept/technical-design/69_qa_telemetrie_aggregation_dashboard.md:383` bis `69_qa_telemetrie_aggregation_dashboard.md:386`.

Was falsch ist:

Run-Scoped Purge ist konzeptuell richtig. Aber die Story-AK wurden nicht angepasst. Der Test beweist nicht AK1, sondern das Gegenteil. Das ist kein PASS, sondern eine nicht formalisierte Vertragsaenderung.

Konkreter Fix:

Story-AK und Tests auf `purge_run(project_key, story_id, run_id)` aendern, falls diese Entscheidung autorisiert ist. Alternativ einen fail-closed `purge_for_story`-Endpoint nur mit vollstaendigem Scope-Resolver implementieren, der `project_key`/`run_id` zwingend aus kanonischem State ableitet und bei Mehrdeutigkeit abbricht.

### 3. ERROR: `write_projection`/`read_projection` sind fuer vier `ProjectionKind`s nur Attrappe

Beleg:

- FK-69 macht `ProjectionAccessor` zum DB-Owner aller Tabellen: `concept/technical-design/69_qa_telemetrie_aggregation_dashboard.md:171` bis `69_qa_telemetrie_aggregation_dashboard.md:188`.
- FK-69 beschreibt Lesen/Schreiben ueber `Telemetry.write_projection`/`Telemetry.read_projection`: `concept/technical-design/69_qa_telemetrie_aggregation_dashboard.md:355` bis `69_qa_telemetrie_aggregation_dashboard.md:358`.
- Typ-Mapping deckt nur `QA_STAGE_RESULTS`, `QA_FINDINGS`, `STORY_METRICS` ab: `src/agentkit/telemetry/projection_accessor.py:127` bis `projection_accessor.py:134`.
- Fuer `PHASE_STATE_PROJECTION` und `FC_*` wirft `write_projection` `NotImplementedError`: `src/agentkit/telemetry/projection_accessor.py:188` bis `projection_accessor.py:196`.
- `read_projection(PHASE_STATE_PROJECTION)` und `read_projection(FC_*)` werfen ebenfalls `NotImplementedError`: `src/agentkit/telemetry/projection_accessor.py:266` bis `projection_accessor.py:280`.
- Tests kodieren diese Nicht-Implementierung: `tests/unit/telemetry/test_projection_accessor.py:190` bis `test_projection_accessor.py:207`.

Was falsch ist:

AK3 fordert fail-closed Typvalidierung mit `ProjectionRecordTypeMismatchError`. Fuer vier Enum-Werte gibt es aber gar keinen erwarteten Record-Typ; der Pfad endet vorher in `NotImplementedError`. Das ist keine zentrale Schreib-/Lesegrenze, sondern ein partieller Router mit toten Enum-Werten.

Konkreter Fix:

Fuer jeden in `ProjectionKind` publizierten Wert einen echten Record-Typ, Repository-Port und read/write-Vertrag implementieren. Falls bestimmte Tabellen bewusst nicht schreibbar sind, duerfen sie nicht als normale `ProjectionKind`-Werte im AK3-Vertrag erscheinen, sondern brauchen einen getrennten Purge-/Read-Scope mit eigener Story-Aenderung.

### 4. ERROR: fc_*-Reset-Purge ist gegen FK-69 vertagt, nicht erledigt

Beleg:

- FK-69 sagt fuer fc_* ausdruecklich: bei Reset eines `run_id` muessen `fc_incidents` entfernt und `fc_patterns` korrigiert/reberechnet werden: `concept/technical-design/69_qa_telemetrie_aggregation_dashboard.md:365` bis `69_qa_telemetrie_aggregation_dashboard.md:368`.
- Formal-Spec fordert, dass ein voller Reset alle read models/facts invalidiert oder purgt: `concept/formal-spec/telemetry-analytics/invariants.md:45` bis `invariants.md:47`.
- Code dokumentiert die Vertagung als `# DRIFT-AG3-028`: `src/agentkit/telemetry/projection_accessor.py:299` bis `projection_accessor.py:303`.
- Purge-Schleife beruehrt nur vier Tabellen: `src/agentkit/telemetry/projection_accessor.py:321` bis `projection_accessor.py:326`.
- Test erwartet keine fc_*-Purge-Aufrufe: `tests/unit/telemetry/test_purge_for_story.py:160` bis `test_purge_for_story.py:189`.

Was falsch ist:

Die Story selbst sagt in AK5, fc_*-Tabellen wuerden nicht geloescht. FK-69 sagt fuer fc_incidents das Gegenteil. Diese Spannung ist nicht sauber entschieden. Der Code macht daraus technische Schuld mit Marker, aber der Review-Auftrag verlangt gerade die Pruefung gegen FK-69 und formal invariant. Nach Severity-Semantik ist das ERROR: ein Reset darf keine korrupten run_id-Zeilen in FK-69-nahen Read Models stehen lassen.

Konkreter Fix:

fc_incidents-Purge und fc_patterns-Recompute/Invalidation in denselben Reset-Purge-Vertrag aufnehmen oder FK-69/Story formal konsistent aendern. Ein Test muss echte persistierte fc_* Daten fuer einen reset run anlegen und beweisen, dass nach Purge keine betroffenen Zeilen/Facts mehr beitragen.

### 5. ERROR: Produktiver QA-Schreibpfad umgeht den `ProjectionAccessor`

Beleg:

- Story verlangt Migration der verify-system-Schreibstellen auf `ProjectionAccessor.write_projection`: `stories/AG3-035-projection-accessor-reset-purge/story.md:82` bis `story.md:83`, AK4 `story.md:149`.
- FK-69-Datenfluss nennt `ProjectionAccessor (write_projection)` vor `qa_stage_results`: `concept/technical-design/69_qa_telemetrie_aggregation_dashboard.md:451` bis `69_qa_telemetrie_aggregation_dashboard.md:454`.
- `ImplementationPhaseHandler` importiert und ruft weiter `record_layer_artifacts`: `src/agentkit/implementation/phase.py:29` bis `phase.py:33`, Aufruf `phase.py:168` bis `phase.py:173`.
- `record_layer_artifacts` baut QA-Zeilen und delegiert direkt an den Backend-Treiber: `src/agentkit/state_backend/store/facade.py:891` bis `facade.py:924`.
- Postgres-Treiber schreibt direkt per `pg_delete_findings_for_scope`, `pg_execute_stage_upsert`, `pg_execute_finding_upsert`: `src/agentkit/state_backend/postgres_store.py:2268` bis `postgres_store.py:2288`.
- Der neue Accessor-Batchpfad `write_qa_layer_batch` existiert, wird aber in Produktivcode nicht gefunden; er ist nur in Tests benutzt: `src/agentkit/telemetry/projection_accessor.py:352` bis `projection_accessor.py:377`, Testnutzung `tests/unit/telemetry/test_projection_roundtrip.py:347`.

Was falsch ist:

Das ist der zentrale SoT-Bruch dieser Story. Der Accessor ist nicht die einzige Schreibgrenze; der laufende QA-Subflow schreibt seine FK-69-Read-Models weiter ueber State-Backend-Fassade/Treiber. Dass der Treiber die gleiche SQL-Funktion nutzt, heilt den Architekturbruch nicht: der fachliche Eintrittspunkt ist nicht `ProjectionAccessor.write_projection`.

Konkreter Fix:

Den QA-Batch-Schreibpfad hinter einen injizierten `ProjectionAccessor`/Batch-Port ziehen. Die Transaktion darf im Driver bleiben, aber der Aufrufpfad aus Implementation/Verify muss den Accessor als fachliche Schreibgrenze benutzen. Zusaetzlich einen Architecture-Test einbauen, der produktive Aufrufer von `record_layer_artifacts` fuer FK-69-Schreiben blockiert oder explizit nur Artefaktpersistenz erlaubt.

### 6. ERROR: DRIFT-AG3-035 ist nicht aufgeloest; `VerifySystem` importiert weiter `state_backend.store.load_story_context`

Beleg:

- Story erlaubt Aufloesung via StoryContext-Injection und sagt, sonst bleibt der Drift: `stories/AG3-035-projection-accessor-reset-purge/story.md:163` bis `story.md:169`.
- User-Pruefpunkt verlangt: kein direkter `state_backend`-Import fuer StoryContext mehr.
- Code importiert direkt in `run_qa_subflow`: `src/agentkit/verify_system/system.py:299` bis `system.py:306`.
- Der Kommentar behauptet nur, der Import sei nicht mehr in `_execute_layer`: `src/agentkit/verify_system/system.py:515` bis `system.py:518`.
- Contract-Test prueft nur den alten Marker-String, nicht den Direct Import selbst: `tests/contract/telemetry/test_projection_accessor.py:98` bis `test_projection_accessor.py:112`.

Was falsch ist:

Der Drift wurde verschoben, nicht geloest. `VerifySystem` kennt weiterhin `state_backend.store` fuer StoryContext. Der Test ist zu schwach, weil er nur die alte Kommentarform sucht. Das verletzt SINGLE SOURCE OF TRUTH und die BC-Topologie-Vorgabe der Story.

Konkreter Fix:

StoryContext als Port/Parameter in die VerifySystem-Top-Surface injizieren, z. B. ueber Composition Root oder einen klaren Query-Port. Den Direct Import aus `verify_system/system.py` entfernen und einen Test schreiben, der `agentkit.backend.state_backend.store`-Importe in `verify_system` fuer StoryContext verbietet.

### 7. WARNING: Tests beweisen die kritischen Negativpfade nicht an echten Phasen-/Persistenzgrenzen

Beleg:

- Telemetry-Integrationstest ist nur ein Import-/Builder-Smoke, kein write->read Roundtrip: `tests/integration/telemetry/test_projection_roundtrip.py:13` bis `test_projection_roundtrip.py:48`.
- Typ-Mismatch-Tests decken nur die drei implementierten Kinds ab: `tests/unit/telemetry/test_projection_accessor.py:145` bis `test_projection_accessor.py:180`.
- Nicht-implementierte Kinds werden als `NotImplementedError` akzeptiert: `tests/unit/telemetry/test_projection_accessor.py:190` bis `test_projection_accessor.py:207`.
- fc_*-Purge-Test nutzt Mocks und beweist nur, dass kein fc_*-Call erfolgt: `tests/unit/telemetry/test_purge_for_story.py:160` bis `test_purge_for_story.py:189`.
- `write_qa_layer_batch` wird in Tests direkt aufgerufen, aber der produktive `ImplementationPhaseHandler -> record_layer_artifacts`-Pfad ruft ihn nicht auf: `src/agentkit/implementation/phase.py:168` bis `phase.py:173`.

Was falsch ist:

Die Tests schuetzen die falschen Vertraege. Sie pruefen isolierte Accessor-Aufrufe, waehrend der echte QA-Pfad am Accessor vorbeigeht. Das ist nach Test-Guardrails eine Coverage-Luecke an der Phasengrenze.

Konkreter Fix:

Integrationstest ueber den echten Implementation-/Verify-Pfad: QA-Subflow laufen lassen, Accessor als injizierten Spy/Port verwenden, danach read_projection gegen echte Persistenz. Negativtest: falscher Record-Typ fuer jeden publizierten ProjectionKind; Reset-Purge mit echten qa_*, story_metrics, phase_state_projection und fc_*-Zeilen.

## AK-Matrix

| AK | Status | Beleg |
|---|---|---|
| AK1 | teilweise | `ProjectionAccessor` existiert und hat `write_projection`/`read_projection` (`src/agentkit/telemetry/projection_accessor.py:150`, `projection_accessor.py:167`, `projection_accessor.py:220`), aber keine `purge_for_story`; stattdessen `purge_run` (`projection_accessor.py:282`) und Test gegen `purge_for_story` (`tests/unit/telemetry/test_purge_for_story.py:197`). |
| AK2 | verletzt | Story fordert acht Werte inklusive `WORKFLOW_METRICS` (`story.md:64` bis `story.md:72`, `story.md:147`); Code hat sieben Werte ohne `workflow_metrics` (`projection_accessor.py:46` bis `projection_accessor.py:60`). |
| AK3 | teilweise | Typfehler wirft fuer drei aktive Kinds `ProjectionRecordTypeMismatchError` (`projection_accessor.py:198` bis `projection_accessor.py:203`); fuer `PHASE_STATE_PROJECTION` und `FC_*` endet der Pfad vor Typvalidierung in `NotImplementedError` (`projection_accessor.py:188` bis `projection_accessor.py:196`). |
| AK4 | teilweise | Closure schreibt ueber Accessor (`src/agentkit/closure/phase.py:258` bis `phase.py:269`); produktive QA-Schreibroute geht aber weiter ueber `record_layer_artifacts`/Backend-Treiber (`src/agentkit/implementation/phase.py:168`, `src/agentkit/state_backend/postgres_store.py:2268` bis `postgres_store.py:2288`). |
| AK5 | teilweise | Run-scoped Delete fuer vier Tabellen ist vorhanden (`projection_accessor.py:321` bis `projection_accessor.py:350`), aber `purge_for_story` fehlt, `workflow_metrics` fehlt, und fc_*-Reset widerspricht FK-69 (`concept/.../69_qa_telemetrie_aggregation_dashboard.md:365` bis `:368`). |
| AK6 | teilweise | SQLite/unit Roundtrips existieren, aber der Integrationstest ist nur Smoke (`tests/integration/telemetry/test_projection_roundtrip.py:13` bis `:48`) und beweist nicht den echten verify-system Schreibpfad via Accessor. |
| AK7 | erfuellt | `ProjectionAccessor` liegt in `agentkit.backend.telemetry` (`projection_accessor.py:1`) und importiert keine konkrete `state_backend.store`-Fassade; `ProjectionRepositories` ist nur unter `TYPE_CHECKING` referenziert (`projection_accessor.py:34` bis `:38`), konkrete Verdrahtung liegt im Composition Root (`src/agentkit/bootstrap/composition_root.py:154` bis `:181`). |
| AK8 | teilweise | Lokal geprueft: `.venv\Scripts\python -m pytest tests/unit/telemetry tests/contract/telemetry -q` = 105 passed; `.venv\Scripts\python -m pytest tests/integration/telemetry -q` = 3 passed; `ruff check src tests` und `mypy src` gruen. Nicht geprueft in diesem Review: Coverage 85%, Jenkins, Sonar Quality Gate. |

## Was gut ist

- DI-Schnitt fuer `ProjectionAccessor` ist im Accessor selbst sauber gehalten; kein direkter Facade-Import im Accessor.
- Run-scoped Purge ist fuer `qa_stage_results`, `qa_findings`, `story_metrics` und `phase_state_projection` technisch umgesetzt.
- Die lokale Telemetry-Testauswahl, `ruff` und `mypy` sind gruen gelaufen.
