# Review: AgentKit v3 Codebase -- R1

**Reviewer:** Claude Opus 4.6 (independent review)
**Date:** 2026-04-07
**Scope:** Full codebase review of AG3-001 Workflow-DSL delivery + pipeline engine + state persistence + installer
**Files reviewed:** 24 production files, 11 test files, 3 context documents

---

## Zusammenfassung

Die Codebase zeigt ein solides architektonisches Fundament mit konsequenter Trennung von Topologie (DSL) und Ausfuehrung (Engine). Die frozen dataclasses, der Builder-Pattern, das Guard-System und die atomic-write-Persistenz sind durchdacht implementiert. Der Code ist durchgaengig gut typisiert, dokumentiert und testbar.

Es gibt jedoch einige relevante Probleme -- zwei HIGH-Severity-Findings (Engine-Fehlerbehandlung mit hardcoded `story_id="unknown"`, fehlende Transition-Ordnungsgarantie bei verify->closure vs. verify->implementation) und mehrere MEDIUM-Findings (fehlende `__init__.py` globbing, Guard-Semantik-Schwaeche, unvollstaendige Test-Negativpfade). Keines der Findings ist ein Showstopper, aber die HIGH-Findings muessen vor einem Production-Deployment adressiert werden.

**Verdict: REWORK** (2 HIGH-Findings erfordern Korrektur)

---

## 1. Architektur-Kohaerenz

### Finding A-1: Saubere Schichtentrennung -- KEIN Finding [Severity: n/a]

Die Abhaengigkeitsrichtung ist korrekt: `pipeline` -> `story` -> (kein Rueckimport). Die `workflow/` Subpackage importiert nur aus `story.models` und `story.types` via `TYPE_CHECKING`. Keine zirkulaeren Dependencies gefunden.

### Finding A-2: Duplizierte atomic-write-Implementierung [Severity: MEDIUM]

**Dateien:**
- `src/agentkit/pipeline/state.py` Zeile 51-67 (`atomic_write_json`)
- `src/agentkit/project_ops/shared/file_ops.py` Zeile 18-41 (`atomic_write_text`) + Zeile 44-57 (`atomic_write_yaml`)

**Beschreibung:** Es existieren zwei unabhaengige atomic-write-Implementierungen. `state.py::atomic_write_json` hat KEIN Cleanup des Temp-Files bei Fehler (im Gegensatz zu `file_ops.py::atomic_write_text` das ein `try/except BaseException` mit `tmp.unlink()` hat). Dies ist ein konsistenz- und robustheitsproblem.

**Vorgeschlagener Fix:** Eine einzige `atomic_write_text`-Funktion in `project_ops/shared/file_ops.py` als kanonische Implementierung. `state.py::atomic_write_json` sollte diese nutzen oder zumindest das gleiche Fehler-Cleanup haben. Alternativ: gemeinsame Funktion in `utils/`.

### Finding A-3: `story/types.py` Profiles vs. Workflow Definitions Redundanz [Severity: LOW]

**Dateien:**
- `src/agentkit/story/types.py` Zeile 69-126 (`PROFILES` dict mit `phases`-Tuple)
- `src/agentkit/pipeline/workflow/definitions.py` (Workflow-Definitionen mit Phasen)

**Beschreibung:** Die Phase-Reihenfolge ist an zwei Stellen definiert: in `StoryTypeProfile.phases` und in den `WorkflowDefinition`-Instanzen. Dies erzeugt ein Risiko fuer Divergenz. Beispiel: `PROFILES[CONCEPT]` hat Phasen `("setup", "implementation", "verify", "closure")` und der `CONCEPT_WORKFLOW` definiert dieselben vier Phasen -- aber es gibt keinen automatischen Sync.

**Vorgeschlagener Fix:** Entweder die Profile aus den Workflow-Definitionen ableiten, oder einen Validierungstest hinzufuegen der sicherstellt, dass `profile.phases` und `workflow.phase_names` konsistent sind.

