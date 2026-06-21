# AG3-032: Principal-Capability-Modell (FK-55) — Principal, PathClass, OperationClass, Matrix, Freeze-Overlay

**Typ:** Implementation
**Groesse:** L
**Abhaengigkeiten:** AG3-021 (Enums)
**Quell-Konzepte (autoritativ, in dieser Reihenfolge):**
- `FK-55 §55.3` (9 kanonische Principals)
- `FK-55 §55.3a` (kein Principal aus Prompt-Inhalt)
- `FK-55 §55.4` (8 Pfadklassen)
- `FK-55 §55.5` (6 Operationsklassen)
- `FK-55 §55.6` (harte Capability-Matrix)
- `FK-55 §55.8` (Conflict-Freeze-Overlay)
- `FK-55 §55.10.3` (10-Schritt-Auswertungsreihenfolge: Principal -> PathClass -> Matrix -> Freeze -> ... -> CCAG)
- `FK-31 §31.2.7` (Freeze-Overlay-Materialisierung)
- `formal.principal-capabilities.*`
- `DK-03 §3` (Governance-Domaene)

---

## 1. Kontext

THEME-006 aus `stories/_priorisierungsempfehlung.md`. Befund `governance-and-guards.A3/A4/B5/C5`: Capability-Enforcement-Pipeline nach FK-55 §55.10.3 ist nicht implementiert. `evaluate_pre_tool_use` kennt nur `principal_kind` (main/subagent), nicht die 9 typisierten Principals. Conflict-Freeze-Overlay fehlt. CCAG laeuft vor der harten Capability-Matrix.

Diese Story liefert das **Datenmodell + Enforcement-Pipeline-Gerust**. Konkrete Guards (Self-Protection, Story-Creation) sind AG3-033; Preflight-Erweiterung und IntegrityGate-Erweiterung sind AG3-034.

## 2. Scope

### 2.1 In Scope

#### 2.1.1 Datenmodelle (FK-55 §55.3-55.5)

Neues Modul `src/agentkit/governance/principal_capabilities/`:

- `principals.py`:
  - `Principal` StrEnum mit den 9 kanonischen Werten aus FK-55 §55.3 (z.B. `MAIN_ORCHESTRATOR`, `IMPLEMENTATION_WORKER`, `BUGFIX_WORKER`, `REMEDIATION_WORKER`, `ADVERSARIAL_WORKER`, `QA_LLM_READER`, `OPERATOR`, `INSTALLER`, `RECOVERY`) — exakte Werte aus FK-55 §55.3 abgleichen
  - `PrincipalResolver`-Klasse, die aus dem Harness-Event-Kontext deterministisch den Principal ermittelt (nie aus Prompt-Inhalt; nur aus `session_id`, `cwd`, `parent_session_id`, `cli_args` etc.)

- `paths.py`:
  - `PathClass` StrEnum mit 8 Werten aus FK-55 §55.4 (z.B. `PROTECTED_QA_ARTIFACT`, `PROTECTED_GOVERNANCE_LOCK`, `PROTECTED_CONTENT_PLANE`, `STORY_BRANCH_WORKSPACE`, `MAIN_BRANCH_PROTECTED`, `READ_ONLY_PROJECT`, `EPHEMERAL_TEMP`, `UNCLASSIFIED`)
  - `PathClassifier`-Klasse: `classify(path: Path, project_root: Path, story_id: str | None) -> PathClass`
  - Klassifikation ist deterministisch (Regex-Pattern + Path-Prefix-Matching). Wenn keine Regel matched: `UNCLASSIFIED`.

- `operations.py`:
  - `OperationClass` StrEnum mit 6 Werten aus FK-55 §55.5 (z.B. `FILE_WRITE`, `FILE_EDIT`, `FILE_READ`, `GIT_WRITE`, `BRANCH_MUTATE`, `SHELL_EXEC`)
  - `OperationClassifier.classify(operation_name: str, args: dict) -> OperationClass`: Mapping z.B. `tool="Write"` -> `FILE_WRITE`, `tool="Edit"` -> `FILE_EDIT`, `tool="Bash" cmd="git push --force"` -> `GIT_WRITE`.

#### 2.1.2 Capability-Matrix (FK-55 §55.6)

`src/agentkit/governance/principal_capabilities/matrix.py`:

```python
class CapabilityMatrix:
    """Harte Matrix: Welcher Principal darf welche OperationClass auf welcher PathClass?"""

    def is_allowed(self, principal: Principal, op_class: OperationClass, path_class: PathClass) -> CapabilityVerdict: ...

class CapabilityVerdict(BaseModel):
    decision: CapabilityDecision  # ALLOW | DENY
    reason: str                   # menschenlesbarer Grund
    rule_id: str | None           # Referenz auf FK-55-Regel
```

