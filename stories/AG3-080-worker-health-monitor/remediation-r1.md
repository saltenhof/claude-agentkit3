# AG3-080 — Remediation r1 (Antwort auf review-r1.md)

Bearbeitet ausschliesslich `story.md` + `status.yaml` der Story AG3-080. Kein
Produktionscode, keine Tests, keine Konzept-Dateien, keine fremden Stories
angefasst. Anker-Korrekturen gegen den realen Code (`src/agentkit/`) verifiziert.

## Finding -> Resolution

### Must-Fix 1 (ERROR, §1) — PostToolUse-Outcome-Contract fehlt
**Befund:** FK-49 verlangt Erkennung ueber Tool/Command/Exit-Code/stdout/stderr
(FK-49 §49.1.1/§49.1.4), aber die Story nannte nur bestehende `HookEvent`-Felder
und schob das Adapter-Mapping pauschal out of scope. Der reale `HookEvent`
(`governance/guard_evaluation.py:38`) hat keine Ergebnisfelder; die Adapter
(`claude_code.py:75`, `codex/event_mapping.py:131`) mappen nur die Eingangs-Seite.

**Resolution:** Neues In-Scope-Item **2.1.0** — harness-neutraler
`PostToolOutcome`-Contract (`exit_code`/`stdout`/`stderr`/`tool_result`) als
Pydantic-Modell im `worker_health`-Namespace, von Scoring + `classify_commit_failure`
konsumiert. Owner-Abgrenzung explizit gemacht: die *Form* (Contract) gehoert in
AG3-080 (FK-49 ist einziger Konsument, §49.1.4 spezifiziert Exit-Code/stderr als
In-Scope); die harness-spezifische *Befuellung* (Claude/Codex-Payload ->
`PostToolOutcome`) ist FK-76-§76.4-Adapter-Arbeit und als Cross-Story-Vorbedingung
deklariert (Out-of-Scope-Block + Hinweise). Ist-Zustand-Bullet zum fehlenden
Outcome ergaenzt. Neue ACs **1a** (Contract existiert, harness-neutral) und **1b**
(End-to-End: realer Outcome -> `hook_conflict`-Beitrag). Item 1 referenziert den
Contract.

### Must-Fix 2 (ERROR, §1) — Sidecar-Persistenz widerspricht SSOT
**Befund:** Story sagte, der Sidecar pollt `agent-health.json` und schreibt
Ergebnis zurueck, obwohl State-Backend die Wahrheit sein soll
(FK-49 §49.1.1 Persistenz im Backend; FK-10 §10.1: parallele Schreibkonflikte
gehoeren ins Backend, nicht ins Projekt-Dateisystem).

**Resolution:** In-Scope-Items **5** und **6** umgeschrieben: Sidecar liest **und**
schreibt `AgentHealthState` ueber das State-Backend-Repository; `agent-health.json`
ist read-only Export, deterministisch/idempotent aus dem Backend serialisiert, nie
Eingabe fuer PreToolUse/Sidecar. `tool-call-log.jsonl` als einziges direkt
fortgeschriebenes Append-Artefakt klar abgegrenzt. ACs **6** und **7** entsprechend
gehaertet (Backend lesen/schreiben statt JSON pollen). Guardrail-Referenz SSOT
prazisiert (FK-10 §10.5/§10.1).

### Must-Fix 3 (ERROR, §3 Klarheit) — Falscher Hook-Anker
**Befund:** Story nannte `telemetry/hooks/base.HookContext`/`HookTrigger` als
kritische Hook-Infrastruktur. Real ist `HookContext` laut `base.py:7` bewusst von
`governance.guard_evaluation.HookEvent` entkoppelt (Telemetrie-Pfad). FK-49/FK-76
verlangen `HookEvent`.

**Resolution:** Anker durchgaengig auf `governance.guard_evaluation.HookEvent`
(`guard_evaluation.py:38`), `governance/runner.py` (`run_hook`) und
`harness_adapters/*` korrigiert — im Ist-Zustand-Block, In-Scope-Item 8 und den
Hinweisen. Explizite **Anker-Korrektur**-Notiz aufgenommen, dass `HookContext` nur
fuer separate Telemetrie-Events (FK-68) zu beruehren ist, nicht fuer Score-Logik.