---

## 2. Workflow-DSL Design

### Finding W-1: Frozen Dataclasses korrekt implementiert [Severity: n/a]

Alle Datenmodelle in `model.py`, `guards.py`, `gates.py`, `recovery.py` sind `@dataclass(frozen=True)`. Die Tests in `test_model.py` verifizieren explizit die Frozen-Eigenschaft via `FrozenInstanceError`. Korrekt.

### Finding W-2: Builder laesst Duplikat-Phasennamen zu [Severity: MEDIUM]

**Datei:** `src/agentkit/pipeline/workflow/builder.py` Zeile 59-75

**Beschreibung:** `WorkflowBuilder.phase()` prueft nicht ob eine Phase mit demselben Namen bereits existiert. Man kann `.phase("setup").phase("setup")` aufrufen und erhaelt ein Workflow mit zwei PhaseDefinitions namens "setup". `WorkflowDefinition.get_phase()` wuerde dann immer die erste finden. Die `build()`-Validierung prueft nur ob Transition-Referenzen gueltig sind, nicht ob Phasennamen einzigartig sind.

**Vorgeschlagener Fix:** In `WorkflowBuilder.phase()` eine Duplikat-Pruefung einfuegen:
```python
if any(p.name == name for p in self._phases):
    raise WorkflowError(f"Phase '{name}' already defined.")
```

### Finding W-3: `yield_to` `target`-Parameter wird nicht verwendet [Severity: LOW]

**Datei:** `src/agentkit/pipeline/workflow/builder.py` Zeile 111-147

**Beschreibung:** Der `target`-Parameter von `yield_to()` (z.B. `"design_review"`) wird in kein YieldPoint-Feld uebertragen. Er ist nur "informational" laut Docstring, landet aber nirgendwo im erzeugten Datenmodell. Das ist verwirrend fuer Leser.

**Vorgeschlagener Fix:** Entweder den Parameter entfernen und durch einen Kommentar ersetzen, oder ein `name`-Feld in `YieldPoint` hinzufuegen und den Wert dort speichern.

### Finding W-4: `Workflow` Funktion als PascalCase -- unkonventionell [Severity: LOW]

**Datei:** `src/agentkit/pipeline/workflow/builder.py` Zeile 376-388

**Beschreibung:** `def Workflow(name: str) -> WorkflowBuilder` ist eine Funktion mit PascalCase-Name, was gegen Python-Konventionen verstosst. Der `# noqa: N802` Kommentar bestaetigt das. Dies ist eine bewusste Design-Entscheidung fuer eine fluent API (`Workflow("name").phase(...)`) und akzeptabel, aber erwaehnungsswert.

---

## 3. Pipeline Engine

### Finding E-1: `_handle_handler_exception` verwendet hardcoded `story_id="unknown"` [Severity: HIGH]

**Datei:** `src/agentkit/pipeline/engine.py` Zeile 583-585

**Beschreibung:** Wenn ein Handler eine Exception wirft, erzeugt `_handle_handler_exception` einen `PhaseState` mit `story_id="unknown"`:
```python
failed_state = PhaseState(
    story_id="unknown",
    phase=phase_name,
    ...
)
```
Die Methode hat Zugriff auf `self` und koennte den `story_id` aus dem uebergebenen `state`-Objekt entnehmen, das in `run_phase`/`resume_phase` vorhanden ist -- aber der `state`-Parameter wird nicht an `_handle_handler_exception` durchgereicht.

Das bedeutet: bei einem Handler-Crash wird ein falscher `story_id` in `phase-state.json` persistiert. Wenn die Pipeline danach per `load_phase_state` geladen wird, hat der geladene State einen anderen `story_id` als der tatsaechliche Story-Kontext.

**Vorgeschlagener Fix:** `_handle_handler_exception` um einen `story_id: str`-Parameter erweitern und in den Aufrufern `state.story_id` uebergeben.

