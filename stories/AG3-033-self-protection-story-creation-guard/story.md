# AG3-033: Self-Protection-Guard + Story-Creation-Guard

**Typ:** Implementation
**Groesse:** M
**Abhaengigkeiten:** AG3-021 (Enums), AG3-031 (HookId-Enum), AG3-032 (PrincipalResolver fuer Self-Protection)
**Quell-Konzepte (autoritativ, in dieser Reihenfolge):**
- `FK-30 §30.5.4` (Self-Protection-Guard — immer aktiv, schuetzt Hook-Settings, CCAG-Symlinks, Lock-Records, governance-Verzeichnis)
- `FK-31 §31.5` (Story-Creation-Guard — blockiert direkte AK3-Story-Service-Mutationen am Skill vorbei)
- `FK-21 §21.13` (Story-Erstellungs-Guard PreToolUse-Hook)
- `DK-03 §3.3 Nachweis` (Governance-Selbstschutz)
- `concept/_meta/bc-cut-decisions.md §BC 4`

---

## 1. Kontext

THEME-006 aus `stories/_priorisierungsempfehlung.md`. Befunde:

- `governance-and-guards.A6`: Self-Protection-Guard fehlt — Hook-ID `self_protection_guard` ist in `PRE_HOOK_IDS` registriert, wird aber an `evaluate_pre_tool_use` weitergeleitet ohne eigene Guard-Logik. Schutz von Hook-Settings, CCAG-Symlinks, Lock-Records, governance-Verzeichnis fehlt.
- `governance-and-guards.A7`: Story-Creation-Guard fehlt — Hook-ID `story_creation_guard` in `PRE_HOOK_IDS`, aber keine Implementierung.
- `governance-and-guards.C5`: Hook-Dispatch pauschal auf `evaluate_pre_tool_use`. Mit dieser Story bekommen zwei Hooks eigene Module.

Mit AG3-032 (Principal-Capability-Modell) ist die Grundlage gelegt: Self-Protection arbeitet entlang `PathClass.PROTECTED_GOVERNANCE_LOCK`.

## 2. Scope

### 2.1 In Scope

#### 2.1.1 `SelfProtectionGuard` (FK-30 §30.5.4)

`src/agentkit/governance/guards/self_protection_guard.py`:

```python
class SelfProtectionGuard:
    """
    Schuetzt Hook-Settings, CCAG-Symlinks, Lock-Records und das
    governance-Verzeichnis vor jeder Mutation (FILE_WRITE/FILE_EDIT/SHELL_EXEC).
    Immer aktiv, unabhaengig vom Story-Modus.
    """
    def __init__(self, path_classifier: PathClassifier, op_classifier: OperationClassifier) -> None: ...

    def evaluate(self, event: HookEvent) -> GuardVerdict: ...
```

Implementation:
- `PathClass.PROTECTED_GOVERNANCE_LOCK` (eingefuehrt mit AG3-032) deckt: `.claude/settings.json`, `.codex/config.toml`, `.agentkit/governance/*`, `_temp/governance/*`, CCAG-Symlink-Targets
- `OperationClass in {FILE_WRITE, FILE_EDIT}` auf Protected-Pfade: hard DENY
- `OperationClass.SHELL_EXEC` mit `rm`/`del`/`mv` auf Protected-Pfade: DENY
- Whitelist: offizielle Servicepfade (AgentKit-CLI) duerfen schreiben (`agentkit register-project`, `agentkit verify-project`, `agentkit deactivate-locks`). Diese Whitelist nutzt den Principal-Resolver — Principal `INSTALLER`/`RECOVERY` duerfen schreiben; alle anderen DENY.

`GuardVerdict` ist Pydantic-Modell mit `decision: GuardDecision` (`ALLOW`/`DENY`), `reason`, `rule_id` (z.B. `FK-30 §30.5.4 a)`).

#### 2.1.2 `StoryCreationGuard` (FK-31 §31.5)

`src/agentkit/governance/guards/story_creation_guard.py`:

```python
class StoryCreationGuard:
    """
    Blockiert direkte AK3-Story-Service-Mutationen am Skill vorbei (FK-21 §21.13).
    Stories MUESSEN ueber den `create-userstory`-Skill angelegt werden, nicht
    durch direkte HTTP-POSTs an /v1/stories.
    """
    def __init__(self, principal_resolver: PrincipalResolver) -> None: ...

    def evaluate(self, event: HookEvent) -> GuardVerdict: ...
```

