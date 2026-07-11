---
concept_id: FK-04
title: Betrieb, Monitoring, Audit und Runbooks
module: operations
cross_cutting: true
status: active
doc_kind: core
parent_concept_id:
authority_over:
  - scope: operations
defers_to:
  - target: FK-68
    scope: event-infrastructure
    reason: Event model and telemetry infrastructure defined in FK-68
  - target: FK-50
    scope: installer-infrastructure
    reason: Installation and verification checkpoints defined in FK-50
  - target: FK-69
    scope: qa-telemetry-store
    reason: Operative Runbook-Schritte verweisen auf FK-69-Read-Models und Raw-/Mirror-Tabellen als nicht zu loeschende Recovery-Quelle
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
  - formal.state-storage.invariants
  - formal.operating-modes.invariants
---

# 4 — Betrieb, Monitoring, Audit und Runbooks

<!-- PROSE-FORMAL: formal.story-closure.commands, formal.story-closure.events, formal.story-closure.invariants, formal.story-closure.scenarios, formal.story-reset.commands, formal.story-reset.events, formal.story-reset.invariants, formal.story-reset.scenarios -->

## 4.1 Zweck

AgentKit hat keinen projektlokalen Server und keinen Betriebsprozess
im klassischen Sinne. "Betrieb" bedeutet hier: Wie stellt der
Mensch sicher, dass die zentrale Infrastruktur läuft, die Qualität
stimmt und Probleme erkannt werden?

## 4.2 Operatives Monitoring

### 4.2.1 Was überwacht werden muss

| Komponente | Prüfung | Wie |
|------------|--------|-----|
| LLM-Hub | Erreichbar? Login aktiv? | Hub-Health-Aufruf über FK-75 |
| Weaviate | Erreichbar? Daten aktuell? | `docker ps` + `story_search` Test-Query |
| ARE (wenn aktiv) | MCP-Server erreichbar? | `are_check_gate` mit Test-Story |
| PostgreSQL | Erreichbar? Rollen/Rechte korrekt? | `agentkit backend health` |
| Git | Keine stale Worktrees/Branches | `git worktree list` |
| Locks | Keine stale Locks | `agentkit query-state --locks` |
| Audit-Export | Exportziel erreichbar | `agentkit export-telemetry --dry-run` |
| Reset-Faehigkeit | Offizieller Reset-Pfad verfuegbar | `agentkit reset-story --help` |
| Split-Faehigkeit | Offizieller Story-Split-Pfad verfuegbar | `agentkit split-story --help` |
| Konfliktaufloesung | Offizieller Freeze-/Resolution-Pfad verfuegbar | `agentkit resolve-conflict --help` |

### 4.2.2 Status-Befehl

```bash
agentkit status

# Output:
# AgentKit v1.0.0
# Config: .agentkit/config/project.yaml (v3.0)
# Project: TP
# GitHub Repo: acme-corp/trading-platform
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

## 4.3 Audit-Logs

### 4.3.1 Was geloggt wird

| Log | Speicherort | Inhalt |
|-----|------------|--------|
| Telemetrie (Laufzeit) | PostgreSQL | Alle Events |
| Telemetrie (Archiv) | Audit-Export / Objektspeicher | JSONL-Export gueltiger, nicht vollstaendig zurueckgesetzter Runs |
| Integrity-Violations | PostgreSQL (Event-Typ `integrity_violation`) | Guard-Blockaden |
| Integrity-Gate-Ergebnisse | PostgreSQL (Event-Typ `integrity_gate_result`) | FAIL-Codes |
| Governance-Adjudication | PostgreSQL (Event-Typ `governance_adjudication`) | Incident-Klassifikation |
| QA-Artefakte | PostgreSQL | Structural, LLM-Review, Adversarial, Policy |
| Failure Corpus | PostgreSQL / Artefaktspeicher | Incidents, Patterns, Checks |

### 4.3.2 Abfragen

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

## 4.4 Wöchentlicher Review-Slot

### 4.4.1 Zweck

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

### 4.4.2 Kein automatischer Trigger

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

## 4.5 Runbooks

### 4.5.1 LLM-Hub nicht erreichbar

```
Symptom: agentkit status zeigt den LLM-Hub als ERROR
Ursache: Hub nicht gestartet oder Modell-Login abgelaufen (Hub-intern)

