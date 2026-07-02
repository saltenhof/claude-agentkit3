# AG3-144 — Job-Muster + Ergebnisarten + Upsert-Fences: 202-Job-Annahme, Ergebnisart-Registry, `stale_observation`-Store, materialisierte Fence-Sicht, gefencte artifact-/QA-/closure-Upserts

- **Typ:** implementation
- **Größe:** L
- **depends_on:**
  - [AG3-141] — die neuen mutierenden Job-Annahme-/Ergebnis-Pfade dieser
    Story nutzen den Objekt-Claim-Mechanismus aus AG3-141; die Deklaration
    des Serialization-Scopes allein genügt nicht (Review-Kante Schritt e).
  - [AG3-142] — die Ownership-Prädikate („aktiver Run-Ownership-Record",
    `ownership_epoch`/`binding_version`) und deren transaktionale
    Durchsetzungsfläche entstehen dort; der gefencte Job-Abschluss-Commit
    dieser Story prüft gegen genau diese Fläche (GAP §4: ST-06 → ST-09).
  - [AG3-143] — das Digest-Prädikat (`execution_contract_digest`) wird dort
    definiert und persistiert; ohne diese Kante wäre der
    Fence-Prädikat-Katalog aus FK-91 Regel 15 unvollständig (Kante
    ST-12 → ST-09, GAP-Review-Runde 1 E2).
- **Quell-Konzept:** FK-91 §91.1a Regeln 14 (Bounded-Pflicht/Job-Muster,
  `202` + op_id, `GET operations/{op_id}`), 15 (drei Ergebnisarten +
  Fence-Prädikat-Katalog), 17 (Transport-Timeouts fachlich bedeutungslos);
  FK-44 §44.3a (Digest-Abweichung ⇒ `stale_observation`); FK-56 §56.13c
  (append-only nach Owner-Wechsel, `ownership_epoch`-Markierung);
  `formal.state-storage.invariants`
  (`stale_results_never_overwrite_current_projections`)
- **Herkunft:** GAP-Analyse Session-Ownership v4 (`_temp/gap-analyse-session-ownership.md`),
  Story-Kandidat GAP-ST-09; normative Basis Commits 3ae011e4 / 1bb4ed8a / 58c190b7
  (+ Decision-Records unter `concept/_meta/decisions/`).

## Kontext / Problem

FK-91 Regel 14/15 verlangt: nicht-bounded Arbeit ist ein Job (Annahme `202`
+ op_id, Fortschritt beobachtbar, Abschluss als gefencte interne Mutation),
und jeder Job-Abschluss ist nach seiner deklarierten Ergebnisart gefenct.
Heute existiert nichts davon (am Code verifiziert 2026-07-02; Grep
`stale_observation` in `src/agentkit/`: null Treffer):

- **Phase-Mutationen sind synchron:** Der HTTP-Handler
  (`control_plane_http/app.py:1134-1200`) führt start/complete/fail/resume
  im Request-Thread aus und mappt nur `201`/`409` (:1191-1195). Der
  VerifySystem-Subflow läuft synchron im Phase-Handler
  (`implementation/phase.py`, Decision-Commit :327) — IMPL-012. Es gibt
  keine `202`-/accepted-Statusform.
- **In-flight nicht beobachtbar:** `GET /v1/project-edge/operations/{op_id}`
  existiert (`app.py:263-294`), aber `get_operation`
  (`control_plane/runtime.py:1749-1757`) liefert für `claimed` (in-flight)
  bewusst `None` → 404. Ein laufender Job wäre damit für den Client
  unsichtbar — Regel 14/17 verlangen den Fortschritts-Read.
