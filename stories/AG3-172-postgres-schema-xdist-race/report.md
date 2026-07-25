# AG3-172 — Story-Bericht

**Stand:** alle sechs Akzeptanzkriterien erfuellt. Ein DoD-Punkt offen: die volle
Suite ist wegen **vorbestehender, storyfremder** Fehler nicht gruen (§8).
**Branch:** `fix/ag3-172-determinism-proof` (ab `main`).

**Vorarbeit:** Commit `d4715d28` (frueherer Lauf, bereits auf `main`) enthaelt den
OID-Race-Fix und den ersten Regressionstest. Der **Determinismus-Beweis war nie
erbracht** worden — Docker/Postgres war damals nicht verfuegbar. Dieser Bericht
liefert ihn und dokumentiert einen zusaetzlichen, bei der AC5-Pruefung gefundenen
und behobenen Defekt derselben Ursachenklasse.

## 1. Ursache

Beide Defekte haben denselben Modellfehler als Wurzel: **der PostgreSQL-
Systemkatalog ist pro DATENBANK global, nicht pro Schema.** `pg_class`,
`pg_constraint` und `pg_namespace` enthalten die Objekte *aller* Schemas derselben
Datenbank. Die Testtopologie (AG3-051) gibt jedem xdist-Worker ein eigenes
*Schema* innerhalb **einer** gemeinsamen Datenbank — alle Worker-Relationen liegen
also in einem gemeinsamen Katalog. Zwei Produktionspfade behandelten diesen
Katalog, als waere er schemalokal.

### 1.1 Die OID-Race in `_verify_evidence_command_kind_present` (Primaerbefund)

Die Abfrage vor dem Fix schraenkte `c` allein durch `contype = 'c'` ein; die
Schema-Einschraenkung hing an den **gejointen** Relationen `pg_class`/
`pg_namespace`. Die beiden `position(... pg_get_constraintdef(c.oid) ...)`-
Praedikate referenzieren ausschliesslich `c` und werden vom Planner deshalb auf den
`pg_constraint`-Scan heruntergezogen: sie werden fuer **jede CHECK-Constraint der
gesamten Datenbank** ausgewertet, bevor der Namespace-Join die fremden Schemas
ausschliessen kann.

`pg_get_constraintdef()` liest **nicht** den Query-Snapshot — die Funktion oeffnet
die Relation ueber den SysCache gegen den *aktuellen* Katalogzustand. Ein
paralleles `DROP SCHEMA ... CASCADE` in einem fremden Worker-Namespace entfernt
damit genau die Relation, deren OID die Funktion im naechsten Moment oeffnen will:

    psycopg.errors.InternalError_: could not open relation with OID <n>

**Eine OID ist kein stabiler Handle ueber Anweisungs- und Snapshot-Grenzen hinweg.**

### 1.2 Der schemauebergreifende Guard-Leak in `_ensure_story_identity_constraints`

Bei der AC5-Pruefung gefunden — ein zweiter, unabhaengiger Defekt derselben Klasse:

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'story_contexts_project_key_fkey'
    ) THEN ...

Ungeschraenkt. Constraint-Namen sind nur **pro Tabelle** eindeutig, `pg_constraint`
ist datenbankweit — der Guard liest also fremde Schemas. Der Fremdschluessel ist
**nicht** Teil des `CREATE TABLE story_contexts`; nur diese Funktion legt ihn an.
Folge: das **erste** in eine Datenbank gebootstrappte Schema bekommt den FK, jedes
spaetere behaelt `story_contexts.project_key` still **unreferenziert**.

- Unter xdist: die Schemaform haengt an der Ausfuehrungsreihenfolge.
- In Produktion: eine Datenbank traegt bewusst mehrere versionierte
  `ak3_v*`-Schemas (FK-21). Eine neue Schemaversion verliert den FK still — ein
  **fail-open Integritaetsloch**.

