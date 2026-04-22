---
concept_id: FK-56
title: Betriebsmodi — AI-Augmented und Story-Execution sauber getrennt
module: operating-modes
status: active
doc_kind: core
parent_concept_id:
authority_over:
  - scope: operating-modes
  - scope: run-binding
  - scope: baseline-vs-story-governance
defers_to:
  - target: FK-59
    scope: story-contract-classification
    reason: operating_mode wird dort explizit als abgeleitete Laufzeitachse eingeordnet
  - target: FK-30
    scope: hook-enforcement
    reason: Betriebsmodi werden technisch ueber Hooks und Run-Bindung wirksam
  - target: FK-55
    scope: principal-capabilities
    reason: Principals und Capabilities muessen mode-scharf interpretiert werden
supersedes: []
superseded_by:
tags: [operating-modes, ai-augmented, story-execution, run-binding, integrity]
prose_anchor_policy: strict
formal_refs:
  - formal.operating-modes.entities
  - formal.operating-modes.state-machine
  - formal.operating-modes.commands
  - formal.operating-modes.events
  - formal.operating-modes.invariants
  - formal.operating-modes.scenarios
  - formal.story-exit.state-machine
  - formal.story-exit.invariants
  - formal.story-contracts.invariants
---

# 56 — Betriebsmodi — AI-Augmented und Story-Execution sauber getrennt

<!-- PROSE-FORMAL: formal.operating-modes.entities, formal.operating-modes.state-machine, formal.operating-modes.commands, formal.operating-modes.events, formal.operating-modes.invariants, formal.operating-modes.scenarios, formal.story-exit.state-machine, formal.story-exit.invariants, formal.story-contracts.invariants -->

## 56.1 Zweck

AgentKit begleitet ein Projekt in zwei grundverschiedenen Betriebsarten:

1. `ai_augmented`
   - freies, menschlich gefuehrtes Arbeiten mit Claude-Code-Agents
   - keine aktive Story-Ausfuehrung
   - keine Workflow- oder Integrity-Pflichten
2. `story_execution`
   - explizit gebundener Story-Run mit `project_key + story_id + run_id`
   - volles Guard-, QA-, Verify- und Integrity-Regime

Dieses Kapitel zieht die Trennung normativ und technisch so scharf, dass
freie Arbeit nicht versehentlich als Story-Ausfuehrung behandelt wird.

**Grenze dieses Kapitels:** Der Modus `ai_augmented` wird hier nur als
Abwesenheit von Story-Execution-Regime beschrieben. Die konkrete
inhaltliche Arbeitsweise des Menschen in diesem freien Modus wird durch
AgentKit nicht weiter fachlich ausmodelliert.

## 56.2 Grundregel

**Ohne explizite Run-Bindung gibt es keinen Story-Governance-Modus.**

Das bedeutet:

- kein Orchestrator-Guard
- kein QA-Artefakt-Schutz
- kein QA-Agent-Guard
- kein Adversarial-Sandbox-Zwang fuer freie Agents
- kein Worker-Health-Monitor
- kein Integrity-Gate
- keine Verify-/Closure-/Story-Prozesspflichten

Es bleiben nur die immer-aktiven Basisschutzregeln und CCAG.

## 56.3 Die zwei Betriebsmodi

| Modus | Wann | Charakter |
|------|------|-----------|
| `ai_augmented` | kein gueltiger `story_execution`-Lock, keine aktive Run-Bindung fuer die Session | freies, interaktives Arbeiten |
| `story_execution` | gueltiger `story_execution`-Lock plus aktive Session-/Run-Bindung | deterministischer Story-Workflow |

**Klarstellung:** Systemische Integrations- und Stabilisierungslagen
gemäss FK-57 erzeugen **keinen dritten Betriebsmodus**. Sie bleiben ein
Spezialvertrag innerhalb von `story_execution`.

### 56.3a `operating_mode` ist keine Story-Hauptklassifikation

`operating_mode` wird nicht als kanonisches Story-Hauptfeld gefuehrt.

Er ist:

- session- und run-gebunden
- aus Lock, Bindung und Worktree-Konsistenz abgeleitet
- fachlich getrennt von `story_type` und `implementation_contract`

Damit darf ein stale oder verloren gegangener Session-Zustand nicht als
vermeintlich persistente Story-Semantik weiterleben.

## 56.4 Principals im Moduskontext

Der Hauptagent ist nicht immer derselbe technische Principal.

| Modus | Hauptagent-Principal |
|------|-----------------------|
| `ai_augmented` | `interactive_agent` |
| `story_execution` | `orchestrator` |

**Normative Regel:** `interactive_agent` und `orchestrator` sind nicht
dieselbe Capability-Klasse. Der freie interaktive Agent ist kein
"gelockerter Orchestrator", sondern ein eigener Principal ausserhalb des
Story-Workflows.

## 56.5 Was immer aktiv bleibt

Diese Regeln gelten in beiden Modi:

- CCAG
- Governance-Selbstschutz
- destructive Git baseline guards:
  - kein Force-Push
  - kein `git reset --hard`
  - kein `git branch -D`
- Secret-/Credential-Schutz
- Prompt-Integrity-Basisschutz gegen Governance-Escape und kaputte
  Spawn-Strukturen
- Story-Create-Guard, sofern Stories weiterhin nur ueber den
  offiziellen Pfad angelegt werden duerfen

## 56.6 Was nur in `story_execution` aktiv ist

