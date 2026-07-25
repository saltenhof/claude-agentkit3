# AG3-174 — Codex Review r7

- **Datum:** 2026-07-25
- **Reviewer:** Codex (read-only, Fortsetzung r1–r6-Session)
- **Branch:** nach N34/N35 + D8 + D9 (10 Commits)
- **Orchestrator-Verifikation vorab:** ruff clean, mypy clean (998), 747 Tests
  gruen, Tree clean, AG3-174-Module 92,62 % Coverage (explizit gemessen).

## VERDICT: REJECT

Die Codeseite ist **nicht** fertig — aber die Bilanz ist eng: **10 von 12 ACs
bestehen.** Offen bleiben **AC3** und **AC6**, und beide haengen an derselben
Wurzel: es gibt keine persistente, monoton fortlaufende Generationsidentitaet
pro Quelle.

## AC-Bilanz

| AC | Status |
|----|--------|
| AC1, AC2, AC4, AC5, AC7, AC8, AC9, AC10, AC11, AC12 | **PASS** |
| **AC3** | **ERROR** — direkte Story-Exporte sind ungestempelt und koennen an der D9-Delete-Closure nicht teilnehmen (N38) |
| **AC6** | **ERROR** — ein ueberholter Takeover kann die neuere Generation zerstoeren und Freshness zurueckdrehen (N37/N39) |

**AC5 ist bestanden** — alle fuenf Ranking-Regeln produktiv, deterministisch
getiert, filtertreu bewiesen. D8 ist damit vollstaendig eingelöst.

## Geschlossen in dieser Runde

N12, N29, N30, N35, N36, R10, P2-3 — sowie ohne Regression: D7 (Regeln 1/2),
N14, N18, N19, N24/N32, N26, N28, N31/N21.

## Die vier verbleibenden Findings

**N37 P0 `sync.py:620` — Observed-Token-Gleichheit autorisiert das Loeschen der
Daten des neueren Besitzers.** Gegenszenario: Writer A passiert seinen Fence, B
uebernimmt per Reclaim und schliesst ab, A setzt fort — liest Bs Chunks mit
Token `2|writer-b`, gruppiert sie **unter genau diesem beobachteten Token**, und
der konditionale Delete trifft und entfernt sie. Die D9-Tests deckten nur die
umgekehrte Reihenfolge ab (B schreibt neu, *nachdem* A das alte Token gelesen
hat). **Codex-Auflage:** eine **global monotone Quell-Generation** persistieren,
die normale Releases ueberlebt, und den Delete storage-seitig an „Generation
nachweislich aelter als der loeschende Claim" binden; Gegen-Reihenfolge-Test
ergaenzen.

**N38 P0 `weaviate_adapter.py:293` — Story-Export umgeht den einzigen
stempelnden Schreibpfad.** `WeaviateStoryAdapter.story_sync()` upserted
StoryContext-Objekte weiterhin direkt (Zeile 313); nur
`WeaviateCorpusStore.upsert_objects()` stempelt `owning_claim`. Automatisch
exportierte Stories liegen damit **ungestempelt** — ein spaeterer MCP-Story-Sync
oder -Delete liest `owning_claim=""` und scheitert hart statt zu aktualisieren
oder zu loeschen. **→ AC3.** Auflage: jeden StoryContext-Producer (inkl.
Export/Split/Repair) durch den claim-bewussten Sync-Owner routen; Test
Export → Resync → Vanished-Delete.

**N39 P0 `sync.py:695` — Eine ueberholte Completion kann neuere Freshness
ersetzen.** A passiert den Receipt-Fence, B uebernimmt und publiziert Revision
B, A haengt danach Revision A an der naechsten Sequence an. `get_receipt()`
waehlt As hoehere Sequence, und das Pruning loescht Bs gueltige Completion
(`engine.py:319`). Insert-only verhindert Ueberschreiben, macht ein
Stale-Append aber nicht harmlos. Auflage: Completion-Gueltigkeit an eine
persistente monotone Claim-Generation bzw. einen Takeover-Wasserstand binden.

**N40 P0 `sync.py:789` — Leere Matrizen umgehen das N34-Gate.**
`_validate_matrix()` validiert die Completion-Eingaben nur *innerhalb* der
Iteration ueber `objects_by_source`. Bei leerer Matrix wird ein leeres
`corpus_revision` nie geprueft, bevor `_delete_vanished_sources()` mutiert.
Auflage: Run-weite Felder am Funktionseingang validieren, ausserhalb der
Schleife; Tests fuer reconcile und full-reindex mit leerer Matrix, leerer
Revision und einer geseedeten verschwundenen Quelle.