Lösung:
1. Hub-Verfügbarkeit/Backends gemäß Hub-Betrieb wiederherstellen
   (Backend-Start/Login ist Hub-Deploymentdetail, nicht AK3)
2. Bei Login-Problem: am betroffenen Hub-Backend einloggen (Hub-intern)
3. Verifizieren: Hub-Health → "ok" (FK-75)
```

### 4.5.2 Stale Lock

```text
Symptom: Story kann nicht gestartet werden (Preflight-Anzeige: stale lock)
Ursache: Vorheriger Run abgestuerzt oder verwaist; Lock und Bindung
bestehen weiter (kein automatischer Entzug)

WICHTIG: Locks laufen nie automatisch ab. Es gibt kein Lease, kein
TTL und keine PID-/Prozess-Liveness-Heuristik. Die Stale-Anzeige (z. B.
letzter API-Kontakt) ist reine Information; Inaktivitaet ist keine
Diagnose (FK-10 §10.6.1/§10.6.2, Kap. 02.7). Der Mensch entscheidet
explizit ueber einen offiziellen Recovery-Pfad.

Loesung:
1. Zustand lesen (reine Information):
   agentkit status --story {story_id} (REST) bzw. Backend-State des Runs
2. Explizit-administrative Recovery-Entscheidung ueber einen offiziellen
   Pfad treffen (kein Warten auf Ablauf, kein manuelles Loeschen):
   - dieselbe Harness-Identitaet nimmt ihre Arbeit wieder auf →
     Session-Continuation via /resume (kein Transfer, kein
     Recovery-Ereignis; FK-56 §56.13g, FK-20 §20.7.3/§20.7.4)
   - Harness-Identitaet verloren / bewusster Clean-Slate →
     agentkit recover-story --story {story_id} (neuer Run,
     acquired_via=recovery; Uebernehmen/Verwerfen: FK-20 §20.7.3)
   - fremde aktive Session soll uebernommen werden →
     Ownership-Takeover (§4.5.10, FK-56 §56.13)
3. Nur bei bewusster Aufraeum-Entscheidung des Menschen:
   agentkit cleanup --story {story_id} (Worktree, Branch, Locks, Artefakte)
```

### 4.5.3 Integrity-Gate FAIL

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

### 4.5.4 Stagnation (Story ohne Fortschritt)

```
Symptom: Story seit > 4 Stunden in derselben Phase
Ursache: Agent hängt, Harness-Session (Claude Code / Codex; FK-76) abgelaufen, oder Loop

Lösung:
1. agentkit status --story {story_id}
2. Phase-State prüfen: `agentkit query-state --story {story_id}`
3. Telemetrie: letzte Events prüfen
4. Wenn Loop: agentkit reset-escalation --story {story_id}
5. Story-Anforderungen vereinfachen oder Mensch greift ein
```

### 4.5.5 Merge-Konflikt

```
Symptom: Closure ESCALATED mit Merge-Konflikt
Ursache: Main hat sich seit Story-Start weiterentwickelt

Lösung:
1. Offiziellen Closure-Retry pruefen: `POST /phases/closure/start` mit `no_ff: true` (Service-API FK-91 §91.1a) oder Operator-CLI `agentkit run-phase closure --story {story_id} --no-ff` (FK-91 §91.1)
2. Wenn Closure damit sauber abschliesst: Story normal beenden
3. Wenn weiterhin harter, nicht workflowfaehiger Konflikt vorliegt:
   Eskalation bestehen lassen und menschliche Entscheidung treffen
4. Nur wenn die Umsetzung als korrupt oder unbrauchbar gilt:
   `agentkit reset-story --story {story_id} --reason "..."`
