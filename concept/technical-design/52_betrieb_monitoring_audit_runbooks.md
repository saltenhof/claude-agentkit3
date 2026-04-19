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
prose_anchor_policy: strict
formal_refs:
  - formal.story-closure.commands
  - formal.story-closure.events
  - formal.story-closure.invariants
  - formal.story-closure.scenarios
  - formal.story-reset.commands
  - formal.story-reset.events
  - formal.story-reset.invariants
  - formal.story-reset.scenarios
---

# 52 — Betrieb, Monitoring, Audit und Runbooks

<!-- PROSE-FORMAL: formal.story-closure.commands, formal.story-closure.events, formal.story-closure.invariants, formal.story-closure.scenarios, formal.story-reset.commands, formal.story-reset.events, formal.story-reset.invariants, formal.story-reset.scenarios -->

## 52.1 Zweck

AgentKit hat keinen projektlokalen Server und keinen Betriebsprozess
im klassischen Sinne. "Betrieb" bedeutet hier: Wie stellt der
Mensch sicher, dass die zentrale Infrastruktur läuft, die Qualität
stimmt und Probleme erkannt werden?

## 52.2 Operatives Monitoring

### 52.2.1 Was überwacht werden muss

| Komponente | Prüfung | Wie |
|------------|--------|-----|
| LLM-Pools | Erreichbar? Login aktiv? | `{pool}_health` MCP-Call |
| Weaviate | Erreichbar? Daten aktuell? | `docker ps` + `story_search` Test-Query |
| ARE (wenn aktiv) | MCP-Server erreichbar? | `are_check_gate` mit Test-Story |
| PostgreSQL | Erreichbar? Rollen/Rechte korrekt? | `agentkit backend health` |
| Git | Keine stale Worktrees/Branches | `git worktree list` |
| Locks | Keine stale Locks | `agentkit query-state --locks` |
| Audit-Export | Exportziel erreichbar | `agentkit export-telemetry --dry-run` |
| Reset-Faehigkeit | Offizieller Reset-Pfad verfuegbar | `agentkit reset-story --help` |
| Split-Faehigkeit | Offizieller Story-Split-Pfad verfuegbar | `agentkit split-story --help` |
| Konfliktaufloesung | Offizieller Freeze-/Resolution-Pfad verfuegbar | `agentkit resolve-conflict --help` |

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
# Backend: PostgreSQL OK
```

## 52.3 Audit-Logs

### 52.3.1 Was geloggt wird

| Log | Speicherort | Inhalt |
|-----|------------|--------|
| Telemetrie (Laufzeit) | PostgreSQL | Alle Events |
| Telemetrie (Archiv) | Audit-Export / Objektspeicher | JSONL-Export gueltiger, nicht vollstaendig zurueckgesetzter Runs |
| Integrity-Violations | PostgreSQL (Event-Typ `integrity_violation`) | Guard-Blockaden |
| Integrity-Gate-Ergebnisse | PostgreSQL (Event-Typ `integrity_gate_result`) | FAIL-Codes |
| Governance-Adjudication | PostgreSQL (Event-Typ `governance_adjudication`) | Incident-Klassifikation |
| QA-Artefakte | PostgreSQL | Structural, LLM-Review, Adversarial, Policy |
| Failure Corpus | PostgreSQL / Artefaktspeicher | Incidents, Patterns, Checks |

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
1. Lock-Record prüfen: Prozess noch aktiv?
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
2. Phase-State prüfen: `agentkit query-state --story {story_id}`
3. Telemetrie: letzte Events prüfen
4. Wenn Loop: agentkit reset-escalation --story {story_id}
5. Story-Anforderungen vereinfachen oder Mensch greift ein
```

### 52.5.5 Merge-Konflikt

```
Symptom: Closure ESCALATED mit Merge-Konflikt
Ursache: Main hat sich seit Story-Start weiterentwickelt

Lösung:
1. Offiziellen Closure-Retry pruefen: `agentkit run-phase closure --story {story_id} --no-ff`
2. Wenn Closure damit sauber abschliesst: Story normal beenden
3. Wenn weiterhin harter, nicht workflowfaehiger Konflikt vorliegt:
   Eskalation bestehen lassen und menschliche Entscheidung treffen
4. Nur wenn die Umsetzung als korrupt oder unbrauchbar gilt:
   `agentkit reset-story --story {story_id} --reason "..."`
```

### 52.5.6 Scope-Explosion / Story-Split

```text
Symptom: Exploration PAUSED mit scope_explosion
Ursache: Story-Scope war zu klein deklariert, Umsetzung muss neu geschnitten werden

Loesung:
1. Gegenueberstellung erwartet vs. festgestellt pruefen
2. Mensch entscheidet ueber Split-Plan und Nachfolger
3. Offiziellen Split ausloesen:
   agentkit split-story --story {story_id} --plan split-plan.json --reason "scope explosion"
4. Ergebnis pruefen:
   - Ausgangs-Story Status = Cancelled
   - Issue geschlossen mit not planned
   - Nachfolger-Stories im Backlog
   - keine aktiven Locks / Worktrees der Ausgangs-Story
```

