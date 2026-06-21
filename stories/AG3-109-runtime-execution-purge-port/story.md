# AG3-109: Runtime-Execution-Purge-Port (koordiniert, je Owner dediziert)

**Typ:** Implementation
**Groesse:** M
**Bounded Context:** Per-Entitaet-Purge der **Runtime-Execution-Persistenz-Subdomaene** an den jeweiligen Owner-Modulen + **ein koordinierender `RuntimeExecutionPurgePort`** an der State-Backend-/Persistenz-Grenze (`agentkit.backend.state_backend.store`, wo die `save_*`-Facade und die bestehenden `purge_run`-Adapter leben). Konsument: `story-lifecycle` (`StoryResetService`, AG3-071) — hier **nicht** gebaut.

> **Ownership-Praezisierung (Review job-75d1ebfe, MED-5):** Registry-Ownership (`bounded-contexts.yaml`), FK-18-Tabellenfamilien-Ownership und die **reale Modul-Platzierung** im Code sind **drei verschiedene Achsen** und werden hier nicht als deckungsgleich „bewiesen" dargestellt. Maßgeblich fuer die Implementierung ist die **physische Mapping-Tabelle** in §1.3.

**Quell-Konzepte (autoritativ):**
- `FK-53 §53.6.2` — Entitaeten, die ein Reset **vollstaendig entfernt** (`FlowExecution`, `NodeExecution`, `AttemptRecord`, `OverrideRecord`, `GuardDecision`, `PhaseState`, umsetzungsgebundene `ArtifactRecord`, `ExecutionEvent` **u. a. mehr** — vgl. §53.6.2 nennt zusaetzlich Read-Models, Analytics, Locks/Leases/Queues, Ephemera/Worktree; diese Story deckt **nur** die Runtime-Execution-Persistenz-Teilmenge ab, siehe §2.2).
- `FK-53 §53.7.5` — Reset-Schritt 5 „Operativen Runtime-State purgen"; Regel: kein verbleibendes Objekt darf einen spaeteren Neustart/Resume/Guard-Entscheid beeinflussen.
- `FK-53 §53.9.1` — Idempotenz: loeschen-wenn-vorhanden / ignorieren-wenn-weg / hart fehlschlagen nur bei echten Infra-/Berechtigungsproblemen.
- `FK-53 §53.8/§53.10` — Service-Ziel-Zustand + `verify_reset_clean_state(reset_id)`; **diese Story liefert nur den Runtime-Residue-Baustein**, nicht die volle Clean-State-Pruefung (siehe §2.1.4 + MED-7).
- `FK-18` — relationale Tabellenfamilien/Reset-Scope (`18_relationales_abbildungsmodell_postgres.md`). **Hinweis Drift (HIGH-2):** FK-18/FK-53-Prosa benennt teils Tabellen, die im Code **anders heissen** — siehe §1.2.
- Herkunft: D3-Entscheidung (PO 2026-06-09, `_OPEN_DECISIONS.md`); No-Owner-Gap aus AG3-071-Remediation (`_CROSS_STORY_PREREQS.md`). Review-Korrekturen: `job-75d1ebfe` (CHANGES-REQUESTED, 2026-06-09).

> **PO-Designentscheidung (D3):** Der Runtime-Execution-Purge wird **je Owner dediziert** ausgefuehrt; der Reset-Service ruft sie **koordiniert** ueber einen schmalen Port auf. **Kein** zentraler „God-Purge", der direkt in fremde BC-Stores greift. Realisiert wird das ueber **Owner-Repository-/Facade-Purge-Methoden** (SQL bleibt im Driver-Helper); der Port ruft diese APIs auf (HIGH-4).

---

## 1. Kontext / Ist-Zustand (belegt)