Messung vor dem Fix (zwei Peer-Schemas, echter Produktions-Bootstrap-Pfad):

    gw0  story_contexts_project_key_fkey = True   fc_patterns_check_ref_fkey = True
    gw1  story_contexts_project_key_fkey = False  fc_patterns_check_ref_fkey = True

Der korrekt geschraenkte Geschwister-Guard (`fc_patterns_check_ref_fkey`) ist in
beiden Schemas vorhanden — der Leak ist also kein Bootstrap-Ausfall, sondern genau
die fehlende Schema-Schraenkung. Nach dem Fix: in beiden Schemas `True`.

## 2. Gewaehlte Loesungsrichtung und Begruendung (AC4)

Gewaehlt: **(a) Constraint-Identitaet und -Definition in EINER Anweisung**,
kombiniert mit **(c) Namensauflösung statt OID-Handle** fuer den Bindungsschritt.

### 2.1 Umsetzung

Die Zielrelation wird zuerst und in derselben Anweisung ueber eine Namensauflösung
gebunden, `pg_constraint` anschliessend ueber `conrelid` geprobt:

    WITH target_constraints AS MATERIALIZED (
        SELECT c.oid FROM pg_constraint c
        WHERE c.conrelid = to_regclass(quote_ident(current_schema()) || '.edge_command_records')
          AND c.contype = 'c'
    ), constraint_definitions AS (
        SELECT pg_get_constraintdef(oid) AS definition FROM target_constraints
    )
    SELECT 1 FROM constraint_definitions
    WHERE position('command_kind' in definition) > 0
      AND position('collect_verify_evidence' in definition) > 0

`conrelid = <eine OID>` ist eine indizierte Gleichheit
(`pg_constraint_conrelid_contypid_conname_index`); das Deparsing laeuft
ausschliesslich fuer Constraints der **eigenen** Relation. Fremde DDL ist
konstruktionsbedingt unerreichbar, und keine OID verlaesst die Anweisung.

Die drei Geschwister-Guards in `_schema_alter_statements()` (`command_kind`,
`status`, `boundary_type`) sind identisch gehaertet. Das anschliessende
`DROP CONSTRAINT` adressiert **ueber den Namen** (`quote_ident(...)`), nie ueber
eine OID.

`_ensure_story_identity_constraints` wird auf `current_schema()` geschraenkt
(`pg_constraint → pg_class → pg_namespace`), exakt wie das bereits korrekte
`_ensure_failure_corpus_constraints`.

### 2.2 Warum nicht Richtung (b) — Transaktion mit geeigneter Isolation

Eine hoehere Isolationsstufe **hilft nicht**. `pg_get_constraintdef()` ist nicht
snapshot-gebunden; die OID kann auch innerhalb einer einzigen
REPEATABLE-READ-Transaktion verschwinden. Richtung (b) haette Sperrkosten und
veraenderte Transaktionssemantik in den Bootstrap gebracht, **ohne** den
Fehlermodus zu beseitigen — ein plausibel aussehender Nicht-Fix.

### 2.3 Warum nicht ausschliesslich Richtung (c)

Die zulaessige Wertemenge der Constraint ist nur ueber den Definitionstext
(`pg_get_constraintdef`) sichtbar; das Deparsing ist unvermeidbar. Vermeidbar ist
das Deparsing **fremder** Constraints — genau das leistet (a)+(c).

### 2.4 Warum keine eigene Datenbank pro Worker

AC5 erlaubt Schema **oder** Datenbank pro Worker. Eine Datenbank pro Worker wurde
bewusst **verworfen**: die Produktion faehrt absichtlich mehrere versionierte
Schemas in **einer** Datenbank (FK-21). Eine Datenbank pro Worker haette die
adversariale Bedingung aus dem Testbett entfernt und den Produktionsdefekt
**stehen gelassen** — die Symptomvariante. Schema-pro-Worker in einer gemeinsamen
Datenbank erhaelt einen produktionstreuen geteilten Katalog; erst das macht die
beiden Regressionstests aussagekraeftig.

