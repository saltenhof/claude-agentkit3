---
concept_id: FK-44
title: Prompt-Bundles, Materialisierung und Audit
module: prompt-runtime
status: active
doc_kind: core
parent_concept_id:
authority_over:
  - scope: prompt-bundles
  - scope: prompt-materialization
  - scope: prompt-audit
defers_to:
  - target: FK-10
    scope: runtime-deployment
    reason: Zentrale Installation, lokale Projektstruktur und Laufzeitgrenzen sind dort beschrieben
  - target: FK-11
    scope: llm-provider
    reason: Pool-Aufrufe und Prompt-Execution-Schnitt liegen dort
  - target: FK-50
    scope: installer
    reason: Projektregistrierung und Bundle-Bindung werden dort ausgefuehrt
supersedes: []
superseded_by:
tags: [prompts, bundles, materialization, audit, central-installation]
prose_anchor_policy: strict
formal_refs:
  - formal.prompt-runtime.entities
  - formal.prompt-runtime.state-machine
  - formal.prompt-runtime.commands
  - formal.prompt-runtime.events
  - formal.prompt-runtime.invariants
  - formal.prompt-runtime.scenarios
---

# 44 — Prompt-Bundles, Materialisierung und Audit

## 44.1 Zweck

<!-- PROSE-FORMAL: formal.prompt-runtime.entities, formal.prompt-runtime.invariants -->

AgentKit trennt Prompt-Quellen, Projektbindung und konkrete
Prompt-Instanzen strikt voneinander.

Der Ausloeser dafuer ist ein echter Praxisfehler: veraltete lokale
Prompt-Kopien duerfen nie wieder dazu fuehren, dass Worker oder
Evaluator mit einem anderen Prompt laufen als dem aktuell gebundenen,
offiziell installierten Bundle.

Der tragende Schnitt ist:

1. **kanonische Prompt-Bundles** systemweit und immutable
2. **projektlokale Prompt-Bindung** ueber einen expliziten
   `prompt-bundle.lock.json`-Datensatz
3. **projektlokale Prompt-Exposition** nur als read-only Projektion auf
   genau eine Bundle-Version
3. **Run-gebundene Prompt-Instanzen** fuer die tatsaechliche Nutzung

## 44.2 Kanonische Quelle

<!-- PROSE-FORMAL: formal.prompt-runtime.invariants -->

Die kanonische Quelle aller produktiven Prompt-Templates liegt
ausschliesslich in systemweit installierten, versionierten
Prompt-Bundles.

Es gilt:

- keine projektlokale Prompt-Datei ist Source of Truth
- keine mutable Projektkopie darf Autoritaet ueber die Laufzeit haben
- `prompt_bundle_version` ist eine gebundene Versionsangabe, kein
  Hinweis auf eine frei editierbare lokale Dateiablage

Fuer **statische Prompt-Templates** wird projektlokal ein
Claude-Code-kompatibler Bindungspunkt unter `prompts/` bereitgestellt.
Autoritativ ist dabei nicht die Dateiansicht selbst, sondern der
explizite Lock-Datensatz
`.agentkit/config/prompt-bundle.lock.json`.

Der Lock enthaelt die gebundene Prompt-Identitaet
(`bundle_id`, `bundle_version`) und den Manifest-Digest, aber **nicht**
den produktiven Bundle-Quellpfad als frei vertrauenswuerdige
Projektinformation. Die Runtime leitet den effektiven Bundle-Pfad aus
dem installerverwalteten, zentralen Prompt-Bundle-Store ab.

Die Dateien unter `prompts/` sind nur eine read-only Projektion auf die
gebundene Bundle-Version, derzeit z. B. ueber Hardlinks; spaeter sind
auch Symlink-/Junction-Varianten zulaessig, solange der Lock-Datensatz
die bindende Autoritaet bleibt.