### 1.1 Was FK-53 spezifiziert / was offen ist
- **FK-53 spezifiziert den Purge fachlich** (§53.6.2 Entitaetenliste, §53.7.5 Purge-Schritt + Regel, §53.9.1 Idempotenz, §53.8/§53.10 Ziel-Zustand). **Nicht** spezifiziert ist die **Realisierungsform** (zentral vs. per-Owner) — das ist der D3-Nachzug.
- **Bestehende `purge_run`-Pfade decken NUR Read-Models/Analytics** (HIGH-3), **nicht** die Runtime-Execution-Kernentitaeten:
  - Konkrete Deletes: `state_backend/store/projection_repositories.py:581` (`qa_stage_results`), `:825` (`qa_findings`), `:889` (`story_metrics`), `:1005` (`risk_window`), `:1049` (`phase_state_projection`-**Read-Model**, FK-39 §39.7). Die Eintraege bei `:75/:113/:149/:176/:196` sind **Protokoll-Signaturen**, keine Deletes (LOW-9).
  - `state_backend/store/fc_incident_repository.py:347` (`fc_incidents`).
  - **Keiner** dieser Pfade loescht `flow_executions`, `attempts`, `node_execution_ledgers`, `override_records`, `guard_decisions`, `phase_states` (kanonisch), `execution_events` oder run-bound `artifact_envelopes`.
- **`PurgeResult` ist projektionsspezifisch (HIGH-1):** `telemetry/projection_accessor.py:149` definiert `PurgeResult` als Ergebnis ueber **`ProjectionKind`** (FK-69-Read-Models); `projection_accessor.py:405 purge_run` fuellt nur QA/Story-Metrics/Phase-State-Projektion/FC-Incidents. **Dieser Typ wird NICHT fuer den Runtime-Purge wiederverwendet** — diese Story fuehrt einen eigenen, runtime-spezifischen Ergebnistyp ein (§2.1.2).
- **Keine Purge-Facade fuer Runtime-Core:** `state_backend/store/facade.py` hat nur `save_*`/`load_*` (`save_flow_execution:1053`, `save_node_execution_ledger:1085`, `save_override_record:1106`, …), **keine** `purge_*`-Methoden (HIGH-4). Diese Story ergaenzt die fehlenden Owner-Purge-APIs.
- **Kein koordinierender Port:** es gibt heute keine kanonische Operation, die — von `(project_key, story_id, run_id)` ausgehend — die Runtime-Execution-Owner-Purges gebuendelt ausloest und ein Gesamt-Ergebnis liefert. AG3-071 (`StoryResetService` §53.7.5, Welle 4) konsumiert sie fail-closed → ohne diese Story ist Reset nicht sauber lieferbar.

### 1.2 Konzept↔Code-Drift (HIGH-2, MUSS in der Story stehen, NICHT still „geraten")
FK-18/FK-53-Prosa nennt teils andere Tabellennamen als der reale Code. Die Implementierung folgt der **physischen Mapping-Tabelle §1.3** (Code ist Ground Truth), und der Drift wird als **doc-only-Folgeaufgabe** zur FK-18/FK-53-Terminologie-Angleichung benannt (Owner: FK-18-Doc; **kein** stilles Umbenennen, **keine** Phantomtabellen anlegen):

| FK-18/FK-53-Prosa | Reale Tabelle (Code) | Beleg |
|---|---|---|
| `attempt_records` | **`attempts`** | `sqlite_store.py:240`, `postgres_schema.sql:99` |
| `node_executions` | **`node_execution_ledgers`** | `sqlite_store.py:290`, `postgres_schema.sql:148` |
| `artifact_records` (entfernt) | **`artifact_envelopes`** (run-bound Zeilen) | `sqlite_store.py:433`, `postgres_schema.sql:295`, `store/artifact_repository.py:304/:340` |
| `phase_state_projection` als „Runtime-PhaseState" | **kanonisch `phase_states`** (Runtime) **vs.** `phase_state_projection` (FK-39-§39.7-Read-Model) | `phase_states`: `sqlite_store.py:209`, `postgres_schema.sql:78`; Projektion-Purge: `projection_repositories.py:1049` |

