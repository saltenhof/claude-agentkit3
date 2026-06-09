# AG3-105: Task-Management-UI (Freestyle-To-Do, nicht pipeline-gemanagt)

**Typ:** Implementation
**Groesse:** M
**Bounded Context:** `frontend` Task-Slice (neuer BC-aligned Slice neben der Story-Verwaltung) ueber der `task_management`-BC-Surface (AG3-096). **PO-Ergaenzung 2026-06-07** — die EINZIGE funktionale Erweiterung gegenueber dem Prototyp.
**Quell-Konzepte (autoritativ):**
- `FK-77 §77.1-§77.7` (`concept/technical-design/77_task_management.md`) — Task-Management-BC: `§77.1` Datenmodell `Task`/`TaskLink`, `§77.2` Lifecycle `open -> done/dismissed`, `§77.3` Verlinkungsmodell (n:m, bidirektional, `target_kind ∈ {task, story}`), `§77.6` technische Abgrenzung (nie an `PipelineEngine`, kein Phase-Handler), `§77.7` Aufruf-Surface. Maschinenpruefbare Semantik: `formal.task-management.entities` (`concept/formal-spec/task-management/entities.md`), `formal.task-management.state-machine`, `formal.task-management.commands` (`concept/formal-spec/task-management/commands.md`). Die UI ist **Konsument** dieser Surface; das Datenmodell/Schreib-/Lesemodell selbst liefert **AG3-096**.
- `FK-72-Stil` (FK-72 §72.2/§72.3/§72.6) — BC-aligned Slice in der App-Shell; Look&Feel/Komponenten im Prototyp-Stil (FK-72 §72.13 Prototyp = normative visuelle/UX-Quelle); FK-64-Design-Tokens.
- **PO-Abgrenzung (Master-Index Welle 7 + AG3-096):** Tasks werden **freestyle durch Mensch/Agent** abgearbeitet, **NICHT** von der AK3-Pipeline orchestriert — kein Phasen-/Gate-/Worktree-Lauf. Die `task_management`-BC verwaltet nur **Zustand/Verlinkung**, nicht die Ausfuehrung.

---

## 1. Kontext / Ist-Zustand (belegt)

