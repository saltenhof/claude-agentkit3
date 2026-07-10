# AG3-153 — Frontend Takeover: globaler governance-Stream `GET /v1/events/governance`, benutzerübergreifender Freigabe-Overlay mit Verlustkorridor-Pflichttext, Cockpit-Takeover-Sicht (SHA/Push-Frische, 4 Edge-Zustände), Wire-Commands + Read-Model

- **Typ:** implementation
- **Größe:** L
- **depends_on:** [AG3-144, AG3-148, AG3-151]
  - **AG3-144** — die 202-Job-Semantik und der beobachtbare Fortschritt via
    `GET operations/{op_id}` entstehen dort; die Job-Anzeige dieser Story
    (In-Scope 5) rendert genau diese Anzeige-Datenquelle.
  - **AG3-148** — sämtliche Backend-Verträge, die diese Story konsumiert,
    entstehen dort: die Ownership-Endpoints `takeover-request`/`takeover-confirm`
    (an die die Wire-Commands gebunden sind), die persistente,
    benutzerübergreifende Approval-Queue (die Datenquelle des Read-Models
    `takeover_approval_request`), die Statusform `pending_human_approval`,
    der Challenge inkl. Verlustkorridor-Pflichttext-Baustein und SHA/Frische
    je Repo sowie das Event `takeover_approval_changed` auf dem
    projekt-skopierten governance-Topic (GAP §4: „ST-07a → ST-10 (nach
    K3-Nachverankerung)"). Diese Story baut NUR Konsum + Darstellung +
    den globalen Stream — keine Transfer-Mechanik.
  - **AG3-151** — die vier Edge-Zustände (`takeover_reconcile_required`,
    `contested_local_writes`, `remote_branch_diverged_after_takeover`,
    `local_stale_or_dirty_takeover_target`) existieren erst mit AG3-151
    als Read-Surface; diese Story rendert nur ihre Anzeige-Seite.
- **Quell-Konzept:** FK-91 §91.8.1 (projektübergreifender governance-Stream,
  Namenskonvention `/v1/events/…`, kein All-Topic-Stream, `?topics=`-Filter),
  §91.8.2 (Lossy-Vertrag + Re-Sync via Initial-GET des Read-Models),
  §91.8.3 (governance-Topic-Zeile); FK-72 §72.4 (Shell hostet Overlay-Region
  als Slot), §72.14.1 (Read-Model `TakeoverApprovalRequest` + die beiden
  Takeover-Commands in der formalen Frontend-Schicht), §72.14.7 (1)/(2)/(3)
  (Cockpit-Sicht, globaler Overlay, Job-/SHA-/Contested-Anzeige);
  FK-56 §56.13b (benutzerübergreifende Freigabe, `pending_human_approval`),
  §56.13c (Verlustkorridor-Pflichttext); FK-30 §30.6.3 (die vier
  Edge-Zustände — Anzeige-Seite);
  `formal.frontend-contracts.commands` (`request_story_run_takeover`,
  `confirm_story_run_takeover`), `.entities` (`takeover_approval_request`),
  `.events` (`takeover_approval_changed`)
- **Herkunft:** GAP-Analyse Session-Ownership v4 (`_temp/gap-analyse-session-ownership.md`),
  Story-Kandidat GAP-ST-10; normative Basis Commits 3ae011e4 / 1bb4ed8a / 58c190b7
  (+ Decision-Records unter `concept/_meta/decisions/`).

## Kontext / Problem

FK-72 §72.14.7 normiert drei Frontend-Anteile des Ownership-Transfers
(Cockpit-Sicht, globaler Freigabe-Overlay, Zustands-Anzeige) und FK-91
§91.8.1 den projektübergreifenden Push-Kanal dafür. Im Code existiert davon
nichts (am Code verifiziert 2026-07-02):

- **Der einzige Push-Kanal ist projekt-skopiert (IMPL-001):** der SSE-Stream
  wird pro Projekt gebaut
  (`backend/telemetry/sse_stream.py:129-158`,
  `iter_project_sse_stream(project_key=…)`; Route
  `/v1/projects/{key}/events`, `telemetry/http/routes.py:22`) und vom
  Frontend nur für das aktuell gewählte Projekt abonniert
  (`frontend/app/App.tsx:199-202`); `onmessage` ist ein reines
  Reload-Signal (:203-210). Ein Reviewer auf Projekt X sähe einen
  Takeover-Request auf Projekt Y nie. **Ist-Divergenz zu gap-02 (Code
  gewinnt):** das Topic-Vokabular enthält inzwischen `governance`
  (`sse_stream.py:20/:35`) — das projekt-skopierte Topic existiert also als
  Vokabel; sein Takeover-**Inhalt** entsteht in AG3-148. Der **globale**
  Stream `GET /v1/events/governance` (K3, per Commit 1bb4ed8a in FK-91
  §91.8.1 normiert) ist trotzdem ein komplett neuer, projektübergreifender
  Kanal — heute null Codepfad.
- **Keine Overlay-Ebene (IMPL-002):** die App-Shell
  (`frontend/app/app_shell/layout/Shell.tsx`) kennt nur Sidebar, Topbar,
  Workspace und DetailInspector; Grep `overlay|modal|dialog|toast` über
  `frontend/app/**/*.tsx`: null produktive Treffer. Ein globaler, über allen
  Sichten liegender Notification-Overlay existiert nicht.
- **Keine Cockpit-Takeover-Sicht, keine Wire-Command-Infrastruktur:** Grep
  `takeover|ownership|approval` über `frontend/app/`: null Treffer. Der
  REST-Client (`frontend/app/api.ts`) kennt nur Story-/Projekt-/Limits-Calls.
- **Client-Randbedingungen (verifiziert):** der Frontend-Client bricht jeden
  Request nach **12 s** ab (`api.ts:156-157`, `AbortController` +
  `setTimeout(…, 12000)`); `op_id` wird client-seitig gemintet
  (`makeOpId`, `api.ts:225`, Verwendung :147) — das ist Regel-5-konform
  (client-beigestelltes `op_id`) und Muster für die neuen Commands. SSE
  läuft über `EventSource` und ist vom 12-s-Budget nicht betroffen.
- **BFF-Topologie:** es gibt keinen eigenen BFF-Service — UI-BFF und
  Project-API sind derselbe Control-Plane-Listener mit Profil-Ports
  (`backend/cli/serve.py:1-15`, `ServeProfile` :35-39, Ports 9701/9702).
  Der neue globale Stream ist damit eine weitere non-project-scoped Route am
  bestehenden Listener (Tenant-Scope-Bypass-Kommentar
  `control_plane_http/app.py:502-503` nennt `/v1/events/hub` als Präzedenz).
- **Read-Model-Lücke:** FK-91 §91.8.2 verlangt den Re-Sync „über den
  Initial-GET des fachlichen Read-Models
  (`frontend-contracts.entity.takeover_approval_request`)" — ein
  Read-Endpoint für offene Takeover-Freigaben existiert weder im Code noch
  als Zeile in der FK-91-§91.1a-Endpoint-Tabelle (verifiziert; der exakte
  Pfad ist Story-Design, die Tabellen-Zeile ist als Konzept-Nachzug Teil
  dieser Story).

Ohne diese Story ist der agenteninitiierte Takeover praktisch tot: AG3-148
liefert `pending_human_approval` + Approval-Queue, aber kein Mensch sieht die
Anfrage, und der normativ einzige Vollzugsweg (menschliche Frontend-Freigabe,
FK-56 §56.13b) hat keine Oberfläche.

## Scope

### In Scope

1. **Globaler Stream `GET /v1/events/governance`** (SOLL-129, 130, 131, 132;
   IMPL-001): neue non-project-scoped SSE-Route am bestehenden Listener.
   Producer ist `telemetry` als Single-Producer (identische
   Envelope-/Wire-Schemas wie auf dem projekt-skopierten Stream — **keine
   zweite Event-Definition**); der Stream bündelt das governance-Topic
   **über alle Projekte**. `?topics=`-Filter wird unterstützt (Subset des
   governance-Vokabulars; unbekanntes Topic → 400, Präzedenz
   `invalid_sse_topics`). Auth: **ausschließlich Strategen-Cookie (UI-BFF)**
   — Thin-Client-Token/Project-API-Pfad wird fail-closed abgewiesen
   (FK-91 §91.8.1 Auth-Spalte). Namenskonvention: eigenes Pfadsegment unter
   `/v1/events/` analog `/v1/events/hub`; es entsteht **kein**
   All-Topic-Stream `/v1/events`. Lossy-Vertrag unverändert (§91.8.2).
2. **Initial-GET-Read-Surface für offene Takeover-Freigaben** (SOLL-102,
   103; Re-Sync-Anteil von SOLL-104/130): Read-only-Endpoint, der das
   Read-Model `takeover_approval_request` benutzerübergreifend liefert
   (Identität `approval_id`; Felder exakt nach
   `frontend-contracts.entity.takeover_approval_request` (v3) inkl.
   `requested_by_principal`, `reason`, `owner_session_id`,
   `ownership_epoch`, `binding_version`, `phase`, `last_api_contact_at`,
   `open_operation_ids`, `repo_push_status` (Liste je teilnehmendem Repo:
   `repo_id`, `last_pushed_head_sha`, `last_push_at`, `push_lag_hint`),
   `takeover_history_count`, `status pending|approved|denied|expired`,
   `requested_at`, `expires_at`). Datenquelle ist die
   AG3-148-Approval-Queue + Challenge-Felder aus dem Owner-BC (nicht aus
   nachlaufenden Read-Models). Der Endpoint-Pfad folgt den
   FK-91-Konventionen; die zugehörige Read-only-Zeile wird in der
   FK-91-§91.1a-Endpoint-Tabelle nachgezogen (Konzept-Nachzug, keine
   Norm-Neuschöpfung — §91.8.2 verlangt den Initial-GET bereits).
3. **Globaler Takeover-Freigabe-Overlay in der App-Shell** (SOLL-105, 108,
   133; IMPL-002): die Shell hostet eine **Overlay-Region als Slot** —
   Inhalt und Entscheidungssemantik (Challenge-Daten, Freigabe-Aktion)
   kommen aus dem Story-Slice/Owner-BC; die Shell trifft keine fachliche
   Aussage (FK-72 §72.4, R-Klammer). Der Overlay erscheint **sofort über
   allen Sichten**, ist **benutzerübergreifend** (nicht an einen Benutzer
   gebunden; jeder eingeloggte Benutzer sieht und entscheidet), speist sich
   aus dem **projektübergreifenden** governance-Stream (nie aus dem
   projekt-skopierten Projekt-Stream) und trägt die vollständige
   Challenge-Information der Cockpit-Sicht. **Verlustkorridor-Pflichttext**
   (FK-56 §56.13c, SOLL-151-Anzeige-Anteil): Challenge-Dialog und Overlay
   rendern verpflichtend und unverkürzt den Pflichttext-Baustein aus dem
   AG3-148-Challenge („Übernommen wird ausschließlich der gepushte Stand
   `<sha>`; nicht gepushte Commits, uncommittete Änderungen und untracked
   Dateien werden nicht übertragen …") — der Mensch bestätigt den möglichen
   Verlust nicht gepushter Arbeit ausdrücklich. Liefert die Bestätigung
   `challenge_reissued`, bleibt der Overlay offen, zeigt die frische
   Challenge vollständig an und verlangt einen zweiten Confirm mit neuem
   `op_id`; erst dieser zweite Confirm vollzieht den Transfer
   (`confirm_story_run_takeover`). Der Zustand „approved, aber frische
   Challenge wartet auf Bestätigung" wird über Initial-GET/Reconnect
   rekonstruiert;
   Ablehnung oder Fristablauf lässt ausschließlich die Anfrage verfallen
   und entzieht niemals Eigentum.
4. **Cockpit-Takeover-Sicht im Story-Inspector** (SOLL-107, SOLL-164):
   für eine Story mit aktivem Run zeigt das Story Cockpit die
   Eigentumslage als Entscheidungsgrundlage — Owner-Session, Principal,
   `ownership_epoch`; „zuletzt aktiv" (letzter API-Kontakt) **mit
   explizitem Nicht-Diagnose-Hinweis** (Information, nie Auslöser); offene
   Jobs mit `op_id`s und Phasenstand; **letzter gemeldeter gepushter
   Head-SHA + Push-Frische je teilnehmendem Repo**
   (`takeover_base_sha`/`last_push_at`/`push_lag_hint`/`base_quality` aus
   Transfer-Record bzw. Branch-Ref-Meldungen) — **statt eines
   Dirty-Zustands-Snapshots**: einen Dirty-/Lokalstand der Worktrees kennt
   das Backend nicht (FK-10 §10.2.4a); die bisherige Takeover-Historie
   prominent (Ping-Pong-Sichtbarkeit). Der Übernahme-Dialog **ist** der
   versionierte Challenge aus dem Owner-BC-Port — veraltet er, scheitert
   der Confirm deterministisch und die Sicht lädt die aktuelle
   Eigentumslage neu.
5. **Job-/SHA-/Contested-Anzeige** (SOLL-109, SOLL-164): laufende Jobs als
   `202` + `op_id` (beobachtbar über `GET operations/{op_id}`); nach einem
   Transfer der `takeover_base_sha` des Transfer-Records als
   **Verantwortungsgrenze**; die vier Edge-Zustände
   `takeover_reconcile_required`, `contested_local_writes`,
   `remote_branch_diverged_after_takeover`,
   `local_stale_or_dirty_takeover_target` als **blockierende, benannte
   Zustände mit Klartext-Hinweis, welcher offizielle Pfad sie auflöst**
   (Anzeige-Seite; Erzeugung/Semantik der Zustände: AG3-151).
6. **Wire-Commands im Frontend-Client** (SOLL-100, 101, 106):
   `request_story_run_takeover` (POST `…/ownership/takeover-request`;
   Inputs `run_id`/`reason` Pflicht/`op_id`; `owner_bc: story-lifecycle`;
   409 bei nicht takeover-admissible; **kein** Frontend-Event — der
   Challenge kommt synchron) und `confirm_story_run_takeover`
   (POST `…/ownership/takeover-confirm`; `challenge_id` Pflicht;
   `challenge_reissued` führt in den zweiten Bestätigungsschritt;
   emittiert `takeover_approval_changed`; 409 bei veraltetem Challenge;
   403 inkl. Ping-Pong-Schranke) — exakt nach
   `formal.frontend-contracts.commands`, `op_id` client-gemintet
   (bestehendes `makeOpId`-Muster), innerhalb des 12-s-Request-Budgets
   (`api.ts:156-157`; der Transfer selbst ist kurz/bounded per AG3-148).
7. **Event-Konsum `takeover_approval_changed`** (SOLL-104): das Event
   (Topic `governance`) öffnet bzw. schließt den globalen Overlay
   (`pending` → anzeigen; `approved` mit frischer pending Challenge →
   Bestätigungsschritt; `denied`/`expired` → schließen/aktualisieren);
   ein `approved`-Event allein schließt den Overlay nicht. Der Overlay
   verlässt sich nie allein auf das lossy
   SSE-Event — bei jedem Connection-Aufbau (initial + Reconnect) frischer
   Initial-GET (Punkt 2).

### Out of Scope (mit Owner)

- **Transfer-Backend** (Endpoints, Challenge-Assembler, Approval-Queue,
  `pending_human_approval`, atomarer Vollzug, Events, projekt-skopiertes
  governance-Topic-Befüllen): **AG3-148**. Diese Story konsumiert.
- **Erzeugung/Semantik der vier Edge-Zustände, Reconcile, Quarantäne**:
  **AG3-151** — hier nur Anzeige + Auflösungs-Hinweis.
- **Freeze-Familie/takeover-admissibility** (409-Grund bei Freeze):
  **AG3-150**.
- **Push-Frische-Erhebung und serverseitige Ref-Verifikation** (Datenquelle
  der SHA-/Frische-Anzeige): **AG3-147**.
- **CLI-/Edge-Tool-Kommandos** (takeover-request/-confirm/recover-story im
  Operator- und Agent-Pfad): **AG3-154**.
- **Job-Muster (202-Annahme), Ergebnisarten**: **AG3-144** — die
  Job-Anzeige (Punkt 5) rendert vorhandene `op_id`-Operationen; sie führt
  kein 202-Muster ein.
- **i18n-Resource-Bundle-Infrastruktur**: nicht Teil dieser Story; die
  neuen UI-Labels folgen dem bestehenden Muster (deutsche UI-Labels inline,
  ARCH-55-Ausnahme), ein Bundle-Umbau wäre eigener Scope.

## Betroffene Dateien

| Datei | Änderungsart | Zweck |
|---|---|---|
| `src/agentkit/backend/telemetry/sse_stream.py` | ändern | Projektübergreifende governance-Stream-Komposition (analog `iter_project_sse_stream` :129-158; gleiche Envelopes, Topic-Filter, Heartbeat) |
| `src/agentkit/backend/telemetry/http/routes.py` | ändern | Route `GET /v1/events/governance` (Präzedenz: `_PROJECT_EVENTS_PATH` :22; Topic-Validierung → 400 `invalid_sse_topics`) |
| `src/agentkit/backend/telemetry/repository.py` | ändern | Projektübergreifender governance-Event-Read-Port (analog `ProjectTelemetryEventSource` :35) |
| `src/agentkit/backend/state_backend/postgres_store.py` + `store/facade.py` (+ `_public_api_names.py`, `__init__.pyi`) | ändern | Adapter: projektübergreifender governance-Event-Read + Approvals-Read (Datenquelle: AG3-148-Approval-Queue, Postgres-only) |
| `src/agentkit/backend/control_plane_http/app.py` | ändern | Wiring der neuen Routen (non-project-scoped, Tenant-Scope-Bypass analog `/v1/events/hub` :502-503); Auth-Durchsetzung Strategen-Cookie-only für den globalen Stream; Approvals-Initial-GET |
| `concept/technical-design/91_api_event_katalog.md` | ändern (minimal) | Read-only-Endpoint-Zeile für den Approvals-Initial-GET in §91.1a nachziehen (Konzept-Nachzug; §91.8.2 verlangt den Initial-GET bereits) |
| `src/agentkit/frontend/app/api.ts` | ändern | Wire-Commands `request_story_run_takeover`/`confirm_story_run_takeover`, Approvals-Initial-GET, typisierte Fehlerbilder (409 stale challenge, 403 ping-pong, `pending_human_approval`-Form) — `makeOpId`-Muster :225, 12-s-Budget :156-157 |
| `src/agentkit/frontend/app/App.tsx` | ändern | Zweite, projekt-**unabhängige** `EventSource` auf `GET /v1/events/governance` (der projekt-skopierte Stream :194-229 bleibt unverändert); Approval-State + Overlay-Steuerung |
| `src/agentkit/frontend/app/app_shell/layout/Shell.tsx` | ändern | Overlay-Region als Slot (R-Klammer, keine fachliche Aussage in der Shell) |
| `src/agentkit/frontend/app/contexts/story_context_manager/components/TakeoverApprovalOverlay.tsx` | neu | Overlay-Inhalt: Challenge-Anzeige inkl. Verlustkorridor-Pflichttext, Freigabe-/Ablehnungs-Aktion (Confirm selektiert `challenge_id`; `challenge_reissued` zeigt die frische Challenge) |
| `src/agentkit/frontend/app/contexts/story_context_manager/components/TakeoverPanel.tsx` | neu | Cockpit-Takeover-Sicht: Eigentumslage, SHA/Push-Frische je Repo, offene Jobs/`op_id`s, Takeover-Historie, Edge-Zustands-Anzeige mit Auflösungs-Hinweis |
| `src/agentkit/frontend/app/app_shell/inspector/DetailInspector.tsx` | ändern | Einhängen der Cockpit-Takeover-Sicht als Story-Slice-Beitrag |
| `tests/unit/telemetry/**`, `tests/unit/control_plane/**` | neu/ändern | Stream-Kompositions-/Filter-/Auth-Entscheidungslogik über Ports/Fakes |
| `tests/integration/**` | neu | Postgres: projektübergreifende Sichtbarkeit (Approval in Projekt Y ohne Projektwahl sichtbar), Auth-Negativpfad, Initial-GET-Re-Sync |
| `tests/contract/**` | neu | Contract-Pins: Approvals-Read-Model-Form, globale Stream-Envelopes (identisch zum Projekt-Stream), Command-Formen inkl. Fehlerbilder |

## Akzeptanzkriterien

1. **Projektübergreifende Sichtbarkeit:** ein Approval-Statuswechsel in
   Projekt Y erzeugt ein `takeover_approval_changed`-Event auf
   `GET /v1/events/governance`, das ein Client **ohne** Projekt-Y-Auswahl
   empfängt (Integrationstest); die Envelope ist byte-identisch zum
   Wire-Schema des projekt-skopierten Streams (Contract-Pin — keine zweite
   Event-Definition, SOLL-130).
2. **Kein All-Topic-Stream, Filter fail-closed:** `/v1/events` existiert
   nicht (404); `?topics=` liefert nur bestellte Topics; ein unbekanntes
   Topic wird mit 400 abgewiesen (SOLL-131, Präzedenz `invalid_sse_topics`).
3. **Auth fail-closed:** der globale Stream akzeptiert ausschließlich die
   authentifizierte Strategen-Cookie-Session; ein Request ohne Session bzw.
   über den Thin-Client-Token-Pfad wird deterministisch abgewiesen
   (Negativtest; FK-91 §91.8.1 Auth-Spalte).
4. **Lossy-Re-Sync bewiesen:** nach einem simulierten Event-Drop +
   Reconnect stellt der Initial-GET des Read-Models den vollständigen
   Approval-Stand wieder her (Integrationstest); der Overlay-Zustand hängt
   nie allein am SSE-Event. Das gilt ausdrücklich für „approved, aber
   frische Challenge wartet auf Bestätigung": Initial-GET liefert Approval
   plus aktuell verknüpfte `challenge_id` und öffnet den Bestätigungsschritt
   erneut (SOLL-104/130).
5. **Read-Model feldgenau:** der Approvals-Initial-GET liefert
   `takeover_approval_request` exakt nach
   `frontend-contracts.entity.takeover_approval_request` (Contract-Pin);
   die Challenge-Felder stammen nachweislich aus dem Owner-BC (AG3-148-
   Flächen), `status` kennt genau `pending|approved|denied|expired`, und
   `expired` ist reiner Entscheidungs-Verfall (Negativtest: kein
   Ownership-Effekt; SOLL-102/103).
6. **Overlay benutzerübergreifend + sofort:** ein `pending`-Approval
   öffnet den Overlay über allen Sichten für **jede** eingeloggte
   Benutzersession (nicht nur für einen adressierten Benutzer); die Shell
   selbst enthält keine fachliche Entscheidungslogik (Slot-Beweis:
   Overlay-Inhalt kommt aus dem Story-Slice; SOLL-105/108).
7. **Verlustkorridor-Pflichttext erzwungen:** Challenge-Dialog und Overlay
   rendern den Pflichttext-Baustein aus dem Challenge vollständig und
   unverkürzt inkl. des konkreten `<sha>` je Repo (Contract-/UI-Test);
   es gibt keinen Confirm-Pfad, der den Pflichttext umgeht (SOLL-151-
   Anzeige-Anteil, FK-56 §56.13c).
8. **Confirm = exakter Challenge-Stand:** die Bestätigung im Overlay bzw.
   Cockpit-Dialog sendet die `challenge_id` des angezeigten, serverseitig
   gespeicherten Standes (`confirm_story_run_takeover`). Bei
   `challenge_reissued` zeigt sie die frische Challenge und sendet einen
   zweiten Confirm mit neuem `op_id`; im ersten Call findet kein Transfer
   statt. Ein zwischenzeitlich veralteter
   Challenge führt zu deterministischem 409 ohne Vollzug, und die Sicht
   lädt die aktuelle Eigentumslage neu (Negativtest; SOLL-101/107).
9. **Ablehnung/Verfall ohne Eigentumswirkung:** Ablehnen im Overlay und
   Fristablauf lassen ausschließlich die Anfrage verfallen — der
   Ownership-Record bleibt nachweislich unverändert (Negativtest;
   SOLL-108).
10. **Kein Dirty-Feld, SHA/Push-Frische je Repo:** das Read-Model enthält
    kein Dirty-Feld mehr (frontend-contracts v3: `repo_push_status`
    ersetzt `last_commit_sha`/`worktree_dirty`); die UI rendert je
    teilnehmendem Repo `last_pushed_head_sha` + Push-Frische
    (`last_push_at`/`push_lag_hint`) und nach Transfer den
    `takeover_base_sha` als Verantwortungsgrenze; ein Dirty-/Lokalstand
    wird nirgends angezeigt oder suggeriert (FK-72 §72.14.7(1), FK-10
    §10.2.4a); „zuletzt aktiv" trägt den Nicht-Diagnose-Hinweis
    (SOLL-107/164; UI-Snapshot-/Component-Test).
11. **Edge-Zustände benannt und blockierend:** die vier Zustände werden
    als unterscheidbare, blockierende Zustände mit Klartext-Auflösungs-
    Hinweis gerendert (kein Sammel-Fehler); fehlt das Zustands-Signal in
    den gelieferten Daten, zeigt die Sicht keinen „grünen" Default
    (fail-closed Unbekannt-Darstellung; SOLL-109/164).
12. **Command-Verträge gepinnt:** beide Wire-Commands sind contract-gepinnt
    (Inputs inkl. Pflicht-`reason`/`challenge_id`/`op_id`, Antwort
    `challenge_reissued`, Fehlercodes
    409/403/404/`idempotency_mismatch`); `op_id` wird client-seitig
    gemintet; `request_story_run_takeover` emittiert kein Frontend-Event
    (SOLL-100/101/106).
13. **Bestehende Streams unangetastet:** der projekt-skopierte Stream und
    sein Abonnement (`App.tsx:194-229`) verhalten sich unverändert
    (Regressionstest); der globale Stream ersetzt ihn nicht.
14. **Frontend-Build + Backend-Gates:** `npm run build` (tsc + vite) läuft
    fehlerfrei; Coverage ≥ 85 % gehalten; `mypy` strict
    (inkl. `--platform linux`) und `ruff` ohne neue Ausnahmen; ARCH-55
    (englische Bezeichner/Wire-Keys/Statusformen; deutsche UI-Labels als
    zulässige Lokalisierungs-Ausnahme).

## Definition of Done

- Alle Akzeptanzkriterien erfüllt; Gate-Suite grün (`pytest -n0`
  unit/integration/contract, Coverage ≥ 85, `mypy src` + `--platform linux`,
  `ruff`, 4 Konzept-Gates).
- Codex-Review PASS.
- Auf `origin/main` gemerged; `status.yaml` → `completed`;
  README-Backlog-Snapshot (§6.7) nachgezogen.

## Abdeckung (Traceability)

**Deckt ab:** SOLL-100–109, SOLL-129–133, SOLL-164; IMPL-001, IMPL-002.

## Konzept-Referenzen

- FK-91 §91.8.1 (SSE-Endpunkt-Tabelle: `GET /v1/events/governance`,
  projektübergreifend, `telemetry` Single-Producer, Strategen-Cookie;
  Namenskonvention `/v1/events/…`, kein All-Topic-Stream, `?topics=`
  überall), §91.8.2 (Lossy-Vertrag; Re-Sync über Initial-GET des
  Read-Models `takeover_approval_request`), §91.8.3 (governance-Zeile:
  ausstehende Takeover-Freigaben; globaler Overlay konsumiert den
  projektübergreifenden Stream)
- FK-72 §72.4 (Slot-Prinzip: Shell hostet die Overlay-Region; Inhalt/
  Entscheidungssemantik aus Story-Slice/Owner-BC), §72.12.4
  (Initial-GET-plus-Subscribe, Lossy-Re-Sync), §72.14.1 (Read-Model
  `TakeoverApprovalRequest` + Commands `request_story_run_takeover`/
  `confirm_story_run_takeover` in der formalen Frontend-Schicht — gap-01
  zitierte hierfür „§72.10"; nach aktuellem Dokumentstand ist §72.14.1 der
  tragende Anker), §72.14.7 (1) Cockpit-Sicht (SHA/Frische je Repo statt
  Dirty-Stand, Nicht-Diagnose-Hinweis, Owner-BC-Port), (2) globaler
  benutzerübergreifender Overlay (speist sich aus dem projektübergreifenden
  Stream; Verlustkorridor-Pflichttext; Verfall entzieht nie Eigentum),
  (3) Job-/SHA-/Contested-Anzeige (vier Edge-Zustände blockierend mit
  Auflösungs-Hinweis)
- FK-56 §56.13b (benutzerübergreifende Freigabe; `pending_human_approval`;
  Permission-Request-Familie), §56.13c (Verlustkorridor-Pflichttext,
  Wortlaut „sinngemäß" normiert)
- FK-30 §30.6.3 (Namen und Blockade-Semantik der vier Edge-Zustände —
  Anzeige-Referenz)
- FK-10 §10.2.4a/§10.2.4b (Backend kennt keinen Worktree-Dirty-Stand;
  Push-Frische als Teil der Eigentumslage-Anzeige — SOLL-144-Anzeigebezug
  liegt in AG3-147)
- `formal.frontend-contracts.commands` →
  `frontend-contracts.command.request_story_run_takeover`,
  `.confirm_story_run_takeover`; `.entities` →
  `frontend-contracts.entity.takeover_approval_request`; `.events` →
  `frontend-contracts.event.takeover_approval_changed` (Topic governance)

## Guardrail-Referenzen

- **FAIL-CLOSED:** unbekannte Topics → 400; fehlende Strategen-Session →
  Abweisung; fehlendes Zustands-Signal → keine optimistische Anzeige;
  veralteter Challenge → kein Vollzug. Der Overlay „übersieht" nie eine
  Anfrage, weil der Kanal projekt-gescopt wäre.
- **SINGLE SOURCE OF TRUTH:** ein Wire-Schema für beide Streams (keine
  zweite Event-Definition); Challenge-Daten aus dem Owner-BC, nicht aus
  Read-Models; die Approval-Queue (AG3-148) ist die eine Freigabe-Wahrheit
  — das Frontend hält keinen eigenen Approval-Zustand als Ersatzwahrheit.
- **FIX THE MODEL, NOT THE SYMPTOM:** der globale Kanal ist ein normierter
  neuer Stream (FK-91 §91.8.1) — kein Frontend-Polling-Workaround über
  alle Projekte und kein Missbrauch des Projekt-Streams.
- **SEVERITY-SEMANTIK:** die vier Edge-Zustände werden als blockierende
  Handlungsaufträge mit Auflösungspfad gerendert — nicht als wegklickbare
  Hinweise.
- **Strukturregeln:** Frontend-Code nur unter
  `src/agentkit/frontend/app/`; BC-aligned Slices (Story-Slice trägt die
  fachlichen Sichten, Shell bleibt R-Klammer); Backend-Anteile in
  `telemetry`/`control_plane_http`, Reads über die sanktionierte
  `state_backend.store`-Fassade.
- **ARCH-55:** englische Bezeichner, Wire-Keys, Zustands-/Statusnamen;
  deutsche UI-Label-Lokalisierung (inkl. Verlustkorridor-Anzeigetext) ist
  die zulässige Oberflächen-Ausnahme.

## Querschnitts-Auflagen

- **K5 Postgres-only:** diese Story legt keine neuen Tabellen an; alle
  Reads (Approval-Queue, governance-Events) laufen über die
  Postgres-only-Flächen aus AG3-148/AG3-137, fail-closed über das
  `_require_postgres_control_plane_backend`-Muster
  (`control_plane/runtime.py:2119`). Contract-/Integrationstests über die
  Postgres-Fixture, Unit-Tests über Ports/Fakes.
- **12-s-Client-Budget (verifiziert, `api.ts:156-157`):** Initial-GET und
  beide Commands müssen im 12-s-Budget antworten (der Transfer ist per
  AG3-148 kurz/bounded); der Stream läuft über `EventSource` und ist vom
  Budget nicht betroffen. Kein langes blockierendes Warten im Frontend.
- **Blutgruppen-Klassifikation**
  (`concept/methodology/software-blutgruppen.md`): Stream-Komposition/
  Topic-Filter (`sse_stream.py`-Erweiterung, reine Funktionen) = **R**;
  HTTP-Routen/Wire-Mapper (`telemetry/http/routes.py`, Approvals-GET) =
  **R**; Polling-/Read-Adapter im `state_backend` = **AT/T** (dort
  lokalisiert); Frontend-Module (Shell-Slot, Overlay, Cockpit-Panel,
  api.ts-Erweiterung) = **R** mit **T**-Anteilen (Browser-APIs) — das
  Frontend trägt keine A-Logik; fachliche Aussagen kommen ausschließlich
  aus dem Owner-BC (FK-72 §72.4).
- **Bundle-Assets:** Keine betroffen (verifiziert:
  `bundles/target_project/tools/agentkit/projectedge.py` hat keine
  Frontend-/Stream-Anteile; die Edge-Tool-Kommandos liegen in **AG3-154**).
