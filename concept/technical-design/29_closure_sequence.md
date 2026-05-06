---
concept_id: FK-29
title: Closure-Sequence
module: closure-sequence
domain: story-closure
status: active
doc_kind: core
parent_concept_id:
authority_over:
  - scope: closure-sequence
  - scope: closure-progress
  - scope: finding-resolution-gate
  - scope: postflight-gates
  - scope: execution-report
  - scope: guard-deactivation
  - scope: story-metric-schema
  - scope: workflow-metric-schema
glossary:
  exported_terms:
    - id: closure-payload
      definition: >
        Phasenspezifische Payload fuer die Closure-Phase als diskriminierte Union
        im PhaseState (payload.type == "closure"). Enthaelt ausschliesslich ein
        ClosureProgress-Objekt als durable Contract Field. Eigentuemerschaft liegt
        beim story-closure BC; Mechanik der diskriminierten Union bei pipeline-framework.
      see_also:
        - term: phase-payload
          domain: pipeline-framework
    - id: closure-progress
      definition: >
        Typisiertes Objekt mit sechs granularen Booleans innerhalb von ClosurePayload,
        das den Fortschritt der Closure-Substates checkpoint-sicher abbildet:
        integrity_passed, story_branch_pushed, merge_done, story_closed,
        metrics_written, postflight_done. Jedes Boolean markiert einen irreversiblen
        Abschluss-Checkpoint; bei Crash-Recovery werden abgeschlossene Schritte
        uebersprungen.
    - id: closure-sequence
      definition: >
        Die normativ festgelegte, geordnete Abfolge von elf Closure-Schritten
        mit irreversiblen Seiteneffekten: Finding-Resolution-Gate,
        Integrity-Gate, Story-Branch-Push, Merge, Worktree-Teardown,
        Story-Closed (AK3-Story-Status Done), Metriken, Rueckkopplungstreue, Postflight-Gates,
        VektorDB-Sync, Guard-Deaktivierung. Reihenfolge ist Pflicht (FK-05-226);
        kein Schritt darf vorgezogen oder uebersprungen werden.
    - id: closure-verdict
      definition: >
        Ergebnis der vollstaendigen Closure-Sequence fuer eine Story. Moegliche
        Werte: COMPLETED (alle Substates erfolgreich abgeschlossen) oder
        ESCALATED (mindestens ein harter Blocker — Finding-Resolution-FAIL,
        Integrity-Gate-FAIL, Push-Fehler oder Merge-Fehler). Es gibt keinen
        degradierten Abschluss-Modus.
      values:
        - COMPLETED
        - ESCALATED
    - id: execution-report
      definition: >
        Konsolidierter Markdown-Report, der am Ende jeder Story-Bearbeitung
        unabhaengig vom Ergebnis erzeugt wird (_temp/qa/{story_id}/execution-report.md).
        Enthaelt Summary Table, Failure Diagnosis, Artifact Health, Errors and Warnings,
        Structural Check Results, Policy Engine Verdict, Closure Sub-Step Status,
        Telemetry Event Counts und Integrity Violations Log. Graceful Degradation:
        fehlende Artefakte werden als MISSING dokumentiert, der Report wird nicht
        abgebrochen.
    - id: finding-resolution-gate
      definition: >
        Eigenstaendiger Closure-Gate-Check vor dem Integrity-Gate, der alle drei
        Layer-2-QA-Artefakte (qa_review.json, semantic_review.json, doc_fidelity.json)
        auf vollstaendige Finding-Resolution prueft. Closure blockiert fail-closed,
        wenn mindestens ein Finding den Status partially_resolved oder not_resolved
        hat. Entfaellt vollstaendig fuer Concept- und Research-Stories.
    - id: guard-deactivation
      definition: >
        Letzter Schritt der Closure-Sequence nach erfolgreichem Postflight: Beenden
        des Lock-Records im State-Backend und Entfernen optionaler Lock-Exporte
        (_temp/governance/locks/{story_id}/qa-lock.json und .agent-guard/lock.json).
        Ab diesem Zeitpunkt ist der AI-Augmented-Modus wieder aktiv (Branch-Guard,
        Orchestrator-Guard und QA-Schutz inaktiv).
    - id: merge-policy
      definition: >
        Offiziell zulaessige Merge-Strategie in der Closure-Sequence. Default ist
        ff_only (Merge ohne Merge-Commit). Einziger offizieller Fallback ist no_ff
        (Merge mit explizitem Merge-Commit) fuer dokumentierte Closure-Retries.
        Manuelle Rebases und Force-Pushes sind kein zulaessiger Closure-Fix.
      values:
        - ff_only
        - no_ff
    - id: postflight-gates
      definition: >
        Fuenf deterministische Konsistenzpruefungen nach erfolgreichem Merge und
        Story-Closed: story_dir_exists, story_closed, metrics_set,
        telemetry_complete, artifacts_complete. Ein Postflight-FAIL ist
        nicht-blockierend (Code ist bereits auf Main); der Mensch entscheidet
        ueber Nacharbeit. Kein automatischer Rollback.
