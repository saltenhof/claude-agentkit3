# AG3-149 — Disown-Building-Block: eingefrorenes Implementierungs-Design

Stand: 2026-07-10. Basis: HEAD `main@3976dc21` (nach AG3-148-Modellfix).
Status: **eingefroren** nach Feasibility-Scoping + Fable-Design-Urteil
(Component-Architecture-Skill). Keine Konzeptaenderung — die Rulings
*bestaetigen/interpretieren* die bestehenden Konzepte (FK-56 §56.7a/§56.13c-h,
FK-55 §55.8.3/8.4, FK-53 §53.7.3/7.3a, FK-58 §58.6, FK-17 §17.7a). Verbindlicher
Kontrakt fuer die AG3-149-Implementierung. Ergaenzt den Feasibility-11-Schritt-
Slice (siehe Task-Notiz) mit den drei geklaerten Design-Punkten.

## D1 — Revoke-with-reason fuer ALLE vier Pfade; physisches Delete/Purge der Bindung ist konzept-FALSCH

Der Disown-Block standardisiert alle vier Entzugspfade auf
`BindingStatus.REVOKED` + per-Pfad-`BindingRevocationReason`
(`ownership_transferred` / `story_ended` / `story_reset` / `story_split`).
Kein Pfad loescht die Binding-Row als Disown-Akt.

Begruendung (Konzept loest die FK-17-Spannung selbst):
- FK-53 §53.7.3: die aktive Session-Bindung wird beim Reset **entwertet**
  (revoked), nicht geloescht; §53.7.3a mandatiert den Disown-Block mit
  deterministischer Reconcile-Antwort **fuer Reset**. Eine geloeschte Row
  liefert diese Antwort nicht — `projectedge/runtime.py:200-209` faellt ohne
  Session auf `ai_augmented` (der stille Pfad, den 149 tilgt); nur der
  `status=="revoked"`-Zweig (`:211-224`) erzeugt `binding_invalid` + Grund.
- FK-17 §17.7a: „**aktive** SessionRunBinding" — *aktive* ist load-bearing.
  ACTIVE→REVOKED nimmt die Bindung aus der aktiven Domaene; die revoked-Row ist
  Audit-Fakt, analog zum Ownership-Record (`nicht entfernt, sondern status=reset`).
  Admission ist ausschliesslich active-record-basiert
  (`historical_ownership_records_are_never_admission_evidence`) — eine
  revoked-Row admittiert nicht und blockiert nicht (AC4-Positivtest).
- FK-58 §58.6: Exit faellt „erst danach kontrolliert auf `ai_augmented`" —
  kontrollierter Fallback *nach* der Notification, nie via Row-Absenz. Das
  heutige Hard-Delete (`story_exit/service.py:568-576`, `BindingDeleteScope`)
  widerspricht dem.

Mechanik:
- `BindingRevocationReason` (`control_plane/ownership.py:100-110`) um
  `STORY_ENDED="story_ended"`, `STORY_RESET="story_reset"`,
  `STORY_SPLIT="story_split"` erweitern (Docstring antizipiert das; Spalte offen
  TEXT `postgres_schema.sql:203` — kein Schema-Delta). Reason-Namen = Wire-Keys
  (ARCH-55), an die Record-Status `ended/reset/split` ausgerichtet.
- Reset: den physischen Binding-Delete (`delete_session_run_binding_global`,
  `_runtime_rows.py:676-686`, via `repository.py:204`) fuer die aktive Bindung
  aus dem Reset-Pfad entfernen; stattdessen Disown-Block-Aufruf **vor** den
  Purge-Schritten (FK-53-Ordnung: §53.7.3 quiesce/disown vor §53.7.5 purge —
  passt zu `story_reset/service.py:504-510` deactivate_locks vor purge_run :516).
- „Reset-Purge-Domaene" fuer die Bindung = die ACTIVE→REVOKED-Transition mit
  Grund `story_reset` (+ Lock-Deaktivierung + Edge-Tombstone).

