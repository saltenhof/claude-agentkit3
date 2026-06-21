# AG3-036: Harness-Telemetrie-Hooks + JSONL-Audit-Bundle

**Typ:** Implementation
**Groesse:** L
**Abhaengigkeiten:** AG3-021 (Enums), AG3-022 (Envelope fuer Hook-Records), AG3-035 (ProjectionAccessor)
**Quell-Konzepte (autoritativ, in dieser Reihenfolge):**
- `FK-68 §68.3.1` (Harness-Hooks als Referenz-Implementierung)
- `FK-68 §68.2.2` (Review-Divergenz Event-Tabelle)
- `FK-68 §68.6` (BudgetEventEmitter, nur Research-Stories)
- `FK-68 §68.3.6` (JSONL-Audit-Bundle-Export bei Closure)
- `FK-68 §68.2.1` (audit-bundle Glossar)
- `DK-05` (Telemetrie-Domaene)

---

## 1. Kontext

THEME-007 aus `stories/_priorisierungsempfehlung.md`. Befunde aus `telemetry-and-events`-GAP-Analyse:

- `telemetry-and-events.A1`: Harness-Hooks fehlen als vollstaendige Referenz-Implementierung. Kein Modul `agentkit.backend.telemetry.hooks.*`. Hook-Namen sind nur als String-Referenz im governance-runner vermerkt.
- `telemetry-and-events.A2`: DivergenceHook fehlt. `review_divergence`-EventType existiert in events.py, wird aber nicht emittiert.
- `telemetry-and-events.A4`: JSONL-Audit-Bundle-Export bei Closure fehlt — keine `export_jsonl`-Funktion.

Diese Story implementiert **sieben Hooks + Audit-Bundle-Export**.

## 2. Scope

### 2.1 In Scope

#### 2.1.1 Hook-Sub `src/agentkit/telemetry/hooks/`

Neue Modul-Struktur:

- `__init__.py` — Re-Export
- `base.py` — `TelemetryHook` Protocol/Basisklasse, `HookContext`, `HookResult`
- `agent_lifecycle_hook.py` — `AgentLifecycleHook` (agent_start, agent_end)
- `commit_hook.py` — `CommitHook` (increment_commit)
- `review_sentinel_hook.py` — `ReviewSentinelHook` (review_request, review_response, review_compliant)
- `review_guard.py` — `ReviewGuard` (Pflicht-Reviewer-Coverage)
- `budget_event_emitter.py` — `BudgetEventEmitter` (nur Research-Stories)
- `drift_check_hook.py` — `DriftCheckHook` (drift_check events)
- `divergence_hook.py` — `DivergenceHook` (review_divergence)

Jeder Hook hat:
- `evaluate(event: HookEvent) -> HookResult` — entscheidet, ob ein Telemetry-Event zu emittieren ist
- `emit(record: ExecutionEventRecord) -> None` — schreibt via existing `StateBackendEmitter` und ggf. `ProjectionAccessor`

#### 2.1.2 `AgentLifecycleHook`

Erzeugt `agent_start`/`agent_end`-Events pro Worker-Spawn:
- Trigger: PreToolUse (Spawn), PostSession (End)
- Pflicht-Felder: `worker_id`, `principal`, `story_id`, `run_id`, `started_at`/`ended_at`, `outcome`
- Persistenz via `Telemetry.StateBackendEmitter` (existing)

#### 2.1.3 `CommitHook`

Erzeugt `increment_commit`-Events bei jedem Worker-Commit:
- Trigger: PostToolUse mit `tool="Bash"`, `cmd matches "git commit"`
- Pflicht-Felder: `commit_sha`, `repo_name`, `story_id`, `worker_id`, `files_changed`
- Drift-Check-Hook (siehe 2.1.7) wird ggf. ausgeloest

#### 2.1.4 `ReviewSentinelHook`

Erzeugt drei Event-Typen fuer Worker-Reviews:
- `review_request`: Worker fragt LLM-Review an
- `review_response`: LLM antwortet
- `review_compliant`: Worker quittiert Review-Beruecksichtigung

Pflicht-Felder pro Event: `reviewer_role`, `review_round`, `template_name`, `verdict` (bei response)

#### 2.1.5 `ReviewGuard`

Stellt sicher, dass alle Pflicht-Reviewer-Rollen pro Worker-Inkrement abgedeckt sind (Voraussetzung fuer Integrity-Gate Dim 5):
- Liest `pipeline_config.review.required_roles`
- Bei PreToolUse `tool="Bash" cmd="git commit"`: prueft `review_compliant`-Events fuer alle required_roles seit letztem Commit
- Bei Verstoss: GuardVerdict.DENY mit `reason="review_not_compliant: missing roles ..."`

ReviewGuard ist sowohl Hook (emit Telemetry-Event `review_guard_intervention`) als auch Guard (returns GuardVerdict). Doppelrolle ist konzeptkonform (FK-68 §68.3.1).

#### 2.1.6 `BudgetEventEmitter`

