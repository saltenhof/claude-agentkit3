# AG3-139 — TTL-Entfall: Rückbau von Claim-Lease-TTL und CAS-Auto-Takeover

- **Typ:** implementation
- **Größe:** S
- **depends_on:** [AG3-138] — **kritische Ordnungs-Kante (IMPL-006):** die
  per-op_id-Lease-TTL ist heute das **einzige** Verwaisungs-Handling des
  Systems; sie darf erst entfallen, wenn AG3-138 die Start-Rekonsiliierung
  (+ `admin_abort`) produktiv ersetzt hat. Zwischen beiden Stories darf kein
  Deployment-Zustand ohne jedes Verwaisungs-Handling existieren (GAP §4:
  „ST-03 TTL-Entfall NUR nach ST-02").
- **Quell-Konzept:** `formal.operating-modes.invariants`
  (`ownership_transfer_requires_explicit_confirmed_request`); FK-91 §91.1a
  Regel 16 (Claims enden nie über Wanduhr/TTL/Lease); FK-10 §10.5.4
  („Kein Lease, kein TTL, keine PID-Heuristik")
- **Herkunft:** GAP-Analyse Session-Ownership v4 (`_temp/gap-analyse-session-ownership.md`),
  Story-Kandidat GAP-ST-03; normative Basis Commits 3ae011e4 / 1bb4ed8a / 58c190b7
  (+ Decision-Records unter `concept/_meta/decisions/`).

## Kontext / Problem

Der heutige Nebenläufigkeitsschutz der Control-Plane ist ein
per-op_id-Lease-Modell mit **automatischer Übernahme** abgelaufener Claims —
exakt das Modell, das der Session-Ownership-Strang fachlich verbietet
(Regel 2: AgentKit kann client-seitiges Schweigen nicht deuten — tot,
Langläufer, Pause, wartet auf Benutzereingabe —, also läuft Ownership **nie**
automatisch ab). Am Code verifiziert (2026-07-02):

- `_CLAIM_LEASE_TTL = timedelta(minutes=5)`
  (`src/agentkit/backend/control_plane/runtime.py:83`).
- `_claim_is_expired` (`runtime.py:629-655`; Wanduhr-Vergleich gegen die TTL
  :655) entscheidet in `_acquire_claim` (:534-627), ob ein fremder in-flight
  Claim per CAS übernommen wird: nicht abgelaufen → in-flight-Reject (:603),
  abgelaufen → `takeover_operation` (:616).
- Der Takeover-Pfad läuft über den Port
  `control_plane/repository.py:83` (`takeover_operation` →
  `takeover_control_plane_operation_global`) zur Fassade
  (`state_backend/store/facade.py:838`) und Row-Funktion
  (`state_backend/postgres_store.py:2332`,
  `takeover_control_plane_operation_global_row`).
- Die Unit-Suite pinnt dieses Verhalten aktiv
  (`tests/unit/control_plane/test_runtime.py`: u. a. :2314-2335 —
  „EXPIRED foreign claim (10 minutes old): CAS takeover succeeds";
  :2626, :2879).
- Lease-Vokabular durchzieht Kommentare/Records (`runtime.py` AG3-054-Blöcke,
  `control_plane/records.py:53-59`, Schema-Kommentar
  `state_backend/postgres_schema.sql:223-230`).

Nach AG3-138 existiert der normkonforme Ersatz: In-Flight-Claims sind
instanzgebunden und enden ausschließlich über die Start-Rekonsiliierung der
eigenen Instanz oder `admin_abort_inflight_operation`. Die TTL-Mechanik ist
dann tote, normwidrige Konkurrenz-Semantik und wird restlos zurückgebaut
(SOLL-110, Code-Seite von Block 11).

## Scope

### In Scope

1. **`_CLAIM_LEASE_TTL` und `_claim_is_expired` entfernen**
   (`runtime.py:83`, :629-655): es gibt keinen Code-Pfad mehr, der das Alter
   eines Claims fachlich interpretiert.
2. **Auto-Takeover-Zweig aus `_acquire_claim` entfernen** (:534-627): ein
   fremder in-flight Claim führt **immer** zum deterministischen
   in-flight-Reject (409) — unabhängig vom Alter. Verwaiste Claims werden
   ausschließlich über die AG3-138-Wege beendet.
3. **`takeover_operation`-Pfad restlos entfernen:** Port
   (`repository.py:83`), Fassaden-Funktion (`facade.py:838`), Row-Funktion
   (`postgres_store.py:2332`) sowie die zugehörigen Einträge in
   `store/_public_api_names.py` / `store/__init__.pyi` (keine toten Exporte).
4. **Lease-Reste bereinigen, soweit sie ausschließlich das TTL-/
   Auto-Takeover-Modell stützten** (z. B. das Threading der Lease-Epoche
   `claimed_at_raw` für den Takeover-CAS, injizierbare Lease-Clock-Seams, die
   nur die Expiry testeten). `claimed_at` bleibt als Audit-Instant erhalten;
   das AG3-138-`operation_epoch`-CAS bleibt unberührt.
5. **Kommentare/Dokumentation im Code angleichen:** AG3-054-Lease-Wortlaut in
   `runtime.py`, `records.py`, `postgres_schema.sql` (:223-230) auf das
   instanzgebundene Claim-Modell umformulieren (keine DDL-Änderung nötig).
6. **Tests umbauen:** TTL-/Expiry-/Auto-Takeover-Tests entfernen bzw. durch
   Negativ-Pins ersetzen (`tests/unit/control_plane/test_runtime.py`):
   ein 10-Minuten-alter fremder Claim — der heute übernommen würde — wird
   jetzt deterministisch abgewiesen; kein Test hängt mehr an einer
   Wanduhr-Expiry.

### Out of Scope (mit Owner)

- **Startup-Rekonsiliierung / `admin_abort`** (der Ersatzmechanismus):
  **AG3-138** — Vorbedingung, hier nur konsumiert.
- **Expliziter Ownership-Transfer** (Challenge-Confirm als der offizielle
  Weg, einen aktiven Run zu übernehmen): **AG3-148**. Der Rückbau hier schafft
  bewusst KEINEN Ersatz-Übernahmepfad — bis AG3-148 gilt: fremde in-flight
  Claims enden nur administrativ.
- **Objekt-Serialisierung** (Claims pro Objekt statt pro op_id): **AG3-141**.
- **Konzept-Rückbauten von Block 11** (FK-10/15/71/93, formal.story-reset/-split
  etc.): bereits normativ erledigt (Commit 3ae011e4, KONZEPT-DONE) — diese
  Story ist ausschließlich die Code-Seite.
- **Betriebs-Runbook** (dokumentiert u. a. die Migrationsreihenfolge):
  **AG3-155**.

## Betroffene Dateien

| Datei | Änderungsart | Zweck |
|---|---|---|
| `src/agentkit/backend/control_plane/runtime.py` | ändern | `_CLAIM_LEASE_TTL` (:83), `_claim_is_expired` (:629-655), Takeover-Zweig in `_acquire_claim` (:534-627) entfernen; Kommentare angleichen |
| `src/agentkit/backend/control_plane/repository.py` | ändern | Port-Feld `takeover_operation` (:83) entfernen |
| `src/agentkit/backend/state_backend/store/facade.py` | ändern | `takeover_control_plane_operation_global` (:838) entfernen |
| `src/agentkit/backend/state_backend/store/_public_api_names.py`, `store/__init__.pyi` | ändern | Export-Bereinigung (keine toten Namen) |
| `src/agentkit/backend/state_backend/postgres_store.py` | ändern | `takeover_control_plane_operation_global_row` (:2332) entfernen |
| `src/agentkit/backend/control_plane/records.py` | ändern | Lease-Doku am `ControlPlaneOperationRecord` (:53-59) auf Instanzbindungs-Modell umformulieren |
| `src/agentkit/backend/state_backend/postgres_schema.sql` | ändern | Kommentarblock (:223-230) angleichen (kein DDL-Delta) |
| `tests/unit/control_plane/test_runtime.py` | ändern | TTL-/Takeover-Tests raus; Negativ-Pins rein (alter fremder Claim → Reject) |
| `tests/integration/**` | ändern/neu | End-to-End-Pin: verwaister Claim wird NICHT per Zeitablauf übernommen; AG3-138-Startup-Reconcile bleibt der Endweg |

## Akzeptanzkriterien

1. **Nullbestand:** `_CLAIM_LEASE_TTL`, `_claim_is_expired`,
   `takeover_operation`, `takeover_control_plane_operation_global` haben
   0 Treffer in `src/agentkit/` (Grep-Beleg im Review); keine toten Exporte in
   der Store-Public-API.
2. **Kein Zeit-Takeover:** ein fremder in-flight Claim beliebigen Alters
   (Test: deutlich älter als die frühere 5-Minuten-TTL) führt zum
   deterministischen in-flight-Reject (409) — die Mutation wird niemals
   automatisch übernommen (SOLL-110;
   `ownership_transfer_requires_explicit_confirmed_request` code-seitig).
3. **Endwege intakt:** der Integrationstest aus AG3-138 (Startup-
   Rekonsiliierung finalisiert verwaiste eigene Claims; `admin_abort` bricht
   ab) bleibt grün — der Rückbau hinterlässt keinen Zustand ohne
   Verwaisungs-Handling (IMPL-006).
4. **Keine Wanduhr-Semantik:** kein verbleibender Code-Pfad interpretiert
   `claimed_at` fachlich (nur Audit-Anzeige); die Test-Suite enthält keinen
   Expiry-Fall mehr.
5. **Fail-closed unverändert:** In-flight-Kollisionen, Claim-Kollisions-Fehler
   (`ControlPlaneClaimCollisionError`-Pfad) und das `operation_epoch`-CAS aus
   AG3-138 verhalten sich unverändert (Regressionstests grün).
6. Coverage ≥ 85 % gehalten (Rückbau senkt die Schwelle nicht unter das
   Limit); `mypy` strict (+ `--platform linux`), `ruff` clean; ARCH-55.

## Definition of Done

- Alle Akzeptanzkriterien erfüllt; Gate-Suite grün (`pytest -n0`
  unit/integration/contract, Coverage ≥ 85, `mypy src` + `--platform linux`,
  `ruff`, 4 Konzept-Gates).
- Codex-Review PASS.
- Auf `origin/main` gemerged; `status.yaml` → `completed` (entsperrt AG3-155);
  README-Backlog-Snapshot (§6.7) nachgezogen.

## Abdeckung (Traceability)

**Deckt ab:** SOLL-110 (Code-Seite von Block 11); IMPL-006 (Reihenfolge).

## Konzept-Referenzen

- `formal.operating-modes.invariants` →
  `operating-modes.invariant.ownership_transfer_requires_explicit_confirmed_request`
  (Owner-Wechsel nie durch Timeout/Lease/Heartbeat/Stille)
- FK-91 §91.1a Regel 16 (In-Flight-Claims enden **niemals** durch Wanduhr,
  TTL oder Lease-Ablauf; nur Start-Rekonsiliierung oder `admin_abort`)
- FK-10 §10.5.4 („Kein Lease, kein TTL, keine PID-Heuristik"), §10.6.1
  (kein automatischer Entzug; Stale-Anzeige ist Information, keine Diagnose)
- FK-02 §2.6 (Invariantenzeile: „Ownership endet nie automatisch")

## Guardrail-Referenzen

- **FIX THE MODEL, NOT THE SYMPTOM:** Das TTL-Modell wird ersatzlos entfernt,
  nicht „konfigurierbar" gemacht oder auf einen großen Wert gestellt — die
  Wanduhr verschwindet als Konzept aus dem Claim-Lebenszyklus.
- **NO ERROR BYPASSING:** Kein versteckter Fallback, der bei „hängenden"
  Claims doch wieder automatisch freiräumt; blockierte Mutationen werden
  administrativ (AG3-138) oder per explizitem Transfer (später AG3-148)
  aufgelöst.
- **ZERO DEBT:** Rückbau restlos inklusive Ports, Fassade, Row-Funktion,
  Exporten, Kommentaren und Tests — keine tote Lease-Terminologie im Code.
- **Konzepttreue:** Die Reihenfolge-Invariante (erst AG3-138, dann diese
  Story) ist verbindlich; ein Start vor AG3-138-`completed` verstößt gegen
  `depends_on` (autoritativ, stories/README.md §2.1).

## Querschnitts-Auflagen

- **Kritische Kante ST-02 → ST-03 (Auflage §3, hier begründet):** Die TTL ist
  bis AG3-138 das einzige Verwaisungs-Handling (IMPL-006, gap-03 W2.5/W5.5).
  Diese Story darf erst nach AG3-138-`completed` gezogen werden; das Briefing
  beider Stories dokumentiert die Reihenfolge. Es gibt keinen
  Zwischen-Deployment-Zustand ohne Verwaisungs-Handling.
- **K5 Postgres-only:** betroffen ist ausschließlich der Postgres-Pfad der
  Control-Plane-Claims; es entsteht keine neue Tabelle und kein
  SQLite-Spiegel. Tests über Postgres-Fixture bzw. Ports/Fakes.
- **Blutgruppen-Klassifikation:** Reiner Rückbau — es entstehen keine neuen
  Module; die angepasste Claim-Entscheidungslogik in `runtime.py` bleibt **A**,
  die entfernten Row-Funktionen waren **T** (Bereinigung in `state_backend`
  lokalisiert).
- **Bundle-Assets:** Keine betroffen (verifiziert: TTL-/Takeover-Mechanik ist
  rein serverseitig; `bundles/target_project/**` referenziert sie nicht).