defers_to:
  - target: FK-27
    scope: qa-subflow
    reason: Closure laeuft erst nach abgeschlossener Implementation-Phase (inkl. QA-Subflow PASS); konsumiert Layer-2-Artefakte (FK-27 §27.5.5)
  - target: FK-35
    scope: integrity-gate
    reason: Integrity-Gate-Definition, 8 Dimensionen, Pflicht-Artefakt-Vorstufe und Audit-Log liegen normativ in FK-35 §35.2
  - target: FK-20
    scope: workflow-engine
    reason: Phase-Runner-Recovery und Workflow-Engine-Mechanik in FK-20
  - target: FK-39
    scope: closure-payload
    reason: ClosurePayload als diskriminierte Union in FK-39 §39.2.3
  - target: FK-38
    scope: feedback-doc-fidelity
    reason: Rückkopplungstreue (Ebene 4) und Finding-Resolution-Quelle aus Layer-2-Artefakten in FK-38
  - target: FK-32
    scope: doc-fidelity
    reason: Fachliche Definition der Dokumententreue-Ebenen
  - target: FK-26
    scope: handover-paket
    reason: Closure konsumiert Worker-Manifest-Stand
  - target: FK-12
    scope: github-merge
    reason: Branch-Push, Merge-Policy, Code-Repo-Mechanik
  - target: FK-13
    scope: vector-db-sync
    reason: VektorDB-Sync nach erfolgreichem Closure
  - target: FK-41
    scope: incident-candidate
    reason: Postflight- und Doc-Fidelity-FAIL erzeugen Incident-Kandidaten
  - target: FK-71
    scope: artefakt-envelope
    reason: closure.json folgt dem Envelope-Schema und ist in der Producer-Registry verzeichnet (FK-71)
supersedes: []
superseded_by:
tags: [closure, integrity-gate, finding-resolution, postflight, execution-report, guard-deactivation]
prose_anchor_policy: strict
formal_refs:
  - formal.story-closure.entities
  - formal.story-closure.state-machine
  - formal.story-closure.commands
  - formal.story-closure.events
  - formal.story-closure.invariants
  - formal.story-closure.scenarios
  - formal.story-workflow.state-machine
  - formal.story-workflow.invariants
  - formal.story-workflow.scenarios
---

# 29 — Closure-Sequence

<!-- PROSE-FORMAL: formal.story-closure.entities, formal.story-closure.state-machine, formal.story-closure.commands, formal.story-closure.events, formal.story-closure.invariants, formal.story-closure.scenarios, formal.story-workflow.state-machine, formal.story-workflow.invariants, formal.story-workflow.scenarios -->

## 29.1 Closure-Phase

### 29.1.0 ClosurePayload — durable Contract Fields

> **[Entscheidung 2026-04-09]** `ClosurePayload` führt `ClosureProgress` als typisiertes Objekt mit granularen Booleans. Granularität ist notwendig, weil "nach Merge vor Story-Closed" als Recovery-Zustand eindeutig identifizierbar sein muss. Ein grobes `current_substate`-Enum würde diese Eindeutigkeit nicht liefern. Verweis auf Designwizard R1+R2 vom 2026-04-09.

`ClosurePayload` ist die phasenspezifische Payload für die Closure-Phase (diskriminierte Union, FK-39 §39.2.3):

```python
class ClosureProgress(BaseModel):
    integrity_passed: bool = False
    story_branch_pushed: bool = False
    merge_done: bool = False
    story_closed: bool = False
    metrics_written: bool = False
    postflight_done: bool = False

class ClosurePayload(BaseModel):
    phase_type: Literal["closure"]
    progress: ClosureProgress = Field(default_factory=ClosureProgress)
```

`ClosureProgress` hat Recovery-Relevanz: Jedes Boolean entspricht einem abgeschlossenen Closure-Substate. Bei Crash und Wiederaufnahme (§29.1.3) überspringt der Phase Runner alle Schritte, deren Boolean bereits `true` ist.

**Granularität:** Die Einzelbooleans sind notwendig, weil Closure-Substates nicht zurückgerollt werden können (Merge ist irreversibel, der Story-Status-Wechsel auf Done ist ein authoritativer Backend-Seiteneffekt). Ein einziges `current_substate`-Enum würde den Zustand "nach Merge, vor Story-Closed" nicht eindeutig von "vor Merge" unterscheiden.

### 29.1.1 Voraussetzung

Closure wird nur aufgerufen, wenn die Implementation-Phase mit
COMPLETED endet. Das schliesst den intern in der Implementation-Phase
durchlaufenen QA-Subflow (FK-27, ehemals "Verify-Phase") ein:
Implementation kann nur dann mit COMPLETED enden, wenn der QA-Subflow
mit `qa_cycle_status = pass` abgeschlossen wurde. **Ausnahme: Concept-
und Research-Stories** durchlaufen keinen QA-Subflow — fuer diese
Story-Typen wird Closure direkt nach der Implementation-Phase
aufgerufen. `integrity_passed` und `merge_done` werden fuer
Concept/Research direkt auf `true` gesetzt (kein Worktree, kein
Branch-Merge, FK-20 §20.8.2).

