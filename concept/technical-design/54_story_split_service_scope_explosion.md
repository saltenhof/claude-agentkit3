---
concept_id: FK-54
title: StorySplitService und Scope-Explosion-Flow
module: story-split
domain: story-lifecycle
status: active
doc_kind: core
parent_concept_id:
authority_over:
  - scope: story-split
  - scope: scope-explosion-recovery
  - scope: successor-story-creation
  - scope: dependency-rebinding
defers_to:
  - target: FK-21
    scope: story-creation
    reason: Nachfolger-Stories werden ueber dieselben Story-Creation-Regeln erzeugt
  - target: FK-25
    scope: scope-explosion-classification
    reason: Klasse-3-Erkennung und menschliche Mandatsgrenze werden dort festgelegt
  - target: FK-35
    scope: pause-escalation-mechanics
    reason: PAUSED/ESCALATED und CLI-Resume-Mechanik werden dort normiert
  - target: FK-12
    scope: github-state
    reason: GitHub-Issue- und Project-Status werden dort technisch konkretisiert
  - target: FK-57
    scope: integration-stabilization-exception
    reason: Enge Reklassifikation auf integration_stabilization ersetzt den Split-Standardpfad und wird dort normiert
supersedes: []
superseded_by:
tags: [story-split, scope-explosion, cancellation, successor-stories, dependency-rebinding]
prose_anchor_policy: strict
formal_refs:
  - formal.story-creation.commands
  - formal.story-creation.invariants
  - formal.story-creation.scenarios
  - formal.story-workflow.scenarios
  - formal.dependency-rebinding.entities
  - formal.dependency-rebinding.state-machine
  - formal.dependency-rebinding.commands
  - formal.dependency-rebinding.events
  - formal.dependency-rebinding.invariants
  - formal.dependency-rebinding.scenarios
  - formal.story-split.entities
  - formal.story-split.state-machine
  - formal.story-split.commands
  - formal.story-split.events
  - formal.story-split.invariants
  - formal.story-split.scenarios
---

# 54 — StorySplitService und Scope-Explosion-Flow

<!-- PROSE-FORMAL: formal.story-creation.commands, formal.story-creation.invariants, formal.story-creation.scenarios, formal.story-workflow.scenarios, formal.dependency-rebinding.entities, formal.dependency-rebinding.state-machine, formal.dependency-rebinding.commands, formal.dependency-rebinding.events, formal.dependency-rebinding.invariants, formal.dependency-rebinding.scenarios, formal.story-split.entities, formal.story-split.state-machine, formal.story-split.commands, formal.story-split.events, formal.story-split.invariants, formal.story-split.scenarios -->

## 54.1 Zweck

`StorySplitService` ist die administrative Recovery-Komponente fuer den
haeufigen Praxisfall, dass eine laufende Story sich als fachlich oder
technisch deutlich groesser herausstellt als ihr deklarierter Scope.

Der Service beendet die ueberdehnte Ausgangs-Story **kontrolliert als
nicht umsetzbar in ihrer aktuellen Form**, ueberfuehrt ihren Scope in
neu geschnittene Nachfolger-Stories und bereinigt dabei alle
steuernden Seiteneffekte, die einen sauberen Weiterlauf behindern
wuerden.

## 54.2 Grundentscheidung

Fuer AK3 gilt normativ:

1. Eine bestaetigte `Scope-Explosion` fuehrt **nicht** zu stiller
   Story-Manipulation waehrend des laufenden Runs.
2. Der Standardpfad ist **nicht** "alte Story umschreiben und
   weitertreiben", sondern:
   - laufende Story wird kontrolliert beendet
   - der Restumfang wird in Nachfolger-Stories neu geschnitten
3. Die Ausgangs-Story geht in den GitHub-Project-Status
   `Cancelled`.
4. Der Split wird **nie automatisch** durch Agent oder Pipeline
   vollzogen; er benoetigt eine ausdrueckliche menschliche
   Entscheidung und den offiziellen CLI-Pfad.

**Narrow exception:** FK-57 definiert einen engen offiziellen
Reklassifikationspfad fuer legitime spaete
Integrations-/Stabilisierungsstories. Diese Ausnahme hebt den
Split-Standardpfad nicht auf, sondern ersetzt ihn nur, wenn der Mensch
die Story bewusst auf `implementation_contract=integration_stabilization`
umstellt und ein Integrations-Scope-Manifest freigibt.

