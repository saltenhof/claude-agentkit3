# AG3-176 — Codex-Review der Konzeptinhalte, Runden 2 und 3

Fortsetzung von `concept-review-round1-codex.md`. Jede Runde ist ein frischer
read-only Codex-Agent; die Nachbesserung dazwischen macht der Orchestrator.

Konvergenz: **7 → 4 → 4** Befunde. Der Verlauf ist bewusst festgehalten, weil er
die eigentliche Erkenntnis dieser Story traegt: die Befunde lagen ganz
ueberwiegend **nicht** im Delta der Story, sondern im nie nachgezogenen
Restkorpus des Beschlusses vom 2026-07-21.

---

## Runde 2 — `job-4342fb5a` — NICHT BESTANDEN

Geschlossen aus Runde 1: R-01, R-04, R-06. Teilweise: R-03, R-05, R-07.

### R-02 — BLOCKER (aus Runde 1, weiterhin offen, verschaerft)

Runde 1 hatte nur bemaengelt, dass `mcp[cli] >= 1.2.0` neue Norm sei und
`pyproject.toml` `mcp>=1.0` sage. Die Korrektur „FK-01 auf `mcp>=1.0`
angleichen" war **falsch herum**: Runde 2 belegte, dass `mcp.server.fastmcp` —
die Klasse, von der unser Tool-Surface erbt — erst ab **1.2.0** existiert.
`mcp>=1.0` war also nicht die Wahrheit, an die man angleicht, sondern der
Defekt: eine Installation mit 1.0/1.1 waere beim Import gestorben.

Bestaetigt aus unserer eigenen Quelle: FK-01 fuehrt in der Technologietabelle
seit jeher „FastMCP 1.2+" — zwei Aussagen im selben Dokument, und die
installierte war die falsche.

**Nachbesserung:** `pyproject.toml` und FK-01 §P7 auf `mcp>=1.2.0`, ohne
`cli`-Extra (das zieht nur typer/python-dotenv fuer ein CLI, das AK3 nicht nutzt).

### N-01 — MAJOR — Receipt-Schema wurde beim Verify nicht fail-closed erzwungen

FK-13 §13.9.9 normierte „strikt, Counter >= 0, `failed > 0` wird nie
publiziert, feste Tool-/Source-Zuordnung" — der Code erzwang nichts davon.
`InitialSyncReceipt` hatte strikte **Typen**, aber keine Wertebereiche und keine
Cross-Field-Validierung: leere `project_id`/`end_revision`, `failed=-5` und ein
`story_sync`, das den Konzeptkorpus beansprucht, gingen glatt durch.
`verify_initial_sync()` band den Dateinamen nicht an den Producer.

Eine Norm, die nur beim Schreiben gilt und beim Lesen nicht, ist keine Norm —
das ist geerbte Nachsicht an einer fail-closed-Grenze, in der Story, die genau
diese Klasse von Fehlern jagt.

**Nachbesserung:** `min_length`/`ge`/`le`-Constraints, `_TOOL_SOURCE_TYPES` +
`model_validator` fuer die Korpusbindung, `verify_initial_sync()` iteriert ueber
Producer statt Dateinamen. Plus fuenf neue Tests.

### N-02 — MAJOR — VektorDB an drei Stellen weiterhin optional/fail-soft

`00-uebersicht.md` „Story Knowledge Base (VectorDB) — optional"; FK-50-Diagramm
„CP 10 (wenn VektorDB/ARE)"; FK-33 `concept.vectordb` „(wenn verfuegbar)".
Letzteres ist woertlich fail-soft an einer fail-closed-Grenze.

### N-03 — MAJOR — FK-30 hielt weiterhin `--sync`

FK-30 §30.5.4a sagte „Pflicht (`--sync`)", obwohl `build` diesen Schalter nicht
kennt.

---

## Runde 3 — `job-787c17aa` — NICHT BESTANDEN

Geschlossen: R-01, R-03, R-04, R-05, R-06, R-07, N-03, Baseline. Teilweise:
R-02, N-01, N-02.

### R3-01 — BLOCKER — die Untergrenze allein war fail-open nach oben

`mcp>=1.2.0` ohne Obergrenze loest heute **2.0.0** auf (LATEST). MCP 2 hat den
Server nach `mcp.server.mcpserver` verschoben.

**Unabhaengig verifiziert** (nicht per Link, sondern am Artefakt): das Wheel
`mcp-2.0.0-py3-none-any.whl` heruntergeladen — ohne Installation — und
inspiziert. Ergebnis: **null** Eintraege fuer `mcp/server/fastmcp`, und
`mcp/types.py` existiert dort ebenfalls nicht; Server-Subpakete sind `auth`,
`lowlevel`, `mcpserver`. Beide unserer Importe waeren gebrochen.

