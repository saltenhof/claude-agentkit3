# AG3-072: StorySplitService + Split-Plan + Dependency-Rebinding

**Typ:** Implementation
**Groesse:** M
**Bounded Context:** `story-lifecycle` — administrative Recovery-Komponente fuer den Praxisfall einer bestaetigten `scope_explosion`: die ueberdehnte Ausgangs-Story wird kontrolliert als `Cancelled` beendet und ihr Scope in neu geschnittene Nachfolger-Stories ueberfuehrt. **Kein** Pipeline-Schritt, **kein** Override, **kein** Reset.

**Quell-Konzepte (autoritativ):**
- `FK-54 §54.4` — Einstiegsvoraussetzungen (fail-closed): festgestellte `scope_explosion`, menschliche Split-Freigabe, gueltiger Split-Plan, keine konkurrierende administrative Operation; typischer Vorzustand `PAUSED`/`escalation_class: scope_explosion`
- `FK-54 §54.5` — Ergebniszustand: Ausgangs-Story `Cancelled`, Nachfolger `Backlog`, Dependencies/Beziehungen umgebogen, steuernde Runtime-Reste/Locks/Worktrees/Branches entfernt, Audit-/Split-Nachweis erhalten
- `FK-54 §54.6` — CLI `agentkit split-story --story --plan --reason` (Split-Plan ist vertraglicher Kern, kein Komfort-Input)
- `FK-54 §54.7` + `formal.story-split.entities` — Split-Plan-Minimalstruktur (`source_story_id`, `reason`, `successors[]` mit `story_id`/`title`/`scope_slice`, `dependency_rebinding[]`, `story_lineage`); `story_lineage` wird deterministisch aus `source_story_id` + `successors[].story_id` abgeleitet
- `FK-54 §54.8` — 7-Schritt-Ablauf: (1) Split-Vorgang registrieren (`split_id`) → (2) Story exklusiv fence'n → (3) aktive Runtime quiescen → (4) Nachfolger ueber Story-Creation-Vertrag erzeugen → (5) Dependencies + `split_from`/`split_successors`-Lineage umbiegen → (6) fachnahe Anreicherungen (ARE/Repo-Affinitaet/Labels/Concept-Refs/VektorDB) neu aufbauen + Ausgangs-Story `superseded_by=[...]` → (7) Ausgangs-Story kontrolliert beenden (nicht via Closure)
- `FK-54 §54.9/§54.10/§54.11` — Audit/Telemetrie bleiben erhalten (gueltiger Befund), duerfen aber Nachfolger nicht blockieren; Guard-Regeln (nur offizieller Split-Pfad trotz Story-Lock); Integrationsfolgen (Backend-Status, Nachfolger-Anlage, Rebinding, Reindexierung, `story.md`, ARE-Neuableitung)

---

## 1. Kontext / Ist-Zustand (belegt)

Der `StorySplitService` ist **vollstaendig ungebaut**; vorhanden ist nur die vorgelagerte FK-25-Scope-Explosion-**Detektion**:

- `src/agentkit/exploration/phase.py:120-121` — explizit „StorySplitService is out of scope, FK-25 §25.6.3"; die Phase reagiert nur mit `_SCOPE_EXPLOSION_REACTION = "scope_explosion_detected: recommend story split"` (Empfehlung, kein Vollzug).
- `src/agentkit/exploration/mandate/classification.py:80` (`SCOPE_EXPLOSION`) + `exploration/.../telemetry.py:85` (`emit_scope_explosion`) — die Detektion existiert, der Reaktions-Service nicht.
- `src/agentkit/governance/principal_capabilities/operations.py:168` — `"split-story"` ist als `ADMIN_SUBCOMMAND` reserviert; `governance/guards/branch_guard.py:26` laesst `"agentkit split-story"` als offiziellen Pfad zu. **Kein Service, kein CLI-Command, kein Split-Plan-Parser, kein Rebinding.**
- `src/agentkit/cli/main.py:38-141` — kein `split-story`-Subparser.

