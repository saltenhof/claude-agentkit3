# AG3-177 — Story Report (Phase 1 + Phase 2)

- **Story:** AG3-177 Sichtbarkeit veralteter Chunks nach einer Claim-Uebernahme
- **Branch:** `feat/ag3-174-vectordb-retrieval-engine` (die Story sitzt auf AG3-174
  und wird mit ihm gelandet; `depends_on: [AG3-174]`)
- **Status:** implementiert. **Alle 6 ACs erfuellt** — AC6 mit einer benannten,
  begruendeten Asymmetrie statt eines Scheintests (siehe unten).
- **Ratifizierte Form:** **Variante (c)** — den Rest vertraglich fassen, **erkennbar
  machen** und sein Aufraeumen zur Betriebspflicht erheben. Ratifizierung:
  `po-decision.md` (2026-07-26).

## Was hier NICHT behauptet wird

Der Restbefund ist **nicht geschlossen**. (c) schliesst ihn nicht und behauptet es
auch nicht: nach Stillstand, administrativem Reclaim und wiederanlaufendem
Altprozess koennen Zeilen einer niedrigeren Generation neben den aktuellen liegen
und vom Retrieval mitgeliefert werden. Es gibt **keine** Atomizitaet und **keine**
zeitliche Schranke — auch kein „nur kurz". Geaendert hat sich, dass dieser Zustand
**nicht mehr unbemerkt** bleiben kann und dass sein Aufraeumen einen zugewiesenen
Ausloeser hat.

## Phase 1 — Entwurf und Ratifizierung (AC1)

`design.md` (Commit `a3d7ecbb`) enthaelt die praezise Restaussage (beide
unabgedeckten Klassen, vier Eintrittsbedingungen), die **verifizierte** — nicht neu
erfundene — Bewertung der drei Formen, die Messungen auf dem heissen Suchpfad und
die Empfehlung. Die Vorbewertung war an fuenf Stellen zu korrigieren; das ist dort
dokumentiert.

**Kein Code vor der Ratifizierung.** Phase 1 lieferte ausschliesslich `design.md`;
die Umsetzung begann erst nach `po-decision.md`. Diese Reihenfolge war die
Kernauflage der Story (in AG3-174 sind drei Mechanismen gescheitert, weil ohne
ratifizierte Entscheidung gebaut wurde).

**Die Messungen in `design.md` bleiben unveraendert** und sind von dieser Umsetzung
auch nicht invalidiert: sie betreffen die Kosten eines **Filters auf dem Suchpfad**
(Variante (b)). Diese Umsetzung fasst den Suchpfad nicht an — sie fuegt eine
Aggregation in `list_sources` hinzu, das die betroffenen Zeilen und die
Abschluss-Records ohnehin liest.

## Phase 2 — was gebaut wurde (AC2, AC3)

### Erkennbarkeit ist die Lieferung, nicht die Fussnote

`story_list_sources` meldet je Source-Type **`stale_chunk_count`**: die Anzahl der
Chunks, die **nicht** zur autoritativen Generation ihrer Quelle gehoeren.

- **Autoritaet** (`authoritative_generations`, `engine.py`) ist die **hoechste
  Generation unter den verifizierten, abgeschlossenen** Records einer Quelle —
  dieselbe Ordnung, mit der `get_receipt` entscheidet, welche Completion gilt
  (N39). Eine Quelle **ohne** Completion hat keine Autoritaet und wird **nicht**
  beurteilt: eine erfundene Bezugsgroesse waere geraten.
- **Gezaehlt** (`stale_chunk_count`, `engine.py`) werden Zeilen **unterhalb** der
  autoritativen Generation (der Uebernahme-Rest — genau das, was der naechste Sync
  entfernt), Zeilen **ohne** Generation (Bestand vor `owning_generation`; derselbe
  Aufraeumweg konvergiert sie) und Zeilen mit **vorhandener, aber unbrauchbarer**
  Generation (nicht autoritativ und behandlungsbeduerftig — der Sync weist sie
  benannt ab, statt sie zu raten).
- **Nicht gezaehlt** werden Zeilen einer **hoeheren** Generation: das ist ein
  laufender, noch nicht publizierter Sync, kein Rest.
- `chunk_count` bleibt die **physische** Zahl. (c) aendert die **Erkennbarkeit**,
  nicht die Sichtbarkeit — eine stillschweigend gefilterte Zaehlung waere genau die
  Beschoenigung, die der Vertrag verbietet.

