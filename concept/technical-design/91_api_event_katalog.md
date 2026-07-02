---
concept_id: FK-91
title: API- und Event-Katalog
module: api-catalog
cross_cutting: true
status: active
doc_kind: core
parent_concept_id:
authority_over:
  - scope: api-catalog
defers_to:
  - FK-53
  - FK-54
supersedes: []
superseded_by:
tags: [api, events, cli, hooks, reference]
prose_anchor_policy: strict
formal_refs:
  - formal.installer.commands
  - formal.installer.events
  - formal.deterministic-checks.commands
  - formal.deterministic-checks.events
  - formal.guard-system.commands
  - formal.guard-system.events
  - formal.conformance.commands
  - formal.conformance.events
  - formal.llm-evaluations.commands
  - formal.llm-evaluations.events
  - formal.integrity-gate.commands
  - formal.integrity-gate.events
  - formal.governance-observation.commands
  - formal.governance-observation.events
  - formal.escalation.commands
  - formal.escalation.events
  - formal.setup-preflight.commands
  - formal.setup-preflight.events
  - formal.verify.commands
  - formal.verify.events
  - formal.exploration.commands
  - formal.exploration.events
  - formal.story-creation.commands
  - formal.story-creation.events
  - formal.dependency-rebinding.events
  - formal.story-closure.commands
  - formal.story-closure.events
  - formal.story-workflow.commands
  - formal.story-workflow.events
  - formal.story-split.commands
  - formal.story-split.events
  - formal.story-reset.state-machine
  - formal.story-reset.commands
  - formal.story-reset.events
  - formal.principal-capabilities.commands
  - formal.principal-capabilities.events
  - formal.operating-modes.commands
  - formal.operating-modes.events
  - formal.execution-planning.state-machine
  - formal.execution-planning.commands
  - formal.execution-planning.events
  - formal.state-storage.commands
  - formal.state-storage.events
  - formal.telemetry-analytics.commands
  - formal.telemetry-analytics.events
  - formal.integration-stabilization.commands
  - formal.integration-stabilization.events
  - formal.story-exit.commands
  - formal.story-exit.events
  - formal.story-contracts.events
  - formal.frontend-contracts.entities
  - formal.frontend-contracts.commands
  - formal.frontend-contracts.events
  - formal.frontend-contracts.invariants
---

# 91 — API- und Event-Katalog

## 91.1a Service-API-Endpunkte (Control Plane)

<!-- PROSE-FORMAL: formal.frontend-contracts.entities, formal.frontend-contracts.commands, formal.frontend-contracts.invariants -->

Die Service-API ist der **normative Standard-Zugriffspfad** fuer
alle Agents und den Orchestrator-Skill. Agents verwenden
ausschliesslich den offiziellen `Project Edge Client` gegen diese
Endpunkte. Die Aufruf-Parameter (story_id, phase, mode, op_id)
sind hier normativ definiert und gelten als Schema-Owner fuer alle
anderen Dokumente, die auf diese Parameter verweisen.

Diese Endpunkte beschreiben die normative Zielgrenze der zentralen
AgentKit-Control-Plane. Die lokale CLI (§91.1) ist ein menschlicher
Adapterpfad auf diese API; fachlich autoritativ ist der API-Vertrag.

Read-Models, Mutationen und Konsistenz-Invarianten fuer den
Web-Frontend-Konsumenten sind formal in
`formal.frontend-contracts.entities`,
`formal.frontend-contracts.commands` und
`formal.frontend-contracts.invariants` festgelegt; die
Endpoint-Liste unten ist die HTTP-Bindung dieser Vertraege.

