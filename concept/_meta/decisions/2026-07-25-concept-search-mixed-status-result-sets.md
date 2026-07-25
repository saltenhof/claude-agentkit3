---
concept_id: META-DEC-2026-07-25-CONCEPT-SEARCH-MIXED-STATUS-RESULT-SETS
title: Concept-Decision-Record — Gemischte Status-Ergebnismengen fuer `concept_search`
module: meta
cross_cutting: true
status: active
doc_kind: decision-record
authority_over: []
defers_to: []
supersedes: []
superseded_by:
tags: [meta, decision-record, vectordb, retrieval, ranking, concept-status, FK-13, AG3-174]
formal_scope: prose-only
---

# Concept-Decision-Record — Gemischte Status-Ergebnismengen fuer `concept_search`

Datum: 2026-07-25. Record gemaess META-CONCEPT-CONSISTENCY P3
(Blast-Radius-Pflicht bei normativen Aenderungen). Aufloesung eines
Selbstwiderspruchs in FK-13; begrenzt auf §13.9.5, §13.9.10 und die
Praezisierung von §13.9.11 Regel 4.

## 1. Anlass

FK-13 §13.9.11 Regel 4 gibt Draft- und Archived-Konzepten einen Rang-Abzug.
§13.9.5/§13.9.10 legten aber fest, dass `concept_search` **genau einen**
`concept_status` filtert (Default `active`). Eine Ergebnismenge war damit immer
statushomogen — ein Abzug kann in einer homogenen Menge keine Reihenfolge
veraendern. Regel 4 war also **normativ vorhanden und praktisch wirkungslos**;
FK-13 widersprach sich an dieser Stelle selbst.

Aufgedeckt durch Codex-Review r6 (Finding N36/R10): der bisherige Rule-4-Beweis
war ein Scheinbeweis — er fragte `draft` ab, waehrend das Test-Double einen
*aktiven* Treffer zurueckgab, den ein echter Weaviate-Filter ausgeschlossen
haette. Damit war die Akzeptanzbedingung „alle fuenf Ranking-Regeln" unerfuellt.

## 2. Entscheidung

**Gemischte Statusmengen werden erlaubt.** Der Statusfilter nimmt kuenftig
mehrere Status an; der Default bleibt unveraendert **ausschliesslich `active`**.

Verbindliche Semantik:

- `concept_status` ist eine **Liste** von Status-Werten, Default `["active"]`.
- Zulaessige Werte ausschliesslich `active`, `draft`, `archived`.
- **Fail-closed, keine Koerzierung:** leere Liste, unbekannter Wert, Duplikat,
  falscher Elementtyp und ein **blosser String** statt einer Liste sind benannte
  Validierungsfehler. Keine stille Normalisierung.
- Der Filter wird als **echte Mengen-Bedingung im Transport** ausgewertet; es gibt
  keine clientseitige Nachfilterung.
- Regel 4 bleibt eine **Praezedenz-Stufe** (nicht durch Aehnlichkeitswerte
  ueberstimmbar), konsistent mit der Tier-Ordnung der Regeln 1/2/4; die Regeln 3
  und 5 wirken innerhalb einer Stufe. Innerhalb einer gemischten Menge stehen
  Aktive vor Draft und Archived.

## 3. Alternativen

- **Regel 4 streichen** (Status ist reine Filtersache, kein Ranking-Kriterium) war
  die billigere Variante und wurde verworfen: sie haette eine Faehigkeit
  weggeschnitten statt den Widerspruch fachlich aufzuloesen. Fuer die
  Konzept-Inkubation (DK-16/FK-78) sind Drafts relevant; „zeig mir alles zu Thema
  X, Gueltiges zuerst" ist ein echter Suchmodus, kein Randfall.
- **Union `String | Liste`** (Rueckwaertskompatibilitaet) wurde verworfen: die
  Faehigkeit ist noch nicht ausgeliefert, es existiert keine Installationsbasis,
  und Unions widersprechen der Striktheitslinie aus D2/D7 (Absenz erlaubt,
  alles andere exakt).