Implementation:
- Erkenne Story-Service-Mutationen: `OperationClass.SHELL_EXEC` mit `agentkit story create` ohne Skill-Markierung; oder `tool="HTTP" target=POST /v1/stories` ohne Skill-Header
- Wenn `Principal in {INSTALLER, RECOVERY}` und Servicepfad: ALLOW
- Wenn Skill-Markierung im Event-Kontext vorhanden (z.B. `cli_args` enthaelt `--via-skill=create-userstory`): ALLOW
- Sonst: DENY mit `reason="story_creation_must_go_through_create_userstory_skill"`

Der Skill-Marker ist ein Header/CLI-Arg, das der Skill setzen muss; das ist eine simple Konvention, kein neuer Mechanismus. Skill registriert sich; Marker-Validation ist Pflicht.

#### 2.1.3 Hook-Dispatch differenzieren (governance-and-guards.C5)

`src/agentkit/governance/runner.py:Governance.run_hook`:

Der heutige Pauschal-Dispatcher auf `evaluate_pre_tool_use` wird differenziert:

```python
def run_hook(self, hook_id: HookId, event: HookEvent, ...) -> GuardVerdict:
    # 1. Capability-Enforcement (aus AG3-032) zuerst
    cap_verdict = self._capability_enforcement.evaluate(event)
    if cap_verdict.decision == CapabilityDecision.DENY:
        return convert_to_guard_verdict(cap_verdict)

    # 2. Hook-spezifischer Dispatch
    if hook_id == HookId.SELF_PROTECTION_GUARD:
        return self._self_protection_guard.evaluate(event)
    if hook_id == HookId.STORY_CREATION_GUARD:
        return self._story_creation_guard.evaluate(event)
    # 3. weitere Guards (branch_guard, scope_guard, artifact_guard): bestehender Pfad
    return self._evaluate_pre_tool_use(event)
    # 4. CCAG am Ende
    ...
```

Andere Hooks (branch_guard, qa_artifact_guard, scope_guard) bleiben in dieser Story unveraendert; sie werden in Folge-Stories analog modularisiert.

#### 2.1.4 Tests

- Unit-Tests fuer `SelfProtectionGuard`:
  - Schreibversuch auf `.claude/settings.json` durch Worker -> DENY
  - Schreibversuch auf `.claude/settings.json` durch Installer-Principal -> ALLOW
  - SHELL_EXEC `rm .agentkit/governance/freeze.json` -> DENY
  - SHELL_EXEC `rm .agentkit/governance/freeze.json` aus CLI `agentkit recovery ...` -> ALLOW (Recovery-Principal)
- Unit-Tests fuer `StoryCreationGuard`:
  - HTTP-POST `/v1/stories` ohne Skill-Marker -> DENY
  - HTTP-POST `/v1/stories` mit Skill-Marker `create-userstory` -> ALLOW
  - `agentkit story create` durch Installer-Principal -> ALLOW
- Integration-Test fuer Hook-Dispatch: jedes Hook-ID landet beim richtigen Guard-Modul (Mock-Guards verifizieren Aufruf)
- Contract-Test `tests/contract/governance/test_guard_dispatch.py`: jeder Hook hat ein dediziertes Module-Mapping

### 2.2 Out of Scope

- IntegrityGate-Erweiterung (`B2`, `C4`) — AG3-034
- Preflight-Checks 2, 5-10 (`B1`) — AG3-034
- WorkerHealthMonitor (`A2`) — nicht in der Erst-Welle
- GovernanceObserver (`A1`) — nicht in der Erst-Welle
- Orchestrator-Guard-Vollausbau (`B4`) — Folge-Story
- Branch-Guard-Erweiterung, Scope-Guard-Erweiterung, Artifact-Guard-Erweiterung — bleiben unveraendert
- Hook-Skill-Usage-Check (`agent-skills.A9`) — Folge-Story der Skills-Welle
- Budget-Guard (Hook-ID existiert; Implementierung gehoert zu nachgelagerter Story)

## 3. Betroffene Dateien

