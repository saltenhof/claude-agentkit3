---
concept_id: FK-91
title: API- und Event-Katalog
module: api-catalog
status: active
doc_kind: core
parent_concept_id:
authority_over:
  - scope: api-catalog
defers_to: []
supersedes: []
superseded_by:
tags: [api, events, cli, hooks, reference]
---

# 91 — API- und Event-Katalog

## 91.1 CLI-Befehle (agentkit)

| Befehl | Kapitel | Beschreibung |
|--------|---------|-------------|
| `agentkit install` | 50 | Installation in Zielprojekt (13 Checkpoints) |
| `agentkit verify` | 50 | Read-only Verifikation der Installation |
| `agentkit run-phase {phase}` | 20 | Pipeline-Phase ausführen |
| `agentkit structural` | 33 | Structural Checks ausführen |
| `agentkit policy` | 33 | Policy-Evaluation ausführen |
| `agentkit stages` | 33 | Stage-Registry anzeigen |
| `agentkit status` | 52 | Systemstatus anzeigen |
| `agentkit cleanup --story {story_id}` | 20 | Stale Worktree/Branch/Locks aufräumen |
| `agentkit resume --story {story_id}` | 35 | Pausierte Story fortsetzen |
| `agentkit reset-escalation --story {story_id}` | 35 | Eskalation zurücksetzen |
| `agentkit reset-story --story {story_id}` | 53 | Vollständige korrupt gewordene Umsetzung administrativ zurücksetzen |
| `agentkit split-story --story {story_id}` | 54 | Scope-Explosion kontrolliert in Nachfolger-Stories überführen |
| `agentkit override-integrity --story {story_id}` | 35 | Integrity-Gate bewusst overriden |
| `agentkit query-telemetry` | 52 | Telemetrie-Events abfragen |
| `agentkit weekly-review` | 52 | Wöchentlichen Review-Slot anzeigen |
| `agentkit failure-corpus suggest-patterns` | 41 | Pattern-Kandidaten vorschlagen |
| `agentkit failure-corpus review-patterns` | 41 | Patterns reviewen |
| `agentkit failure-corpus review-checks` | 41 | Check-Proposals reviewen |
| `agentkit failure-corpus effectiveness-report` | 41 | Wirksamkeits-Report |
| `agentkit failure-corpus list-checks` | 41 | Aktive Checks anzeigen |
| `agentkit failure-corpus add-incident` | 41 | Incident manuell erfassen |
| `agentkit evidence assemble` | 26 | Evidence-Bundle für Review assemblieren (3-Stufen: Git-Diff, Import-Resolver, Worker-Hints) |

## 91.2 Telemetrie-Event-Typen

| Event-Typ | Kapitel | Quelle | Beschreibung |
|-----------|---------|--------|-------------|
| `agent_start` | 14 | Hook (PostToolUse Agent) | Worker/Adversarial Agent gestartet |
| `agent_end` | 14 | Hook (PostToolUse Agent) | Agent regulär beendet |
| `increment_commit` | 14 | Hook (PreToolUse Bash) | Worker committet Inkrement |
| `drift_check` | 14 | Hook (PreToolUse Bash) | Drift-Prüfung Ergebnis |
| `review_request` | 14 | Hook (PreToolUse Pool-Send) | Worker fordert Review an |
| `review_response` | 14 | Hook (PostToolUse Pool-Send) | Review-Antwort empfangen |
| `review_compliant` | 14 | Review-Guard (PostToolUse) | Review über freigegebenes Template |
| `llm_call` | 14 | LLM-Evaluator / Hook | LLM über Pool aufgerufen |
| `adversarial_start` | 14 | Hook (PostToolUse Agent) | Adversarial Agent gestartet |
| `adversarial_sparring` | 14 | Hook (PostToolUse Pool-Send) | Sparring-LLM aufgerufen |
| `adversarial_test_created` | 14 | Hook (PostToolUse Write) | Neuer Test in Sandbox |
| `adversarial_test_executed` | 14 | Hook (PostToolUse Bash) | Test ausgeführt |
| `adversarial_end` | 14 | Hook (PostToolUse Agent) | Adversarial Agent beendet |
| `integrity_violation` | 14 | Guard-Hooks (PreToolUse) | Guard hat blockiert |
| `web_call` | 14 | Budget-Hook (PostToolUse) | Web-Aufruf |
| `governance_signal` | 35 | Hooks (normalisiert) | Governance-Anomalie-Signal |
| `governance_adjudication` | 35 | Governance-Beobachtung | LLM-Klassifikation eines Incidents |
| `integrity_gate_result` | 35 | Phase Runner (Closure) | Integrity-Gate PASS/FAIL |
| `integrity_override` | 35 | CLI (Mensch) | Manueller Override |
| `story_reset_requested` | 53 | CLI / StoryResetService | Menschlicher Reset-Vorgang angefordert |
| `story_reset_started` | 53 | StoryResetService | Reset-Fencing und Purge begonnen |
| `story_reset_completed` | 53 | StoryResetService | Reset vollständig abgeschlossen, Story in sauberem Neustartzustand |
| `story_reset_failed` | 53 | StoryResetService | Reset unvollständig gescheitert, Story bleibt administrativ blockiert |
| `story_split_requested` | 54 | CLI / StorySplitService | Menschlicher Story-Split angefordert |
| `story_split_started` | 54 | StorySplitService | Story gefenced, Split-Plan-Ausführung begonnen |
| `story_split_completed` | 54 | StorySplitService | Ausgangs-Story beendet, Nachfolger-Stories angelegt |
| `story_split_failed` | 54 | StorySplitService | Split unvollständig gescheitert, Story bleibt administrativ blockiert |
| `preflight_request` | 14 | Hook (PreToolUse Pool-Send) | Preflight-Prompt an LLM-Pool gesendet (Preflight-Sentinel) |
| `preflight_response` | 14 | Hook (PostToolUse Pool-Send) | Preflight-Antwort vom LLM empfangen |
| `preflight_compliant` | 14 | Review-Guard (PostToolUse) | Preflight verwendete genehmigtes Template (Preflight-Sentinel) |
| `review_divergence` | 14 | `telemetry/divergence.py` | Divergenz zwischen zwei Reviewern gemessen |
| `are_requirements_linked` | 40 | Pipeline-Skript | ARE: Anforderungen verlinkt |
| `are_evidence_submitted` | 40 | Worker/QA-Prozess | ARE: Evidence eingereicht |
| `are_gate_result` | 40 | Pipeline-Skript | ARE: Gate PASS/FAIL |