> **Wichtige Abgrenzung:** Diese Story purged die **kanonische `phase_states`** (Runtime-Core, kein vorhandener Purge). Die `phase_state_projection` (Read-Model) hat bereits `purge_run` (`:1049`) und ist hier **out of scope** (gehoert zur Read-Model-/Analytics-Purge-Domaene, §2.2).

### 1.3 Physisches Mapping (autoritativ fuer die Implementierung)

| §53.6.2-Entitaet | Reale Tabelle | Modul-Platzierung (Code) | Registry-Ownership | Save-API (Beleg) | Purge heute? |
|---|---|---|---|---|---|
| FlowExecution | `flow_executions` | `state_backend/store` (+`phase_state_store`) | pipeline-framework | `facade.save_flow_execution:1053` | **nein → neu** |
| NodeExecution(Ledger) | `node_execution_ledgers` | `state_backend/store` | pipeline-framework | `facade.save_node_execution_ledger:1085` | **nein → neu** |
| AttemptRecord | `attempts` | `state_backend/store` | pipeline-framework | `facade.save_attempt:540` (Insert `sqlite_store.py:2226/2241`) | **nein → neu** |
| OverrideRecord | `override_records` | **`phase_state_store/models.py:59`** | FK-18-Tabellenfamilie: guard_system | `facade.save_override_record:1106` | **nein → neu** |
| GuardDecision | `guard_decisions` | `state_backend/store` (governance-and-guards) | governance-and-guards | `GuardDecisionRepository.append` (`store/guard_decision_repository.py:98`, SQL `:128-147`) | **nein → neu** |
| kanonischer PhaseState | `phase_states` | Modell **`pipeline_engine/phase_executor/models.py:279`** (Persistenz via `state_backend/store/facade.py`) | Registry: telemetry `PhaseStateProjection` (Read-Model); kanonisches Modell liegt in `pipeline_engine` | `facade.save_phase_state:470` | **nein → neu** |
| ExecutionEvent | `execution_events` | `state_backend`/telemetry | telemetry-and-events | `facade.append_execution_event:570` (Insert `sqlite_store.append_execution_event_row:2368/:2374`) | **nein → neu** |
| umsetzungsgebundene ArtifactRecord | **run-bound** `artifact_envelopes` | `state_backend/store/artifact_repository.py` | artifacts (`ArtifactReference/Envelope/ProducerId/ArtifactClass`) | `artifact_repository.py:304/:340` | **nein → neu (nur run-bound Zeilen, §2.1.5)** |
| PhaseState-Projektion (Read-Model) | `phase_state_projection` | `state_backend/store/projection_repositories.py` | telemetry | — | **ja (`:1049`) → wiederverwenden, OUT-OF-SCOPE** |

## 2. Scope

