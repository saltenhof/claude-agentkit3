# AG3-071: StoryResetService + Reset-Record + Purge-Domänen

**Typ:** Implementation
**Groesse:** L
**Bounded Context:** `story-lifecycle` — administrative, destruktive Recovery-Komponente fuer eine irreparabel eskalierte Story-Umsetzung. Explizit **kein** Teil der PipelineEngine (FK-53 defers_to FK-20), sondern ein menschlich ausgeloester, checkpointfaehiger Admin-Flow.

**Quell-Konzepte (autoritativ):**
- `FK-53 §53.3` — CLI `agentkit reset-story --story --reason` (offizieller Kontrollpfad; optional `--escalation-ref`/`--dry-run`/`--force`)
- `FK-53 §53.4/§53.5` — Eingangsbedingungen (typischer Vorzustand: eskalierte/festsitzende Umsetzung, **als Befund** nachgewiesen — kein Story-Stammdatenstatus), Autorisierung/Audit, minimaler Reset-Record mit `reset_id`
- `FK-53 §53.6` — was bleibt (Story/StoryContext/Stammdaten/Reset-Nachweis) vs. was vollstaendig verschwindet (FlowExecution/NodeExecution/AttemptRecord/OverrideRecord/GuardDecision/PhaseState/umsetzungsgebundene ArtifactRecord/ExecutionEvent/FK-69-Read-Models/Analytics/Locks/Worktree)
- `FK-53 §53.7` — 8-Schritt Reset-Flow: (1) Vorgang registrieren → (2) Story exklusiv fence'n + Status `RESETTING` → (3) aktive Laufzeitteilnehmer quiescen → (4) minimalen Beweis sichern → (5) operativen Runtime-State purgen (§53.7.5) → (6) Read-Models + Analytics purgen (§53.7.6) → (7) ephemere Arbeitsoberflaechen entfernen → (8) Worktree/Branch behandeln (tainted)
- `FK-53 §53.8` — Endzustand (Story als fachliche Einheit erhalten, restartbarer Grundzustand, kein resumierbarer Run)
- `FK-53 §53.9` — Fehlerbehandlung/Idempotenz: kein globaler ACID-Tx, jeder Purge-Schritt konvergent; `RESET_FAILED` ist **nicht runnable**; gleiche `reset_id` = Resume, nicht neuer Reset; Lock erst nach Verifikation freigeben
- `FK-53 §53.10` — minimaler Service-Vertrag: `request_reset` / `execute_reset(reset_id)` / `resume_reset(reset_id)` / `verify_reset_clean_state(reset_id)` (FK-53 §53.10: „mindestens diese Operationen"; interne Schritte/Ports erlaubt)

---

## 1. Kontext / Ist-Zustand (belegt)

Der `StoryResetService` ist als BC **vollstaendig ungebaut**; nur der CLI-Subkommando-Name ist als guarded admin path reserviert:

- `src/agentkit/governance/principal_capabilities/operations.py:168` — `ADMIN_SUBCOMMANDS = frozenset({"reset-story", "split-story", "resolve-conflict", "cleanup"})` (reserviert, kein Service dahinter).
- `src/agentkit/governance/guards/branch_guard.py:25` — `"agentkit reset-story"` ist als offizieller Pfad zugelassen (Guard-Allowlist vorhanden, Service fehlt).
- `src/agentkit/cli/main.py:38-141` — die `argparse`-Subparser kennen `install`/`uninstall`/`run-story`/`doctor`/`serve-control-plane`. **Kein `reset-story`-Command, kein Handler.**
- `src/agentkit/story_context_manager/story_model.py:34-46` — `StoryStatus` hat `Backlog|Approved|In Progress|Done|Cancelled`. **Kein `RESETTING`, kein `RESET_FAILED`, und kein `ESCALATED`** — Eskalation ist Run-/Phase-/Befund-Kontext, kein Story-Stammdatenstatus.
- `src/agentkit/story_context_manager/service.py:80-89` — `_ALLOWED_TRANSITIONS` und `_TERMINAL_STATUSES` (`:91-94`) kennen die Reset-Statuswechsel nicht.

Reale Anknuepfungspunkte fuer den Purge (FIX-THE-MODEL: vorhandene Owner konsumieren, keine zweite Wahrheit). **Wichtig: die beiden FK-53-Purge-Schritte haben unterschiedliche Owner und duerfen nicht vermengt werden.**

**Schritt 5 — operativer Runtime-State (§53.7.5: Execution / Governance-Laufzeitreste / PhaseState / Locks+Leases):**
- **Es gibt heute keinen einheitlichen `purge_run(...)`-Owner fuer den kanonischen Runtime-Execution-State.** `src/agentkit/phase_state_store/store.py` (Owner von `FlowExecution`/`NodeExecutionLedger`, `phase_state_store/models.py:22-53`) besitzt **keine** Purge-/Delete-fuer-Story-Surface (kein `purge_run`, kein `delete_for_story`). Der Runtime-Execution-/Governance-Purge-Port ist damit **noch nicht vorhanden** und muss als getypte Outgoing-Schnittstelle benannt werden (kein erfundenes Roh-DELETE an einem fremden Owner vorbei; fehlt der Owner, fail-closed melden — siehe Scope 2.1.5 + Cross-Story).
- **Locks/Leases haben einen realen, eigenen Owner:** `src/agentkit/state_backend/store/lock_record_repository.py:184` — `LockRecordRepository.deactivate_locks_for_story(story_id)` (fail-closed bei unbekannter Story, idempotent bei bereits INACTIVE). Aggregiert wird das ueber `src/agentkit/governance/runner.py:265` — `Governance.deactivate_locks(story_id) -> DeactivationResult` (Lock-Deaktivierung + Lock-Export-/Edge-Bundle-Entfernung). Das ist der autoritative Lock-/Lease-Purge-Owner — **nicht** `projection_repositories`.
- **`PhaseStateProjectionRepository.purge_run(...)`** (`projection_repositories.py:196`) deckt nur die **Projektion** `phase_state_projection` ab (Read-Model-Sicht, FK-39 §39.7), nicht den kanonischen PhaseState-Runtime-Owner. Es ist damit Teil von Schritt 6 (abgeleitete Sicht), nicht der Runtime-Quelle.

**Schritt 6 — Read-Models + Analytics (§53.7.6: FK-69-Read-Models / `fact_story` / periodische Aggregationen):**
- `src/agentkit/state_backend/store/projection_repositories.py:75/113/149/196` — fuer die **FK-69-Projektions-/Read-Model-Familien** existiert ein typisierter `purge_run(project_key, story_id, run_id) -> int` (`QAStageResultsRepository`/`QAFindingsRepository`/`StoryMetricsRepository`/`PhaseStateProjectionRepository`; analog `RiskWindowRepository.purge_run`, `:176`). Das ist der autoritative **Read-Model-/Projektions**-Purge-Owner. Schritt 6 dockt **hier** an, statt eigenes DELETE zu erfinden — aber nur fuer den abgeleiteten Read-Model-Anteil.
- Die **Read-Model-/`fc_*`-Purge-Kette** (welche Tabellen ueber den Run-Scope hinaus wie geleert werden) wird von **AG3-081** geschlossen; **`purge_story_analytics`/Recompute periodischer Aggregationen** ist **AG3-082** (siehe Out-of-Scope + Dependencies). AG3-071 ist hier nur **Ausloeser** und konsumiert die dort definierten Purge-/Recompute-Schnittstellen unter ihrem autoritativen Namen.

**Idempotenz-/Claim-Muster fuer den Reset-Record:**
- `src/agentkit/control_plane/records.py:49-89` — `ControlPlaneOperationRecord` (leased, owner-scoped, idempotent ueber `op_id`/`operation_kind`/`status`) ist der vorhandene Idempotenz-/Claim-Mechanismus fuer administrative Mutationen. Der Reset-Record/Resume-Punkt orientiert sich an diesem Muster bzw. nutzt es (kein paralleler Hidden-Claim).

**Status-Owner:**
- `src/agentkit/story_context_manager/service.py:97` — `_check_transition` ist der Status-Owner der Story; `RESETTING`/`RESET_FAILED` und die zugehoerigen erlaubten Uebergaenge gehoeren in dieses Modell (`_ALLOWED_TRANSITIONS`, `:80`), nicht in einen Schattenstatus.

**Kontext-Konflikt-Check (zwei harte Trennungen):**
1. **Reset ist kein `Cancelled`.** FK-53 §53.6/§53.8 haelt die Story als fachliche Einheit am Leben (restartbar), waehrend `Cancelled` terminal ist (`_TERMINAL_STATUSES`, `service.py:91-94`). `RESETTING`/`RESET_FAILED` sind administrative Zwischenstati, **kein** `terminal_state`. **Bekannter Konzept-Drift:** FK-91 §91 (`91_api_event_katalog.md:311`) fuehrt noch ein Event `story_cancelled_administratively` „ueber Split, Exit oder Reset … auf `Cancelled` gesetzt". Das widerspricht FK-53 fuer den Reset-Pfad. AG3-071 emittiert/setzt fuer Reset **kein** `Cancelled`; der FK-91-Widerspruch wird als doc-only-Nachzug an den FK-91-Owner geroutet (siehe Cross-Story-Voraussetzungen) — **nicht** im AG3-071-Code-Cut umgangen.
2. **Eskalation ist Befund, nicht Status.** Der typische Vorzustand (FK-53 §53.4) ist eine eskalierte/festsitzende Umsetzung. Im echten `StoryStatus` gibt es **kein** `ESCALATED`; Eskalation lebt im Run-/Phase-/Audit-Kontext. Die Eingangsbedingung wird daher als **Eskalations-/Ausnahmebefund aus Runtime-/Audit-Artefakten** nachgewiesen, nicht als Story-Stammdatenstatus. Der Story-Statuswechsel ist `StoryStatus.IN_PROGRESS -> RESETTING`.

## 2. Scope

### 2.1 In Scope
1. **`StoryResetService` (story-lifecycle-BC)** mit mindestens dem Vertrag aus §53.10: `request_reset(...)`, `execute_reset(reset_id)`, `resume_reset(reset_id)`, `verify_reset_clean_state(reset_id)` (FK-53 §53.10 = „mindestens diese"; weitere interne Schritte/Ports erlaubt). Reine Orchestrierung des Admin-Flows; Seiteneffekte ueber getypte Ports/Repositories.
2. **Reset-Record (`reset_id`)** als typisiertes, dauerhaft auditierbares Modell mit mindestens den §53.5-Feldern: `project_key`, `story_id`, `reset_id`, `requested_by`, `reason`, `escalation_ref`, `requested_at`, `status`. `status`-Werte mindestens `started`/`completed`/`failed` (englisch). Idempotenz-/Resume-Anker; an das `ControlPlaneOperationRecord`-Muster angelehnt (kein zweiter Hidden-Claim).
3. **CLI `agentkit reset-story`** in `cli/main.py` als Subparser + Handler, Pflichtparameter `--story`/`--reason`, optional `--escalation-ref`/`--dry-run`/`--force`. `--dry-run` fuehrt **keine** destruktive Mutation aus, berichtet aber die geplanten Purge-Domaenen. Der Befehl ist der **einzige** Ausloeser (kein automatischer Pfad).
4. **Status-Erweiterung am Story-Modell:** `RESETTING` und `RESET_FAILED` als administrative Story-Stati (am vorhandenen `StoryStatus`/`_check_transition`-Owner, nicht als Schattenfeld) inklusive erlaubter Uebergaenge:
   - `StoryStatus.IN_PROGRESS -> RESETTING` (regulaerer Reset-Start; ein Eskalations-/Ausnahmebefund aus Runtime-/Audit-Artefakten ist getrennt nachzuweisen — **kein** `StoryStatus.ESCALATED` als Quelle).
   - `RESETTING` → restartbarer Grundzustand (`IN_PROGRESS`/Backlog-Aequivalent gemaess Status-Owner) bei Erfolg.
   - `RESETTING -> RESET_FAILED` bei Abbruch.
   - `RESET_FAILED -> RESETTING` (Resume desselben Vorgangs).
   `RESET_FAILED` ist **nicht runnable** (Guard/Service blockiert Start/Resume/Retry/Scheduler-Aufnahme); `RESETTING`/`RESET_FAILED` sind **kein** `terminal_state`.
5. **8-Schritt-Flow (§53.7) in fester Reihenfolge**, jeder Purge-Schritt **konvergent/idempotent** (loeschen wenn vorhanden, ignorieren wenn weg, hart nur bei echten Infra-/Berechtigungsfehlern). **Schritt 5 und Schritt 6 sind getrennte Purge-Domaenen mit getrennten Ownern:**
   - Schritt 2 (fence) **vor** jeder Loeschung: exklusiver Reset-Lock + Story `RESETTING` + Blockade neuer Starts/Resumes/Retries/Scheduler-Aufnahmen.
   - **Schritt 5 — operativer Runtime-State (§53.7.5):** purgt Execution/Governance-Laufzeitreste/kanonischen PhaseState **sowie** Locks/Leases ueber **getypte Runtime-Purge-Ports**:
     - Locks/Leases: vorhandener Owner `Governance.deactivate_locks(story_id)` (`runner.py:265`) bzw. `LockRecordRepository.deactivate_locks_for_story` (`lock_record_repository.py:184`).
     - Execution/Governance-Laufzeit/kanonischer PhaseState: ueber einen **getypten Outgoing-Port** des `phase_state_store`-/Runtime-Owners. Existiert dieser Purge-Port noch nicht (Ist-Zustand: `phase_state_store/store.py` hat keine Purge-Surface), gilt **fail-closed** — die Owner-Schnittstelle wird als Vertrag benannt/erwartet und das Fehlen gemeldet (Cross-Story), **statt** eine zweite Purge-Wahrheit oder ein Roh-DELETE am fremden Owner vorbei aufzubauen.
   - **Schritt 6 — Read-Models + Analytics (§53.7.6):** purgt die FK-69-Read-Model-Anteile ueber die vorhandenen `purge_run(...)`-Owner in `projection_repositories` (qa_stage_results/qa_findings/story_metrics/phase_state_projection/risk_window) und ruft fuer den Rest die von **AG3-081** definierte Read-Model-/`fc_*`-Purge-Kette sowie den **AG3-082**-`purge_story_analytics`-/Recompute-Pfad auf. Per-Story-gebundene Zeilen werden geloescht; periodische Aggregationen werden ueber den AG3-082-Owner gezielt neu berechnet/ersetzt (hier nur **Ausloesen** + per-Story-Loeschen ueber die fremden Owner — kein direktes Tabellen-DELETE).
   - Schritt 8 (Worktree/Branch) entfernt/entkoppelt den tainted Worktree; ein Story-Branch bleibt hoechstens forensischer Referenzstand, nie aktive Runtime-Basis.
6. **Idempotenz + Fehlerzustand (§53.9):** gleiche `reset_id` = Resume (kein neuer Reset). Bei Abbruch bleibt die Story administrativ blockiert (`RESET_FAILED`), nur gezielter Resume desselben Vorgangs ist erlaubt. Reset-Lock-Freigabe **erst** nach erfolgreichem Purge aller Domaenen (Schritt 5 **und** 6) + `verify_reset_clean_state` + Record `completed`.
7. **Reset-Purge-Ausloeser-Vertrag zu den Schritt-6-Ownern (Read-Model/Analytics):** der Service ruft die getypten Purge-/Recompute-Schnittstellen der zustaendigen BCs (AG3-081 Read-Model-/`fc_*`-Kette, AG3-082 `purge_story_analytics`) auf; keine zweite Wahrheit, kein direktes Tabellen-DELETE an einem fremden Owner vorbei. Sind diese Schnittstellen (Mergestand) noch nicht vorhanden, gilt fail-closed: melden statt eine zweite Purge-Wahrheit aufzubauen.
8. **Negativ-/Phasengrenz-Tests** (siehe AC): Vorbedingungen, Idempotenz, `RESET_FAILED`-not-runnable, Endzustand-Verifikation, getrennte Schritt-5/Schritt-6-Port-Aufrufe.

### 2.2 Out of Scope (mit Owner)
- **Kanonische Runtime-Execution-Purge-Surface am `phase_state_store`-Owner** (`FlowExecution`/`NodeExecutionLedger`/Attempt/Override/GuardDecision-Purge) — soweit dieser getypte Purge-Port noch nicht existiert, ist seine **Definition/Persistenzhaelfte** nicht Teil dieses Cuts; AG3-071 **konsumiert** ihn als getypten Outgoing-Vertrag und meldet fail-closed, wenn er fehlt (siehe Cross-Story-Voraussetzungen). Kein Roh-DELETE-Ersatz in dieser Story.
- **Read-Model-/`fc_*`-Schema-/Purge-Ketten-Definition** (welche Tabellen wie geloescht werden) — **AG3-081** (Reset-Purge-Kette der `fc_*`/Read-Models). Dieser Service konsumiert die dort definierten Purge-Ketten.
- **Recompute periodischer Analytics-Aggregationen** nach Purge — `purge_story_analytics`/RefreshWorker bei **AG3-082**; hier nur Ausloesen + per-Story-Loeschen.
- **FK-91-Konzept-Drift** (`story_cancelled_administratively` setzt Reset auf `Cancelled`, widerspricht FK-53) — doc-only-Nachzug am FK-91-Owner **AG3-103** (Konzept-Nachzug: interne FK-Widersprueche, u. a. FK-91). AG3-071 schliesst den `Cancelled`-Pfad fuer Reset im Code aktiv aus.
- **Offizieller Servicepfad-Verdict `ALLOW_VIA_OFFICIAL_SERVICE_PATH` / `is_official_service_path`** — **AG3-087** (FK-55). Hier wird der bereits reservierte Branch-Guard-Pfad genutzt; das positive Servicepfad-Verdict ist nicht in dieser Story durchzusetzen.
- **Operator-CLI-Sammeloberflaeche** (`run-phase`/`resume`/`reset-escalation`/`cleanup`/`status`) — **AG3-076** dockt nur an; der hier gebaute Service bleibt der Owner der Reset-Logik.
- **`StorySplitService`** (Split statt Reset) — **AG3-072** (FK-54): Split haelt die Auditspur als gueltig, Reset macht sie fachlich ungueltig.

## 3. Akzeptanzkriterien
1. `StoryResetService` existiert mit mindestens den vier Vertragsoperationen aus §53.10 (`request_reset`/`execute_reset`/`resume_reset`/`verify_reset_clean_state`); jede ist typisiert und ohne stillen Default. Die public API umfasst diese vier; interne Schritte/Ports sind erlaubt (FK-53 §53.10 „mindestens diese").
2. `agentkit reset-story --story X --reason "..."` ist in `cli/main.py` registriert, Pflichtparameter erzwungen; `--dry-run` fuehrt **keine** destruktive Mutation aus und listet die geplanten Purge-Domaenen (Test).
3. Eingangsbedingungen (§53.4) werden fail-closed geprueft: nicht existierende Story / kein nachgewiesener Eskalations-/Ausnahmebefund (aus Runtime-/Audit-Artefakten, **nicht** aus einem Story-Stammdatenstatus) / konkurrierende Admin-Operation → Reset abgelehnt (je ein Negativtest).
4. Reset-Flow haelt die §53.7-Reihenfolge: **fence (Status `RESETTING`) vor jeder Loeschung** (Test, der bei einem injizierten Purge-Fehler nachweist, dass die Story bereits `RESETTING`/geblockt ist und nicht still resumebar bleibt).
5. **Schritt 5 (Runtime-Purge, §53.7.5) konsumiert die Runtime-Purge-Ports** — Locks/Leases ueber `Governance.deactivate_locks` / `LockRecordRepository.deactivate_locks_for_story`, Execution/Governance-Laufzeit/kanonischen PhaseState ueber den getypten Runtime-Purge-Port (fail-closed, wenn der Owner-Port fehlt) — und ruft **kein** FK-69-`projection_repositories.purge_run` als Runtime-Owner auf (Test/Assertion ueber die aufgerufenen Ports; Negativ-Assertion, dass Schritt 5 nicht ueber Read-Model-Repos purgt).
5b. **Schritt 6 (Read-Models/Analytics, §53.7.6) konsumiert die abgeleiteten Owner** — die vorhandenen `purge_run(...)` der FK-69-`projection_repositories` (qa_stage_results/qa_findings/story_metrics/phase_state_projection/risk_window) **plus** die AG3-081-Read-Model-/`fc_*`-Purge-Kette und den AG3-082-`purge_story_analytics`-Pfad; kein direktes Tabellen-DELETE an fremden Ownern vorbei (Test/Assertion ueber die aufgerufenen Ports). Fehlen AG3-081/AG3-082-Schnittstellen am Mergestand: fail-closed gemeldet, kein Ersatz-DELETE.
6. `verify_reset_clean_state(reset_id)` belegt den Endzustand (§53.8): kein laufender/resumierbarer Run, keine aktiven Locks/Leases, keine Read-Model-/Analytics-Reste der korrupten Umsetzung, kein tainted Worktree, Reset-Nachweis vorhanden; Story als fachliche Einheit erhalten (Test).
7. Idempotenz: zweiter Lauf mit derselben `reset_id` ist ein Resume (kein neuer Reset, keine Doppel-Purge-Fehler); ein bereits geloeschtes Objekt fuehrt nicht zu hartem Fehler (Test).
8. `RESET_FAILED` ist **nicht runnable**: Start/Resume/Retry/Scheduler-Aufnahme einer `RESET_FAILED`-Story wird fail-closed blockiert; nur `resume_reset` desselben Vorgangs ist erlaubt (Negativtest).
9. Reset-Lock wird **erst** nach erfolgreichem Purge aller Domaenen (Schritt 5 **und** 6) + `verify_reset_clean_state` + Record `completed` freigegeben (Test).
10. `RESETTING`/`RESET_FAILED` sind administrative Stati und werden **nicht** mit `terminal_state=Cancelled` (AG3-074) verwechselt; der Reset-Pfad emittiert/setzt **kein** `Cancelled` (Gegenbeleg zum FK-91-Drift `story_cancelled_administratively`); die Story bleibt restartbar (Test).
11. **Pflichtbefehle gruen:** pytest unit/integration/contract (in Chunks, `-n0`); mypy default + `--platform linux`; ruff; vier Konzept-Gates (`scripts/ci/check_concept_frontmatter.py`, `scripts/ci/compile_formal_specs.py`, `scripts/ci/check_concept_code_contracts.py`, `scripts/ci/check_architecture_conformance.py`); Coverage >= 85 %.

## 4. Definition of Done
- AK 1–11 erfuellt; giftige Codex-Review PASS; (Implementierung/Commit erst nach Execution-Plan-Freigabe — diese Story wird zunaechst nur autorisiert/reviewt).

## 5. Guardrail-Referenzen
- **FAIL-CLOSED:** unklare/unvollstaendige Vorbedingungen, mittendrin gescheiterter Reset und `RESET_FAILED` blockieren jeden normalen Neustart; fehlende Owner-Purge-Ports (Schritt 5 Runtime, Schritt 6 AG3-081/082) werden gemeldet, nicht durch Ersatz-DELETEs umgangen; keine grosszuegige Toleranz.
- **FIX-THE-MODEL / SINGLE SOURCE OF TRUTH:** keine verdeckte Schattenkopie des Runtime-State als stiller Rueckweg (§53.7.4); Schritt 5 ueber die echten Runtime-/Lock-Owner (`Governance.deactivate_locks`, getypter `phase_state_store`-Runtime-Purge-Port), Schritt 6 ueber die FK-69-`projection_repositories.purge_run`-Owner + AG3-081/082-Schnittstellen — **keine** Vermengung von Runtime- und Read-Model-Purge; `RESETTING`/`RESET_FAILED` am echten Story-Status-Owner.
- **ZERO DEBT:** keine Attrappe; der Service purgt real und verifiziert den Endzustand; kein „spaeter sauber machen". Wo ein fremder Purge-Owner (Runtime-Port / AG3-081 / AG3-082) noch nicht gemerged ist, wird die Luecke als harte Cross-Story-Voraussetzung gemeldet, nicht still ueberbrueckt.
- **TYPISIERT STATT STRINGS:** Reset-Record, `reason`/`status`, Purge-Domaenen typisiert; kein String-/Flag-Geflecht.
- **ARCH-55:** alle neuen Identifier/Enum-Werte/Wire-Keys/CLI-Optionen/DB-Spalten englisch (Story-Prosa darf deutsch bleiben).

## 6. Cross-Story-Voraussetzungen (harte Abhaengigkeiten)
- **AG3-081** — Read-Model-/`fc_*`-Reset-Purge-Kette (Schritt 6). AG3-071 konsumiert diese Kette; ohne sie ist Schritt 6 nur teilweise (FK-69-`projection_repositories`-Anteil) abdeckbar und der Rest fail-closed zu melden.
- **AG3-082** — `purge_story_analytics`/RefreshWorker-Recompute (Schritt 6, periodische Aggregationen). AG3-071 loest nur aus.
- **Runtime-Execution-Purge-Port** am `phase_state_store`-/Runtime-Owner (`FlowExecution`/`NodeExecution`/Attempt/Override/GuardDecision/kanonischer PhaseState, Schritt 5): existiert heute **nicht** als Purge-Surface. Wird AG3-071 vor dessen Bereitstellung implementiert, ist Schritt 5 ueber die Locks/Leases hinaus fail-closed zu melden — diese Owner-Schnittstelle ist eine genuine Cross-Story-/Owner-Voraussetzung (keine Story im Index liefert sie heute explizit; ggf. als neuer Schnitt zu klaeren, **nicht** AG3-081/082 zuschreiben — deren Scope ist Read-Model/Analytics, nicht kanonischer Runtime-Execution-State).
- **AG3-103** (doc-only) — FK-91-`story_cancelled_administratively`-Widerspruch zu FK-53 (Reset ≠ Cancelled) als Konzept-Nachzug. AG3-071 schliesst den `Cancelled`-Pfad im Code bereits aus.

## 7. Hinweise fuer den Sub-Agent
- Read T:/codebase/claude-agentkit3/CLAUDE.md first — all project rules apply to you.
- Kritische Anknuepfungspunkte, **getrennt nach Purge-Schritt**:
  - Schritt 5 (Runtime): `Governance.deactivate_locks` (`governance/runner.py:265`) / `LockRecordRepository.deactivate_locks_for_story` (`lock_record_repository.py:184`) fuer Locks/Leases; getypter Runtime-Purge-Port am `phase_state_store` fuer Execution/Governance/PhaseState (fehlt heute — fail-closed melden, kein Roh-DELETE).
  - Schritt 6 (Read-Model/Analytics): `projection_repositories.purge_run(...)` (`projection_repositories.py:75/113/149/176/196`) fuer die FK-69-Anteile; AG3-081-Read-Model-/`fc_*`-Kette + AG3-082-`purge_story_analytics` fuer den Rest.
  - `ControlPlaneOperationRecord` (`control_plane/records.py:49-89`) als Idempotenz-/Claim-Muster fuer Reset-Record/Resume.
  - `story_context_manager/service.py` `_check_transition`/`_ALLOWED_TRANSITIONS` (`:80`,`:97`) + `StoryStatus` (`story_model.py:34-46`) als Status-Owner — `RESETTING`/`RESET_FAILED` dort, nicht als Schattenfeld.
  - `branch_guard.py:25`/`operations.py:168` (offizieller Pfad bereits reserviert — nicht doppeln).
- Fallstrick: **Runtime-Purge (Schritt 5) NICHT ueber `projection_repositories` verkaufen** — diese Repos decken nur FK-69-Read-Models/Projektionen ab (`purge_run` ist dort der Read-Model-Purge, nicht der Runtime-Purge). Locks haben ihren eigenen Owner (`deactivate_locks_for_story`).
- Fallstrick: Reset ist **kein** `Cancelled`. Verwechsle die administrative Reset-Statusachse nicht mit der Ergebnisachse `terminal_state` (AG3-074). Story bleibt restartbar. Kein `StoryStatus.ESCALATED` einfuehren — Eskalation als Befund aus Runtime-/Audit-Artefakten nachweisen, Statuswechsel `IN_PROGRESS -> RESETTING`.
- Fallstrick: Recompute der periodischen Analytics gehoert NICHT hierher (AG3-082); Read-Model-/`fc_*`-Purge-Kette gehoert AG3-081. Nur Auslösen + per-Story-Purge ueber die fremden Owner. Wenn diese Owner-Schnittstellen noch nicht definiert/gemerged sind, melden statt eine zweite Purge-Wahrheit aufzubauen.
- AK2 NICHT veraendern. `.mcp.json` NICHT anfassen. **Kein Commit** ohne expliziten Auftrag.
- „done" nur mit Beleg: Diff-Zusammenfassung, gruene Pflichtbefehle (genaue Ausgaben), Test-Namen (Vorbedingungen, Idempotenz, `RESET_FAILED`-not-runnable, Endzustand-Verifikation, getrennte Schritt-5/Schritt-6-Port-Aufrufe).

---

## Globale Akzeptanzkriterien (verbindlich)

Zusaetzlich zu den obigen Akzeptanzkriterien gelten die **globalen Akzeptanzkriterien**
aus `stories/_GLOBAL_ACCEPTANCE.md` (Single Source of Truth):

- **GAC-1:** `scripts/ci/check_architecture_conformance.py` laeuft mit **0 Errors**
  (Exit 0, fail-closed) — `PYTHONPATH=src .venv\Scripts\python scripts/ci/check_architecture_conformance.py`.
- **GAC-2:** Die Architektur-Guardrails `guardrails/architecture-guardrails.md`
  (ARCH-NN) werden eingehalten; Konflikt = hart stoppen und melden.