- **Blinde Upserts ohne jedes Fence-Prädikat** (eigene Recherche, Grep über
  `ON CONFLICT`-Pfade — die im GAP §5/v4-Log bewusst in dieses Briefing
  deferrierte Betroffene-Dateien-Liste der Governance-/State-Writes wird
  hiermit konkretisiert; die physischen Git-/Worktree-Umzüge liegen bei
  AG3-145/AG3-152):
  - `artifact_envelopes`: `store/artifact_repository.py:488-520`
    (`ON CONFLICT ... DO UPDATE` :508-517) — blindes Überschreiben.
  - `qa_stage_results`: `pg_execute_stage_upsert`
    (`postgres_store.py:3169`, Upsert :3194); `qa_findings`:
    `pg_execute_finding_upsert` (:3211, Upsert :3235); Batch-Pfad
    `persist_layer_artifact_rows` (:3284) löscht sogar Findings und baut
    sie neu (`pg_delete_findings_for_scope` :3255) — ohne Ownership-/
    Epoch-/Digest-Prüfung.
  - Verify-Decision (steuernd): `persist_verify_decision_row` (:3352,
    `decision_records`-Upsert :3384).
  - Closure-Report: `record_closure_report` (`store/facade.py:1682`) →
    `persist_closure_report_row` (:3587-3605) — Projektions-Write ohne
    Fence; Aufrufer `closure/execution_report/writer.py:36`.
  - Current-Pointer-artige Projektions-Dateien (`_write_projection`:
    QA-Artefakte :3325, Verify-Decision :3374, Closure :3604).
- **Es fehlen:** Ergebnisart-Deklaration (IMPL-025), `stale_observation`-
  Store (IMPL-014), materialisierte Run-Status-/Fence-Sicht (IMPL-015).
- **Tragfähig:** `compaction_epochs` als story-scoped Epochen-Prädikat
  (Tabelle `postgres_schema.sql:139`, Inkrement
  `store/compaction_epoch_repository.py:156/:175`); der op_id-Reconcile-Weg
  (`GET operations/{op_id}`); das atomare Commit-Muster der Facade-Writes
  (QA-Batch in EINER Transaktion, :3284 ff.).
- **Wire-Randbedingung (K4-Umfeld):** Das Frontend bricht Requests nach
  12 s ab; langes synchrones Warten ist unzulässig — das Job-Muster ist
  auch dafür die richtige Form (IMPL-016 gehört AG3-141, wirkt hier aber
  als Design-Constraint: Annahme bounded, nie lange blockieren).

## Scope

### In Scope

1. **Job-Muster für nicht-bounded Operationen** (SOLL-058, IMPL-012):
   Einstufung der mutierenden Control-Plane-Operationen nach der
   Bounded-Pflicht; der nicht-bounded Phase-Dispatch (Engine-run/-resume
   inkl. VerifySystem-Subflow, `dispatch.py:246`/:416/:424) läuft als Job:
   Annahme = kurze committete Mutation (Job-Record im bestehenden
   operations-Ledger), Antwort **`202` + op_id**; Fortschritt via
   `GET /v1/project-edge/operations/{op_id}` (dazu wird `get_operation`
   :1749-1757 um eine beobachtbare in-flight-Statusform erweitert — kein
   404 mehr für angenommene Jobs); Abschluss = interne, **gefencte**
   Mutation. Zwischen Annahme und Abschluss hält der Job **keine**
   Serialisierung (die heutige Claim-Haltung über die gesamte
   Engine-Ausführung wird auf Annahme-/Abschluss-Commits verengt). Alle
   neuen mutierenden Endpoints/Pfade dieser Story erwerben vor Anwendung
   den Story-Objekt-Claim über den AG3-141-Helper — kein Zweitmechanismus,
   keine bloße Scope-Deklaration.
2. **Ergebnisart-Registry** (SOLL-059, IMPL-025): Typisierte, deklarative
   Registry der drei Ergebnisarten je Job-/Abschlussart —
   `append_only_observation` / `projection_upsert` / `steering` (analog
   Stage-/Producer-Registry-Muster, keine String-Kaskaden). Fail-closed:
   ein Abschluss ohne deklarierte Ergebnisart wird nicht committet.
