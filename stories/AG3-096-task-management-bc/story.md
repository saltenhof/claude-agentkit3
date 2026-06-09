# AG3-096: task_management BC (Entitaeten/Tabellen/Top-Surface)

**Typ:** Implementation
**Groesse:** L
**Bounded Context:** `task_management` (neuer BC) — verwaltet **Zustand und Verlinkung** von Tasks/To-Dos. **Abgrenzung (PO 2026-06-07):** Task-Abarbeitung ist **freestyle durch Mensch/Agent** und wird **NICHT** von der AK3-Pipeline orchestriert. Dieser BC fuehrt **keine** Phasen, Gates oder Worktrees — er ist reine Zustands-/Verlinkungs-Verwaltung.
**Quell-Konzepte (autoritativ):**
- `FK-77 §77.1` (Datenmodell `Task`/`TaskLink`), `§77.2` (Lifecycle-Uebergaenge open→done/dismissed), `§77.3` (Verlinkungsmodell, bidirektional), `§77.5` (Speicher/relationale Abbildung `tm_tasks`/`tm_task_links`), `§77.6` (technische Abgrenzung: nie an `PipelineEngine`, kein Phase-Handler), `§77.7` (Aufruf-Surface).
- `formal.task-management.entities` — exakte Attribut-Sets `Task`/`TaskLink` (`concept/formal-spec/task-management/entities.md`).
- `formal.task-management.state-machine` — Lifecycle.
- `formal.task-management.commands` — Schreib-Surface (`concept/formal-spec/task-management/commands.md`).

---

## 1. Kontext / Ist-Zustand (belegt)

FK-77 ist ein **kompletter, noch unimplementierter** BC:

- Glob `**/task_management/**` und Grep `task_management|tm_tasks|tm_task_links|create_task|TaskLink|class Task` **eingeschraenkt auf `src/agentkit`** -> **0 Treffer** (kein produktiver Code, keine Tabellen im State-Backend, keine Top-Surface).
- `src/agentkit/state_backend/postgres_schema.sql` und `src/agentkit/state_backend/sqlite_store.py` enthalten **kein** `tm_tasks`/`tm_task_links`.

Anknuepfungspunkte (existieren, konsumieren — kein Neubau):
- Persistenz-Substrat: der bestehende Projektionspfad mit ownership-strenger Record-Bindung. Die reale Code-Surface heisst **`ProjectionAccessor.write_projection` / `ProjectionAccessor.read_projection`** (`src/agentkit/telemetry/projection_accessor.py:249` / `:329`), **nicht** eine Klasse `Telemetry` (existiert nicht; FK-77 §77.5 nennt sie prosaisch — der Code-Owner ist `ProjectionAccessor`). Ownership-Strenge (eine `ProjectionKind` = genau ein Record-Typ) ist in `src/agentkit/telemetry/errors.py` (`ProjectionRecordTypeMismatchError`, `ProjectionKindNotAccessorOwnedError`) verankert.
- Story-Identitaet (`project_key`, `story_id`) als ein Verlinkungsziel (`target_kind=story`); Task-zu-Task als zweites Verlinkungsziel (`target_kind=task`).
- State-Backend-Schema (`src/agentkit/state_backend/postgres_schema.sql` + `src/agentkit/state_backend/sqlite_store.py`) fuer `tm_tasks`/`tm_task_links`.

**Kontext-Konflikt-Check (Sinnhaftigkeit):** Es darf **keine** Pipeline-/Phasen-/Gate-Logik in diesen BC einfliessen. Tasks sind bewusst **ausserhalb** des Story-Run-Lifecycles (FK-77 §77.6: ein Task wird nie an die `PipelineEngine` uebergeben, es existiert kein Phase-Handler). Wer hier Phasen/Gates einbaut, verletzt den Schnitt.

