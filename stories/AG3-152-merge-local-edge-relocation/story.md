# AG3-152 — `merge_local`-Umzug (Closure): FK-29-Merge-Block als Edge-Auftrag mit unverändertem Vertrag, Closure-Resume-Cross-Fall mit Reprovisionierung

- **Typ:** implementation
- **Größe:** M
- **depends_on:** [AG3-145, AG3-147]
  - **AG3-145** — `merge_local` ist eine Auftragsart der
    Edge-Command-Queue; Beauftragung, Ack, Result-Meldung und
    Regel-15-Result-Fencing sind deren Trägerschicht; die
    Cross-Fall-Reprovisionierung nutzt `provision_worktree` (GAP §4:
    ST-14a → ST-14b, „Edge-Aufträge sind deren Trägerschicht").
  - **AG3-147** — vor produktivem `merge_local` ist der Remote-Push
    **plus** serverseitiger Ref-Read Pflicht; dessen Durchsetzung
    (Barriere am Closure-Eintritt, wiederverwendbarer
    Push-Verifikations-Prüfpunkt, SOLL-190) liegt in AG3-147 (GAP §4:
    ST-15 → ST-14b, Review-v4-Finding 3).
- **Quell-Konzept:** FK-29 §29.1a.1 (Ausführungsort Edge, Vertrag
  unverändert, API nur lesend/verifizierend, Closure-Resume-Cross-Fall);
  FK-12 §12.5.2 (Ausführungsort des Merge-Blocks), §12.7.1
  (Closure-Zeile: `merge_local` + `ls-remote`-Verifikation, Adapter nur
  Fallback)
- **Herkunft:** GAP-Analyse Session-Ownership v4
  (`_temp/gap-analyse-session-ownership.md`), Story-Kandidat GAP-ST-14b;
  normative Basis Commits 3ae011e4 / 1bb4ed8a / 58c190b7 (+ Decision-Records
  unter `concept/_meta/decisions/`, insb.
  `2026-07-02-k1-worktree-topologie.md`, Konsequenz 2).

## Kontext / Problem

FK-29 §29.1a.1 normiert: Der gesamte Pre-Merge-Scan-und-Merge-Block wird
vom **Project Edge** ausgeführt (Auftragsart `merge_local`); vertraglich
ändert sich **nichts** — Kandidatenbildung, Merge-Serialisierungs-Lock,
`locked_sha`-CAS, `pre_merge_sha`-Rollback und die Multi-Repo-Stufen
bleiben, nur der Ausführungsort wandert. Heute läuft der Block vollständig
als **Backend-Subprocess** (am Code verifiziert 2026-07-02):

- **Merge-Orchestrierung backend-seitig:** `closure/phase.py` importiert
  und ruft `run_pre_merge_and_merge_block`/`run_fast_merge_block`
  (:27-32, `_reach_merge_done` :392-405). `closure/merge_sequence.py`
  führt die Git-Mechanik im Backend-Prozess aus: Lock-Aufbau +
  `locked_sha`-Capture + Drift-Assert (:858-885), Integrate
  (`merge --no-ff` :889), `git clean -xfd` (:903), CAS-Pre-Check
  (:753-754, `_verify_main_unchanged` :1061-1078), Teardown (:1213),
  Rollback nach CAS-Failure (`_rollback_after_cas_failure` :1255).
- **Saga-Bausteine backend-seitig:** `closure/multi_repo_saga.py` —
  `SubprocessGitBackend` (:76-95), `pre_merge_check` (:122),
  `push_story_branches` (:147), `local_ff_merge_with_rollback` (:191),
  `push_main` (:264), `teardown_worktrees` (:324); produktiv verdrahtet
  in `bootstrap/composition_root.py:2886-2928`.
- **Scan-/Attestation-Binding liest lokales Git im Backend:**
  `verify_system/pre_merge_runner/scan_runner.py:116-118`
  (`utils.git.tree_hash_of_commit`) und
  `verify_system/sonarqube_gate/runtime_wiring.py:238/:286-298`
  (Worktree-HEAD-/Tree-Reads für die commit-gebundene Attestation).
- **Closure-Git-Reads backend-seitig:** `closure/runtime_ports.py` —
  Fast-Sanity-Checks (`git status --porcelain`, Dry-Rebase, :112-181)
  und `_read_final_diff` (:367-386, `git diff` für Feedback-Fidelity).
- **Kein Cross-Fall:** Für eine auf anderer Maschine fortgesetzte Closure
  existiert kein Reprovisionierungs-Schritt — `StoryContext.worktree_map`
  zeigt auf Pfade der ursprünglichen Maschine; ein Resume würde ins Leere
  greifen statt vor dem Merge einen sauberen Worktree aus dem
  maßgeblichen gepushten Stand zu provisionieren (SOLL-187).

**Tragfähig und unverändert zu erhalten:** die FK-29-Verträge selbst —
Substate-/Recovery-Modell (`ClosureProgress`, `merge_done` wird nie
wiederholt), atomare Grün-und-FF-Mergbarkeits-Barriere vor dem ersten
Push, `locked_sha`-CAS, `pre_merge_sha`-Rollback, ESCALATED-Semantik bei
partiellem Cross-Remote-Push (FK-29 §29.1.6). Diese Story ist ein
**Ausführungsort-Umzug**, keine Vertragsänderung.

## Scope

### In Scope

1. **`merge_local` als Edge-Auftrag** [SOLL-185]: Die Closure beauftragt
   den Edge über die Command-Queue (AG3-145) mit dem gesamten
   Pre-Merge-Scan-und-Merge-Block; das Result trägt die vertraglichen
   Fortschritts-/Substate-Informationen (per-Repo Push-/Merge-Status,
   Eskalations-Fälle), aus denen das Backend `ClosurePayload`/
   `ClosureProgress` fortschreibt. Der FK-29-Vertrag bleibt unverändert:
   Kandidatenbildung, Merge-Serialisierungs-Lock, `locked_sha`-CAS,
   `pre_merge_sha`-Rollback, Multi-Repo-Stufen, Merge-Policy
   (ff_only/no_ff), ESCALATED bei partiellem Push. `merge_local` ist
   nicht bounded (Build/Test/Scan) — zwischen Beauftragung und Result
   hält das Backend keine Serialisierung; der Result-Commit ist ein
   steuerndes Ergebnis und nur bei gültigen Fences wirksam
   (AG3-145-Fläche, FK-91 Regel 15).
2. **Verlagerung der Git-Mechanik in den Edge-Executor**
   (`harness_client` + Bundle-Tool): die komplette Block-Mechanik aus
   `merge_sequence.py`/`multi_repo_saga.py` inklusive
   Fast-Sanity-Git-Checks, Tree-/HEAD-Binding-Reads des Scan-Runners und
   des Closure-Teardowns nach erfolgreichem Merge (nutzt die
   AG3-145-Teardown-Mechanik bzw. läuft im `merge_local`-Auftrag — Design
   dieser Story). Der Schnitt, welche lesenden Verifikationen das Backend
   am Result vornimmt (z. B. Sonar-QG-Read per `analysisId`,
   Attestation-Verify durch die Integrity-Gate-Dimension 9 — die
   verifiziert, nie selbst vermisst), ist Design dieser Story; normativ
   fix ist: physische Git-/Worktree-Mechanik dev-lokal, Backend nur
   lesend/verifizierend.
3. **Push-Verifikations-Vorbedingung** [SOLL-189/190-Konsum]: Vor
   produktivem `merge_local` ist der AG3-147-Prüfpunkt Pflicht — der
   aktuelle Story-Branch aller beteiligten Repos ist serverseitig
   (Ref-Read) als gepusht verifiziert; ohne Verifikation wird kein
   Auftrag erzeugt (fail-closed). Der Merge arbeitet ausschließlich gegen
   den gepushten Story-Branch.
4. **Closure-Resume-Cross-Fall** [SOLL-187]: Wird die Closure auf einer
   anderen Maschine/Session fortgesetzt, provisioniert der ausführende
   Edge **vor** `merge_local` einen sauberen Worktree aus dem
   maßgeblichen gepushten Stand (`provision_worktree`, AG3-145); ohne
   erfolgreiche Reprovisionierung startet kein Merge.
5. **FK-12 §12.7.1-Ablauf** [SOLL-189]: Die Closure-Kontaktpunkte zum
   Code-Backend sind exakt: Edge-Auftrag `merge_local` (Schreiben,
   dev-lokal) + serverseitige Push-/Ref-Verifikation via git-Protokoll
   (`ls-remote`; Provider-Adapter nur als Fallback für Lesen).
6. **Abgrenzungs-Zusicherung:** Es entsteht **kein** schreibender
   Code-Backend-Adapter und kein API-Merge-Pfad (SOLL-186 ist
   KONZEPT-DONE; ein API-Merge bliebe ein eigener, späterer Strang mit
   FK-29-Äquivalenznachweis).

### Out of Scope (mit Owner)

- **Command-Queue-Trägerschicht** (Endpoints, Ack/Result-Mechanik,
  Result-Fencing, `provision_worktree`/`teardown_worktree`-Executor):
  **AG3-145**.
- **Push-Barrieren, serverseitige Push-Verifikation, Edge-Push-Gate,
  Dienst-Identität, Ref-Schutz**: **AG3-147** (diese Story konsumiert den
  Prüfpunkt).
- **Provider-Adapter/`ls-remote`-Lesefläche**: **AG3-146**.
- **`takeover_reconcile`, Quarantäne, Guard-Zustände**: **AG3-151**.
- **Edge-Tool-Kommandos Takeover/Abort/Recover**: **AG3-154**.
- **Vertragsänderungen am Merge-Block** (Reihenfolge, CAS, Rollback,
  Multi-Repo-Barriere, Sanity-Gate-Semantik, Sonar-Applicability): keine —
  ausdrücklich nicht Gegenstand dieser Story (FK-29 §29.1a.2–.6 und
  §29.1.6 sind unverändert gültig).

## Betroffene Dateien

| Datei | Änderungsart | Zweck |
|---|---|---|
| `src/agentkit/backend/closure/phase.py` | ändern | `_reach_merge_done` (:392-405) beauftragt `merge_local` über die Command-Queue und schreibt Substates/Progress aus dem Result fort; Vorbedingungs-Prüfpunkt (AG3-147) vor Auftrag |
| `src/agentkit/backend/closure/merge_sequence.py` | ändern | Backend-Git-Mechanik raus (:753-754, :858-885, :889, :903, :1061-1078, :1213, :1255); Vertrag/Ordnung bleibt als typisiertes Auftrags-/Result-Modell + Result-Bewertung erhalten |
| `src/agentkit/backend/closure/multi_repo_saga.py` | ändern | `SubprocessGitBackend` (:76-95) und Saga-Git-Bausteine (:122/:147/:191/:264/:324) aus dem Backend-Prozess in den Edge-Executor verlagert; Saga-Stufen-/Rollback-Vertrag unverändert |
| `src/agentkit/backend/closure/runtime_ports.py` | ändern | Fast-Sanity-Git-Checks (:112-181) und `_read_final_diff` (:367-386) laufen Edge-seitig im Auftrag bzw. auf gemeldetem/gepushtem Stand |
| `src/agentkit/backend/verify_system/pre_merge_runner/scan_runner.py` | ändern | `tree_hash_of_commit`-Read (:116-118) Edge-seitig erhoben/Result-getragen |
| `src/agentkit/backend/verify_system/sonarqube_gate/runtime_wiring.py` | ändern | Worktree-HEAD-/Tree-Reads (:238/:286-298) Edge-seitig erhoben; QG-/Attestation-Verifikation bleibt lesend backend-seitig |
| `src/agentkit/backend/bootstrap/composition_root.py` | ändern | `SubprocessGitBackend`-Wiring (:2886-2928) entfällt; Wiring des Auftrags-/Result-Wegs |
| `src/agentkit/backend/utils/git.py` | ändern | Nach dem Umzug verbleibende Backend-Konsumenten: keine — Restfunktionen entfernen oder in den Edge-Executor überführen (Abschluss des AG3-145-Inventars) |
| `src/agentkit/harness_client/projectedge/**` (Executor-Modul aus AG3-145) | ändern | `merge_local`-Executor: vollständiger Block dev-lokal (Lock, Kandidat, clean, Build/Test/Scan-Anstoß, CAS-Push, Rollback, Teardown), Result-Meldung |
| `src/agentkit/bundles/target_project/tools/agentkit/projectedge.py` | ändern | Edge-seitige `merge_local`-Ausführung im deployten Tool (Abgrenzung: AG3-154) |
| `tests/unit/**`, `tests/integration/**`, `tests/contract/**` | neu/ändern | Vertrags-Äquivalenz-Tests über den Auftragsweg (CAS-Failure/Rollback/ESCALATED), Cross-Resume-Test, Vorbedingungs-Negativtest, Fencing-Negativtest |

## Akzeptanzkriterien

1. **Kein Backend-Git in der Closure:** Nach dem Umzug führt kein
   Backend-Codepfad der Closure einen git-Subprocess auf
   Worktrees/Repos aus (`SubprocessGitBackend`-Wiring entfernt;
   Konformanz-Grep über die im AG3-145-Inventar dieser Story
   zugeordneten Fundstellen inkl. `scan_runner.py`/`runtime_wiring.py`/
   `runtime_ports.py`); die einzigen Code-Backend-Kontakte der Closure
   sind lesend/verifizierend (Ref-Read).
2. **Vertrags-Äquivalenz:** Über den Auftragsweg sind die
   FK-29-Vertragspfade unverändert bewiesen — Erfolgsfall
   (Kandidatenbildung → Grün-Barriere → Push innerhalb des Locks →
   ff-only-Merge + CAS gegen `locked_sha`), CAS-Failure → Rollback auf
   `pre_merge_sha` + fail-closed Eskalation (kein Clobber), Lock-Drift →
   Re-Setup. Die bestehenden Vertrags-/Golden-Tests werden auf den
   Auftragsweg umgezogen, nicht aufgeweicht (identische
   Entscheidungs-Semantik; Negativpfade an der Phasengrenze).
3. **Multi-Repo unverändert:** Atomare Grün-und-FF-Mergbarkeits-Barriere
   über alle Repos vor dem ersten Push; partieller Push → ESCALATED mit
   kompensierender Recovery und per-Repo-Progress
   (`ClosurePayload.multi_repo`) — über den Edge-Weg verprobt
   (FK-29 §29.1.6-Semantik; Single-Repo als Ein-Element-Fall desselben
   Pfads).
4. **Vorbedingung fail-closed:** Ohne serverseitig verifizierten Push
   (AG3-147-Prüfpunkt) wird kein `merge_local`-Auftrag erzeugt —
   Negativtest am Closure-Eintritt: unverifizierter Push → Blockade,
   kein Auftrag, keine Side-Effects.
5. **Cross-Resume:** Eine Closure-Fortsetzung ohne lokalen Worktree der
   ausführenden Session provisioniert vor `merge_local` einen sauberen
   Worktree aus dem maßgeblichen gepushten Stand (Integrationstest über
   den echten Resume-Pfad); scheitert die Reprovisionierung, startet
   kein Merge (fail-closed).
6. **Result-Fencing:** Ein `merge_local`-Result einer Session, deren
   Ownership nicht (mehr) dem aktiven Record entspricht, wird über die
   AG3-145-Fence deterministisch abgewiesen — ohne Steuerwirkung auf
   Substates/Progress und ohne Story-Transition (Negativpfad).
7. **Idempotenz-/Recovery-Erhalt:** Ein bereits erreichtes `merge_done`
   wird nie erneut ausgeführt (bestehende Substate-Recovery bleibt
   semantisch grün über den Auftragsweg); ein wiederholtes Result zum
   selben Auftrag ist über den op_id-Vertrag idempotent.
8. **Kein API-Merge:** Es existiert kein schreibender
   Code-Backend-Adapter-Pfad für den Merge (Code-Beweis; Abgrenzung
   SOLL-186/FK-29-Äquivalenzvorbehalt dokumentiert).
9. Coverage ≥ 85 % gehalten; `mypy` strict (inkl. `--platform linux`)
   und `ruff` ohne neue Ausnahmen; ARCH-55. Neue Persistenz wird nicht
   erwartet; sollte das Result-/Progress-Design dennoch Schema brauchen,
   gilt K5 (Postgres-only, fail-closed).

## Definition of Done

- Alle Akzeptanzkriterien erfüllt; Gate-Suite grün (`pytest -n0`
  unit/integration/contract, Coverage ≥ 85, `mypy src` + `--platform linux`,
  `ruff`, 4 Konzept-Gates).
- Codex-Review PASS.
- Auf `origin/main` gemerged; `status.yaml` → `completed`;
  README-Backlog-Snapshot (§6.7) nachgezogen.

## Abdeckung (Traceability)

**Deckt ab:** SOLL-185, SOLL-187, SOLL-189.

## Konzept-Referenzen

- FK-29 §29.1a.1 (Ausführungsort: gesamter Block vom Edge über die
  Command-Queue, Auftragsart `merge_local`; „Vertraglich ändert sich
  dadurch nichts" — Kandidatenbildung, Lock, `locked_sha`-CAS,
  `pre_merge_sha`-Rollback, Multi-Repo-Stufen; Code-Backend-API
  ausschließlich lesend/verifizierend; API-Merge nur mit
  FK-29-Äquivalenznachweis; Cross-Fall: Reprovisionierung vor
  `merge_local`; Dimension 9 verifiziert, vermisst nicht)
- FK-29 §29.1a.2–.3 (Merge-Serialisierungs-Lock, strikte Sequenz),
  §29.1.6 (Multi-Repo-Atomicity, ESCALATED, kompensierende Recovery) —
  unveränderte Verträge, die der Umzug erhalten muss
- FK-12 §12.5.2 („Ausführungsort des Merge-Blocks": Project Edge via
  `merge_local`; Ordnung defers_to FK-29), §12.7.1 (Closure-Zeile:
  Edge-Auftrag `merge_local`; Push-Verifikation serverseitig via
  git-Protokoll-Ref-Read, Provider-Adapter nur Fallback)
- FK-12 §12.4.3 (Push-Erfolg serverseitig verifiziert vor Merge —
  Vorbedingung, Durchsetzung in AG3-147)
- FK-91 §91.1b (Auftragsart `merge_local`; Result-Fencing nach Regel 15)
- Decision-Record `2026-07-02-k1-worktree-topologie.md` (Konsequenz 2:
  Hybrid mit Edge-Merge als Default; Alternativen-Abschnitt: API-Merge
  verworfen — kein exact-old-head-CAS, keine Kandidatenbildung, keine
  Multi-Repo-Rollback-Semantik in der GitHub-API)

## Guardrail-Referenzen

- **KONZEPTTREUE:** FK-29-VERTRAG UNVERÄNDERT — jede Abweichung von
  Sequenz/CAS/Rollback/Multi-Repo-Semantik ist ein Konzeptkonflikt und
  hart zu stoppen; diese Story verschiebt ausschließlich den
  Ausführungsort.
- **FAIL-CLOSED:** Kein Auftrag ohne verifizierten Push; kein Merge ohne
  Reprovisionierung im Cross-Fall; CAS-Failure eskaliert mit Rollback,
  nie Clobber; abgewiesene Results haben keine Steuerwirkung.
- **NO ERROR BYPASSING:** Der normative Recovery-Pfad bei
  Nicht-FF-Fähigkeit bleibt der erneute Closure-Lauf mit offizieller
  Policy `no_ff` — keine manuellen Rebases/Force-Pushes über den
  Auftragsweg.
- **SINGLE SOURCE OF TRUTH:** Merge-Gegenstand ist ausschließlich der
  gepushte, grün-vermessene Story-Branch; Substate-Wahrheit bleibt
  `ClosurePayload`/`ClosureProgress` — das Result ist Meldung, nicht
  zweite Wahrheit.
- **Testing-Guardrails:** Negativpfade an der Closure-Phasengrenze
  (Vorbedingung, CAS-Failure, partieller Push, gefenctes Result) sind
  Pflicht; Closure-State über echte Vorgängerphasen erzeugt.

## Querschnitts-Auflagen

- **K5 Postgres-only:** Kein neuer Schema-Bedarf erwartet (der Auftrag
  läuft über `edge_command_records` aus AG3-145); falls das
  Result-/Progress-Design doch Persistenz ergänzt, ist sie Postgres-only,
  fail-closed (`_require_postgres_control_plane_backend`,
  `control_plane/runtime.py:2119`).
- **Blutgruppen-Klassifikation**
  (`concept/methodology/software-blutgruppen.md`): Vertrags-/
  Sequenz-Modell, Result-Bewertung und Vorbedingungs-Prädikate (Backend)
  = **A**; Auftrag/Result-Mapper = **R**; Edge-Executor-Git-Mechanik
  (dev-lokale Subprocesses im `harness_client`) = **T**. Der A-Kern
  bleibt AT-frei.
- **Bundle-Assets:** **Betroffen** —
  `bundles/target_project/tools/agentkit/projectedge.py` erhält die
  Edge-seitige `merge_local`-Ausführung (Closure-Merge ist
  Zielprojekt-Edge-Verhalten). Abgrenzung verifiziert: das Tool trägt
  heute nur dünne Phasen-Kommandos (u. a. `closure-complete`, :142 ff.);
  die Takeover-/Abort-/Recover-Kommandos liegen in **AG3-154**, nicht
  hier.