Reale Anknuepfungspunkte (FIX-THE-MODEL):
- **Story-Creation-Vertrag**: Nachfolger werden ueber denselben fachlichen Story-Creation-Pfad erzeugt wie normale Stories (`story_context_manager/service.py`, Story-Anlage mit `status=Backlog` → `service.py:384`). Der aufrufende Actor ist `StorySplitService` (offizieller Systempfad, skriptgesteuerte Anlage zulaessig — §54.8.4).
- **`Cancelled`-Status**: `StoryStatus.CANCELLED` existiert (`story_model.py:46`). Der vorhandene `cancel_story()`-Pfad (`service.py:594-654`) reicht fuer den Split **nicht**: `_ALLOWED_TRANSITIONS` enthaelt nur `Backlog/Approved -> Cancelled` (`service.py:84-85`), und `_check_transition` wirft fuer `In Progress -> Cancelled` explizit `InvalidStatusTransitionError` mit Verweis auf Story-Reset/Story-Exit (`service.py:112-122`); die Docstring bestaetigt `In Progress or Done -> invalid_transition` (`service.py:604`). Da die Ausgangs-Story im Split typischerweise `In Progress` ist, muss diese Story einen **administrativen Split-Cancel-Pfad** spezifizieren (offizieller Systempfad, `In Progress -> Cancelled` mit Begruendung `scope_split`), der die `Cancelled`-Semantik nutzt, aber **nicht** ueber Closure und **nicht** ueber den fuer Frontend-Transitions gedachten `cancel_story()`-Guard laeuft (§54.8.7). Die `terminal_state`/`exit_class`-Achse selbst bleibt AG3-074-Owner (siehe Out of Scope).
- **Quiesce/Runtime-Purge**: `state_backend/store/projection_repositories.py` `purge_run(...)` (`:196/:202`) fuer `phase_state_projection`; Worktree/Branch-Behandlung analog zum Reset-Anker (AG3-071).
- **Idempotenz/Claim**: `control_plane/records.py:49-89` `ControlPlaneOperationRecord` (leased, `op_id`/`operation_kind`) als Muster fuer den Split-Record/Resume.
- **VektorDB-Reindexierung**: AG3-068 (`story_sync`/Reindex, `vectordb`) ist der Owner — der Split ruft die Reindex-Schnittstelle, baut keinen eigenen Index.

Kontext-Konflikt-Check: Im Unterschied zum Reset (AG3-071) bleiben Telemetrie/Auditspur der Ausgangs-Story **erhalten** (gueltiger Befund, §54.9.2) — kein voller Purge der Analytics. Die Ausgangs-Story wird im Index **nicht** geloescht, sondern `Cancelled` + `superseded_by=[...]` fortgeschrieben (§54.8.6). Der Split darf NICHT den Closure-Pfad benutzen.

## 2. Scope

