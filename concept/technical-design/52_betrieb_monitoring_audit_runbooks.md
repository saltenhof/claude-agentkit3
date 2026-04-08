---
concept_id: FK-52
title: Betrieb, Monitoring, Audit und Runbooks
module: operations
status: active
doc_kind: core
parent_concept_id:
authority_over:
  - scope: operations
defers_to:
  - target: FK-14
    scope: event-infrastructure
    reason: Event model and telemetry infrastructure defined in FK-14
  - target: FK-50
    scope: installer-infrastructure
    reason: Installation and verification checkpoints defined in FK-50
supersedes: []
superseded_by:
tags: [operations, monitoring, audit, runbooks, telemetry]
---

# 52 — Betrieb, Monitoring, Audit und Runbooks

## 52.1 Zweck

AgentKit hat keinen zentralen Server und keinen Betriebsprozess
im klassischen Sinne. "Betrieb" bedeutet hier: Wie stellt der
Mensch sicher, dass die Infrastruktur läuft, die Qualität stimmt
und Probleme erkannt werden?

## 52.2 Operatives Monitoring

### 52.2.1 Was überwacht werden muss

| Komponente | Prüfung | Wie |
|------------|--------|-----|
| LLM-Pools | Erreichbar? Login aktiv? | `{pool}_health` MCP-Call |
| Weaviate | Erreichbar? Daten aktuell? | `docker ps` + `story_search` Test-Query |
| ARE (wenn aktiv) | MCP-Server erreichbar? | `are_check_gate` mit Test-Story |
| Git | Keine stale Worktrees/Branches | `git worktree list` |
| Locks | Keine stale Locks | `ls _temp/governance/locks/` + PID-Prüfung |
| SQLite-DB | Datei existiert, nicht korrupt | `sqlite3 _temp/agentkit.db "SELECT COUNT(*) FROM events"` |
| Disk-Space | `_temp/` nicht übermäßig groß | `du -sh _temp/` |

### 52.2.2 Status-Befehl

```bash
agentkit status

# Output:
# AgentKit v1.0.0
# Config: .story-pipeline.yaml (v3.0)
# GitHub: acme-corp/trading-platform (Project #7)
#
# LLM Pools:
#   chatgpt: OK (3/4 slots free)
#   gemini:  OK (2/3 slots free)
#   grok:    ERROR (not reachable)
#
# VectorDB: OK (Weaviate localhost:9903, 342 chunks indexed)
# ARE: disabled
#
# Active Stories:
#   ODIN-042: implementation (run a1b2..., 2h active)
#   ODIN-045: verify (run c3d4..., 15min active)
#
# Stale Locks: none
# Disk Usage: _temp/ 23MB
```

## 52.3 Audit-Logs

### 52.3.1 Was geloggt wird

| Log | Speicherort | Inhalt |
|-----|------------|--------|
| Telemetrie (Laufzeit) | `_temp/agentkit.db` | Alle Events (SQLite) |
| Telemetrie (Archiv) | `_temp/story-telemetry/{story_id}.jsonl` | JSONL-Export bei Closure |
| Integrity-Violations | `_temp/agentkit.db` (Event-Typ `integrity_violation`) | Guard-Blockaden |
| Integrity-Gate-Ergebnisse | `_temp/agentkit.db` (Event-Typ `integrity_gate_result`) | FAIL-Codes |
| Governance-Adjudication | `_temp/agentkit.db` (Event-Typ `governance_adjudication`) | Incident-Klassifikation |
| QA-Artefakte | `_temp/qa/{story_id}/*.json` | Structural, LLM-Review, Adversarial, Policy |
| Failure Corpus | `.agentkit/failure-corpus/` | Incidents, Patterns, Checks |

### 52.3.2 Abfragen

```bash
# Telemetrie einer Story
agentkit query-telemetry --story ODIN-042

# Nur bestimmte Events
agentkit query-telemetry --story ODIN-042 --event integrity_violation

# Alle Events eines Runs
agentkit query-telemetry --run a1b2c3d4-...

# Governance-Incidents
agentkit query-telemetry --event governance_adjudication --since 7d
```

## 52.4 Wöchentlicher Review-Slot

### 52.4.1 Zweck

Das FK sieht einen wöchentlichen 15-Minuten-Review-Slot vor
(FK-10-058). Hier prüft der Mensch:

1. **Failure-Corpus-Kandidaten:** Offene Pattern-Kandidaten
   bestätigen oder verwerfen
2. **Check-Proposals:** Offene Check-Proposals freigeben oder
   verwerfen
3. **Wirksamkeits-Reports:** Checks, die deaktiviert wurden oder
   werden sollten
4. **Schwellenwert-Tuning:** VektorDB-Similarity-Schwellenwert
   basierend auf protokollierten FP/FN-Raten anpassen

### 52.4.2 Kein automatischer Trigger

Es gibt keinen Kalendereintrag oder Wecker. Die Reports
erscheinen automatisch bei jedem `agentkit status` oder
explizitem Review-Aufruf:

```bash
agentkit weekly-review

# Output:
# --- Failure Corpus Review ---
# Pattern Candidates: 2 (suggest-patterns für Details)
# Check Proposals: 1 (review-checks für Details)
# Effectiveness Alerts: CHK-0003 (90d, 0 TP, 4 FP → auto-deaktiviert)
#
# --- VektorDB Tuning ---
# Threshold: 0.7
# Last 30d: 12 searches, 3 above threshold, 1 LLM-conflict
# Recommendation: threshold OK
```

