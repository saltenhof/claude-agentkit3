# AG3-024: PhaseEnvelope + RuntimeMetadata + PauseReason-Typisierung

**Typ:** Implementation
**Groesse:** M
**Abhaengigkeiten:** AG3-021 (`PauseReason`-StrEnum)
**Quell-Konzepte (autoritativ, mit `rel_path` ab Repo-Root):**
- `FK-39 §39.1/39.3` — `concept/technical-design/39_phase_state_persistenz.md` (PhaseEnvelope, RuntimeMetadata, Persistenzgrenze, Z. 110-200)
- `FK-39 §39.2.2` — `concept/technical-design/39_phase_state_persistenz.md` (PauseReason-StrEnum, drei Werte, Glossar Z. 62-69)
- `FK-39 §39.4.1` — `concept/technical-design/39_phase_state_persistenz.md` (PhaseState-Persistenz / AttemptRecord-Struktur, Z. 376-389)
- `concept/_meta/bc-cut-decisions.md §BC 1 Layer 1` — pipeline-framework PhaseEnvelopeStore-Sub
- `AG3-021 §2.1.4` — `stories/AG3-021-kern-enums/story.md` — `PauseReason.from_yield_status`-Mapping (Helper, von dem diese Story konsumiert)
- `AG3-025` — `stories/AG3-025-attempt-record-write-ordering/story.md` — Abgrenzung der `AttemptOutcome.YIELDED`-Markierung am AttemptRecord (siehe Yield-Klarstellung 2.1.5.1 unten)

---

## 1. Kontext

THEME-004 aus `stories/_priorisierungsempfehlung.md`, Teil 1. Befunde:

- `pipeline-framework.C1`: `PhaseEnvelope` und `RuntimeMetadata` fehlen — Engine arbeitet direkt mit `PhaseState`; keine Persistenzgrenze zwischen durable `PhaseState` und ephemerer `RuntimeMetadata`.
- `pipeline-framework.C2`: `PauseReason` als freier String. (`AG3-021` hat den Enum bereitgestellt — diese Story zieht ihn in die Engine.)
- `pipeline-framework.A2`: `PhaseEnvelopeStore` als Sub fehlt — Phase-State-Persistenz laeuft ueber `agentkit.state_backend.store` ohne BC-eigenen Store.

Die Trennung `PhaseState` (durable) vs. `RuntimeMetadata` (ephemer) ist Voraussetzung fuer Crash-Recovery-Korrektheit (THEME-009: QA-Zyklus-Persistenz baut auf PhaseEnvelope auf).

## 2. Scope

### 2.1 In Scope

#### 2.1.1 `PhaseEnvelope`-Modell (FK-39 §39.1/39.3)

Neues Modul `src/agentkit/pipeline_engine/phase_envelope/envelope.py`:

```python
class PhaseEnvelope(BaseModel):
    state: PhaseState              # durable, wird persistiert
    runtime: RuntimeMetadata       # ephemer, wird NICHT persistiert
    model_config = ConfigDict(frozen=True, extra="forbid")
```

#### 2.1.2 `RuntimeMetadata`-Modell

`src/agentkit/pipeline_engine/phase_envelope/runtime.py`:

```python
class PhaseOrigin(StrEnum):
    NEW = "new"           # Erstaufruf, neu erstellt
    LOADED = "loaded"     # aus Persistenz geladen

class RuntimeMetadata(BaseModel):
    origin: PhaseOrigin
    loaded_at: datetime | None       # Zeitpunkt des Loads (None bei NEW)
    process_id: int                  # OS-Prozess-ID
    worker_id: str | None            # Worker-Identifikation (None falls Engine ohne Worker)
    model_config = ConfigDict(frozen=True, extra="forbid")
```

Begruendung: das Konzept (FK-39 §39.3) nennt `origin` als Pflichtfeld; `loaded_at`/`process_id`/`worker_id` sind die natuerlichen Begleitfelder fuer Debugging und Telemetrie.

#### 2.1.3 `PhaseEnvelopeStore` (bc-cut-decisions.md §BC 1 Layer 1)

Neues Sub `src/agentkit/pipeline_engine/phase_envelope/store.py`:

```python
class PhaseEnvelopeStore:
    def __init__(self, repository: PhaseEnvelopeRepository) -> None: ...
    def load(self, story_id: str, phase: PhaseName) -> PhaseEnvelope | None:
        # state aus Repository laden; RuntimeMetadata mit origin=LOADED rekonstruieren
        ...
    def save(self, envelope: PhaseEnvelope) -> None:
        # nur state persistieren, runtime wird verworfen
        ...
    def exists(self, story_id: str, phase: PhaseName) -> bool: ...
```