## D9-Bewertung im Detail

- **(a)** Die Nicht-Monotonie-Feststellung des Implementierers ist **wahr**:
  `release_source()` loescht den Claim-Record (`engine.py:462`), der naechste
  normale `try_claim_source()` beginnt wieder bei Epoche 1 (`engine.py:377`);
  nur der administrative Reclaim inkrementiert. **Der PO-Vorschlag
  („Epoche aelter als meine") war also zu Recht verworfen.**
- **(b)** Observed-Token-Gleichheit erfuellt die Invariante **nicht**: sie
  schliesst nur das Intervall zwischen Lesen und Loeschen eines Tokens, belegt
  aber nicht, ob das Token zu As Vergangenheit, Bs neuerer Generation oder einem
  fremden Lauf gehoert.
- **(d)** Epoche + Owner ist besser als Epoche allein, aber **nicht
  ausreichend**: Epochen wiederholen sich, und ein langlebiger `SyncService`
  kann denselben Owner ueber mehrere normale Acquisitions tragen — das Paar ist
  kein global eindeutiger oder geordneter Generationsbezeichner.
- **(e)** Transportfaktum bestaetigt: nur `delete_many(where=…)` bietet eine
  storage-seitige Vorbedingung; `delete_by_id`/`update`/`replace` haben keine.
- **(f)** Die Pre-Delete-`assert_claim_held`-Aufrufe sind aus **beiden**
  Chunk-Delete-Pfaden verschwunden, ohne Ersatz im Applikationscode — wie
  beauftragt. **Kein dritter StoryContext-Delete-Pfad gefunden.**
- **(g)** Kurze/gescheiterte Counts werden nicht als Erfolg missdeutet.
- Die **Ausweitung** des Schutzes auf beide zerstoerenden Deletes ist
  „correct in principle" — der innere Alt-Generations-Pfad ist allerdings genau
  dort, wo der Autorisierungsfehler am leichtesten ausloest.

**Folge:** Der D9-Decision-Record ist inhaltlich falsch, wo er „neuere Daten
koennen nicht geloescht werden" und „Stale-Completion ist harmlos" behauptet
(widerlegt durch N37/N39). Er braucht Korrektur und eine **erneute PO-Bestaetigung
des Ersatzmodells**.

## D8-Bewertung

**Korrekt und begrenzt.** `concept_status` ist ein striktes, nicht-leeres,
duplikatfreies Array; malformte Container, blosse Strings, null, Duplikate,
unbekannte Werte und Nicht-String-Elemente scheitern vor dem Retrieval. Mehrere
Werte werden ein server-seitiges `Filter.any_of`, ein einzelner Wert bleibt
einfache Gleichheit, Abwesenheit bleibt exakt active-only. Regel 4 ist produktiv
und filtertreu.

## Coverage

Der Mechanismus-Befund ist **bestaetigt**: `pyproject.toml:71` enthaelt nur
xdist-Optionen, ein einfaches `pytest` startet keine Coverage, und
`coverage report` kann veraltete Daten wiederverwenden — die frueheren Zahlen
waren bedeutungslos. Die explizite Messung ist die richtige Evidenz: 86,53 %
gesamt, 92,62 % fuer AG3-174 → **Coverage-DoD erfuellt**. Die
repository-weite Durchsetzungsluecke bleibt **Governance-Schuld**, ist aber
nicht das Coverage-Versaeumnis dieser Story.

## Scope / D-Decisions

Kein unautorisiertes Leakage. D8/D9-Konzeptaenderungen PO-autorisiert, §13.9.6
unberuehrt (Q2-Stand: 75 Dokumente, 2077 Chunks, 275 Fehler — die beiden neuen
Decision Records tragen zwei erwartete `decision-record`-Vokabularfehler bei).

D1, D2, D4, D5, D6, D7, D8 **HONORED**.
**D3 nicht vollstaendig** — Takeover kann das Bounded Window und die Freshness
korrumpieren. **D9 NICHT eingehalten** — die storage-seitige
No-Newer-Delete-Invariante ist in der implementierten Ordnung falsch.

## P2

- **P2-4** `test_sync.py:771` — Claim-Release-Wortlaut weiter unpraezise (jeder
  normale Sync ruft `release_source()` im `finally`; nur ein abgestuerzter Claim
  braucht Reclaim).
- **P2-5** `sync.py:125` — `COMPLETION_INPUT_FIELDS` dupliziert vier Namen aus
  `RECEIPT_MANDATORY_FIELDS` manuell; strukturell ableiten, damit kuenftige
  Receipt-Felder das Pre-Mutation-Gate nicht still verpassen.
