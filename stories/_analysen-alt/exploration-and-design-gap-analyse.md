# exploration-and-design — GAP-Analyse

> Generiert von einem dedizierten Sonnet-Sub-Agent (Stand 2026-05-16).

## Header

| Feld | Wert |
|---|---|
| BC-ID | `exploration-and-design` |
| Display-Name | `Exploration und Design` |
| Analyse-Datum | `2026-05-16` |
| Konzept-Quellen (autoritativ) | `FK-23, FK-25, formal.exploration.entities, formal.exploration.state-machine, formal.exploration.commands, formal.exploration.events, formal.exploration.invariants, formal.exploration.scenarios` |
| Codebase-Hauptpfade | `src/agentkit/pipeline_engine/exploration_phase/`, `src/agentkit/pipeline/phases/exploration/`, `src/agentkit/process/language/`, `src/agentkit/story_context_manager/` |

## 1. Executive Summary

Der BC `exploration-and-design` ist konzeptionell vollstaendig spezifiziert (FK-23, FK-25, sieben formale Spec-Dateien) und in Teilen in Datenmodellen und Guard-Logik verankert, aber die produktive Phasendurchfuehrung fehlt vollstaendig. Weder `ExplorationPhaseHandler` noch seine Sub-Komponenten `ExplorationDrafting`, `ExplorationReview` und `MandateClassification` existieren als Quellcode. Das `ExplorationPayload`-Modell verwendet `gate_status: str | None` statt des normierten `ExplorationGateStatus`-StrEnum. Der Exploration-Guard prueft nur `PhaseStatus.COMPLETED`, nicht `payload.gate_status == APPROVED`, was die Defense-in-Depth-Anforderung aus FK-23 §23.5 verletzt.

| Kategorie | Anzahl |
|---|---|
| A — Nicht umgesetzt | 8 |
| B — Teilweise umgesetzt | 4 |
| C — Drift / Fehler | 3 |

## 2. Konzept-Soll (Kurzfassung)

- **Modus-Ermittlung deterministisch (fail-closed, Default Exploration):** `ModeRouter` prueft Exploration-Trigger und VektorDB-Konflikte; bei Unklarheit greift Exploration Mode — `FK-23 §23.2`
- **ExplorationPayload mit ExplorationGateStatus StrEnum (PENDING/APPROVED/REJECTED):** Typisiertes Gate-Status-Feld, nicht freier String — `FK-23 §23.5.0`
- **Dreistufiges Exit-Gate (Stufe 1 Dokumententreue, Stufe 2a Design-Review, Stufe 2b Design-Challenge):** Stufe 1 binaer via StructuredEvaluator, Stufe 2a mit Remediation-Loop (max 3 Runden) — `FK-23 §23.5.1 bis §23.5.3`
- **Entwurfsartefakt (Change-Frame) mit sieben Pflichtbestandteilen und JSON-Schema:** Artefakt bleibt editierbar bis Gate-PASS, Freeze erst danach — `FK-23 §23.4, FK-25 §25.4.2`
- **Nachklassifikation (H2) mit vier Eskalationsklassen (Prueffolge 1→3→4→2):** LLM-gestuetzter semantischer Prozess mit deterministischen Teilberechnungen fuer Klasse 3/4 — `FK-25 §25.3, §25.4.1`
- **Feindesign-Subprozess (Klasse 2) mit Multi-LLM-Diskussion:** ChatGPT Pflicht, Qwen bevorzugt; max 10 Runden; AgentKit ueberwacht via Hook und Hub-Session-Summary — `FK-25 §25.5`
- **Scope-Explosion-Erkennung mit quantitativen Indikatoren:** Zwei oder mehr Hoch-Indikatoren loesen Klasse-3-Eskalation aus — `FK-25 §25.6`
- **Drift-Erkennung und Telemetrie-Events waehrend Implementation:** `drift_check`-Events pro Inkrement; signifikanter Drift erzwingt Selbstkorrektur oder BLOCKED — `FK-23 §23.7`
- **Impact-Violation-Check im QA-Subflow (Schicht 1):** Tatsaechlicher vs. deklarierter Impact via Git-Diff; FAIL = ESCALATED — `FK-23 §23.8`
- **Formale Spec vollstaendig umgesetzt:** Entities, State-Machine, Commands, Events, Invariants, Scenarios — `formal.exploration.*`
- **Exploration-Exit-Gate prueft payload.gate_status == APPROVED (Defense-in-Depth):** Guard reicht nicht; Payload muss APPROVED tragen — `FK-23 §23.5.0, FK-45 §45.2`
- **Telemetrie-Events fuer Mandate und Feindesign-Entscheidungen:** `mandate_classification`, `fine_design_decision`, `scope_explosion_check`, `impact_exceedance_check` — `FK-25 §25.8`

