---
concept_id: META-DEC-2026-07-26-POST-COMPLETION-STALE-CHUNK-CONTRACT
title: Concept-Decision-Record — Ratifizierter Vertrag fuer veraltete Chunks nach einer Claim-Uebernahme
module: meta
cross_cutting: true
status: active
doc_kind: decision-record
authority_over: []
defers_to: []
supersedes: []
superseded_by:
tags: [meta, decision-record, vectordb, retrieval, sync, generation, observability, FK-13, FK-04, AG3-177]
formal_scope: prose-only
---

# Concept-Decision-Record — Ratifizierter Vertrag fuer veraltete Chunks nach einer Claim-Uebernahme

Datum: 2026-07-26. Record gemaess META-CONCEPT-CONSISTENCY P3
(Blast-Radius-Pflicht bei normativen Aenderungen). Grundlage:
PO-Ratifizierung in
`stories/AG3-177-stale-chunk-visibility-after-takeover/po-decision.md`,
Entwurf mit gemessenen Kosten in `design.md` derselben Story.

## 1. Anlass

AG3-174 hat den zerstoerenden Schritt des VektorDB-Syncs storage-seitig an
die Quell-Generation gebunden (D9): ein ueberholter Halter kann Daten einer
neueren Generation nicht loeschen, und die gemeldete Frische kann nicht
zurueckgedreht werden. Offen blieb die **Gegenrichtung**: der Chunk-Write
selbst ist an diesem Rand nicht fenchbar (`weaviate-client 4.22.0` kennt
keine Vorbedingung fuer Schreibvorgaenge), also kann ein wieder
anlaufender, ueberholter Schreiber Zeilen **seiner** niedrigeren Generation
**anhaengen**.

Der eingebaute Abschluss-Delete verkleinert dieses Fenster, schliesst es
aber nicht: seine Grenze ist die Beobachtungsgrenze des **paginierten
Lesevorgangs** davor, und eine Paginierung ist kein Snapshot. Ein einzelner
endlicher Durchgang kann ein spaeter oder nebenlaeufig eintreffendes
Schreiben strukturell nicht abdecken.

FK-13 §13.9.9 hielt diesen Rest als **offenen, nicht ratifizierten** Punkt
fest — ausdruecklich als Nicht-Vertrag. Genau dieser Zustand war
unhaltbar: eine Norm, die ihre eigene Luecke als „ungeklaert" fuehrt, ist
nicht wahr im Sinne von ZERO DEBT.

## 2. Entscheidung

Der Rest wird **nicht** durch einen Filter auf der Abfrageoberflaeche
geschlossen, sondern **vertraglich gefasst, beobachtbar gemacht und sein
Aufraeumen zur Betriebspflicht erhoben**.

- **Zugesichert** bleibt, was AG3-174 belegt hat: kein Loeschen der Daten
  einer neueren Generation (storage-seitige Ordnungsbedingung, in beiden
  Wettlauf-Reihenfolgen belegt), keine Umkehrung der gemeldeten Frische
  (Completions insert-only, positionsgebunden, nach Generation geordnet).
- **Nicht zugesichert** ist die Abwesenheit zusaetzlicher, veralteter
  Zeilen zwischen dem Abschluss-Delete und dem naechsten Sync derselben
  Quelle. Es wird **keine** transaktionale Atomizitaet und **keine**
  zeitliche Schranke behauptet — auch kein „nur kurz".
- **Erkennbarkeit ist die tragende Bedingung, nicht das Beiwerk.**
  `story_list_sources` meldet je Source-Type `stale_chunk_count`.
  Autoritativ ist die Generation der Completion mit der hoechsten
  Generation dieser Quelle. Die Kennzahl ist ein **exaktes Praedikat**,
  kein Sammelbegriff „alles Nicht-Autoritative": gezaehlt werden Zeilen
  **strikt unter** der autoritativen Generation, Zeilen **ohne**
  Generation und Zeilen mit **vorhandener, aber unbrauchbarer**
  Generation. **Nicht** gezaehlt werden Zeilen einer **hoeheren**
  Generation (laufender Sync), und eine Quelle **ohne** abgeschlossene
  Synchronisierung wird **nicht beurteilt**. `> 0` ist ein
  handlungspflichtiger Befund, **kein Beweis** fuer einen
  Uebernahme-Rest: die dritte Klasse loest kein Sync auf, sondern wird
  vom Sync benannt abgewiesen und braucht eine Eskalation.
- **Aufraeumen ist Betriebspflicht:** nach jedem administrativen Reclaim
  ist ein Sync der betroffenen Quelle zu fahren (Runbook FK-04 §4.5.14).
  Der Aufraeumweg existierte bereits und ist deterministisch; es fehlte
  allein der Ausloeser.
