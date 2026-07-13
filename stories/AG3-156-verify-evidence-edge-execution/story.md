# AG3-156 — Verify-Evidenz-Ausführungsort: Request-DSL-Resolver vom Backend-Worktree-Zugriff lösen (K1-Akteursmodell), shell=True-Härtung, FK-47-Konzept-Nachzug

- **Typ:** implementation
- **Größe:** L
- **depends_on:** [AG3-144, AG3-145]
  - **AG3-145** — die worktree-abhängigen Request-Auflösungen laufen (in
    Variante a, siehe Scope 1) als Edge-Auftrag über die
    Edge-Command-Queue: neue Auftrags-/Result-Art analog `preflight_probe`
    mit bounded wait wie beim Preflight-Muster; Endpoints, Ack-Semantik,
    client-op_id-Pflicht und Regel-15-Result-Fencing sind deren
    Trägerschicht — diese Story baut keine eigene Auftragsmechanik.
  - **AG3-144** — die Anwendung der gemeldeten Auflösungs-Evidenz ist ein
    mutierender Story-Projektions-Write und muss transaktional vom aktiven
    Ownership-Lease gedeckt sein (No-Lease-no-Write, FK-91 §91.1a Regel 15;
    AG3-142-Fence `_enforce_ownership_fence_row` in DERSELBEN Transaktion,
    `SELECT … FOR UPDATE`). Ein verspätetes/Ex-Owner-Ergebnis wird
    deterministisch abgewiesen (Regel 18) — OHNE State-Write, nicht als
    Historie/Stale abgelegt.
- **Quell-Konzept:** FK-10 §10.2.4a (Topologie-Regel, Akteursmodell
  Agent/Edge/niemand, Ausführungsort-Grundsatz mit
  Fehlbetriebs-Klassifikation); FK-47 (Request-DSL und Preflight-Turn —
  Konzept-Nachzug ist Teil dieses Scopes); FK-91 §91.1b (Command-Queue-
  Auftragsvertrag); META-CONCEPT-CONSISTENCY P3 (Decision-Record-Pflicht
  bei normativen Änderungen)
- **Herkunft:** Story-Schnitt-Review 2026-07-02 — Codex-WARNING
  „Verify-System-Testevidence bleibt backend-seitiger
  shell=True-Worktree-Zugriff" + Batch-C-Befund; PO-Freigabe 2026-07-02.
  Kein GAP-Nenner-Bezug (Review-Fund).
- **Story-Nachzug 2026-07-13 (Konzept-/Spec-Konformität, PO-freigegeben):**
  Die Ergebnisanwendung war beim Schnitt (2026-07-02) gegen das async-Modell
  von AG3-144 formuliert (Ergebnisart-Registry, `stale_observation`-Routing).
  AG3-144 wurde am 2026-07-05 per bindender PO-Entscheidung neu geschnitten
  (synchron; aktiver Ownership-Lease = ALLEINIGER Fence; Ex-Owner-Ergebnisse
  werden deterministisch abgewiesen, NICHT als `stale_observation` abgelegt —
  Registry/Fence-Sicht/Stale-Store ENTFALLEN, AG3-144 Scope 3). Die Story ist
  gegen die Konzepte (FK-91 §91.1a Regel 14/15/18, FK-44 §44.3a — maßgebliche
  Norm) nachgezogen: Scope 4, AK5, AK8, depends_on- und Out-of-Scope-Zeilen.
  Kern der Story (Ausführungsort-Verlagerung Edge/Agent + shell=True-Härtung)
  ist unberührt. Zusätzlich sind einige Code-Anker seit dem Schnitt veraltet
  (Refactor-Drift, bei Umsetzung zu verifizieren): `control_plane/runtime.py`
  ist ein Package `control_plane/runtime/` (u. a. `_di.py`);
  `cli/main.py:1435-1442` → `cli/evidence_commands.py`; die
  Diff-Expansion-Restfundstelle ist durch das gelandete AG3-147 bereits
  content-basiert abgelöst (der AC1-Abschlussbeweis ist damit sofort
  erfüllbar). Ebenfalls präzisiert: das Timing-/Claim-Serialisierungs-Modell
  (Scope 1, AK4) — der Design-Freeze muss es auflösen, bevor Scope 2-8 gebaut
  wird.