## 52.5 Runbooks

### 52.5.1 LLM-Pool nicht erreichbar

```
Symptom: agentkit status zeigt Pool als ERROR
Ursache: Pool-Server nicht gestartet oder Login abgelaufen

Lösung:
1. Pool-Server starten (start.cmd für ChatGPT, boot.sh für Gemini/Grok)
2. Bei Login-Problem: VNC verbinden und manuell einloggen
3. Verifizieren: {pool}_health → "ok"
```

### 52.5.2 Stale Lock

```
Symptom: Story kann nicht gestartet werden (Preflight FAIL: stale lock)
Ursache: Vorheriger Run abgestürzt, Lock nicht aufgeräumt

Lösung:
1. PID in Lock-Datei prüfen: Prozess noch aktiv?
2. Wenn Prozess tot: agentkit cleanup --story {story_id}
3. Wenn Prozess aktiv: Warten oder Prozess manuell beenden
```

### 52.5.3 Integrity-Gate FAIL

```
Symptom: Story kann nicht geschlossen werden
Ursache: Prozess nicht vollständig durchlaufen

Lösung:
1. agentkit query-telemetry --story {story_id} --event integrity_gate_result
2. FAIL-Codes analysieren (z.B. MISSING_LLM_qa_review)
3. Ursache beheben (z.B. Pool war offline während Run)
4. Neuer Run oder Override:
   agentkit override-integrity --story {story_id} --reason "..."
```

### 52.5.4 Stagnation (Story ohne Fortschritt)

```
Symptom: Story seit > 4 Stunden in derselben Phase
Ursache: Agent hängt, Claude-Code-Session abgelaufen, oder Loop

Lösung:
1. agentkit status --story {story_id}
2. Phase-State prüfen: _temp/qa/{story_id}/phase-state.json
3. Telemetrie: letzte Events prüfen
4. Wenn Loop: agentkit reset-escalation --story {story_id}
5. Story-Anforderungen vereinfachen oder Mensch greift ein
```

### 52.5.5 Merge-Konflikt

```
Symptom: Closure ESCALATED mit Merge-Konflikt
Ursache: Main hat sich seit Story-Start weiterentwickelt

WICHTIG: Rebase auf Main ist durch den Branch-Guard blockiert.
Dieser Schritt erfolgt MANUELL durch den Menschen, NICHT durch
einen Agent. Der Mensch arbeitet direkt im Terminal, nicht in
einer Claude-Code-Session.

Lösung:
1. In Worktree wechseln: cd worktrees/{story_id}
2. Rebase: git rebase main  (manuell, kein Agent)
3. Konflikte manuell lösen
4. agentkit reset-escalation --story {story_id}
5. Pipeline neu starten (ab Verify oder Closure)
```

## 52.6 Kapazitäts- und Kostensteuerung

### 52.6.1 Kosten

| Ressource | Kosten | Steuerung |
|-----------|--------|----------|
| Claude API (Worker, Orchestrator) | API-Kosten pro Token | Story-Größe begrenzen, Feedback-Loops begrenzen (max 3) |
| LLM-Pools (Browser) | Kostenlos | Kein API-Budget, Pool-Slots begrenzen Parallelität |
| Weaviate (Docker) | Lokale Rechenleistung | CPU/RAM des Docker-Containers |
| GitHub API | Kostenlos (im Rahmen der Rate Limits) | Wenige Aufrufe pro Story |
| Disk | Lokaler Speicher | Archivierung alter QA-Artefakte |

### 52.6.2 Parallelitäts-Limits

Die Parallelität ist durch die Pool-Sizes begrenzt (Kap. 10):
- ChatGPT: 4 Slots (Default)
- Gemini: 3 Slots (Default)
- Grok: 3 Slots (Default)

Wenn alle Slots belegt sind, warten nachfolgende Aufrufe in der
Queue. Das ist eine natürliche Begrenzung der Parallelität —
kein zusätzliches Limit nötig.

## 52.7 Backup und Retention

### 52.7.1 Was gesichert werden sollte

| Daten | Wichtigkeit | Backup-Methode |
|-------|-----------|---------------|
| `.story-pipeline.yaml` | Hoch | Teil des Git-Repos |
| `.installed-manifest.json` | Mittel | Teil des Git-Repos |
| `.claude/ccag/rules/` | Hoch | Teil des Git-Repos |
| `.agentkit/failure-corpus/` | Hoch | Separates Backup (nicht in Git: zu groß) |
| `_temp/agentkit.db` | Mittel | Wiederherstellbar aus JSONL-Exports |
| `_temp/qa/` | Niedrig | Archivierbar nach Closure |

### 52.7.2 Retention

| Daten | Retention | Begründung |
|-------|----------|-----------|
| QA-Artefakte abgeschlossener Stories | 90 Tage, dann archivierbar | Audit-Trail, Failure-Corpus-Grundlage |
| JSONL-Exports | Permanent | Langfrist-Audit |
| Failure Corpus | Permanent | Wächst über die Projektlaufzeit |
| Stale Locks/Marker | Sofort löschbar nach Cleanup | Kein Langfrist-Wert |
| Adversarial-Sandbox | Löschbar nach Promotion | Ephemer |

---

*FK-Referenzen: FK-10-058 (wöchentlicher Review-Slot),
FK-10-086 bis FK-10-093 (Anti-Patterns, Sunset),
FK-11-009 (nachgelagerte Verifikation)*
