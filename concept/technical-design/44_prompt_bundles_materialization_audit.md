---
concept_id: FK-44
title: Prompt-Bundles, Materialisierung und Audit
module: prompt-runtime
domain: prompt-runtime
status: active
doc_kind: core
parent_concept_id:
authority_over:
  - scope: prompt-bundles
  - scope: prompt-materialization
  - scope: prompt-audit
  - scope: execution-contract-digest
defers_to:
  - target: FK-10
    scope: runtime-deployment
    reason: Zentrale Installation, lokale Projektstruktur und Laufzeitgrenzen sind dort beschrieben
  - target: FK-11
    scope: llm-provider
    reason: Pool-Aufrufe und Prompt-Execution-Schnitt liegen dort
  - target: FK-50
    scope: installer
    reason: Projektregistrierung und Bundle-Pin-Aktualisierung werden dort ausgefuehrt; FK-50 ruft PromptRuntime.update_binding auf
  - target: FK-71
    scope: artifact-persistence
    reason: AuditRecords werden via artifacts.ArtifactManager persistiert; Artefakt-ID-Vergabe liegt bei artifacts
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
glossary:
  exported_terms:
    - id: bundle-materialization
      definition: >
        Der Vorgang, bei dem ein run-scoped Prompt-Instanzpfad oder eine
        aequivalente run-scoped Projektion aus dem gepinnten PromptBundle
        erzeugt wird. Jeder Agent-Prompt-Aufruf setzt eine abgeschlossene
        Materialisierung voraus.
    - id: bundle-version
      definition: >
        Die gebundene, unveraenderliche Versionskennung eines PromptBundle,
        bestehend aus bundle_id und bundle_version. Sie ist Bestandteil des
        Lock-Datensatzes und jedes Run-Prompt-Pins und darf waehrend eines
        aktiven Runs nicht geaendert werden.
    - id: project-prompt-pin
      definition: >
        Die projektspezifische Zuordnung eines PromptBundle zu einem Projekt,
        autoritativ verwaltet durch den Lock-Datensatz
        .agentkit/config/prompt-bundle.lock.json. Die read-only Dateien
        unter prompts/ sind nur eine Projektion dieses Pins, nicht die
        Pin-Autoritaet selbst. Klasse: ProjectPromptPin
        (agentkit.backend.prompt_runtime.bundle_pinning).
    - id: prompt-audit-hash
      definition: >
        Der kryptografische Nachweis einer Prompt-Nutzung, bestehend aus
        template_sha256, render_input_digest (bei dynamischen Prompts) und
        output_sha256. Ermoeglicht die lueckenlose Rekonstruktion, welcher
        Prompt in welchen Bytes fuer welchen Agenten oder Evaluator genutzt
        wurde.
    - id: prompt-bundle
      definition: >
        Eine systemweit installierte, versionierte und unveraenderliche
        Sammlung von Prompt-Templates. Kanonische Quelle aller produktiven
        Prompts; wird durch den Installer verwaltet und ist nie
        projektlokal editierbar.
    - id: prompt-template
      definition: >
        Eine einzelne, adressierbare Vorlage innerhalb eines PromptBundle,
        identifiziert durch logical_prompt_id und template_relpath. Kann
        statisch (wird unveraendert verwendet) oder dynamisch (wird zur
        Laufzeit gerendert) sein.
    - id: execution-contract-digest
      definition: >
        Beim Setup gebildeter Digest des fachlichen Execution-Contracts
        eines Runs: Story-Spec-Version und fachlich tragende Spec-Felder,
        einschlaegige Projekt-/QA-/Gate-Konfiguration sowie
        Skill-/Prompt-/Capability-Versionen. Der run-prompt-pin ist eine
        Komponente davon. Dient als Fencing-Praedikat fuer gefencte
        Abschluss-Commits und macht Contract-Aenderungen waehrend eines
        aktiven Runs explizit statt still wirksam.
      see_also:
        - term: run-prompt-pin
          domain: prompt-runtime
    - id: run-prompt-pin
      definition: >
        Der bei Run-Start eingefrorene Snapshot der aufgeloesten Bundle-Bindung
        fuer genau einen Run, persistiert unter
        .agentkit/manifests/prompt-pins/{run_id}.json. Spaetere
        Rebind-Aktionen veraendern den Pin eines laufenden Runs nicht.
  internal_terms:
    - id: bundle-manifest-digest
      reason: >
        Implementierungsdetail der Integritaetspruefung innerhalb des
        PromptBundle-Stores; wird nicht als eigenstaendiger Vertragsbegriff
        nach aussen getragen, sondern ist Bestandteil von PromptAuditHash
        und RunPromptPin.
    - id: render-mode
      reason: >
        Internes Enum (static | rendered) der Materialisierungslogik;
        beschreibt, wie ein PromptTemplate in eine Instanz ueberfuehrt wird.
        Kein exportierter Vertragsbegriff, weil andere BCs nur das Ergebnis
        (prompt-instance-path), nicht die interne Render-Strategie kennen.
    - id: run-scoped-prompt-instance
      reason: >
        Interner Hilfsbegriff fuer den materialisierten Prompt-Dateipfad
        unter .agentkit/prompts/{run_id}/{invocation_id}/prompt.md; das
        Konzept selbst ist nach aussen durch bundle-materialization und
        prompt-audit-hash repraesentiert.
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
harness-neutraler Bindungspunkt unter `prompts/` bereitgestellt.
Autoritativ ist dabei nicht die Dateiansicht selbst, sondern der
explizite Lock-Datensatz
`.agentkit/config/prompt-bundle.lock.json`.

