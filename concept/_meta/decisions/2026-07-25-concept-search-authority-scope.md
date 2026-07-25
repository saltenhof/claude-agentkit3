---
concept_id: META-DEC-2026-07-25-CONCEPT-SEARCH-AUTHORITY-SCOPE
title: Concept-Decision-Record — `authority_scope` als expliziter Eingang von `concept_search`
module: meta
cross_cutting: true
status: active
doc_kind: decision-record
authority_over: []
defers_to: []
supersedes: []
superseded_by:
tags: [meta, decision-record, vectordb, retrieval, authority, ranking, FK-13, AG3-174]
formal_scope: prose-only
---

# Concept-Decision-Record — `authority_scope` als expliziter Eingang von `concept_search`

Datum: 2026-07-25. Record gemaess META-CONCEPT-CONSISTENCY P3
(Blast-Radius-Pflicht bei normativen Aenderungen). Eine einzige,
begrenzte Norm-Ergaenzung an FK-13 §13.9.5 und §13.9.11.

## 1. Anlass

FK-13 §13.9.11 definiert fuenf Regeln der Authority-Auflösung. Die
Regeln 1 („Direkter `authority_over`-Match") und 2 („Scoped Deferral")
ranken gegen einen **Scope** — sie brauchen also die Information, zu
welchem Thema Zustaendigkeit gefragt wird. Der zugehoerige
Werkzeug-Vertrag in §13.9.5 definierte fuer `concept_search` **kein**
solches Feld. Die Norm war damit in sich unvollstaendig: zwei ihrer
fuenf Regeln hatten keine Bezugsgroesse.

Die Implementierung (AG3-174) hatte behelfsweise den `module`-Filter als
Scope verwendet. Das ist fachlich falsch — FK-13 modelliert `module`
(wo ein Dokument liegt) und `authority_over` (wofuer es zustaendig ist)
getrennt — und wurde im Review r4 (Finding N23/R10) entfernt. Danach
blieb der Scope-Eingang leer und die Regeln 1/2 wirkungslos, womit die
Faehigkeit ihren Kernnutzen nur zu drei Fuenfteln erbrachte.

## 2. Entscheidung

Der Werkzeug-Vertrag `concept_search` erhaelt ein **optionales
`authority_scope`-Feld** (String). Es ist **Ranking-Eingang, kein
Filter**: es schraenkt die Treffermenge nicht ein, sondern benennt den
Scope, gegen den §13.9.11 rankt.

- §13.9.5 nimmt den Parameter in die normative Tabelle auf und haelt
  fest, dass er kein Filter ist und **nie** aus `module` abgeleitet
  wird.
- §13.9.11 haelt fest, dass die Regeln 1 und 2 gegen diesen Scope
  ranken, dass Regel 2 dem **Ziel** des qualifizierten `defers_to`
  zugutekommt, und dass ohne `authority_scope` die Regeln 1/2 nicht
  greifen, waehrend 3/4/5 unveraendert wirksam bleiben.

Der Scope kommt damit explizit vom Aufrufer. Ein fehlender Scope ist ein
gueltiger Zustand (kein Fehler): die Suche liefert dann eine
Aehnlichkeitsordnung mit Status- und Modul-/Appendix-Wirkung, aber ohne
Zustaendigkeits-Praezedenz.

**Nicht** Teil dieser Entscheidung: das `doc_kind`-Vokabular aus
§13.9.6, die Frage nach einer eigenen Korpus-Klasse fuer AK3s
Entwicklungs-Korpus, und jede andere Lockerung. Diese Aenderung ist
bewusst auf zwei Abschnitte begrenzt.

## 3. Alternativen

- **Ableitung aus einer `module` → Scope-Zuordnungstabelle** wurde
  verworfen: sie muesste dauerhaft gepflegt werden, verwischt die von
  FK-13 bewusst getrennten Begriffe und nimmt dem Aufrufer die freie
  Themenwahl. Zustaendigkeit ist quer zu Modulgrenzen definiert —
  genau deshalb existiert `authority_over` separat.
