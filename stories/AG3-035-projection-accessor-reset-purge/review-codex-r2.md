# Codex-Review AG3-035 Recheck Runde 2

Stand: 2026-05-31

Gepruefte Grundlagen:

- Commit `2c0eefb` (`git show`, `git show --stat`)
- `stories/AG3-035-projection-accessor-reset-purge/story.md`
- `stories/AG3-028-failure-corpus-top-surface/story.md`
- `concept/technical-design/69_qa_telemetrie_aggregation_dashboard.md`
- `concept/technical-design/41_failure_corpus_pattern_promotion_check_factory.md`
- `src/agentkit/telemetry/projection_accessor.py`
- `src/agentkit/state_backend/store/projection_repositories.py`
- `src/agentkit/implementation/phase.py`
- `src/agentkit/verify_system/system.py`
- `tests/unit/telemetry/test_projection_roundtrip.py`
- `tests/contract/telemetry/test_projection_accessor.py`
- `tests/unit/telemetry/test_purge_for_story.py`

## Gesamturteil

BLOCK.

Der urspruengliche BLOCK ist nicht aufgehoben. Die LightWild-Remediation hat
den groessten echten SoT-Bruch (#5) fachlich ordentlich in den Accessor gezogen
und die Story-Drifts #1/#2 sauber an FK-69 angepasst. Das reicht aber nicht:
Der Accessor publiziert weiter `ProjectionKind`-Werte, fuer die `write_projection`
und `read_projection` bewusst in `NotImplementedError` enden (#3), und der
DRIFT-AG3-035 wurde kosmetisch weggetestet statt aufgeloest (#6). Besonders
giftig: `verify_system/system.py` importiert weiterhin
`state_backend.store.load_story_context`, waehrend der neue Contract-Test nur
den alten Marker-String sucht. Das ist keine Remediation, das ist ein
Semantik-Etikett.

## Runde-1-Befunde

### #1 ProjectionKind 8 vs 7

Verdikt: RESOLVED-BY-SCOPE-DECISION. Die Scope-Entscheidung ist legitim.

Beleg:

- FK-69 autorisiert genau sieben Tabellen: `concept/technical-design/69_qa_telemetrie_aggregation_dashboard.md:148` bis `:168`.
- Die aktualisierte Story nennt genau diese sieben Werte und grenzt `workflow_metrics` als FK-68 ab: `stories/AG3-035-projection-accessor-reset-purge/story.md:75` bis `:88`, AK2 `story.md:182`.
- Der Code definiert genau sieben Werte ohne `workflow_metrics`: `src/agentkit/telemetry/projection_accessor.py:49` bis `:63`.
- Der Contract-Test pinnt die Abgrenzung: `tests/contract/telemetry/test_projection_accessor.py:32` bis `:61`.

Bewertung: Das war in Runde 1 kein Code-Fehler, sondern eine unentschiedene
Story-vs-Konzept-Spannung. Sie ist jetzt formal in der Story korrigiert. Kein
BLOCK mehr fuer #1.

### #2 `purge_for_story` vs `purge_run`

Verdikt: RESOLVED-BY-SCOPE-DECISION. Die Scope-Entscheidung ist legitim.

Beleg:

- Die aktualisierte Story verlangt `purge_run(project_key, story_id, run_id)`: `stories/AG3-035-projection-accessor-reset-purge/story.md:55` bis `:61`, `story.md:113` bis `:118`, AK1/AK5 `story.md:181` und `story.md:185`.
- Der Code implementiert exakt diese Signatur: `src/agentkit/telemetry/projection_accessor.py:285` bis `:300`.
- Der Test stellt sicher, dass `purge_for_story` nicht als stiller Alias bleibt: `tests/unit/telemetry/test_purge_for_story.py:197` bis `:208`.

Bewertung: Run-Scoped Purge ist die richtige fachliche API. Ein
story_id-only-Endpoint waere fuer Reset-Semantik zu weich. Kein BLOCK mehr fuer
#2.

### #3 Partielle `write_projection`/`read_projection`-Implementierung

Verdikt: STILL-OPEN. Severity: ERROR.

Beleg:

- Die Story beschreibt den `ProjectionAccessor` als DB-Owner und zentrale
  Schreib-/Lese-Grenze fuer Projektionsdaten: `stories/AG3-035-projection-accessor-reset-purge/story.md:33` bis `:37`.
- `ProjectionKind` publiziert sieben FK-69-Werte inklusive
  `PHASE_STATE_PROJECTION` und `FC_*`: `story.md:75` bis `:83` und
  `src/agentkit/telemetry/projection_accessor.py:57` bis `:63`.
- `write_projection` kennt aber nur `QA_STAGE_RESULTS`, `QA_FINDINGS` und
  `STORY_METRICS`; fuer `PHASE_STATE_PROJECTION` und `FC_*` wird vor jeder
  Typvalidierung `NotImplementedError` geworfen: `src/agentkit/telemetry/projection_accessor.py:120` bis `:137`, `projection_accessor.py:170` bis `:199`.
- `read_projection(PHASE_STATE_PROJECTION)` und `read_projection(FC_*)` sind
  ebenfalls nur harte `NotImplementedError`-Pfade: `src/agentkit/telemetry/projection_accessor.py:269` bis `:282`.
- Die Tests akzeptieren genau diese Nicht-Implementierung: `tests/unit/telemetry/test_projection_accessor.py:186` bis `:207`, `test_projection_accessor.py:278` bis `:295`.

Was daran falsch ist:

Die Remediation hat diesen Befund nicht fachlich geloest, sondern nur
umetikettiert. Wenn ein `ProjectionKind` als kanonischer Tabellenwert
veroeffentlicht ist, dann darf der zentrale Accessor-Vertrag nicht so tun, als
sei `write_projection`/`read_projection` allgemein vorhanden, waehrend vier
publizierte Kinds in `NotImplementedError` laufen. Das ist genau die Art von
halbfertigem Architekturuebergang, die ZERO DEBT verbietet.

Minimal sauber waeren zwei Wege: entweder die Story und die API trennen aktive
Projection-Kinds von reservierten/future Kinds explizit, oder die fehlenden
Record-/Repo-/Read-Write-Vertraege werden umgesetzt. Der aktuelle Zustand ist
nicht fail-closed im Sinne eines sauberen Vertrags, sondern ein Runtime-Stopp an
einer zu breit publizierten API.

### #4 fc_*-Reset-Purge

Verdikt: RESOLVED-BY-SCOPE-DECISION. Die Scope-Entscheidung ist legitim, aber nur
weil AG3-028 jetzt einen konkreten Handlungsauftrag traegt.

Beleg:

- FK-69 stellt klar: `fc_incidents` des reset `run_id` muessen weg,
  `fc_patterns.incident_count` wird korrigiert/reberechnet,
  `fc_check_proposals` bleiben unberuehrt: `concept/technical-design/69_qa_telemetrie_aggregation_dashboard.md:365` bis `:374`.
- FK-41 sagt dasselbe fachlich: `fc_incidents` werden beim vollstaendigen
  Story-Reset geloescht (`concept/technical-design/41_failure_corpus_pattern_promotion_check_factory.md:181` bis `:182`), `fc_patterns.incident_count` wird neu berechnet (`:213` bis `:215`), `fc_check_proposals` bleiben unberuehrt (`:256` bis `:257`).
- AG3-035 dokumentiert die Vertagung auf AG3-028 explizit: `stories/AG3-035-projection-accessor-reset-purge/story.md:126` bis `:133`.
- AG3-028 hat jetzt einen konkreten Abschnitt, betroffene Dateien und AK9 fuer
  `fc_incidents`-Purge: `stories/AG3-028-failure-corpus-top-surface/story.md:186` bis `:207`, `story.md:246` bis `:248`, AK9 `story.md:272`.
- Der Code traegt den Marker offen: `src/agentkit/telemetry/projection_accessor.py:302` bis `:306`.

Bewertung: Das ist keine stille Schuld mehr. Die Pflicht ist owner-bezogen nach
AG3-028 verschoben, wo `fc_incidents` entsteht. Giftig formuliert: Das ist nur
deshalb akzeptabel, weil AG3-028 nun wirklich einen testbaren AK9 hat. Ohne
diesen AK waere #4 weiter ERROR.

### #5 Produktiver QA-Schreibpfad umgeht den Accessor

Verdikt: RESOLVED.

Beleg:

- `ImplementationPhaseHandler` importiert `record_layer_artifacts` nicht mehr
  direkt, sondern baut den Accessor und ruft
  `record_qa_layer_artifacts`: `src/agentkit/implementation/phase.py:168` bis `:180`.
- `ProjectionAccessor.record_qa_layer_artifacts` ist jetzt der fachliche
  Eintrittspunkt und delegiert an den injizierten Batch-Port:
  `src/agentkit/telemetry/projection_accessor.py:355` bis `:393`.
- Der Port ist in der Repository-Schicht modelliert:
  `src/agentkit/state_backend/store/projection_repositories.py:184` bis `:204`.
- Die konkrete Adapterklasse kapselt den bestehenden atomaren Facade-/Driver-
  Batch in der DB-Schicht: `src/agentkit/state_backend/store/projection_repositories.py:934` bis `:959`.
- Die Composition verdrahtet den Port: `src/agentkit/state_backend/store/projection_repositories.py:962` bis `:981`.
- Produktivcode ausserhalb der DB-Schicht ruft `record_layer_artifacts` nicht
  mehr; die verbleibenden Produktionsvorkommen liegen in Facade, Repository-
  Adapter, Public API und Dokumentations-/Contract-Texten.

Bewertung: Das ist die richtige Reparatur. Die Transaktion bleibt dort, wo sie
hingehoert, aber der fachliche Eintrittspunkt ist nun der Accessor. Kein BLOCK
mehr fuer #5.

### #6 DRIFT-AG3-035 / `VerifySystem` importiert weiter `load_story_context`

Verdikt: STILL-OPEN. Severity: ERROR.

Beleg:

- Die Story sagt selbst, dass diese Story den Drift schliesst oder andernfalls
  der `# DRIFT-AG3-035`-Kommentar im Code bleibt: `stories/AG3-035-projection-accessor-reset-purge/story.md:196` bis `:204`.
- `verify_system/system.py` importiert weiterhin direkt aus
  `agentkit.state_backend.store`: `src/agentkit/verify_system/system.py:299` bis `:306`.
- Der Kontext wird dann an `_execute_layer` injiziert: `src/agentkit/verify_system/system.py:327` bis `:331`, `system.py:343` bis `:348`.
- `_execute_layer` selbst nutzt den injizierten Wert oder faellt auf einen Stub
  zurueck: `src/agentkit/verify_system/system.py:514` bis `:529`.
- Der Contract-Test prueft nur, ob der alte Marker-String
  `'load_story_context  # DRIFT-AG3-035'` verschwunden ist:
  `tests/contract/telemetry/test_projection_accessor.py:98` bis `:112`. Er
  prueft nicht, ob der Direct Import verschwunden ist.

Was daran falsch ist:

Das ist keine Scope-Entscheidung, die ZERO DEBT sauber ueberlebt. Wenn der Drift
bewusst offen bleiben soll, muss er offen markiert bleiben und aktiv an den
Auftraggeber gespiegelt werden. Hier wurde der Marker entfernt, der Direktimport
steht weiter im VerifySystem, und der Test sucht nur nach der alten
Kommentarform. Das ist ein kosmetischer Fix: Der Bruch wurde aus der
Nachweisflaeche entfernt, nicht aus dem Modell.

Konkreter Fix:

Entweder den StoryContext wirklich ueber einen Top-Surface-/Composition-Port
injizieren und den `state_backend.store`-Import aus `verify_system/system.py`
entfernen, oder den Drift explizit mit `# DRIFT-AG3-035` im Code stehen lassen
und diese Story nicht als Drift-geschlossen verkaufen. Der aktuelle Zustand ist
fail-open gegen die eigene Drift-Semantik.

### #7 Testabdeckung an echten Grenzen

Verdikt: STILL-OPEN. Severity: WARNING.

Beleg:

- Es gibt einen Spy-Test fuer `record_qa_layer_artifacts`:
  `tests/unit/telemetry/test_projection_roundtrip.py:324` bis `:354`.
- Es gibt einen echten Accessor -> BatchWriter -> Facade/Driver-Test:
  `tests/unit/telemetry/test_projection_roundtrip.py:356` bis `:449`.
- Der Test behauptet aber, der produktive End-to-End-Pfad sei in
  `tests/unit/implementation/test_implementation_phase.py` abgedeckt:
  `tests/unit/telemetry/test_projection_roundtrip.py:330` bis `:332`. In dieser
  Datei gibt es keinen Treffer fuer `record_qa_layer_artifacts`,
  `build_projection_accessor` oder `record_layer_artifacts`.
- Der Integrationstest fuer Telemetry bleibt ein Import-/Builder-Smoke:
  `tests/integration/telemetry/test_projection_roundtrip.py:13` bis `:48`.
- Der schwache Drift-Test fuer #6 ist ein konkretes Beispiel fuer eine
  Nachweislaecke: `tests/contract/telemetry/test_projection_accessor.py:98` bis `:112`.

Bewertung: Die Remediation hat die Lage verbessert, aber nicht auf das Niveau,
das die Runde-1-Warnung verlangt hat. Der neue echte Batch-Chain-Test ist
wertvoll, beweist aber nicht, dass `ImplementationPhaseHandler` im Test wirklich
ueber den Accessor laeuft. Diese Warnung darf nicht versanden: Wie wollen wir
hier vorgehen?

## Neue Befunde durch die Remediation

### N1. ERROR: Drift-Test testet Marker-Kosmetik statt Architekturbruch

Beleg:

- `tests/contract/telemetry/test_projection_accessor.py:98` bis `:112` sucht
  nur den alten String `'load_story_context  # DRIFT-AG3-035'`.
- Der Direct Import steht weiterhin in `src/agentkit/verify_system/system.py:304`.

Bewertung: Das ist kein harmloser schwacher Test, sondern ein falsch positives
Architektur-Signal. Der Testname sagt "resolved", obwohl der Import weiter
existiert. Das muss korrigiert werden.

### N2. WARNING: Lazy Composition-Root-Import in `implementation/phase.py`

Beleg:

- `ImplementationPhaseHandler` importiert `build_projection_accessor` innerhalb
  des Laufzeitpfads: `src/agentkit/implementation/phase.py:172`.
- Das Muster existiert analog in Closure: `src/agentkit/closure/phase.py:258` bis `:269`.

Bewertung: Kein BLOCK. Das ist im aktuellen Repo ein akzeptiertes
Anti-Circular-/Composition-Muster. Fachlich sauberer waere langfristig DI ueber
den Handler-Konstruktor, aber fuer diese LightWild-Remediation ist das keine
neue rote Stelle. Wie wollen wir hier vorgehen?

## AK-Matrix gegen aktualisierte Story

| AK | Status | Beleg |
|---|---|---|
| AK1 | TEILWEISE | `ProjectionAccessor` existiert mit `write_projection`, `read_projection`, `purge_run` und `record_qa_layer_artifacts`: `src/agentkit/telemetry/projection_accessor.py:153`, `:170`, `:223`, `:285`, `:355`. Aber der Vertrag ist fuer mehrere publizierte Kinds nur partiell (#3). |
| AK2 | ERFUELLT | Story fordert sieben Werte ohne `workflow_metrics` (`story.md:181` bis `:182`); Code hat exakt diese sieben (`projection_accessor.py:49` bis `:63`); Contract-Test pinnt das (`tests/contract/telemetry/test_projection_accessor.py:32` bis `:61`). |
| AK3 | TEILWEISE | Typvalidierung funktioniert fuer aktive Kinds (`src/agentkit/telemetry/projection_accessor.py:191` bis `:206`), aber fuer `PHASE_STATE_PROJECTION` und `FC_*` kommt vorher `NotImplementedError` (`projection_accessor.py:193` bis `:199`). |
| AK4 | TEILWEISE | Produktiver QA-Batch laeuft jetzt ueber `record_qa_layer_artifacts` (`src/agentkit/implementation/phase.py:168` bis `:180`), Closure schreibt `StoryMetricsRecord` ueber `write_projection` (`src/agentkit/closure/phase.py:258` bis `:269`). Die Story nennt aber `verify_system/qa_read_models.py`; der eigentliche produktive Pfad sitzt in `implementation/phase.py`. Als Zielbild ok, als Wortlaut unscharf. |
| AK5 | ERFUELLT IM AKTUALISIERTEN SCOPE | `purge_run` loescht die vier aktiven Tabellen (`src/agentkit/telemetry/projection_accessor.py:324` bis `:349`); Tests pruefen die vier Repo-Aufrufe (`tests/unit/telemetry/test_purge_for_story.py:55` bis `:69`) und die fc_*-Vertagung (`test_purge_for_story.py:161` bis `:184`). AG3-028 traegt AK9 fuer `fc_incidents`. |
| AK6 | TEILWEISE | SQLite Roundtrips existieren fuer aktive Kinds (`tests/unit/telemetry/test_projection_roundtrip.py:63` bis `:84` exemplarisch) und Purge echte Zeilen (`test_projection_roundtrip.py:193` bis `:295`). Der Integrationstest bleibt aber nur Smoke (`tests/integration/telemetry/test_projection_roundtrip.py:13` bis `:48`). |
| AK7 | TEILWEISE | `ProjectionAccessor` importiert keine konkrete Facade und delegiert an `ProjectionRepositories`/Port (`src/agentkit/telemetry/projection_accessor.py:389` bis `:393`). Die Facade-Kapselung liegt in der Store-Schicht (`projection_repositories.py:934` bis `:959`). Aber der angrenzende VerifySystem-Drift importiert weiter `state_backend.store.load_story_context` (`src/agentkit/verify_system/system.py:299` bis `:306`), was die BC-Schnitt-Story nicht sauber abschliesst. |
| AK8 | NICHT VON MIR VOLL REPRODUZIERT | Auftraggeber-Evidenz: Jenkins Build #10 SUCCESS, Sonar Quality Gate OK, lokal 2554 passed/25 skipped, ruff clean, mypy 324 files. Ich habe in dieser Recheck-Runde die Dateien/Diffs geprueft; die vollstaendige lokale Suite wurde nicht erneut gestartet. |

## Schluss

Die Remediation ist besser als Runde 1, aber nicht gut genug fuer PASS. #5 ist
fachlich repariert. #1/#2/#4 sind als Scope-Entscheidungen tragbar. #3 und #6
bleiben rote Stellen; #6 ist besonders klar, weil der Direct Import weiterlebt
und nur der Marker-Test beruhigt wurde. Gesamturteil: BLOCK.
