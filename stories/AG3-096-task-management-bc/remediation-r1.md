# AG3-096 — Remediation r1 (nach giftiger Codex-Review)

**Datum:** 2026-06-07
**Geaenderte Dateien:** `story.md` (komplett ueberarbeitet). `status.yaml` unveraendert (kein Feld faktisch falsch). `remediation-r1.md` (dieser Bericht).
**Quellen geprueft:** FK-77 (`concept/technical-design/77_task_management.md`), `formal.task-management.entities/commands/events`, realer Code `src/agentkit/telemetry/projection_accessor.py` + `errors.py`, State-Backend (`postgres_schema.sql`, `sqlite_store.py`), `_STORY_INDEX.md`.

---

## Konzept-Vollstaendigkeit

### ERROR — Falsche Link-Ziele (`Stories/Artefakte` statt `task|story`)
**Befund:** Story modellierte `Task <-> Stories/Artefakte`. FK-77 §77.1 / entities.md:100 definieren `target_kind ∈ {task, story}` (inkl. Task-zu-Task), keine Artefakte.
**Resolution:** Artefakt-Links vollstaendig entfernt. Scope 2.1#1, AK1/AK2, Hinweise §6 stellen jetzt auf `target_kind ∈ {task, story}` um, inkl. Task-zu-Task und der `kind`-Beziehung `relates_to | spawned_story | duplicate_of`. AK2 fordert Validierung des Ziels (Task: Existenz + gleicher `project_key`; Story: Existenz) und nennt Artefakte explizit als ungueltiges Linkziel.

### ERROR — Top-Surface unvollstaendig
**Befund:** Story nannte nur `create_task`/`link_task`/`resolve_task`. FK-77 §77.7 fordert schreibend zusaetzlich `unlink_task`, `dismiss_task` und lesend `get_task`, `list_tasks`, `list_tasks_for_target`.
**Resolution:** Scope 2.1#4 listet jetzt alle acht Methoden mit Vor-/Nachbedingungen (allowed_from gem. commands.md). AK6 verlangt Positiv-/Negativpfad **je Methode**. §6-Belegliste fordert Test-Namen fuer Surface-Vollstaendigkeit aller acht.

### ERROR — Entity-Scope nicht FK-77-vollstaendig (`owner`/`note` erfunden)
**Befund:** Story beschrieb `id`, `title/description`, `owner/note`. formal entities.md:34 fordert `task_id`, `kind`, `type`, `title`, `body`, `priority`, `status`, `origin`, `source_story_id?`, `execution_report_ref?`, `created_at`, `resolved_at?`, `resolved_by?`.
**Resolution:** Scope 2.1#1 und AK1 listen jetzt **exakt** das formal-spec-Feldset (englisch) fuer `Task` und `TaskLink` inkl. Identitaeten. `owner`/`note` entfernt; AK1 verlangt Reject undefinierter Zusatzfelder; §6 weist explizit „keine erfundenen Felder" an.

### WARNING — Formal command/event semantics fehlen
**Befund:** FK-77 bindet `formal.task-management.*`; commands.md/events.md definieren Events.
**Resolution (in der Story geklaert, nicht stillgelegt):** Commands sind jetzt vollstaendig abgebildet (AK6). Events sind **autoritativ ausgeschlossen** mit Begruendung: FK-77 §77.7 ("Abgrenzung API vs. Events") stellt die Events **selbst** zurueck, bis ein konkreter Konsument modelliert ist — Owner **FK-91**/frontend-contracts (Welle 7). Das ist in Scope 2.2 (Out of Scope) mit Owner verankert; kein offener Konzept-Widerspruch, kein „spaeter"-Stub.

## AC-Schaerfe

### ERROR — AC1 fachlich falsch testbar (Stories+Artefakte)
**Resolution:** AC1 prueft jetzt das exakte Feldset; AC2 (neu fokussiert) prueft `target_kind ∈ {task, story}` plus Ziel-Existenz und gleichen `project_key` bei Task-Ziel — exakt wie vom Review gefordert.

### ERROR — AC5 testet nicht die volle Surface
**Resolution:** Frueheres AC5 ist jetzt AK6 und deckt alle acht Surface-Methoden mit Positiv-/Negativpfad ab, inkl. expliziter `resolve_task`(done)/`dismiss_task`(dismissed)-Trennung und beidseitiger n:m-Abfrage.

### PASS — No-pipeline-boundary als AC testbar
Unveraendert beibehalten (jetzt AK7), zusaetzlich mit FK-77 §77.6-Anker und Strukturpruefung verbotener Imports.

## Klarheit/Eindeutigkeit

### ERROR — `resolve_task (-> done/dismissed)` widerspruechlich
**Befund:** commands.md:57 trennt `resolve_task` (done) und `dismiss_task` (dismissed).
**Resolution:** Ueberall getrennt: Scope 2.1#4 und AK6 definieren `resolve_task` ausschliesslich `open->done` und `dismiss_task` ausschliesslich `open->dismissed`; der vermischte „-> done/dismissed"-Pfad ist eliminiert.

