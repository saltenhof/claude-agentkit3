# AG3-154 — CLI/Admin-Kommandos + Edge-Tool: `takeover-request`/`takeover-confirm` (human_cli), echtes `recover-story` (`acquired_via=recovery`, neuer Run auf bestehendem Worktree), Agent-Kommandos im deployten `projectedge.py`

- **Typ:** implementation
- **Größe:** M
- **depends_on:** [AG3-138, AG3-145, AG3-148]
  - **AG3-138** — der Endpoint
    `POST /v1/project-edge/operations/{op_id}/admin-abort` (inkl.
    `operation_epoch`-CAS-Fence und menschlichem CLI-Adapter) entsteht dort;
    das Edge-Tool-Abort-Kommando dieser Story ist ein reiner Adapter auf
    diesen Endpoint (GAP §4: „ST-11 (auch: ST-02)").
  - **AG3-145** — Edge-Aufträge sind die Trägerschicht: die physischen
    Worktree-Anteile des Recovery (Wiederverwendung bzw. Verwerfen/
    Zurücksetzen des Worktree-Halbstands, Reprovisionierung) laufen als
    Edge-Aufträge über die Command-Queue — nie als Backend-Subprocess
    (FK-10 §10.2.4a; GAP §4: „ST-14a → … ST-11 — Edge-Aufträge sind deren
    Trägerschicht").
  - **AG3-148** — die Transfer-Endpoints `takeover-request`/`takeover-confirm`,
    der Challenge, `pending_human_approval`, die Approval-Queue und die
    HTTP-Attestierung entstehen dort; die CLI-/Edge-Kommandos dieser Story
    sind dünne Adapter darauf (GAP §4: ST-07a → ST-11).
- **Quell-Konzept:** FK-20 §20.7.3 (`agentkit recover-story --story {story_id}`
  mit Auswahl-Modus Übernehmen/Verwerfen), §20.7.4 (Crash-Recovery als
  Ownership-Transfer-Spezialfall: `acquired_via=recovery`, **neuer Run auf
  bestehendem Worktree**); FK-56 §56.13b (menschlich initiierte Takeovers
  via UI/**CLI** durchlaufen denselben informierten Challenge-Dialog direkt;
  Vollzug als `admin_transition`, auditiert), §56.13g (Recovery als
  Transfer-Spezialfall); FK-91 §91.1 (CLI = ausschließlich menschlicher/
  administrativer Adapterpfad; Agents nie direkt), §91.1a Regel 10 (jeder
  CLI-Befehl ist Adapter auf einen Control-Plane-Endpoint) + Endpoint-Tabelle
  (`…/ownership/takeover-request`, `…/takeover-confirm`,
  `…/operations/{op_id}/admin-abort`); FK-55 §55.5 (op-class
  `admin_transition`); `formal.operating-modes.invariants`
  (`ownership_transfer_requires_explicit_confirmed_request` — Owner wechselt
  nur durch Challenge-Confirm, offiziellen Endpfad **oder Recovery**)
- **Herkunft:** GAP-Analyse Session-Ownership v4 (`_temp/gap-analyse-session-ownership.md`),
  Story-Kandidat GAP-ST-11; normative Basis Commits 3ae011e4 / 1bb4ed8a / 58c190b7
  (+ Decision-Records unter `concept/_meta/decisions/`).

## Kontext / Problem

Das Ownership-Modell hat nach AG3-148 Backend-Verträge, aber keinen einzigen
Operator- oder Agent-Zugangsweg außerhalb des Frontends (am Code verifiziert
2026-07-02):

- **`recover-story` existiert nicht:** Grep `recover-story|recover_story`
  über `src/agentkit/`: **null Treffer** — das Kommando ist konzept-only
  (FK-20 §20.7.3 nennt es wörtlich als Strategen-Werkzeug des
  Worker-Loop-Recovery; FK-56 §56.13g ordnet es als Transfer-Spezialfall
  ein). Die CLI kennt heute: `split-story` (`backend/cli/main.py:200`),
  `reset-story` (:215), `exit-story` (:239), `run-phase` (:1704), `resume`
  (:1732), `reset-escalation` (:1761), `cleanup` (:1768), `status` (:1775),
  `query-state` (:1783) — keinerlei Takeover-/Recovery-Kommandos
  (Grep `takeover` in `cli/main.py`: null).
- **FK-91-§91.1-CLI-Tabelle (verifiziert):** die normative CLI-Tabelle
  listet die neuen Kommandos **noch nicht** (weder `takeover-request`/
  `takeover-confirm` noch `admin-abort` noch `recover-story`); die
  zugehörigen **Endpoints** sind in §91.1a vollständig verankert. Regel 10
  („jeder CLI-Befehl in §91.1 ist Adapter auf einen
  Control-Plane-Endpoint") verlangt Tabellen-Pflege, sobald die Kommandos
  entstehen — Konzept-Nachzug ist Teil dieser Story. Für das Recovery
  existiert zudem **kein** Endpoint in der §91.1a-Tabelle; der Wire-Pfad
  ist Story-Design innerhalb der verankerten Semantik (siehe Scope 3).
- **Confirm-Semantik der CLI (am Konzept verifiziert, FK-56 §56.13b):**
  „Menschlich initiierte Takeovers (UI/CLI) durchlaufen denselben
  informierten Challenge-Dialog **direkt**. Der Vollzug wird als Operation
  der Klasse `admin_transition` geführt und vollständig auditiert." — Die
  CLI hat also den **attestierten menschlichen Admin-Weg**: `human_cli`
  erhält auf den Request den Challenge und darf selbst confirmen. Agents
  dagegen dürfen die CLI **niemals** aufrufen (FK-91 §91.1 Akteur); ihr
  Weg ist der Project-Edge-Pfad mit `pending_human_approval` — einen
  Agent-Confirm gibt es nicht (AG3-148: direkter Agent-Confirm → 403).
- **Attestierungs-Präzedenz existiert:** `exit-story` trägt bereits ein
  verdecktes `--ak3-principal-attest`-Argument
  (`cli/main.py:246-251`) — Muster für die Principal-Attestierung der
  neuen Kommandos gegen die AG3-148-Attestierungsfläche.
- **Das deployte Edge-Tool hat keine Ownership-Kommandos:**
  `bundles/target_project/tools/agentkit/projectedge.py` kennt genau
  `phase-start`/`phase-complete`/`phase-fail`/`closure-complete`/`sync`/
  `create-story` (:84-108); Grep `takeover|admin-abort|recover`: null. Das
  client-seitige `op_id`-Minten (`op-{uuid4.hex}`, :228) ist
  Regel-5-konform (client-beigestelltes `op_id`) und bleibt Muster. Das
  Tool ist dünner Wrapper über `agentkit.harness_client.projectedge`
  (`ProjectEdgeClient`, Import :31-34) — Transportmethoden gehören in
  `harness_client/projectedge/client.py` (Bundle-/Tombstone-Mechanik dort
  bereits vorhanden, :370-383).
- **Kapazitäts-Kontext Recovery:** die Übernahme-/Verwerfen-Semantik des
  Worker-Halbstands (FK-20 §20.7.3) bleibt unverändert gültig; nach der
  K1-Verankerung ist ihr physischer Anteil (Worktree zurücksetzen bzw.
  wiederverwenden) zwingend Edge-Arbeit (FK-10 §10.2.4a Akteursmodell) —
  die AG3-145-Aufträge (`provision_worktree` etc.) sind dafür die
  Trägerschicht.

Ohne diese Story gibt es für den Strategen keinen offiziellen Weg, eine
gecrashte Session wieder aufzunehmen (FK-20-Recovery bleibt Papier), und
für Agents keinen vertragskonformen Zugang zu Takeover-Anfrage und
Abort-Eskalation.

## Scope

### In Scope

1. **CLI `agentkit takeover-request`** — dünner REST-Adapter (Regel 10) auf
   `POST …/ownership/takeover-request` (AG3-148): Pflicht-`reason`,
   client-gemintetes `op_id`; zeigt den versionierten Challenge vollständig
   an (Eigentumslage, „zuletzt aktiv" mit Nicht-Diagnose-Hinweis, offene
   Jobs/`op_id`s, Takeover-Historie, Kandidaten-SHA + Push-Frische je Repo,
   **Verlustkorridor-Pflichttext**) — der Operator entscheidet informiert.
   Kein eigener DB-/Runtime-Pfad, keine eigene Semantik.
2. **CLI `agentkit takeover-confirm`** — Adapter auf
   `POST …/ownership/takeover-confirm` mit Challenge-Echo: der
   **attestierte menschliche Admin-Weg** exakt nach FK-56 §56.13b
   (`human_cli` durchläuft den Challenge-Dialog direkt; Vollzug als
   `admin_transition`, vollständig auditiert; Attestierungs-Muster analog
   `--ak3-principal-attest` gegen die AG3-148-Attestierungsfläche).
   Deterministische Fehlerbilder werden 1:1 durchgereicht: 409 bei
   veraltetem/invalidiertem Challenge, 403 inkl. Ping-Pong-Schranke.
   **Es wird keine weichere CLI-Semantik erfunden**: kein Confirm ohne
   Challenge-Echo, kein „force".
3. **CLI `agentkit recover-story --story {story_id}`** (SOLL-090) — das
   echte Kommando aus FK-20 §20.7.3 mit **Auswahl-Modus**:
   - **Einordnung (FK-20 §20.7.4, FK-56 §56.13g):** Recovery ist ein
     Transfer-Spezialfall — Ownership-Erwerb mit `acquired_via=recovery`
     (Enum-Wert aus AG3-137), aber mit **neuem Run auf dem bestehenden
     Worktree**, weil der alte Run-Zustand nach einem Crash nicht
     vertrauenswürdig ist (im Unterschied zum Takeover, der denselben
     `run_id` unter neuer `ownership_epoch` fortführt).
   - **Übernehmen:** neuer Run; der Worker setzt mit dem vorhandenen
     Worktree-Stand fort (`worker-manifest.json` wird vom Worker
     aktualisiert).
   - **Verwerfen:** neuer Run; der Worktree wird zurückgesetzt und die
     Implementation-Phase beginnt von vorn — der physische Reset-/
     Reprovisionierungs-Anteil läuft als **Edge-Auftrag** (AG3-145),
     niemals als Backend-Subprocess-Git.
   - Die Übernahme-/Verwerfen-Semantik aus §20.7.3 bleibt **unverändert**;
     diese Story ordnet sie nur ownership-seitig ein (SOLL-090 wörtlich).
   - **Wire-Anbindung (Regel 10):** das Kommando ist Adapter auf den
     offiziellen Control-Plane-Pfad des Recovery. Da die
     FK-91-§91.1a-Tabelle keinen Recovery-Endpoint führt, definiert die
     Story den Pfad innerhalb der verankerten Semantik (Recovery ist per
     `ownership_transfer_requires_explicit_confirmed_request` ein
     anerkannter expliziter Erwerbsweg) — als eigener
     Ownership-Endpoint oder als deklarierte Recovery-Variante der
     Transfer-Endpoints; in beiden Fällen wird die
     **FK-91-Endpoint-Tabelle nachgezogen** (kein Endpoint ohne
     Tabellen-Zeile). Fail-closed-Vorbedingungen: es existiert kein
     konkurrierender aktiver Owner-Anspruch, der Erwerb schreibt einen
     neuen `run_ownership_records`-Eintrag (`acquired_via='recovery'`)
     über die AG3-148-Vollzugsmechanik; nichts läuft automatisch — der
     Auslöser ist ausschließlich der explizite menschliche Befehl.
4. **Edge-Tool-Kommandos im deployten Zielprojekt-Asset**
   (`bundles/target_project/tools/agentkit/projectedge.py` +
   Transportmethoden in `harness_client/projectedge/client.py`) —
   **Bundle-Asset-Pflichtdeklaration (Plan §3): BETROFFEN**:
   - `takeover-request` — Agent-Pfad: Antwort ist deterministisch
     `pending_human_approval`; das Tool gibt `op_id` + die explizite
     Information aus, dass ein Benutzer im Frontend freigeben muss, und
     beobachtet den Ausgang über `GET …/operations/{op_id}`.
   - `abort` — Adapter auf den AG3-138-Endpoint
     `…/operations/{op_id}/admin-abort`. Die Autorisierung liegt
     **ausschließlich serverseitig** (op-class `admin_transition`): ein
     nicht-privilegierter Agent-Principal erhält deterministisch 403 —
     das Tool erfindet keinen Umgehungsweg und keine clientseitige
     „Erlaubnis".
   - `recover` — Recovery-Anfrage derselben Harness-Identität über den
     offiziellen Recovery-Pfad aus Punkt 3; der Server verweigert
     Agent-Principals diesen frischen Recovery-Pfad fail-closed mit
     `recovery_requires_human_cli`.
   - **Kein `takeover-confirm` im Edge-Tool:** der Vollzug einer fremden
     aktiven Session erfordert menschliche Freigabe; ein Agent-Confirm
     existiert nicht (fail-closed; AG3-148).
   - Alle Kommandos: client-gemintetes `op_id` (Muster :228), Ausgabe als
     strukturiertes JSON analog Bestand, Fehlerbilder 1:1 durchgereicht.
5. **FK-91-§91.1-CLI-Tabellen-Nachzug** (Konzept-Pflege, Regel-10-
   Konsistenz): die neuen CLI-Kommandos `takeover-request`,
   `takeover-confirm`, `recover-story` werden als Zeilen der
   §91.1-Tabelle ergänzt (Kapitel-Verweise 56 bzw. 20; `admin-abort` trägt
   AG3-138 ein, falls dort noch nicht geschehen — verifizieren, nicht
   doppeln); ggf. die Recovery-Endpoint-Zeile in §91.1a (Punkt 3).

### Out of Scope (mit Owner)

- **`admin-abort`: Endpoint, CAS-Fencing und menschliches CLI-Kommando**:
  **AG3-138** (dort bereits im Scope). Diese Story liefert nur das
  agentenseitige Edge-Tool-Kommando als Adapter.
- **Transfer-Mechanik** (Challenge-Assembler, Approval-Queue,
  `pending_human_approval`-Statusform, atomarer Vollzug, HTTP-Attestierung):
  **AG3-148** — hier nur Adapter + Anzeige.
- **Self-Rebind-/Ping-Pong-Capability-Regeln** (SOLL-091, SOLL-035/036)
  und der Disown-Baustein: **AG3-149**.
- **Edge-seitige Reconcile-/Quarantäne-Ausführung** im Edge-Tool
  (`takeover_reconcile`-Executor): **AG3-151**.
- **Frontend** (Overlay, Cockpit, globaler Stream): **AG3-153**.
- **Command-Queue-Trägerschicht** (Endpoints, Auftragsarten, Executor):
  **AG3-145** — Recovery-Worktree-Aufträge nutzen sie nur.
- **Einheitlicher Idempotenz-Vertrag der Bestandsrouten**: **AG3-140** —
  die neuen Kommandos sind von Anfang an client-op_id-konform.

## Betroffene Dateien

| Datei | Änderungsart | Zweck |
|---|---|---|
| `src/agentkit/backend/cli/main.py` | ändern | Subcommands `takeover-request`, `takeover-confirm`, `recover-story` als dünne REST-Adapter (Regel 10; Attestierungs-Muster analog `--ak3-principal-attest` :246-251); Challenge-/Pflichttext-Ausgabe |
| `src/agentkit/backend/control_plane/models.py`, `runtime.py` | ändern (minimal) | Recovery-Erwerbsweg (`acquired_via='recovery'`, neuer Run auf bestehendem Worktree) auf der AG3-148-Vollzugsmechanik; Wire-Modelle des Recovery-Pfads |
| `src/agentkit/backend/control_plane_http/app.py` | ändern (minimal) | Recovery-Endpoint bzw. Recovery-Variante der Ownership-Routen (Story-Design nach Scope 3) |
| `src/agentkit/harness_client/projectedge/client.py` | ändern | Transportmethoden `takeover_request`/`admin_abort`/`recover` (Fehlerbilder 1:1, `op_id` client-beigestellt) |
| `src/agentkit/bundles/target_project/tools/agentkit/projectedge.py` | ändern | Neue Agent-Subcommands `takeover-request`, `abort`, `recover` (:84-108-Muster; kein `takeover-confirm`) |
| `concept/technical-design/91_api_event_katalog.md` | ändern (minimal) | §91.1-CLI-Tabellen-Zeilen für die neuen Kommandos; ggf. Recovery-Endpoint-Zeile in §91.1a (Konzept-Nachzug, Regel 10) |
| `tests/unit/cli/**`, `tests/unit/control_plane/**` | neu/ändern | Adapter-Delegations-Pins (kein Zweitpfad), Recovery-Entscheidungslogik (Übernehmen/Verwerfen-Statusformen) über Ports/Fakes |
| `tests/integration/**` | neu | Postgres: Recovery-E2E (Crash-Fixture über echten Dispatch-Pfad → recover-story → neuer Run, `acquired_via='recovery'`, Record-/Worktree-Zusicherungen); Agent-Pfad `pending_human_approval`; 403-Negativpfade |
| `tests/contract/**` | neu | Contract-Pins: CLI-Ausgabeformen (Challenge inkl. Pflichttext), Edge-Tool-JSON-Formen, Recovery-Wire-Form |

## Akzeptanzkriterien

1. **Reine Adapter (Regel 10):** alle drei CLI-Kommandos rufen
   ausschließlich ihre Control-Plane-Endpoints (Delegations-Pin analog
   AG3-138-AK7); es existiert kein eigener DB-/Runtime-Zweitpfad in der
   CLI (Code-Beweis).
2. **Challenge vollständig in der CLI:** `takeover-request` zeigt den
   versionierten Challenge inkl. Kandidaten-SHA + Push-Frische je Repo und
   dem unverkürzten Verlustkorridor-Pflichttext an; ohne `--reason` wird
   der Request lokal wie serverseitig abgewiesen (fail-closed, kein
   Default).
3. **Confirm nur attestiert-menschlich:** `takeover-confirm` vollzieht nur
   mit gültigem Challenge-Echo und menschlicher Principal-Attestierung
   (`human_cli`-Weg, `admin_transition`, auditiert — Audit-Beleg im Test);
   ein veralteter Challenge → deterministisches 409 ohne Vollzug; eine
   disowned Session → 403 (Ping-Pong; Fehlerbilder 1:1 durchgereicht,
   Negativtests).
4. **`recover-story` existiert und trägt die verankerte Semantik:** nach
   einem Crash-Szenario (Fixture über den echten Dispatch-/Run-Pfad, nicht
   manuell zusammengesetzt) erzeugt `recover-story` einen **neuen Run**;
   der neue `run_ownership_records`-Eintrag trägt
   `acquired_via='recovery'`; der **bestehende Worktree** wird
   wiederverwendet (kein Neu-Provisionieren im Übernehmen-Pfad); der alte
   Record wird nie gelöscht, sondern statusgeführt (AG3-137-Modell).
5. **Auswahl-Modus beide Pfade:** Übernehmen — Worker-Fortsetzung auf dem
   vorhandenen Worktree-Stand (Integrationstest); Verwerfen —
   Zurücksetzen des Halbstands läuft als Edge-Auftrag über die
   AG3-145-Queue (Beweis: kein `utils/git`-/Subprocess-Aufruf im
   Backend-Pfad; Negativ-Grep + Test), danach startet die
   Implementation-Phase im neuen Run von vorn.
6. **Kein Automatismus:** es existiert kein Codepfad, der Recovery oder
   Takeover aus Stille/Timeout/Frische auslöst; Auslöser ist ausschließlich
   der explizite Befehl (Code-Beweis; `ownership_transfer_requires_
   explicit_confirmed_request`).
7. **Edge-Tool-Agent-Pfad:** `projectedge.py takeover-request` liefert für
   einen Agent-Principal deterministisch `pending_human_approval` + `op_id`
   und macht den Ausgang über `GET operations/{op_id}` beobachtbar
   (Integrationstest); das Edge-Tool besitzt **kein**
   `takeover-confirm`-Kommando (Code-Beweis).
8. **Edge-Tool-Abort fail-closed:** `projectedge.py abort` mit
   nicht-privilegiertem Agent-Principal wird serverseitig mit 403
   abgewiesen und das Tool reicht das Fehlerbild strukturiert durch
   (Negativtest); es existiert kein clientseitiger Umgehungs- oder
   Retry-in-Schleife-Pfad.
9. **`op_id`-Vertrag:** alle neuen Kommandos minten `op_id` client-seitig
   (Regel 5) und sind über `GET operations/{op_id}` rekonsilierbar
   (Muster `projectedge.py:228`; Contract-Pin der Ausgabeformen inkl.
   `op_id`).
10. **Konzept-Nachzug konsistent:** die FK-91-§91.1-CLI-Tabelle führt die
    neuen Kommandos; jeder Tabellen-Eintrag verweist auf einen existierenden
    §91.1a-Endpoint (Regel 10); die 4 Konzept-Gates
    (`scripts/ci/check_concept_frontmatter.py`, `compile_formal_specs.py`,
    `check_concept_code_contracts.py`, `check_architecture_conformance.py`)
    sind grün.
11. Coverage ≥ 85 % gehalten; `mypy` strict (inkl. `--platform linux`) und
    `ruff` ohne neue Ausnahmen; ARCH-55 (englische Kommando-/Flag-/
    Wire-Namen, Fehlercodes; CLI-Hilfetexte englisch analog Bestand).

## Definition of Done

- Alle Akzeptanzkriterien erfüllt; Gate-Suite grün (`pytest -n0`
  unit/integration/contract, Coverage ≥ 85, `mypy src` + `--platform linux`,
  `ruff`, 4 Konzept-Gates).
- Codex-Review PASS.
- Auf `origin/main` gemerged; `status.yaml` → `completed`;
  README-Backlog-Snapshot (§6.7) nachgezogen.

## Abdeckung (Traceability)

**Deckt ab:** SOLL-090 und SOLL-091.

**SOLL-091 DISPOSITION:** satisfied by the `/resume` session-continuation
path (FK-56 §56.13g), see decision-record 2026-07-11; `recover-story` is
the fresh-session fallback.

## Konzept-Referenzen

- FK-20 §20.7.3 (Worker-Loop-Recovery: manueller Strategen-Eingriff;
  `agentkit recover-story --story {story_id}` mit Auswahl-Modus;
  Übernehmen = Fortsetzung mit vorhandenem Worktree-Stand + neuem Run,
  Verwerfen = Worktree zurückgesetzt + Implementation von vorn),
  §20.7.4 (Einordnung: Crash-Recovery als Ownership-Transfer-Spezialfall,
  `acquired_via=recovery`, neuer Run auf bestehendem Worktree; die
  Übernahme-/Verwerfen-Semantik aus §20.7.3 bleibt unverändert)
- FK-56 §56.13b (menschlich initiierte Takeovers via UI/CLI durchlaufen
  denselben informierten Challenge-Dialog direkt; Vollzug als
  `admin_transition`, vollständig auditiert), §56.13g (Crash-Recovery als
  Transfer-Spezialfall; Self-Rebind-Ausnahme — deren Capability-Regel:
  AG3-149)
- FK-91 §91.1 (Akteur: CLI ist ausschließlich menschlicher/administrativer
  Adapterpfad; Agents laufen über den Project Edge Client), §91.1a
  Regel 5 (client-beigestelltes `op_id`), Regel 10 (jeder CLI-Befehl ist
  Adapter auf einen Control-Plane-Endpoint), Endpoint-Tabelle
  (`…/ownership/takeover-request`, `…/ownership/takeover-confirm`,
  `…/operations/{op_id}/admin-abort`), Regel 17 (Reconcile unklarer
  Mutationen via `GET operations/{op_id}`)
- FK-55 §55.5 (op-class `admin_transition`: Ownership-Transfer-Confirm,
  `admin_abort_inflight_operation`)
- FK-10 §10.2.4a (Akteursmodell: physische Worktree-Ops nur Agent/Edge;
  Backend-Subprocess = Fehlbetrieb — bindend für den Verwerfen-Pfad),
  §10.6.2 (Recovery-Protokoll: Mensch entscheidet explizit; keine
  automatische Stale-Freigabe)
- `formal.operating-modes.invariants` →
  `ownership_transfer_requires_explicit_confirmed_request` („… official
  end path **or recovery** and never through timeout lease expiry heartbeat
  loss …" — Recovery ist ein anerkannter expliziter Erwerbsweg);
  `formal.operating-modes.entities` →
  `operating-modes.entity.run-ownership-record` (`acquired_via`-Vokabular
  inkl. `recovery`)

## Guardrail-Referenzen

- **FAIL-CLOSED:** kein Confirm ohne Challenge-Echo + Attestierung; kein
  Agent-Vollzug; Abort ohne Privileg → 403; Recovery nur als expliziter
  Befehl mit klaren Vorbedingungen — im Zweifel passiert nichts.
- **FIX THE MODEL, NOT THE SYMPTOM:** Recovery wird als das modelliert,
  was das Konzept sagt — ein Transfer-Spezialfall auf dem
  Ownership-Record — nicht als weiteres ad-hoc CLI-Skript neben dem
  Modell; die CLI bleibt Adapter, nie Zweitimplementierung (Regel 10).
- **SINGLE SOURCE OF TRUTH:** eine Vollzugsmechanik (AG3-148) für
  Takeover UND Recovery; die CLI-/Edge-Kommandos erzeugen keine zweite
  Befehls-Semantik; FK-91-Tabellen bleiben die eine Endpoint-/CLI-Wahrheit
  (Nachzug statt Drift).
- **NO ERROR BYPASSING:** die 403-/409-Fehlerbilder werden durchgereicht,
  nie clientseitig „geglättet"; kein `--force` am Confirm.
- **Strukturregeln:** CLI unter `backend/cli/`, Transport unter
  `harness_client/`, deploybares Asset unter `bundles/target_project/`
  (dünn, keine Backend-Fachlogik); Fachlogik des Recovery-Erwerbs im
  `control_plane`.
- **Testing-Guardrails:** der Crash-/Recovery-Zustand entsteht über den
  echten Dispatch-/Run-Pfad (keine manuell zusammenfantasierten
  Fixtures); Negativpfade (Agent-Confirm, unprivilegierter Abort,
  veralteter Challenge) sind Pflicht.

## Querschnitts-Auflagen

- **K5 Postgres-only:** diese Story legt keine neuen Tabellen an; der
  Recovery-Erwerb schreibt über die Postgres-only-Flächen aus
  AG3-137/148, fail-closed via
  `_require_postgres_control_plane_backend`
  (`control_plane/runtime.py:2119`). Contract-/Integrationstests über die
  Postgres-Fixture, Unit-Tests über Ports/Fakes.
- **Blutgruppen-Klassifikation**
  (`concept/methodology/software-blutgruppen.md`): CLI-Adapter und
  Edge-Tool-Subcommands = **R** (reine Übersetzung Befehl ↔ Wire, keine
  Fachaussage); `harness_client`-Transportmethoden = **R** mit
  **T**-Anteil (HTTP); Recovery-Erwerbslogik im `control_plane`
  (Vorbedingungen, Statusformen Übernehmen/Verwerfen) = **A** (klein),
  Persistenz über die bestehende **AT/T**-Fläche des `state_backend`.
  Der A-Kern bleibt AT-frei.
- **Bundle-Assets (Pflichtdeklaration, Plan §3): BETROFFEN** —
  `bundles/target_project/tools/agentkit/projectedge.py` erhält die
  Takeover-/Abort-/Recover-Kommandos für Agents (dünne Adapter;
  Autorisierung ausschließlich serverseitig; kein `takeover-confirm`).
  **Abgrenzung:** die Edge-seitige Reconcile-/Quarantäne-**Ausführung**
  im selben Asset liegt in **AG3-151**.