```

### 4.5.6 Scope-Explosion / Story-Split

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
   - keine externe Tracker-Mutation
   - Nachfolger-Stories im Backlog
   - keine aktiven Locks / Worktrees der Ausgangs-Story
```

### 4.5.7 Autoritativer Snapshot-/Normkonflikt

```text
Symptom: Worker oder Verify stoppt mit Widerspruch zwischen
AK3-Story-Backend, story.md-Export, ARE-Bundle oder anderem
autoritativen Snapshot

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

### 4.5.8 Vollstaendiger Story-Reset

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
   - keine FK-69/FK-60ff-Ableitungen der korrupten Umsetzung
5. Story bei Bedarf neu starten
```

### 4.5.9 Permission-Block / externe Permission-Interferenz

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

<!-- PROSE-FORMAL: formal.state-storage.invariants, formal.operating-modes.invariants -->

Die folgenden vier Runbooks betreffen den Ownership-/In-Flight-Betrieb.
Sie sind reine Betriebssicht (Symptom → Ursache → Loesungsschritte ueber
offizielle Pfade) und definieren nichts neu: Protokoll, Zustaende und
Endpoints liegen bei den Owner-Konzepten (FK-56, FK-91, FK-30, FK-10,
FK-20) und den formalen Speicher-/Betriebsmodus-Invarianten
(`formal.state-storage.invariants`, `formal.operating-modes.invariants`).
Ein durchgaengiges Prinzip: **Nichts laeuft ab.** Ownership und In-Flight-
Claims enden nie durch Wanduhr, TTL, Lease-Ablauf oder Heartbeat-Verlust
(`operating-modes.invariant.ownership_transfer_requires_explicit_confirmed_request`,
FK-91 §91.1a Regel 16/17). Jeder Endweg ist eine explizite Entscheidung.

### 4.5.10 Ownership-Takeover

```text
Symptom: Ein aktiver Story-Run soll unter neuem Owner (andere Session)
fortgefuehrt werden — z. B. Reviewer/Operator uebernimmt eine haengende
oder abwesende Fremd-Session, oder ein Agent fordert die Uebernahme an
Ursache: Der Run gehoert noch der bisherigen Session; Ownership wird nie
automatisch entzogen (FK-56 §56.13 Grundsatz 1). Ein Wechsel ist nur der
offizielle Ownership-Transfer (Takeover)

WICHTIG: Der Transfer uebertraegt ausschliesslich den gepushten Stand
`takeover_base_sha` (Pushed-only, FK-56 §56.13c). Nicht gepushte Commits,
uncommittete und untracked Aenderungen der bisherigen Session sind kein
Uebergabegut (Verlustkorridor); sie werden lokal quarantaeniert, nie
stillschweigend mitgenommen.

Loesung:
1. Anfrage stellen (Begruendungspflicht, auditiert):
   agentkit takeover-request --story {story_id} --run {run_id} ...
   (REST: POST .../ownership/takeover-request, FK-91 §91.1a)
   Antwort ist nie der Vollzug, sondern ein versionierter Challenge:
   Eigentumslage (owner_session_id, ownership_epoch, binding_version),
   Kandidaten-SHA + Push-Frische und der Verlustkorridor-Pflichttext
   (FK-56 §56.13a/§56.13c). Letzter API-Kontakt ist Nicht-Diagnose.
2. Menschlich vollziehen (informierte Freigabe):
   agentkit takeover-confirm --story {story_id} --challenge-id {id} ...
   (REST: POST .../ownership/takeover-confirm). Der Confirm ist
   human-BFF-session-exklusiv (Strategen-Session; FK-91 §91.1) und
   waehlt die gespeicherte Challenge nur per challenge_id aus; der CAS
   laeuft serverseitig gegen die persistierte Challenge-Basis
   (FK-56 §56.13a). Kein Force-Pfad.
3. Agenten-initiierter Fall: Der anfragende Agent erhaelt deterministisch
   `pending_human_approval` (kein Vollzug). Ein Mensch gibt die Uebernahme
   im globalen Notification-Overlay des Frontends (FK-72) frei — eine
   agenteninitiierte Anfrage verlangt die Frontend-Freigabe (die CLI ist
   der Weg fuer den direkt menschlich initiierten Takeover, §4.5.10
   Schritt 1/2); den Ausgang beobachtet der Agent ueber
   GET .../operations/{op_id} (FK-56 §56.13b,
   `operating-modes.invariant.agent_initiated_takeover_requires_human_frontend_approval`).
   Die offene Freigabe darf wie jede Permission-Request verfallen (dann
   DENIED) — sie entzieht nie bestehendes Eigentum.
4. Wirkung auf den Ex-Owner pruefen: Die alte Session geht in
   binding_invalid mit Grund `ownership_transferred`; jeder mutierende
   Call wird deterministisch abgewiesen, Reads (inkl.
   GET .../operations/{op_id} zur eigenen Rekonsiliierung) bleiben
   erlaubt (FK-56 §56.13c, FK-91 §91.1a Regel 18). Der Ex-Owner erhaelt
   ueber den Disown-Baustein eine klare, maschinenlesbare Auskunft mit
   Grund (FK-56 §56.13h).
5. takeover_reconcile durch die NEUE Session ausfuehren und Betriebs-
   Befund aufloesen (siehe Tabelle). Offizieller Pfad:
   POST .../ownership/takeover-reconcile-worktree (SHA-Semantik gegen
   takeover_base_sha; FK-91 §91.1a, FK-30 §30.6.3).
```

