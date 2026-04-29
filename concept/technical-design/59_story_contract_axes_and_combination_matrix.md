---
concept_id: FK-59
title: Story-Vertragsachsen und Kombinationsmatrix
module: story-contracts
cross_cutting: true
status: active
doc_kind: core
parent_concept_id:
authority_over:
  - scope: story-contract-classification
  - scope: contract-axis-matrix
  - scope: valid-invalid-combinations
  - scope: non-axis-boundary
defers_to:
  - target: FK-24
    scope: story-type-delivery-contract
    reason: Story-Typen und Lieferpflichten bleiben dort fachlich kanonisch
  - target: FK-56
    scope: operating-mode-resolution
    reason: operating_mode bleibt ein abgeleiteter Session-/Run-Zustand
  - target: FK-57
    scope: implementation-contract
    reason: integration_stabilization bleibt dort fachlich ausgearbeitet
  - target: FK-58
    scope: exit-contract
    reason: administrative Exits und Human-Takeover bleiben dort operationalisiert
supersedes: []
superseded_by:
tags: [story-contracts, classification, combinations, terminality, fail-closed]
prose_anchor_policy: strict
formal_refs:
  - formal.story-contracts.entities
  - formal.story-contracts.state-machine
  - formal.story-contracts.commands
  - formal.story-contracts.events
  - formal.story-contracts.invariants
  - formal.story-contracts.scenarios
---

# 59 — Story-Vertragsachsen und Kombinationsmatrix

<!-- PROSE-FORMAL: formal.story-contracts.entities, formal.story-contracts.state-machine, formal.story-contracts.commands, formal.story-contracts.events, formal.story-contracts.invariants, formal.story-contracts.scenarios -->

## 59.1 Zweck

Die Story-Klassifikation darf in AK3 nicht aus immer mehr lose
nebeneinanderstehenden Feldern bestehen.

Dieses Kapitel zieht deshalb den konsolidierten Schnitt zwischen:

- **persistenten Vertragsachsen**
- **abgeleiteten Laufzeitachsen**
- **Terminal-/Exit-Ergebnissen**
- **Feldern, die ausdruecklich keine Vertragsachse sind**

Ziel ist eine kleine, belastbare Matrix statt eines ausfransenden
Kreuzprodukts.

## 59.2 Grundregel

Eine Achse ist nur dann kanonisch, wenn ein Wertewechsel
erstklassige Governance-Semantik aendert, insbesondere mindestens eines
von:

- Lieferpflicht
- Guard-/Capability-Verhalten
- Verify-/Closure-Zulaessigkeit
- administrativen Endpfaden

Wenn ein Feld nur Routing-Hinweis, Laufzeitdiagnose, Audit-Anreicherung
oder abgeleiteter Session-Zustand ist, ist es **keine** Vertragsachse.

## 59.3 Kanonische Schichten

### 59.3.1 Persistente Vertragsachsen

Persistente Vertragsachsen sind:

1. `story_type`
2. `implementation_contract` (nur fuer `story_type=implementation`)

Diese Felder gehoeren zur kanonischen Story-Semantik und duerfen im
State-Backend bzw. Story-Metadatenmodell persistent gefuehrt werden.

### 59.3.2 Abgeleitete Laufzeitachsen

Abgeleitete Laufzeitachsen sind:

1. `operating_mode`
2. `execution_route`

Sie werden nicht als gleichrangige Story-Klassifikation persistiert,
sondern deterministisch aus Run-Bindung, Story-Typ und Setup-/Routing-
Ergebnis abgeleitet.

### 59.3.3 Ergebnisachsen

Ergebnisachsen sind:

1. `terminal_state`
2. `exit_class` (nur unter `terminal_state=Cancelled`)

Sie beschreiben nicht den Auftrag der Story, sondern wie dieser Auftrag
endet.

## 59.4 Persistente Vertragsachsen

### 59.4.1 `story_type`

`story_type` bleibt die primaere Liefervertragsachse mit genau vier
gueltigen Werten:

- `implementation`
- `bugfix`
- `concept`
- `research`

### 59.4.2 `implementation_contract`

`implementation_contract` ist eine zweite, eng geschnittene
Vertragsachse mit genau zwei gueltigen Werten:

- `standard`
- `integration_stabilization`

Regeln:

- nur zulaessig bei `story_type=implementation`
- fuer andere Story-Typen ungueltig
- `standard` ist der Default
- `integration_stabilization` erzeugt weder neuen Story-Typ noch neuen
  Betriebsmodus

## 59.5 Abgeleitete Laufzeitachsen

### 59.5.1 `operating_mode`

`operating_mode` beschreibt das Governance-Regime der aktiven Session:

- `ai_augmented`
- `story_execution`

`binding_invalid` ist **kein** normaler dritter Modus, sondern ein
blockierender Fehlerzustand bei gebrochener Story-Bindung.

`operating_mode` ist kein kanonisches Story-Feld, sondern wird gemaess
FK-56 aus Session-Bindung, Lock und Worktree-Konsistenz abgeleitet.

### 59.5.2 `execution_route`

`execution_route` beschreibt innerhalb von `story_execution`, ob eine
Story unmittelbar in die Umsetzung geht oder zuerst den Exploration-Pfad
durchlaeuft:

- `execution`
- `exploration`

Wichtig:

- `execution_route` ist nicht identisch mit `operating_mode`
- das historische Feld `mode` in `phase-state.json` bezeichnet
  fachlich **`execution_route`**
- ausserhalb eines gueltigen Story-Runs hat `execution_route` keine
  eigenstaendige Bedeutung

Fuer `concept` und `research` ist `execution_route=execution` nur ein
kompatibler Wire-Wert ohne implementierungsartige Exploration-Semantik.

## 59.6 Ergebnisachsen

### 59.6.1 `terminal_state`

Die konsolidierte Ergebnisachse fuer Stories lautet:

- `Open`
- `Done`
- `Cancelled`

`Open` ist kein eigener administrativer Endzustand, sondern die
Sammelkategorie fuer alle nicht terminal beendeten Stories.

### 59.6.2 `exit_class`

`exit_class` ist **keine** frei stehende Vertragsachse.

Sie ist nur zulaessig, wenn:

- `terminal_state=Cancelled`

und wird dann in einem offiziellen Exit-/Split-/Reset-Record
dokumentiert.

Beispiele:

- `scope_split`
- `viability_handoff`
- weitere offizielle administrative Abbruchklassen

## 59.7 Gültige Kernkombinationen

| `story_type` | `implementation_contract` | Typischer Pfad | Terminal zulaessig |
|-------------|----------------------------|----------------|--------------------|
| `implementation` | `standard` | Setup -> Execution oder Exploration -> Implementation -> Verify -> Closure | `Done`, `Cancelled` |
| `implementation` | `integration_stabilization` | Setup -> Exploration -> Integration-Stabilisierung -> Verify -> Stability-Gate -> Closure | `Done`, `Cancelled` |
| `bugfix` | `standard` | Setup -> direkte oder explorative Bugfix-Umsetzung -> Verify -> Closure | `Done`, `Cancelled` |
| `concept` | nicht anwendbar | Story-Definition / Konzeptbearbeitung / Review | `Done`, `Cancelled` |
| `research` | nicht anwendbar | Recherchepfad / Ergebnisdokumentation | `Done`, `Cancelled` |

## 59.8 Harte Ungueltigkeiten

Die folgenden Kombinationen sind fail-closed unzulaessig:

1. `implementation_contract != standard` bei `story_type != implementation`
2. `terminal_state=Done` und `exit_class != null`
3. `terminal_state != Cancelled` und `exit_class != null`
4. `Cancelled` als Ergebnis normaler Closure-Semantik
5. `operating_mode=story_execution` ohne gueltige Run-Bindung
6. stiller Rueckfall von inkonsistenter Story-Bindung auf
   `ai_augmented`
7. Interpretation von `integration_stabilization` als eigener
   Betriebsmodus

## 59.9 Was ausdruecklich keine Vertragsachse ist

Die folgenden Dinge sind wichtig, aber **keine** kanonischen
Vertragsachsen:

- `phase`
- `pause_reason`
- `escalation_reason`
- `binding_invalid`
- `principal_type`
- `verify_context`
- `change_impact`
- Labels, Repo-Affinität, Komponentenzuordnung
- Scope-Explosion, Governance-Incident, Merge-Fail als Befundklassen

Sie gehoeren in State Machines, Guards, Routing-Inputs oder
Audit-Telemetrie, nicht in die Vertragsmatrix.

## 59.10 Abgeleitete Konsequenzen

Aus der Matrix folgen einige harte Regeln direkt:

1. `story_type in {implementation, bugfix}` plus
   `execution_route=exploration` bedeutet:
   - `implementation_required=true`
   - `closure_allowed=false`
   - reine Exploration ist nicht terminal
2. `implementation_contract=integration_stabilization` bedeutet:
   - Exploration ist Pflicht
   - Manifest, Budget und Stability-Gate sind Pflicht
   - Cross-Scope-Arbeit bleibt manifestgebunden
3. `terminal_state=Cancelled` bedeutet:
   - kein Merge
   - keine erfolgreiche Closure
   - Story gilt sichtbar als nicht geliefert

## 59.11 Technische Konsequenz fuer Schemas und State

Der kanonische Persistenzschnitt lautet:

- `story_type`: persistent
- `implementation_contract`: persistent
- `operating_mode`: abgeleitet, nicht kanonisches Story-Feld
- `execution_route`: runtime-scoped; derzeit ueber das Wire-Feld `mode`
  materialisiert
- `exit_class`: nur in offiziellen Exit-/Split-/Reset-Records, nicht als
  freies Story-Hauptfeld

Damit wird verhindert, dass Session-Brueche, stale Locks oder
administrative Exits als normale Story-Klassifikation verwechselt
werden.

## 59.12 Test- und Compile-Pflichten

Pflichtpruefungen fuer diesen Vertrag sind:

- `test_implementation_contract_only_allowed_for_implementation`
- `test_exit_class_only_allowed_when_terminal_state_cancelled`
- `test_operating_mode_is_runtime_derived_not_story_persisted`
- `test_binding_invalid_is_not_free_ai_augmented`
- `test_integration_stabilization_is_not_third_operating_mode`
- `test_phase_state_mode_is_execution_route_alias`