Die lokale `.venv` (1.27.2) maskierte das — ein installierter Stand beweist
keinen Clean-Install.

**Nachbesserung:** `mcp>=1.2.0,<2` in Packaging und beiden FK-01-Tabellen.

**Lehre:** eine offene Obergrenze ist derselbe Fehler wie geerbte Nachsicht an
einer fail-closed-Grenze — nur in der Zukunft.

### R3-02 — MAJOR — Receipt-Grenzen weiterhin nicht vollstaendig fail-closed

Drei Reste: (1) `empty_corpus` war eine unabhaengige Meinung statt an die
Entdeckungsseite gebunden; (2) `verify_initial_sync()` pruefte nicht, dass beide
Receipts zum selben Projekt gehoeren; (3) der Register-/Upgrade-Pfad las ueber
`_old_receipt()` ohne erwarteten Producer — ein vertauschtes Paar konnte als
Before-Image uebernommen und seine Revisionen auf den falschen Korpus gekettet
werden.

**Nachbesserung:** Validator `empty_corpus == (discovered == 0)` und bei leerem
Korpus `unchanged == upserted == 0`, wobei `deleted` bewusst frei bleibt (der
Uebergang nichtleer → leer loescht seine Alt-Chunks); Paar-Pruefung auf
`project_id`; gemeinsame Lesefunktion `_load_receipt(path, expected_tool=...)`,
ueber die **jeder** Lesepfad geht.

### R3-03 — MAJOR — die neuen Negativtests waren regressionsblind

Der unangenehmste Befund, weil er die Nachbesserung aus Runde 2 traf:
`_valid_receipt_payload()` lieferte `source_types` als **Liste**, das Modell
verlangt im Strict-Mode ein **Tupel**. Jeder parametrisierte Negativfall schlug
damit schon aus dem falschen Grund fehl — die Tests waeren gruen geblieben, wenn
man saemtliche Wertebereichs-Constraints wieder ausgebaut haette.

Ein Test, der aus dem falschen Grund besteht, ist schlimmer als kein Test: er
taeuscht Deckung vor.

**Nachbesserung:** alle direkten Modelltests ueber `model_validate_json`; ein
Guard-Test, der zuerst beweist, dass die Baseline-Payload gueltig ist; jeder
Negativfall assertiert die Fehler-**Lokation**; zusaetzliche Faelle fuer
Empty-Corpus (positiv mit `deleted>0` und negativ), vertauschtes Paar auf dem
Registerpfad und Paar aus zwei Projekten.

### R3-04 — MAJOR — DK-00 fuehrte VektorDB weiterhin als Feature-Flag

§8 nannte sie (nach Runde 2) korrekt Pflicht, §10 zaehlte sie zwei Absaetze
spaeter weiter unter „Feature-Flags (VectorDB, ARE, …)".

### Positiv festgehalten (Runde 3)

- Die Aenderungen in DK-00 §8, BC-Cut, FK-33 und FK-50 normieren **nichts** ueber
  Rand 1 hinaus — sie korrigieren Tatsachen gegen Beschluss und Code.
- Baseline: Working Tree und `HEAD` haben je 51 Eintraege, keine neue
  Unterdrueckung; die vier verschobenen Eintraege zeigen exakt auf die
  behaupteten Referenzen.
- `empty_corpus=true, deleted>0` bleibt zulaessig.
- Die asynchrone Closure-Indizierung (FK-13/20/29/BC-Cut) wurde geprueft und
  ausdruecklich **nicht** als Befund gewertet: sie wird stets ausgeloest und ist
  bestehende Post-Merge-Semantik; Rand 1 betrifft nur den Installer-Abschaltzweig.

---

## PO-Entscheidung 2026-07-30 zum Umfang

Auf die Frage, ob der Restkorpus-Nachzug hier weiterlaeuft oder eine eigene
Story wird:

> „In dem Moment, wo du sagst, du schneidest daraus eine extra Story, sage ich
> dir im Anschluss an diese Story: mach die naechste Story. Die Arbeit bleibt
> dieselbe. Sie wird mehr, weil du noch die Story schreiben musst. Also mach
> lieber gleich mit."

Der Nachzug laeuft damit **in dieser Story**; festgehalten als AC 10. Der
Orchestrator hat daraufhin aufgehoert, passiv auf Codex-Funde zu warten, und den
Restkorpus aktiv flaechendeckend durchsucht (Optionalitaets-/Feature-Flag-
Formulierungen, nicht ausfuehrbare Aufrufe, Korpuszuordnungen,
`vectordb_disabled`-Pfade, Bundle-Assets, Schema-/Beispielkonfigurationen).
Dabei zusaetzlich gefunden und behoben: FK-50 §50.6 fuehrte
`configuration_invalid` noch mit „`features.vectordb` **aktiv**, aber …" — eine
Formulierung, die die Abschaltbarkeit implizit weitertraegt.