## 3. Code-Stand (Ist-Bild)

- `src/agentkit/story_context_manager/models.py:ExplorationPayload` — vorhanden, aber `gate_status: str | None` statt `ExplorationGateStatus`-StrEnum
- `src/agentkit/story_context_manager/models.py:ExplorationPhaseMemory` — vorhanden, `review_rounds: int` korrekt
- `src/agentkit/story_context_manager/models.py:PhaseState` — validiert, dass `verify` kein gueltiger Phasenname ist; Exploration als `PhaseName.EXPLORATION` enthalten
- `src/agentkit/story_context_manager/types.py:StoryMode` — `EXECUTION`, `EXPLORATION`, `NOT_APPLICABLE` korrekt definiert
- `src/agentkit/story_context_manager/types.py:StoryTypeProfile` — Profile fuer IMPLEMENTATION mit Exploration in `phases`-Tuple vorhanden
- `src/agentkit/story_context_manager/routing_rules.py:should_run_exploration` — Routing-Logik vorhanden, prueft `StoryMode.EXPLORATION`
- `src/agentkit/story_context_manager/routing_rules.py:get_phases_for_story` — entfernt Exploration-Phase bei Execution-Mode korrekt
- `src/agentkit/process/language/guards.py:exploration_gate_approved` — Guard vorhanden, prueft nur `phase=="exploration"` und `status==COMPLETED`
- `src/agentkit/process/language/guards.py:mode_is_exploration` — Guard vorhanden, prueft `execution_route == StoryMode.EXPLORATION`
- `src/agentkit/process/language/definitions.py:_build_implementation_workflow` — Exploration-Phase im Workflow-DAG mit Yield-Points fuer `design_review` und `design_challenge`; Transitionen setup→exploration und exploration→implementation mit Guards
- `src/agentkit/pipeline_engine/exploration_phase/__init__.py` — leere Namensraum-Datei; kein Implementierungscode
- `src/agentkit/pipeline/phases/exploration/__init__.py` — leere Namespace-Datei; Legacy-Paket als Stub
- `src/agentkit/prompt_composer/selectors.py:select_template_name` — gibt `worker-exploration` fuer `StoryMode.EXPLORATION` zurueck
- `src/agentkit/telemetry/events.py:EventType` — `DRIFT_CHECK`, `IMPACT_VIOLATION_CHECK`, `DOC_FIDELITY_CHECK` als Event-Typen vorhanden; `mandate_classification`, `fine_design_decision`, `scope_explosion_check` fehlen

## 4. GAP-Analyse

### 4.1 A — Nicht umgesetzt