Die vier Edge-Zustaende nach dem Transfer sind benannte Guard-Zustaende
(FK-30 §30.6.3), keine Sammel-FAILs — jeder hat einen definierten
Aufloesungscharakter:

| Betriebs-Befund | Bedeutung (Owner-Konzept) | Offizielle Aufloesung |
|---|---|---|
| `takeover_reconcile_required` | Normaler Startzustand des neuen Owners: Worktree noch nicht auf `takeover_base_sha` ausgerichtet (FK-30 §30.6.3, FK-56 §56.13e) | Reconcile ausfuehren — Quarantaene + Reprovisionierung, dann Meldung ueber `POST .../ownership/takeover-reconcile-worktree`. Keine menschliche Entscheidung noetig |
| `contested_local_writes` | Reconcile gescheitert oder Worktree-Identitaet nicht eindeutig — read-only Konflikt-Freeze (Admission-Blocker mit `freeze_epoch`/`freeze_reason`; FK-30 §30.6.3, FK-56 §56.13f) | Menschliche/administrative Entscheidung loest den Freeze; kein automatisches Fortfahren, kein manueller DB-Eingriff. Ownership bleibt `active` (nur Admission blockiert) |
| `remote_branch_diverged_after_takeover` | Remote-Head des Story-Branch weicht nach dem Confirm von `takeover_base_sha` ab (z. B. regelwidriger Ex-Owner-Push; FK-30 §30.6.3, FK-56 §56.13c) | Administrative Aufloesung; kein stilles Mitnehmen des divergierten Stands. Der SHA-Vergleich macht den Verstoss zuordenbar |
| `local_stale_or_dirty_takeover_target` | Am Provisionierungsziel liegt ein alter/schmutziger Worktree derselben Story (Reprovisionierungs-Fall; FK-30 §30.6.3, FK-56 §56.13e) | Quarantaene (gleiche Mechanik wie beim Same-Worktree-Reconcile); nie stilles Ueberschreiben |

### 4.5.11 Haengende In-Flight-Operation / admin_abort