> **[Entscheidung 2026-05-01]** Closure-Precondition lautet jetzt
> "Implementation COMPLETED" statt "Verify COMPLETED". Die Top-Phase
> `verify` ist entfallen; Output-QA ist interner Subflow innerhalb
> der Implementation-Phase (analog zum Exit-Gate der
> Exploration-Phase, FK-23 §23.5). Die Capability `VerifySystem`
> bleibt als Bounded-Context-Capability bestehen und wird sowohl von
> `ExplorationPhase` als auch von `ImplementationPhase` aufgerufen.
> Siehe `concept/_meta/bc-cut-decisions.md` "Verify als Capability
> (Variante Y)".

**REF-034:** Fuer Exploration-Mode-Stories gilt: Der QA-Subflow laeuft
innerhalb der Implementation-Phase, also NACH der vollstaendigen
Exploration-Phase (einschliesslich Design-Review-Gate). Das
Design-Review-Gate (`ExplorationGateStatus.APPROVED`) wird durch den
Phase-Runner-Guard am Uebergang `exploration -> implementation`
erzwungen (FK-20 §20.4.2a). Wenn Closure erreicht wird, ist `APPROVED`
durch die State-Machine-Invariante garantiert — kein erneuter
Payload-Zugriff noetig. [Korrektur 2026-04-09: Direkte Referenz auf
`ExplorationPayload.gate_status` aus dem QA-Subflow entfernt —
ExplorationPayload ist nicht der aktive Payload in der
Implementation-Phase (aktiv: ImplementationPayload). Die Garantie
stammt aus dem Transition-Guard, nicht aus einem Laufzeit-Check im
QA-Subflow.] [Entscheidung 2026-05-01: ehemals "Verify-Phase" / "VerifyPayload" — jetzt QA-Subflow innerhalb Implementation / ImplementationPayload.]

**REF-036 / FK-37 §37.1:** Die QA-Tiefe wird ueber `verify_context`
gesteuert, nicht ueber `mode`. Nach Worker-Run innerhalb der
Implementation-Phase gilt `verify_context = VerifyContext.POST_IMPLEMENTATION`,
nach einer Subflow-internen Remediation-Iteration
`verify_context = VerifyContext.POST_REMEDIATION` — beide loesen den
vollen 4-Schichten-QA-Subflow aus, unabhaengig davon, ob die Story im
Exploration- oder Execution-Modus gestartet wurde. `verify_context`
ist Subflow-internes Diskriminator-Feld auf `ImplementationPayload`
(FK-39 §39.2.3). [Korrektur 2026-04-09: `STRUCTURAL_ONLY_PASS` und
`post_exploration` entfernt — der QA-Subflow laeuft immer mit voller
Pipeline (FK-37 §37.1.5).] [Entscheidung 2026-05-01: `verify_context`
liegt jetzt auf `ImplementationPayload`, nicht mehr auf
`VerifyPayload`.]

> **[Entscheidung 2026-04-08]** Element 17 — Alle 11 Eskalations-Trigger werden beibehalten. FK-20 §20.6.1 und FK-35 §35.4.2 normativ. Kein Trigger ist redundant.
> Siehe `stories/entscheidung-v2-ballast-bewertung.md`, Element 17.

### 29.1.2 Ablauf mit Substates