## 91.3 MCP-Tool-Katalog

### LLM-Session-Pools (pro Pool)

| Tool | Kapitel | Beschreibung |
|------|---------|-------------|
| `{pool}_acquire` | 11 | Slot anfordern |
| `{pool}_send` | 11 | Nachricht senden |
| `{pool}_release` | 11 | Slot freigeben |
| `{pool}_health` | 11 | Lebendigkeit prüfen |
| `{pool}_pool_status` | 11 | Pool-Übersicht |

### Story-Knowledge-Base (Weaviate)

| Tool | Kapitel | Beschreibung |
|------|---------|-------------|
| `story_search` | 13 | Semantische Suche |
| `story_list_sources` | 13 | Datenquellen auflisten |
| `story_sync` | 13 | Inkrementelle Indexierung |

### ARE (optional)

| Tool | Kapitel | Beschreibung |
|------|---------|-------------|
| `are_list_requirements` | 40 | Anforderungen auflisten |
| `are_get_recurring` | 40 | Wiederkehrende Pflichtanforderungen |
| `are_load_context` | 40 | must_cover für Worker-Kontext |
| `are_submit_evidence` | 40 | Evidence einreichen |
| `are_check_gate` | 40 | Gate prüfen |

## 91.4 Hook-Katalog

| Hook-Modul | Typ | Matcher | Kapitel |
|-----------|-----|---------|---------|
| `governance.branch_guard` | PreToolUse | Bash | 31.1 |
| `governance.orchestrator_guard` | PreToolUse | Bash, Read\|Grep\|Glob | 31.2 |
| `governance.integrity` | PreToolUse | Write\|Edit, Bash | 31.3 |
| `governance.qa_agent_guard` | PreToolUse | Write\|Edit | 31.4 |
| `governance.adversarial_guard` | PreToolUse | Write\|Edit | 31.6 |
| `governance.self_protection` | PreToolUse | Write\|Edit\|Bash | 30.5.3 |
| `governance.story_creation_guard` | PreToolUse | Bash | 31.5 |
| `governance.ccag_gatekeeper` | PreToolUse | Bash\|Write\|Edit\|Read\|Grep\|Glob\|Agent | 42.5 |
| `telemetry.hook` | Pre+PostToolUse | Agent, Bash, *_send | 14.3 |
| `telemetry.review_guard` | PostToolUse | *_send | 14.5 |
| `telemetry.budget` | PostToolUse | WebSearch\|WebFetch | 14.6 |

## 91.5 Phase-State Status-Werte

| Status | Bedeutung | Kapitel |
|--------|----------|---------|
| `IN_PROGRESS` | Phase läuft | 20.3.2 |
| `COMPLETED` | Phase erfolgreich abgeschlossen | 20.3.2 |
| `FAILED` | Phase gescheitert (z.B. Preflight) | 20.3.2 |
| `ESCALATED` | Dauerhaft gestoppt, neuer Run nötig | 35.4.3 |
| `PAUSED` | Vorübergehend angehalten, fortsetzbar | 35.4.3 |

## 91.6 Story-Reset-Statuswerte

Diese Werte gehoeren **nicht** zum normalen Phase-State, sondern zum
administrativen Reset-Vorgang aus FK-53.

| Status | Bedeutung | Kapitel |
|--------|----------|---------|
| `STARTED` | Reset-Vorgang angelegt, aber noch nicht abgeschlossen | 53.5 |
| `RESETTING` | Story ist gefenced und der Purge-Flow läuft | 53.7 |
| `COMPLETED` | Reset vollständig abgeschlossen | 53.9.3 |
| `RESET_FAILED` | Reset unvollständig gescheitert; Story bleibt blockiert | 53.9.2 |

## 91.7 Story-Split-Statuswerte

Diese Werte gehoeren **nicht** zum normalen Phase-State, sondern zum
administrativen Split-Vorgang aus FK-54.

| Status | Bedeutung | Kapitel |
|--------|----------|---------|
| `STARTED` | Split-Vorgang angelegt | 54.8.1 |
| `SPLITTING` | Story ist gefenced, Nachfolger und Rebindings werden aufgebaut | 54.8 |
| `COMPLETED` | Split vollständig abgeschlossen | 54.5 |
| `SPLIT_FAILED` | Split unvollständig gescheitert; Story bleibt administrativ blockiert | 54.8 |
