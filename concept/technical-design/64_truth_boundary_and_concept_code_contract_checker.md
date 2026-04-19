---
concept_id: FK-64
title: "Truth Boundary und Concept-to-Code-Contract-Checker"
module: truth-boundary-checker
status: active
doc_kind: detail
parent_concept_id:
authority_over:
  - scope: truth-boundary
  - scope: concept-to-code-contract-checker
defers_to:
  - FK-01
  - FK-17
  - FK-18
  - FK-33
  - FK-35
supersedes: []
superseded_by:
tags: [truth-boundary, contract-checker, static-analysis, architecture]
prose_anchor_policy: strict
formal_refs:
  - formal.state-storage.invariants
  - formal.truth-boundary-checker.invariants
---

# 64 — Truth Boundary und Concept-to-Code-Contract-Checker

<!-- PROSE-FORMAL: formal.state-storage.invariants, formal.truth-boundary-checker.invariants -->

## 64.1 Zweck

Dieses Kapitel zieht die Wahrheitsgrenze von AK3 technisch scharf:

- kanonische operative Wahrheit liegt in den kanonischen Record-
  Familien des State-Backends
- materialisierte Dateien im Story-Verzeichnis sind Exporte,
  Projektionen oder Kompatibilitätsartefakte
- Runtime-, Governance- und Verify-Code dürfen diese Dateien nicht als
  Entscheidungsgrundlage lesen

Zusätzlich definiert dieses Kapitel einen deterministischen
Concept-to-Code-Contract-Checker, der genau diese Grenze gegen den
Python-Code durchsetzt.

## 64.2 Normative Zielarchitektur

### 64.2.1 Kanonische Wahrheit

Die operative Wahrheit für Story-Ausführung, Verify und Governance liegt
in den kanonischen Tabellen-/Record-Familien des State-Backends,
insbesondere:

- `story_contexts`
- `flow_executions`
- `node_executions`
- `attempt_records`
- `artifact_records`
- `guard_decisions`
- `override_records`

### 64.2.2 Nicht-kanonische Materialisierungen

Dateien wie:

- `context.json`
- `phase-state.json`
- `phase-state-*.json`
- `structural.json`
- `qa_review.json`
- `semantic_review.json`
- `adversarial.json`
- `policy.json`
- `decision.json`
- `verify-decision.json`
- `closure.json`

sind nur:

- Exporte
- Projektionen
- Debug-/Audit-Artefakte
- Legacy-/Interop-Artefakte

Sie dürfen nie die einzige Wahrheitsquelle für Runtime- oder
Governance-Entscheidungen sein.

## 64.3 Harte Leseregel

Für folgende Codezonen gilt ein hartes Leserverbot gegen nicht-
kanonische Story-Exports:

- `agentkit.governance.*`
- `agentkit.pipeline.*`
- `agentkit.qa.structural.*`
- weitere im Contract-Checker explizit geschützte Runtime-/Verify-
  Module

Verboten ist dort insbesondere:

- direkte Datei-I/O auf AK3-Story-Exports
- JSON-Parsing solcher Exporte
- Import von Hilfsfunktionen, die diese Exporte laden

Erlaubt bleiben:

- Export-/CLI-/Debug-Pfade
- Migrationen mit expliziter Sonderkennzeichnung
- Tests und Fixtures

## 64.4 Checker-Vertrag

Der Contract-Checker muss mindestens folgende Verstöße fail-closed
erkennen:

1. geschützte Module lesen AK3-Exportdateien direkt
2. geschützte Module importieren bekannte Export-Loader
3. geschützte Module verwenden `json.load`/`json.loads` zur
   Entscheidungsgewinnung über AK3-Exportdateien
4. geschützte Module referenzieren bekannte Exportdateinamen in
   operationalen Pfaden
5. geschützte Module greifen auf nur-projizierte oder nur-
   beobachtende Datenfamilien als operative Hauptwahrheit zu, wenn
   dafür kein expliziter Ausnahmepfad definiert ist

## 64.5 Schärfegrad

Der Checker ist bewusst nicht „warnend“, sondern giftig:

- Verstöße sind CI- und Lint-Fehler
- bekannte Altpfade müssen explizit und knapp begründet ausgenommen
  werden
- neue Verstöße dürfen niemals still akzeptiert werden

## 64.6 Migrationsprinzip

Solange Legacy-Dateiexporte im Repo noch existieren, gilt:

- Schreiben der Exporte ist erlaubt
- Lesen dieser Exporte in geschützten Runtime-/Governance-Pfaden ist
  verboten

Damit bleibt die menschliche und toolingseitige Sichtbarkeit erhalten,
ohne die Wahrheitsgrenze erneut aufzuweichen.
