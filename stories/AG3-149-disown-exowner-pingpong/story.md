# AG3-149 — Disown-Baustein + Ex-Owner-Verhalten + Ping-Pong-Schranke: vereinheitlichte Entzugspfade (Exit/Reset/Split), Record-Status-Pflege, Ablösung der Exit-Fence

- **Typ:** implementation
- **Größe:** M
- **depends_on:** [AG3-148] — der Disown-Baustein verallgemeinert exakt die
  Entzugs-Mechanik, die der Transfer-Vollzug in AG3-148 erstmals produktiv
  ausübt (Audit mit Grund, Binding-Revocation, Edge-Tombstone,
  deterministische Reconcile-Antwort); Ex-Owner-Verhalten, Ping-Pong-Schranke
  und die Ausnahme für Self-Rebind setzen existierende Transfers,
  Challenges und die Approval-Queue voraus (GAP §4: ST-07a → ST-07b).
- **Quell-Konzept:** FK-56 §56.13h (Disown-Baustein), §56.13c (Wirkung auf
  den Ex-Owner; Ex-Owner-Edge-Quarantäne), §56.13d (Ping-Pong-Schranke),
  §56.13g (Recovery/Self-Rebind ohne Mitzeichnung), §56.7a
  (`binding_invalid`-Gründe als Attribut); FK-55 §55.8.3 (Entmündigung
  analog `conflict_freeze`), §55.8.4 (Ping-Pong als Capability-Regel);
  FK-53 §53.7.3 (Reset-Quiesce ohne Leases/Heartbeats), §53.7.3a
  (Reset-Disown + `status=reset`); FK-54 §54.8.2a (Split nutzt den
  Disown-Baustein — Disown-Anteil); FK-58 §58.2a (Abgrenzung Exit vs.
  Transfer), §58.6 (Exit-Disown + `status=ended`); FK-17 §17.7a
  (aktive `SessionRunBinding` in der Reset-Purge-Domäne);
  `formal.operating-modes.invariants` →
  `disowned_session_cannot_immediately_reclaim`,
  `historical_ownership_records_are_never_admission_evidence`
- **Herkunft:** GAP-Analyse Session-Ownership v4 (`_temp/gap-analyse-session-ownership.md`),
  Story-Kandidat GAP-ST-07b; normative Basis Commits 3ae011e4 / 1bb4ed8a / 58c190b7
  (+ Decision-Records unter `concept/_meta/decisions/`).

## Kontext / Problem

FK-56 §56.13h verlangt EINEN Disown-Baustein für alle vier offiziellen
Entzugspfade (Transfer, Exit, Reset, Split): Audit mit Grund,
Owner-Notification beim nächsten Kontakt, Edge-Tombstone, deterministische
Reconcile-Antwort. Heute existieren nur pfadspezifische Fragmente (am Code
verifiziert 2026-07-02):

- **Exit hat einen partiellen, exit-spezifisch verdrahteten Disown:**
  `_commit_fence` (`story_exit/service.py:191`), `_administratively_cancel`
  (:197), `_commit_teardown` (:198, Definition :514 — deaktiviert Locks +
  Bindung, KEIN physischer Worktree-Teardown), `deactivate_locks` (:199),
  `binding_revoked=True` (:212, `exit_status="binding_revoked"` :566);
  serverseitige Tombstones über die Bundle-Assemblierung
  (`control_plane/runtime.py:1573`). Nichts davon ist als
  wiederverwendbarer Baustein geschnitten.
- **Reset entwertet fremde Bindungen nicht disown-konform:** die
  Quiesce-/Purge-Ports existieren (`story_reset/service.py`:
  Runtime-/Read-Model-Purge-Ports :152/:176, `deactivate_locks`-Aufruf
  :504, Purges :449/:510/:519 — gap-02 nannte :166 für `deactivate_locks`;
  das ist die Port-Definition, der Aufruf liegt bei :504), aber es gibt
  keine Owner-Notification, keine deterministische Reconcile-Antwort und
  keine Record-Status-Pflege. (Hinweis: die konzeptseitigen
  Lease-/Heartbeat-Formulierungen sind bereits bereinigt; der Code kennt
  ohnehin keine Ownership-Leases am Reset-Pfad.)