### Must-Fix 4 (ERROR, §4 Kontext) — `status.yaml` `unblocks` falsch
**Befund:** `_STORY_INDEX.md:97` und `AG3-086/status.yaml:10` (`depends_on: AG3-080`)
sagen, AG3-086 haengt von AG3-080 ab; AG3-080 hatte trotzdem `unblocks: []`.

**Resolution:** `AG3-080/status.yaml` -> `unblocks: [AG3-086]`. Index und AG3-086
unveraendert (sie waren bereits konsistent; AG3-080 war die falsche Datei).

### Must-Fix 5 (WARNING, §2 AC-Schaerfe) — Scoring-Fenster undefiniert
**Befund:** Die Einmal-Garantie haengt am "Scoring-Fenster", das nirgends
definiert war.

**Resolution:** In-Scope-Item 3 um eine explizite Scoring-Fenster-Definition
ergaenzt: Fenster = **pro Worker-Run** (eine `AgentHealthState`-Instanz pro
`worker_id`/`story_id`); Einmal-Garantie-Flags leben darin und werden nicht
zurueckgesetzt (kein Sliding-Reset, kein Reset nach Soft); erst ein neuer
Worker-Spawn oeffnet ein neues Fenster. Damit: genau eine Soft-Intervention + ein
Hard Stop pro Run, monoton eskalierend.

## Anker-Verifikation (gegen realen Code)
- `governance/guard_evaluation.py:38` — `class HookEvent`, ohne Ergebnisfelder: **bestaetigt**.
- `governance/harness_adapters/claude_code.py:75` — `to_neutral_event`, nur Eingangs-Mapping: **bestaetigt**.
- `governance/harness_adapters/codex/event_mapping.py:131` — `to_neutral_event`, nur Eingangs-Mapping: **bestaetigt**.
- `telemetry/hooks/base.py:7` — `HookContext` explizit von `HookEvent` entkoppelt: **bestaetigt**.
- `governance/hook_registration.py:55` — `HEALTH_MONITOR = "health_monitor"`: **bestaetigt**.
- `governance/runner.py:56` (PRE_HOOK_IDS) / `:73` (POST_HOOK_IDS) — `"health_monitor"`: **bestaetigt** (Zeilenrollen prazisiert).
- `_STORY_INDEX.md:81/97` + `AG3-086/status.yaml:10` — AG3-086 depends_on AG3-080: **bestaetigt**.

## Cross-Story-Vorbedingungen (echt, nicht in AG3-080 lieferbar)
- **FK-76-PostToolUse-Outcome-Adapter:** Der harness-neutrale `PostToolOutcome`-
  Contract (AG3-080 2.1.0) muss von den Harness-Adaptern (`claude_code`, `codex`)
  aus dem realen PostToolUse-Payload (Exit-Code/stdout/stderr) befuellt werden,
  damit echte `git commit`-Failures den `hook_conflict`-Score treiben. **Im
  `_STORY_INDEX.md` existiert dafuer aktuell keine Owner-Story** — AG3-086 deckt es
  nachweislich nicht ab (Scope: WebCallBudgetGuard/skill_usage_check/Prompt-
  Integrity/CCAG-TTL; `health_monitor` dort explizit out of scope, kein
  Outcome-Adapter). Dies ist ein echter Folge-Bedarf und sollte als neue FK-76-
  Adapter-Erweiterungs-Story aufgenommen werden. **Bis dahin** laeuft die AG3-080-
  Engine korrekt, der Commit-Failure-Score-Beitrag aus realen Events bleibt jedoch
  0 (deterministisch, fail-safe, kein Crash). Diese Abhaengigkeit wurde **nicht**
  als `depends_on` in `status.yaml` aufgenommen, weil AG3-080 ohne den Adapter
  baubar/testbar ist (Engine + Contract + Unit-/Integrationstests ueber den
  Engine-Eintrittspunkt) — es ist eine nachgelagerte Vervollstaendigung, keine
  Vorbedingung fuer diese Story.

## Geaenderte Dateien (nur AG3-080)
- `stories/AG3-080-worker-health-monitor/story.md`
- `stories/AG3-080-worker-health-monitor/status.yaml`
- `stories/AG3-080-worker-health-monitor/remediation-r1.md` (dieses Dokument)
