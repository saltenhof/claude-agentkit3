# AG3-031: Governance Top-Surfaces — register_hooks und deactivate_locks

**Typ:** Implementation
**Groesse:** M
**Abhaengigkeiten:** AG3-021 (Enums), AG3-022 (ArtifactClass-Bezug fuer Hook-Bindings)
**Quell-Konzepte (autoritativ, in dieser Reihenfolge):**
- `FK-30 §30.3.1` (`Governance.register_hooks(hook_definitions)`)
- `FK-30 §30.6.0` (`Governance.deactivate_locks(story_id)`)
- `concept/_meta/bc-cut-decisions.md §BC 4 governance-and-guards`
- `FK-22 §22.7` (Lock-Record + Project Edge Client)
- `FK-29 §29.5` (Closure ruft `deactivate_locks`)

---

## 1. Kontext

THEME-005 aus `stories/_priorisierungsempfehlung.md`. Befund `governance-and-guards.A5`: Top-Surfaces `Governance.register_hooks(hook_definitions)` und `Governance.deactivate_locks(story_id)` fehlen. `Governance.run_hook()` existiert, aber weder `register_hooks` (fuer den Installer) noch `deactivate_locks` (fuer Closure) sind als Methoden der `Governance`-Klasse implementiert.

Diese Story stellt die zwei Top-Surfaces bereit. Sie sind in sich klein, aber blockieren zwei groessere Aufrufer-Pfade (Installer in AG3-027 nutzt Skills.bind_skill und braucht parallel register_hooks; Closure-Story der Folge-Welle braucht deactivate_locks). Daher in der Erst-Welle.

## 2. Scope

### 2.1 In Scope

#### 2.1.1 `Governance.register_hooks` (FK-30 §30.3.1)

`src/agentkit/governance/runner.py:Governance`:

```python
def register_hooks(self, hook_definitions: list[HookDefinition]) -> RegistrationResult:
    """
    Registriert harness-spezifische Hook-Definitionen im Projekt.
    Idempotent: doppelte Registrierung gleicher hook_id ueberschreibt nicht ohne Force.
    """
```

`HookDefinition` ist Pydantic-Modell:
- `hook_id: HookId` — StrEnum mit allen 9 Pre-Hook-IDs aus FK-30 §30.5 (`branch_guard`, `orchestrator_guard`, `qa_artifact_guard`, `qa_agent_guard`, `adversarial_guard`, `self_protection_guard`, `story_creation_guard`, `budget_guard`, `health_monitor`) plus `ccag`
- `harness: HookHarness` — StrEnum `CLAUDE_CODE`, `CODEX`
- `command_template: str` — wie der Hook aufgerufen wird (z.B. `agentkit-hook-claude --hook=branch_guard`)
- `event_pattern: str` — auf welches Harness-Event gehoert wird

`RegistrationResult` ist Pydantic-Modell:
- `registered: list[HookId]`
- `skipped: list[HookId]` (idempotent: war schon registriert)
- `errors: list[HookRegistrationError]`

Persistenz: hook_definitions werden im State-Backend-Storage abgelegt (neue Tabelle `governance_hook_registrations` mit `(project_key, harness, hook_id)` UNIQUE). Datei-/Settings-Schreibvorgaenge (`.claude/settings.json`, `.codex/config.toml`) werden vom Installer-Body geschrieben (Cross-BC-Aktion); diese Top-Surface verwaltet nur den Backend-Zustand und liefert dem Installer die Liste der zu schreibenden Hooks.

#### 2.1.2 `Governance.deactivate_locks` (FK-30 §30.6.0)

```python
def deactivate_locks(self, story_id: str) -> DeactivationResult:
    """
    Wird von story-closure am Ende eines Runs aufgerufen.
    Beendet alle Lock-Records der Story (Story-Execution-Lock, Worktree-Locks etc.)
    und entfernt Edge-Bundle-Exporte (FK-22 §22.7).
    """
```

`DeactivationResult` ist Pydantic-Modell:
- `deactivated_locks: list[LockRecordId]`
- `removed_edge_bundles: list[Path]`
- `errors: list[str]`