- **Im Prototyp fehlt jede Task-/To-Do-Oberflaeche.** Beleg: die Top-Navigation in `frontend/prototype/src/App.tsx:602`-`:618` kennt nur `graph`/`kanban`/`sheet`/`analytics`/`hub` (`ViewMode`, `App.tsx:76`); es gibt keinen Task-View, kein Task-Modell im Store (`frontend/prototype/src/store/storyModel.ts` enthaelt nur Story-/Execution-Typen), keine Task-Selektoren (`frontend/prototype/src/store/storySelectors.ts`).
- Diese Story ist die **einzige funktionale Neuentwicklung** der Frontend-Welle (Master-Index §111/§120: „EINZIGE funktionale Ergaenzung gegenueber dem Prototyp"). Sie ist im Prototyp-Stil **neu zu entwerfen**, nicht aus vorhandenem UI abzuleiten.
- **Die fachliche Surface (`task_management`-BC) ist ein Abhaengigkeits-Vertrag, noch kein geliefertes Produkt.** AG3-096 (`status: draft`, `phase: review_pending`, `stories/AG3-096-task-management-bc/status.yaml:4`-`:5`) definiert die Surface autoritativ — `Task`/`TaskLink`, State-Machine `open -> done/dismissed`, Tabellen `tm_tasks`/`tm_task_links`, Top-Surface `create_task`/`link_task`/`unlink_task`/`resolve_task`/`dismiss_task` + Read-Methoden (`stories/AG3-096-task-management-bc/story.md:42`-`:45`). AG3-096 selbst belegt, dass **noch kein Produktionscode** existiert (`stories/AG3-096-task-management-bc/story.md:16`-`:18`: Grep `task_management|tm_tasks|create_task|TaskLink` in `src/agentkit` = 0 Treffer). Diese UI-Story konsumiert diesen Vertrag und ist erst lauffaehig, sobald AG3-096 implementiert ist und gruen ist (siehe §7 Vorbedingung). Sie baut **keine** eigene Task-Persistenz/Logik.
- Verfuegbare Stil-/Komponenten-Anker im Prototyp: `frontend/prototype/src/components/StoryCard.tsx` (Card-Muster), `KpiBar.tsx`, `CopyButton.tsx`, `FastBadge.tsx`, `Badge`/`Info` (`App.tsx:2073`/`App.tsx:2087`), Kanban-Spalten-/Drag-Muster (`App.tsx:853`), Inspector-Tab-Strip (`App.tsx:1726`/`App.tsx:1753`). Status-/Statusfarben-Konventionen aus `frontend/prototype/src/design-system.css` (FK-64).

## 2. Scope

### 2.1 In Scope
1. **Neuer Task-Slice in der App-Shell** (FK-72 §72.3, eigener `contexts`-/Foundation-naher Slice neben den Story-Sichten): eigener Navigationspunkt + View, klar **getrennt** von der Story-Verwaltung (Tasks sind keine Stories, durchlaufen keine Pipeline).
2. **Task-Liste/-Board** im Prototyp-Stil: Anzeige der Tasks aus der `task_management`-Surface (AG3-096) mit Status `open`/`done`/`dismissed`, Titel/Beschreibung, Verlinkungs-Badges. Look&Feel via Prototyp-Komponenten (Card/Badge/Info) und FK-64-Tokens (AG3-092).
3. **Task-Aktionen** gebunden an die BC-Top-Surface (AG3-096, FK-77 §77.7, `formal.task-management.commands`), **nicht** an Pipeline-Endpunkte:
   - **Anlegen** -> `create_task` (Titel/Beschreibung; optional initiale Links),
   - **Verlinken (n:m)** -> `link_task` zu Stories und/oder anderen Tasks (mehrfach, beidseitig sichtbar),
   - **Entlinken** -> `unlink_task` (entfernt eine `TaskLink`-Kante; aendert keinen Status),
   - **Erledigen** -> `resolve_task` (`open -> done`, setzt `resolved_by`/`resolved_at`),
   - **Verwerfen** -> `dismiss_task` (`open -> dismissed`, setzt `resolved_by`/`resolved_at`).
   Die State-Machine ist `open -> done/dismissed` (terminale Zustaende, kein Reopen in v1); die UI bietet aus `open` nur die erlaubten Uebergaenge an. `resolve_task` setzt ausschliesslich `done`, `dismiss_task` ausschliesslich `dismissed` — **kein** vermischter `resolve_task(... dismissed)`-Pfad (FK-77 §77.2, `formal.task-management.commands`: getrennte Commands).
4. **Verlinkungs-Sicht (n:m)**: pro Task die verknuepften Stories/Tasks; `target_kind ∈ {task, story}` mit typisierter Beziehung `kind` (`relates_to | spawned_story | duplicate_of`), **keine** Artefakt-Links (FK-77 §77.3, `formal.task-management.entities:100`-`:110`). Beidseitige Rueckschau ueber `list_tasks_for_target` (Story-/Task-Detail -> verlinkende Tasks). Klick auf einen verlinkten Story-Link fokussiert die Story in der bestehenden Story-Sicht (Cross-Slice-Navigation ueber die Shell).
5. **Explizite Abgrenzung im UI** (PO-Mandat sichtbar machen): Tasks tragen **keine** Phasen-/Gate-/Worktree-/QA-Elemente; kein Story-Inspector-Flow-Tab, kein Mode-Indicator, keine Execution-Limits. Die Freestyle-Natur (Mensch/Agent arbeitet ab) ist im UI klar (z. B. simple open/done/dismissed-Semantik statt Pipeline-Status).
6. **Empty-/Error-Verhalten** analog FK-72 §72.14.6: leere Task-Liste -> Hinweis + Anlege-CTA; fehlgeschlagene Aktion -> Optimistic-Revert + Fehler-Pille mit `error_code`.

### 2.2 Out of Scope (mit Owner)
- **`task_management`-BC** (Entitaeten `Task`/`TaskLink`, State-Machine, Tabellen `tm_tasks`/`tm_task_links`, Top-Surface inkl. Read-Methoden, n:m-Persistenz) — **AG3-096** (`depends_on`, Vertrag noch nicht implementiert, siehe §1 und §7). Diese UI baut **keine** eigene Task-Logik/Persistenz.
- **BFF-`http/`-Modul fuer `task_management`** — die `task_management`-BC-Surface ist transport-agnostisch (FK-77 §77.7); fuer die Browser-UI braucht es ein duennes `http/`-Adaptermodul analog AG3-090 (Routing-Huelle) bzw. AG3-091 (Read-Model). **Dieses Modul ist derzeit von keiner Story geliefert**: AG3-090 zaehlt acht BC-`http/`-Module auf (`pipeline_engine/verify_system/governance/closure/artifacts/kpi_analytics/failure_corpus/requirements_coverage`) — `task_management` ist **nicht** dabei; AG3-091 listet keine Task-Read-Models. Das ist eine echte Cross-Story-Luecke (§7) — **nicht** als zweite Wahrheit hier gebaut.
- **App-Shell/Design-Tokens** — **AG3-093** (`depends_on`) / **AG3-092**.
- **Pipeline-Funktionen jeder Art** — bewusst NICHT: Tasks sind nicht pipeline-gemanagt (PO).

## 3. Akzeptanzkriterien
1. Es gibt einen eigenen Task-Navigationspunkt/-View, getrennt von den Story-Sichten; Tasks erscheinen nicht in Story-Board/Sheet/Graph und umgekehrt (Struktur-/Render-Test).
2. Task-Liste rendert die Tasks der `task_management`-Surface mit Status `open`/`done`/`dismissed` und Verlinkungs-Badges (Test gegen gemockte Surface-Antwort).
3. **Anlegen** ruft `create_task` (Test: neuer Task erscheint nach `create_task`-Response, nicht aus lokalem Schattenstate).
4. **Verlinken/Entlinken** rufen `link_task`/`unlink_task` und stellen n:m-Links **nur** mit `target_kind ∈ {task, story}` dar (Test: ein Story-Link und ein Task-Link, beidseitig sichtbar via `list_tasks_for_target`; ein versuchter Artefakt-Link existiert in der UI nicht / wird nicht angeboten — Artefakte sind kein gueltiges Linkziel, `formal.task-management.entities:100`-`:110`).
5. **Erledigen** ruft `resolve_task` (Ziel `done`), **Verwerfen** ruft `dismiss_task` (Ziel `dismissed`) — getrennte Commands, kein gemischter `resolve_task(... dismissed)`-Aufruf; die UI bietet aus `open` nur diese Uebergaenge, terminale Tasks (`done`/`dismissed`) bieten keine weiteren Aktionen (Test inkl. Negativ: kein `done -> open`, und Verwerfen ruft niemals `resolve_task`).
6. **Read-Surface tenant-scoped:** die UI liest ausschliesslich ueber die `project_key`-skopierten Read-Methoden der Surface — `get_task(project_key, task_id)`, `list_tasks(project_key, filter: status|type|kind|origin)`, `list_tasks_for_target(project_key, target_kind, target_id)` (FK-77 §77.7 + AG3-096-Praezisierung `stories/AG3-096-task-management-bc/story.md:44`; Task-Identitaet `(project_key, task_id)`, `formal.task-management.entities:28`). Test: zwei Projekte mit identischer `task_id` liefern strikt partitionierte Listen/Detail — kein Cross-Tenant-Leak im UI-Read-Pfad.
7. **Keine Pipeline-Kopplung**: ein Test/Review belegt, dass die Task-Aktionen ausschliesslich gegen die `task_management`-Top-Surface gehen und **kein** Phasen-/Gate-/Worktree-/Story-Mutations-Endpunkt aufgerufen wird (FK-77 §77.6).
8. Look&Feel im Prototyp-Stil ueber Design-Tokens (AG3-092): keine `font-size`-Literale/Ad-hoc-Hex ausserhalb der Tokens (Conformance gruen).
9. Empty-State + Fehler-Pille (Optimistic-Revert) vorhanden (Test).
10. **Pflichtbefehle gruen:** pytest unit/integration/contract (in Chunks, `-n0`); mypy default + `--platform linux`; ruff; vier Konzept-Gates; Coverage >= 85 %. Zusaetzlich (Frontend-TS): Build + Frontend-Test-/Lint-Lauf gruen.

## 4. Definition of Done
- AK 1–10 erfuellt; giftige Codex-Review PASS; (Implementierung/Commit erst nach Execution-Plan-Freigabe **und** nach Lieferung/Gruen-Status des AG3-096-Vertrags + des Task-BFF-`http/`-Moduls — siehe §7 — diese Story wird zunaechst nur autorisiert/reviewt).

## 5. Guardrail-Referenzen
- **FIX THE MODEL / SINGLE SOURCE OF TRUTH:** Task-Zustand/-Verlinkung leben in der `task_management`-BC (AG3-096); die UI haelt **keine** zweite Task-Wahrheit, keinen Schattenstate als Persistenz.
- **ABGRENZUNG (PO):** Tasks sind freestyle, nicht pipeline-gemanagt — keine Phasen/Gates/Worktrees an Tasks. Diese Trennung ist ein fachliches Prinzip, kein optionales Detail (FK-77 §77.6).
- **FAIL CLOSED:** fehlgeschlagene Aktion -> sichtbar gemeldet (Fehler-Pille + Revert), nicht stilles Schlucken. Fehlender BC-Vertrag/BFF-Adapter -> melden (§7), nicht durch Frontend-Persistenz wegerklaeren.
- **TYPISIERT STATT STRINGS:** Task-Status/-Link-Typen typisiert (gebunden an die AG3-096-Surface: `open`/`done`/`dismissed`, `target_kind ∈ {task, story}`, `relates_to|spawned_story|duplicate_of`), keine String-Kaskaden.
- **KEIN GOD-VIEW:** Task-Slice ist ein eigener BC-aligned Slice, kein Anhaengsel an die Story-Sichten (FK-72 §72.2).
- **ARCH-55:** Task-Felder, Status-/Link-Werte, Aktions-Bezeichner englisch (`open`/`done`/`dismissed`, `create_task`/`link_task`/`unlink_task`/`resolve_task`/`dismiss_task`, `target_kind=task|story`); deutsche UI-Label sind Lokalisierung.

## 6. Hinweise fuer den Sub-Agent
- Read T:/codebase/claude-agentkit3/CLAUDE.md first — all project rules apply to you.
- Diese Sicht ist **neu** — es gibt keinen Prototyp-View zum Kopieren. Stil-/Komponenten-Anker: `frontend/prototype/src/components/StoryCard.tsx`, `KpiBar.tsx`, `CopyButton.tsx`, `Badge`/`Info` (`App.tsx:2073`/`App.tsx:2087`), Kanban-Muster (`App.tsx:853`), Inspector-Tab-Strip (`App.tsx:1753`), Statusfarben aus `frontend/prototype/src/design-system.css`. Look&Feel passend, Funktion neu.
- Harte Abgrenzung (PO): keinerlei Pipeline-Mechanik an Tasks. Wenn der Sub-Agent versucht, Tasks einen Flow-Tab/Phasen/Gates/Mode/Worktree zu geben, ist das ein Verstoss gegen den Auftrag (FK-77 §77.6).
- Surface-Vertrag (AG3-096, FK-77 §77.7, `formal.task-management.commands`): schreibend `create_task`/`link_task`/`unlink_task`/`resolve_task`/`dismiss_task`; lesend `get_task(project_key, task_id)`/`list_tasks(project_key, ...)`/`list_tasks_for_target(project_key, target_kind, target_id)`. **`resolve_task` (done) und `dismiss_task` (dismissed) strikt getrennt.** Linkziele **nur** `task | story` — **keine** Artefakte. Falls das BFF-`http/`-Modul/Read-Model fuer Tasks noch nicht existiert (es existiert derzeit nicht, §7), **melden** (Anknuepfung an AG3-090/091/096), nicht eine Task-Persistenz im Frontend erfinden.
- AK2 NICHT veraendern. `.mcp.json` NICHT anfassen. **Kein Commit** ohne expliziten Auftrag.
- „done" nur mit Beleg: Diff, gruene Pflichtbefehle, Frontend-Build/-Tests, Surface-Binding-Tests (inkl. „keine Pipeline-Kopplung" und Tenant-Scope der Read-Surface).