**Vorab zu entscheidender Konzept-/Code-Konflikt (BLOCKING, vor Implementierung):** FK-77 §77.5 sagt, geschrieben wird ueber den Projektionspfad. Der reale `ProjectionKind`-Enum ist aber **FK-69-streng auf exakt 7 Tabellen** begrenzt (`src/agentkit/telemetry/projection_accessor.py:56-71`, Kommentar §69.3) und besitzt **keinen** Task-Wert. `tm_tasks`/`tm_task_links` sind **keine** FK-69-Read-Models. Diese Story darf den 7-Werte-Enum **nicht** still aufweiten. Es gibt zwei zulaessige Auswege, von denen **einer vor der Implementierung autoritativ festgeschrieben werden muss** (siehe AK 8):
  - (a) `task_management` erhaelt einen **dedizierten Persistenz-Port** analog dem fc_incidents-Sonderpfad (`ProjectionAccessor.record_fc_incident`, `projection_accessor.py:313`) — d. h. dedizierte Task-Schreib-/Lese-Methoden statt einer neuen `ProjectionKind`; FK-77 §77.5 ("Telemetry.write_projection") wird dann als Prosa praezisiert (doc-only). **Default-Empfehlung dieser Story.**
  - (b) FK-69/`ProjectionKind` wird **autoritativ** um Task-Projektionen erweitert. Das ist eine FK-69-Owner-Entscheidung und gehoert **nicht** in diese Story (Owner: **AG3-081**, FK-69 §69.3/§69.9/§69.14). Wird (b) gewaehlt, ist AG3-096 von AG3-081 abhaengig und wartet auf dessen Enum-Erweiterung.
  Es wird **nicht** geraten: ohne festgeschriebene Entscheidung wird die Implementierung nicht freigegeben.

## 2. Scope

### 2.1 In Scope
1. **Entitaeten (§77.1, `formal.task-management.entities`):** `Task` und `TaskLink` als typisierte Pydantic-v2-Modelle mit **exakt** den formal spezifizierten, englischen Feldern — keine erfundenen Felder:
   - `Task`: `task_id` (Format `TM-YYYY-NNNN`, eindeutig pro `project_key`), `project_key`, `kind` (`reminder | actionable`), `type` (Herkunftskategorie, v1: `concept_update`), `title`, `body`, `priority` (`low | normal | high`), `status` (`open | done | dismissed`), `origin` (`closure | verify | governance | human`), `source_story_id?`, `execution_report_ref?`, `created_at` (UTC), `resolved_at?`, `resolved_by?` (`human | agent`). Identitaet: `(project_key, task_id)`.
   - `TaskLink`: `project_key`, `task_id`, `target_kind` (`task | story`), `target_id`, `kind` (`relates_to | spawned_story | duplicate_of`). Identitaet: `(project_key, task_id, target_kind, target_id, kind)`. n:m, **kein** gespiegelter Status.
   - Status/kind/priority/origin/target_kind/relation-kind als StrEnum (englische Werte).