Der projektlokale `prompts/`-Pfad
ist eine reine Konvention zur menschenlesbaren Orientierung, kein
Mechanikbezug zu einem bestimmten Harness. Weder Claude Code noch Codex
benoetigen einen projektlokal vorgeschriebenen Prompt-Pfad: Worker
erhalten den tatsaechlich konsumierten Prompt-Pfad (run-scoped, siehe
§44.4.1) ueber Variable-Substitution. Codex' Custom-Prompts sind
user-home-scoped (`~/.codex/prompts/`) und fuer AK3-Produktivpfade
bewusst nicht relevant; der projektweite Skill-Auslieferungspfad fuer
beide Harnesses ist in FK-43 §43.4.1 normiert.

Prompt-**Inhalte** sind ebenfalls harness-neutral. Verweise auf
`CLAUDE.md` im Projektroot gelten fuer beide Harnesses; Codex liest die
Datei ohne Substitution. AK3 pflegt die Basisinstruktionen einheitlich
in `CLAUDE.md`; eine eigenstaendige `AGENTS.md`-Quelle ist im AK3-Setup
nicht vorgesehen.

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

Die Schnittstelle `PromptRuntime.update_binding(bundle_id, version)` ist
die Top-Surface dieses BC fuer projektweite Pin-Aktualisierungen.
Aufrufer ist ausschliesslich `installation-and-bootstrap` (FK-50).
Andere BCs rufen diese Schnittstelle nicht direkt auf.

## 44.3a Verallgemeinerung: Execution-Contract-Digest

Das Run-Pinning aus §44.3 ist der Prototyp eines allgemeineren
Prinzips: Ein aktiver Run arbeitet nicht nur gegen einen
eingefrorenen Prompt-Stand, sondern gegen einen eingefrorenen
**fachlichen Execution-Contract**. Beim Setup wird dafuer ein
**`execution_contract_digest`** gebildet aus:

- der Story-Spec-Version und den fachlich tragenden Spec-Feldern
  (Scope, Akzeptanzkriterien, Story-Text; Mutations-Schranken dieser
  Felder: FK-59 §59.9a)
- der einschlaegigen Projekt-, QA- und Gate-Konfiguration
- den Skill-, Prompt- und Capability-Versionen