3. **Fence-Prädikat-Katalog am Abschluss-Commit** (SOLL-060): Auswertung
   am Commit-Zeitpunkt in derselben Transaktion — aktiver
   Ownership-Record der Story, `ownership_epoch`/`binding_version` wie
   erwartet (AG3-142), `operation_epoch` des eigenen Claims unverändert
   (Spalte aus AG3-137, soweit befüllt), Reset-Fence/`compaction_epoch` wo
   einschlägig, `execution_contract_digest` wo einschlägig (AG3-143),
   Zielversion des adressierten Artefakts wo einschlägig.
4. **`stale_observation`-Store** (SOLL-061, IMPL-014): Immutabler,
   projektions-neutraler Historien-Store (Postgres-only): Job-Ergebnisse
   mit ungültigen Fences werden als separater, immutabler Eintrag (mit
   verletztem Prädikat als Grund) abgelegt und aktualisieren **niemals**
   Current-Pointer, „latest"-Sichten, Projektionen oder Steuerzustand.
5. **Append-only nach Owner-Wechsel** (SOLL-062): Reine append-only
   Observationen bleiben nach einem Owner-Wechsel ablegbar — dem Run
   zugeordnet und mit dem `ownership_epoch` ihres Starts markiert (Feld
   z. B. `started_by_ownership_epoch`); sie aktualisieren nie eine
   Projektion.
6. **Materialisierte Run-Status-/Fence-Sicht** (IMPL-015): Eine
   deterministisch abfragbare Sicht (aktiver Record, `ownership_epoch`,
   `binding_version`, `compaction_epoch`, Digest, Exit-/Reset-/
   Split-Freiheit) als die EINE Auswertungsfläche aller Prädikate —
   keine Ad-hoc-Einzelabfragen pro Schreibpfad. Quelle der Exit-/Reset-/
   Split-Freiheit beidseitig: ist AG3-149 bereits gelandet, sind die
   Record-Status (`ended/reset/split`) des Run-Ownership-Records die
   Quelle; andernfalls dient übergangsweise die Ableitung aus committed
   Exit-Ops als Quelle — mit EXPLIZITER Ablösungspflicht durch AG3-149.
7. **Fences auf die inventarisierten Upsert-/Projektions-Pfade**
   (IMPL-013): `artifact_envelopes`-, `qa_stage_results`-, `qa_findings`-,
   `decision_records`-Upserts sowie die Verify-/Closure-/QA-Projektions-
   Writes laufen über das Fence-Gate; jede dieser Schreibflächen deklariert
   ihre Ergebnisart (Artefakt-/QA-Rows = `projection_upsert`;
   Verify-Decision und Phasenfortschritt-Abschluss = `steering`). Bei
   ungültigen Fences: `stale_observation` statt Write.
8. **Wire-/Client-Anpassung:** `202`-/accepted-Statusform in
   `control_plane/models.py` + HTTP-Mapping; `harness_client`
   (`projectedge/client.py`, `start_phase` :398 ff.) und das deployte
   Bundle-Tool (`bundles/target_project/tools/agentkit/projectedge.py`,
   phase-Kommandos :124-141) verstehen die Job-Annahme und rekonsiliieren
   über `GET operations/{op_id}` (Regel 17; kein blockierendes Warten
   > bounded Annahme — verträglich mit dem 12-s-Frontend-Timeout).

### Out of Scope (mit Owner)

- **Prädikat-DEFINITIONEN:** Ownership-Record/Epoch-Fence-Fläche
  **AG3-142**; `execution_contract_digest` **AG3-143** — hier nur deren
  Verwendung.
- **Objekt-Serialisierung** (durable Objekt-Claims, Lock-Sets,
  Erwerbsordnung, Queue-Fairness, Warte-Semantik/K4): **AG3-141**.
- **Instanz-Identität, Startup-Rekonsiliierung, `operation_epoch`-
  CAS-Finalize, `admin_abort`**: **AG3-138** (das `operation_epoch`-Prädikat
  wird hier nur konsumiert, soweit vorhanden).