- **Split entwertet Bindungen als Nebeneffekt:** `_run_split_to_completion`
  quiesct die Steuer-Runtime und deaktiviert Locks
  (`story_split/service.py:312-315`), ohne Disown-Semantik für eine fremde
  aktive Bindung (Audit-Grund, Reconcile-Antwort, Tombstone).
- **Record-Status-Pflege fehlt vollständig:** kein Beendigungspfad schreibt
  `status='ended'|'reset'|'split'` auf den `run_ownership_records`-Eintrag
  (Tabelle + Enum aus AG3-137; der AG3-148-Transfer-Vollzug ist dagegen
  ein In-Place-CAS, bei dem der Record `status='active'` bleibt —
  `transferred` hat in diesem Strang keinen Writer, FK-56 §56.8a).
  Genau daran hängt der **Übergabepunkt aus AG3-142**:
  AG3-142 hat nur die **positive** committed-op-Admission abgelöst; die
  **Exit-Fence-Negativprüfung**
  (`has_committed_story_exit_operation_for_run`,
  `control_plane/runtime.py:1078` in `_run_admission_evidence` :1051-1092)
  besteht als Übergangsschutz weiter, BIS diese Story die
  Record-Status-Pflege vollendet. Danach ist die Admission ausschließlich
  record-basiert; historische Records sind nie Admission-Evidenz.
- **Ping-Pong-Schranke fehlt:** die Capability-Enforcement kennt keine
  disowned-Regel (`governance/principal_capabilities/enforcement.py`
  konsultiert nur `is_frozen` :424); ein soeben entmündigter Ex-Owner
  könnte sofort einen Rück-Takeover anfragen und (menschlich bestätigt)
  vollziehen.
- **Ex-Owner-Edge-Verhalten fehlt:** der Edge kennt nach AG3-142 den
  `binding_invalid`-Grund `ownership_transferred`, aber kein
  Quarantäne-Verhalten beim Reconcile (Grep `takeover|contested|quarantine`
  über `src/agentkit/harness_client/`: null Treffer); lokale nicht-gepushte
  Reste des Ex-Owners blieben unbehandelt im Worktree liegen.

Ohne diese Story bleiben Exit/Reset/Split Ad-hoc-Varianten mit stillen
Fehlversuchen für den Ex-Owner, die Admission trägt dauerhaft die
committed-op-Übergangskrücke, und AG3-150 (Freeze-Familie) sowie AG3-155
(Runbook) haben keinen vereinheitlichten Entzugs-Vertrag.

## Scope

### In Scope

1. **Wiederverwendbarer Disown-Baustein** (SOLL-081): eine Komponente, die
   alle vier offiziellen Entzugspfade nutzen — Transfer (AG3-148-Vollzug
   wird auf den Baustein umgestellt), Exit, Reset, Split. Leistungsumfang:
   Audit-Eintrag mit maschinenlesbarem Grund (Grund-Vokabular je Pfad,
   analog `ownership_transferred` aus dem AG3-137-Schema),
   Binding-Revocation, Edge-Tombstone (bestehende
   `tombstone_worktree_roots`-Mechanik), deterministische
   Reconcile-Antwort für den Ex-Owner beim nächsten Kontakt
   (Owner-Notification — dieselbe klare, maschinenlesbare Auskunft auf
   jedem Pfad statt stiller Fehlversuche).
2. **Exit nutzt den Baustein + `status='ended'`** (SOLL-089): die
   exit-spezifische Verdrahtung (:191-:212) wird auf den Baustein
   umgestellt; der committete Exit setzt den aktiven Record auf
   `status='ended'` (Audit-Fakt). Abgrenzung bleibt normativ sichtbar:
   Exit beendet den Run → `ai_augmented`; Transfer führt ihn fort
   (FK-58 §58.2a — Verhaltens-Beweis über die Testpaare).
3. **Ablösung der Exit-Fence (Vollendung von IMPL-021):** mit der
   Record-Status-Pflege entfällt die Negativprüfung
   `has_committed_story_exit_operation_for_run` (`runtime.py:1078`)
   ersatzlos; `_run_admission_evidence` bzw. sein AG3-142-Nachfolger
   entscheidet ausschließlich über den aktiven Ownership-Record.
   Historische Records (`ended`/`reset`/`split`/`transferred`/`closed`)
   admittieren nie (`historical_ownership_records_are_never_admission_evidence`).