## 7. Vorbedingungen und offene fachliche Punkte
- **Vorbedingung — AG3-096 ist Vertrag, noch nicht geliefert.** AG3-096 ist `draft`/`review_pending` und besitzt laut eigener Ist-Aufnahme **keinen** Produktionscode (`stories/AG3-096-task-management-bc/story.md:16`-`:18`). Diese UI-Story kann erst **implementiert/ausgefuehrt** werden, wenn AG3-096 implementiert ist und seine Pflichtbefehle gruen sind. Bis dahin gilt AG3-096 als **Abhaengigkeits-Vertrag** (Surface-Definition), nicht als „geliefert". Alle Surface-Bezuege dieser Story sind contractual, nicht „real existing code".
- **Cross-Story-Voraussetzung — Task-BFF-`http/`-Modul fehlt (echte Luecke).** Die Browser-UI braucht ein transport-konkretes Adaptermodul ueber der transport-agnostischen `task_management`-Surface (FK-77 §77.7). AG3-090 liefert acht BC-`http/`-Module **ohne** `task_management`; AG3-091 listet keine Task-Read-Models. Damit traegt **keine** bestehende Story den Task-BFF-Adapter. Dies ist an die Owner AG3-090/091 (BFF-Welle) zu routen — siehe `remediation-r1.md` Cross-Story-Voraussetzungen. Diese Story baut den Adapter **nicht** selbst und erfindet keine Frontend-Persistenz.
- **Master-Index-Drift (doc-only, var/):** `var/concept-gap-analysis/_STORY_INDEX.md:120` beschreibt AG3-105 noch als „n:m zu Stories/Artefakten" und nennt die Surface „create_task/link_task/resolve_task". Beides ist gegenueber dem inzwischen autoritativen FK-77/`formal.task-management.*` veraltet (Linkziele `task | story`; Surface enthaelt zusaetzlich `unlink_task`/`dismiss_task`). `_STORY_INDEX.md` ist `var/`-ephemer (kein autoritativer Owner) — diese Story richtet sich nach FK-77 + formal-spec. Der Index-Drift ist als doc-only-Nachzug zu melden, nicht in dieser Story zu korrigieren.
- **Agent-Zugriff/Owner-Sicht:** Tasks werden „durch Mensch/Agent" abgearbeitet; `resolved_by ∈ {human, agent}` ist Surface-Feld (`formal.task-management.entities:81`-`:84`). Ob die UI eine Akteur-Spalte/-Badge zeigt, ist UI-Detail im Prototyp-Stil und kann ohne weitere Surface-Erweiterung aus `resolved_by` abgeleitet werden; keine neuen Felder erfinden.

---

## Globale Akzeptanzkriterien (verbindlich)

Zusaetzlich zu den obigen Akzeptanzkriterien gelten die **globalen Akzeptanzkriterien**
aus `stories/_GLOBAL_ACCEPTANCE.md` (Single Source of Truth):

- **GAC-1:** `scripts/ci/check_architecture_conformance.py` laeuft mit **0 Errors**
  (Exit 0, fail-closed) — `PYTHONPATH=src .venv\Scripts\python scripts/ci/check_architecture_conformance.py`.
- **GAC-2:** Die Architektur-Guardrails `guardrails/architecture-guardrails.md`
  (ARCH-NN) werden eingehalten; Konflikt = hart stoppen und melden.
