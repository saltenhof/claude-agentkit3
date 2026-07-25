# AG3-172 — Story-Bericht

**Stand:** alle sechs Akzeptanzkriterien erfuellt. Ein DoD-Punkt offen: die volle
Suite ist wegen **vorbestehender, storyfremder** Fehler nicht gruen (§8).
**Branch:** `fix/ag3-172-determinism-proof` (ab `main`).

**Vorarbeit:** Commit `d4715d28` (frueherer Lauf, bereits auf `main`) enthaelt den
OID-Race-Fix und den ersten Regressionstest. Der **Determinismus-Beweis war nie
erbracht** worden — Docker/Postgres war damals nicht verfuegbar. Dieser Bericht
liefert ihn und dokumentiert einen zusaetzlichen, bei der AC5-Pruefung gefundenen
und behobenen Defekt derselben Ursachenklasse.

**Nachtrag (Review-Befund F1, Commit `ed228e4e`):** Die erste Remediation dieses
zweiten Defekts war selbst ein **Halbfix** — sie schraenkte nur auf das Schema ein,
nicht auf die Zieltabelle. Der externe Review hat das aufgedeckt; §1.2 und §2.1
benennen jetzt die tatsaechlich erforderliche Praezision (Schema **und** Tabelle
**und** Constraint-Klasse) und halten fest, dass der als Vorbild verwendete
Geschwister-Guard dieselbe Luecke trug und daher **kein** Referenzmuster ist.

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

### 1.2 Der unpraezise Constraint-Existenz-Guard (`conname` ohne Relationsbindung)

Bei der AC5-Pruefung gefunden — ein zweiter, unabhaengiger Defekt derselben Klasse:

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'story_contexts_project_key_fkey'
    ) THEN ...

**Die erforderliche Praezision ist `conname` PLUS Schema PLUS Tabelle — nicht
`conname` und nicht `conname` plus Schema.** PostgreSQL dokumentiert
`pg_constraint.conname` ausdruecklich als "not necessarily unique"; der eindeutige
Katalogindex liegt auf `(conrelid, contypid, conname)`. Ein Name ist also nur **pro
Tabelle** eindeutig. Empirisch gegen PostgreSQL 17 bestaetigt: zwei Constraints
namens `dup_name_fkey` koexistieren in EINEM Schema auf verschiedenen Tabellen.

Daraus folgen zwei getrennte Fehlerstufen:

**Stufe 1 — schemauebergreifend (Erstbefund).** `pg_constraint` ist datenbankweit,
der Guard liest also fremde Schemas. Der Fremdschluessel ist **nicht** Teil des
`CREATE TABLE story_contexts`; nur diese Funktion legt ihn an. Folge: das **erste**
in eine Datenbank gebootstrappte Schema bekommt den FK, jedes spaetere behaelt
`story_contexts.project_key` still **unreferenziert**.

- Unter xdist: die Schemaform haengt an der Ausfuehrungsreihenfolge.
- In Produktion: eine Datenbank traegt bewusst mehrere versionierte
  `ak3_v*`-Schemas (FK-21). Eine neue Schemaversion verliert den FK still — ein
  **fail-open Integritaetsloch**.

Messung vor dem Fix (zwei Peer-Schemas, echter Produktions-Bootstrap-Pfad):

    gw0  story_contexts_project_key_fkey = True   fc_patterns_check_ref_fkey = True
    gw1  story_contexts_project_key_fkey = False  fc_patterns_check_ref_fkey = True

**Stufe 2 — gleiches Schema, andere Tabelle (Review-Befund F1).** Die erste
Remediation schraenkte nur auf `current_schema()` ein und war damit ein **Halbfix**:
ein gleichnamiger Constraint auf einer ANDEREN Tabelle desselben Schemas erfuellt
den Guard weiterhin, das `ALTER TABLE` entfaellt, und `story_contexts.project_key`
bleibt ohne FK — derselbe stille Integritaetsverlust, nur eine Variante tiefer. Der
Regressionstest der ersten Remediation blieb dabei gruen, weil er ausschliesslich
schemauebergreifende Kollisionen erzeugte.