## 3. Regressionstests (AC3)

Beide in `tests/integration/state_backend/test_constraint_catalog_race_postgres.py`.

| Test | Provoziert | Ohne Fix |
|---|---|---|
| `test_constraint_verification_ignores_parallel_foreign_catalog_churn` | vier parallele Threads, die je ein fremdes Schema mit gleichnamiger `edge_command_records`-Relation dauerhaft `DROP`/`CREATE`-en, waehrend 250 Verifikationen laufen | **rot**, 3/3 Laeufe: `could not open relation with OID 44804708 / 44806115 / 44807520` |
| `test_story_identity_fk_is_applied_per_schema` | zwei Peer-Schemas, sequenziell ueber den echten Produktions-Bootstrap (`_connect_global`) | **rot**, 2/2 Laeufe: `story_contexts_project_key_fkey missing` (vorhanden nur im zuerst gebootstrappten Schema) |

Beide Rot-Beweise wurden durch **echtes**, lokales und wieder zurueckgenommenes
Revertieren der jeweiligen Produktionsabfrage erbracht — nicht behauptet. Der
zweite Test prueft zusaetzlich den korrekt geschraenkten Geschwister-FK, damit ein
gruenes Ergebnis nicht durch einen ausgefallenen Bootstrap vorgetaeuscht werden
kann.

## 4. Determinismus-Belege

### AC1 — Reproduktionsbefehl, 20 aufeinanderfolgende Wiederholungen

    .venv\Scripts\python -m pytest -n 2 --dist loadfile --randomly-seed=3250338151 `
      tests/integration/installer/test_third_party_backend_mediation.py `
      tests/integration/installer/test_upgrade_entry.py

**20 von 20 gruen** (`8 passed` je Wiederholung, 12,3–13,8 s). Kein roter Lauf,
daher auch keine Wiederholung eines roten Laufs.
*Orchestrator-Gegenprobe: 3 weitere Wiederholungen, ebenfalls gruen.*

### AC2 — Vollstaendige Installer-Suite, fuenf verschiedene Seeds

Standard-`addopts` (`-n 4 --dist loadfile`), `tests/unit/installer
tests/integration/installer`:

| Seed | Ergebnis |
|---|---|
| `3250338151` (der diagnostizierte Seed) | 550 passed |
| `1` | 550 passed |
| `20260725` | 550 passed |
| `987654321` | 550 passed |
| `4294967295` | 550 passed |

**5 von 5 gruen.** Kein roter Lauf, keine Wiederholung. Die Suite ist seit
Story-Aufnahme von 506 auf 550 Tests gewachsen; es wurde nichts ausgeschnitten.

## 5. Worker-Isolation (AC5)

`tests/fixtures/postgres_backend.py` wurde **nicht geaendert** — die Datei
implementiert die Isolation bereits korrekt. Der tatsaechliche Isolationsdefekt lag
im **Produktionscode** (§1.2). Die Dateiliste im Story-Briefing war eine
Hypothese; AC5 erlaubt ausdruecklich die Begruendung.

**Geteilt:** die Postgres-Instanz und die Datenbank `agentkit_test`; folglich der
datenbankweite Systemkatalog (**bewusst**, §2.4); das `public`-Schema
ausschliesslich ueber `public.ak3_test_schema_registry` (Advisory Lock, Zeilen ueber
den eigenen Schemanamen geschluesselt).

**Nicht geteilt:** das Schema (`ak3test_<testrun_uid>_<PYTEST_XDIST_WORKER>`); der
`search_path` (pro Verbindung auf `<eigenes Schema>, public`); die Prozessumgebung
(jeder xdist-Worker ist ein eigener Prozess); die Testdaten (`TRUNCATE` vor und
nach jedem Test).