4. **Reset nutzt den Baustein** (SOLL-082, SOLL-083 Verhaltens-Anteil,
   SOLL-084, SOLL-085): hält eine fremde Session zum Reset-Zeitpunkt die
   aktive Bindung, entwertet der Reset sie über den Disown-Baustein; der
   Ex-Owner erhält die deterministische Reconcile-Antwort. Der Record wird
   **nicht gelöscht**, sondern wechselt auf `status='reset'` — reiner
   Audit-Fakt, nie Admission-Evidenz, blockiert die Neuaufnahme nicht
   (Verhaltens-Anteil; das Enum/Schema kommt aus AG3-137). Der Reset
   quiesct In-Flight-Operationen (servereigene, instanzgebundene Claims
   über die AG3-138/141-Flächen), Retry-/Resume-Mechanismen und
   story-bezogene Queue-/Timer-Einträge — es gibt keine Ownership-Leases
   oder Heartbeats (SOLL-084). Die aktive `SessionRunBinding` gehört zur
   Reset-Purge-Domäne (SOLL-085, FK-17 §17.7a).
5. **Split nutzt den Baustein** (SOLL-088): der Split entwertet aktive
   fremde Bindungen über den Disown-Baustein und setzt den Record auf
   `status='split'`. Der Split bleibt Beendigungspfad, **kein
   Hintertür-Takeover** — wer die Umsetzung fortführen will, nimmt den
   offiziellen Transfer (AG3-148). (Der Umbau der Split-Fence auf einen
   Admin-Freeze ist **AG3-150**.)
6. **Ex-Owner-Verhalten nach Transfer** (SOLL-033 Disown-Verhaltens-Anteil,
   SOLL-153): beim nächsten Kontakt (Bundle-Sync/Resolve/Mutation) erhält
   der Ex-Owner deterministisch die `ownership_transferred`-Auskunft —
   kein stiller Rückfall auf `ai_augmented`, keine stillen Fehlversuche
   (Fehlerbild-Anteil kam mit AG3-142; hier der vollständige
   Notification-/Reconcile-Fluss). Der Ex-Owner-Edge **quarantäniert beim
   Reconcile lokale nicht-gepushte Reste lokal**: atomarer
   Verzeichnis-Move/-Copy in die lokale Quarantäne-Ablage (nie
   `git stash`), auditiert als lokales Ereignis; **nichts davon geht ans
   Backend**. Die Quarantäne-Mechanik baut **diese Story** als
   eigenständiges Edge-Modul `harness_client/projectedge/quarantine.py`;
   AG3-151 nutzt es für den Neu-Owner-Reconcile (Kante
   AG3-151 ← AG3-149 existiert; eine Mechanik, zwei Aufrufer — keine
   zweite Implementierung).
7. **Ping-Pong-Schranke als Capability-Regel** (SOLL-035, SOLL-036):
   `disowned_session_cannot_immediately_reclaim` — die entmündigte Session
   kann nicht unmittelbar per Confirm zurückübernehmen; ein erneuter
   Transfer derselben Story kurz darauf erfordert einen privilegierten
   Principal (`human_cli`/`admin_service`) und Begründung. Durchsetzung
   capability-seitig (governance) UND am Confirm-Pfad (deterministisches
   `403`); die Takeover-Historie ist bereits Challenge-Bestandteil
   (AG3-148) — wiederholtes Entreißen ist sichtbarer Governance-Verstoß,
   kein technisches Wettrennen.
8. **Entmündigung capability-seitig analog `conflict_freeze`** (SOLL-037):
   die disowned Session verliert jede storybezogene
   Mutationsberechtigung — ausdrücklich auch `complete_phase`/`fail_phase`/
   Closure; Reads einschließlich `op_id`-Rekonsiliierung bleiben erlaubt.
   Auflösung nur über offizielle Pfade (erneuter Transfer, Neubindung nach
   Run-Ende), nie durch Zeitablauf oder erneute Aktivität. Anders als
   `conflict_freeze` ist die Entmündigung **kein Story-Freeze**: die Story
   bleibt unter dem neuen Owner voll arbeitsfähig.
