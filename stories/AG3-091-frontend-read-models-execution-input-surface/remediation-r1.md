# AG3-091 — Remediation R1 (post hostile Codex review)

Scope of this remediation: `story.md` only (and a status.yaml audit — no change required).
No production code, tests, concept files, or other stories' files were touched.
All finding evidence was re-verified against the real code, the FK/§ sources, the
formal spec, the prototype, and the story index before rewriting.

---

## 1) Konzept-Vollstaendigkeit

### ERROR — `execution-input/limits` fehlte im Scope/ACs (must-fix #1)
- **Verified:** `_STORY_INDEX.md:116` weist AG3-091 `/execution-input/snapshot|next|limits` zu; FK-91 katalogisiert `GET /v1/projects/{project_key}/execution-input/limits` (`91_api_event_katalog.md:134`); formale Entitaet `frontend-contracts.entity.execution_limits` existiert (`entities.md:728-753`).
- **Resolution:** In-Story aufgenommen. Neuer Scope-Punkt 2 (`GET .../execution-input/limits` -> `ExecutionLimits`, read-only, sechs Caps als non-negative Integer). Neue AC5 (Wire-Shape, 404, read-only). Der korrespondierende `PUT` bleibt explizit Out-of-Scope (Command `update_execution_limits`), konsistent mit dem bestehenden Mutations-Cut.

### ERROR — Mode-Lock-Zielbild kollidiert mit Formal-Spec/Code (must-fix #2)
- **Verified:** Formal-Spec `frontend-contracts.entity.project_mode_lock` = `{project_key, mode ∈ {standard, fast, idle}}`, **kein** `holder_count` (`entities.md:93-110`); Invariant `mode_lock_derived` = story-derived (`invariants.md:108-122`). Realer Code bildet das exakt ab: `views.py:44-56` (`ProjectModeLock`), `service.py:124-153` (`derive_mode_lock`). Das kanonische Persistenz-Objekt `project_mode_lock` mit `active_mode`/`holder_count` (`mode_lock_repository.py:61-77`, `:199-213`) ist der **Control-Plane-Mutex** (Acquire/Release), ein anderer Belang.
- **Resolution:** Die frühere Forderung (`null/standard/fast + holder_count` + "Formal-Spec-/Code-Migration auf canonical `project_mode_lock`") war **falsch** — sie haette die Read-Model-Wire-Shape gegen die Formal-Spec gebrochen und zwei Belange vermischt. Story korrigiert auf die formale Wire-Shape `{project_key, mode}`, story-derived ueber `derive_mode_lock`. Die Abgrenzung Read-Model vs. Control-Plane-Mutex ist in §1, Scope 3, AC6 und §5 explizit gemacht. **Keine** Persistenz-Migration im Cut. (Der Review-Fix-Vorschlag selbst war contra-konzeptionell; die korrekte Aufloesung folgt Formal-Spec + ARCH-55, nicht dem woertlichen Review-Wortlaut.)

### ERROR — Feldnamen nicht vertragsklar (must-fix #3)
- **Verified:** Formal-Spec nutzt snake_case `eligible_ready`/`total_ready`/`global_slots_left` (`entities.md:685`/`:694`/`:699`); Prototyp nutzt CamelCase (UI).
- **Resolution:** Wire-Contract eindeutig auf snake_case (formale Feldnamen) festgelegt; Prototyp-CamelCase explizit als UI-seitig markiert (Scope 1, AC1/AC3, §5 ARCH-55). Story durchgaengig auf snake_case-Wire-Felder umgestellt.

## 2) AC-Schaerfe

### ERROR — Scope-Punkte 3+4 ohne AC-Abdeckung (must-fix #4)
- **Verified:** Planning-Angleichung und Project-Config waren Scope ohne AC. Realer Planning-Router: `routes.py:39-52` (`dependency-graph`/`dependencies`/`next-ready`/`config`, **kein** `ready-set`/`execution-plan`). FK-73 §73.3 (`73_project_management.md:67-80`) katalogisiert **keinen** separaten Config-Read-Endpunkt.
- **Resolution:** Scope 4 (Planning) auf realen Ist-Zustand korrigiert (Abgrenzung statt Anlage neuer Routen) + neue AC10 (keine Triage-Doppelung, Detail-Routen unveraendert). Scope 5 (Project-Config) korrigiert: **kein** neuer Config-Read-Endpunkt; nur `project_key`-Autoritaet aus `Project.key` (FK-73 §73.5) + 404 fail-closed; neue AC11 deckt `project_key`-Autoritaet/404 ab.