Der geteilte Katalog ist nur so lange unschaedlich, wie **jeder** produktive
Katalogzugriff schemagebunden ist. Das ist keine Behauptung mehr, sondern durch
die zwei Regressionstests aus §3 festgenagelt. Ein vollstaendiger Sweep des Baums
(`pg_get_*def`, `pg_constraint`, `pg_class`, `pg_index`, `pg_namespace`,
`information_schema`) bestaetigt: alle vier `pg_get_constraintdef`-Stellen liegen
in `_schema.py` und sind `conrelid`-gebunden; alle uebrigen Katalog- und
`information_schema`-Abfragen der Bootstrap-Kette sind auf `current_schema()` bzw.
den aufgeloesten Schemanamen geschraenkt.

### WARNING (geerbt, ausserhalb dieses Scopes)

`_sweep_stale_test_schemas()` verwirft Registry-Schemas, die nach DB-Uhr aelter als
24 h sind. Ein Lauf jenseits von 24 h, ein pausierter Debugger oder ein haengender
Worker koennte ein noch **lebendes** Geschwister-Schema verwerfen. Die Fixture
dokumentiert das bereits und benennt ein Heartbeat-/`last_seen`-Ownership-Modell
als Folgearbeit. Hier gemeldet statt still liegengelassen (SEVERITY-SEMANTIK).

## 6. Keine Unterdrueckung (AC6)

| Pruefung | Befund |
|---|---|
| `-p no:randomly` | nirgends im Baum. `pytest-randomly` aktiv, jeder Lauf meldet `Using --randomly-seed=...` |
| Retry-/Rerun-Mechanik | kein `pytest-rerunfailures`, kein `--reruns`, kein Flaky-Plugin |
| Serialisierung der betroffenen Dateien | keine. Kein `xdist_group`-Marker. Die drei `pytest_collection_modifyitems`-Hooks binden bzw. ueberspringen ausschliesslich die Postgres-Fixture — sie ordnen und gruppieren nicht |
| `addopts` | `-n 4 --dist loadfile`, durch diese Story **unveraendert**. Eingefuehrt 2026-07-03 in `aadf9bfc` zur Begrenzung des Verbindungs-Footprints — 18 Tage vor Anlage dieser Story |
| Verengung der Suite | keine (550 Tests, gewachsen von 506) |

## 7. Geaenderte Dateien

| Datei | Aenderung |
|---|---|
| `src/agentkit/backend/state_backend/postgres_store/_schema.py` | `_ensure_story_identity_constraints`: Existenz-Guard auf `current_schema()` geschraenkt (+ Begruendung im Docstring). Der OID-Race-Fix stammt aus `d4715d28` und ist hier **verifiziert**, nicht erneut geaendert |
| `tests/integration/state_backend/test_constraint_catalog_race_postgres.py` | zweiter Regressionstest + Modul-Docstring, der beide Defektklassen benennt |
| `stories/AG3-172-postgres-schema-xdist-race/status.yaml` | `ready → in_progress` |
| `stories/AG3-172-postgres-schema-xdist-race/report.md` | dieser Bericht |

`tests/fixtures/postgres_backend.py`: unveraendert, Begruendung in §5.

Commits: `05c27b6d` (Fix + Regressionstest), `bbe86461` (Status).

## 8. Validatoren

| Validator | Ergebnis |
|---|---|
| `ruff check src tests` | **All checks passed** |
| `mypy src` | **Success: no issues found in 972 source files** |
| `pytest tests/integration/state_backend tests/contract/state_backend` | **189 passed** |
| `pytest` (volle Suite) | **4 failed, 9999 passed, 14 skipped** in 550 s — siehe unten |
| Coverage (explizit `--cov=agentkit`) | **92 %** (57752 Statements) — ueber der 85-%-Schwelle |