### ERROR — Falsche Abschnittsreferenzen (§77.5/§77.6)
**Befund:** Story sagte State-Machine `§77.5`, Tabellen `§77.6`. Real: Lifecycle §77.2, Speicher §77.5, Abgrenzung §77.6.
**Resolution:** Alle Anker korrigiert — Datenmodell §77.1, Lifecycle §77.2, Verlinkung §77.3, Speicher §77.5, Abgrenzung §77.6, Surface §77.7. Header-Quellkonzepte und alle Inline-Verweise angeglichen.

## Kontext-Sinnhaftigkeit

### ERROR — ProjectionKind-Erweiterung kollidiert mit Ist-Code
**Befund:** `ProjectionKind` ist FK-69-streng auf exakt 7 Tabellen begrenzt (projection_accessor.py:56-71); Story forderte naiv einen dedizierten ProjectionKind.
**Resolution:** Neuer BLOCKING-Abschnitt in §1 und **AK8** schreiben die Entscheidung **vor** der Implementierung fest. Zwei zulaessige Auswege benannt: (a) dedizierter Task-Persistenz-Port analog `ProjectionAccessor.record_fc_incident` (projection_accessor.py:313) — **Default**, FK-77 §77.5-Prosa wird dann doc-only praezisiert; (b) FK-69-`ProjectionKind`-Erweiterung — Owner **AG3-081** (FK-69 §69.3/§69.9/§69.14), dann dokumentierte Abhaengigkeit. AK8 verbietet explizit das stille Aufweiten des 7-Werte-Enums. Out of Scope 2.2 routet (b) an AG3-081.

### WARNING — `Telemetry.write_projection` existiert nicht
**Befund:** Reale Surface ist `ProjectionAccessor.write_projection`/`read_projection` (projection_accessor.py:249/:329); eine Klasse `Telemetry` existiert nicht (per Grep verifiziert).
**Resolution:** §1, Scope und §6 nennen jetzt die reale Code-Klasse `ProjectionAccessor` mit Datei:Zeile und vermerken, dass FK-77 §77.5 ("Telemetry...") nur Prosa ist; kein Import einer nicht existenten Klasse.

### NIT — Ist-Zustand „repo-weite Null-Treffer" unpraezise
**Befund:** Stories/var enthalten Treffer.
**Resolution:** §1 schraenkt die Null-Treffer-Aussage explizit auf `src/agentkit` (produktiver Code + State-Backend) ein und belegt das Fehlen von `tm_tasks`/`tm_task_links` in `postgres_schema.sql`/`sqlite_store.py`.

---

## Falsche Code-Anker korrigiert
- „`Telemetry.write/read_projection`" -> `ProjectionAccessor.write_projection` `telemetry/projection_accessor.py:249` / `read_projection` `:329`.
- ProjectionKind-7-Tabellen-Constraint belegt: `projection_accessor.py:56-71`.
- fc_incidents-Sonderpfad als Port-Vorbild: `ProjectionAccessor.record_fc_incident` `projection_accessor.py:313`.
- Ownership-Strenge: `telemetry/errors.py` (`ProjectionRecordTypeMismatchError`, `ProjectionKindNotAccessorOwnedError`).
- Schema-Dateien: `state_backend/postgres_schema.sql`, `state_backend/sqlite_store.py` (Existenz verifiziert).

## Scope-Treue (`_STORY_INDEX.md`)
Innerhalb des AG3-096-Cuts geblieben (BC `task_management`: Entitaeten/Tabellen/Top-Surface, n:m, State-Machine). Keine Scope-Ausweitung: UI -> AG3-105; Producer-Verdrahtung -> FK-29/38; Events -> FK-91; FK-69-Enum-Erweiterung (nur falls Ausweg b) -> AG3-081. Alle als Out-of-Scope mit Owner verankert.

## ARCH-55
Alle Identifier/Tabellen/Spalten/Wire-Keys/Enum-Werte englisch (`tm_tasks`, `tm_task_links`, `create_task`..`list_tasks_for_target`, `target_kind=task|story`, `relates_to|spawned_story|duplicate_of`, Status/kind/priority/origin als StrEnum). Fach-Prosa bleibt deutsch (zulaessig).

## status.yaml
Geprueft — kein Feld faktisch falsch: `depends_on: [AG3-035, AG3-040]` deckt den Default-Pfad (a) ab (ProjectionAccessor-Ownership stammt aus AG3-035). Die AG3-081-Abhaengigkeit ist **konditional** (nur bei Ausweg b) und in der Story dokumentiert, daher nicht als harte `depends_on`-Kante gesetzt. `status: draft`, `phase: review_pending` bleiben korrekt (Story wird nur autorisiert/reviewt). Keine Aenderung vorgenommen.
