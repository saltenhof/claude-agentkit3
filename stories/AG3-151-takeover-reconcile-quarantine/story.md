# AG3-151 — Takeover-Reconcile + Quarantäne + Edge-Zustände: `takeover-reconcile-worktree` mit `base_sha`-Abgleich, atomare Quarantäne + Reprovisionierung, vier Guard-Zustände (K1-Semantik)

- **Typ:** implementation
- **Größe:** L
- **depends_on:** [AG3-145, AG3-148, AG3-149, AG3-150]
  - **AG3-145** — die Auftragsarten `takeover_reconcile` und
    `provision_worktree`, die Result-Typen (inkl. Quarantäne-Details) und
    die benannten Takeover-Fehlerbilder im Wire-Vokabular sind die
    Trägerschicht dieser Story; Edge-Aufträge sind der einzige Weg zu
    physischen Worktree-Operationen (GAP §4: „ST-14a → … ST-08 —
    Edge-Aufträge sind deren Trägerschicht").
  - **AG3-148** — der beim Confirm atomar materialisierte
    `takeover-transfer-record` mit `takeover_base_sha` je Repo ist das
    Referenzobjekt des Reconcile-SHA-Abgleichs; ohne vollzogene Transfers
    gibt es nichts zu rekonsiliieren (GAP §4: „ST-08 ← ST-07a, ST-14a").
  - **AG3-149** — das atomare Quarantäne-Modul
    (`harness_client/projectedge/quarantine.py`) entsteht in AG3-149;
    der Neu-Owner-Reconcile dieser Story verwendet es wieder (eine
    Mechanik, zwei Aufrufer — keine zweite Implementierung).
  - **AG3-150** — `contested_local_writes` wird über die
    `freeze_epoch`-Familienfläche aus AG3-150 registriert (story-scoped
    Admission-Blocker); kein Bestands-`conflict_freeze`-Fallback.
- **Quell-Konzept:** FK-91 §91.1a Endpoint-Tabelle
  (`…/ownership/takeover-reconcile-worktree` — SHA-Semantik, Owner-Fence,
  Fehlerbilder), §91.1b (Auftragsart `takeover_reconcile`,
  Quarantäne-Ergebnisdetails, benannte Result-Zustände);
  FK-30 §30.6.3 (die vier Guard-Zustände, Guard-Erzwingung,
  Bundle-Quelle fail-closed); FK-56 §56.13c (Übergabeobjekt = SHA,
  Immobilität, Diverged-Zustand), §56.13e (Worktree-Identität via
  Marker+Pfad; Quarantäne nie `git stash`; Reprovisionierung), §56.13f
  (contested als Freeze-Zustand); FK-31 §31.1.3c (Salvage-Commit
  entfällt); FK-36 §36.6.3 (Marker `.agentkit-story.json` als
  Identitätsanker); FK-58 §58.6a (Worktree-Schicksal beim Exit)
- **Herkunft:** GAP-Analyse Session-Ownership v4 (`_temp/gap-analyse-session-ownership.md`),
  Story-Kandidat GAP-ST-08 (per 58c190b7 neu hergeleitet); normative Basis
  Commits 3ae011e4 / 1bb4ed8a / 58c190b7 (+ Decision-Records unter
  `concept/_meta/decisions/`, insb. `2026-07-02-k1-worktree-topologie.md`).

## Kontext / Problem

Der Transfer (AG3-148) überträgt Backend-Ownership und das Übergabeobjekt
`takeover_base_sha` — aber **keinen Dateizustand und keine
OS-Dateiexklusivität** (SOLL-080). Deshalb muss der lokale Worktree des
neuen Owners vor dem ersten Write exakt auf `takeover_base_sha`
ausgerichtet werden, guard-erzwungen. Diese komplette Schicht fehlt (am
Code verifiziert 2026-07-02):

- **Keine Reconcile-Infrastruktur:** Grep
  `takeover|contested|reconcile_required|quarantine` über
  `src/agentkit/harness_client/`: null Treffer; der Edge kennt nur die
  drei `binding_invalid`-Gründe
  (`harness_client/projectedge/runtime.py:214/:226/:234` — plus
  `ownership_transferred` ab AG3-142). Es gibt keinen
  `takeover-reconcile-worktree`-Endpoint (die Project-Edge-Routen sind
  Sync + Operations-Reads) und keine der vier Zustandspublikationen.
- **Edge-Bundle-Mechanik trägt als Fundament:** `resolve()`
  (`projectedge/runtime.py:199-242`), `FreshnessClass` (:35),
  Lock-Export + Tombstone-Cleanup (`projectedge/client.py:370-383`) und
  die serverseitige Bundle-Assemblierung
  (`control_plane/runtime.py:2293-2364`) sind die Erweiterungspunkte für
  die Zustands-Publikation (IMPL-020).
- **Kein Salvage-Pfad existiert — und darf nicht entstehen:** FK-31
  §31.1.3c streicht den Salvage-Commit ersatzlos (Pushed-only); es gibt
  kein übernommenes Uncommitted mehr. Die frühere Snapshot-Herleitung
  (SOLL-071/076/077, `git diff --binary`, Untracked-Manifeste) ist
  SUPERSEDED — es wird keinerlei Snapshot-/Salvage-Infrastruktur gebaut.
- **Quarantäne-Mechanik:** das atomare Quarantäne-Modul
  (`harness_client/projectedge/quarantine.py`) entsteht in AG3-149 für den
  Ex-Owner-Fall und wird hier für den Neu-Owner-Reconcile wiederverwendet
  (eine Mechanik, zwei Aufrufer).
- **Physische Git-Primitiven sind nach AG3-145 Edge-Sache:** die
  Backend-seitigen `utils/git.py`-Primitiven (`create_worktree` :58,
  `branch_exists` :119, `tree_hash_of_commit` :158, `remove_worktree`
  :196) sind für Reconcile-Zwecke tabu (FK-10 §10.2.4a: Backend-Subprocess
  = Fehlbetrieb); die Reconcile-Ausführung ist von Anfang an dev-lokal im
  Edge zu bauen.
- **Exit-Worktree-Schicksal (SOLL-079):** der Exit räumt heute nur Locks +
  Bindung ab (`story_exit/service.py:514` ff. — kein physischer
  Teardown); nach dem AG3-145-Umzug erzeugen Reset-Detach und
  Setup-Failure-Cleanup `teardown_worktree`-Aufträge. Die normative
  Zusicherung „Exit lässt Worktree/Branch als Arbeitsstand stehen — kein
  Auto-Teardown" ist bisher nirgends als Vertrag verprobt.

Ohne diese Story ist jeder Takeover physisch ungesichert: ein lokal
weiterschreibender A-Prozess, ein alter Checkout oder ein regelwidriger
Push nach dem Confirm blieben unentdeckt — genau die Lücken, die FK-30
§30.6.3 mit den vier Zuständen schließt.

## Scope

### In Scope

1. **Wire-Contract `POST /v1/project-edge/story-runs/{run_id}/ownership/takeover-reconcile-worktree`**
   (SOLL-127, SOLL-128, SOLL-160): Reconcile-Meldung durch den neuen
   Owner — **SHA-Semantik**: Abgleich gegen den beim Confirm
   materialisierten `takeover_base_sha` des Transfer-Records (nie gegen
   einen Datei-Snapshot). Mutierende Operation: client-beigestelltes
   `op_id` (Regel 5), Serialisierungsobjekt `(project_key, story_id)`
   (Regel 13), zulässig nur für den aktuellen Owner (Fence auf
   `owner_session_id`/`ownership_epoch` — AG3-142-Fläche). Erfolg
   (Worktree exakt auf `takeover_base_sha` ausgerichtet, Quarantäne
   abgeschlossen, Identität verifiziert) hebt `takeover_reconcile_required`
   auf; die Guard-Semantik/Exklusivität dieses Aufhebungspfads bleibt in
   FK-30 verankert (SOLL-128).
2. **Backend-Kommissionierung + Validierung:** nach vollzogenem Transfer
   erzeugt das Backend den `takeover_reconcile`-Auftrag für die neue
   Session (AG3-145-Queue); die Reconcile-Validierung prüft serverseitig:
   (a) gemeldeter Worktree-Stand == `takeover_base_sha` je teilnehmendem
   Repo, (b) Remote-Head des Story-Branch == `takeover_base_sha`
   (Ref-Read über die transitiv verfügbare AG3-147/146-Lesefläche) —
   Abweichung ⇒ `remote_branch_diverged_after_takeover` (SOLL-162,
   blockierend, administrative Auflösung; der SHA-Vergleich macht den
   Verstoß sichtbar und zuordenbar), (c) Worktree-Identität verifiziert.
   Multi-Repo: Abgleich und Zustand **je Repo**; ein abweichendes Repo
   blockiert die Aufhebung.
3. **Edge-seitige Reconcile-Ausführung** (SOLL-154, 155, 156): Executor
   für `takeover_reconcile` im `harness_client` —
   - **Worktree-Identitäts-Verifikation** über Marker
     (`.agentkit-story.json`) **und** Pfadbindung (FK-36 §36.6.3,
     FK-56 §56.13e): nicht Maschinen-Identität, sondern
     Worktree-Identität klassifiziert Same-Worktree vs.
     Reprovisionierung (SOLL-154).
   - **Same-Worktree:** B übernimmt den **Pfad**, nicht den Inhalt — der
     vorhandene Stand wird **vollständig und atomar** in die lokale
     Quarantäne-Ablage verschoben (Verzeichnis-Move/-Copy über das
     AG3-149-Quarantäne-Modul — **NIEMALS `git stash`**), der Pfad wird
     sauber aus `takeover_base_sha` reprovisioniert; der gepushte
     Story-Branch wird dabei nie resettet; Quarantäne statt stiller
     Löschung, auditiert als lokales Ereignis (SOLL-155). Eine
     menschliche Entscheidung ist NICHT je Ausrichtung nötig — nur bei
     Scheitern oder unklarer Identität.
   - **Reprovisionierung (anderer Pfad/andere Maschine):** frischer
     Worktree aus `takeover_base_sha` via `provision_worktree`
     (AG3-145); existiert am Ziel ein alter/schmutziger Worktree
     derselben Story ⇒ `local_stale_or_dirty_takeover_target`
     (SOLL-156, SOLL-163) mit derselben Quarantäne-Mechanik — nie
     stilles Überschreiben. Zwei Sessions derselben Maschine mit anderem
     Checkout oder zwei Maschinen desselben Entwicklers sind
     Reprovisionierungs-Fälle.
   - Ergebnis-Meldung mit Quarantäne-Details über den Wire-Contract
     (Result-Typen aus AG3-145).
4. **Die vier Guard-Zustände via Bundle-Sync + Hook-Guards** (SOLL-073,
   074, 075, 161, 162, 163; IMPL-020):
   - `takeover_reconcile_required` — der minimale story-scoped
     Admission-Blocker entsteht bereits in **AG3-148** beim Confirm (im
     atomaren Vollzug mitgesetzt); **diese Story** baut ihn zum vollen
     Reconcile-Contract aus (Wire-Contract, Quarantäne,
     Reprovisionierung, die übrigen drei Zustände,
     Bundle-Sync-/Hook-Guard-Fläche) und löst ihn regulär auf.
     Startzustand des Edge-Bundles des neuen Owners nach dem Transfer;
     blockiert fail-closed:
     dateimutierende Werkzeuge in den Story-Worktrees, Commits (einen
     Salvage-Commit gibt es nicht), `complete_phase`/`fail_phase` sowie
     Verify-/Closure-Starts, die auf dem Worktree-Zustand beruhen;
     Reads bleiben durchgehend erlaubt (SOLL-073/160).
   - `contested_local_writes` — Ergebnis eines gescheiterten oder nicht
     eindeutig verifizierbaren Reconciles: read-only Konflikt-Freeze bis
     zur menschlichen/administrativen Entscheidung; backend-seitig als
     story-scoped Admission-Blocker mit `freeze_epoch`/`freeze_reason`/
     Audit registriert (SOLL-074/161) — verbindlich über die
     `freeze_epoch`-Familienfläche aus AG3-150 (Kante existiert; kein
     Bestands-`conflict_freeze`-Fallback).
   - `remote_branch_diverged_after_takeover` (SOLL-162) und
     `local_stale_or_dirty_takeover_target` (SOLL-163) — blockierend,
     benannte Zustände, administrative bzw. Quarantäne-Auflösung.
   - Alle Zustände werden wie alle Guard-Signale aus dem **lokal
     publizierten Edge-Bundle** gelesen; fehlt das Signal oder ist der
     Bundle-Stand inkonsistent ⇒ fail-closed (SOLL-075). Publikation:
     serverseitige Bundle-Assemblierung + Edge-Export (bestehende
     Mechanik erweitert).
5. **Kein Salvage-Pfad** (SOLL-078, SOLL-159): vor abgeschlossenem
   Reconcile blockieren die Hook-Guards jeden Commit; die
   Branch-Guard-Blockade (FK-31) bleibt; Verwerfen des gepushten Stands
   bleibt der offizielle Reset-Pfad. Es existiert **kein**
   Salvage-Commit-Codepfad; die Guards liefern stattdessen den
   Quarantäne-Hinweis. Menschliche Verwertung quarantänierter Inhalte
   liegt außerhalb des Takeover-Vertrags — nie als Nachreichung, Replay
   oder Salvage durch den Ex-Owner; Wiedereinführung nur durch den
   **aktuellen Owner** nach abgeschlossenem Reconcile via
   Commit/Push/QA.
6. **Keine OS-Dateiexklusivität — Absicherungskette** (SOLL-080): die
   Story beweist die K1-Absicherungskette `takeover_base_sha` +
   Quarantäne/Reprovisionierung + Contested-Eskalation: physischer Drift
   wird vor B's erstem Write erkannt und eskaliert statt überschrieben.
7. **Exit-Worktree-Schicksal** (SOLL-079): Worktree und Branch bleiben
   nach dem Story-Exit als Arbeitsstand erhalten — der Exit erzeugt
   keinen `teardown_worktree`-Auftrag und keinen physischen Cleanup;
   aufgeräumt wird erst durch die Closure einer Nachfolge-Umsetzung oder
   einen expliziten Reset-/Cleanup-Pfad (vertraglich verprobt).
8. **Bundle-Asset** (Plan §3, Pflichtdeklaration):
   `bundles/target_project/tools/agentkit/projectedge.py` erhält die
   Edge-seitige Reconcile-/Quarantäne-**Ausführung** (Abruf/Ausführung/
   Meldung des `takeover_reconcile`-Auftrags im Rahmen des
   AG3-145-Command-Loops). **Abgrenzung:** die Takeover-/Abort-/
   Recover-**Kommandos** des Edge-Tools (agent-initiierbare CLI-Pfade)
   liegen in **AG3-154**, nicht hier.

### Out of Scope (mit Owner)

- **Command-Queue-Trägerschicht** (Endpoints, Ack/Result-Mechanik,
  Wire-Vokabular, `provision_worktree`-Executor): **AG3-145** — hier wird
  die Auftragsart `takeover_reconcile` fachlich gefüllt.
- **Transfer selbst** (Challenge/Confirm, Transfer-Record-Materialisierung,
  Tombstone des Ex-Owners): **AG3-148**.
- **Ex-Owner-Reconcile-Verhalten + Quarantäne-Modul** (der Ex-Owner-Fall
  von SOLL-153; das wiederverwendete `quarantine.py`): **AG3-149**.
- **Freeze-Familie/`freeze_epoch`-Generalisierung + Admission-Blocker-
  Durchsetzung an den Regime-Pfaden**: **AG3-150** (diese Story erzeugt
  den `contested_local_writes`-**Eintritt** und seine Edge-Wirkung).
- **Push-Barrieren, Push-Gate, Ref-Schutz, Push-Frische**: **AG3-147**.
- **Closure-Merge (`merge_local`) + Closure-Teardown**: **AG3-152**.
- **Frontend-Anzeige der Edge-Zustände + Auflösungs-Hinweise**: **AG3-153**.
- **CLI-/Agent-Kommandos** (takeover-request/-confirm/admin-abort/
  recover-story im Edge-Tool): **AG3-154**.

## Betroffene Dateien

| Datei | Änderungsart | Zweck |
|---|---|---|
| `src/agentkit/backend/control_plane/takeover_reconcile.py` | neu | Reconcile-Validierungslogik: SHA-Abgleich je Repo gegen den Transfer-Record, Identitäts-/Diverged-/Stale-Klassifikation, Zustandsübergänge der vier Zustände — Blutgruppe A |
| `src/agentkit/backend/control_plane/runtime.py` | ändern | `takeover_reconcile`-Auftrag nach Transfer-Vollzug kommissionieren; Reconcile-Endpoint-Handler (Owner-Fence, Story-Serialisierung); Bundle-Assemblierung (:2293-2364) um die vier Zustands-Signale erweitern |
| `src/agentkit/backend/control_plane/models.py`, `records.py`, `repository.py` | ändern | Wire-Modelle der Reconcile-Meldung (client-op_id Pflicht, Quarantäne-Details, je-Repo-Ergebnis), Zustands-Records/-Ports |
| `src/agentkit/backend/control_plane_http/app.py` | ändern | Route `POST .../ownership/takeover-reconcile-worktree` (Project-Edge-Gruppe); Fehlerbilder der benannten Zustände im Regel-8-Fehlervertrag |
| `src/agentkit/backend/state_backend/postgres_store.py` + `store/facade.py` (+ `_public_api_names.py`, `__init__.pyi`) | ändern | Persistenz der Reconcile-/Zustands-Fakten (Postgres-only, K5), transaktional mit dem Endpoint-Commit |
| `src/agentkit/backend/governance/principal_capabilities/freeze.py` | ändern (minimal) | `contested_local_writes` als story-scoped Blocker-Eintrag über die AG3-150-`freeze_epoch`-Familienfläche registrieren |
| `src/agentkit/harness_client/projectedge/reconcile.py` | neu | Edge-Executor `takeover_reconcile`: Identitäts-Verifikation (Marker+Pfad), Same-Worktree-Quarantäne + Reprovisionierung aus `takeover_base_sha`, Stale-/Dirty-Target-Behandlung, Ergebnis-Meldung — nutzt `quarantine.py` (AG3-149) |
| `src/agentkit/harness_client/projectedge/runtime.py`, `client.py` | ändern | Bundle-Zustände `takeover_reconcile_required`/`contested_local_writes`/`remote_branch_diverged_after_takeover`/`local_stale_or_dirty_takeover_target` im Resolve-/Guard-Kontext (fail-closed bei fehlendem/inkonsistentem Signal); Export der Zustands-Signale in die `.agent-guard`-Projektion |
| `src/agentkit/backend/story_exit/service.py` | ändern (minimal/Beweis) | Zusicherung SOLL-079: Exit erzeugt keinen `teardown_worktree`-Auftrag (Vertragstest; Codeänderung nur falls der AG3-145-Umzug hier einen Aufruf hinterlassen hat) |
| `src/agentkit/bundles/target_project/tools/agentkit/projectedge.py` | ändern | Edge-seitige Reconcile-/Quarantäne-Ausführung im deployten Tool (Command-Loop-Anbindung; KEINE Takeover-/Abort-/Recover-Kommandos — AG3-154) |
| `tests/unit/**`, `tests/integration/**`, `tests/contract/**` | neu/ändern | SHA-Abgleich-/Klassifikations-Logik (Ports/Fakes); E2E Transfer→Reconcile→Freigabe; Negativpfade je Zustand; Guard-Blockade-Tests; Contract-Pins der Wire-Formen und Zustands-Namen |

## Akzeptanzkriterien

1. **Startzustand erzwungen:** nach echtem Transfer (AG3-148-Pfad, nicht
   präpariert) startet das Edge-Bundle der neuen Session in
   `takeover_reconcile_required`; in diesem Zustand blockieren die Guards
   fail-closed: dateimutierende Werkzeuge im Story-Worktree, Commits,
   `complete_phase`/`fail_phase` und Verify-/Closure-Starts (je ein
   Negativtest); Reads bleiben durchgehend erlaubt (Positivtest).
2. **Fail-closed ohne Signal:** fehlt das Zustands-Signal im lokal
   publizierten Bundle oder ist der Bundle-Stand inkonsistent, blockieren
   die Guards — nie optimistisch freigeben (SOLL-075-Negativtest).
3. **Same-Worktree-Reconcile:** bei verifizierter Worktree-Identität
   (Marker + Pfadbindung) wird der vorhandene Stand vollständig und
   atomar in die Quarantäne-Ablage verschoben und der Pfad aus
   `takeover_base_sha` reprovisioniert; es existiert kein
   `git stash`-Aufruf im Codepfad (Code-Beweis); der gepushte
   Story-Branch wird nie resettet (Negativtest: Remote-Ref unverändert);
   das Quarantäne-Ereignis ist lokal auditiert; keine menschliche
   Interaktion im Erfolgsfall.
4. **Erfolgs-Aufhebung nur über den offiziellen Pfad:** der erfolgreiche
   `takeover-reconcile-worktree`-Call (SHA-Abgleich je Repo gegen den
   Transfer-Record bestanden) hebt `takeover_reconcile_required` auf —
   und NUR er (Negativtest: Bundle-Re-Sync, Neustart oder Zeitablauf
   heben nicht auf); der Call ist owner-gefenct (Ex-Owner/fremde Session
   → 409/403, AG3-142-Fehlerbild) und client-op_id-pflichtig.
5. **Contested bei Scheitern/Unklarheit:** scheitert
   Quarantäne/Reprovisionierung (z. B. gesperrte Dateien) oder ist die
   Worktree-Identität nicht eindeutig verifizierbar (fehlender/falscher
   Marker, Pfad-Mismatch), geht der Worktree deterministisch in
   `contested_local_writes`: read-only (Guards blockieren jede Mutation),
   backend-seitig als story-scoped Blocker mit
   `freeze_epoch`/`freeze_reason`/Audit registriert; Auflösung nur
   menschlich/administrativ (Negativtest: erneuter Reconcile-Call allein
   löst nicht auf).
6. **Remote-Divergenz:** weicht der Remote-Head des Story-Branch nach dem
   Confirm vom `takeover_base_sha` ab (präparierter durchgeschlüpfter
   Push), meldet die Validierung `remote_branch_diverged_after_takeover`
   — blockierend, kein stilles Mitnehmen; der Zustand benennt Repo und
   beide SHAs (zuordenbar); administrative Auflösung ist der einzige
   Ausweg (Negativtest).
7. **Stale/Dirty-Ziel:** eine Reprovisionierung auf ein Ziel mit
   altem/schmutzigem Worktree derselben Story erzeugt
   `local_stale_or_dirty_takeover_target` und quarantäniert den Bestand
   — nie stilles Überschreiben (Negativtest: Bestandsinhalt liegt danach
   in der Quarantäne-Ablage, nicht gelöscht).
8. **Multi-Repo:** SHA-Abgleich und Zustand gelten je teilnehmendem Repo;
   ein einziges abweichendes Repo verhindert die Aufhebung, auch wenn
   alle anderen passen (Teildivergenz-Negativtest).
9. **Kein Salvage-Pfad:** es existiert kein Codepfad, der übernommene
   uncommittete Inhalte committet oder ans Backend nachreicht
   (Code-Beweis + Negativtest: Quarantäne-Inhalte erreichen weder Commit
   noch Backend); die Guard-Ablehnung während `takeover_reconcile_required`
   enthält den Quarantäne-Hinweis; Wiedereinführung quarantänierter
   Inhalte gelingt nur dem aktuellen Owner nach abgeschlossenem Reconcile
   über den normalen Commit-/Push-/QA-Weg (Positivtest).
10. **Verantwortungsgrenze (SOLL-157):** ab `takeover_base_sha` ist es
    B's Epoche — nach dem Reconcile committete Arbeit trägt
    `run_id + ownership_epoch` der neuen Epoche (Attribution-Test über
    die AG3-142-Stempel).
11. **Exit-Worktree-Schicksal (SOLL-079):** ein Story-Exit erzeugt keinen
    `teardown_worktree`-Auftrag und keinen physischen Cleanup; Worktree
    und Branch bestehen nach dem Exit fort (Vertragstest); Aufräumen
    erfolgt erst durch Closure einer Nachfolge oder expliziten
    Reset-/Cleanup-Pfad (Positivtest über den Reset-Detach-Auftrag aus
    AG3-145).
12. **Wire-Formen gepinnt:** Contract-Tests pinnen die Reconcile-Meldung
    (je-Repo-Ergebnis, Quarantäne-Details) und die vier Zustands-Namen
    (`takeover_reconcile_required`, `contested_local_writes`,
    `remote_branch_diverged_after_takeover`,
    `local_stale_or_dirty_takeover_target`) als benannte, unterscheidbare
    Zustände — kein Sammel-FAIL.
13. Coverage ≥ 85 % gehalten; `mypy` strict (inkl. `--platform linux`)
    und `ruff` ohne neue Ausnahmen; ARCH-55 (englische Zustands-Namen,
    Wire-Keys, Befund-Codes).

## Definition of Done

- Alle Akzeptanzkriterien erfüllt; Gate-Suite grün (`pytest -n0`
  unit/integration/contract, Coverage ≥ 85, `mypy src` + `--platform linux`,
  `ruff`, 4 Konzept-Gates).
- Codex-Review PASS.
- Auf `origin/main` gemerged; `status.yaml` → `completed`;
  README-Backlog-Snapshot (§6.7) nachgezogen.

## Abdeckung (Traceability)

**Deckt ab:** SOLL-073–075, SOLL-078–080, SOLL-127, SOLL-128, SOLL-154–157, SOLL-159–163; IMPL-020.

## Konzept-Referenzen

- FK-30 §30.6.3 (die vier Guard-Zustände mit exakter Blockade-Liste;
  Reconcile = Quarantäne + Reprovisionierung, nie `git stash`; Mensch nur
  bei Scheitern/unklarer Identität; Aufhebung ausschließlich über den
  offiziellen `takeover-reconcile-worktree`-Pfad mit SHA-Abgleich;
  contested als read-only Konflikt-Freeze mit
  `freeze_epoch`/`freeze_reason`; Zustände aus dem lokal publizierten
  Edge-Bundle, fehlend/inkonsistent ⇒ fail-closed)
- FK-91 §91.1a Endpoint-Tabelle
  (`…/ownership/takeover-reconcile-worktree`: SHA-Semantik gegen
  `state-storage.entity.takeover-transfer-record`; Fehlerbilder
  contested/diverged/stale_target; client-op_id, Story-Serialisierung,
  Owner-Fence), §91.1b (Auftragsart `takeover_reconcile` — „das Ergebnis
  wird über den Wire-Contract `takeover-reconcile-worktree` gemeldet";
  Quarantäne-Ergebnisdetails; benannte Result-Zustände, kein Sammel-FAIL)
- FK-56 §56.13c (Übergabeobjekt = `takeover_base_sha`, Immobilität;
  Remote-Divergenz nach Confirm ⇒ `remote_branch_diverged_after_takeover`),
  §56.13e (Klassifikation über Worktree-Identität — Marker + Pfadbindung;
  Same-Worktree übernimmt den Pfad, nicht den Inhalt; Reprovisionierung
  via `provision_worktree`; `local_stale_or_dirty_takeover_target`;
  Verantwortungsgrenze = SHA, B's Epoche ab `takeover_base_sha`),
  §56.13f (contested als Admission-Blocker der Freeze-Familie)
- FK-31 §31.1.3c (Salvage-Commit entfällt; Quarantäne-Hinweis; menschliche
  Verwertung außerhalb des Vertrags; Wiedereinführung nur durch den
  aktuellen Owner via Commit/Push/QA)
- FK-36 §36.6.3 (Marker `.agentkit-story.json` + Pfadbindung als
  Verifikationsanker der Worktree-Identität)
- FK-58 §58.6a (Worktree/Branch bleiben nach Exit als Arbeitsstand; kein
  Auto-Teardown; Aufräumen erst durch Closure einer Nachfolge oder
  expliziten Reset/Cleanup)
- Decision-Record `concept/_meta/decisions/2026-07-02-k1-worktree-topologie.md`
  (SHA-Übergabe, Quarantäne-Mechanik, Edge-Cases 1–8)

## Guardrail-Referenzen

- **FAIL-CLOSED:** fehlendes/inkonsistentes Bundle-Signal blockiert; jede
  Abweichung (Drift, Divergenz, unklare Identität) eskaliert in einen
  benannten blockierenden Zustand statt stillem Weiterlaufen oder
  Überschreiben; die Aufhebung hat genau einen Pfad.
- **NO ERROR BYPASSING:** es gibt keinen Bypass an
  `takeover_reconcile_required` vorbei (kein „Commit trotzdem", kein
  Salvage); contested wird nicht durch Wiederholung „weggeklickt".
- **SINGLE SOURCE OF TRUTH:** das Übergabeobjekt ist ausschließlich der
  `takeover_base_sha` im Transfer-Record; Quarantäne-Inhalte sind lokale
  Menschen-Artefakte und nie Backend-Wahrheit; die Quarantäne-Mechanik
  existiert genau einmal (AG3-149-Modul, hier wiederverwendet).
- **SEVERITY-SEMANTIK:** die vier Zustände sind benannte, unterscheidbare
  ERRORs mit Handlungsauftrag/Auflösungspfad — kein Sammel-FAIL, keine
  ignorierbaren Warnings.
- **Strukturregeln:** physische Ausführung im `harness_client` (Edge),
  Validierungs-/Zustandslogik in `control_plane`, deploybares Asset in
  `bundles/target_project/` ohne Backend-Fachlogik.
- **Testing-Guardrails:** der Reconcile-State entsteht über den echten
  Transfer-Pfad (AG3-148) und die echte Command-Queue (AG3-145) — nicht
  manuell zusammengesetzt; Negativpfade je Zustand und je Repo sind
  Pflicht.

## Querschnitts-Auflagen

- **K5 Postgres-only:** Reconcile-/Zustands-Persistenz läuft auf der
  Postgres-Control-Plane (fail-closed via
  `_require_postgres_control_plane_backend`,
  `control_plane/runtime.py:2119`, Check :2139); neue Persistenzflächen
  dieser Story sind Postgres-only, kein SQLite-Spiegel.
  Contract-/Integrationstests über die Postgres-Fixture, Unit-Tests über
  Ports/Fakes.
- **Blutgruppen-Klassifikation**
  (`concept/methodology/software-blutgruppen.md`): SHA-Abgleich-,
  Klassifikations- und Zustandsübergangs-Logik
  (`takeover_reconcile.py`) = **A**; Wire-/HTTP-/Bundle-Signal-Mapper =
  **R**; Persistenz-Row-Funktionen im `state_backend` = **AT/T**;
  Edge-Executor (`reconcile.py`: dev-lokale Git-/Dateisystem-Operationen)
  = **T** mit dünner **R**-Meldeschicht. Der A-Kern bleibt AT-frei.
- **Bundle-Assets (Pflichtdeklaration, Plan §3): Betroffen** —
  `bundles/target_project/tools/agentkit/projectedge.py` erhält die
  Edge-seitige Ausführung des `takeover_reconcile`-Auftrags
  (Quarantäne + Reprovisionierung + Meldung; die Reconcile-/Quarantäne-
  Ausführung ist Edge-seitig). **Abgrenzung:** die Takeover-/Abort-/
  Recover-**Kommandos** des Edge-Tools (agent-initiierbare Pfade) liegen
  in **AG3-154**.