### Finding E-2: Transition-Reihenfolge Closure vs. Remediation -- funktioniert, aber fragil [Severity: HIGH]

**Datei:** `src/agentkit/pipeline/workflow/definitions.py` Zeile 97-98

**Beschreibung:** Im Implementation-Workflow:
```python
.transition("verify", "closure", guard=verify_completed)
.transition("verify", "implementation", resume_policy="remediation")
```
Die Engine (`evaluate_transitions`, Zeile 298-305) iteriert in Definitionsreihenfolge und nimmt die erste Transition deren Guard passt. Die `verify->closure`-Transition hat einen Guard (`verify_completed`), die `verify->implementation`-Transition hat KEINEN Guard (= immer gueltig).

**Korrektheit:** Das funktioniert: Wenn verify COMPLETED ist, passt der Guard der ersten Transition, und closure wird genommen. Wenn verify NICHT completed ist, failt der Guard, und die zweite (guardlose) Transition greift -- remediation.

**Problem:** Diese Korrektheit haengt von der Definitionsreihenfolge ab. Wenn jemand die Reihenfolge der zwei `.transition()`-Aufrufe umkehrt, wuerde die guardlose `verify->implementation` immer zuerst greifen und closure waere nie erreichbar. Es gibt keinen Test oder Guard der das verhindert.

**Vorgeschlagener Fix:** EINE der folgenden Massnahmen:
1. Einen expliziten Guard auf `verify->implementation` (z.B. `verify_not_completed`) statt es guardlos zu lassen. Dann ist die Reihenfolge irrelevant.
2. Einen Kommentar-Block der erklaert warum die Reihenfolge kritisch ist UND einen Test der das verifiziert.
3. (Empfohlen) Option 1 -- ein expliziter Guard eliminiert die Order-Dependency.

### Finding E-3: Guard-Evaluation auf Phase-Entry vs. Transition-Guards [Severity: LOW]

**Datei:** `src/agentkit/pipeline/engine.py` Zeile 370-406 (`_evaluate_guards`)

**Beschreibung:** `_evaluate_guards` evaluiert die Guards einer Phase (`phase.guards`), aber deren Ergebnis wird nur in den Audit-Trail geschrieben -- es beeinflusst NICHT die Ausfuehrungsentscheidung. Die tatsaechliche Eintrittsblockade erfolgt ueber `preconditions`. Phase-Guards sind aktuell rein informativ im Audit-Trail.

Dies koennte Verwirrung stiften: `PhaseDefinition.guards` existiert und wird evaluiert, aber hat keine blockierende Wirkung. Der Name "guards" suggeriert Blockade-Semantik.

**Vorgeschlagener Fix:** Entweder:
- Phase-Guards blockierend machen (dann waere die Semantik konsistent mit Transition-Guards), oder
- Den Docstring/Naming klaeren dass Phase-Guards nur Audit-Zwecken dienen (z.B. `audit_guards` statt `guards`).

---

## 4. State-Persistenz

### Finding S-1: Atomic writes -- Crash-Sicherheit [Severity: n/a]

`atomic_write_json` in `state.py` verwendet `os.fsync()` und `os.replace()`. Das ist korrekt fuer POSIX-Systeme und garantiert Atomizitaet auf dem meisten Dateisystemen. Unter Windows ist `os.replace` auf NTFS atomar. Solide.

### Finding S-2: AttemptRecord Serialisierung/Deserialisierung ist manuell [Severity: MEDIUM]

**Datei:** `src/agentkit/pipeline/state.py` Zeile 154-243

**Beschreibung:** `AttemptRecord` ist ein `@dataclass(frozen=True)` (kein Pydantic-Modell). Die Serialisierung in `save_attempt` (Zeile 169-180) und Deserialisierung in `load_attempts` (Zeile 204-240) ist manuell geschrieben. Das ist fehleranfaellig und inkonsistent mit dem Rest der Codebase, die Pydantic `model_dump()`/`model_validate()` nutzt.

