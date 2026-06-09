# AG3-096 — Remediation r2 (nach Review-r2)

**Datum:** 2026-06-08
**Geaenderte Dateien:** `story.md` (Read-Surface tenant-scoped). `status.yaml` unveraendert (kein Feld faktisch falsch). `remediation-r2.md` (dieser Bericht).
**Quellen geprueft:** `review-r2.md`, FK-77 §77.1/§77.7 (`concept/technical-design/77_task_management.md:48,61,127-142`), `formal.task-management.entities` (`identity: [project_key, task_id]`, Zeile 28 / `task_link` identity Zeile 88), `formal.task-management.invariants` (`link_target_valid`, Zeile 53-58), Mandantenregel (`concept/technical-design/02_domaenenmodell_zustaende_artefakte.md:164`, Abschnitt §2.2.1 ab Zeile 58), `_STORY_INDEX.md`.

---

## Remaining Must-Fix ERROR

### ERROR — Read-Surface nicht tenant-sicher spezifiziert
**Befund (Review-r2):** Story pinnte `get_task(task_id)` und `list_tasks_for_target(target_kind, target_id)` ohne `project_key`. Das kollidiert mit der Task-Identitaet `(project_key, task_id)` und der Mandantenregel (`story_id`/`task_id` allein nicht systemweit ausreichend).

**Autoritative Grundlage (geprueft, nicht geraten):**
- `formal.task-management.entities`: `task` `identity: [project_key, task_id]` (Zeile 28); `task_link` `identity: [project_key, task_id, target_kind, target_id, kind]` (Zeile 88).
- `formal.task-management.invariants.link_target_valid` (Zeile 53-58): Ziel-Task liegt im selben `project_key`.
- FK-77 §77.1 (Zeile 48): `task_id` „eindeutig pro `project_key`", `project_key` tenant-scoped (Zeile 49).
- Mandantenregel `02_domaenenmodell_zustaende_artefakte.md:164` (§2.2.1): `story_id` ist kein systemweit ausreichender Schluessel; kanonische Records immer mindestens `(project_key, ...)`.

**Resolution (Fix-Variante: Read-Methoden explizit `project_key`-scoped, in-story):**
- **Scope 2.1#4 (Lesend):** auf `get_task(project_key, task_id)`, `list_tasks(project_key, ...)`, `list_tasks_for_target(project_key, target_kind, target_id)` umgestellt; expliziter Tenant-Scope-Absatz mit Verweis auf die formal-spec-Identitaet und die Mandantenregel.
- **AK6:** Read-Methoden mit `project_key` signiert; neue testbare Tenant-Scope-Bedingung verankert — gleiche `task_id` unter zwei verschiedenen `project_key` muss bei `get_task` und `list_tasks_for_target` strikt partitioniert aufloesen (kein Cross-Tenant-Leak).
- **Scope 2.1#6 (Tests):** Test „Tenant-Scope der Read-Surface" in die Belegliste aufgenommen.
- **§6 Hinweise:** neuer Punkt — Read-Surface verbindlich `project_key`-scoped bauen; keine ungescopeten Read-Methoden.

**Warum in-story und nicht an anderen Owner geroutet:** Die Top-Surface ist Kern des AG3-096-Cuts (`_STORY_INDEX.md`: BC `task_management` Entitaeten/Tabellen/Top-Surface). Die Korrektur ist eine reine Praezisierung der bereits autoritativ in der formal-spec festgelegten Identitaet `(project_key, task_id)` — kein Scope-Zuwachs, keine fremde Story noetig.

**Warum keine Konzept-Datei angefasst:** Review-r2 bot als Alternative „ambient project context in Story/FK-77 festschreiben". Das haette eine Aenderung an FK-77 (Konzept-Datei) bedingt, die in diesem Auftrag ausgeschlossen ist. Die gewaehlte Variante (Read-Methoden explizit `project_key`-scoped) ist vollstaendig durch die bestehende formal-spec gedeckt und macht die Story self-consistent, ohne FK-77 zu editieren. FK-77 §77.7 traegt die ungescopeten Prosa-Signaturen als bekannte Prosa-Luecke; die Story praezisiert das genauso, wie sie bereits §77.5 (`Telemetry` -> realer `ProjectionAccessor`) praezisiert — autoritativ aus der formalen Quelle, kein zweiter Lesepfad.

---

## Per-Dimension-Verdikte aus Review-r2 (zur Bestaetigung)
- Konzept-Vollstaendigkeit: PASS (unveraendert) — R1-ERRORs bleiben resolved.
- AC-Schaerfe: war FAIL wegen Read-Surface; mit AK6-Tenant-Scope jetzt adressiert.
- Klarheit/Eindeutigkeit: PASS (unveraendert).
- Kontext-Sinnhaftigkeit: PASS (unveraendert) — Freestyle/No-Pipeline-Grenze unangetastet; keine Phasen/Gates/Worktrees/`PipelineEngine`-Kopplung hinzugefuegt.

## Korrigierte Anker
- Tenant-Scope-Begruendung verweist auf `formal.task-management.entities` `identity: [project_key, task_id]` und `02_domaenenmodell_zustaende_artefakte.md` §2.2.1 (Mandantenregel, Zeile 164). Beide gegen die realen Dateien verifiziert.

## Scope-Treue (`_STORY_INDEX.md`)
Innerhalb des AG3-096-Cuts geblieben. Keine Ausweitung; UI -> AG3-105, Producer -> FK-29/38, Events -> FK-91, ggf. FK-69-Enum -> AG3-081 bleiben als Out-of-Scope mit Owner verankert.

## ARCH-55
Alle neuen/geaenderten Identifier englisch (`get_task`, `list_tasks_for_target`, `project_key`, `target_kind`). Fach-Prosa bleibt deutsch (zulaessig).

## status.yaml
Geprueft — kein Feld faktisch falsch. `depends_on: [AG3-035, AG3-040]`, `status: draft`, `phase: review_pending` bleiben korrekt. Keine Aenderung.
