# AG3-196 — Fixtures leiten ab statt zu behaupten; selbsterfuellende Tests beseitigen

- **Typ:** implementation
- **Groesse:** M
- **Abhaengigkeiten:** `depends_on: ["AG3-194"]`
- **Quell-Konzept:** `CLAUDE.md` §Tests, `PROJECT_STRUCTURE.md` §tests,
  `guardrails/testing-guardrails.md`
- **Herkunft:** PO-Befund vom 2026-08-02. Ausgezogen aus AG3-183 am 2026-08-02
  nach unabhaengigem Codex-Review (Auflagen ERROR-10 / ERROR-11).

## Kontext

### Befund — belegt, mit Locator

Eine Suite kann interne Konsistenz beweisen. **Uebereinstimmung mit der Welt
kann sie strukturell nicht** — sie leitet Eingabe UND Erwartung aus derselben
Annahme im Repo ab. Es gibt in AK3 zwei Bauarten, die diesen strukturellen
Mangel zusaetzlich verschaerfen:

**(a) Die behauptende Fixture.** `_named_vector_config` schrieb
`poolingStrategy: "masked_mean"` von Hand hin. Sie beschrieb damit eine
Collection, die niemand betreibt, und hielt die Suite gruen, waehrend die
Infrastruktur laengst auf bge-m3 lief. **Dreizehn** Tests haengen an dieser
einen Konstante. Neben ihr existierten sorgfaeltige Negativpfade, die genau die
beiden Abweichungen als Verletzung parametrisierten, samt Notiz „N35: Pooling +
vectorizeClassName uebereinstimmend ist NICHT genug" — sie waren gruendlich
ueber den **Mechanismus** und blind ueber den **Wert**, und setzten den
falschen durch.

**(b) Der Test, der sich seine Voraussetzung selbst erschafft.**

- `set_password` wird ausschliesslich aus Tests aufgerufen
  (`tests/unit/auth/test_credentials.py`,
  `tests/unit/auth/http/test_auth_routes.py`,
  `tests/integration/control_plane/test_takeover_confirm_pg.py`). Die Suite
  erschafft die Voraussetzung, die der Wirklichkeit fehlt — deshalb ist nie
  aufgefallen, dass es keinen Bootstrap gibt.
- `test_real_hook_pair_...` injizierte ein falsches `python` ueber den PATH und
  *verlangte*, dass der Hook es aufruft. Der Test schrieb den defekten Vertrag
  fest; nach der Installation im Fremdprojekt starb jeder Commit an einem
  fehlenden Import.
- `vectorize_property_name` wurde gegen ein Feld geprueft, das die benutzte API
  nie befuellt. Der Vergleich lief gegen Defaults und war zufaellig gruen — er
  hat nie etwas geprueft.

### Warum die Sollverteilung hier haengt

Der Ist-Stand ist gemessen (4457 unit / 696 integration / 595 contract /
5 e2e). Eine wiederholbare Messung ist nur sinnvoll gegen ein Zielbild, und das
Zielbild ist eine PO-Entscheidung — **AG3-194**. Ohne sie waere „zu wenig E2E"
eine Meinung und die Messung ein Zahlenfriedhof.

## Scope

### In Scope

- Beseitigung handgeschriebener SSOT-Konstanten in Fixtures, beginnend beim
  belegten VektorDB-Bereich.
- Beseitigung der drei belegten selbsterfuellenden Tests.
- Eine wiederholbare Messung der Pyramidenverteilung gegen die Sollverteilung
  aus AG3-194.

### Out of Scope

- Die Fremdsystem-Vertragsmatrix und die E2E-Spitzen — **AG3-183**.
- Gate-Outcome-Ehrlichkeit — **AG3-195**.
- **Keine Erhoehung der Coverage-Schwelle und kein Massenschreiben von
  Unit-Tests.** Diese Story adressiert die **Bauart**, nicht die Menge.
- Die Behebung der Fachdefekte, die dabei sichtbar werden (Bootstrap:
  **AG3-180**; Interpreter: **AG3-189**; Modellvertrag: **AG3-181**).

## Betroffene Dateien