`CapabilityDecision` StrEnum: `ALLOW`, `DENY`.

Die Matrix-Werte werden aus FK-55 §55.6 (Tabelle) als Python-Dict (`dict[tuple[Principal, OperationClass, PathClass], CapabilityVerdict]`) materialisiert. Vollstaendig. Wenn ein Tripel nicht in der Matrix ist: fail-closed `DENY` mit Verweis "tripel_not_in_matrix".

Default-Initialisierung: Matrix wird aus einem Konstanten-Modul `matrix_data.py` geladen, das die FK-55-§55.6-Tabelle 1:1 abbildet.

#### 2.1.3 Conflict-Freeze-Overlay (FK-55 §55.8, FK-31 §31.2.7)

`src/agentkit/governance/principal_capabilities/freeze.py`:

```python
class ConflictFreezeOverlay:
    """
    Wenn eine Story in Konflikt-Freeze ist (z.B. nach Hard-Stop),
    werden Orchestrator-Mutationen und Worker-Schreibvorgaenge zusaetzlich
    gesperrt, unabhaengig von der Matrix-Default-Entscheidung.
    """

    def is_frozen(self, story_id: str) -> bool: ...
    def apply(self, base_verdict: CapabilityVerdict, story_id: str, op_class: OperationClass) -> CapabilityVerdict: ...
```

Persistenz: Tabelle `governance_freeze_records` mit `story_id`, `frozen_at`, `freeze_reason`, `freeze_version`. Doppelt materialisiert: State-Backend (Wahrheit) **und** lokaler Export unter `.agentkit/governance/freeze.json` (FK-31 §31.2.7).

Schema-Versionierung Side-by-Side (AG3-005).

#### 2.1.4 Enforcement-Pipeline (FK-55 §55.10.3)

`src/agentkit/governance/principal_capabilities/enforcement.py`:

```python
class CapabilityEnforcement:
    def __init__(
        self,
        principal_resolver: PrincipalResolver,
        path_classifier: PathClassifier,
        op_classifier: OperationClassifier,
        matrix: CapabilityMatrix,
        freeze: ConflictFreezeOverlay,
    ) -> None: ...

    def evaluate(self, event: HookEvent) -> CapabilityVerdict:
        # Schritte gemaess FK-55 §55.10.3:
        # 1. Principal aufloesen (PrincipalResolver)
        # 2. OperationClass aufloesen
        # 3. PathClass aufloesen
        # 4. Harte Matrix konsultieren
        # 5. Freeze-Overlay anwenden
        # 6. (offizielle Servicepfade, Modusregel — Folgestory)
        # 7. CCAG nur wenn alle vorherigen ALLOW (auch FK-30 §30.2.6)
        ...
```

Das Resultat wird in den existierenden `Governance.run_hook`-Pfad eingehaengt: BEVOR `evaluate_pre_tool_use` (legacy) -> `evaluate_ccag` laeuft, wird `CapabilityEnforcement.evaluate` aufgerufen. Bei `DENY`: harte Ablehnung, kein CCAG-Fallback (`governance-and-guards.B5`).

Schritte 6 (Servicepfade, Modusregel) bleiben in dieser Story bewusst rudimentaer; vollstaendiger Einbau gehoert zu Folge-Stories rund um Fast-Modus und Skill-Pfade.

#### 2.1.5 Hook-Event-Erweiterung

Das existing `HookEvent` (`src/agentkit/governance/guard_evaluation.py`) wird um Felder ergaenzt, die fuer `PrincipalResolver` noetig sind: `parent_session_id`, `cli_args: list[str] | None`. Wo fehlend wird `None` belegt; die Resolver-Logik klassifiziert dann ggf. nach Default-Principal.

#### 2.1.6 Tests

- Unit-Tests fuer `Principal`-StrEnum (9 Werte)
- Unit-Tests fuer `PrincipalResolver` (alle 9 Principals deterministisch aufloesbar; kein Lookup im Prompt-Inhalt — `FK-55 §55.3a`)
- Unit-Tests fuer `PathClassifier` (alle 8 PathClass-Werte erreichbar)
- Unit-Tests fuer `OperationClassifier` (alle 6 OperationClass-Werte erreichbar)
- Unit-Tests fuer `CapabilityMatrix` (Matrix vollstaendig; jedes Principal/OpClass/PathClass-Tripel hat einen Eintrag; default DENY bei fehlendem Eintrag)
- Unit-Tests fuer `ConflictFreezeOverlay` (freeze setzen, lesen, apply uebersteuert ALLOW zu DENY)
- Unit-Tests fuer `CapabilityEnforcement.evaluate`:
  - happy path: Worker schreibt in Story-Branch-Workspace -> ALLOW
  - fail-closed: Worker schreibt in Protected-QA-Artifact -> DENY
  - Freeze uebersteuert ALLOW