Implementation:
- Lookup im `state_backend/store/lock_record_repository.py` (Lock-Records pro Story)
- Loesche Lock-Records aus DB
- Entferne `_temp/governance/{story_id}/edge-bundle.json` (existing-Pfad aus FK-22 §22.7)
- Fail-closed bei IO-Fehlern; partial-Deactivation wird in `errors[]` reportiert (nicht silent)

#### 2.1.3 `HookDefinition`-Datenmodell und Repository

`src/agentkit/governance/hook_registration.py`:
- `HookDefinition`, `HookId` (StrEnum), `HookHarness` (StrEnum), `RegistrationResult`
- `HookRegistrationRepository`-Protocol

`src/agentkit/state_backend/store/governance_hook_repository.py`:
- konkrete Implementierung (SQLite + Postgres) mit Tabelle `governance_hook_registrations`
- Schema-Versionierung Side-by-Side

#### 2.1.4 Tests

- Unit-Tests fuer `register_hooks`:
  - happy path: Registrierung aller 9 Hook-IDs
  - Idempotenz: doppelter Aufruf liefert `skipped`-Liste statt Fehler
  - Validation-Fehler bei unbekanntem `harness` oder unbekannter `hook_id`
- Unit-Tests fuer `deactivate_locks`:
  - happy path: Locks geloescht, Edge-Bundle entfernt
  - Missing Lock-Record: leeres Ergebnis ohne Fehler (Idempotenz)
  - IO-Fehler bei Edge-Bundle-Loeschung: in `errors[]`, nicht in raise
- Unit-Tests fuer `HookDefinition`, `RegistrationResult`, `DeactivationResult` (Pydantic-Modelle)
- Unit-Tests fuer `governance_hook_registrations`-Repository (SQLite + Postgres parametrisiert)
- Contract-Test `tests/contract/governance/test_top_surfaces.py`: beide Methoden mit Signaturen

### 2.2 Out of Scope

- Volles Principal-Capability-Modell (`governance-and-guards.A3`) — THEME-006 (AG3-032)
- Conflict-Freeze-Overlay (`A4`) — THEME-006
- Self-Protection-Guard (`A6`) — THEME-006 (AG3-033)
- Story-Creation-Guard (`A7`) — THEME-006 (AG3-033)
- Preflight-Checks 2, 5-10 (`B1`) — THEME-006 (AG3-034)
- IntegrityGate-8-Dimensionen (`B2`) — THEME-006 (AG3-034)
- Orchestrator-Guard (`B4`) — THEME-006
- CCAG-vor-Capability-Matrix Fix (`B5`) — THEME-006
- GovernanceObserver (`A1`) — explizit "spaetere Iteration"
- WorkerHealthMonitor (`A2`) — explizit "spaetere Iteration"
- IntegrityGate-Concept/Research-Drift (`C4`) — THEME-006
- Hook-Dispatch-Differenzierung (`C5`) — THEME-006
- Namensraum-Konsolidierung guard_system (`C1`) — wurde unter THEME-001 adressiert
- Cleanup `governance.monitoring`, `doc_fidelity`, `policies` (`C2/C3`) — THEME-001
- Tatsaechliches Schreiben von `.claude/settings.json`/`.codex/config.toml` durch register_hooks — bleibt im Installer; `register_hooks` liefert nur die Hook-Liste

## 3. Betroffene Dateien

