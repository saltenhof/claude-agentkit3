# AG3-013: CCAG Permission-Runtime + Gate-Keeper-Hook

**Typ:** Implementation
**Groesse:** L
**Abhaengigkeiten:** keine
**Quell-Konzept:** FK-42, AK2-Vorlage `agentkit/governance/ccag_gatekeeper.py` + `agentkit/governance/ccag_rules.py`

---

## Kontext

FK-42 normiert CCAG (Claude Code Agent Governance) als
**lernfaehige Permission-Schicht** fuer Tool-Aufrufe — ergaenzt die
harten Guards (FK-30/31), ersetzt sie aber nicht. AK2 hat das in
`T:/codebase/claude-agentkit/agentkit/governance/ccag_gatekeeper.py`
und `ccag_rules.py` voll ausgepraegt; AK3 hat den Sub noch nicht
implementiert.

Architektur (FK-42 §42.1):
- `CcagPermissionRuntime` als eigenstaendiger Sub im BC
  `governance-and-guards`, NICHT Teil von `GuardSystem`
- Letzter PreToolUse-Hook in der Kette (nach allen Guard-Hooks)
- Harness-neutraler Aufruf ueber `HookEvent`-Felder; Hook-
  Registrierung erfolgt harness-spezifisch via Adapter (FK-30 §30.11)

Konfigurations-Pfad: `.agentkit/ccag/rules/` (FK-42 §42.7); pro
Harness ggf. Symlinks unter dem harness-eigenen Bindungspunkt.

## Scope

### In Scope

- `CcagPermissionRuntime` als Sub:
  - Top-Surface mit Methode `evaluate(hook_event: HookEvent) -> CcagDecision`
  - Decision-Werte: `allow`, `block_by_rule`, `unknown_permission`
- YAML-Regeldateien-Loader (`.agentkit/ccag/rules/`):
  - `approved.yaml` (LLM-generalisierte Freigaben)
  - `subagents.yaml`, `global.yaml` (statisch installiert)
  - Sessionuebergreifende Persistenz
  - Parameter-basierte Regeln (FK-42 §42.2.2)
- Permission-Lease und Permission-Request:
  - `permission-lease`: befristete Einzelfall-Freigabe
  - `permission-request`: setzt Run auf PAUSED, blockiert Tool-Call,
    laedt Mensch zur Entscheidung ein, TTL-Default-Ablauf -> DENIED
- Modus-scharfe Entscheidungsarten (FK-42 §42.2.5):
  - `story_execution`: keine Host-Prompt-Aufloesung; unbekannte
    Freigaben -> permission_request
  - `ai_augmented` + interactive_agent: Host-Prompt zugelassen
- Gate-Keeper-Hook:
  - Adapter-Verweis fuer Hook-Registrierung in
    `.claude/settings.json` und `.codex/config.toml`
  - Aufruf-Pfad CLI: `python -m agentkit.backend.governance.ccag` oder analog
- LLM-Generalisierung (FK-42 §42.3) — optional; Voraussetzung:
  Multi-LLM-Hub
- Tests:
  - Static-Rule-Match -> allow
  - Block-Rule-Match -> block_by_rule
  - Unknown im story_execution -> unknown_permission + Permission-Request
  - Permission-Lease-Consume-Once
  - YAML-Regeldatei-Roundtrip

### Out of Scope

- LLM-Generalisierung (FK-42 §42.3) — kann als separate Story
  AG3-013b
- Frontend-Permission-Inbox (UI-Folge-Story)

## Betroffene Dateien

| Datei | Aenderungsart | Beschreibung |
|-------|---------------|--------------|
| `src/agentkit/governance/ccag/runtime.py` | Neu | CcagPermissionRuntime |
| `src/agentkit/governance/ccag/rules.py` | Neu | YAML-Loader, Rule-Eval |
| `src/agentkit/governance/ccag/leases.py` | Neu | Permission-Lease |
| `src/agentkit/governance/ccag/requests.py` | Neu | Permission-Request |
| `src/agentkit/governance/ccag/cli.py` | Neu | Hook-Entry |
| `src/agentkit/installer/ccag_settings.py` | Neu | Initialer Regeldatei-Deploy |
| `src/agentkit/resources/target_project/.agentkit/ccag/rules/` | Neu | Default-Regeln |
| `tests/unit/governance/ccag/...` | Neu | umfangreiche Suite |

## Akzeptanzkriterien

1. CCAG-Runtime evaluiert Tool-Calls auf `allow`/`block_by_rule`/
   `unknown_permission`.
2. Im `story_execution`-Modus loest CCAG keine unbekannten Freigaben
   per Host-Prompt; offener Permission-Request blockiert den Call und
   erscheint im State-Backend.
3. Permission-Lease (consume-once) funktioniert.
4. Hook-Registrierung in beiden Harnesses (Claude Code + Codex) durch
   den Adapter; CCAG-Hook-Code ist harness-neutral.
5. Tests gruen, Lints clean.

## Definition of Done

- Build kompiliert
- Tests gruen (alle Modus-Pfade, Lease, Request)
- mypy strict
- Smoke-Test: synthetisches Projekt mit Test-Regeln, Tool-Call
  durchlaufen, Decision wie erwartet

## Konzept-Referenzen

- FK-42 — vollstaendige Spezifikation
- FK-30 §30.11 — Multi-Harness Hook-Registrierung
- FK-55 — Principal-Capability-Modell (harte Denies)
- AK2: `T:/codebase/claude-agentkit/agentkit/governance/ccag_gatekeeper.py`,
  `agentkit/governance/ccag_rules.py`, `ccag/bundle/`

## Guardrail-Referenzen

- FAIL CLOSED: unbekannte Freigaben im story_execution -> blockieren
- ZERO DEBT: nicht "wir machen Permission-Lease spaeter"
- SINGLE SOURCE OF TRUTH: Regeldateien in `.agentkit/ccag/rules/`,
  harness-spezifische Symlinks sind nur Projektion