2. **State-Machine (§77.2, `formal.task-management.state-machine`):** `create -> open`, `open --resolve--> done`, `open --dismiss--> dismissed`. `done` und `dismissed` sind **terminal** (kein Reopen in v1). Jeder andere Uebergang ist fail-closed. `resolved_by`/`resolved_at` werden beim Abschluss gesetzt. **Keine** Pipeline-Phasen.
3. **Tabellen (§77.5):** `tm_tasks` und `tm_task_links` in **beiden** Stores (`postgres_schema.sql` + `sqlite_store.py`). Keys gem. §77.5: `tm_tasks` `(project_key, task_id)`; `tm_task_links` `(project_key, task_id, target_kind, target_id, kind)`. `project_key` Pflichtspalte auf beiden Tabellen. `tm_task_links.task_id` referenziert `tm_tasks` per `(project_key, task_id)`. Provenienz (`source_story_id`, `execution_report_ref`) sind Spalten auf `tm_tasks`, **getrennt** von den Links. `tm_task_links` traegt **keinen** Status. Schreib-/Lesezugriff laeuft ausschliesslich ueber den entschiedenen Persistenz-Port (§1, Ausweg (a) oder (b)) — kein zweiter Schreibweg, kein eigenes Datei-Format. `SCHEMA_VERSION` ziehen falls noetig.
4. **Top-Surface (§77.7, `formal.task-management.commands`):** transport-agnostische Task-API.
   - **Schreibend:** `create_task` (legt Task im Zustand `open` an), `link_task` (erzeugt `TaskLink`; erlaubt aus `open|done|dismissed`; aendert keinen Status), `unlink_task` (loescht eine `TaskLink`-Kante; erlaubt aus `open|done|dismissed`), `resolve_task` (`open -> done`, setzt `resolved_by`/`resolved_at`), `dismiss_task` (`open -> dismissed`, setzt `resolved_by`/`resolved_at`).
   - **Lesend (alle `project_key`-scoped, Mandantenregel):** `get_task(project_key, task_id)`, `list_tasks(project_key, filter: status | type | kind | origin)`, `list_tasks_for_target(project_key, target_kind, target_id)` (Rueckschau von der Story-/Task-Detailseite). **Tenant-Scope:** Task-Identitaet ist `(project_key, task_id)` (`formal.task-management.entities`: `identity: [project_key, task_id]`); `task_id`/`story_id` sind allein **nicht** systemweit ausreichend (Mandantenregel, `02_domaenenmodell_zustaende_artefakte.md` §2.2.1). Daher tragen **alle** Read-Methoden `project_key` explizit; FK-77 §77.7 nennt prosaisch `get_task(task_id)`/`list_tasks_for_target(target_kind, target_id)` ohne `project_key` — das ist eine Prosa-Luecke, die hier autoritativ aus der formal-spec-Identitaet praezisiert wird (kein zweiter, ungescopeter Lesepfad).
   - Idempotenz/Validierung an der Surface; n:m-Verlinkung beidseitig abfragbar (Task -> verlinkte Stories/Tasks; Ziel -> verlinkende Tasks via `list_tasks_for_target`).
5. **Abgrenzungs-Garantie (PO + §77.6):** der BC stellt **keine** Phase/Gate/Worktree bereit und haengt **nicht** am Story-Run-Lifecycle. Er importiert **keine** `pipeline_engine`-/Phase-/Gate-Orchestrierung; ein Task wird nie an die `PipelineEngine` uebergeben. Tasks werden freestyle durch Mensch/Agent erledigt; AK3 verwaltet nur Zustand/Verlinkung.
6. **Tests:** State-Machine (gueltig `open->done`/`open->dismissed`, ungueltige Uebergaenge fail-closed, Terminalitaet), n:m-Verlinkung gegen **Stories und Tasks** (ein Task n Ziele, ein Ziel n Tasks, beidseitige Abfrage via `list_tasks_for_target`), `target_kind=task`-Validierung (Ziel-Task existiert + gleicher `project_key`), `target_kind=story`-Validierung (Ziel-Story existiert), Persistenz-Roundtrip ueber den entschiedenen Port (beide Stores), Ownership-Strenge (falscher Record-Typ -> Fehler), Surface-Vollstaendigkeit (Positiv-/Negativpfad fuer jede der acht Methoden), **Tenant-Scope der Read-Surface** (gleiche `task_id` unter zwei `project_key` -> `get_task`/`list_tasks_for_target` strikt partitioniert, kein Cross-Tenant-Leak), **Abgrenzungstest** (Task-Operationen loesen keinerlei Pipeline-Phasen/Gates aus / haengen nicht am Run-State + Strukturpruefung: kein verbotener `pipeline_engine`/phase/gate-Import).