Konkretes Problem: Die Deserialisierung in `load_attempts` nutzt `cast()` mit Stringliteralen (Zeile 215-219, 222-226) und hat umfangreiche `data.get()` Fallbacks. Wenn sich die Felder von `AttemptRecord` aendern, muss die manuelle Serialisierung/Deserialisierung manuell nachgezogen werden -- kein Pydantic-Schema schuetzt hier.

**Vorgeschlagener Fix:** `AttemptRecord` zu einem Pydantic-Modell migrieren und `model_dump(mode="json")`/`model_validate()` nutzen, analog zu `PhaseState`, `StoryContext`, `PhaseSnapshot`.

### Finding S-3: Attempt-ID Generierung hat Race Condition Potenzial [Severity: LOW]

**Datei:** `src/agentkit/pipeline/engine.py` Zeile 355-368

**Beschreibung:** `_generate_attempt_id` zaehlt existierende Attempt-Dateien und inkrementiert. `save_attempt` zaehlt ebenfalls existierende Dateien und inkrementiert (Zeile 166-168 in `state.py`). Das sind zwei unabhaengige Zaehlungen die auseinanderlaufen koennten -- allerdings nur bei konkurrierendem Zugriff, der im Single-Pipeline-Betrieb nicht vorkommt.

**Status:** Akzeptabel fuer den aktuellen Single-Pipeline-Use-Case. Fuer zukuenftigen Multi-Agent-Betrieb sollte ein atomarer Zaehler oder Lock-Mechanismus eingefuehrt werden.

---

## 5. Test-Qualitaet

### Finding T-1: Transition-Graph Tests sind vorbildlich [Severity: n/a]

`test_transitions.py` testet fuer JEDEN der 4 Workflow-Typen sowohl gueltige als auch ungueltige Transitionen parametrisiert. Die Tests pruefen auch spezifische Eigenschaften (Guards, Resume-Policies). Dies entspricht exakt dem Testing-Standard 1.4 (Uebergangsgraph vollstaendig verprobt). Ausgezeichnet.

### Finding T-2: Fehlende Negativpfad-Tests fuer `resolve_workflow` [Severity: MEDIUM]

**Datei:** `tests/unit/pipeline/workflow/test_definitions.py`

**Beschreibung:** `resolve_workflow()` mit einem ungueltigen `StoryType` wird nicht getestet. Die Funktion wirft `WorkflowError` -- das sollte in einem Negativtest verifiziert werden. Da `StoryType` ein `StrEnum` ist, ist ein ungueltiger Wert in der Praxis schwer zu konstruieren (man muesste casten), aber der Test dokumentiert das erwartete Verhalten.

**Vorgeschlagener Fix:** Test hinzufuegen der `WorkflowError` bei ungueltigem Input verifiziert (oder explizit dokumentieren warum das nicht noetig ist).

### Finding T-3: Kein Test fuer `WorkflowValidator.validate()` mit leeren Transitions [Severity: LOW]

**Datei:** `tests/unit/pipeline/workflow/test_validators.py`

**Beschreibung:** Der Test `test_empty_workflow_produces_error` testet ein Workflow ohne Phasen. Aber es gibt keinen expliziten Test fuer ein Workflow mit Phasen aber ohne Transitions (ausser dem Single-Phase-Fall). Ein 3-Phasen-Workflow ohne jede Transition wuerde mehrere Fehler produzieren.

### Finding T-4: Fehlende Tests fuer Recovery/Rehydration [Severity: MEDIUM]

**Beschreibung:** Die Story (Zeile 67 von story.md) listet `tests/unit/pipeline/workflow/test_recovery.py` als erwartete Datei. Diese Datei existiert NICHT im Repository. Die `RecoveryContract` und `RehydrationRule` Klassen in `recovery.py` haben keine Unit-Tests.

`DEFAULT_RECOVERY_CONTRACT` wird nirgendwo im Produktionscode verwendet -- er ist definiert aber nie aufgerufen. Die Recovery-Logik existiert als Datenstruktur, aber ihre Anwendung (das tatsaechliche Rehydrieren) ist nicht implementiert.

