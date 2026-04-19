---
concept_id: FK-58
title: Story-Exit und Human-Takeover-Handoff
module: story-exit
status: active
doc_kind: core
parent_concept_id:
authority_over:
  - scope: story-exit
  - scope: human-takeover-handoff
  - scope: lightweight-exit-approval
defers_to:
  - target: FK-56
    scope: operating-modes
    reason: Der Exit fuehrt kontrolliert von story_execution nach ai_augmented
  - target: FK-55
    scope: principal-capabilities
    reason: Bindung, Cleanup und Capability-Wechsel muessen dort technisch konsistent bleiben
  - target: FK-57
    scope: integration-stabilization
    reason: Der Exit ist vor allem fuer ausgedehnte Integrations-/Stabilisierungsfaelle gedacht
  - target: FK-54
    scope: story-split
    reason: Story-Split bleibt der normale Exit fuer falsch geschnittene Stories
supersedes: []
superseded_by:
tags: [story-exit, human-takeover, ai-augmented, lightweight-approval, handoff]
prose_anchor_policy: strict
formal_refs:
  - formal.story-exit.entities
  - formal.story-exit.state-machine
  - formal.story-exit.commands
  - formal.story-exit.events
  - formal.story-exit.invariants
  - formal.story-exit.scenarios
---

# 58 — Story-Exit und Human-Takeover-Handoff

<!-- PROSE-FORMAL: formal.story-exit.entities, formal.story-exit.state-machine, formal.story-exit.commands, formal.story-exit.events, formal.story-exit.invariants, formal.story-exit.scenarios -->

## 58.1 Zweck

Es gibt Faelle, in denen eine laufende Story nicht mehr sinnvoll als
deterministische Story-Execution weitergefuehrt werden kann.

Der Grund ist dann nicht primaer:

- fehlendes Pfadmandat
- fehlendes Repo-Mandat
- oder fehlendes API-Mandat

sondern:

- der gesamte Loesungsvorschlag muss menschlich bewertet werden
- die naechsten Schritte sind fallbezogene Architektur- oder
  Integrationsentscheidungen
- die Story ist als Liefervertrag fuer diesen Zustand nicht mehr die
  passende Huelle

Fuer diesen Fall definiert AK3 einen **offiziellen administrativen
Story-Exit**.

## 58.2 Grundentscheidung

Der Story-Exit ist:

- **kein** neuer Betriebsmodus
- **kein** normaler Phase-Schritt
- **kein** erfolgreicher Story-Abschluss
- **kein** Story-Reset
- **kein** Story-Split-Ersatz fuer gewoehnliche Scope-Explosion

Er ist der kontrollierte Uebergang von:

- `story_execution`

nach:

- administrativ beendetem Story-Run
- anschliessend freiem, menschlich gefuehrtem `ai_augmented`

## 58.3 Wann der Exit zulaessig ist

Der Exit ist nur zulaessig, wenn mindestens einer dieser Gruende
vorliegt:

- `solution_viability_requires_human_design`
- `integration_strategy_not_scope_question`
- `integration_budget_exhausted`
- `approved_manifest_no_longer_sufficient`
- `bound_story_contract_no_longer_fit_for_decision_space`

Nicht zulaessig ist der Exit fuer:

- normale Schwierigkeit
- bloesse Agent-Unsicherheit
- uebliche Remediation
- Faelle, die ueber Story-Split oder regulaeres Replan sauber loesbar
  sind

## 58.4 Leichtgewichtsprinzip fuer den Menschen

Der Mensch soll in diesem Pfad **nicht** mit schwerer Dokumentationslast
belegt werden.

Normative Regel:

1. AgentKit bereitet das Handoff-Dossier selbst vor.
2. Der Mensch gibt im Regelfall nur:
   - einen offiziellen Exit-Befehl
   - einen Grundcode
   - optional einen kurzen Einzeiler
3. Ausfuehrliche Befundsammlung, Delta-Sichtung, technische
   Referenzen und Querverlinkungen erzeugt AgentKit automatisch.

**Leitbild:** Der Mensch soll im Idealfall nicht mehr als eine sehr
kurze administrative Entscheidung treffen muessen.

## 58.5 Menschlicher Eingriff

Der offizielle Pfad ist bewusst leichtgewichtig:

```bash
agentkit exit-story --story ODIN-042 --reason solution_viability_requires_human_design --note "Ich uebernehme ab hier fallbezogen."
```

Pflicht ist:

- `--story`
- `--reason`

Optional:

- `--note`

Die Notiz ist als Kurzkommentar gedacht, nicht als Aktenlage.

## 58.6 Ergebnis des Exits

Nach erfolgreichem Story-Exit gilt:

1. der aktive Story-Run ist terminal und nicht resumable
2. die Story wird administrativ `Cancelled`
3. zusaetzlich wird ein `exit_class=viability_handoff` dokumentiert
4. Story-Locks, Session-Bindung und storybezogene Guard-Regime werden
   geloest
5. die Session faellt erst danach kontrolliert auf `ai_augmented`
   zurueck

## 58.7 Kein Fluchtkanal

Damit schwierige Stories nicht still “nach draussen fliehen”, gilt:

1. Exit nur ueber `human_cli` / offiziellen Admin-Pfad
2. Exit nie durch Orchestrator-Selbstentscheidung
3. Exit erst nach ausdruecklicher Pruefung der Alternativen:
   - Standardvertrag weitertragen
   - Reklassifikation nach `integration_stabilization`
   - Story-Split
4. Exit-Ereignisse zaehlen sichtbar als administrativ beendete,
   nicht gelieferte Stories

## 58.8 Minimalartefakte

Der Exit erzeugt bewusst nur ein kleines, aber hinreichendes Paket:

1. `viability_dossier.md`
   - automatisch durch AgentKit vorbereitet
   - kurzer Problemkern
   - warum der Story-Vertrag endet
   - offene Architektur-/Integrationsfragen
   - empfohlene naechste Schritte
2. `story_exit_record.json`
   - kanonischer Audit-Record
3. `exit_manifest_snapshot.json`
   - letzter gebundener Story-/Manifest-/Budget-Stand

Optional:

4. `delta_quarantine.json`
   - nur wenn out-of-contract Deltas gesondert markiert werden muessen

## 58.9 Was danach erlaubt ist

Nach dem erfolgreichen Exit arbeitet die Session wieder im Modus
`ai_augmented`.

Dann gilt:

- kein Story-Execution-Regime mehr
- kein Integrity-Gate fuer diesen beendeten Story-Run
- keine Story-Closure-Pflichten
- freie, menschlich gefuehrte Agent-Arbeit innerhalb der allgemeinen
  Basisschutzregeln

Wenn der Mensch danach fallbezogene Mandate braucht, duerfen diese
leichtgewichtig und ausserhalb des Story-Vertrags gegeben werden.

## 58.10 Exit-Gate statt Closure

Der Story-Exit geht **nicht** durch normale Closure.

Stattdessen gibt es ein leichtes administratives `exit_gate`, das nur
prueft:

- gueltiger Exit-Grund
- Exit-Record vorhanden
- Dossier vorhanden
- Lock-/Binding-/Export-Cleanup abgeschlossen
- Session nicht mehr im Story-Regime gebunden

Damit bleibt der Exit formal sauber, ohne den Menschen mit unnoetiger
Prozesslast zu blockieren.
