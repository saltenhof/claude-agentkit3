# AG3-004: Codex-Harness-Adapter

**Typ:** Implementation
**Groesse:** M
**Abhaengigkeiten:** Keine (Claude-Code-Adapter existiert als Referenz)
**Quell-Konzept:** FK-30 §30.11

---

## Kontext

AK3 muss **ab Tag 1 zwei Harnesses parallel** unterstuetzen — Claude
Code und Codex. Der Claude-Code-Adapter existiert in `agentkit.
governance.harness_adapters.claude_code` (mit Backward-Compat-Pfad
`agentkit.backend.governance.hookruntime`). Der Codex-Adapter fehlt.

Beide Adapter mappen die harness-spezifische Hook-Mechanik auf die
generische `HookEvent`-Struktur in `agentkit.backend.governance.guard_evaluation`
(harness-neutraler A-Kern). Damit funktioniert der gesamte Guard-/
Capability-/Worker-Health-Apparat fuer beide Harnesses gleichermassen.

## Scope

### In Scope

- Neues Modul `agentkit.harness_client.harness_adapters.codex` als
  AT-Insel (Bluttyp A, fachlich Mediation; siehe FK-30 §30.11.3)
- Eingangs-Mapping: Codex-Hook-Event → generische `HookEvent`
  - Tool-Namen-Mapping auf `operation` (mutating: `bash_command`,
    `file_write`, `file_edit`; read-only: `file_read`)
  - `principal_kind`-Mapping auf Codex-Aequivalent (Codex-Sub-Agent
    vs. Haupt-Agent — pruefen, wie Codex das exponiert)
  - `freshness_class`-Ableitung
  - `cwd`, `session_id`-Uebernahme
- Ausgangs-Mapping: generische Decision (`allow` / `block` mit
  Begruendung) → Codex-spezifischer Output
  - Codex-Block-Konvention pruefen und implementieren (Exit-Code-
    Konvention, Stdout-Format, Decision-Struktur — Detail aus
    Codex-Doku ableiten)
- Sub-Agent-Lifecycle: wenn Codex Sub-Agent-Spawn unterstuetzt, das
  Mapping mitfuehren
- CLI-Entry: `agentkit-hook-codex` oder analog (das, was die
  Codex-Settings-Datei aufruft)
- Tests: Roundtrip-Tests Codex-Event → HookEvent → Decision →
  Codex-Output, plus Edge-Cases
- Cookbook-Section in FK-30 §30.11.3 ergaenzen: konkrete Anschluss-
  Anleitung fuer einen Harness, basierend auf der dann existierenden
  zweifachen Implementierung

### Out of Scope

- Installer-Integration (das ist AG3-006)
- Hybrid-Sub-Agent-Mechanik (Claude Code spawnt Codex via
  Sub-Agent) — der Outer-Harness vermittelt; eine eigene Story dafuer
  kommt erst, wenn die Mechanik real benoetigt wird
- Frontend-Hub-Integration

## Betroffene Dateien

| Datei | Aenderungsart | Beschreibung |
|-------|--------------|--------------|
| `src/agentkit/governance/harness_adapters/codex/__init__.py` | Neu | Package-Init |
| `src/agentkit/governance/harness_adapters/codex/event_mapping.py` | Neu | Codex-Event → HookEvent |
| `src/agentkit/governance/harness_adapters/codex/decision_mapping.py` | Neu | Decision → Codex-Output |
| `src/agentkit/governance/harness_adapters/codex/cli.py` | Neu | CLI-Entry-Punkt fuer Codex-Hook-Aufruf |
| `src/agentkit/cli/main.py` | Modifiziert | `agentkit-hook-codex` registrieren (oder analoger Mechanismus) |
| `concept/formal-spec/architecture-conformance/entities.md` | Modifiziert | Neuer `harness_adapters_codex`-Sub von BC `governance` (analog zu `harness_adapters_claude_code`) |
| `concept/technical-design/30_hook_adapter_guard_enforcement.md` | Modifiziert | §30.11.3 Cookbook-Anhang ergaenzt mit konkretem Codex-Anschluss-Beispiel |
| `tests/unit/governance/harness_adapters/codex/test_event_mapping.py` | Neu | Tool-Namen-Mapping, Operation-Klassifikation |
| `tests/unit/governance/harness_adapters/codex/test_decision_mapping.py` | Neu | Decision → Codex-Output |
| `tests/unit/governance/harness_adapters/codex/test_cli.py` | Neu | CLI-Roundtrip |

## Akzeptanzkriterien

1. **`agentkit.harness_client.harness_adapters.codex`-Modul existiert** und ist als A-Sub von `governance` in `entities.md` modelliert (analog zu `harness_adapters_claude_code`).
2. **Eingangs-Mapping vollstaendig**: alle Codex-Tool-Namen werden auf eine `HookEvent.operation` abgebildet; unbekannte Tools werden auf `unknown_tool` gemappt.
3. **Ausgangs-Mapping vollstaendig**: jede `GuardVerdict`-Decision wird auf das Codex-spezifische Output-Format gemappt (Block/Allow, Begruendung).
4. **Roundtrip funktioniert**: synthetischer Codex-Hook-Event durch Adapter → `evaluate_pre_tool_use` → Decision → Codex-Output.
5. **CLI-Entry funktioniert**: `agentkit-hook-codex` (oder analoger Pfad) ist als Skript ausfuehrbar, liest stdin, schreibt stdout, exit-Code-Konvention ist Codex-konform.
6. **Tests gruen**, ruff, mypy strict, alle drei concept-lints, architecture-conformance-Audit clean.
7. **Keine AC012-Warnings**.
8. **FK-30 §30.11.3 Cookbook-Anhang** ist ergaenzt und beschreibt anhand der konkreten Implementation, wie ein dritter Harness anzuschliessen waere.

## Definition of Done

- Build kompiliert
- Tests gruen, Lints clean
- Cookbook-Anhang nachvollziehbar fuer einen menschlichen Leser
- Akzeptanzkriterien nachweislich erfuellt

## Konzept-Referenzen

- FK-30 (`concept/technical-design/30_hook_adapter_guard_enforcement.md`) §30.11 — Multi-Harness-Festlegung
- `concept/methodology/software-blutgruppen.md` §4.2 — AT-Mediation als legitime Mischform
- `agentkit.harness_client.harness_adapters.claude_code` als Referenz-Implementation

## Guardrail-Referenzen

- ZERO DEBT, FAIL CLOSED
- AT-Mediation lokalisieren: der Adapter ist die einzige Stelle mit
  Codex-spezifischer Mechanik, der A-Kern (`guard_evaluation`)
  bleibt harness-neutral
