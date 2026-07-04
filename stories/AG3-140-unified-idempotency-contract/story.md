# AG3-140 — Einheitlicher Idempotenz-Vertrag (BC-weit): Client-op_id-Pflicht + In-Flight-Schutz + Body-Hash überall

- **Typ:** implementation
- **Größe:** L
- **depends_on:** [AG3-137] — die Vereinheitlichung konsolidiert den
  In-Flight-Schutz auf die `inflight-operation-record`-Persistenz
  (erweiterte `control_plane_operations`-Spalten inkl.
  `declared_serialization_scope`/`finalized_at`), die AG3-137 anlegt
  (GAP §4: ST-01 → ST-04).
- **Quell-Konzept:** FK-91 §91.1a Regel 5 (client-beigestelltes `op_id`, EIN
  einheitlicher Vertrag), Regel 12 (Guard-Counter-Pfad vollständig unter dem
  Vertrag); `formal.story-workflow.commands` (run-phase/resume:
  „op_id is the client-supplied idempotency key" — op_id-Vertragsanteil)
- **Herkunft:** GAP-Analyse Session-Ownership v4 (`_temp/gap-analyse-session-ownership.md`),
  Story-Kandidat GAP-ST-04; normative Basis Commits 3ae011e4 / 1bb4ed8a / 58c190b7
  (+ Decision-Records unter `concept/_meta/decisions/`).

## Kontext / Problem

FK-91 §91.1a Regel 5 fordert: `op_id` ist **client-beigestellt** (serverseitiges
Minten macht Retries blind — der Client kann eine unklare Mutation nicht mehr
rekonsiliieren) und es gilt **EIN** einheitlicher Idempotenz-Vertrag (Replay →
gespeichertes Ergebnis; Body-Abweichung → `409 idempotency_mismatch`;
parallele gleiche `op_id` → in-flight abgewiesen/serialisiert). Der Ist-Zustand
verletzt beides mehrfach (am Code verifiziert 2026-07-02):

**Serverseitiges op_id-Minten via `default_factory` (11 Stellen + Varianten):**

- `control_plane/models.py:242, :267, :324` — die Kern-Requests! (:324 ist der
  `PhaseMutationRequest`-Pfad: lässt der Client `op_id` weg, mintet der Server
  still) — plus `:75-76` (`gc-{uuid4}`-Default am
  `GuardCounterMutationRequest`; laut Doku „hook-side" gemintet, aber der
  Default greift auch beim serverseitigen Parsen eines Bodys ohne `op_id`)
- `project_management/http/routes.py:77, :89, :97` + expliziter Mint `:366`
- `auth/http/routes.py:59, :67`
- `execution_planning/http/routes.py:90, :100`
- `failure_corpus/story_creation_adapter.py:81` (`fc-check-story-…`-Mint)

**task_management-POSTs haben GAR KEIN `op_id`** (Review-Fund E1, verifiziert):
`task_management/http/routes.py` enthält keinerlei `op_id` — die 5 mutierenden
Routen (create :116/`_CreateTaskRequest` :115-131, resolve/dismiss
:134-139/`_handle_resolve_task` :609, links/links-delete :142-152) sind
komplett ohne Idempotenzschutz.

**Zwei (real drei) getrennte Mechanismen mit unterschiedlicher Schutztiefe:**

1. Claim-basiert **mit** In-Flight-Schutz (Control-Plane-Operationen,
   `control_plane/runtime.py`).
2. check-then-record **ohne** In-Flight-Schutz
   (`story_context_manager/idempotency.py`: `check` :135 / `record` :170,
   Body-Hash :29; das dokumentierte Muster „Mutation vor Record" :123-128
   lässt ein Crash-Fenster zwischen Mutation und Idempotenz-Eintrag — real an
   6 Stellen in `story_context_manager/service.py`
   374/428, 479/519, 631/660, 809/846, 919/956, 1024/1051; Tabelle
   `idempotency_keys` ohne In-Flight-Feld,
   `state_backend/postgres_schema.sql:777-784`).
3. Guard-Counter (`control_plane/guard_counter.py:114, :134-145`): atomar in
   einer Transaktion (gut), aber ebenfalls ohne In-Flight-Schutz gegen
   parallele gleiche `op_id`.

**Vertragskonforme Client-Seite existiert bereits** (Vorbild, nicht Baustelle):
Frontend mintet client-seitig (`frontend/app/api.ts` `makeOpId()` :225,
verwendet :132/:147); `harness_client/projectedge/client.py` nimmt `op_id` als
Aufrufer-Parameter (:562); das Bundle-Asset
`bundles/target_project/tools/agentkit/projectedge.py` mintet client-seitig
(`args.op_id or f"op-{uuid4.hex}"` :228).

## Scope

### In Scope

1. **Client-op_id-Pflicht (SOLL-045):** Alle `default_factory`-Mints und
   expliziten Server-Mints an mutierenden Wire-Modellen entfernen (vollständige
   Liste oben; inkl. `control_plane/models.py:242/267/324`, `:75-76`,
   `project_management/http/routes.py:366`,
   `failure_corpus/story_creation_adapter.py:81` — letzterer ist ein
   interner Aufrufer und mintet künftig als **Client** vor dem Service-Call,
   nicht im Wire-Modell-Default). `op_id` wird Pflichtfeld ohne Default
   (`min_length=1`); ein Request ohne `op_id` ist fail-closed `422`.
2. **task_management unter den Vertrag:** alle 5 mutierenden POST-Routen
   (create/resolve/dismiss/link/unlink) akzeptieren verpflichtend `op_id` und
   erfüllen den vollen Vertrag (Replay/Body-Hash/In-Flight-Schutz).
3. **EIN Mechanismus (SOLL-046):** Body-Hash-Prüfung **und** In-Flight-Schutz
   gelten überall. Der `idempotency_keys`-Pfad wird entweder (a) auf den
   `inflight-operation-record` (AG3-137) konsolidiert oder (b) um einen
   In-Flight-Zustand + atomare Claim-Semantik erweitert — Designentscheidung
   im Execution-Plan; zwei Mechanismen unterschiedlicher Schutztiefe sind
   Endzustand-unzulässig. Das „Mutation-vor-Record"-Crash-Fenster in
   `story_context_manager/service.py` (6 Stellen) wird geschlossen
   (claim → mutate → finalize).
4. **Guard-Counter-Pfad (SOLL-047, Regel 12):** client-`op_id` (Hook mintet),
   Body-Hash (bleibt) **plus** In-Flight-Schutz; die atomare
   Ein-Transaktions-Garantie (Increment + Idempotenz-Eintrag) bleibt erhalten.
5. **Pflicht-Inventar ALLER mutierenden BC-Routen** (Querschnitts-Auflage):
   vollständige, belegte Route-für-Route-Tabelle
   (Route → Mechanismus → Nachweis) für: `story_context_manager`,
   `project_management`, `execution_planning`, `task_management`,
   `governance/guard-counter` (`POST /v1/governance/guard-counters`), `auth`,
   `control_plane`/project-edge (phases start/complete/fail/resume,
   closure/complete, project-edge sync, story-creation). Dokumentierte
   Konzept-Ausnahme: `POST /v1/governance/worker-health` ist idempotenter
   Upsert ohne `op_id` (FK-91-Endpoint-Tabelle) — explizit ausweisen, nicht
   stillschweigend überspringen. **`kpi_analytics` + `concept_catalog` als
   read-only verifizieren** (Ist-Befund: `kpi_analytics/http/routes.py:177-183`
   „KPI surface is read-only"; `concept_catalog/http` ohne POST-Handler — im
   Zuge der Story erneut belegen).
6. **`formal.story-workflow`-op_id-Vertragsanteil (SOLL-056/057,
   op_id-Anteil):** der Code erfüllt den formalen Wortlaut „op_id is the
   client-supplied idempotency key" für run-phase und „reserved by the SAME
   in-flight operation claim" für resume — d. h. der Resume-Replay derselben
   `op_id` liefert das gespeicherte Ergebnis, eine parallele gleiche `op_id`
   wird in-flight abgewiesen. (Die **Objekt**-Serialisierung dieser Commands
   ist AG3-141.)
7. **Bundle-Asset-Scope (Auflage):**
   `bundles/target_project/tools/agentkit/projectedge.py` prüfen und
   ausweisen: client-seitiges Minten (:228) ist vertragskonform (Regel 5) und
   bleibt; sicherstellen, dass **alle** mutierenden Kommandos des Tools ein
   `op_id` mitsenden (kein Kommando verlässt sich auf Server-Defaults, die es
   nach dieser Story nicht mehr gibt). Frontend `api.ts` und
   `harness_client/projectedge/client.py` analog verifizieren (heute bereits
   konform).

### Out of Scope (mit Owner)

- **Serialisierungs-Anteil von SOLL-056/057** — per-Story-Objekt-Claims vor
  Dispatch, Warte-Semantik: **AG3-141**.
- **Instanzbindung der Claims, Startup-Rekonsiliierung, `admin_abort`**:
  **AG3-138**.
- **TTL-Rückbau**: **AG3-139**.
- **Ownership-/Epoch-Fencing der Regime-Pfade**: **AG3-142**.
- **202-Job-Muster / Ergebnisarten / `stale_observation`** (Regeln 14/15):
  **AG3-144**.

## Betroffene Dateien

| Datei | Änderungsart | Zweck |
|---|---|---|
| `src/agentkit/backend/control_plane/models.py` | ändern | `op_id`-Defaults raus (:75-76, :242, :267, :324) → Pflichtfeld |
| `src/agentkit/backend/project_management/http/routes.py` | ändern | Defaults :77/:89/:97 raus; expliziter Mint :366 raus |
| `src/agentkit/backend/auth/http/routes.py` | ändern | Defaults :59/:67 raus |
| `src/agentkit/backend/execution_planning/http/routes.py` | ändern | Defaults :90/:100 raus |
| `src/agentkit/backend/failure_corpus/story_creation_adapter.py` | ändern | Mint (:81) bleibt, wird aber explizit als Client-Mint des Aufrufers geführt (kein Wire-Default) |
| `src/agentkit/backend/task_management/http/routes.py` + `task_management/service.py` | ändern | `op_id`-Pflicht + voller Idempotenz-Vertrag auf allen 5 mutierenden Routen |
| `src/agentkit/backend/story_context_manager/idempotency.py` + `service.py` | ändern | In-Flight-Schutz; check-then-record-Fenster schließen (6 Stellen); ggf. Konsolidierung auf `inflight-operation-record` |
| `src/agentkit/backend/control_plane/guard_counter.py` | ändern | In-Flight-Schutz ergänzen (atomare TX bleibt) |
| `src/agentkit/backend/state_backend/postgres_schema.sql` + `postgres_store.py` | ändern | `idempotency_keys` (:777-784) um In-Flight-Zustand erweitern ODER Konsolidierungspfad (additive Migration) |
| `src/agentkit/backend/control_plane_http/app.py` | ändern | einheitliche 422-/409-Fehlerform (`idempotency_mismatch`, in-flight-Reject) über alle gehosteten BC-Router |
| `src/agentkit/frontend/app/api.ts` | prüfen/ggf. ändern | Client-Mint für ALLE mutierenden Calls (heute :132/:147 konform) |
| `src/agentkit/harness_client/projectedge/client.py` | prüfen/ggf. ändern | `op_id` bleibt Aufrufer-Pflicht (:562) |
| `src/agentkit/bundles/target_project/tools/agentkit/projectedge.py` | prüfen/ggf. ändern | Bundle-Asset: client-seitiges Minten für alle mutierenden Kommandos ausweisen (:228) |
| `tests/unit/**`, `tests/integration/**`, `tests/contract/**` | neu/ändern | Vertrags-Tests je Route (Replay/Mismatch/In-Flight/fehlendes op_id); Regressions-Grep-Pin gegen Server-Mints |

## Akzeptanzkriterien

1. **Kein Server-Mint:** `default_factory`-op_id-Mints in
   `src/agentkit/backend` = 0 Treffer (Grep-Pin als Test/Review-Beleg);
   mutierende Requests ohne `op_id` werden fail-closed mit `422` abgewiesen —
   kein stilles Minten, keine Ausnahme.
2. **task_management vollständig:** alle 5 mutierenden Routen beweisen per
   Test: Replay derselben `op_id` → gespeichertes Ergebnis ohne zweite
   Mutation; gleicher `op_id` mit abweichendem Body → `409
   idempotency_mismatch`; parallele gleiche `op_id` → in-flight
   abgewiesen/serialisiert (Concurrency-Test).
3. **Ein Vertrag überall:** kein mutierender Endpoint verbleibt mit
   check-then-record ohne In-Flight-Schutz; das Crash-Fenster
   „Mutation committed, Record fehlt" ist geschlossen (Test: Crash-Simulation
   zwischen Mutation und Finalize hinterlässt keinen doppelt ausführbaren
   Zustand — reproduzierender Negativtest an der Servicegrenze).