| # | Thema | Konzept-Referenz | Anmerkung |
|---|---|---|---|
| A1 | `ExplorationPhaseHandler` (Top-Komponente `Exploration.run_phase`) | `FK-23 §23.3, bc-cut-decisions.md §BC5` | Kein Quellcode unter `src/agentkit/pipeline_engine/exploration_phase/` oder `src/agentkit/pipeline/phases/exploration/` — nur leere Namespace-Dateien |
| A2 | `ExplorationDrafting` — Story-Verdichtung, Referenzdokument-Recherche, Aenderungsflaechen-Lokalisierung, Loesungsrichtung, Selbst-Konformitaetspruefung, ChangeFrame-Erzeugung | `FK-23 §23.3.2, bc-cut-decisions.md §BC5` | Sub-Komponente vollstaendig fehlend; sieben Worker-Schritte nicht implementiert |
| A3 | `ExplorationReview` — dreistufiges Exit-Gate (Stufe 1 Dokumententreue via StructuredEvaluator, Stufe 2a Design-Review, Stufe 2b Design-Challenge) | `FK-23 §23.5, bc-cut-decisions.md §BC5` | Kein Orchestrator fuer den Review-Zyklus; Aufruf von `verify-system.LlmEvaluator` und `verify-system.ConformanceService` fehlt |
| A4 | `MandateClassification` — H1-Aggregation, H2-Nachklassifikation, Klasse-1/3/4-Eskalation, Feindesign-Subprozess (Klasse 2) | `FK-25 §25.3, §25.4, §25.5, bc-cut-decisions.md §BC5` | Vollstaendig fehlend; Scope-Explosion-Detektor und Impact-Exceedance-Check nicht vorhanden |
| A5 | `DesignFreezeMarker` — Freeze des Entwurfsartefakts nach Gate-PASS (`frozen: true`, Ablage in `_temp/qa/{story_id}/entwurfsartefakt.json`) | `FK-23 §23.4.3` | Kein Code; Freeze-Logik nicht implementiert |
| A6 | `ExplorationGateStatus`-StrEnum als typisiertes Feld in `ExplorationPayload` | `FK-23 §23.5.0` | Stattdessen `gate_status: str | None` in `models.py` — der normierte StrEnum-Typ existiert nicht |
| A7 | Telemetrie-Events `mandate_classification`, `fine_design_decision`, `scope_explosion_check`, `impact_exceedance_check` in `EventType` | `FK-25 §25.8` | `EventType` enthaelt diese vier BC-spezifischen Event-Typen nicht; nur `DRIFT_CHECK`, `IMPACT_VIOLATION_CHECK` und `DOC_FIDELITY_CHECK` vorhanden |
| A8 | Contract-Tests und Unit-Tests fuer Exploration-Phase-Handler, ModeRouter-Logik, MandateClassification und dreistufiges Exit-Gate | `guardrails/testing-guardrails.md §Negativpfade` | Keine Tests unter `tests/unit/`, `tests/integration/pipeline/exploration_mode/` oder `tests/contract/` fuer BC-Kernlogik — Verzeichnis `exploration_mode` existiert als leerer Stub |

### 4.2 B — Teilweise umgesetzt

| # | Thema | Code-Referenz | Konzept-Referenz | Was fehlt |
|---|---|---|---|---|
| B1 | `exploration_gate_approved`-Guard prueft nur `PhaseStatus.COMPLETED`, nicht `payload.gate_status == ExplorationGateStatus.APPROVED` | `src/agentkit/process/language/guards.py:exploration_gate_approved` | `FK-23 §23.5.0, FK-45 §45.2` | Guard liest den `ExplorationPayload`-State nicht aus; ein COMPLETED-Status ohne APPROVED-gate_status wuerde den Eintritt in Implementation erlauben — Defense-in-Depth verletzt |
| B2 | `ExplorationPayload` mit `gate_status: str | None` ohne Typbindung | `src/agentkit/story_context_manager/models.py:ExplorationPayload` | `FK-23 §23.5.0` | Fehlt: `ExplorationGateStatus`-StrEnum als Typ; fehlt: Validierung auf PENDING/APPROVED/REJECTED; freier String ermoeglicht ungueltige Werte und verhindert typsichere Gate-Pruefung |
| B3 | Workflow-DSL hat Yield-Points fuer `design_review` und `design_challenge`, aber keine vollstaendige Gate-Stufenmodellierung | `src/agentkit/process/language/definitions.py:_build_implementation_workflow` | `FK-23 §23.5, FK-25 §25.4.2` | Yield-Points sind im Workflow deklariert, aber Stufe-1 (Dokumententreue), Stufe-2a und Stufe-2b fehlen als typisierte Gate-Stufen-Objekte; H2-Routing-Logik (Klasse 1→3→4→2) nicht modelliert |
| B4 | Drift-Erkennung teilweise vorbereitet (`DRIFT_CHECK`-Event-Typ) | `src/agentkit/telemetry/events.py:EventType.DRIFT_CHECK` | `FK-23 §23.7.2` | Event-Typ deklariert, aber kein Code, der `drift_check`-Events bei Inkrementen erzeugt; Impact-Violation-Check (`IMPACT_VIOLATION_CHECK`) ist ebenfalls nur Event-Typ, kein Struktural-Check-Modul unter `verify-system` |

