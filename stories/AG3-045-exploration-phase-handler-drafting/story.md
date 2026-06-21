# AG3-045: ExplorationPhaseHandler + ExplorationDrafting + Bugfix-Profil-Fix + Gate-Guard-Erweiterung

> **SCOPE-AENDERUNG (Product-Owner-Entscheidung 2026-06-05, „Option Y"):** AG3-045 liefert die **deterministische Klempnerei** der Exploration-Phase — Handler, Gate-Guard, ChangeFrame-**Schema** (FK-23, englische Felder), Persistenz, Protected-Path, Bugfix-Profil — **NICHT** das inhaltliche Drafting. Das echte Erzeugen des ChangeFrame ist Aufgabe eines gespawnten Workers und wurde in die eigene Story **AG3-055** (BC `exploration-and-design`; Worker-Verhalten via `worker-exploration.md`) ausgegliedert. **Folge:** **AC 2** (sieben Drafting-Schritte als Eigenleistung) und der **AC-9-Provisorium-APPROVE** sind hierdurch **SUPERSEDED** — statt eines regelbasierten Pseudo-Produzenten ist die Phase **ehrlich fail-closed**, solange kein vom Worker (AG3-055) erzeugter, valider ChangeFrame vorliegt. `ExplorationDrafting` als Inhaltsproduzent **entfaellt**; Maschinerie-Tests laufen gegen ein statisches Beispiel-Fixture. **Ebenso SUPERSEDED (historische Body-Texte unten):** §2.1.1 Stub-Review/Provisorium-APPROVE, §2.1.6 `change_frame_ref`-Validator, sowie die AC7/AC9-Provisorium-Formulierungen — tatsaechlich **eskaliert der Handler fail-closed** (kein Fake-APPROVED), es gibt **kein** `change_frame_ref`-Feld (die Invariante „APPROVED nur mit persistiertem ChangeFrame" liegt an der Handler-Grenze), und das Artefakt heisst **`change_frame.json`**.

**Typ:** Implementation
**Groesse:** M
**Abhaengigkeiten:** AG3-021 (ExplorationGateStatus), AG3-024 (PhaseEnvelope), AG3-026 (VerifySystem-Top fuer Exploration-QA-Aufruf spaeter), AG3-041 (QA-Cycle-Lifecycle fuer Review-Aufruf)
**Quell-Konzepte (autoritativ, in dieser Reihenfolge):**
- `FK-23 §23.3` (ExplorationPhaseHandler)
- `FK-23 §23.3.2` (ExplorationDrafting — sieben Worker-Schritte)
- `FK-23 §23.4` (Entwurfsartefakt mit sieben Pflichtbestandteilen)
- `FK-23 §23.5.0` (`exploration_gate_approved`-Guard prueft `payload.gate_status == APPROVED`)
- `FK-23 §23.1` (Bugfix als Exploration-faehiger Story-Typ)
- `concept/_meta/bc-cut-decisions.md §BC 5 exploration-and-design`

---

## 1. Kontext

THEME-010 aus `stories/_priorisierungsempfehlung.md`. Befunde aus `exploration-and-design`:

- `exploration-and-design.A1`: `ExplorationPhaseHandler` Top-Komponente fehlt — leere Namespace-Datei.
- `exploration-and-design.A2`: `ExplorationDrafting`-Sub mit sieben Worker-Schritten fehlt.
- `exploration-and-design.B1`: `exploration_gate_approved`-Guard prueft nur `PhaseStatus.COMPLETED`, nicht `payload.gate_status == APPROVED`.
- `exploration-and-design.B3`: Workflow-DSL ohne typisierte Gate-Stufen.
- `exploration-and-design.C3`: Bugfix-Profil blockiert Exploration-Vorlauf — FK-23 §23.1 erlaubt aber Bugfix mit `Concept Quality=Low` als Exploration-fall.

Diese Story bringt den **Phase-Handler-Eingang** und das **Drafting**. ExplorationReview (drei-stufiges Gate) und MandateClassification sind separate Stories (AG3-046, AG3-047) — sie bauen aufeinander auf.