Der bestehende `run-prompt-pin` (§44.3) ist eine **Komponente** dieses
Digests; seine Semantik ("spaetere Rebind-Aktionen veraendern den Pin
eines laufenden Runs nicht") bleibt unangetastet gueltig.

Fuer Aenderungen an Contract-Bestandteilen waehrend eines aktiven
Runs gibt es genau drei zulaessige Wirkungsklassen:

1. **run-neutral** — die Aenderung beruehrt keinen Bestandteil des
   Digests des laufenden Runs;
2. **gepinnt-fuer-neue-Runs** — die Aenderung wird wirksam, aber erst
   fuer kuenftige Runs; der laufende Run arbeitet auf seinem Digest
   weiter (Default, analog §44.3);
3. **bewusster administrativer Eingriff** — die Aenderung soll den
   laufenden Run treffen; sie laeuft dann sichtbar gegen den
   Run-Owner bzw. als explizite Run-Invalidierung, nie als stiller
   Mid-run-Drift.

Der Digest ist ein **Run-Pinning-/Audit-Artefakt**: er haelt den
eingefrorenen fachlichen Contract eines Runs reproduzierbar und
auditierbar fest. Er ist **kein Fencing-Praedikat**. Die operative
Abschottung eines Runs gegen fremde/veraltete Mutationen leistet allein
der aktive Ownership-Record (Lease, FK-91 §91.1a Regel 15): wer den
Lease nicht (mehr) haelt, kann ohnehin nichts Mutierbares durchsetzen,
und ein laufender Run behaelt seinen gepinnten Digest (Klasse 2), ist
also nicht "veraltet". Ein "bewusster administrativer Eingriff"
(Klasse 3) laeuft weiterhin sichtbar gegen den Run-Owner bzw. als
explizite Run-Invalidierung — nie als stiller Mid-run-Drift und nie als
automatisch abgeleiteter Stale-Verwurf.

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

`verify_system.LlmEvaluator` muss alle Templates ausschliesslich ueber
`PromptRuntime.materialize_prompt` aufloesen. Ein direkter Zugriff auf
lokale Prompt-Dateien oder den Bundle-Store ist dem Evaluator verboten.
`PromptRuntime.materialize_prompt` ist die einzige zulaessige
Aufloesungsschnittstelle fuer Evaluator-Prompts.

## 44.5 Keine langlebige lokale Prompt-Cache-Autoritaet

<!-- PROSE-FORMAL: formal.prompt-runtime.invariants -->

Ein langlebiger, projektlokaler Prompt-Cache oder eine lokale
Prompt-Kopie ist als Produktionspfad verboten.

Das Schema fuer den projektspezifischen Pin (`ProjectPromptPin`) liegt
im Sub `agentkit.backend.prompt_runtime.bundle_pinning`. Der Lock-Datensatz
`.agentkit/config/prompt-bundle.lock.json` ist die laufzeitautorative
Projektion dieses Schemas; das Schema selbst ist nicht projektlokal.
Run-Pins werden als `RunPromptPin`-Instanzen materialisiert.

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

Das Pydantic-Schema `PromptAuditHash` (Felder: `template_sha256`,
`render_input_digest`, `output_sha256`) wird vom Sub
`agentkit.backend.prompt_runtime.materialization` definiert und ist Bestandteil
jedes vollstaendigen Audit-Records.

Audit-Records werden als typisierte Artefakte ueber
`artifacts.ArtifactManager` persistiert (Beziehung PR -> A). Der
`ArtifactManager` (BC artifacts) ist die einzige zulaessige
Persistenzschicht fuer Audit-Records; direktes Schreiben in
Telemetrie-Tabellen oder lose JSON-Dateien ist unzulaessig.

Der `ArtifactManager` vergibt die autoritative Artefakt-ID; diese ID
fliesst als `artifact_path`-Referenz in den Audit-Record zurueck.

Praktische Regel:

- fuer Agent-Prompts wird die final genutzte Datei als Artefakt
  festgehalten
- fuer Evaluator-Prompts muss mindestens der finale gerenderte Inhalt
  oder ein aequivalenter reproduzierbarer Artefaktnachweis vorliegen

Telemetrie-Ereignis: Das Event `prompt_used` ist in diesem BC nicht
eingefuehrt. Falls es in einem kuenftigen Inkrement eingefuehrt wird,
muss die EventTypeId in der BC 9 TelemetryContract-Liste registriert
werden, bevor das Event emittiert werden darf.

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