- **Einheitlicher Idempotenz-Vertrag** (op_id-Minten, `idempotency_keys`,
  Guard-Counter-Pfad): **AG3-140**.
- **Edge-Command-Queue** (Result-Fencing der Edge-Aufträge nutzt dieselbe
  Regel-15-Mechanik): **AG3-145**.
- **`pending_human_approval`** als dritte Antwort-/Statusform (IMPL-010):
  **AG3-148**.
- **Ablösung der Übergangsquelle committed-Exit-Ops** in der
  Fence-Sicht durch die Record-Status `ended/reset/split`: **AG3-149**
  (greift nur, falls diese Story vor AG3-149 landet).
- **Frontend-Anzeige** von Jobs/op_ids/Edge-Zuständen (FK-72 §72.14.7(3)):
  **AG3-153**.
- **Freeze-Familie** (`governance_freeze_records`/`conflict_freeze_proofs`,
  `freeze_epoch`, Admission-Blocker): **AG3-150**.
- **Engine-Zustandstabellen** (`phase_states` :1645, `attempts` :1711,
  `flow_executions` :2940, `flow_node_states` :3055 in
  `postgres_store.py`): deren Schutz ist der Executor-/Regime-Fence aus
  **AG3-142** plus der hier gebaute steuernde Abschluss-Fence — es wird
  keine zweite, eigene Fence-Schicht je Tabelle gebaut (eine Fence-Fläche,
  FIX THE MODEL).

## Betroffene Dateien

| Datei | Änderungsart | Zweck |
|---|---|---|
| `src/agentkit/backend/control_plane/models.py` | ändern | `202`-/accepted-Job-Statusform + typisierte Ergebnisart-/Stale-Antwortformen |
| `src/agentkit/backend/control_plane/runtime.py` | ändern | Job-Annahme als kurze committete Mutation; Abschluss als gefencte Mutation; `get_operation` (:1749-1757) liefert beobachtbare in-flight-Statusform statt `None` |
| `src/agentkit/backend/control_plane/dispatch.py` | ändern | Engine-Ausführung zwischen Annahme- und gefenctem Abschluss-Commit; keine gehaltene Serialisierung während der Ausführung (:246/:416/:424) |
| `src/agentkit/backend/control_plane/result_kinds.py` | neu | Ergebnisart-Registry (typisiert, fail-closed; deklariert je Job-/Abschlussart) |
| `src/agentkit/backend/control_plane_http/app.py` | ändern | `202`-Mapping im Phase-Mutation-Handler (:1134-1200, Status-Mapping :1191-1195); in-flight-Antwort im operations-GET (:263-294) |
| `src/agentkit/backend/state_backend/postgres_schema.sql` | ändern | `stale_observations`-Tabelle (append-only) + materialisierte Run-Status-/Fence-Sicht (Postgres-only, additiv) |
| `src/agentkit/backend/state_backend/postgres_store.py` | ändern | Fence-Gate-Row-Funktionen (Prädikat-Auswertung in derselben Transaktion); gefencte Fassung von `persist_layer_artifact_rows` (:3284), `persist_verify_decision_row` (:3352, Upsert :3384), `persist_closure_report_row` (:3587); `pg_execute_stage_upsert` (:3169)/`pg_execute_finding_upsert` (:3211) hinter das Gate |
| `src/agentkit/backend/state_backend/store/artifact_repository.py` | ändern | `_pg_write`-Upsert (:488-520) über das Fence-Gate; ungültige Fences ⇒ `stale_observation` statt `DO UPDATE` |
| `src/agentkit/backend/state_backend/store/facade.py` (+ `_public_api_names.py`, `__init__.pyi`, `mappers.py`) | ändern | `record_layer_artifacts` (:1430), `record_verify_decision` (:1508), `record_closure_report` (:1682) nehmen Fence-Kontext/Ergebnisart; `stale_observation`-Lese-/Schreib-API |
| `src/agentkit/backend/closure/execution_report/writer.py` | ändern | Closure-Report-Write als gefencter steuernder Abschluss (:36) |
| `src/agentkit/backend/verify_system/artifacts.py` | ändern | QA-Schreibpfad deklariert Ergebnisart + reicht Fence-Kontext durch |
| `src/agentkit/backend/implementation/phase.py` | ändern | Verify-Decision-Commit (:327) als steuernder, gefencter Abschluss |
| `src/agentkit/harness_client/projectedge/client.py` | ändern | `202`-Job-Annahme verstehen; Reconcile über `GET operations/{op_id}` (`start_phase` :398 ff.) |
| `src/agentkit/bundles/target_project/tools/agentkit/projectedge.py` | ändern | Bundle-Asset: Job-Statusform in `phase-start`/`phase-complete`/`phase-fail` (:124-141) inkl. op_id-Reconcile |
| `tests/unit/control_plane/**`, `tests/unit/state_backend/**` | neu/ändern | Registry, Fence-Auswertung, Stale-Routing über Ports/Fakes |
| `tests/integration/**` | neu | Postgres: Fences an allen inventarisierten Pfaden; Owner-Wechsel-/Reset-/Exit-Szenarien; TOCTOU-Concurrency |
| `tests/contract/**` | neu/ändern | Contract-Pin der `202`-Antwortform, der in-flight-Statusform und des `stale_observation`-Formats |