### 2.1 In Scope
1. **Per-Owner-Purge der Runtime-Execution-Kernentitaeten** (am jeweiligen Owner-Repository/Facade, **beide** Stores, idempotent gem. §53.9.1): `flow_executions`, `node_execution_ledgers`, `attempts`, `override_records`, `guard_decisions`, kanonische `phase_states`, `execution_events`, run-bound `artifact_envelopes`. **Neue Owner-Purge-APIs** dort ergaenzen, wo heute nur `save_*`/`load_*` existiert (HIGH-3/HIGH-4); SQL bleibt im Driver-Helper (`sqlite_store.py`/`postgres_store.py`). **Kein** Duplikat zu bestehenden Read-Model-`purge_run`.
2. **Koordinierender `RuntimeExecutionPurgePort`** an der Persistenz-/State-Backend-Grenze: nimmt `(project_key, story_id, run_id)`, ruft die Per-Owner-Purge-**APIs** der Runtime-Execution-Domaene **gebuendelt** auf und liefert einen **eigenen, runtime-spezifischen Ergebnistyp** (z. B. `RuntimeExecutionPurgeResult` — Map `runtime_purge_domain → geloeschte Zeilen`). **NICHT** den projektionsspezifischen `PurgeResult` (`projection_accessor.py:149`) wiederverwenden (HIGH-1). **Kein** direkter Cross-BC-SQL-Zugriff des Ports (HIGH-4) — er orchestriert Owner-Operationen.
3. **Idempotenz (§53.9.1):** jeder Per-Owner-Purge ist konvergent (loeschen-wenn-vorhanden, ignorieren-wenn-weg); harter Fehler nur bei echten Infra-/Berechtigungsproblemen. Mehrfacher Aufruf mit derselben `(project_key, run_id)` ist sicher (Resume-faehig).
4. **Runtime-Residue-Verify (Baustein fuer §53.10, NICHT die volle Clean-State-Pruefung — MED-7):** eine Pruefoperation, die fail-closed bestaetigt, dass fuer den `run_id` **kein Runtime-Execution-Residuum** der o. g. Entitaeten verbleibt. Dies ist ein **Baustein**, den AG3-071 in `verify_reset_clean_state` einbindet; die volle §53.8/§53.10-Clean-State-Pruefung (Read-Models, Analytics, Locks/Leases, Workspace, Audit-Beleg) ist **nicht** Teil dieser Story.
5. **Run-bound-Abgrenzung der Artefakte (MED-8 / LOW-NEW-2):** nur `artifact_envelopes`-Zeilen, die an `(story_id, run_id)` gebunden sind, werden gepurged. **Wichtig:** `artifact_envelopes` hat **keine** `project_key`-Spalte — der reale Primaerschluessel ist `(story_id, run_id, stage, attempt, artifact_class, producer_name)` (`artifact_repository.py:83-92/:304-323/:340-359`). Der Purge erfolgt also ueber `(story_id, run_id)` im Artifact-Repository; ein etwaiger `project_key`-Scope wird **ausserhalb** des Tabellenschluessels validiert, nicht als Spalte impliziert. Dauerhafte/referenzielle Artefaktklassen, die ueber einen Reset hinaus bestehen muessen, werden **nicht** geloescht. Bei Unklarheit ueber durable vs. run-bound: **melden, nicht raten**.
6. **Tests:** Roundtrip je Entitaet (anlegen → purge → weg) in **beiden** Stores; Idempotenz (zweiter Purge = 0 zusaetzliche Loeschungen, kein Fehler); Port-Fan-out (ein Aufruf entfernt alle Runtime-Execution-Domaenen, Ergebnis-Zaehler stimmen); Negativpfad (fehlender `project_key` → fail-closed); Runtime-Residue-Verify positiv (sauber) + negativ (kuenstliches Residuum erkannt); **Abgrenzung** (Read-Model-Purge `phase_state_projection`/`story_metrics` wird **nicht** von dieser Story dupliziert; kanonische `phase_states` werden gepurged, `phase_state_projection` bleibt der bestehenden Operation ueberlassen).

### 2.2 Out of Scope (mit Owner — MED-6: diese Story = Runtime-Execution-Teilmenge von §53.6.2)
- **`StoryResetService`-Flow selbst** (Fence/Quiesce/Audit/Resume, §53.7.1-4/§53.9) — **AG3-071** (story-lifecycle). Diese Story liefert nur den Purge-Port + Runtime-Residue-Verify-Baustein, den AG3-071 in §53.7.5 / `verify_reset_clean_state` aufruft.
- **Read-Models-/Analytics-Purge** (FK-69-Read-Models inkl. `phase_state_projection`, `story_metrics`, `qa_*`, `risk_window`; FK-60ff-Analytics; `fact_story`, §53.7.6) — bestehende `purge_run`-Pfade / AG3-081/082-Umfeld.
- **Locks/Leases/Queues/Retry-State** (§53.7.3) — Operator-/Reset-Service-Mechanik (AG3-071/AG3-076).
- **Worktree-/Branch-Behandlung + ephemere Arbeitsoberflaechen** (§53.7.7/§53.7.8) — story_context_manager / WorktreeManager (D11/AG3-104-Umfeld).
- **FK-18/FK-53-Terminologie-Angleichung** (Drift §1.2, doc-only) — separater Konzept-Approval-Schritt; hier nur **benannt + geflaggt**, nicht geaendert.
- **FK-18-Tabellen-Normalisierung** — bestehend; hier konsumiert, nicht neu definiert.

