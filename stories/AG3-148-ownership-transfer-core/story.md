# AG3-148 — Transfer-Kern: `takeover-request`/`takeover-confirm` (Challenge-Confirm-CAS), persistente Approval-Queue, `pending_human_approval`, atomarer Vollzug mit `takeover_base_sha`

- **Typ:** implementation
- **Größe:** L
- **depends_on:** [AG3-141, AG3-142, AG3-147]
  - **AG3-141** — der Transfer/Confirm ist **selbst eine story-serialisierte
    Mutation** (FK-56 §56.13 Grundsatz 4): er wird hinter laufenden Mutationen
    derselben Story serialisiert und wirkt dadurch als Fence; die durable
    Story-Claim-Maschinerie entsteht in AG3-141 (GAP §4: „ST-07a ← zusätzlich
    ST-05").
  - **AG3-142** — der Confirm ist ein CAS auf den aktiven
    `run_ownership_records`-Eintrag (`ownership_epoch+1`), und die Entmündigung
    des Ex-Owners wirkt nur, weil ALLE Regime-Pfade gegen
    `owner_session_id`/`ownership_epoch` fencen; Record-Schreiben im Setup,
    Fence-Fläche und `ownership_transferred`-Fehlerbild entstehen in AG3-142
    (GAP §4: ST-06 → ST-07a).
  - **AG3-147** — der Challenge braucht **Push-Frische und
    Branch-Ref-Meldungen**; `takeover_base_sha` wird aus den gemeldeten,
    serverseitig verifizierten Pushes materialisiert (GAP §4: „ST-07a ← ST-15:
    Challenge braucht Push-Frische/Branch-Ref-Meldungen; base_sha aus
    gemeldeten Pushes").
- **Quell-Konzept:** FK-56 §56.13 (Grundsätze 1–4), §56.13a
  (Challenge-Confirm-Protokoll), §56.13b (Berechtigung + menschliche
  Frontend-Freigabe), §56.13c (atomarer Vollzug, Transfer-Record, Immobilität,
  Verlustkorridor-Pflichttext), §56.13e (worktree_roots-Rebinding — Signaturbezug);
  FK-91 §91.1a Endpoint-Tabelle (`takeover-request`/`takeover-confirm`),
  §91.8 Topic-Tabelle (governance-Zeile, `takeover_approval_changed`);
  FK-55 §55.5 (op-class `admin_transition` um Ownership-Transfer-Confirm
  erweitert); `formal.operating-modes.commands`
  (`request-run-ownership-takeover`, `confirm-run-ownership-takeover`),
  `.events` (vier Takeover-Events), `.invariants`
  (`ownership_transfer_requires_explicit_confirmed_request`,
  `agent_initiated_takeover_requires_human_frontend_approval`,
  `takeover_confirm_fences_in_flight_mutations`);
  `formal.state-storage.entities` → `state-storage.entity.takeover-transfer-record`
- **Herkunft:** GAP-Analyse Session-Ownership v4 (`_temp/gap-analyse-session-ownership.md`),
  Story-Kandidat GAP-ST-07a; normative Basis Commits 3ae011e4 / 1bb4ed8a / 58c190b7
  (+ Decision-Records unter `concept/_meta/decisions/`).

## Kontext / Problem

FK-56 §56.13 normiert den einzigen Weg, einen aktiven Run unter neuem Owner
fortzuführen: den expliziten, zweistufigen, CAS-gesicherten Ownership-Transfer
mit menschlicher Frontend-Freigabe bei agenteninitiiertem Request. Im Code
existiert **kein einziger** takeover-spezifischer Träger (am Code verifiziert
2026-07-02):

- **Keine Endpoints, keine Statusform, kein Fehlerbild:** Grep
  `takeover-request|takeover-confirm|pending_human_approval|ownership_transferred`
  über `src/agentkit/`: null Wire-Treffer. Die einzigen „takeover"-Fundstellen
  sind der **TTL-Lease-CAS des per-op_id-Claims**
  (`control_plane/runtime.py:556-621`, `takeover_operation` :616) — exakt das
  Modell, das der Strang ersetzt (Rückbau: AG3-139).
- **`pending_human_approval` passt in keine bestehende Antwortform** (IMPL-010):
  die Phase-Mutation-Handler mappen ausschließlich `rejected → 409`, sonst
  `201` (`control_plane_http/app.py:1191-1200`); eine dritte, ausstehende
  Statusform mit op_id-Beobachtbarkeit existiert nicht.
- **Keine persistente Approval-Queue** (IMPL-011): das einzige
  Freigabe-Substrat ist die `PermissionLease` — ausdrücklich session-scoped,
  SQLite, „a restart clears all leases"
  (`governance/ccag/leases.py:8-9`). Für eine neustart-feste,
  benutzerübergreifende Takeover-Freigabe ist sie unbrauchbar; sie bleibt als
  Vorbild für Verfall-Semantik (Entscheidungs-Verfall, nie Ownership-Entzug).
- **Keine HTTP-seitige Principal-Attestierung der Ownership-Endpoints**
  (IMPL-018): `admin_transition` existiert nur an der Hook-/Tool-Kante
  (`governance/principal_capabilities/matrix_data.py:103/:146`,
  `enforcement.py:404-445`); die `AuthMiddleware`
  (`auth/middleware.py:50`) ist Session-/CSRF-Mechanik ohne
  Unterscheidung „agenteninitiiert vs. menschliche Frontend-Freigabe".
- **Kein abfragbarer Challenge-/Historien-Datenpfad aus dem Owner-BC**
  (IMPL-022): es gibt keine Query „Eigentumslage + offene Jobs +
  Takeover-Historie" — die Owner-Daten liegen verstreut (Binding, Operationen,
  ab AG3-137 der Ownership-Record, ab AG3-147 die Push-Frische). Die
  Lifecycle-Event-Mechanik trägt als Muster
  (`_lifecycle_event_record`, `control_plane/runtime.py:1575` ff.;
  Tabelle `execution_events`, `state_backend/postgres_schema.sql:161`).
- **Fundamente liegen bereit:** `takeover_transfer_records` und die
  Ownership-/Binding-Repositories aus AG3-137 (bis hierhin unbefüllt);
  Fence-Fläche + `ownership_transferred`-Payload aus AG3-142; Story-Claims aus
  AG3-141; Push-Frische-Lesefläche + serverseitige Ref-Verifikation aus
  AG3-147; Edge-Tombstone-Mechanik (`runtime.py:1573`,
  `harness_client/projectedge/client.py:380-383`).
- **Ist-Divergenz zu gap-02 (Code gewinnt):** das projekt-skopierte
  SSE-Topic-Vokabular enthält inzwischen `governance`
  (`telemetry/sse_stream.py:20/:35`) — gap-02 nannte nur
  `stories,phases,planning,telemetry,coverage`. SOLL-043 ist damit
  Topic-**Inhalts**-Erweiterung (ausstehende Takeover-Freigaben +
  `takeover_approval_changed`), kein neues Topic.

Ohne diese Story bleibt die einzige Antwort auf eine festgefahrene fremde
Session destruktiv (Exit/Reset), und AG3-149 (Disown/Ping-Pong), AG3-151
(Reconcile), AG3-153 (Overlay/Cockpit) und AG3-154 (CLI/Edge-Tool) haben
keinen Transfer, an den sie andocken.

## Scope

### In Scope

1. **Endpoint `POST /v1/project-edge/story-runs/{run_id}/ownership/takeover-request`**
   (SOLL-023, SOLL-040): formal `request-run-ownership-takeover`
   (allowed_statuses `ai_augmented`/`unresolved`). Antwortvarianten:
   menschlich initiiert (`human_cli`/UI via BFF) → versionierter **Challenge**
   (`offered`); agenteninitiiert → deterministisch **`pending_human_approval`**.
   Anfrage offen für `human_cli`/`admin_service` und Agents
   (`interactive_agent`/`orchestrator`) über den offiziellen Project-Edge-Pfad
   (SOLL-030-Anfrage-Anteil). **Begründungspflicht:** freies, auditiertes
   Begründungsfeld ist Pflicht (SOLL-026). Client-beigestelltes `op_id`
   (Regel 5, kein `default_factory`-Minting), Serialisierungsobjekt
   `(project_key, story_id)` über die AG3-141-Claims. Emittiert
   `run_ownership_takeover_offered` bzw.
   `run_ownership_takeover_approval_requested` (SOLL-039-Anteil). Der neue
   Übergang `story_execution(A) → story_execution(B)` existiert damit als
   offizieller Pfad (SOLL-022); Owner wechselt **nur** durch Challenge-Confirm,
   offiziellen Endpfad oder Recovery — es gibt keinerlei Codepfad von
   Timeout/Lease/Heartbeat/Stille zu einem Transfer (SOLL-029).
2. **Challenge-Assembler + Historien-Query aus dem Owner-BC** (SOLL-025,
   IMPL-022): der Challenge versioniert die Entscheidungsgrundlage —
   mindestens `owner_session_id`, `ownership_epoch`, `binding_version`,
   Phasenstand, Anzeigedaten (Principal, gebunden seit, letzter API-Kontakt
   MIT Nicht-Diagnose-Hinweis, offene Jobs/`op_id`s, bisherige
   Takeover-Historie) — gelesen aus dem Owner-BC (Ownership-Record, Binding,
   `control_plane_operations`, Transfer-Historie), **nicht** aus
   nachlaufenden Read-Models. Je teilnehmendem Repo zeigt der Challenge den
   **Kandidaten-SHA + Push-Frische** aus der AG3-147-Lesefläche VOR der
   Entscheidung (SOLL-150-Challenge-Anteil). Der
   **Verlustkorridor-Pflichttext** (pushed-only: „Übernommen wird
   ausschließlich der gepushte Stand `<sha>`; nicht gepushte Commits,
   uncommittete Änderungen und untracked Dateien werden nicht übertragen …")
   ist fester, maschinenlesbar adressierbarer Challenge-Bestandteil
   (SOLL-151; die Overlay-/UI-Anzeige liegt in AG3-153).
3. **Challenge-Befristung als Entscheidungs-Verfall** (SOLL-028): ein
   Challenge darf befristet sein; der Verfall lässt ausschließlich die offene
   Anfrage verfallen und entzieht **niemals** Ownership.
4. **Persistente, verfallbare, benutzerübergreifende Approval-Queue**
   (SOLL-031, IMPL-011): neue Postgres-only-Tabelle (K5) für ausstehende
   Takeover-Freigaben (Identität `approval_id`; Projekt/Story/Run,
   anfragender Principal, Begründung, Challenge-Referenz, Status
   `pending|approved|denied|expired`, `requested_at`, `expires_at`).
   Neustart-fest; **nicht an einen Benutzer gebunden** — jeder eingeloggte
   Benutzer kann entscheiden. Verfall (`expired`) folgt der
   Permission-Request-Familie: DENIED-artiger Ausgang der Anfrage, nie
   Ownership-Wirkung.
5. **Statusform `pending_human_approval`** (SOLL-031, IMPL-010): typisierte
   Response-Form + HTTP-Mapping für den agenteninitiierten Request, mit der
   expliziten Information, dass ein Benutzer im Frontend freigeben muss; der
   Agent beobachtet den Ausgang über `GET /v1/project-edge/operations/{op_id}`
   (`challenge_reissued` → frische Challenge erneut bestätigen; erst der
   zweite Confirm liefert das Vollzug-Ergebnis; denied/expired →
   deterministischer terminaler Ausgang).
6. **Endpoint `POST /v1/project-edge/story-runs/{run_id}/ownership/takeover-confirm`**
   (SOLL-024, SOLL-027, SOLL-041): formal `confirm-run-ownership-takeover`
   mit `challenge_id` als einzigem Selektor; **serverseitiger CAS auf
   `owner_session_id`/`ownership_epoch`/`binding_version` der gespeicherten
   Challenge**. Jede
   zwischenzeitliche Änderung der Eigentumslage (Transfer, Exit, Reset,
   Split, Closure) invalidiert offene Challenges; von zwei konkurrierenden
   Confirms gewinnt deterministisch genau einer, der zweite scheitert
   fail-closed am veralteten Challenge (kein Vollzug, erneuter Request
   nötig). Der Vollzug wird als Operation der Klasse `admin_transition`
   geführt und vollständig auditiert (**SOLL-038, Transfer-Anteil** — der
   `admin_abort`-Anteil liegt in AG3-138).
7. **HTTP-Attestierung des Confirms** (SOLL-030-Vollzug-Anteil, IMPL-018):
   der Vollzug des Entmündigens einer fremden aktiven Session erfordert
   einen menschlich attestierten Principal — die Frontend-Freigabe
   (authentifizierte BFF-Session, AuthMiddleware-Kontext) bzw.
   `human_cli`/`admin_service`. Ein Agent kann den Confirm **nie** selbst
   vollziehen; agenteninitiierte Requests werden ausschließlich über den
   Approval-Queue-Weg wirksam (fail-closed 403 bei direktem
   Agent-Confirm-Versuch).
8. **Atomarer Vollzug** (SOLL-032; K1-Präzisierung SOLL-148/149/152): in
   **einer** Transaktion —
   - Ownership-Record-CAS auf B: `ownership_epoch + 1`,
     `acquired_via='takeover'`, `owner_session_id` = B;
   - A's Bindung revoked mit Grund `ownership_transferred`
     (Vokabular aus AG3-137, Fehlerbild-Wirkung aus AG3-142);
   - neue Bindung für B: **gleicher `run_id`**, neue monotone
     `binding_version`; die `worktree_roots` der neuen Bindung sind die
     **Edge-gemeldeten** Roots der neuen Session (Rebinding, SOLL-148/152 —
     das Backend leitet keine Pfade ab; die Meldung kommt über die
     AG3-145-`worktree_report`-Fläche);
   - Edge-Tombstone für A's lokales Bundle (bestehende
     `tombstone_worktree_roots`-Mechanik);
   - story-scoped Admission-Blocker `takeover_reconcile_required` gesetzt
     (Scope-Punkt 11);
   - **Transfer-Record materialisiert** (SOLL-149): je teilnehmendem Repo
     `takeover_base_sha` (der zu diesem Zeitpunkt gemeldete, serverseitig
     verifizierte **gepushte** Head aus AG3-147), `last_push_at`,
     `push_lag_hint`, `base_quality`, `challenge_ref`/`confirm_ref` — in
     `takeover_transfer_records` (AG3-137). **Per SOLL-147/ST-01 ist das ein
     Transfer-Record, KEIN Snapshot**: keine Binär-Diffs, keine
     Untracked-Manifeste, kein Dateizustand als Übergabegut.
   - Emittiert `session_run_binding_transferred` + `session_disowned`
     (SOLL-039-Anteil).
9. **Immobilität des Übergabeobjekts** (SOLL-150): ein
   **Pre-Confirm-Refresh** (Anfrage an A's Edge, den aktuellen Stand zu
   pushen) ist optional zulässig — bounded, best-effort, NUR vor der
   Entscheidung; **nach dem Confirm ändert kein A-Push mehr das
   Übergabeobjekt** (der Transfer-Record ist immutabel; Remote-Divergenz
   danach ist der AG3-151-Zustand `remote_branch_diverged_after_takeover`).
10. **Events + governance-Topic** (SOLL-039, SOLL-043): die vier Events
    `run_ownership_takeover_offered`, `run_ownership_takeover_approval_requested`,
    `session_run_binding_transferred`, `session_disowned` über die
    Lifecycle-Event-Mechanik (Wire-Schemas `operating-modes.event.*`); das
    projekt-skopierte governance-Topic liefert ausstehende
    Takeover-Freigaben und das Event `takeover_approval_changed`
    (Wire-Schema `frontend-contracts.event.takeover_approval_changed`) bei
    jedem Statuswechsel der Approval.
11. **Minimaler story-scoped Admission-Blocker `takeover_reconcile_required`:**
    wird im atomaren Vollzug (Scope-Punkt 8) mitgesetzt; alle
    Regime-Mutationspfade der Story bleiben danach fail-closed blockiert
    (409, maschinenlesbarer Grund `takeover_reconcile_required`), bis ein
    Reconcile-Abschluss gemeldet wird. Bis AG3-151 den vollen
    Reconcile-Contract liefert, ist die einzige Auflösung der auditierte
    Admin-Weg. AG3-151 baut Contract, Quarantäne, Reprovisionierung und
    die übrigen Zustände und übernimmt den Blocker in die
    Guard-/Bundle-Sync-Fläche.

### Out of Scope (mit Owner)

- **Ping-Pong-Schranke** (`disowned_session_cannot_immediately_reclaim` als
  Capability-Regel), **Disown-Baustein-Vereinheitlichung**
  (Exit/Reset/Split-Reuse, Record-Status-Pflege `ended`/`reset`/`split`,
  Owner-Notification-Vereinheitlichung), **Ex-Owner-Edge-Quarantäne** und
  die Self-Rebind-Ausnahme ohne Mitzeichnung: **AG3-149**. Der Transfer
  lässt den Record hier **aktiv** (In-Place-CAS per Scope-Punkt 8, der
  Record bleibt `status='active'`); er schreibt die Revocation der
  A-Bindung + den Tombstone als Teil seines atomaren Vollzugs. Die
  Record-STATUS-Pflege (`ended`/`reset`/`split`) ist AG3-149;
  `transferred` wird beim Run-fortführenden Takeover nicht gesetzt. Die
  Verallgemeinerung zum wiederverwendbaren Baustein ist AG3-149.
- **Freeze-basierte Challenge-Invalidierung** (`freeze_epoch`,
  takeover-admissibility bei Freeze-Zuständen): **AG3-150**. Diese Story
  invalidiert Challenges bei Eigentumslage-Änderungen (Transfer, Exit,
  Reset, Split, Closure).
- **Takeover-Reconcile, Quarantäne, die vier Guard-Zustände,
  `takeover-reconcile-worktree`**: **AG3-151** — baut den minimalen
  `takeover_reconcile_required`-Blocker aus Scope-Punkt 11 zum vollen
  Reconcile-Contract aus (Wire-Contract, Quarantäne, Reprovisionierung,
  übrige Zustände) und übernimmt ihn in die Guard-/Bundle-Sync-Fläche.
- **Frontend**: globaler benutzerübergreifender Overlay, Story-Cockpit,
  globaler governance-Stream (`GET /v1/events/governance`), Wire-Commands
  `request_story_run_takeover`/`confirm_story_run_takeover` im BFF:
  **AG3-153**. Diese Story liefert die Backend-Verträge, auf denen das BFF
  aufsetzt.
- **CLI-/Agent-Kommandos** (`takeover-request`/`-confirm` im Edge-Tool,
  `recover-story`, `admin-abort`-CLI): **AG3-154**; **`admin_abort`-Endpoint
  + operation_epoch-CAS**: **AG3-138**.
- **Job-Muster/Ergebnisarten-Registry/`stale_observation`**: **AG3-144**.
- **BC-weiter Client-op_id-Vertrag der Bestandsrouten**: **AG3-140** — die
  neuen Ownership-Routen sind von Anfang an client-op_id-pflichtig.

## Betroffene Dateien

| Datei | Änderungsart | Zweck |
|---|---|---|
| `src/agentkit/backend/control_plane/ownership_transfer.py` | neu | Challenge-Modell + Assembler-Regeln, Confirm-CAS-Entscheidungslogik, Approval-Lifecycle (pending/approved/denied/expired), Verlustkorridor-Pflichttext-Baustein, Invalidierungsregeln — Blutgruppe A |
| `src/agentkit/backend/control_plane/runtime.py` | ändern | Request-/Confirm-Handler; atomarer Vollzug (Record-CAS + Binding-Revoke/Neu-Bind + Tombstone + Transfer-Record in einer Transaktion); Event-Emission über die Lifecycle-Event-Mechanik (:1575 ff.); Historien-/Challenge-Query-Orchestrierung |
| `src/agentkit/backend/control_plane/models.py` | ändern | Wire-Modelle: TakeoverRequest; Challenge-Response; selector-only `TakeoverConfirmRequest`; boundary-konstruiertes Confirm-/Deny-Command mit attestierter Human-Identität; `pending_human_approval`-Response; Approval-Records |
| `src/agentkit/backend/control_plane/records.py`, `repository.py` | ändern | Approval-Queue-Record + Repository-Port; Transfer-/Ownership-Repositories aus AG3-137 konsumieren (Schreibfläche des Vollzugs) |
| `src/agentkit/backend/control_plane_http/app.py` | ändern | Routen `POST .../ownership/takeover-request` und `.../takeover-confirm` (Project-Edge-Gruppe); Statusform-Mapping inkl. `pending_human_approval`; Attestierungs-Wiring (Confirm nur menschlich attestiert); Fehlerbilder im Regel-8-Fehlervertrag |
| `src/agentkit/backend/auth/middleware.py` (+ Attestierungs-Anbindung) | ändern (minimal) | Principal-Attestierungs-Kontext für die Ownership-Endpoints (menschliche BFF-Session vs. Agent-Pfad) — IMPL-018 |
| `src/agentkit/backend/state_backend/postgres_schema.sql` + `postgres_store.py` + `store/facade.py` (+ `_public_api_names.py`, `__init__.pyi`, `mappers.py`) | ändern | Approval-Queue-Tabelle (Postgres-only, K5) + Challenge-Persistenz; transaktionale Row-Funktion des atomaren Vollzugs (Record-CAS + Bindungen + Transfer-Record + Events in einem Commit) |
| `src/agentkit/backend/telemetry/sse_stream.py` (+ Poll-Quelle des governance-Topics) | ändern | governance-Topic-Inhalt: ausstehende Takeover-Freigaben + `takeover_approval_changed` (projekt-skopiert; der globale Stream ist AG3-153) |
| `tests/unit/control_plane/**` | neu/ändern | Challenge-Assembler-, CAS-, Approval-Lifecycle- und Attestierungs-Entscheidungslogik über Ports/Fakes |
| `tests/integration/**` | neu | Postgres: E2E-Transfer (Setup → Transfer → Ex-Owner abgewiesen), Concurrency-Confirm-Rennen, Approval-Verfall, Serialisierung hinter laufender Mutation, Atomicity-Negativpfade |
| `tests/contract/**` | neu | Contract-Pins: Challenge-Form (inkl. Pflichttext + SHA/Frische je Repo), `pending_human_approval`-Form, vier Event-Schemas, `takeover_approval_changed`, Approval-Statusformen |

## Akzeptanzkriterien

1. **Challenge vollständig und Owner-BC-basiert:** ein menschlich
   initiierter Request liefert den versionierten Challenge mit
   `owner_session_id`, `ownership_epoch`, `binding_version`, Phasenstand,
   Anzeigedaten (inkl. „letzter API-Kontakt" mit Nicht-Diagnose-Hinweis,
   offenen Jobs/`op_id`s, Takeover-Historie), je teilnehmendem Repo
   Kandidaten-SHA + Push-Frische, und dem Verlustkorridor-Pflichttext —
   contract-gepinnt; die Daten stammen nachweislich aus den
   Owner-BC-Flächen (Record/Binding/Operationen/Transfer-Historie/
   AG3-147-Frische), nicht aus Read-Models.
2. **Begründungspflicht:** Request ohne `reason` wird mit strukturiertem
   Fehler abgewiesen (fail-closed, kein Default).
3. **Agent-Pfad:** ein agenteninitiierter Request erzeugt deterministisch
   `pending_human_approval` + einen persistenten, benutzerübergreifenden
   Approval-Eintrag; der Ausgang ist über `GET operations/{op_id}`
   beobachtbar: der erste Confirm kann terminal `challenge_reissued`
   liefern, ohne zu vollziehen; erst ein zweiter Confirm mit neuem `op_id`
   auf der frischen `challenge_id` liefert das Vollzugs-Ergebnis.
   `denied`/`expired` bleiben deterministische terminale Ausgänge. Der Eintrag übersteht einen
   Backend-Neustart (Integrationstest gegen die Postgres-Fixture).
4. **Verfall ist nie Ownership-Entzug:** ein verfallener Approval-Eintrag
   (`expired`) und ein verfallener Challenge lassen den
   `run_ownership_records`-Eintrag nachweislich unverändert (Negativtest:
   kein Statuswechsel, keine Epoch-Änderung, keine Bindungswirkung).
5. **Confirm-CAS deterministisch:** zwei konkurrierende Confirms auf
   denselben Challenge-Stand — genau einer gewinnt (Concurrency-
   Integrationstest); der Verlierer erhält einen deterministischen
   fail-closed Fehler; jeder Basis-Mismatch terminalisiert die Challenge
   als `invalidated` und muss anschließend neu angefragt werden.
6. **Challenge-Invalidierung an den Phasengrenzen:** je ein Negativtest für
   zwischenzeitlichen Transfer, Exit, Reset, Split und Closure — der
   Confirm mit der veralteten `challenge_id` scheitert deterministisch;
   die Challenge und eine per `challenge_ref` verknüpfte pending Approval
   werden atomar invalidiert, ohne Ownership-/Binding-/Transfer-Wirkung
   (Freeze-Eintritt: AG3-150).
7. **Atomarer Vollzug:** nach erfolgreichem Confirm existiert genau ein
   aktiver Record (`ownership_epoch` um 1 erhöht, `acquired_via='takeover'`,
   Owner = B), A's Bindung ist revoked (Grund `ownership_transferred`),
   B's Bindung trägt denselben `run_id`, eine höhere monotone
   `binding_version` und die Edge-gemeldeten Roots, A's Bundle ist
   tombstoned, und der Transfer-Record trägt je teilnehmendem Repo den
   serverseitig verifizierten `takeover_base_sha` + Frische-Felder +
   Challenge-/Confirm-Referenzen — alles in einer Transaktion: ein
   injizierter Fehler an jedem Einzelschritt hinterlässt **keinen**
   Teilzustand (Atomicity-Negativtest).
8. **Kein Snapshot:** es existiert keinerlei Snapshot-Infrastruktur
   (Grep-Beleg: kein Binär-Diff-/Untracked-Manifest-Codepfad; das
   Übergabeobjekt ist ausschließlich der SHA im Transfer-Record).
9. **Pushed-only fail-closed:** fehlt für ein teilnehmendes Repo ein
   serverseitig verifizierter gepushter Head, scheitert der Confirm
   deterministisch (kein Raten, kein lokaler Stand als Ersatz).
10. **Immobilität:** eine nach dem Confirm eintreffende Push-Meldung des
    Ex-Owners verändert den Transfer-Record nicht (Negativtest);
    Pre-Confirm-Refresh ist nur vor der Entscheidung wirksam und bounded.
11. **Attestierung:** ein Confirm-Versuch eines Agent-Principals ohne
    menschliche Frontend-Freigabe wird mit `403` abgewiesen (fail-closed);
    der vollzogene Confirm ist als `admin_transition` auditiert
    (Audit-/Event-Beleg im Test).
12. **Kein Automatik-Pfad (SOLL-029):** es existiert kein Codepfad, der
    aus Stille/Frische/Timeout einen Transfer auslöst (Code-Beweis +
    Negativtest: präparierte veraltete Push-Frische löst nichts aus).
13. **Story-Serialisierung:** ein Confirm, der während einer laufenden
    Mutation derselben Story eintrifft, greift erst nach deren
    Terminierung (AG3-141-Claim; Integrationstest: kein Fenster mit zwei
    Schreibern); der Transfer selbst ist kurz/bounded.
14. **Events + Topic:** die vier Events werden mit ihren Wire-Schemas
    emittiert (Contract-Pins); jeder Approval-Statuswechsel erzeugt
   `takeover_approval_changed` auf dem projekt-skopierten governance-Topic;
   zusätzlich wird das Event bei jedem erfolgreichen Challenge-Relink
   emittiert (auch `approved` → `approved`) und trägt die aktuell
   verknüpfte `challenge_id`.
15. **E2E-Regression mit AG3-142:** nach echtem Transfer (kein präparierter
    Record) wird eine Ex-Owner-Mutation an den Regime-Pfaden mit
    `409`/`403` + `ownership_transferred`-Payload abgewiesen; Reads inkl.
    `GET operations/{op_id}` bleiben A erlaubt.
16. **Admission-Blocker `takeover_reconcile_required`:** nach erfolgreichem
    Confirm ist der story-scoped Blocker im selben atomaren Commit gesetzt;
    jede Regime-Mutation der Story wird danach fail-closed mit `409` +
    maschinenlesbarem Grund abgewiesen, bis ein Reconcile-Abschluss
    gemeldet wird (Negativpfad-Test an der Confirm-Grenze); vor AG3-151
    ist die einzige Auflösung der auditierte Admin-Weg (Negativtest: ein
    nicht-auditierter/agentischer Auflösungsversuch scheitert fail-closed).
17. Coverage ≥ 85 % gehalten; `mypy` strict (inkl. `--platform linux`) und
    `ruff` ohne neue Ausnahmen; ARCH-55 (englische Bezeichner, Wire-Keys,
    Statusformen, Fehlercodes; der Verlustkorridor-Pflichttext ist
    UI-Lokalisierungs-Gegenstand — der Wire-Baustein trägt englische Keys).

## Definition of Done

- Alle Akzeptanzkriterien erfüllt; Gate-Suite grün (`pytest -n0`
  unit/integration/contract, Coverage ≥ 85, `mypy src` + `--platform linux`,
  `ruff`, 4 Konzept-Gates).
- Codex-Review PASS.
- Auf `origin/main` gemerged; `status.yaml` → `completed` (Vorbedingung für
  AG3-149, AG3-151, AG3-153, AG3-154); README-Backlog-Snapshot (§6.7)
  nachgezogen.

## Abdeckung (Traceability)

**Deckt ab:** SOLL-022–032, SOLL-038 (Transfer-Anteil), SOLL-039–041, SOLL-043, SOLL-148–152; IMPL-010, IMPL-011, IMPL-018, IMPL-022.

## Konzept-Referenzen

- FK-56 §56.13 (Grundsätze: explizit/nie automatisch; zweistufig;
  vollständig; selbst Story-Mutation), §56.13a (Challenge-Inhalt aus dem
  Owner-BC, Begründungspflicht, Confirm = CAS, Befristung =
  Entscheidungs-Verfall), §56.13b (Anfrage-Berechtigung; Vollzug nur nach
  menschlicher Frontend-Freigabe; `pending_human_approval`;
  Permission-Request-Familie; `admin_transition`), §56.13c (atomarer
  Vollzug; Transfer-Record mit `takeover_base_sha` je Repo als einziges
  Übergabeobjekt; Immobilität + Pre-Confirm-Refresh;
  Verlustkorridor-Pflichttext; Wirkung auf A), §56.13e (worktree_roots =
  Edge-gemeldete Pfade von B — Signaturbezug des Rebindings)
- FK-91 §91.1a Endpoint-Tabelle (`…/ownership/takeover-request`,
  `…/ownership/takeover-confirm` — Antwortvarianten, CAS-Fehlerbild),
  Regel 5 (client-op_id), Regel 13 (Story-Serialisierung); §91.8
  Topic-Tabelle governance-Zeile (`ausstehende Takeover-Freigaben`,
  `frontend-contracts.event.takeover_approval_changed`); Event-Katalog
  Quelle 56 (die vier Takeover-Events)
- FK-55 §55.5 (op-class `admin_transition`: Ownership-Transfer-Confirm)
- `formal.operating-modes.commands` →
  `operating-modes.command.request-run-ownership-takeover`
  (allowed_statuses, emits) und `.confirm-run-ownership-takeover`
  (CAS-Signatur inkl. Transfer-Record-Materialisierung, worktree_roots-
  Rebinding, Disown des Ex-Owners; requires-Invarianten)
- `formal.operating-modes.events` → die vier Takeover-Events;
  `formal.operating-modes.invariants` →
  `ownership_transfer_requires_explicit_confirmed_request`,
  `agent_initiated_takeover_requires_human_frontend_approval`,
  `takeover_confirm_fences_in_flight_mutations`
- `formal.state-storage.entities` →
  `state-storage.entity.takeover-transfer-record` (Feldliste:
  `takeover_base_sha`, `last_push_at`, `push_lag_hint`, `base_quality`,
  `challenge_ref`, `confirm_ref`)
- `formal.frontend-contracts.events` →
  `frontend-contracts.event.takeover_approval_changed` (Emissions-Seite;
  Konsum in AG3-153)

## Guardrail-Referenzen

- **FAIL-CLOSED:** veralteter/invalidierter Challenge → kein Vollzug;
  fehlender verifizierter Push-Head → kein Confirm; fehlende Begründung →
  Abweisung; Agent ohne Freigabe → 403. Im Zweifel wird nicht übernommen.
- **FIX THE MODEL, NOT THE SYMPTOM:** der Transfer ist ein typisierter,
  CAS-gesicherter Zustandsübergang auf dem Ownership-Record — kein
  Lease-Härtungs-Workaround (Lehre aus AG3-135) und keine zweite
  Eigentums-Wahrheit neben AG3-137/142.
- **SINGLE SOURCE OF TRUTH:** Challenge-Daten kommen aus dem Owner-BC;
  das Übergabeobjekt ist genau der `takeover_base_sha` im Transfer-Record;
  die Approval-Queue ist die eine persistente Freigabe-Wahrheit (kein
  Session-Lease-Nebenspeicher).
- **ZERO DEBT:** `pending_human_approval`, Approval-Verfall und
  Attestierung gehören vollständig zum Scope — kein „UI kommt später,
  solange vollzieht der Agent selbst".
- **Testing-Guardrails:** Negativpfade an den Phasengrenzen
  (Confirm-Rennen, Invalidierung je Übergangsart, Atomicity je
  Einzelschritt); Pipeline-/Ownership-State über echte Vorgängerpfade
  (Setup aus AG3-142) erzeugt, nicht manuell zusammengesetzt.

## Querschnitts-Auflagen

- **K5 Postgres-only:** Approval-Queue- und Challenge-Persistenz sind
  Postgres-only, fail-closed über das
  `_require_postgres_control_plane_backend`-Muster
  (`control_plane/runtime.py:2119`, Check :2139); kein SQLite-Spiegel.
  Contract-/Integrationstests über die Postgres-Fixture, Unit-Tests über
  Ports/Fakes.
- **Blutgruppen-Klassifikation**
  (`concept/methodology/software-blutgruppen.md`): Challenge-/Confirm-/
  Approval-Entscheidungslogik und Invalidierungsregeln
  (`ownership_transfer.py`) = **A**; Wire-/HTTP-Mapper, Event-Payload- und
  SSE-Projektions-Mapper = **R**; transaktionale Vollzugs-Row-Funktion im
  `state_backend` = **AT/T** (dort lokalisiert). Der A-Kern bleibt AT-frei.
- **Bundle-Assets:** Keine betroffen (verifiziert:
  `bundles/target_project/tools/agentkit/projectedge.py` ist ein dünner
  Wrapper ohne Ownership-Kommandos; die Takeover-/Abort-/Recover-Kommandos
  für Agents liegen in **AG3-154**, die Edge-Reconcile-Ausführung in
  **AG3-151**).