- **Weiterverwendung des `module`-Filters als Scope** wurde als Defekt
  eingestuft und in r4 entfernt; die Wiederherstellung waere eine
  Ruecknahme dieses Befunds.
- **Landen mit drei von fuenf Regeln** wurde verworfen: eine stille
  Qualitaetsluecke im Kernnutzen der Faehigkeit ist ein
  ZERO-DEBT-Verstoss.
- **Scope aus dem Suchtext ableiten** (analog zum Detail-Hinweis der
  Regel 3) wurde verworfen: „interface"/„test" ist ein geschlossenes,
  im Konzept benanntes Vokabular, Scopes sind es nicht — eine Ableitung
  waere Raten und wuerde Regel 1 unvorhersehbar ausloesen.

## 4. Impact-Sweep (P3)

Lexikalischer Sweep ueber `concept/`, `guardrails/`, `scripts/ci/`,
`tools/`, `src/` und `stories/` nach `authority_over`, `authority_scope`,
`13.9.5`, `13.9.11` und „Ranking":

- Normativer Owner der Werkzeug-Tabelle und der Ranking-Policy ist
  ausschliesslich FK-13 (§13.9.5, §13.9.11). Kein weiteres
  Konzeptdokument beschreibt die Parameterliste von `concept_search`.
- `concept/_meta/decisions/2026-07-21-vectordb-edge-sharpening.md`
  praezisiert FK-13-Raender, beruehrt aber die Ranking-Policy nicht.
- Die Frontmatter-Spezifikation §13.9.6 definiert `authority_over` als
  Datenfeld des Korpus; sie ist **nicht betroffen** — der neue Parameter
  liest dieses Feld, er aendert es nicht.
- `concept_validate` (§13.9.7) prueft Authority-Disjunktheit und
  Deferral-Zyklen; unveraendert, da keine neue Frontmatter-Semantik
  entsteht.
- Die uebrigen Werkzeuge (§13.4.1) haben keinen Ranking-Eingang und
  bleiben unveraendert.
- K5/Datenhaltung: kein Laufzeitdatum, kein Schema, keine neue
  Property in `StoryContext` — der Scope ist reiner Anfrage-Eingang.

## 5. Betroffenheitsmatrix

| Stelle | Klassifikation | Begruendung |
|---|---|---|
| FK-13 §13.9.5 (`concept_search`-Tabelle) | geaendert | Neuer optionaler Parameter `authority_scope` inkl. Nicht-Filter-/Nicht-Ableitungs-Norm. |
| FK-13 §13.9.11 (Ranking-Policy) | geaendert | Bezugsgroesse der Regeln 1/2 benannt; Verhalten ohne Scope festgehalten. |
| FK-13 §13.9.6 (Frontmatter) | nicht-betroffen | `authority_over` bleibt unveraendert; der Parameter liest nur. |
| FK-13 §13.9.7 (`concept_validate`) | nicht-betroffen | Keine neue Frontmatter-Semantik. |
| FK-13 §13.4.1 (Story-Werkzeuge) | nicht-betroffen | Kein Ranking-Eingang vorhanden. |
| `concept/_meta/decisions/2026-07-25-concept-search-authority-scope.md` | geaendert | Dieses Record persistiert Entscheidung, Alternativen und Impact-Sweep. |
| Werkzeug-Vertrag im Code (`backend/vectordb/contracts.py`) | referenziert-jetzt | Vertrags-SSOT und strikte Validierung folgen der Tabelle; Contract-Test transkribiert sie. |
| Resolver (`backend/vectordb/concept_corpus/resolver.py`) | referenziert | `query_authority_scope` existiert bereits als expliziter Eingang; die Regeln 1/2 werden nur produktiv gespeist. |

Grundlage: PO-Ratifizierung D7 in
`stories/AG3-174-vectordb-retrieval-engine/po-decisions.md`. Diese
Ratifizierung autorisiert genau diese Konzeptaenderung und keine
weitere.