## Kontext / Problem

FK-10 §10.2.4a (K1, PO-Entscheidung 2026-07-02) normiert: Worktrees leben
dev-lokal; das Backend hat **nie** physischen Worktree-Zugriff; Akteure
für physische Worktree-Operationen sind ausschließlich Agent, Project Edge
(beauftragt, meldend) oder niemand; backend-seitige Subprocess- und
Dateisystem-Zugriffe auf Worktrees sind Fehlbetrieb
(`concept/technical-design/10_runtime_deployment_speicher.md:426-461`).
Der Request-DSL-Resolver des Verify-Systems verletzt dieses Akteursmodell
heute vollständig — in einer Remote-Backend-Topologie existiert sein
Ausführungspfad schlicht nicht.

**Inventar der worktree-berührenden Resolver** (Modul
`src/agentkit/backend/verify_system/evidence/request_resolver.py`, am Code
verifiziert 2026-07-02):

| Fundstelle | Befund |
|---|---|
| `_resolve_test_evidence` :154-181 | führt das **LLM-gelieferte** Reviewer-Kommando `request.target` per `subprocess.run(request.target, cwd=repo.repo_path, shell=True, check=False, capture_output=True, timeout=REQUEST_TIMEOUT_S)` (:159-167) backend-seitig im Spawn-Worktree aus. Doppelbefund: falscher Ausführungsort (K1) **und** Injection-Risiko durch `shell=True` mit ungeprüftem LLM-Text (einziger `shell=True`-Treffer in `src/agentkit/`: :162) |
| `_resolve_runtime_binding` :143-152 | liest Worktree-Config-Dateien (`CONFIG_SUFFIXES`/`.env`) backend-seitig über `_repo_files` |
| `_resolve_file` :122-129 | physische Pfadauflösung/Glob/Namenssuche über `_exact_file_candidates` :256-264, `_glob_candidates` :266-272, `_filename_contains_candidates` :274-281 |
| `_resolve_schema` :131-136, `_resolve_callsite` :138-141 | Textsuche über Worktree-Dateien via `_text_match_candidates` :283-299 (`read_text` :296) |
| Helfer `_repo_files` :308-309 | `repo.repo_path.rglob("*")` — physischer Dateisystem-Walk über den Worktree |
| Helfer `_candidate` :318-332 | `read_text` (:331) auf Worktree-Dateien |
| `_resolve_diff_expansion` :196-227 | `git diff`-Subprocess im Worktree (:210-217) — **bereits AG3-147 zugeordnet** (siehe Abgrenzung) |

**Nicht worktree-berührend** (bleiben backend-seitig): `parse_preflight_response`
:57-79 (reines JSON-Parsing) und `_resolve_concept_source` :183-194
(liest backend-lokale `concept/`-/`stories/`-Verzeichnisse über
`story_dir`, `_project_root_for_story_dir` :361-365 — kein Ziel-Worktree).

**Aufrufkette:** Der Resolver wird im FK-47-Preflight-Turn instanziiert
(`verify_system/evidence/preflight_turn.py:76-81`); `RepoContext.repo_path`
ist ausdrücklich „Repository root or worktree path"
(`verify_system/evidence/repo_context.py:15-16`, Feld :24). Der
Review-Transport läuft über den fail-closed Port `PreflightReviewSender`
(`evidence/preflight_sender.py:28-43`) — die Co-Location-Annahme steckt
allein in der Auflösung, nicht im Transport.