9. **Self-Rebind-Ausnahme** (SOLL-091): Recovery-/Self-Rebind-Fälle, in
   denen **dieselbe Harness-Identität** ihre eigene verwaiste Arbeit
   wieder aufnimmt, benötigen keine menschliche Mitzeichnung — als Regel
   im Request-/Approval-Pfad (kein Approval-Queue-Zwang für Self-Rebind),
   auditiert. (Das `recover-story`-Kommando selbst ist **AG3-154**.)
10. **Umstellung der Fence-Sicht-Quelle (AG3-144):** ist die
    materialisierte Run-Status-/Fence-Sicht aus AG3-144 bereits gelandet,
    wird ihre Quelle der Exit-/Reset-/Split-Freiheit von der
    Übergangsquelle committed-Exit-Ops auf die Record-Status
    (`ended`/`reset`/`split`) umgestellt; die Exit-Ops-Übergangsquelle
    wird entfernt (kein Doppelpfad).

### Out of Scope (mit Owner)

- **Transfer-Endpoints, Challenge/Confirm, Approval-Queue, atomarer
  Vollzug** (In-Place-CAS, Record bleibt `active`; Revocation der
  Alt-Bindung + Tombstone): **AG3-148**.
- **Freeze-Zustände als Admission-Blocker** (`freeze_epoch`,
  Challenge-Invalidierung bei Freeze-Eintritt, Split-Fence → Admin-Freeze):
  **AG3-150**. Diese Story liefert den Disown-Anteil des Splits, nicht die
  Saga-/Freeze-Modellierung.
- **Neu-Owner-Reconcile, Reprovisionierung, die vier Guard-Zustände,
  `takeover-reconcile-worktree`, Exit-Worktree-Schicksal (SOLL-079)**:
  **AG3-151** (die hier geschnittene Quarantäne-Mechanik wird dort
  wiederverwendet).
- **Push-Doppel-Sperre** (Edge-Push-Gate + Ref-Schutz — die zweifache
  Push-Abweisung des Ex-Owners): **AG3-147**; hier wird nur der
  Reconcile-/Quarantäne-Anteil von SOLL-153 gebaut.
- **TTL-/Lease-Rückbau** (`_CLAIM_LEASE_TTL`-Familie): **AG3-139**.
- **Frontend-Anzeige** (Overlay, Cockpit, Takeover-Historie-UI): **AG3-153**;
  **CLI/Edge-Tool-Kommandos + echtes `recover-story`**: **AG3-154**;
  **Betriebs-Runbook**: **AG3-155**.

## Betroffene Dateien

| Datei | Änderungsart | Zweck |
|---|---|---|
| `src/agentkit/backend/control_plane/disown.py` | neu | Disown-Baustein: Grund-Vokabular je Pfad, Record-Status-Übergänge (`ended`/`reset`/`split` — `transferred` hat keinen Writer, AG3-137), Notification-/Reconcile-Antwort-Regeln — Blutgruppe A |
| `src/agentkit/backend/control_plane/runtime.py` | ändern | Exit-Fence-Negativprüfung (:1078) entfernen — Admission ausschließlich record-basiert; Baustein-Aufrufe der Beendigungspfade; deterministische Reconcile-Antwort im Sync-/Resolve-Pfad |
| `src/agentkit/backend/story_exit/service.py` | ändern | Exit-Disown auf den Baustein umstellen (:191-:212, :514-:566); Record → `status='ended'` im committeten Exit |
| `src/agentkit/backend/story_reset/service.py` + `bootstrap/story_reset_adapters.py` | ändern | Reset-Disown fremder aktiver Bindungen; Record → `status='reset'`; Bindung in der Purge-Domäne; In-Flight-Quiesce über die AG3-138/141-Flächen |
| `src/agentkit/backend/story_split/service.py` | ändern | Disown fremder aktiver Bindungen in der Saga (:312-315-Umfeld); Record → `status='split'` (Fence-Umbau: AG3-150) |
| `src/agentkit/backend/control_plane/ownership_transfer.py` (aus AG3-148) | ändern | Transfer-Vollzug konsumiert den Baustein statt eigener Inline-Disown-Schritte (eine Mechanik, vier Aufrufer) |
| `src/agentkit/backend/governance/principal_capabilities/enforcement.py` (+ Regel-/Matrix-Daten) | ändern | Entmündigung analog `conflict_freeze` (storybezogene Mutationsrechte entzogen, Reads erlaubt); Ping-Pong-Regel `disowned_session_cannot_immediately_reclaim` |
| `src/agentkit/backend/control_plane/records.py`, `repository.py`, `state_backend/postgres_store.py` + `store/facade.py` | ändern | Status-Übergangs-Row-Funktionen (transaktional mit dem jeweiligen Beendigungs-Commit), soweit nicht von AG3-137-Repositories gedeckt |
| `src/agentkit/harness_client/projectedge/quarantine.py` | neu | Atomare lokale Quarantäne-Ablage (Verzeichnis-Move/-Copy, nie `git stash`), lokales Audit-Ereignis — von AG3-151 wiederverwendbares Modul |
| `src/agentkit/harness_client/projectedge/runtime.py`, `client.py` | ändern | Ex-Owner-Reconcile-Verhalten: `ownership_transferred`-Auskunft verarbeiten, lokale nicht-gepushte Reste quarantänieren, nichts ans Backend melden |
| `tests/unit/**`, `tests/integration/**`, `tests/contract/**` | neu/ändern | Baustein-Einheitlichkeits-Pins, Status-Pflege je Pfad, Exit-Fence-Ablösungs-Regression, Ping-Pong-/Entmündigungs-Negativpfade, Edge-Quarantäne-Tests |

