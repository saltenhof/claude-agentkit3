---
concept_id: FK-53
title: StoryResetService und Recovery-Flow
module: story-reset
domain: story-lifecycle
status: active
doc_kind: core
parent_concept_id:
authority_over:
  - scope: story-reset
  - scope: reset-recovery-flow
  - scope: destructive-story-recovery
defers_to:
  - target: FK-17
    scope: fachliches-datenmodell
    reason: Story, Runtime-State, Audit und Reset-Grenzen bauen auf den Entitaeten aus FK-17 auf
  - target: FK-18
    scope: relationales-abbildungsmodell
    reason: Purge-Domaenen und Tabellenfamilien werden dort normiert
  - target: FK-20
    scope: workflow-engine-abgrenzung
    reason: Story-Reset ist explizit kein Teil der PipelineEngine
  - target: FK-04
    scope: runbooks
    reason: Operative Bedienung und Runbooks werden dort beschrieben
  - target: FK-69
    scope: qa-telemetry-read-models
    reason: Reset-Purge muss FK-69-Read-Models des betroffenen run_id konsistent entfernen
supersedes: []
superseded_by:
tags: [story-reset, recovery, purge, operations, reset]
prose_anchor_policy: strict
formal_refs:
  - formal.story-reset.entities
  - formal.story-reset.state-machine
  - formal.state-storage.state-machine
  - formal.state-storage.invariants
  - formal.state-storage.scenarios
  - formal.story-reset.commands
  - formal.story-reset.events
  - formal.story-reset.invariants
  - formal.story-reset.scenarios
---

# 53 — StoryResetService und Recovery-Flow

<!-- PROSE-FORMAL: formal.story-reset.entities, formal.story-reset.state-machine, formal.state-storage.state-machine, formal.state-storage.invariants, formal.state-storage.scenarios, formal.story-reset.commands, formal.story-reset.events, formal.story-reset.invariants, formal.story-reset.scenarios -->

## 53.1 Zweck

`StoryResetService` ist die administrative Recovery-Komponente fuer
Faelle, in denen eine eskalierte Story-Umsetzung nicht mehr ueber den
normalen Workflow repariert oder fortgesetzt werden kann.

Der Service fuehrt **keinen Resume-Pfad** aus. Er kappt die korrupt
gewordene Umsetzungs-Epoche, purgt deren operativen und abgeleiteten
Zustand und hinterlaesst eine neue, saubere Startbasis fuer eine
spaetere Neuaufnahme der Story.

## 53.2 Grundregeln

1. Ein vollstaendiger Story-Reset wird **nie automatisch** ausgefuehrt.
2. Ausloeser ist ausschliesslich ein ausdruecklicher menschlicher
   CLI-Befehl.
3. Der Orchestrator darf einen Reset hoechstens empfehlen,
   dokumentieren oder vorbereiten, nie selbst vollziehen.
4. Der Story-Reset ist **kein** Pipeline-Schritt, **kein** Override und
   **kein** normaler Recovery-Loop.
5. Die Story als fachliche Arbeitseinheit bleibt erhalten; die
   korrupt gewordene Umsetzung verschwindet vollstaendig.

## 53.3 CLI-Schnittstelle

Normativer Kontrollpfad:

```bash
agentkit reset-story --story ODIN-042 --reason "irreparabler merge-konflikt"
```

Pflichtparameter:

- `--story`
- `--reason`

Optionale weitere Parameter wie `--escalation-ref`, `--dry-run` oder
`--force` sind zulaessig, aendern aber nicht die Grundregel, dass der
Reset nur ueber den offiziellen AgentKit-CLI-Pfad erfolgen darf.

## 53.4 Eingangsbedingungen

Ein Reset ist nur zulaessig, wenn alle folgenden Bedingungen gelten:

1. Die Story existiert als fachlicher Datensatz.
2. Fuer die Story liegt ein belastbarer Eskalations- oder
   Ausnahmebefund vor.
3. Die menschliche Entscheidung zum vollstaendigen Reset wurde bewusst
   getroffen; ein Reset ist kein Routinepfad fuer normale Verify-Fails.
