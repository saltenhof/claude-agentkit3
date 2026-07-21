---
concept_id: META-DEC-2026-07-21-VECTORDB-EDGE-SHARPENING
title: Concept-Decision-Record — VektorDB-/Retrieval-Raender praezisiert (FK-13-Umfeld)
module: meta
cross_cutting: true
status: active
doc_kind: decision-record
authority_over: []
defers_to: []
supersedes: []
superseded_by:
tags: [meta, decision-record, vectordb, retrieval, installer, mcp, harness, FK-13]
formal_scope: prose-only
---

# Concept-Decision-Record — VektorDB-/Retrieval-Raender praezisiert (FK-13-Umfeld)

Datum: 2026-07-21. Fuenf entschiedene Praezisierungen an der VektorDB-/
Retrieval-Faehigkeit (FK-13). Vier sind **Ableitungen** aus dem bestehenden
Normbestand (nur fehlende Detaillierung wird nachgezogen), eine ist eine
**PO-Entscheidung**. Es wird kein neuer Scope erfunden; die Entscheidungen sind
alle getroffen und werden hier normativ verankert.

## 1. Praezisierung 1 — Feature-Flag → Pflichtinfrastruktur (Ableitung)

FK-13 §13.1 sagt bereits „VektorDB-Abgleich ist immer aktiv. Keine
Feature-Flag-Stufung." FK-21 §21.4.3 verstaerkt das (Pflicht, fail-closed, kein
Fallback). Einzige Abweichung war der Installer-Zweig `branch_vectordb_enabled`
(FK-50), der VektorDB als optional behandelte.

Entscheidung: `features.vectordb` ist nur noch ein **deprecateter
Migrations-Konfigschluessel**. In einem unterstuetzten Zielprojekt ist
`features.vectordb: false` ein harter Konfigurationsfehler, kein Abschaltpfad.
Der Optionalitaetszweig (`branch_vectordb_enabled`) ist als **deprecated**
markiert; die Code-Entfernung ist einer spaeteren Story vorbehalten — hier nur
die Norm. Der bestehende `SKIPPED`/`vectordb_disabled`-Pfad in FK-50 §50.3 CP 10
bleibt bis dahin als deprecateter Uebergang erhalten; die ARE-Optionalitaet
(`features.are`) ist davon unberuehrt. FK-21 referenziert den Optionalitaetsast
nicht und bleibt unveraendert.

## 2. Praezisierung 2 — Quelle→Tool-Zuordnung und Checkpoint-Nummern (Ableitung)

