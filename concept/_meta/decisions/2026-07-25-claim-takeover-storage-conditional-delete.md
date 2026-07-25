---
concept_id: META-DEC-2026-07-25-CLAIM-TAKEOVER-STORAGE-CONDITIONAL-DELETE
title: Concept-Decision-Record — Zerstoerender Sync-Schritt wird storage-seitig an den Besitz gebunden
module: meta
cross_cutting: true
status: active
doc_kind: decision-record
authority_over: []
defers_to: []
supersedes: []
superseded_by:
tags: [meta, decision-record, vectordb, retrieval, claim, concurrency, FK-13, AG3-174]
formal_scope: prose-only
---

# Concept-Decision-Record — Zerstoerender Sync-Schritt wird storage-seitig an den Besitz gebunden

Datum: 2026-07-25. Record gemaess META-CONCEPT-CONSISTENCY P3
(Blast-Radius-Pflicht bei normativen Aenderungen). Begrenzt auf FK-13 §13.3.1
(ein neues Feld) und §13.9.9 (Verhalten bei Besitzwechsel).

## 1. Anlass

Codex-Review r6, Finding N33 (= N15/N27): jeder Fence im Corpus-Sync ist ein
**Read** (`assert_claim_held`), gefolgt von einer **separaten** Mutation. Ein
administrativer Reclaim (D3/N27: kein Zeitablauf, nur bewusster Eingriff) kann
genau dazwischen landen — dann mutiert der ueberholte Halter trotzdem. Eine
vorgelagerte Pruefung kann dieses Fenster prinzipiell nicht schliessen.

Am Weaviate-Rand wurde verifiziert: es gibt **keine** allgemeine
epoch-konditionale Mutation. `data.update`, `data.replace` und
`data.delete_by_id` kennen keine Vorbedingung; `data.insert` ist ausschliesslich
auf die Objekt-ID konditional (genau das nutzen Claim- und Completion-Record
bereits). **Eine** storage-seitige Bedingung existiert jedoch:
`data.delete_many(where=…)` ist filter-konditional.

Verifizierte Risiko-Asymmetrie der drei gefencten Schritte:

1. **Chunk-Write** — idempotent (deterministische UUID, identischer Inhalt).
2. **Completion** — insert-only und positionsgebunden; ein Nachzuegler kann nur
   eine neue Position anfuegen, nichts ueberschreiben.
3. **Loeschen alter/verschwundener Chunks** — der **einzige zerstoerende**
   Schritt und damit das einzige echte Datenverlustrisiko.

## 2. Entscheidung

**Nur der zerstoerende Schritt wird storage-seitig an den Besitz gebunden; die
beiden harmlosen Fenster werden ehrlich dokumentiert.**

Verbindliche Invariante: *Ein ueberholter Halter darf niemals Daten loeschen, die
der neuere Besitzer geschrieben hat — und dies muss storage-seitig erzwungen
sein, nicht durch eine vorgelagerte Pruefung.*

Umsetzung in der Norm:

- FK-13 §13.3.1 erhaelt das Feld `owning_claim`: das Besitz-Token der
  Claim-Generation, die eine Objektversion geschrieben hat. Es ist **kein**
  zweiter Besitz-Wahrheitstraeger — autoritativ bleibt der Claim-Datensatz —,
  geht nicht in die Einbettung ein und ist kein Rueckgabefeld der Werkzeuge.
- FK-13 §13.9.9 haelt fest, dass der zerstoerende Schritt an das **beobachtete**
  `owning_claim` gebunden und **ohne** vorgelagerte Ersatzpruefung ausgefuehrt
  wird, und benennt die zwei verbleibenden Fenster als bekannt und unschaedlich.
- Es wird **keine** transaktionale Atomizitaet behauptet (Linie aus
  DR 2026-07-21 Rand 5).

## 3. Alternativen

- **Das Restfenster vollstaendig akzeptieren** wurde verworfen: der Loeschschritt
  bliebe ein echtes Datenverlustrisiko.
- **Vollabsicherung aller drei Schritte** wurde verworfen: sie braucht ein
  Takeover-Protokoll, das den alten Prozess nachweislich stilllegt — also
  Prozessaufsicht ausserhalb dieser Schicht. Eigene Story; AG3-174 wuerde darauf
  warten.
- **Bedingung „Epoche des Objekts aelter als meine"** (der urspruengliche
  Mechanismus-Vorschlag) wurde bei der Pruefung **verworfen**: die Claim-Epoche
  ist nur *innerhalb* einer Uebernahmekette monoton. Ein freigegebener Claim wird
  verworfen, die naechste Akquisition beginnt wieder bei Epoche 1. Ein
  Ordnungspraedikat wuerde daher legitim loeschbare Alt-Chunks ueberspringen,
  sobald die vorige Generation dieselbe oder eine hoehere Epoche hielt — mit der
  Folge, dass verschwundene Quellen **stillschweigend nie** entfernt werden
  (Bruch der Delete-Closure). Gewaehlt ist deshalb **Gleichheit gegen den
  beobachteten Wert** (Compare-and-Delete): sie braucht keine Ordnungsannahme und
  schliesst die Daten des neueren Besitzers dennoch aus, weil ein
  ueberholendes Generationstoken zwangslaeufig ein **anderes** ist.