### 2.2 Out of Scope (mit Owner)
- **Task-Management-UI** (Anlegen/Verlinken/Erledigen/Verwerfen im Prototyp-Stil) — **AG3-105** (anderer Autor). Diese Story liefert nur die **BC-Surface**, an die AG3-105 andockt.
- **Producer-Verdrahtung in FK-29/FK-38** (Tasks aus Closure/Feedback automatisch erzeugen) — FK-77 §77.8 nennt das ausdruecklich als separate Folgeaufgabe; **nicht** hier.
- **Task-Lifecycle-Events** (`task_created`/`task_linked`/`task_unlinked`/`task_resolved`/`task_dismissed`, `formal.task-management.events`) — FK-77 §77.7 ("Abgrenzung API vs. Events") sagt **autoritativ**, dass die Events erst dann als publizierte EventTypeId-/Wire-Surface katalogisiert werden, **wenn ein konkreter Konsument modelliert ist** (Owner: **FK-91** / frontend-contracts, Welle 7). Diese Story baut die **Request/Response-API**, **keine** Event-Emission. (Begruendung gegen den Review-Befund: das Konzept selbst stellt Events explizit zurueck — kein offener Widerspruch.)
- **FK-69/`ProjectionKind`-Erweiterung um Task-Projektionen** (falls Ausweg (b) gewaehlt) — Owner **AG3-081** (FK-69 §69.3/§69.9/§69.14). Diese Story erweitert den 7-Werte-Enum nicht selbst.
- **Jegliche Pipeline-/Phasen-/Gate-/Worktree-Orchestrierung** — bewusst **nicht** Teil dieses BC (PO-Abgrenzung; Owner der Story-Pipeline bleiben pipeline_engine/closure-BCs).
- **BFF-`http/`-Endpunkte** fuer Tasks — Frontend/BFF-Welle (AG3-090/091); hier nur die transport-agnostische BC-Top-Surface, keine HTTP-Routen.