## 2. Scope

### 2.1 In Scope

#### 2.1.1 `ExplorationPhaseHandler` (FK-23 §23.3)

Neues Modul `src/agentkit/pipeline/phases/exploration/`:

- `__init__.py` — Re-Export `ExplorationPhaseHandler`
- `phase.py` — Handler-Klasse:

```python
class ExplorationPhaseHandler(PhaseHandler):
    def __init__(self, drafting: ExplorationDrafting, review: ExplorationReview | None = None) -> None: ...

    def on_enter(self, envelope: PhaseEnvelope) -> HandlerResult: ...
    def on_resume(self, envelope: PhaseEnvelope) -> HandlerResult: ...
```

Diese Story implementiert `on_enter` mit Drafting + Stub-Review (Review-Methodik kommt in AG3-046). Stub-Review setzt `payload.gate_status = APPROVED` direkt — das ist ein **explizit dokumentierter Provisorium-Pfad**, der von AG3-046 ersetzt wird.

#### 2.1.2 `ExplorationDrafting` (FK-23 §23.3.2)

`src/agentkit/pipeline/phases/exploration/drafting/`:

```python
class ExplorationDrafting:
    def __init__(self, artifact_manager: ArtifactManager) -> None: ...

    def execute(self, ctx: PhaseContext) -> DraftingResult: ...
```

Sieben Worker-Schritte (FK-23 §23.3.2):
1. Story-Verdichtung (Story-Brief in Kurzform)
2. Referenzdokument-Recherche (FK-/DK-Anker)
3. Aenderungsflaechen-Lokalisierung (welche Module sind betroffen)
4. Loesungsrichtung (high-level Design)
5. Selbst-Konformitaetspruefung (gegen Konzept-Anker)
6. ChangeFrame-Erzeugung (Entwurfsartefakt-Bauen)
7. Persistenz via ArtifactManager (ArtifactClass.ENTWURF)

Jeder Schritt liefert ein typisiertes Result; alle Ergebnisse werden in `ChangeFrame`-Pydantic-Modell aggregiert.

#### 2.1.3 `ChangeFrame`-Datenmodell (FK-23 §23.4, FK-25 §25.4.2)

Pydantic-v2-Modell mit sieben Pflichtbestandteilen (FK-23 §23.4):
- `story_condensed: str`
- `reference_docs: list[ReferenceAnchor]`
- `affected_modules: list[str]`
- `solution_direction: str`
- `self_consistency_check: SelfConsistencyResult`
- `change_summary: str`
- `acceptance_criteria_mapping: dict[str, str]` (Story-AC -> Loesungsschritt)

Plus Lifecycle-Felder:
- `gate_status: ExplorationGateStatus` (aus core_types; Default `PENDING`)
- `frozen: bool` (Default False)
- `frozen_at: datetime | None`

Persistenz: JSON unter `_temp/qa/{story_id}/change_frame.json` (FK-23 §23.4.3) plus Envelope ueber ArtifactManager.

> **Sprache (Guardrail ARCH-55, PO-Entscheidung 2026-06-05):** Code und Datenmodell sind durchgaengig **englisch**; ChangeFrame-Feldnamen sind englisch. FK-23 §23.4 wurde von deutschen auf englische Wire-Keys umgestellt. (Die genaue Feld-Dekomposition gegenueber FK-23s sieben Bestandteilen wird zusammen mit D2 final geklaert.)

#### 2.1.4 `exploration_gate_approved`-Guard Erweiterung (exploration-and-design.B1)

`src/agentkit/process/language/guards.py:exploration_gate_approved`:

Aktuelle Logik: prueft nur `phase == "exploration"` und `status == COMPLETED`. Neu:

