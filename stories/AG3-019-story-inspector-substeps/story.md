# AG3-019: Story-Inspector — Phase-/Substep-Visualisierung mit Mode-Label

**Typ:** Implementation
**Groesse:** M
**Abhaengigkeiten:** AG3-018 (Fast-Modus konzeptionell vorhanden + Mode-Field im Service-API-Schema)
**Quell-Konzept:** FK-72 (Frontend-Architektur), FK-22-29 (Phase-Substep-Sequenzen), FK-91 §91.1a (Service-API Phase-State), FK-24 §24.X (Mode-Profil, nach AG3-018)

---

## Kontext

Der Story-Inspector im Frontend zeigt heute die Phase einer laufenden Story auf grober Granularitaet (Setup / Exploration / Implementation / Closure). Im Alltag ist das zu grob: der User moechte sehen, **in welchem Substep** der Phase die Story steckt — z.B. "Implementation > QA-Subflow Schicht 2 LLM-Bewertungen" oder "Closure > Branch-Merge". Zusaetzlich soll bei Stories im `mode=fast` ein **prominentes Label** sofort sichtbar sein, damit klar ist, dass diese Story die abgespeckte Pruef-/Guard-Strecke nimmt.

Die Substep-Sequenzen sind in den Phase-Konzepten (FK-22, 23, 26, 27, 29) als Mermaid-Diagramme normativ definiert und werden mit AG3-018 um das Fast-Profil ergaenzt.

## Voraussetzungen / Abhaengigkeiten

- **AG3-018** liefert: `Mode`-StrEnum mit `fast`, Service-API akzeptiert/persistiert `mode`, FK-24 Mode-Profil als kanonische Quelle.
- **Service-API** liefert pro Story den aktuellen Phase-State **mit Substep-Granularitaet**. Falls heute nur die Phase im Phase-State liegt, wird das Schema im Rahmen dieser Story erweitert (§Service-API).

## Scope

### In Scope — Datenmodell / Backend

- `PhaseStateCore` (oder aequivalent): zusaetzliches typisiertes Feld `substep` (StrEnum pro Phase). Substep-Werte aus den Phase-Konzepten abgeleitet:
  - Setup: `preflight`, `story_context`, `are_bundle`, `type_switch`, `worktree`, `guard_activation`, `mode_resolution`
  - Exploration: `worker_spawn`, `draft`, `structural_validation`, `doc_fidelity_l2`, `design_review`, `triggered_challenge`, `aggregation`, `feindesign`, `freeze`
  - Implementation: `worker_start`, `incremental`, `inline_reviews`, `final_build`, `handover`, plus QA-Subflow: `qa_layer1_structural`, `qa_layer2_llm`, `qa_layer3_adversarial`, `qa_layer4_policy`, `qa_feedback`
  - Closure: `finding_resolution`, `integrity_gate`, `branch_push`, `merge`, `main_push`, `teardown`, `story_close`, `metrics`, `doc_fidelity_l4`, `postflight`, `vectordb_sync`, `guards_off`
- Phase-Handler setzen `substep` deterministisch beim Eintritt jedes Substeps (kein nachgelagertes Inferieren).
- Substep-Werte sind Phase-spezifische StrEnums; ein Service-API-Endpoint liefert `{phase, substep, mode, ...}`.

### In Scope — Service-API (FK-91 §91.1a)

- Phase-State-Endpoint erweitert um `substep`-Feld (StrEnum-String).
- Mode-Feld im Response (von AG3-018 vorhanden).
- Schema-Doku in FK-91 nachziehen.

### In Scope — Frontend (FK-72)

- **Phase-Stepper**: 4-stufiger Stepper (Setup, Exploration, Implementation, Closure). Aktuelle Phase visuell hervorgehoben; durchlaufene Phasen als "completed" markiert.
- **Substep-Indicator** pro aktiver Phase: Liste der Substeps der aktuellen Phase mit aktueller Position. Visuell als Sub-Stepper oder Progress-Liste.
- **Mode-Label** prominent neben Story-Header: Badge "FAST" (oder analoge visuelle Auszeichnung) wenn `mode=fast`. Im Standard-Modus kein Label oder neutrales "STANDARD"-Label.
- **Fast-Profil-Hinweise** (optional, aber sinnvoll): Substeps die im Fast-Profil OUT sind, ausgegraut. Substeps die MOD sind: Tooltip mit Verweis auf FK-24 §24.X.
- **Read-Only**: Substep-Position ist nur Visualisierung, nicht editierbar.