**Vorgeschlagener Fix:** Entweder `test_recovery.py` implementieren (mindestens Tests fuer `RecoveryContract.get_rule()`, `required_fields`, und den Default-Contract), oder explizit dokumentieren dass Recovery als out-of-scope fuer diese Story betrachtet wird.

### Finding T-5: Precondition-Tests nutzen nicht den echten Pipeline-Flow [Severity: MEDIUM]

**Datei:** `tests/unit/pipeline/test_engine.py` Zeile 371-454

**Beschreibung:** Die Precondition-Tests (`test_precondition_satisfied_allows_entry`, `test_precondition_violated_blocks`) bauen State manuell auf (PhaseState direkt konstruiert). Das Testing-Standard-Dokument (Abschnitt 1.2) fordert explizit:

> "Tests duerfen den Eingabezustand eines Pipeline-Schritts nicht manuell zusammenbauen [...] State muss durch den tatsaechlichen Aufruf des vorgelagerten Schritts entstehen."

Die Engine-Unit-Tests verwenden jedoch durchgaengig manuell konstruierte PhaseState-Objekte. Dies ist fuer Unit-Tests akzeptabel (sie testen Engine-Logik isoliert), sollte aber durch Integration-Tests ergaenzt werden die den echten Flow nutzen.

Die E2E-Smoke-Tests (`test_smoke_pipeline.py`) kompensieren dies teilweise, indem sie den echten Pipeline-Flow testen. Dennoch fehlen spezifische Integrationstests die Precondition-Verletzungen durch defekte vorgelagerte Schritte erzeugen (z.B. Exploration-Precondition bei echtem Pipeline-Durchlauf im EXPLORATION-Modus).

---

## 6. E2E-Tests

### Finding E2E-1: Smoke-Tests verwenden echten Pipeline-Flow [Severity: n/a]

Die E2E-Smoke-Tests in `test_smoke_pipeline.py` folgen dem korrekten Pattern:
1. `install_agentkit` ins Temp-Verzeichnis
2. `save_story_context` fuer Story-Setup
3. `run_pipeline` mit echten Workflow-Definitionen
4. Assertions auf Result und persistierte Artefakte

Das ist vorbildlich und entspricht dem Testing-Standard 2.4.

### Finding E2E-2: Fehlender EXPLORATION-Mode E2E-Test [Severity: MEDIUM]

**Datei:** `tests/e2e/smoke/test_smoke_pipeline.py`

**Beschreibung:** Alle Implementation-Story-Tests verwenden `StoryMode.EXECUTION`. Es gibt KEINEN E2E-Test der den `StoryMode.EXPLORATION`-Pfad durch den Implementation-Workflow testet. Dieser Pfad ist der komplexeste (setup -> exploration -> implementation -> verify -> closure mit Preconditions und mode-abhaengigen Guards).

Der EXPLORATION-Pfad wird in Unit-Tests (guard-Tests fuer `mode_is_exploration`) und Transition-Tests (Definition-Tests) abgedeckt, aber nie End-to-End durchlaufen.

**Vorgeschlagener Fix:** E2E-Test hinzufuegen:
```python
def test_exploration_mode_runs_all_five_phases(self, tmp_path):
    ctx, s_dir = _setup_story(
        project_dir, "TEST-EXPL",
        StoryType.IMPLEMENTATION, StoryMode.EXPLORATION,
    )
    result = run_pipeline(ctx, s_dir, registry, workflow)
    assert result.phases_executed == (
        "setup", "exploration", "implementation", "verify", "closure",
    )
```

### Finding E2E-3: NoOpHandler verbirgt reale Phase-Logik [Severity: LOW]

