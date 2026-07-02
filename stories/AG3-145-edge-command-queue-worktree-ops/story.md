# AG3-145 — Edge-Command-Queue + Worktree-Ops-Umzug: Auftrags-Endpoints (Ack/Result), `provision_worktree`/`teardown_worktree`/`preflight_probe`, Marker-Materialisierung dev-lokal, `workspace_locator` als reiner State-Anker

- **Typ:** implementation
- **Größe:** L
- **depends_on:** [AG3-137, AG3-141, AG3-142, AG3-146]
  - **AG3-137** — die Command-Record-Persistenz baut auf dem
    Persistenz-Fundament auf (additive Postgres-Schema-Präzedenz,
    Postgres-only-Muster), und der Preflight-Entscheid „legitim übernommen"
    liest den aktiven `run_ownership_records`-Eintrag plus
    `takeover_transfer_records.takeover_base_sha` (GAP §4: ST-01 → ST-14a,
    „Command-Record-Persistenz").
  - **AG3-141** — der mutierende `POST .../commands/{command_id}/result`-Pfad
    läuft über den Objekt-Claim-Mechanismus aus AG3-141: der
    Result-Anwendungs-Pfad erwirbt vor Anwendung den Story-Objekt-Claim
    (Review-Kante Schritt e).
  - **AG3-142** — der Abschluss-Commit eines Command-Results ist nach
    FK-91 §91.1b/Regel 15 gegen den **aktiven Ownership-Record** gefenct;
    die Fence-Fläche (Record-Evidenz, Ex-Owner-Fehlerbild,
    `ownership_transferred`-Payload) entsteht in AG3-142 (GAP §4:
    ST-06 → ST-14a, Review-v4-Finding 2).
  - **AG3-146** — die serverseitige `ls-remote`-Ref-Lesefläche für den
    Preflight-Entscheid kommt aus dem Provider-Adapter (AG3-146); diese
    Story baut keine eigene Übergangs-Lesefläche.
- **Quell-Konzept:** FK-91 §91.1b (Command-Queue: Endpoints, Auftragsarten,
  Result-Typen); FK-10 §10.2.4a (Topologie-Regel, Akteursmodell,
  Ausführungsort-Grundsatz, workspace_locator-Trennung), §10.4.2
  (Teardown als Edge-Auftrag), §10.5.3 (Provisionierungs-Idempotenz);
  FK-22 §22.3.1 (Checks 7/8 als Edge-Probe, differenzierte Befunde),
  §22.6.2/§22.6.3 (`setup_worktrees` beauftragt Edge, Pfade Edge-gemeldet);
  FK-12 §12.5 (setup/teardown als Edge-Aufträge, Signaturen = fachliche
  Mechanik); FK-36 §36.6.3 (Marker `.agentkit-story.json` dev-lokal durch
  den Edge; Identitätsanker); FK-91 §91.1a Regeln 5/13/15/16
- **Herkunft:** GAP-Analyse Session-Ownership v4
  (`_temp/gap-analyse-session-ownership.md`), Story-Kandidat GAP-ST-14a;
  normative Basis Commits 3ae011e4 / 1bb4ed8a / 58c190b7 (+ Decision-Records
  unter `concept/_meta/decisions/`, insb.
  `2026-07-02-k1-worktree-topologie.md`).

## Kontext / Problem

FK-10 §10.2.4a normiert: Worktrees leben dev-lokal; physische
Worktree-Operationen führen ausschließlich der Agent oder der Project Edge
(beauftragt, meldend) aus; backend-seitige Subprocess-Git-Zugriffe,
physische Pfadableitungen und Governance-Writes in Worktrees sind
**Fehlbetrieb**. Heute ist das Backend durchgängig der physische Akteur
(alle Anker am Code verifiziert 2026-07-02):

- **Es gibt kein Auftrag/Meldung-Muster.** Der Edge kennt nur Bundle-Sync
  und Mutations-Calls: `control_plane_http/app.py` routet
  `/v1/project-edge/sync` (:757) und `GET operations/{op_id}` (:64, :684);
  Command-Records, Ack- oder Result-Endpoints existieren nirgends (Grep
  `commands`/`command_id` in `src/agentkit/`: keine Wire-Treffer).
- **Setup provisioniert backend-seitig:** `setup_worktrees`/`setup_worktree`
  (`governance/setup_preflight_gate/worktree.py:41/:131`) rufen
  `utils.git.create_worktree` (`backend/utils/git.py:58`) im
  Backend-Prozess auf; Aufrufer ist der Setup-Phase-Handler
  (`setup_preflight_gate/phase.py:562-599`, Aufruf :575), der
  `worktree_path`/`worktree_map` aus **backend-abgeleiteten** Pfaden baut
  (:585-593) — das Gegenteil von SOLL-191 (Pfade Edge-gemeldet).
- **Marker backend-seitig:** `write_story_marker`
  (`worktree.py:108-128`) schreibt `.agentkit-story.json` in den Worktree —
  laut FK-36 §36.6.3 materialisiert ihn der Edge im
  `provision_worktree`-Auftrag (SOLL-138).
- **Preflight 7/8 sind Backend-Git + Sammel-FAIL:** Check 7 probt per
  `git show-ref` im Backend (`setup_preflight_gate/preflight.py:104-123`
  via `utils.git.branch_exists`); `no_story_branch.py:36-45` und
  `no_stale_worktree.py` liefern je EINEN undifferenzierten FAIL („Branch
  of an unfinished prior run exists") — ohne Ownership-Kontext, ohne
  Unterscheidung „stale fremd" vs. „legitim übernommen", ohne den Befund
  `local_stale_or_dirty_takeover_target` (FK-22 §22.3.1 verlangt benannte,
  unterscheidbare Befunde).
- **Teardown/Detach backend-seitig:** Reset-Detach ruft
  `utils.git.remove_worktree` direkt
  (`bootstrap/story_reset_adapters.py:230-235`; Port
  `story_reset/service.py:201`, Aufruf :535); der Setup-Failure-Cleanup
  importiert `remove_worktree` (`setup_preflight_gate/phase.py:50`).
- **Backend als Pfad-Autorität:** `StateBackendWorktreeRepository`
  (`state_backend/store/worktree_repository.py:21-62`) leitet physische
  Worktree-Pfade aus `StoryContext.worktree_map` ab; Konsument ist die
  Governance-Deaktivierung, die **physisch in Worktrees schreibt**
  (`governance/runner.py:494-519`: `.agent-guard/lock.json` löschen,
  `.agent-guard/mode.json` schreiben; Port `governance/repository.py:368-372`).
- **`workspace_locator` trägt die verbotene Doppelrolle:** `project_root`
  ist dokumentiert „canonical run store / **worktree anchor**"
  (`control_plane/workspace_locator.py:39-49`, Kommentar :106-109) und muss
  als Verzeichnis **auf dem Backend-Host existieren** (:181) — exakt die
  Kopplung, die FK-10 §10.2.4a ersatzlos abschafft (SOLL-137).
- **`worktree_roots` sind nicht Edge-gemeldet:** Der Edge prüft
  `session.worktree_roots` beim Resolve (`harness_client/projectedge/
  runtime.py:230-236`), aber die Roots stammen aus backend-abgeleiteten
  Setup-Pfaden, nicht aus einer Edge-Meldung.

**Tragfähig:** Die dev-lokale `.agent-guard`-Projektion existiert bereits
Edge-seitig — der Edge schreibt Lock-Exports in `worktree_roots` und räumt
`tombstone_worktree_roots` auf (`harness_client/projectedge/
client.py:370-383`). Der op_id-Reconcile-Weg (`GET operations/{op_id}`)
und die Postgres-only-Mechanik (AG3-137, `_require_postgres_control_plane_
backend`, `control_plane/runtime.py:2119`, Check :2139) tragen.

Ohne diese Story fehlt AG3-147 (sync_push), AG3-151 (takeover_reconcile),
AG3-152 (merge_local) und AG3-154 (Edge-Tool) die Trägerschicht.

## Scope

Der GAP erwartet für dieses Fundament einen **internen Schnitt**: EIN
Story-Paket, umgesetzt in nummerierten Teilschritten mit eigener
Reihenfolge und Zwischen-Verifikation (nach jedem Teilschritt: Gate-Suite
grün auf dem Zwischenstand).

### In Scope

**Teilschritt A — Command-Queue-Fundament (Backend):**

1. **Tabelle `edge_command_records`** (Postgres-only, K5): Identität
   `command_id`; Zuordnung `(project_key, story_id, run_id, session_id)`;
   `command_kind`, typisiertes Payload, Lifecycle-Status (mindestens
   angelegt/zugestellt/abgeschlossen/gescheitert), Zustell-Quittung (Ack),
   Result-Referenz, Zeitstempel, `ownership_epoch`-Stempel der Anlage.
   **Kein Wanduhr-Verfall**: offene Aufträge enden nie per TTL (sinngemäß
   FK-91 §91.1a Regel 16) — sie bleiben sichtbar offen. [SOLL-165]
2. **`GET /v1/project-edge/story-runs/{run_id}/commands`**: offene
   Aufträge der **eigenen Session** abrufen; der Abruf quittiert die
   Zustellung (Ack); Read — nimmt keine Sperren (Regel 13). [SOLL-166]
3. **`POST /v1/project-edge/commands/{command_id}/result`**: Ergebnis
   melden; **client-beigestelltes `op_id` ist Pflicht** (Regel 5 — kein
   Server-Minting, unabhängig vom BC-weiten Vertrag aus AG3-140);
   Serialisierungsobjekt `(project_key, story_id)` (Regel 13) — der
   Result-Anwendungs-Pfad erwirbt vor Anwendung den Story-Objekt-Claim
   über den AG3-141-Helper; der
   Abschluss-Commit ist nach Regel 15 gegen den **aktiven
   Ownership-Record** gefenct (AG3-142-Fläche): Ex-Owner-/Epoch-Drift-
   Results werden deterministisch abgewiesen. [SOLL-167]
4. **Auftragsarten- und Result-Typ-Vokabular** (typisiert, contract-gepinnt):
   alle sechs Auftragsarten `provision_worktree`, `teardown_worktree`,
   `preflight_probe`, `sync_push`, `takeover_reconcile`, `merge_local`
   [SOLL-168]; Result-Typen `branch_ref_report`, `push_status_report`,
   `worktree_report` (inkl. `worktree_roots`) sowie Quarantäne-
   Ergebnisdetails; die Takeover-Fehlerbilder
   (`remote_branch_diverged_after_takeover`,
   `local_stale_or_dirty_takeover_target`, `contested_local_writes`) als
   **benannte Result-Zustände** im Wire-Vokabular [SOLL-169].
   Ausgeführt werden in dieser Story nur `provision_worktree`,
   `teardown_worktree`, `preflight_probe`; die übrigen Arten sind
   registriert, ihre Beauftragung/Ausführung liegt in AG3-147/151/152 —
   ein Edge, der eine ihm unbekannte Auftragsart erhält, meldet
   deterministisch ein Fehler-Result (kein stiller No-op).

**Teilschritt B — Edge-seitige Kommando-Ausführung:**

5. **Command-Loop im Harness-Client** (`harness_client/projectedge/`):
   Aufträge der eigenen Session abrufen, ausführen, Result mit eigenem
   `op_id` melden; Executor für `provision_worktree` (Git-Mechanik
   dev-lokal nach FK-12 §12.5.1 inkl. **Marker-Materialisierung**
   `.agentkit-story.json`, SOLL-138/139; `.agent-guard`-Export weiter über
   die bestehende Bundle-Publikation), `teardown_worktree` (FK-12 §12.5.3,
   idempotent nach FK-10 §10.5.3) und `preflight_probe` (je teilnehmendem
   Repo: Branch-Klasse + Head-SHA; lokale Worktree-Lage inkl.
   Marker-Inhalt und Pfad — reine Erhebung, keine Entscheidung).
6. **Bundle-Asset**: `bundles/target_project/tools/agentkit/projectedge.py`
   erhält die Edge-seitige Kommando-Ausführung (Abruf/Ausführung/Meldung
   im Rahmen der bestehenden Phasen-Kommandos bzw. als eigener
   Einstiegspunkt — Design dieser Story). **Abgrenzung:** die
   Agent-Kommandos für Takeover/Abort/Recover sind AG3-154, nicht hier.

**Teilschritt C — Setup-Umzug (Provisionierung + Preflight):**

7. **`setup_worktrees` beauftragt den Edge** je teilnehmendem Repo
   (`provision_worktree`); das `WorktreeResult` inklusive des physischen
   Pfads kommt als `worktree_report` zurück; die gemeldeten Pfade sind die
   `worktree_roots` der Session (FK-56 §56.8), `StoryContext.worktree_map`
   wird aus der **Meldung** befüllt; das Backend leitet keine physischen
   Pfade mehr ab. Der Setup-Ablauf wird auftragsgetrieben: ohne
   gemeldetes Ergebnis schließt die Setup-Phase nicht ab (fail-closed
   Blockade, kein Timeout-Weiter — offene Aufträge sind sichtbar).
   [SOLL-191, SOLL-134/135/136-Durchsetzung]
8. **Preflight 7/8 als Edge-Probe + Backend-Entscheid** [SOLL-192, 193]:
   Checks 7/8 konsumieren das `preflight_probe`-Ergebnis; die
   **Entscheidung trifft das Backend** mit Ownership-Kontext (aktiver
   Ownership-Record, Transfer-Record) und verifiziert die Remote-Lage des
   Story-Branch per Ref-Read — nie per eigenem Worktree-Git-Subprocess.
   Der Ref-Read konsumiert die serverseitige `ls-remote`-Lesefläche des
   Provider-Adapters aus AG3-146 (Netz-Protokoll, kein physischer
   Repo-Zugriff — von FK-10 §10.2.4a(b) ausdrücklich gedeckt); diese Story
   baut keine eigene Übergangs-Lesefläche.
   **Differenzierte Befunde statt Sammel-FAIL:** benannte, unterscheidbare
   Befunde mindestens für: stale lokaler Branch (fremder Run), lokal
   voraus, falscher Marker/falsche Story, fremder Worktree,
   Remote-Divergenz, `local_stale_or_dirty_takeover_target`. Check 7
   unterscheidet **„stale fremd"** (FAIL, Mensch entscheidet) vs.
   **„legitim übernommen"** (aktiver Ownership-Record der eigenen Session
   **plus** Ausrichtung auf `takeover_base_sha` aus dem Transfer-Record →
   PASS).

**Teilschritt D — Teardown-/Detach-Umzug + Pfad-Autoritäts-Rückbau:**

9. **Teardown als Edge-Auftrag** [SOLL-188, 194]: Reset-Detach
   (`story_reset_adapters.py:230-235`) und der Setup-Failure-Cleanup
   beauftragen `teardown_worktree` statt selbst zu löschen; die
   Worktree-Beseitigung ist ein nachlaufender, sichtbar offener
   Edge-Auftrag (die Quiesce-/Reset-Semantik von FK-53 bleibt unberührt;
   der Reset blockiert nicht auf die physische Beseitigung, der offene
   Auftrag bleibt auditierbar).
10. **`StateBackendWorktreeRepository` außer Betrieb**: die
    Governance-Deaktivierung schreibt nicht mehr physisch in Worktrees
    (`governance/runner.py:494-519` entfällt backend-seitig); die
    dev-lokale `.agent-guard`-Projektion läuft vollständig über den
    bestehenden Edge-Mechanismus (Bundle-Publikation + serverseitige
    `tombstone_worktree_roots`, `client.py:370-383`).
11. **`workspace_locator`-Trennung** [SOLL-137]: `project_root` wird
    reiner backend-lokaler State-Anker (Run-Store/`story_dir`-Persistenz);
    die Worktree-Anker-Rolle entfällt ersatzlos (Docstrings/Kommentare
    :39-49/:106-109 einschließlich der veralteten FK-01-§1.1a-Begründung
    bereinigt); kein Konsument leitet physische Worktree-Pfade daraus ab.

**Teilschritt E — Ausführungsort-Konformanz-Schließung:**

12. **Konformanz-Nachweis SOLL-136**: Die in dieser Story umgezogenen
    Backend-Fundstellen sind beseitigt (Grep-Beleg als Test/Review-
    Artefakt); die **verbleibenden** backend-seitigen Git-Fundstellen sind
    exakt die den Nachbar-Stories zugeordneten (siehe Inventar in
    „Betroffene Dateien"): Closure-Merge-Block → AG3-152, Push-/QA-Grenz-
    Evidenz → AG3-147. `utils/git.py` behält übergangsweise nur die von
    AG3-152 noch konsumierten Primitiven (`multi_repo_saga.py:19`,
    `pre_merge_runner/scan_runner.py:116-118`).

### Out of Scope (mit Owner)

- **`sync_push`-Ausführung, Push-Barrieren, Push-Gate, Push-Frische,
  Ref-Schutz, Dienst-Identität** sowie die Umstellung der Push-/QA-Grenz-
  Evidenz (`branch_checks.py`, `system_evidence.py`,
  `qa_cycle/fingerprint.py`, `evidence/request_resolver.py`): **AG3-147**.
- **`merge_local`-Ausführung + Closure-Git-Block** (`merge_sequence.py`,
  `multi_repo_saga.py`, `closure/runtime_ports.py`-Git-Reads,
  Sonar-Tree-Binding) inkl. Closure-Teardown-Aufruf: **AG3-152**.
- **`takeover_reconcile`-Ausführung** (Quarantäne-Mechanik, SHA-Abgleich,
  die vier Guard-Zustände als Verhalten): **AG3-151**.
- **Provider-Adapter-Schnittstelle, gh-Kapselung** (stellt die
  `ls-remote`-Ref-Lesefläche, die der Preflight-Entscheid konsumiert):
  **AG3-146**.
- **Job-Muster/202/Ergebnisarten/`stale_observation`**: **AG3-144** (die
  Command-Queue nutzt ihr eigenes Result-Fencing nach Regel 15; die
  generische Ergebnisart-Registry ist nicht Voraussetzung).
- **BC-weiter Client-op_id-Vertrag** (Minten-Rückbau an Bestandsrouten):
  **AG3-140** — die neuen Command-Routen werden von Anfang an
  client-op_id-pflichtig gebaut.
- **Edge-Tool-Kommandos Takeover/Abort/Recover**: **AG3-154**.

## Betroffene Dateien

| Datei | Änderungsart | Zweck |
|---|---|---|
| `src/agentkit/backend/state_backend/postgres_schema.sql` + `postgres_store.py` + `store/facade.py` (+ `_public_api_names.py`, `__init__.pyi`, `mappers.py`) | ändern | Tabelle `edge_command_records` (Postgres-only), Row-Funktionen, Fassaden-Loader/-Saver |
| `src/agentkit/backend/control_plane/edge_commands.py` | neu | Command-Kind-/Result-Typ-Vokabular, Command-/Result-Records, Preflight-Entscheidungslogik (differenzierte Befunde) — Blutgruppe A |
| `src/agentkit/backend/control_plane/records.py`, `repository.py` | ändern | Command-Repository-Ports; Anbindung Ownership-/Transfer-Read für den Preflight-Entscheid |
| `src/agentkit/backend/control_plane/runtime.py` | ändern | Command-Anlage (Setup/Reset), Result-Finalisierung mit Regel-15-Fence, Ack-Verbuchung |
| `src/agentkit/backend/control_plane/models.py` | ändern | Wire-Modelle GET commands / POST result (client-op_id Pflicht, `min_length=1`, **kein** `default_factory`-Minting) |
| `src/agentkit/backend/control_plane_http/app.py` | ändern | Neue Routen `GET .../story-runs/{run_id}/commands`, `POST .../commands/{command_id}/result` (analog Project-Edge-Gruppe :64/:757) |
| `src/agentkit/backend/governance/setup_preflight_gate/worktree.py` | ändern | Backend-Git raus (`create_worktree`/`branch_exists`/`remove_worktree`, Import :17); fachliche Provisionierungslogik wandert in den Edge-Executor; Marker-Write (:108-128) entfällt backend-seitig |
| `src/agentkit/backend/governance/setup_preflight_gate/phase.py` | ändern | `_setup_worktrees_if_needed` (:562-599) auftragsgetrieben; `worktree_map` aus Edge-Meldung; `remove_worktree`-Import (:50) raus |
| `src/agentkit/backend/governance/setup_preflight_gate/preflight.py` + `preflight_checks/no_story_branch.py` + `no_stale_worktree.py` | ändern | `_default_branch_exists` (:104-123) raus; Checks 7/8 konsumieren Edge-Probe + Ownership-Kontext; differenzierte Befunde statt Sammel-FAIL |
| `src/agentkit/backend/bootstrap/story_reset_adapters.py` | ändern | Reset-Detach (:230-235) → `teardown_worktree`-Auftrag |
| `src/agentkit/backend/governance/runner.py` + `governance/repository.py` | ändern | Physische Worktree-Writes der Deaktivierung (:494-519) raus; `WorktreeRepository`-Port (:368-372) entfällt |
| `src/agentkit/backend/state_backend/store/worktree_repository.py` | löschen | `StateBackendWorktreeRepository` (Pfadableitung :21-62) außer Betrieb |
| `src/agentkit/backend/control_plane/workspace_locator.py` | ändern | Rollen-Schnitt: reiner State-Anker; Worktree-Anker-Doku (:39-49/:106-109) bereinigt |
| `src/agentkit/backend/utils/git.py` | ändern | Backend-Nutzung auf AG3-152-Restkonsumenten eingegrenzt (`create_worktree`/`branch_exists` ohne Backend-Aufrufer) |
| `src/agentkit/harness_client/projectedge/client.py`, `runtime.py` (+ neues Executor-Modul) | ändern/neu | Command-Abruf (Ack), Executor provision/teardown/preflight_probe, Result-Meldung mit eigenem op_id; Marker-Materialisierung dev-lokal |
| `src/agentkit/bundles/target_project/tools/agentkit/projectedge.py` | ändern | Edge-seitige Kommando-Ausführung im deployten Tool (Abgrenzung: keine Takeover-/Abort-/Recover-Kommandos — AG3-154) |
| `tests/unit/**`, `tests/integration/**`, `tests/contract/**` | neu/ändern | Endpoint-/Fence-/Ack-Tests, Setup-/Preflight-/Teardown-Integrationstests (Postgres-Fixture), Contract-Pins des Wire-Vokabulars |

**Ausführungsort-Inventar (SOLL-136; verbleibende Backend-Fundstellen →
Nachbar-Stories):**

| Fundstelle | Befund | Ziel-Story |
|---|---|---|
| `closure/multi_repo_saga.py:76-95` (`SubprocessGitBackend`), `:147` (`push_story_branches`), `:191` (`local_ff_merge_with_rollback`), `:264` (`push_main`), `:324` (`teardown_worktrees`) | Closure-Git-Sequenz backend-seitig | AG3-152 |
| `closure/merge_sequence.py:858-885` (Lock/`locked_sha`), `:753-754`/`:1061-1078` (CAS), `:1213` (Teardown), `:1255` (Rollback) | Merge-Block backend-seitig | AG3-152 |
| `closure/runtime_ports.py:112-181` (Fast-Sanity-Git), `:367-386` (`_read_final_diff`) | Closure-Git-Reads | AG3-152 |
| `verify_system/pre_merge_runner/scan_runner.py:116-118` (`tree_hash_of_commit`), `verify_system/sonarqube_gate/runtime_wiring.py:238/:286-298` (Worktree-HEAD-Reads) | Scan-/Attestation-Binding im Merge-Block | AG3-152 |
| `bootstrap/composition_root.py:2886-2928` (`SubprocessGitBackend`-Wiring) | Closure-Wiring | AG3-152 |
| `verify_system/structural/checks/branch_checks.py:173-201` (`check_completion_push`), `structural/system_evidence.py:44-87` (`ChangeEvidence`), `bootstrap/composition_root.py:1345-1373/:1229/:2297` (Subprocess-Provider) | Phasen-Abschluss-/Push-Evidenz lokal erhoben | AG3-147 |
| `verify_system/qa_cycle/fingerprint.py` (git diff --stat, :43 ff.), `verify_system/evidence/request_resolver.py:196-210` (Diff-Expansion) | QA-/Review-Grenz-Evidenz lokal | AG3-147 |

## Akzeptanzkriterien

1. **Endpoints + Ack-Semantik:** `GET .../story-runs/{run_id}/commands`
   liefert die offenen Aufträge der eigenen Session und quittiert die
   Zustellung; der Read nimmt keine Sperren/Claims. Eine fremde Session
   erhält die Aufträge nicht (Session-Scope-Negativtest, fail-closed).
2. **Result-Vertrag:** `POST .../commands/{command_id}/result` ohne
   client-`op_id` wird mit strukturiertem Fehler abgewiesen (kein
   Server-Minting); der Abschluss läuft story-serialisiert — der
   Result-Anwendungs-Pfad erwirbt vor Anwendung den Story-Objekt-Claim
   über den AG3-141-Helper (Test pinnt den Helper-Aufruf); ein Result zu
   einem unbekannten `command_id` oder ein Doppel-Abschluss wird
   deterministisch abgewiesen (Idempotenz über op_id-Reconcile).
3. **Regel-15-Fencing:** Ein Result einer Session, deren Ownership nicht
   (mehr) dem aktiven Record entspricht (präparierte Epoch-Drift über die
   AG3-137-Schreibfläche), wird mit `409`/`403` +
   `ownership_transferred`-Payload abgewiesen — **ohne** State-Write
   (Negativpfad an der Commit-Grenze; AG3-142-Fehlerbild).
4. **Kein Wanduhr-Verfall:** Ein nie beantworteter Auftrag bleibt offen
   und sichtbar; es existiert kein TTL-/Expiry-Feld und kein
   Ablauf-Codepfad (Schema- und Code-Beweis); eine Setup-Phase ohne
   gemeldetes Provisionierungs-Ergebnis schließt nicht ab (fail-closed).
5. **Setup-Umzug:** Im echten Setup-Pfad (Integrationstest über den
   Phase-Dispatch, nicht manuell zusammengesetzt) entstehen
   `provision_worktree`-Aufträge je teilnehmendem Repo; nach
   Edge-Ausführung stammen `worktree_map`/`worktree_roots` aus dem
   `worktree_report`; der Marker `.agentkit-story.json` wird dev-lokal
   materialisiert und gemeldet; kein Backend-Codepfad ruft mehr
   `create_worktree`/`write_story_marker` (Grep-Beleg).
6. **Preflight-Differenzierung:** Checks 7/8 entscheiden auf
   Edge-Probe + Ownership-Kontext + Remote-Ref-Read; beide Pfade der
   Check-7-Unterscheidung bewiesen: „stale fremd" → benannter FAIL-Befund;
   „legitim übernommen" (aktiver Record + `takeover_base_sha`-Ausrichtung)
   → PASS. `local_stale_or_dirty_takeover_target` ist ein benannter
   Check-8-Befund. Fehlt das Probe-Ergebnis oder ist es nicht lesbar,
   FAILt der Check fail-closed — nie optimistisch PASS.
7. **Teardown-Umzug:** Reset-Detach und Setup-Failure-Cleanup erzeugen
   `teardown_worktree`-Aufträge; kein Backend-Pfad ruft
   `remove_worktree` außerhalb der AG3-152-Restkonsumenten (Grep-Beleg);
   die Edge-Ausführung ist idempotent (doppelter Teardown = gemeldeter
   No-op, kein Fehler — FK-10 §10.5.3).
8. **Pfad-Autoritäts-Rückbau:** `StateBackendWorktreeRepository` ist
   entfernt; die Governance-Deaktivierung schreibt nicht mehr physisch in
   Worktrees (Backend-Write-Pfade :494-519 entfallen); die dev-lokale
   Projektion über Bundle-Publikation/Tombstones ist per Integrationstest
   bewiesen; `workspace_locator.project_root` wird von keinem Konsumenten
   mehr als Worktree-Anker verwendet.
9. **Wire-Vokabular gepinnt:** Contract-Tests pinnen alle sechs
   Auftragsarten, die drei Result-Typen, die Quarantäne-Detailform und
   die benannten Takeover-Fehlerbild-Zustände; eine dem Edge unbekannte
   Auftragsart führt zu einem deterministischen Fehler-Result (kein
   stiller No-op).
10. **K5 Postgres-only:** Zugriff auf `edge_command_records` über ein
    Nicht-Postgres-Backend scheitert als expliziter `ConfigError`
    (Muster `_require_postgres_control_plane_backend`); keine
    SQLite-Implementierung (Negativtest).
11. **Ausführungsort-Konformanz (Teilschritt E):** Das SOLL-136-Inventar
    ist abgearbeitet: die in dieser Story umgezogenen Backend-Fundstellen
    sind beseitigt, und die verbleibenden backend-seitigen
    Git-Fundstellen sind exakt die den Nachbar-Stories (AG3-147, AG3-152)
    zugeordneten (Grep-Beleg als Review-Artefakt; keine unzugeordnete
    Fundstelle).
12. Coverage ≥ 85 % gehalten; `mypy` strict (inkl. `--platform linux`)
    und `ruff` ohne neue Ausnahmen; ARCH-55 (englische Bezeichner,
    Wire-Keys, Befund-Codes).

## Definition of Done

- Alle Akzeptanzkriterien erfüllt; Gate-Suite grün (`pytest -n0`
  unit/integration/contract, Coverage ≥ 85, `mypy src` + `--platform linux`,
  `ruff`, 4 Konzept-Gates) — auch nach jedem Teilschritt (interner Schnitt).
- Codex-Review PASS.
- Auf `origin/main` gemerged; `status.yaml` → `completed` (Vorbedingung für
  AG3-147, AG3-151, AG3-152, AG3-154); README-Backlog-Snapshot (§6.7)
  nachgezogen.

## Abdeckung (Traceability)

**Deckt ab:** SOLL-134–139, SOLL-165–169, SOLL-188, SOLL-191–194.

## Konzept-Referenzen

- FK-91 §91.1b (Command-Queue: beide Endpoints, Ack-Semantik, client-op_id
  + Story-Serialisierung + Regel-15-Fencing des Result-Commits;
  Auftragsarten; Result-Typen inkl. `worktree_roots` und benannter
  Takeover-Fehlerbilder; Bundle-Sync bleibt reine Projektion)
- FK-91 §91.1a Regel 5 (client-op_id), Regel 13 (Serialisierung, Reads ohne
  Sperren), Regel 15 (Fencing-Prädikate), Regel 16 (kein Wanduhr-/TTL-Ende)
- FK-10 §10.2.4a (Topologie-Regel; Akteursmodell Agent/Edge/niemand;
  Ausführungsort-Grundsatz mit Fehlbetriebs-Klassifikation;
  workspace_locator-Trennung; `worktree_roots` Edge-gemeldet), §10.4.2
  (Teardown = Edge-Auftrag `git worktree remove` dev-lokal), §10.5.3
  (Provisionierung idempotent als Edge-Auftrag)
- FK-22 §22.3.1 (Checks 7/8 als Edge-Probe; Backend-Entscheid mit
  Ownership-/Transfer-Kontext; Remote-Verifikation per Ref-Read;
  differenzierte Befunde; „stale fremd" vs. „legitim übernommen"),
  §22.6.2 (`setup_worktrees` beauftragt Edge; `WorktreeResult` inkl. Pfad
  Edge-gemeldet), §22.6.3 (Worktree-Pfad dev-lokal, Edge-gemeldet)
- FK-12 §12.5/§12.5.1/§12.5.3 (setup/teardown als Edge-Aufträge;
  Signaturen = fachliche Mechanik, kein Backend-Subprocess)
- FK-36 §36.6.3 (Marker `.agentkit-story.json` dev-lokal durch den Edge im
  `provision_worktree`-Auftrag materialisiert; Marker + Pfadbindung als
  Verifikationsanker der Worktree-Identität)
- FK-56 §56.8 (Edge-gemeldete `worktree_roots` der Session; via FK-91
  §91.1b referenziert)
- Decision-Record `concept/_meta/decisions/2026-07-02-k1-worktree-topologie.md`
  (Konsequenzen 1/7/9/10; Endpoint-Platzierung analog Project-Edge-Gruppe)

## Guardrail-Referenzen

- **FIX THE MODEL, NOT THE SYMPTOM:** Die Backend-Pfad-Autorität wird
  abgeschafft (Locator-Rollen-Schnitt, Repository-Löschung), nicht hinter
  einer weiteren Indirektion versteckt; Auftrag/Meldung ersetzt die
  imperativen Backend-Subprocesses.
- **FAIL-CLOSED:** Fehlendes Probe-/Provisionierungs-Ergebnis blockiert
  (kein optimistisches PASS, kein Timeout-Weiter); Result-Fencing weist
  Ex-Owner-Ergebnisse ohne State-Write ab; unbekannte Auftragsarten sind
  Fehler.
- **SINGLE SOURCE OF TRUTH:** Physische Worktree-Pfade haben genau eine
  Wahrheit — die Edge-gemeldeten `worktree_roots`; `project_root` ist nur
  noch State-Anker.
- **SEVERITY-SEMANTIK:** Differenzierte Preflight-Befunde sind benannte
  ERRORs mit Handlungsauftrag, kein Sammel-FAIL und keine weggeklickten
  Warnings.
- **Strukturregeln:** Edge-Mechanik in `harness_client/`, deploybares
  Asset in `bundles/target_project/` (ohne Backend-Fachlogik),
  Fachlogik/Vokabular in `control_plane` — keine God-Services.
- **Testing-Guardrails:** Negativpfade an den Phasengrenzen (Setup ohne
  Ergebnis, Result nach Ownership-Wechsel, fremde Session); Setup-State
  über den echten Dispatch-Pfad erzeugt.

## Querschnitts-Auflagen

- **K5 Postgres-only:** `edge_command_records` ist Postgres-only,
  fail-closed über das `_require_postgres_control_plane_backend`-Muster
  (`control_plane/runtime.py:2119`, Check :2139); kein SQLite-Spiegel.
  Contract-/Integrationstests über die Postgres-Fixture, Unit-Tests über
  Ports/Fakes.
- **Blutgruppen-Klassifikation**
  (`concept/methodology/software-blutgruppen.md`): Command-Kind-/
  Result-Typ-Vokabular, Preflight-Entscheidungslogik und
  Befund-Differenzierung (`edge_commands.py`) = **A**; Wire-/HTTP-Mapper
  und Row↔Record-Mapper = **R**; Persistenz-Row-Funktionen im
  `state_backend` = **AT/T**; Edge-Executor (dev-lokale Git-Subprocesses
  im `harness_client`) = **T** mit dünner **R**-Meldeschicht. Der A-Kern
  bleibt AT-frei.
- **Bundle-Assets:** **Betroffen** —
  `bundles/target_project/tools/agentkit/projectedge.py` erhält die
  Edge-seitige Kommando-Ausführung (provision/teardown/preflight_probe).
  Abgrenzung verifiziert: das Tool ist heute ein dünner CLI-Wrapper
  (create-story, phase-start/complete/fail, closure-complete; keine
  Git-Mechanik) — das große Edge-Tool-Paket für Takeover/Abort/Recover
  liegt in **AG3-154**, nicht hier.
- **Interner Schnitt (Plan §3):** Teilschritte A–E in dieser Reihenfolge,
  je Teilschritt Zwischen-Verifikation (Gate-Suite grün); kein Teilschritt
  hinterlässt einen Zustand mit zwei operativen Wahrheiten (alte und neue
  Provisionierung koexistieren nie in einem Release-Stand).
  Zuordnung der Akzeptanzkriterien: Teilschritt A → AK 1–4, 9, 10;
  B → AK 5/7/9 (Edge-Ausführungs-Anteile: Provisionierung + Marker,
  idempotenter Teardown, Fehler-Result bei unbekannter Auftragsart);
  C → AK 5, 6; D → AK 7, 8; E → AK 11.