## 3. Akzeptanzkriterien
1. `Task` und `TaskLink` existieren als typisierte Pydantic-v2-Modelle mit **exakt** den Feldern aus `formal.task-management.entities` (englisch); `Task`-Felder: `task_id`/`project_key`/`kind`/`type`/`title`/`body`/`priority`/`status`/`origin`/`source_story_id?`/`execution_report_ref?`/`created_at`/`resolved_at?`/`resolved_by?`; `TaskLink`-Felder: `project_key`/`task_id`/`target_kind`/`target_id`/`kind`. Keine undefinierten Zusatzfelder (Test: Modell-Validierung positiv + Reject unbekannter/fehlender Pflichtfelder).
2. `TaskLink.target_kind ∈ {task, story}`; bei `target_kind=task` wird die Existenz des Ziel-Tasks **und** gleicher `project_key` validiert, bei `target_kind=story` die Existenz der Ziel-Story; Artefakte sind **kein** gueltiges Linkziel (Test: gueltiger task-Link, gueltiger story-Link, ungueltiges/nicht existentes Ziel fail-closed).
3. State-Machine: `open->done` (`resolve_task`) und `open->dismissed` (`dismiss_task`) sind gueltig und setzen `resolved_by`/`resolved_at`; jeder andere Uebergang ist fail-closed; `done`/`dismissed` sind terminal (kein Reopen) (Test: gueltig + ungueltig + Terminalitaet).
4. `tm_tasks`/`tm_task_links` existieren in `postgres_schema.sql` **und** `sqlite_store.py` mit den §77.5-Keys; Schreiben/Lesen laeuft ausschliesslich ueber den in AK8 festgeschriebenen Persistenz-Port mit ownership-strenger Record-Bindung (Test: Roundtrip beide Stores).
5. Ownership-Strenge: ein falscher Record-Typ fuer den Task-Persistenzpfad wird fail-closed abgelehnt (Test, analog `ProjectionRecordTypeMismatchError`).
6. **Volle Top-Surface** funktioniert mit Positiv-**und** Negativpfad je Methode: `create_task`, `link_task`, `unlink_task`, `resolve_task`, `dismiss_task` (schreibend) sowie `get_task(project_key, task_id)`, `list_tasks(project_key, filter status|type|kind|origin)`, `list_tasks_for_target(project_key, target_kind, target_id)` (lesend). **Alle Read-Methoden sind `project_key`-scoped** (Mandantenregel): `get_task` loest **nur** innerhalb des uebergebenen `project_key` auf, `list_tasks_for_target` liefert **nur** Tasks desselben `project_key` (Test: ein Task `task_id=T` unter zwei verschiedenen `project_key` -> `get_task` und `list_tasks_for_target` liefern strikt partitioniert, kein Cross-Tenant-Leak). `resolve_task` setzt ausschliesslich `done`, `dismiss_task` ausschliesslich `dismissed` (kein vermischter `-> done/dismissed`-Pfad). n:m beidseitig abfragbar (ein Task -> n Stories/Tasks; ein Ziel -> n Tasks) (Test pro Methode).
7. **Abgrenzung:** Task-Operationen loesen **keine** Pipeline-Phasen/Gates/Worktrees aus und haengen nicht am Story-Run-Lifecycle; der BC importiert keine `pipeline_engine`/phase-/gate-Orchestrierung (Test: Strukturpruefung verbotener Import + Verhaltenstest; §77.6).
8. **Persistenz-Port-Entscheidung festgeschrieben:** vor Implementierung ist autoritativ entschieden und in dieser Story dokumentiert, ob (a) dedizierter Task-Persistenz-Port (Default) oder (b) FK-69-`ProjectionKind`-Erweiterung via AG3-081 (dann Abhaengigkeit dokumentiert). Der 7-Werte-`ProjectionKind`-Enum wird **nicht** still aufgeweitet.
9. **Pflichtbefehle gruen:** pytest unit/integration/contract (in Chunks, `-n0`); mypy default + `--platform linux`; ruff; vier Konzept-Gates; Coverage >= 85 %.

## 4. Definition of Done
- AK 1–9 erfuellt; giftige Codex-Review PASS; (Implementierung/Commit erst nach Execution-Plan-Freigabe und nach Festschreibung der Persistenz-Port-Entscheidung AK8 — diese Story wird zunaechst nur autorisiert/reviewt).

## 5. Guardrail-Referenzen
- **FIX-THE-MODEL / SINGLE SOURCE OF TRUTH:** Persistenz ausschliesslich ueber den entschiedenen Projektionspfad mit ownership-strenger Record-Bindung — keine Seitentabelle, kein zweiter Schreibweg, kein Hidden-State. Kanonische Wahrheit ist das State-Backend (§77.5).
- **FAIL-CLOSED:** ungueltige State-Uebergaenge, falsche Record-Typen und ungueltige/nicht existente Linkziele werden hart abgelehnt.
- **TYPISIERT STATT STRINGS:** Status/kind/priority/origin/target_kind/relation-kind als StrEnum, Link-Ziele typisiert, keine Flag-Kaskaden.
- **STRUKTURREGELN / BC-SCHNITT:** task_management ist ein eigenstaendiger BC ohne Pipeline-Kopplung — keine Phasen/Gates/Worktrees, keine zirkulaere Abhaengigkeit auf `pipeline_engine` (§77.6).
- **ARCH-55:** Entitaeten/Tabellen/Spalten/Wire-Keys/Enum-Werte (`tm_tasks`/`tm_task_links`, `create_task`, `target_kind=task|story`, `relates_to|spawned_story|duplicate_of` etc.) englisch.
- **ZERO DEBT:** der BC ist im FK-77-Scope (§77.1-§77.7) vollstaendig (Zustand + Verlinkung + volle Surface); die bewusst ausgelagerten Teile (UI AG3-105, Producer-Verdrahtung FK-29/38, Events FK-91, ggf. FK-69-Enum AG3-081) sind mit Owner benannt.