```python
def exploration_gate_approved(envelope: PhaseEnvelope) -> bool:
    return (
        envelope.state.phase == PhaseName.EXPLORATION
        and envelope.state.status == PhaseStatus.COMPLETED
        and isinstance(envelope.state.payload, ExplorationPayload)
        and envelope.state.payload.gate_status == ExplorationGateStatus.APPROVED
    )
```

Defense-in-Depth (FK-23 §23.5.0): COMPLETED ohne APPROVED-gate_status -> Guard liefert False; Implementation-Phase wird nicht freigegeben.

#### 2.1.5 Bugfix-Profil Fix (exploration-and-design.C3)

`src/agentkit/story_context_manager/types.py:PROFILES[StoryType.BUGFIX]`:

- `allowed_modes` wird erweitert: `(StoryMode.EXECUTION, StoryMode.EXPLORATION)` statt nur `(StoryMode.EXECUTION,)`
- `phases` bleibt unveraendert (Bugfix-Stories durchlaufen Exploration nur, wenn Mode==EXPLORATION). **Boundary:** AG3-045 setzt ausschliesslich das `allowed_modes`-Flag (AC6). Die tatsaechliche **Mode→Exploration-Phase-Routing-Weiche** fuer Bugfix ist Workflow-Dispatch (**AG3-054 §2.1.3**, `resolve_workflow`); bis diese mode-aware ist, darf ein Bugfix+EXPLORATION **nicht still** in Implementation durchrutschen (AG3-054 muss mode-aware routen oder fail-closed ablehnen). Offener Owner: AG3-054.
- Tests bestaetigen, dass Bugfix-Stories mit `Concept Quality=Low` zu Exploration-Mode routen koennen (FK-21 §21.3.3)

#### 2.1.6 `ExplorationPayload`-Hardening (exploration-and-design.B2)

`src/agentkit/story_context_manager/models.py:ExplorationPayload`:

- Feld `gate_status: ExplorationGateStatus | None` -> `gate_status: ExplorationGateStatus = ExplorationGateStatus.PENDING` (typisiert, Default PENDING)
- Validator: `gate_status` darf nicht direkt von PENDING zu APPROVED springen ohne `change_frame_ref` (Referenz auf persistierten ChangeFrame)

#### 2.1.7 `_temp/qa/{story_id}/change_frame.json` als Protected-Path

`src/agentkit/governance/protected_paths.py` (AG3-023) wird erweitert: Entwurfsartefakt-Pfad ist nach Freeze write-protected.

#### 2.1.8 Tests

- Unit-Tests fuer `ExplorationDrafting.execute` (alle sieben Schritte produzieren typisierten Output)
- Unit-Tests fuer `ChangeFrame`-Modell (Pflichtfelder, Validators)
- Unit-Test fuer `exploration_gate_approved`-Guard:
  - COMPLETED + APPROVED -> True
  - COMPLETED + PENDING -> False
  - COMPLETED + REJECTED -> False
  - COMPLETED + ExplorationPayload-None -> False
- Unit-Test Bugfix-Profil: `PROFILES[StoryType.BUGFIX].allowed_modes` enthaelt EXPLORATION
- Integration-Test: ExplorationPhaseHandler.on_enter erzeugt ChangeFrame, persistiert via ArtifactManager
- Contract-Test `tests/contract/exploration/test_change_frame.py`: sieben Pflichtbestandteile
- Contract-Test `tests/contract/exploration/test_gate_guard.py`: Defense-in-Depth-Pfad

### 2.2 Out of Scope