`PhaseEnvelopeRepository` ist Protocol (analog AG3-023 Artifact-Repository). Konkrete Implementierungen verbinden sich mit `state_backend/store/phase_state_repository.py` (existing; ggf. minor refactor noetig, aber kein neues Tabellen-Schema).

`load()` liefert `PhaseEnvelope` mit:
- `state`: aus Storage geladen
- `runtime`: NEU erzeugt mit `origin=PhaseOrigin.LOADED`, `loaded_at=now()`, aktuelle process_id/worker_id

`save()` schreibt nur `envelope.state` ins Repository — Runtime-Metadata bleibt prozesslokal.

#### 2.1.4 Engine-Migration auf PhaseEnvelope (FK-39 §39.1)

`src/agentkit/pipeline/engine.py:PipelineEngine`:

- `run_phase` arbeitet ab jetzt mit `PhaseEnvelope` statt `PhaseState`. State-Initialisierung in Engine: `envelope = PhaseEnvelope(state=fresh_state, runtime=RuntimeMetadata(origin=NEW, ...))`.
- `load_phase_state(...)` wandert zu `PhaseEnvelopeStore.load(...)`. Engine-Aufrufe werden umgestellt.
- Handler-Signaturen: Handler nehmen `PhaseEnvelope` entgegen statt `PhaseState`; im einfachsten Fall lesen sie `envelope.state` weiter. Default-Implementierungen werden migriert.

`src/agentkit/pipeline/runner.py:run_pipeline`:
- iteriert ueber Phasen mit PhaseEnvelope; bei resume laed der Store den Envelope mit `origin=LOADED`.

#### 2.1.5 `paused_reason` typisieren (pipeline-framework.C2)

`src/agentkit/pipeline/engine.py:_handle_paused_result` und die zugrunde liegende Yield-Result-Datenstruktur:

- `paused_reason: PauseReason` (aus `agentkit.core_types`) statt `str`.
- Wenn der Handler einen `yield_status`-String liefert, der nicht zu einem `PauseReason` mappt: fail-closed mit `InvalidPauseReasonError` (neue Exception in `pipeline_engine/errors.py`).
- Hilfsfunktion `PauseReason.from_yield_status(s: str) -> PauseReason` (in `agentkit.core_types.pause_reason`) wurde in AG3-021 bereits angelegt; hier wird sie konsumiert.

##### 2.1.5.1 Yield-Klarstellung (Codex-Befund §"Konzept-Spannungen" Pkt. 3)

Yield-Information ueber zwei Datenstrukturen — verbindliche Trennung:

- **`paused_reason: PauseReason`** lebt in der `PhaseEnvelope.state` (durable, persistiert via `PhaseEnvelopeStore.save`) — dies ist der **fachliche Pause-Grund** (z.B. `AWAITING_DESIGN_REVIEW`). Konzept-Soll: `PhaseStateCore.pause_reason` (FK-39 §39.2.2 Glossary `pause-reason`). AG3-024 ist der Owner dieses Feldes und seiner Typisierung.
- **`AttemptOutcome.YIELDED`** ist eine reine **Outcome-Markierung** am `AttemptRecord` (AG3-025 §2.1.1). Sie zeigt "dieser Phase-Versuch endete mit YIELD" — ohne den fachlichen Grund zu redundant zu fuehren.

Doppelpflege ist verboten. Es gibt **eine** Quelle fuer den Pause-Grund (`PhaseEnvelope.state.paused_reason`); der `AttemptRecord` markiert nur das Outcome.

Wo liest welcher Konsument:
- Recovery-Logik (FK-39 §39.4.4) liest `paused_reason` aus dem persistierten PhaseState.
- AttemptRecord-History liefert ueber `outcome=YIELDED` einen Marker, ohne den Grund zu duplizieren — bei Detail-Bedarf wird die PhaseState-Projektion fuer denselben `(run_id, phase, attempt)` gelesen.

#### 2.1.6 Tests

- Unit-Tests fuer `PhaseEnvelope`-Modell (frozen, extra forbid)
- Unit-Tests fuer `RuntimeMetadata` und `PhaseOrigin`
- Unit-Tests fuer `PhaseEnvelopeStore` (load mit origin=LOADED, save persistiert nur state, exists)
- Engine-Migration-Tests:
  - `run_phase` mit frischem Envelope (origin=NEW) — happy path
  - `run_phase` mit geladenem Envelope (origin=LOADED) — Resume-Pfad
  - `_handle_paused_result` mit unbekanntem Yield-Status faellt fail-closed