4. Es laeuft keine konkurrierende administrative Operation fuer
   dieselbe Story.

**Typischer Vorzustand:** `ESCALATED`.  
**Nicht erforderlich:** dass bereits jeder Restzustand manuell
aufgeraeumt wurde. Das Quiescing ist Aufgabe des Services selbst.

## 53.5 Autorisierung und Audit

Vor jedem destruktiven Schritt muss `StoryResetService`:

1. die menschliche Identitaet und Berechtigung pruefen
2. `story_id`, `reason` und optional `escalation_ref` binden
3. einen dauerhaften Reset-Vorgang (`reset_id`) anlegen
4. den Vorgang sofort auditierbar markieren

Minimaler Reset-Record:

- `project_key`
- `story_id`
- `reset_id`
- `requested_by`
- `reason`
- `escalation_ref`
- `requested_at`
- `status`

## 53.6 Fachliche Abgrenzung: Was bleibt, was verschwindet

### 53.6.1 Bleibt erhalten

- `Story`
- `StoryContext`, soweit er die fachliche Arbeitseinheit und ihre
  externen Referenzen beschreibt
- Story-Custom-Field-Werte, soweit sie Stammdaten oder Tracker-Status
  sind und nicht nur die korrupt gewordene Umsetzung spiegeln
- Reset-/Audit-Nachweis des Eingriffs

### 53.6.2 Wird vollstaendig entfernt

- `FlowExecution`
- `NodeExecution`
- `AttemptRecord`
- `OverrideRecord`
- `GuardDecision`
- `PhaseState`
- umsetzungsgebundene `ArtifactRecord`
- `ExecutionEvent`
- FK-69-Read-Models
- FK-60ff-Analytics-Ableitungen der korrupten Umsetzung
- story-bezogene Locks, Leases, Queue-/Retry-Zustaende
- ephemere Arbeitsartefakte, Worktree-Bindungen und tainted
  Arbeitsverzeichnisse

## 53.7 Reset-Flow

Der Service fuehrt die Recovery in einer festen Reihenfolge aus.

### 53.7.1 Schritt 1: Reset-Vorgang registrieren

Der Service legt den Reset-Vorgang mit `status = started` an.

Zweck:

- Audit-Anker
- Idempotenz-Anker
- Resume-Punkt bei Abbruch

### 53.7.2 Schritt 2: Story exklusiv fence'n

Vor jeder Loeschung muss die Story gegen neue Aktivitaet gesperrt
werden.

Der Service:

- erwirbt einen exklusiven Reset-Lock
- markiert die Story administrativ als `RESETTING`
- blockiert neue Starts, Resumes, Retries und Scheduler-Aufnahmen

**Regel:** Der Reset fenced die Story zuerst und loescht erst danach.

### 53.7.3 Schritt 3: Aktive Laufzeitteilnehmer quiescen

Der Service beendet oder entwertet alle noch aktiven Laufzeitbesitzer:

- Worker-Leases
- Heartbeats
- Retry-/Resume-Mechanismen
- story-bezogene Queue- oder Timer-Eintraege

Ziel ist nicht "sanft weitermachen", sondern "keine neue Mutation mehr
zulassen".

### 53.7.4 Schritt 4: Minimalen Beweis sichern

Vor dem Purge bleibt nur ein kleiner, dauerhafter Nachweis zurueck:

- `reset_id`
- `story_id`
- Eskalationsbezug
- Actor
- Grund
- grobe Purge-Zusammenfassung

Der Service legt **keine** verdeckte Schattenkopie des Runtime-State
als stillen Rueckweg an.

### 53.7.5 Schritt 5: Operativen Runtime-State purgen

Jetzt werden alle operativ steuernden Laufzeitobjekte entfernt.

Purge-Domaene:

- Execution
- Governance-Laufzeitreste
- PhaseState-Projektion
- story-bezogene Lock- und Lease-Objekte

**Regel:** Kein verbleibendes Objekt dieses Schritts darf einen
spaeteren Neustart, Resume oder Guard-Entscheid beeinflussen.