## Akzeptanzkriterien

1. **Baustein-Einheitlichkeit:** alle vier Entzugspfade (Transfer, Exit,
   Reset, Split) erzeugen dieselbe strukturierte Disown-Auskunft
   (Audit-Eintrag mit Grund, Binding-Revocation, Edge-Tombstone,
   deterministische Reconcile-Antwort) — contract-gepinnt; die
   exit-spezifische Inline-Verdrahtung ist ersetzt (Code-Beweis: genau ein
   Baustein, vier Aufrufer).
2. **Record-Status-Pflege:** nach echtem Exit trägt der Record
   `status='ended'`, nach Reset `'reset'`, nach Split `'split'` (jeweils
   über den echten Vorgängerpfad erzeugt, nicht präpariert); Records werden
   nie gelöscht; ein historischer Record admittiert an keinem Regime-Pfad
   (Negativtest je Status an der Phasengrenze).
3. **Exit-Fence-Ablösung:** `has_committed_story_exit_operation_for_run`
   wird von keiner Admission mehr aufgerufen (Code-Beweis); die
   AG3-142-Regression „keine Re-Admission nach Exit" bleibt grün — jetzt
   ausschließlich über `status='ended'` (fail-closed, kein
   Übergangs-Doppelpfad mehr).
4. **Reset-Disown:** ein Reset gegen eine fremde aktive Bindung entwertet
   sie über den Baustein; der Ex-Owner erhält beim nächsten Kontakt die
   deterministische Reconcile-Antwort; die aktive `SessionRunBinding` ist
   Teil der Purge-Domäne; eine Neuaufnahme der Story nach Reset startet
   gegen sauberen Zustand — der `reset`-Record blockiert nicht
   (Positivtest Setup nach Reset).
5. **Reset-Quiesce:** eine laufende In-Flight-Operation der Story wird beim
   Reset deterministisch quiesct (servereigener, instanzgebundener Claim —
   keine Wanduhr-Semantik); nach dem Quiesce ist keine neue Mutation des
   alten Runs mehr möglich (Negativtest an der Phasengrenze).
6. **Split-Disown, kein Hintertür-Takeover:** ein Split einer Story mit
   fremder aktiver Bindung entwertet die Bindung über den Baustein; die
   entwertete Session ist danach an Quelle UND Nachfolgern nicht
   mutationsberechtigt, ohne den offiziellen Transfer (Negativtest).
7. **Ex-Owner-Reconcile + Quarantäne (SOLL-153):** nach echtem Transfer
   liefert der nächste Edge-Kontakt deterministisch die
   `ownership_transferred`-Auskunft; der Edge verschiebt lokale
   nicht-gepushte Reste atomar in die lokale Quarantäne-Ablage (Beweis:
   kein `git stash`-Aufruf im Codepfad), auditiert das als lokales
   Ereignis, und **kein** Byte davon erreicht das Backend (Negativtest:
   kein Upload-/Melde-Codepfad; Bundle-Sync-Payload enthält keine
   Quarantäne-Inhalte).