**Der Geschwister-Guard war KEINE gueltige Referenz.** Die erste Remediation
begruendete ihr Vorgehen mit „genauso wie das bereits korrekte
`_ensure_failure_corpus_constraints`". Dieser Geschwister-Guard trug **dieselbe
Tabellen-Unschaerfe** und war damit selbst fehlerhaft — „dem korrekten Geschwister
folgen" war hier also kein tragfaehiger Maßstab. Beide sind jetzt gefixt, und der
Docstring von `_ensure_failure_corpus_constraints` sagt ausdruecklich, dass er nicht
als Referenzimplementierung dieses Musters gelten darf.

Insgesamt trugen **fuenf** Guards in `_schema.py` dieselbe Unschaerfe; die drei ueber
den Review-Befund hinausgehenden wurden mitgefixt statt liegengelassen (§2.1).

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

Dasselbe Bindungsmuster tragen jetzt **alle fuenf** Constraint-Existenz-Guards des
Bootstraps. Jeder bindet `c.conrelid` an `to_regclass()` der voll qualifizierten
Zielrelation und prueft zusaetzlich `conname` und `contype` — Schema **und** Tabelle
**und** Constraint-Klasse:

| Guard | Zielrelation | `contype` | Herkunft |
|---|---|---|---|
| `_ensure_story_identity_constraints` | `story_contexts` | `f` | Review-Befund F1 |
| `_ensure_failure_corpus_constraints` | `fc_patterns` | `f` | Review-Befund F1 |
| `_ensure_session_binding_constraints` (2 Guards) | `session_run_bindings` | `c` | ueber F1 hinaus mitgefixt |
| `_ag3_137_binding_constraints_present` (Canary) | `session_run_bindings` | `c` | ueber F1 hinaus mitgefixt |

Die beiden letzten Zeilen gehen ueber den Review-Befund hinaus: es ist derselbe
Defekt in derselben Datei. Drei Instanzen einer gerade als Halbfix zurueckgewiesenen
Unschaerfe stehen zu lassen waere ein ZERO-DEBT-Verstoss. Beim Canary ist die
Wirkung besonders unangenehm: ein gleichnamiger CHECK auf einer anderen Tabelle
haette ihn „vorhanden" melden lassen und damit genau die Migration unterdrueckt, die
er ausloesen soll. Fehlt die Zielrelation, liefert `to_regclass` NULL, keine Zeile
matcht und der Canary faellt geschlossen aus (`fail-closed`).

Nicht betroffen: `_takeover_approval_challenge_ref_unique_present` war bereits
tabellenpraezise (prueft `takeover_approvals` und den Indexnamen im selben
Namespace). Nach dem Fix existiert in `_schema.py` kein Constraint-Guard mehr, der
allein auf `conname` (+ Schema) filtert.

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
| `test_bootstrap_fk_guards_ignore_same_name_decoy[story_identity]` | Decoy-FK des geschuetzten Namens auf einer ANDEREN Tabelle des SELBEN Schemas, gepflanzt VOR dem Bootstrap | **rot**, 2/2 Laeufe **gegen den Schema-only-Guard**: FK landet nur auf `ak3_decoy_child`, nie auf `story_contexts` |
| `test_bootstrap_fk_guards_ignore_same_name_decoy[failure_corpus]` | dito fuer `fc_patterns_check_ref_fkey` | **rot**, 2/2 Laeufe gegen den Schema-only-Guard |

Alle Rot-Beweise wurden durch **echtes**, lokales und wieder zurueckgenommenes
Revertieren der jeweiligen Produktionsabfrage erbracht — nicht behauptet.

Zwei Eigenschaften machen die Decoy-Faelle belastbar:

1. **Revert-Basis ist der Halbfix, nicht das Original.** Die Decoy-Faelle wurden
   gegen den **schema-only** Guard rot verifiziert, nicht bloss gegen den
   urspruenglich ungeschraenkten. Genau das ist der Punkt: sie beweisen die
   Tabellen-Praezision, nicht nur die Schema-Praezision. Waehrend die Decoy-Faelle
   rot waren, blieben die beiden aelteren Tests gruen — die neuen Faelle decken also
   eine tatsaechlich andere Variante ab.
2. **Der Decoy ueberlebt den Bootstrap.** Die Bootstrap-Hilfsfunktion bekam einen
   `recreate=False`-Pfad; ein `DROP SCHEMA` vor dem Bootstrap haette den Decoy
   entfernt und der Test haette nichts bewiesen.