Fuer **run-scoped Prompt-Instanzen und gerenderte Ergebnisse** gibt es
zusaetzlich einen Runtime-Artefaktbereich unter `.agentkit/prompts/`.
Dieser Ort ist nie Bundle-Quelle.

## 44.3 Bindung und Run-Pinning

<!-- PROSE-FORMAL: formal.prompt-runtime.state-machine, formal.prompt-runtime.commands, formal.prompt-runtime.events, formal.prompt-runtime.scenarios -->

Die Projektbindung bestimmt, **welches Prompt-Bundle neue Runs
verwenden sollen** und worauf der projektlokale Bindungspunkt
`prompts/` fuer kuenftige Runs zeigt.

Ein aktiver Run arbeitet dagegen nie gegen eine "live" aufgeloeste
Projektbindung, sondern gegen einen **bei Run-Start aufgeloesten und
eingefrorenen Prompt-Stand**.

Bei `setup` bzw. Run-Erzeugung werden mindestens festgehalten:

- `resolved_prompt_bundle_version`
- `resolved_prompt_bundle_manifest_digest`
- ein eigener Run-Pin unter
  `.agentkit/manifests/prompt-pins/{run_id}.json`

Die Aufloesung des Bundles fuer diesen Run erfolgt nicht ueber einen
freien Pfad im Projekt, sondern ueber den installerverwalteten
zentralen Prompt-Bundle-Store anhand der gebundenen
`bundle_id`/`bundle_version`.

Ab diesem Moment gilt:

- spaetere Installer-/Rebind-Aktionen betreffen nur **zukuenftige Runs**
- ein aktiver Run sieht keinen stillen Prompt-Wechsel mehr
- mid-run Prompt-Drift ist unzulaessig
- der projektlokale Bindungspunkt `prompts/` darf fuer einen bereits
  gepinnten Run nicht mehr die konsumierte Autoritaetsoberflaeche sein

## 44.4 Materialisierung

<!-- PROSE-FORMAL: formal.prompt-runtime.commands, formal.prompt-runtime.invariants, formal.prompt-runtime.scenarios -->

Jede tatsaechliche Prompt-Nutzung arbeitet gegen eine
**run-scoped Prompt-Instanz** oder eine aequivalente run-scoped
Projektion auf die gepinnte Bundle-Version.

### 44.4.1 Agent-Prompts

Agents brauchen einen Dateipfad. Deshalb wird fuer jeden Spawn ein
konkreter Prompt-Dateipfad bereitgestellt.

Normativer Zielort:

```text
{project_root}/.agentkit/prompts/{run_id}/{invocation_id}/prompt.md
```

Dabei gilt:

- **statische Prompts** werden aus dem gepinnten Bundle unveraendert
  als run-scoped Instanz oder run-scoped Symlink-/Hardlink-Projektion
  auf genau die gepinnte zentrale Datei bereitgestellt
- **dynamische Prompts** werden aus dem gepinnten Bundle gerendert und
  dann als Instanzdatei abgelegt

Der projektlokale Pfad `prompts/...` bleibt der **default binding
surface** fuer kuenftige Runs und fuer menschenlesbare Orientierung.
Die konsumierte Vertragsoberflaeche eines aktiven Runs bleibt aber ein
run-scoped Prompt-Pfad, damit spaetere Rebinds keinen Mid-run-Drift
erzeugen.

### 44.4.2 Evaluator-Prompts

Deterministische Python-Evaluatoren brauchen keinen Agent-Dateipfad,
duerfen aber genauso wenig direkt gegen mutable Projektkopien laufen.

Sie muessen ihre Templates ebenfalls immer aus dem **gepinnten Bundle**
aufloesen. Eine zusaetzliche Dateimaterialisierung ist fuer sie
optional, die Auditierbarkeit des finalen Prompt-Inhalts aber nicht.

## 44.5 Keine langlebige lokale Prompt-Cache-Autoritaet

<!-- PROSE-FORMAL: formal.prompt-runtime.invariants -->