```text
Symptom: Eine serverseitige Operation steht dauerhaft auf `claimed`; der
ausloesende Client ist weg (Verbindung gerissen, Prozess beendet)
Ursache: Der In-Flight-Claim ist instanzgebunden und laeuft NICHT ab —
weder Transport-Timeout noch Client-Stille beenden ihn (FK-91 §91.1a
Regel 16/17)

WICHTIG: Nicht auf Ablauf warten — es laeuft nichts ab. Kein Lease, kein
TTL, keine PID-Heuristik. Transport-/Proxy-Timeouts haben keine fachliche
Bedeutung (Regel 17).

Diagnose:
1. Lage rekonsiliieren, nicht raten:
   GET /v1/project-edge/operations/{op_id} (FK-91 §91.1a Regel 17)
2. Betrifft der Claim eine servereigene In-Flight-Operation? admin_abort
   adressiert servereigene Claims (geladen per `op_id`) und ist NICHT auf
   die eigene `backend_instance_id` beschraenkt — die Beschraenkung auf
   eigene fruehere Inkarnationen gilt nur fuer die Startup-Rekonsiliierung
   (§4.5.12), nicht fuer admin_abort (FK-91 §91.1a Regel 16).

Loesung (einziger manueller Endweg):
1. Administrativen Abbruch ausloesen — ausschliesslich ueber
   POST /v1/project-edge/operations/{op_id}/admin-abort
   (`admin_abort_inflight_operation`, Klasse `admin_transition`, FK-55;
   auditiert) oder den gleichbedeutenden CLI-Adapter (AG3-138). Betrifft
   ausschliesslich servereigene Claims und leitet nie Client-Ownership
   aus Stille ab (FK-91 §91.1a Regel 16).
2. Teil-Writes behandeln: Hat die abgebrochene Mutation bereits
   Teil-Writes hinterlassen, geht die Operation in einen expliziten,
   auditierten Reconcile-/Repair-Zustand statt stillschweigend in
   `failed` (FK-91 §91.1a admin-abort;
   `state-storage.invariant.operation_finalize_requires_cas_on_operation_epoch`).
   Der Operator behandelt diesen Zustand als Handlungsauftrag: den
   auditierten Reconcile-/Repair-Pfad abschliessen, nicht ignorieren.
3. Alt-Executor-Fence beachten: Ein physisch noch weiterlaufender
   Alt-Executor kann nach dem Abort nichts mehr finalisieren — das
   Finalize ist per `operation_epoch`-CAS gefenct; Late-Commits scheitern
   deterministisch und registrieren hoechstens einen No-op-/Abort-Vermerk
   (FK-91 §91.1a admin-abort).
```

### 4.5.12 Server-Boot / Startup-Rekonsiliierung

```text
Symptom: Verstaendnis, was ein Neustart der Control-Plane-Writer-Instanz
mit verwaisten Claims tut — bzw. der Start wird fail-closed verweigert
Ursache: Nach einem Absturz koennen Claims der eigenen frueheren
Inkarnation verwaist zurueckbleiben; sie muessen deterministisch
finalisiert werden, bevor Requests angenommen werden

Betriebsannahme (normativ): genau eine aktive Control-Plane-Writer-Instanz
pro Datenbank (FK-10 §10.5.4). Diese Ein-Writer-Annahme ist die Grundlage
der Startup-Rekonsiliierung.

Was der Boot deterministisch tut:
1. Vor Beginn der Request-Annahme finalisiert die Instanz verwaiste
   Claims IHRER EIGENEN Identitaet aus frueheren Inkarnationen: ein Claim
   ohne Teil-Writes wird `failed`, ein Claim mit bereits persistierten
   Teil-Writes geht in den auditierten Reconcile-/Repair-Zustand statt
   stillschweigend `failed` (Start-Rekonsiliierung; FK-10 §10.5.4,
   `state-storage.invariant.operation_finalize_requires_cas_on_operation_epoch`).
2. FREMDE Claims (andere `backend_instance_id`) bleiben unangetastet —
   der Server spekuliert nie ueber fremde Instanzen oder ueber
   Client-Stille (FK-91 §91.1a Regel 16,
   `state-storage.invariant.orphaned_claims_are_finalized_only_by_same_instance_startup_reconciliation_or_admin_abort`).

Loesung bei fail-closed verweigertem Start:
1. Scheitert die Start-Rekonsiliierung, nimmt die Instanz keine Requests
   an (fail-closed) — sie startet nicht mit halb finalisiertem Zustand.
2. Der Operator behebt die Ursache (DB-Erreichbarkeit/Integritaet); kein
   Bypass, kein manuelles Freigeben von Claims. Verbleibende
   servereigene In-Flight-Operationen werden ausschliesslich ueber
   admin_abort aufgeloest (§4.5.11), nie durch Warten auf Ablauf.
```

