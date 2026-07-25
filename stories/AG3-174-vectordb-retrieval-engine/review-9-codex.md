# AG3-174 — Codex Review r9 (Abnahme-Review)

- **Datum:** 2026-07-25
- **Reviewer:** Codex (read-only, Fortsetzung r1–r8-Session)
- **Branch:** nach 8 Commits (N42/N44/N45/P2-6 + Shape 3 + Backfill)
- **Orchestrator-Verifikation vorab:** ruff clean, mypy clean (998), 930 Tests
  gruen, 93,16 % Coverage, Tree clean.

## VERDICT: REJECT — 9 von 12 ACs

## Der strukturelle Befund (entscheidend)

> **„One finite sweep cannot close a write that may land afterwards."**

Der Post-Completion-Sweep **verengt** das Stale-Write-Fenster, **schliesst** es
aber nicht: ein Stale-Write unmittelbar *nach* dem Sweep bleibt bis zu einem
**unbestimmten** spaeteren Sync liegen — „next sync" kann Stunden spaeter sein
oder nie. Der offengelegte Restbefund ist **ehrlich, aber nicht begrenzt**.

Codex nennt genau drei zulaessige Aufloesungen:
1. den Stale-Write eliminieren oder storage-seitig fencen — **an diesem Rand
   nicht verfuegbar** (ueber drei Runden verifiziert),
2. das Retrieval nicht-autoritative Generationen ausschliessen lassen — ein
   Design mit echten Kosten (Query-Kopplung an die Completion-Menge),
3. **einen ratifizierten Vertrag, der eine potenziell unbegrenzte
   Post-Completion-Inkonsistenz ehrlich modelliert.**

→ **Das ist der Punkt, an dem der PO-Deckel greift** (PO-Mandat 2026-07-25:
„eine Runde weiter, dann Schnitt").

## Geschlossen

**N42, N44, N45, P2-6 CLOSED.** R01–R14 CLOSED (R12-Regression repariert).
N01–N40 CLOSED, keine Regression.

Positiv bestaetigt: die Sweep-Delete-Praedikate sind korrekt an die eigene
Generation gebunden und koennen die Zeilen eines neueren Besitzers nicht treffen;
deterministische Identitaet und Delete-Closure unveraendert; der Transport-Test
bindet echt gegen die Client-Filterdarstellung (`by_id CONTAINS_ANY AND
owning_generation IS NULL`); der praesente Backfill-Pfad konvergiert im ersten
Lauf, der zweite ist ein sauberer No-op; eine ungueltige Generation wird benannt,
nicht geraten. **Beide vom Implementierer selbst gemeldeten schwachen Reverts
sind jetzt echt revert-sensitiv.**

## Offen — ordentliche Defekte (nicht das Strukturproblem)

**N46 (Teil 1) P0 `sync.py:942`** — das Receipt wird **vor** dem erforderlichen
Abschluss-Delete publiziert (Cleanup erst bei Zeile 963): ein Sweep-Fehler
liefert einen Error, **nachdem** Freshness vorgerueckt ist. Verletzt AC6s
Receipt-last-Ordnung. **Behebbar.**

**N47 P0 `sync.py:894`** — der Legacy-Backfill loescht Alt-Zeilen (Zeile 900)
**bevor** der Upsert (Zeile 904) laeuft. Scheitert der Upsert, sind indizierte
Alt-Zeilen weg, ohne vollstaendigen Ersatz und ohne Receipt. Kehrt die
verbindliche Reihenfolge „neu schreiben und validieren → alt loeschen →
Receipt" um. Der Erfolgstest uebt den zwischenzeitlichen Write-Fehler nie.

**N48 P0 `weaviate_adapter.py:854`** — der neue Legacy-Delete traegt **kein
Projekt- und kein Source-Praedikat**: `id CONTAINS_ANY … AND owning_generation
IS NULL`. Der Port bekommt weder `project_id` noch `source_file`, obwohl AC4
Projektisolation fuer **jede** Loeschoperation verlangt. **→ AC4.** Dies ist das
dritte Mal, dass ein neuer Code-Pfad eine etablierte Pflicht nicht mitgenommen
hat (nach N44 Counter-Striktheit).

**N49 P1 `sync.py:680`** — der Vanished-Pfad loescht alle Null-Generation-Zeilen
*zuerst* und validiert die gestempelten danach: bei einer Legacy-Zeile plus einer
praesent-aber-ungueltigen Generation wird zuerst geloescht und dann gehoben.
Ausserdem bleibt `SyncResult.backfilled` im Vanished-Fall leer.

**N50 P1 `engine.py:595`** — `_release_marker_exists` akzeptiert **jede** Zeile
an der deterministischen UUID, ohne `state=released`, Projekt, Source, Owner oder
Generation zu pruefen: ein malformter Duplikat-Marker mit `state=claimed` laesst
den Sync erfolgreichen Release melden, waehrend die Quelle belegt bleibt.
**→ AC10.**

**P2-7** `sync.py:886` — Produktionskommentar traegt die widerlegte
„same content"-Praemisse weiter. **P2-8** `test_sync.py:861` — die
Testbegruendung „ein uebernommener Halter erreicht seine Completion nie" ist
**falsch**: ein Takeover nach dem Receipt-Fence kann sehr wohl zu einer
Completion niedrigerer Generation samt Sweep fuehren (das Praedikat schuetzt
weiterhin, die Begruendung nicht).

## Konzeptbewertung

Die Edits bleiben innerhalb FK-13 §13.9.9/D9, fuegen keine Vertrags-/
Zustandsflaeche hinzu, §13.9.6/doc_kind unberuehrt; P3-Record und Addendum
strukturell adaequat und markieren die „same content"-Praemisse korrekt als
falsch.

**Die normative Schlussfolgerung ist dennoch unzutreffend:** FK-13 sagt, das
Fenster sei „bis zur Completion" begrenzt, waehrend das Cleanup *nach* der
Completion laeuft — und raeumt danach ein, dass spaeter Eintreffendes auf den
naechsten Sync wartet. Das ist weder completion-begrenzt noch notwendig endlich.
Zudem stellt es einen erforderlichen zerstoerenden Schritt **nach** das Receipt,
entgegen AC6.

## AC-Bilanz

| AC | Status |
|----|--------|
| AC1, AC2, AC3, AC5, AC7, AC8, AC9, AC11, AC12 | **PASS** |
| **AC4** | ERROR — neuer IS-NULL-Delete ohne Projekt-/Source-Praedikate (N48) |
| **AC6** | ERROR — erforderlicher Delete nach dem Receipt; After-Sweep-Stale-Writes unbegrenzt; Legacy-Cleanup loescht vor der Verifikation (N46/N47) |
| **AC10** | ERROR — malformte Duplikat-Release-Marker akzeptiert; gemischte Vanished-Legacy-Zeilen mutieren vor vollstaendiger Validierung (N49/N50) |

**Ausdruecklich nicht die Ursache dieses Verdikts:** Q2, die D9-PO-Rebestaetigung
und das AG3-172-Landegate.
