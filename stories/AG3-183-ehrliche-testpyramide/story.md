# AG3-183 — Ehrliche Testpyramide: Tests, die die Wirklichkeit beruehren

- **Typ:** implementation
- **Groesse:** L
- **Betroffen:** `tests/` (alle Ebenen), `Jenkinsfile`, `CLAUDE.md`-Regel vom 2026-08-02
- **Herkunft:** PO-Befund vom 2026-08-02, ausgeloest durch sechs VektorDB-Storys ohne einen einzigen Live-Lauf.

## Befund

Die Pyramide ist keine. Nachgemessen am 2026-08-02:

| Ebene | Dateien | Testfunktionen |
|---|---:|---:|
| unit | 599 | 4457 |
| integration | 109 | 696 |
| contract | 97 | 595 |
| **e2e** | **3** | **5** |

Die fuenf E2E-Tests decken `github_live` und `smoke` ab. **Fuer den
VektorDB-Pfad existiert kein einziger** — sechs Storys haben eine
Weaviate-Integration gebaut, und die Spitze der Pyramide weiss nichts davon.

**Die Ursache ist nicht die Zahl, sondern die Bauart.** Eine Suite leitet
Eingabe UND Erwartung aus derselben Annahme im Repo ab. Sie kann interne
Konsistenz und Durchsetzung beweisen; Uebereinstimmung mit der Welt kann sie
strukturell nicht. Belege aus einem einzigen Tag:

- **Die Pooling-Strategie.** Eine Fixture (`_named_vector_config`) schrieb
  `poolingStrategy: "masked_mean"` von Hand hin. Sie beschrieb damit eine
  Collection, die niemand betreibt, und hielt die Suite gruen, waehrend die
  Infrastruktur laengst auf bge-m3 lief. **Dreizehn** Tests haengen an dieser
  einen Konstante.
- **Sorgfaeltige Negativpfade helfen nicht.** Es gab Tests, die genau unsere
  zwei Abweichungen als Verletzung parametrisierten, samt Notiz „N35: Pooling +
  vectorizeClassName uebereinstimmend ist NICHT genug". Sie waren gruendlich
  ueber den Mechanismus und blind ueber den Wert — sie setzten den falschen Wert
  durch.
- **Der Git-Hook-Test.** `test_real_hook_pair_...` injizierte ein falsches
  `python` ueber den PATH und *verlangte*, dass der Hook es aufruft. Er schrieb
  damit den defekten Vertrag fest: nach der Installation im Fremdprojekt starb
  jeder Commit an einem fehlenden Import.
- **Ein Blindgaenger.** `vectorize_property_name` wurde gegen ein Feld geprueft,
  das die benutzte API nie befuellt. Der Vergleich lief gegen Defaults und war
  zufaellig gruen — er hat nie etwas geprueft.
- **Der Erstzugang.** `set_password` wird ausschliesslich aus Tests aufgerufen.
  Die Suite erschafft sich die Voraussetzung, die der Wirklichkeit fehlt.

## Akzeptanzkriterien

1. **Jeder Fremdsystem-Vertrag hat eine eigene Spitze.** Fuer VektorDB,
   State-Backend, Harness und CI existiert je ein E2E-Nachweis gegen das echte
   Gegenueber. Eine E2E-Ebene, die GitHub und einen Smoke-Pfad abdeckt, sagt
   nichts ueber Weaviate.
2. **Diese Nachweise laufen in der CI** und sind blockierend — nicht opt-in.
   Faellt einer aus, weil ein Dienst fehlt, ist das eine **benannte Luecke** mit
   Grund im Lauf, nie ein stilles Ueberspringen und nie „gruen".
3. **Fixtures leiten ab, statt zu behaupten.** Kein Test schreibt einen Wert von
   Hand hin, der eine SSOT-Konstante wiedergibt. Nachgewiesen an der
   Kernursache: keine Fixture im VektorDB-Bereich enthaelt mehr eine
   handgeschriebene Modell-, Pooling- oder Schema-Konstante.
4. **Es gibt eine benannte Sollverteilung der Pyramide** — PO-Entscheidung, kein
   erfundener Wert — und eine Messung, die den Ist-Stand dagegen sichtbar macht.
   Ohne Zielbild ist „zu wenig E2E" eine Meinung.
5. **Der Retrieval-Qualitaetsnachweis des Modellwechsels** ist erbracht: vorher
   gegen nachher auf dem eigenen Korpus. Der Wechsel auf bge-m3 war fachlich
   vermutlich richtig und ist bis heute **nicht gemessen**.
6. **Ein Test, der seine eigene Voraussetzung erschafft, ist als solcher
   erkennbar.** Mindestens fuer die belegten Faelle (Erstzugang, PATH-Injektion,
   handgeschriebene Schema-Konstanten) existiert je ein Test, der ohne die
   selbstgesetzte Voraussetzung laeuft — oder eine begruendete Feststellung,
   warum das an dieser Stelle unmoeglich ist.
7. Die Regel aus `CLAUDE.md` („Realitaetsnachweis an Fremdsystem-Grenzen") ist
   mit dem tatsaechlichen CI-Aufbau abgeglichen. Der dort genannte Anlassfall
   bleibt korrekt oder wird praezisiert.

## Abgrenzung

Keine Erhoehung der Coverage-Schwelle und kein Massenschreiben von Unit-Tests.
Die Story adressiert die **Bauart** und die fehlende Spitze, nicht die Menge.

Die Behebung der einzelnen Fremdsystem-Defekte, die dabei auffallen, gehoert in
die jeweilige Fach-Story — hier entsteht der Nachweis, nicht der Fix.
