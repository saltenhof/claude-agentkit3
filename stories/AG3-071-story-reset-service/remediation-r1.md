# AG3-071 — Remediation R1 (Antwort auf review-r1.md)

Status der Vorlage: review-r1.md = OVERALL CHANGES-REQUESTED. Alle 5 Must-Fix,
beide blockierenden ERRORs aus Block 1/2/4 sowie die WARNINGs/NIT sind unten
einzeln aufgeloest. Geaendert wurden ausschliesslich `story.md` und `status.yaml`
dieser Story. Produktionscode/Tests/Konzepte/andere Stories: nicht angefasst.

Faktenbasis verifiziert am realen Code (anchors am Ist-Zustand geprueft):
- `projection_repositories.py` deckt ausschliesslich FK-69-Read-Model-/
  Projektionsfamilien ab (qa_stage_results/qa_findings/story_metrics/
  phase_state_projection/risk_window); `purge_run` ist dort der Read-Model-Purge.
- `phase_state_store/store.py` (Owner von `FlowExecution`/`NodeExecutionLedger`,
  `models.py:22-53`) hat **keine** Purge-/Delete-fuer-Story-Surface — der
  kanonische Runtime-Execution-Purge-Port existiert heute nicht.
- Locks: `LockRecordRepository.deactivate_locks_for_story` (`:184`), aggregiert
  ueber `Governance.deactivate_locks` (`runner.py:265`) — eigener, realer Owner.
- `StoryStatus` (`story_model.py:34-46`) hat kein `ESCALATED`/`RESETTING`/
  `RESET_FAILED`; `Cancelled` ist terminal (`service.py:91-94`).
- FK-91 (`91_api_event_katalog.md:311`) `story_cancelled_administratively`
  widerspricht FK-53 fuer den Reset-Pfad — bestaetigt.

---

## ERROR-1 (Block 1) — Runtime-Purge faelschlich ueber FK-69-`projection_repositories`
**Finding:** AG3-071 beanspruchte, Schritt 5/6 ueber `purge_run(...)` der
`projection_repositories` zu loesen; FK-53 trennt aber Runtime-State (§53.7.5)
hart von Read-Models/Analytics (§53.7.6).
**Resolution:** Ist-Zustand (§1) und Scope (§2.1.5) komplett umgebaut. Schritt 5
und Schritt 6 sind jetzt explizit getrennte Purge-Domaenen mit getrennten Ownern.
Schritt 5 (Runtime) nutzt `Governance.deactivate_locks` /
`LockRecordRepository.deactivate_locks_for_story` fuer Locks/Leases und einen
**getypten Runtime-Purge-Port** am `phase_state_store` fuer Execution/Governance/
kanonischen PhaseState — fail-closed, wenn der Port fehlt. `projection_repositories.
purge_run` ist ausdruecklich nur Schritt 6 (Read-Model-Anteil).

## ERROR-2 (Block 2) — AC5 testet falschen Owner fuer Runtime
**Finding:** AC5 verlangte, dass Schritt 5/6 die `purge_run`-Owner
(projection_repositories) konsumieren, obwohl diese nur FK-69 abdecken.
**Resolution:** AC5 in **AC5 (Runtime, §53.7.5)** und **AC5b (Read-Model/
Analytics, §53.7.6)** gesplittet. AC5 fordert jetzt Runtime-Purge-Ports +
Negativ-Assertion, dass Schritt 5 **nicht** ueber Read-Model-Repos purgt.
AC5b fordert die FK-69-`purge_run`-Owner **plus** AG3-081/AG3-082-Schnittstellen.

## ERROR-3 (Block 4) — falscher Anker-Claim „autoritativer Runtime-Purge-Owner"
**Finding:** `projection_repositories.py`-Anker existieren, aber die Aussage
„autoritativer Runtime-/Read-Model-Purge-Owner" ist falsch; echte Locks haben
`deactivate_locks_for_story`.
**Resolution:** Ist-Zustand-Claim korrigiert. Anker praezisiert auf die real
existierenden Zeilen (`:75/113/149/176/196` Read-Model; `:196` ist die
phase_state_**projection**, nicht der Runtime-Owner). Lock-Owner mit korrektem
file:line ergaenzt (`lock_record_repository.py:184`, `runner.py:265`). Falscher
Sammel-Anker `:202` und „autoritativ"-Behauptung entfernt.

## Must-Fix-1 (Purge-Owner-Modell) — siehe ERROR-1/ERROR-3. Erledigt.
## Must-Fix-2 (AC5 + Scope 2.1.5/2.1.7 splitten/testbar) — siehe ERROR-2.
Scope 2.1.5 in getrennte Schritt-5/Schritt-6-Bullets aufgeteilt; 2.1.7 auf die
Schritt-6-Owner (AG3-081/082) prazisiert. AC5/AC5b testbar formuliert
(Port-Aufruf-Assertion + Negativ-Assertion). Erledigt.