4. **Guard-Counter:** Regel-12-Pfad erfüllt den vollen Vertrag inkl.
   In-Flight-Schutz; exactly-once pro `op_id` bleibt (bestehende
   Atomicity-Tests grün).
5. **Inventar belegt:** die Route-Inventar-Tabelle liegt als
   Story-Artefakt/Execution-Plan-Anhang vor; jede mutierende Route hat einen
   Mechanismus-Nachweis (Test-Name); `kpi_analytics`/`concept_catalog` sind
   als read-only belegt; die worker-health-Upsert-Ausnahme ist mit
   FK-91-Referenz dokumentiert.
6. **Clients konform:** Frontend, `ProjectEdgeClient` und Bundle-Asset
   `projectedge.py` senden für jede Mutation ein client-gemintetes `op_id`
   (Tests/Static-Pins); das Bundle-Asset-Verhalten ist im Story-Ergebnis
   explizit ausgewiesen (Auflage Bundle-Assets).
7. **formal-Konformität:** run-phase/resume erfüllen den op_id-Wortlaut der
   `formal.story-workflow.commands` (client-supplied; Replay liefert
   gespeichertes Ergebnis; parallele gleiche op_id in-flight abgewiesen) —
   Contract-Tests pinnen die Antwortformen.
8. **Negativpfade an Phasengrenzen:** fehlendes `op_id`, Body-Mismatch,
   Replay nach Erfolg, Replay nach Fehlschlag, parallele gleiche `op_id` —
   je Route mindestens der einschlägige Negativtest (testing-guardrails).
