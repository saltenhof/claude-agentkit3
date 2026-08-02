# AG3-184 — Qualitaetswerkzeuge, die nicht luegen

- **Typ:** implementation
- **Groesse:** M
- **Betroffen:** `concept/_meta/reference-integrity-baseline.yaml`, `scripts/ci/`, `Jenkinsfile`, `tools/`, FK-93
- **Herkunft:** Drei unabhaengige Befunde am 2026-08-02.

## Befund

**Die Referenz-Integritaets-Baseline haengt an Zeilennummern.** Jeder Eintrag
nennt Pfad **und Zeile**. Jede Textaenderung im referenzierten Konzeptdokument
verschiebt sie, und der Gate-Lauf bricht mit `STALE_BASELINE` ab. Am 2026-08-02
ist das **dreimal an einem Tag** passiert (FK-78 zweimal, FK-13 einmal). Der
Mechanismus erzeugt Arbeit, die nichts prueft, und erzieht dazu, Baseline-
Eintraege gedankenlos nachzuziehen — genau die Haltung, die eine Baseline
wertlos macht.

**`tools/` wird von keinem Gate abgedeckt.** Die verbindlichen Kommandos sind
`ruff check src tests` und `mypy src`. Damit liegen rund 40 000 Zeilen unter
`tools/` (Konzept-Compiler, Governance-Werkzeuge, Ingester) ausserhalb jeder
Pruefung. Nachweisbar vorhanden und unbemerkt: ein `ruff`-C901 in
`tools/concept_compiler/architecture_conformance.py:1409` (20 > 15) und ein
`mypy`-Fehler in `tools/concept_ingester/discovery.py:243`. Ausgerechnet die
Werkzeuge, die unsere Konzeptqualitaet sichern, sind selbst ungeprueft.

**FK-93 fuehrt acht Werte ohne Eigentuemer.** Der Katalog war als reine
Wiedergabe definiert: jede Zeile gibt einen Wert wieder, dessen Norm anderswo
lebt. Fuer acht Werte gibt es dieses Anderswo nicht — fuenf in §93.5a
(`request_ttl_s`, `pause_ttl_s`, `lease_ttl`, External-Prompt-Grace,
`max_open_requests_per_run`; auch die zugehoerigen `permissions.*`-Config-Pfade
existieren in keinem Konfigurationsmodell, nicht einmal in FK-03) und drei in
§93.9a. Ein Umsetzer hat FK-93 daraufhin fuer diese acht selbst zur Normquelle
erklaert; das unabhaengige Review hat das zurueckgewiesen, weil es eine
Grundentscheidung ersetzt statt sie auszudetaillieren.

**Die dahinterliegende Frage ist eine PO-Entscheidung:** Darf ein
Nachschlagekatalog jemals Quelle der Wahrheit sein? Bei „ja" braucht es eine
Regel *wann*, sonst wandert jeder heimatlose Wert dorthin und der Katalog wird
zur zweiten Wahrheit neben den Fachkonzepten. Bei „nein" muessen die acht Werte
bei ihren besitzenden Dokumenten normiert werden.

## Akzeptanzkriterien

1. **Die Baseline bindet nicht mehr an Zeilennummern.** Ein Eintrag ueberlebt
   eine Textaenderung im referenzierten Dokument, ohne nachgezogen zu werden.
   Nachgewiesen: eine Zeile vor dem Eintrag einfuegen, Gate bleibt gruen.
   Gleichzeitig bleibt die Ausnahme so eng, dass sie nicht versehentlich mehr
   abdeckt als gemeint.
2. **`tools/` ist von `ruff` und `mypy` abgedeckt**, und die beiden bekannten
   Befunde sind an der Wurzel behoben — nicht per `noqa`, nicht per Exclude.
   Falls ein Teil von `tools/` bewusst ausgenommen bleibt, steht die Begruendung
   in der Konfiguration, nicht im Kopf des Naechsten.
3. **Die PO-Entscheidung zu FK-93 ist eingeholt und umgesetzt.** Bei „Katalog
   darf Normquelle sein": die Regel *wann* ist ausgeschrieben und maschinell
   pruefbar. Bei „nein": die acht Werte sind bei ihren Eigentuemern normiert und
   FK-93 gibt sie nur noch wieder.
4. **Die `permissions.*`-Pfade haben ein Konfigurationsmodell** oder sind als
   nicht existent entfernt. Ein Konfigurationspfad, den kein Modell kennt, ist
   entweder Schuld oder eine Erfindung — beides wird benannt.
5. **Kein Gate meldet mehr „gruen" fuer etwas, das es nicht geprueft hat.**
   Insbesondere: ein uebersprungener, abgebrochener oder nicht gefahrener Lauf
   ist im Ergebnis unterscheidbar von einem bestandenen.
6. Volle Suite, `ruff`, `mypy --strict` fuer win32/linux/darwin, alle
   deterministischen Konzept-Gates gruen — inklusive der neu abgedeckten Flaeche.

## Abgrenzung

Keine neuen Gates und keine Verschaerfung bestehender Schwellwerte. Diese Story
repariert die Werkzeuge, die es gibt, damit ihre Aussagen tragen.

Die W2/W3-Ablloesung und das agentische Pruefverfahren gehoeren zu AG3-185.