### 2.1 In Scope
1. **`StorySplitService` (story-lifecycle-BC)** mit dem §54-Vertrag: Einstiegsgate, Registrierung, Fence/Quiesce, Nachfolger-Erzeugung, Rebinding, Lineage, kontrollierte Beendigung der Ausgangs-Story.
2. **Einstiegsgate (§54.4)** als harter, fail-closed Service-Vertrag **vor** jeder Mutation: Der Split wird abgelehnt, wenn nicht alle vier Voraussetzungen erfuellt sind — (a) `scope_explosion` festgestellt, (b) typischer Vorzustand `PAUSED`/`escalation_class: scope_explosion`, (c) explizite menschliche Split-Freigabe (vertreten durch den menschlich gestarteten CLI-Pfad mit gueltigem `--plan`), (d) keine konkurrierende administrative Operation (z. B. aktiver Reset) fuer dieselbe Story. Reject ohne Teil-Mutation.
3. **Split-Record (`split_id`)** als typisiertes Audit-Modell (§54.8.1): `split_id`, `project_key`, `source_story_id`, `requested_by`, `reason`, `plan_ref`, `status`. `split_id` wird **deterministisch** aus dem Resume-Key `(project_key, source_story_id, plan_ref-Hash)` abgeleitet, damit ein zweiter Lauf mit identischem `--story`/`--plan` denselben Split-Record wiederfindet, ohne dass die CLI eine `split_id` annehmen muss (siehe CLI-Vertrag). Am `ControlPlaneOperationRecord`-Leased-Muster.
4. **Split-Plan-Parser** (typisiertes Pydantic-Modell) gemaess §54.7-Minimalstruktur: `project_key`, `source_story_id`, `reason`, `successors[]` (`story_id`/`title`/`scope_slice`), `dependency_rebinding[]` (`dependent_story_id`/`old_dependency`/`new_dependencies[]`) und `story_lineage`. **`story_lineage`** wird deterministisch aus `source_story_id` + den `successors[].story_id` abgeleitet (kein zusaetzlicher freier Plan-Input); die formale Entitaet `formal.story-split.entities` fuehrt `story_lineage` als Plan-Attribut, das ueber `split_from`/`split_successors` (Scope-Item 7) materialisiert wird. Fail-closed bei fehlenden Pflichtfeldern oder inkonsistenten Referenzen.
5. **CLI `agentkit split-story`** in `cli/main.py`: Pflichtparameter `--story`/`--plan`/`--reason` (genau die §54.6-Schnittstelle, keine zusaetzliche `--split-id`-Option); einziger Ausloeser (kein automatischer Pfad). Der Plan wird gelesen/validiert, bevor irgendeine Mutation erfolgt. Der Resume-Key (Scope-Item 3) ergibt sich aus `--story` + `--plan`.
6. **7-Schritt-Ablauf (§54.8)** in fester Reihenfolge: Fence (kein resume/reset-escalation/Worker-Spawn/Git unter Lock) → Quiesce (Flow/Node, `phase_state_projection`, Locks/Leases, Branch/Worktree) → Nachfolger-Erzeugung im `Backlog` ueber Story-Creation-Vertrag inkl. `story.md`-Export → Dependency-Rebinding + `split_from`/`split_successors` → fachnahe Neuableitung (ARE/Repo-Affinitaet/Labels/Concept-Refs/VektorDB-Reindex) + Ausgangs-Story `superseded_by=[...]` → kontrollierte Beendigung ueber den **administrativen Split-Cancel-Pfad** (Backend `In Progress → Cancelled` mit Begruendung `scope_split`, Split-Artefakt/Auditspur verlinkt, **nicht** via Closure, **nicht** via Frontend-`cancel_story()`).
7. **Dependency-Rebinding (§54.8.5 + `formal.dependency-rebinding.invariants`):** Umsetzung aller Plan-Eintraege unter den formalen Invarianten — (a) Rebinding erst **nach** erfolgreicher Nachfolger-Anlage (`mapping_requires_successors_created`); (b) **kein stiller Drop**: jede entfernte Dependency-Kante wird entweder an deklarierte Nachfolger-Kanten umgebogen oder endet in einer expliziten Ablehnung (`no_silent_drop`); (c) **keine stale Cancelled-Kante** (`no_stale_cancelled_target`); (d) **deterministische Zielauswahl**: identische Inputs/Policy erzeugen immer dieselbe Zielmenge (`deterministic_target_selection`); (e) **kein unbegruendeter Fanout**: eine Quell-Dependency darf nur dann auf mehrere Nachfolger expandieren, wenn der Plan das explizit deklariert (`no_unjustified_fanout`); (f) **Graph-Integritaet**: keine doppelten aktiven Kanten und keine Zyklen im expliziten Story-Graph (`graph_integrity_preserved`).
8. **Audit/Telemetrie-Erhalt (§54.9):** bisherige Auditspur/Telemetrie der Ausgangs-Story bleibt erhalten, blockiert aber keinen Nachfolger-Start, triggert keine Nachfolger-Guards, zaehlt nicht als erfolgreiche Delivery.
9. **Branch-Guard-Allowlist (§54.10, Teil 1):** Der vorhandene `BranchGuard` laesst den Kommando-Prefix `"agentkit split-story"` ueber `_OFFICIAL_ALLOW_PREFIXES` (`branch_guard.py:23-27`) trotz aktivem Story-Lock zu, waehrend freie Git-Mutationen geblockt bleiben. Diese Story verprobt **nur** den vorhandenen Prefix-Pfad; sie erweitert die Allowlist nicht. Das Backend-Servicepfad-Verdict (`ALLOW_VIA_OFFICIAL_SERVICE_PATH`/`is_official_service_path`) ist explizit **nicht** Teil dieser Story (siehe Out of Scope, AG3-087).
10. **Negativ-/Phasengrenz-Tests** (siehe AC).