**Beschreibung:** Alle E2E-Tests verwenden `NoOpHandler` fuer alle Phasen. Das ist korrekt fuer den aktuellen Scope (Workflow-DSL testen, nicht Phase-Handler), aber es bedeutet dass die E2E-Tests nicht die reale Phase-Ausfuehrung testen. Das ist akzeptabel und explizit out-of-scope fuer AG3-001, sollte aber bewusst sein.

---

## 7. Code-Qualitaet

### Finding Q-1: Type-Hints durchgaengig vorhanden [Severity: n/a]

Alle Funktionssignaturen sind vollstaendig typisiert. `from __future__ import annotations` ist in jedem Modul vorhanden. `TYPE_CHECKING` Guards werden korrekt eingesetzt um zirkulaere Imports zu vermeiden. `mypy --strict` Kompatibilitaet ist offensichtlich ein Design-Ziel.

### Finding Q-2: Google-Style Docstrings konsistent [Severity: n/a]

Alle public Funktionen und Klassen haben Google-Style Docstrings mit Args, Returns, Raises. Die Qualitaet ist durchgaengig hoch.

### Finding Q-3: Exception-Hierarchie sauber [Severity: n/a]

`exceptions.py` definiert eine klare Hierarchie: `AgentKitError` -> `WorkflowError` -> `TransitionError`/`GuardError`/`GateError`. Jede Exception hat ein optionales `detail`-Dict fuer strukturierte Fehlerinfos. Das ist gutes Design.

### Finding Q-4: `PipelineConfig.verify_layers` Default als mutable List [Severity: MEDIUM]

**Datei:** `src/agentkit/config/models.py` Zeile 42

**Beschreibung:**
```python
verify_layers: list[str] = list(DEFAULT_VERIFY_LAYERS)
```
Pydantic v2 mit `strict=True` handhabt das korrekt (jede Instanz bekommt eine eigene Liste). Aber `DEFAULT_VERIFY_LAYERS` in `defaults.py` ist selbst ein mutable `list[str]` (Zeile 29). Obwohl der `list()` Aufruf eine Kopie macht, koennte ein Caller `DEFAULT_VERIFY_LAYERS` direkt mutieren und damit den Default aendern.

Analog gilt das fuer `DEFAULT_STORY_TYPES` (Zeile 15).

**Vorgeschlagener Fix:** `DEFAULT_VERIFY_LAYERS` und `DEFAULT_STORY_TYPES` als `tuple[str, ...]` definieren (statt `list[str]`), um versehentliche Mutation zu verhindern.

### Finding Q-5: `if False:` statt `TYPE_CHECKING` in conftest.py [Severity: LOW]

**Datei:** `tests/unit/pipeline/workflow/conftest.py` Zeile 19

**Beschreibung:**
```python
if False:  # TYPE_CHECKING -- avoid import for type checkers only
    pass
```
Das ist ein Workaround der nichts tut -- der Block ist leer und der Kommentar erklaert nichts. Standard waere `from typing import TYPE_CHECKING` und `if TYPE_CHECKING:`. Der aktuelle Code funktioniert, ist aber unkonventionell.

### Finding Q-6: `simple_workflow` Fixture hat `object` Return-Type [Severity: LOW]

**Datei:** `tests/unit/pipeline/test_engine.py` Zeile 174

**Beschreibung:**
```python
@pytest.fixture()
def simple_workflow() -> object:
```
Die Fixture gibt ein `WorkflowDefinition` zurueck, der Return-Type ist aber `object`. Das fuehrt zu `type: ignore[arg-type]` Kommentaren bei der Verwendung (Zeile 210, 228, etc.). Der korrekte Type waere `WorkflowDefinition`.

### Finding Q-7: `psutil` als Dependency ohne Nutzung [Severity: LOW]

**Datei:** `pyproject.toml` Zeile 18

**Beschreibung:** `psutil>=5.9` ist als Dependency aufgefuehrt, wird aber in keinem der reviewten Produktions-Dateien importiert oder verwendet. Es koennte in nicht-reviewten Modulen genutzt werden (z.B. in Pipeline-Phases, Telemetrie), sollte aber verifiziert werden.