```mermaid
flowchart TD
    START(["Service: POST /phases/closure/start<br/>{story_id: ODIN-042}"]) --> STYPE{Story-Typ?}

    STYPE -->|"impl / bugfix"| FR
    STYPE -->|"concept / research<br/>(kein QA-Subflow, kein Merge)"| CR_SUB1["Substate:<br/>integrity_passed = true<br/>story_branch_pushed = true<br/>merge_done = true<br/>(direkt gesetzt, §29.1.1)"]
    CR_SUB1 --> CLOSE_CR["Story-Status: Done<br/>(AK3-Story-Service)"]
    CLOSE_CR --> SUB3

    FR["Finding-Resolution-Gate<br/>(§29.2)"]
    FR -->|"FAIL: Ungelöste Findings"| ESC_FR(["ESCALATED:<br/>Offene Findings."])
    FR -->|PASS| INTEGRITY

    INTEGRITY["Integrity-Gate<br/>(agentkit.governance.integrity_gate;<br/>FK-35 §35.2: Pflicht-Artefakt-Vorstufe +<br/>8 Dimensionen +<br/>Telemetrie-Korrelation)"]
    INTEGRITY -->|FAIL| ESC_I(["ESCALATED:<br/>Opake Meldung.<br/>Details in Audit-Log."])
    INTEGRITY -->|PASS| SUB1["Substate:<br/>integrity_passed = true"]

    SUB1 --> PUSH_SB["Story-Branch pushen<br/>(git push origin story/{story_id})"]
    PUSH_SB -->|Push-Fehler| ESC_P(["ESCALATED:<br/>Story-Branch-Push fehlgeschlagen."])
    PUSH_SB -->|Erfolg| SUB_PUSH["Substate:<br/>story_branch_pushed = true"]

    SUB_PUSH --> MERGE["Branch mergen<br/>(Default: git merge --ff-only)<br/>Fallback: git merge --no-ff"]
    MERGE -->|Merge-Fehler| ESC_M(["ESCALATED:<br/>Merge fehlgeschlagen.<br/>Closure-Retry mit offizieller Merge-Policy prüfen."])
    MERGE -->|Erfolg| PUSH_MAIN["Main pushen<br/>(git push origin main)"]
    PUSH_MAIN -->|Push-Fehler| ESC_PM(["ESCALATED:<br/>Main-Push fehlgeschlagen.<br/>Lokaler Merge wird zurueckgesetzt."])
    PUSH_MAIN -->|Erfolg| SUB2["Substate:<br/>merge_done = true"]

    SUB2 --> TEARDOWN["Worktree aufräumen<br/>Branch löschen"]
    TEARDOWN --> CLOSE["Story-Status: Done<br/>(AK3-Story-Service)"]
    CLOSE --> SUB3["Substate:<br/>story_closed = true"]

    SUB3 --> STATUS["Projektstatus: Done<br/>+ QA Rounds, Completed At"]
    STATUS --> SUB4["Substate:<br/>metrics_written = true"]

    SUB4 --> DOCTREUE4["Dokumententreue Ebene 4:<br/>Rückkopplungstreue<br/>(agentkit.verify_system.llm_evaluator;<br/>StructuredEvaluator, FK-34)"]
    DOCTREUE4 -->|"FAIL (non-blocking)"| WARN_DT(["Warnung an Mensch<br/>(FK-38 §38.3.1)"])
    DOCTREUE4 -->|"PASS"| POSTFLIGHT["Postflight-Gates"]
    WARN_DT --> POSTFLIGHT
    POSTFLIGHT -->|"FAIL (non-blocking)"| WARN_PF(["Warnung an Mensch<br/>(§29.3.2)"])
    POSTFLIGHT -->|"PASS"| SUB5["Substate:<br/>postflight_done = true"]
    WARN_PF --> SUB5

    SUB5 --> VDBSYNC["VektorDB-Sync<br/>(async, Fire-and-Forget)"]
    VDBSYNC --> GUARDS_OFF["Guards deaktivieren:<br/>Governance.deactivate_locks(story_id)<br/>(agentkit.governance)"]
    GUARDS_OFF --> DONE(["Story abgeschlossen"])
```

### 29.1.3 Substates und Recovery

[Entscheidung 2026-04-09: `closure_substates` ersetzt durch
`ClosurePayload.progress` (Typ `ClosureProgress`). Die Bool-
Felder liegen jetzt unter `payload.progress.*` im Phase-State.]

Die sechs ClosureProgress-Booleans markieren die kritischen
Checkpoints mit Crash-Recovery-Relevanz. Weitere Schritte
(Finding-Resolution-Gate, VectorDB-Sync, Guards-Off) werden nicht
separat im Progress-Feld verfolgt — Finding-Resolution ist eine
Vorstufe, VectorDB-Sync und Guards-Off sind idempotente
Fire-and-Forget-Operationen. Bei Crash: Recovery setzt beim letzten
bestätigten Fortschrittsfeld wieder an (FK-10 §10.5.3).

```python
class ClosureProgress(BaseModel):
    integrity_passed: bool = False
    story_branch_pushed: bool = False
    merge_done: bool = False
    story_closed: bool = False
    metrics_written: bool = False
    postflight_done: bool = False

class ClosurePayload(BaseModel):
    progress: ClosureProgress
```

Im Phase-State (`phase-state.json`):

```json
"payload": {
  "progress": {
    "integrity_passed": true,
    "story_branch_pushed": true,
    "merge_done": true,
    "story_closed": false,
    "metrics_written": false,
    "postflight_done": false
  }
}
```

Zugriff: `payload.progress.integrity_passed`,
`payload.progress.story_branch_pushed`,
`payload.progress.merge_done` etc.

Bei erneutem Aufruf (Service: `POST /phases/closure/start` oder Operator-CLI `agentkit run-phase closure`):

- Story-Branch-Push wird übersprungen, wenn
  `payload.progress.story_branch_pushed == true`
- Merge wird übersprungen, wenn
  `payload.progress.merge_done == true`
- Story-Status-Wechsel auf Done wird ausgeführt, wenn
  `payload.progress.story_closed == false`

Teardown (Worktree aufräumen, Branch löschen) ist idempotent — er wird bei jedem Recovery-Lauf mit `merge_done == true && story_closed == false` erneut ausgeführt. Ein eigenes `teardown_done`-Feld ist nicht erforderlich, da ein fehlgeschlagener oder bereits erledigter Teardown keinen Datenverlust verursacht.

### 29.1.4 Reihenfolge ist Pflicht (FK-05-226)

Die Reihenfolge stellt sicher, dass eine Story nie auf Done gesetzt
wird, wenn der Merge scheitert:

1. Erst Finding-Resolution-Gate (§29.2) → sicherstellt: alle Findings vollständig aufgelöst
2. Erst Integrity-Gate (FK-35 §35.2) → sicherstellt: Prozess wurde durchlaufen
3. Erst Story-Branch pushen → Remote enthält den finalen Integrationsstand
4. Erst mergen → Code ist auf Main
5. Erst Worktree aufräumen → kein staler Worktree
6. Dann Story-Status auf Done setzen (AK3-Story-Service) → fachlich abgeschlossen
7. Dann Metriken → Nachvollziehbarkeit
8. Dann Rückkopplungstreue (FK-38 §38.3) → Doku aktuell?
9. Dann Postflight → Konsistenzprüfung
10. Dann VektorDB-Sync → für nachfolgende Stories suchbar
11. Zuletzt Guards deaktivieren → AI-Augmented-Modus wieder frei

### 29.1.5 Merge-Policy

Closure kennt zwei offizielle Merge-Policies:

| Merge-Policy | Bedeutung | Verwendung |
|--------------|-----------|-----------|
| `ff_only` | Merge ohne Merge-Commit | Default |
| `no_ff` | Merge mit explizitem Merge-Commit | Offizieller Fallback-/Recovery-Pfad |

**Verbotene Recovery:** Manuelle Rebases, Force-Pushes oder
Guard-Umgehungen sind kein zulässiger Closure-Fix.

**Zulässige Recovery:** Ein dokumentierter Closure-Retry mit der
offiziellen Merge-Policy `no_ff`.

### 29.1.6 Multi-Repo-Closure (Atomicity)

[Entscheidung 2026-05-04 — Multi-Repo-Closure ist atomar] Bei Stories
mit mehreren teilnehmenden Repos (`participating_repos` mit |N| >= 2,
FK-22 §22.6) ist die Closure **atomar ueber alle teilnehmenden Repos**:
entweder werden alle N Repos gemerged und gepusht, oder kein einziger
Merge wird auf `main` sichtbar gelassen. Eine partial-merged Story ist
ein **defekter Endzustand** und nicht zulaessig.

#### 29.1.6.1 Sequenz

Die Reihenfolge aus §29.1.4 gilt unveraendert; Schritte 3 (Push), 4
(Merge) und 5 (Teardown) werden bei Multi-Repo zu **Stufen ueber alle
Repos** ausgepraegt. Die nachfolgenden Stufen 1-5 sind die Multi-Repo-
Auspraegung dieser drei Schritte aus der Single-Repo-Sequenz; alles
nach Teardown (Story-Closed, Metriken, Postflight, VektorDB-Sync,
Guards-Off; §29.1.4 Schritte 6-11) laeuft pro-Story und ist nicht
multi-repo-aufgespalten.

1. **Stufe 1 — Pre-Merge-Check (vor Push):** fuer jedes teilnehmende
   Repo wird geprueft, ob `story/{story_id}` ff-mergebar gegen den
   aktuellen `origin/main` ist. Auch ein einziger nicht-ff-faehiger
   Repo blockiert die gesamte Closure (ESCALATED, kein Push, kein
   Merge).
2. **Stufe 2 — Push der Story-Branches:** alle Story-Branches werden
   gepusht. Erst nach Erfolg in **allen** teilnehmenden Repos wird
   `payload.progress.story_branch_pushed = true` gesetzt. Bei
   Push-Fehler in Repo k werden bereits gepushte Branches nicht
   ausgerollt (Push ist remote-irreversibel ohne force-push), die
   Closure escaliert mit Hinweis auf den partial-push-Zustand.
3. **Stufe 3 — lokal-atomarer FF-Merge:** alle teilnehmenden
   Worktrees fuehren `git merge --ff-only` lokal aus. Vor jedem Merge
   wird der `pre_merge_sha` des Ziel-Branches festgehalten. Wenn
   Merge in Repo k fehlschlaegt, werden alle bereits lokal gemergten
   Repos via `git reset --hard <pre_merge_sha>` zurueckgesetzt
   (lokale Atomicity-Garantie). Closure escaliert.
4. **Stufe 4 — Push-zu-main:** alle gemergten Hauptbranches werden
   gepusht. Bei Push-Fehler in Repo k bleiben Repos 1..k-1 permanent
   auf den Remotes; Repos k..N werden lokal zurueckgesetzt; Closure
   escaliert mit explizitem **Partial-Push-State** (siehe §29.1.6.3).
5. **Stufe 5 — Teardown:** Worktrees aller teilnehmenden Repos werden
   aufgeraeumt, Story-Branches lokal geloescht. Idempotent.

`payload.progress.merge_done = true` wird erst gesetzt, wenn Stufe 5
erfolgreich abgeschlossen ist UND Stufe 4 fuer alle Repos PASS
gemeldet hat. Ein einzelner Repo-Push-Fehler in Stufe 4 verhindert
das Setzen von `merge_done`.

#### 29.1.6.2 ClosureProgress bei Multi-Repo