**Konzeptkonflikt (Pre-K1-Stand):** FK-47 verankert den Backend-Ausführungsort
heute selbst normativ:
`concept/technical-design/47_request_dsl_und_preflight_turn.md` — Tabelle
§47.2 (Zeile `NEED_TEST_EVIDENCE` … „`subprocess.run` mit cwd=repo_root",
:100), Tabelle §47.3 („`repo_path` (als cwd für subprocess)", :115) und
Code-Skizze `_resolve_test_evidence` („subprocess.run mit
timeout=REQUEST_TIMEOUT_S, cwd=repo_root", :237-242). Der Konzept-Nachzug
(Auflösungs-Ausführungsort = Edge/Agent, nie Backend) gehört deshalb IN
diesen Story-Scope — inklusive P3-Decision-Record-Pflicht.

## Scope

### In Scope

1. **Design-Entscheidung + Konzept-Nachzug FK-47** (normativ vorgegebene
   Richtung, Detail-Design in dieser Story): Die worktree-abhängigen
   Request-Auflösungen laufen entweder
   (a) als **Edge-Auftrag** über die AG3-145-Command-Queue — neue
   Auftrags-/Result-Art analog `preflight_probe`, bounded wait wie beim
   Preflight-Muster — oder
   (b) werden dem **Agenten-Turn** zugeordnet (der Agent löst die Requests
   in seinem Worktree auf und meldet Ergebnisse).
   Die Story prüft beide Varianten im FK-47-Rahmen (Latenz im
   Preflight-Turn, Determinismus/D3-Regel, Session-/Ownership-Bindung,
   Multi-Repo, **und — entscheidend — die Interaktion mit der synchronen
   Objekt-Serialisierung nach FK-91 §91.1a Regel 13/14**: der QA-Subflow
   hält für seine Dauer den `(project_key, story_id)`-Claim, während der
   Edge-Result-POST (§91.1b) denselben Claim als mutierende Operation
   erwirbt — ein In-Request-bounded-wait unter gehaltenem Claim (Variante a
   naiv) timeoutet daher systematisch (fail-closed-by-construction, kein
   echtes RESOLVED). Der P3-Decision-Record MUSS dieses Timing-Modell
   auflösen: Wartepunkt mit Claim-Freigabe + Resume des Preflight-Turns
   vs. Auflösung im Agenten-Turn (Variante b), inkl. Ergebnis-Korrelation
   und Supersede verspäteter/epoch-drifteter Ergebnisse); der
   **Konzept-Nachzug entscheidet**. Hart normiert ist nur:
   **Ausführungsort nie Backend**; **fail-closed, wenn kein Edge erreichbar**
   (kein stiller Backend-Fallback); **keine `shell=True`-Ausführung von
   LLM-geliefertem Text ohne Kommando-Whitelist/Vertrag**. Der Nachzug
   bereinigt §47.2/§47.3/§47.5 (inkl. Code-Skizzen), zieht **FK-46**
   (`46_import_resolver.md`) mit — dort ist der backend-seitige
   Dateisystemzugriff des Import-Resolvers normativ verankert (u. a.
   Z. 68, 76-80, 247-249, 365-368; Anker bei Umsetzung verifizieren) —
   sowie den FK-28-Anteil (Scope 7), und erhält einen
   **P3-Decision-Record** unter `concept/_meta/decisions/`
   (Benennung `YYYY-MM-DD-<slug>.md`, Format-Vorbild
   `2026-07-02-k1-worktree-topologie.md`) mit Betroffenheitsmatrix;
   Konzept-Gates bleiben grün.
2. **Umbau aller inventarisierten Resolver** auf den entschiedenen
   Ausführungsort: `_resolve_test_evidence`, `_resolve_runtime_binding`,
   `_resolve_file`, `_resolve_schema`, `_resolve_callsite` samt der Helfer
   `_repo_files`/`_candidate`/`_exact_file_candidates`/`_glob_candidates`/
   `_filename_contains_candidates`/`_text_match_candidates` verlieren jeden
   backend-seitigen Worktree-Zugriff. Die D3-Mehrdeutigkeitsregel
   (FK-47 §47.4: 1 Treffer RESOLVED, mehrere/0 UNRESOLVED, nie
   Heuristik-Picking) und der 8er-Cap (`MAX_REQUESTS`) bleiben
   unverändert — die **Entscheidung** über Auflösungs-Ergebnisse bleibt
   deterministisch backend-seitig, nur die **Erhebung** wandert.
3. **Härtung `NEED_TEST_EVIDENCE` (eigenes AK):** LLM-gelieferter
   `request.target` wird nie als Shell-Text ausgeführt. Es gilt ein
   typisierter Kommando-Vertrag (Whitelist zulässiger Test-Runner-Formen,
   argumentweise Übergabe ohne Shell-Interpretation, harter Timeout) — er
   gilt am Ausführungsort (Edge/Agent) genauso wie an jeder anderen
   Stelle; ein nicht vertragskonformes Kommando wird deterministisch als
   benannter Befund abgelehnt, nie ausgeführt.
4. **Ergebnisanwendung unter dem aktiven Ownership-Lease
   (No-Lease-no-Write):** Die gemeldeten Auflösungs-Ergebnisse werden als
   mutierender Projektions-Write nur angewandt, wenn der schreibende
   Session-Kontext den aktiven `RunOwnershipRecord` hält — transaktional
   gedeckt durch den AG3-142-Lease-Fence (`_enforce_ownership_fence_row`,
   `SELECT … FOR UPDATE`, kein TOCTOU). Ein Commit ohne (aktuellen) Lease
   wird deterministisch abgewiesen (FK-91 §91.1a Regel 15/18) — OHNE
   State-Write; das Ergebnis erweitert nie das Review-Bundle.
5. **Fail-closed-Verhalten im Preflight-Turn:** Ist kein Edge erreichbar
   (bzw. meldet der Agenten-Turn nicht), enden die betroffenen Requests
   nach bounded wait als benannter, deterministischer Status (kein
   optimistisches RESOLVED, kein Backend-Selbstversuch); der Review läuft
   nach der FK-47-Fehlertoleranz mit unaufgelösten Requests weiter — der
   Reviewer wird informiert.
6. **Bundle-Asset:** `bundles/target_project/tools/agentkit/projectedge.py`
   erhält (bei Variante a) die Ausführung der neuen Auftragsart im Rahmen
   der AG3-145-Kommando-Ausführung; der Kommando-Vertrag aus Scope 3 ist
   dort durchgesetzt.
7. **Worktree-Leseflächen des Evidence-Assemblers** (gleiche Problemklasse
   im Nachbarmodul, am Code verifiziert): `evidence/assembler.py` liest
   den Worktree backend-seitig direkt — `_ensure_repo_path`-`is_dir`-Guard
   (:318-320), Datei-Reads `read_text` (:332-336, :349-353),
   Verzeichnis-Walks (:385, :416), `_safe_join`-Familie (:488-517). Diese
   Erhebungen wandern mit demselben Mechanismus und demselben
   Fail-closed-Verhalten an den entschiedenen Ausführungsort; der
   FK-28-Anteil des Konzept-Nachzugs (Scope 1) benennt die Grenze.
   **Ausgenommen bleibt** der `_change_evidence_port.collect(...)`-Aufruf
   (:199) — die Diff-/Change-Evidenz-Erhebung selbst gehört AG3-147
   (siehe Out of Scope).
8. **Import-Resolver (Stage-2-Import-Evidenz, Review-Fund der
   Schnitt-Review):** `evidence/import_resolver.py` liest Worktrees
   backend-seitig — `from_repo_contexts` übernimmt `repo.repo_path`
   (:148-150), liest Quelldateien (:154, :175), `tsconfig`/`jsconfig`
   (:274-282), Java per `rglob` (:333-335) und Bundle-Inhalte (:430-431);
   produktiv verdrahtet über `cli/main.py:1435-1442`
   (`import_evidence_provider=ImportResolver.from_repo_contexts(repos)`)
   und den Stage-2-Aufruf `assembler.py:230-238`. Diese Erhebung wandert
   mit demselben Mechanismus an den entschiedenen Ausführungsort
   (Variante a: Import-Evidenz als Teil des Auflösungs-/Assembly-Auftrags;
   Variante b: Agenten-Meldung); die deterministische Konsolidierung der
   Import-Evidenz bleibt backend-seitig. FK-46-Nachzug siehe Scope 1.

### Out of Scope (mit Owner)

- **Diff-Expansion-Evidenz** (`_resolve_diff_expansion` :196-227,
  `git diff`-Subprocess :210-217): **AG3-147** — dort verifiziert:
  Kontext-Befund „QA-/Review-Grenz-Evidenz ist ebenfalls backend-lokal …
  `evidence/request_resolver.py:196-210`"
  (`stories/AG3-147-sync-points-push-gate-ref-protection/story.md`,
  Kontext, In-Scope 8, Betroffene-Dateien-Zeile, AK 11). Diese Story
  fasst die Diff-Expansion **nicht** an — keine Doppel-Ownership; der
  FK-47-Konzept-Nachzug referenziert für diesen Request-Typ die
  AG3-147-Lesefläche (Adapter-Compare/Edge-Meldung, FK-10 §10.2.4a(b)).
- **Command-Queue-Trägerschicht** (Endpoints, Ack/Result, Regel-15-Fencing
  der Queue): **AG3-145**.
- **Ownership-Lease-Fence-Mechanismus** (`_enforce_ownership_fence_row`,
  No-Lease-no-Write-Vollständigkeit) selbst: **AG3-142/AG3-144** — hier nur
  dessen Anwendung auf den Evidenz-Write.
- **Push-/QA-Grenz-Evidenz** (`branch_checks.py`, `system_evidence.py`,
  `qa_cycle/fingerprint.py`): **AG3-147** (AG3-145-Ausführungsort-Inventar).
- **Diff-/Change-Evidenz-Erhebung des Assemblers**
  (`_change_evidence_port.collect(repo.repo_path)`, `assembler.py:199`):
  **AG3-147** — Teil der dort geowneten Push-/QA-Grenz-Evidenz. Die
  übrigen Assembler-Worktree-Reads sind In Scope (Punkt 7); es bleibt
  kein unzugeordneter Worktree-Zugriff im `verify_system/evidence/`-Modul
  zurück (PO-Entscheid 2026-07-02: keine Spiegelpflicht-Reste, Scope
  vollständig).

## Betroffene Dateien

| Datei | Änderungsart | Zweck |
|---|---|---|
| `concept/technical-design/47_request_dsl_und_preflight_turn.md` | ändern | Konzept-Nachzug: Auflösungs-Ausführungsort = Edge/Agent, nie Backend (§47.2-Tabelle :100, §47.3-Tabelle :115, Code-Skizze :237-242 bereinigt); Variante-a/b-Entscheid normiert |
| `concept/_meta/decisions/<YYYY-MM-DD>-verify-evidence-edge-execution.md` | neu | P3-Decision-Record (Entscheidung, Anlass, Alternativen a/b, Betroffenheitsmatrix; Vorbild `2026-07-02-k1-worktree-topologie.md`) |
| `src/agentkit/backend/verify_system/evidence/request_resolver.py` | ändern | Backend-seitige Worktree-Zugriffe der inventarisierten Resolver raus (:122-152, :154-181, :256-332); deterministische Ergebnis-Konsolidierung (D3) bleibt backend-seitig |
| `src/agentkit/backend/verify_system/evidence/assembler.py` | ändern | Assembler-Worktree-Reads raus (Scope 7: :318-320, :332-336, :349-353, :385, :416, :488-517) — gleiche Erhebungs-Mechanik, gleiche Fail-closed-Semantik; `_change_evidence_port.collect` (:199) bleibt (AG3-147) |
| `concept/technical-design/28_evidence_assembly_review_vorbereitung.md` | ändern | FK-28-Anteil des Konzept-Nachzugs: Erhebungs-Ausführungsort des Bundle-Aufbaus + Grenze zur AG3-147-Change-Evidenz explizit benennen |
| `concept/technical-design/46_import_resolver.md` | ändern | FK-46-Anteil des Konzept-Nachzugs: Erhebungs-Ausführungsort der Import-Evidenz = Edge/Agent, nie Backend (Z. 68, 76-80, 247-249, 365-368 bereinigen) |
| `src/agentkit/backend/verify_system/evidence/import_resolver.py` | ändern | Scope 8: backend-seitige Worktree-Reads raus (:148-150, :154, :175, :274-282, :333-335, :430-431); deterministische Import-Evidenz-Konsolidierung bleibt |
| `src/agentkit/backend/cli/main.py` | ändern | Verdrahtung des `import_evidence_provider` (:1435-1442) auf die neue Erhebungsfläche umstellen |
| `src/agentkit/backend/verify_system/evidence/request_types.py` | ändern | Benannte Result-Status für nicht erreichbare Ausführungsorte + typisierter Kommando-Vertrag für `NEED_TEST_EVIDENCE` (englische Status-/Befund-Codes, ARCH-55) |
| `src/agentkit/backend/verify_system/evidence/preflight_turn.py` | ändern | Auflösungsschritt beauftragt (Variante a) bzw. konsumiert Agenten-Meldungen (Variante b); bounded wait; Fehlertoleranz-Pfad (:76-81) |
| `src/agentkit/backend/control_plane/edge_commands.py` (AG3-145-Fläche) | ändern (Variante a) | Neue Auftrags-/Result-Art (analog `preflight_probe`) im typisierten Vokabular, contract-gepinnt |
| `src/agentkit/backend/control_plane/runtime/` (Package, seit Schnitt zerlegt) | ändern (Variante a) | Anlage der Auflösungs-Aufträge; Result-Anwendung unter dem aktiven Ownership-Lease (No-Lease-no-Write, FK-91 §91.1a Regel 15/18) |
| `src/agentkit/harness_client/projectedge/**` (Executor-Modul aus AG3-145) | ändern (Variante a) | Edge-seitige Ausführung der Auflösungs-Aufträge (Datei-/Glob-/Text-Suche, vertragskonforme Test-Ausführung ohne Shell-Interpretation) |
| `src/agentkit/bundles/target_project/tools/agentkit/projectedge.py` | ändern (Variante a) | Bundle-Asset: Ausführung der neuen Auftragsart im deployten Edge-Tool |
| `tests/unit/verify_system/**`, `tests/integration/**`, `tests/contract/**` | neu/ändern | Resolver-Umbau-Tests (Ports/Fakes), Fail-closed-/bounded-wait-Negativtests, Kommando-Vertrags-Negativtests, Contract-Pin der neuen Auftrags-/Result-Art bzw. Meldeform |

## Akzeptanzkriterien

1. **Kein Backend-Worktree-Zugriff mehr:** Für alle dieser Story
   zugeordneten Request-Typen (`NEED_FILE`, `NEED_SCHEMA`,
   `NEED_CALLSITE`, `NEED_RUNTIME_BINDING`, `NEED_TEST_EVIDENCE`) enthält
   `request_resolver.py` keinen `subprocess`-Aufruf und keinen physischen
   `repo_path`-Read mehr; dasselbe gilt für die Scope-7-Leseflächen des
   `assembler.py` und die Scope-8-Leseflächen des `import_resolver.py`.
   **Modulweiter Abschluss-Beweis:** Nach Umsetzung dieser Story und
   AG3-147 existiert in `src/agentkit/backend/verify_system/evidence/`
   kein backend-seitiger Worktree-Zugriff mehr — Grep-/Code-Beweis über
   das GESAMTE Modul als Review-Artefakt (einzige zulässige
   Restfundstellen bis zur AG3-147-Landung: die AG3-147-eigene
   Diff-Expansion im Resolver und der `_change_evidence_port.collect`-
   Aufruf im Assembler; dauerhaft zulässig: backend-lokale
   `concept/`-/`stories/`-Reads). `_resolve_concept_source` liest weiterhin
   nur backend-lokale `concept/`-/`stories/`-Pfade (expliziter
   Regressions-Pin — keine Ausweitung auf Worktrees).
2. **Keine Shell-Ausführung von LLM-Text:** In `src/agentkit/` existiert
   kein `shell=True` mit LLM-geliefertem Text mehr (heute einziger
   Treffer: `request_resolver.py:162`); `NEED_TEST_EVIDENCE` läuft
   ausschließlich über den typisierten Kommando-Vertrag — ein nicht
   gelistetes/nicht vertragskonformes Kommando wird deterministisch als
   benannter Befund abgelehnt und **nirgends** ausgeführt (Negativtest
   backend-seitig UND am Ausführungsort).
3. **Fail-closed ohne Edge:** Ist kein Edge erreichbar (bzw. bleibt die
   Agenten-Meldung aus), enden die betroffenen Requests nach bounded wait
   deterministisch mit benanntem Status; es existiert **kein** Codepfad,
   der die Auflösung ersatzweise backend-seitig ausführt (Negativtest:
   Edge nicht verfügbar → Status-Assertion + Beweis, dass kein
   Worktree-Zugriff stattfand); der Review läuft nach FK-47-Fehlertoleranz
   weiter, der Reviewer sieht die unaufgelösten Requests.
4. **Bounded wait / kein Claim-Deadlock:** Der Preflight-Turn blockiert nie
   unbegrenzt auf Auflösungs-Ergebnisse; Timeout ist ein benannter
   Result-Status (`TIMEOUT`-Familie), kein Fehlerabbruch des Turns.
   **Achtung (FK-91 §91.1a Regel 13/14):** das AG3-145-Preflight-Probe-Muster
   läuft in einer claim-freigebenden Setup-Phase und ist NICHT unbesehen auf
   den claim-haltenden QA-Subflow übertragbar — der vom Decision-Record
   gewählte Mechanismus (Wartepunkt+Resume bzw. Agenten-Turn) muss die
   Serialisierung so lösen, dass die Ergebnis-Meldung nie hinter dem
   wartenden Preflight-Request staut (Negativtest: der Result-POST wird
   angewandt, ohne dass der Preflight-Request ihn blockiert).
5. **Gefencte Ergebnisanwendung (No-Lease-no-Write):** Auflösungs-Ergebnisse
   werden nur unter dem aktiven Ownership-Lease angewandt; ein präpariertes
   Ex-Owner-/Epoch-Drift-Result (über die sanktionierte
   AG3-137/142-Schreibfläche erzeugt) wird deterministisch abgewiesen — OHNE
   State-Write — und erweitert weder `extended_paths` noch das Review-Bundle
   (Negativpfad an der Commit-Grenze, FK-91 §91.1a Regel 15/18).
6. **D3-Regel unverändert:** 1 Treffer → RESOLVED, mehrere Treffer →
   UNRESOLVED mit Kandidatenliste, 0 Treffer → UNRESOLVED; der 8er-Cap
   bleibt (Regressionstests gegen die bestehende Semantik, FK-47 §47.4).
7. **Konzept-Nachzug vollständig:** FK-47 enthält keinen normativen Satz
   mehr, der eine backend-seitige Worktree-Auflösung verankert
   (insb. §47.2-Tabellenzeile, §47.3-Tabelle, `_resolve_test_evidence`-
   Skizze); der P3-Decision-Record existiert mit Betroffenheitsmatrix;
   alle Konzept-Gates (`check_concept_frontmatter`,
   `check_concept_code_contracts`, `compile_formal_specs`,
   `check_architecture_conformance`) sind grün.
8. **Negativpfade an Phasengrenzen:** Auflösung nach Story-Exit/Reset
   (Zustand über echte Vorgängerpfade erzeugt) wirkt nie auf das
   Review-Bundle (testing-guardrails; Anbindung an die
   AG3-144-No-Lease-no-Write-/Ex-Owner-Abweis-Mechanik).
9. Coverage ≥ 85 % gehalten; `mypy` strict (inkl. `--platform linux`) und
   `ruff` ohne neue Ausnahmen; ARCH-55 (englische Bezeichner, Wire-Keys,
   Status-/Befund-Codes).

## Definition of Done

- Alle Akzeptanzkriterien erfüllt; Gate-Suite grün (`pytest -n0`
  unit/integration/contract, Coverage ≥ 85, `mypy src` + `--platform linux`,
  `ruff`, 4 Konzept-Gates).
- Codex-Review PASS.
- Auf `origin/main` gemerged; `status.yaml` → `completed`;
  README-Backlog-Snapshot (§6.7) nachgezogen.

## Abdeckung (Traceability)

**Deckt ab:** — (Review-Fund außerhalb des GAP-Nenners; Quelle: Story-Schnitt-Review 2026-07-02 — Codex-WARNING „Verify-System-Testevidence bleibt backend-seitiger shell=True-Worktree-Zugriff" + Batch-C-Befund; PO-Freigabe 2026-07-02).

## Konzept-Referenzen

- FK-10 §10.2.4a (`10_runtime_deployment_speicher.md:426-468`:
  Topologie-Regel „Backend nie physischer Worktree-Zugriff";
  Akteursmodell Agent/Edge/niemand :440-450; Ausführungsort-Grundsatz
  (a) Edge-Auftrag / (b) gepushter Stand / (c) entfällt, Fehlbetriebs-
  Klassifikation :452-461)
- FK-47 (`47_request_dsl_und_preflight_turn.md`: §47.2 Request-Typen +
  Tabelle mit `NEED_TEST_EVIDENCE`-Zeile :100; §47.3 RequestResolver-
  Kontexttabelle :115 und Code-Skizze :237-242 — Pre-K1-Stand, wird durch
  den Nachzug dieser Story bereinigt; §47.4 D3-Mehrdeutigkeitsregel;
  §47.5 Preflight-Turn-Architektur inkl. Fehlertoleranz)
- FK-91 §91.1a (Regel 13/14 synchrone Objekt-Serialisierung; Regel 15/18
  No-Lease-no-Write + Ex-Owner-Abweisung — maßgeblich für Ergebnisanwendung
  und Timing-Modell: Scope 1/4, AK4/AK5)
- FK-91 §91.1b (Command-Queue: Auftrags-/Result-Vertrag — Andockpunkt der
  neuen Auftragsart in Variante a)
- META-CONCEPT-CONSISTENCY (`concept/_meta/konzept-konsistenz-governance.md`)
  §3 P3 (Decision-Record + Betroffenheitsmatrix als Pflicht-Artefakt),
  §4 (Severity: normative Änderung ohne Record = ERROR)
- Decision-Record-Vorbild:
  `concept/_meta/decisions/2026-07-02-k1-worktree-topologie.md`

## Guardrail-Referenzen

- **FIX THE MODEL, NOT THE SYMPTOM:** Der Ausführungsort wird am Modell
  (FK-47-Nachzug + Akteursmodell) korrigiert — nicht durch einen
  Backend-Sonderpfad „nur wenn co-located" kaschiert.
- **FAIL-CLOSED:** Kein Edge erreichbar → benannter Status, nie stiller
  Backend-Fallback; nicht vertragskonforme Kommandos werden abgelehnt,
  nie ausgeführt.
- **NO ERROR BYPASSING:** Das `shell=True`-Injection-Risiko wird an der
  Ursache behoben (Kommando-Vertrag), nicht durch Escaping-Kosmetik
  umgangen.
- **QA-Artefakt-Schutz (CLAUDE.md):** Die Ergebnisanwendung läuft gefenct
  über den aktiven Ownership-Lease (No-Lease-no-Write, FK-91 §91.1a
  Regel 15/18) — Worker/Ex-Owner können Review-Evidenz nicht nachträglich
  manipulieren.
- **Konzepttreue:** Der FK-47-Konflikt wird nicht implizit wegimplementiert,
  sondern per Konzept-Nachzug + P3-Decision-Record aufgelöst (hart
  gestoppt wäre ohne Nachzug jede Abweichung vom geschriebenen FK-47).
- **Testing-Guardrails:** Negativpfade (Edge fehlt, Timeout, Ex-Owner,
  Exit/Reset) an echten Phasengrenzen; keine zusammenfantasierten
  Ersatz-Zustände.

## Querschnitts-Auflagen

- **K5 Postgres-only:** Einschlägig nur, falls die Design-Entscheidung
  (Variante a) neue Persistenzflächen über die bestehenden
  `edge_command_records` hinaus erfordert — dann Postgres-only, fail-closed
  über das `_require_postgres_control_plane_backend`-Muster
  (`control_plane/runtime/_di.py`, seit Schnitt zerlegt), kein SQLite-Spiegel. Erwartung:
  keine neue Tabelle (Wiederverwendung der AG3-145-Command-Records);
  Abweichung ist im Decision-Record zu begründen.
- **Blutgruppen-Klassifikation**
  (`concept/methodology/software-blutgruppen.md`): Kommando-Vertrag,
  Result-Status-Modell und Auflösungs-/Konsolidierungsregeln (D3) =
  **A** (technologiefreier Kern, bleibt AT-frei); Wire-/Result-Mapper
  und Preflight-Turn-Anbindung = **R**; Edge-/Agent-seitige Ausführung
  (Dateisystem-/Subprocess-Mechanik im `harness_client` bzw. Agenten-Turn)
  = **T** mit dünner **R**-Meldeschicht.
- **Bundle-Assets:** **Betroffen (Variante a)** —
  `bundles/target_project/tools/agentkit/projectedge.py` führt die neue
  Auflösungs-Auftragsart aus (deklariert; verifiziert: das Tool ist der
  einzige API-konsumierende Edge-Einstiegspunkt im Bundle). Bei
  Variante b (Agenten-Turn) ist stattdessen die Prompt-/Skill-Fläche des
  Worker-Turns betroffen — Festlegung im Decision-Record.