- Integration-Test: `Governance.run_hook` ruft `CapabilityEnforcement.evaluate` VOR CCAG; CCAG wird bei DENY nicht aufgerufen
- Contract-Test `tests/contract/governance/test_capability_matrix.py`: alle Matrix-Eintraege aus FK-55 §55.6 sind als Konstanten enthalten

### 2.2 Out of Scope

- Self-Protection-Guard und Story-Creation-Guard (`governance-and-guards.A6/A7`) — AG3-033
- IntegrityGate-8-Dimensionen (`B2`) — AG3-034
- Preflight-Checks 2, 5-10 (`B1`) — AG3-034
- Modus-Ermittlung (`B3`) — AG3-018 (Fast-Modus) bzw. THEME-009
- Orchestrator-Guard-Vollausbau (`B4`) — Folge-Story nach AG3-033
- IntegrityGate-Concept/Research-Drift (`C4`) — AG3-034
- Hook-Dispatch-Differenzierung (`C5`) — AG3-034 (in IntegrityGate-Story fokussiert)
- WorkerHealthMonitor (`A2`) — bewusst nicht in der Erst-Welle
- GovernanceObserver (`A1`) — bewusst nicht in der Erst-Welle
- Schritt 6 der Auswertungsreihenfolge (Servicepfade, Modusregel) — Folge-Story rund um Fast-Modus
- HookEvent-Komplettueberarbeitung (Felder, Harness-Adapter) — nur die fuer Principal-Resolution noetigen Felder werden ergaenzt; volle Harmonisierung mit Codex/Claude-Adaptern ist separate Adapter-Story

## 3. Betroffene Dateien

| Datei | Aenderungsart | Beschreibung |
|---|---|---|
| `src/agentkit/governance/principal_capabilities/__init__.py` | Neu | Re-Export |
| `src/agentkit/governance/principal_capabilities/principals.py` | Neu | `Principal`, `PrincipalResolver` |
| `src/agentkit/governance/principal_capabilities/paths.py` | Neu | `PathClass`, `PathClassifier` |
| `src/agentkit/governance/principal_capabilities/operations.py` | Neu | `OperationClass`, `OperationClassifier` |
| `src/agentkit/governance/principal_capabilities/matrix.py` | Neu | `CapabilityMatrix`, `CapabilityVerdict`, `CapabilityDecision` |
| `src/agentkit/governance/principal_capabilities/matrix_data.py` | Neu | FK-55-§55.6-Tabelle als Konstante |
| `src/agentkit/governance/principal_capabilities/freeze.py` | Neu | `ConflictFreezeOverlay` |
| `src/agentkit/governance/principal_capabilities/enforcement.py` | Neu | `CapabilityEnforcement` |
| `src/agentkit/governance/principal_capabilities/errors.py` | Neu | Exceptions |
| `src/agentkit/governance/guard_evaluation.py` | Modifiziert | HookEvent um `parent_session_id`, `cli_args` ergaenzt |
| `src/agentkit/governance/runner.py` | Modifiziert | `Governance.run_hook` ruft `CapabilityEnforcement.evaluate` vor CCAG |
| `src/agentkit/state_backend/store/freeze_repository.py` | Neu | `governance_freeze_records`-Repository |
| `src/agentkit/state_backend/postgres_schema.sql` | Modifiziert | Tabelle `governance_freeze_records` |
| `src/agentkit/state_backend/sqlite_store.py` | Modifiziert | analog SQLite |
| `src/agentkit/state_backend/config.py` | Modifiziert | SCHEMA_VERSION-Bump |
| `tests/unit/governance/principal_capabilities/...` | Neu | Vollabdeckung der Module |
| `tests/integration/governance/test_capability_pipeline.py` | Neu | Enforcement-Pipeline End-to-End |
| `tests/contract/governance/test_capability_matrix.py` | Neu | Matrix-Pinning |

## 4. Akzeptanzkriterien