## 54.3 Abgrenzung

- `StorySplitService` ist **kein** normaler Pipeline-Schritt.
- `StorySplitService` ist **kein** Override.
- `StorySplitService` ist **kein** Story-Reset:
  - beim Reset ist die bisherige Umsetzung korrupt und wird fachlich
    ungueltig
  - beim Split ist die bisherige Umsetzung als Auditspur gueltig,
    aber die Story als Liefervertrag war falsch geschnitten

## 54.4 Einstiegsvoraussetzungen

Ein Story-Split ist nur zulaessig, wenn:

1. fuer die Story `scope_explosion` festgestellt wurde
2. der Mensch den Split explizit freigibt
3. ein offizieller Split-Plan vorliegt
4. keine konkurrierende administrative Operation fuer dieselbe Story
   aktiv ist

**Typischer Vorzustand:** `PAUSED` in Exploration mit
`escalation_class: "scope_explosion"`.

## 54.5 Ergebniszustand

Nach erfolgreichem Split gilt:

1. die Ausgangs-Story ist im Project-Status `Cancelled`
2. das GitHub-Issue der Ausgangs-Story ist mit `not planned`
   geschlossen
3. neue Nachfolger-Stories existieren im Status `Backlog`
4. Abhaengigkeiten und Story-Beziehungen sind auf die Nachfolger
   umgebogen
5. steuernde Runtime-Reste, Locks, Worktrees und Branches der
   Ausgangs-Story sind entfernt
6. Audit- und Split-Nachweis bleiben erhalten

## 54.6 CLI-Schnittstelle

Normativer Kontrollpfad:

```bash
agentkit split-story --story ODIN-042 --plan split-plan.json --reason "scope explosion in exploration"
```

Pflichtparameter:

- `--story`
- `--plan`
- `--reason`

Der Split-Plan ist ein menschenfreigegebenes Artefakt. Er ist kein
optional komfortabler Input, sondern der vertragliche Kern der
Operation.

## 54.7 Split-Plan

Der Split-Plan beschreibt mindestens:

- Ausgangs-Story
- Split-Grund
- Menge der Nachfolger-Stories
- Ziel-Scope je Nachfolger
- Zuordnung der Akzeptanzkriterien / Anforderungen
- Dependency-Rebinding
- Story-Lineage

Minimalstruktur:

```json
{
  "project_key": "brainbox",
  "source_story_id": "ODIN-042",
  "reason": "scope_explosion",
  "successors": [
    {
      "story_id": "ODIN-107",
      "title": "Teilscope A",
      "scope_slice": "..."
    },
    {
      "story_id": "ODIN-108",
      "title": "Teilscope B",
      "scope_slice": "..."
    }
  ],
  "dependency_rebinding": [
    {
      "dependent_story_id": "ODIN-051",
      "old_dependency": "ODIN-042",
      "new_dependencies": ["ODIN-107"]
    }
  ]
}
```

## 54.8 Ablauf

### 54.8.1 Schritt 1: Split-Vorgang registrieren

`StorySplitService` legt einen auditierbaren Split-Vorgang an:

- `split_id`
- `project_key`
- `source_story_id`
- `requested_by`
- `reason`
- `plan_ref`
- `status`

### 54.8.2 Schritt 2: Story exklusiv fence'n

Die Ausgangs-Story wird gegen jede weitere normale Pipeline-Aktion
gesperrt:

- kein `resume`
- kein `reset-escalation`
- kein neuer Worker-Spawn
- keine manuelle Git-Weiterarbeit unter Story-Lock

### 54.8.3 Schritt 3: Aktive Runtime quiescen

Der Service beendet oder entwertet alle steuernden Laufzeitobjekte:

- aktive Flow- und Node-Ausfuehrungen
- Phase-State-Projektion der Story
- story-bezogene Locks und Leases
- Story-Branch und Worktree

**Ziel:** Die Ausgangs-Story darf die Erstellung und Bearbeitung ihrer
Nachfolger nicht mehr blockieren.

### 54.8.4 Schritt 4: Nachfolger-Stories erzeugen

Die Nachfolger werden ueber denselben fachlichen Story-Creation-Vertrag
erzeugt wie normale Stories:

- GitHub Issue anlegen
- Project-Item anlegen
- Story-Custom-Fields setzen
- `story.md` exportieren