### 52.5.7 Autoritativer Snapshot-/Normkonflikt

```text
Symptom: Worker oder Verify stoppt mit Widerspruch zwischen
story.md / GitHub / ARE-Bundle / anderem autoritativen Snapshot

Ursache: Der laufende Run basiert auf einer Autoritaetslage, die nicht
mehr konsistent ist. Der Orchestrator darf diesen Konflikt nicht selbst
reparieren.

Loesung:
1. Pruefen, dass fuer die Story ein `conflict_freeze` aktiv ist
2. Keine freien Cleanup-, Git- oder ARE-Kuratierungsaktionen ausfuehren
3. Mensch trifft die Aufloesungsentscheidung
4. Offiziellen Pfad verwenden:
   agentkit resolve-conflict --story {story_id} --decision {decision} --reason "..."
5. Ergebnis pruefen:
   - `conflict_freeze` aufgehoben oder in offiziellen Folgeservice ueberfuehrt
   - kein freier Orchestrator-Write waehrend des Freeze
   - neuer Snapshot / Redirect / Split / Cancel sauber auditiert
```

### 52.5.8 Vollstaendiger Story-Reset

```
Symptom: Story ist ESCALATED und kann ueber Standardpfade nicht mehr
sauber weitergefuehrt werden
Ursache: Schwerer technischer Fehler, irreparabler Merge-Konflikt,
inkonsistenter Runtime-State oder vergleichbarer Ausnahmefall

WICHTIG: Ein Story-Reset wird nie automatisch vom Orchestrator oder
von AgentKit selbst ausgeloest. Er ist eine ausdruecklich menschliche
Recovery-Entscheidung.

Lösung:
1. Eskalationsgrund und letzte gueltige Telemetrie pruefen
2. Sicherstellen, dass normale Recovery-Pfade nicht mehr tragfaehig sind
3. Reset ausloesen:
   agentkit reset-story --story {story_id} --reason "..."
4. Ergebnis pruefen:
   - keine aktiven Locks
   - kein aktiver Runtime-State
   - keine FK-16/FK-60ff-Ableitungen der korrupten Umsetzung
5. Story bei Bedarf neu starten
```

### 52.5.9 Permission-Block / externe Permission-Interferenz

```text
Symptom: `permission_request_opened` oder
`external_permission_interference_detected` im aktiven Run
Ursache: Unbekannte Freigabe oder hostseitiges Permission-/TTY-Verhalten;
der Tool-Call darf nicht unendlich auf Mensch/UI warten

Loesung:
1. Offenen Permission-Request fuer `story_id` und `run_id` pruefen
2. Entscheiden:
   - Einzelfall freigeben:
     agentkit approve-permission-request --request {request_id}
   - Einzelfall ablehnen:
     agentkit reject-permission-request --request {request_id}
3. Nur bei bewusstem Mehrwert daraus spaeter eine Dauerregel machen
4. Wenn ein Host-Prompt oder TTY-Effekt auftrat:
   - als `external_permission_interference_detected` dokumentieren
   - keinen haengenden Tool-Call weiterverwenden
   - Story nur ueber offiziellen Resume-/Folgepfad fortsetzen
5. Ergebnis pruefen:
   - Request ist `approved`, `rejected` oder `expired`
   - kein unendlicher Wait auf Host-UI
   - derselbe Run wird nur mit expliziter Entscheidung fortgesetzt
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
| `.claude/ccag/rules/` | Hoch | Teil des Git-Repos |
| PostgreSQL | Hoch | Zentrales DB-Backup / PITR |
| Audit-Exports | Mittel | Objektspeicher / Archiv-Backup |

### 52.7.2 Retention

| Daten | Retention | Begründung |
|-------|----------|-----------|
| QA-Artefakte abgeschlossener Stories | 90 Tage, dann archivierbar | Audit-Trail, Failure-Corpus-Grundlage |
| JSONL-Exports | Permanent fuer gueltige Runs | Langfrist-Audit |
| Failure Corpus | Permanent | Wächst über die Projektlaufzeit |
| Stale Locks/Marker | Sofort löschbar nach Cleanup | Kein Langfrist-Wert |
| Adversarial-Sandbox | Löschbar nach Promotion | Ephemer |

**Reset-Regel:** Ein vollstaendig zurueckgesetzter Story-Run ist kein
retentionswuerdiger gueltiger Lauf. Seine runtime-nahen Auditdaten und
abgeleiteten Artefakte werden mit entfernt; dauerhafte Aufbewahrung
gilt nur fuer gueltige Runs.

---

*FK-Referenzen: FK-10-058 (wöchentlicher Review-Slot),
FK-10-086 bis FK-10-093 (Anti-Patterns, Sunset),
FK-11-009 (nachgelagerte Verifikation)*