- Branch-Isolation auf `story/{story_id}`
- Orchestrator-Guard
- QA-Artefakt-Schutz
- QA-Agent-Guard
- Adversarial-Sandbox-Guard
- storybezogene Capability-Freeze-Logik
- Worker-Health-Monitor
- Verify-/Closure-Prozess
- Integrity-Gate
- storygebundene Governance-Beobachtung

## 56.7 Technische Aktivierung

`story_execution` darf nie aus Prompt, Branchname oder lokaler Datei
allein geraten werden.

Es braucht **beides**:

1. einen kanonischen, gueltigen Lock-/Run-Record im State-Backend
2. eine aktive Session-Bindung auf genau diesen Run

Die Session-Bindung enthaelt in Multi-Repo-Faellen keine einzelne
`worktree_root`, sondern die Menge der erlaubten `worktree_roots`.

Hooks und Guards lesen diese Lage im Normalfall nicht per
State-Backend-Roundtrip, sondern aus einer lokal publizierten,
abgeleiteten Projektion:

- `_temp/governance/current.json`
- `_temp/governance/bundles/{export_version}/session.json`
- `_temp/governance/bundles/{export_version}/lock.json`

Fehlt beides, gilt:

- `ai_augmented`

Existiert dagegen bereits eine Session-Bindung, aber Lock oder
Worktree-Match sind inkonsistent, gilt **nicht** freier Modus, sondern
ein blockierender Fehlerzustand.

## 56.7a Invalide Story-Bindung

Wenn eine Session an einen Story-Run gebunden ist, aber mindestens eine
der technischen Voraussetzungen wegbricht, geht der Modus auf
`binding_invalid`.

Typische Ursachen:

- Lock-Record verloren oder stale
- Worktree stimmt nicht mehr mit der Bindung ueberein
- Run wurde extern beendet, Session ist aber noch gebunden

**Wirkung:**

- keine storygebundene Normalfortsetzung
- kein stiller Rueckfall in freien Modus
- mutierende Story-Aktionen blockieren fail-closed
- Mensch muss per offiziellem Pfad aufraeumen oder neu binden

## 56.8 Run-Bindung

Die aktive Session-Bindung enthaelt mindestens:

- `project_key`
- `story_id`
- `run_id`
- `principal_type`
- `worktree_roots`
- `binding_version`

Lokale Exporte sind nur Materialisierung. Kanonisch bleibt der
State-Backend-Eintrag. Fuer Hook-Entscheidungen ist `current.json`
der einzige lokale Einstieg; einzelne Exportdateien oder
Worktree-Projektionen sind fuer sich allein nie ausreichend.

## 56.9 Mode-Resolution

Der Hook darf den Modus nicht aus Host-UI oder Prompt erraten. Er leitet
ihn deterministisch ab:

```python
def resolve_operating_mode(event: HookEvent) -> str:
    current = load_current_edge_pointer()
    if current is None:
        return "ai_augmented"

    bundle = load_edge_bundle(current)
    if bundle.session.session_id != event.session_id:
        return "binding_invalid"

    if bundle.lock.status != "ACTIVE":
        return "binding_invalid"

    if not worktree_matches_binding(event.cwd, bundle.session.worktree_roots):
        return "binding_invalid"

    return "story_execution"
```

### 56.9a Bounded Re-Sync statt DB-Roundtrip pro Hook

Hooks fuehren keine zentrale Abfrage pro Tool-Call aus. Stattdessen
gilt:

- offizielle Zustandswechsel materialisieren lokal ein komplettes
  Edge-Bundle
- `current.json` zeigt atomar auf genau ein vollstaendiges Bundle
- jedes Bundle traegt ein `sync_after`
- nur der erste Hook nach Ablauf von `sync_after` darf einen bounded
  Re-Sync gegen AK3 ausloesen
- mutierende Story-Entscheidungen blockieren fail-closed, wenn der
  Bundle-Stand zu alt oder inkonsistent ist

## 56.10 Integrity-Gate-Abgrenzung

Das Integrity-Gate ist **kein** allgemeiner Live-Guard fuer freie
Projektarbeit. Es prueft ausschliesslich Story-Runs in der Closure-Phase.

Im `ai_augmented`-Modus gibt es deshalb:

- kein `integrity_gate_started`
- kein `integrity_gate_result`
- keine Closure-FAIL-Codes
- keine Pflicht auf Story-Telemetrie, Verify oder Review-Proofs

## 56.11 Prompt-Integrity im freien Modus

Der Prompt-Integrity-Guard bleibt aktiv, aber reduziert:

- Governance-Escape-Erkennung bleibt aktiv
- Freestyle-Spawn-Schema bleibt aktiv
- storyspezifische Template-Integritaet und Skill-Proof-Pflichten gelten
  nur in `story_execution`

Damit duerfen freie Sub-Agents im Projekt arbeiten, ohne in die
Story-Template-Maschinerie gezwungen zu werden.

## 56.12 Ende eines Story-Runs

Ein Story-Run endet technisch erst, wenn:

1. der Lock-/Run-Record beendet ist
2. die Session-Bindung geloest ist
3. das lokale Edge-Bundle auf den deaktivierten Zustand
   umgeschaltet wurde und Tombstones alte Exporte entfernt haben

Erst danach faellt die Session wieder auf `ai_augmented` zurueck.

### 56.12a Rueckfall nach offiziellem Story-Exit

Ein Rueckfall in `ai_augmented` ist auch ueber den offiziellen
Story-Exit gemaess FK-58 zulaessig.

Dabei gilt:

- kein stiller Rueckfall
- kein Mischzustand
- erst Exit-Gate, dann Binding-Revocation, dann `ai_augmented`