## 6. Hinweise fuer den Sub-Agent
- Read T:/codebase/claude-agentkit3/CLAUDE.md first — all project rules apply to you.
- **Kritische Abgrenzung (PO + §77.6):** dieser BC verwaltet NUR Zustand/Verlinkung. KEINE Phasen, KEINE Gates, KEINE Worktrees, KEINE Kopplung an den Story-Run-Lifecycle, KEINE `PipelineEngine`-Uebergabe. Tasks werden freestyle abgearbeitet. Baue nichts „Pipeline-artiges" ein.
- **Felder exakt** aus `formal.task-management.entities` uebernehmen (siehe AK1) — keine erfundenen Felder wie `owner`/`note`.
- **Linkziele:** `target_kind ∈ {task, story}` — **nicht** Artefakte. Task-zu-Task und Task-zu-Story beidseitig abfragbar modellieren; bei `target_kind=task` gleicher `project_key` Pflicht.
- **`resolve_task` vs. `dismiss_task` strikt trennen** (done vs. dismissed); `link_task`/`unlink_task` aendern keinen Status.
- **Read-Surface tenant-scoped:** `get_task(project_key, task_id)` und `list_tasks_for_target(project_key, target_kind, target_id)` tragen `project_key` **verbindlich** (Task-Identitaet `(project_key, task_id)`, Mandantenregel). Keine ungescopeten Read-Methoden bauen, auch wenn FK-77 §77.7 die Prosa-Signaturen ohne `project_key` zeigt — das ist eine bekannte Prosa-Luecke, die hier aus `formal.task-management.entities` praezisiert wird.
- **Persistenz-Surface:** die reale Code-Klasse heisst `ProjectionAccessor` (`telemetry/projection_accessor.py`), **nicht** `Telemetry`. Vor Code-Beginn die AK8-Entscheidung festschreiben: Default (a) dedizierter Task-Port analog `record_fc_incident`; (b) FK-69-Enum-Erweiterung NUR via AG3-081 (dann Abhaengigkeit). Den 7-Werte-`ProjectionKind`-Enum NICHT still erweitern.
- **Events** sind bewusst nicht Teil dieser Story (FK-77 §77.7 stellt sie bis zum konkreten Konsumenten zurueck, Owner FK-91); keine Event-Emission bauen, kein „spaeter"-Stub.
- Schema in **beiden** Stores (`postgres_schema.sql` + `sqlite_store.py`), `SCHEMA_VERSION` ziehen falls noetig.
- Die UI (AG3-105) dockt an diese Surface an — anlegen/verlinken/entlinken/erledigen/verwerfen/lesen muessen sauber abgedeckt sein.
- AK2 NICHT veraendern. `.mcp.json` NICHT anfassen. **Kein Commit** ohne expliziten Auftrag.
- „done" nur mit Beleg: Diff-Zusammenfassung, gruene Pflichtbefehle, Test-Namen (State-Machine, n:m gegen task+story, Surface-Vollstaendigkeit aller acht Methoden, Persistenz-Roundtrip, Abgrenzungstest).

---

## Globale Akzeptanzkriterien (verbindlich)

Zusaetzlich zu den obigen Akzeptanzkriterien gelten die **globalen Akzeptanzkriterien**
aus `stories/_GLOBAL_ACCEPTANCE.md` (Single Source of Truth):

- **GAC-1:** `scripts/ci/check_architecture_conformance.py` laeuft mit **0 Errors**
  (Exit 0, fail-closed) — `PYTHONPATH=src .venv\Scripts\python scripts/ci/check_architecture_conformance.py`.
- **GAC-2:** Die Architektur-Guardrails `guardrails/architecture-guardrails.md`
  (ARCH-NN) werden eingehalten; Konflikt = hart stoppen und melden.