Die sechs `ClosureProgress`-Booleans (§29.1.0) bleiben pro-Story, nicht
pro-Repo. Recovery-Granularitaet auf Repo-Ebene wird ueber separate
Substate-Felder im `ClosurePayload.multi_repo`-Block dokumentiert:

```python
class MultiRepoClosureState(BaseModel):
    pre_merge_check_passed: list[str] = Field(default_factory=list)
    pushed_repos: list[str] = Field(default_factory=list)
    merged_repos: list[str] = Field(default_factory=list)
    rolled_back_repos: list[str] = Field(default_factory=list)
    failed_repo: str | None = None
```

Diese Liste wird NUR fuer Multi-Repo-Stories gefuehrt; bei
Single-Repo-Stories bleibt das Feld leer und wird ignoriert.

#### 29.1.6.3 Partial-Push-State (Stufe 3 Failure)

Cross-Remote-Atomicity ueber mehrere Git-Hosts ist nicht erreichbar.
Wenn in Stufe 4 (Push-zu-main) Repo k push-failed, nachdem Repos
1..k-1 bereits auf `origin/main` gepusht wurden, ist der Zustand
nicht mehr automatisch rueckgaengig zu machen. Closure setzt:

- `closure_verdict = ESCALATED`
- `multi_repo.pushed_repos = [r1, ..., r_{k-1}]`
- `multi_repo.failed_repo = r_k`
- Repos `r_{k+1}..r_N` werden lokal via `git reset --hard <pre_merge_sha>`
  zurueckgesetzt (nicht gepusht, nicht gemerged auf Remote)

Der Mensch entscheidet:

a) **Force-revert** der bereits gepushten Repos via dokumentiertem
   `git revert <merge_sha>` + Push (kein force-push), oder
b) **Closure-Retry** der verbleibenden Repos, sobald die Ursache
   behoben ist (typischerweise temporaerer Remote-Fehler).

Beide Pfade sind dokumentierte Recovery-Operationen und keine
Guard-Umgehung.

#### 29.1.6.4 Implementations-Anker

Die AK2-Implementierung (`agentkit.worktree.merge.merge_story_multi_repo`
mit `pre_merge_sha`-Rollback) ist die fachliche Vorlage. Die AK3-
Umsetzung lebt im BC `story-closure` und respektiert die
ClosureProgress-Granularitaet aus §29.1.0.

## 29.2 Finding-Resolution als Closure-Gate (FK-27-221 bis FK-27-225)

### 29.2.1 Prinzip

Closure blockiert, wenn mindestens ein Finding aus dem Layer-2-Output
den Resolution-Status `partially_resolved` oder `not_resolved` hat.
Es gibt keinen degradierten Modus — ein offenes Finding ist ein
harter Blocker.

**Ausnahme Concept/Research:** Fuer Concept- und Research-Stories
entfallen Finding-Resolution-Gate UND Integrity-Gate vollstaendig (kein
Layer-2-QA, kein QA-Subflow, kein Merge). `integrity_passed` und
`merge_done` werden direkt auf `true` gesetzt; der Closure-Ablauf
startet effektiv bei `story_closed` (§29.1.2 Concept/Research-Pfad im
Flowchart).

**Provenienz:** DK-04 §4.6. Empirischer Beleg BB2-012: Worker
markierte ein Finding als `ADDRESSED`, obwohl nur ein Teilfall
behoben war. Das System uebernahm die Teilbehebung als
Vollbehebung, weil keine andere Instanz den Finding-Status setzte.

### 29.2.2 Quelle des Resolution-Status (FK-27-222)

Der Resolution-Status kommt ausschliesslich aus den Layer-2-QA-
Review-Checks (`agentkit.verify_system.llm_evaluator`,
`StructuredEvaluator` im Remediation-Modus, FK-34).
Es gibt keine eigene Quelle und kein separates Artefakt:

- **Kanonisch:** Layer-2-Evaluator (`agentkit.verify_system.llm_evaluator`)
  bewertet pro Finding: `fully_resolved`, `partially_resolved`, `not_resolved`
- **Nicht kanonisch:** Worker-Artefakte (`protocol.md`,
  `handover.json`) — diese haben Trust C und duerfen den Status
  eines Findings nicht autoritativ setzen (DK-04 §4.2)

Die Bewertung erfolgt als zusaetzliche Check-IDs in den bestehenden
Layer-2-Artefakten (`qa_review.json`, `semantic_review.json`, `doc_fidelity.json`, FK-27 §27.5.5). Kein
neues Artefakt.

### 29.2.3 Finding-Laden im Remediation-Zyklus (FK-27-223)

Im Remediation-Zyklus (Runde 2+) werden die Findings der Vorrunde
direkt aus den Review-Artefakten geladen, NICHT aus Worker-
Zusammenfassungen:

```python
def load_previous_findings(story_id: str, previous_cycle_id: str) -> list[dict]:
    """Laedt Findings der Vorrunde aus stale/ Review-Artefakten.

    Wichtig: Direkt aus Review-Artefakten, nicht aus Worker-
    Zusammenfassungen (BB2-012: Worker-Zusammenfassungen
    komprimieren offene Subcases weg).
    """
    stale_dir = Path(f"_temp/qa/{story_id}/stale/{previous_cycle_id}")
    findings = []
    for artifact_name in ("qa_review.json", "semantic_review.json", "doc_fidelity.json"):
        artifact_path = stale_dir / artifact_name
        if artifact_path.exists():
            artifact = json.loads(artifact_path.read_text())
            for check in artifact.get("checks", []):
                if check.get("status") == "FAIL":
                    findings.append(check)
    return findings
```

### 29.2.4 Gate-Pruefung vor Closure (FK-27-224)

[Korrektur 2026-04-09: Die Finding-Resolution-Pruefung laeuft als
**Closure-Gate** (§29.2.1), nicht als Teil der Policy-Evaluation
(Schicht 4). Policy-Evaluation prueft auf BLOCKING-Failures und
major_threshold — Finding-Resolution ist ein eigenstaendiger
Vorstufen-Check am Beginn der Closure-Phase, konsistent mit dem
Abschnittstitel "Finding-Resolution als Closure-Gate" und FK-27 §27.7.1.]

Die Finding-Resolution-Pruefung laeuft als Closure-Gate (§29.2.1)
— vor dem Integrity-Gate, am Beginn der Closure-Phase. Sie prueft
alle drei Layer-2-Artefakte:

```python
# [Korrektur 2026-04-09] Alle drei Layer-2-Artefakte pruefen (FK-27 §27.5.5),
# konsistent mit §29.2.3 und FK-38 §38.1.1.
def check_finding_resolution(story_id: str) -> bool:
    """Prueft ob alle Findings vollstaendig aufgeloest sind.

    Returns False wenn mindestens ein Finding partially_resolved
    oder not_resolved ist.
    """
for artifact_id in ("qa_review", "semantic_review", "doc_fidelity"):
        review = load_artifact(story_id, artifact_id)
        if review is None:
            return False  # fail-closed

        for check in review.get("checks", []):
            resolution = check.get("resolution")
            # Design-Invariante: Erstlauf (Runde 1, kein Remediation) → keine Checks haben
            # ein resolution-Feld → Gate gibt True zurück → Closure nicht blockiert.
            # Ab Runde 2 (Remediation-Modus, §29.2.2): Checks haben resolution-Feld →
            # Gate wird aktiv. fail-closed für unbekannte/problematische Werte.
            if resolution is None:
                continue  # kein Remediation-Check, nicht prüfen
            if resolution not in ("fully_resolved", "not_applicable"):
                return False
    return True
```

### 29.2.5 Artefakt-Invalidierung (FK-27-225)

Die Finding-Resolution ist Teil der bestehenden Layer-2-Artefakte
`qa_review.json`, `semantic_review.json` und `doc_fidelity.json` (FK-27 §27.5.5) — alle drei
Artefakte sind bereits in der Invalidierungstabelle (FK-27 §27.2.3)
enthalten. Eine Erweiterung der Tabelle ist daher nicht erforderlich.

**Querverweis:** FK-34 fuer die technische Erweiterung des
StructuredEvaluator um den Remediation-Modus.

## 29.3 Postflight-Gates

### 29.3.1 Checks (FK-05-227 bis FK-05-231)

Nach erfolgreichem Merge und Story-Status-Wechsel auf Done (für
Concept/Research: nach `merge_done = true` und `story_closed = true`,
§29.1.1):

| Check | Was | FAIL wenn |
|-------|-----|----------|
| `story_dir_exists` | Story-Verzeichnis existiert mit `protocol.md` | Verzeichnis oder Protokoll fehlt |
| `story_closed` | AK3-Story-Status == Done | Story noch nicht geschlossen |
| `metrics_set` | QA Rounds und Completed At gesetzt | Felder leer |
| `telemetry_complete` | `agent_start` und `agent_end` Events vorhanden | Events fehlen |
| `artifacts_complete` | Bei impl/bugfix: `structural.json`, `decision.json`, `context.json` vorhanden. Bei concept/research: nur `context.json` Pflicht (`structural.json` und `decision.json` entfallen — kein QA-Subflow). | Pflicht-Artefakte fehlen |

### 29.3.2 Postflight-FAIL

Postflight-Failure nach erfolgreichem Merge ist ein Sonderfall:
Der Code ist bereits auf Main. Ein Rollback ist nicht vorgesehen.
Stattdessen: Warnung an den Menschen, dass die Konsistenz
unvollständig ist. Der Mensch entscheidet, ob Nacharbeit nötig ist.

## 29.4 Execution Report

### 29.4.1 Zweck

Am Ende jeder Story-Bearbeitung — unabhängig vom Ergebnis (COMPLETED,
ESCALATED, FAILED) — wird ein konsolidierter Markdown-Report erzeugt:
`_temp/qa/{story_id}/execution-report.md`. Konsument ist der Mensch
(Oversight/Audit); bei erfolgreich abgeschlossenen Stories ist keine
aktive Intervention erforderlich.