### 4.3 C — Drift / Fehler

| # | Thema | Code-Referenz | Konzept-Referenz | Drift / Fehler |
|---|---|---|---|---|
| C1 | Veraltetes `pipeline_engine/verify_phase`-Paket mit kompilierten Dateien (kein Quellcode) | `src/agentkit/pipeline_engine/verify_phase/` (nur `.pyc`) | `bc-cut-decisions.md §uebergreifende-entscheidungen` | Laut BC-Schnitt-Entscheidungen entfaellt die Top-Phase `verify`; es existieren aber noch kompilierte Artefakte (`cycle.cpython-314.pyc`, `phase.cpython-314.pyc`) ohne Quellcode — deutet auf unvollstaendig bereinigten Altzustand hin; kein Single Source of Truth |
| C2 | `VerifyContext`-Enum in `models.py` kennt nur `POST_IMPLEMENTATION` und `POST_REMEDIATION`, nicht `EXPLORATION_INITIAL` und `EXPLORATION_REMEDIATION` | `src/agentkit/story_context_manager/models.py:VerifyContext` | `bc-cut-decisions.md §QaContext-Werte` | Laut bc-cut-decisions sind vier `QaContext`-Werte normiert: `IMPLEMENTATION_INITIAL`, `IMPLEMENTATION_REMEDIATION`, `EXPLORATION_INITIAL`, `EXPLORATION_REMEDIATION`. Der Code hat nur zwei Werte und verwendet andere Namen (`POST_IMPLEMENTATION`, `POST_REMEDIATION`) — Namens- und Vollstaendigkeitsdrift |
| C3 | `StoryTypeProfile` fuer `BUGFIX` erlaubt nur `StoryMode.EXECUTION`, nicht `StoryMode.EXPLORATION`; aber FK-23 §23.1 nennt Bugfix als Exploration-faehigen Story-Typ | `src/agentkit/story_context_manager/types.py:PROFILES[StoryType.BUGFIX]` | `FK-23 §23.1` | FK-23 §23.1 sagt explizit: Geltungsbereich der Modus-Ermittlung sind `Implementation` und `Bugfix`. Der Bugfix-Profile erlaubt aber nur `EXECUTION` — FK-23-konforme Bugfix-Stories mit Exploration koennen nicht erzeugt werden |

## 5. Ableitungen / Empfehlungen

1. **`ExplorationGateStatus`-StrEnum einfuehren und `ExplorationPayload` haerten (Blocker):** Solange `gate_status: str | None` und kein typisierter Enum existieren, kann die Defense-in-Depth-Guard nicht korrekt implementiert werden und alle nachgelagerten Gate-Pruefungen bleiben fehlerhaft. Dies ist Vorbedingung fuer jede weitere Exploration-Implementierung.

2. **`exploration_gate_approved`-Guard um Payload-Pruefung erweitern:** Guard muss `payload.gate_status == ExplorationGateStatus.APPROVED` pruefen, nicht nur `status == COMPLETED`. Sicherheitsrelevant: verhindert, dass eine Phase, die aus sonstigen Gruenden COMPLETED ist, faelschlicherweise die Implementation freigibt.

3. **`VerifyContext`-Enum auf die vier normierten Werte ausrichten:** `POST_IMPLEMENTATION`/`POST_REMEDIATION` durch `IMPLEMENTATION_INITIAL`/`IMPLEMENTATION_REMEDIATION`/`EXPLORATION_INITIAL`/`EXPLORATION_REMEDIATION` ersetzen oder ersetzen und umbenennen; Contracts und Golden-Tests mitziehen.

4. **Bugfix-Profil auf Konzeptkonformitaet mit FK-23 §23.1 pruefen:** Klaeren, ob Bugfix-Stories Exploration-Mode unterstuetzen sollen und Profile entsprechend anpassen oder FK-23 §23.1 praezisieren.