### 2.2 Out of Scope (mit Owner)
- **Scope-Explosion-Detektion + PAUSED/escalation_class** — bereits vorhanden (FK-25, `exploration/mandate/classification.py`); diese Story konsumiert den Befund, baut die Detektion nicht neu.
- **Enge Reklassifikation auf `integration_stabilization`** (FK-05 narrow exception statt Split) — **AG3-069** (Integration-Stabilization-Maschinerie). Hier nur der Standard-Split-Pfad.
- **VektorDB-Reindex-Laufzeit** (`story_sync`/Reindex) — **AG3-068**; der Split ruft die Schnittstelle, ist nicht ihr Owner.
- **`terminal_state`/`exit_class`-Achse + `exit_class=scope_split`-Invarianten** — **AG3-074** (FK-59). Diese Story setzt den Backend-Status `Cancelled`; die konsolidierte Ergebnisachse + `exit_class`-Constraints sind dort modelliert. Falls AG3-074 noch nicht gebaut ist, nur den vorhandenen `StoryStatus.CANCELLED` setzen und das `exit_class`-Mapping an AG3-074 spiegeln (nicht hier doppeln).
- **Offizielles Servicepfad-Verdict `ALLOW_VIA_OFFICIAL_SERVICE_PATH` / `is_official_service_path`** — **AG3-087** (FK-55 §55.6/§55.10.8/§55.10.10). Diese Story modelliert es **nicht** und macht sich davon **nicht** abhaengig: Der Guard-Vertrag (Scope-Item 9) wird ausschliesslich ueber den bereits vorhandenen Branch-Guard-Kommando-Prefix abgesichert. Sobald AG3-087 das Servicepfad-Verdict liefert, kann der Split-Guard-Pfad zusaetzlich daran andocken — das ist kein Blocker fuer diese Story.
- **Operator-CLI-Sammeloberflaeche** — **AG3-076** dockt nur an.