## 3. Akzeptanzkriterien
1. Fuer jede Runtime-Execution-Kernentitaet aus der Mapping-Tabelle §1.3 (`flow_executions`, `node_execution_ledgers`, `attempts`, `override_records`, `guard_decisions`, kanonische `phase_states`, `execution_events`, run-bound `artifact_envelopes`) existiert eine **neue** Owner-Purge-API in **beiden** Stores; Roundtrip-Test (anlegen→purge→weg) je Store. Bestehende Read-Model-`purge_run` werden **nicht** dupliziert.
2. `RuntimeExecutionPurgePort` purgt von `(project_key, story_id, run_id)` ausgehend alle Runtime-Execution-Domaenen gebuendelt und liefert einen **runtime-spezifischen** Ergebnistyp (Map Domaene→Zeilen). Der projektionsspezifische `PurgeResult` (`projection_accessor.py:149`) wird **nicht** wiederverwendet (Test: Fan-out + Ergebnis-Zaehler + Typ-Assertion).
3. Idempotenz (§53.9.1): zweiter Purge-Aufruf liefert 0 zusaetzliche Loeschungen ohne Fehler; harter Fehler nur bei Infra/Berechtigung (Test).
4. **Regel §53.7.5 bewiesen:** nach Purge gibt es fuer den `run_id` kein Objekt der o. g. Entitaeten mehr, das einen Neustart/Resume/Guard-Entscheid beeinflussen koennte (Runtime-Residue-Verify positiv; Negativtest mit kuenstlichem Residuum schlaegt fail-closed an). Die Verify-Operation ist als **Runtime-Residue-Baustein** benannt, nicht als volle Clean-State-Pruefung (MED-7).
5. **Kein God-Purge (HIGH-4):** der Port ruft **Owner-Facade/Repository-Purge-APIs** auf; **kein** direkter SQL-/Treiber-Zugriff des Ports in fremde Tabellen ausserhalb der Owner-API. SQL liegt im jeweiligen Driver-Helper (`sqlite_store.py`/`postgres_store.py`). (Review/Architektur-Assertion; GAC-1 ohne neue Boundary-Verletzung; Importrichtung gem. `architecture-conformance/entities.md`: `state_backend.store` Adapter, Raw-Driver importiert keine Component-Groups.)
6. **Run-bound-Artefakt-Praezision (MED-8 / LOW-NEW-2):** nur run-gebundene `artifact_envelopes`-Zeilen (Schluessel ueber `(story_id, run_id)`; **keine** `project_key`-Spalte) werden gepurged; etwaige durable/referenzielle Artefakte bleiben erhalten; die Run-Bindung ist am realen Tabellenschluessel festgemacht und im Code dokumentiert.
7. **Drift dokumentiert (HIGH-2):** die physische Mapping-Tabelle §1.3 ist im Code (Docstring/Modulkommentar) gespiegelt; der FK-18/FK-53-Namensdrift ist als doc-only-Folgeaufgabe benannt; **keine** Phantomtabelle (`attempt_records`/`node_executions`/`artifact_records`) wird referenziert oder angelegt.
8. ARCH-55; Schema-/Purge-Pfade in **beiden** Stores; Contract/Golden-Tests nachgezogen; `SCHEMA_VERSION` nur falls Schemaaenderung noetig (Purge-APIs allein erfordern i. d. R. keine).
9. **Pflichtbefehle gruen:** scoped pytest (`tests/unit/state_backend`, `tests/unit/pipeline_engine`, `tests/unit/governance`, `tests/contract`, `-n0`) + `pytest --collect-only -q tests` (0 Importfehler) + broad `pytest tests/unit tests/contract -q -n0` (0 failed); `mypy src` (+`--platform linux`); `ruff`; GAC-1 (Exit 0); Konzept-Gates; Coverage >= 85 %.