5. **`ExplorationPhaseHandler` mit Sub-Komponenten als naechste Implementierungsphase angehen:** BC-Schnitt-Entscheidung ist fertig (bc-cut-decisions.md §BC5); Klassen-Skizzen und Schichten-Ordnung liegen vor. Reihenfolge: zuerst `ModeRouter` (Layer 0, isoliert), dann `ExplorationDrafting` (Layer 1), dann `MandateClassification` (Layer 2), dann `ExplorationReview` (Layer 3).

6. **Veraltete `pipeline_engine/verify_phase`-Artefakte aufraumen:** Nur `.pyc`-Dateien ohne Quellcode verstoessen gegen SINGLE SOURCE OF TRUTH. Verzeichnis bereinigen oder, falls noch benoetigt, Quellcode wiederherstellen und Entscheidung dokumentieren.

7. **Telemetrie-Events fuer BC-spezifische Mandate-Events nachziehen:** `mandate_classification`, `fine_design_decision`, `scope_explosion_check`, `impact_exceedance_check` in `EventType` aufnehmen — ohne diese sind Mandate-Entscheidungen nicht rueckverfolgbar.

8. **Integrationstests fuer exploration_mode-Verzeichnis befoellen:** `tests/integration/pipeline/exploration_mode/` ist ein leerer Stub. Negativpfade an Phasengrenzen (Gate REJECTED, Scope-Explosion, Klasse-1-Eskalation) sind Pflicht gemaess `guardrails/testing-guardrails.md`.

## 6. Suchstrategie & Quellen

- **Vollstaendig gelesen:**
  - `concept/technical-design/23_modusermittlung_exploration_change_frame.md`
  - `concept/technical-design/25_mandatsgrenzen_feindesign_autonomie.md`
  - `concept/formal-spec/exploration/entities.md`
  - `concept/formal-spec/exploration/state-machine.md`
  - `concept/formal-spec/exploration/commands.md`
  - `concept/formal-spec/exploration/events.md`
  - `concept/formal-spec/exploration/invariants.md`
  - `concept/formal-spec/exploration/scenarios.md`
  - `concept/technical-design/_meta/domain-registry.yaml`
  - `src/agentkit/story_context_manager/models.py`
  - `src/agentkit/story_context_manager/types.py`
  - `src/agentkit/story_context_manager/routing_rules.py`
  - `src/agentkit/process/language/guards.py`
  - `src/agentkit/process/language/definitions.py`
  - `src/agentkit/process/language/gates.py`
  - `src/agentkit/pipeline/lifecycle.py`
  - `src/agentkit/pipeline/phases/implementation/phase.py`
  - `src/agentkit/pipeline_engine/exploration_phase/__init__.py`
  - `src/agentkit/pipeline/phases/exploration/__init__.py`
  - `src/agentkit/prompt_composer/selectors.py`
  - `src/agentkit/telemetry/events.py`
  - `stories/_gap-analyse-schema.md`
  - `CLAUDE.md`
- **Punktuell via Grep (bc-cut-decisions.md, Datei zu gross fuer Vollread):**
  - Query `exploration`: BC-5-Schnitt-Entscheidung, QaContext-Werte, Klasseninventarliste gelesen
- **Code-Scan (Glob/Grep):**
  - Glob `src/agentkit/pipeline/phases/exploration/**`: prueft Vorhandensein von Quellcode
  - Glob `src/agentkit/pipeline_engine/**`: findet `exploration_phase/__init__.py` und unvermutetes `verify_phase/`-Paket
  - Grep `exploration|ExplorationPayload|ExplorationGateStatus` in `src/`: findet alle betroffenen Module
  - Grep `ExplorationGateStatus|design.freeze|drift.check` in `src/`: bestaetigt Fehlen von StrEnum und Handler-Code
  - Grep `EXPLORATION_INITIAL|EXPLORATION_REMEDIATION|QaContext` in `src/`: bestaetigt Drift in `VerifyContext`
  - Glob `tests/**/*explor*` und `tests/**/*.py`: bestaetigt leere Exploration-Testverzeichnisse