FK-13 §13.3.2 ordnete alle Quellen pauschal `story_sync` zu; die spaetere,
spezifischere FK-13 §13.9.5 fuehrt `concept_sync`/`concept_search` ein (§13.9.2:
„Trennung auf Tool-Ebene"). Die spezifischere Stelle regelt.

Entscheidung: Konzept- und Architekturquellen (`source_type="concept"`) laufen
ueber `concept_sync`/`concept_search`, Story- und Research-Quellen ueber
`story_sync`/`story_search`. FK-13 §13.3.2 ist entsprechend korrigiert und
verweist auf §13.9.5 als massgeblich.

**Checkpoint-Nummern:** FK-50 ist Checkpoint-Autoritaet. Es gilt **CP 10**
(MCP-Server-Registrierung) und **CP 10a** (ConceptContext-Properties und
Erstindizierung). Die beilaeufigen CP-9/CP-9a-Nennungen in FK-13 waren falsch und
sind angeglichen: FK-13 §13.4.3 (MCP-Registrierung) → CP 10; die
Install-Erstindizierungs-Zeilen in FK-13 §13.7.1 und §13.9.9 → CP 10a. (§13.7.1
liegt ausserhalb der beiden namentlich genannten Abschnitte, traegt aber
dieselbe falsche Nummer; sie wird aus ZERO-DEBT-Konsistenz mit angeglichen.)

## 3. Praezisierung 3 — Tokenizer-Bereitstellung (Ableitung aus FK-43 + Fail-closed)

FK-13 §13.2 benennt das Modell `sentence-transformers/all-MiniLM-L6-v2`, aber
nicht den Lieferweg. Aus FK-43 (versionierte, unveraenderliche Bundle-Assets) und
der Fail-closed-/Kein-stiller-Fallback-Regel folgt zwingend:

Entscheidung: Der Tokenizer (`tokenizer.json` samt Vokabular) wird als
**versioniertes Package-Asset** mit **gebundenem Digest** (SHA-256) und gepinnter
Modell-/Tokenizer-Revision ausgeliefert. Vor Nutzung wird der Digest gegen den
Sollwert geprueft. **Fail-closed:** fehlt das Asset oder weicht der Digest ab,
bricht der Lauf hart ab — keine Laufzeit-Netzabholung, kein zeichenbasierter
Ersatz. Verankert in FK-13 §13.2.

## 4. Praezisierung 4 — Codex-MCP-Registrierungsvertrag (Ableitung)

FK-76 normierte bisher nur `.codex/hooks.json`, keinen MCP-Eintrag. Der
Claude-Code-Vertrag (projektlokale `.mcp.json`, erforderliche Server,
semantischer Merge, fail-closed, nie Benutzer-/Globalkonfiguration; Owner FK-50
§50.3 CP 10) wird auf das extern von OpenAI dokumentierte Codex-Format
gespiegelt.

Entscheidung: FK-76 §76.5.4 ergaenzt die MCP-Server-Registrierung: projektlokale
`.codex/config.toml`, Tabelle `[mcp_servers.<id>]` mit `command`, `args`, `cwd`,
`env`, `required = true`; **semantischer Merge**, der fremde Tabellen erhaelt;
**fail-closed** bei unparsebarer/konfligierender Konfiguration; **niemals**
Benutzer-/Globalkonfiguration (`~/.codex/`). Explizit als Spiegelung des
Claude-Code-`.mcp.json`-Vertrags gekennzeichnet.

## 5. Praezisierung 5 — Shadow-Replace: „atomar" → Bounded-Window (PO-ENTSCHEIDUNG)

FK-13 §13.9.9 beschrieb den Concept-Sync-Shadow-Replace als impliziten
Atomizitaetsvorgang. Weaviate garantiert das nicht nativ.

PO-Entscheidung: Bounded-Window akzeptieren, Norm ehrlich abschwaechen — **kein**
CAS-Mechanismus. Der Replace ist **nicht** transaktional atomar; eine neue
Generation wird geschrieben, dann die alte entfernt. Waehrend eines **kurzen
Umschaltfensters** koennen nebenlaeufige Leser einen Uebergangsstand sehen. Der
Abschluss wird ueber `corpus_revision` markiert. Formulierung:
„generationskonsistent mit kurzem Umschaltfenster" statt „atomar"; jede
Behauptung transaktionaler Atomizitaet und jede CAS-/Generations-Zeiger-Mechanik
an dieser Stelle entfaellt. Verankert in FK-13 §13.9.9.

## 6. Betroffenheitsmatrix

| # | Rand | Datei / Abschnitt | Klassifikation | Aenderung |
|---|------|-------------------|----------------|-----------|
| 1 | Feature-Flag → Pflicht | FK-13 §13.1 | geaendert | `features.vectordb` als deprecateter Migrations-Schluessel; `false` = harter Konfigurationsfehler |
| 1 | Feature-Flag → Pflicht | FK-03 §3.1 | geaendert | Deprecation-Vermerk am Schluessel `features.vectordb` |
| 1 | Feature-Flag → Pflicht | FK-50 §50.3 CP 10 | geaendert | `branch_vectordb_enabled`/`vectordb: false` als deprecated markiert (Norm; Code-Entfernung spaeter); SKIPPED-Pfad als Uebergang erhalten |
| 1 | Feature-Flag → Pflicht | FK-21 §21.4.3 | nicht-betroffen | referenziert Optionalitaetsast nicht |
| 2 | Quelle→Tool | FK-13 §13.3.2 | geaendert | Konzept/Architektur → `concept_sync`; Story/Research → `story_sync`; Verweis auf §13.9.5 |
| 2 | Checkpoint-Nummern | FK-13 §13.4.3, §13.7.1, §13.9.9 | geaendert | CP 9/9a → CP 10/10a (FK-50 ist Autoritaet) |
| 2 | Checkpoint-Autoritaet | FK-50 §50.3 CP 10/CP 10a | referenziert | Nummern unveraendert; als Autoritaet bestaetigt |
| 3 | Tokenizer | FK-13 §13.2 | geaendert | versioniertes Package-Asset + Digest + Pinning + fail-closed |
| 3 | Tokenizer | FK-43 | referenziert | versionierte Bundle-Assets als Herleitungsbasis |
| 4 | Codex-MCP | FK-76 §76.5.4 | geaendert | neue MCP-Server-Registrierung `.codex/config.toml` als Spiegelung |
| 4 | Codex-MCP | FK-50 §50.3 CP 10 | referenziert | Owner des Merge-/Conformance-Vertrags |
| 5 | Shadow-Replace | FK-13 §13.9.9 | geaendert | „atomar" → „generationskonsistent mit kurzem Umschaltfenster"; kein CAS |

Kein Story-Schnitt und kein Produktionscode in diesem Schritt — das ist ein
separater, nachgelagerter Schritt.