## 3. Akzeptanzkriterien
1. `StorySplitService` existiert mit Einstiegsgate/Registrierung/Fence/Quiesce/Nachfolger-Erzeugung/Rebinding/Beendigung; der Split-Plan ist ein typisiertes Pflicht-Modell, kein freier Dict-Durchreich.
2. `agentkit split-story --story X --plan p.json --reason "..."` ist in `cli/main.py` registriert (genau `--story`/`--plan`/`--reason`); der Plan wird **vor** jeder Mutation gelesen/validiert; ungueltiger/unvollstaendiger Plan → fail-closed, keine Teil-Mutation (Negativtest).
3. **Einstiegsgate (§54.4, `formal.story-split.scenario.reject-without-scope-explosion-preconditions`):** Fehlt eine der vier Voraussetzungen (kein festgestellter `scope_explosion`, kein `PAUSED`/`escalation_class: scope_explosion`, keine menschliche Freigabe via CLI, oder eine konkurrierende administrative Operation fuer dieselbe Story aktiv), schlaegt der Split fehl (`status=failed`) **ohne jede Teil-Mutation** — keine Nachfolger angelegt, kein Rebinding, Ausgangs-Story unveraendert (Negativtest pro Voraussetzung).
4. Nach erfolgreichem Split gilt der §54.5-Endzustand: Ausgangs-Story `Cancelled` (Backend), Nachfolger im `Backlog`, Runtime-Reste/Locks/Worktree/Branch entfernt, Audit-/Split-Nachweis erhalten (Test).
5. Nachfolger werden ueber den **Story-Creation-Vertrag** angelegt (gleicher Pfad wie normale Stories), inkl. `story.md`-Export; Actor ist `StorySplitService` (Test).
6. **Dependency-Rebinding-Invarianten (`formal.dependency-rebinding.invariants`):** Das Rebinding setzt die Plan-Eintraege erst nach erfolgreicher Nachfolger-Anlage um und erfuellt fail-closed:
   - **no stale cancelled target** — keine abhaengige Story zeigt nach dem Split still auf die `Cancelled`-Ausgangs-Story, wenn Nachfolger existieren (Negativtest: ungebogene Dependency → fail-closed);
   - **no silent drop** — jede entfernte Kante wird umgebogen oder explizit abgelehnt; eine still verschwundene Kante ist ein Fehler (Negativtest);
   - **deterministic target selection** — identische Inputs/Policy erzeugen reproduzierbar dieselbe Zielmenge (Test: Wiederholung liefert identisches Ergebnis);
   - **no unjustified fanout** — eine Quell-Dependency expandiert nur bei expliziter Plan-Angabe auf mehrere Nachfolger; impliziter Fanout → fail-closed (Negativtest);
   - **graph integrity preserved** — keine doppelten aktiven Kanten und keine Zyklen im expliziten Story-Graph (Negativtest: Plan, der ein Duplikat/einen Zyklus erzeugen wuerde → fail-closed).
7. `split_from`/`split_successors`-Lineage ist gesetzt (deterministisch aus `source_story_id` + `successors[].story_id`); Ausgangs-Story `superseded_by=[...]` im Index (Test).
8. Ausgangs-Story wird ueber den **administrativen Split-Cancel-Pfad** `In Progress → Cancelled` beendet, **nicht** ueber Closure und **nicht** ueber den Frontend-`cancel_story()`-Guard (Test: Closure-Pfad wird nicht aufgerufen; der Frontend-Cancel-Guard, der `In Progress → Cancelled` verbietet, wird nicht als Vollzugspfad benutzt; reiner administrativer Status-/Audit-Pfad).
9. Audit/Telemetrie der Ausgangs-Story bleiben erhalten und blockieren keinen Nachfolger-Start / triggern keine Nachfolger-Guards / zaehlen nicht als Done (Test).
10. **Branch-Guard:** der vorhandene `BranchGuard` laesst den Kommando-Prefix `"agentkit split-story"` trotz aktivem Story-Lock zu (`_OFFICIAL_ALLOW_PREFIXES`), waehrend eine freie Git-Mutation am Service vorbei geblockt bleibt (Test ueber die vorhandene Branch-Guard-Allowlist; **kein** Test des AG3-087-Servicepfad-Verdikts).
11. **Idempotenz/Resume:** Ein zweiter `split-story`-Lauf mit identischem `--story` und `--plan` findet ueber den deterministischen Resume-Key `(project_key, source_story_id, plan_ref-Hash)` denselben Split-Record (`split_id`) und ist ein Resume — keine Doppel-Anlage der Nachfolger, kein Doppel-Rebinding, keine zweite Cancel-Transition (Test; die CLI nimmt **keine** `split_id` entgegen).
12. **Pflichtbefehle gruen:** pytest unit/integration/contract (in Chunks, `-n0`); mypy default + `--platform linux`; ruff; vier Konzept-Gates; Coverage >= 85 %.

## 4. Definition of Done
- AK 1–12 erfuellt; giftige Codex-Review PASS; (Implementierung/Commit erst nach Execution-Plan-Freigabe — diese Story wird zunaechst nur autorisiert/reviewt).

