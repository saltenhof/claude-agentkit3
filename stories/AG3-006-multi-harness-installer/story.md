# AG3-006: Multi-Harness Installer-Mechanik

**Typ:** Implementation
**Groesse:** S
**Abhaengigkeiten:** AG3-004 (Codex-Adapter muss existieren)
**Quell-Konzept:** FK-30 §30.11.5

---

## Kontext

Die Installation von AK3 in ein Zielprojekt registriert heute nur den
**Claude-Code-Harness** — `.claude/settings.json`, Hooks etc. Mit
Multi-Harness-Architektur (FK-30 §30.11) muss der Installer **beide
Harnesses parallel** registrieren, sobald AG3-004 (Codex-Adapter)
durch ist.

Ergebnis: jedes AK3-Zielprojekt hat **zwei Hook-Konfigurationen
parallel installiert**. Der Stratege waehlt **bei der Session-
Erstellung**, welchen Harness er startet (`claude` oder `codex`) —
es gibt keine Projekt-lokale "aktiver Harness"-Konfiguration.

## Scope

### In Scope

- Installer-Erweiterung in `agentkit.backend.installer.runner`:
  - Bestehende Claude-Code-Settings-Anlage bleibt
  - Neue Codex-Settings-Anlage parallel:
    - Codex-Konfigurations-Datei-Pfad pruefen (vermutlich
      `.codex/config.toml` oder analog — Detail aus Codex-Doku
      ableiten)
    - Hook-Registrierung fuer `agentkit-hook-codex`-Skript
  - Beide Settings werden idempotent angelegt (zweiter Installer-
    Lauf ist No-Op)
- Wrapper unter `tools/agentkit/`: pruefen, ob bestehende Wrapper
  harness-neutral sind. Wenn nicht: harness-neutral machen oder
  pro Harness ein eigener Wrapper-Slot
- Uninstall-Pfad: bei `agentkit uninstall` werden beide Settings-
  Dateien sauber rueckgebaut
- Tests:
  - Installer legt beide Settings-Dateien an (synthetisches Projekt)
  - Idempotenz: zweiter Lauf aendert nichts
  - Uninstall raeumt beide Konfigurationen auf

### Out of Scope

- Hybrid-Sub-Agent-Mechanik (Claude Code spawnt Codex)
- Auto-Detection vorhandener Harnesses
- Harness-Selection-UI

## Betroffene Dateien

| Datei | Aenderungsart | Beschreibung |
|-------|--------------|--------------|
| `src/agentkit/installer/runner.py` | Modifiziert | Codex-Settings parallel anlegen |
| `src/agentkit/installer/codex_settings.py` | Neu | Codex-Settings-Datei-Komposition |
| `src/agentkit/installer/claude_settings.py` | Pruefen | Pfad-/Naming-Konvention konsistent zu codex_settings |
| `src/agentkit/resources/target_project/.codex/...` | Neu | Codex-Settings-Template (analog zu `.claude/settings.json`) |
| `tests/unit/installer/test_codex_settings.py` | Neu | Codex-Settings-Komposition |
| `tests/unit/installer/test_runner_multi_harness.py` | Neu | Beide Settings parallel; Idempotenz; Uninstall |

## Akzeptanzkriterien

1. **Installer schreibt beide Settings parallel**: nach `agentkit install` existieren `.claude/settings.json` und `.codex/config.toml` (oder analoger Codex-Pfad) im Zielprojekt.
2. **Idempotenz**: zweiter Installer-Lauf aendert nichts an existierenden Konfigurationen.
3. **Uninstall raeumt beide Konfigurationen sauber zurueck**: keine Reste.
4. **Tests gruen**, Lints clean, audit clean.

## Definition of Done

- Build kompiliert
- Unit-Tests gruen
- Manuelles Smoke-Test: in einem leeren Test-Projekt `agentkit install`, beide Settings-Dateien sind da, Hook-Aufrufe funktionieren fuer beide Harnesses (Claude-Code-Hook + Codex-Hook).

## Konzept-Referenzen

- FK-30 (`concept/technical-design/30_hook_adapter_guard_enforcement.md`) §30.11.5 — Multi-Harness Installer
- FK-50 (`concept/technical-design/50_installer_checkpoint_engine_bootstrap.md`) — bestehende Installer-Mechanik

## Guardrail-Referenzen

- ZERO DEBT: nicht "wir machen die Codex-Settings spaeter"; entweder beide oder keine
- FAIL CLOSED: wenn ein Settings-File nicht geschrieben werden kann, bricht der Installer ab
- SINGLE SOURCE OF TRUTH: jede Settings-Datei wird vom Installer geschrieben, niemals manuell editiert