8. **Ping-Pong-Schranke:** ein unmittelbares Rück-Confirm der disowned
   Session wird deterministisch mit `403` abgewiesen (Capability-Regel,
   contract-gepinnt); ein erneuter Transfer derselben Story kurz darauf
   gelingt nur mit privilegiertem Principal + Begründung (beide
   Negativpfade einzeln getestet; die Schranke ist Regel, keine Konvention
   — Code-Beweis: Durchsetzung in der Capability-Schicht, nicht nur im
   Handler).
9. **Entmündigung analog `conflict_freeze`:** die disowned Session verliert
   alle storybezogenen Mutationsrechte inkl. `complete`/`fail`/Closure
   (enforcement- UND HTTP-Pfad getestet); Reads inkl.
   `GET operations/{op_id}` bleiben erlaubt; eine vorgerückte Uhr oder
   erneute Aktivität löst den Zustand nicht (Negativtest); die Story
   selbst bleibt unter dem neuen Owner mutierbar (kein Story-Freeze,
   Positivtest).
10. **Self-Rebind-Ausnahme:** dieselbe Harness-Identität re-bindet ihre
    eigene verwaiste Arbeit ohne menschliche Freigabe und ohne
    Approval-Queue-Eintrag (auditiert); eine fremde Identität fällt
    nachweislich nicht unter die Ausnahme (Negativtest fail-closed).
11. **Fence-Sicht-Quellen-Umstellung:** die materialisierte
    Run-Status-/Fence-Sicht (AG3-144, falls gelandet) bezieht die
    Exit-/Reset-/Split-Freiheit ausschließlich aus den Record-Status
    (`ended`/`reset`/`split`); die committed-Exit-Ops-Übergangsquelle ist
    entfernt (Code-Beweis: kein Aufrufer mehr; die AG3-144-Fence-Tests
    bleiben grün — jetzt record-basiert).
12. Coverage ≥ 85 % gehalten; `mypy` strict (inkl. `--platform linux`) und
    `ruff` ohne neue Ausnahmen; ARCH-55 (englische Bezeichner,
    Grund-Vokabular, Wire-Keys).

## Definition of Done

- Alle Akzeptanzkriterien erfüllt; Gate-Suite grün (`pytest -n0`
  unit/integration/contract, Coverage ≥ 85, `mypy src` + `--platform linux`,
  `ruff`, 4 Konzept-Gates).
- Codex-Review PASS.
- Auf `origin/main` gemerged; `status.yaml` → `completed` (Vorbedingung für
  AG3-150 und AG3-155); README-Backlog-Snapshot (§6.7) nachgezogen.

## Abdeckung (Traceability)

**Deckt ab:** SOLL-033 (Disown-Verhaltens-Anteil), SOLL-035–037, SOLL-081, SOLL-082, SOLL-083 (Verhaltens-Anteil), SOLL-084, SOLL-085, SOLL-088, SOLL-089, SOLL-091, SOLL-153.

## Konzept-Referenzen