## 4. Definition of Done
- AK 1–9 erfuellt; Codex-Review PASS; Commit auf `main` erst nach explizitem PO-Go.

## 5. Guardrail-Referenzen
- **FIX THE MODEL / BC-OWNERSHIP:** jede Entitaet wird ueber ihre Owner-API gepurgt; der Port koordiniert nur — keine zweite Loesch-Wahrheit, kein Cross-BC-Direktzugriff. Konzept↔Code-Drift wird benannt und an FK-18-Doc geroutet, nicht still umgangen.
- **FAIL-CLOSED (§53.9.1):** harter Fehler nur bei echten Infra-/Berechtigungsproblemen; sonst konvergent; Runtime-Residue-Verify schlaegt bei Residuum an.
- **SINGLE SOURCE OF TRUTH:** bestehende Read-Model-`purge_run` wiederverwenden/abgrenzen, nichts duplizieren; eigener Runtime-Ergebnistyp statt Missbrauch des projektionsspezifischen `PurgeResult`.
- **ZERO DEBT:** beide Stores zusammen; alle Runtime-Execution-Entitaeten der Mapping-Tabelle abgedeckt; out-of-scope-Reset-Domaenen mit Owner benannt; keine stille Restmenge, keine Phantomtabelle.

## 6. Hinweise fuer den Sub-Agent
- Read T:/codebase/claude-agentkit3/CLAUDE.md first — all project rules apply to you.
- **Code ist Ground Truth fuer Tabellennamen** — folge §1.3, nicht der FK-18/FK-53-Prosa. Lege **keine** Tabellen `attempt_records`/`node_executions`/`artifact_records` an und referenziere sie nicht.
- **Kanonische `phase_states` purgen** (Runtime), **`phase_state_projection` NICHT** (Read-Model, hat schon `purge_run` `:1049`).
- **Neue Owner-Purge-APIs** an Facade/Repository ergaenzen (heute nur `save_*`); SQL in den Driver-Helper; der Port ruft die APIs — **kein** Port-eigener Fremd-SQL (GAC-1/Importrichtung beachten).
- **GAC-1-Platzierung (Re-Review-Hinweis):** Port- und Repository-Purge-Arbeit unter der **registrierten** Boundary `agentkit.backend.state_backend.store` halten (Adapter, darf Component-Groups importieren — `entities.md:1386-1404`). **Keine** neuen Purge-Implementierungsmodule unter dem **unregistrierten** physischen Pfad `agentkit.backend.phase_state_store` als Workaround anlegen. Das kanonische `PhaseState`-Modell liegt in `pipeline_engine/phase_executor/models.py:279`; persistiert wird ueber `state_backend/store/facade.py` (`save_phase_state:470`).
- **Eigener Runtime-Ergebnistyp** — `projection_accessor.PurgeResult` (`:149`) ist FK-69-projektionsspezifisch und tabu fuer den Runtime-Purge.
- **Run-bound vs. durable Artefakte** am realen `artifact_envelopes`-Schluessel unterscheiden; bei Unklarheit melden, nicht raten.
- Verify ist **Runtime-Residue**-Pruefung (Baustein fuer AG3-071/§53.10), **nicht** die volle Clean-State-Pruefung.
- AK2/`.mcp.json` nicht anfassen; `concept/**`/`stories/**` nicht im Code-Commit.
- „done" nur mit Beleg: Diff, gruene Pflichtbefehle, Test-Namen (Per-Entitaet-Roundtrip beide Stores, Port-Fan-out + Typ, Idempotenz, Runtime-Residue-Verify positiv/negativ, Abgrenzung gegen Read-Model-Purge).

---

## Globale Akzeptanzkriterien (verbindlich)
- **GAC-1:** `scripts/ci/check_architecture_conformance.py` mit **0 Errors** (Exit 0) — `PYTHONPATH=src .venv\Scripts\python scripts/ci/check_architecture_conformance.py`.
- **GAC-2:** Architektur-Guardrails `guardrails/architecture-guardrails.md` eingehalten; Konflikt = hart stoppen und melden.