## D2 — Kein neuer gespeicherter Enforcement-Flag; abgeleitetes Praedikat; Ping-Pong aus Transfer-Record+Challenge

### (a) Disenfranchisement (Item 8)
Signal ist ein **abgeleitetes Praedikat** ueber dem bestehenden Ownership-Modell
— kein gespeicherter disowned-Flag, keine Freeze-Row (waere zweite operative
Wahrheit → FIX-THE-MODEL-Verstoss; ist zudem **kein** Story-Freeze, FK-55 §55.8.3).
Es loest sich von selbst, wenn die Records sich ueber offizielle Pfade aendern.
Zwei autoritative Quellen je Trust-Boundary (beide existieren, blockieren schon):
- Hook/Edge: revoked-Bindung → `binding_invalid` (`projectedge/runtime.py:211-224`)
  → Mode ≠ `story_execution` → Story-Mutations-Guards feuern.
- Backend-HTTP: Ownership-Fence auf `owner_session_id`/`ownership_epoch` in
  jedem Regime-Mutations-Commit inkl. complete/fail/closure (FK-56 §56.8a).

Item 8 fuegt nur eine **benannte Capability-Regel** hinzu (Disowned-Overlay
analog `ConflictFreezeOverlay`, konsultiert wo heute `self._freeze.apply(...)`
`enforcement.py:366` / `is_frozen` `:424`), abgeleitet aus dem aufgeloesten
Binding-Revocation-Grund, damit der DENY Rule-Id + Klartext-Grund + Neu-Owner-Ref
traegt (AC9). **Speichert nichts.** `SESSION_DISOWNED`-Events
(`runtime/_ownership_transfer.py:576-581`) sind Telemetrie, **nie** Enforcement-
Evidenz.

### (b) Ping-Pong-Schranke (Item 7)
Autoritative Quelle = `takeover_transfer_records` am aktuellen `ownership_epoch`
des aktiven Records, join via `challenge_ref` → `takeover_challenges.owner_session_id`
(die beim Transfer *in* diese Epoch entzogene Identitaet). Durabel, story-skopiert,
epoch-indiziert, bereits Challenge-Bestandteil (FK-56 §56.13d). **Nicht** die
revoked-Bindung (PK `session_id`, ueberschreibbar — untauglich als Historie).