**Kosten: keine.** `list_sources` liest die Zeilen und die Abschluss-Records
bereits; die Autoritaetskarte wird **einmal** pro Aufruf gebildet, nicht je
Source-Type. Kein neuer Transportaufruf, keine gespeicherte Kennzahl, keine zweite
operative Wahrheit — die Zahl wird bei jedem Aufruf aus dem gelesenen Zustand
berechnet.

### Der Ort der Meldung

`contracts.py` nimmt `stale_chunk_count` in die `return_fields` von
`story_list_sources` auf. D1 fixierte eine **Mindest**-Shape („Mindestens …"), die
Erweiterung ist damit vertragskonform. **Kollision mit der Strenge-Regelung: keine.**
`story_list_sources` nimmt keine Eingabeparameter (das Projekt kommt aus der
Umgebung, D2), also sind Eingabevalidierung und `reject_unknown_args` unberuehrt;
gewachsen ist allein der Rueckgabe-Envelope. Die beiden Vertrags-Pins sind
entsprechend nachgezogen: die D1-Mindestmenge wird als **Untermenge** geprueft
(darf wachsen, nie schrumpfen) **und** die aktuelle Menge **exakt** (die
Erweiterung bleibt bewusst, nicht beliebig).

### Die Betriebspflicht — dort, wo der Betrieb sie findet

- **FK-04 §4.5.14** (neues Runbook, Format `Symptom / Ursache / Loesung` wie die
  13 bestehenden): Symptom (`stale_chunk_count > 0`), Ursache (wieder angelaufener
  ueberholter Schreiber; **kein** Datenverlust), **Betriebspflicht** („nach JEDEM
  administrativen Reclaim einen Sync der betroffenen Quelle fahren — nicht erst,
  wenn die Kennzahl auffaellt"), Loesungsschritte, Eskalation bei unbrauchbarer
  Generation und ein ausdrueckliches „nicht manuell in der VektorDB loeschen".
- **Am Ort der Handlung:** `cli.py` nennt die Pflicht im Docstring des
  Sync-Kommandos **und** im `--reclaim`-Hilfetext, mit Verweis auf FK-04 §4.5.14 —
  der Operator liest sie beim Ausloesen der Uebernahme, nicht erst im Story-Report.

### Konzept: FK-13 ist wieder wahr (AC5)

- **§13.9.9:** Der Block „Offener Restbefund (nicht ratifiziert)" ist durch den
  **ratifizierten Restvertrag** ersetzt: Zugesichertes, **Nicht**-Zugesichertes
  (ausdruecklich keine Atomizitaet, keine Zeitschranke, kein „nur kurz"), Wirkung,
  Erkennbarkeit als **tragende Bedingung**, der deterministische Aufraeumweg samt
  Betriebspflicht, und die bewusst offen gehaltene Option (b). Beide unabgedeckten
  Klassen bleiben benannt; der Abschluss-Delete bleibt ausdruecklich erhalten.
- **§13.4.1:** Die vage Prosa („Liefert Übersicht über …") ist durch die
  **explizite Rueckgabetabelle** ersetzt, inkl. `stale_chunk_count`, inkl. des
  Hinweises, dass `chunk_count` die physische Zahl ist, und inkl. der
  Mindest-Shape-Regel und der unveraenderten Eingabe-Strenge.
- **Decision Record (P3):**
  `concept/_meta/decisions/2026-07-26-post-completion-stale-chunk-contract.md` —
  Anlass, Entscheidung, gemessene Kostenasymmetrie, **fuenf** verworfene
  Alternativen mit Begruendung, Neubewertungsbedingungen, Impact-Sweep und
  Betroffenheitsmatrix.
- **D9-Record:** erhaelt einen **Vorwaertszeiger** (Nachtrag /4). Seine Historie
  („in AG3-174 wurde keine der drei Formen entschieden") bleibt richtig und wird
  nicht umgeschrieben; die D9-Entscheidung selbst wird **nicht** ersetzt, daher
  `supersedes: []`.
- **§13.9.6 (`doc_kind`-Vokabular) und §13.9.5 (Abfrageoberflaeche) bleiben
  unberuehrt.** Es entsteht kein Abfrageparameter und kein Frontmatter-Feld; die
  Generation bleibt von der Abfrageoberflaeche fern.

## Beweise — sieben Tests, alle revert-verifiziert (AC3)

Alle in `tests/unit/vectordb/test_engine_realpath_r2.py`, alle durch die **echte**
Kette `handle_tool_call` -> `McpToolService` -> `WeaviateRetrievalPort` ->
`WeaviateCorpusStore`, mit dem Double **nur** am Weaviate-Client-Rand.

| Test | Aussage |
|---|---|
| `…_a_materialised_residual_is_reported_in_the_source_listing` | Der Rest wird **gemeldet** (`stale_chunk_count == 1`), und `chunk_count` bleibt die physische Zahl |
| `…_the_reported_residual_disappears_when_the_source_is_synced` | Der Aufraeumweg aus dem Runbook wirkt: nach dem Sync `0`, und die Zeile ist physisch weg |
| `…_a_legacy_row_is_reported_as_non_authoritative` | Eine Zeile ohne Generation ist ebenfalls nicht autoritativ |
| `…_an_in_flight_newer_generation_is_not_reported_as_stale` | Eine **hoehere** Generation ist ein laufender Sync, kein Rest |
| `…_rows_of_a_source_without_a_completion_are_not_judged` | Ohne Completion keine Autoritaet — es wird nicht geraten |
| `…_an_unfinished_record_does_not_grant_authority` | Ein unfertiger Record erzeugt **keinen Fehlalarm** ueber die aktuellen Zeilen |
| `…_the_figure_is_part_of_the_published_envelope` | Die Kennzahl steht im **veroeffentlichten** Vertrag, und jede Zeile fuellt genau ihn (Integer, kein Bool) |

**Revert-Check: 7 von 7 Faellen RED**, danach restauriert gruen (`__pycache__` je
Fall gepurgt — ein groessengleicher Patch, im selben Uhrzeit-Sekundenschritt
zurueckgesetzt, hinterlaesst sonst gueltiges Bytecode und erzeugt
Phantom-Ergebnisse): Kennzahl aus dem Envelope entfernt (4 Tests fallen),
Aelter-Bedingung neutralisiert (2), Zeilen ohne Generation uebersprungen (1), `<`
durch `!=` ersetzt (1), Quellen ohne Completion doch beurteilt (1),
Completion-Zustandsfilter entfernt (1), Vertragsfeld entfernt (1).

**Eine Fixture-Korrektur, offen benannt.** Mein erster Aufbau war **physikalisch
falsch**: der haengende Schreiber haelt nach seinem Claim eine **hoehere**
Generation als die letzte Completion, also war seine Zeile korrekterweise
„in-flight" und nicht „stale" — der Test scheiterte zu Recht. Der Rest entsteht
erst, wenn die Quelle **nach** der Uebernahme abgeschlossen synchronisiert wurde.
Die Fixture fuehrt jetzt genau diese Folge und **prueft** die Voraussetzung
(`authoritative.generation > hung.generation`), statt sie anzunehmen.

**Ein Test bewusst am Funktionsrand begruendet.** Der Completion-Zustandsfilter
liess sich nicht ueber `set_receipt` beweisen: dieses prunt beim Schreiben die
niedrigeren Generationen derselben Quelle und kann die zu pruefende Konstellation
daher nie selbst hinterlassen. Der Record wird deshalb — digest-gueltig, an seiner
positionsgebundenen UUID, wie ein fremder/legacy Schreiber ihn hinterlaesst —
direkt eingesetzt und dann durch die **echte** Leseverifikation von
`list_receipts` gezogen. Das ist der reale Lesepfad, keine Attrappe.

## AC4 — keine Regression der AG3-174-Zusicherungen

Voller Lauf: **10537 passed, 14 skipped**. Die AG3-174-Beweise laufen unveraendert
mit: kein Loeschen der Daten einer neueren Generation (storage-seitige
Ordnungsbedingung, beide Wettlauf-Reihenfolgen), keine Umkehrung der gemeldeten
Freshness, Receipt-last, Legacy-Konvergenz, Projekt-Isolation server-seitig.
`sync.py` wurde **nicht** angefasst — der Abschluss-Delete bleibt unveraendert
(Auflage 6 des PO: „Der Post-Completion-Sweep bleibt").

## AC6 — Race-Reihenfolgen, ohne Scheinsymmetrie

Die beiden **erreichbaren** Reihenfolgen sind belegt:

- **Stale-Write trifft nach dem zerstoerenden Schritt ein** -> er bleibt liegen und
  wird **gemeldet** (Test 1).
- **Ein zerstoerender Schritt laeuft nach dem Stale-Write** -> er ist entfernt und
  die Kennzahl faellt auf `0` (Test 2).

Die **zweite unabgedeckte Klasse** — eine Zeile, die **waehrend** des paginierten
Lesens an einer bereits gelesenen Seite vorbei eintrifft — wird **nicht** separat
getestet, und das ist Absicht: sie hinterlaesst denselben beobachtbaren Zustand
(Zeilen einer niedrigeren Generation neben den aktuellen), und die Meldung ist
**zustands-**, nicht reihenfolgebasiert. Ein zweiter Test wuerde sich nur in der
Fixture unterscheiden und keinen anderen Produktionspfad durchlaufen — das waere
die symmetrische Attrappe, die AC6 ausdruecklich ausschliesst. Im Vertrag
(§13.9.9) bleibt die Klasse dennoch **benannt**.

## Validatoren (nur Projekt-venv)

| Lauf | Ergebnis |
|---|---|
| `pytest -q --cov=src/agentkit --cov=tools` | **10537 passed, 14 skipped**; **Coverage 90.29 %** (Schwelle 85 %, explizit gemessen — `addopts` enthaelt kein `--cov`) |
| `mypy src` | **Success: no issues found in 998 source files** |
| `ruff check src tests tools/concept_ingester tools/concept_governance` | **All checks passed!** |
| `check_concept_frontmatter` | OK: 90 docs, all lints passed |
| `compile_formal_specs` | OK: 192 documents, 1802 ids, 2344 references |
| `check_concept_reference_integrity` | **PASS**: 0 errors, 55 reports (Reports vorbestehend) |
| `check_concept_code_contracts` | OK: no truth-boundary contract violations |
| `check_architecture_conformance` | OK: no architecture contract violations |
| `check_concept_decision_record` | PASS (Trailer `Concept-Decision:` am Konzept-Commit) |

**Vorbestehend rot, nicht von dieser Story:** `check_concept_scope_consistency`
scheitert repoweit im `concept_ingester`-Schema (**275** Dokumente vor dieser Story,
**276** danach — mein Record scheitert mit demselben `doc_kind 'decision-record' is
not in appendix|core` wie **alle 23** bestehenden Decision Records). Das ist ein
eigener Befund am Ingester-Schema, kein Ergebnis dieser Aenderung — nach
SEVERITY-SEMANTIK hiermit gespiegelt, nicht stillschweigend uebergangen.
`check_concept_authority_prose` ist ein LLM-Gate (`--mode nightly|pre-merge`) und
wurde hier nicht gefahren.

## Ausdruecklich nicht getan

- **Kein Filter auf dem Suchpfad.** Variante (b) bleibt offen entscheidbar; die
  Messungen und die Neubewertungsbedingungen liegen in `design.md` bzw. im Decision
  Record. Die dort bewusst **nicht** erhobene Messung (Filtereinfluss auf
  Trefferqualitaet/Antwortzeit) ist Vorbedingung **jener** Entscheidung, nicht
  dieser.
- **Kein Eingriff in `sync.py`**, kein neues Schema, keine neue Property, kein
  gespeicherter Zaehler.
- **Keine Prozessaufsicht** ausserhalb der VektorDB-Schicht (out of scope: ein
  ueberholter Schreiber kann ein fremder Betriebssystemprozess sein).
- **§13.9.6 / `doc_kind`** unberuehrt.

## AC-Bilanz

| AC | Status | Beleg |
|---|---|---|
| 1 — Phase-1-Entwurf ratifiziert, kein Code davor | **erfuellt** | `design.md` (`a3d7ecbb`), `po-decision.md`; Umsetzung erst danach |
| 2 — ratifizierte Form ohne stille Erweiterung | **erfuellt** | Kennzahl + Vertragstext + Betriebspflicht; kein Retrieval-Filter, kein weiteres Feld |
| 3 — (c): Rest wird erkennbar **gemeldet**, Vertragstext ohne Beschoenigung | **erfuellt** | 7 Tests am realen Pfad, 7/7 revert-verifiziert; §13.9.9 benennt beide Klassen, keine Atomizitaet, keine Zeitschranke |
| 4 — keine Regression der AG3-174-Zusicherungen | **erfuellt** | 10537 passed; `sync.py` unangetastet |
| 5 — §13.9.9 beschreibt den tatsaechlichen Zustand, Record vorhanden, Gates gruen | **erfuellt** | ratifizierter Vertrag ersetzt den offenen Punkt; Decision Record; Gates gruen (Ausnahme vorbestehend benannt) |
| 6 — beide erreichbaren Reihenfolgen, Unerreichbares begruendet | **erfuellt** | Tests 1 und 2; die zweite Klasse ist begruendet **nicht** separat getestet, statt symmetrisch vorgetaeuscht |