---

## Severity-Zusammenfassung

| Severity | Count | Findings |
|----------|-------|----------|
| HIGH | 2 | E-1 (story_id="unknown"), E-2 (Transition-Ordnungsabhaengigkeit) |
| MEDIUM | 7 | A-2, W-2, S-2, T-2, T-4, T-5/E2E-2, Q-4 |
| LOW | 7 | A-3, W-3, W-4, S-3, T-3, Q-5, Q-6, Q-7 |

---

## Akzeptanzkriterien-Abgleich

| AK# | Beschreibung | Status | Kommentar |
|-----|-------------|--------|-----------|
| 1 | WorkflowDefinition frozen, alle Felder | PASS | |
| 2 | PhaseDefinition alle Felder | PASS | |
| 3 | TransitionRule mit duplizierten (source,target) | PASS | Getestet in test_model.py |
| 4 | YieldPoint alle Felder | PASS | |
| 5 | HookPoints alle Felder | PASS | |
| 6 | GuardResult PASS/FAIL Konstruktion | PASS | |
| 7 | Guard Signatur + seiteneffektfrei | PASS | Seiteneffektfreiheit getestet |
| 8 | @guard Dekorator | PASS | |
| 9 | 4 Guards implementiert | PASS | preflight, exploration_gate, verify, mode_is_exploration |
| 10 | Gate Struktur | PASS | |
| 11 | GateStage Struktur | PASS | |
| 12 | Gate = Vertrag, kein Executor | PASS | |
| 13 | Builder Fluent API | PASS | |
| 14 | build() immutabel, mehrfach unabhaengig | PASS | Getestet |
| 15 | build() validiert Transition-Referenzen | PASS | Aber keine Duplikat-Pruefung (W-2) |
| 16 | Builder unterstuetzt alle Methoden | PASS | |
| 17 | 4 Workflow-Definitionen | PASS | |
| 18 | resolve_workflow() | PASS | Kein Negativ-Test (T-2) |
| 19 | Implementation-Workflow Struktur | PASS | |
| 20 | Bugfix ohne Exploration | PASS | |
| 21 | WorkflowValidator.validate() | PASS | |
| 22 | Validierungschecks (a)-(d) | PASS | |
| 23 | Unerreichbare Phasen = Error | PASS | |
| 24 | Gueltige Transitions getestet | PASS | test_transitions.py |
| 25 | Ungueltige Transitions getestet | PASS | test_transitions.py |
| 26 | Precondition-Verletzung getestet | PASS | test_engine.py (manueller State, nicht Pipeline-Flow) |
| 27 | RecoveryContract Struktur | PASS | Definiert, aber keine Tests (T-4) |
| 28 | Fehlende Quelle = harter Fehler | PARTIAL | Contract definiert, Enforcement nicht implementiert |
| 29 | ruff + mypy clean | NOT VERIFIED | Nicht im Review-Scope ausgefuehrt |
| 30 | future annotations | PASS | In jedem Modul |
| 31 | Google-style Docstrings | PASS | |

---

## Verdict

**REWORK**

Begruendung: Zwei HIGH-Severity-Findings erfordern Korrektur vor Abnahme:

1. **E-1**: `story_id="unknown"` in Exception-Handler ist ein Data-Integrity-Bug. Einfacher Fix (~5 Zeilen Aenderung).
2. **E-2**: Die Korrektheit der verify->closure vs. verify->implementation Transition haengt von der Definitionsreihenfolge ab. Ein expliziter Guard auf der Remediation-Transition wuerde die Order-Dependency eliminieren.

Empfohlene weitere Korrekturen (MEDIUM):
- W-2: Duplikat-Phasennamen im Builder verhindern.
- T-4: `test_recovery.py` implementieren.
- E2E-2: EXPLORATION-Mode E2E-Test hinzufuegen.
- Q-4: Mutable default-Listen in `defaults.py` zu Tuples aendern.