| Datei | Aenderungsart | Beschreibung |
|---|---|---|
| `src/agentkit/governance/runner.py` | Modifiziert | `Governance.register_hooks`, `Governance.deactivate_locks` |
| `src/agentkit/governance/hook_registration.py` | Neu | `HookDefinition`, `HookId`, `HookHarness`, `RegistrationResult`, Errors |
| `src/agentkit/governance/locks.py` | Neu (oder Modifiziert) | `DeactivationResult`, `LockRecordId` |
| `src/agentkit/governance/repository.py` | Neu | `HookRegistrationRepository`-Protocol |
| `src/agentkit/state_backend/store/governance_hook_repository.py` | Neu | SQLite/Postgres-Implementierung |
| `src/agentkit/state_backend/store/lock_record_repository.py` | Modifiziert | `deactivate_locks_for_story(story_id)` Methode |
| `src/agentkit/state_backend/postgres_schema.sql` | Modifiziert | Tabelle `governance_hook_registrations` |
| `src/agentkit/state_backend/sqlite_store.py` | Modifiziert | analog SQLite |
| `src/agentkit/state_backend/config.py` | Modifiziert | SCHEMA_VERSION-Bump |
| `tests/unit/governance/test_register_hooks.py` | Neu | Registrierungs-Tests |
| `tests/unit/governance/test_deactivate_locks.py` | Neu | Lock-Deaktivierungs-Tests |
| `tests/unit/state_backend/store/test_governance_hook_repository.py` | Neu | parametrisiert SQLite + Postgres |
| `tests/contract/governance/test_top_surfaces.py` | Neu | Vertrags-Pinning |

## 4. Akzeptanzkriterien

1. **`Governance.register_hooks(hook_definitions: list[HookDefinition]) -> RegistrationResult`** ist als Methode der bestehenden `Governance`-Klasse verfuegbar.
2. **`HookDefinition`** ist Pydantic-Modell mit `hook_id`, `harness`, `command_template`, `event_pattern`. `hook_id` ist `HookId`-StrEnum mit allen 9 Pre-Hooks + `ccag`. `harness` ist `HookHarness` (`CLAUDE_CODE`, `CODEX`).
3. **`register_hooks` ist idempotent**: doppelte Registrierung gleicher `(harness, hook_id)`-Kombination liefert `skipped`-Eintrag, kein Fehler. Tests bestaetigen das.
4. **`Governance.deactivate_locks(story_id) -> DeactivationResult`** ist als Methode der bestehenden `Governance`-Klasse verfuegbar.
5. **`deactivate_locks` ist idempotent**: leerer Story-Lock-Stand liefert `DeactivationResult` mit leeren Listen, ohne Fehler.
6. **Fail-closed-Verhalten**: IO-Fehler bei Edge-Bundle-Loeschung landen in `errors[]`, werden nicht silent verschluckt; bei kritischen Fehlern (DB-Fehler) wird gehoben.
7. **Persistenz**: `governance_hook_registrations`-Tabelle in SQLite + Postgres. UNIQUE `(project_key, harness, hook_id)`.
8. **Architecture-Conformance**: `agentkit.governance` (ausser Repository-Modul) importiert nicht direkt aus state_backend.store-Fassaden.
9. **Pflichtbefehle gruen**: pytest unit + contract; mypy --strict; ruff clean; Coverage haelt 85%.

## 5. Definition of Done

- AK 1-9 erfuellt.
- `.venv\Scripts\python -m pytest tests/unit/governance tests/contract/governance -q` gruen.
- `mypy --strict` gruen, `ruff check src tests` gruen.
- SQLite + Postgres migriert.
- Aenderungen committed auf `main`.

## 6. Konzept-Referenzen (autoritativ)

- **FK-30 §30.3.1** — `register_hooks`
- **FK-30 §30.6.0** — `deactivate_locks`
- **`concept/_meta/bc-cut-decisions.md §BC 4`** — Governance-Top
- **FK-22 §22.7** — Lock-Record + Edge-Bundle
- **FK-29 §29.5** — Closure ruft `deactivate_locks`

## 7. Guardrail-Referenzen

- **FIX THE MODEL, NOT THE SYMPTOM**: Top-Surfaces, die Installer und Closure brauchen, endlich verfuegbar.
- **ZERO DEBT**: Idempotenz typisiert; keine "magic"-Re-Registrierung.
- **FAIL CLOSED**: IO-Fehler nicht verschluckt.

## 8. Hinweise fuer den Sub-Agent

- `Governance`-Klasse existiert bereits in `runner.py`. Methoden werden dort angesetzt.
- `LockRecordId` als NewType. Lock-Record-Repository existiert vermutlich teilweise — pruefe `state_backend/store/`-Verzeichnis.
- AK2 NICHT veraendern.