- Existing Engine/Runner-Tests werden migriert (Signaturen aendern sich von `PhaseState` auf `PhaseEnvelope`)

### 2.2 Out of Scope

- `AttemptRecord`-Schema-Migration und Write-Ordering-Bug — separate Story AG3-025
- `PipelineRegistry` (`pipeline-framework.A3`) — separate kleine Folge-Story (nicht in dieser Welle adressiert)
- `StoryResetService` (`pipeline-framework.A4`) — bewusst nicht in der Erst-Welle (siehe Priorisierungsempfehlung §5)
- `CompactionResilience` (`pipeline-framework.A1`) — bewusst nicht in der Erst-Welle
- Prefix-Migration `agentkit.pipeline` -> `agentkit.pipeline_engine` (`pipeline-framework.B1`) — gehoert zu THEME-001 (bereits erledigt) bzw. zu separater Cleanup-Story; nicht hier
- Phase-Transition-Enforcement nach FK-45-Semantik (`pipeline-framework.B3`) — gehoert zu THEME-006 (AG3-032)
- Orchestrator-Trennung des Remediation-Loops (`pipeline-framework.C3`) — gehoert zu THEME-009 (AG3-044)
- Recovery-CLI `agentkit run-phase`/`resume`/... (`pipeline-framework.B5`) — separate CLI-Story (nicht in der Erst-Welle)

## 3. Betroffene Dateien

| Datei | Aenderungsart | Beschreibung |
|---|---|---|
| `src/agentkit/pipeline_engine/phase_envelope/__init__.py` | Neu | Re-Export |
| `src/agentkit/pipeline_engine/phase_envelope/envelope.py` | Neu | `PhaseEnvelope` Pydantic-v2-Modell |
| `src/agentkit/pipeline_engine/phase_envelope/runtime.py` | Neu | `RuntimeMetadata`, `PhaseOrigin` |
| `src/agentkit/pipeline_engine/phase_envelope/store.py` | Neu | `PhaseEnvelopeStore` Sub |
| `src/agentkit/pipeline_engine/phase_envelope/repository.py` | Neu | `PhaseEnvelopeRepository` Protocol |
| `src/agentkit/pipeline_engine/errors.py` | Neu/Modifiziert | `InvalidPauseReasonError` |
| `src/agentkit/state_backend/store/phase_envelope_repository.py` | Neu | Konkrete Repository-Implementierung (faktoriert ggf. aus existing `phase_state_repository.py`) |
| `src/agentkit/pipeline/engine.py` | Modifiziert | `run_phase` arbeitet mit `PhaseEnvelope`; `_handle_paused_result` typisiert `paused_reason` |
| `src/agentkit/pipeline/runner.py` | Modifiziert | `run_pipeline` ueber `PhaseEnvelopeStore.load/save` |
| `src/agentkit/pipeline/phases/setup/phase.py` | Modifiziert | Handler-Signatur akzeptiert `PhaseEnvelope` |
| `src/agentkit/pipeline/phases/implementation/phase.py` | Modifiziert | analog |
| `src/agentkit/pipeline/phases/closure/phase.py` | Modifiziert | analog |
| `src/agentkit/phase_state_store/store.py` | Modifiziert | Falls dieser Compat-Re-Export weiter benoetigt wird, dann re-exportiert er nun den `PhaseEnvelopeStore`; alternativ Entfernung dieses Pakets (Drift `pipeline-framework.C5`) — Entscheidung: Re-Export auf neues Sub umstellen, Modul nicht entfernen |
| `tests/unit/pipeline_engine/phase_envelope/test_envelope.py` | Neu | PhaseEnvelope-Tests |
| `tests/unit/pipeline_engine/phase_envelope/test_runtime.py` | Neu | RuntimeMetadata-Tests |
| `tests/unit/pipeline_engine/phase_envelope/test_store.py` | Neu | Store-Tests (load, save, exists) |
| `tests/unit/pipeline/test_engine.py` | Modifiziert | Engine mit Envelope |
| `tests/unit/pipeline/test_runner.py` | Modifiziert | Runner mit Store |
| `tests/unit/pipeline/test_engine_pause_reason.py` | Neu | PauseReason-Typisierung; fail-closed-Pfad |

## 4. Akzeptanzkriterien

