# AG3-174 — Codex Review r8

- **Datum:** 2026-07-25
- **Reviewer:** Codex (read-only, Fortsetzung r1–r7-Session)
- **Branch:** nach der r7-Remediation (5 Commits, Mechanismus 3)
- **Orchestrator-Verifikation vorab:** ruff clean, mypy clean (998), 897 Tests
  gruen, 92,73 % Coverage, Tree clean.

## VERDICT: REJECT — 9 von 12 ACs

Der Implementierer hatte „alle 12 ACs" gemeldet. Tatsaechlich: **9**. AC3, AC6
und AC10 sind ERROR — darunter eine **Regression** eines zuvor geschlossenen
Findings.

## Mechanismus 3 — Kern haelt, Ende-zu-Ende nicht

**Was haelt (bestaetigt):** Der geordnete Delete traegt. Normale Acquisitions
*und* Reclaims allokieren Leiterpositionen per Conditional Create; ein normaler
Release behaelt den Claim-Record; Housekeeping trifft nur niedrigere Positionen;
ein unlesbarer Hoechststand faellt fail-closed; zwei Allokatoren auf derselben
Nummer ergeben einen Gewinner und eine abgewiesene Kollision. **Beide
Race-Reihenfolgen und die Dreierkette A→B→C sind sicher** gegen das Loeschen von
Daten einer hoeheren Generation. Die Schranke kommt allein aus der eigenen
Generation des Loeschenden. Auch die Receipts halten: eine Stale-Append
niedrigerer Generation kann weder autoritativ werden noch eine hoehere
Completion pruenen. **N37 und N39 CLOSED.**

**Was nicht haelt:** Die Ende-zu-Ende-Kette. Der **Schreib**-Race blieb offen —
auf der falschen Annahme, der Inhalt sei ohnehin identisch. Und Altdaten ohne
Stempel koennen nicht konvergieren.

## Geschlossen in dieser Runde

N37, N39, N40, P2-4, P2-5 — sowie ohne Regression R01–R11, R13–R14, N01–N36
(explizit bestaetigt: N12/N30/N35 Schema-Read-back, N19 Return-Fields,
N24/N32 Research-Identitaet, N26 Projekt-Bindung, N28 unveraenderliche
Completions, N31/N21 kanonische Pfade, D7 Regeln 1/2, D8 Mixed-Status).

## Die fuenf verbleibenden Findings

**N41 P0 `sync.py:673` — Ein zurueckgesetzter Writer kann nach Abschluss des
neuen Besitzers Stale-Chunks anhaengen.** Pre-Write-Fence und Upsert sind
getrennte Operationen: A passiert den Fence, B uebernimmt und schliesst ab, A
setzt fort und schreibt seine Objekte niedrigerer Generation. **Bei geaendertem
Inhalt haben sie andere UUIDs** — die Stale-Chunks koexistieren mit Bs aktuellen.
Der spaetere Receipt-Fence weist A ab, entfernt aber seine bereits geschriebenen
Zeilen nicht. Widerspricht direkt der „selber Inhalt"-Annahme in FK-13:723.
**Auflage:** Stale-Generation-Writes storage-seitig unmoeglich machen, fuer das
Retrieval unsichtbar machen **oder** deterministisch entfernbar halten — plus
FK-13/D9 korrigieren und den Race mit *abweichendem* Inhalt testen.

**N42 P0 `weaviate_index.py:145` — Der echte Export-Pfad rekonstruiert die
falsche Chunk-Identitaet.** `story_file_to_objects` leitet UUIDs aus
`chunk_id = story-<ordinal>-<content-prefix>` ab, `_as_corpus_object` ersetzt
diesen Identitaets-Input aber durch `content_hash`. Die Produktions-
Identitaetspruefung lehnt damit **jede** normal projizierte Story ab. Der Test
fabriziert seine UUID ebenfalls aus `content_hash` — also ein Fixture-only-Shape.
Zusaetzlich faengt der `VectorDbError`-Handler des Exports `SyncError` nicht.
**→ AC3.**

**N43 P0 `sync.py:636` — Vorbestehende ungestempelte Objekte haben keinen
konvergenten Migrationspfad.** Jede Alt-Zeile ohne `owning_generation` wird
dauerhaft abgewiesen. Ein Reindex kann zuerst aktuelle Zeilen schreiben und dann
an einer alten scheitern; jeder Retry wiederholt den Fehler, ohne Freshness zu
publizieren oder die Altzeile zu entfernen. Der Test beweist die Abweisung, aber
liefert **keinen Recovery-Pfad**. **Auflage:** explizite, claim-eigene,
fail-closed Migration/Backfill.

**N44 P0 `weaviate_adapter.py:811` — REGRESSION von R12.** Der neue
Conditional-Delete-Transport nutzt `getattr(..., 0)`, `or 0` und `int(...)` und
akzeptiert damit fehlende Felder, Zahlstrings und Booleans: `successful="1"` bei
fehlendem `failed` kann als vollstaendig bestaetigter Delete gelten. Verletzt
AC10 und oeffnet den R12-Falsch-Erfolg-Pfad wieder. **→ AC10.**

**N45 P0 `engine.py:525` — Normale Claim-Release-Fehler werden still in Erfolg
verwandelt.** `release_source` unterdrueckt Availability- *und* Write-Fehler: ein
Sync kann seine Completion publizieren, den Release-Marker nicht persistieren,
Erfolg zurueckmelden — und die Quelle bleibt dauerhaft belegt bis zu einem
unerklaerlichen administrativen Reclaim. Verletzt FAIL-CLOSED.

**P2-6** `report.md:535` — der Report ueberzeichnet die Race-Pfad-Deckung: die
zweite Reihenfolge ist ueber den geteilten privaten Delete-Helper getestet, nicht
Ende-zu-Ende je Einstiegspfad.

## AC-Bilanz

| AC | Status |
|----|--------|
| AC1, AC2, AC4, AC5, AC7, AC8, AC9, AC11, AC12 | **PASS** |
| **AC3** | ERROR — die echte Export-Projektion passiert die Identitaetspruefung nicht (N42) |
| **AC6** | ERROR — Stale-Writes nach Reclaim bleiben sichtbar; Altzeilen konvergieren nicht (N41/N43) |
| **AC10** | ERROR — Conditional-Delete-Counter weiter koerzierend/defaultend (N44) |

## Korrigierter D9-Record

Das Addendum benennt die gescheiterten Mechanismen 1 und 2 ehrlich, erhaelt D9s
ratifizierte Delete-Invariante und begrenzt das Konzept-Delta auf
§13.3.1/§13.9.9; §13.9.6/doc_kind unberuehrt; P3-Impact strukturell adaequat.
**Inhaltlich unvollstaendig:** FK-13:723 und der Record behaupten weiterhin,
ein fortgesetzter Chunk-Write habe „denselben Inhalt" — die Implementierung
belegt diese Praemisse nicht (N41).

Der **gestrichene 14. Revert-Test** wurde **zu Recht** weggelassen: der
Claim-Record bleibt erhalten, das Ausschliessen des redundanten Release-Markers
aendert kein Verhalten und ist kein gueltiger Revert-Beweis.

## Scope / D-Decisions

Kein unautorisiertes Leakage; FK-13-Aenderung innerhalb der D9-Grenze; Q2
unberuehrt. D1–D8 **HONORED**. D9s **enge** storage-seitige Delete-Invariante
ist eingehalten — aber **Mechanismus und Konzeptbegruendung sind wegen
N41/N43/N45 nicht reif fuer die PO-Rebestaetigung.**