## Akzeptanzkriterien

1. **Job-Annahme:** Eine nicht-bounded Phase-Mutation antwortet nach kurzer
   Annahme-Mutation mit `202` + op_id; der angenommene Job ist ab sofort
   über `GET /v1/project-edge/operations/{op_id}` als in-flight beobachtbar
   (kein 404); ein paralleler Request derselben op_id wird als in-flight
   abgewiesen (bestehender In-Flight-Schutz bleibt).
2. **Keine gehaltene Serialisierung:** Zwischen Annahme- und
   Abschluss-Commit hält der Job keine Serialisierung (Beleg: während eines
   laufenden Jobs bleibt eine unabhängige bounded Read-/Reconcile-Operation
   möglich; Claim-Haltung nachweislich auf die beiden Commits verengt).
3. **Ergebnisart-Pflicht fail-closed:** Ein Job-/Abschlusstyp ohne
   Registry-Deklaration wird deterministisch abgelehnt (Negativtest); die
   Registry ist typisiert und vollständig für alle umgestellten Pfade.
4. **`append_only_observation`:** Nach präpariertem Owner-Wechsel (Record
   über die sanktionierte AG3-137-Single-Writer-Schreibfläche auf
   `transferred`/Epoche+1) wird eine append-only Observation weiterhin
   abgelegt, dem Run zugeordnet und mit dem `ownership_epoch` ihres Starts
   markiert; keine „latest"-Sicht und keine Projektion ändert sich
   (Negativ-Assertion; SOLL-062).
5. **`projection_upsert` gefenct:** Artefakt-/QA-Upsert
   (`artifact_envelopes`, `qa_stage_results`, `qa_findings` inkl.
   Batch-Pfad mit Delete+Rebuild) mit ungültigem Fence ⇒ Projektion und
   Current-Pointer bleiben byte-identisch, das Ergebnis liegt als
   immutabler `stale_observation`-Eintrag vor; mit gültigem Fence ⇒ Upsert
   wie spezifiziert (Positivtest).
6. **`steering` gefenct:** Ein steuernder Abschluss (Verify-Decision,
   Phasenfortschritt) mit ungültigem Fence — getestet je einzeln für
   Owner-Wechsel, Reset (`compaction_epoch`-Sprung) und geänderten
   `execution_contract_digest` — wirkt deterministisch als
   `stale_observation`: kein `decision_records`-Write, kein Phasenübergang,
   keine steuernden Events (`stale_results_never_overwrite_current_projections`).