### In Scope — Konzept-Updates

- FK-72 §72.6 (Inspector-Tabs) bzw. §72.7 (Schreibpfade): Story-Inspector mit Phase-/Substep-Stepper und Mode-Label dokumentieren.
- FK-91 §91.1a: Phase-State-Response um `substep`-Feld erweitern.
- FK-39 (Phase-State-Persistenz) oder analoges Konzept: `substep`-Feld im Phase-State-Schema spezifizieren.

### Out of Scope

- Live-Updates ueber SSE (kann Folge-Story sein; FK-72 §72.12 SSE-Mechanismus existiert bereits)
- Substep-Tracking ausserhalb der vier Hauptphasen (Hooks, Telemetry-Subsysteme)
- Editierbarkeit der Substep-Position
- Animation oder Sequenz-Replay (statisch reicht fuer den Anwendungsfall)

## Betroffene Dateien (Auswahl)

| Datei | Aenderungsart | Beschreibung |
|-------|---------------|--------------|
| `concept/technical-design/72_frontend_architektur.md` | Modifiziert | Story-Inspector mit Phase-/Substep-Stepper + Mode-Label |
| `concept/technical-design/91_api_event_katalog.md` | Modifiziert | Phase-State-Endpoint um `substep` erweitern |
| `concept/technical-design/39_phase_state_persistenz.md` (oder aehnlich) | Modifiziert | `substep`-Feld im Schema |
| `src/agentkit/core/phase_state.py` | Modifiziert | Substep-StrEnum-Felder pro Phase, typisiert |
| `src/agentkit/pipeline/phases/...` | Modifiziert | Substep-Position bei Eintritt setzen |
| `src/agentkit/control_plane/api/phase_state.py` (oder aequivalent) | Modifiziert | API-Response um `substep` |
| Frontend Story-Inspector Komponenten | Neu / Modifiziert | Stepper-Komponente, Mode-Label-Komponente |
| `tests/unit/core/test_phase_state_substeps.py` | Neu | Substep-Wert-Tests, Setzungs-Tests |
| `tests/unit/control_plane/test_phase_state_api.py` | Neu | API-Response-Schema |
| Frontend-Tests (Komponenten) | Neu | Stepper- und Mode-Label-Tests |

## Akzeptanzkriterien

1. Story-Inspector zeigt fuer eine laufende Story: aktuelle Phase + aktueller Substep, visuell als 4er-Stepper plus Sub-Stepper.
2. Wenn `mode=fast`: prominentes "FAST"-Label am Story-Header sichtbar.
3. Wenn `mode=fast`: OUT-Substeps ausgegraut, MOD-Substeps mit Tooltip auf FK-24 §24.X.
4. Service-API liefert `substep` in der Phase-State-Response (typisierter StrEnum-String).
5. Substep-Position wird im Backend deterministisch beim Substep-Eintritt gesetzt — kein heuristisches Inferieren.
6. Substep-Werte sind als StrEnum pro Phase typisiert (kein String-Frei-Form).
7. Tests gruen, mypy strict, ruff clean.
8. Frontend mit echter Fast- und Standard-Story durchgespielt; Phasen- und Substep-Wechsel werden korrekt visualisiert; Mode-Label korrekt gesetzt.

## Definition of Done

- Konzept-Aenderungen committed (FK-72, FK-91, FK-39)
- Code-Aenderungen (Backend + Frontend) mit Tests committed
- Manuelles UI-Smoke-Testing mit echtem Service durchgefuehrt
- Validatoren gruen

## Konzept-Referenzen

- FK-72 — Frontend-Architektur, Owner Story-Inspector
- FK-91 §91.1a — Service-API Phase-State
- FK-39 — Phase-State-Persistenz
- FK-22, 23, 26, 27, 29 — Substep-Quellen (Mermaids)
- FK-24 §24.X — Mode-Profil Fast (nach AG3-018)

## Guardrail-Referenzen

- **SINGLE SOURCE OF TRUTH**: Substep-Definitionen typisiert (StrEnum pro Phase), kein String-Frei-Form. Mode-Profil-Sicht im Frontend referenziert FK-24 §24.X (Tooltips), dupliziert nicht.
- **ZERO DEBT**: Substep-Position-Setzen passiert deterministisch beim Substep-Eintritt im Backend, kein nachgelagertes Inferieren.
- **FAIL CLOSED**: ungueltige Substep-Werte werden im Backend abgewiesen; Frontend rendert unbekannte Substeps als "unknown" mit Warn-Indikator.