Nur fuer Research-Stories (`story_type=research`):
- Trigger: PreToolUse `tool="WebFetch"` oder `tool="WebSearch"`
- Erzeugt `web_call_attempted`-Event mit Cost-Schaetzung
- Wenn Story-Budget ueberschritten: GuardVerdict.DENY

#### 2.1.7 `DriftCheckHook`

Trigger: PostToolUse mit Increment-Commit:
- Berechnet Diff gegen Entwurfsartefakt (`_temp/qa/{story_id}/entwurfsartefakt.json`, FK-23 §23.4.3)
- Bei signifikanter Abweichung: `drift_check`-Event mit `drift_detected=true`
- Folge-Aktion (Eskalation) ist nicht hier; nur Event-Emission

#### 2.1.8 `DivergenceHook`

Trigger: nach Layer-2 `review_response`-Events:
- Erkennt Verdikt-Divergenz zwischen Reviewern (z.B. 2 PASS, 1 FAIL)
- Emit `review_divergence`-Event (EventType existiert bereits in `events.py`)
- Folge-Aktion (dritter Reviewer) ist Inhalt von THEME-009 (`verify-system.A9`); nur Event-Emission hier

#### 2.1.9 JSONL-Audit-Bundle (FK-68 §68.3.6)

Neues Modul `src/agentkit/telemetry/audit_bundle.py`:

```python
class AuditBundleExporter:
    def __init__(self, projection_accessor: ProjectionAccessor, event_store: StateBackendEmitter) -> None: ...

    def export(self, story_id: str, run_id: str, output_dir: Path) -> AuditBundle:
        """
        Exportiert alle Telemetry-Events + Projektionen einer Story
        als JSONL-Dateien. Nur fuer abgeschlossene Stories (nicht zurueckgesetzte).
        """
        ...
```

Output-Struktur:
- `events.jsonl` — alle ExecutionEventRecord-Eintraege (FK-68 §68.3.6)
- `qa_stage_results.jsonl`
- `qa_findings.jsonl`
- `story_metrics.json` (single record)
- `phase_states.jsonl`
- `manifest.json` (Inhaltsverzeichnis + Hashes)

Aufruf erfolgt aus Closure-Phase (nicht in dieser Story; Closure-Vollausbau ist nicht in der Erst-Welle). Diese Story stellt `AuditBundleExporter` bereit, mit oeffentlicher API; Aufrufer kommt spaeter.

#### 2.1.10 Tests

- Unit-Tests pro Hook (Trigger-Bedingung, Event-Emission, Pflicht-Felder)
- Unit-Test `ReviewGuard` mit fehlenden Rollen -> DENY
- Unit-Test `BudgetEventEmitter` mit Story-Typ research/non-research
- Unit-Test `DriftCheckHook` mit/ohne Drift
- Unit-Test `DivergenceHook` mit/ohne Divergenz
- Unit-Test `AuditBundleExporter`: JSONL-Roundtrip + Manifest-Hash-Pflicht
- Integration-Test: ein simulierter Worker-Lauf erzeugt die erwarteten Events; `AuditBundleExporter.export` produziert die sechs Dateien

### 2.2 Out of Scope

- TelemetryContract (`B1`) — AG3-037
- Preflight-Telemetrie-Stream (`B2`) — AG3-037
- NormalizedEvent-Risk-Window (`A3`) — AG3-037
- Workflow-Metriken-Felder Vollausbau (`B3`) — Folge-Story
- SSE-Topic-Mapping-Korrektur (`B5`) — Folge-Story
- TelemetryService-Schreibgrenze (`C1`) — Folge-Story
- compute_pipeline_metrics-qa_rounds-Bug (`C2`) — Folge-Story
- exploration-and-design Telemetrie-Events (`exploration-and-design.A7`) — AG3-046 (Exploration-Story der Welle)
- WorkerHealth-Events (`implementation-phase.B3`) — bewusst nicht in der Erst-Welle (WorkerHealthMonitor ist nicht in der Erst-Welle)
- Planning-Events (`execution-planning.A10`) — nicht in der Erst-Welle (execution-planning ist orthogonal)
- ARE-Events (`requirements-and-scope-coverage.A8`) — kommt mit ARE-Vollausbau
- fc_*-Events (`failure-corpus.A6`) — kommt mit fc-Vollausbau
- Aufruf des `AuditBundleExporter` aus der Closure-Phase — Folge-Story
- DriftCheckHook-Eskalationslogik (Selbstkorrektur, BLOCKED) — THEME-009 (Worker-Loop)

## 3. Betroffene Dateien