### 4.5.13 Deployment-/Migrationsreihenfolge (Ownership ohne TTL)

Dies ist eine **Betriebsregel**, kein Symptom-Runbook: die Reihenfolge,
in der die Ownership-ohne-TTL-Mechanik ausgerollt wird, ist verbindlich.

```text
Regel: Der Rollout folgt der harten Ordnung
  AG3-137  (Schema + Backfill laufender Runs)
    → AG3-138  (Startup-Rekonsiliierung + admin_abort produktiv)
      → AG3-139  (TTL-Entfall)
Eine Umkehrung oder ein Ueberspringen ist unzulaessig.

Begruendung (IMPL-006): Zwischen AG3-138 und AG3-139 darf KEIN
Deployment-Zustand ohne Verwaisungs-Handling existieren. Bis AG3-138
produktiv ist, war die Claim-TTL das EINZIGE Verwaisungs-Handling; sie
darf erst entfallen (AG3-139), nachdem Startup-Rekonsiliierung und
admin_abort (die beiden einzigen Endwege verwaister Claims,
`state-storage.invariant.orphaned_claims_are_finalized_only_by_same_instance_startup_reconciliation_or_admin_abort`)
tatsaechlich laufen. Andernfalls entstuende ein Fenster, in dem verwaiste
Claims weder ablaufen noch offiziell finalisiert werden koennen —
fail-closed-widrig.

Backfill-Hinweis (AG3-137): Der Backfill laufender Runs ist idempotent —
bestehende aktive Runs erhalten `ownership_epoch=1` und `status='active'`.
Wiederholtes Anwenden aendert nichts (Idempotenz).
```

## 4.6 Kapazitäts- und Kostensteuerung

### 4.6.1 Kosten

| Ressource | Kosten | Steuerung |
|-----------|--------|----------|
| Claude API (Worker, Orchestrator) | API-Kosten pro Token | Story-Größe begrenzen, Feedback-Loops begrenzen (max 3) |
| LLM-Hub (Browser-Backends) | Kostenlos | Kein API-Budget; Slot-Kapazität des Hubs begrenzt Parallelität |
| Weaviate (Docker) | Lokale Rechenleistung | CPU/RAM des Docker-Containers |
| Git-Remote/GitHub | Kostenlos (im Rahmen der Rate Limits) | Push/Merge-Operationen pro Story |
| Disk | Lokaler Speicher | Archivierung alter QA-Artefakte |

### 4.6.2 Parallelitäts-Limits

Die Parallelität ist durch die Slot-Kapazität des LLM-Hubs begrenzt
(Hub-internes Deploymentdetail; die konkreten Slot-Zahlen pro
Modell-Backend legt der Hub fest, nicht AK3).

Wenn alle Slots belegt sind, warten nachfolgende Aufrufe in der
Queue. Das ist eine natürliche Begrenzung der Parallelität —
kein zusätzliches Limit nötig.

## 4.7 Backup und Retention

### 4.7.1 Was gesichert werden sollte

| Daten | Wichtigkeit | Backup-Methode |
|-------|-----------|---------------|
| `.agentkit/config/project.yaml` | Hoch | Teil des Git-Repos |
| `.agentkit/ccag/rules/` (kanonisch; harness-spezifische Symlinks via Adapter, FK-76) | Hoch | Teil des Git-Repos |
| PostgreSQL | Hoch | Zentrales DB-Backup / PITR |
| Audit-Exports | Mittel | Objektspeicher / Archiv-Backup |

### 4.7.2 Retention

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
