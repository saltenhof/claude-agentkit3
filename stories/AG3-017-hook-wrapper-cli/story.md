# AG3-017: Harness-Hook-Wrapper-CLI

**Typ:** Implementation
**Groesse:** M
**Abhaengigkeiten:** keine (AG3-004 hat den Codex-Adapter geliefert; Wrapper kann darauf aufsetzen)
**Quell-Konzept:** FK-30 §30.3.1 (Hook-Registrierung), FK-30 §30.11 (Multi-Harness)

---

## Kontext

FK-30 §30.3.1 zeigt logische Hook-Identifikatoren in der Settings-Datei
(z. B. `agentkit-hook-claude pre branch_guard`). Die Konzept-Linie:
der harness-spezifische Wrapper liest stdin im Harness-Format, normalisiert
ueber den Adapter (FK-30 §30.11.3) auf `HookEvent` und ruft dann die
harness-neutrale `Governance.run_hook(hook_id, event)`-Top-Surface.

Der AK3-Code hat:
- `src/agentkit/governance/harness_adapters/claude_code.py`
- `src/agentkit/governance/harness_adapters/codex/cli.py` +
  `decision_mapping.py` + `event_mapping.py`
- `src/agentkit/governance/guard_evaluation.py` (A-Kern)
- Guards unter `src/agentkit/governance/guards/`
  (branch_guard, scope_guard, artifact_guard)
- `src/agentkit/governance/integrity_gate/`

Was fehlt:
- Einheitlicher CLI-Wrapper `agentkit-hook-claude` und `agentkit-hook-codex`
  als Setuptools-Entry-Point
- Hook-Identifikator-Dispatcher (`pre branch_guard`, `pre orchestrator_guard`,
  `post telemetry`, etc.)
- Top-Surface `Governance.run_hook(hook_id, event)` als harness-neutrale
  Eingangsstelle

## Scope

### In Scope

- Setuptools-Entry-Points in `pyproject.toml`:
  - `agentkit-hook-claude = agentkit.harness_client.harness_adapters.claude_code.cli:main`
  - `agentkit-hook-codex = agentkit.harness_client.harness_adapters.codex.cli:main`
- Wrapper-Konvention: Aufruf `agentkit-hook-{harness} {phase} {hook_id}`
  mit `phase ∈ {pre, post}` und `hook_id ∈ {branch_guard,
  orchestrator_guard, story_creation_guard, integrity_guard,
  qa_agent_guard, adversarial_guard, self_protection_guard,
  health_monitor, ccag_gatekeeper, telemetry, review_guard, budget}`
- Wrapper-Implementierung pro Harness:
  - stdin lesen (harness-spezifisches Format)
  - Adapter aufrufen, der `HookEvent` erstellt
  - `Governance.run_hook(hook_id, hook_event)` mit harness-neutralem
    Event aufrufen
  - exit-Code des Hooks zurueckgeben
- Top-Surface `Governance.run_hook(hook_id: str, event: HookEvent) -> HookDecision`
  in `src/agentkit/governance/__init__.py`
- Dispatcher: `hook_id` -> registrierter Guard-/Telemetrie-Handler
- Tests:
  - End-to-End fuer beide Harnesses (synthetisches stdin -> exit-Code)
  - Hook-Identifikator-Dispatcher (alle 12 IDs)
  - Falsche `hook_id` -> fail-closed (exit 2)
  - Falsche `phase` -> fail-closed

### Out of Scope

- Implementierung der einzelnen Guards (existiert bereits unter
  `governance/guards/`)
- Adapter-Erweiterung (Claude/Codex bestehen)
- Settings-Datei-Anpassung (FK-50 hat das schon CP 9)

## Betroffene Dateien

| Datei | Aenderungsart | Beschreibung |
|-------|---------------|--------------|
| `pyproject.toml` | Modifiziert | Entry-Points fuer beide Wrapper |
| `src/agentkit/governance/harness_adapters/claude_code.py` | Modifiziert | `main()` als CLI-Entry |
| `src/agentkit/governance/harness_adapters/codex/cli.py` | Modifiziert | `main()` als CLI-Entry konsolidieren |
| `src/agentkit/governance/__init__.py` | Modifiziert | `Governance.run_hook(hook_id, event)`-Top-Surface |
| `src/agentkit/governance/runner.py` | Modifiziert | Hook-Dispatcher |
| `tests/unit/governance/harness_adapters/test_hook_wrapper.py` | Neu | E2E-Tests |

## Akzeptanzkriterien

1. `agentkit-hook-claude pre branch_guard` ist als Shell-Befehl
   verfuegbar nach `pip install -e .`.
2. `agentkit-hook-codex pre branch_guard` ebenso.
3. Beide nehmen JSON/TOML auf stdin entgegen, normalisieren ueber den
   jeweiligen Adapter und rufen dieselbe `Governance.run_hook`-Surface.
4. Falscher Hook-ID oder Phase -> exit 2 mit aussagekraeftigem
   stderr-Text.
5. Tests gruen, Lints clean.

## Definition of Done

- Build kompiliert
- Beide Wrapper als Konsolen-Skripte aufrufbar
- Tests gruen (E2E + Dispatcher + Fehlerpfade)
- mypy strict

## Konzept-Referenzen

- FK-30 §30.3.1 — Hook-Registrierung (Settings-Datei-Beispiel)
- FK-30 §30.11 — Multi-Harness Adapter-Architektur
- FK-42 §42.5.2 — CCAG-Hook-Registrierung (analog)

## Guardrail-Referenzen

- ZERO DEBT: keine zwei Code-Pfade pro Harness (nur Adapter
  unterschiedlich, A-Kern identisch)
- FAIL CLOSED: unbekannte Hook-IDs blockieren
- SINGLE SOURCE OF TRUTH: ein Hook-Identifikator-Set fuer beide Harnesses
