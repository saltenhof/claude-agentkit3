# AG3-015: Prompt-Runtime — Bundle-Pinning + Materialisierung + Audit

**Typ:** Implementation
**Groesse:** L
**Abhaengigkeiten:** keine
**Quell-Konzept:** FK-44 (vollstaendig), FK-50 §50.5 (Installer-Bindung)

---

## Kontext

FK-44 normiert die Prompt-Runtime mit drei Schichten:

1. **Kanonische Prompt-Bundles** (systemweit, immutable, versioniert)
2. **Projektlokale Prompt-Bindung** ueber expliziten
   `prompt-bundle.lock.json`-Datensatz
3. **Run-gebundene Prompt-Instanzen** unter
   `.agentkit/prompts/{run_id}/{invocation_id}/prompt.md`

Im AK3-Code existiert **kein** `src/agentkit/prompt_runtime/`. Das
gesamte BC fehlt, obwohl viele andere BCs (Setup, Worker-Spawn,
Verify-System) auf
`PromptRuntime.materialize_prompt(...)` und
`PromptRuntime.update_binding(bundle_id, version)` verweisen.

## Scope

### In Scope

- Neues Sub-Paket `src/agentkit/prompt_runtime/`:
  - `bundle_store.py` — kanonischer System-Bundle-Store (`PromptBundleStore`)
  - `bundle_pinning.py` — `ProjectPromptPin`, `RunPromptPin`,
    Pin-Lifecycle (`update_binding`, Run-Pin-Snapshot bei `setup`)
  - `materialization.py` — `materialize_prompt(...)`, statisch via
    Hardlink/Symlink, dynamisch via Render in
    `.agentkit/prompts/{run_id}/{invocation_id}/prompt.md`
  - `audit.py` — `PromptAuditHash` (template_sha256,
    render_input_digest, output_sha256), Persistierung via
    `artifacts.ArtifactManager`
  - `runtime.py` — Top-Surface `PromptRuntime` mit
    `materialize_prompt(...)` und `update_binding(...)`
- Lock-Datei `.agentkit/config/prompt-bundle.lock.json` mit
  `bundle_id`, `bundle_version`, `manifest_digest`
- Run-Pin-Datei `.agentkit/manifests/prompt-pins/{run_id}.json`
- Installer-Anschluss: `Skills.bind_skill` und
  `PromptRuntime.update_binding` werden parallel in CP 8 aufgerufen
  (FK-50 §50.5)
- Tests:
  - Bundle-Pin-Roundtrip (bind, read, update)
  - Materialisierung statischer Prompts (Hardlink-Korrektheit)
  - Materialisierung dynamischer Prompts (Render mit Input-Digest)
  - Run-Pin-Snapshot-Konsistenz (mid-run-Drift verhindert)
  - PromptAuditHash deterministisch (gleicher Input -> gleicher Hash)

### Out of Scope

- `prompt_used`-Telemetrie-Event (FK-44 §44.6 noch optional)
- Frontend-Lese-API fuer Prompt-Audit
- Migration alter Prompt-Bundles (greenfield in AK3)

## Betroffene Dateien

| Datei | Aenderungsart | Beschreibung |
|-------|---------------|--------------|
| `src/agentkit/prompt_runtime/__init__.py` | Neu | Top-Surface-Re-Export |
| `src/agentkit/prompt_runtime/runtime.py` | Neu | PromptRuntime |
| `src/agentkit/prompt_runtime/bundle_store.py` | Neu | PromptBundleStore |
| `src/agentkit/prompt_runtime/bundle_pinning.py` | Neu | ProjectPromptPin, RunPromptPin |
| `src/agentkit/prompt_runtime/materialization.py` | Neu | materialize_prompt |
| `src/agentkit/prompt_runtime/audit.py` | Neu | PromptAuditHash |
| `src/agentkit/installer/runner.py` | Modifiziert | CP 8: PromptRuntime.update_binding-Aufruf |
| `tests/unit/prompt_runtime/...` | Neu | Umfangreich |

## Akzeptanzkriterien

1. `PromptRuntime.materialize_prompt(...)` liefert Pfad zu
   `.agentkit/prompts/{run_id}/{invocation_id}/prompt.md` und persistiert
   `PromptAuditHash`-Record als Artefakt.
2. Statische Prompts werden via Hardlink/Symlink projeziert (FK-44 §44.4.1).
3. Dynamische Prompts werden gerendert; Input-Digest deterministisch.
4. Run-Pin friert Bundle-Version bei Run-Start ein; spaetere
   `update_binding` aendern den Pin nicht.
5. Lock-Datei + Run-Pins folgen FK-44 §44.3-Format.
6. Tests gruen, Lints clean.

## Definition of Done

- Build kompiliert
- Tests gruen (Bundle, Pinning, Materialisierung, Audit)
- mypy strict
- Konzept-Referenzen FK-44 in Modul-Docstrings

## Konzept-Referenzen

- FK-44 (vollstaendig) — Prompt-Runtime
- FK-50 §50.5 — Installer-Bindung
- FK-71 — ArtifactManager fuer Audit-Persistierung

## Guardrail-Referenzen

- SINGLE SOURCE OF TRUTH: kanonische Bundles im System-Store, lokal
  nur Projektion
- ZERO DEBT: kein "wir haendeln Pinning spaeter"
- FAIL CLOSED: ohne validen Run-Pin kein Worker-Spawn
