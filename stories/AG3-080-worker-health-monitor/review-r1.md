OVERALL CHANGES-REQUESTED

**1) Konzept-Vollstaendigkeit: FAIL**

- ERROR: Commit-Failure-Klassifikation ist im Scope, aber die Story spezifiziert keinen tragfaehigen Datenvertrag fuer PostToolUse-Ergebnisdaten. FK-49 verlangt Erkennung ueber Tool/Command/Exit-Code/stdout/stderr ([49_worker_health_monitor.md](T:/codebase/claude-agentkit3/concept/technical-design/49_worker_health_monitor.md:353)); die Story schiebt Adapter-Mapping out of scope ([story.md](T:/codebase/claude-agentkit3/stories/AG3-080-worker-health-monitor/story.md:45)) und nennt nur bestehende `HookEvent`-Felder ([story.md](T:/codebase/claude-agentkit3/stories/AG3-080-worker-health-monitor/story.md:33)). Realer `HookEvent` hat `operation_args`, aber keine Ergebnisfelder ([guard_evaluation.py](T:/codebase/claude-agentkit3/src/agentkit/governance/guard_evaluation.py:43)); Claude/Codex-Adapter mappen aktuell nur Command/File-Path/Tool-Name, kein `exit_code`/`stderr` ([claude_code.py](T:/codebase/claude-agentkit3/src/agentkit/governance/harness_adapters/claude_code.py:75), [event_mapping.py](T:/codebase/claude-agentkit3/src/agentkit/governance/harness_adapters/codex/event_mapping.py:131)).  
  Fix: Story muss explizit einen harness-neutralen PostToolUse-Outcome-Contract aufnehmen oder FK-76-Adapter-Erweiterung als Dependency/In-Scope-Schnitt deklarieren.

- ERROR: Sidecar-Persistenz ist widerspruechlich zur SSOT-Regel. Story sagt, der Sidecar pollt `agent-health.json` und schreibt Ergebnis zurueck ([story.md](T:/codebase/claude-agentkit3/stories/AG3-080-worker-health-monitor/story.md:37), [story.md](T:/codebase/claude-agentkit3/stories/AG3-080-worker-health-monitor/story.md:58)), gleichzeitig ist `agent-health.json` nur Export und State-Backend Wahrheit ([story.md](T:/codebase/claude-agentkit3/stories/AG3-080-worker-health-monitor/story.md:38), [story.md](T:/codebase/claude-agentkit3/stories/AG3-080-worker-health-monitor/story.md:70)). FK-49 bestaetigt State-Backend als Persistenz-Owner ([49_worker_health_monitor.md](T:/codebase/claude-agentkit3/concept/technical-design/49_worker_health_monitor.md:99)); FK-10 sagt parallele Hook-Schreibkonflikte gehoeren ins Backend, nicht ins Projekt-Dateisystem ([10_runtime_deployment_speicher.md](T:/codebase/claude-agentkit3/concept/technical-design/10_runtime_deployment_speicher.md:134)).  
  Fix: Sidecar muss per Repository/State-Backend schreiben; `agent-health.json` darf nur daraus exportiert/aktualisiert werden, oder der Export-Import-Mechanismus muss als deterministischer Owner beschrieben werden.

**2) AC-Schaerfe: WEAK**

- ERROR: ACs erzwingen nicht, dass die PostToolUse-Ergebnisdaten wirklich von realen Adapter-/Runner-Pfaden kommen. AC 5 testet nur `classify_commit_failure`, nicht die End-to-End-Erkennung eines fehlgeschlagenen `git commit` aus einem realen PostToolUse-Event ([story.md](T:/codebase/claude-agentkit3/stories/AG3-080-worker-health-monitor/story.md:57)).  
  Fix: AC ergaenzen: realer PostToolUse-Payload mit `git commit`, non-zero Exit-Code und stderr wird ueber Adapter/Runner zu Hook-Failure-State.

- WARNING: “Scoring-Fenster” ist nicht definiert, obwohl die Einmal-Garantie daran haengt ([story.md](T:/codebase/claude-agentkit3/stories/AG3-080-worker-health-monitor/story.md:35)).  
  Fix: Reset-/Fenster-Semantik festlegen: pro Worker-Run, Sliding-Window, nach Score-Abfall, nach Hard Stop, oder nach neuem Worker.

**3) Klarheit: WEAK**

- ERROR: Falscher/irrefuehrender Integrationsanker. Story nennt `telemetry/hooks/base.HookContext`/`HookTrigger` als kritische Hook-Infrastruktur ([story.md](T:/codebase/claude-agentkit3/stories/AG3-080-worker-health-monitor/story.md:27), [story.md](T:/codebase/claude-agentkit3/stories/AG3-080-worker-health-monitor/story.md:79)). Real ist `HookContext` explizit von `governance.guard_evaluation.HookEvent` entkoppelt ([base.py](T:/codebase/claude-agentkit3/src/agentkit/telemetry/hooks/base.py:7)); FK-49/FK-76 verlangen `HookEvent` ([49_worker_health_monitor.md](T:/codebase/claude-agentkit3/concept/technical-design/49_worker_health_monitor.md:55), [76_agent_harness_integration.md](T:/codebase/claude-agentkit3/concept/technical-design/76_agent_harness_integration.md:131)).  
  Fix: Hook-Anker auf `governance.guard_evaluation.HookEvent`, `governance.runner.run_hook`, `harness_adapters/*` korrigieren; `HookContext` nur als Telemetrie-Event-Adapter nennen, falls benoetigt.

**4) Kontext-Sinnhaftigkeit: FAIL**

- ERROR: `status.yaml` widerspricht dem Story-Index und AG3-086. Index sagt AG3-086 haengt von AG3-080 ab ([\_STORY_INDEX.md](T:/codebase/claude-agentkit3/var/concept-gap-analysis/_STORY_INDEX.md:97)); AG3-086 `status.yaml` bestaetigt `depends_on: AG3-080` ([status.yaml](T:/codebase/claude-agentkit3/stories/AG3-086-hook-guard-buildout/status.yaml:10)); AG3-080 `status.yaml` hat trotzdem `unblocks: []` ([status.yaml](T:/codebase/claude-agentkit3/stories/AG3-080-worker-health-monitor/status.yaml:10)).  
  Fix: `AG3-080/status.yaml` muss `unblocks: [AG3-086]` enthalten oder der Index/AG3-086 muss geaendert werden. Stand jetzt ist die Planungsmetadatei falsch.

- PASS: Die Ist-Zustand-Claims selbst sind groesstenteils belegt: `implementation/worker_health/` fehlt, die gesuchten Symbole fehlen in `src/agentkit`, `HEALTH_MONITOR` steht in `hook_registration.py:55`, `health_monitor` steht in `runner.py:56,73`, `watch-worker` fehlt im CLI, und `PROJECT_STRUCTURE.md` sieht den Namespace vor.

**Must-Fix**

1. PostToolUse-Outcome-Contract fuer `exit_code`/`stdout`/`stderr`/Tool-Ergebnis definieren und AC dazu aufnehmen.
2. Sidecar-Schreibpfad auf State-Backend klaeren; `agent-health.json` nicht als Schattenstate spezifizieren.
3. Hook-Anker von `HookContext` auf `HookEvent`/Runner/Adapter korrigieren.
4. `status.yaml` `unblocks` mit AG3-086 synchronisieren.
5. Scoring-Fenster fuer Einmal-Garantie definieren.