| Endpoint | Methode | Beschreibung |
|----------|---------|--------------|
| `/v1/projects/{project_key}/story-runs/{run_id}/phases/{phase}/start` | `POST` | Offiziellen Start einer Phase anfordern (projekt-skopiert seit AG3-090, FK-72 §72.8.1) |
| `/v1/projects/{project_key}/story-runs/{run_id}/phases/{phase}/complete` | `POST` | Erfolgreichen Phasenabschluss melden |
| `/v1/projects/{project_key}/story-runs/{run_id}/phases/{phase}/fail` | `POST` | Fehlerhaften Phasenabschluss melden |
| `/v1/projects/{project_key}/story-runs/{run_id}/phases/{phase}/resume` | `POST` | Fortsetzung einer PAUSED-Phase anfordern (Operator-Recovery, FK-45) |
| `/v1/projects/{project_key}/story-runs/{run_id}/closure/complete` | `POST` | Offiziellen Closure-Abschluss anfordern |
| `/v1/project-edge/sync` | `POST` | Lokalen Edge-Bundle-Stand fuer einen Projekt-Client bounded neu abgleichen |
| `/v1/project-edge/operations/{op_id}` | `GET` | Unklare Remote-Lage eines mutierenden Requests ueber `op_id` reconciliieren |
| `/v1/project-edge/story-runs/{run_id}/ownership/takeover-request` | `POST` | Expliziten Ownership-Transfer (Takeover) fuer einen aktiven Story-Run anfragen (formal: `operating-modes.command.request-run-ownership-takeover`). Antwort ist nie der Vollzug, sondern eine von zwei Varianten: menschlich initiierte Requests (`human_cli`/UI via BFF) erhalten einen versionierten **Challenge** (`offered`: Eigentumslage inkl. `owner_session_id`, `ownership_epoch`, `binding_version`, Phasenstand, Anzeigedaten aus dem Owner-BC); agenteninitiierte Requests erhalten deterministisch **`pending_human_approval`** (Vollzug erfordert menschliche Frontend-Freigabe; Ausgang beobachtbar ueber `GET /v1/project-edge/operations/{op_id}`). Jede Anfrage traegt eine Begruendungspflicht (auditiert) |
| `/v1/project-edge/story-runs/{run_id}/ownership/takeover-confirm` | `POST` | Takeover per Challenge-Echo vollziehen (formal: `operating-modes.command.confirm-run-ownership-takeover`; Klasse `admin_transition`, FK-55 §55.5): CAS auf `ownership_epoch`/`binding_version`. Fehlerbild bei verfallenem oder invalidiertem Challenge (zwischenzeitlicher Transfer, Exit, Reset, Split, Closure oder Freeze-Eintritt): deterministischer fail-closed Fehlschlag ohne Vollzug — erneuter Request gegen die aktuelle Eigentumslage noetig |
| `/v1/project-edge/operations/{op_id}/admin-abort` | `POST` | Haengende serverseitige In-Flight-Operation administrativ abbrechen (`admin_abort_inflight_operation`, Klasse `admin_transition`, FK-55 §55.5; auditiert). Betrifft ausschliesslich servereigene Claims und leitet niemals Client-Ownership aus Stille ab (Regel 16). Das Finalize ist per `operation_epoch`-CAS gefenct: Late-Commits eines physisch noch weiterlaufenden Alt-Executors scheitern deterministisch am Operation-Fence und registrieren hoechstens einen No-op-/Abort-Vermerk; hat die abgebrochene Mutation bereits Teil-Writes hinterlassen, geht die Operation in einen expliziten, auditierten Reconcile-/Repair-Zustand statt stillschweigend in `failed` |
| `/v1/compat` | `GET` | Unterstuetztes Versionsfenster lesen: `min`/`recommended`/`blocked` fuer Agent-Runtime und Wire (dev↔central-Handshake, FK-10 §10.2.7) |
| `/v1/telemetry/events` | `POST` | Kanonisches Telemetrie-Event ingestieren |
| `/v1/telemetry/events` | `GET` | Kanonische Execution-Events einer `(project_key, story_id)`-Sicht lesen (optional `event_type`-Filter); server-vermittelter Read fuer den Hook-Emitter (FK-10 §10.1.0 I1, AG3-129) |
| `/v1/governance/guard-counters` | `POST` | Guard-Invocation-Counter server-vermittelt mutieren (`record` inkl. Week-Rollover oder `housekeeping`-Sweep, FK-61 §61.4.3); reiner Volume-Counter, nicht-blockierend (FK-30), Dev-Seite ist REST-Anforderer (FK-10 §10.1.0 I1, AG3-129). Traegt `op_id` (Regel 5): ein wiederholtes `op_id` zaehlt **exakt einmal** — Counter-Increment und `idempotency_keys`-Eintrag committen **atomar in EINER Transaktion** (kein Doppelzaehlen und kein verlorener Increment bei Crash/Retry); gleiches `op_id` mit ABWEICHENDEM Body ⇒ fail-closed `409 idempotency_mismatch` |
| `/v1/governance/worker-health` | `GET` | Kanonischen Worker-Health-State einer `(story_id, worker_id)`-Sicht lesen; fail-closed Gate-Operation (FK-30 §30.10, FK-10 §10.1.0 I1, AG3-129) |
| `/v1/governance/worker-health` | `POST` | Kanonischen Worker-Health-State server-vermittelt schreiben; fail-closed Gate-Operation (FK-30 §30.10, FK-10 §10.1.0 I1, AG3-129). Der Save ist ein **idempotenter Upsert** auf `(story_id, worker_id)` — ein Retry ueberschreibt denselben State (harmlos), daher kein separates `op_id` noetig |
| `/v1/projects/{project_key}/stories/{story_id}` | `GET` | Projekt-skopierte Story-Detailansicht (`StoryDetail`→`StorySummary`, inkl. Wire-Key `story_type`); vom Governance-Hook als **server-vermittelter Story-Typ-Read** konsumiert (FK-24 §24.3.2, FK-10 §10.1.0 I1, AG3-129) — fehlender Record ⇒ `404 story_not_found` ⇒ Hook fail-closed UNRESOLVED |
| `/v1/projects/{project_key}/planning/dependency-graph` | `GET` | Projektgebundenen Abhaengigkeits- und Konfliktgraph lesen (FK-72 §72.8.2) |
| `/v1/projects/{project_key}/planning/ready-set` | `GET` | Aktuell `READY`, blockierte und konfliktierte Stories mit Gruenden lesen |
| `/v1/projects/{project_key}/planning/execution-plan` | `GET` | Kritischen Pfad, Waves, empfohlenen Batch und maximale Parallelisierung lesen |
| `/v1/projects/{project_key}/planning/proposals` | `POST` | Strukturierte Agenten- oder Analyse-Proposals fuer Abhaengigkeiten, Gates und Waves offiziell einreichen |
| `/v1/projects/{project_key}/planning/proposals/{proposal_id}` | `GET` | Persistiertes Planning-Proposal mit Validierungs- und Anwendungsstatus lesen |
| `/v1/projects/{project_key}/planning/recompute` | `POST` | Offizielle Neuplanung nach Aenderung an Graph, Gates oder Story-Zustaenden ausloesen |
| `/v1/projects/{project_key}/execution-input/snapshot` | `GET` | Lebende Execution-Input-Sicht fuer das Frontend: laufende Stories + Triage-gefilterte delegierbare Stories + Counters (FK-70 §70.8a.1) |
| `/v1/projects/{project_key}/execution-input/next` | `GET` | Agent-orientierter Pull: genau eine naechste delegierbare Story (oder `null`) plus Triage-Begruendung; idempotent (FK-70 §70.8a.2) |
| `/v1/stories` | `POST` | Neue Story in der Control-Plane anlegen (kanonische Story-Wahrheit) |
| `/v1/stories` | `GET` | Projektgebundene Story-Liste für Web- und Agent-Clients |
| `/v1/stories/{story_id}` | `GET` | Story-Detailansicht mit Status, Laufzeit- und Telemetriebezug |
| `/v1/stories/{story_id}` | `PATCH` | Stammdaten einer Story aktualisieren (z. B. `title`, `labels`, `size`) |
| `/v1/stories/{story_id}/approve` | `POST` | Status-Transition `backlog` → `approved` (menschliche Freigabe) |
| `/v1/stories/{story_id}/reject` | `POST` | Status-Transition zurueck nach `backlog` (Nacharbeit) |
| `/v1/stories/{story_id}/cancel` | `POST` | Story administrativ abbrechen (`Cancelled`) |
| `/v1/stories/{story_id}/fields` | `GET` | Story-Attribut-Werte einer Story lesen |
| `/v1/stories/{story_id}/fields/{field_key}` | `PUT` | Einzelnen Story-Attribut-Wert setzen |
| `/v1/dashboard/board` | `GET` | Board- oder Listenansicht für die Story-Steuerung |
| `/v1/dashboard/story-metrics` | `GET` | Read-only Story-Metriken aus Runtime- und Analytics-Sicht |
| `/v1/projects/{project_key}/coverage/stories/{story_id}/acceptance` | `GET` | Soll-Sicht: Akzeptanzkriterien und ARE-Anforderungs-Verknuepfungen, die diese Story adressiert (Inspector-Spezifikations-Tab; FK-40 §40.10) |
| `/v1/projects/{project_key}/coverage/stories/{story_id}/are-evidence` | `GET` | Ist-Sicht: ARE-Evidenz pro Story — verlinkte Anforderungen, Coverage-Status, Evidenz-Pfade (Inspector-Ergebnis-Tab; FK-40 §40.10) |
| `/v1/projects` | `GET` | Projekt-Liste (`project_summary`) fuer den Topbar-Project-Selector (FK-72 §72.5) |
| `/v1/projects/{project_key}` | `GET` | Projekt-Detail (`project_detail`) inklusive `mode_lock` und `story_counters` (FK-72 §72.5 Topbar; `formal.frontend-contracts.entities.project_detail`) |
| `/v1/projects/{project_key}/mode-lock` | `GET` | Projektweiter Story-Mode-Lock (Standard/Fast/Idle) fuer den Topbar-ModeIndicator (FK-24 §24.3.3) |
| `/v1/projects/{project_key}/stories/counters` | `GET` | Aggregierte Story-Zaehler (total, finished, running, ready, queue, blocked) fuer die KpiBar |
| `/v1/projects/{project_key}/stories/{story_id}/flow` | `GET` | Phasen- und Substep-Snapshot fuer den Inspector-Ablauf-Tab (FK-72 §72.6, Projektion auf `phase-state-projection` FK-39) |
| `/v1/projects/{project_key}/execution-input/limits` | `GET` | Aktive Execution-Limits-Caps lesen (FK-70 §70.6.2) |
| `/v1/projects/{project_key}/execution-input/limits` | `PUT` | Caps anpassen; triggert Re-Plan (§70.6.2a) und SSE-Events `limits_changed` + `execution_input_changed` |
| `/v1/projects/{project_key}/stories/search` | `GET` | Projektgebundene Story-Suche (Query-Parameter `q`); filtert auf `id`, `title`, `repos`, `module`, `epic` und liefert `story_summary`-Liste (FK-72 §72.5 Topbar-Search) |

**Normative Regeln:**

1. Jeder mutierende Endpoint ist tenant-scoped und verlangt
   `project_key` explizit oder implizit aus dem authentisierten
   Projektkontext.
2. Die Control Plane exponiert mutierende Endpunkte nur ueber HTTPS;
   Plain-HTTP-Listener sind fachlich unzulaessig.
3. Agents muessen ausschliesslich den offiziellen
   `Project Edge Client` gegen die Control-Plane-API verwenden.
   Direkte CLI-Aufrufe durch Agents sind unzulaessig; freie
   `curl`-Kommandos ebenfalls. Die CLI (§91.1) ist menschlicher
   und administrativer Adapterpfad und kein Agent-Eingangstor.
4. Jeder mutierende Endpoint muss neben dem zentralen Commit-Resultat
   ein lokales Materialisierungs-Bundle fuer den `Project Edge Client`
   bereitstellen. Dieses Bundle umfasst mindestens `current.json`,
   `session.json`, den `story_execution`-Lock und alle fuer lokale
   Guard-Entscheidungen erforderlichen Zusatzlocks wie
   `qa_artifact_write`.