Ein langlebiger, projektlokaler Prompt-Cache oder eine lokale
Prompt-Kopie ist als Produktionspfad verboten.

Zulaessig sind nur:

- projektlokale read-only Prompt-Projektionen auf konkrete
  Bundle-Versionen
- ein expliziter Lock-Datensatz als bindende Autoritaet
- run-scoped Prompt-Instanzen
- streng versions- und digestgebundene technische Optimierungen, die
  nicht zur neuen Autoritaetsquelle werden

Unzulaessig sind:

- lokale Prompt-Kopien, die unabhaengig vom Bundle weiterleben
- projektlokale Prompt-Dateien, die sich von der gebundenen
  Bundle-Version entkoppeln
- "sync this prompt" als manueller Menschenprozess
- Runtime-Pfade, die mal das Bundle und mal eine alte Projektkopie lesen

## 44.6 Audit und Reproduzierbarkeit

<!-- PROSE-FORMAL: formal.prompt-runtime.entities, formal.prompt-runtime.events, formal.prompt-runtime.invariants -->

Fuer jeden aktiven Run muss rekonstruierbar sein, **welcher Prompt in
welchen Bytes** fuer welchen Agenten oder Evaluator genutzt wurde.

Minimaler Nachweis pro Prompt-Nutzung:

- `run_id`
- `invocation_id`
- `logical_prompt_id`
- `template_relpath`
- `prompt_bundle_version`
- `prompt_bundle_manifest_digest`
- `template_sha256`
- `render_mode` (`static` | `rendered`)
- `render_input_digest` (bei dynamischen Prompts)
- `output_sha256`
- `artifact_path` oder aequivalente Artefakt-ID

Praktische Regel:

- fuer Agent-Prompts wird die final genutzte Datei als Artefakt
  festgehalten
- fuer Evaluator-Prompts muss mindestens der finale gerenderte Inhalt
  oder ein aequivalenter reproduzierbarer Artefaktnachweis vorliegen

## 44.7 Geringe Menschenlast

<!-- PROSE-FORMAL: formal.prompt-runtime.invariants, formal.prompt-runtime.scenarios -->

Die Driftvermeidung wird nicht dem Menschen aufgebuerdet.

Der Mensch soll insbesondere **nicht**:

- lokale Prompt-Kopien manuell loeschen
- Prompt-Versionen von Hand nachziehen
- nach Installer-Updates Prompt-Verzeichnisse "synchronisieren"

Stattdessen gilt:

- der Installer/Rebind aktualisiert nur die Projektbindung
- neue Runs uebernehmen die neue Bindung automatisch
- aktive Runs bleiben stabil auf ihrem gepinnten Prompt-Bundle
- Prompt-Instanzen werden zur Laufzeit automatisch materialisiert

## 44.8 Konsequenz fuer die Praxisfrage

<!-- PROSE-FORMAL: formal.prompt-runtime.invariants, formal.prompt-runtime.scenarios -->

Die Antwort auf die Praxisfrage lautet damit:

- **ja**, statische Prompt-Templates werden projektlokal ueber
  read-only Bindungen auf zentrale Bundle-Dateien exponiert
- **ja**, AgentKit legt fuer aktive Runs zusaetzlich run-scoped
  Prompt-Instanzen oder run-scoped Projektionen an
- **nein**, diese lokalen Pfade sind nie die kanonische Quelle
- **ja**, auch statische Review-Templates muessen immer aus dem aktuell
  gebundenen, run-gepinnten zentralen Bundle stammen
- **nein**, ein alter lokaler Prompt-Cache darf nie weiterverwendet
  werden, nur weil er schon existiert

Damit loest AK3 den Zielkonflikt sauber:

- Agents bekommen Dateipfade
- Bundles bleiben zentral und aktuell
- aktive Runs bleiben reproduzierbar
- Menschen muessen keine Prompt-Hygiene manuell betreiben