## 5. Guardrail-Referenzen
- **FAIL-CLOSED:** fehlende §54.4-Einstiegsvoraussetzungen, ungueltiger/unvollstaendiger Split-Plan, stiller Dependency-Drop, unbegruendeter Fanout, Duplikat-/Zyklus-Kanten und ungebogene Dependencies blockieren; keine Teil-Mutation, kein stiller Zeiger auf eine `Cancelled`-Story.
- **FIX-THE-MODEL / SINGLE SOURCE OF TRUTH:** Nachfolger ueber den vorhandenen Story-Creation-Vertrag, Reindex ueber AG3-068, Quiesce ueber die vorhandenen `purge_run`-Owner; keine zweite Steuerwahrheit, kein Closure-Missbrauch.
- **ZERO DEBT:** der Split zieht alle §54.11-Integrationsfolgen real durch; keine „recommend split"-Attrappe wie im Ist-Zustand.
- **TYPISIERT STATT STRINGS:** Split-Plan/Split-Record/Lineage typisiert (Pydantic v2), kein String-/Flag-Geflecht.
- **ARCH-55:** alle neuen Identifier/Wire-Keys/CLI-Optionen/DB-Spalten englisch.

## 6. Hinweise fuer den Sub-Agent
- Read T:/codebase/claude-agentkit3/CLAUDE.md first — all project rules apply to you.
- Kritische Anknuepfungspunkte: `exploration/phase.py:120-121` (heutiger „recommend split"-Stub — der wird durch den realen Service abgeloest, der Befund/Empfehlung bleibt der Eingang), Story-Creation-Pfad in `story_context_manager/service.py` (`:378-384` Backlog-Anlage), bestehender `cancel_story()`-Pfad `service.py:594-654` mit Transition-Tabelle `service.py:80-89` und `_check_transition` `service.py:97-130` (der `In Progress -> Cancelled` blockt — siehe Ist-Zustand), `branch_guard.py:23-27` (`_OFFICIAL_ALLOW_PREFIXES` inkl. `"agentkit split-story"`) + `operations.py:168` (`ADMIN_SUBCOMMANDS` inkl. `"split-story"`).
- Fallstrick: Split ist **kein** Reset. Auditspur/Telemetrie der Ausgangs-Story bleibt erhalten (kein Voll-Purge), die Story bleibt im Index als `Cancelled`+`superseded_by`. Ausgangs-Story NICHT ueber Closure beenden.
- Fallstrick: `exit_class=scope_split` + `terminal_state` gehoeren AG3-074. Wenn dort noch nicht gebaut: nur `StoryStatus.CANCELLED` setzen und das `exit_class`-Mapping an AG3-074 spiegeln (kein zweites exit_class-Modell hier).
- Fallstrick: VektorDB-Reindex ist AG3-068-Owner — Schnittstelle aufrufen, nicht neu bauen.
- AK2 NICHT veraendern. `.mcp.json` NICHT anfassen. **Kein Commit** ohne expliziten Auftrag.
- „done" nur mit Beleg: Diff-Zusammenfassung, gruene Pflichtbefehle, Test-Namen (Plan-Validierung, Endzustand, Rebinding-Negativtest, Closure-nicht-aufgerufen, Idempotenz).

---

## Globale Akzeptanzkriterien (verbindlich)

Zusaetzlich zu den obigen Akzeptanzkriterien gelten die **globalen Akzeptanzkriterien**
aus `stories/_GLOBAL_ACCEPTANCE.md` (Single Source of Truth):

- **GAC-1:** `scripts/ci/check_architecture_conformance.py` laeuft mit **0 Errors**
  (Exit 0, fail-closed) — `PYTHONPATH=src .venv\Scripts\python scripts/ci/check_architecture_conformance.py`.
- **GAC-2:** Die Architektur-Guardrails `guardrails/architecture-guardrails.md`
  (ARCH-NN) werden eingehalten; Konflikt = hart stoppen und melden.