| Datei | Aenderungsart | Beschreibung |
|---|---|---|
| `src/agentkit/telemetry/hooks/__init__.py` | Neu | Re-Export |
| `src/agentkit/telemetry/hooks/base.py` | Neu | Hook-Basis |
| `src/agentkit/telemetry/hooks/agent_lifecycle_hook.py` | Neu | |
| `src/agentkit/telemetry/hooks/commit_hook.py` | Neu | |
| `src/agentkit/telemetry/hooks/review_sentinel_hook.py` | Neu | |
| `src/agentkit/telemetry/hooks/review_guard.py` | Neu | Doppelrolle Hook+Guard |
| `src/agentkit/telemetry/hooks/budget_event_emitter.py` | Neu | |
| `src/agentkit/telemetry/hooks/drift_check_hook.py` | Neu | |
| `src/agentkit/telemetry/hooks/divergence_hook.py` | Neu | |
| `src/agentkit/telemetry/audit_bundle.py` | Neu | `AuditBundleExporter` |
| `src/agentkit/governance/runner.py` | Modifiziert | ReviewGuard wird in Hook-Dispatch eingebunden |
| `tests/unit/telemetry/hooks/...` | Neu | Pro Hook |
| `tests/unit/telemetry/test_audit_bundle.py` | Neu | Export |
| `tests/integration/telemetry/test_worker_lifecycle.py` | Neu | End-to-end |

## 4. Akzeptanzkriterien

1. **Hook-Paket existiert** unter `src/agentkit/telemetry/hooks/` mit allen sieben Hook-Modulen plus `base.py`.
2. **`AgentLifecycleHook` emittiert `agent_start`/`agent_end`** mit den Pflicht-Feldern (`worker_id`, `principal`, `story_id`, `run_id`, `started_at`/`ended_at`, `outcome`).
3. **`CommitHook` emittiert `increment_commit`** bei `git commit`-Bash-Aufruf mit `commit_sha`, `repo_name`, `story_id`, `worker_id`, `files_changed`.
4. **`ReviewSentinelHook`** emittiert `review_request`, `review_response`, `review_compliant` mit `reviewer_role`, `review_round`, `template_name`, `verdict`.
5. **`ReviewGuard`** liefert DENY bei fehlenden Pflicht-Reviewern. Tests verifizieren das.
6. **`BudgetEventEmitter`** ist nur fuer research-Stories aktiv; emittiert `web_call_attempted` bei WebFetch/WebSearch; bei Budget-Ueberschreitung -> DENY.
7. **`DriftCheckHook`** emittiert `drift_check` mit `drift_detected: bool` nach Increment-Commits.
8. **`DivergenceHook`** emittiert `review_divergence` bei verschiedenen Verdikten.
9. **`AuditBundleExporter.export(story_id, run_id, output_dir)`** produziert sechs JSONL/JSON-Dateien plus `manifest.json` mit Hashes. Roundtrip: gelesen liefert genau die geschriebenen Datensaetze.
10. **Architecture-Conformance**: Hooks importieren aus dem governance-BC ausschliesslich aus `agentkit.backend.governance.protocols` (der kanonische Heimatort von `GuardVerdict`/`ViolationType`) — zusaetzlich aus `agentkit.backend.core_types` und `agentkit.backend.telemetry`. Die Hooks reagieren auf einen **self-contained `HookContext`** (`telemetry.hooks.base`), nicht auf `guard_evaluation.HookEvent`. Begruendung (AG3-036 FIX-4): der self-contained Context haelt die Hooks frei von config-/story-context-/installer-Importen (werte wie `story_type`, `required_roles`, `web_call_limit` werden als plain values injiziert), und `GuardVerdict` wird aus seinem kanonischen Heimatort `protocols` bezogen — kein Re-Export-Shim allein zur Erfuellung alter Formulierung. Kein Import von config/story-context/installer/`guard_evaluation` im Hook-Paket.
11. **Pflichtbefehle gruen**: pytest unit + integration; mypy --strict; ruff clean; Coverage haelt 85%.

## 5. Definition of Done

- AK 1-11 erfuellt.
- `.venv\Scripts\python -m pytest tests/unit/telemetry/hooks tests/unit/telemetry/test_audit_bundle tests/integration/telemetry -q` gruen.
- `mypy --strict` gruen, `ruff check src tests` gruen.
- Aenderungen committed auf `main`.

## 6. Konzept-Referenzen (autoritativ)

- **FK-68 §68.3.1** — Harness-Hooks Referenz
- **FK-68 §68.2.2** — review_divergence
- **FK-68 §68.6** — BudgetEventEmitter
- **FK-68 §68.3.6** — Audit-Bundle
- **FK-68 §68.2.1** — audit-bundle Glossar
- **DK-05** — Telemetrie-Domaene

## 7. Guardrail-Referenzen

- **FIX THE MODEL, NOT THE SYMPTOM**: Hooks endlich implementiert, nicht nur als String-Referenz.
- **ZERO DEBT**: sieben Hooks vollstaendig; keine "spaeter erweitern"-Hinweise.
- **FAIL CLOSED**: ReviewGuard DENY, BudgetEventEmitter DENY bei Ueberschreitung.

## 8. Hinweise fuer den Sub-Agent

- Worker-Lifecycle: `agent_start`/`agent_end`-Trigger sind harness-spezifisch — Claude Code emittiert PreToolUse mit speziellem `Task` tool; Codex hat parallel-Workflow. Pruefe harness_adapters/.
- Drift-Check braucht das Entwurfsartefakt — falls THEME-010 (Exploration) noch nicht fertig ist, faellt der DriftCheckHook fail-closed mit `drift_detected=false, reason="no_design_artifact"` (kein silent Pass).
- AK2 NICHT veraendern.
