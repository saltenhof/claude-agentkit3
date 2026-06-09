OVERALL CHANGES-REQUESTED

**1) Konzept-Vollstaendigkeit: FAIL**

- **ERROR**: Zentraler Epoch-Store ist konzeptionell unvollstaendig spezifiziert. Die Story fordert `(project_key, story_id) -> epoch` und atomare Updates, aber der Marker enthaelt nur `story_id/run_id/created_at`; FK-36 nennt fuer den Marker ebenfalls nur `story_id/worktree_id/created_at`. Damit ist nicht definiert, wie `epoch_writer` den `project_key` deterministisch ermittelt.  
  Evidence: `stories/AG3-075-compaction-resilience/story.md:42`, `stories/AG3-075-compaction-resilience/story.md:44`, `stories/AG3-075-compaction-resilience/story.md:45`, `concept/technical-design/36_compaction_resilience_prompt_persistence.md:503`, `concept/technical-design/36_compaction_resilience_prompt_persistence.md:507`, `concept/technical-design/36_compaction_resilience_prompt_persistence.md:513`, `src/agentkit/story_context_manager/models.py:312`.  
  Fix: `project_key` explizit in `.agentkit-story.json`, Spawn-Spec und Manifest aufnehmen oder einen eindeutigen Lookup-Vertrag aus cwd/project config/state backend als AC festschreiben.

- **WARNING**: FK-36 ist intern noch widerspruechlich zur Agent-Spawn-Policy. DD-09 sagt `Inject + Warn (exit 0), kein hartes Deny`; §36.10/§36.11 sprechen noch von Agent-Spawn-Deny/blockiert. Die Story folgt DD-09, markiert die widersprechenden FK-Stellen aber nicht konkret.  
  Evidence: `concept/technical-design/36_compaction_resilience_prompt_persistence.md:534`, `concept/technical-design/36_compaction_resilience_prompt_persistence.md:545`, `concept/technical-design/36_compaction_resilience_prompt_persistence.md:660`, `concept/technical-design/36_compaction_resilience_prompt_persistence.md:663`, `stories/AG3-075-compaction-resilience/story.md:41`.  
  Fix: In der Story den FK-36-Widerspruch explizit als doc-follow-up benennen und DD-09 als gueltige Prioritaet festhalten.

**2) AC-Schaerfe: FAIL**

- **ERROR**: Pflicht-Gates sind unvollstaendig. AC 13 nennt lokale Tests/Lint/Typisierung/Konzept-Gates, aber nicht das verpflichtende Remote-Gate `scripts/ci/check_remote_gates.ps1` fuer Jenkins und Sonar.  
  Evidence: `stories/AG3-075-compaction-resilience/story.md:68`, `AGENTS.md:31`, `AGENTS.md:43`, `AGENTS.md:52`, `scripts/ci/check_remote_gates.ps1:75`, `scripts/ci/check_remote_gates.ps1:78`.  
  Fix: AC 13 um `scripts/ci/check_remote_gates.ps1` inklusive Sonar-Nullmetriken und Jenkins gruen ergaenzen.

- **ERROR**: Fail-open/fail-closed-Semantik fuer Sicherheitsfehler ist unscharf. Die Story sagt einerseits Fail-open bei Drift-Hash-Mismatch, andererseits “Fail-closed gilt fuer Input-Validierung und Drift-Hash-Erkennung”; AC 11 sagt nur “abgewiesen”, ohne Exit-/Output-Vertrag.  
  Evidence: `stories/AG3-075-compaction-resilience/story.md:40`, `stories/AG3-075-compaction-resilience/story.md:46`, `stories/AG3-075-compaction-resilience/story.md:66`, `stories/AG3-075-compaction-resilience/story.md:67`, `stories/AG3-075-compaction-resilience/story.md:74`.  
  Fix: Pro Fall exakt festlegen: Exit-Code, stderr-Warning, ob Dateien gelesen/geschrieben werden, und ob der Hook den Agenten weiterlaufen laesst.

**3) Klarheit: WEAK**

- **ERROR**: Ist-Zustand-Anker ist falsch: `src/agentkit/composition_root.py:132` existiert nicht. Die reale Datei ist `src/agentkit/bootstrap/composition_root.py:132`.  
  Evidence: `stories/AG3-075-compaction-resilience/story.md:24`, `stories/AG3-075-compaction-resilience/story.md:82`, `src/agentkit/bootstrap/composition_root.py:132`.  
  Fix: Beide Story-Stellen auf `src/agentkit/bootstrap/composition_root.py:132` korrigieren.

- **WARNING**: Session-Line-Range ist stale/zu knapp. Die Story nennt `implementation/worker_session/session.py:193-207`; der `materialize_prompt`-Call laeuft real ueber `207-214`, Rueckgabe `215`.  
  Evidence: `stories/AG3-075-compaction-resilience/story.md:24`, `stories/AG3-075-compaction-resilience/story.md:27`, `src/agentkit/implementation/worker_session/session.py:193`, `src/agentkit/implementation/worker_session/session.py:207`, `src/agentkit/implementation/worker_session/session.py:215`.  
  Fix: Anchor auf `session.py:169-215` oder gezielt `207-215` aktualisieren.

- **NIT**: Der `_temp`/`var`-Konflikt ist ueberzeichnet und mit ARCH-55 falsch begruendet. `.gitignore` dokumentiert `/_temp/` explizit als ephemeres Laufzeitverzeichnis.  
  Evidence: `stories/AG3-075-compaction-resilience/story.md:31`, `.gitignore:52`, `.gitignore:59`.  
  Fix: ARCH-55-Verweis entfernen; stattdessen echte Pfadentscheidung `_temp` vs. `.agentkit/prompts`/`var` knapp begruenden.

**4) Kontext-Sinnhaftigkeit: FAIL**

- **ERROR**: Der zentrale Store hat keinen klaren Code-Owner/Schema-Anschluss. Die Story legt ihn in `pipeline_engine/compaction_resilience` in Scope, aber der bestehende zentrale Persistenzpfad ist `state_backend`; ein neues `(project_key, story_id, epoch, updated_at)`-Schema samt Repository/Migration ist nicht als Owner-Vertrag beschrieben.  
  Evidence: `stories/AG3-075-compaction-resilience/story.md:36`, `stories/AG3-075-compaction-resilience/story.md:44`, `src/agentkit/state_backend/config.py:173`, `src/agentkit/state_backend/postgres_schema.sql:4`, `src/agentkit/state_backend/postgres_schema.sql:125`, `src/agentkit/state_backend/postgres_schema.sql:154`.  
  Fix: Store-Owner explizit machen: Tabelle/Migration/Repository im `state_backend`, plus schmale API fuer `compaction_resilience`.

**Must-Fix**

1. `project_key`-Quelle fuer `epoch_writer`/Manifest/Store verbindlich spezifizieren.
2. Falsche/stale Ist-Zustand-Anker korrigieren, besonders `bootstrap/composition_root.py:132`.
3. Fail-open/fail-closed fuer Drift, fehlende Artefakte und invaliden `agent_id` als testbaren Exit-/Output-Vertrag formulieren.
4. Remote-Gate `scripts/ci/check_remote_gates.ps1` in AC/DoD aufnehmen.
5. Zentralen Epoch-Store mit State-Backend-Owner, Schema/Migration und atomarer Repository-API beschreiben.