- FK-56 §56.13h (Disown-Baustein: Audit mit Grund, Owner-Notification beim
  nächsten Kontakt, Edge-Tombstone, deterministische Reconcile-Antwort —
  „dieselbe klare, maschinenlesbare Auskunft statt stiller Fehlversuche")
- FK-56 §56.13c (Wirkung auf A: `binding_invalid` mit
  `ownership_transferred`, kein stiller Rückfall; Reads erlaubt; „A's Edge
  quarantäniert beim nächsten Kontakt lokale nicht-gepushte Reste lokal,
  auditiert als lokales Ereignis; nichts davon geht ans Backend"),
  §56.13d (Ping-Pong-Schranke), §56.13g (Recovery/Self-Rebind derselben
  Harness-Identität ohne menschliche Mitzeichnung), §56.7a
  (`binding_invalid` trägt den Grund als Attribut)
- FK-55 §55.8.3 (Entmündigung wirkt capability-seitig analog
  `conflict_freeze`; kein Story-Freeze; Auflösung nur über offizielle
  Pfade), §55.8.4 (Ping-Pong-Schranke als Capability-Regel; formal
  `operating-modes.invariant.disowned_session_cannot_immediately_reclaim`)
- FK-53 §53.7.3 (Reset quiesct In-Flight-Operationen/Retry/Resume/Queue —
  keine Ownership-Leases/Heartbeats), §53.7.3a (Reset-Disown über den
  Baustein; Record → `status=reset`, Audit-Fakt, blockiert Neuaufnahme
  nicht)
- FK-54 §54.8.2a (Split entwertet fremde Bindungen über den Disown-Baustein;
  Beendigungspfad, kein Hintertür-Takeover — der Saga-/Freeze-Anteil liegt
  in AG3-150)
- FK-58 §58.2a (Exit beendet den Run → `ai_augmented`; Transfer führt ihn
  fort; beide explizit/auditiert, keiner aus Stille), §58.6 (Exit-Disown
  über den Baustein; Record → `status=ended`)
- FK-17 §17.7a (aktive `SessionRunBinding` in der Reset-Purge-Domäne;
  Record wird nicht entfernt, sondern `status=reset`)
- `formal.operating-modes.invariants` →
  `disowned_session_cannot_immediately_reclaim`,
  `historical_ownership_records_are_never_admission_evidence`

## Guardrail-Referenzen

- **FIX THE MODEL, NOT THE SYMPTOM:** ein Baustein für vier Pfade statt
  vier Ad-hoc-Varianten; die Exit-Fence-Krücke wird durch die
  Record-Status-Wahrheit **ersetzt**, nicht daneben weitergepflegt.
- **ZERO DEBT:** der in AG3-142 explizit deklarierte Übergangsschutz
  (`runtime.py:1078`) wird hier planmäßig abgelöst — kein Liegenlassen des
  Doppelpfads; die Ablösung ist Akzeptanzkriterium, nicht Absichtserklärung.
- **FAIL-CLOSED:** historische Records admittieren nie; unbekannte
  Disown-Gründe führen zu `binding_invalid`; die Self-Rebind-Ausnahme gilt
  nur für die nachgewiesen selbe Identität.
- **SINGLE SOURCE OF TRUTH:** der Record-Status ist die eine
  Beendigungs-Wahrheit; die Quarantäne-Mechanik existiert genau einmal
  (ein Edge-Modul, wiederverwendet von AG3-151).
- **Testing-Guardrails:** jeder Beendigungspfad wird über den echten
  Vorgängerpfad erzeugt (kein manuell zusammengesetzter State); gültige
  UND ungültige Übergänge (Re-Admission je historischem Status,
  Rück-Confirm, fremde Identität im Self-Rebind) sind verprobt.

## Querschnitts-Auflagen

- **K5 Postgres-only:** die Status-Übergänge laufen auf den
  Postgres-only-Tabellen aus AG3-137 über die sanktionierte
  `state_backend.store`-Fassade (fail-closed via
  `_require_postgres_control_plane_backend`, `control_plane/runtime.py:2119`);
  diese Story legt keine neuen Tabellen an — sollte die
  Notification-Persistenz doch eine brauchen, ist sie Postgres-only.
  Contract-/Integrationstests über die Postgres-Fixture, Unit-Tests über
  Ports/Fakes.
- **Blutgruppen-Klassifikation**
  (`concept/methodology/software-blutgruppen.md`): Disown-Baustein
  (Grund-Vokabular, Status-Übergänge, Reconcile-Antwort-Regeln,
  Ping-Pong-/Entmündigungs-Regeln) = **A**; Wire-/HTTP-/Event-Mapper =
  **R**; transaktionale Status-Row-Funktionen im `state_backend` = **AT/T**;
  Edge-Quarantäne (`quarantine.py`, Dateisystem-Move/-Copy) = **T** mit
  dünner **R**-Audit-Schicht. Der A-Kern bleibt AT-frei.
- **Bundle-Assets:** Keine betroffen (verifiziert:
  `bundles/target_project/tools/agentkit/projectedge.py` delegiert an den
  `harness_client` — das Ex-Owner-Reconcile-/Quarantäne-Verhalten liegt
  vollständig in der Bibliothek; die Agent-Kommandos für
  Takeover/Abort/Recover liegen in **AG3-154**).
