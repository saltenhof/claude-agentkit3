# AG3-049: Codex-Harness-Adapter — CodexSettingsWriter Vollausbau

<!-- AG3-049 (Stefan-Entscheidung 2026-05-25): Folge-Story zu AG3-031.
AG3-031 lieferte die Governance-Top-Surfaces register_hooks + deactivate_locks
inklusive eines ClaudeCodeSettingsWriter (produktiv) und eines
CodexSettingsWriter (Stub). Der Codex-Adapter-Vollausbau (Hook-Command-Mapping
+ Tool-Matcher-Konventionen) ist hier ausgelagert, weil er FK-30-§30.11-tiefes
harness-spezifisches Mapping braucht und AG3-031 bereits 7 Korrektur-Passes
durchlaufen hat. -->

**Typ:** Implementation
**Groesse:** M
**Abhaengigkeiten:** AG3-031 (Governance-Top-Surfaces + Settings-Writer-Geruest)
**Quell-Konzepte (autoritativ, in dieser Reihenfolge):**
- `FK-30 §30.11` (Codex-Harness-Aequivalent fuer Settings + Tool-Bezeichner-Mapping)
- `FK-30 §30.3.1` (register_hooks Settings-Materialisierung)
- `concept/_meta/bc-cut-decisions.md §BC 4 governance-and-guards`

---

## 1. Kontext

AG3-031 hat `Governance.register_hooks(hook_definitions)` mit
Settings-Materialisierung geliefert. Der `ClaudeCodeSettingsWriter` ist
produktiv (`.claude/settings.json` mit FK-30-§30.3.1-Schema
`{hooks: {PreToolUse: [{matcher, command}]}}`). Der `CodexSettingsWriter`
(`src/agentkit/governance/harness_adapters/settings_writer.py`) ist aktuell
ein **Stub**, der:

- die `command`-Strings unveraendert von Claude uebernimmt (`agentkit-hook-claude ...`
  statt `agentkit-hook-codex ...`),
- ein minimales TOML-Format schreibt, das die Codex-eigenen Tool-Matcher-
  Konventionen (FK-30 §30.11) nicht abbildet.

Codex-Review-Befund AG3-031 (job-fcb2e17b, 2026-05-24): "CodexSettingsWriter ist
explizit als Stub markiert und uebernimmt die uebergebenen command-Strings
unveraendert; die vorhandenen Definitionen/Tests nutzen agentkit-hook-claude ...,
waehrend der Codex-Pfad agentkit-hook-codex sein muss."

## 2. Scope

### 2.1 In Scope

#### 2.1.1 Hook-Command-Mapping (Claude -> Codex)

`CodexSettingsWriter.write` mappt pro `HookDefinition` den `command`-String von
der Claude-Code-Wrapper-Form (`agentkit-hook-claude {phase} {hook_id}`) auf die
Codex-Wrapper-Form (`agentkit-hook-codex {phase} {hook_id}`). FK-30 §30.11.

#### 2.1.2 Tool-Matcher-Konventionen (FK-30 §30.11)

FK-30 §30.11: "der Codex-Adapter mappt analog gegen seine harness-eigenen
Tool-Bezeichner". Der `matcher`-String (Claude-Code-Tool-Namen) wird auf die
Codex-Tool-Bezeichner gemappt. Konkrete Mapping-Tabelle aus FK-30 §30.11 ziehen.

#### 2.1.3 TOML-Format-Vollausbau

Das `.codex/config.toml`-Format muss dem Codex-harness-eigenen
Settings-Schema entsprechen (FK-30 §30.11), nicht nur einer "TOML-like"-
Naeherung. Konkretes Schema aus FK-30 §30.11 verifizieren.

#### 2.1.4 Tests

- Unit-Test: `command`-Mapping `agentkit-hook-claude` -> `agentkit-hook-codex`
- Unit-Test: Tool-Matcher-Mapping pro FK-30-§30.11-Eintrag
- Unit-Test: TOML-Schema-Konformitaet (parse-back + Feld-Pruefung)
- Contract-Test: `register_hooks` schreibt fuer Codex-Harness korrekte Commands

### 2.2 Out of Scope

- ClaudeCodeSettingsWriter (ist AG3-031, produktiv).
- register_hooks/deactivate_locks-Top-Surface (ist AG3-031).
- Andere Harness-Adapter ausser Codex.

## 3. Betroffene Dateien

| Datei | Aenderungsart | Beschreibung |
|---|---|---|
| `src/agentkit/governance/harness_adapters/settings_writer.py` | Modifiziert | `CodexSettingsWriter` Stub -> produktiv (Command + Matcher-Mapping) |
| `tests/unit/governance/harness_adapters/test_codex_settings_writer.py` | Neu | Mapping- + Schema-Tests |

## 4. Akzeptanzkriterien

1. `CodexSettingsWriter.write` mappt `command` von `agentkit-hook-claude` auf
   `agentkit-hook-codex` (FK-30 §30.11).
2. Tool-Matcher werden auf Codex-Tool-Bezeichner gemappt (FK-30 §30.11).
3. `.codex/config.toml` entspricht dem Codex-harness-eigenen Settings-Schema.
4. Keine Stub-Markierung mehr im Docstring; Verhalten produktiv.
5. Pflichtbefehle gruen: pytest unit + contract; mypy --strict; ruff clean;
   Coverage haelt 85%.

## 5. Definition of Done

- AK 1-5 erfuellt.
- `.venv\Scripts\python -m pytest tests/unit/governance/harness_adapters -q` gruen.
- mypy --strict gruen, ruff clean.
- Sonar Quality-Gate gruen.
- Aenderungen committed auf `main`.

## 6. Konzept-Referenzen (autoritativ)

- **FK-30 §30.11** — Codex-Harness-Aequivalent + Tool-Bezeichner-Mapping
- **FK-30 §30.3.1** — register_hooks Settings-Materialisierung
- **`concept/_meta/bc-cut-decisions.md §BC 4`** — Governance-Top

## 7. Guardrail-Referenzen

- **ZERO DEBT**: kein Stub-Adapter, der Claude-Commands faelschlich als
  Codex-Commands ausgibt.
- **FAIL CLOSED**: unbekannte Tool-Matcher fuehren zu typisiertem Fehler,
  nicht zu stillem Passthrough.

## 8. Hinweise fuer den Sub-Agent

- FK-30 §30.11 selbst lesen; die Tool-Matcher-Mapping-Tabelle ist dort
  normativ. Bei Unklarheit hart stoppen und melden.
- AK2 NICHT veraendern.