1. **Paket `src/agentkit/governance/principal_capabilities/` existiert** und exportiert `Principal`, `PathClass`, `OperationClass`, `CapabilityMatrix`, `CapabilityVerdict`, `CapabilityDecision`, `ConflictFreezeOverlay`, `CapabilityEnforcement`.
2. **`Principal` enthaelt 9 Werte** gemaess FK-55 §55.3.
3. **`PathClass` enthaelt 8 Werte**, `OperationClass` enthaelt 6 Werte gemaess FK-55 §55.4/55.5.
4. **`PrincipalResolver` liest niemals aus Prompt-Inhalt** (FK-55 §55.3a) — Tests verifizieren das via Negativtest: ein Event mit "ich-bin-orchestrator" im Prompt-Body wird trotzdem als Worker klassifiziert, wenn der `session_id`/`parent_session_id`-Kontext das vorgibt.
5. **`CapabilityMatrix` ist vollstaendig**: jedes `(Principal, OperationClass, PathClass)`-Tripel hat entweder einen expliziten Eintrag oder default DENY. Contract-Test enthaelt mindestens die zentralen Matrix-Zeilen aus FK-55 §55.6 (siehe Test-Pinning-Liste in `tests/contract/governance/test_capability_matrix.py`).
6. **`ConflictFreezeOverlay` persistiert doppelt**: State-Backend (Tabelle `governance_freeze_records`) + lokaler Export `.agentkit/governance/freeze.json`. Tests verifizieren beide Pfade.
7. **`CapabilityEnforcement.evaluate` durchlaeuft Schritte 1-5 von FK-55 §55.10.3** in der konzept-normierten Reihenfolge. Bei DENY in einem der Schritte wird CCAG nicht mehr aufgerufen — Test mit Mock-CCAG bestaetigt das.
8. **`Governance.run_hook` ruft `CapabilityEnforcement.evaluate` vor CCAG** (governance-and-guards.B5 Fix).
9. **Fail-closed**: unbekannte Principals/PathClasses/OperationClasses oder fehlende Matrix-Eintraege -> DENY mit klarem `reason`.
10. **Architecture-Conformance**: `principal_capabilities`-Paket importiert nur `agentkit.backend.core_types`, `agentkit.backend.governance.guard_evaluation` (HookEvent); nicht aus state_backend.store-Fassaden ausserhalb Repository.
11. **Pflichtbefehle gruen**: pytest unit + integration + contract; mypy --strict; ruff clean; Coverage haelt 85%.

## 5. Definition of Done

- AK 1-11 erfuellt.
- `.venv\Scripts\python -m pytest tests/unit/governance/principal_capabilities tests/integration/governance tests/contract/governance -q` gruen.
- `mypy --strict` gruen, `ruff check src tests` gruen.
- SQLite + Postgres migriert.
- Aenderungen committed auf `main`.

## 6. Konzept-Referenzen (autoritativ)

- **FK-55 §55.3** — 9 Principals
- **FK-55 §55.3a** — kein Principal aus Prompt
- **FK-55 §55.4** — 8 PathClasses
- **FK-55 §55.5** — 6 OperationClasses
- **FK-55 §55.6** — harte Matrix
- **FK-55 §55.8** — Conflict-Freeze
- **FK-55 §55.10.3** — Auswertungsreihenfolge
- **FK-31 §31.2.7** — Freeze-Overlay-Materialisierung
- **`formal.principal-capabilities.*`** — formale Spec

## 7. Guardrail-Referenzen

- **FIX THE MODEL, NOT THE SYMPTOM**: Trust-Boundary wird typsicher; keine String-Principals mehr.
- **ZERO DEBT**: Matrix vollstaendig; nicht "spaeter Matrix erweitern".
- **FAIL CLOSED**: jedes unbekannte Tripel -> DENY.
- **SINGLE SOURCE OF TRUTH**: Matrix-Daten in `matrix_data.py`; nicht ueber Code verstreut.
- **NO ERROR BYPASSING**: CCAG kann harte DENY nicht aufweichen.

## 8. Hinweise fuer den Sub-Agent

- Die FK-55-§55.6-Tabelle ist der Schluessel: tippt sie vollstaendig in `matrix_data.py` ab. Wenn unsicher: lies FK-55 §55.6 nochmal — keine Eigeninterpretation.
- `PrincipalResolver`: pruefe die existing `principal_kind` (main/subagent)-Heuristik in `guard_evaluation.py` — die ist ein primitiver Ersatz und wird hier ersetzt.
- Lokaler Freeze-Export: `.agentkit/governance/freeze.json` — Pfad in `governance/protected_paths.py` (AG3-023) eintragen.
- AK2 NICHT veraendern.