7. **Store-Immutabilität:** Der `stale_observation`-Store hat keinen
   Update-/Delete-Pfad in der öffentlichen Fassade; Einträge sind
   nachrichtlich abfragbar und tragen das verletzte Prädikat; ein
   wiederholter stale-Commit derselben op_id erzeugt keinen zweiten
   Eintrag (Idempotenz-Test).
8. **Fence-Sicht ohne TOCTOU:** Die materialisierte Run-Status-/Fence-Sicht
   liefert deterministisch (aktiver Record, Epochen, Digest, Exit-/Reset-/
   Split-Freiheit); die Prädikat-Auswertung erfolgt am Commit-Zeitpunkt in
   derselben Transaktion wie der Write (Concurrency-Test: Owner-Wechsel
   zwischen Prüfung und Commit gewinnt nie).
9. **Vollständigkeit der Umstellung:** Kein verbleibender ungefencter
   `ON CONFLICT ... DO UPDATE` auf `artifact_envelopes`/`qa_stage_results`/
   `qa_findings`/`decision_records` und kein ungefencter Verify-/Closure-/
   QA-Projektions-Write (Review-Grep als Beleg; Betroffene-Dateien-Tabelle
   vollständig abgearbeitet).
10. **Negativpfade an Phasengrenzen:** Ein verspäteter Job-Abschluss nach
    Story-Exit bzw. nach Reset — Zustand über den ECHTEN Exit-/Reset-Pfad
    erzeugt, nicht manuell zusammengesetzt — landet als
    `stale_observation`, ohne Projektions- oder Steuerwirkung
    (testing-guardrails).
11. **Wire/Clients:** Contract-Tests pinnen `202`-Form, in-flight-Form und
    Fehlerverträge; `harness_client` und Bundle-Tool behandeln accepted
    Jobs über den op_id-Reconcile; kein Client-Pfad blockiert länger als
    die bounded Annahme (12-s-Frontend-Timeout bleibt eingehalten).
12. **Objekt-Claim-Erwerb:** Alle neuen mutierenden Endpoints/Pfade dieser
    Story (Job-Annahme- und Abschluss-Commit) erwerben vor Anwendung den
    Story-Objekt-Claim über den AG3-141-Helper — kein Zweitmechanismus,
    keine bloße Scope-Deklaration (Test pinnt den Helper-Aufruf).
13. Coverage ≥ 85 % gehalten; `mypy` strict (+ `--platform linux`) und
    `ruff` ohne neue Ausnahmen; ARCH-55 (englische Bezeichner, Wire-Keys,
    Statusformen, Fehlercodes).

## Definition of Done

- Alle Akzeptanzkriterien erfüllt; Gate-Suite grün (`pytest -n0`
  unit/integration/contract, Coverage ≥ 85, `mypy src` + `--platform linux`,
  `ruff`, 4 Konzept-Gates).
- Codex-Review PASS.
- Auf `origin/main` gemerged; `status.yaml` → `completed`;
  README-Backlog-Snapshot (§6.7) nachgezogen.

## Abdeckung (Traceability)

**Deckt ab:** SOLL-058–062; IMPL-012, IMPL-013, IMPL-014, IMPL-015, IMPL-025.

## Konzept-Referenzen

- FK-91 §91.1a Regel 14 (Bounded-Pflicht; Job = `202` + op_id, Fortschritt
  via `GET /v1/project-edge/operations/{op_id}`, Abschluss als gefencte
  Mutation; Job hält zwischendrin keine Serialisierung)
- FK-91 §91.1a Regel 15 (drei Ergebnisarten für Job-Abschlüsse; append-only
  mit `ownership_epoch`-Markierung des Starts; Projektions-Upsert nur bei
  gültigen Fences; steuernde Ergebnisse sonst deterministisch
  `stale_observation`; Prädikat-Katalog: aktiver Ownership-Record,
  `ownership_epoch`/`binding_version`, `operation_epoch`,
  Reset-Fence/`compaction_epoch`, `execution_contract_digest`,
  Artefakt-Zielversion)
