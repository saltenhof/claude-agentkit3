# AG3-114: §91.1a Agent-Surface fuer Story-Create — `ProjectEdgeClient.create_story` + Target-Project-Tool-Entry gegen `POST /v1/stories`

**Typ:** Implementation
**Groesse:** L
**Bounded Context:** `projectedge` (der schlanke projektlokale AK3-Client = die normative Agent-Boundary, FK-91 §91.1a Regel #3) + die deployte Target-Project-Tool-Variante (`resources/target_project/tools/agentkit/projectedge.py`). Konsumiert die bestehende Control-Plane-Create-Boundary (`POST /v1/stories`, FK-91 §91.1a) und das `ReconciliationEvidence`-Modell (FK-21). **Kein** Re-Design der Create-Boundary oder des Story-Service.

**Quell-Konzepte (autoritativ):**
- `FK-91 §91.1a` — **Service-API ist der normative Standard-Zugriffspfad fuer alle Agents.** Regel #3: „Agents muessen ausschliesslich den offiziellen `Project Edge Client` gegen die Control-Plane-API verwenden. Direkte CLI-Aufrufe durch Agents sind unzulaessig; freie `curl`-Kommandos ebenfalls." Regel #9: „Stories werden ausschliesslich ueber die Control-Plane-API angelegt und mutiert. Externe Issue-Tracker … sind niemals Wahrheitsquelle." Endpoint `POST /v1/stories` = „Neue Story in der Control-Plane anlegen (kanonische Story-Wahrheit)". Regel #5: jeder mutierende Endpoint akzeptiert `op_id` als Idempotenzschluessel. Regel #7: stabile `correlation_id`. Regel #2: HTTPS fuer mutierende Endpunkte.
- `FK-21 §21.4 / §21.12 / §21.13` — Story-Anlage ist skill-getrieben mit **fail-closed VectorDB-Reconciliation** (zweistufig) + Konfliktloesung; die Create-Boundary ist **non-bypassable** und verlangt typisierte `ReconciliationEvidence` (Weaviate-Readiness + 4 `VECTORDB_SEARCH`-Counter + Verdict + repo-affinity). Ohne Evidence wird fail-closed geblockt **vor** jeder Persistenz.
- `FK-12 §12.1.1 / §12.7.1` — GitHub ist Code-Backend, nicht Story-Tracker; `gh issue create` ist **keine** Pipeline-GitHub-Op.

---

## 1. Ist-Zustand (belegt)

**Die Create-Boundary + das Evidence-Modell + der Client existieren — es fehlt genau die Client-Operation + der Tool-Entry, damit ein Agent nativ anlegt.**

- **`POST /v1/stories` ist gebaut + erzwingt Evidence non-bypassable:** `story_context_manager/http/routes.py:~290-320` ruft `_enforce_reconciliation(body, …)` (fail-closed ohne `ReconciliationEvidence`) und dann `self._svc.create_story(request, op_id=op_id, correlation_id=correlation_id)`. Der Kommentar (`:~283-289`, AG3-068 FIX-1) haelt fest: „the agent-facing create path is NON-BYPASSABLE … a story can never be created here while silently skipping the Weaviate check / affinity feed."
- **`ReconciliationEvidence` ist gebaut + self-validating:** `story_creation/reconciliation_evidence.py` — produziert vom deterministischen `StoryCreationReconciler` (`story_creation/create_flow.py:80,157,207`), Konstruktion fail-closed bei inkonsistenter Attestierung (Weaviate-Outage kann nicht mit Such-Countern koexistieren etc.).
- **`ProjectEdgeClient` ist gebaut + als Target-Tool deployt — aber ohne create:** `projectedge/client.py:197` `class ProjectEdgeClient` hat `start_phase`/`complete_phase`/`fail_phase`/`complete_closure`/`sync`/`reconcile_operation` — **kein `create_story`**. Die deployte Variante `resources/target_project/tools/agentkit/projectedge.py:20` (`main`) kennt Subcommands `phase-start`/`phase-complete`/`phase-fail`/`closure-complete`/`sync` — **kein `create-story`**.
- **Heute legt der Skill via GitHub an (zu ersetzen, gehoert AG3-113):** `create-userstory-core/4.0.0/SKILL.md` ruft `gh issue create` (4×, je Story-Typ) + Board-Schritte. Das ist FK-91 §91.1a Regel #9 / FK-12 §12.1.1-widrig. **Diese Story baut die native Capability; das Umschreiben des Skill-Bundles ist AG3-113** (das auf AG3-114 wartet).
- **Reachability-Klarstellung:** Der `story_creation_guard`-Docstring nennt `POST /v1/stories` „NOT yet reachable through a production harness adapter" — das bezieht sich auf die **Guard-Detektion** des HTTP-Tool-Calls (Adapter mappen Nicht-Bash-Tools auf `unknown_tool`), **nicht** darauf, dass ein Skill den Request nicht absetzen kann: der Skill ruft den **Bash-erreichbaren** `projectedge`-Tool-Befehl, der den HTTP-POST macht. Diese Story macht genau diesen Bash-erreichbaren Create-Pfad real.

## 2. Scope

### 2.1 In Scope

1. **`ProjectEdgeClient.create_story(...)` (BC `projectedge`):** eine neue Client-Operation, die einen typisierten Create-Request + die `ReconciliationEvidence` + `op_id` an `POST /v1/stories` sendet (ueber den bestehenden `ControlPlaneTransport`/`HttpsJsonTransport`) und das Ergebnis (angelegte Story inkl. **backend-allozierter** Story-ID + `correlation_id`) typisiert zurueckgibt. Respektiert die §91.1a-Normregeln: `op_id`-Idempotenz (Regel #5, Wiederholung = keine zweite Mutation), `correlation_id`-Propagation (Regel #7), HTTPS (Regel #2), stabiler Fehler-Vertrag (`error_code`/`error`/`correlation_id`, Regel #8). Falls der Endpoint ein lokales Materialisierungs-Bundle liefert (Regel #4), wird es wie bei den Phase-/Closure-Operationen behandelt (kein Sonderpfad erfinden).
2. **Reconciliation-Evidence-Produktion erreichbar machen:** der Agent muss die fail-closed VectorDB-Reconciliation (FK-21 §21.4) **ausfuehren** und daraus die `ReconciliationEvidence` erzeugen koennen, bevor er create aufruft — ueber den deterministischen `StoryCreationReconciler`/dessen Reconciliation-Runtime, **nicht** durch eine handgebaute Evidence im Skill. Konkrete Verdrahtung (eigener Reconcile-Schritt im Tool, der die Evidence zurueckgibt, ODER ein `create-story`-Toolbefehl, der die Reconciliation intern fahrt und dann postet) ist Umsetzungsentscheidung; **Pflicht:** die Evidence stammt aus der echten Reconciliation-Runtime, ist self-validating, und ohne sie (z. B. Weaviate-Outage) bricht der Pfad fail-closed ab (kein Dummy, kein Skip). Existiert keine erreichbare Reconcile-Surface, ist sie als Teil dieser Story zu schaffen (nicht im Skill fingieren).
3. **Target-Project-Tool-Entry (`resources/target_project/tools/agentkit/projectedge.py`):** ein neuer Subcommand `create-story` (analog zu `phase-start` etc.), den der Skill via Bash aufruft; nimmt die Story-Eingangsfelder + den `op_id` + die Reconciliation-Eingaben, fahrt die Reconciliation (item 2), ruft `client.create_story(...)` und gibt das Ergebnis (Story-ID, Status, `correlation_id`) als JSON aus. Fehler fail-closed mit stabilem Exit-Code + `error_code`.
4. **SINGLE-SOURCE-/Owner-Disziplin:** **keine** Aenderung an `create_story`-Service-Logik, am `ReconciliationEvidence`-Modell oder an der Route-Enforcement (fremde Owner: Story-Service / FK-21 / AG3-068). AG3-114 ruft sie nur ueber den Client/das Tool. **Keine** zweite Story-Anlage-Wahrheit, **kein** direkter In-Process-Aufruf am Tool vorbei, **kein** `gh issue create`.
5. **Tests (real, kein Stub der Boundary/Reconciliation):**
   - Unit: `ProjectEdgeClient.create_story` setzt den korrekten Request ab (Methode/Pfad/Body/`op_id`/`correlation_id`), `op_id`-Idempotenz (zweiter Call mit gleicher `op_id` -> keine zweite Mutation), Fehler-Vertrag-Mapping, fail-closed bei fehlender/inkonsistenter Evidence.
   - **E2E NO-STUB (Kernkriterium):** gegen die **echte** Create-Boundary (`POST /v1/stories` + echtes `create_story` + echte Evidence-Enforcement): ein realer Tool-`create-story`-Aufruf fahrt die reale Reconciliation, erzeugt eine self-validating Evidence, legt die Story in der Control-Plane an (backend-allozierte ID, kanonische Wahrheit), **ohne** jeden GitHub-Aufruf; Negativ: Weaviate-Outage / fehlende Evidence -> fail-closed, keine Story angelegt; Idempotenz: Wiederholung mit gleicher `op_id` -> dieselbe Story, keine Dublette.
   - Assertion: kein `gh issue create`/`gh project`/`gh api graphql` im Create-Pfad dieser Story.

### 2.2 Out of Scope (mit Owner)

- **Re-Cut von `create-userstory-core` SKILL.md** (Board raus, Tokens, lowercase, Skill ruft `create-story` statt `gh issue create`) — **AG3-113** (depends_on AG3-114). AG3-114 liefert die Capability; AG3-113 verdrahtet das Bundle darauf.
- **`create_story`-Service-Logik / Story-ID-Allokation / `ReconciliationEvidence`-Modell / Route-Enforcement** — Story-Service / FK-21 / **AG3-068**. Unveraendert konsumiert.
- **Reset-Agent-Surface (`ProjectEdgeClient.reset_story` + §91.1a-Reset-Endpoint + AG3-071-Review-Remediation)** — **dedizierte Folge-Reset-Story** (FK-91 §91.1a Regel #10 „offene Konzept-Schuld"). **Nicht** Teil von AG3-114; AG3-114 ist create-only.
- **`gh issue`-Lese-/Lookup-Nutzung** (`gh issue list/view`) — gehoert in den AG3-113-Re-Cut (create+lookup-Bundles), nicht hierher.
- **AK2 / `.mcp.json`** — nicht anfassen.

### 2.3 Abhaengigkeits-/Reachability-Befund

- `depends_on: [AG3-014 (Story-Service), AG3-068 (Evidence-Enforcement auf der Route), AG3-090 (Control-Plane-HTTP)]` — alle `completed`. `unblocks: [AG3-113]`.
- Die §91.1a-Create-Boundary ist gebaut (AG3-068/090); AG3-114 schliesst nur die Client-/Tool-/Reconciliation-Luecke. Sollte sich beim Bauen zeigen, dass eine erreichbare Reconcile-Surface fehlt (item 2), ist sie hier zu schaffen — **fail-closed melden**, falls ein dafuer noetiger fremder Owner-Vertrag fehlt, statt eine zweite Wahrheit zu bauen.

## 3. Akzeptanzkriterien

1. **`ProjectEdgeClient.create_story` existiert + ist §91.1a-konform:** sendet `POST /v1/stories` mit Request + `ReconciliationEvidence` + `op_id`; gibt die angelegte Story (backend-allozierte ID, `correlation_id`) typisiert zurueck; respektiert `op_id`-Idempotenz (Regel #5), `correlation_id` (Regel #7), Fehler-Vertrag (Regel #8). Tests je Aspekt.
2. **Reconciliation-Evidence aus der echten Runtime:** die an create uebergebene Evidence stammt aus der deterministischen Reconciliation (FK-21 §21.4), ist self-validating; Weaviate-Outage/fehlende Evidence -> fail-closed Abbruch **vor** Persistenz (kein Dummy/Skip). Test (positiv + Outage-negativ).
3. **Target-Tool `create-story`-Subcommand:** via Bash aufrufbar, fahrt Reconciliation + ruft `client.create_story`, gibt JSON (Story-ID/Status/`correlation_id`) aus; Fehler fail-closed mit stabilem Exit-Code + `error_code`. Test.
4. **E2E NO-STUB (Kernkriterium):** realer Tool-`create-story`-Lauf gegen die **echte** Create-Boundary legt eine Story in der Control-Plane an (kanonische Wahrheit, backend-allozierte ID) **ohne** jeden GitHub-Aufruf; Idempotenz (gleiche `op_id` -> dieselbe Story); Negativ (fehlende/inkonsistente Evidence -> kein Story). Kein Mock der Boundary/Reconciliation/Evidence.
5. **Owner-Disziplin:** keine Aenderung an `create_story`-Service/`ReconciliationEvidence`/Route-Enforcement; kein `gh issue create`/Board im Create-Pfad; keine zweite Anlage-Wahrheit. Review/Assertion.
6. **ARCH-55 + Typisierung:** englische Bezeichner, volle Type-Hints, Pydantic v2 fuer Request/Response, mypy strict, ruff.
7. **Pflichtbefehle gruen:** scoped pytest (`tests/unit/projectedge`, `tests/unit/story_context_manager`, ggf. `tests/integration/...`, `tests/contract`, `-n0`) + `pytest --collect-only -q tests` (0 Importfehler) + broad `pytest tests/unit tests/contract -q -n0` (0 failed); `mypy src` (+`--platform linux`); `ruff check src tests`; GAC-1; Concept-Gates; Coverage >= 85 %.

## 4. Definition of Done

- AK 1–7 erfuellt (inkl. E2E-NO-STUB AC4); giftiges Doppel-Review (Codex + Fable) PASS.
- AG3-113 wird entblockt: die native `create-story`-Capability existiert + ist e2e bewiesen, sodass der AG3-113-Re-Cut den Skill darauf verdrahten kann (statt `gh issue create`).
- Commit/Push erst nach grünem Doppel-Review (Orchestrator-Policy). `.mcp.json` nicht mitcommitten.

## 5. Guardrail-Referenzen

- **FIX THE MODEL / SINGLE SOURCE OF TRUTH:** die Create-Boundary + Evidence + Story-Service sind die eine Wahrheit; AG3-114 ist nur die Agent-Adapter-Operation (Client + Tool) darauf — kein Parallel-Pfad, kein In-Process-Bypass, kein zweiter Allokator.
- **FAIL-CLOSED / NO ERROR BYPASSING:** ohne valide Reconciliation-Evidence keine Anlage; Weaviate-Outage blockt; kein Dummy-Evidence, kein `--force`-artiger Bypass, kein GitHub-Fallback.
- **§91.1a-Normregeln:** Agents ueber den Client (Regel #3), `op_id`-Idempotenz (#5), `correlation_id` (#7), HTTPS (#2), stabiler Fehler-Vertrag (#8), GitHub nie Story-Wahrheit (#9).
- **ARCH-55:** englische Bezeichner/Wire-Keys.
- **ZERO DEBT:** der native Create-Pfad ist nach dieser Story real und e2e bewiesen; kein toter Client-Stub.

## 6. Hinweise fuer den Sub-Agent

- Read T:/codebase/claude-agentkit3/CLAUDE.md first — all project rules apply to you.
- **Bestehende Surfaces konsumieren, nicht neu bauen:** `POST /v1/stories` (`story_context_manager/http/routes.py`), `ReconciliationEvidence` (`story_creation/reconciliation_evidence.py`), `StoryCreationReconciler` (`story_creation/create_flow.py`), `ProjectEdgeClient`/`ControlPlaneTransport` (`projectedge/client.py`), Target-Tool (`resources/target_project/tools/agentkit/projectedge.py`). Spiegele das Muster der bestehenden `phase-start`/`sync`-Operationen exakt (Transport, op_id, Fehler-Mapping).
- **Reconciliation-Evidence kommt aus der echten Runtime** — nicht im Tool/Skill von Hand zusammenbauen. Wenn ein erreichbarer Reconcile-Schritt fehlt, baue ihn als Teil dieser Story (Owner-treu), statt die Evidence zu fingieren.
- **`create_story`-Service / Evidence-Modell / Route NICHT veraendern** (fremde Owner). Nur Client-Operation + Tool-Subcommand + Reconcile-Verdrahtung + Tests.
- **Kein `gh issue create`/`gh project`/`gh api graphql`** in dieser Story; das Skill-Bundle ruehrt AG3-113 an, nicht du.
- AK2 / `.mcp.json` nicht anfassen. Kein Commit ohne Orchestrator-Auftrag.
- „done" nur mit Beleg: Diff-Zusammenfassung, gruene Pflichtbefehle, Test-Namen (Client-create_story Request/Idempotenz/Fehler, Reconcile-Evidence positiv/Outage-negativ, Tool-Subcommand, **E2E-NO-STUB** [Tool -> Reconcile -> Evidence -> POST /v1/stories -> Story angelegt ohne GitHub, Idempotenz, Negativ]).

---

## Globale Akzeptanzkriterien (verbindlich)

Zusaetzlich gelten die **globalen Akzeptanzkriterien** aus `stories/_GLOBAL_ACCEPTANCE.md`:
- **GAC-1:** `scripts/ci/check_architecture_conformance.py` mit **0 Errors** (`PYTHONPATH=src .venv\Scripts\python scripts/ci/check_architecture_conformance.py`).
- **GAC-2:** Architektur-Guardrails `guardrails/architecture-guardrails.md` (ARCH-NN); Konflikt = hart stoppen und melden.