### 53.7.6 Schritt 6: Read Models und Analytics purgen

Nach dem Runtime-Purge entfernt der Service alle daraus abgeleiteten
Sichten:

- FK-69-Read-Models
- `fact_story`
- periodische Facts und Aggregationen, soweit der korrupte Run dort
  eingeflossen ist

Per Story gebundene Zeilen werden direkt geloescht; periodische
Aggregationen werden gezielt neu berechnet oder ersetzt.

**Regel:** Kein Dashboard und keine KPI-Sicht darf spaeter ueber
Query-Filter kompensieren muessen, dass ein zurueckgesetzter Run noch
in Facts steckt.

### 53.7.7 Schritt 7: Ephemere Arbeitsoberflaechen entfernen

Der Service entfernt alle lokalen und zentralen Arbeitsreste der
korrupten Umsetzung:

- temp-/scratch-Verzeichnisse
- Adversarial-Sandboxes
- story-bezogene Exportartefakte
- materialisierte Guard-/Lock-Exporte

### 53.7.8 Schritt 8: Worktree und Branch behandeln

Der aktive Worktree der korrupten Umsetzung gilt als tainted und darf
nicht als lebende Arbeitsbasis erhalten bleiben.

Normative Regeln:

1. Der aktuelle Story-Worktree wird entfernt oder dauerhaft von der
   Story entkoppelt.
2. Ein Reset fuehrt **nicht** zu einer "weiterverwenden und nur DB
   leeren"-Semantik.
3. Ein vorhandener Story-Branch bleibt hoechstens als forensischer
   Referenzstand bestehen, aber nicht als aktive Runtime-Basis.
4. Nach dem Reset beginnt eine spaetere Neuaufnahme auf einer neuen
   sauberen Arbeitsbasis.

## 53.8 Endzustand

Ein erfolgreicher Reset hinterlaesst:

- die Story als fachliche Arbeitseinheit
- keinen laufenden oder resumierbaren Run
- keine aktiven Locks oder Worker-Besitzer
- keine Read Models oder Analytics-Reste der korrupten Umsetzung
- keine tainted Arbeitsoberflaeche
- einen auditierbaren Reset-Nachweis

Die Story landet fachlich in einem **nicht laufenden, restartbaren
Grundzustand**. Ein spaeterer Neustart ist eine neue Umsetzungs-Epoche,
nicht die Fortsetzung des alten Runs.

## 53.9 Fehlerbehandlung und Idempotenz

Ein Story-Reset ist keine einzelne globale ACID-Transaktion ueber
Datenbank, Git, Queue und Dateisystem. Der Service arbeitet deshalb als
checkpointfaehiger administrativer Flow.

### 53.9.1 Idempotenzregeln

Jeder Purge-Schritt muss konvergent sein:

- loeschen, wenn vorhanden
- ignorieren, wenn bereits weg
- hart fehlschlagen nur bei echten Infrastruktur- oder
  Berechtigungsproblemen

Ein erneuter Lauf mit derselben `reset_id` ist ein Resume, kein neuer
Reset.

### 53.9.2 Fehlerzustand

Wenn der Reset mitten im Ablauf scheitert:

1. bleibt die Story administrativ blockiert
2. darf kein normaler Neustart erfolgen
3. muss der Service denselben Reset-Vorgang gezielt wiederaufnehmen
   koennen

**Normative Regel:** `RESET_FAILED` ist nicht runnable.

### 53.9.3 Abschlussregel

Der Reset-Lock wird erst ganz am Ende freigegeben, nachdem:

- alle Purge-Domaenen erfolgreich abgeschlossen sind
- der Endzustand verifiziert wurde
- der Reset-Record auf `completed` gesetzt ist

## 53.10 Minimale Service-Schnittstelle

Fachlich liefert `StoryResetService` mindestens diese Operationen:

- `request_reset(...)`
- `execute_reset(reset_id)`
- `resume_reset(reset_id)`
- `verify_reset_clean_state(reset_id)`

Die Implementierung darf intern weitere Schritte besitzen, aber diese
vier Operationen bilden den minimalen fachlichen Vertrag.