- **Der Abschluss-Delete bleibt.** Er deckt den Regelfall; der Vertrag
  ergaenzt ihn, er ersetzt ihn nicht.

## 3. Begruendung

Der entscheidende Befund der Phase-1-Analyse: **das Mittel fehlte nicht,
der Ausloeser fehlte.** Ein Sync der betroffenen Quelle entfernt die
veralteten Zeilen zuverlaessig ueber die Generationsordnung.

Die Kostenasymmetrie entscheidet — gemessen, nicht geschaetzt (Details in
`design.md`):

| | Kosten |
|---|---|
| **Ausschliessen** (Filter auf der Abfrageoberflaeche) | +1 Lesezugriff bei **jeder** Suchanfrage (ein Cache hilft nicht: Suche und Sync sind verschiedene Prozesse), zzgl. einer mit der Quellenzahl wachsenden Filterbreite (3,7 KiB / 11,9 KiB / 49 KiB bei 75 / 242 / 1000 Quellen), zzgl. eines **ungemessenen** Risikos fuer Trefferqualitaet und Antwortzeit der Vektorsuche |
| **Erkennen** (Kennzahl im Envelope) | keine zusaetzliche Transportlast: `list_sources` liest die betroffenen Zeilen und die Abschluss-Records ohnehin |

Eine Dauerlast auf dem meistgenutzten Pfad des Systems fuer eine
**Vier-fach-Koinzidenz** (haengender Sync **und** bewusste
Admin-Uebernahme **und** wieder anlaufender Altprozess **und** kein
nachfolgender Sync) ist nicht vertretbar — **solange der Rest erkennbar
ist.** Ohne Erkennbarkeit waere die Entscheidung „hoffen, dass es niemandem
auffaellt", also ein verschwiegener Rest; das verbieten FAIL-CLOSED und die
Severity-Semantik. Die Erkennbarkeit ist gratis, deshalb traegt die
Bedingung.

## 4. Alternativen

- **(a) Den Stale-Write storage-seitig verhindern** — an diesem Rand
  **nicht verfuegbar**: der gepinnte Client bietet keine Vorbedingung fuer
  Schreibvorgaenge; `delete_many(where=…)` ist die einzige konditionale
  Mutation. Eine Emulation ueber generationsgebundene UUIDs zerstoert die
  deterministische Chunk-Identitaet, auf der idempotenter Re-Sync,
  Delete-Closure und Identitaetspruefung beruhen. Verworfen, weil
  technisch unmoeglich, nicht weil unerwuenscht.
- **(b) Das Retrieval nicht-autoritative Generationen ausschliessen
  lassen** — technisch machbar und kohaerent, aber verworfen wegen der
  oben gemessenen Dauerlast auf dem heissen Suchpfad. **Bewusst offen
  gehalten** in der gemessenen billigsten Form (ein abgeleiteter
  Autoritaetsschluessel `source_file|generation` → **eine**
  Mengenbedingung statt 2N Einzelbedingungen, halbe Wire-Groesse).
  Ausgeschlossen bleibt allein die **Sichtbarkeit** der Generation auf der
  Abfrageoberflaeche (FK-13 §13.9.5), nicht ihre interne Nutzung.
- **Den Rest als offenen Punkt stehen lassen** — verworfen: ein
  unratifizierter Dauerzustand in einer Norm ist genau die stille
  Restluecke, die ZERO DEBT verbietet.
- **Nur dokumentieren, ohne Kennzahl** — verworfen: ein Rest, den niemand
  bemerken kann, ist im Effekt ein verschwiegener Rest.
- **Meldung ueber Telemetrie statt im Werkzeug-Envelope** — verworfen:
  Telemetrie, die niemand liest, hat denselben Fehlermodus wie ein
  undokumentierter Rest. Die Kennzahl gehoert dorthin, wo ein Agent oder
  Operator ohnehin hinsieht.

## 5. Neubewertungsbedingungen

Diese Entscheidung ist an ihre Voraussetzungen gebunden und wird neu
bewertet, wenn

- „die Suche darf nie eine ueberholte Fassung zeigen" zu einer **harten
  Zusage** wird (z. B. durch eine Zielprojekt-Anforderung), oder
- die gemeldete Kennzahl im Betrieb zeigt, dass der Fall **haeufiger**
  auftritt als die Vier-fach-Koinzidenz erwarten laesst.

Dann ist (b) in der gemessenen billigsten Form der naechste Schritt.
**Vorbedingung jener Entscheidung** — nicht dieser — ist die bislang
bewusst nicht erhobene Messung des Filtereinflusses auf Trefferqualitaet
und Antwortzeit der Vektorsuche.

## 6. Impact-Sweep (P3)