1. **`PhaseEnvelope` Pydantic-v2-Modell existiert** in `src/agentkit/pipeline_engine/phase_envelope/envelope.py` mit Feldern `state: PhaseState`, `runtime: RuntimeMetadata`, `frozen=True`, `extra="forbid"`.
2. **`RuntimeMetadata` enthaelt** `origin: PhaseOrigin`, `loaded_at`, `process_id`, `worker_id`. `PhaseOrigin` ist StrEnum mit `NEW`, `LOADED`.
3. **`PhaseEnvelopeStore` existiert** mit `load`, `save`, `exists`. `save` persistiert nur `envelope.state`; `load` setzt `origin=LOADED` und befuellt `loaded_at`/`process_id`/`worker_id`.
4. **Engine arbeitet mit Envelopes**: `PipelineEngine.run_phase` und `run_pipeline` nehmen/geben Envelopes statt PhaseStates. Handler-Signaturen sind entsprechend angepasst.
5. **`paused_reason` ist typisiert**: `_handle_paused_result` setzt `paused_reason: PauseReason`. Unbekannte Yield-Status-Strings fuehren zu `InvalidPauseReasonError`.
6. **Crash-Safety wird nicht verschlechtert**: existing Tests fuer Resume/Recovery laufen weiter; ein neuer Test beweist, dass `runtime` nicht persistiert wird (Roundtrip: save -> load -> runtime.origin == LOADED).
7. **`phase_state_store/store.py`** ist konsistent: entweder re-exportiert es `PhaseEnvelopeStore` (Re-Export-Compat) oder es ist entfernt; in beiden Faellen existiert keine zweite Persistenz-Facade fuer denselben Inhalt.
8. **Architecture-Conformance**: `pipeline_engine.phase_envelope` darf nur aus `agentkit.core_types`, `agentkit.story_context_manager.models` (PhaseState/PhaseName), und `agentkit.pipeline_engine` importieren.
9. **Pflichtbefehle gruen**: pytest unit + integration; mypy --strict; ruff clean; Coverage haelt 85%.

## 5. Definition of Done

- AK 1-9 erfuellt.
- `.venv\Scripts\python -m pytest -q` gruen.
- `mypy --strict` gruen, `ruff check src tests` gruen.
- Existing Pipeline-Tests weiterhin gruen — Envelope-Migration darf keinen Engine-Vertrag brechen.
- Aenderungen committed auf `main`.

## 6. Konzept-Referenzen (autoritativ, mit `rel_path`)

- **FK-39 §39.1/39.3** — `concept/technical-design/39_phase_state_persistenz.md` (Z. 110-200) — PhaseEnvelope + RuntimeMetadata, Persistenzgrenze (state durable, runtime ephemer)
- **FK-39 §39.2.2** — `concept/technical-design/39_phase_state_persistenz.md` (Glossar Z. 62-69) — PauseReason mit drei Werten
- **FK-39 §39.4.1** — `concept/technical-design/39_phase_state_persistenz.md` (Z. 376-389) — PhaseState-Persistenz / AttemptRecord-Struktur
- **`concept/_meta/bc-cut-decisions.md §BC 1 pipeline-framework`** — PhaseEnvelopeStore-Sub-Definition
- **AG3-021 §2.1.4** — `stories/AG3-021-kern-enums/story.md` — Mapping `PauseReason.from_yield_status`
- **AG3-025 §2.1.1** — `stories/AG3-025-attempt-record-write-ordering/story.md` — `AttemptOutcome.YIELDED` Outcome-Markierung (vgl. Yield-Klarstellung 2.1.5.1)

## 7. Guardrail-Referenzen

- **FIX THE MODEL, NOT THE SYMPTOM**: Persistenzgrenze typisiert ziehen — ephemer (Runtime) vs. durable (State).
- **ZERO DEBT**: alle Aufrufstellen migriert in einem Wurf; kein paralleles Doppelgesicht von PhaseState + PhaseEnvelope.
- **FAIL CLOSED**: unbekannte PauseReason-Strings -> Exception.
- **SINGLE SOURCE OF TRUTH**: ein Store-Sub fuer Phase-Persistenz; kein paralleles `phase_state_store`-Konstrukt.

## 8. Hinweise fuer den Sub-Agent

- `PhaseState` und `PhaseName` leben weiter in `story_context_manager.models`. Diese Story aendert sie NICHT; sie wickelt nur einen Envelope drum herum.
- `PhaseOrigin` koennte auch nach `core_types` wandern. Entscheidung: bleibt im `pipeline_engine`-Sub, weil es nur dort relevant ist und keine Cross-BC-Verwendung absehbar ist.
- Migrationspfad fuer existing-Tests: parametrisierte Test-Helper auf Envelope umstellen; bei reinen PhaseState-Asserts kann ein `envelope.state`-Lookup vorgeschaltet werden.
- AK2 NICHT veraendern.