| Pfad | Aenderungsart | Warum |
|---|---|---|
| `tests/**/conftest.py`, VektorDB-Fixtures (`_named_vector_config` u. a.) | geaendert | Ableitung aus der SSOT statt handgeschriebener Konstanten |
| `tests/unit/auth/`, `tests/integration/control_plane/` | geaendert | Erstzugangs-Tests ohne selbstgesetzte Voraussetzung |
| Der Hook-Test `test_real_hook_pair_...` | geaendert/entfernt | schreibt heute den defekten Vertrag fest |
| Die `vectorize_property_name`-Pruefung | geaendert | prueft heute nichts |
| `scripts/ci/` (Messung) | neu | Ist-Verteilung gegen Sollverteilung |
| `concept/_meta/decisions/2026-XX-XX-testbauart.md` | neu | Decision Record mit Betroffenheitsmatrix |

## Akzeptanzkriterien

1. **Keine Fixture schreibt einen Wert von Hand hin, der eine SSOT-Konstante
   wiedergibt.** Nachgewiesen an der Kernursache: keine Fixture im
   VektorDB-Bereich enthaelt mehr eine handgeschriebene Modell-, Pooling- oder
   Schema-Konstante. Der Nachweis ist eine **Liste der geprueften Fixtures**,
   nicht die Aussage „durchgesehen".
2. **Ein Aendern der SSOT bricht die abgeleiteten Tests.** Nachgewiesen per
   Mutation: die SSOT-Konstante wird testweise veraendert, die zugehoerigen
   Tests werden rot, die Aenderung wird zurueckgenommen. Eine Ableitung, die
   die Mutation ueberlebt, ist keine.
3. **Die drei belegten selbsterfuellenden Tests sind beseitigt** — nicht
   ergaenzt:
   - Erstzugang: es existiert ein Test, der **ohne** vorher gesetztes Passwort
     laeuft.
   - Git-Hook: es existiert ein Test, der zeigt, dass der Hook korrekt laeuft,
     **obwohl** ein falsches `python` im PATH steht; der alte Test, der das
     Gegenteil verlangte, ist korrigiert oder entfernt.
   - `vectorize_property_name`: die Pruefung liest ein Feld, das die benutzte
     API tatsaechlich befuellt — nachgewiesen daran, dass sie gegen einen
     falschen Wert rot wird.
   **Es gibt keinen Ausweg ueber eine Begruendung, warum das „unmoeglich" sei.**
4. **Die Messung der Pyramidenverteilung ist wiederholbar** und stellt den
   Ist-Stand der Sollverteilung aus AG3-194 gegenueber. Sie laeuft als Kommando,
   nicht als einmalige Handzaehlung.
5. **Die Story deckt auf, was sie nicht beseitigen konnte.** Bleiben
   handgeschriebene Konstanten oder selbsterfuellende Tests ausserhalb des
   VektorDB-/Auth-/Hook-Bereichs stehen, sind sie **namentlich** aufgelistet und
   einem Nachfolger zugeordnet — nicht stillschweigend uebergangen.
6. **Volle Suite gruen**, `ruff` clean, `mypy --strict` fuer `win32`, `linux`,
   `darwin`; Coverage haelt die 85-%-Schwelle; alle deterministischen
   Konzept-Gates gruen.

## Definition of Done

- AC 1–6 erfuellt, jedes mit benanntem Beleg (Kommando, Ausgabe, Testname).
- Die Mutationsnachweise aus AC 2 und AC 3 liegen mit Diff und Testausgabe im
  Story-Record.
- Decision Record im Diff oder gueltiger `Concept-Decision`-Trailer.
- Unabhaengiges Codex-Review bis zum Abbruchkriterium aus `CLAUDE.md`.

## Konzept-Referenzen

- `CLAUDE.md` §Tests — Pflichtregeln, Testebenen
- `PROJECT_STRUCTURE.md` §tests Regel 5 und 6 — Golden Files versioniert,
  Fixtures enthalten statische Testdaten, keine generierten Dateien
- `guardrails/testing-guardrails.md`

## Guardrail-Referenzen

- `CLAUDE.md` „REALITAETSNACHWEIS AN FREMDSYSTEM-GRENZEN" — der Abschnitt
  „gruendlich ueber den Mechanismus und blind ueber den Wert" beschreibt genau
  diese Story.
- `CLAUDE.md` §Tests — „Tests duerfen produktiven Pipeline-State nicht als
  Abkuerzung manuell zusammenfantasieren."
- `CLAUDE.md` „MOCKS/STUBS NUR IM ENGEN AUSNAHMEFALL".
- `CLAUDE.md` „ZERO DEBT RULE" — AC 5.