Lexikalischer Sweep ueber `concept/`, `guardrails/`, `scripts/ci/`,
`tools/`, `src/` und `stories/` nach `owning_generation`,
`stale_chunk_count`, `story_list_sources`, `Restbefund`, `13.9.9` und
`13.4.1`:

- Normativer Owner des Sync-Lifecycles und der Werkzeug-Rueckgaben ist
  ausschliesslich FK-13 (§13.4.1, §13.9.9). Kein weiteres
  Konzeptdokument beschreibt die Rueckgabefelder von
  `story_list_sources`.
- FK-04 ist Autoritaet fuer **Runbooks** (`authority_over: operations`);
  der neue Betriebsschritt gehoert dorthin und verweist auf FK-13 als
  Mechanik-Autoritaet — dieselbe Aufteilung wie bei §4.5.10
  (Ownership-Takeover → FK-56).
- `concept/_meta/decisions/2026-07-25-claim-takeover-storage-conditional-delete.md`
  (D9) haelt den Rest als offen fest. Es erhaelt einen **Vorwaertszeiger**
  (Nachtrag /4); seine Historie bleibt unveraendert, und die
  D9-Entscheidung selbst wird **nicht** ersetzt — daher `supersedes: []`.
- FK-13 §13.9.5/§13.9.6 (Abfrageoberflaeche, `doc_kind`-Vokabular) sind
  **nicht betroffen**: es entsteht kein Abfrageparameter und kein
  Frontmatter-Feld. Die Generation bleibt von der Abfrageoberflaeche fern.
- FK-13 §13.3.1: `owning_generation` bleibt unveraendert (INT,
  filterbar, FIELD-untokenisiert, nie vektorisiert, kein
  Werkzeug-Rueckgabefeld). Die Kennzahl ist eine **Aggregation**, kein
  neues Feld auf der Objektebene.
- K5/Datenhaltung: kein neues Schema, keine neue Property, kein neuer
  Laufzeitzustand. `stale_chunk_count` wird bei jedem Aufruf aus den
  ohnehin gelesenen Zeilen und Abschluss-Records berechnet und **nicht**
  gespeichert — es entsteht keine zweite operative Wahrheit.
- Werkzeug-Vertrag im Code (`backend/vectordb/contracts.py`) und der
  Contract-Test transkribieren die Tabelle aus §13.4.1; die
  D1-Mindest-Shape bleibt als Untermenge erhalten.

## 7. Betroffenheitsmatrix

| Stelle | Klassifikation | Begruendung |
|---|---|---|
| FK-13 §13.9.9 (Restbefund) | geaendert | Der offene, nicht ratifizierte Punkt wird durch den ratifizierten Vertrag ersetzt: Zusicherungen, Nicht-Zusicherungen, Erkennbarkeit, Aufraeumweg, offen gehaltene Option. |
| FK-13 §13.4.1 (`story_list_sources`) | geaendert | Die bisher vage Prosa wird zur expliziten Rueckgabetabelle inkl. `stale_chunk_count`; D1-Mindest-Shape und Eingabe-Strenge bleiben unveraendert. |
| FK-04 §4.5.14 (neues Runbook) | geaendert | Die Betriebspflicht „nach administrativer Uebernahme einen Sync der betroffenen Quelle fahren" wird dort verankert, wo der Betrieb sie findet. |
| FK-13 §13.9.5 / §13.9.6 | nicht-betroffen | Kein Abfrageparameter, kein Frontmatter-Feld; die Generation bleibt von der Abfrageoberflaeche fern. |
| FK-13 §13.3.1 (`owning_generation`) | nicht-betroffen | Property und ihre Regeln bleiben unveraendert; die Kennzahl aggregiert nur. |
| `concept/_meta/decisions/2026-07-25-claim-takeover-storage-conditional-delete.md` | geaendert | Vorwaertszeiger (Nachtrag /4); Historie und D9-Entscheidung bleiben gueltig. |
| `concept/_meta/decisions/2026-07-26-post-completion-stale-chunk-contract.md` | geaendert | Dieses Record persistiert Entscheidung, Alternativen, Messgrundlage und Neubewertungsbedingungen. |
| `backend/vectordb/engine.py` (`list_sources`) | referenziert-jetzt | Berechnet die Autoritaet je Quelle aus den Abschluss-Records und meldet die nicht-autoritative Teilmenge. |
| `backend/vectordb/cli.py` (`--reclaim`) | referenziert-jetzt | Nennt die Betriebspflicht an der Stelle der Handlung und verweist auf FK-04 §4.5.14. |
| `backend/vectordb/sync.py` (Abschluss-Delete) | nicht-betroffen | Der Sweep bleibt unveraendert erhalten; er deckt den Regelfall. |

Diese Ratifizierung autorisiert genau diese Konzeptaenderungen und keine
weitere. §13.9.6 (`doc_kind`-Vokabular) bleibt ausdruecklich unberuehrt.