## Must-Fix-3 (AG3-081/082 Dependency-/Port-Strategie eindeutig) — WARNING Block 1
**Finding:** Reset-Purge-Kette laut Index aufgeteilt (AG3-081 Read-Model/`fc_*`,
AG3-082 `purge_story_analytics`); `status.yaml` haengt nur an AG3-032/035.
**Resolution:** **Beide** Strategien angewandt: (a) `status.yaml` `depends_on`
um **AG3-081** und **AG3-082** ergaenzt (harte Dependencies); (b) Scope/AC auf
getypte Outgoing-Ports + fail-closed „Owner-Schnittstelle fehlt" reduziert
(§2.1.7, AC5b, §6 Cross-Story). Damit ist die Story self-consistent, ohne einer
anderen Story Scope anzudichten, den sie nicht hat.

## Must-Fix-4 (`ESCALATED` als Vorbedingungsnachweis, nicht StoryStatus) — WARNING Block 3
**Finding:** `ESCALATED-Vorzustand -> RESETTING` vermischt Achsen; kein
`StoryStatus.ESCALATED`.
**Resolution:** Durchgaengig auf `StoryStatus.IN_PROGRESS -> RESETTING`
umgestellt (Quell-Konzepte, §1 Konflikt-Check Punkt 2, §2.1.4, AC3). Eskalation
wird als **Befund aus Runtime-/Audit-Artefakten** nachgewiesen; kein
`StoryStatus.ESCALATED` eingefuehrt. AC3 Negativtest entsprechend gefasst.

## Must-Fix-5 (FK-91-`Cancelled`-Konflikt routen/ausschliessen) — WARNING Block 4
**Finding:** FK-91 `story_cancelled_administratively` setzt Reset auf `Cancelled`,
widerspricht FK-53.
**Resolution:** Als Konzept-Drift sichtbar gemacht (§1 Konflikt-Check Punkt 1),
**im Code aktiv ausgeschlossen** (AC10: Reset emittiert/setzt kein `Cancelled`),
und der doc-only-Nachzug an den FK-91-Owner **AG3-103** geroutet (§2.2 + §6).
AG3-103 ist laut `_STORY_INDEX.md:144` der Owner fuer interne FK-Widersprueche
inkl. FK-91 — kein neuer Scope erfunden.

## WARNING (Block 2) — AC11 „vier Konzept-Gates" ungenau
**Resolution:** AC11 nennt jetzt die exakten Scriptnamen:
`check_concept_frontmatter.py`, `compile_formal_specs.py`,
`check_concept_code_contracts.py`, `check_architecture_conformance.py`
(alle real unter `scripts/ci/` verifiziert).

## NIT (Block 3) — AC1 „exakt vier" enger als FK-53 „mindestens"
**Resolution:** AC1 + Scope 2.1.1 + Quell-Konzept-Zeile auf „public API umfasst
mindestens diese vier; interne Schritte/Ports erlaubt" prazisiert.

## Anchor-Korrekturen (file:line auf Ist-Zustand)
- `service.py:80-93` -> praeziser `_ALLOWED_TRANSITIONS` `:80`, `_TERMINAL_STATUSES`
  `:91-94`, `_check_transition` `:97`.
- Lock-Owner ergaenzt: `lock_record_repository.py:184`, `runner.py:265`.
- Runtime-Owner-Luecke belegt: `phase_state_store/store.py` (keine Purge-Surface),
  `phase_state_store/models.py:22-53`.
- FK-91-Drift: `91_api_event_katalog.md:311`.

---

## Genuine Cross-Story-Voraussetzungen (an den Auftraggeber gespiegelt)
1. **AG3-081** (hart, Schritt 6 Read-Model/`fc_*`-Purge-Kette) — neu in
   `status.yaml`.
2. **AG3-082** (hart, Schritt 6 `purge_story_analytics`/Recompute) — neu in
   `status.yaml`.
3. **Runtime-Execution-Purge-Port** am `phase_state_store`-Owner
   (`FlowExecution`/`NodeExecution`/Attempt/Override/GuardDecision/kanonischer
   PhaseState fuer Schritt 5): existiert heute **nicht** als Purge-Surface und
   wird von **keiner** Story im `_STORY_INDEX.md` explizit geliefert (AG3-081/082
   decken nur Read-Model/Analytics ab, **nicht** kanonischen Runtime-State).
   **Offene Frage an den Auftraggeber:** eigener Owner-/Story-Schnitt fuer diese
   Runtime-Purge-Surface noetig. AG3-071 behandelt sie fail-closed (meldet das
   Fehlen, baut kein Roh-DELETE) — das ist ein WARNING-Handlungsauftrag, kein
   stilles Ueberbruecken.
4. **AG3-103** (doc-only) — FK-91-`story_cancelled_administratively`-Widerspruch
   zu FK-53 als Konzept-Nachzug.

## Geaenderte Dateien (nur AG3-071)
- `stories/AG3-071-story-reset-service/story.md` (vollstaendig ueberarbeitet,
  AG3-057-Template-Struktur beibehalten; ARCH-55-konform).
- `stories/AG3-071-story-reset-service/status.yaml` (`depends_on` +AG3-081/+AG3-082).
- `stories/AG3-071-story-reset-service/remediation-r1.md` (diese Datei).