**Aufrufpfad bei FAILED in fruehen Phasen (Entscheidung):**
Wenn eine Story in einer fruehen Phase (z.B. Setup oder Implementation)
mit FAILED endet ohne Closure regulaer zu erreichen, ruft
`pipeline-framework.PipelineEngine` die ClosureSequence-Top dennoch
auf — im Skip-Modus: `ClosureProgress`-Felder bleiben auf `false`, der
`ExecutionReport` wird trotzdem erzeugt (Graceful Degradation, §29.4.3).
Modul: `agentkit.closure.execution_report` (`ExecutionReport`, intern in
BC 7). Begruendung: Single-Owner fuer alle Closure-Anteile;
pipeline-framework bleibt orchestrierend statt fachlich.
`ExecutionReport` ist deshalb NICHT `sub_exposed` und wird nicht von
`agentkit.pipeline_engine` direkt aufgerufen.

### 29.4.2 Report-Sektionen

| Sektion | Inhalt |
|---------|--------|
| **Summary Table** | Story-ID, Typ, Modus, Status, Dauer, QA Rounds, Feedback Rounds, durchlaufene QA-Subflow-Schichten |
| **Failure Diagnosis** | Fehlgeschlagene Phase, primärer Fehler, Trigger — nur bei FAILED/ESCALATED |
| **Artifact Health** | Verfügbare vs. fehlende/invalide Datenquellen; Ladestatus pro Quelle |
| **Errors and Warnings** | Aggregierte Fehler und Warnungen aus allen Phasen |
| **Structural Check Results** | Ergebnisse der deterministischen Checks (Schicht 1) |
| **Policy Engine Verdict** | Aggregiertes Policy-Ergebnis mit Blocking/Major/Minor Counts |
| **Closure Sub-Step Status** | Status jedes `ClosureProgress`-Feldes (`payload.progress.integrity_passed`, `payload.progress.story_branch_pushed`, `payload.progress.merge_done`, `payload.progress.story_closed`, `payload.progress.metrics_written`, `payload.progress.postflight_done`) [Entscheidung 2026-04-09] |
| **Telemetry Event Counts** | Zähler aller relevanten Telemetrie-Events |
| **Integrity Violations Log** | Vollständiger Integrity-Violations-Auszug (falls vorhanden) |

### 29.4.3 Graceful Degradation

Jede Datenquelle ist optional. Wenn ein Artefakt fehlt oder nicht
ladbar ist, wird der Ladestatus in der Sektion "Artifact Health"
als `MISSING` oder `LOAD_ERROR` dokumentiert. Die restlichen Sektionen
werden trotzdem befüllt — der Report wird nie wegen fehlender
Einzeldaten abgebrochen.

### 29.4.4 FK-Referenz

Domänenkonzept 5.2 Closure-Phase "Execution Report".

## 29.5 Guard-Deaktivierung

Nach erfolgreichem Postflight ruft Closure `Governance.deactivate_locks(story_id)`
(`agentkit.governance`, Top-Surface). Die Lock-Record-Verwaltung gehoert
ausschliesslich zum Governance-BC; Closure haelt keinen eigenen Lock-Sub.

`Governance.deactivate_locks` fuehrt intern aus:

1. Lock-Record im State-Backend beenden und optionale Lock-Exporte entfernen:
   `_temp/governance/locks/{story_id}/qa-lock.json`
   sowie `.agent-guard/lock.json` in betroffenen Worktrees
2. Ab hier: AI-Augmented-Modus wieder aktiv (Branch-Guard inaktiv,
   Orchestrator-Guard inaktiv, QA-Schutz inaktiv)

Closure selbst enthaelt keine Lock-Logik — der Aufruf ist ein einzelner
Delegationsschritt an `agentkit.governance.integrity_gate` (IntegrityGate-Aufruf
in §29.1.2) und `agentkit.governance` (Guard-Deaktivierung hier).

## 29.6 Schema-Owner-Cut: StoryMetric und WorkflowMetric

**Owner: story-closure BC (agentkit.closure.post_merge_finalization)**

Analog zum Schema-Owner-Cut in FK-69 §69.6-69.8 fuer telemetry-and-events gilt:

| Schema | Owner | Modul | Schreibzeitpunkt |
|--------|-------|-------|-----------------|
| `StoryMetric` | story-closure | `agentkit.closure.post_merge_finalization` | Ende der Closure-Phase (Substate `metrics_written = true`) |
| `WorkflowMetric` | story-closure | `agentkit.closure.post_merge_finalization` | Ende der Closure-Phase (Substate `metrics_written = true`) |

`PostMergeFinalization` definiert die Schema-Struktur und schreibt die Werte
via `Telemetry.write_projection` (Top-Surface von `agentkit.telemetry`).
Die Persistenz-Schicht (Projektionstabellen) liegt bei telemetry-and-events —
Schema-Ownership und Schreibverantwortung liegen bei story-closure.

Lesezugriff auf `StoryMetric`/`WorkflowMetric` erfolgt ausschliesslich
ueber `Telemetry.read_projection` (sub_exposed, `agentkit.telemetry.projection_accessor`).
Direktes Lesen der Projektionstabellen durch andere BCs ist nicht zulaessig.