| Datei | Aenderungsart | Beschreibung |
|---|---|---|
| `src/agentkit/governance/guards/self_protection_guard.py` | Neu | `SelfProtectionGuard` |
| `src/agentkit/governance/guards/story_creation_guard.py` | Neu | `StoryCreationGuard` |
| `src/agentkit/governance/guards/__init__.py` | Modifiziert | Re-Export der neuen Guards |
| `src/agentkit/governance/runner.py` | Modifiziert | Hook-Dispatch differenziert: SELF_PROTECTION_GUARD/STORY_CREATION_GUARD landen bei eigenen Modulen |
| `tests/unit/governance/guards/test_self_protection_guard.py` | Neu | Self-Protection-Tests |
| `tests/unit/governance/guards/test_story_creation_guard.py` | Neu | Story-Creation-Tests |
| `tests/integration/governance/test_hook_dispatch.py` | Neu | Dispatch-Integration |
| `tests/contract/governance/test_guard_dispatch.py` | Neu | Vertrags-Pinning |

## 4. Akzeptanzkriterien

1. **`SelfProtectionGuard` existiert** in `src/agentkit/governance/guards/self_protection_guard.py` mit Methode `evaluate(event) -> GuardVerdict`.
2. **Self-Protection schuetzt vier Pfadgruppen**: Hook-Settings (.claude/, .codex/), CCAG-Symlinks (.claude/skills/), Lock-Records (state_backend Lock-Tabellen), governance-Verzeichnis (`.agentkit/governance/`, `_temp/governance/`).
3. **Whitelist Self-Protection**: Operationen mit Principal `INSTALLER`/`RECOVERY` werden zugelassen; alle anderen geblockt.
4. **`StoryCreationGuard` existiert** in `src/agentkit/governance/guards/story_creation_guard.py`.
5. **Story-Creation-Guard erkennt drei Mutationen**: HTTP-POST `/v1/stories`, `agentkit story create` CLI, direkte DB-INSERTs (durch Pfad-Klassifikation auf Story-DB-Datei).
6. **Story-Creation-Guard Whitelist**: Skill-Marker (`--via-skill=create-userstory`) und Installer/Recovery-Principal.
7. **Hook-Dispatch in `Governance.run_hook` differenziert**: `SELF_PROTECTION_GUARD` und `STORY_CREATION_GUARD` werden an die neuen Module dispatcht, nicht mehr an `evaluate_pre_tool_use`.
8. **Capability-Enforcement laeuft vor Guards** (Verbindung zu AG3-032): wenn die Matrix bereits DENY sagt, kommen die Guards gar nicht erst zum Zuge.
9. **`GuardVerdict.rule_id`** verweist auf die jeweilige FK-Regel (`FK-30 §30.5.4` fuer Self-Protection, `FK-31 §31.5` fuer Story-Creation).
10. **Pflichtbefehle gruen**: pytest unit + integration + contract; mypy --strict; ruff clean; Coverage haelt 85%.

## 5. Definition of Done

- AK 1-10 erfuellt.
- `.venv\Scripts\python -m pytest tests/unit/governance/guards tests/integration/governance tests/contract/governance -q` gruen.
- `mypy --strict` gruen, `ruff check src tests` gruen.
- Aenderungen committed auf `main`.

## 6. Konzept-Referenzen (autoritativ)

- **FK-30 §30.5.4** — Self-Protection
- **FK-31 §31.5** — Story-Creation-Guard
- **FK-21 §21.13** — Story-Creation Hook-Pflicht
- **DK-03 §3.3** — Selbstschutz-Nachweis

## 7. Guardrail-Referenzen

- **FIX THE MODEL, NOT THE SYMPTOM**: zwei Hooks bekommen eigene Module — kein Pauschal-Dispatch mehr.
- **ZERO DEBT**: Hook-IDs sind nicht mehr nur Strings im Dispatcher.
- **FAIL CLOSED**: jeder Pfad ohne Whitelist-Match -> DENY.
- **NO ERROR BYPASSING**: Self-Protection laesst keine Mutationen am Hook-Settings vorbei, ausser Servicepfad-Whitelist.

## 8. Hinweise fuer den Sub-Agent

- Skill-Marker-Konvention: keine bestehende Konvention; lege sie pragmatisch fest (CLI-Arg `--via-skill=...` oder HTTP-Header `X-Skill: ...`). Dokumentiere im Story-Creation-Guard-Modul-Docstring.
- AK2 NICHT veraendern.
