---
concept_id: META-DEC-2026-07-14-CONCEPT-AUTHORITY-PROSE-CHECK
title: Concept-Decision-Record — Concept-Authority-Prose-Check W2
module: meta
cross_cutting: true
status: active
doc_kind: decision-record
authority_over: []
defers_to: []
supersedes: []
superseded_by:
tags: [meta, decision-record, concept-consistency, nightly, AG3-159]
formal_scope: prose-only
---

# Concept-Decision-Record — Concept-Authority-Prose-Check W2

Datum: 2026-07-14. Record gemaess META-CONCEPT-CONSISTENCY P3
(Blast-Radius-Pflicht bei normativen Aenderungen).

## 1. Anlass

META-CONCEPT-CONSISTENCY P2 bindet normative Prosa an die in der
Frontmatter deklarierte Authority. W2 war als LLM-gestuetzter Detektor
mit deterministischer Policy spezifiziert, aber sein konkreter
Vor-Merge-Aufruf und die Abgrenzung zur blockierenden Push-CI waren im
Betriebsmodell noch nicht als ausfuehrbarer Vertrag dokumentiert.

## 2. Entscheidung

W2 konsumiert ausschliesslich die deterministischen Working-Tree-Chunks
des Konzept-Ingesters. Das LLM klassifiziert je Chunk nur, ob normative
Aussagen vorliegen und welche Scopes sie betreffen. Eine reine Policy
entscheidet anschliessend anhand der Live-Scope-Vokabeln sowie
`authority_over` und scope-qualifizierten `defers_to`-Kanten. Skalare
Dokument-Deferrals erteilen keine Scope-Authority.

Der produktive Transport verwendet den bestehenden Hub-Lifecycle ueber
`HubLlmClient`; Parse- und Transportfehler werden als benannte ERROR-
Befunde behandelt. Befunde tragen stabile Dokument-/Anker-/Aussage-
Referenzen sowie Prompt- und Modellversion. Die versionierte Baseline
unter `concept/_meta/` akzeptiert nur Eintraege mit konkretem Grund,
listet unterdrueckte Befunde weiterhin und meldet veraltete Eintraege.

W2 laeuft im taeglichen Jenkins-Timer nicht blockierend und vor der
Landung normativer Konzeptaenderungen als dokumentierter, auf die Git-
Range begrenzter CLI-Aufruf. Die regulaeren blockierenden Konzept-
Stages bleiben unveraendert und hub-frei.

## 3. Alternativen

- Ein blockierendes Push-Gate wurde verworfen, weil dessen Ergebnis von
  einem externen LLM abhinge und damit den CI-Determinismus verletzte.
- Der externe Weaviate-/MCP-Index wurde als Quelle verworfen, weil sein
  Zustand nicht Teil des Working Trees ist; verwendet wird dieselbe
  lokale Discovery-Funktion, die den Index speist.
- Eine LLM-Entscheidung ueber PASS oder ERROR wurde verworfen, weil nur
  der Registry-Abgleich die Authority-Regel reproduzierbar durchsetzt.
- Eine stille oder pauschal begruendete Baseline wurde verworfen, weil
  sie neue P2-Verstoesse unsichtbar machen wuerde.

## 4. Impact-Sweep (P3)

Der semantische und lexikalische Sweep umfasste den META-Owner, die
Konzept-Frontmatter-Flaeche, den Ingest-Chunker, W1-/W4-Baseline- und
Gate-Praezedenzen, den bestehenden Hub-Client, Jenkins, `AGENTS.md`,
Story-Status und Backlog-Snapshot. Die neue Policy aendert keine
fachliche Authority und keinen Produktiv-Service; sie operationalisiert
ausschliesslich P2. K5 ist nicht betroffen, weil die versionierte
Repo-Baseline kein Runtime-State ist.

## 5. Betroffenheitsmatrix

| Stelle | Klassifikation | Begruendung |
|---|---|---|
| `concept/_meta/konzept-konsistenz-governance.md` §6 | geaendert | Der normative Owner erhaelt den exakten Vor-Merge-Aufruf und die explizite Non-Blocking-Abgrenzung. |
| `concept/_meta/decisions/2026-07-14-concept-authority-prose-check.md` | geaendert | Dieses Record persistiert Entscheidung, Alternativen und Impact-Sweep. |
| `tools/concept_governance/` und W2-Prompt | referenziert-jetzt | Implementieren Klassifikation, deterministische Policy, Befundschluessel und Baseline-Vertrag. |
| `tools/concept_ingester/` | geaendert | Ausschliesslich paketrelative Imports machen die unveraenderte Discovery ueber den festgelegten CLI-Bootstrap wiederverwendbar. |
| `scripts/ci/check_concept_authority_prose.py` | geaendert | Stellt Nightly- und range-begrenzten Pre-Merge-Einstieg bereit. |
| `Jenkinsfile` | geaendert | Der taegliche Timer verwendet den expliziten Nightly-Modus; W2 meldet Fehler, blockiert den Build aber nicht. |
| `AGENTS.md` | geaendert | Dokumentiert den verpflichtenden W2-Aufruf vor normativen Konzept-Merges. |
| Bestehende W1-/W4- und Push-CI-Stages | nicht-betroffen | Keine Hub-Abhaengigkeit oder W2-Ausfuehrung wird in einen blockierenden Stage aufgenommen. |
| Produktive Backend- und Runtime-State-Modelle | nicht-betroffen | W2 ist Repo-Governance-Tooling ausserhalb der AK3-Laufzeit. |