Abweichung: Der aufrufende Actor ist hier `StorySplitService` und nicht
ein frei arbeitender Agent. Fuer diesen offiziellen Systempfad darf die
Story-Erstellung intern skriptgesteuert erfolgen.

### 54.8.5 Schritt 5: Abhaengigkeiten und Story-Lineage umbiegen

Der Service aktualisiert alle expliziten Story-Beziehungen gemaess
Split-Plan:

- eingehende Dependencies auf die Ausgangs-Story
- ausgehende Dependencies der Ausgangs-Story
- `split_from` / `split_successors`-Beziehungen

**Normative Regel:** Kein abhängiges Issue darf still auf eine
`Cancelled`-Story zeigen, wenn laut Split-Plan bereits Nachfolger
existieren.

### 54.8.6 Schritt 6: Fachnahe Anreicherungen neu aufbauen

Fuer die Nachfolger muessen die fachnahen Anreicherungen **neu**
abgeleitet werden. Das betrifft insbesondere:

- ARE-Anforderungsverknuepfung
- Repo-Affinitaet
- Labels
- Concept-Referenzen
- VektorDB-/Weaviate-Indexierung

Die Ausgangs-Story wird im Index nicht geloescht, sondern als
`Cancelled` und `superseded_by=[...]` fortgeschrieben.

### 54.8.7 Schritt 7: Ausgangs-Story kontrolliert beenden

Die Ausgangs-Story wird **nicht** ueber Closure beendet. Stattdessen:

1. GitHub Project `Status -> Cancelled`
2. GitHub Issue `close --reason "not planned"`
3. Split-Artefakt und Auditspur verlinken

Damit ist sichtbar, dass die Story nicht erfolgreich geliefert wurde,
aber auch nicht einfach "haengen blieb".

## 54.9 Umgang mit Artefakten, Telemetrie und Analytics

### 54.9.1 Operativer Zustand

Alle steuernden Runtime-Reste der Ausgangs-Story werden entfernt oder
invalidiert:

- `phase_state_projection`
- aktive Lock-/Lease-Zustaende
- offene Retry-/Resume-Mechanik
- Story-Branch / Worktree

### 54.9.2 Audit und Telemetrie

Im Unterschied zum vollstaendigen Reset bleiben die bisherige
Telemetrie und Auditspur der Ausgangs-Story erhalten, weil sie einen
gueltigen Befund dokumentieren: Die Story wurde wegen Scope-Explosion
kontrolliert beendet.

Diese Auditdaten duerfen aber:

- keinen Start neuer Nachfolger blockieren
- keine Guards fuer Nachfolger triggern
- nicht als erfolgreiche Delivery zaehlen

### 54.9.3 KPI- und Dashboard-Regel

`Cancelled`-Stories werden gesondert ausgewertet:

- nicht als `Done`
- nicht als erfolgreich geliefert
- optional als eigene Qualitaets-/Planungsmetrik

## 54.10 Hook- und Guard-Regeln

Waehrend einer aktiven Story-Execution blockieren die Guards viele
Mutationen absichtlich. Fuer den offiziellen Split-Pfad gilt deshalb:

1. Nur `agentkit split-story ...` darf trotz aktivem Story-Lock die
   administrative Split-Operation ausfuehren.
2. Freie Git-, Issue- oder Project-Manipulationen bleiben weiter
   blockiert.
3. Der Branch-Guard und der Story-Creation-Guard muessen den
   offiziellen Split-Service-Pfad explizit zulassen.

## 54.11 Daten- und Integrationsfolgen

Der Service muss mindestens diese Integrationsfolgen durchziehen:

- GitHub Project-Status der Ausgangs-Story
- GitHub-Issue-Close der Ausgangs-Story
- Erzeugung der Nachfolger-Issues
- Rebinding expliziter Dependencies
- Reindexierung der Story-KB / Weaviate
- Neuanlage fachlicher Nachfolger-Artefakte (`story.md`)
- Neuableitung von ARE- und Scope-bezogenen Metadaten

## 54.12 Endgueltige normative Aussage

AK3 kennt fuer regelmaessige `Scope-Explosion` **nicht** den
Sollprozess "laufende Story im selben Vertrag weitermodifizieren".

Der normative Standardpfad ist:

`Scope-Explosion` -> `PAUSED` -> menschliche Split-Freigabe ->
`StorySplitService` -> Ausgangs-Story `Cancelled` -> Nachfolger-Stories
im `Backlog`.