### ERROR — `execution-input/next` ohne formale Entity (must-fix #4 / Vertrag)
- **Verified:** `formal.frontend-contracts.entities` enthaelt nur `execution_input_snapshot`/`execution_input_stack`/`execution_limits` (`entities.md:669-753`) — **keine** `execution_input_next`/Reason-Entitaet. FK-72 §72.14.3 verlangt Entity/Command je Endpoint.
- **Resolution:** Da AG3-091 die Formal-Spec **nicht** anfassen darf und AG3-100 laut `_STORY_INDEX.md:136` Owner der snapshot/next-Surface ist, ist die formale Reason-Entitaet als **Cross-Story-Voraussetzung an AG3-100** geroutet (§6 + Out-of-Scope). AG3-091 bindet `next` formal an die bestehende `story_summary`/Snapshot-Entitaet (erste Karte des Pick-Ergebnisses), baut die Reason-Felder typisiert (Pydantic) und meldet die Luecke — kein Endpunkt ohne formale Bindung, keine stille Formal-Spec-Aenderung (AC12).

## 3) Klarheit

### ERROR — Mode-Lock-Anweisung widerspruechlich
- **Verified:** Prototyp `selectActiveProjectMode` (`storySelectors.ts:280-286`) ist eindeutig story-derived (`Mode | null`, kein `holder_count`). Die frühere "Mode-Lock-Semantik 1:1 aus dem Selektor" + gleichzeitig "`holder_count` aus Control-Plane" war in sich widerspruechlich.
- **Resolution:** §6-Hinweis korrigiert: Prototyp-Mode-Lock nur als **UI-Zustandsbild**; fachliche Quelle ist die kanonische story-derived Ableitung (`service.derive_mode_lock`, FK-24 §24.3.3 / `invariant.mode_lock_derived`). Keine Bindung an `mode_lock_repository`, kein `holder_count`.

### WARNING — `key`/`project_key` inkonsistent
- **Verified:** Frühere Story mischte `{project_key}` und `{key}`. FK-91 nutzt `{project_key}`.
- **Resolution:** Durchgaengig `{project_key}` in allen Pfaden und ACs. **Spiegelung an den Auftraggeber (Severity-Semantik):** der Warning ist aktiv adressiert und vollstaendig behoben, kein aufschiebendes Restrisiko.

## 4) Kontext-Sinnhaftigkeit

### ERROR — Ist-Zustand "Backend-Read-Model fehlt" falsch fuer Counters/Mode-Lock
- **Verified:** `GET /v1/projects/{project_key}` liefert bereits `mode_lock` + `story_counters` (route `routes.py:162-174`, Aggregation `service.py:109-117`, Modelle `views.py:44-95`).
- **Resolution:** §1 umformuliert: das story-derived Aggregat **existiert** und ist Single Source of Truth; AG3-091 liefert die fehlenden **Standalone-Endpunkte**, die dieses Aggregat **wiederverwenden/lesen**, statt einer zweiten Logik (Scope 3, AC6/AC7, §6 Wiederverwendungs-Hinweis mit `service.py:124-153`/`:156-217`).

### ERROR — Planning-Baseline passt nicht zum Code
- **Verified:** Reale Routen sind projekt-skopiert `next-ready`/`dependency-graph`/`dependencies`/`config` (`routes.py:39-52`); `ready-set`/`execution-plan` sind nur FK-70-§70.8a.5-Prosa (`70_...:733`), als Endpunkte nicht vorhanden.
- **Resolution:** §1 + Scope 4 auf realen Ist-Zustand korrigiert; klar gesagt, dass AG3-091 **keine** neuen `ready-set`/`execution-plan`-Routen anlegt, sondern nur die Execution-Input-Teilmenge gegen die bestehenden Detail-Routen abgrenzt. Optionaler FK-Prosa-Nachzug als doc-only-Cross-Story-Voraussetzung markiert.

---

## status.yaml — Audit
Geprueft: `depends_on: [AG3-090, AG3-098]` deckt sich mit `_STORY_INDEX.md:116`. `status: draft` / `phase: review_pending` sind korrekt fuer eine noch nicht freigegebene/gemergte Story. **Kein Feld geaendert** (kein Feld war fachlich falsch).

## Template-Treue
AG3-057-Template-Struktur erhalten: Titel/Meta/Quell-Konzepte -> §1 Kontext/Ist-Zustand (belegt) -> §2 Scope (2.1/2.2 mit Owner) -> §3 Akzeptanzkriterien -> §4 DoD -> §5 Guardrail-Referenzen -> §6 Hinweise + Cross-Story-Voraussetzungen.

## Genuine cross-story prerequisites (an andere Owner geroutet)
1. **Formale Reason-Entitaet `execution_input_next`** fuer den Agent-Pull-Endpoint — Owner **AG3-100** (`_STORY_INDEX.md:136`, lebende snapshot/next-Surface; FK-72 §72.14.3). AG3-091 darf die Formal-Spec nicht selbst aendern.
2. **Doc-only FK-70 §70.8a.5-Nachzug** — Prosa-Pfade `ready-set`/`execution-plan` an die realen projekt-skopierten Route-Namen angleichen (Welle-10-Klasse, ausserhalb des AG3-091-Code-Cuts).
