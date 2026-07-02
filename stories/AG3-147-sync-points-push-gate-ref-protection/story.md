# AG3-147 — Sync-Punkte + Push-Gate + Ref-Schutz: pushed-only-Durchsetzung mit harten fail-closed Push-Barrieren, serverseitiger `ls-remote`-Verifikation, Edge-Push-Gate und `story/*`-Ref-Schutz

- **Typ:** implementation
- **Größe:** L
- **depends_on:** [AG3-145, AG3-146]
  - **AG3-145** — `sync_push` läuft über die Edge-Command-Queue; die
    Result-Typen `push_status_report`/`branch_ref_report` und das
    Regel-15-Result-Fencing sind deren Trägerschicht (GAP §4:
    ST-14a → ST-15, „sync_push läuft über die Queue").
  - **AG3-146** — die Ref-Schutz-Administration und die serverseitigen
    Ref-Reads (`ls-remote`) laufen über die Provider-Adapter-Schnittstelle
    und deren Capability-Deklaration (GAP §4: ST-16 → ST-15,
    „Ref-Schutz-Administration braucht den Provider-Adapter").
- **Quell-Konzept:** FK-10 §10.2.4b (pushed-only, Sync-Punkte-Hybrid,
  Push-Frische, WIP-Ref-Verwurf, dauerhaft scheiternde Barriere) und
  §10.6.1 (Remote-Fehlerbild); FK-12 §12.1.3 (Dienst-Identität +
  regelgeschützte `story/*`-Refs, Degradations-Regel), §12.4.3
  (Push-Erfolg serverseitig verifiziert vor Merge); FK-15 §15.5.1
  (Dienst-Identität als Credential-Klasse), §15.5.4 (zweistufiges
  Schutzmodell, Edge-Push-Gate online-pflichtig, kein
  Bundle-Re-Sync-Fallback für den Push-Pfad); FK-55 §55.9
  (offizieller Edge-Push-Pfad, doppelte Sperre für disowned Sessions);
  FK-91 §91.1b (serverseitige Push-Verifikation, `sync_push`)
- **Herkunft:** GAP-Analyse Session-Ownership v4
  (`_temp/gap-analyse-session-ownership.md`), Story-Kandidat GAP-ST-15;
  normative Basis Commits 3ae011e4 / 1bb4ed8a / 58c190b7 (+ Decision-Records
  unter `concept/_meta/decisions/`, insb.
  `2026-07-02-k1-worktree-topologie.md`).

## Kontext / Problem

PO-Entscheidung II (FK-10 §10.2.4b): Was nicht auf den Story-Branch
committed **und** gepusht ist, existiert für AgentKit nicht und ist nie
übernahmefähig. Die Durchsetzung fehlt heute vollständig (am Code
verifiziert 2026-07-02):

- **Die einzige Push-Barriere entscheidet rein lokal:** Der
  Structural-Check `completion.push`
  (`verify_system/structural/checks/branch_checks.py:173-201`,
  Stage-Registry `verify_system/stage_registry/data.py:99`) entscheidet
  auf `ChangeEvidence.pushed` — erhoben durch einen **backend-lokalen
  git-Subprocess** auf dem Worktree
  (`structural/system_evidence.py:44-87`; produktiver Provider
  `_SubprocessGitChangeEvidenceProvider`,
  `bootstrap/composition_root.py:1345-1373`, Wiring :1229/:2297). Eine
  serverseitige Verifikation gegen das Code-Backend existiert nicht (Grep
  `ls-remote` in `src/agentkit/`: null Treffer) — genau das von
  SOLL-142/170 verbotene „allein lokal".
- **Kein offizieller Edge-Push-Pfad:** Grep `push` über
  `src/agentkit/harness_client/`: **null Treffer**. Es gibt kein
  Push-Gate, keine Online-Ownership-Verifikation vor dem Push, keine
  Absicherung gegen ein stales ACTIVE-Bundle (der Re-Sync-Fallback aus
  FK-56 §56.9a würde heute auch für Push-Entscheidungen gelten — für den
  Push-Pfad laut FK-15 §15.5.4 ausdrücklich verboten).
- **Keine Sync-Punkte:** Es existieren weder opportunistische Pushes je
  Commit noch Branch-Ref-/Push-Status-Meldungen noch ein sichtbarer
  Push-Rückstand oder eine Push-Frische-Lesefläche (Grep
  `push_lag`/`push_status`/`branch_ref_report`: null Treffer; das Feld
  `branch_ref` in `verify_system/contract.py:207` und
  `implementation/handover/packager.py:148-192` ist ein reiner
  Envelope-Feldname des Worker-Handovers, kein Meldemechanismus).
- **Keine Dienst-Identität:** Das einzige Credential-Modell ist das
  persönliche Entwickler-Token via `gh auth token`/keyring/
  credentials-file (`integration_clients/github/client.py:34-88`) — die
  FK-15-§15.5.1-Zeile „AK3-/Edge-Dienst-Identität (backend-verwaltet, nie
  im Repo)" hat kein Code-Gegenstück.
- **Kein Ref-Schutz:** Es gibt keinerlei `story/*`-Schutz-Administration
  und keine Capability-Abfrage; direkte Entwickler-Pushes (auch
  Fast-Forward) sind unverhindert.
- **QA-/Review-Grenz-Evidenz ist ebenfalls backend-lokal** (Teil des
  Ausführungsort-Inventars aus AG3-145, dieser Story zugeordnet):
  QA-Zyklus-Fingerprint per `git diff origin/main..HEAD --stat`
  (`verify_system/qa_cycle/fingerprint.py:12/:43` ff.) und
  Diff-Expansion der Evidence-Assemblierung
  (`verify_system/evidence/request_resolver.py:196-210`).
- **Abgrenzung Closure:** Die Closure pusht heute selbst backend-seitig
  (`closure/multi_repo_saga.py:147/:264`) — dieser Umzug liegt in
  AG3-152; die **Verifikationspflicht** „Push-Erfolg serverseitig
  verifiziert, bevor der Merge beginnt" (SOLL-190, FK-12 §12.4.3)
  entsteht hier und ist Vorbedingung für produktives `merge_local`.

Ohne diese Story bleibt der Verlustkorridor unbegrenzt und unsichtbar,
und AG3-148 (Challenge braucht Push-Frische/`base_sha` aus gemeldeten
Pushes) sowie AG3-152 (Push-Verifikation vor Merge) sind blockiert.

## Scope

### In Scope

1. **Harte Push-Barrieren (Pflicht, fail-closed)** an den vier
   Grenz-Typen: Phasen-Abschlüsse (`completion.push`-Structural-Check —
   der Check-Katalog FK-33 bleibt, Erhebung/Verifikation stellen um),
   QA-Zyklus-Grenzen, Yield-Points, Closure-Eintritt. Verifikation ist
   **zweistufig und beides Pflicht**: Edge-Erhebung (Auftragsart
   `sync_push` über die AG3-145-Queue; Results `push_status_report` +
   `branch_ref_report` mit Head-SHA je teilnehmendem Repo) **plus**
   serverseitiger Ref-Read auf den gepushten Story-Branch (`ls-remote`
   über die AG3-146-Lesefläche). Die Edge-Meldung allein ist nie
   hinreichend. Ohne verifizierten Push kein Phasen-Abschluss.
   [SOLL-141, 142, 170]
2. **Opportunistische Pushes (best-effort, queued):** nach jedem
   AK3-registrierten Commit; Scheitern blockiert die lokale Arbeit
   nicht, wird aber als sichtbarer **Push-Rückstand** geführt. Dauerhaft
   scheiternde Barriere (Remote nicht erreichbar): lokale Arbeit läuft
   weiter, der Abschluss bleibt fail-closed blockiert, der Rückstand
   sichtbar — Eskalation an den Menschen statt Bypass (FK-10 §10.6.1).
   [SOLL-143, 146]
3. **Push-Frische als persistierte Lesefläche** (Postgres-only, K5):
   je `(story, run, repo)` letzter gemeldeter Head-SHA + Zeitpunkt +
   Rückstands-Hinweis — die Datenbasis für Eigentumslage-Anzeige und
   Takeover-Challenge (Konsumenten: AG3-148/AG3-153). **Sync-Punkte lösen
   nie Ownership-Wirkungen aus**: Stille/Frische ist Information, nie
   Entscheidung — es gibt keinerlei Automatik von Push-Stille zu
   Transfer/Status-Wechsel. [SOLL-144]
4. **Edge-Push-Gate (online-pflichtig):** Der **offizielle Edge-Push-Pfad**
   ist die einzige sanktionierte Push-Mechanik für `story/*`: Er
   verifiziert die Ownership online unmittelbar vor dem Push (bounded);
   ohne Server-Bestätigung kein Push — offline heißt: lokale Arbeit ja,
   Push nein. Der Bundle-Re-Sync-Fallback (FK-56 §56.9a) gilt für den
   Push-Pfad ausdrücklich **nicht**: ein stales ACTIVE-Bundle erlaubt
   keinen Push. Ex-Owner scheitern damit **zweifach** (Gate +
   Ref-Schutz); Edge-Selbstdisziplin allein ist als Schutz unzureichend.
   [SOLL-174, 175]
5. **Dienst-Identität als Credential-Klasse:** Geschrieben wird auf
   `story/*` nur über die AK3-/Edge-Dienst-Identität (provider-neutrale
   Service-Identität; konkrete Mechanik ausschließlich im
   Provider-Adapter aus AG3-146); AK3 gibt die Schreibfähigkeit nur für
   den aktuellen `(owner_session, ownership_epoch)` frei; das Credential
   ist backend-verwaltet, liegt nie im Repository und ist nicht das
   persönliche Entwickler-Token (FK-15 §15.5.1-Zeile). [SOLL-173, 177]
6. **Ref-Schutz `story/*` als Provider-Capability:** Administration über
   die AG3-146-Capability `ref_protection_administration`; direkte
   Entwickler-Pushes sind verboten — ausdrücklich auch
   Fast-Forward-Pushes. **Degradations-Regel:** Das Edge-Push-Gate ist
   die überall verpflichtende, provider-unabhängige Basis; kann ein
   Provider die Ref-Schutz-Capability nicht abbilden, ist das ein
   dokumentierter, projektsichtbarer Betriebs-Befund mit
   **WARNING-Pflicht** (Severity-Semantik: Handlungsauftrag mit
   aufschiebender Wirkung, aktiv gespiegelt — kein stilles
   Liegenlassen), niemals stilles Weglassen. [SOLL-171, 172, 176, 178]
7. **WIP-Ref-Verwurf als Zusicherung:** Der offizielle Push-Pfad kennt
   ausschließlich `story/{story_id}` als Ziel-Ref; es gibt keinen
   Codepfad, der uncommittete Stände als eigenen Ref pusht. [SOLL-145]
8. **Umstellung der Grenz-Evidenz-Leseflächen** (zugeordnet aus dem
   AG3-145-Ausführungsort-Inventar): `check_completion_push` +
   `ChangeEvidence.pushed` entscheiden auf Edge-Meldung + serverseitiger
   Verifikation statt backend-lokalem Subprocess; der QA-Zyklus-
   Fingerprint und die Diff-Expansion der Evidence-Assemblierung werden
   auf die an der Grenze gemeldeten Head-SHAs bzw. die
   Adapter-Compare-/Edge-Meldungs-Lesefläche umgestellt (FK-10 §10.2.4a
   Option b). Die Check-Kataloge (FK-33/FK-27) bleiben unverändert —
   nur Erhebung/Verifikation wandern.
9. **Push-Verifikation vor Merge (SOLL-190):** Der Prüfpunkt „aktueller
   Story-Branch in allen beteiligten Repos serverseitig als gepusht
   verifiziert" steht als wiederverwendbare Vorbedingung bereit —
   AG3-152 konsumiert ihn vor produktivem `merge_local`.

### Out of Scope (mit Owner)

- **Command-Queue-Trägerschicht** (Endpoints, Ack/Result, Fencing):
  **AG3-145** — hier werden nur `sync_push`-Aufträge und deren Results
  fachlich gefüllt.
- **Provider-Adapter-Schnittstelle + `ls-remote`-Lesefläche + Capability-
  Deklaration**: **AG3-146** — hier werden die Capabilities Ref-Schutz/
  Dienst-Identität implementiert bzw. administriert.
- **Closure-Merge-Umzug** (`merge_local`, Backend-Push der Closure raus):
  **AG3-152**.
- **Challenge/Confirm, `takeover_base_sha`-Materialisierung,
  Verlustkorridor-Pflichttext im Challenge**: **AG3-148** (konsumiert die
  Push-Frische); **Frontend-Anzeige** (Cockpit/Overlay): **AG3-153**.
- **Takeover-Reconcile/Quarantäne/Guard-Zustände**: **AG3-151**.
- **Disown-Verhalten/doppelte Sperre als Capability-Regel-Durchsetzung im
  Enforcement** (FK-55 §55.8.3-Familie): **AG3-149** — hier entsteht die
  Push-seitige Doppel-Sperre (Gate + Ref-Schutz).

## Betroffene Dateien

| Datei | Änderungsart | Zweck |
|---|---|---|
| `src/agentkit/backend/control_plane/push_sync.py` | neu | Sync-Punkt-Modell (Grenz-Typen), Barrieren-Prädikat (Edge-Meldung ∧ Server-Ref-Read), Push-Frische-/Rückstands-Records, Freigabe-Regel `(owner_session, ownership_epoch)` — Blutgruppe A |
| `src/agentkit/backend/state_backend/postgres_schema.sql` + `postgres_store.py` + `store/facade.py` (+ `_public_api_names.py`, `__init__.pyi`) | ändern | Persistenz Push-Frische/Push-Rückstand je `(story, run, repo)` (Postgres-only, K5) |
| `src/agentkit/backend/control_plane/runtime.py` | ändern | Barrieren-Prüfpunkt an den Phasen-/Closure-Grenzen (complete/closure-Eintritt); Konsum der `sync_push`-Results; keine Ownership-Wirkung aus Frische |
| `src/agentkit/backend/verify_system/structural/checks/branch_checks.py` | ändern | `check_completion_push` (:173-201) entscheidet auf Edge-Meldung + serverseitiger Verifikation (Check-ID/Katalog unverändert) |
| `src/agentkit/backend/verify_system/structural/system_evidence.py` + `bootstrap/composition_root.py` | ändern | Push-Anteil der `ChangeEvidence` (:44-87) aus dem lokalen Subprocess-Provider (:1345-1373, Wiring :1229/:2297) herausgelöst; Evidenz-Quelle = Meldungen/Server-Read |
| `src/agentkit/backend/verify_system/qa_cycle/fingerprint.py` | ändern | QA-Grenz-Fingerprint an gemeldeten Head-SHA verankert statt backend-lokalem `git diff --stat` |
| `src/agentkit/backend/verify_system/evidence/request_resolver.py` | ändern | Diff-Expansion (:196-210) liest gepushten Stand via Adapter-Compare/Edge-Meldung statt Backend-Subprocess |
| `src/agentkit/backend/code_backend/**` + `src/agentkit/integration_clients/github/**` (AG3-146-Flächen) | ändern | Implementierung der Capabilities Ref-Schutz-Administration + Dienst-Identität-Mechanik im GitHub-Adapter; Degradations-Befund bei fehlender Capability |
| `src/agentkit/harness_client/projectedge/client.py`, `runtime.py` (+ Push-Gate-Modul) | ändern/neu | Offizieller Edge-Push-Pfad: Online-Ownership-Verifikation (bounded) vor Push; `sync_push`-Executor (Barriere + opportunistisch); kein Bundle-Fallback für Push-Entscheidungen |
| `src/agentkit/bundles/target_project/tools/agentkit/projectedge.py` | ändern | Edge-seitige `sync_push`-Ausführung + Push-Gate im deployten Tool (Abgrenzung: keine Takeover-/Abort-/Recover-Kommandos — AG3-154) |
| `src/agentkit/backend/control_plane_http/app.py` | ändern | Lesefläche Push-Frische/Rückstand (Read-Model für AG3-148/153); Barrieren-Fehlerbild im Regel-8-Fehlervertrag |
| `tests/unit/**`, `tests/integration/**`, `tests/contract/**` | neu/ändern | Barrieren-Negativpfade an allen vier Grenz-Typen, Gate-Offline-Tests, Degradations-Befund-Pin, Push-Frische-Contract |

## Akzeptanzkriterien

1. **Barriere zweistufig, fail-closed:** Ein Phasen-Abschluss ohne
   verifizierten Push wird deterministisch blockiert. Beide
   Negativpfade einzeln bewiesen: (a) Edge meldet Push-Erfolg, aber der
   serverseitige Ref-Read bestätigt den gemeldeten Head-SHA nicht →
   Blockade; (b) Server-Read würde passen, aber es liegt keine
   Edge-Meldung vor → Blockade. Die Edge-Meldung allein genügt nie.
2. **Alle vier Grenz-Typen:** Phasen-Abschluss, QA-Zyklus-Grenze,
   Yield-Point und Closure-Eintritt sind einzeln als harte Barrieren
   getestet — an echten Phasengrenzen (Pipeline-State über echte
   Vorgängerpfade erzeugt, nicht manuell zusammengesetzt).
3. **Multi-Repo:** Die Barriere gilt je teilnehmendem Repo; ein
   ungepushtes Repo blockiert den Abschluss auch dann, wenn alle anderen
   verifiziert sind (Teildivergenz-Negativtest).
4. **Opportunistische Pushes:** Ein scheiternder opportunistischer Push
   blockiert die lokale Arbeit nicht, erzeugt aber sichtbaren
   Push-Rückstand; bei dauerhaft nicht erreichbarem Remote bleibt der
   Abschluss fail-closed blockiert — es existiert kein Bypass- oder
   „weiche Regel"-Pfad (SOLL-146; FK-10 §10.6.1-Fehlerbild).
5. **Push-Frische ohne Ownership-Wirkung:** Die Lesefläche liefert je
   Repo letzten gemeldeten Head-SHA + Zeitpunkt (Contract-Pin);
   präparierte Stille/veraltete Frische löst keinerlei Status- oder
   Ownership-Übergang aus (Negativtest: kein Codepfad von Frische zu
   Transfer).
6. **Edge-Push-Gate online-pflichtig:** Ohne erreichbaren Server
   unterbleibt der Push (Offline-Negativtest); ein stales ACTIVE-Bundle
   erlaubt keinen Push — der Re-Sync-Fallback greift für den Push-Pfad
   nachweislich nicht (Negativtest gegen den FK-56-§56.9a-Fallback);
   die Gate-Prüfung ist bounded (keine unbegrenzte Blockade des lokalen
   Prozesses).
7. **Ex-Owner scheitert zweifach:** Nach präpariertem Ownership-Wechsel
   (sanktionierte AG3-137/142-Fläche) verweigert (a) das Gate die
   Server-Bestätigung und (b) die Ref-Schutz-/Dienst-Identitäts-Freigabe
   das Schreiben — ausdrücklich auch für einen Fast-Forward-Push
   (SOLL-172; beide Stufen einzeln getestet).
8. **Dienst-Identität:** `story/*`-Schreibzugriff läuft über das
   backend-verwaltete Dienst-Credential (Mechanik nur im Adapter); das
   Credential erscheint nie im Repo/Worktree; das persönliche
   Entwickler-Token erhält keine `story/*`-Schreibfreigabe
   (Negativtest der Credential-Auswahl).
9. **Degradations-WARNING:** Gegen einen Provider(-Fake) ohne
   Ref-Schutz-Capability entsteht ein deterministischer, persistierter,
   projektsichtbarer Betriebs-Befund (WARNING, contract-gepinnt); das
   Push-Gate bleibt aktiv (verpflichtende Basis); es gibt keinen stillen
   Weiterbetrieb ohne Befund.
10. **Kein WIP-Ref:** Der offizielle Push-Pfad akzeptiert ausschließlich
    `story/{story_id}` als Ziel-Ref (Negativtest mit abweichendem Ref);
    uncommittete Stände sind nie Push-Gegenstand.
11. **Evidenz-Umstellung:** `completion.push` entscheidet nachweislich
    nicht mehr auf backend-lokaler Subprocess-Erhebung (Code-Beweis +
    Regressionstest: Check-Semantik PASS/FAIL unverändert);
    QA-Fingerprint und Evidence-Diff-Expansion lesen keine
    Backend-Worktree-Gits mehr (Konformanz-Grep auf die in AG3-145
    inventarisierten Fundstellen dieser Story).
12. **Merge-Vorbedingung bereit:** Der wiederverwendbare Prüfpunkt
    „Story-Branch in allen beteiligten Repos serverseitig als gepusht
    verifiziert" existiert mit eigenem Vertragstest (Konsument: AG3-152,
    SOLL-190).
13. **K5:** Push-Frische-/Rückstands-Tabellen sind Postgres-only,
    fail-closed (`_require_postgres_control_plane_backend`-Muster,
    `control_plane/runtime.py:2119`); kein SQLite-Spiegel (Negativtest).
14. Coverage ≥ 85 % gehalten; `mypy` strict (inkl. `--platform linux`)
    und `ruff` ohne neue Ausnahmen; ARCH-55 (englische Wire-Keys,
    Befund-Codes, Feldnamen).

## Definition of Done

- Alle Akzeptanzkriterien erfüllt; Gate-Suite grün (`pytest -n0`
  unit/integration/contract, Coverage ≥ 85, `mypy src` + `--platform linux`,
  `ruff`, 4 Konzept-Gates).
- Codex-Review PASS.
- Auf `origin/main` gemerged; `status.yaml` → `completed` (Vorbedingung für
  AG3-148 und AG3-152); README-Backlog-Snapshot (§6.7) nachgezogen.

## Abdeckung (Traceability)

**Deckt ab:** SOLL-140–146, SOLL-170–178, SOLL-190.

## Konzept-Referenzen

- FK-10 §10.2.4b (pushed-only-Regel + Verlustkorridor; Sync-Punkte-Hybrid:
  harte Barrieren an Phasen-Abschlüssen/QA-Grenzen/Yield-Points/
  Closure-Eintritt mit Edge-Erhebung **plus** serverseitigem Ref-Read;
  opportunistische Pushes; Push-Frische als Information, nie Entscheidung;
  WIP-Ref-Push verworfen; dauerhaft scheiternde Barriere), FK-10 §10.6.1
  (Remote nicht erreichbar: Barrieren bleiben fail-closed blockiert)
- FK-91 §91.1b (Auftragsart `sync_push`; Result-Typen `branch_ref_report`/
  `push_status_report`; „Serverseitige Push-Verifikation: … die
  Edge-Meldung allein ist nie hinreichend")
- FK-12 §12.1.3 (regelgeschützte `story/*`-Refs als Capability-Anforderung;
  Verbot direkter Entwickler-Pushes inkl. Fast-Forward; Schreibfreigabe nur
  für aktuellen `(owner_session, ownership_epoch)`; zweifaches Scheitern
  des Ex-Owners; Degradations-Regel mit WARNING-Pflicht), §12.4.3
  (Push-Erfolg serverseitig verifiziert — Vorbedingung des Merge)
- FK-15 §15.5.1 (Dienst-Identität als Credential-Klasse, backend-verwaltet,
  nie im Repo; Abgrenzung zum persönlichen GitHub-Token), §15.5.4
  (zweistufiges Schutzmodell; Edge-Push-Gate online-pflichtig, bounded;
  Re-Sync-Fallback gilt nicht für den Push-Pfad; Edge-Selbstdisziplin
  unzureichend)
- FK-55 §55.9 (Story-Branch-Push nur über den offiziellen Edge-Push-Pfad;
  doppelte capability-seitige Sperre für disowned Sessions)
- FK-10 §10.2.4a Option (b) (Grenz-Evidenz über gepushten Stand:
  `ls-remote`-Ref-Reads; Compare/Change-Evidence via Adapter oder
  Edge-gemeldet) — Grundlage der Evidenz-Umstellung (In-Scope 8)
- FK-56 §56.13c (Push-Frische als Bestandteil von Challenge/Anzeige —
  hier nur die Datenbasis; Konsum in AG3-148/153)
- Decision-Record `2026-07-02-k1-worktree-topologie.md` (Konsequenzen 8;
  Impact-Sweep-Zeile `completion.push`: Check-Kataloge unverändert,
  Erhebung/Verifikation nach FK-10 §10.2.4b)

## Guardrail-Referenzen

- **FAIL-CLOSED:** Jede Barriere blockiert ohne verifizierten Push; das
  Push-Gate verweigert offline; fehlende Provider-Capability erzeugt einen
  Befund statt stiller Degradation; kein „weiche Regel"-Fallback.
- **NO ERROR BYPASSING:** Dauerhaft scheiternde Pushes werden nicht
  wegerklärt — der Abschluss bleibt blockiert, die Ursache eskaliert;
  keine Umgehung der Barriere durch lokale Selbstauskunft.
- **SEVERITY-SEMANTIK (CLAUDE.md):** Die Degradations-Regel ist ein
  WARNING mit Handlungsauftrag und Spiegel-Pflicht — projektsichtbar
  persistiert, nie weggeklickt; die Barrieren selbst sind ERRORs ohne
  aufschiebende Wirkung.
- **SINGLE SOURCE OF TRUTH:** Die Push-Wahrheit ist der serverseitig
  verifizierte Remote-Stand — nicht die lokale Erhebung und nicht die
  unbestätigte Edge-Meldung; die Push-Frische ist deren eine persistierte
  Projektion.
- **FIX THE MODEL, NOT THE SYMPTOM:** Die lokale
  Subprocess-Selbstauskunft wird durch das Meldung+Verifikation-Modell
  ersetzt, nicht um einen weiteren lokalen Check ergänzt.
- **Testing-Guardrails:** Negativpfade an allen vier Grenz-Typen sind
  Pflicht; Pipeline-State über echte Vorgängerphasen erzeugt.

## Querschnitts-Auflagen

- **K5 Postgres-only:** Die neuen Push-Frische-/Rückstands-Tabellen sind
  Postgres-only, fail-closed über das
  `_require_postgres_control_plane_backend`-Muster
  (`control_plane/runtime.py:2119`, Check :2139); kein SQLite-Spiegel.
  Contract-/Integrationstests über die Postgres-Fixture, Unit-Tests über
  Ports/Fakes.
- **Blutgruppen-Klassifikation**
  (`concept/methodology/software-blutgruppen.md`): Sync-Punkt-Modell,
  Barrieren-Prädikat, Freigabe-Regel und Degradations-Regel
  (`push_sync.py`) = **A**; Wire-/Result-Mapper und HTTP-Lesefläche =
  **R**; Persistenz-Row-Funktionen = **AT/T** (im `state_backend`
  lokalisiert); Edge-Push-Gate/`sync_push`-Executor (dev-lokale
  git-Subprocesses) = **T** mit dünner **R**-Meldeschicht. Der A-Kern
  bleibt AT-frei.
- **Bundle-Assets:** **Betroffen** —
  `bundles/target_project/tools/agentkit/projectedge.py` erhält die
  Edge-seitige `sync_push`-Ausführung und das Push-Gate (der offizielle
  Push-Pfad ist Edge-Verhalten im Zielprojekt). Abgrenzung: das
  Edge-Tool-Paket für Takeover/Abort/Recover liegt in **AG3-154**.