5. Jeder mutierende Endpoint muss `op_id` als Idempotenzschluessel
   akzeptieren; Wiederholungen mit derselben `op_id` duerfen keine
   zweite Mutation erzeugen. Das `op_id` wird **vom Client
   beigestellt**; serverseitiges Minten ist unzulaessig, weil es
   Retries blind macht (der Client kann eine unklare Mutation dann
   nicht mehr ueber `op_id` rekonsiliieren). Es gilt **EIN
   einheitlicher Idempotenz-Vertrag** fuer alle mutierenden
   Endpoints: ein Replay derselben `op_id` liefert das gespeicherte
   Ergebnis ohne zweite Mutation; gleiche `op_id` mit abweichendem
   Body ist fail-closed `409 idempotency_mismatch`
   (Body-Hash-Pruefung); eine parallel laufende gleiche `op_id` wird
   als in-flight abgewiesen bzw. serialisiert, nie doppelt
   ausgefuehrt (In-Flight-Schutz). Body-Hash-Pruefung und
   In-Flight-Schutz gelten ueberall — zwei getrennte Mechanismen mit
   unterschiedlicher Schutztiefe (Claim-Pfad mit In-Flight-Schutz
   neben einem Idempotenz-Schluessel-Pfad ohne) sind unzulaessig.
6. Die API ist die fachlich autoritative Zielgrenze. CLI und
   `Project Edge Client` erzeugen keine zweite Befehls- oder
   Event-Semantik neben der API; sie sind ausschliesslich
   Adapter auf den API-Vertrag.
7. Jede HTTP-Antwort der Control Plane traegt eine stabile
   `correlation_id`; bei HTTP-Transport wird sie ueber
   `X-Correlation-Id` propagiert oder, falls nicht vorhanden, von der
   Control Plane erzeugt.
8. Fehlerantworten folgen einem stabilen Vertrag mit mindestens
   `error_code`, `error` und `correlation_id`; optionale strukturierte
   `detail`-Daten duerfen diesen Vertrag nur erweitern, nicht ersetzen.
9. Stories werden ausschliesslich ueber die Control-Plane-API
   angelegt und mutiert. GitHub-Issues/Projects als Story-Verwaltung
   waren ein verworfenes AK2-Experiment und werden in AK3 nicht mehr
   verwendet. Externe Referenzen sind niemals Wahrheitsquelle fuer
   Story-Identitaet, -Status oder -Story-Attribute; sie duerfen
   hoechstens als read-only Anzeige gespiegelt werden.
10. Jeder CLI-Befehl in §91.1 ist Adapter auf einen
    Control-Plane-Endpoint. Eigenstaendige CLI-Implementierungen ohne
    API-Vertrag sind unzulaessig.
11. **Versions-Handshake (dev↔central):** Jeder Dev→Control-Plane-Request
    fuehrt die Agent-Runtime-Version (Paketversion) und das gebundene
    Skill-Bundle als Header (z. B. `X-AK3-Client`, `X-AK3-Skill-Bundle`).
    Die Control Plane prueft gegen ein unterstuetztes Fenster
    `[min, max]` und annonciert `recommended`/`blocked` (Antwort-Header
    bzw. `GET /v1/compat`). **Inkompatibel ist fail-closed** (`426
    Upgrade Required`): Runtime unter `min` oder in `blocked`, nicht
    unterstuetzte Wire-Version, fehlender Handshake an mutierenden oder
    Governance-Endpunkten. Runtime unter `recommended` aber im Fenster
    ist WARNING (Request laeuft). `/v1` bleibt eine statische Grenze; ein
    Bruch erzeugt `/v2`, keine In-Place-Aenderung. Treibermodell und
    vollstaendige Reaktionsmatrix: FK-10 §10.2.7/§10.2.8.
