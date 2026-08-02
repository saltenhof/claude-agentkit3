# AG3-183 — Fremdsystem-Vertragsmatrix und eine echte Spitze je Vertrag

- **Typ:** implementation
- **Groesse:** L
- **Abhaengigkeiten:** `depends_on: ["AG3-194"]`
- **Quell-Konzept:** `CLAUDE.md` „REALITAETSNACHWEIS AN FREMDSYSTEM-GRENZEN",
  `PROJECT_STRUCTURE.md` §tests, `guardrails/testing-guardrails.md`
- **Herkunft:** PO-Befund vom 2026-08-02, ausgeloest durch sechs
  VektorDB-Storys ohne einen einzigen Live-Lauf. Neu geschnitten am 2026-08-02
  nach unabhaengigem Codex-Review (Auflagen ERROR-10 und ERROR-11).

## Kontext

### Befund — gemessen am 2026-08-02

| Ebene | Dateien | Testfunktionen |
|---|---:|---:|
| unit | 599 | 4457 |
| integration | 109 | 696 |
| contract | 97 | 595 |
| **e2e** | **3** | **5** |

Die fuenf E2E-Tests decken `github_live` und `smoke` ab. **Fuer den
VektorDB-Pfad existiert kein einziger** — sechs Storys haben eine
Weaviate-Integration gebaut, und die Spitze der Pyramide weiss nichts davon.
Der heutige `Jenkinsfile` faehrt keine E2E-Stage.

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

### Was am ersten Schnitt falsch war

1. **Die Fremdsystemmenge war unvollstaendig.** AC1 nannte vier Systeme.
   `src/agentkit/integration_clients/` fuehrt **acht**: `are`, `github`,
   `jenkins`, `llm_pools`, `mcp`, `multi_llm_hub`, `sonar`, `vectordb` — dazu
   Postgres als State-Backend und der Harness. Eine Systematik, die zwei
   Drittel ihres Gegenstands nicht kennt, ist keine.
2. **Die CI-Forderung war konzeptwidrig.** AC2 verlangte blockierende
   E2E-Nachweise in der CI, waehrend `PROJECT_STRUCTURE.md:307` und
   `CLAUDE.md` §Tests ausdruecklich „nie in Standard-CI" normieren — ohne die
   normative Aenderung zu benennen. **Diese Weiche entscheidet AG3-194**, nicht
   diese Story.
3. **AC6 enthielt einen billigen Ausstieg:** statt eines realen Tests genuegte
   eine Begruendung, warum er „unmoeglich" sei. Das widerspricht der
   Fremdsystem-Grundregel direkt und ist gestrichen.
4. **AC2 und AG3-184 AC5 trugen dieselbe Aussage** (skipped darf nicht gruen
   sein) — zwei Eigentuemer fuer eine Regel. Sie hat jetzt genau einen:
   **AG3-195**.

## Scope

### In Scope

- Eine **maschinenlesbare Fremdsystem-Vertragsmatrix** ueber **alle**
  Fremdsysteme, mit je: Vertrag, Owner, echter Checkpoint, benoetigte
  Credentials, Pflicht/optional, CI-Stufe, Verhalten bei Abwesenheit.
- Je Vertrag ein E2E-Nachweis gegen das echte Gegenueber.
- Der normative Nachzug in `PROJECT_STRUCTURE.md` und
  `guardrails/testing-guardrails.md` — **entlang der Entscheidung aus
  AG3-194**, nicht darueber hinaus.

### Out of Scope

- Die normative Weiche „CI-Stufe" selbst — **AG3-194**.
- Gate-Outcome-Ehrlichkeit (uebersprungen ≠ bestanden) — **AG3-195**.
- Fixtures, die behaupten statt abzuleiten, und selbsterfuellende Tests —
  **AG3-196**.
- Der Produktpfad einer Fremdinstallation — **AG3-187**.
- **Die Behebung der einzelnen Fremdsystem-Defekte**, die dabei auffallen. Die
  gehoert in die jeweilige Fach-Story; hier entsteht der Nachweis, nicht der Fix.
- Keine Erhoehung der Coverage-Schwelle, kein Massenschreiben von Unit-Tests.

## Betroffene Dateien

| Pfad | Aenderungsart | Warum |
|---|---|---|
| `concept/technical-design/_meta/third-party-contracts.yaml` (o. ae. Ort) | neu | die maschinenlesbare Vertragsmatrix |
| `tests/e2e/` (je Vertrag ein Modul) | neu | die Spitze je Fremdsystem |
| `tests/conftest.py` | geaendert | Marker-/Credential-Registrierung je Vertrag |
| `Jenkinsfile` | geaendert | Stages entsprechend der CI-Stufe aus AG3-194 |
| `scripts/ci/` | neu/geaendert | Pruefung, dass die Matrix vollstaendig ist |
| `PROJECT_STRUCTURE.md` | geaendert | Ebenen-Tabelle und Regel 4 entlang AG3-194 |
| `guardrails/testing-guardrails.md` | geaendert | dito |
| `concept/_meta/decisions/2026-XX-XX-fremdsystem-vertragsmatrix.md` | neu | Decision Record mit Betroffenheitsmatrix |

## Akzeptanzkriterien