9. Coverage ≥ 85 %, `mypy` strict (+ `--platform linux`), `ruff`, ARCH-55
   (englische `error_code`s/Wire-Keys).

## Definition of Done

- Alle Akzeptanzkriterien erfüllt; Gate-Suite grün (`pytest -n0`
  unit/integration/contract, Coverage ≥ 85, `mypy src` + `--platform linux`,
  `ruff`, 4 Konzept-Gates).
- Codex-Review PASS.
- Auf `origin/main` gemerged; `status.yaml` → `completed`;
  README-Backlog-Snapshot (§6.7) nachgezogen.

## Abdeckung (Traceability)

**Deckt ab:** SOLL-045–047, SOLL-056 (op_id-Vertragsanteil), SOLL-057 (op_id-Vertragsanteil).

## Konzept-Referenzen

- FK-91 §91.1a Regel 5 (client-beigestelltes `op_id`; EIN einheitlicher
  Vertrag: Replay, Body-Hash-`409 idempotency_mismatch`, In-Flight-Schutz;
  „zwei getrennte Mechanismen mit unterschiedlicher Schutztiefe sind
  unzulässig"), Regel 12 (Guard-Counter-Pfad vollständig unter Regel 5),
  Regel 17 (Reconcile unklarer Mutationen via
  `GET /v1/project-edge/operations/{op_id}` — der Grund, warum Server-Minten
  Retries blind macht)
- `formal.story-workflow.commands` → run-phase-Zeile („op_id is the
  client-supplied idempotency key (an in-flight operation claim …); a replay
  returns the stored result") und resume-Zeile („reserved by the SAME
  in-flight operation claim") — **op_id-Vertragsanteil**
- `formal.state-storage.entities` → `state-storage.entity.inflight-operation-record`
  (Konsolidierungsziel aus AG3-137)

## Guardrail-Referenzen

- **FAIL-CLOSED:** fehlendes `op_id` ist `422`, Body-Mismatch ist `409` — kein
  weicher Fallback auf „mintet halt der Server".
- **FIX THE MODEL, NOT THE SYMPTOM:** nicht drei Mechanismen härten, sondern
  auf EINEN Vertrag konsolidieren; das Mutation-vor-Record-Fenster wird im
  Modell geschlossen, nicht mit Retries kaschiert.
- **SINGLE SOURCE OF TRUTH:** ein Idempotenz-Mechanismus, eine
  Record-Wahrheit; keine parallele Schutztiefe je BC.
- **NO ERROR BYPASSING:** kein Endpoint wird „übergangsweise" vom Vertrag
  ausgenommen; die einzige Ausnahme (worker-health-Upsert) ist konzeptseitig
  normiert und wird zitiert, nicht erfunden.
- **ZERO DEBT:** das Pflicht-Inventar erzwingt Vollständigkeit — keine stille
  Restlücke à la task_management noch einmal.

## Querschnitts-Auflagen

- **K5 Postgres-only:** Erweiterungen an `idempotency_keys` bzw. die
  Konsolidierung auf den `inflight-operation-record` folgen der
  Postgres-only-Festlegung der Control-Plane-Tabellen (fail-closed,
  `_require_postgres_control_plane_backend`, `control_plane/runtime.py:2119`);
  kein SQLite-Spiegel. Tests: Postgres-Fixture für Integration/Contract,
  Ports/Fakes für Unit.
- **Blutgruppen-Klassifikation:** Vertragslogik (Claim-/Replay-/
  Mismatch-Entscheidung) = **A**; Wire-Modell-Anpassungen der Routen = **R**;
  Persistenz der In-Flight-/Idempotenz-Records = **AT** (lokalisiert in
  `state_backend`); keine neuen 0-Utilities erwartet.
- **Bundle-Assets (Pflicht-Auflage für diese Story):** Scope ist explizit
  deklariert — `bundles/target_project/tools/agentkit/projectedge.py` wird
  geprüft und als vertragskonformer client-seitiger Minter ausgewiesen bzw.
  minimal nachgezogen, falls ein mutierendes Kommando ohne `op_id` sendet.
  Keine weiteren Bundle-Assets betroffen (verifiziert: kein anderes Asset
  spricht mutierende `/v1`-Routen).