- **Clientseitige Nachfilterung** (alles laden, dann filtern) wurde verworfen:
  sie unterlaeuft `limit`, verfaelscht die Server-Rangfolge und macht den Filter
  unbeweisbar.
- **Impliziter Draft-Einschluss** (Default `["active","draft"]`) wurde verworfen:
  Drafts sind nicht normativ; sie muessen explizit angefragt werden.

## 4. Impact-Sweep (P3)

Lexikalischer Sweep ueber `concept/`, `guardrails/`, `scripts/ci/`, `tools/`,
`src/` und `stories/` nach `concept_status`, `archiv`, `draft`, `archived` und
„Regel 4":

- Normativer Owner des Statusfilters und der Ranking-Policy ist ausschliesslich
  FK-13 (§13.9.5, §13.9.10, §13.9.11). Kein weiteres Konzeptdokument beschreibt
  die Parameterliste von `concept_search`.
- Die Frontmatter-Spezifikation §13.9.6 definiert `status` als Korpusfeld; sie ist
  **nicht betroffen** — der Filter liest dieses Feld, er aendert es nicht. Auch das
  offene `doc_kind`-Vokabular (Frage Q2) bleibt unberuehrt.
- `concept_validate` (§13.9.7) prueft Authority-Disjunktheit und
  Supersession-Reziprozitaet ueber Statuswerte; unveraendert, da keine neuen
  Statuswerte entstehen.
- Der Archiv-Pfad (`{concepts_dir}/archiv/` → `concept_status=archived`) bleibt
  unveraendert; nur die Abfrageseite wird zur Menge.
- Die uebrigen Werkzeuge (§13.4.1) haben keinen Statusfilter; `story_search`
  filtert `status` (Story-Status) und ist nicht betroffen.
- K5/Datenhaltung: kein Laufzeitdatum, kein Schema, keine neue Property in
  `StoryContext` — die Aenderung betrifft ausschliesslich Anfrage und Ranking.

## 5. Betroffenheitsmatrix

| Stelle | Klassifikation | Begruendung |
|---|---|---|
| FK-13 §13.9.5 (`concept_search`-Tabelle + Default-Filter-Absatz) | geaendert | `concept_status` wird Liste mit Default `["active"]`; Mengen-Bedingung im Transport; Striktheitsregeln. |
| FK-13 §13.9.10 (Archiv-Handling) | geaendert | Statusfilter als Menge benannt; Default weiterhin nur `active`. |
| FK-13 §13.9.11 Regel 4 | geaendert | Wirkungsbereich praezisiert: wirkt innerhalb gemischter Mengen, bleibt Praezedenz-Stufe. |
| FK-13 §13.9.6 (Frontmatter) | nicht-betroffen | `status` bleibt unveraendert; der Filter liest nur. |
| FK-13 §13.9.7 (`concept_validate`) | nicht-betroffen | Keine neuen Statuswerte. |
| FK-13 §13.4.1 (Story-Werkzeuge) | nicht-betroffen | Kein Konzept-Statusfilter vorhanden. |
| `concept/_meta/decisions/2026-07-25-concept-search-mixed-status-result-sets.md` | geaendert | Dieses Record persistiert Entscheidung, Alternativen und Impact-Sweep. |
| Werkzeug-Vertrag im Code (`backend/vectordb/contracts.py`) | referenziert-jetzt | Vertrags-SSOT und strikte Validierung folgen der Tabelle; Contract-Test transkribiert sie. |
| Transport-Adapter (`integration_clients/vectordb/weaviate_adapter.py`) | referenziert-jetzt | Setzt die Mengen-Bedingung serverseitig. |
| Resolver (`backend/vectordb/concept_corpus/resolver.py`) | referenziert | Die Stufen-Abstufung der Regel 4 existiert bereits; sie wird durch gemischte Mengen erst beobachtbar. |

Grundlage: PO-Ratifizierung D8 in
`stories/AG3-174-vectordb-retrieval-engine/po-decisions.md`. Zusammen mit D7 sind
das die einzigen Konzeptaenderungen, die AG3-174 gestattet sind.