12. **Hook-Mediation (Dev→Core, AG3-129).** Der kurzlebige Hook-Prozess
    oeffnet keine direkte Datenbankverbindung (FK-10 §10.1.0 I1); Guard-Counter,
    Worker-Health und Telemetrie laufen ueber die obigen `/v1`-Endpunkte, deren
    serverseitige Adapter die zustaendigen BC-Services aufrufen. Die
    Blockier-Wirkung ist differenziert: **Worker-Health** ist eine kanonische
    Gate-Operation und **fail-closed** (unerreichbarer Kern blockt); der reine
    **Guard-Volume-Counter** und die **Telemetrie-Emission** sind
    **nicht-blockierend** (FK-30 „blockieren nie") — ein unerreichbarer Kern
    verwirft das Event sauber, niemals ein Direkt-DB-Fallback und niemals ein
    stilles „leeres OK". Der **Story-Typ** wird ebenfalls server-vermittelt
    gelesen (`GET /v1/projects/{project_key}/stories/{story_id}` → `story_type`,
    FK-24 §24.3.2); ein fehlender Record ODER Kern-Fault ist fail-closed
    UNRESOLVED (nie ein stiller Story-Typ). Der Guard-Counter-`record` traegt
    `op_id` und ist damit **exactly-once** pro `op_id` (Regel 5): Increment und
    Idempotenz-Schluessel committen atomar in EINER Transaktion (Crash zwischen
    beiden rollt beides zurueck); gleiches `op_id` mit abweichendem Body ist ein
    `409 idempotency_mismatch`. Auch dieser Pfad unterliegt dem einheitlichen
    Idempotenz-Vertrag aus Regel 5 vollstaendig — client-beigestelltes `op_id`,
    Body-Hash-Pruefung UND In-Flight-Schutz; ein Idempotenz-Schluessel-Pfad
    ohne In-Flight-Schutz ist kein zulaessiger Sondermechanismus. Der
    Worker-Health-Write ist ein idempotenter Upsert.
13. **Serialisierungsobjekt-Deklaration.** Jede mutierende Operation
    deklariert ihr Serialisierungsobjekt. Default fuer umsetzungs- und
    lifecyclebezogene Mutationen ist `(project_key, story_id)`;
    projektweite Mutationen (z. B. Mode-Lock, Story-Nummernvergabe,
    Projekt-/Planning-Konfiguration) serialisieren auf `(project_key)`.
    Mehr-Objekt-Mutationen deklarieren ein **Lock-Set mit globaler
    Erwerbsordnung**: erst der Projekt-Claim, dann Story-Claims in
    lexikographischer `story_id`-Reihenfolge; niemals einen Story-Claim
    halten und danach den Projekt-Claim anfordern. Gegen Starvation gilt
    **Queue-Fairness**: ein wartender Projekt-Claim konfligiert auch mit
    spaeter eintreffenden Story-Claims desselben Projekts — juengere
    Story-Claims ueberholen ihn nicht; administrative Uebergaenge haben
    definierte FIFO-Fairness. **Reads nehmen niemals Sperren.**
14. **Bounded-Pflicht und Job-Muster.** Objekt-serialisierte Mutationen
    muessen kurz, transaktional und technisch bounded sein. Was nicht
    bounded ist, ist per Definition ein Job: die Annahme ist eine kurze
    Mutation (Job-Record, Antwort `202` mit `op_id`), der Fortschritt
    ist ueber `GET /v1/project-edge/operations/{op_id}` beobachtbar,
    der Abschluss ist eine interne, gefencte Mutation (Regel 15).
    Zwischen Annahme und Abschluss haelt der Job **keine**
    Serialisierung.
15. **Drei Ergebnisarten fuer Job-Abschluesse.** Jeder Job deklariert
    seine Ergebnisart; der Abschluss-Commit ist danach gefenct:
    (a) **Reine append-only Observationen** (immutable Evidenzen,
    Historieneintraege) duerfen auch nach einem Owner-Wechsel abgelegt
    werden — dem Run zugeordnet und mit dem `ownership_epoch` ihres
    Starts markiert; sie aktualisieren **niemals** eine
    „latest"-Sicht, einen Current-Pointer oder eine Projektion.
    (b) **Projektions-/Upsert-Ergebnisse**: das Artefakt selbst darf
    abgelegt werden, aber die aktuelle Projektion bzw. der
    Current-Pointer wird **nur bei gueltigen Fences** aktualisiert;
    bei ungueltigen Fences wird das Ergebnis als separater, immutabler
    `stale_observation`-Historieneintrag abgelegt und ueberschreibt
    die aktuelle Projektion **nicht**. (c) **Steuernde Ergebnisse**
    (Gate-Entscheidungen, Phasenfortschritt, Run-/Story-Zustand)
    werden nur wirksam, wenn die Fencing-Praedikate zum
    Commit-Zeitpunkt passen; andernfalls deterministisch
    `stale_observation`, nachrichtlich, ohne Steuerwirkung. Die
    Fencing-Praedikate: aktiver Ownership-Record der Story,
    `ownership_epoch`/`binding_version` wie erwartet,
    `operation_epoch` des eigenen Claims unveraendert,
    Reset-Fence/`compaction_epoch` wo einschlaegig,
    `execution_contract_digest` wo einschlaegig, Zielversion des
    adressierten Artefakts wo einschlaegig.
16. **In-Flight-Claims sind instanzgebunden, nie wanduhrgebunden.**
    Jeder In-Flight-Claim traegt eine stabile Instanz-Identitaet
    (`backend_instance_id` + Boot-Inkarnation) und endet nur auf zwei
    Wegen: durch die **Start-Rekonsiliierung der eigenen Instanz**
    (beim Serverstart, vor Beginn der Request-Annahme, werden
    verwaiste Claims der eigenen Identitaet aus frueheren
    Inkarnationen deterministisch als gescheitert finalisiert) oder
    durch den expliziten administrativen Abbruch
    (`admin_abort_inflight_operation`) — **niemals** durch Wanduhr,
    TTL oder Lease-Ablauf. Betriebsannahme (normativ): **genau eine
    aktive Control-Plane-Writer-Instanz pro Datenbank**
    (FK-10 §10.5.4).
17. **Transport-Timeouts haben keine fachliche Bedeutung.**
    HTTP-/Proxy-Timeouts duerfen existieren, sind aber kein
    Steuerungsinstrument fuer Ownership oder Operations-Semantik: ein
    Client, dessen Verbindung riss, rekonsiliiert seine unklare
    Mutation ueber `GET /v1/project-edge/operations/{op_id}` — er
    verliert dadurch niemals sein Ownership.
18. **Ex-Owner-Fehlerbild.** Mutierende Story-Umsetzungs-Calls einer
    Session, deren Run-Ownership uebertragen wurde, werden
    deterministisch mit `409` bzw. `403` und einer
    `ownership_transferred`-Payload abgewiesen — mindestens: Grund,
    neuer Owner, Zeitpunkt des Transfers — eingebettet in den
    Fehlervertrag aus Regel 8. Reads, einschliesslich
    `GET /v1/project-edge/operations/{op_id}` zur Rekonsiliierung
    eigener frueherer Mutationen, bleiben dem Ex-Owner erlaubt.

## 91.1 Operator-Recovery-CLI (agentkit)

**Akteur:** Die CLI ist ausschliesslich ein menschlicher und
administrativer Adapterpfad auf die Control-Plane-API (§91.1a).
Agents duerfen die CLI niemals direkt aufrufen; ihr Zugriff laeuft
ueber den `Project Edge Client` gegen die REST-API. Die folgenden
Befehle sind damit fachlich gleichbedeutend mit dem zugehoerigen
API-Aufruf und erzeugen dieselbe Befehls- und Event-Semantik.

**Standardweg fuer Agents ist §91.1a (Service-API). Die CLI ist
Operator-Recovery-Pfad, kein Agent-Eingangstor.**

<!-- PROSE-FORMAL: formal.installer.commands, formal.deterministic-checks.commands, formal.guard-system.commands, formal.conformance.commands, formal.llm-evaluations.commands, formal.integrity-gate.commands, formal.governance-observation.commands, formal.escalation.commands, formal.setup-preflight.commands, formal.verify.commands, formal.exploration.commands, formal.story-creation.commands, formal.story-closure.commands, formal.story-workflow.commands, formal.story-split.commands, formal.story-reset.commands, formal.principal-capabilities.commands, formal.operating-modes.commands, formal.execution-planning.state-machine, formal.execution-planning.commands, formal.state-storage.commands, formal.telemetry-analytics.commands, formal.integration-stabilization.commands, formal.story-exit.commands -->

| Befehl | Kapitel | Beschreibung |
|--------|---------|-------------|
| `agentkit register-project --gh-owner {owner} --gh-repo {repo}` | 50 | Projekt registrieren bzw. idempotent erneut registrieren |
| `agentkit register-project --gh-owner {owner} --gh-repo {repo} --dry-run` | 50 | Checkpoint-Vorschau ohne Mutation |
| `agentkit verify-project` | 50 | Read-only Verifikation des Registrierungszustands |
| `agentkit run-phase {phase} --story {story_id} --run {run_id} --session {session_id} --principal {principal_type} --worktree {path} --project {project_key} --base-url {url}` | 45 | Pipeline-Phase ausfuehren — **Operator-Recovery-Spezialfall**. Seit AG3-130 duenner REST-Anforderer: dispatcht ausschliesslich ueber `POST /v1/projects/{project_key}/story-runs/{run_id}/phases/{phase}/start` (§91.1a, FK-10 §10.1.0 I3), kein in-process Runtime-Build im CLI-Prozess |
| `agentkit structural` | 33 | Structural Checks ausführen |
| `agentkit policy` | 33 | Policy-Evaluation ausführen |
| `agentkit stages` | 33 | Stage-Registry anzeigen |
| `agentkit status` | 52 | Systemstatus anzeigen |
| `agentkit cleanup --story {story_id}` | 20 | Stale Worktree/Branch/Locks aufräumen |
| `agentkit resume {phase} --story {story_id} --run {run_id} --session {session_id} --principal {principal_type} --worktree {path} --trigger {resume_trigger} --project {project_key} --base-url {url}` | 35 | Pausierte Phase fortsetzen. Seit AG3-130 duenner REST-Anforderer: dispatcht ueber `POST /v1/projects/{project_key}/story-runs/{run_id}/phases/{phase}/resume` (§91.1a, FK-45); der Resume-Trigger reist im `PhaseMutationRequest.detail.resume_trigger`, kein in-process Pipeline-Engine-Build im CLI-Prozess |
| `agentkit reset-escalation --story {story_id}` | 35 | Eskalation zurücksetzen |
| `agentkit reset-story --story {story_id}` | 53 | Vollständige korrupt gewordene Umsetzung administrativ zurücksetzen — **Operator-Notfallpfad** |
| `agentkit split-story --story {story_id}` | 54 | Scope-Explosion kontrolliert in Nachfolger-Stories überführen — **Operator-Notfallpfad** |
| `agentkit resolve-conflict --story {story_id} --decision {decision}` | 55 | Autoritativen Snapshot-/Normkonflikt offiziell auflösen |
| `agentkit approve-integration-manifest --story {story_id} --manifest {path}` | 57 | Integrations-Scope-Manifest fuer systemische E2E-/Stabilisierungsstory offiziell freigeben |
| `agentkit amend-integration-manifest --story {story_id} --manifest {path}` | 57 | Erweiterung oder Rekonfiguration eines laufenden Integrations-Manifests offiziell anfordern |
| `agentkit exit-story --story {story_id} --reason {reason}` | 58 | Story-Execution offiziell beenden und in Human-Takeover uebergeben — **Operator-Notfallpfad** |
| `agentkit approve-permission-request --request {request_id}` | 55 | Offenen Permission-Einzelfall als Mensch freigeben, optional als Lease |
| `agentkit reject-permission-request --request {request_id}` | 55 | Offenen Permission-Einzelfall als Mensch ablehnen |
| `agentkit guard-status` | 56 | Aktuellen Betriebsmodus, Run-Bindung und aktives Guard-Regime anzeigen |
| `agentkit override-integrity --story {story_id}` | 35 | Integrity-Gate bewusst overriden |
| `agentkit query-telemetry` | 52 | Telemetrie-Events abfragen |
| `agentkit dashboard [--port {port}]` | 63 | Read-only Dashboard für Runtime- und Analytics-Daten starten |
| `agentkit weekly-review` | 52 | Wöchentlichen Review-Slot anzeigen |
| `agentkit failure-corpus suggest-patterns` | 41 | Pattern-Kandidaten vorschlagen |
| `agentkit failure-corpus review-patterns` | 41 | Patterns reviewen |
| `agentkit failure-corpus review-checks` | 41 | Check-Proposals reviewen |
| `agentkit failure-corpus effectiveness-report` | 41 | Wirksamkeits-Report |
| `agentkit failure-corpus list-checks` | 41 | Aktive Checks anzeigen |
| `agentkit failure-corpus add-incident` | 41 | Incident manuell erfassen |
| `agentkit evidence assemble` | 26 | Evidence-Bundle für Review assemblieren (3-Stufen: Git-Diff, Import-Resolver, Worker-Hints) |

## 91.2 Telemetrie-Event-Typen

<!-- PROSE-FORMAL: formal.installer.events, formal.deterministic-checks.events, formal.guard-system.events, formal.conformance.events, formal.llm-evaluations.events, formal.integrity-gate.events, formal.governance-observation.events, formal.escalation.events, formal.setup-preflight.events, formal.verify.events, formal.exploration.events, formal.story-creation.events, formal.dependency-rebinding.events, formal.story-closure.events, formal.story-workflow.events, formal.story-split.events, formal.story-reset.state-machine, formal.story-reset.events, formal.principal-capabilities.events, formal.operating-modes.events, formal.execution-planning.events, formal.state-storage.events, formal.telemetry-analytics.events, formal.integration-stabilization.events, formal.story-exit.events, formal.story-contracts.events -->

| Event-Typ | Kapitel | Quelle | Beschreibung |
|-----------|---------|--------|-------------|
| `project_registration_requested` | 50 | CLI | Projektregistrierung explizit angefordert |
| `project_registration_started` | 50 | Installer | Checkpoint-Engine für Registrierung gestartet |
| `project_registration_completed` | 50 | Installer | Registrierung und Bundle-Bindung erfolgreich abgeschlossen |
| `project_registration_verified` | 50 | Installer | Read-only Verifikation abgeschlossen |
| `project_registration_dry_run_completed` | 50 | Installer | Dry-Run ohne Mutation abgeschlossen |
| `bundle_binding_rebound` | 51 | Installer | Bundle-Bindung im Upgrade-/Rebind-Pfad neu gesetzt |
| `project_customization_preserved` | 51 | Installer | Projektspezifische Anpassungen aktiv erhalten |
| `project_registration_failed` | 50 | Installer | Registrierung oder Rebind abgebrochen/gescheitert |
| `agent_start` | 14 | Hook (PostToolUse Agent) | Worker/Adversarial Agent gestartet |
| `agent_end` | 14 | Hook (PostToolUse Agent) | Agent regulär beendet |
| `increment_commit` | 14 | Hook (PreToolUse Bash) | Worker committet Inkrement |
| `drift_check` | 14 | Hook (PreToolUse Bash) | Drift-Prüfung Ergebnis |
| `review_request` | 14 | Review-Flow | Worker fordert Review an |
| `review_response` | 14 | Review-Flow | Review-Antwort empfangen |
| `review_compliant` | 14 | Review-Guard (PostToolUse) | Review über freigegebenes Template |
| `llm_call` | 14 | LLM-Evaluator / Hook | LLM über den LLM-Hub aufgerufen |
| `conformance_assessment_started` | 32 | ConformanceService | Dokumententreue-Bewertung begonnen |
| `conformance_level_evaluated` | 32 | ConformanceService | Dokumententreue-Ebene bewertet |
| `conformance_assessment_completed` | 32 | ConformanceService | Dokumententreue-Bewertung abgeschlossen |
| `llm_evaluation_started` | 34 | Verify Layer 2/3 Runner | Layer-2- oder Layer-3-Bewertung gestartet |
| `llm_evaluation_completed` | 34 | Verify Layer 2/3 Runner | Layer-2- oder Layer-3-Bewertung abgeschlossen |
| `adversarial_start` | 14 | Hook (PostToolUse Agent) | Adversarial Agent gestartet |
| `adversarial_sparring` | 14 | Harness-Eigenbedarf | Freiwilliges Sparring-LLM aufgerufen |
| `adversarial_test_created` | 14 | Hook (PostToolUse Write) | Neuer Test in Sandbox |
| `adversarial_test_executed` | 14 | Hook (PostToolUse Bash) | Test ausgeführt |
| `adversarial_end` | 14 | Hook (PostToolUse Agent) | Adversarial Agent beendet |
| `integrity_violation` | 14 | Guard-Hooks (PreToolUse) | Guard hat blockiert |
| `web_call` | 14 | Budget-Hook (PostToolUse) | Web-Aufruf |
| `governance_signal` | 35 | Hooks (normalisiert) | Governance-Anomalie-Signal |
| `governance_adjudication` | 35 | Governance-Beobachtung | LLM-Klassifikation eines Incidents |
| `governance_incident_opened` | 35 | Governance-Beobachtung | Incident-Kandidat eröffnet |
| `governance_measure_applied` | 35 | Governance-Beobachtung | Pause oder Eskalation deterministisch gesetzt |
| `run_paused` | 35 | Eskalationslogik / CLI | Story-Run auf `PAUSED` gesetzt |
| `run_escalated` | 35 | Eskalationslogik / CLI | Story-Run auf `ESCALATED` gesetzt |
| `run_resumed` | 35 | CLI | Pausierter Run desselben `run_id` fortgesetzt |
| `run_reopened` | 35 | CLI | Eskalierter Fall über neuen `run_id` wieder geöffnet |
| `run_redirected` | 35 | CLI | Eskalierter oder pausierter Fall in offiziellen Folgeprozess umgeleitet |
| `integrity_gate_started` | 35 | Phase Runner (Closure) | Integrity-Gate gestartet |
| `integrity_gate_result` | 35 | Phase Runner (Closure) | Integrity-Gate PASS/FAIL |
| `integrity_override` | 35 | CLI (Mensch) | Manueller Override |
| `story_reset_requested` | 53 | CLI / StoryResetService | Menschlicher Reset-Vorgang angefordert |
| `story_reset_started` | 53 | StoryResetService | Reset-Fencing und Purge begonnen |
| `story_reset_completed` | 53 | StoryResetService | Reset vollständig abgeschlossen, Story in sauberem Neustartzustand |
| `story_reset_failed` | 53 | StoryResetService | Reset unvollständig gescheitert, Story bleibt administrativ blockiert |
| `story_split_requested` | 54 | CLI / StorySplitService | Menschlicher Story-Split angefordert |
| `story_split_started` | 54 | StorySplitService | Story gefenced, Split-Plan-Ausführung begonnen |
| `story_split_completed` | 54 | StorySplitService | Ausgangs-Story beendet, Nachfolger-Stories angelegt |
| `story_split_failed` | 54 | StorySplitService | Split unvollständig gescheitert, Story bleibt administrativ blockiert |
| `capability_context_resolved` | 55 | GuardSystem / Capability Layer | Principal-, Pfad-, Operations- und Story-Scope-Kontext aufgeloest |
| `capability_allowed` | 55 | GuardSystem / Capability Layer | Tool-Aufruf nach harter Capability-Prüfung erlaubt |
| `capability_denied` | 55 | GuardSystem / Capability Layer | Tool-Aufruf nach harter Capability-Prüfung blockiert |
| `unauthorized_mutation_detected` | 55 | GuardSystem / Integrity Layer | Erfolgreiche oder nachtraeglich festgestellte unzulaessige Mutation erkannt |
| `conflict_freeze_entered` | 55 | GuardSystem / Eskalationslogik | Storybezogener Freeze fuer HARD-STOP-/Normkonflikt aktiviert |
| `conflict_freeze_released` | 55 | offizieller Resolution-Pfad | Freeze offiziell aufgehoben |
| `conflict_resolution_requested` | 55 | CLI / Admin-Service | Offizielle Konfliktaufloesung angefordert |
| `conflict_resolution_applied` | 55 | CLI / Admin-Service | Konfliktaufloesung auditiert angewendet |
| `conflict_resolution_rejected` | 55 | CLI / Admin-Service | Konfliktaufloesung abgelehnt oder unzulaessig |
| `permission_request_opened` | 55 | GuardSystem / CCAG | Unbekannte Freigabe als auditierbarer Einzelfall geoeffnet |
| `permission_request_approved` | 55 | CLI (Mensch) | Mensch hat einen Permission-Einzelfall freigegeben |
| `permission_request_rejected` | 55 | CLI (Mensch) | Mensch hat einen Permission-Einzelfall abgelehnt |
| `permission_request_expired` | 55 | GuardSystem / CLI | Offener Permission-Einzelfall ist lazy ohne Antwort in `DENIED` ausgelaufen |
| `permission_lease_issued` | 55 | CLI (Mensch) | Befristete story-/run-scoped Permission-Lease wurde ausgestellt |
| `external_permission_interference_detected` | 55 | Telemetrie / Supervisor / manueller Audit-Pfad | Hostseitiges Permission-/TTY-Verhalten stoert den deterministischen Story-Run |
| `operating_mode_resolved` | 56 | GuardSystem | Aktueller Betriebsmodus fuer die Session wurde bestimmt |
| `interactive_mode_assumed` | 56 | GuardSystem | Session arbeitet frei ausserhalb eines Story-Runs |
| `session_run_binding_created` | 56 | Setup / Runtime | Session wurde explizit an einen Story-Run gebunden |
| `session_run_binding_removed` | 56 | Closure / Cleanup / Reset / Split | Session-Bindung an einen Story-Run geloest |
| `story_execution_regime_activated` | 56 | Setup / Runtime | Storygebundene Guards und Workflow-Pflichten sind aktiv |
| `story_execution_regime_deactivated` | 56 | Closure / Cleanup / Reset / Split | Session faellt auf freien AI-Augmented-Modus zurueck |
| `binding_invalid_detected` | 56 | GuardSystem | Inkonsistenter Lock-/Bindungszustand wurde als blockierende inkonsistente Story-Bindung erkannt |
| `local_edge_bundle_materialized` | 56 | offizieller lokaler Project Edge Client | Lokales Edge-Bundle fuer Hooks und Guards atomar publiziert |
| `edge_operation_reconciled` | 56 | offizieller lokaler Project Edge Client / Control Plane | Unklare Remote-Lage einer Mutation ueber `op_id` reconciliiert |
| `run_ownership_takeover_offered` | 56 | Control Plane / Admin-Service | Versionierter Takeover-Challenge fuer einen aktiven Story-Run ausgestellt (Wire-Schema: `operating-modes.event.run_ownership_takeover_offered`) |
| `run_ownership_takeover_approval_requested` | 56 | Control Plane / Permission-Request-Pfad | Agenteninitiierter Takeover-Request wartet auf menschliche Frontend-Freigabe; Anfrager erhielt `pending_human_approval` (Wire-Schema: `operating-modes.event.run_ownership_takeover_approval_requested`) |
| `session_run_binding_transferred` | 56 | Control Plane / Admin-Service | Run-Bindung per bestaetigtem Takeover (CAS auf `ownership_epoch`/`binding_version`) auf die neue Session uebertragen (Wire-Schema: `operating-modes.event.session_run_binding_transferred`) |
| `session_disowned` | 56 | Control Plane / Admin-Service | Ex-Owner-Session entmuendigt: Zustand `binding_invalid` mit Grund `ownership_transferred`, Edge-Bundle tombstoned (Wire-Schema: `operating-modes.event.session_disowned`) |
| `story_contract_classified` | 59 | Setup / Story-Metadata | Persistenter Story-Vertrag aus `story_type` und optionalem `implementation_contract` wurde konsolidiert |
| `runtime_classification_derived` | 59 | Setup / GuardSystem | Laufzeitklassifikation aus `operating_mode` und `execution_route` wurde abgeleitet |
| `story_marked_done` | 59 | Closure | Story wurde erfolgreich geliefert und auf `Done` gesetzt |
| `story_cancelled_administratively` | 59 | Admin-Pfad | Story wurde ueber Split, Exit oder Reset administrativ auf `Cancelled` gesetzt |
| `invalid_contract_combination_detected` | 59 | Setup / GuardSystem | Ungueltige Vertragskombination oder verbotene Achsenmischung wurde fail-closed erkannt |
| `integration_manifest_approved` | 57 | CLI / human_cli | Integrations-Scope-Manifest fuer eine systemische E2E-/Stabilisierungsstory freigegeben |
| `stabilization_campaign_started` | 57 | Pipeline / Verify | Budgetierte Integrations-Stabilisierungsschleife gestartet |
| `integration_verify_passed` | 57 | Verify / Stability Gate | Integrationszielmatrix und Stability-Gate erfolgreich passiert |
| `integration_verify_failed` | 57 | Verify / Stability Gate | Integrations-Verify gescheitert; weiterer Zyklus oder Replan noetig |
| `undeclared_surface_detected` | 57 | GuardSystem | Produktiver Pfad ausserhalb des freigegebenen Integrations-Manifests beruehrt |
| `stabilization_budget_exhausted` | 57 | GuardSystem / Verify | Freigegebenes Stabilisierungshaushalt erschopft; normaler Weiterlauf blockiert |
| `manifest_amendment_requested` | 57 | CLI / human_cli | Erweiterung eines laufenden Integrations-Manifests offiziell beantragt |
| `stability_gate_passed` | 57 | Verify / Closure Precondition | Zusätzliche Integrations-Stabilitätsbedingungen für Closure erfüllt |
| `story_exit_requested` | 58 | CLI / human_cli | Offizieller Human-Takeover-Exit fuer eine Story angefordert |
| `story_exit_gate_passed` | 58 | Admin-Service | Leichtgewichtiges Exit-Gate bestanden |
| `story_exit_rejected` | 58 | Admin-Service | Exit-Voraussetzungen oder Exit-Grund waren unzulaessig |
| `story_exit_binding_revoked` | 58 | Admin-Service | Story-Lock und Session-Bindung fuer den beendeten Run wurden geloest |
| `story_exit_completed` | 58 | Admin-Service | Story ist administrativ beendet und Session wieder im freien Modus |
| `planning_metadata_captured` | 66 | Story-Erstellung / Planning Service | Planungsmetadaten fuer eine Story wurden initial oder verfeinert erfasst |
| `planning_proposal_submitted` | 66 | Agent / Planning Service | Strukturierter Planvorschlag wurde offiziell an AK3 uebergeben |
| `planning_proposal_rejected` | 66 | Planning Service | Proposal wurde wegen Struktur-, Konflikt- oder Governance-Verletzung verworfen |
| `planning_proposal_applied` | 66 | Planning Service | Proposal wurde in kanonische Planungsdaten ueberfuehrt |
| `human_review_requested` | 66 | Agent / Planning Service | Nicht-blockierende menschliche Review zur Qualitaetsverbesserung oder Validierung wurde angefragt |
| `human_review_recorded` | 66 | Mensch / Planning Service | Ergebnis einer nicht-blockierenden menschlichen Review wurde erfasst |
| `dependency_declared` | 66 | Planning Service / Admin-Pfad | Abhaengigkeitskante oder Konfliktregel offiziell erfasst oder geaendert |
| `planning_rulebook_compiled` | 66 | Planning Service / Admin-Pfad | Projektspezifisches Rulebook wurde in kanonische Planungsdaten uebersetzt |
| `blocker_recorded` | 66 | Planning Service / Admin-Pfad | Externer, menschlicher, kapazitiver oder Konflikt-Blocker wurde typisiert erfasst |
| `story_became_ready` | 66 | Planning Service | Regelbasierte Readiness-Bewertung hat eine Story auf `READY` gehoben |
| `story_became_blocked` | 66 | Planning Service | Readiness- oder Scheduling-Auswertung hat eine Story auf blockiert gesetzt |
| `execution_plan_created` | 66 | Planning Service | Kritischer Pfad, Waves und Batch-Vorschlag wurden neu berechnet |
| `execution_plan_replanned` | 66 | Planning Service | Eine bestehende Ausfuehrungsplanung wurde aufgrund von Zustandsaenderungen neu geschnitten |
| `scheduling_decision_issued` | 66 | Planning Service | Empfohlener und maximal erlaubter Batch fuer den Orchestrator wurde ausgegeben |
| `external_gate_cleared` | 66 | Planning Service / Admin-Pfad | Ein externer Blocker wurde offiziell als erledigt markiert |
| `human_gate_satisfied` | 66 | Planning Service / Admin-Pfad | Ein menschlicher Gate wurde offiziell als erfuellt markiert |
| `capacity_window_opened` | 66 | Planning Service | Frei gewordenes Scheduling-Budget erlaubt erneute Batch-Bewertung |
| `capacity_consumed` | 66 | Planning Service / Orchestrator | Start eines Batches oder einer Wave hat Scheduling-Budget belegt |
| `wave_collapsed` | 66 | Planning Service | Teilfehlschlag oder Konflikt hat eine aktive Wave invalidiert |
| `planning_state_sync_conflict` | 66 | Planning Service | konkurrierende Revisionen oder Adapterkonflikte haben eine manuelle Klaerung erzwungen |
| `deadlock_detected` | 66 | Planning Service | Planungsgraph oder Worklist fuehrt in einen Deadlock und erfordert Eskalation |
| `dependency_cycle_detected` | 66 | Planning Service | Zyklische Abhaengigkeit wurde erkannt und fail-closed eskaliert |
| `dependency_rebinding_started` | 54 | StorySplitService / DependencyRebinding | Rebinding der expliziten Story-Abhaengigkeiten begonnen |
| `dependency_rebinding_completed` | 54 | StorySplitService / DependencyRebinding | Alle expliziten Dependency-Kanten gemaess Split-Plan umgebogen |
| `dependency_rebinding_rejected` | 54 | StorySplitService / DependencyRebinding | Rebinding wegen unvollständigem Mapping oder Graph-Verletzung abgelehnt |
| `canonical_state_persisted` | 18 | PipelineEngine / StoryContextManager | Kanonischer PostgreSQL-Zustand einer Story- oder Runtime-Identität persistiert |
| `derived_storage_materialized` | 18 | PhaseStateStore / Analytics | Projektion oder Read-Model aus kanonischen Familien erzeugt |
| `derived_storage_rebuilt` | 18 | PhaseStateStore / Analytics | Stale oder rebuild-pending Family neu aus kanonischer Quelle aufgebaut |
| `derived_storage_stale` | 18 | PhaseStateStore / Analytics | Projektion oder Read-Model als stale markiert |
| `derived_storage_invalidated` | 18 | StoryResetService | Nicht-kanonische Family durch Reset invalidiert oder gelöscht |
| `telemetry_append_degraded` | 18 | TelemetryService | Telemetrie konnte nur degradiert verarbeitet werden, ohne den kanonischen Fortschritt zu blockieren |
| `runtime_storage_purged` | 18 | StoryResetService | Runtime-, Telemetrie- und Projektionsfamilien einer Story bereinigt |
| `storage_policy_violation` | 18 | GuardSystem / Runtime Check | Kanonizitäts-, Single-Writer- oder Scope-Verletzung am Speicherschnitt erkannt |
| `telemetry_collection_completed` | 14 | TelemetryService / Analytics Intake | Gültige Runtime-Events für Weiterverarbeitung gesammelt |
| `analytics_read_models_materialized` | 16 | QA-/Failure-Corpus-Projektion | Operative Read Models aus gültigen Quellen materialisiert |
| `analytics_facts_refreshed` | 62 | Analytics Refresh Worker | Fact-Familien aus gültigen Quellen neu berechnet |
| `analytics_data_invalidated` | 16 | StoryResetService / Analytics Worker | Telemetrie-/Analytics-Daten eines resetbetroffenen Runs invalidiert |
| `dashboard_query_served` | 63 | Dashboard Service | Read-only Ergebnis aus Runtime-/Analytics-Daten ausgeliefert |
| `analytics_policy_violation` | 63 | Dashboard Service / Guard | Ungültiger Auswertungspfad oder Serve-Versuch über invalidierte Daten erkannt |
| `preflight_passed` | 22 | Setup / Preflight | Alle Preflight-Checks bestanden |
| `preflight_failed` | 22 | Setup / Preflight | Mindestens ein Preflight-Check gescheitert |
| `setup_completed` | 22 | Setup / Preflight | Setup abgeschlossen, Mode und Spawn-Vertrag gesetzt |
| `verify_started` | 27 | Verify | QA-Zyklus gestartet |
| `verify_passed` | 27 | Verify | Vollständige 4-Schichten-QA erfolgreich abgeschlossen |
| `verify_failed` | 27 | Verify | QA-Befunde erfordern Remediation |
| `verify_escalated` | 27 | Verify | Verify wegen harter Verletzung oder Impact-Violation eskaliert |
| `preflight_request` | 14 | Review-Flow | Preflight-Prompt an den LLM-Hub gesendet (Preflight-Sentinel) |
| `preflight_response` | 14 | Review-Flow | Preflight-Antwort vom LLM empfangen |
| `preflight_compliant` | 14 | Review-Guard (PostToolUse) | Preflight verwendete genehmigtes Template (Preflight-Sentinel) |
| `review_divergence` | 14 | `telemetry/divergence.py` | Divergenz zwischen zwei Reviewern gemessen |
| `are_requirements_linked` | 40 | Pipeline-Skript | ARE: Anforderungen verlinkt |
| `are_evidence_submitted` | 40 | Worker/QA-Prozess | ARE: Evidence eingereicht |
| `are_gate_result` | 40 | Pipeline-Skript | ARE: Gate PASS/FAIL |

**Control-Plane-Regel:** Alle Event-Typen bleiben plattformneutral.
Hooks, CLI und kuenftige REST-Aufrufe sind nur Producer-Pfade auf
diesen Katalog; sie duerfen keine abweichenden Event-Namen oder
Payload-Formate einfuehren.

## 91.3 MCP-Tool-Katalog

### Story-Knowledge-Base (Weaviate)

| Tool | Kapitel | Beschreibung |
|------|---------|-------------|
| `story_search` | 13 | Semantische Suche |
| `story_list_sources` | 13 | Datenquellen auflisten |
| `story_sync` | 13 | Inkrementelle Indexierung |

### ARE (optional)

| Tool | Kapitel | Beschreibung |
|------|---------|-------------|
| `are_list_requirements` | 40 | Anforderungen auflisten |
| `are_get_recurring` | 40 | Wiederkehrende Pflichtanforderungen |
| `are_load_context` | 40 | must_cover für Worker-Kontext |
| `are_submit_evidence` | 40 | Evidence einreichen |
| `are_check_gate` | 40 | Gate prüfen |

## 91.4 Hook-Katalog

| Hook-Modul | Typ | Matcher | Kapitel |
|-----------|-----|---------|---------|
| `governance.branch_guard` | PreToolUse | Bash | 31.1 |
| `governance.orchestrator_guard` | PreToolUse | Bash, Read\|Grep\|Glob | 31.2 |
| `governance.integrity` | PreToolUse | Write\|Edit, Bash | 31.3 |
| `governance.qa_agent_guard` | PreToolUse | Write\|Edit | 31.4 |
| `governance.adversarial_guard` | PreToolUse | Write\|Edit | 31.6 |
| `governance.self_protection` | PreToolUse | Write\|Edit\|Bash | 30.5.3 |
| `governance.story_creation_guard` | PreToolUse | Bash | 31.5 |
| `governance.ccag_gatekeeper` | PreToolUse | Bash\|Write\|Edit\|Read\|Grep\|Glob\|Agent | 42.5 |
| `telemetry.hook` | Pre+PostToolUse | Agent, Bash, *_send | 14.3 |
| `telemetry.review_guard` | PostToolUse | *_send | 14.5 |
| `telemetry.budget` | PostToolUse | WebSearch\|WebFetch | 14.6 |

## 91.5 Phase-State Status-Werte

| Status | Bedeutung | Kapitel |
|--------|----------|---------|
| `PENDING` | Phase angelegt, noch nicht gestartet (Pre-Dispatch) | 39.2.1 |
| `IN_PROGRESS` | Phase läuft | 20.3.2 |
| `COMPLETED` | Phase erfolgreich abgeschlossen | 20.3.2 |
| `FAILED` | Phase gescheitert (z.B. Preflight) | 20.3.2 |
| `ESCALATED` | Dauerhaft gestoppt, neuer Run nötig | 35.4.3 |
| `PAUSED` | Vorübergehend angehalten, fortsetzbar | 35.4.3 |

## 91.6 Story-Reset-Statuswerte

Diese Werte gehoeren **nicht** zum normalen Phase-State, sondern zum
administrativen Reset-Vorgang aus FK-53.

| Status | Bedeutung | Kapitel |
|--------|----------|---------|
| `STARTED` | Reset-Vorgang angelegt, aber noch nicht abgeschlossen | 53.5 |
| `RESETTING` | Story ist gefenced und der Purge-Flow läuft | 53.7 |
| `COMPLETED` | Reset vollständig abgeschlossen | 53.9.3 |
| `RESET_FAILED` | Reset unvollständig gescheitert; Story bleibt blockiert | 53.9.2 |

## 91.7 Story-Split-Statuswerte

Diese Werte gehoeren **nicht** zum normalen Phase-State, sondern zum
administrativen Split-Vorgang aus FK-54.

| Status | Bedeutung | Kapitel |
|--------|----------|---------|
| `STARTED` | Split-Vorgang angelegt | 54.8.1 |
| `SPLITTING` | Story ist gefenced, Nachfolger und Rebindings werden aufgebaut | 54.8 |
| `COMPLETED` | Split vollständig abgeschlossen | 54.5 |
| `SPLIT_FAILED` | Split unvollständig gescheitert; Story bleibt administrativ blockiert | 54.8 |

## 91.8 Live-Event-Streams (SSE)

<!-- PROSE-FORMAL: formal.frontend-contracts.events -->

Frontend und BFF kommunizieren Live-Updates ueber Server-Sent Events
(SSE), siehe FK-72 §72.12. Dieser Abschnitt katalogisiert die
verfuegbaren SSE-Endpunkte und Event-Topics. Die konkreten
Event-Schemas auf dem projekt-skopierten Stream
`/v1/projects/{key}/events` sind formal in
`formal.frontend-contracts.events` definiert; FK-90 fuehrt zusaetzlich
die rohen Telemetrie-Schemas auf, soweit sie auch in
nicht-Frontend-Pfaden verwendet werden.

### 91.8.1 SSE-Endpunkte

| Endpoint | Skoping | Producer | Auth |
|---|---|---|---|
| `GET /v1/projects/{key}/events` | projekt-skopiert | `telemetry` (Single-Producer) | Strategen-Cookie (UI-BFF) bzw. Thin-Client-Token (Project-API), siehe FK-15 §15.10 |
| `GET /v1/events/hub` | projektneutral | `multi_llm_hub`-Adapter (Ausnahme) | Strategen-Cookie |

Beide Endpunkte unterstuetzen den Query-Parameter `?topics=` (Komma-
getrennte Liste), der die zu liefernden Topics einschraenkt. Ohne
Filter werden alle Topics geliefert. Server filtert serverseitig.

### 91.8.2 Lossy-Vertrag

SSE ist **lossy**: bei Backpressure droppt der Server Events. Der
Konsument muss bei jedem Connection-Aufbau einen frischen Initial-GET
auf den fachlichen REST-Endpoint machen, um den vollstaendigen Stand
zu holen. Es gibt keinen Sequence-Cursor, kein Acknowledge-Protokoll.

### 91.8.3 Event-Topics (projekt-skopierter Stream)

Der Katalog der unter `/v1/projects/{key}/events` gestreamten Topics
ist ueber das formale Set erweiterbar. Die folgenden Topics
sind als verbindliche Bereiche festgelegt; die Spalte
"Wire-Schemas" verweist auf die formalen Event-IDs in
`formal.frontend-contracts.events`. Erweiterungen werden ueber das
formale Set gepflegt; eine zusaetzliche Prosa-Tabelle der einzelnen
Event-Schemas ist explizit unzulaessig (keine zweite Wahrheitsquelle).

| Topic | Inhalt | Owner-BC | Wire-Schemas |
|---|---|---|---|
| `stories` | Story-Lifecycle: angelegt, geaendert, entfernt | `story_context_manager` | `frontend-contracts.event.story_upserted`, `.story_deleted` |
| `phases` | Phasen- und Substep-Uebergaenge, Phase-Status | `pipeline_engine` | `frontend-contracts.event.phase_transitioned` |
| `gates` | QA-Gate-Ergebnisse (pass, warning, fail) | `verify_system` | `frontend-contracts.event.gate_evaluated` |
| `governance` | Guard-Verletzungen, Integrity-Gate-Resultate, ausstehende Takeover-Freigaben (globaler Overlay, FK-72 §72.14.7) | `governance` | `frontend-contracts.event.governance_signal`, `.takeover_approval_changed` |
| `closure` | Closure-Substate-Uebergaenge | `closure` | `frontend-contracts.event.closure_transitioned` |
| `artifacts` | Artefakt-Erzeugungen mit Envelope-Metadaten | `artifacts` | `frontend-contracts.event.artifact_produced` |
| `telemetry` | Mode-Lock-Projektion plus rohe Execution-Events (verbose) | `telemetry` | `frontend-contracts.event.mode_lock_changed` |
| `kpi` | KPI-Aenderungen, neue Aggregate | `kpi_analytics` | offen (folgt mit der Analytics-Hauptsicht; FK-72 §72.14.2) |
| `planning` | Triage-Updates, Caps-Aenderungen, Graph-Aenderungen | `execution_planning` | `frontend-contracts.event.execution_input_changed`, `.limits_changed`, `.dependency_graph_changed` |
| `failure_corpus` | Pattern-Promotions, neue Incidents | `failure_corpus` | offen (folgt mit dem Failure-Corpus-Browser) |
| `coverage` | ARE-Verknuepfungen, Coverage-Status-Updates | `requirements_coverage` | `frontend-contracts.event.coverage_updated` |

### 91.8.4 Event-Topics (Hub-Stream)

Topics unter `/v1/events/hub`:

| Topic | Inhalt |
|---|---|
| `backend_status` | Backend-Health, Slot-Belegung |
| `sessions` | Session-Lifecycle (acquire, release, expire) |
| `session_messages` | Eingehende Antworten in laufenden Sessions |

### 91.8.5 Pflicht zum Nachtrag

Pro neuem Event-Typ auf dem projekt-skopierten Stream wird die
formale Spec `formal.frontend-contracts.events` erweitert; die
Topic-Tabelle §91.8.3 referenziert den neuen Event-Bezeichner unter
"Wire-Schemas". FK-90 fuehrt weiterhin die rohen Telemetrie-Schemas,
soweit sie ueber Frontend-/SSE-Pfade hinausgehen. Hub-Events
(§91.8.4) bleiben out-of-scope der Frontend-Contracts-Spec, siehe
`concept/formal-spec/frontend-contracts/README.md`.