Zusaetzlich prueft `test_story_identity_fk_is_applied_per_schema` den
Geschwister-FK, damit ein gruenes Ergebnis nicht durch einen ausgefallenen
Bootstrap vorgetaeuscht werden kann. Die Fundort-Hilfsfunktion loest
`(Schema, Tabelle)`-Paare auf statt nur Schemas — „der Name existiert irgendwo in
meinem Schema" beweist nach §1.2 gerade nichts.

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
| `src/agentkit/backend/state_backend/postgres_store/_schema.py` | fuenf Constraint-Existenz-Guards an Schema **und** Tabelle **und** `contype` gebunden (§2.1, + Begruendung in den Docstrings). Der OID-Race-Fix stammt aus `d4715d28` und ist hier **verifiziert**, nicht erneut geaendert |
| `tests/integration/state_backend/test_constraint_catalog_race_postgres.py` | drei zusaetzliche Regressionsfaelle (Cross-Schema + zwei parametrisierte Decoy-Faelle), tabellenpraezise Fundort-Hilfsfunktion, `recreate=False`-Bootstrap-Pfad, Modul-Docstring benennt beide Defektklassen |
| `stories/AG3-172-postgres-schema-xdist-race/status.yaml` | `ready → in_progress` |
| `stories/AG3-172-postgres-schema-xdist-race/report.md` | dieser Bericht |

`tests/fixtures/postgres_backend.py`: unveraendert, Begruendung in §5.

Commits: `05c27b6d` (Erst-Remediation + Regressionstest), `bbe86461` (Status),
`c8d333d6` (Bericht), `ed228e4e` (Review-Befund F1: Schema-**und**-Tabellen-Bindung
aller fuenf Guards + parametrisierter Decoy-Test).

## 8. Validatoren

Stand nach `ed228e4e` (F1-Remediation):

| Validator | Ergebnis |
|---|---|
| `ruff check src tests` | **All checks passed** |
| `mypy src` | **Success: no issues found in 972 source files** |
| `pytest tests/integration/state_backend tests/contract/state_backend` | **191 passed** (+2 Decoy-Faelle) |
| `pytest` (volle Suite) | **4 failed, 10001 passed, 14 skipped** in 566 s — dieselben vier vorbestehenden Fehler, +2 neue Tests, **keine Regression** |
| AC1-Reproduktionsbefehl (Gegenprobe nach F1) | **8 passed**, gruen |
| Coverage (explizit `--cov=agentkit`, Stand `05c27b6d`) | **92 %** (57752 Statements) — ueber der 85-%-Schwelle |

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

### Beobachtung — `llm_hub`-Gegenreview nicht verfuegbar

Der externe Reviewer meldet, dass seine vorgeschriebene `llm_hub`-Gegenpruefung
zweimal nicht erreichbar war (`ECONNREFUSED` auf `127.0.0.1:9600`). Die
Review-Aussagen zu AG3-172 beruhen damit auf einer Quelle statt zwei. Rein als
Beobachtung erfasst — nicht Gegenstand dieser Story und hier nicht verfolgt.

## 9. Akzeptanzkriterien

| AC | Kriterium | Status |
|---|---|---|
| 1 | Reproduktionsbefehl in 20 aufeinanderfolgenden Wiederholungen gruen | **erfuellt** — 20/20, Seed `3250338151` |
| 2 | Installer-Suite in fuenf Laeufen mit unterschiedlichen Seeds gruen, ohne Wiederholung roter Laeufe | **erfuellt** — 5/5, `550 passed` je Lauf; kein roter Lauf aufgetreten |
| 3 | Regressionstest provoziert die Race gezielt, ohne Fix nachweislich rot | **erfuellt** — vier Faelle, alle durch echtes Revertieren als rot belegt; die beiden Decoy-Faelle gegen den **Halbfix**, nicht nur gegen das Original (§3) |
| 4 | Keine OID ueber Anweisungsgrenzen; Loesungsrichtung begruendet | **erfuellt** — alle vier `pg_get_constraintdef`-Stellen `conrelid`-gebunden, DROP ueber Namen; Begruendung inkl. Verwerfen von (b) in §2 |
| 5 | Kein gegenseitig veraenderbarer Katalogzustand — oder begruendet unschaedlich | **erfuellt** — Schema-pro-Worker belegt; geteilter Katalog bewusst beibehalten und begruendet; der dabei gefundene echte Leak (§1.2) behoben, inkl. der vom Review nachgewiesenen Tabellen-Unschaerfe in fuenf Guards |
| 6 | Keine Unterdrueckung | **erfuellt** — Nachweis in §6 |