1. **Die Vertragsmatrix ist vollstaendig und maschinenlesbar.** Sie fuehrt
   **jedes** Fremdsystem: die acht Adapter unter
   `src/agentkit/integration_clients/` (`are`, `github`, `jenkins`,
   `llm_pools`, `mcp`, `multi_llm_hub`, `sonar`, `vectordb`) sowie Postgres und
   den Harness. Je Eintrag: **Vertrag, Owner, echter Checkpoint, benoetigte
   Credentials, Pflicht/optional, CI-Stufe, Verhalten bei Abwesenheit.**
2. **Vollstaendigkeit ist maschinell erzwungen.** Ein neues Verzeichnis unter
   `integration_clients/` ohne Matrixeintrag laesst ein Gate rot werden.
   Nachgewiesen an einem konstruierten Zusatzverzeichnis, das rot macht und
   danach zurueckgenommen wird. Ohne diese Pruefung ist die Matrix beim
   naechsten Adapter wieder unvollstaendig.
3. **Jeder Vertrag hat eine eigene Spitze.** Fuer jeden Pflicht-Eintrag der
   Matrix existiert ein E2E-Nachweis gegen das **echte** Gegenueber. Eine
   E2E-Ebene, die GitHub und einen Smoke-Pfad abdeckt, sagt nichts ueber
   Weaviate. Es gibt **keinen** Ausweg ueber eine Begruendung, warum ein realer
   Test „unmoeglich" sei: ist er es tatsaechlich, ist das nach
   `CLAUDE.md` „FEHLENDES BESCHAFFEN STATT UMGEHEN" entscheidungsreif dem PO
   vorzulegen — was fehlt, warum es die richtige Wahl ist, welche Nachteile es
   hat, und die explizite Frage, ob beschafft wird.
4. **Jeder Nachweis prueft einen Wert, nicht nur einen Mechanismus.** Fuer jede
   Spitze ist benannt, **welche Groesse das Gegenueber mitbestimmt** (Modell,
   Schema, Port, Endpunkt, Version) und dass der Nachweis genau diese Groesse
   ausliest — nicht eine Repo-Konstante gegen sich selbst prueft.
5. **Die CI-Stufe folgt der Entscheidung aus AG3-194.** Jeder Matrixeintrag
   traegt sie, und der `Jenkinsfile` bildet sie ab. Weicht die Umsetzung von der
   Entscheidung ab, ist das ein Fehler, keine Auslegung.
6. **Ein ausgefallener Nachweis ist eine benannte Luecke mit Grund im Lauf** —
   nie ein stilles Ueberspringen, nie „gruen". Die technische Durchsetzung
   dieser Unterscheidung liegt bei **AG3-195**; diese Story stellt sicher, dass
   jeder Matrixeintrag ein definiertes „Verhalten bei Abwesenheit" hat und dass
   es getestet ist.
7. **Die Regel aus `CLAUDE.md` ist mit dem tatsaechlichen CI-Aufbau
   abgeglichen.** Der dort genannte Anlassfall bleibt korrekt oder wird
   praezisiert.
8. **Konzept nachgezogen:** `PROJECT_STRUCTURE.md` und
   `guardrails/testing-guardrails.md` entsprechen der Entscheidung aus
   AG3-194; Decision Record mit Betroffenheitsmatrix; alle deterministischen
   Konzept-Gates gruen.

## Definition of Done

- AC 1–8 erfuellt, jedes mit benanntem Beleg (Kommando, Ausgabe, Testname).
- Jede Spitze ist mindestens einmal gegen das echte Gegenueber gefahren;
  Kommando und Ausgabe liegen im Story-Record. Wo ein Gegenueber nicht
  verfuegbar war, steht die Luecke benannt mit Grund — nicht „gruen".
- `.venv\Scripts\python -m pytest` gruen; `ruff check src tests` clean;
  `mypy src --strict` gruen fuer `win32`, `linux` und `darwin`.
- Decision Record im Diff oder gueltiger `Concept-Decision`-Trailer.
- Unabhaengiges Codex-Review bis zum Abbruchkriterium aus `CLAUDE.md`.

## Konzept-Referenzen

- `CLAUDE.md` „REALITAETSNACHWEIS AN FREMDSYSTEM-GRENZEN" — die Grundregel und
  ihr belegter Anlassfall
- `PROJECT_STRUCTURE.md` §tests, Ebenen-Tabelle (`:298`), Regel 4 (`:307`)
- `guardrails/testing-guardrails.md`
- `concept/technical-design/13_retrieval_vektordb_wissenszugriff.md` (VektorDB),
  `18_relationales_abbildungsmodell_postgres.md` (State-Backend)

## Guardrail-Referenzen

- `CLAUDE.md` „REALITAETSNACHWEIS AN FREMDSYSTEM-GRENZEN" — AC 3, AC 4, AC 6.
- `CLAUDE.md` „FEHLENDES BESCHAFFEN STATT UMGEHEN" — AC 3: fehlt ein Dienst,
  wird er entscheidungsreif vorgelegt, nicht der Test abgeschwaecht.
- `CLAUDE.md` „ZERO DEBT RULE" — AC 1 und AC 2: keine Restluecke in der Matrix.
- `CLAUDE.md` „Konzepttreue ist Pflicht" — AC 5 und AC 8.