### ERROR — volle Suite nicht gruen (vorbestehend, storyfremd)

    FAILED tests/unit/concept_toolchain/test_incubator_check.py::test_green_run_passes
    FAILED tests/unit/concept_toolchain/test_incubator_check.py::test_local_overlay_union_keeps_run_green
    FAILED tests/unit/concept_toolchain/test_intake_freeze.py::test_green_run_satisfies_both_pins
    FAILED tests/unit/concept_toolchain/test_incubation_e2e.py::test_full_mini_run_reaches_promotion_closure

**Als vorbestehend nachgewiesen:** mit gestashten Aenderungen (sauberer HEAD)
treten exakt dieselben vier Fehler auf. Sie sind **deterministisch** (scheitern auch
isoliert), also **kein** Determinismusdefekt und nicht Gegenstand dieser Story.

**Praezise Ursache (Orchestrator-Nachdiagnose):** Der Befund lautet
`baseline digest does not match the committed blob of base_revision` **plus**
`baseline byte count does not match` fuer *jede* Korpusdatei, aus
`_check_baseline_rederivation`
(`.../concept_toolchain/incubator_check.py:611-613`). Betroffen sind
ausschliesslich **Fixture-Dateien** eines temporaeren Repos
(`concept/domain-design/01-sample.md`, `concept/formal-spec/sample/*`,
`concept/technical-design/10_sample.md`, `concept-governance.json`,
`projection-manifest.json`) — die **echten** Repo-Dateien sind LF und
byte-identisch mit ihrem Blob (verifiziert).

Ursache ist eine **Newline-Uebersetzung in der Test-Fixture**:
`tests/unit/concept_toolchain/runfixtures.py` schreibt korrekt mit
`newline="\n"`, `tests/unit/concept_toolchain/conftest.py` aber an drei Stellen
**ohne** (Zeilen 79, 124, 267). Auf Windows uebersetzt `Path.write_text()` dann
`\n` → `\r\n`, wodurch Byte-Zahl und Digest gegen den Vergleichsblob abweichen.
Genau die dort geschriebenen Dateien sind die scheiternden.

**Einordnung:** umgebungsspezifisch (Windows), gehoert zum
`concept_toolchain`-Strang (AG3-157..160), **nicht** zu AG3-172. Blockiert den
DoD-Punkt „voller pytest gruen" und damit auch die AG3-164-Landevoraussetzung
„hermetische Pflichtsuite". Der Fix waere klein (`newline="\n"` an den drei
Stellen, analog zur bereits korrekten Konvention in `runfixtures.py`), erfordert
aber eine eigene Story bzw. PO-Freigabe.

## 9. Akzeptanzkriterien

| AC | Kriterium | Status |
|---|---|---|
| 1 | Reproduktionsbefehl in 20 aufeinanderfolgenden Wiederholungen gruen | **erfuellt** — 20/20, Seed `3250338151` |
| 2 | Installer-Suite in fuenf Laeufen mit unterschiedlichen Seeds gruen, ohne Wiederholung roter Laeufe | **erfuellt** — 5/5, `550 passed` je Lauf; kein roter Lauf aufgetreten |
| 3 | Regressionstest provoziert die Race gezielt, ohne Fix nachweislich rot | **erfuellt** — zwei Tests, beide durch echtes Revertieren als rot belegt (§3) |
| 4 | Keine OID ueber Anweisungsgrenzen; Loesungsrichtung begruendet | **erfuellt** — alle vier Stellen `conrelid`-gebunden, DROP ueber Namen; Begruendung inkl. Verwerfen von (b) in §2 |
| 5 | Kein gegenseitig veraenderbarer Katalogzustand — oder begruendet unschaedlich | **erfuellt** — Schema-pro-Worker belegt; geteilter Katalog bewusst beibehalten und begruendet; der dabei gefundene echte Leak (§1.2) behoben |
| 6 | Keine Unterdrueckung | **erfuellt** — Nachweis in §6 |