- FK-91 §91.1a Regel 17 (Transport-Timeouts fachlich bedeutungslos;
  Rekonsiliierung via op_id)
- FK-44 §44.3a (geänderte Contract-Grundlage ⇒ Job-Ergebnis deterministisch
  `stale_observation` — Digest-Prädikat aus AG3-143)
- FK-56 §56.13c (Wirkung des Owner-Wechsels; append-only Ablage nach
  Transfer bleibt zulässig, Attribution an `run_id + ownership_epoch`)
- `formal.state-storage.invariants` →
  `stale_results_never_overwrite_current_projections`

## Guardrail-Referenzen

- **FAIL-CLOSED:** Ungültige Fences wirken nie „trotzdem"; fehlende
  Ergebnisart-Deklaration lehnt ab; stale Ergebnisse sind nachrichtlich,
  nie steuernd.
- **NO ERROR BYPASSING:** Es gibt keinen Direkt-Schreibpfad an Fence-Gate
  und Registry vorbei (Konformanz über die eine `state_backend.store`-
  Fassade; AK 9 belegt die Vollständigkeit).
- **FIX THE MODEL, NOT THE SYMPTOM:** EINE materialisierte Fence-Sicht und
  EINE Registry statt Ad-hoc-Prüfungen je Schreibpfad; die blinden Upserts
  werden am Modell repariert, nicht per Sonderfall kaschiert.
- **SINGLE SOURCE OF TRUTH / State-Disziplin:** `stale_observation` ist ein
  typisierter, immutabler Store mit klarem Owner — kein Schattenfeld und
  keine zweite operative Wahrheit neben den Projektionen; QA-Artefakte
  bleiben geschützt (Worker können per stale-Routing keine fremden
  QA-Ergebnisse überschreiben).
- **Testing-Guardrails:** Negativpfade an Phasengrenzen (Exit/Reset/
  Owner-Wechsel je einzeln); Pipeline-State über echte Vorgängerpfade,
  nicht zusammenfantasiert.

## Querschnitts-Auflagen

- **K5 Postgres-only:** `stale_observations` und die materialisierte
  Fence-Sicht sind Postgres-only, fail-closed über das
  `_require_postgres_control_plane_backend`-Muster
  (`control_plane/runtime.py:2119`); kein SQLite-Spiegel. Der bestehende
  SQLite-Artefakt-Schreibpfad (`artifact_repository.py:474`) bleibt das
  enge, gated Unit-Test-Backend und erhält KEINE Spiegel-Implementierung
  von Gate/Store — explizite Festlegung, kein stilles Offenlassen.
  Teststrategie: Contract-/Integrationstests über die Postgres-Fixture,
  Unit-Tests über Ports/Fakes.
- **ST-09-Auflage (Plan §3):** Das Digest-Fence-Prädikat setzt AG3-143
  voraus (Kante ST-12 → ST-09, Review-Runde 1 E2) — in `depends_on`
  abgebildet und in AK 6 verprobt.
- **Blutgruppen-Klassifikation**
  (`concept/methodology/software-blutgruppen.md`): Ergebnisart-Registry +
  Fence-Auswertungs-/Stale-Routing-Logik (`result_kinds.py`, Gate-Kern)
  = **A**; Statusform-/Wire-/Client-Mapping = **R**; Fence-Sicht-SQL,
  Stale-Store-Row-Funktionen und transaktionale Gate-Mechanik im
  `state_backend` = **AT/T** (dort lokalisiert). Der A-Kern bleibt AT-frei.
- **Bundle-Assets:** **Betroffen und deklariert:**
  `bundles/target_project/tools/agentkit/projectedge.py` wird angepasst
  (Job-Statusform `202` + op_id-Reconcile in den phase-Kommandos);
  weitere Bundle-Assets sind nicht betroffen (verifiziert: einziges
  API-konsumierendes Tool im Bundle).