- ExplorationReview (drei-stufiges Exit-Gate) — AG3-046
- MandateClassification — AG3-047
- DesignFreezeMarker — AG3-047
- Telemetrie-Events (`mandate_classification`, `fine_design_decision`, `scope_explosion_check`, `impact_exceedance_check`) — AG3-047 + THEME-007 (Event-Types wurden in AG3-037 bereitgestellt)
- Drift-Erkennung im Implementation (`exploration-and-design.B4`) — gehoert zu THEME-009/AG3-044 (Worker-Loop hat DriftCheckHook)
- Impact-Violation-Check im QA-Subflow Schicht 1 (`FK-23 §23.8`) — bereits Teil von AG3-042
- Veraltete `pipeline_engine/verify_phase`-Artefakte Cleanup (`exploration-and-design.C1`) — gehoert zu THEME-001 (bereits adressiert)
- Tests-Stub-Verzeichnis `tests/integration/pipeline/exploration_mode/` befuellen — Folge-Story nach AG3-046/047
- **Produktive Registrierung des `ExplorationPhaseHandler` an der `PhaseHandlerRegistry`** — **AG3-054** (`pipeline-composition-root-phase-handler-registry`, dort §2.1.1: „exploration → der `ExplorationPhaseHandler` … aus AG3-045"). AG3-045 stellt **nur** die registrierbare Surface/Factory (`build_exploration_phase_handler`) bereit; ein Review-Befund „Handler nicht produktiv verdrahtet" ist damit OOS, **kein** AG3-045-Blocker.

## 3. Betroffene Dateien

| Datei | Aenderungsart | Beschreibung |
|---|---|---|
| `src/agentkit/pipeline/phases/exploration/__init__.py` | Modifiziert (leer -> exportiert Handler) | |
| `src/agentkit/pipeline/phases/exploration/phase.py` | Neu | `ExplorationPhaseHandler` |
| `src/agentkit/pipeline/phases/exploration/drafting/__init__.py` | Neu | |
| `src/agentkit/pipeline/phases/exploration/drafting/drafting.py` | Neu | `ExplorationDrafting` |
| `src/agentkit/pipeline/phases/exploration/drafting/steps.py` | Neu | sieben Step-Funktionen |
| `src/agentkit/pipeline/phases/exploration/change_frame.py` | Neu | `ChangeFrame`, `ReferenceAnchor`, `SelfConsistencyResult` |
| `src/agentkit/process/language/guards.py` | Modifiziert | `exploration_gate_approved` mit Payload-Pruefung |
| `src/agentkit/story_context_manager/models.py` | Modifiziert | ExplorationPayload mit typisiertem `gate_status` |
| `src/agentkit/story_context_manager/types.py` | Modifiziert | Bugfix-Profil erweitert |
| `src/agentkit/governance/protected_paths.py` | Modifiziert | Entwurfsartefakt-Pfad nach Freeze |
| `tests/unit/pipeline/phases/exploration/test_drafting.py` | Neu | |
| `tests/unit/pipeline/phases/exploration/test_phase.py` | Neu | |
| `tests/unit/pipeline/phases/exploration/test_change_frame.py` | Neu | |
| `tests/unit/process/language/test_exploration_gate_guard.py` | Neu | Defense-in-Depth |
| `tests/unit/story_context_manager/test_bugfix_profile.py` | Neu | EXPLORATION erlaubt |
| `tests/integration/pipeline/exploration/test_phase_e2e.py` | Neu | E2E Drafting |
| `tests/contract/exploration/test_change_frame.py` | Neu | sieben Pflichtbestandteile |
| `tests/contract/exploration/test_gate_guard.py` | Neu | Defense-in-Depth |

## 4. Akzeptanzkriterien

1. **`ExplorationPhaseHandler` existiert** unter `src/agentkit/pipeline/phases/exploration/phase.py` mit `on_enter` und `on_resume`.
2. **`ExplorationDrafting` implementiert die sieben Worker-Schritte** aus FK-23 §23.3.2 in der genannten Reihenfolge.
3. **`ChangeFrame`** ist Pydantic-v2-Modell mit sieben Pflichtbestandteilen (Story-condensed, Reference-Docs, Affected-Modules, Solution-Direction, Self-Consistency, Change-Summary, AC-Mapping).
4. **`exploration_gate_approved`-Guard prueft `payload.gate_status == APPROVED`** zusaetzlich zu `status==COMPLETED`. Defense-in-Depth-Test bestaetigt das.
5. **`ExplorationPayload.gate_status`** ist typisiert (`ExplorationGateStatus`) mit Default `PENDING`.
6. **Bugfix-Profil**: `PROFILES[StoryType.BUGFIX].allowed_modes` enthaelt `StoryMode.EXPLORATION`. Tests bestaetigen das.
7. **`ChangeFrame`-Persistenz** ueber `ArtifactManager` mit `ArtifactClass.ENTWURF`; Envelope-Pflichtfelder gesetzt; auch JSON unter `_temp/qa/{story_id}/change_frame.json` geschrieben.
8. **Protected-Path**: Entwurfsartefakt-Pfad ist nach Freeze (siehe AG3-047) write-protected; die Konstante ist hier vorbereitet, der Freeze-Wechsel passiert in AG3-047.
9. **Provisorium-Pfad in `ExplorationPhaseHandler.on_enter`**: setzt `gate_status=APPROVED` direkt nach Drafting **mit explizitem TODO-Verweis auf AG3-046** (Review-Methodik) — das ist die einzige Stelle mit dokumentiertem Provisorium; alle anderen Pfade sind konzeptkonform. (Aufgabe von AG3-046 ist diesen Provisorium-Pfad zu ersetzen.)
10. **Architecture-Conformance**: `pipeline/phases/exploration/` importiert nur `agentkit.backend.core_types`, `agentkit.backend.artifacts`, `agentkit.backend.story_context_manager.models`, `agentkit.backend.process.language`.
11. **Pflichtbefehle gruen**: pytest unit + integration + contract; mypy --strict; ruff clean; Coverage haelt 85%.

## 5. Definition of Done

- AK 1-11 erfuellt.
- `.venv\Scripts\python -m pytest tests/unit/pipeline/phases/exploration tests/integration/pipeline/exploration tests/contract/exploration -q` gruen.
- `mypy --strict` gruen, `ruff check src tests` gruen.
- Aenderungen committed auf `main`.

## 6. Konzept-Referenzen (autoritativ)

- **FK-23 §23.3** — ExplorationPhaseHandler
- **FK-23 §23.3.2** — sieben Worker-Schritte
- **FK-23 §23.4** — Entwurfsartefakt
- **FK-23 §23.5.0** — Gate-Status + Guard
- **FK-23 §23.1** — Bugfix-Exploration
- **FK-25 §25.4.2** — ChangeFrame
- **`concept/_meta/bc-cut-decisions.md §BC 5`** — BC-Schnitt

## 7. Guardrail-Referenzen

- **FIX THE MODEL, NOT THE SYMPTOM**: Exploration-Phase-Handler endlich existent; Defense-in-Depth im Gate-Guard.
- **ZERO DEBT**: ChangeFrame mit allen sieben Pflichtbestandteilen.
- **FAIL CLOSED**: Gate-Guard ohne APPROVED-Status laesst Implementation nicht starten.
- **NO ERROR BYPASSING**: COMPLETED+PENDING kann nicht weiter zur Implementation routen.

## 8. Hinweise fuer den Sub-Agent

- Provisorium-Pfad fuer Gate-Approval: setze `gate_status=APPROVED` mit klarem TODO-Kommentar im Code (`# TODO AG3-046: replace with full ExplorationReview`). Nicht silent.
- **Inhaltliches Drafting ist NICHT Teil von AG3-045** (Option Y, PO 2026-06-05): die sieben FK-23-§23.3.2-Schritte erzeugt der gespawnte Exploration-Worker — **AG3-055** (BC `exploration-and-design`; Worker-Verhalten via `worker-exploration.md`). AG3-045 baut die deterministische Klempnerei + das ChangeFrame-**Schema** und **konsumiert/validiert** den vom Worker erzeugten ChangeFrame. Ohne validen Worker-Entwurf ist die Phase **fail-closed** — kein regelbasierter Pseudo-Entwurf, keine Fake-APPROVED. Maschinerie-Tests gegen statisches Beispiel-Fixture; Test-Determinismus der Worker-Grenze via record-replay (AG3-055).
- AK2 NICHT veraendern.
