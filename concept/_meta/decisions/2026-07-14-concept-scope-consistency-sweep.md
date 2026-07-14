---
concept_id: META-DEC-2026-07-14-CONCEPT-SCOPE-CONSISTENCY-SWEEP
title: Concept-Decision-Record — Concept-Scope-Consistency-Sweep W3
module: meta
cross_cutting: true
status: active
doc_kind: decision-record
authority_over: []
defers_to: []
supersedes: []
superseded_by:
tags: [meta, decision-record, concept-consistency, nightly, AG3-160]
formal_scope: prose-only
---

# Concept-Decision-Record — Concept-Scope-Consistency-Sweep W3

Datum: 2026-07-14. Record gemaess META-CONCEPT-CONSISTENCY P3
(Blast-Radius-Pflicht bei normativen Aenderungen).

## 1. Anlass

META-CONCEPT-CONSISTENCY W3 verlangt eine semantische
Widerspruchssuche innerhalb jedes `authority_over`-Scopes. Der konkrete
Vor-Merge-Aufruf, die Begrenzung auf geschlossene Scope-Sets und stabile
Partitionen sowie der verpflichtende P4-Triage-Vertrag waren im
Betriebsmodell noch nicht als ausfuehrbarer Vertrag dokumentiert.

## 2. Entscheidung

W3 invertiert deterministisch die von der repo-lokalen Discovery
projizierten `authority_over`- und scope-qualifizierten `defers_to`-
Metadaten. Dadurch entsteht je Live-Scope ein geschlossenes Set stabiler
Chunks ohne Weaviate-, MCP- oder vorgelagerte LLM-Klassifikation. Grosse
Sets werden vollstaendig und reproduzierbar partitioniert; es wird nie
gekuerzt und nie ueber Scope-Grenzen verglichen.

Jedes Set beziehungsweise jede Partition erzeugt genau einen
strukturierten Hub-Aufruf. Das LLM darf nur Widerspruchsgruppen mit
exakten Zitaten und Fundstellen melden. Eine deterministische Policy
validiert alle Fundstellen gegen den Eingabesatz und erzeugt daraus den
ERROR-Befund `SCOPE_CONTRADICTION`; das LLM liefert kein Verdict.
Transport-, Parse- und Evidence-Vertragsfehler verwerfen alle
Teilergebnisse und erzeugen zusaetzlich `INCOMPLETE_SWEEP`.

W2 und W3 verwenden dieselbe versionierte Governance-Baseline. W3 hat
eine eigene Befundart und erweitert den Schluessel nur um die weiteren
Widerspruchs-Fundstellen. Ein triagierter W3-Eintrag ist ausschliesslich
mit nichtleerem Grund und der P4-Formalisierungspruefung (Ja/Nein plus
konkreter Begruendung) gueltig. Der ungefilterte Nightly-Lauf ist nicht
blockierend; vor normativen Konzeptlandungen wird W3 mit wiederholbarem
`--scope` nur fuer die betroffenen Scopes ausgefuehrt.

## 3. Alternativen

- Ein paarweiser Gesamtkorpusvergleich wurde verworfen, weil er die
  Scope-Authority ignoriert und quadratisch skaliert.
- Eine vorgelagerte W2-Klassifikation jedes Chunks wurde verworfen, weil
  sie den W3-Lauf unnoetig vervielfacht; W3 liest die geschlossenen Sets
  direkt.
- Stilles Abschneiden grosser Sets wurde verworfen, weil ein scheinbarer
  PASS bei ungeprueften Aussagen die Fail-Closed-Regel verletzt.
- Ein LLM-Verdict oder eine vom LLM ausgefuellte P4-Triage wurde
  verworfen, weil Policy und fachliche Formalisierungsentscheidung
  deterministisch beziehungsweise menschlich verantwortet bleiben.
- Ein blockierendes Push-Gate wurde verworfen, weil es die regulaere CI
  an einen externen Hub koppeln wuerde.

## 4. Impact-Sweep (P3)

Der semantische und lexikalische Sweep umfasste den META-Owner, W2-
Discovery/Authorization/Baseline/Hub-Infrastruktur, Konzept-Ingester,
Jenkins, `AGENTS.md`, Story-Status und Backlog-Snapshot. W3 aendert keine
fachliche Authority und keinen Produktiv-Service. K5 ist nicht betroffen,
weil die Repo-Baseline kein Runtime-State ist. W1 und W4 bleiben
blockierend und hub-frei; W2 bleibt unveraendert nightly/pre-merge.

## 5. Betroffenheitsmatrix

| Stelle | Klassifikation | Begruendung |
|---|---|---|
| `concept/_meta/konzept-konsistenz-governance.md` §6 | geaendert | Der normative Owner erhaelt Scope-Aufruf, Bound und P4-/Fail-Closed-Vertrag. |
| `concept/_meta/decisions/2026-07-14-concept-scope-consistency-sweep.md` | geaendert | Dieses Record persistiert Entscheidung, Alternativen und Impact-Sweep. |
| `tools/concept_governance/` und W3-Prompt | referenziert-jetzt | Implementieren Set-Inversion, Partitionierung, Evaluator, Policy und gemeinsame Baseline. |
| `scripts/ci/check_concept_scope_consistency.py` | geaendert | Stellt Nightly-, Scope- und Smoke-Einstieg bereit. |
| `Jenkinsfile` | geaendert | W3 laeuft neben W2 im taeglichen Timer explizit nicht blockierend. |
| `AGENTS.md` | geaendert | Dokumentiert den scope-gefilterten Aufruf vor normativen Konzeptlandungen. |
| Bestehende W1-/W4- und Push-CI-Stages | nicht-betroffen | Keine Hub-Abhaengigkeit wird in einen blockierenden Stage aufgenommen. |
| Produktive Backend- und Runtime-State-Modelle | nicht-betroffen | W3 ist Repo-Governance-Tooling ausserhalb der AK3-Laufzeit. |