Deterministische, epoch-skopierte Bedeutung von „unmittelbar/kurz darauf"
(keine Wanduhr, FK-55 §55.8.3 „nie durch Zeitablauf"):
- Prong 1 (`disowned_session_cannot_immediately_reclaim`, hartes 403): solange
  der aktive Record auf der per Transfer erzeugten Epoch steht, kann die von
  *diesem* Transfer entzogene Session nicht Confirm-Beguenstigte sein — ausser
  Principal `human_cli`/`admin_service` + Begruendung. Loest sich nur ueber
  offizielle Pfade (weiterer Transfer / Run-Ende / Reset).
- Prong 2 (Wieder-Transfer „kurz darauf"): weiterer Transfer derselben Story,
  waehrend die aktuelle Epoch `acquired_via=takeover` ist (bzw. ein
  Transfer-Record der aktuellen Epoch existiert), erfordert privilegierten
  Principal + Begruendung — geprueft bei Request UND Confirm.

Enforcement-Loci: `DISOWNED_SESSION_CANNOT_IMMEDIATELY_RECLAIM` (+ repeat-transfer-
privilege-Failure) zu `TakeoverConfirmFailure`; Auswertung im A-Kern
`evaluate_takeover_confirm` (`ownership_transfer.py:32-43,237-261`) aus **neuen
expliziten Inputs** (entzogene Identitaet der aktuellen Epoch, Beguenstigten-
Session, Principal-Privileg), die die Runtime aus obiger Quelle liefert →
Mapping auf das bereits gepinnte deterministische 403 (`forbidden`,
`formal.frontend-contracts.commands`). Capability-Schicht benennt **dasselbe
Praedikat** als Regel (AC8: Durchsetzung in der Capability-Schicht, nicht nur im
Handler). **Praedikat-Funktion einmal definieren (A-Kern), beide Konsumenten
rufen sie** — zwei Enforcement-Punkte, eine Wahrheit.

## D3 — Reconcile-Antwort rein ueber revoked-Grund-Vokabel; kein neues Wire-DTO

FK-56 §56.7a: `binding_invalid` traegt den Grund als **Attribut**, kein eigener
Status pro Ursache. Carrier existiert end-to-end: `revocation_reason` auf der
Binding-Row → Bundle `session.json` → `ResolvedEdgeState.block_reason`
(`projectedge/runtime.py:219-224`). Einheitlich ueber alle vier Pfade
(FK-56 §56.13h). HTTP-seitige Variante (disowned Session mutiert) nutzt denselben
Grund-String in der Fence-Rejection.

Contract-Test-Pins:
1. geschlossene 4-Wert-Grund-Vokabel als exakte Wire-Strings (Enum-Werte = Keys).
2. AC1-Einheitlichkeit: je Pfad (ueber den ECHTEN Vorgaengerpfad erzeugt,
   nicht fabriziert) identische Disown-Ausgabe (Audit-Event mit Grund, Binding
   `status=revoked`+Grund, `tombstone_worktree_roots` im Bundle, Record-Status-
   Transition).
3. Edge-Resolve: jeder der vier Gruende → `operating_mode="binding_invalid"` +
   `block_reason=<grund>`, nie `ai_augmented`.
4. Fail-closed: unbekannter/fehlender Grund → weiterhin `binding_invalid` mit
   generischem `session_binding_mismatch`, nie „not revoked".
5. Fence-Parity: Backend-Mutations-Rejection einer disowned Session traegt
   denselben maschinenlesbaren Grundwert wie die Edge-Reconcile-Antwort.

## Component-Architecture

- `control_plane/disown.py` (Blutgruppe A, rein): eine Verantwortung — die
  einheitlichen Disown-Konsequenzen (Grund-Vokabel, revoked-Binding-Werte,
  Record-Status-Ziel, Audit-Payload, Tombstone-Roots, Reconcile-Antwort-Regel).
  Provided: reine Plan-Assembly `build_disown_plan(binding, path_reason, now) ->
  DisownPlan`. Required: **keine** zur Laufzeit — Inputs sind Caller-gelieferte
  Records; importiert NUR `ownership.py` + `records.py`, **nie** `runtime` oder
  einen Path-Service → 4 Aufrufer, unidirektional, zyklenfrei. Top-Level-Peer in
  `control_plane`. BC: story-lifecycle (owner der Disown-Konsequenz).
- Ownership-Record-Status-Writer: konditionales
  `UPDATE run_ownership_records SET status=? WHERE ... AND status='active'`
  (CAS-Form, rowcount-0 → fail-closed) in der
  `state_backend/postgres_store/_ownership_rows.py`-Lifecycle-Familie,
  transaktional **im** jeweiligen Path-Commit (Muster `commit_takeover_confirm`),
  ueber die Store-Facade. Caller reichen Rows durch → kein Store→Store-Zyklus.
  Exit-Fence-Negativpruefung entfaellt nur, weil der `status='ended'`-Write in
  derselben Transaktion wie der Exit-Teardown-Commit liegt.

## Groesstes Risiko (explizit designen + testen)

Ein-Slot-Binding-Row (PK `session_id`) vs. revoked-Row-als-Notification:
1. Der WHERE-geguardete Conditional-Upsert (`_control_plane_rows.py:303-332`)
   **verweigert** das Ueberschreiben der revoked Ex-Owner-Row, wenn dieselbe
   Session spaeter an einen *anderen* Run bindet (PK-Konflikt, 0 Rows) — exakt
   der AC4/AC10-Fluss (Setup-nach-Reset, Self-Rebind). Der Rebind-Pfad muss ein
   Supersedieren einer `status='revoked'`-Row explizit erlauben (nur revoked,
   NIE eine active).
2. Notification-Verlust bei legitimem Rebind: bindet der Ex-Owner (irgendeine
   Story) vor seinem naechsten Kontakt neu, ueberschreibt der Upsert die
   revoked-Row → Reconcile-Antwort weg. Zulaessig nur, weil jeder Overwrite ein
   offizieller auditierter Pfad ist — als Test-Invariante pinnen: „revoked-Row
   ueberlebt bis zum naechsten Kontakt ODER wird ausschliesslich durch einen
   offiziellen Rebind supersediert".

## Korrigierte Loci (Story-Stand → aktuell)
- Exit-Fence `runtime.py:1078` → `runtime/_run_gates.py:439` (`_evaluate_run_admission`)
- Tombstone `runtime.py:1573` → `runtime/_edge_bundles.py:145` (Exit tombstoned heute nicht)
- Postgres-Guard `runtime.py:2119` → `runtime/_di.py:35`
- Reset `service.py` :152/:176/:504 → port-basiert; deactivate_locks-Call :510; heute KEIN binding/ownership-Touch
- Exit `story_exit/service.py:191-212/:514-566` → akkurat
- Split `story_split/service.py:312-315` → akkurat
- Transfer-Inline-Disown → `runtime/_ownership_transfer.py:466-523,576-582`
- Item 10 (AG3-144-Fence-Switch): AG3-144 nicht gelandet → vakant, kein Doppelpfad zu entfernen; DoD: AC11 vacuously erfuellt.

---

## Addendum 2026-07-10 — R2-Rulings (Self-Rebind + Capability-Locus), eingefroren

Nach dem AG3-149-R1-Review (Codex: 6 ERRORs) ein zweites Fable-Urteil auf die
zwei echten Design-Fragen. Verbindlich fuer R2.

### Q1 — Self-Rebind ist Recovery, nicht Takeover; Exploit ersatzlos entfernen
- FK-56 §56.13g / FK-20 §20.7.4: Self-Rebind = Crash-**Recovery** (`recover-story`,
  `acquired_via=recovery`, **neuer** Run), NICHT der Takeover-Confirm-Pfad, und
  NIE der lebende aktive Owner (FK-56 §56.13c setzt A≠B voraus).
- Kein Orphan-Signal: FK-56 §56.13 Grundsatz 1 + FK-53 §53.7.3 — keine
  Heartbeats/Leases; „verwaist" ist server-seitig NICHT ableitbar, nur durch
  explizites Invozieren des Recovery-Pfads etabliert.
- Keine stabile Harness-Identitaet im Code (grep `harness_id` = 0; edge_commands
  hat nur `command_id`). `session_id`-Gleichheit beweist das Gegenteil von
  Orphanhood.
- Ist-Impl (`ownership_transfer.py:331-358`, `runtime/_ownership_transfer.py:326-339,
  :482-488, :541-546`) ist ein **Self-Transfer-Exploit** (requester==active-owner
  ⇒ Approval-Queue + Ping-Pong-Prong-2 umgangen; Confirm bleibt trotzdem
  HUMAN_CLI, daher echter Orphan unmoeglich).
- **Entscheidung R2:** `is_self_rebind_identity` + beide `requires_human_approval`-
  Session-Parameter + alle drei Runtime-Wirings + die `not self_rebind` /
  `!= disowned_session_id`-Abschwaechungen in beiden Barrier-Calls **ersatzlos
  loeschen**. `requester == active.owner_session_id` deterministisch am Request
  abweisen (`requester_already_owner`). Confirm bleibt unbedingt human-exclusive.
- AC10 in 149: nur der revoked-row-supersede (offizieller Rebind supersediert
  ausschliesslich eine `status='revoked'`-Row, nie eine aktive) + der
  Fremd-Identitaets-Negativtest (fail-closed, trivial sobald kein Exemption
  existiert).
- **Positive Self-Rebind (SOLL-091/AC10-positiv) → AG3-154** (recover-story,
  story.md:166). Dort: stabile Harness-Identitaet bei Bind persistieren;
  recover-story vergleicht praesentierte vs. aufgezeichnete Owner-Identitaet;
  Match ⇒ keine Approval-Queue, keine Mitzeichnung, auditiert, acquired_via=
  recovery, neuer Run; Mismatch ⇒ fail-closed in den normalen Takeover-Pfad.
  KEINE Ad-hoc-Identitaet in 149 erfinden (FIX THE MODEL).
- WARNING-Pflicht (Severity-Semantik): die AC10-*positiv*-Verschiebung ist dem
  Auftraggeber aktiv gespiegelt.

### Q2 — Ping-Pong-Autoritaet ist der A-Kern; Disenfranchisement-Overlay verdrahten (terminal)
- Ping-Pong (AC8): ein Takeover-Request/Confirm ist eine HTTP-Control-Plane-Op,
  die den Hook-Dispatch (`runner.py:1794/1866`) NIE durchlaeuft. Ein
  Capability-Locus-Ping-Pong kann strukturell nicht feuern; Verdrahtung schuefe
  einen `control_plane→governance`-Zyklus. FK-55 §55.8.4 „Capability-Regel" =
  benannte deterministische Regel des Capability-Modells (formal
  `disowned_session_cannot_immediately_reclaim`), erfuellt durch das EINE A-Kern-
  Praedikat `evaluate_disowned_session_takeover_barrier` an Request UND Confirm.
  **`evaluate_takeover_barrier` + `PING_PONG_RULE_ID` + der ungenutzte
  `enforcement.py:40`-Import entfernen** (totes Wrapper = AC8-„Code-Beweis"
  VERFEHLT). Request-seitig `current_epoch_disowned_session_id=None` ist ok
  (Prong 1 ist confirm-scoped); am Confirm muss die echte disowned-id fliessen
  (tut sie, `:555`).
- Disenfranchisement (AC9): die eigenen mutierenden Aktionen des disowned Agents
  (Write/Edit/complete/fail/closure) SIND hook-sichtbar (anders als der
  Takeover). FK-55 §55.8.3 „analog `conflict_freeze`" ⇒ **Overlay verdrahten**:
  `_resolve_capability_context` liefert server-resolved `binding_revocation_reason`
  (aus `ResolvedEdgeState.block_reason`) + `new_owner_ref`; beide Runner-Call-Sites
  (`runner.py:1790/1864`) reichen sie in `enforcement.evaluate`. Fuer
  `ownership_transferred` new-owner-ref mitfuehren (FK-56 §56.13c); fuer
  story_ended/reset/split kein neuer Owner (Overlay-`"unknown"`-Fallback korrekt).
- **Terminal-Fence:** wenn `deny.rule_id == DisownedSessionOverlay.RULE_ID`, DENY
  zurueckgeben OHNE `_service_path_override_allowed`/`ALLOW_VIA_OFFICIAL_SERVICE_PATH`
  (`enforcement.py:437-450`) — Aufloesung nur ueber ownership-state-aendernde
  offizielle Pfade, nie per Per-Call-Service-Attestierung. Mode-Guard
  (`guard_evaluation.py:106`) + HTTP-Ownership-Fence bleiben unveraendert.
- Biggest risk Q2 (stale-bundle-Misattribution): `binding_revocation_reason` nur
  weiterreichen, wenn die aufgeloeste revoked-Row zur `session_id` des Events
  gehoert; sonst fail-closed via Mode-Guard.

### R2-Scope (alle 6 Codex-ERRORs)
1. Public-Binding-Writer `save_session_run_binding_global_row` (`_runtime_rows.py:621`)
   ist ein unbedingtes `ON CONFLICT DO UPDATE` — one-slot-Guard (supersede nur
   same-run ODER `status='revoked'`, rowcount-geprueft, kein stilles Clobbern
   einer aktiven/revoked-Row ohne Ledger-Audit) auf den oeffentlichen Pfad ziehen.
2. Exit + Split **atomar**: committed-Marker + Disown + Record-Status-Transition
   in EINER Operation-Ledger-Transaktion (heute getrennte Commits → Crash-Fenster,
   das die Exit-Fence-Entfernung untergraebt).
3. Q2 (oben): Overlay verdrahten + terminal; toten Ping-Pong-Locus entfernen.
4. Q1 (oben): Self-Rebind-Carve-out loeschen; owner-self-request abweisen; positive
   Self-Rebind → AG3-154.
5. Unknown *nicht-leerer* revocation_reason ⇒ generisch `session_binding_mismatch`
   (Edge `projectedge/runtime.py:211` UND Backend `_admission_rejections.py:137`);
   geschlossenes Vier-Wert-Wire-Vokabular.
6. Test-Integritaet: echter Split-Vorgaenger bis Successor-Creation/Source-Cancel/
   Finalize (nicht ein direkt nach dem Fence/Disown geworfener Partial-Split als
   „terminal"); Capability-Tests ueber den ECHTEN Runner/Resolver (nicht
   direkt-injizierte Overlay-Inputs).

---

## Closure Addendum — 2026-07-10

**Status: CLOSED.** Merged SHA `main@cd29236b`; Jenkins #1780 SUCCESS; Sonar
`claude-agentkit3` OK (0 violations / 0 critical / 0 hotspots, new-code coverage
84.2%); 9222 tests pass.

### Review convergence
- **Codex R1→R3**: 9 defects fixed (R1: 6 ERRORs incl. a self-transfer exploit
  and a crash-window exit/split atomicity bug; R2-rereview + R3: 3 adjacent-case
  fail-closed holes — public-writer same-run disown, override-convertible
  disowned DENY, raw unknown revocation reason on the wire).
- **Codex convergence re-review** (`job-a23673fa`): `APPROVE`.
- **Orchestrator adjudication**: every fix verified at code level
  (`_runtime_rows.py:657-658`, `enforcement.py:404-427`, `_edge_bundles.py:93-98`).
- **Fable finale** (independent adversarial, read-only): `APPROVE`, full
  per-focus-area file:line evidence.
- **GLM round trimmed**: demonstrably low-signal on this story (R1 surfaced only
  2 of 6 ERRORs; missed the self-transfer exploit). Per orchestrator latitude.

### Non-blocking hardening notes (carried, not silently dropped — ZERO DEBT)
1. **Public-writer INSERT arm** (`_runtime_rows.py:622-679`): the `EXCLUDED.status='active'
   AND revocation_reason IS NULL` guard constrains only the UPDATE arm; the INSERT
   arm can still create a *fresh* `status='revoked'`+reason row for a session with
   no existing row. Unreachable in production (`ControlPlaneRuntimeRepository.save_binding`
   has zero call sites in `src`) and deny-direction if ever hit. → **Tech-debt**:
   constrain the INSERT arm too (defense-in-depth).
2. **`_current_epoch_disown_context`** (`ownership_transfer.py:107`): degrades prong 1
   to `None` (rather than failing loudly) if multiple distinct challenge owners ever
   coexisted at one epoch. Structurally impossible today (all transfer rows of one
   confirm share one `challenge_ref`); prong 2 (`current_epoch_was_takeover`) still
   fires, so no authority escalation. Informational only.
3. **Request-side privileged exemption** trusts wire `request.principal_type`; confirm
   remains boundary-attested human-exclusive (`_ownership_transfer.py:222`). This is the
   AG3-148 trust-boundary model, not a 149 regression. Informational only.

### Deferred by frozen ruling
- Positive self-rebind / recovery → **AG3-154** (recover-story, stable harness
  identity, fresh run). A disowned session self-rebind is correctly rejected
  fail-closed here.