- **Nur die Epoche als Token** wurde verworfen: Epochenwerte wiederholen sich
  ueber Laeufe hinweg, also identifiziert erst das **Paar** aus Epoche und
  Besitzer eine Generation. Das Token ist `<epoch>|<owner_id>`; damit ruht die
  Garantie auf der Struktur und nicht auf dem Argument, ein wiederholter
  Epochenwert koenne nicht mit einem lebenden Halter kollidieren.
- **Eine Ersatzpruefung im Applikationscode „zur Sicherheit" behalten** wurde
  verworfen: sie stellt genau die Scheinsicherheit wieder her, die diese
  Entscheidung beseitigt.

## 4. Impact-Sweep (P3)

Lexikalischer Sweep ueber `concept/`, `guardrails/`, `scripts/ci/`, `tools/`,
`src/` und `stories/` nach `StoryContext`, `claim`, `Shadow-Replace`,
`corpus_revision` und `delete`:

- Normativer Owner des Datenmodells und des Sync-Lifecycles ist ausschliesslich
  FK-13 (§13.3.1, §13.9.9). Kein weiteres Konzeptdokument fuehrt die
  `StoryContext`-Properties.
- `concept/_meta/decisions/2026-07-21-vectordb-edge-sharpening.md` (Rand 5) hat
  den Shadow-Replace auf „generationskonsistent mit kurzem Umschaltfenster"
  abgeschwaecht. Diese Entscheidung ergaenzt sie, ohne sie zu ueberschreiben: das
  Fenster bleibt, nur die **Nicht-Loeschbarkeit fremder, neuerer Daten** wird
  garantiert.
- §13.9.5/§13.4.1 (Werkzeug-Vertraege) sind **nicht betroffen**: `owning_claim`
  ist kein Parameter und kein Rueckgabefeld.
- §13.9.6 (Frontmatter) ist **nicht betroffen** — das Feld ist Laufzeit-Besitz,
  keine Korpus-Metadatenaussage. Auch das offene `doc_kind`-Vokabular (Frage Q2)
  bleibt unberuehrt.
- §13.2/§13.9.3 (Vektorisierung): das Feld ist ausdruecklich **nicht**
  vektorisiert und nicht Teil der Einbettungsquellen.
- K5/Datenhaltung: die Aenderung betrifft die Weaviate-Collection `StoryContext`
  (ein zusaetzliches, nicht vektorisiertes, filterbares Textfeld); kein
  relationales Schema, keine Telemetrie.

## 5. Betroffenheitsmatrix

| Stelle | Klassifikation | Begruendung |
|---|---|---|
| FK-13 §13.3.1 (`StoryContext`-Properties) | geaendert | Neues Feld `owning_claim` samt Abgrenzung „kein zweiter Besitz-Wahrheitstraeger". |
| FK-13 §13.9.9 (Corpus-Build-Lifecycle) | geaendert | Verhalten bei Besitzwechsel: storage-seitig gebundener zerstoerender Schritt, zwei benannte Restfenster, keine Atomizitaetsbehauptung. |
| `concept/_meta/decisions/2026-07-21-vectordb-edge-sharpening.md` (Rand 5) | referenziert | Bounded-Window-Linie, die hier fortgeschrieben und nicht aufgehoben wird. |
| FK-13 §13.9.5 / §13.4.1 (Werkzeug-Vertraege) | nicht-betroffen | Kein Parameter, kein Rueckgabefeld. |
| FK-13 §13.9.6 (Frontmatter) | nicht-betroffen | Laufzeit-Besitz statt Korpus-Metadatum. |
| FK-13 §13.2 / §13.9.3 (Vektorisierung) | nicht-betroffen | Feld ist nicht vektorisiert. |
| `concept/_meta/decisions/2026-07-25-claim-takeover-storage-conditional-delete.md` | geaendert | Dieses Record persistiert Entscheidung, Alternativen und Impact-Sweep. |
| Sync/Store im Code (`backend/vectordb/sync.py`, `engine.py`) | referenziert-jetzt | Stempelt beim Schreiben und loescht ausschliesslich storage-konditional. |
| Transport-Adapter (`integration_clients/vectordb/weaviate_adapter.py`) | referenziert-jetzt | Setzt die Bedingung ueber `delete_many(where=…)`. |

Grundlage: PO-Ratifizierung D9 in
`stories/AG3-174-vectordb-retrieval-engine/po-decisions.md`. Zusammen mit D7 und
D8 sind das die Konzeptaenderungen, die AG3-174 gestattet sind.
